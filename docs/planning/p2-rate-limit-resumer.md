# P2 Rate-Limit Resumer and HUD - Design Plan

## Problem statement

Long-running jobs - specifically the persistence loop introduced in P0 - die silently when a Claude API rate limit or session expiry fires mid-iteration. There is no mechanism to detect the interruption type, preserve the loop's in-context state to disk, or restart where work left off. The result is lost iteration progress: everything from the current Engineer fix pass, any LOOP_STATE the conductor had accumulated, and the findings_log entries that took multiple Skeptic rounds to build up.

A second, related gap is observability. When the conductor is supervising concurrent Workers across an N-unit parallel plan (possible once P1 fan-out is in place), there is no external surface showing which Workers are active, what phase each is in, or whether any loop has stalled. The conductor must carry all of this in context, which is fragile and invisible to the human operator.

OMC addresses both problems: `omc wait` is a daemon that detects rate limits, waits out the reset window, and auto-resumes sessions via tmux. OMC's HUD statusline provides live observability across all workers. Neither is specific to OMC's methodology - both are infrastructure primitives this repo can adopt without abandoning its Skeptic-gated rigor.

The rate-limit resumer is higher priority than the HUD: a job that cannot survive a rate limit is not a reliable job, and the HUD is only useful once there are long-running jobs worth supervising.

## Scope

**In scope:**

- Detection heuristic for rate limit vs other failure
- Disk state schema for loop resume (the "state-on-disk" that P0 deliberately deferred)
- Wait strategy: how long to wait and how to estimate reset time
- Resume protocol: what the conductor does at session restart to pick up a paused loop
- Classification of which loop phases are resumable vs require restart
- HUD statusline design: information surface, update mechanism, and implementation approach
- Connection to the P1 task-state file (`.agentic/tasks.jsonl`)

**Explicitly out of scope:**

- The parallel fan-out primitive itself - this is P1
- Benchmark harness - this is P1
- Cost-aware model routing - this is P2 (separate work item, not addressed here)
- tmux process management (OMC uses tmux for auto-resume; this design targets manual resume with minimal infrastructure burden, not full daemonization)
- Notification routing (Telegram, Discord, Slack) - explicitly skipped per omc-comparison.md roadmap

## Dependency on P0 and P1

The rate-limit resumer presupposes P0 (persistence loop) is in place. Without P0, loops do not exist and there is nothing to resume. The P0 design (p0-persistence-loop.md) deliberately scoped out cross-session persistence as P2 work: "cross-session resume (save loop state to disk and restart after a rate limit or session expiry) - this is P2." This document designs that deferred capability.

The HUD depends on the P1 fan-out primitive. A HUD showing a single active Worker is not much more than a log line. The HUD becomes valuable when N concurrent Workers exist and the conductor needs to track their aggregate status. Design both here but mark HUD as blocked on P1 fan-out.

The P1 task-state file (`.agentic/tasks.jsonl`) is a shared coordination surface for Workers. The rate-limit resumer's state-on-disk is a related but distinct artifact: the task-state file is a DAG of planned work units; the loop-state file is the runtime status of an in-progress loop. They complement each other - the loop-state file tells you where a loop is within a task, the task-state file tells you where a task is within the overall plan. If P1 is in place before this feature is implemented, the loop-state file should be co-located in `.agentic/` for consistency.

---

## Part 1: Rate-Limit Resumer

### Detection

The Claude API returns HTTP 429 for rate limit errors. In Claude Code sessions, a rate limit manifests as an interruption in the agent's output stream, typically accompanied by an error message from the harness such as "Rate limit exceeded" or "Too many requests." Session expiry (a different failure mode) manifests as a context-window or session-timeout error, not a 429.

**Detection heuristic:**

1. **Rate limit (primary target):** The session ends with a 429 error or the harness prints a message matching the pattern `rate limit` / `too many requests` / `quota exceeded`. The session can be safely restarted after a wait.

