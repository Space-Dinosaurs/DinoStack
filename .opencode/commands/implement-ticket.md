---
description: Implement Ticket
agent: build
---
# Implement Ticket

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted back to the ticket.

## Invocation

`/implement-ticket <input>`

`<input>` accepts any of:
- A single ticket ID: `DINO-639`
- A comma- or space-separated list: `DINO-639, DINO-638` or `DINO-639 DINO-638`
- A tracker issue URL: Jira `/browse/DINO-639`, Linear `/issue/ENG-42/...`
- A tracker search/filter URL: Jira `/issues?jql=...`, Linear filter URL
- A pasted screenshot of a tracker board, column, or issue list
- A freeform description (no tracker reference)
- Any mixture of the above
- Any project-local extension classifier defined in `.agentic/phase0-classifiers.yml`

Phase 0 normalizes the input into a canonical ordered list of ticket entries before any other phase runs. Bare-ID, single-issue-URL, and operator-enumerated list invocations bypass the confirmation prompt — backward compatible with the prior single-argument contract.

---

## Conductor responsibilities (irreducible)

The conductor delegates implementation work aggressively to specialist subagents but retains a fixed set of responsibilities that are never delegated. This section enumerates at minimum:

- **Risk classification.** Must precede any spawn (per METHODOLOGY.md §Risk Classification).
- **Promotion-gate check + Brief/Plan authoring.** Comprehension artifacts that the conductor must produce itself (per METHODOLOGY.md §Planning Artifacts).
- **Stop-and-ask decisions.** The user-facing surface; subagents do not interact with the user.
- **All `.agentic/*.json[l]` writes.** Sole-writer rule for `loop-state.json`, `tasks.jsonl`, and any other state file under `.agentic/`.
- **Re-route limit + convergence-failure tracking.** Conductor must hold the full loop history across iterations.
- **Status updates and breadcrumbs to user.** All `[phase: ...]` and `[loop: ...]` emissions originate from the conductor.
- **Dispatch logic.** Which agent, when, with what brief.
- **Summary synthesis for downstream spawn briefs.** PR body, tracker comment, findings input - the conductor extracts and reformats subagent outputs for downstream consumers.
- **`BASE_BRANCH` resolution and `AGENTS.md` config parsing.** Setup phase work.
- **`gh pr create` in Phase 9.** PR opener stays in the conductor; synthesis-context savings did not justify a spawn.
- **CI Test URL polling in Phase 10.**
- **Branch/worktree creation on the Phase 5 parallel fan-out path.** The Elevated single-engineer path AND the Trivial single-engineer path both delegate branch/worktree creation to the (worktree-isolated) engineer (see Phase 4). Only fan-out worktree creation remains conductor-orchestrated.

This list is not exhaustive — any operation listed elsewhere as conductor-direct is also irreducible.

---

## Batch state contracts (binding)

These contracts govern every conductor write to `.agentic/batch-state.json` and `.agentic/loop-state.json`. Phases that write to either file (Phase 0a, Phase 0a-pre, Phase 6/6b, Phase 7, Phase 12, Phase 12a) MUST apply the contracts below.

**Contract A — Per-write `session_id` gate (applies to BOTH `batch-state.json` and `loop-state.json`).**

Before every conductor write to either file:

1. Read the current on-disk file (if present).
2. If the file exists and its `session_id` field is a non-empty string AND does not match the current session, AND its `last_updated` is within the last 10 minutes: ABORT the write. Print the verbatim warning:
   ```
   WARNING: write to .agentic/<file> aborted - another session (session_id=<X>, last_updated=<Y>) appears to own this file. Identify the live session via .agentic/*.json last_updated. Resolve manually (kill the other session, or remove the file) and retry.
   ```
3. If the file exists and its `session_id` is null/missing/empty (legacy state from a prior version): treat as mismatch — force-takeover-eligible. Operator may resolve via the Phase 0a-pre force-takeover prompt or by manually removing the file. The same WARNING above is printed.
4. Otherwise (no file, matching `session_id`, or stale > 10 min): proceed with the write. Set `session_id` to the current session's id and update `updated_at` in the new payload.

Both readers and writers tolerate absence of `session_id` for back-compat with state files written by prior versions; absence is treated as mismatch for write-gating but not for read-only resume prompts (those follow the Phase 0a-pre decision table).

**Contract B — `replan_log[]` read-merge-write preservation (applies to `batch-state.json`).**

Every conductor write to `batch-state.json` MUST:

1. Read the current on-disk file first.
2. Take the existing `replan_log[]` from disk and merge any new entries authored in-memory by the current conductor turn (append-only; never reorder; never drop entries).
3. Write the merged array back along with the rest of the payload.

This preserves the audit log across overlapping writes and across resume migrations.

**Contract C — One batch per project root.**

When Phase 0a is initializing a new `batch-state.json` (invocation where Phase 0 produced ≥ 2 entries) and the file already exists with `status=active`, a different `session_id`, and `last_updated` within the last 10 minutes: REFUSE the new batch with the verbatim message:

```
Another batch session is active for this project root (session_id=<X>, last_updated=<Y>). Wait for it to finish, or kill it and re-invoke.
```

Concurrent batches per project root are not supported. Operators wanting parallel batches use separate worktrees with separate `.agentic/`.

**N=1 foreign-batch warning.** If Phase 0 produced exactly 1 entry (single-ticket) AND `.agentic/batch-state.json` exists with `status=active` + different `session_id` + `last_updated` within the last 10 minutes: print the verbatim warning:

```
NOTE: a batch session is active for this project root (session_id=<X>, last_updated=<Y>). Single-ticket invocations are not refused, but loop-state.json writes will collide if the same ticket is touched. Identify the live session via .agentic/loop-state.json last_updated. Continue? (yes/no)
```

On `no`: abort. On `yes`: proceed with the single-ticket flow. This is the only single-entry interaction with `batch-state.json`.

**Contract D — Stop hook mirror.**