2. **Session expiry / context-window exhaustion:** The session ends because the context window is full. This is NOT a rate limit - waiting does not help. However, if LOOP_STATE was flushed to disk before the expiry, a new session can still resume. The resume protocol is the same; only the wait behavior differs (no wait needed, just restart).

3. **Other failure (process kill, network drop, crash):** No specific error message. Same resume path as session expiry - if state was on disk, resume is possible; if not, restart from the phase boundary.

**Practical implication:** The conductor should write loop state to disk at every phase transition regardless of whether a rate limit is expected. This makes the resume path identical for all three failure modes and eliminates the need for precise detection at resume time. Detection matters only for the wait duration before restarting.

**Rate limit detection at resume time:** At the start of a new session, before running `/implement-ticket`, the conductor checks for a `.agentic/loop-state.json` file. If found and `status == "interrupted"`, the conductor reads the file to determine whether to wait (if the interrupt timestamp suggests a rate limit window is still open) or restart immediately.

### State persistence requirements (connection to P1 task-state file)

The P0 design defines a LOOP_STATE schema that is maintained in-context only. This section promotes that schema to a disk-backed file.

**File location:** `.agentic/loop-state.json` in the project root.

**Write triggers:** The conductor writes (overwrites) this file at the following points:
- After LOOP_STATE is initialized (before the first Skeptic spawn)
- After each phase transition (Skeptic spawn, Skeptic return, Engineer spawn, Engineer return, QA spawn, QA return)
- Before spawning the Phase 7 engineer fix pass: write `last_phase=quality_gate, last_phase_action=engineer_spawned`
- After Phase 7 engineer returns and commits: write `last_phase=quality_gate, last_phase_action=engineer_returned`
- Before re-running `$QUALITY_CMD` after Phase 7 engineer fix: write `last_phase=quality_gate, last_phase_action=rerun_pending`
- On loop clean exit (with `status: "complete"`)
- On loop escalation exit (cap_reached, convergence_failure, blocked) - with `status: "stalled"`)
- On session interruption (the Stop hook writes `status: "interrupted"` if the file exists and status is not already "complete" or "stalled")

**Schema (extends P0 LOOP_STATE in-context schema):**

```json
{
  "schema_version": 1,
  "ticket_id": "<string | null>",
  "branch": "<string>",
  "repo": "<string>",
  "base_branch": "<string>",
  "status": "active | interrupted | complete | stalled",
  "interrupted_at": "<ISO-8601 timestamp | null>",
  "interrupt_reason": "rate_limit | session_expiry | unknown | null",
  "last_phase": "skeptic | qa | engineer | quality_gate",
  // AUTHORITATIVE for resume entry selection. Do NOT use loop_state.phase for this.
  "last_phase_action": "spawned | returned | engineer_spawned | engineer_returned | rerun_pending",
  // For last_phase=quality_gate: use engineer_spawned, engineer_returned, rerun_pending.
  // For last_phase=skeptic | qa | engineer: use spawned | returned.
  "loop_state": {
    "phase": "skeptic | qa",
    // Used to reconstruct in-context LOOP_STATE only. Not the resume entry key.
    "iteration": "<integer>",
    "max_iterations": 3,
    "findings_log": [
      {
        "id": "<slug>",
        "severity": "Critical | Major | Minor",
        "first_raised": "<integer>",
        "status": "open | addressed | deferred | closed",
        "claimed_fix": "<string | null>",
        "re_raised": "<boolean>"
      }
    ],
    "qa_failures_log": [
      {
        "id": "<slug>",
        "description": "<string>",
        "first_raised": "<integer>",
        "status": "open | addressed | closed",
        "claimed_fix": "<string | null>",
        "re_raised": "<boolean>"
      }
    ],
    "last_engineer_summary": "<string | null>",
    "termination_reason": "null | clean | cap_reached | convergence_failure | blocked"
  }
}
```