The Stop hook (`hooks/stop-context.js`) mirrors its `loop-state.json` interrupted-mark write to `batch-state.json` via the helper `writeBatchState(cwd, sessionId)`. The mirror applies an ownership check: if the file's `session_id` is a non-empty string and does not match the Stop hook's session uuid, the write is aborted silently (the hook does not steal another session's batch state). Best-effort silent-fail throughout. The mirror sets `status=interrupted`, `interrupted_at=now`, `interrupt_reason="unknown"`, `updated_at=now`; all other fields including `last_updated_phase`, `tickets[]`, and `replan_log[]` are preserved.

---

## `.agentic/batch-state.json` schema

```json
{
  "schema_version": 1,
  "session_id": "<current session uuid or null>",
  "batch_id": "<first-ticket-prefix>-batch-<ISO8601>-<4hex>",
  "status": "active",
  "created_at": "<ISO8601>",
  "updated_at": "<ISO8601>",
  "last_updated_phase": "<phase label>",
  "interrupted_at": null,
  "interrupt_reason": null,
  "paused_at": null,
  "pause_reason": null,
  "wallclock_cap_min": 90,
  "wallclock_started_at": "<ISO8601>",
  "tickets": [
    {
      "ticket_id": "ABC-123",
      "status": "pending",
      "cluster_id": "<planner cluster id>",
      "depends_on": ["ABC-122"],
      "started_at": null,
      "ended_at": null,
      "branch": null,
      "pr_number": null,
      "last_summary": null
    }
  ],
  "replan_log": [],
  "resume_invocation_hint": "/implement-ticket"
}
```

**Field semantics:**

- `schema_version`: integer; current is `1`.
- `session_id`: uuid of the conductor session that last wrote the file; null only on legacy files written by a prior version.
- `batch_id`: stable identifier for the batch. Format `<prefix>-batch-<ISO8601>-<4hex>` where `<prefix>` is the first ticket's `TICKET_PREFIX` (used when tickets span multiple prefixes; the first ticket wins).
- `status`: enum `active | paused | interrupted | complete | stalled`.
- `interrupt_reason`: enum `unknown | null` — only `unknown` is a writable value (other values reserved for future writers; the Stop hook cannot distinguish rate-limit vs crash at hook time).
- `pause_reason`: enum `stale_pace | operator_pause | wallclock_cap | null` — these three values match the three Phase 12a triggers.
- `wallclock_started_at`: set once at Phase 0a init; preserved across resume. The wallclock cap is per-batch lifetime, not per-session.
- `wallclock_cap_min`: integer minutes. Default `90`. Overridable via env `AGENTIC_BATCH_MAX_WALLCLOCK_MIN`.
- `tickets[]`: planner-derived; `status` per-ticket is `pending | in_progress | complete | blocked | skipped_already_merged`.
- `replan_log[]`: append-only audit log. Each entry: `{ts, action, ticket_id, detail}`. Actions include `drop_merged`, `investigator_rerun`, `re_sequence`. Preserved by Contract B.

---

## Resume check (before setup)

Before reading AGENTS.md or doing any setup, check for `.agentic/loop-state.json`:

**If the file exists and `status == "interrupted"`:**
- Print: "Interrupted loop detected on branch [branch] for ticket [ticket_id]."
- Print: "Last phase: [last_phase] / [last_phase_action], iteration [loop_state.iteration]/[loop_state.max_iterations]."
- Print: "Open findings: [count of findings_log entries with status=open or status=addressed]"
- Ask: "Resume this loop or start fresh? (resume / fresh)"
- If "fresh": delete the file. Proceed normally from Setup below.
- If "resume": apply wait strategy (see below), then jump to the resume entry point determined by `last_phase` / `last_phase_action` per the table below.

**If the file exists and `status == "active"` with `last_updated` more than 10 minutes ago:** treat as implicitly interrupted (the Stop hook may not have fired). Print: "Found an active loop state last written [elapsed] ago — treating as interrupted." Then follow the "interrupted" path above.

**If the file exists and `status == "complete"` or `"stalled"`:**
- Print: "A completed/stalled loop state file exists for ticket [ticket_id]. Clearing it."
- Delete the file. Proceed normally.

**If no file exists:** proceed normally.

**Wait strategy (applied before resuming when `interrupt_reason == "rate_limit"`):**
```
elapsed = now() - interrupted_at
if interrupt_reason == "rate_limit":
  if elapsed < 60 seconds:
    wait_remaining = 60 - elapsed
    print: "Rate limit detected. Waiting [wait_remaining]s before resuming."
    sleep(wait_remaining)
else:
  # session_expiry or unknown: no wait needed
  print: "Loop interrupted. Resuming from last checkpoint."
```

**Resume entry point table:**

| last_phase | last_phase_action | Resume action |
|---|---|---|
| skeptic | spawned | Re-spawn Skeptic with current diff (`git diff origin/$BASE_BRANCH..HEAD`). On iteration 2+, include prior-iteration findings block from `findings_log` (same as normal iteration 2+ behavior). |
| skeptic | returned | Skeptic output was received but Engineer fix pass was not yet spawned. Re-classify findings from `findings_log` (entries with status=open) and spawn the Engineer fix pass. |
| engineer | spawned | Check `git status --porcelain` on the branch. If clean: re-spawn Engineer with same open findings brief. If dirty (uncommitted changes): ask human "The Engineer had uncommitted changes. Discard and re-run, or commit what's there and re-run Skeptic?" |
| engineer | returned | Engineer returned but loop did not advance. Use `last_engineer_summary` from state file. Re-enter Skeptic spawn step. |
| qa | spawned | Re-spawn QA engineer with the prior brief. |
| qa | returned | QA engineer returned but loop did not advance. Re-spawn Engineer fix pass for QA failures. |
| quality_gate | engineer_spawned | Check `git status --porcelain`. If clean: re-spawn Phase 7 engineer with quality gate failure output from `loop_state.last_engineer_summary`. If dirty: ask human (discard and re-run, or commit and re-run `$QUALITY_CMD`). |
| quality_gate | engineer_returned | Phase 7 engineer committed. On the Elevated path: verify the engineer's reported `quality_gate_results`. On the Trivial path: re-run `$QUALITY_CMD`. |
| quality_gate | rerun_pending | On the Elevated path: wait for the fix-engineer return and verify its `quality_gate_results` - do not invoke `$QUALITY_CMD` directly. On the Trivial path: re-run `$QUALITY_CMD`. |
| quality_gate | debugger_spawned | Re-spawn Debugger from scratch with the captured gate failure output (Debugger is read-only and idempotent - same pattern as "Full Skeptic re-run on interruption"). |
| quality_gate | debugger_returned | Debugger output was captured before interruption. Proceed to spawn the next engineer fix pass with the Debugger's Fix brief. No Debugger re-run needed. |
| ci_wait | timeout | Re-enter Phase 10 poll loop once (operator may have manually fixed; if still timing out, re-escalate). |
| ci_loop | fix_engineer_spawned | Re-spawn the fix engineer from the latest commit on the branch (assumes prior spawn was interrupted). Resume from cycle N. |
| ci_loop | fix_engineer_returned | Re-enter Phase 10 poll loop to check CI status. |
| ci_loop | ci_poll_pending | Re-enter Phase 10 poll loop from current iteration. |
| ci_loop | cap_exceeded | Do NOT auto-resume. Surface the prior escalation summary and require human direction. |

**After resuming:** always run `git -C $REPO diff origin/$BASE_BRANCH..HEAD` to confirm branch state before re-spawning agents. If the diff is empty and open findings exist, the Engineer's prior work was lost (uncommitted at interruption); flag this to the human before resuming.

**Parse failure:** if `.agentic/loop-state.json` exists but cannot be parsed as JSON, print a warning, offer to delete the file and start fresh. Do not silently ignore it.

**Concurrent session guard.** **REPLACED in this version by Contract A's per-write `session_id`-mismatch abort gate, applied to every conductor write of `loop-state.json` and `batch-state.json`.** See Phase 0a-pre and the "Batch state contracts" section above for the full contract. Every conductor write to `loop-state.json` includes a top-level `session_id: <current session>` field; readers tolerate absence for back-compat with state files written by prior versions.

**N=1 foreign-batch warning.** Before proceeding to Phase 0a-pre on an invocation where Phase 0 produced exactly 1 entry, apply the N=1 foreign-batch check from "Batch state contracts" above. If `.agentic/batch-state.json` exists with `status=active` + different `session_id` + recent (≤10 min): print the verbatim NOTE, prompt yes/no, and abort on `no`.

---

## Setup: Read project config

Before any phase, read the project's `AGENTS.md` and extract the following values:

- `REPO` — absolute path to the repo root
- `GH_REPO` — GitHub repo slug (e.g. `org/repo-name`)
- `BASE_BRANCH` — the branch all work is based from. If not declared in `AGENTS.md`, resolve in this order: (1) `main` if it exists locally; (2) `master` if it exists locally; (3) `develop` if it exists locally; (4) `development` if it exists locally; (5) stop and ask the user which branch to use. Do not auto-create a branch. Once resolved, print: `BASE_BRANCH resolved to: [value]`.
- `QUALITY_CMD` — the full quality gate command to run from repo root
- `DEBUGGER_ON_FAILURE` — read from `.agentic/config.json` key `debugger_on_failure` (boolean, default `false`). When `true` and the path is Elevated, a Debugger diagnosis step is interposed between a failed quality gate and the next engineer fix pass in Phase 7 - see Phase 7 for the full flow.
- `AUTO_MERGE_ON_CI_GREEN` — read from `.agentic/config.json` key `auto_merge_on_ci_green` (boolean, default `false`). When `true`, Phase 12 squash-merges the PR after CI passes, the PR is ready, and no reviewer has requested changes. Default `false` leaves the PR open for human review.
- `PR_WORKFLOW_REVIEWERS` — read from `AGENTS.md` `## PR Workflow` section, `Reviewers:` field (comma-separated GitHub usernames). Default: empty string. Section absence = empty. Used in Phase 10b as fallback reviewer assignment when no CODEOWNERS file is found.

**Tracker resolution** — read tracker config using this fallback chain:

1. If a `## Tracker` section exists in `AGENTS.md` and contains `TRACKER: jira`: set `TRACKER=jira`. Extract `TICKET_PREFIX`, `JIRA_BASE_URL`, `JIRA_QA_ASSIGNEE_ACCOUNT_ID` (optional), `JIRA_QA_TRANSITION` (optional — no default). Also extract optional state-name overrides: `JIRA_STATE_IN_PROGRESS` → `TRACKER_STATE_IN_PROGRESS` (default `"In Progress"`), `JIRA_STATE_IN_REVIEW` → `TRACKER_STATE_IN_REVIEW` (default `"In Review"`), `JIRA_STATE_QA` → `TRACKER_STATE_QA` (default `"QA"`), `JIRA_STATE_BLOCKED` → `TRACKER_STATE_BLOCKED` (default `"Blocked"`), `JIRA_STATE_DONE` → `TRACKER_STATE_DONE` (default `"Done"`). All five fields are optional; absence = use default.
2. Else if a `## Tracker` section exists with `TRACKER: linear` (future-proofing): treat as Linear and read Linear fields from `## Tracker` instead of `## Linear`. Apply the same state-name override fields as the Linear path below.
3. Else if a `## Linear` section exists: set `TRACKER=linear`. Extract `Team` → `TICKET_PREFIX`, `Workspace` → `LINEAR_WORKSPACE`, `QA assignee ID` → `LINEAR_QA_ASSIGNEE_ID` (optional). Also extract optional state-name overrides: `State In Progress:` → `TRACKER_STATE_IN_PROGRESS` (default `"In Progress"`), `State In Review:` → `TRACKER_STATE_IN_REVIEW` (default `"In Review"`), `State QA:` → `TRACKER_STATE_QA` (default `"Testing"`), `State Blocked:` → `TRACKER_STATE_BLOCKED` (default `"Blocked"`), `State Done:` → `TRACKER_STATE_DONE` (default `"Done"`). All five fields are optional; absence = use default. (Note: Linear `TRACKER_STATE_QA` defaults to `"Testing"` while Jira defaults to `"QA"` — reflects common workspace conventions for each tracker.)
4. Else: set `TRACKER=none`. Set all `TRACKER_STATE_*` variables to their defaults: `TRACKER_STATE_IN_PROGRESS="In Progress"`, `TRACKER_STATE_IN_REVIEW="In Review"`, `TRACKER_STATE_QA="Testing"`, `TRACKER_STATE_BLOCKED="Blocked"`, `TRACKER_STATE_DONE="Done"`.

**Dual-shape note:** Linear projects canonically store tracker config under `## Linear`; Jira projects use `## Tracker`. This is intentional — it preserves zero-migration compatibility for every existing Linear project that already has a `## Linear` section.

**Legacy `## Linear` shape guard** — if `TRACKER=linear` was resolved from a `## Linear` section AND the section is missing the `Workspace:` field (required for URL generation), stop immediately and print:

```
Your tracker config is missing fields /implement-ticket needs. Run /init-project to update it —
discovery will fill in most fields automatically.
```

Do not continue. Do not attempt to write the migration. All config-mutation logic lives in `/init-project`.

Print a summary of resolved values before Phase 1:

```
Tracker:                    [linear | jira | none]
TICKET_PREFIX:              [value or "n/a"]
BASE_BRANCH:                [value]
AUTO_MERGE_ON_CI_GREEN:     [true | false]
PR_WORKFLOW_REVIEWERS:      [comma-separated usernames or "(none)"]
TRACKER_STATE_IN_PROGRESS:  [value]
TRACKER_STATE_IN_REVIEW:    [value]
TRACKER_STATE_QA:           [value]
TRACKER_STATE_BLOCKED:      [value]
TRACKER_STATE_DONE:         [value]
```

All work lives in `$REPO`.

---

## Tracker Writeback Helper

Reusable subagent invocation pattern. Used by Phase 11 (existing) and 7 new sites below. Gated on `TRACKER != none`; no-op otherwise.

**Invocation contract:**

When the conductor reaches a writeback boundary:
1. Skip entirely if `TRACKER == none`.
2. Spawn the tracker-writeback subagent (Tier 1, `general-purpose`) in background (fire-and-forget; do NOT wait for return before continuing the phase).
3. Pass to the subagent:
   - `tracker`: `linear` | `jira`
   - `ticket_id`: from current task context
   - `target_state`: one of the resolved `TRACKER_STATE_*` variables
   - `forward_only_guard`: `true` for all 7 new sites; preserves existing Phase 11 behavior (which used hardcoded `Testing`)
   - Tracker-specific config: `LINEAR_WORKSPACE`, `LINEAR_QA_ASSIGNEE_ID` for Linear; equivalent for Jira

**Subagent responsibilities (extended for `forward_only_guard`):**

1. **Pre-read current state:** call `mcp__linear__get_issue` (or Jira `mcp__mcp-atlassian__jira_get_issue`) to read the ticket's current state including `state.type` (Linear: `backlog`, `unstarted`, `started`, `completed`, `cancelled`; Jira: map via status category).
2. **Forward-only guard:** compute rank of current state and target state.

   **Linear ranking** (uses `state.type` directly):
   `backlog` < `unstarted` < `started` < `completed`; `cancelled` is terminal (never overwritten by any automatic transition).

   **Jira ranking** (map via status category, available on every Jira status via `statusCategory.key`):
   - `new` (To Do, Open, Backlog) → rank `unstarted`
   - `indeterminate` (In Progress, In Review, Testing) → rank `started`
   - `done` (Done, Closed, Resolved) → rank `completed`
   - Custom categories or names matching cancellation semantics (Won't Do, Cancelled, Will Not Fix) → terminal (never overwritten)

   Apply the same rank-comparison rule for both trackers: if current rank >= target rank, skip the transition.
3. **Skip semantics:**
   - If current state read fails (MCP/API error): skip transition silently. Do NOT assume position; do NOT proceed with the transition. Log a one-line warning to stderr.
   - If current rank >= target rank (already there or past it): skip transition. No notification noise.
   - If current state is `cancelled`: skip transition unconditionally.
   - Otherwise: perform the transition via `mcp__linear__save_issue` (or Jira equivalent).
4. **Soft-fail:** any transition error logged to stderr; subagent returns `{ "status": "failed", "errors": [...] }`. Conductor logs and continues; never blocks the phase.

**Failure logging:** subagent stderr is captured by the conductor's `agentic-emit` event; one operator-visible line per failure of the form: `tracker-writeback: <ticket_id> -> '<target_state>' FAILED: <error>`. No block.

For full details of the Phase 11 writeback subagent brief shape, see the Phase 11 block below — the brief is unchanged except for the addition of `target_state` and `forward_only_guard` parameters.

---

## Phase 0: Input normalization

> Run this phase BEFORE Phase 0a-pre. Output is the in-memory `normalized_input` structure consumed by every later phase. No disk side-effects.

<!--
Phase 0 manifest:
  Purpose: normalize any form of /implement-ticket input into a canonical entries[] list.
  Public contract: produces in-memory normalized_input { entries[], freeform_task, additional_operator_context, raw_invocation, resolution_notes[] }.
  Upstream deps: TRACKER/TICKET_PREFIX/JIRA_BASE_URL from Setup; tracker MCP tools; .agentic/phase0-classifiers.yml (optional).
  Downstream consumers: Phase 0a-pre, Phase 0a, Phase 1, Phase 3 architect, Phase 5 engineer, Phase 12a (all key off len(entries) or batch-state.json).
  Failure modes: pagination cap (50, narrow/proceed), sanity ceiling (200, refuse), JQL auth failure (abort), no entries + no freeform (exit). Confirmation runs only for ambiguous, screenshot, residue-attached, cap-hit, no-IDs+TRACKER≠none, or operator-enumerated >5.
  Performance: single tracker API roundtrip per URL (paginated up to 50); screenshot read is local multimodal.
-->

**Goal:** convert any form of `<input>` into a deterministic ordered list of `{ticket_id, source}` entries, an optional `freeform_task`, and an optional `additional_operator_context`. Confirm only when classification is ambiguous or destructive.

**Fast paths (no confirmation, no operator-visible output beyond the resolution itself).**

| Condition | Action |
|---|---|
| Invocation is a single token matching `^[A-Z][A-Z0-9_]+-\d+$` AND matches `TICKET_PREFIX` (when TRACKER ≠ none) | `entries=[{ticket_id, source: "literal"}]`, proceed to Phase 0a-pre. Zero new operator output. |
| `TRACKER == none` AND input is freeform text only (no tickets, no URLs, no images) | `entries=[]`, `freeform_task=<input>`, proceed. No confirmation prompt. (TRACKER=none has zero ambiguity for freeform — Phase 1's prior freeform prompt is now redundant.) |

**Otherwise, classify the input.** Built-in classifiers run first, in this order; project-local classifiers (see "Extension point" below) run after for inputs that fall through.

| Input shape | Detection | Resolution |
|---|---|---|
| Bare ticket ID | matches `^[A-Z][A-Z0-9_]+-\d+$` | append `{ticket_id, source: "literal"}` |
| Comma/space-separated list | tokenize on `[,\s]+`, each token matches bare-ID regex | append each as `source: "list"` |
| Jira issue URL | `^https?://[^/]+/browse/([A-Z][A-Z0-9_]+-\d+)` | extract group 1, append `source: "url:jira-issue"` |
| Jira JQL/search URL | host matches `JIRA_BASE_URL` host AND path is `/issues` (or `/jira/.../issues`) AND query contains `jql=` | URL-decode `jql`, call `mcp__mcp-atlassian__jira_search`, paginate up to cap, append each as `source: "url:jira-jql"` with `title` |
| Linear issue URL | `^https?://linear\.app/[^/]+/issue/([A-Z][A-Z0-9_]+-\d+)` | extract group 1, append `source: "url:linear-issue"` |
| Linear filter URL | `linear.app/<workspace>/view/...` or filter query string | call `mcp__linear__list_issues` with decoded filter, paginate to cap, append `source: "url:linear-filter"` with `title` |
| Pasted screenshot | **Any image attachment present in the operator's user-message payload (image MIME type or attachment marker indicating an image was uploaded with the invocation)** | conductor reads the image directly (Tier 2, multimodal). Extract every distinct `[A-Z][A-Z0-9_]+-\d+` substring. Append each as `source: "screenshot"`. **Do not spawn an OCR subagent.** |
| Freeform residue | any non-matching text after all classifiers consumed their inputs | held aside; see Freeform handling below |

**Extension point (project-local classifiers).**

If `.agentic/phase0-classifiers.yml` exists at the project root, load it after Setup and before built-in classifiers run. Built-in classifiers run FIRST; project-local classifiers run only against inputs that fell through (residue not matched by any built-in). Schema:

```yaml
# .agentic/phase0-classifiers.yml
classifiers:
  - source_label: "github-issue"           # appended as source: "extension:github-issue"
    detect: "^https?://github\\.com/[^/]+/[^/]+/issues/(\\d+)"   # regex; capture group 1 is the ID
    resolver: "gh issue view $1 --json number,title --jq '{ticket_id: \"GH-\\(.number)\", title: .title}'"
    # resolver is either a shell command (string) or an mcp_tool spec object:
    #   resolver:
    #     mcp_tool: "mcp__some-server__some-tool"
    #     args: { id: "$1" }
    #     response_path: "$.data"   # optional; default omitted (read top-level)
  - source_label: "asana-task"
    detect: "^https?://app\\.asana\\.com/0/\\d+/(\\d+)"
    resolver:
      mcp_tool: "mcp__asana__get_task"
      args: { gid: "$1" }
      response_path: "$.data"
```

**Resolution rules:**
1. `detect` is a regex applied to each fall-through input token/URL.
2. `resolver` is either a shell command (string) or an MCP tool spec (object with `mcp_tool`, `args`, optional `response_path`). The resolver MUST yield (directly or via `response_path` extraction) at minimum `ticket_id` (and optionally `title`).
3. Resolver failures are treated like "Unparseable URL" — appended to `resolution_notes`, no entry produced.
4. Each matched input contributes one entry with `source: "extension:<source_label>"`.

**Shell-command resolver contract (binding).**

- **Output channel:** resolver MUST emit JSON on stdout. Stderr is captured and logged to `resolution_notes` but is NOT parsed.
- **Exit code:** zero exit = success; non-zero exit = treat as "no entries from this resolver" (log stderr, continue Phase 0; do NOT abort).
- **JSON shape:** stdout MUST be either a single object `{ticket_id: string, title?: string}` OR a JSON array of such objects. Any other shape (non-JSON, missing `ticket_id`, wrong types) is a resolver failure.
- **Capture-group substitution:** `$1` through `$9` correspond to regex capture groups from `detect`. Substituted values MUST be shell-escaped by wrapping the value in single quotes and replacing every embedded single quote `'` with the four-character sequence `'\''`. Example: a capture value `O'Brien's repo` is substituted as `'O'\''Brien'\''s repo'`. The engineer MUST NOT use unquoted `$1` substitution under any circumstance — raw URLs and tracker IDs may contain shell metacharacters (`;`, `&`, `` ` ``, `$()`, `|`, newlines) that would otherwise inject commands into the conductor shell.
- **Timeout:** 10 seconds per resolver invocation. On timeout: kill the process, treat as zero entries, append a `"resolver timeout: <source_label>"` warning to `resolution_notes`.

**MCP-tool resolver contract (binding).**

- **Invocation:** the conductor calls the named MCP tool with `args` as the input dict. Capture-group substitution `$1`-`$9` applies to string-typed values inside `args` by literal string replacement. Shell-escaping does NOT apply (these are tool-call arguments, not shell tokens). The conductor MUST type-check each substituted value against the schema the MCP tool advertises — if the tool expects an integer and substitution produces a non-numeric string, treat as resolver failure and log; do NOT silently coerce.
- **Response parsing:** the resolver entry MAY specify `response_path:` — a JSONPath-like expression (root `$`, dot-traversal, optional array index e.g. `$.data.items[0]`) telling the conductor which sub-object of the tool response carries `ticket_id` and `title`. If `response_path` is omitted, the conductor reads `ticket_id`/`title` directly from the top-level response object. If `response_path` is present but does not resolve (key missing, type mismatch), treat as resolver failure.
- **Failure & timeout:** MCP tool errors and tool-side timeouts are treated identically to shell-command non-zero exit — log and continue.

**Security model.**

`.agentic/phase0-classifiers.yml` runs with full conductor privileges: shell-command resolvers execute as the operator's shell user, and MCP-tool resolvers can invoke any MCP server the conductor has access to. Trust level is therefore equivalent to executable code committed to the repository — anyone who can land a change to this file can execute arbitrary commands in any session that runs `/implement-ticket` against the affected branch. **Operators MUST review changes to `.agentic/phase0-classifiers.yml` whenever pulling an untrusted or unfamiliar branch (collaborator PR, fork, dependabot, agent-authored branch) before invoking `/implement-ticket` on that branch.** The file is project-local by convention and is not signed, sandboxed, or sandbox-enforced. This trust posture matches the rest of the `.agentic/` umbrella but is called out explicitly here because Phase 0 runs before any other phase and is therefore the first execution surface a malicious classifier file could exploit.

**Rationale for `.agentic/phase0-classifiers.yml`** (over the AGENTS.md `## Tracker` extension): the project-local YAML keeps the classifier registry decoupled from tracker config (which is single-tracker by design); supports multiple un-enumerated trackers simultaneously (a project may use Jira primary + GitHub Issues secondary); and matches the `.agentic/` convention for project-local agentic state. AGENTS.md `## Tracker` remains the single-tracker config; new trackers don't replace it.

**Pagination cap.** Default 50 issues per URL/filter (combined across pagination). On overflow, prompt: `"JQL/filter returned >50 issues; capped at 50. Narrow the query or proceed with the first 50? (narrow / proceed)"`. On `narrow`: abort Phase 0. On `proceed`: keep first 50, log to `resolution_notes`.

**Sanity ceiling.** Hard refuse if `len(entries) > 200` after all classifiers and pagination. Print: `"Phase 0 resolved >200 tickets; refusing as a sanity ceiling. Narrow your input."` Exit. This is the ONLY hard refusal in Phase 0.

**Deduplication.** Dedupe `entries[]` by `ticket_id` preserving first-seen order. Record dropped duplicates in `resolution_notes`.

**Freeform handling (mixed-input residue).**

| Condition | Action |
|---|---|
| `entries` non-empty AND freeform residue present | **Default: route residue to `additional_operator_context`** (attach to every entry's downstream brief). Print residue + entries summary, prompt: `"Mixed input detected. Residue: '<first 200 chars>'. Entries: <list>. Attach residue as additional context to all entries, drop, or abort? (attach-to-all / drop / abort)  [default: attach-to-all]"`. On `attach-to-all`: set `additional_operator_context=<residue>`. On `drop`: set `additional_operator_context=null`, log to `resolution_notes`. On `abort`: exit. |
| `entries` empty AND residue AND `TRACKER=none` | Fast path above already caught this case. |
| `entries` empty AND residue AND `TRACKER ≠ none` | Confirm: `"No tracker IDs detected and TRACKER=<tracker>. Treat input as freeform task (no tracker fetch), or abort? (freeform / abort)"`. On `freeform`: set `freeform_task=<residue>`, `entries=[]`. On `abort`: exit. |
| `entries` empty AND no residue | Print: `"Phase 0 produced no entries and no freeform task. Re-invoke with a ticket reference or description."` Exit. |

**Failure handling per classifier.**

| Failure | Action |
|---|---|
| Unparseable URL | Treat as freeform residue. Log to `resolution_notes`. |
| JQL/filter returns 0 results | Print `"JQL/filter returned 0 issues."` Continue with other inputs. |
| JQL/filter auth failure | Print verbatim error. Abort Phase 0 (no silent freeform fallback — masks credential issues). |
| Screenshot has no detectable IDs | Print `"Screenshot contained no <PREFIX>-NNN matches."` Continue. |
| Screenshot ID prefix ≠ TICKET_PREFIX | Append anyway with `resolution_notes` warning. Phase 1 fetch is authoritative. |
| Mixed input where some IDs don't exist in tracker | Phase 0 validates *shape*, not *existence*. Phase 1's per-ticket fetch is authoritative. |
| Project-local classifier resolver failure | Treat as Unparseable URL. Log to `resolution_notes`. |

**Confirmation policy.** Confirmation runs ONLY in the cases below. All other resolutions proceed silently with a one-line `[phase: input-normalization | entries=<N> | freeform=<bool> | extra_context=<bool>]` breadcrumb.

| Trigger | Confirmation |
|---|---|
| JQL/filter URL → any N entries | **Soft warn + auto-proceed** — print resolved IDs + titles in a one-per-line list, do NOT prompt; emit `resolution_notes` entry. The operator wrote the JQL deliberately; Phase 0a batch triage already presents a per-ticket summary downstream; "as autonomously as possible" is the stated goal. (Aligned with the operator-enumerated >5 row below.) |
| Screenshot → any N entries | Yes — OCR is approximate, print extracted IDs, `(proceed / abort)` |
| Mixed input with freeform residue | Yes — `(attach-to-all / drop / abort)`, default `attach-to-all` |
| Cap hit (>50 from JQL/filter) | Yes — `(narrow / proceed)` |
| No IDs + TRACKER ≠ none + freeform residue | Yes — `(freeform / abort)` |
| Operator-enumerated sources (literal IDs, comma/space lists, single issue URLs, mixed bare-IDs+issue-URLs) producing >5 entries | **Soft warn + auto-proceed** — print loud warning enumerating all resolved IDs in a one-per-line list, do NOT prompt; emit `resolution_notes` entry. (Threshold of 5 is chosen because a single visual scan can verify ≤5 IDs; >5 deserves an explicit list so the operator catches typos, but the operator already enumerated each one — confirming would violate "as autonomously as possible".) |
| All other operator-enumerated cases (≤5 IDs, single URL, fully unambiguous) | **No confirmation.** Proceed silently. |
| Sanity ceiling (>200) | Refused (no prompt; hard exit). |

**Tier:** Tier 2 (conductor-direct, including screenshot read and resolver execution).

---

## Phase 0a-pre: Batch resume check

> Run this phase BEFORE the per-ticket Resume check below. This is the composition anchor: batch-level resume picks the ticket cursor first; the per-ticket Resume check then runs unmodified scoped to that ticket's branch and `loop-state.json`.

**Trigger:** Phase 0 normalization produced ≥ 2 entries (same trigger as Phase 0a). Skip otherwise. Single-entry invocations (Phase 0 produced exactly 1 entry, including the bare-ID fast path used by all Trivial single-ticket flows) bypass this phase entirely - no `.agentic/batch-state.json` is read or created.

**Read** `.agentic/batch-state.json` if present. Apply the decision table below.

| `batch-state.json` state | Action |
|---|---|
| absent | Skip Phase 0a-pre. Fall through to the existing per-ticket Resume check, then Setup, then Phase 0a (which initializes `batch-state.json`). |
| `status=complete` | Print: "Prior batch complete; clearing." Delete the file. Fall through to the existing per-ticket Resume check. |
| `status=stalled` | Print stalled summary (tickets + reasons). Prompt: `resume / fresh / abandon`. On `abandon`: delete file and exit. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration (below) and pick next pending ticket. |
| `status=paused` | Print: `"Batch paused at operator request: [last_summary]."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=interrupted` | Print: `"Batch interrupted (reason: [interrupt_reason]). N completed, M pending/blocked."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=active` AND `last_updated > 10 min` ago | Treat as implicit interrupt. Same prompt as `interrupted` row. |
| `status=active` AND `last_updated ≤ 10 min` AND `session_id` matches current | Silent re-entry resume (rare; e.g. `/implement-ticket` re-invoked within the same session). Pick next pending ticket from `tickets[]`. |
| `status=active` AND `last_updated ≤ 10 min` AND (`session_id` differs OR `session_id` is null/absent) | If Phase 0 produced ≥ 2 entries: refuse with the verbatim Contract C message. If Phase 0 produced exactly 1 entry: see "N=1 foreign-batch warning" below; this row does not apply (Phase 0a-pre runs only when Phase 0 produced ≥ 2 entries). For N≥2 force-takeover prompts: print `"WARNING: another session (session_id=<X>, last_updated=<Y>) may still be active. Force takeover? (yes/no). Identify the live session via .agentic/loop-state.json last_updated."` and require explicit operator confirmation. |
| Parse failure | Print warning. Prompt: `delete-and-fresh / abort`. On `abort`: exit. On `delete-and-fresh`: delete file and fall through. |
| Inconsistent pair (`batch-state.json` says `active`, `loop-state.json` says `interrupted`) | Trust the non-active file. If both are stale-active (>10 min), treat as implicit interrupt for both. |

**Move ordering hazard (resume case).** On resume, `batch-state.json.tickets[]` is the authoritative ticket cursor and supersedes any Phase 0 output produced in the resuming session. If the operator re-supplied input that does not match the on-disk `tickets[]`, Phase 0a-pre MUST surface a warning before falling through:

```
WARNING: resumed batch tickets[] = [<list>] do not match this invocation's Phase 0 entries[] = [<list>].
The on-disk batch state takes precedence on resume. Continue resuming the prior batch, or abandon resume and use the new input?
(continue-resume / abandon-resume-and-use-new-input)
```

On `continue-resume`: discard Phase 0 output, use `batch-state.json.tickets[]`. On `abandon-resume-and-use-new-input`: delete `batch-state.json` and re-run Phase 0a from the new entries.

**Resume composition rule (binding).** If Phase 0a-pre confirms resume of an active batch, it sets the in-memory ticket cursor to the next pending ticket from `tickets[]` BEFORE falling through to the existing per-ticket Resume check. The per-ticket Resume check then runs UNMODIFIED but scoped to the picked ticket's branch and `loop-state.json`. The two state mechanisms compose: batch resume picks the ticket; per-ticket resume picks the phase within that ticket. They have non-overlapping scopes.

**Re-plan migration on resume.** When the operator confirms resume of any non-active batch state (`stalled`, `paused`, `interrupted`, or stale-`active` treated as interrupted):

1. `git fetch origin`.
2. For each ticket in `tickets[]` with `status` `pending` or `blocked`: re-fetch the tracker record. If the ticket has been merged elsewhere (per tracker status, or per `gh pr list --state merged --head <branch>` returning a non-empty result), append a `replan_log` entry `{ts, action: "drop_merged", ticket_id, detail}` and set the ticket's `status` to `skipped_already_merged`.
3. Spawn `orchestration-planner` over the surviving pending/blocked tickets to re-sequence. Re-spawn `investigator` only when `replan_count >= 2` (counted from `replan_log` entries with `action: "investigator_rerun"`).
4. All writes apply Contract A (per-write `session_id` gate) and Contract B (`replan_log[]` read-merge-write preservation). See "Batch state contracts" below.
5. Bump `status` back to `active`. Preserve `wallclock_started_at` from the prior batch (the wallclock cap is per-batch lifetime, not per-session - a batch resumed in a later session continues counting against the original `wallclock_started_at`).

Emit breadcrumb: `[phase: batch-resume | tickets_remaining=K]`.

---

## Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries)

**Trigger:** Phase 0 normalization produced ≥ 2 entries.

**Skip:** Phase 0 produced exactly 1 entry. Mixed-form inputs that Phase 0 normalized down to a single entry count as single-entry and skip Phase 0a.

**Flow:**

1. Spawn `investigator` (Tier 2) to read each ticket, identify shared files, flag duplicates, and cluster by surface area. The investigator returns a structured table mapping each ticket to its files-touched, related tickets, and any duplicates.
2. Spawn `orchestration-planner` (Tier 2) with the investigator's output. The planner returns a sequenced execution plan: which tickets can be processed in parallel, which must be sequential, which are blocked by others.
3. **Initialize `.agentic/batch-state.json`** (persistent batch cursor). First apply the Contract C concurrent-batch refusal: if the file already exists with `status=active`, a different `session_id`, and `last_updated` within the last 10 minutes, REFUSE with the verbatim Contract C message and exit. Otherwise, write the initial skeleton:
   - `schema_version: 1`
   - `session_id: <current>`
   - `batch_id: "<first ticket's TICKET_PREFIX>-batch-<ISO8601>-<4hex>"`
   - `status: "active"`
   - `tickets[]`: populated from planner output, each entry `status: "pending"`, with `cluster_id` and `depends_on` carried through from the planner
   - `wallclock_started_at: now`, `wallclock_cap_min: <env AGENTIC_BATCH_MAX_WALLCLOCK_MIN or 90>`
   - `replan_log: []`
   - `created_at: now`, `updated_at: now`

   Atomic tmp+rename. Apply Contract A on the write (this is a fresh write so no prior `session_id`; the gate effectively passes).
4. Conductor iterates through the planner's order, running existing per-ticket phases (1 → 12) for each ticket. **Per-ticket transition writes to `batch-state.json`** (each via Contract A + Contract B):
   - At ticket start: `status: "pending" → "in_progress"`, set `started_at`, update `updated_at`.
   - At ticket complete: `status: "in_progress" → "complete"`, set `ended_at`, `last_summary`, `pr_number`, `branch`.
   - At ticket block: `status → "blocked"` with detail in `last_summary`.
   - At ticket merged-elsewhere skip: `status → "skipped_already_merged"` with `replan_log` append.

**Persistent batch state lives in `.agentic/batch-state.json`. See Phase 0a-pre for the resume protocol.**

Emit breadcrumb: `[phase: batch-triage | N tickets | clusters=K]`.

---

## Phase 0b: Brief check + qa.md snapshot + on-resume Brief migration

Before any architect spawn, check for an existing Brief, snapshot qa.md for Elevated tickets, and handle the on-resume Brief migration for tickets predating the `qa_criteria` requirement.

### Brief check

**Slug derivation:** convert the ticket title to kebab-case and strip any ticket-ID prefix
(e.g. `AE-123 Add user login` becomes `add-user-login`).

**Check (either condition satisfies):**
1. A file exists at `docs/planning/<slug>.md`, OR
2. `.agentic/brief-session.json` exists with `status: complete` AND `brief_path` matching
   the ticket slug.

**If found:**
- Set `brief_path = docs/planning/<slug>.md` in the architect execution contract (Phase 3).
- At the promotion gate in Phase 3b: skip the conductor-authored Brief step - the Brief is
  pre-existing and operator-confirmed.
- Pass `brief_source: operator` to the Skeptic-on-Brief gate; use the operator-confirmed
  Skeptic variant (completeness-only review per `content/commands/brief.md` Section 6).
- If `.agentic/brief-session.json` confirms `brief_source: operator`, set `operator_brief_injectionable: true` to signal Phase 3 that the Brief's committed constraints should be injected into the architect spawn brief (see Phase 3 "Pre-authored Brief injection").

**If not found:** proceed normally. The promotion gate in Phase 3b determines whether a
Brief is required based on the unit count from the orchestration-planner.

### qa.md snapshot (Elevated only)

After risk has been classified, if the current ticket is Elevated, snapshot any existing `.agentic/qa.md` to a per-ticket snapshot file. **Trivial invocations skip this step entirely** (preserves bit-for-bit-identical guarantee for Trivial single-ticket invocations - no `.agentic/qa.md.snapshot-*` file is produced).

**Snapshot rules:**

1. If risk is Trivial: skip this entire subsection. Do not create or touch any snapshot file.
2. If risk is Elevated and `.agentic/qa.md` does not exist: skip silently (nothing to snapshot).
3. If risk is Elevated and `.agentic/qa.md` exists and `.agentic/qa.md.snapshot-<ticket_id>` does NOT already exist: copy `.agentic/qa.md` to `.agentic/qa.md.snapshot-<ticket_id>` via atomic write (write to `.agentic/qa.md.snapshot-<ticket_id>.tmp`, then rename).
4. If risk is Elevated and `.agentic/qa.md.snapshot-<ticket_id>` already exists (e.g., on resume of a paused or interrupted ticket): preserve the existing snapshot. Do not overwrite. The original snapshot represents the qa.md state at the start of this ticket's first run.

The snapshot is consumed at Phase 11b by `wrap-ticket` to compute the diff between the snapshot and the working-tree `.agentic/qa.md`, surfacing qa.md additions made during this ticket. Phase 12 cleanup removes the snapshot file. The snapshot path is gitignored under the existing `.agentic/` umbrella; no `.gitignore` change is needed.

### On-resume Brief migration (qa_criteria backfill)

When Phase 0a-pre or the per-ticket Resume check detects an in-flight ticket whose Brief lacks the `qa_criteria` field (because the ticket was started before the `qa_criteria` requirement was rolled out), apply this migration before spawning any worker:

1. **Probe architect plan.** If the architect plan (referenced from the Brief or stored alongside it) contains a `qa_criteria` block, the conductor authors a retroactive Brief amendment appending the architect's `qa_criteria` block verbatim into the Brief. Proceed normally.
2. **If neither has `qa_criteria`** (legitimate transition ticket), surface the operator prompt verbatim:

   ```
   WARNING: this ticket's Brief and architect plan predate the qa_criteria requirement. Options:
     (a) provide a qa_criteria block now (paste YAML)
     (b) one-time bypass for this transition ticket (skip QA for this ticket only)
   Choose (a/b).
   ```

   On `(a)`: the operator pastes the YAML; conductor injects it into the Brief and proceeds.
   On `(b)`: conductor records a one-time bypass marker for THIS ticket only (in-context, scoped to this resume) and proceeds with QA skipped. The bypass does NOT extend to future tickets.

3. **New invocations (no in-flight state) hard-fail per architect plan.** Fresh `/implement-ticket` invocations on Elevated tickets without a `qa_criteria` block in the Brief or architect plan emit a Critical Skeptic finding on the architect plan; the conductor does not proceed past Phase 3 until the architect plan supplies the block. The on-resume bypass option is exclusively for tickets that started before this requirement existed.

---

## Phase 1: Understand the ticket

(Setup has already resolved TRACKER. Execute exactly one of the sub-sections below.)

**Iteration:** Phase 1 runs once per `entry` in `normalized_input.entries`. The current `[TICKET_ID]` refers to `entry.ticket_id`. When `normalized_input.entries` is empty AND `normalized_input.freeform_task` is set, only the `TRACKER is none` sub-section executes, with `freeform_task` as the description. When `entries` is non-empty, the `TRACKER is none` sub-section is skipped regardless of TRACKER value.

When `normalized_input.additional_operator_context` is non-null, append it verbatim to every entry's downstream architect (Phase 3) and engineer (Phase 5) brief, prefixed with `"Additional operator context (applied to all entries):"`. This routes mixed-input residue into the per-entry brief without dropping operator intent.

#### If TRACKER is `linear`

1. Call `mcp__linear__get_issue` with the ticket ID and `includeRelations: true`.
2. Read the full description — specifically the **Implementation**, **Files**, and **QA** sections.
3. Note any blocking tickets (`blockedBy`) — confirm they are done before proceeding.
4. Note the ticket type (feature vs bug) — this drives branch naming.

#### If TRACKER is `jira`

1. Call `mcp__mcp-atlassian__jira_get_issue` with `issue_key: "[TICKET_PREFIX]-NNN"` and `fields: "*all"` to get the full issue including description and current status.
2. Read the full description — note any **Acceptance Criteria**, **Implementation Notes**, and **QA** content in the description or sub-tasks.
3. Note any blocking issues — confirm they are resolved before proceeding.
4. Note the issue type (Story, Bug, Task) — this drives branch naming.

#### If TRACKER is `none`

No ticket to fetch. **Use `normalized_input.freeform_task` as the ticket content** for all downstream phases. The pre-existing operator prompt is superseded by Phase 0's freeform fast path. Set ticket type to "feature" unless the operator's description indicates otherwise.

---

Proceed to Phase 2 regardless of which sub-section executed.

---

## Phase 2: Read the codebase

Before planning, gather context:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO fetch origin $BASE_BRANCH --quiet
```

Read:
- Files mentioned in the ticket description
- Sibling files to understand existing patterns
- `$REPO/AGENTS.md` for conventions
- The project's `MEMORY.md` (auto-injected at session start) for architectural decisions and rationale; if the project maintains a custom decision log, read that too
- Any `[track]/AGENTS.md` files for tracks touched by this ticket - track-specific conventions, stack, and gotchas

Focus on understanding enough to make a solid plan - don't over-read.

**Investigator conditional:** If the task risk is **Low or above AND** the code area touched by this ticket is unfamiliar to the current session (files not yet read, subsystems not yet traced), spawn an `investigator` agent first. Pass its brief to the Architect in Phase 3. Skip this step if Phase 2 reads already covered the relevant area.

Trivial-classified tickets skip the investigator (not required); the shippable change is still performed by a worktree-isolated `engineer` (no Skeptic, no brief) per METHODOLOGY.md §Risk Classification - the conductor does not edit the shippable tree directly.

---

## Phase 2b: Pre-architect ambiguity scan

**Applies only when ALL of the following hold:**
- Risk classification is Elevated
- `brief_path` was NOT set in Phase 0b (no Brief found — neither a file-existence match nor an operator-confirmed session)
- This is the single-unit path (no prior agent has decomposed the ticket into multiple units)

Skip this phase entirely for Trivial, Low, multi-unit, or Brief-present tickets.

**The conductor scans the ticket text for ambiguity signals:**
- Vague scope language ("something like", "similar to", "improve", "better", "clean up") with no concrete target state
- No explicit done condition or acceptance criteria stated anywhere in the ticket
- Two or more mutually exclusive reasonable interpretations of the core ask
- A load-bearing context value is unstated (target environment, performance budget, affected user type, data scale) where the implementation would materially branch on it

**When one or more signals are present:** the conductor surfaces 1-3 targeted, specific questions in its user-facing turn, each with a recommended default. Format follows the surface-and-proceed protocol in `content/sections/02-delegation.md`. The conductor waits exactly one operator turn.
- If the operator answers: fold answers verbatim into the Phase 3 architect brief under `"Operator clarifications:"`.
- If the operator does not answer within their next turn (says "proceed", asks something else, or is silent): proceed with the recommended defaults, noted in the architect brief under `"Conductor defaults applied:"`.

The scan never blocks more than one turn. Proceed to Phase 3 after the response (or default).

**When no signals are present:** proceed directly to Phase 3, silently.

**Stop-frequency budget:** this pre-architect planning-input scan is explicitly exempt from the stop-frequency table in `content/sections/02-delegation.md` (see the carve-out there). It does not count toward the per-task stop budget for any task shape. It is a planning-input step, not a mid-work blocker.

---

## Phase 2c: Tracker state discovery (conditional)

Runs only when `TRACKER != none`. Skipped silently otherwise. Purpose: fetch the tracker's workflow states once, cache them, and validate the configured `TRACKER_STATE_*` names so misconfigurations surface as a warning at planning time rather than as a silent no-op transition at runtime.

**Cache check.** Read `.agentic/tracker-states.json` if present. Use the cache when ALL hold: file exists, `fetched_at` is within 24 hours of now, `tracker` matches the resolved `TRACKER`, and `workspace` matches the resolved workspace/base-url. Otherwise fetch fresh.

**Fetch.**
- Linear: call `mcp__linear__list_workflow_states` (filter by the resolved team when available). Collect `{id, name, type}` for each state.
- Jira: call `mcp__mcp-atlassian__jira_get_transitions` on a probe ticket (the first unresolved ticket in the batch, or `$TICKET_PREFIX-1` as a fallback probe). On 404 or error, fall back to an empty state list and skip validation. Map each transition's target status to `{id, name, type}` where `type` derives from the status category (`new`->`unstarted`, `indeterminate`->`started`, `done`->`completed`).

**Write cache** atomically (tmp + `mv`) to `.agentic/tracker-states.json`:

```json
{
  "fetched_at": "<ISO8601 UTC>",
  "tracker": "linear|jira",
  "workspace": "<workspace-slug-or-base-url>",
  "states": [{"id": "...", "name": "In Progress", "type": "started"}],
  "warnings": []
}
```

`.agentic/tracker-states.json` is a runtime cache, gitignored under the `.agentic/` umbrella (NOT committed - it is machine-local and may be stale on a fresh checkout; that is acceptable since this preflight is soft-fail).

**Validate.** For each of the 5 resolved `TRACKER_STATE_*` values, look for an exact (case-insensitive) name match in `states[].name`. For each miss, compute the closest match by case-insensitive Levenshtein distance and emit one operator-visible warning:

```
WARNING: configured state '<name>' not found in <tracker> workflow. Closest match: '<closest>'. Proceeding with configured name - transition may be silently skipped at runtime.
```

Append each warning to the cache's `warnings[]` array. Do NOT block execution.

**Soft-fail.** Any MCP/API error during fetch is logged and the phase proceeds (no cache write on fetch failure; validation skipped). Never block planning on tracker discovery.

Emit breadcrumb: `[phase: tracker-state-discovery | cached=<true|false> | misses=<N>]`

---

## Phase 3: Architecture plan

Spawn an `architect` agent. Provide:
- The full ticket title and description
- The relevant code snippets you gathered
- The AGENTS.md conventions
- Any architectural decisions and rationale from MEMORY.md (or the project's custom decision log) that bear on this ticket

**Pre-authored Brief injection (only when `operator_brief_injectionable` was set in Phase 0b).** Check this flag before proceeding. When set, read the Brief file at `brief_path` and prepend the following to the architect spawn brief:
- The Brief's **Problem** section, labeled: `"Committed problem statement (from operator Brief — do not redefine):"`
- The Brief's **Success criteria** bullets, labeled: `"Committed success criteria — your plan MUST demonstrably address every one of these:"`
- The Brief's **Non-goals**, labeled: `"Out of scope (do not design for these):"`
- The Brief's **Constraints**, labeled: `"Hard constraints (a design that violates any of these is rejected):"`

The architect treats these as fixed inputs. An uncovered committed success criterion is a Critical Skeptic finding on the architect plan.

This injection does NOT apply to conductor-authored Briefs (those are downstream of the architect by design). Only operator-authored Briefs (`brief_source: operator`) carry committed constraints.

Ask the architect for:
1. A concrete implementation plan (what changes, in which files, in what order)
2. Which units of work can be done **in parallel** vs must be **sequential**
3. Any risks, gotchas, or ambiguities that need resolution before coding
4. The appropriate adversarial brief type for Skeptic review (security, logic, performance, data integrity, etc.)

**Architect plan Skeptic review (mandatory):** After the Architect returns its plan, spawn a Skeptic with the "Document synthesis, architecture, and planning" adversarial brief. Do not proceed to Phase 3b or Phase 4 until the Skeptic grants sign-off. If the Skeptic-approved plan contains a non-empty "Open questions" section, resolve every open question before proceeding - see `METHODOLOGY.md` for resolution paths. For the full adversarial brief menu, see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

---

## Phase 3b: Orchestration plan (conditional)

**Trigger** - spawn `orchestration-planner` if any of the following are true:
- The architect identified parallel units
- The ticket mentions changes across 3 or more distinct directories or top-level modules
- The architect's plan contains 3 or more distinct implementation units, or explicitly flags sequencing uncertainty or agent selection ambiguity

**Skip** - proceed directly to Phase 4 if none of the trigger conditions above are true.

**When spawning `orchestration-planner`, provide:**
- The full ticket title and description
- The architect's complete output
- Instruction to produce: agent roster, execution phases (each with Give it / Returns / Proceed when fields), Skeptic checkpoints, and parallelization opportunities

The orchestration-planner's output drives Phase 5 agent spawning. If Phase 3b was skipped, Phase 5 falls back to the architect's plan directly.

### Task-state initialization (multi-unit only)

**Single-unit threshold:** If the orchestration plan identifies only 1 task, skip this step entirely. Task-state initialization is only warranted for plans with 2 or more tasks. For single-unit plans, the conductor operates as today (in-context state only).

After receiving the orchestration-planner's output and before Phase 4, initialize the task-state file:

```bash
mkdir -p .agentic && [ -f .agentic/tasks.jsonl ] || touch .agentic/tasks.jsonl
```

Also add `.agentic/` to the project's `.gitignore` if not already present.

**Generate identifiers (once per conductor session):**
- `session_id`: `<ISO-date>-<4hex>`, e.g. `20260415-a3f2`
- `task_id` per task: `<ticket_id>-<unit_slug>` (e.g. `ENG-42-auth-middleware`), or `<session_id>-<unit_slug>` for null-ticket projects

**Read the orchestration-planner's structured JSONL block** (the `## Task entries (machine-readable)` section at the end of the plan output). For each entry in that block, append a `pending` entry to `.agentic/tasks.jsonl`. Write tasks in dependency order - independent tasks (empty `depends_on`) first, dependent tasks after. Each entry must include the fields from the schema: `task_id`, `session_id`, `ticket_id`, `unit_slug`, `status: pending`, `depends_on`, `created_at`, `updated_at`, and the full `inputs` object (`description`, `acceptance_criteria`, `files_in_scope`, `quality_cmd`, `repo_path`, `base_branch`).

Emit breadcrumb: `[phase: task-state-init | N tasks written]`

### Cross-artifact alignment check (Brief present + planner returned units with non-empty criteria)

**Applies only when ALL hold:**
- `brief_path` is set (a Brief exists — operator-authored from Phase 0b, or conductor-authored at the promotion gate)
- The orchestration-planner returned a JSONL block with at least one unit carrying a non-empty `acceptance_criteria` array

When the guard does not apply (no Brief, or all units carry `acceptance_criteria: []`): emit `[phase: cross-artifact-check-skipped | no criteria to map]` and proceed to the promotion gate.

**This is a conductor-direct mechanical mapping, not a subagent and not adversarial review.** It complements the Skeptic-on-Brief; it does not replace it.

**Procedure:**
1. For each **Success criterion** in the Brief: scan every orchestration unit's `acceptance_criteria` array. Mark the criterion **COVERED** if at least one unit's entry explicitly addresses it; mark it **UNCOVERED** otherwise.
2. Produce a mapping table: `success criterion → covering unit_slug(s)`, or `"UNCOVERED"`.

**On any UNCOVERED criterion:** resolve before the Skeptic-on-Brief fires by one of:
- (a) Re-spawn the orchestration-planner with the specific uncovered criteria called out, so it adds or amends a unit's `acceptance_criteria`.
- (b) Surface the mismatch to the operator with a recommended resolution (descope the criterion from the Brief, or expand scope to cover it).

The conductor does not proceed to the Skeptic-on-Brief with an unresolved UNCOVERED criterion.

**On full coverage:** emit `[phase: cross-artifact-aligned | N/N criteria covered]` and proceed to the promotion gate.

See `content/sections/03-planning-artifacts.md` Gate semantics for where this step sits relative to the Skeptic-on-Brief.

**ALL writes to `.agentic/tasks.jsonl` are conductor-only.** Workers do not read or write the task file. Workers return their summaries to the conductor in the normal return path; the conductor extracts results and writes all updates. No lock protocol is needed because the conductor is the sole writer.

**File-absent vs file-present behavior:**

- **File absent:** Fresh start. Create the file and append `pending` entries as described above.
- **File present, same `session_id`:** Continuation within the same session (e.g., a prior worker returned BLOCKED and the human provided direction). Build the in-memory index using the field-level merge algorithm (see Worker behavior in the P1 design), determine which tasks are pending/in-progress/done, and proceed accordingly.
- **File present, different `session_id`, with `in_progress` or `blocked` entries:** Orphaned tasks from a dead session. Log: "Found `.agentic/tasks.jsonl` with N orphaned tasks from a prior session." Surface the task list to the human with their last-known status and `updated_at` timestamp. Ask: "Do you want to resume from this state, or start fresh? (resume/restart)". On **restart**: rename the existing file to `.agentic/tasks.jsonl.YYYYMMDD-HHMMSS.bak`, create a new file, and proceed as fresh start. On **resume**: automatic resume is not yet implemented (P2). Display the last-known state of each task and say: "Automatic resume is not yet implemented. Here is the last-known state of each task: [table]. You can manually direct re-spawns for any in-progress tasks."
- **File present, different `session_id`, all terminal (`done`, `failed`, `abandoned`):** Historical records from a prior implementation. Append new entries for the current session without disturbing existing ones.

---

## Phase 4: Create the branch

**Branch naming:** use the branch naming convention from AGENTS.md. Derive the short title from the ticket title: lowercase, hyphens, ~4-5 words max. The conductor resolves `BRANCH_NAME` here regardless of path.

**Elevated single-engineer path.** The conductor does NOT run `git checkout -b` on this path. Branch and worktree creation are delegated to the engineer via the new `worktree_setup` execution-contract field (see Phase 5). The conductor passes the resolved `BRANCH_NAME` and `BASE_BRANCH` in the engineer brief; the engineer runs the literal git commands.

**Trivial single-engineer path.** Branch and worktree creation are delegated to the worktree-isolated Trivial `engineer` (the conductor never runs `nvm use`/`git checkout -b` itself). Because the Trivial engineer carries the lightweight contract and therefore has NO `worktree_setup` contract field (see the Trivial-path carve-out, STEP 9c), the conductor conveys the create sequence as plain prose in the lightweight engineer brief: the resolved `BRANCH_NAME`, `BASE_BRANCH`, AND the literal create-commands sequence INCLUDING the `export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20` bootstrap line followed by the `git -C $REPO checkout -b [BRANCH_NAME per AGENTS.md convention] origin/$BASE_BRANCH` command. The engineer runs that sequence verbatim in its own worktree. The lightweight Trivial contract (no Skeptic, no brief file, no heavy `worktree_setup`/`quality_gates`/`git_finalization` block) is preserved.

**Phase 5 parallel fan-out path.** Conductor-side worktree creation is preserved as today; the fan-out logic lives in Phase 5 itself.

**Cross-reference note.** Branch/worktree creation paths: (a) Elevated single-engineer — engineer-owned via `worktree_setup`; (b) Trivial single-engineer — engineer-owned in a worktree (lightweight contract; conductor never edits the shippable tree directly); (c) Parallel fan-out — conductor-orchestrated per Phase 5 protocol. Future edits to any one site should sync the others.

---

## Phase 5: Implement

Use the orchestration-planner's output to drive agent spawning decisions if Phase 3b produced a plan. If Phase 3b was skipped, use the architect's plan directly. When both are present, the orchestration-planner's output supersedes the architect's plan for agent spawning and parallelization decisions.

Read the orchestration-planner's output to make the routing determination below if Phase 3b ran; read the architect's output directly if Phase 3b was skipped.

**Module manifests:** Files modified must carry module manifests per `~/agentic-engineering/.claude/skills/agentic-engineering/rules/module-manifest.md` when non-trivial. Skeptic enforcement is tiered in Phase 6: missing manifests are flagged as Minor (does not block sign-off), stale manifests as Major (blocks sign-off absent a compelling documented reason to defer), and stale manifests whose inaccuracy could mislead a caller on a correctness or security path as Critical. When modifying an existing manifested file, update the manifest in the same change if purpose, public API, upstream dependencies, downstream consumers, or failure/retry semantics shift.

### If work is a single logical unit (or units must be sequential):

**Tracker writeback (W1):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_IN_PROGRESS`, `forward_only_guard: true`. Fire-and-forget; do NOT wait for return. Continue immediately to the engineer spawn below.

[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS]

Spawn one `engineer` agent per unit in sequence. Each agent prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, filling in fields from the architect's plan / orchestration-planner output for this unit
- The plan for this unit: if Phase 3b ran, use the orchestration-planner's output for this unit; if Phase 3b was skipped, use the architect's plan for this unit
- The branch name to work on
- The repo path: `$REPO`
- Instruction to run `$QUALITY_CMD` from the repo root before finishing and fix any errors

**Worktree isolation is mandatory on the Elevated path.** The Agent tool call spawning the engineer MUST set `isolation: "worktree"` (see METHODOLOGY.md §Delegation > Worker preamble). This applies to every Elevated-path engineer spawn - single-unit, parallel fan-out, and Phase 7 fix engineers alike. Only the Trivial-path solo engineer carve-out (below) is exempt.

**Stale remote branch preflight (mandatory before every engineer spawn).** Before passing `BRANCH_NAME` to the engineer (single-engineer path) or before creating per-unit sub-branches (fan-out path), the conductor MUST run:

```bash
git -C $REPO ls-remote --heads origin "$BRANCH_NAME"
```

Decision table:

| `ls-remote` result | Action |
|---|---|
| Empty (no remote ref) | Proceed with `BRANCH_NAME` as resolved. |
| Returns a SHA AND that SHA is reachable from the local resume state for this ticket (resume case - we're picking up our own prior work) | Proceed with `BRANCH_NAME` as resolved. |
| Returns a SHA that does NOT match anything we intend to push (stale branch from an unrelated session, abandoned PR, prior batch run) | Append a uniqueness suffix to `BRANCH_NAME` BEFORE passing it to the engineer. Default suffix: `-v2`. If `-v2` also collides, use `-<7-char-short-sha>` of the conductor's current HEAD. Re-run `ls-remote` against the new name to confirm it is free. |

The engineer is never asked to handle a rename mid-implementation. The conductor resolves uniqueness once, before the spawn. Log the resolution to `resolution_notes` (one line: `branch_collision: <original> → <renamed> (remote SHA <sha>)`) so the operator can audit later. This preflight runs on every engineer spawn that creates a branch (Elevated single-engineer, fan-out per-unit, Phase 7 fix engineer, and the Trivial-path solo worktree engineer - branch creation on the Trivial path is performed by that engineer in its worktree, see Phase 4).

**Elevated-path engineer-contract extensions.** On the Elevated path, the engineer brief MUST include three additional contract fields (in addition to the standard `outputs`, `tool_scope`, `completion_conditions`, etc.):

- `worktree_setup`: `{ branch_name, base_branch, worktree_path, create_commands }` — the engineer creates the branch and worktree (or in-place branch if no worktree) using these literal git commands. The conductor populates `branch_name` and `base_branch`; `worktree_path` is set when worktree isolation is in use, otherwise null; `create_commands` is the literal `git -C $REPO checkout -b ...` (or `git -C $REPO worktree add ...`) sequence.
- `quality_gates`: `{ command, cwd, must_pass: true }` — the engineer runs `$QUALITY_CMD` itself before declaring done. The conductor never re-runs gates on this path (Phase 7 verifies from the return shape; see Phase 7).
- `git_finalization`: `{ commit_message_template, files_to_stage, push }` — the engineer commits and pushes. `push: true` for the Elevated path.

Extend `completion_conditions` to include: "quality_gates.command exits 0", "commit and push completed per git_finalization", and "quality_gate_results captured in return".

The engineer return shape on the Elevated path now requires `quality_gate_results: { lint, typecheck, test, raw_output }` (with `raw_output` capped at 4000 chars). This mirrors the binding contract documented in `content/agents/engineer.md`.

**Phase 7 fail path note.** When `DEBUGGER_ON_FAILURE` is `true` (see Setup) and the path is Elevated, Phase 7's gate-failure path interposes a Debugger diagnosis step before the next engineer fix pass. See Phase 7 "If the gate fails" for the full flow.

**Trivial-path solo engineer carve-out.** Trivial solo engineer spawns keep the lightweight contract: no heavy `worktree_setup`/`quality_gates`/`git_finalization` contract block, no `quality_gate_results` return field, no Skeptic, no brief file. But the actor is a worktree-isolated `engineer`, not the conductor: branch creation, the (lightweight) quality check, the commit, and the push are all performed by the Trivial engineer inside its own worktree (`isolation: "worktree"`). The conductor never edits the shippable tree directly. Only the heavy Elevated ceremony is dropped - the actor and execution location are the worktree engineer.

**Tracker writeback (W1 — Trivial path):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_IN_PROGRESS`, `forward_only_guard: true`. Fire-and-forget; do NOT wait for return. Continue immediately to the Trivial engineer spawn.

[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS | path: trivial]

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Task-state reads (multi-unit only, when `.agentic/tasks.jsonl` is in use):**

Before spawning each worker: check the task's `depends_on` field in the file. All dependency `task_id`s must have `status: done` before this task can start. Update the task entry from `pending` -> `in_progress` immediately before spawning. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path if using worktree isolation, null otherwise), and `branch_name` (the branch the worker will operate on).

After each worker returns: read the return summary, extract `worker_summary`, `commit_sha`, `files_modified`, and `quality_gate_passed`. Write an update entry to `.agentic/tasks.jsonl` with these output fields. Status remains `in_progress` until Skeptic sign-off or final determination.

After the Skeptic/QA loop resolves: update the task entry to its terminal status (`done`, `failed`, `blocked`, or `abandoned`) and populate the `loop_state` field from the P0 LOOP_STATE object. Include `outputs.skeptic_status` and `outputs.skeptic_findings_count` from the completed Skeptic review (or `skipped`/null if Skeptic was not required).

### If parallel independent units were identified:

**N=1 degenerate case:** If the orchestration-planner returned exactly 1 unit, do NOT invoke the fan-out primitive. Fall through to the standard single-engineer path above.

Use git worktrees to give each engineer an isolated copy. The orchestration-planner's JSONL block provides `unit_slug`, `merge_order`, and `skeptic_strategy` for each unit - read these fields to drive worktree naming, merge ordering, and Skeptic strategy. Before creating worktrees, prune stale state from any prior fan-out:

```bash
# Prune stale worktree metadata and remove any leftover sub-branches from prior runs:
git -C $REPO worktree prune
# If any ${FEATURE_BRANCH}-${unit_slug} branches exist from a prior run, delete them before proceeding.
```

Create one worktree per unit, each rooted from `BASE_BRANCH` (loop over all N units from the planner's JSONL block in `merge_order` sequence):

```bash
# For each unit (unit_slug from planner JSONL block):
git -C $REPO worktree add ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} \
  -b ${FEATURE_BRANCH}-${unit_slug} origin/$BASE_BRANCH
```

**Task-state reads (when `.agentic/tasks.jsonl` is in use):** Before spawning, verify all `depends_on` task_ids are `done` in the file and update each task entry from `pending` -> `in_progress`. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path of the unit's worktree), and `branch_name` (the unit's sub-branch `${FEATURE_BRANCH}-${unit_slug}`).

Spawn one `engineer` agent per worktree in a single message (parallel, background). Each engineer works in its assigned worktree path and commits to its own sub-branch. Each agent's prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, with fields filled in from the per-unit scope in the planner's JSONL block
- The unit's `task_id`, acceptance criteria, `files_in_scope`, `quality_cmd`, and worktree path
- The per-unit scope: extracted from the orchestration-planner's JSONL block for that unit

**Join condition.** The conductor spawns all N engineers in a single message and waits for all N to return. After all N engineers return, evaluate the join:

- **All-done join:** all N units reach `status: done` (Skeptic signed off per P0 loop where applicable). Proceed to merge phase.
- **Partial success:** one or more units reach `status: failed` or `status: blocked`, and one or more reach `status: done`. Do NOT merge any branch. Apply partial success path (see below).
- **Total failure:** all units failed or blocked. Clean up all worktrees, escalate to human with the orchestration-planner's original plan and all failure outputs. Recommend sequential implementation as fallback.
- **Blocked:** any unit with `status: blocked` is treated as failed for join evaluation. A worker returns `Status: BLOCKED` when it encounters a scope conflict, design ambiguity, or permission issue requiring human input.

**Join timeout.** The join phase has a 30-minute total deadline. If the deadline elapses before all engineers have returned, units with no completion entry are treated as timed out (failed) and handled via the partial success path. Units that completed `status: done` before the deadline are still eligible for merge.

**Fallback: no task-state file.** If `.agentic/tasks.jsonl` is not in use, derive status from each engineer's return value. Each engineer's return must include a structured status line as the first line: `Status: DONE`, `Status: DONE_WITH_CONCERNS`, or `Status: BLOCKED`. The engineer brief must explicitly require this structured first line.

After all engineers return, update task-state output fields for each unit: write `worker_summary`, `commit_sha`, `files_modified`, and `quality_gate_passed` to each task's entry. Status remains `in_progress` until Skeptic sign-off or final determination.

**Partial success path.** When one or more units fail and one or more succeed:
1. Record which units are `done` vs `failed`/`blocked`.
2. If done units are truly independent (no shared interface with failed units): merge done units into `FEATURE_BRANCH` sequentially in `merge_order`. Leave failed units' worktrees in place.
3. Spawn a retry engineer for each failed unit, pointing it at the preserved worktree and the failure detail. The retry brief must include: (a) the original task brief from the task-state `inputs` field, (b) the failure detail from `outputs.worker_summary` and `outputs.quality_gate_passed`, (c) the preserved worktree path, (d) any partial commits in the worktree, and (e) explicit instruction that this is a re-run, not a fresh start.
4. If the retry succeeds, merge and proceed to the Skeptic phase.
5. If the retry fails a second time, escalate to human with the full failure history.
6. Maximum retry depth: 1 automatic retry per unit.

**Per-unit Skeptic spawning (when `SKEPTIC_STRATEGY: per-unit`).** After each unit's engineer returns `done`, spawn a Skeptic for that unit's diff (unit worktree diff against `BASE_BRANCH`). Per-unit Skeptics for independent units can be spawned in parallel (single message - they are reviewing non-overlapping diffs). Each unit's Skeptic integrates with the P0 persistence loop (Engineer -> Skeptic -> fix loop within the unit's worktree). A unit is `status: done` only after its Skeptic signs off, not after the engineer's first commit. After each unit's Skeptic/QA loop resolves, update the task entry to terminal status and populate `loop_state`, `outputs.skeptic_status`, and `outputs.skeptic_findings_count`.

**Integration Skeptic (when `SKEPTIC_STRATEGY: integration`).** Do NOT spawn per-unit Skeptics. After all units' engineers return done, merge all unit branches onto a scratch integration branch (not `FEATURE_BRANCH` - the merge is provisional until the Skeptic signs off). Spawn one integration Skeptic reviewing the combined diff from `BASE_BRANCH` to the scratch integration branch. The integration Skeptic IS the Phase 6 gate for this strategy (see Phase 6 guard below). The orchestration-planner's independence annotation (added when the planner classified units) becomes the adversarial brief hint: pass it to the integration Skeptic so it knows the expected interaction boundaries.

**Merge phase (all-done join).** After all units are done (Skeptics signed off for `per-unit`, or after integration merge for `integration`), merge unit sub-branches into `FEATURE_BRANCH` sequentially in `merge_order`:

```bash
git -C $REPO checkout $FEATURE_BRANCH

# For each unit in merge_order sequence:
git -C $REPO merge --no-ff ${FEATURE_BRANCH}-${unit_slug}

# After each merge, check for conflicts before continuing:
# git -C $REPO diff --name-only --diff-filter=U
# If that command outputs any file names, conflicts are present - apply N>2 conflict recovery below.
```

**N>2 conflict recovery.** On merge conflict at any step:
1. `git -C $REPO merge --abort`
2. Do not attempt remaining merges.
3. Collect conflict files, all units' diffs, and the orchestration-planner output.
4. Spawn a single engineer with a conflict-resolution brief: all units' complete changes, the conflict markers, and explicit instruction to implement all units sequentially in a single worktree targeting `FEATURE_BRANCH`.
5. The sequential re-implementation engineer inherits a single-Skeptic review obligation (one Skeptic over combined diff, since units are now interdependent by fact of their conflict).
6. The conflict re-route counts as iteration 1 of the Phase 6 loop (do not double-count).

**Branch verification before merge.** Before merging each unit's branch, verify the worktree is on the expected branch:

```bash
# Confirm branch matches expected sub-branch before merging:
# git -C ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} rev-parse --abbrev-ref HEAD
# If the branch name does not match ${FEATURE_BRANCH}-${unit_slug}, abort that unit's merge and escalate.
```

**Post-merge integration quality check.** After all N merges complete cleanly on `FEATURE_BRANCH`, run `$QUALITY_CMD` from `FEATURE_BRANCH` root. If the integration check fails, spawn one engineer on `FEATURE_BRANCH` with the integration failure output. This engineer has full context (all units' work is on the branch). The resulting fix goes through a single Skeptic on the incremental diff before Phase 5 is declared complete. The integration fix Skeptic does NOT replace Phase 6.

**Worktree cleanup.** After all merges succeed (or after escalation, to prevent stale worktree accumulation):

```bash
# For each unit:
git -C $REPO worktree remove ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} --force
git -C $REPO branch -d ${FEATURE_BRANCH}-${unit_slug}
git -C $REPO worktree prune
```

For full worktree cleanup rules (isolation worktrees, feature worktrees, stale branch pruning), see `METHODOLOGY.md §Worktree Lifecycle`.

**Merge-conflict re-route and loop iteration:** If a merge conflict re-route occurred above and the re-routed Engineer's output then goes through Skeptic review in Phase 6, the conflict re-route counts as iteration 1 of the Phase 6 loop. Do not double-count: the conflict-resolution Engineer pass is the first fix pass; Phase 6 initializes its `iteration` counter at 1 to reflect this.

---

## Phase 6: Skeptic review

**Phase 6 guard (fan-out integration Skeptic).** When fan-out was active in Phase 5 and `SKEPTIC_STRATEGY: integration`, the integration Skeptic that reviewed the combined diff in Phase 5 IS the Phase 6 gate. Do not spawn a second Skeptic - Phase 6 is complete when the integration Skeptic signs off. When `SKEPTIC_STRATEGY: per-unit`, Phase 6 fires as normal - a Skeptic reviews the combined diff from `BASE_BRANCH` after all merges (`git -C $REPO diff origin/$BASE_BRANCH..HEAD`). This is a full-picture review that catches cross-unit interactions the per-unit Skeptics could not see (emergent behaviors, combined diff scope). Phase 6 is NOT skipped for the `per-unit` strategy.

**Tracker writeback (W2)** — fires on iteration 1 only: if `TRACKER != none` AND this is the first Skeptic spawn in Phase 6 (not a re-route from a prior engineer fix pass), invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_IN_REVIEW`, `forward_only_guard: true`. Fire-and-forget.

[phase: tracker-writeback | site: W2 | target: $TRACKER_STATE_IN_REVIEW | iter: 1]

Spawn a `skeptic` agent with:
- The adversarial brief type identified by the architect
- The full diff: `git -C $REPO diff origin/$BASE_BRANCH..HEAD`
- The ticket description as the success criteria
- The QA section from the ticket as acceptance tests

For the full adversarial brief menu (security, logic, performance, data integrity, etc.), see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Findings handling - loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (create `.agentic/` directory if absent). **Use atomic write: write to `.agentic/loop-state.json.tmp` first, then rename to `.agentic/loop-state.json`.**

**Full P2 schema (extends the P0 in-context schema with cross-session resume fields):**

```json
{
  "schema_version": 1,
  "session_id": "<current session uuid or null>",
  "ticket_id": "<string | null>",
  "branch": "<string>",
  "repo": "<string>",
  "base_branch": "<string>",
  "status": "active",
  "interrupted_at": null,
  "interrupt_reason": null,
  "last_phase": "skeptic",
  "last_phase_action": "spawned",
  "loop_state": {
    "phase": "skeptic",
    "iteration": 1,
    "max_iterations": 3,
    "findings_log": [],
    "qa_failures_log": [],
    "last_engineer_summary": null,
    "termination_reason": null
  }
}
```

**Field notes:**
- `session_id` is the conductor session uuid. Every conductor write to `loop-state.json` includes this field; every write applies Contract A's per-write `session_id`-mismatch abort gate. Readers tolerate absence for back-compat with state files written by prior versions. See "Batch state contracts" above.
- `last_phase` is the **authoritative resume key** - used exclusively for resume entry selection. Do NOT use `loop_state.phase` for this.
- `loop_state.phase` reflects which loop is active (skeptic or qa) and is used only to reconstruct in-context LOOP_STATE on resume.
- `last_engineer_summary` must be written verbatim to disk when an Engineer returns, capped at 2000 characters if longer. This allows resume to reconstruct the brief for the next Skeptic spawn.
- `status` values: `"active"` (loop running), `"interrupted"` (Stop hook or crash), `"complete"` (loop exited cleanly), `"stalled"` (cap_reached/convergence_failure/blocked escalation).

**Write triggers for Phase 6 Skeptic loop (overwrite using atomic write at each transition):**
- At loop initialization (before first Skeptic spawn): `last_phase=skeptic`, `last_phase_action=spawned`
- After Skeptic returns, before Engineer spawn: `last_phase=skeptic`, `last_phase_action=returned`
- After Engineer spawned (fix pass): `last_phase=engineer`, `last_phase_action=spawned`
- After Engineer returns: `last_phase=engineer`, `last_phase_action=returned`; update `loop_state.last_engineer_summary` (verbatim, capped 2000 chars)
- After each `findings_log` update (Steps 2, 3, 5): overwrite with updated `loop_state`
- On clean termination: set `status=complete`, `loop_state.termination_reason=clean`
- On stalled termination (cap_reached, convergence_failure, blocked): set `status=stalled`

**Stability contract:** `.agentic/loop-state.json` is a stable contract from P0 onward. Any schema change must consider resume readers.

The file is overwritten (not appended) on each iteration state update and at loop exit with `termination_reason` set. It is not deleted on clean termination - the final state is the post-mortem record until the next loop invocation overwrites it. Whether `.agentic/` is gitignored is deferred to project convention.

Emit the inline breadcrumb:

```
[loop: skeptic | iteration 1/3 | open findings: -]
```

**Loop entry (repeat until termination):**

**Step 1.** Spawn `skeptic` with adversarial brief. On iteration 2+, prepend the "Prior iteration findings" block to the brief (see `skeptic-protocol.md` Section 4 - findings_log entries map directly to the preflight list format). Format re-invocations (up to 3 per `skeptic-protocol.md` Section 11) do NOT increment `iteration`.

**Telemetry emit (V1):** Bracket the Skeptic Task tool call with:
```
agentic-emit spawn_start skeptic - '{"tier":<tier>,"tool_use_id":"<toolu_id_if_known_else_null>"}'
# ... Task tool call ...
# After return, parse subagent transcript for tokens/wall_seconds:
USAGE="$(agentic-parse-subagent-usage <session_uuid> <agent_id>)"
agentic-emit spawn_complete skeptic - "$(printf '{"tier":<tier>,"agent_id":"<agent_id>","status":"ok",%s}' "${USAGE#\{}")"
```
See `METHODOLOGY.md §Events log` for the full event schema.

```
## Prior iteration findings

The following findings were raised in earlier iterations. For each:
- If the current diff shows the finding was addressed: mark it CLOSED with a one-line confirmation.
- If the current diff does NOT show the finding was addressed: re-raise it using [PREV: <id>] prefix in the finding title.
- Do not re-raise findings that were resolved - do not invent new instances of a previously-closed finding without new evidence.

[paste findings_log entries with status=open or status=addressed]
```

**Step 2.** Receive Skeptic output. Classify findings. Update `findings_log`:
- Each finding gets a short slug `id` (e.g. `"null-deref-user-service"`), `severity`, `first_raised: <iteration>`, `status: open`.
- If a finding carries `[PREV: <id>]`, set `re_raised: true` on the matching `findings_log` entry.
- Minor findings: the conductor may mark them `deferred` if the finding scope exceeds the ticket. Deferred Minors do not re-enter the loop and are documented in the PR description. Major findings may NOT be deferred without explicit human approval - escalate rather than accepting a self-declared deferral. **Loop-context override:** the base `skeptic-protocol.md` permits deferral of Majors with "a compelling documented reason"; inside the loop, this is tightened to require explicit human approval. The conductor escalates rather than accepting an Engineer's self-declared deferral.
- Overwrite `.agentic/loop-state.json` with the updated LOOP_STATE.

**Meta-divergence surfacing (in-session scan).** Before each turn boundary entering Phase 6 (loop initialization) and after returning from a Worker (after Step 5), the conductor scans `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For any event with non-empty `data.divergence.critical_missed` or `data.divergence.major_missed`, emit a META-DIVERGENCE line at the next user-facing turn boundary and append `original_task_id` to the tracker file:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Tracker append is a single line per `original_task_id`; the file is created if absent (`.agentic/.meta-divergence-surfaced`, gitignored under the `.agentic/` umbrella). Minor-only divergences are NOT surfaced inline. See `content/references/skeptic-protocol.md` Section 14 for the full specification.

**Step 3. Termination check:**
- If no Critical or Major findings: auto-close all `findings_log` entries with `status: open` or `status: addressed` (set to `closed`). Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. **Then run "Learning extraction" below, followed by "Calibration emit + meta-Skeptic sampling".** Exit loop cleanly. Proceed to Phase 6b.
- If `iteration == max_iterations` AND Critical or Major findings remain: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human (see Escalation section below). Phase 6b does NOT run.
- If any Critical finding carries `re_raised: true` (same finding re-raised after a claimed fix): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human. (This overrides the 2-re-route rule in `skeptic-protocol.md` Section 5 - see that section for the override note. One re-raise after a claimed fix is sufficient within the loop.)

**Learning extraction (clean exit only).** When Step 3 takes the clean-exit branch (sign-off granted), the conductor spawns `learning-extractor` BEFORE calibration emit and meta-Skeptic sampling. This captures durable fix-pattern learnings from the resolved `findings_log` before the loop state is cleaned up.

**Spawn:** `learning-extractor` (Tier 1, background, fire-and-forget).

**Spawn brief inputs:**
- `ticket_id`: the resolved ticket id.
- `findings_log`: the final resolved `findings_log` from `.agentic/loop-state.json` (all entries with `status: closed` or `status: addressed`).
- `merged_diff`: `git -C $REPO diff origin/$BASE_BRANCH..HEAD` (the full ticket diff).

**Failure semantics:**
- `learning-extractor` failure NEVER blocks the calibration emit, meta-Skeptic sampling, or Phase 6b. Soft-fail silently.
- The conductor does NOT wait for `learning-extractor` to return. It is fire-and-forget.
- On return (asynchronous): if `learning-extractor` returns with a valid JSON shape, the conductor stores the `learning_ids[]` for Phase 11b and prints `operator_summary` to the user at the next turn boundary. If `skipped_reason` is populated (zero-substance, etc.), the conductor notes it silently.
- If `learning-extractor` does not return before Phase 11b, `wrap-ticket` reads whatever entries exist in `.agentic/learnings.md` (may be partial or empty). No warning needed.

**Calibration emit + meta-Skeptic sampling (clean exit only).** When Step 3 takes the clean-exit branch (sign-off granted), the conductor performs the following before declaring the unit complete:

1. **Build the calibration data block.** Compute `diff_lines` from the reviewed diff (`git -C $REPO diff origin/$BASE_BRANCH..HEAD | wc -l`, or the unit-scoped equivalent for fan-out). Tally `findings_count` from the final Skeptic round's findings list (Critical / Major / Minor counts). Read `iteration` from the loop state.

2. **Emit the extended `spawn_complete` event.** Construct the merged JSON inline (no `bin/agentic-emit` flag changes) and call:

   ```bash
   USAGE_AND_CALIBRATION='{"tier":<tier>,"agent_id":"<agent_id>","status":"ok","wall_seconds":<n>,"tokens":{...},"findings_count":{"critical":<c>,"major":<m>,"minor":<n>},"diff_lines":<d>,"signed_off":true,"iteration":<i>,"meta_review":null}'
   agentic-emit spawn_complete skeptic <task_id> "$USAGE_AND_CALIBRATION"
   ```

   The conductor builds the JSON by merging the existing usage fields (from `agentic-parse-subagent-usage`) with the calibration fields. `bin/agentic-emit` is unchanged.

3. **Compute the deterministic sampling bucket.** Hash `<task_id><iteration>` into a uniform 0-99 bucket (`python3 -c 'import hashlib,sys; print(int(hashlib.sha256(sys.argv[1].encode()).hexdigest(),16) % 100)' "<task_id><iteration>"`). If `bucket < 5`, the spawn is sampled.

4. **If sampled, spawn meta-Skeptic in background (fire-and-forget).** Do NOT wait for return. The conductor declares the unit complete and proceeds to Phase 6b without blocking. Meta-Skeptic spawn brief includes:
   - The original diff
   - The original Skeptic's findings list verbatim
   - The original Skeptic's sign-off statement verbatim
   - The original adversarial brief
   - Instruction to produce a divergence report as TEXT in the return summary (Critical missed / Major missed / Minor missed / Agreement). Meta-Skeptic does NOT write to `.agentic/`.

5. **On meta-Skeptic return (asynchronous).** When meta-Skeptic eventually returns its textual divergence report, the conductor parses the report, constructs the `meta_review_complete` payload, and emits:

   ```bash
   META_DATA='{"original_task_id":"<id>","divergence":{"critical_missed":[...],"major_missed":[...],"minor_missed":[...]},"agreement":<bool>}'
   agentic-emit meta_review_complete skeptic-meta <original_task_id> "$META_DATA"
   ```

   The next in-session scan or session-start sweep will surface any Critical/Major divergence per the Meta-divergence surfacing block above.

See `content/references/skeptic-protocol.md` Section 14 for the full calibration specification.

**Step 4. Engineer fix pass.** Spawn a fresh `engineer` agent with:
- The open Critical and Major findings from `findings_log` (status=open)
- The `last_engineer_summary` from the prior iteration
- **Iter N (N >= 2) surgical-edit directive.** When `iteration >= 2`, the brief MUST include the iter N-1 Engineer output VERBATIM as input — not a summary, not a paraphrase, not "the prior engineer changed files X, Y, Z". Paste the prior return summary in full (or, when the prior output was committed code, paste the full diff or list the committed files plus their relevant excerpts). Then include this instruction verbatim: *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a Skeptic finding listed below. Each edit you make must trace to a specific finding id."* Rationale: a fresh subagent has no session context, so a brief that says "address findings and return revised outputs" causes the Engineer to regenerate from scratch — hallucinating the parts it cannot see and producing output that diverges from prior iterations. Anchoring on the prior output verbatim is the only reliable way to scope a fresh subagent to surgical fixes.
- Instruction: "Address only the findings listed below. Do not expand scope. Do not refactor, rename, or clean up code outside the finding scope. For each finding, confirm in your summary what you changed and why it addresses the finding."
- The branch name and repo path
- Instruction to run `$QUALITY_CMD` before finishing

**Telemetry emit (V1):** Bracket the Engineer Task tool call with `agentic-emit spawn_start engineer <task_id> ...` before, and `agentic-emit spawn_complete engineer <task_id> ...` after - using `agentic-parse-subagent-usage` to populate tokens/model/wall_seconds. Same pattern as the Skeptic emit in Step 1.

**Step 5.** Receive Engineer output.
- If `Status: BLOCKED`: set `termination_reason: blocked`. Overwrite `.agentic/loop-state.json`. **Tracker writeback (W4):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W4 | target: $TRACKER_STATE_BLOCKED]` Emit escalation format. Stop. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply the missing context (from codebase, session context, or by asking the human) and re-spawn the Engineer with the same findings brief and the added context. Do NOT increment `iteration`. If the conductor cannot supply the context, escalate to the human with the Engineer's stated gap.
- If `Status: DONE_WITH_CONCERNS`: proceed normally. The Engineer's stated concerns become additional context for the next Skeptic spawn (include them alongside the adversarial brief). Update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.
- Otherwise (`Status: DONE`): update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.

**Escalation format (cap_reached, convergence_failure, or blocked):**

```
LOOP STALLED - [reason: cap_reached | convergence_failure | blocked]
Iteration: [N] of 3

Open findings that could not be resolved:
[list findings_log entries with status=open]

[If convergence_failure]: The following finding was re-raised after a claimed fix:
[finding id, original raise, claimed fix, Skeptic's re-raise note]

[If blocked]: Engineer returned BLOCKED with the following description:
[Engineer's blocker description verbatim]

Recommended action: review the open findings above and either:
(a) Provide clarifying direction to the Engineer on how to address [finding id], or
(b) Accept the finding as a known limitation and confirm deferral, or
(c) Scope the fix as a follow-on ticket.
```

Note: the escalation format surfaces findings and history only. The conductor does not synthesize fix suggestions - that would undermine the convergence failure signal.

### Findings curator (loop exit)

At Phase 6 loop exit (both clean termination and stalled termination paths), spawn a findings-curator subagent. **Note:** `findings-curator` does not yet exist as a named agent; use `general-purpose` agent type (Tier 1, fire-and-forget) until the named agent is formally added.

**Brief:**
- Input: the full final-iteration Skeptic output (verbatim), the `ticket_id`, and the curated index path (`.agentic/findings.md`).
- The curator reads from the Skeptic's final return text - NOT from the `findings_log` field in `loop-state.json`.
- The curator computes `pattern_hash` per the canonicalization spec: lowercase the finding text, collapse whitespace runs (including newlines) to a single space, strip code-block fence markers (` ``` ` and `~~~`), strip leading/trailing whitespace, SHA-256 the result, take the first 16 hex chars.
- De-dup key: `(pattern_hash, ticket_id)`. Skip writing if a matching key already exists in `.agentic/findings.md`.
- The curator is the sole writer of `.agentic/findings.md` (append-only by discipline; the curator is fire-and-forget so the conductor never writes the file).

Fires exactly once per ticket per `/implement-ticket` invocation.

**Limitation:** Cross-iteration semantic-dup within the same ticket where the Skeptic re-words the finding may produce different `pattern_hash` values and result in duplicate entries. Acknowledged.

**Context budget check:** After Round 2 sign-off, if the conductor turn count is approaching the soft limit (15–20 turns), the conductor MUST recommend `/wrap` and preserve state before continuing. Do not initiate Round 3 or beyond if the hard limit (25–30 turns) is within reach. See `content/references/subagent-protocol.md` Section 13.

**Exchange log compression:** After Round 2 sign-off, if the conductor detects the exchange log is growing large (>500 tokens), apply the compressed format for subsequent rounds. Always preserve Round 1 and the most recent round in full. See `content/references/skeptic-protocol.md` Section 3 "Exchange log compression".

---

## Phase 6b: QA Gate (conditional)

**Phase 6b only runs if Phase 6 exits cleanly (Skeptic sign-off granted, `termination_reason: clean`).** If Phase 6 exits via `cap_reached`, `convergence_failure`, or `blocked` escalation, Phase 6b is skipped entirely. Running QA on a Skeptic-rejected implementation is wasteful - the Phase 6 escalation subsumes Phase 6b for that session.

**Cap independence:** Phase 6 and Phase 6b caps are independent - exhausting the Phase 6 Skeptic cap (3 fix passes) does not consume Phase 6b QA cap budget, and vice versa. Each phase gets its own 3-fix-pass budget evaluated separately.

**Trigger:** Phase 6b QA fires for Elevated units IFF all of the following hold:
1. The unit's `qa_criteria` block (from the Brief, or from the architect plan if no Brief) is present.
2. `qa_criteria.qa_skip == null`.
3. `qa_criteria.scenarios[]` is non-empty.
4. Phase 6 `termination_reason == clean`.

The Trivial path never enters Phase 6b (Trivial units bypass the entire Skeptic/QA loop per METHODOLOGY.md §Risk Classification).

**Invalid `qa_skip` enum normalization (at Phase 6b entry).** If `qa_criteria.qa_skip` is non-null and not in the 5-valid-enum set (`pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`), normalize to null and emit the operator warning verbatim:

```
WARNING: qa_skip value '<X>' is not a valid enum (one of: pure-backend-library, config-only, type-only-refactor, dep-bump-no-runtime-change, docs-only). Treating as null; QA will fire.
```

After normalization, re-evaluate the trigger conditions (with `qa_skip` now null, QA fires if scenarios are present).

**qa.md is supplemental, not gating.** Whether `.agentic/qa.md` (or legacy `.claude/qa.md`) exists, has a `## QA triggers` section, or matches the diff is NOT part of the trigger decision. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental project knowledge (dev server config, project quirks, matched trigger patterns) into its context, but the gate decision is owned by the architect's `qa_criteria`. qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`.

**Phase 6b is per-ticket and in-flow.** Phase 6b runs inside this ticket's loop, before Phase 7. The conductor MUST NOT defer Phase 6b to a final batch-end QA sweep across multiple tickets. If runtime QA cannot run for this ticket at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for THIS ticket, surfaced as `qa_blocked` with the operator's three options (provide the missing input, accept INCONCLUSIVE with `qa_unverified=true`, or abandon the ticket). See `content/sections/05-qa-gate.md` §"Per-ticket, in-flow" for the anti-pattern and `content/sections/05-qa-gate.md` §"INCONCLUSIVE classification" for the no-static-only-auto-pass rule.

**Conductor preflight before any qa-engineer spawn.** Before spawning qa-engineer for this unit, verify the project env file exists at the path the dev server will load (resolved from qa.md `env_file:` + `env_pull_command:` fields, or from project config such as a `package.json` `env:pull:<app>` script). If the env file is missing, do NOT spawn qa-engineer - surface the verbatim message defined in `content/sections/05-qa-gate.md` §"Conductor preflight before any qa-engineer spawn" with the resolved `<env_pull_command>` and wait for the operator. Spawning qa-engineer just to discover the env is missing wastes a worker turn.

**Multi-PR / multi-ticket parallel-by-worktree.** When more than one PR or unit is awaiting QA, default to spawning one qa-engineer per worktree in parallel (single message, background, each on a unique port `PORT=$((3000 + N))`). See `content/sections/05-qa-gate.md` §"Multi-PR / multi-ticket parallel-by-worktree".

- **If trigger conditions hold (QA fires) - UI-visible changes (concurrent path):** when the unit's diff is UI-visible, `qa-engineer` was already spawned IN PARALLEL with the Skeptic during Phase 6 (single message, both background). If QA passed concurrently, Phase 6b is already satisfied - skip to Phase 7. If QA failed concurrently or was deferred, proceed with the QA loop contract below. See `content/sections/05-qa-gate.md` for the full concurrent QA spec.
- **If trigger conditions hold (QA fires) - non-UI changes (sequential path):** proceed with the QA loop contract below.
- **If trigger conditions do not hold (QA skipped):** record the skip rationale (`qa_skip` value or "Trivial path") in the conductor's status update and proceed directly to Phase 7.

For full QA gate rules, see `METHODOLOGY.md §QA Gate`.

**QA loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (overwriting the Phase 6 state). **Use atomic write (tmp+rename).** Reset `last_phase=qa`, `last_phase_action=spawned`. Same write-trigger pattern as Phase 6 applies here: write at every phase transition (QA spawn, QA return, Engineer spawn, Engineer return). On clean exit set `status=complete`; on stalled exit set `status=stalled`.

```
LOOP_STATE initialized:
  phase: qa
  iteration: 1
  max_iterations: 3
  qa_failures_log: []
  last_engineer_summary: null
  termination_reason: null
```

Write as JSON to `.agentic/loop-state.json` (same stability contract as Phase 6 - see above).

Emit the inline breadcrumb:

```
[loop: qa | iteration 1/3 | open failures: -]
```

**Loop entry (repeat until termination):**

**Tracker writeback (W3)** — fires on iteration 1 only: if `TRACKER != none` AND this is the first qa-engineer spawn in Phase 6b, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_QA`, `forward_only_guard: true`. Fire-and-forget.

[phase: tracker-writeback | site: W3 | target: $TRACKER_STATE_QA | iter: 1]

**Step 1.** Spawn `qa-engineer` with ticket context, the diff, the unit's `qa_criteria` block (required input - the authoritative test plan), the `ticket_id` (for knowledge attribution), and the resolved qa.md config as supplemental context (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). The Agent tool call MUST set `isolation: "worktree"` (mandatory per METHODOLOGY.md §Delegation > Worker preamble). On iteration 2+, prepend the "Prior QA failures" section to the brief:

**Telemetry emit (V1):** Bracket the QA Task tool call with `agentic-emit spawn_start qa-engineer <task_id> ...` before and `agentic-emit spawn_complete qa-engineer <task_id> ...` after. Same pattern as Phase 6 emits.

```
## Prior QA failures

The following failures were identified and fix attempts were made in earlier iterations. For each:
- If the acceptance criterion now passes: mark it CLOSED with a one-line confirmation.
- If the criterion still fails: re-raise it using [PREV: <id>] prefix in the failure description.
- Do not re-raise failures that are confirmed fixed.

[paste qa_failures_log entries with status=open or status=addressed]
```

**Step 2.** Receive QA output. Update `qa_failures_log`:
- Each failure gets a short slug `id`, `description`, `first_raised: <iteration>`, `status: open`.
- If a failure carries `[PREV: <id>]`, set `re_raised: true` on the matching `qa_failures_log` entry.
- Overwrite `.agentic/loop-state.json` with the updated LOOP_STATE.

**Step 3. Termination check:**
- If PASS (all acceptance criteria met): auto-close all `qa_failures_log` entries. Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. Exit loop cleanly. Proceed to Phase 7.
- If `iteration == max_iterations` AND still failing: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human with the `qa_failures_log`. Phase 7 does NOT run.
- If same failure recurs unchanged after a claimed fix (`re_raised: true`): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human with convergence note.

**Step 4. Engineer fix pass.** Spawn `engineer` with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. **Iter N (N >= 2) surgical-edit directive.** When `iteration >= 2`, the brief MUST include the iter N-1 Engineer output VERBATIM as input — not a summary, not a paraphrase. Paste the prior return summary in full (or the prior diff plus committed-file excerpts when the prior output was code). Then include this instruction verbatim: *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a QA failure listed below. Each edit you make must trace to a specific failure id."* Same rationale as Phase 6: a fresh subagent without prior-iteration context regenerates from scratch and hallucinates; anchoring on the prior output verbatim is the only reliable way to scope a fresh subagent to surgical fixes. Bracket the Task call with `agentic-emit spawn_start engineer <task_id> ...` and `agentic-emit spawn_complete engineer <task_id> ...` per the Phase 6 emit pattern. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6:
- If `Status: BLOCKED`: set `termination_reason: blocked`. **Tracker writeback (W5):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W5 | target: $TRACKER_STATE_BLOCKED]` Escalate immediately. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply context and re-spawn without incrementing `iteration`. If context cannot be supplied, escalate to human.

**Step 5.** Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT (whether `Status: DONE` or `Status: DONE_WITH_CONCERNS`): update `qa_failures_log` entries the Engineer claims to have fixed to `status: addressed`. Update `last_engineer_summary`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.

---

## Phase 7: Quality gate

**Elevated path: verify from engineer return, do not re-execute.**

The Elevated-path engineer ran `$QUALITY_CMD` itself (per the `quality_gates` contract field in Phase 5) and reported `quality_gate_results: { lint, typecheck, test, raw_output }` in its return summary. Phase 7 verifies this return shape - the conductor does NOT invoke `$QUALITY_CMD` directly on this path.

**Verification:**
- If `quality_gate_results.lint == "pass" && quality_gate_results.typecheck == "pass" && quality_gate_results.test == "pass"`: mark Phase 7 complete. Proceed to Phase 8.
- If any field is `"fail"` (or the block is absent on an Elevated-path return - that is a Major Skeptic finding per the engineer.md return-shape contract): dispatch a `quality-gate-fix` engineer (same `engineer` agent, scoped brief) with the captured `raw_output`. That fix engineer runs gates and re-reports `quality_gate_results`.

**Trivial path:** preserves today's behavior. The conductor (or its solo engineer) runs `$QUALITY_CMD` directly:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
cd $REPO && $QUALITY_CMD
```

All checks must pass (typecheck, lint, tests, knip, jscpd). Do not suppress or skip checks.

**If the gate fails (either path):**

This phase runs after Phase 6 and 6b loops have already exited cleanly. A quality gate failure here does NOT continue or re-enter the Phase 6 iteration counter.

**Check `DEBUGGER_ON_FAILURE` (from Setup) to determine the failure path:**

**Trivial-path exclusion (unconditional).** A Trivial-path ticket NEVER invokes the Debugger, regardless of `debugger_on_failure`. The Debugger gate is `debugger_on_failure == true` AND path is Elevated; both conditions must hold. A Trivial-path gate failure always takes the default (no-Debugger) path below even when `debugger_on_failure: true` is set in `.agentic/config.json`.

---

**When `DEBUGGER_ON_FAILURE` is `false` OR the path is Trivial** - preserve existing behavior exactly:

1. Before spawning the Phase 7 engineer: write `.agentic/loop-state.json` with `last_phase=quality_gate`, `last_phase_action=engineer_spawned` (atomic write).
2. Spawn one `engineer` fix pass scoped to the quality gate failure output (passing the captured `raw_output` on the Elevated path). The Skeptic has already signed off on the implementation - this is a targeted quality gate fix, not a Skeptic-loop re-entry. The Agent tool call MUST set `isolation: "worktree"` on the Elevated path (mandatory per METHODOLOGY.md §Delegation > Worker preamble).
3. After the engineer returns and commits: write `last_phase=quality_gate`, `last_phase_action=engineer_returned` (atomic write).
4. Before verifying the re-run: write `last_phase=quality_gate`, `last_phase_action=rerun_pending` (atomic write). On resume from this state, the conductor waits for the fix-engineer return rather than executing `$QUALITY_CMD` itself (Elevated path) - the engineer reports `quality_gate_results` from its own re-run.
5. Verify the fix engineer's `quality_gate_results` (Elevated path) or re-run `$QUALITY_CMD` (Trivial path).
6. If it passes: set `status=complete` in loop-state.json. Proceed to Phase 8.
7. If it still fails: set `status=stalled`. Escalate to the human. Include the quality gate output from both the first run and the post-fix re-run. Do not spawn another Engineer pass.

**No unbounded loop (default path):** Phase 7 failure only ever triggers one Engineer fix pass followed by one re-run. There is no retry loop at this phase.

---

**When `DEBUGGER_ON_FAILURE` is `true` AND the path is Elevated** - interpose a Debugger diagnosis step before each engineer fix pass. Max 3 debug-fix cycles total.

For each debug-fix cycle (cycle count tracked in-context; escalate to human after 3 exhausted cycles with open gate failures):

1. Write `.agentic/loop-state.json` with `last_phase=quality_gate`, `last_phase_action=debugger_spawned` (atomic write).
2. Spawn `debugger` (read-only; no worktree isolation needed - Debugger never writes files) with:
   - The captured gate failure output (`raw_output` from the failing run)
   - The failing context (branch diff, relevant files, prior cycle summaries if any)
3. After Debugger returns: write `last_phase=quality_gate`, `last_phase_action=debugger_returned` (atomic write).
4. Write `last_phase=quality_gate`, `last_phase_action=engineer_spawned` (atomic write).
5. Spawn one `engineer` fix pass with the Debugger's Fix brief appended to the scoped brief. The Agent tool call MUST set `isolation: "worktree"` (mandatory on Elevated path per METHODOLOGY.md §Delegation > Worker preamble).
6. After the engineer returns and commits: write `last_phase=quality_gate`, `last_phase_action=engineer_returned` (atomic write).
7. Write `last_phase=quality_gate`, `last_phase_action=rerun_pending` (atomic write). The engineer re-runs gates and reports `quality_gate_results`.
8. Verify the fix engineer's `quality_gate_results`.
   - If it passes: set `status=complete` in loop-state.json. Proceed to Phase 8.
   - If it still fails AND cycle count < 3: check convergence short-circuit (below), then start the next debug-fix cycle with the new failure output.
   - If it still fails AND cycle count == 3: set `status=stalled`. **Tracker writeback (W6a):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W6a | target: $TRACKER_STATE_BLOCKED | escalation: quality-gate-cap]` Escalate to the human. Include quality gate output from every cycle run. Do not spawn another pass.

**Convergence short-circuit (test runners only).** If the quality gate is a test runner (pytest, jest, vitest, cargo test, etc.) AND the set of failing test IDs in `quality_gate_results.failures[]` is identical to the set from the immediately preceding cycle (the engineer made no progress on the failing tests), escalate immediately without consuming remaining cycles. Surface the stalled test IDs and both cycle outputs to the human. This short-circuit applies ONLY to test runners with structured `failures[]` output. For lint (eslint, ruff, etc.) and typecheck (tsc, mypy, pyright, etc.) gates, rely solely on the 3-cycle limit - do not attempt a short-circuit.

**Cross-reference:** `content/sections/05-qa-gate.md` Re-route limits section for shared escalation semantics.

---

## Phase 8: Commit and push

**Sequential path:** Stage specific files and commit as described below.

**Parallel path:** All commits were already made to sub-branches and merged in Phase 5. Phase 8 should only handle any post-merge fixup files that were not captured in the sub-branch commits. Run `git -C $REPO status --short` after the merge to check for any unstaged post-merge fixup files. If output is non-empty, stage and commit those files. If output is empty, skip the stage-and-commit step and proceed directly to push.

**Only run the following commit block if `status --short` was non-empty (parallel path) or on the sequential path:**

Stage specific files - never `git add -A` or `git add .`:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO add [specific files]
git -C $REPO commit -m "$(cat <<'EOF'
type(scope): short imperative description

More detail on what changed and why if needed.
Closes [TICKET_PREFIX]-NNN

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
git -C $REPO push -u origin [BRANCH_NAME]
```

Commit message types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.

---

## Phase 9: Open the PR

Compose the `[TRACKER_REFERENCE_BLOCK]` based on the resolved `TRACKER`, then run the `gh pr create` command with that block included in the body.

#### If TRACKER is `linear`

```
## Linear
Closes [[TICKET_PREFIX]-NNN](https://linear.app/[LINEAR_WORKSPACE]/issue/[TICKET_PREFIX]-NNN)
```

#### If TRACKER is `jira`

```
## Jira
Closes [[TICKET_PREFIX]-NNN]([JIRA_BASE_URL]/browse/[TICKET_PREFIX]-NNN)
```

#### If TRACKER is `none`

Omit the tracker reference block entirely. The PR body will have only Summary and Test plan, and the PR title should omit the `[TICKET_PREFIX]-NNN:` prefix.

---

Open as draft PR. GitHub does not request reviewers on a draft; reviewers are assigned in Phase 10b after CI passes.

Run:

```bash
gh pr create \
  --repo [GH_REPO] \
  --base [BASE_BRANCH] \
  --head [BRANCH_NAME] \
  --draft \
  --title "[TICKET_PREFIX]-NNN: [ticket title]" \
  --body "$(cat <<'EOF'
## Summary
- [bullet 1]
- [bullet 2]

[TRACKER_REFERENCE_BLOCK]

## Test plan
- [ ] [step 1]
- [ ] [step 2]
EOF
)"
```

For `TRACKER=none`, omit the tracker reference block line and drop the `[TICKET_PREFIX]-NNN:` prefix from `--title`.

Capture the PR number from the URL printed by `gh pr create`.

---

## Phase 10: Wait for CI checks

Poll all CI check runs until completion. The conductor uses `gh pr checks` to detect when every required check has finished. Outcomes route to one of three sub-phases.

**Preserved fast-exit:** the `preview_blocked: true` qa.md flag continues to suppress preview-URL polling specifically. It does NOT suppress the CI-check poll - those are distinct concerns. If `preview_blocked` is set, the Test URL line in the tracker comment (Phase 11) is "Preview deploy blocked - verify with local QA."

**Poll loop:**

```bash
PR_NUMBER=<captured-from-Phase-9>
TIMEOUT_POLLS=60
POLL_INTERVAL=30

for i in $(seq 1 $TIMEOUT_POLLS); do
  STATUS=$(gh pr checks "$PR_NUMBER" --repo "$GH_REPO" --json name,status,conclusion 2>/dev/null)
  if [ -z "$STATUS" ]; then
    # No checks configured - treat as passed (project has no CI)
    echo "[phase: ci-wait | no-checks-configured | status: passed-by-default]"
    break
  fi
  PENDING=$(echo "$STATUS" | jq -r '[.[] | select(.status != "COMPLETED")] | length')
  if [ "$PENDING" -eq 0 ]; then
    echo "[phase: ci-wait | all-checks-complete]"
    break
  fi
  echo "Waiting for CI checks... ($i/$TIMEOUT_POLLS, $PENDING pending)"
  sleep $POLL_INTERVAL
done

# After the loop, check final state
FAILED=$(gh pr checks "$PR_NUMBER" --repo "$GH_REPO" --json conclusion 2>/dev/null | jq -r '[.[] | select(.conclusion == "FAILURE" or .conclusion == "TIMED_OUT")] | length')
```

**Outcome routing:**
- `STATUS empty` (no checks configured): emit `[phase: ci-wait | result: passed-by-default | no-checks]`. Proceed to Phase 10b.
- `FAILED == 0` after all complete: emit `[phase: ci-wait | result: passed]`. Proceed to Phase 10b.
- `FAILED > 0`: emit `[phase: ci-wait | result: failed | failing-checks: <names>]`. Enter Phase 10a.
- Loop hit `TIMEOUT_POLLS` without all-complete: emit `[phase: ci-wait | result: timeout]`. Write `last_phase: ci_wait, last_phase_action: timeout` to `.agentic/loop-state.json`. Surface to human and STOP (do NOT auto-fix, do NOT proceed). Human decides whether to extend the wait or escalate.

---

## Phase 10a: CI fix loop (conditional on Phase 10 result: failed)

Mirrors Phase 7's quality-gate retry loop, but targets CI failures detected post-push.

**Cap:** 3 cycles. Convergence short-circuit on identical failing check-name set across two consecutive cycles.

**Per cycle:**

1. **Capture failure log:**
   ```bash
   RUN_ID=$(gh run list --pr "$PR_NUMBER" --repo "$GH_REPO" --status failure --limit 1 --json databaseId 2>/dev/null | jq -r '.[0].databaseId')
   FAILURE_LOG=$(gh run view "$RUN_ID" --repo "$GH_REPO" --log-failed 2>/dev/null | tail -300)
   ```

   The `tail -300` truncation caps log size to keep engineer context bounded. The last 300 lines of the failed run almost always contain the actual failure - earlier lines are setup/install noise. If the truncated log misses the failure (extremely rare), the next cycle will retry with the next failure run's log.

2. **Write loop-state:** `last_phase: ci_loop, last_phase_action: fix_engineer_spawned, last_phase_iteration: N`.

3. **Spawn engineer** (worktree-isolated, Elevated path). Brief includes:
   - The failure log (`$FAILURE_LOG`, last-300 truncated)
   - Prior cycle summaries (iter N >= 2 surgical-edit directive: paste iter N-1 verbatim, instruction "APPLY SURGICAL EDITS, do not regenerate")
   - Instruction to commit and push to the same branch

4. **After engineer returns:** Write `last_phase: ci_loop, last_phase_action: fix_engineer_returned, last_phase_iteration: N` to loop-state. Re-enter Phase 10 poll. Write `last_phase: ci_loop, last_phase_action: ci_poll_pending, last_phase_iteration: N` while polling.

5. **Convergence short-circuit:** If failing check-name set in cycle N equals cycle N-1 (engineer made no progress), escalate immediately without consuming remaining cycles.

6. **Cap exceeded (3 cycles without all-pass):**
   - Write `last_phase: ci_loop, last_phase_action: cap_exceeded` to loop-state.
   - Print summary of failing checks + each cycle's outcome.
   - **Tracker writeback (W6b):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W6b | target: $TRACKER_STATE_BLOCKED | escalation: ci-fix-loop-cap]`
   - STOP. Human investigates.

Emit breadcrumb: `[phase: ci-fix-loop | iteration N/3 | failing: <check-names>]`

---

## Phase 10b: Mark ready + assign reviewers (conditional on Phase 10 result: passed)

**Mark ready-for-review:**

```bash
gh pr ready "$PR_NUMBER" --repo "$GH_REPO" 2>/dev/null
```

Soft-fail: if the call errors, log and continue. The PR remaining in draft state is recoverable (operator can mark ready manually).

**Reviewer assignment (resolution order; first match wins):**

1. **CODEOWNERS path** - check 3 standard locations:
   ```bash
   if [ -f .github/CODEOWNERS ] || [ -f docs/CODEOWNERS ] || [ -f CODEOWNERS ]; then
     echo "CODEOWNERS detected - GitHub will auto-route review requests."
   ```
   (Note: this checks repo root and `.github/`/`docs/` subdirectories - the standard GitHub CODEOWNERS locations. Subdirectory CODEOWNERS in monorepo tracks - e.g. `helios/.github/CODEOWNERS` - are out of scope for v1; root-level CODEOWNERS is sufficient for the typical project.)

2. **AGENTS.md `## PR Workflow` `Reviewers:` fallback** - if no CODEOWNERS file found AND `PR_WORKFLOW_REVIEWERS` (resolved in Setup) is non-empty:
   ```bash
   else
     gh pr edit "$PR_NUMBER" --repo "$GH_REPO" --add-reviewer "$PR_WORKFLOW_REVIEWERS" 2>/dev/null
   ```

3. **Neither configured** - emit one-line operator notice:
   ```
   No reviewers assigned: no CODEOWNERS file found and no Reviewers: in AGENTS.md ## PR Workflow.
   ```

Emit breadcrumb: `[phase: pr-ready | reviewers: auto|assigned|none]`

---

## Phase 11: Post to tracker

Once you have the Test URL (or the PR link as fallback):

#### If TRACKER is `linear` or `jira`

Spawn a tracker-writeback subagent (Tier 1, `general-purpose` agent type). The conductor does NOT call `mcp__linear__*` or `mcp__mcp-atlassian__*` tools directly on this path - all MCP traffic for tracker write-back is delegated.

**Spawn brief:**

> Post a tracker comment with the PR URL and Test URL, and (where configured) transition the ticket status and update the assignee.
>
> **Inputs (resolved by conductor and passed in):**
> - `TRACKER`: `linear` or `jira`
> - `TICKET_ID`: e.g. `[TICKET_PREFIX]-NNN`
> - `PR_URL`: `https://github.com/[GH_REPO]/pull/[PR_NUMBER]`
> - `TEST_URL`: extracted from CI (or the literal string `pending — see PR` if Phase 10 timed out)
> - `qa_summary`: 1-2 sentences on what specifically to test and any known limitations from the Skeptic review
> - `target_state`: `$TRACKER_STATE_QA` (resolved in Setup; defaults to `"Testing"` for Linear, `"QA"` for Jira)
> - `forward_only_guard`: `true`
> - For Linear: `LINEAR_QA_ASSIGNEE_ID` (optional - omit if not configured)
> - For Jira: `JIRA_QA_TRANSITION` (optional - omit if not configured); `JIRA_QA_ASSIGNEE_ACCOUNT_ID` (optional - omit if not configured)
>
> For the full brief shape governing this subagent (state pre-read, forward-only guard semantics, skip conditions, soft-fail), see the `## Tracker Writeback Helper` block above.
>
> **Behavior:**
> - **Linear:** Apply forward-only guard (pre-read current state, skip if already at or past `target_state` rank). Call `mcp__linear__save_issue` with `state: $TRACKER_STATE_QA` and `assigneeId` only when configured. Then call `mcp__linear__save_comment` with the comment body below.
> - **Jira:** Apply forward-only guard (pre-read current status via `mcp__mcp-atlassian__jira_get_issue`, skip if already at or past `target_state`). Call `mcp__mcp-atlassian__jira_get_transitions` to discover available transitions, then `mcp__mcp-atlassian__jira_transition_issue` to `$TRACKER_STATE_QA` (only if `JIRA_QA_TRANSITION` configured AND the name matches an available transition - log and skip on miss). Update assignee via `mcp__mcp-atlassian__jira_update_issue` (only if configured). Post the comment via `mcp__mcp-atlassian__jira_add_comment`. Failures on transition or assignee are logged and the spawn proceeds to the comment - the comment is higher value than the status change.
>
> **Comment body template:**
>
> ```
> Implementation complete. Ready for QA.
>
> Test URL: [TEST_URL]
> PR: [PR_URL]
>
> [qa_summary]
> ```
>
> (Linear comment may use markdown bold for `Test URL:` and `PR:` labels; Jira comment is plain text.)
>
> **Returns:** `{ transitioned: <bool>, assigned: <bool>, comment_posted: <bool>, status: "ok" | "partial" | "failed", errors: [<string>] }`. Partial success (e.g. comment posted but transition skipped) returns `status: "partial"` with the reason in `errors`.

#### If TRACKER is `none`

Skip Phase 11 entirely. Print: "No tracker configured — skipping ticket update. PR is open at: https://github.com/[GH_REPO]/pull/[PR_NUMBER]"

(This sub-section is conductor-direct - it is a print, not delegable.)

---

## Phase 11b: Wrap learnings (per-ticket capture)

**Trigger:** every PR opened, subject to skip conditions below. Fires AFTER Phase 11 completes and BEFORE Phase 12 cleanup. Phase 11b reads `findings_log` from `.agentic/loop-state.json` BEFORE Phase 12 clears it - explicit ordering. The findings-curator at Phase 6 exit reads `findings_log` but does NOT clear it; Phase 12 is the only clearer.

**Skip conditions:**
- Phase 9 was skipped (no PR was opened): skip Phase 11b entirely.
- The current ticket was Trivial: skip with `skipped_reason: "trivial-no-brief"`. Do NOT spawn `wrap-ticket`.

**Spawn:** `wrap-ticket` (Tier 1, foreground, blocking, 60-second timeout).

**Lock acquisition:** before spawning, attempt to acquire `.agentic/wrap.lock` (atomic `mkdir`). The lock is shared with `/wrap` to prevent concurrent writes to MEMORY.md, decisions.md, and `.agentic/context.md`.

- **If the lock is held by another session** (e.g., `/wrap` is running concurrently in another session): skip Phase 11b with the operator note: `"Phase 11b skipped: /wrap is running in another session."` Do NOT spawn `wrap-ticket`. Do NOT release the lock (this session never acquired it).
- **If the lock is acquired:** spawn `wrap-ticket` with the inputs below. The conductor releases the lock on every exit path (success, timeout, soft-fail) before proceeding to Phase 12.

**`wrap-ticket` spawn brief inputs:**

- `ticket_id`: the resolved ticket id.
- `ticket_title`: the ticket title.
- `ticket_description`: the full ticket description.
- `architect_plan_path`: absolute path to the architect's plan output (or in-context if no path).
- `brief_path`: absolute path to the Brief (or "n/a" if no Brief).
- `findings_log`: read from `.agentic/loop-state.json` `loop_state.findings_log` BEFORE Phase 12 clears the file.
- `qa_md_diff`: the diff between `.agentic/qa.md.snapshot-<ticket_id>` (created at Phase 0b for Elevated tickets) and the current working-tree `.agentic/qa.md`. Empty if no snapshot exists or qa.md is unchanged.
- `merged_diff`: `git -C $REPO diff origin/$BASE_BRANCH..HEAD` (the full ticket diff).
- `pr_url`: the PR URL captured at Phase 9.
- `conversation_summary`: a brief recap of the conductor's session covering this ticket.
- `learnings_extracted`: the `learning_ids[]` array from the `learning-extractor` return at Phase 6 clean exit (or `[]` if learning extraction was skipped/soft-failed).

**Failure semantics:**

- `wrap-ticket` failure NEVER blocks Phase 12 cleanup or PR completion. Soft-fail with a warning line printed to the operator.
- If `wrap-ticket` returns within 60s with a valid JSON shape: conductor parses the JSON and prints `operator_summary` to the user. If `size_advisory` is non-null, print it as a separate line.
- If `wrap-ticket` returns within 60s but the output is not parseable as JSON: conductor warns the operator (`"Phase 11b: wrap-ticket return was not valid JSON; proceeding without learnings capture."`) and proceeds.
- If `wrap-ticket` exceeds the 60s timeout: conductor warns the operator (`"Phase 11b: wrap-ticket exceeded 60s timeout; proceeding without learnings capture."`) and proceeds. Lock is released before timeout.
- If `wrap-ticket` returns with `skipped_reason` populated (zero-substance, wrap-lock-contention, etc.): conductor prints the `operator_summary` and proceeds without warning.

Lock release: `rm -rf .agentic/wrap.lock` runs unconditionally on every Phase 11b exit path before advancing to Phase 12.

Emit breadcrumb: `[phase: wrap-ticket | ticket=<ticket_id> | status=<ok|skipped|failed>]`

---

## Phase 12: Loop state cleanup

After the PR is open (Phase 9 complete) and Phase 11b has run (or been skipped), set `.agentic/loop-state.json` to `status: "complete"` using atomic write (tmp+rename), or delete the file. This prevents the next `/implement-ticket` invocation on this project from presenting a stale completed loop as a resume candidate. The write applies Contract A (per-write `session_id` gate); abort with the verbatim warning on mismatch.

If the file does not exist (it was never written, e.g. loop never started), skip silently.

**`findings_log` clearing.** Phase 12 is the ONLY clearer of `findings_log`. The findings-curator at Phase 6 exit reads `findings_log` from `.agentic/loop-state.json` but does NOT clear it. Phase 11b's `wrap-ticket` reads `findings_log` BEFORE this Phase 12 cleanup. Setting `status: "complete"` (or deleting the file) is the moment `findings_log` is dropped.

**qa.md snapshot cleanup.** Remove `.agentic/qa.md.snapshot-<ticket_id>` if it exists (it was created at Phase 0b for Elevated tickets). Best-effort silent-fail; if the file is absent or removal fails, do not block Phase 12 completion.

```bash
rm -f .agentic/qa.md.snapshot-<ticket_id> 2>/dev/null || true
```

**Conditional auto-merge** (only when `auto_merge_on_ci_green: true` in `.agentic/config.json`):

```bash
if [ "$AUTO_MERGE_ON_CI_GREEN" = "true" ]; then
  PR_STATE=$(gh pr view "$PR_NUMBER" --repo "$GH_REPO" --json isDraft,mergeable,reviewDecision 2>/dev/null)
  IS_DRAFT=$(echo "$PR_STATE" | jq -r '.isDraft')
  MERGEABLE=$(echo "$PR_STATE" | jq -r '.mergeable')
  REVIEW_DECISION=$(echo "$PR_STATE" | jq -r '.reviewDecision // "NONE"')

  if [ "$IS_DRAFT" = "false" ] && [ "$MERGEABLE" = "MERGEABLE" ] && [ "$REVIEW_DECISION" != "CHANGES_REQUESTED" ]; then
    if gh pr merge "$PR_NUMBER" --repo "$GH_REPO" --squash --delete-branch 2>/dev/null; then
      echo "[phase: auto-merged | pr=$PR_NUMBER]"
      # Tracker writeback (W7): if TRACKER != none, invoke Tracker Writeback Helper
      # with target_state: $TRACKER_STATE_DONE, forward_only_guard: true.
      # Fire-and-forget. Fires ONLY when merge succeeded (this branch).
      # [phase: tracker-writeback | site: W7 | target: $TRACKER_STATE_DONE | trigger: auto-merge-success]
    else
      echo "[phase: auto-merge-failed | pr=$PR_NUMBER]"
    fi
  else
    echo "[phase: auto-merge-skipped | isDraft=$IS_DRAFT mergeable=$MERGEABLE reviewDecision=$REVIEW_DECISION]"
  fi
else
  echo "PR #$PR_NUMBER is open and ready for review: https://github.com/$GH_REPO/pull/$PR_NUMBER"
  echo "Note: If auto-merge is off (default), run \`/ticket-status-sync TICKET_ID\` after manual merge to push the Done transition to the tracker."
fi
```

The `Note:` line is a forward-reference to PR 4's `/ticket-status-sync` command. In PR 1 it is just a hint; PR 4 lands the actual command.

**Tracker writeback (W7):** fires only if `gh pr merge` exits 0 (inside the `AUTO_MERGE_ON_CI_GREEN` gate and the isDraft/mergeable/reviewDecision inner check). If `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_DONE`, `forward_only_guard: true`. Fire-and-forget.

[phase: tracker-writeback | site: W7 | target: $TRACKER_STATE_DONE | trigger: auto-merge-success]

Note: W7 fires ONLY on the auto-merge success path (`AUTO_MERGE_ON_CI_GREEN=true` AND merge succeeds). On the default human-merge path (`AUTO_MERGE_ON_CI_GREEN=false`), W7 does NOT fire here. The `Note:` above mentions `/ticket-status-sync` as the post-merge reconciliation path for the human-merge case (PR 4 ships that command).

---

## Phase 12a: Handoff evaluation (batch only)

**Trigger:** `.agentic/batch-state.json` exists (set by Phase 0a when Phase 0 produced ≥ 2 entries during this session). Skip when batch-state.json is absent.

After Phase 12 completes for a ticket and BEFORE the conductor advances to the next ticket in the batch, evaluate the three handoff triggers below. If any one fires, gracefully pause the batch and exit cleanly; if none fire, continue to the next ticket.

**Triggers (exactly THREE; any one fires):**

1. **Stale-pace pattern.** The last 2 completed tickets each took more than 2× the median wallclock of completed tickets in this batch. Requires ≥5 completed tickets to be meaningful (below this threshold, sample size is too small to be a reliable signal). `pause_reason: "stale_pace"`.
2. **Operator literal "pause the batch".** Case-insensitive substring match against the most recent operator message. `pause_reason: "operator_pause"`.

   **Invariant (binding).** The conductor MUST NOT write `pause_reason: "operator_pause"` to `batch-state.json` unless the operator's most recent message contains the literal substring `pause the batch` (case-insensitive). Conductor self-doubt about remaining wallclock, context pressure, perceived pace, or "feeling like the operator might want a break" is NOT a valid `operator_pause` trigger. The correct conductor behavior in those subjective cases is to spawn the next ticket and let `wallclock_cap` (trigger 3) fire mechanically if the cap is actually hit. A conductor that paraphrases the operator, infers intent from "I'm tired" / "let's stop soon" / "we're running long", or pauses preemptively to avoid a future cap hit is violating this invariant - the operator's literal words are the authoritative trigger. If an operator phrases a pause request differently (e.g. "stop after this one"), the correct response is to surface a one-line confirmation (`Proceeding to pause the batch after the current ticket - confirm with 'pause the batch' or override with 'continue'.`) and continue executing until the literal substring arrives.
3. **Wallclock cap.** `now - wallclock_started_at >= wallclock_cap_min` (default 90 min unless `AGENTIC_BATCH_MAX_WALLCLOCK_MIN` env override). `wallclock_started_at` is preserved across resume, so the cap is per-batch lifetime, not per-session. `pause_reason: "wallclock_cap"`.

(Context-pressure auto-detection is explicitly NOT a trigger; the conductor cannot read its own context %. Operators use trigger 2 if context pressure is observed.)

**On trigger:** apply Contract A + Contract B and write `batch-state.json` with:
- `status: "paused"`
- `paused_at: now`
- `pause_reason: <trigger>`
- `last_summary` populated for the ticket just completed
- `replan_log[]` preserved (Contract B)

Print the structured remaining-tickets summary:

```
BATCH PAUSED — pause_reason: <trigger>
Completed: <k>/<N> tickets
  ✓ <ticket_id> (PR #<pr_number>)
  ...
Remaining: <N-k> tickets
  · <ticket_id> (depends_on: <list>, status: <status>)
  ...
Resume: /implement-ticket from this directory
```

Exit cleanly. Do NOT advance to the next ticket. Emit breadcrumb: `[phase: batch-paused | reason=<trigger>]`.

**On no trigger:** continue to the next ticket in the batch.

> Note: `paused_at` and `pause_reason` are written by Phase 12a on graceful handoff. `interrupted_at` and `interrupt_reason` are written by the Stop hook on session-exit crash. These are two distinct paths; `last_summary` is only populated on graceful pause (the Stop hook cannot synthesize it).