**`last_phase` vs `loop_state.phase` - reconciliation rule:** `last_phase` is the **authoritative resume key** - use it exclusively for resume entry selection. `loop_state.phase` reflects the P0 loop's internal phase (which loop is active) and is used only for reconstructing the in-context LOOP_STATE on resume; it does not determine the resume entry point. When `last_phase=engineer`, the conductor was about to spawn or had spawned an engineer fix pass within the currently active loop (`loop_state.phase` tells you which loop). An implementing engineer MUST NOT use `loop_state.phase` to select the resume entry point; that field has a narrower purpose.

**Connection to P1 task-state file:** If `.agentic/tasks.jsonl` exists, the loop-state file should include a `task_id` field referencing the specific task in the DAG this loop is executing against. This allows the P1 fan-out orchestrator to observe that a loop is running against task T and not re-dispatch T to a new Worker while resume is pending. When P1 is not yet in place, `task_id` is omitted or null.

**File hygiene:** The file is deleted (or its status set to "complete") when the loop exits cleanly and the PR is merged. It must NOT be committed to git - add `.agentic/loop-state.json` to `.gitignore`.

### Wait strategy

When a session is interrupted by a rate limit, the conductor in the new session should wait before spawning agents that will hit the same limit.

**Reset time estimation:**

The Claude API rate limit resets on a rolling window (typically per-minute and per-day quotas). Without direct API introspection, estimate conservatively:

- **Per-minute rate limit:** wait 60 seconds from the `interrupted_at` timestamp. If the new session starts more than 60 seconds after interruption, no wait is needed.
- **Per-day quota exhaustion:** wait until the next UTC midnight from the `interrupted_at` timestamp. This is detectable if the error message contains "daily" or "per-day" or the error code maps to quota exhaustion vs. transient rate limiting.
- **Default (unknown limit type):** wait 60 seconds from `interrupted_at`. If the first spawned agent also fails with a rate limit, double the wait (120s, then 240s, capped at 10 minutes) before retrying.

**Implementation in the resume protocol:**

```
At session start with status="interrupted":
  elapsed = now() - interrupted_at
  if interrupt_reason == "rate_limit":
    if elapsed < 60 seconds:
      wait_remaining = 60 - elapsed
      print: "Rate limit detected. Waiting [wait_remaining]s before resuming."
      sleep(wait_remaining)
  else:
    # session_expiry or unknown: no wait needed, restart immediately
    print: "Loop interrupted. Resuming from last checkpoint."
```

**No daemon:** This design does not implement a tmux daemon or background process. The wait is a brief sleep in the new session's setup phase. For daily quota exhaustion, the human is expected to start the new session the next day; the conductor reads `interrupted_at`, computes the remaining wait, and either proceeds or advises the human to retry later.

### Resume protocol

When `/implement-ticket` is invoked and `.agentic/loop-state.json` exists with `status == "interrupted"`, the conductor executes the following resume path instead of starting from Phase 1.

**Resume entry check (prepended to /implement-ticket setup):**

```
Before reading AGENTS.md, check: does .agentic/loop-state.json exist?
  If yes and status == "interrupted":
    Print: "Interrupted loop detected on branch [branch] for ticket [ticket_id]."
    Print: "Last phase: [last_phase] / [last_phase_action], iteration [loop_state.iteration] of [loop_state.max_iterations]."
    Print: "Open findings: [count of findings_log entries with status=open or status=addressed]"
    Ask: "Resume this loop or start fresh? (resume / fresh)"
    If "fresh": delete .agentic/loop-state.json. Proceed with normal /implement-ticket from Phase 1.
    If "resume": apply wait strategy (see above), then jump to resume entry point.
  If yes and status == "complete" or "stalled":
    Print: "A completed/stalled loop state file exists for ticket [ticket_id]. Clearing it."
    Delete the file. Proceed with normal /implement-ticket.
  If no file: proceed normally.
```

**Resume entry point determination:**

The `last_phase` and `last_phase_action` fields identify where to re-enter:

| last_phase | last_phase_action | Resume action |
|---|---|---|
| skeptic | spawned | Re-spawn Skeptic with current diff. The prior Engineer output is on the branch; use `git diff origin/$BASE_BRANCH..HEAD` as the diff input. Include the prior-iteration findings block from `findings_log` (same as normal iteration 2+ behavior). |
| skeptic | returned | Skeptic output was received but the Engineer fix pass was not yet spawned. Re-classify findings from `findings_log` (entries with status=open) and spawn the Engineer fix pass. |
| engineer | spawned | The Engineer was mid-execution when interrupted. The branch may have uncommitted work. Check `git status --porcelain` on the branch. If clean, treat as if Engineer had not yet started: re-spawn the Engineer with the same brief (open findings from `findings_log`). If dirty (uncommitted changes exist), ask the human: "The Engineer had uncommitted changes. Discard and re-run, or commit what's there and re-run Skeptic?" |
| engineer | returned | Engineer returned but the loop did not advance. Update `last_engineer_summary` from the last-known engineer output (if stored in the state file; see "engineer summary storage" below) and re-enter the Skeptic spawn step. |
| qa | spawned | Re-spawn QA engineer with the prior brief. |
| qa | returned | QA engineer returned but the loop did not advance. Re-spawn Engineer fix pass for QA failures. |
| quality_gate | engineer_spawned | Branch may have uncommitted changes. Check `git status --porcelain`. If clean: re-spawn Phase 7 engineer with the quality gate failure output from `loop_state.last_engineer_summary`. If dirty: ask human (discard and re-run, or commit and re-run `$QUALITY_CMD`). |
| quality_gate | engineer_returned | Phase 7 engineer committed. Re-run `$QUALITY_CMD` only. |
| quality_gate | rerun_pending | Same as engineer_returned: just re-run `$QUALITY_CMD`. |

**Engineer summary storage:** The state-on-disk schema includes `last_engineer_summary` as a field. The conductor must write this to disk when an Engineer returns (not just keep it in-context) so resume can reconstruct the brief for the next Skeptic spawn. This is a small addition to the write trigger list above.

**Branch state at resume:** The conductor always runs `git -C $REPO diff origin/$BASE_BRANCH..HEAD` after resuming to confirm the branch state matches expectations before re-spawning agents. If the diff is empty and open findings exist, the Engineer's prior work was lost (uncommitted at interruption). The conductor must flag this to the human before resuming.

**Findings log continuity:** The `findings_log` and `qa_failures_log` from disk are loaded directly into the resumed LOOP_STATE. The iteration counter resumes at its last-written value. No findings are re-raised as new unless the Skeptic re-raises them explicitly (same behavior as within-session loops).

### Resumable vs restart-required phases

Not every loop phase is safely resumable without human review. The following classification governs what the resume protocol does at each point.

**Resumable (automatic):**

- **Phase 6 Skeptic loop, iteration boundary:** The branch has committed Engineer output. The Skeptic can be re-run against the current diff without any information loss. The `findings_log` carries all prior context. This is the cleanest resume point and should be the common case.
- **Phase 6b QA loop, iteration boundary:** Same as above. QA re-runs are idempotent against a committed state.
- **Phase 7 (quality gate fix pass):** Resumable. If `last_phase=quality_gate` and the Phase 7 fix pass was committed (`engineer_returned` or `rerun_pending`), just re-run `$QUALITY_CMD`. If the fix pass engineer was interrupted mid-execution (`engineer_spawned`), treat as mid-Engineer resume - check branch state via `git status --porcelain` and optionally re-spawn the Phase 7 engineer.

**Resumable with human confirmation:**

- **Mid-Engineer (last_phase=engineer, last_phase_action=spawned, dirty branch):** The branch has uncommitted changes from an interrupted Engineer. The conductor cannot safely determine whether those changes are complete or partial. Human must decide: discard and re-run, or commit as-is and proceed to Skeptic.
- **Phase 5 (Implement) initial pass:** If the initial Engineer (not a fix pass) was interrupted, the architect's plan is still valid but the implementation is incomplete. Human confirmation is needed before spawning a continuation Engineer, because the scope of "resume" vs "restart from scratch" is ambiguous for partial initial implementations.

**Restart required:**

- **Phase 1-4 (pre-implementation):** Phases 1 through 4 are cheap to re-run and produce no persistent side effects on the branch. If interrupted before Phase 5, always restart from Phase 1. The state file should not be written until Phase 6 loop initialization.
- **Phase 6, convergence_failure or cap_reached escalation that fired before interrupt:** If the loop was in a stalled state when interrupted, the resume restores the stall. The conductor presents the same escalation output and waits for human direction. This is not truly a "resume" - it is restoring a human decision point.

---

## Part 2: HUD Statusline

> **Dependency note:** The HUD is only meaningful once the P1 parallel fan-out primitive is in place. A single-Worker session already surfaces status via the conductor's inline `[loop: ...]` breadcrumbs. Do not implement the HUD before P1 fan-out.

### Information surface

The HUD surfaces the following per active Worker:

```
[worker-id] [phase] [iteration] [findings-summary] [last-update-age]
```

Example (multi-worker, P1 fan-out in progress):

```
HUD - 3 workers active
  unit1  [loop: skeptic | iter 2/3 | 1 Critical, 0 Major]   5s ago
  unit2  [loop: qa      | iter 1/3 | 2 failures]            12s ago
  unit3  [phase: engineer | implementing]                   3s ago
```

Fields per row:
- **worker-id:** short label from the orchestration-planner's unit label (e.g., "unit1", "auth-fix", "migration")
- **phase:** current phase breadcrumb (loop:skeptic, loop:qa, phase:engineer, phase:architect, etc.)
- **iteration:** current loop iteration / max, if in a loop phase; omitted for non-loop phases
- **findings-summary:** count of open Critical and Major findings (skeptic loop) or failure count (qa loop); omitted for non-loop phases
- **last-update-age:** seconds since the state file for this worker was last written

The HUD does NOT include:
- Full findings text (that belongs in the state file, not the statusline)
- Per-finding details
- Model names or cost estimates (that is cost-aware routing scope)

### Update mechanism

The HUD is file-driven, not event-driven. Each Worker writes its own state to a per-worker file under `.agentic/hud/`. The conductor reads all files to render the HUD on demand.

**Per-worker state file:** `.agentic/hud/<worker-id>.json`

```json
{
  "worker_id": "<string>",
  "phase": "<phase-breadcrumb-string>",
  "iteration": "<integer | null>",
  "max_iterations": "<integer | null>",
  "open_criticals": "<integer>",
  "open_majors": "<integer>",
  "qa_failures": "<integer>",
  "last_updated": "<ISO-8601>"
}
```

**Write triggers (by Workers):**
- At every phase transition the Worker emits (same events that produce `[loop: ...]` breadcrumbs)
- The Worker writes to its own HUD file; it does not write to other Workers' files
- The stop hook cleans up the Worker's HUD file on normal exit (status=DONE)

**Read triggers (by conductor):**
- On demand when the human asks "status" or types a status command
- Automatically when the conductor completes a phase (the conductor reads all HUD files and prints a one-line summary)
- No polling loop is needed in the conductor's main thread

**Why file-driven, not real-time:** Claude Code does not have a native IPC mechanism between agents. A file-based approach matches the existing Stop hook pattern (the P0 plan's open question 4 suggests writing loop state to a file; the HUD extends that to per-worker granularity). Files are also inspectable post-mortem.

### Implementation approach

**Phase 1 (minimal - add to rate-limit resumer implementation):**

Implement the per-worker HUD file writes as a side effect of the loop-state file writes already required by the rate-limit resumer. The `.agentic/loop-state.json` file already contains all the fields needed for a single-worker HUD entry. The conductor derives the HUD display from loop-state.json directly.

This requires zero additional code for the single-worker case - the HUD is just a formatted print of loop-state.json fields.

**Phase 2 (multi-worker - requires P1 fan-out):**

Once P1 introduces multiple concurrent Workers, each Worker writes to `.agentic/hud/<worker-id>.json`. The conductor aggregates these files to produce the multi-row HUD display.

The Stop hook must be extended to delete `.agentic/hud/<worker-id>.json` on Worker exit. If the Stop hook is not per-Worker (current harness only has one Stop hook in the main session), the conductor must explicitly clean up Worker HUD files after receiving each Worker's result.

**Phase 3 (terminal statusline - optional):**

OMC implements a terminal statusline via tmux or a background process that re-renders a status bar. This repo can approximate it by writing a `.agentic/hud/status.txt` file with the rendered multi-line HUD (suitable for `watch -n 2 cat .agentic/hud/status.txt` in a side pane). This is a cosmetic improvement and explicitly optional.

### Dependency on Part 1

The HUD's per-worker state file is a subset of the loop-state file. The rate-limit resumer must be implemented first because:

1. The loop-state file schema (from Part 1) is the source of truth for HUD data. The HUD file is a projection of the loop-state file, not an independent data source.
2. Persisting state to disk (Part 1) is a prerequisite for the HUD's "last-update-age" field to be meaningful across session boundaries.
3. The Stop hook extensions needed for Part 1 (writing `status: interrupted` on abnormal exit) are the same hook extensions needed for Part 2 (cleaning up HUD files on normal exit).

Implement Part 1 first. Part 2 is additive on top of Part 1's infrastructure.

---

## Changes required

### `/implement-ticket`

1. **Prepend resume check block** (before setup/AGENTS.md read): check for `.agentic/loop-state.json` and branch to resume protocol if `status == "interrupted"`.

2. **Phase 6 loop initialization:** Add a write of `.agentic/loop-state.json` after LOOP_STATE is initialized (replacing the in-context-only initialization from P0). Add write calls at every phase transition in the loop.

3. **Phase 6b loop initialization:** Same as Phase 6 - write loop state to disk at initialization and every transition.

4. **Phase 7:** Write a "complete" or "stalled" status to the file on loop exit.

5. **Phase 8/9 (cleanup):** Delete `.agentic/loop-state.json` after the PR is merged (or set to "complete" so it is not confused with an interrupted loop on the next run).

### `agent-methodology.md`

1. **New subsection: "Cross-session loop resume"** under the QA Gate or Re-route limits section. Documents the `.agentic/loop-state.json` file, the resume check at session start, and the resumable vs restart-required phase classification.

2. **Update Stop hook guidance** (if any): note that the Stop hook should write `status: "interrupted"` to `.agentic/loop-state.json` if the file exists and `status == "active"`.

### `subagent-protocol.md`

1. **Phase breadcrumb vocabulary (Rule 6):** Add `[loop: phase | iter N/M | ...]` breadcrumb format for the HUD file write trigger. (P0 may have already added this; verify the vocabulary is present and add the HUD file write as the mechanical action that accompanies emitting the breadcrumb.)

### `.gitignore` (project-level template)

1. Add `.agentic/loop-state.json` to the gitignore template scaffolded by `/init-project`. Loop state is runtime data and must not be committed.

2. Add `.agentic/hud/` to the gitignore template for the same reason.

### `content/agents/engineer.md`

1. **UPDATE REQUIRED (HUD Phase 2 only).** When P1 fan-out is in place and the engineer is spawned as a parallel Worker with a `worker_id` in the execution contract block, the engineer writes phase transition updates to `.agentic/hud/<worker-id>.json` before each major action (before spawning sub-agents, at completion). The HUD file write is the mechanical action that accompanies emitting `[loop: ...]` breadcrumbs. The `worker_id` is provided in the spawn prompt. Engineers spawned without a `worker_id` (single-unit, non-fan-out contexts) do not write HUD files.

### `content/references/agent-team.md`

1. **MINOR UPDATE (HUD Phase 2 only).** Update spawn guidance to note that when fan-out Workers are active (P1), each Worker writes phase transition updates to `.agentic/hud/<worker-id>.json`. The `worker_id` is provided in the spawn prompt alongside `task_id`.

### `content/commands/wrap.md`

1. **MINOR UPDATE.** At wrap time, if `.agentic/loop-state.json` exists with `status=active`, note this in the session summary - an active loop was not completed. If `status=interrupted`, note this as a pending resume. The wrap command does NOT delete `loop-state.json` - that is the user's choice (resume vs fresh-start). This is a documentation note only; wrap does not change the file.

### `init-project.md`

1. **Scaffold `.agentic/` directory** if release or multi-agent signals are present. Add `.agentic/` creation with a `.gitignore` entry covering `loop-state.json` and `hud/`.

### Docs and slides

- **`docs/agentic-engineering.html`** - UPDATE REQUIRED. Add crash recovery / session resume as a capability. The hub page should note that long-running loops survive rate limits and session exits, resuming from the last phase boundary.
- **`docs/slides/how-it-works-slides.md`** - UPDATE REQUIRED. Add a durability callout to the persistence loop flow: loop state is written to disk at each phase transition, enabling resume after interruption. A single slide note or annotation on the existing loop diagram is sufficient.
- **New deck consideration:** A standalone `docs/slides/session-recovery-slides.md` may be warranted if the HUD feature (Part 2) ships alongside resume. Together, "loop durability + live observability" is a coherent topic that benefits from dedicated teaching material. Assess at implementation time. If only the resumer ships (not the HUD), the how-it-works update is sufficient.

### `hooks/stop-context.js` (existing Stop hook)

1. **UPDATE REQUIRED** - Add new behavior at the end of the file: after the existing context-file write, add a check for `.agentic/loop-state.json`. If the file exists and can be parsed as JSON with `status === 'active'`, overwrite `status` to `'interrupted'` and write `interrupted_at` to the current ISO timestamp. Use a separate try/catch block so that failures in this new behavior do not affect the existing context-file write. Silent failure (exit 0 on error) is acceptable for this write as a fallback path - the 10-minute heuristic (edge case 8) handles the case where the hook write fails. However, best effort should be made: use `fs.writeFileSync` with a tmp+rename pattern to minimize partial-write corruption.

   The file path for the loop-state check is `path.join(cwd, '.agentic', 'loop-state.json')`, using the `cwd` already extracted from the Stop hook payload (the existing `cwd` variable on line 53 of the current file).

   Note: if a second Stop hook file is preferred over modifying `stop-context.js`, Claude Code supports multiple Stop hooks. A second entry can be added to the hooks configuration alongside the existing `stop-context.js` entry. Either approach is acceptable; modifying `stop-context.js` is preferred for simplicity.

---

## Edge cases and failure modes

**1. State file written mid-transition.** If the session crashes between the "Engineer spawned" write and the "Engineer returned" write, `last_phase_action` will be "spawned" even though the Engineer may have completed and even committed. The resume protocol handles this by checking `git status --porcelain` on the branch: if the branch has new commits since the interrupted_at timestamp, the Engineer likely completed. The conductor should treat this as "engineer returned" and proceed to the Skeptic spawn. This requires comparing `git log` timestamps against `interrupted_at`.

**2. Concurrent sessions writing to the same state file.** If the human starts two sessions against the same ticket (e.g., by accident), both will attempt to write `.agentic/loop-state.json`. The second session's resume check will see `status == "active"` (from the first session) and offer to resume - which would mean two conductors driving the same loop. Guard: if `status == "active"` and `last_updated` was within the last 10 minutes, print a warning ("A session appears to be actively writing this loop state. Are you sure you want to resume here?") and require explicit confirmation before proceeding. The 10-minute threshold matches the implicit-interrupt threshold in edge case 8 - a session writing within that window is considered potentially active.

**3. State file corruption.** JSON write is not atomic. A crash mid-write produces a truncated or malformed file. The resume check must wrap the file parse in a try/catch. On parse failure: print a warning, offer to delete the file and start fresh. Do not silently ignore the file.

**4. Branch divergence after interrupt.** If the human makes manual commits to the branch between the interruption and the resume, the diff the Skeptic sees will include those manual commits. This is acceptable behavior - the Skeptic reviews what is on the branch. The conductor should print the current diff size at resume time so the human can confirm no unintended changes are present.

**5. Findings log grows unboundedly on very long loops.** The max-iteration cap of 3 from P0 limits findings_log to at most 3 * (max findings per iteration) entries. In practice this is small. No pagination or truncation is needed.

**6. Loop state file left behind after ticket abandonment.** If the human abandons a ticket mid-loop and starts fresh on a different ticket, the old `loop-state.json` will confuse the next `/implement-ticket` invocation on that same project. The resume check must show the ticket ID and branch name prominently so the human can recognize a stale file. Always offer a "start fresh" option that deletes the file.

**7. HUD files from crashed Workers.** If a Worker crashes without the Stop hook firing (SIGKILL, OOM), its `.agentic/hud/<worker-id>.json` will not be cleaned up. The HUD aggregator should treat any HUD file not updated within 5 minutes as stale and mark it `[stale]` rather than displaying its last status as current.

**8. Rate-limit resume without the Stop hook.** If the Stop hook does not fire (the process is killed before the hook runs), `status` remains "active" rather than "interrupted". The resume check should treat `status == "active"` with `last_updated` more than 10 minutes (600 seconds) ago as implicitly interrupted. The distinction between "active and healthy" and "active and dead" is the recency of `last_updated`. Rationale for the 10-minute threshold: agent runs (Skeptic review, Engineer implementation) can take 2-8 minutes without writing a phase transition. A threshold shorter than the longest plausible agent run produces false positive interrupt detection. 10 minutes is chosen as a conservative upper bound. A future enhancement could add a "heartbeat" write (conductor writes a no-op status update every 60 seconds while waiting for an agent to return), which would allow the threshold to be safely lowered without false positives - flag as future mitigation, not required for P2.

---

## Open questions (resolved 2026-04-16)

**Q1: ATOMIC WRITE.** Decision: yes. Use tmp file + rename pattern (`fs.writeFileSync` to `.agentic/loop-state.json.tmp`, then `fs.renameSync` to `.agentic/loop-state.json`). The corruption fallback (try/catch on parse, offer delete) still exists as a safety net. Rationale: atomic write prevents corruption at the source; cheap to implement.

**Q2: BAKED INTO /implement-ticket.** Decision: no dedicated `/resume` command. The resume check is a guard prepended to `/implement-ticket` setup. Rationale: simpler, one command surface, no new command to maintain, matches the plan's own recommendation.

**Q3: VERBATIM, CAPPED AT 2000 CHARACTERS.** Decision: store `last_engineer_summary` verbatim in the state file, truncated to 2000 characters if longer. Rationale: truncation risks losing Skeptic brief context; 2000 chars is ample for a summary while keeping the file readable.

**Q4: FULL SKEPTIC RE-RUN.** Decision: if a Skeptic is interrupted mid-output, the resume protocol re-runs the Skeptic from scratch (last_phase=skeptic, last_phase_action=spawned). No partial Skeptic output recovery. Rationale: Skeptic is read-only and idempotent; re-run cost is low relative to engineer passes; partial output recovery adds complexity for negligible benefit.

**Q5: ON-DEMAND FOR PHASE 2.** Decision: HUD rendered on-demand only (conductor reads HUD files and prints when asked or at phase transitions). No background `watch` process. A `watch`-compatible `.agentic/hud/status.txt` file is a Phase 3 optional enhancement. Rationale: matches existing breadcrumb pattern, requires no background process, still provides observability.

**Q6: NO SPECIAL HANDLING FOR TIGHT-FIX PATH.** Decision: the existing dirty-branch resume path (check `git status --porcelain`, ask human if dirty) covers the tight-fix interruption case. No tight-fix-specific resume logic needed. Rationale: the tight-fix failure path in P0 (VERIFY fails -> uncommitted diff -> standard Skeptic) is already consistent with the dirty-branch resume path. Flag as a test case during implementation verification.
