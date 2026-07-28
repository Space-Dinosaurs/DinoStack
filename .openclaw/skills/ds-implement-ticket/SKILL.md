---
name: ds-implement-ticket
description: "Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted bac"
user-invocable: true
---
# Implement Ticket

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

> **Context-size preflight (run immediately after Activation, before any other step):** Assess the current session's context load against the soft and hard limits defined in `content/references/subagent-protocol.md` Section 13.
>
> **Hard limit check (Section 13.2) - checked first:** If the session has reached the hard limit, Section 13.2 governs absolutely - there is no `yes`/proceed override at or above the hard limit. Do the following in this order: (1) print the hard-limit block below verbatim, (2) invoke `/ds-wrap` automatically to preserve state via `context.md` and `MEMORY.md` updates (or instruct the operator to run `/ds-wrap` if auto-invoke is unavailable in the current harness), (3) exit - refusing further implementation work, Skeptic rounds, and subagent spawns for the remainder of this session. Do not print the soft-limit warning block below or the "Proceed anyway?" prompt.
>
> **Hard-limit block (print verbatim - this is a plain print, not an `AskUserQuestion` tool call, and does not wait for operator confirmation):**
> ```
> Context-size hard limit reached: this session has reached the conductor
>    context hard limit (Section 13.2 of the Subagent Protocol). The hard
>    limit is absolute - there is no override, and further implementation
>    work, Skeptic rounds, and subagent spawns are refused for the rest of
>    this session.
>
>    Why: the hard limit exists to protect output quality. A conductor
>    operating past this point risks missing details from earlier turns,
>    re-introducing bugs already fixed, and producing stale crash-recovery
>    state. A fresh session is required to continue - this is not optional.
>
>    Next steps:
>      1. /ds-wrap          - save session state and generate a hand-off summary
>      2. Start a new session (on Claude Code, /clear also works)
>      3. /ds-implement-ticket <your input>   - in the fresh session
> ```
>
> **Danger signals below the hard limit (any one triggers the soft-limit warning, per Section 13.1):**
> - Session turn count at or above the soft limit with substantive tool-call results still in context.
> - Any prior subagent result block, of substantive size, is visible and was produced in this same session before `/ds-implement-ticket` was invoked.
>
> **If a danger signal is detected below the hard limit, print verbatim (this is a plain print-and-wait for the operator's next message, not an `AskUserQuestion` tool call):**
> ```
> Context-size warning: your current session carries significant prior context
>    (a long turn history and/or one or more prior subagent result blocks still
>    visible). Running /ds-implement-ticket now risks exhausting your token budget
>    before the architect-plan-review phase completes.
>
>    Recommended safe pattern:
>      1. /ds-wrap          - save session state and generate a hand-off summary
>      2. Start a new session (on Claude Code, /clear also works)
>      3. /ds-implement-ticket <your input>   - in the fresh session
>
>    Proceed anyway? (yes / no)
> ```
> On `no`: exit immediately. On `yes`: continue with a one-line note: `Context-size warning acknowledged - proceeding in large session.` This `yes` override is valid only below the hard limit - it never applies once the hard limit is reached (see Hard limit check above).
>
> **If no danger signals are present:** continue silently (no output).

Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted back to the ticket.

## Invocation

`/ds-implement-ticket <input>`

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

**Open-goal / wallclock-cap parameters (optional, trailing key=value tokens).** `<input>` may be followed by any of `goal_mode=open_goal`, `goal_condition="<string>"`, `max_iterations=<int>`, `max_wallclock_min=<int>`, `dry_run=true`. Extracted by a trailing-token scan (`\w+=(\S+|"[^"]*")`) BEFORE Phase 0 classification runs; matched tokens are stripped so ticket-reference classification is unaffected. `dry_run` is meaningful ONLY when `goal_mode=open_goal` is also present - on any other invocation shape it is parsed and explicitly ignored (no effect, no error).

---

## Conductor responsibilities (irreducible)

The conductor delegates implementation work aggressively to specialist subagents but retains a fixed set of responsibilities that are never delegated. This section enumerates at minimum:

- **Risk classification.** Must precede any spawn (per METHODOLOGY.md §Risk Classification).
- **Promotion-gate check + Brief/Plan authoring.** Comprehension artifacts that the conductor must produce itself (per METHODOLOGY.md §Planning Artifacts).
- **Stop-and-ask decisions.** The user-facing surface; subagents do not interact with the user.
- **All `.agentic/*.json[l]` writes.** Sole-writer rule for the per-ticket keyed `loop-state-$LOOP_KEY.json` (and the legacy unkeyed `loop-state.json` it supersedes), `tasks.jsonl`, and any other state file under `.agentic/`.
- **Re-route limit + convergence-failure tracking.** Conductor must hold the full loop history across iterations.
- **Status updates and breadcrumbs to user.** All `[phase: ...]` and `[loop: ...]` emissions originate from the conductor.
- **Dispatch logic.** Which agent, when, with what brief.
- **Summary synthesis for downstream spawn briefs.** PR body, tracker comment, findings input - the conductor extracts and reformats subagent outputs for downstream consumers.
- **`BASE_BRANCH` resolution and `AGENTS.md` config parsing.** Setup phase work.
- **`gh pr create` in Phase 9.** PR opener stays in the conductor; the synthesis output is consumed inline by the next phase and does not benefit from isolation in a separate spawn.
- **CI Test URL polling in Phase 10.**
- **Branch/worktree creation on the Phase 5 parallel fan-out path.** The Elevated single-engineer path AND the Trivial single-engineer path both delegate branch/worktree creation to the (worktree-isolated) engineer (see Phase 4). Only fan-out worktree creation remains conductor-orchestrated.

This list is not exhaustive — any operation listed elsewhere as conductor-direct is also irreducible.

---

## Batch state contracts (binding)

These contracts govern every conductor write to `.agentic/batch-state.json` and `.agentic/loop-state-$LOOP_KEY.json`. Phases that write to either file (Phase 0a, Phase 0a-pre, Phase 6/6b, Phase 7, Phase 10, Phase 10a, Phase 12, Phase 12a) MUST apply the contracts below.

**Contract A — Per-write `session_id` gate (applies to BOTH `batch-state.json` and the keyed `loop-state-$LOOP_KEY.json`).**

Before every conductor write to either file:

1. Read the current on-disk file (if present).
2. If the file exists, its `session_id` field is a non-empty string AND does not match the current session, AND its liveness-timestamp field (`last_updated` for `loop-state-$LOOP_KEY.json`, `updated_at` for `batch-state.json` - same per-file mapping as step 4 below) is within the last 10 minutes: ABORT the write - EXCEPT that on `batch-state.json` ONLY, this condition additionally requires `status` to be `active`; a non-`active` `batch-state.json` (`interrupted`, `paused`, `complete`, or `stalled`) never aborts a write under this step. This per-file asymmetry is deliberate, not an oversight:
   - **`batch-state.json` carries the `status=active` precondition** because `markInterrupted` stamps `updated_at=now` on it at session exit (`touchTimestampOnTerminal: true` in `hooks/lib/state-mark.js`), so a dead session's file looks fresh for a full 10 minutes; and every one of its non-`active` states follows a path that exits the session - e.g. the pause path says `Exit cleanly. Do NOT advance to the next ticket.` Without this precondition, the first write of an approved resume of an interrupted or paused batch would abort against the dead session's still-fresh terminal-mark timestamp, with no live session left to kill.
   - **`loop-state-$LOOP_KEY.json` does NOT carry the precondition**, for two reasons: (a) it is already shielded from the stale-freshness hazard by `touchTimestampOnTerminal: false` (see "Why the keyed loop-state file's `last_updated` is never touched by the terminal mark" below - the two facts are linked); and (b) a live session CAN hold a non-`active` keyed loop-state file - the Phase 7 stall path sets `status=stalled` and then routes through "Batch-mode escalation routing (mark-blocked-and-continue)", so the conductor stays alive and continues to the next ticket rather than exiting. Adding the precondition here would let a foreign session's write clobber a live session's `loop-state-$LOOP_KEY.json` in that window. **Per-ticket keying does not make this gate redundant:** it removes DIFFERENT-ticket contention (those sessions now write different files), but two sessions on the SAME ticket derive the same `LOOP_KEY` and therefore still meet here, which is exactly the case the gate must keep catching.

   Print the verbatim warning, substituting `<field>` with the file's own liveness-timestamp field name:
   ```
   WARNING: write to .agentic/<file> aborted - another session (session_id=<X>, <field>=<Y>) appears to own this file. Identify the live session via .agentic/*.json's liveness-timestamp field. Resolve manually (kill the other session, or remove the file) and retry.
   ```
3. If the file exists and its `session_id` is null/missing/empty (legacy state from a prior version): treat as mismatch — force-takeover-eligible. Operator may resolve via the Phase 0a-pre force-takeover prompt or by manually removing the file. The same WARNING above is printed.

   **Self-ownership carve-out.** Step 3 applies only when the CURRENT session has a non-empty `session_id` of its own. When the current session's `session_id` is itself null - a harness that has declared it cannot produce an id in the same namespace as its session-exit hook payload - a null/missing/empty `session_id` on disk is **self-owned**: proceed with the write, print nothing, and leave the field null. Rationale: two nulls on such a harness are indistinguishable by construction, so treating them as a mismatch produces a guaranteed false warning on every transition rather than catching a real collision.
4. Otherwise (no file, matching `session_id`, or stale > 10 min): proceed with the write. Set `session_id` to the current session's id and update the file's liveness-timestamp field in the new payload - the two files use different field names for this same timestamp: `last_updated` for `loop-state-$LOOP_KEY.json`, `updated_at` for `batch-state.json`.

Both readers and writers tolerate absence of `session_id` for back-compat with state files written by prior versions; absence is treated as mismatch for write-gating - unless the current session's own `session_id` is also null, per the self-ownership carve-out above - but not for read-only resume prompts (those follow the Phase 0a-pre decision table). This is now 5-way logic once the self-ownership carve-out is counted alongside steps 1-4 (see the two prose sites below that still say "4-way" - corrected in this pass).

The hook-side writes (`hooks/lib/state-mark.js`, used by `hooks/stop-context.js` and `hooks/session-end-wrap.js`) apply an intentionally ASYMMETRIC ownership predicate that differs from this conductor-side Contract A: the per-turn liveness refresh requires a POSITIVE `session_id` match (absent/null/empty/differing all skip), while the terminal interrupted-mark proceeds unless the on-disk `session_id` is a POSITIVELY differing non-empty string (absent/null/empty proceeds). See `hooks/lib/state-mark.js`'s module manifest for the full rationale - a false-positive liveness refresh on an unowned file is much worse than a redundant true interrupted-mark.

**Contract B — `replan_log[]` read-merge-write preservation (applies to `batch-state.json`).**

Every conductor write to `batch-state.json` MUST:

1. Read the current on-disk file first.
2. Take the existing `replan_log[]` from disk and merge any new entries authored in-memory by the current conductor turn (append-only; never reorder; never drop entries).
3. Write the merged array back along with the rest of the payload.

This preserves the audit log across overlapping writes and across resume migrations.

**Contract C — One batch per project root.**

When Phase 0a is initializing a new `batch-state.json` (invocation where Phase 0 produced ≥ 2 entries, OR Phase 0a-open-goal is performing a Fresh init (`goal_mode=open_goal`), OR the Phase 0a-pre single-ticket-capped carve-out is performing its create (`max_wallclock_min` alone, no `goal_mode`)) and the file already exists with `status=active`, a different `session_id`, and `updated_at` within the last 10 minutes: REFUSE the new batch with the verbatim message:

```
Another batch session is active for this project root (session_id=<X>, updated_at=<Y>). Wait for it to finish, kill it and re-invoke, or remove .agentic/batch-state.json and re-invoke.
```

Concurrent batches per project root are not supported. Operators wanting parallel batches use separate worktrees with separate `.agentic/`.

**N=1 foreign-batch warning.** If Phase 0 produced exactly 1 entry (single-ticket) AND `.agentic/batch-state.json` exists with `status=active` + different `session_id` + `updated_at` within the last 10 minutes: print the verbatim warning:

```
NOTE: a batch session is active for this project root (session_id=<X>, updated_at=<Y>). Single-ticket invocations are not refused; per-ticket loop state is keyed separately so bookkeeping will not collide. Identify the live session via .agentic/batch-state.json updated_at. Continue? (yes/no)
```

On `no`: abort. On `yes`: proceed with the single-ticket flow. This is the only single-entry interaction with `batch-state.json`.

**Contract D — Stop hook / SessionEnd hook mirror.**

The Claude Code Stop hook (`hooks/stop-context.js`) fires once per TURN, not once per session. It no longer marks the loop-state / `batch-state.json` files interrupted on every turn. Instead it is wired with `--cadence=turn`, which dispatches to `hooks/lib/state-mark.js`'s `refreshLiveness(cwd, sessionId)`: a per-turn liveness-only touch that updates `last_updated` (every loop-state candidate) or `updated_at` (`batch-state.json`) ONLY when the file is `status=active` AND its on-disk `session_id` is a non-empty string EQUAL to the current session's id (POSITIVE match required - absent/null/empty/differing all skip). It never sets `status=interrupted`.

The terminal interrupted-mark now lives on `hooks/session-end-wrap.js` (the SessionEnd hook, which fires once per session). On a terminal reason (`clear`, `logout`, `prompt_input_exit`, `bypass_permissions_disabled`, `other` - `resume` is excluded), it calls `hooks/lib/state-mark.js`'s `markInterrupted(cwd, sessionId)`, which mirrors the ownership check across every candidate file: if the file's `session_id` is a non-empty string and does not match the current session's uuid, the write is aborted silently (the hook does not steal another session's state); absent/null/empty `session_id` on disk PROCEEDS (opposite polarity from `refreshLiveness` - see `hooks/lib/state-mark.js`'s module manifest for why). Best-effort silent-fail throughout, gated per file. The mirror sets `status=interrupted`, `interrupted_at=now`, `interrupt_reason="unknown"` on every candidate, plus `updated_at=now` on `batch-state.json` only (`.agentic/loop-state-$LOOP_KEY.json`'s `last_updated` is deliberately NOT touched by the terminal mark - see below); all other fields including `last_updated_phase`, `tickets[]`, and `replan_log[]` are preserved.

**Candidate set (hook side).** The hooks derive no `LOOP_KEY` and hardcode no path. `hooks/lib/state-mark.js`'s `candidatePaths(cwd)` resolves the set at call time: every per-ticket keyed `.agentic/loop-state-<LOOP_KEY>.json` present on disk (newest-mtime-first, capped at 100), plus `.agentic/batch-state.json` and the legacy `.agentic/loop-state.json`, which are **always** included even when `.agentic/` is unreadable. Selection among them is by the per-file `session_id` predicates above, never by key derivation. The keyed rows inherit `tsField`, `healthTarget` and `touchTimestampOnTerminal` verbatim from the legacy loop-state row, so a keyed file has no semantics of its own and cannot drift from the legacy file's.

`--cadence=session` (or an absent/unrecognized flag) is `hooks/stop-context.js`'s fallback dispatch, preserved so callers that invoke the script directly without the flag (e.g. Pi's `session_shutdown`) keep their pre-existing once-per-invocation interrupted-mark behavior.

**Why `.agentic/loop-state-$LOOP_KEY.json`'s `last_updated` is never touched by the terminal mark:** the Resume check above branches on `last_updated` staleness with no `status` exemption. Writing `last_updated` on the terminal interrupted-mark would make a freshly-interrupted loop look "recently live" to a resuming session for the full 10-minute staleness window, offering a resume it cannot actually execute. `interrupted_at` already timestamps the terminal event, which is sufficient.

---

## `.agentic/batch-state.json` schema

```json
{
  "schema_version": 1,
  "session_id": "<current session uuid or null>",
  "batch_id": "<first-ticket-prefix>-batch-<ISO8601>-<4hex>",
  "status": "active",
  "mode": "batch",
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
  "resume_invocation_hint": "/ds-implement-ticket",
  "open_goal": {
    "active": false,
    "goal_condition": null,
    "iteration": 1,
    "max_iterations": null,
    "risk_declared": null,
    "termination_reason": null,
    "dry_run": false
  }
}
```

**Field semantics:**

- `schema_version`: integer; current is `1`.
- `session_id`: uuid of the conductor session that last wrote the file; null only on legacy files written by a prior version.
- `updated_at`: the file's liveness-timestamp field - `loop-state-$LOOP_KEY.json`'s equivalent field is named `last_updated` (see that schema's Field notes below and `content/references/cross-session-loop-resume.md`); the two files intentionally use different field names for the same concept. Written on every conductor write per Contract A step 4, and refreshed per-turn by the Claude Code Stop hook's `hooks/lib/state-mark.js` `refreshLiveness` per Contract D - off Claude Code, `updated_at` advances only at conductor ticket-transition writes, which are routinely more than 10 minutes apart mid-ticket; this makes every staleness gate below fail-open (weaker, never a false-abort) rather than misfire, but it does mean the field is a coarser liveness signal off Claude Code than the per-turn refresh implies. Every staleness gate that reads this field (Contract A step 2, Contract C, the N=1 foreign-batch warning, the Phase 0a-pre decision table, and the Phase 0a-open-goal resume classification) treats an ABSENT `updated_at` as **stale** - i.e. the gate does NOT fire, matching the pre-fix effective behavior - rather than as fresh. This is deliberate back-compat tolerance for files written before this field existed; it is not a migration, and no on-read rewrite occurs.
- `batch_id`: stable identifier for the batch. Format `<prefix>-batch-<ISO8601>-<4hex>` where `<prefix>` is the first ticket's `TICKET_PREFIX` (used when tickets span multiple prefixes; the first ticket wins).
- `status`: enum `active | paused | interrupted | complete | stalled`.
- `mode`: enum `"batch" | "open_goal" | "single_ticket_capped"`. Absent = `"batch"` (100% back-compat). `"open_goal"` is set by Phase 0a-open-goal's Fresh init; `"single_ticket_capped"` is set by the Phase 0a-pre single-ticket wallclock carve-out - the ONLY N=1 path that creates `batch-state.json`.
- `interrupt_reason`: enum `unknown | null` — only `unknown` is a writable value (other values reserved for future writers; the terminal-mark writer - the SessionEnd hook's `markInterrupted`, not the per-turn Stop hook - cannot distinguish rate-limit vs crash at hook time).
- `pause_reason`: enum `stale_pace | operator_pause | wallclock_cap | open_goal_iteration_cap | null` - these four values match the four Phase 12a triggers. NOTE: `paused_stale_pace` / `paused_operator_request` / `cap_reached_wallclock` / `cap_reached_iterations` / `goal_met` / `blocked` are `open_goal.termination_reason` values, NOT `pause_reason` values - deliberately avoiding a dual-enum collision. Only `open_goal_iteration_cap` was added to `pause_reason`; triggers 1-3 keep their existing `pause_reason` values `stale_pace` / `operator_pause` / `wallclock_cap`.
- `wallclock_started_at`: set once at Phase 0a init; preserved across resume. The wallclock cap is per-batch lifetime, not per-session.
- `wallclock_cap_min`: integer minutes. Default `90`. Overridable via env `AGENTIC_BATCH_MAX_WALLCLOCK_MIN`.
- `tickets[]`: triage-derived executable cursor; contains only lane-assigned tickets (deferred and in-progress-excluded tickets are not included). `status` per-ticket is `pending | in_progress | complete | blocked | skipped_already_merged`.
- `replan_log[]`: append-only audit log. Each entry: `{ts, action, ticket_id, detail}`. Actions include `drop_merged`, `investigator_rerun`, `re_sequence`. Preserved by Contract B.
- `open_goal`: present (meaningfully populated) only when `mode == "open_goal"`. `active`: boolean, whether an open-goal loop is currently running. `goal_condition`: operator-declared condition string, set once at Fresh init, read-only thereafter (divergent re-invocation values are warned and ignored - on-disk governs). `iteration`: current iteration number; invariant `iteration == len(tickets[])` from the first synthetic entry onward (SOLE momentary exception: immediately after Fresh init, `iteration=1` but `tickets=[]` - closed the moment Phase 1 of iteration 1 appends its entry). `max_iterations`: operator-declared cap, mandatory at Fresh init, no default. `risk_declared`: this iteration's risk classification (`low | elevated | trivial`), written at Phase 6 clean exit - the DURABLE audit record (see `content/references/trigger-catalog.md` §Risk and review discipline (c)). `termination_reason`: enum `null | cap_reached_iterations | cap_reached_wallclock | goal_met | blocked | paused_stale_pace | paused_operator_request` - partitions TERMINAL (`cap_reached_iterations`, `cap_reached_wallclock`, `goal_met`, `blocked`) from RESUMABLE (`paused_stale_pace`, `paused_operator_request`, or `null` with `status` in `{paused, interrupted}`). `dry_run`: boolean, set once at Fresh init, never changes mid-loop; when `true`, Phases 6b/8-11b are skipped for every iteration (no QA, no ship, no PR) - see Phase 6b and Phase 8 dry-run gates.

---

## Resume check (before setup)

### Loop-key derivation (runs first, exactly once per ticket)

Loop state is stored **per ticket**, at `.agentic/loop-state-<LOOP_KEY>.json`, so two sessions working two different tickets in one checkout never contend for one file. Derive `LOOP_KEY` **once** - here at the Resume check, or at Phase 6 loop init if that comes first - record it in the file's own `loop_key` field, and carry it in-context for the rest of that ticket. **Never re-derive it**, and **never derive it from `$BRANCH_NAME`** (the workflow deletes the branch after merge, so a later rework derives the same slug and two attempts look like one).

Inputs are the invoked `TICKET_ID` (may be absent on a batch or open-goal invocation) and the current session's `SESSION_ID` (may be absent, or the 4-char string `null` on a harness whose `session_id` is a JSON null read through `jq -r`).

```bash
# Resume check: loop-key derivation
ae_sanitize() {
  # 1. every char outside [A-Za-z0-9._-] -> '-'   2. collapse '-' runs
  # 3. strip leading/trailing '-' and '.'          4. truncate to 64
  # 5. re-strip trailing '-' and '.' exposed by the truncation
  #
  # STEP 1 USES `tr -c`, NOT `sed`. This is not a style choice. `sed` and `cut`
  # are LINE-ORIENTED: a newline is sed's record separator, so `s/[^...]/-/g`
  # does NOT replace it, and `cut -c1-64` truncates PER LINE. Measured:
  #   printf 'x\ny' | sed -e 's/[^A-Za-z0-9._-]/-/g'   ->  x\ny   (newline SURVIVES)
  #   printf 'x\ny' | tr -c 'A-Za-z0-9._-' '-'          ->  x-y   (correct)
  # With sed, a newline-bearing ticket id yields a filename containing a raw
  # newline, which fails the `^loop-state-.+\.json$` invariant the candidate
  # enumeration below relies on, and a multi-line 200-char id defeats the
  # 64-char cap entirely (measured: key length 129). `tr` is byte-oriented and
  # has no record concept, so it closes both.
  #
  # `tr -c` complements the SET, so the set must not be a regex bracket
  # expression - `A-Za-z0-9._-` with the `-` last is correct for tr.
  printf '%s' "${1-}" \
    | LC_ALL=C tr -c 'A-Za-z0-9._-' '-' \
    | LC_ALL=C sed -e 's/--*/-/g' \
    | LC_ALL=C sed -e 's/^[-.]*//' -e 's/[-.]*$//' \
    | cut -c1-64 \
    | LC_ALL=C sed -e 's/[-.]*$//'
}

ae_derive_loop_key() {
  # $1 = TICKET_ID (may be empty)   $2 = SESSION_ID (may be empty, or "null")
  #
  # This function's ONLY output is the key on stdout. Do NOT add a diagnostic
  # print here - callers capture stdout as the key, and so does
  # bin/tests/test_loop_key_derivation.sh. The sanitize-to-empty operator
  # notice is emitted by the CALLER (see below), not from inside here.
  local raw_ticket="${1-}" raw_sid="${2-}" core key=""

  # B1 - ticket branch.
  core="$(ae_sanitize "$raw_ticket")"
  [ -n "$core" ] && key="$core"

  # B2 - session branch. SESSION_ID is sanitized BEFORE the prefix is applied,
  # never after: sanitizing "session-<garbage>" would yield the shared key
  # "session", colliding across every session that reached this branch.
  # The 4-char string "null" is treated as absent - Contract A mandates
  # session_id: null on harnesses with no id namespace, and a JSON null read
  # through `jq -r` surfaces as that literal string.
  if [ -z "$key" ] && [ -n "$raw_sid" ] && [ "$raw_sid" != "null" ]; then
    core="$(ae_sanitize "$raw_sid")"
    [ -n "$core" ] && key="session-$core"
  fi

  # Truncate + re-strip, applied uniformly to whatever B1/B2 produced.
  if [ -n "$key" ]; then
    key="$(printf '%s' "$key" | cut -c1-64 | LC_ALL=C sed -e 's/[-.]*$//')"
  fi

  # B3 - TERMINAL FLOOR. The emptiness test is on the FINAL ASSEMBLED KEY,
  # not on the raw inputs. This is what makes `.agentic/loop-state-.json`
  # unreachable: no branch above can emit an empty key past this point.
  if [ -z "$key" ]; then
    key="session-nosid-$(od -An -tx1 -N4 /dev/urandom | tr -d ' \n')"
  fi

  printf '%s' "$key"
}
```

`LOOP_STATE_FILE` is `.agentic/loop-state-$LOOP_KEY.json` and its staging path is `.agentic/loop-state-$LOOP_KEY.json.tmp` - a **flat sibling**, not a subdirectory, so `.tmp` files stay direct children of `.agentic/`. Before every write, assert the assembled path's dirname resolves to `.agentic/`.

**Traversal impossibility has three independent guards. Do not remove one thinking it redundant:** (a) `ae_sanitize` maps `/` to `-`, so no key contains a path separator; (b) the key is always wrapped in the fixed affixes `loop-state-` and `.json`, so it can never *be* a path component like `..` - note that `..` **does** survive sanitization, because `.` is in the safe set (`feature/../../etc/passwd` yields `feature-..-..-etc-passwd`), and traversal safety never depended on stripping it; (c) the dirname assertion above.

**Sanitize-to-empty notice (emitted HERE, by the caller - never from inside `ae_derive_loop_key`).** When `TICKET_ID` was non-empty but `ae_sanitize "$TICKET_ID"` returned empty (e.g. `###`, or `..`), so the key fell through to the session or nosid branch, print exactly one line:

```
Ticket id '<raw>' sanitizes to empty; loop state keyed on session instead (<LOOP_KEY>).
```

Emit it after the key is derived and only under that condition. It must not live inside `ae_derive_loop_key`: that function's only output is the key via `printf`, so a diagnostic there corrupts every caller and every assertion in `bin/tests/test_loop_key_derivation.sh`.

`LOOP_KEY` also governs telemetry attribution: export `AGENTIC_LOOP_KEY="$LOOP_KEY"` at every `bin/agentic-emit` call site (see Phase 6).

### Candidate check

Before reading AGENTS.md or doing any setup, check for `.agentic/loop-state-$LOOP_KEY.json`. Also enumerate the other candidates - `.agentic/loop-state-*.json` and the legacy `.agentic/loop-state.json` - because they affect the informational line and the legacy-adoption path below, but **the recommendation is `.agentic/loop-state-$LOOP_KEY.json` only.**

**Key match is the primary guard, never freshness.** If the keyed file is absent or not resumable, print the informational line below and **proceed to Setup with no resume prompt.** There is deliberately **no cross-ticket freshness fallback**: a fallback on "most recent `last_updated`" would offer a resuming session another ticket's *live* file whenever that file's timestamp was over 10 minutes old - routine during a CI wait, and guaranteed on the ten harnesses with no per-turn liveness refresh - and accepting it would then destroy that ticket's `findings_log`.

**If `.agentic/loop-state-$LOOP_KEY.json` exists and `status == "interrupted"`:**
- Print: "Interrupted loop detected on branch [branch] for ticket [ticket_id]."
- Print: "Last phase: [last_phase] / [last_phase_action], iteration [loop_state.iteration]/[loop_state.max_iterations]."
- Print: "Open findings: [count of findings_log entries with status=open or status=addressed]"
- Ask: "Resume this loop or start fresh? (resume / fresh)"
- If "fresh": delete **only** `.agentic/loop-state-$LOOP_KEY.json` - the recommended candidate. Every other candidate listed in the informational line stays byte-identical and remains resumable later. Proceed normally from Setup below.
- If "resume": apply wait strategy (see below), then jump to the resume entry point determined by `last_phase` / `last_phase_action` per the table below. Increment `resume_count` on the accepted file.

**If `.agentic/loop-state-$LOOP_KEY.json` exists and `status == "active"` with `last_updated` more than 10 minutes ago:** treat as implicitly interrupted (the SessionEnd hook's terminal `markInterrupted` write may not have fired - e.g. a hard kill with no clean session end - and the Stop hook's own `--cadence=turn` write only refreshes `last_updated` liveness, never `status`). Print: "Found an active loop state last written [elapsed] ago — treating as interrupted." Then follow the "interrupted" path above.

**If `.agentic/loop-state-$LOOP_KEY.json` exists and `status == "active"` with `last_updated` within the last 10 minutes:** a live session owns it. Not resumable. No prompt.

**If `.agentic/loop-state-$LOOP_KEY.json` exists and `status == "complete"` or `"stalled"`:**
- Print: "A completed/stalled loop state file exists for ticket [ticket_id]. Clearing it."
- Delete **that keyed file only**. Proceed normally.

**If `.agentic/loop-state-$LOOP_KEY.json` does not exist but other resumable `.agentic/loop-state-*.json` candidates do:** print **no resume prompt**. Print one informational line, capped, then proceed to Setup:

```
N other resumable loops exist: <up to 3 keys, most-recent last_updated first>[, +M more]. Re-invoke with that ticket id to resume one.
```

One line, recommendation-plus-confirmation, never a co-equal ballot (required by the AskUserQuestion precondition in `content/sections/02-delegation.md`). If those other candidates exist but none is resumable, proceed silently.

**If `.agentic/loop-state-$LOOP_KEY.json` does not exist and the legacy `.agentic/loop-state.json` does - legacy adoption.** A legacy file is never silently ignored. When it is resumable (`status == "interrupted"`, or `status == "active"` and stale > 10 min via the implicit-interrupt path above):
1. Derive the **adoption key** from the legacy file's own `ticket_id`; else `session-<its own session_id>`; else the literal `legacy`.
2. Atomically write the legacy payload to `.agentic/loop-state-<that adoption key>.json`, setting `loop_key` to the adoption key and incrementing `resume_count`.
3. `rm -f .agentic/loop-state.json` (loop-key: legacy - this is the legacy-adoption path's own cleanup of the unkeyed file, deliberately not a keyed path).
4. Adopt that `loop_key` as this session's key for the rest of the ticket, then follow the "interrupted" path above.

When the legacy file is `active` and fresh, it is not resumable: no prompt, and leave it untouched. When it is `complete`/`stalled`, print the clearing line above and delete the legacy file. **When BOTH the keyed file and a legacy file are resumable, the keyed file wins** - the legacy file is listed in the informational line, not adopted, because adopting older state over newer would overwrite it.

**Null-ticket resume (`session-*` and `session-nosid-*` key families).** These families are resumable; a synthetic key regenerated per session would otherwise match nothing and every interrupted null-ticket run would orphan a file. When `TICKET_ID` is absent, resolve against the resumable `.agentic/loop-state-session-*.json` candidates:

| Current `SESSION_ID` | Resumable `session-*` candidates | Behavior |
|---|---|---|
| non-empty | exactly one whose `loop_key == "session-" + sanitize(SESSION_ID)` | recommend it (exact match, highest precedence) |
| non-empty | no exact match, exactly one `session-*` | recommend it, and **adopt its `loop_key`** as this session's key for the rest of the ticket |
| non-empty | no exact match, 2+ | recommend none; print the informational line; proceed to Setup |
| `null`/empty | exactly one | recommend it; adopt its `loop_key`. **This row preserves today's behavior on harnesses with no session-id namespace** - today there is exactly one file, hence exactly one candidate |
| `null`/empty | 2+ | recommend none; print the informational line. Not a regression: two such loops would have collided into one file before keying, so no working behavior is lost |
| any | zero | no prompt |

Adopting the candidate's own `loop_key` rather than re-deriving is what makes the `session-nosid-*` family resumable at all.

**If a candidate's `loop_key` field is present but differs from its own filename's key** (a manual operator edit, or a partial write): the **filename wins for selection**, and the `loop_key` field wins for this session's in-context key after an accepted resume. Print one warning line. Do not auto-repair.

**If no candidate of any kind exists:** proceed normally, no prompt, no output.

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

**Parse failure:** if a candidate (`.agentic/loop-state-$LOOP_KEY.json`, another `.agentic/loop-state-*.json`, or the legacy `.agentic/loop-state.json`) exists but cannot be parsed as JSON, print a warning and offer to delete **that one candidate** and start fresh. A parse failure demotes only the candidate that failed; every other candidate is unaffected and stays resumable. Do not silently ignore it.

**Concurrent session guard.** **REPLACED in this version by Contract A's per-write `session_id`-mismatch abort gate, applied to every conductor write of the keyed `loop-state-<LOOP_KEY>.json` and of `batch-state.json`.** See Phase 0a-pre and the "Batch state contracts" section above for the full contract. Every conductor write to the keyed loop-state file includes a top-level `session_id: <current session>` field; readers tolerate absence for back-compat with state files written by prior versions. Note that per-ticket keying means **different-ticket contention no longer reaches this gate at all** - the two sessions write different files. The gate still fires, as designed, when two sessions work the **same** ticket, because they derive the same `LOOP_KEY` and therefore the same file.

**N=1 foreign-batch warning.** Before proceeding to Phase 0a-pre on an invocation where Phase 0 produced exactly 1 entry, apply the N=1 foreign-batch check from "Batch state contracts" above. If `.agentic/batch-state.json` exists with `status=active` + different `session_id` + recent (≤10 min): print the verbatim NOTE, prompt yes/no, and abort on `no`.

---

## Setup: Read project config

Before any phase, read the project's `AGENTS.md` and extract the following values:

- `REPO` — absolute path to the repo root
- `GH_REPO` — GitHub repo slug (e.g. `org/repo-name`)
- `BASE_BRANCH` — the branch all work is based from. Resolve in this order: (1) if declared via a `BASE_BRANCH:` line in `AGENTS.md`, use that; (2) else `develop` if it exists locally; (3) else `development` if it exists locally; (4) else stop and ask the user: no `develop`/`development` integration branch found - use `main` (falling back to `master`), or set up a develop-based workflow? Offer `main` as the recommended default; (5) on decline / main preference, resolve `main` (fall back to `master`). Do not auto-create a branch. Once resolved, print: `BASE_BRANCH resolved to: [value]`.
- `QUALITY_CMD` — the full quality gate command to run from repo root
- `DEBUGGER_ON_FAILURE` — read from `.agentic/config.json` key `debugger_on_failure` (boolean, default `false`). When `true` and the path is Elevated, a Debugger diagnosis step is interposed between a failed quality gate and the next engineer fix pass in Phase 7 - see Phase 7 for the full flow.
- `AUTO_MERGE_ON_CI_GREEN` — read from `.agentic/config.json` key `auto_merge_on_ci_green` (boolean, default `false`). When `true`, Phase 12 squash-merges the PR after CI passes, the PR is ready, and no reviewer has requested changes. Default `false` leaves the PR open for human review.
- `PR_WORKFLOW_REVIEWERS` — read from `AGENTS.md` `## PR Workflow` section, `Reviewers:` field (comma-separated GitHub usernames). Default: empty string. Section absence = empty. Used in Phase 10b as fallback reviewer assignment when no CODEOWNERS file is found.
- `REWORK_DETECTION` — read from `.agentic/config.json` key `rework_detection` (boolean, default `true`; absent key resolves to `true`). When `false`, the ticket-rework alert goes fully dark: the Phase 9 ledger write, the Phase 1 detection read, the REWORK notice, and the escalation (Elevated risk floor, architect/Skeptic callouts, Tier-3 bump) are all disabled. See `content/references/ticket-rework.md`.

**Tracker resolution** — read tracker config using this fallback chain:

1. If a `## Tracker` section exists in `AGENTS.md` and contains `TRACKER: jira`: set `TRACKER=jira`. Extract `TICKET_PREFIX`, `JIRA_BASE_URL`, `JIRA_QA_ASSIGNEE_ACCOUNT_ID` (optional), `JIRA_QA_TRANSITION` (optional — no default). Also extract optional state-name overrides: `JIRA_STATE_IN_PROGRESS` → `TRACKER_STATE_IN_PROGRESS` (default `"In Progress"`), `JIRA_STATE_IN_REVIEW` → `TRACKER_STATE_IN_REVIEW` (default `"In Review"`), `JIRA_STATE_QA` → `TRACKER_STATE_QA` (default `"QA"`), `JIRA_STATE_BLOCKED` → `TRACKER_STATE_BLOCKED` (default `"Blocked"`), `JIRA_STATE_DONE` → `TRACKER_STATE_DONE` (default `"Done"`). All five fields are optional; absence = use default.
2. Else if a `## Tracker` section exists with `TRACKER: linear` (future-proofing): treat as Linear and read Linear fields from `## Tracker` instead of `## Linear`. Apply the same state-name override fields as the Linear path below.
3. Else if a `## Linear` section exists: set `TRACKER=linear`. Extract `Team` → `TICKET_PREFIX`, `Workspace` → `LINEAR_WORKSPACE`, `QA assignee ID` → `LINEAR_QA_ASSIGNEE_ID` (optional). Also extract optional state-name overrides: `State In Progress:` → `TRACKER_STATE_IN_PROGRESS` (default `"In Progress"`), `State In Review:` → `TRACKER_STATE_IN_REVIEW` (default `"In Review"`), `State QA:` → `TRACKER_STATE_QA` (default `"Testing"`), `State Blocked:` → `TRACKER_STATE_BLOCKED` (default `"Blocked"`), `State Done:` → `TRACKER_STATE_DONE` (default `"Done"`). All five fields are optional; absence = use default. (Note: Linear `TRACKER_STATE_QA` defaults to `"Testing"` while Jira defaults to `"QA"` — reflects common workspace conventions for each tracker.)
4. Else: set `TRACKER=none`. Set all `TRACKER_STATE_*` variables to their defaults: `TRACKER_STATE_IN_PROGRESS="In Progress"`, `TRACKER_STATE_IN_REVIEW="In Review"`, `TRACKER_STATE_QA="Testing"`, `TRACKER_STATE_BLOCKED="Blocked"`, `TRACKER_STATE_DONE="Done"`.

**Dual-shape note:** Linear projects canonically store tracker config under `## Linear`; Jira projects use `## Tracker`. This is intentional — it preserves zero-migration compatibility for every existing Linear project that already has a `## Linear` section.

**Legacy `## Linear` shape guard** — if `TRACKER=linear` was resolved from a `## Linear` section AND the section is missing the `Workspace:` field (required for URL generation), stop immediately and print:

```
Your tracker config is missing fields /ds-implement-ticket needs. Run /ds-init-project to update it —
discovery will fill in most fields automatically.
```

Do not continue. Do not attempt to write the migration. All config-mutation logic lives in `/ds-init-project`.

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

Reusable subagent invocation pattern. Used by Phase 11 (existing), 7 new sites below, and 2 awaiting callers (`/ds-ticket-status-sync` both single-ticket and `--all` modes, `/ds-wrap` Part F). Gated on `TRACKER != none`; no-op otherwise.

**Invocation contract:**

When the conductor reaches a writeback boundary:
1. Skip entirely if `TRACKER == none`.
2. Spawn the tracker-writeback subagent (Tier 1, `general-purpose`) in background (fire-and-forget; do NOT wait for return before continuing the phase). Fire-and-forget applies at W1-W7 and Phase 11; awaiting callers (`/ds-ticket-status-sync`, `/ds-wrap` Part F) are enumerated in the guard's step 4.d.iv below.
3. Pass to the subagent:
   - `tracker`: `linear` | `jira`
   - `ticket_id`: from current task context
   - `target_state`: one of the resolved `TRACKER_STATE_*` variables
   - `forward_only_guard`: `true` for every writeback caller - the 7 new sites, Phase 11 (preserving its prior hardcoded `Testing` behavior), and the awaiting callers `/ds-ticket-status-sync` (both single-ticket and `--all` modes) and `/ds-wrap` Part F
   - `tracker_state_values`: `{ "IN_PROGRESS": "$TRACKER_STATE_IN_PROGRESS", "IN_REVIEW": "$TRACKER_STATE_IN_REVIEW", "QA": "$TRACKER_STATE_QA", "BLOCKED": "$TRACKER_STATE_BLOCKED", "DONE": "$TRACKER_STATE_DONE" }` - the 5 values resolved once in Setup; required by the forward-only guard's same-category pipeline sub-rank
   - Tracker-specific config: `LINEAR_WORKSPACE`, `LINEAR_QA_ASSIGNEE_ID` for Linear; equivalent for Jira

**Subagent responsibilities (extended for `forward_only_guard`):**

1. **Pre-read current state:**
   - Linear: call `mcp__linear__get_issue` to read the ticket's current state, capturing both `state.type` and `state.name` (e.g. `"In Review"`) from the response.
   - Jira: call `mcp__mcp-atlassian__jira_get_issue` to read the ticket's current status, capturing both `fields.status.statusCategory.key` and `fields.status.name` (e.g. `"In Review"`) from the response.

2. **Field-absence guard.** If the pre-read call succeeds (no MCP/API error) but the returned object omits `state.type` (Linear) or `fields.status.statusCategory.key` (Jira) - a successful call with an incomplete response, not a call failure - treat it identically to the pre-read failure in step 5: **skip** the transition, do not compute any rank, and emit one stderr line: `tracker-writeback: <ticket_id> pre-read succeeded but response omitted the state-type field ('state.type' / 'statusCategory.key') - skipping, no rank assumed.` Absence always routes to skip, never to permit - a missing category must never be read as "already past every target" or "not yet at any target."

3. **Compute category rank** (governs cross-category comparisons only):
   - Linear: `backlog` < `unstarted` < `started` < `completed` < `canceled` < `duplicate`; `canceled` and `duplicate` are both terminal (never overwritten by any automatic transition).
   - Linear defensive fallback (separate from the primary enum above): if a state's `type` is instead spelled `cancelled` (double L) - e.g. a differently-shaped MCP response or a stale cached row - treat it as terminal too. The canonical/primary spelling the Linear API emits is single-L `canceled`; this fallback exists only for robustness against a non-conforming response shape.
   - Jira: `new` < `indeterminate` < `done` (via `statusCategory.key`); a status whose category or name matches cancellation semantics (Won't Do, Cancelled, Duplicate, Will Not Fix) is terminal (never overwritten).

4. **Apply the guard** - category rank first, then a same-category pipeline sub-rank:
   a. If current state is terminal (Linear `canceled` / `duplicate` / defensive `cancelled` (double L), or Jira cancellation-semantic): **skip** unconditionally.
   b. If `category_rank(current) < category_rank(target)`: **permit** (forward move across categories).
   c. If `category_rank(current) > category_rank(target)`: **skip** (backward move across categories - this is what prevents Blocked or In Review from ever overwriting Done).
   d. If `category_rank(current) == category_rank(target)` (the same-category band that holds In Progress / In Review / QA / Blocked on both trackers), apply the **pipeline sub-rank** by case-insensitive exact-name match against the 5 values in `tracker_state_values`:
      - i. If `target_state`'s name case-insensitive-exact-matches the CURRENT state's name: **skip** (idempotent no-op - already there).
      - ii. Else if `target_state` matches `BLOCKED`: **permit** unconditionally. Blocked is always a permitted same-category target on both trackers - a genuine problem signal that must never be silently dropped, regardless of where the tracker's columns happen to sit.
      - iii. Else if the CURRENT state's name matches `BLOCKED`: **permit** unconditionally. Resuming or unblocking a ticket must always be able to move it forward into In Progress, In Review, or QA - Blocked never blocks a later forward transition.
      - iv. Else, look up current and target against the fixed pipeline sequence `IN_PROGRESS` (rank 0) < `IN_REVIEW` (rank 1) < `QA` (rank 2) from `tracker_state_values`. This order is fixed by which writeback site fires it (W1 < W2 < W3) - it is not read from any tracker API and does not depend on operator-configured board/column order.
        - If BOTH names resolve to a pipeline rank: **permit** iff `pipeline_rank(current) < pipeline_rank(target)`; otherwise **skip**.
        - Otherwise (at least one name does not resolve to a pipeline rank - either because it does not match any of the 5 known `tracker_state_values` at all, or because it matches one of the 5 values that has no pipeline rank, e.g. `DONE` or `BLOCKED` reached here only on a misconfigured tracker where that value's category coincides with this same-category band): **skip** unconditionally. Set the return payload's `unmatched_state_name` to that name only when it does not resolve to any of the 5 known `tracker_state_values` at all - a name that resolves to a configured value but simply lacks a pipeline rank is not "unmatched." **Fire-and-forget call sites** (W1-W7, Phase 11 - these never read the subagent's return value) additionally emit ONE stderr line directly here, bounded to at most one line per fire because each fire covers exactly one ticket: `tracker-writeback: <ticket_id> current state '<name>' did not match any configured TRACKER_STATE_* value - skipping same-category comparison.` **Callers that await the result** (`/ds-ticket-status-sync`, `/ds-wrap` Part F) do NOT get a per-ticket stderr line for this branch; they read `unmatched_state_name` from each ticket's return, accumulate across their sweep, and print exactly ONE aggregate line at the end.
5. **Soft-fail:** any transition error logged to stderr; subagent returns `{ "status": "failed", "errors": [...] }`. Conductor logs and continues; never blocks the phase. A state pre-read failure (MCP/API error) is also a skip: log a one-line warning to stderr and do not proceed. Do not assume any rank when the pre-read fails.

**This ranking never reads `.agentic/tracker-states.json`.** It uses only the live pre-read of the ticket's own current state (step 1) and the 5 `tracker_state_values` strings resolved once in Setup. The Phase 2c cache remains Phase 2c-only and purely advisory; no writeback subagent reads or writes it.

**Failure logging:** subagent stderr is captured by the conductor's `agentic-emit` event; one operator-visible line per failure of the form: `tracker-writeback: <ticket_id> -> '<target_state>' FAILED: <error>`. No block.

For full details of the Phase 11 writeback subagent brief shape, see the Phase 11 block below — the brief is unchanged except for the addition of `target_state`, `forward_only_guard`, and `tracker_state_values` parameters.

---

## Tracker Create Helper

Reusable SYNCHRONOUS pattern - the conductor waits for the new ticket ID before routing to `/ds-implement-ticket`. Called by the ticket-offer gate (cross-ref `content/sections/02-delegation.md` §Ticket-offer gate).

**Invocation contract:**

Caller supplies:
- `TICKET_TITLE` - one-line summary of the work
- `TICKET_BODY` - markdown description; include Problem + Acceptance Criteria when known
- `TICKET_TYPE` - `feature` | `bug` | `task`

Helper returns:
- `CREATED_TICKET_ID` - e.g. DS-42; empty string on failure
- `CREATED_TICKET_URL` - empty string on failure
- `CREATE_STATUS` - `created` | `skipped` | `failed`
- `CREATE_ERROR` - error message string, or null on success
**Collision pre-check (runs BEFORE the create branches):**

Before calling any tracker create API, scan in-flight tickets in the same tracker project/team for overlapping output surfaces. Overlap surface = same source files, same exported symbols, same DB tables/migrations, or same shared utility/config that the proposed TICKET_BODY scope touches. This is the cross-ticket boundary analysis that prevents two parallel sessions from colliding on the same file - the failure mode where a boundary gets retrofitted AFTER the ticket already exists instead of at creation time.

Scan target: open AND in-progress tickets in the same project/team. For Linear: `mcp__linear__list_issues` filtered by team, excluding state types completed, canceled, and duplicate. For Jira: `mcp__mcp-atlassian__jira_search` with project JQL scoped to statusCategory != Done. For trackers with no query branch: skip silently (fail-safe - the boundary-in-body rule below still applies but relies on the conductor's own scope knowledge rather than a scan).

Decision:

- **No overlap, OR tracker has no query branch:** proceed to the create branches with TICKET_BODY unchanged.
- **Overlap found:** append a `## Scope boundary` section to TICKET_BODY BEFORE the create call. The section names the overlapping ticket(s) and the file/symbol/table each side owns. Worked example (AUT-301 vs AUT-300, both touching the operator-list surface):

  ```
  ## Scope boundary

  - AUT-300 owns: packages/qa-auth/src/adapters/admin.ts (prod-DB guard), admin/scripts/seed-qa-operator.ts, and any isTestAccount schema migration if that route is chosen.
  - This ticket owns: backend/src/operators/index.ts GET /operators WHERE-clause filter only.
  - Merge order: this ticket is the symptom-fix; AUT-300 is root-cause. If AUT-300 adds an isTestAccount flag, that migration is AUT-300's to own.
  ```

The boundary section is binding, not advisory: it travels with the ticket into the tracker so the other session sees it on its next pull. If the conductor cannot determine a clean boundary (the two tickets genuinely own the same lines with no split), STOP before creating and surface the conflict to the operator for a manual scope-split.

The scan is a single tracker query (one API roundtrip, paginated to the project/team). It is cheap and runs only at create time - it does not run on every phase transition.

**Branch on TRACKER:**

- **`TRACKER == linear`**: call `mcp__linear__save_issue` with NO `id` field (save_issue creates when no id is supplied - this matches the repo's existing Linear convention; do NOT use a `createIssue` tool, it does not exist). Pass `title`=TICKET_TITLE, `description`=TICKET_BODY, and the Linear team. IMPORTANT team-source note: the `## Linear` section's `Team:` field resolves to `TICKET_PREFIX` (a prefix string like "DS"), but save_issue needs the Linear team key/id - if only a prefix is available, resolve the actual team via the Linear team-list tool. Do NOT invent a `## Linear Team` heading; use the existing `## Linear` `Team:` resolution that the rest of this command uses. On success read `issue.identifier` -> CREATED_TICKET_ID, `issue.url` -> CREATED_TICKET_URL, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed, CREATE_ERROR=\<msg\>.

- **`TRACKER == jira`**: call `mcp__mcp-atlassian__jira_create_issue` (naming-consistent with the existing `mcp__mcp-atlassian__jira_*` family used elsewhere in this file). Pass `project_key`=TICKET_PREFIX, `summary`=TICKET_TITLE, `description`=TICKET_BODY, `issue_type` mapped from TICKET_TYPE (feature -> "Story", bug -> "Bug", task -> "Task"; omit to accept project default if uncertain). On success read the returned issue key -> CREATED_TICKET_ID, construct CREATED_TICKET_URL as `<JIRA_BASE_URL>/browse/<CREATED_TICKET_ID>`, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed.

- **`TRACKER` has no built-in create branch (forward-looking fall-through)**: CREATE_STATUS=skipped. Emit one operator line: `ticket_driven: create not supported for this tracker - proceeding ad-hoc.` Do NOT run any shell command from `.agentic/phase0-classifiers.yml` as a create operation - the classifier contract is read-only; creation is a write operation outside that contract. This branch is the extension point for trackers not yet integrated: adding a new tracker means adding a create branch above; until then it falls through here. Adding a project-local classifier does NOT constitute a create integration.

**LOUD failure (NOT silent):** on CREATE_STATUS=failed, emit an operator-visible line mirroring the Writeback Helper's failure line format: `tracker-create: '<TICKET_TITLE>' FAILED: <CREATE_ERROR>`. Do not block the caller; the caller (the gate) decides: offer mode proceeds ad-hoc AFTER emitting the warning; require mode surfaces and waits.

---

## Phase 0: Input normalization

> Run this phase BEFORE Phase 0a-pre. Output is the in-memory `normalized_input` structure consumed by every later phase. No disk side-effects.

<!--
Phase 0 manifest:
  Purpose: normalize any form of /ds-implement-ticket input into a canonical entries[] list.
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

`.agentic/phase0-classifiers.yml` runs with full conductor privileges: shell-command resolvers execute as the operator's shell user, and MCP-tool resolvers can invoke any MCP server the conductor has access to. Trust level is therefore equivalent to executable code committed to the repository — anyone who can land a change to this file can execute arbitrary commands in any session that runs `/ds-implement-ticket` against the affected branch. **Operators MUST review changes to `.agentic/phase0-classifiers.yml` whenever pulling an untrusted or unfamiliar branch (collaborator PR, fork, dependabot, agent-authored branch) before invoking `/ds-implement-ticket` on that branch.** The file is project-local by convention and is not signed, sandboxed, or sandbox-enforced. This trust posture matches the rest of the `.agentic/` umbrella but is called out explicitly here because Phase 0 runs before any other phase and is therefore the first execution surface a malicious classifier file could exploit.

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
**Collision-awareness backstop (consume-time).** When Phase 0 resolves ticket entries, the conductor reads each ticket body for a `## Scope boundary` section (written by the Create Helper collision pre-check). If present, carry it into the architect brief and engineer execution contract. If absent AND the tracker supports queries, run the same in-flight overlap scan the Create Helper runs before the architect spawns; on overlap, surface the boundary to the operator and append it to the architect brief. Best-effort, never blocks Phase 0 - this catches human-filed tickets that skipped the create-time pre-check.

---

## Phase 0a-open-goal: Open-goal loop init or resume (conditional)

**Trigger:** invocation carries `goal_mode=open_goal`. Mutually exclusive with Phase 0a-pre/Phase 0a - skip both when this fires; fall through unmodified when it does not.

### Step 0 - resume-vs-fresh classification (before any write). Provably complete partition.

Read `.agentic/batch-state.json` if present.

- Absent, or `mode != "open_goal"`: → Fresh init.
- `mode == "open_goal"`: classify via `termination_reason` first (authoritative when non-null, regardless of `status`); fall back to `status` sub-partition only when `termination_reason == null`.

  **A. `termination_reason` non-null (6 of 7 buckets; resolved without consulting `status`):**
  - `cap_reached_iterations` | `cap_reached_wallclock` → TERMINAL; print:
    ```
    A prior open-goal loop already terminated (reason: <termination_reason>, iteration <N>/<max_iterations>). Starting fresh clears this state. To continue this goal instead, re-invoke with max_iterations and/or max_wallclock_min set HIGHER than the current values (max_iterations=<X>, max_wallclock_min=<Y>). Confirm: fresh-start (delete + reinit) or raise-caps (continue from iteration <N+1>)? (fresh / raise-caps)
    ```
    Offer both `fresh` and `raise-caps`.
  - `blocked` → TERMINAL, fresh ONLY (raise-caps can't unblock a stuck Skeptic loop); prompt adds: "To resume the specific blocked iteration's stuck work instead, use the ordinary per-ticket Resume check against that iteration's own branch - this phase does not do that."
  - `goal_met` → TERMINAL, fresh ONLY (nothing to raise).
  - `paused_stale_pace` | `paused_operator_request` → RESUMABLE.

  **B. `termination_reason == null` (7th bucket; sub-partitioned on `status`, exhaustively):**
  - `status` in `{paused, interrupted}` → RESUMABLE.
  - `status == "active"` → apply Contract A's existing per-write `session_id`-mismatch determination to this READ (same 5-way logic Contract A uses to gate every `batch-state.json` WRITE - including the self-ownership carve-out - applied here as read-time classification):
    - `session_id` non-empty and matches current session → RESUMABLE (same-session continuation; covers crash-mid-advance re-invoked same session).
    - `session_id` non-empty, differs, AND `updated_at` older than 10 min → RESUMABLE, treated as implicitly interrupted (mirrors Phase 0a-pre "status=active AND updated_at>10min → implicit interrupt"). Covers crash-mid-advance surviving into a later session.
    - `session_id` non-empty, differs, AND `updated_at` within last 10 min → REFUSE, verbatim Contract C message: `"Another batch session is active for this project root (session_id=<X>, updated_at=<Y>). Wait for it to finish, kill it and re-invoke, or remove .agentic/batch-state.json and re-invoke."` Exit. (live-foreign-session; closes the null+active Contract-C bypass.)
    - `session_id` null/absent AND the CURRENT session's own id is ALSO null (self-ownership carve-out - see Contract A step 3) → RESUMABLE (self-owned, same as the matching-session row above; no force-takeover prompt - on a harness that cannot produce a matching session id, two nulls are indistinguishable by construction).
    - `session_id` null/absent AND the CURRENT session HAS its own non-null id (i.e. the self-ownership carve-out row above does NOT apply) → force-takeover prompt verbatim (Phase 0a-pre): `"WARNING: another session (session_id=<X>, updated_at=<Y>) may still be active. Force takeover? (yes/no). Identify the live session via .agentic/batch-state.json updated_at."` `yes` → RESUMABLE; `no` → exit/wait. (This is a READ-time classification of the ON-DISK file's null/absent id, distinct from but complementary to Contract A's WRITE-time self-ownership carve-out.)
  - `status == "complete"` → TERMINAL, fresh ONLY (safe default; unexpected/legacy combo).
  - `status == "stalled"` → TERMINAL, fresh ONLY (same rationale).
  - any other/unrecognized `status` → TERMINAL, fresh ONLY (safe default).

**Completeness statement:** every `(termination_reason, status)` pair lands in exactly one of {Fresh init, RESUMABLE, raise-caps-or-fresh (terminal-cap bucket), refuse}. Bucket A resolves 6 of 7 `termination_reason` values without consulting `status`. Bucket B exhaustively covers the 7th value (`null`) across all 5 named `status` enum values + explicit catch-all; `status==active` within bucket B is itself exhaustively partitioned by Contract A's 5-way `session_id`/staleness logic (including the self-ownership carve-out). No pair unclassified.

- On fresh (any TERMINAL branch): delete `batch-state.json` → Fresh init. (force-takeover "no" exits/waits, does NOT go fresh.)
- On raise-caps: refuse unless declared `max_iterations`/`max_wallclock_min` strictly greater than on-disk: `"raise-caps requires re-invoking with max_iterations and/or max_wallclock_min set higher than the existing values (current: max_iterations=<X>, max_wallclock_min=<Y>). Re-invoke with a higher value, or choose fresh."` On success: Contract A write (update, NO Contract C - update not create) setting raised cap(s), `termination_reason:null`, `status:"active"` → Advance to next iteration (idempotency-checked).
- On RESUMABLE (any sub-case incl. force-takeover yes): Contract A write `status:"active"`; do NOT reset `iteration` → Advance to next iteration (idempotency-checked).
- `goal_condition` divergence (unchanged): read from disk on any resume, never re-parsed; differing invocation value prints one-line "on-disk value governs" warning (mirrors Phase 0a-pre GENUINE-divergence pattern), continues.

### Advance to next iteration (idempotency-checked)

Read the last entry in `tickets[]` (if any):
- `tickets[]` empty OR last entry `status == "complete"`: no next-iteration entry yet → apply the IDENTICAL Contract A+B write Phase 12a "On no trigger, GOAL_MET false" performs (increment `open_goal.iteration`, append pending entry) - reused by reference.
- last entry `status` is `"pending"` or `"in_progress"`: a next-iteration entry was ALREADY appended (most likely by Phase 12a's advance-write interrupted before Phase 1 - the crash-mid-advance scenario). Do NOT increment `iteration` or append again - use the existing entry as-is. Prevents double-advance (silent skip/dupe of an iteration).

Either way, fall through to Phase 1 for the iteration corresponding to the last `tickets[]` entry.

### Fresh init (only via the branches above - never unconditional)

**Validation (refuse before Phase 1 on failure):**
- `goal_condition` missing → refuse: `"goal_mode=open_goal requires goal_condition to be declared. Re-invoke with goal_condition set."` Exit.
- `max_iterations` or `max_wallclock_min` missing/non-positive → refuse verbatim (trigger-catalog.md Hard-stop rule 5): `"goal_mode=open_goal requires max_iterations and max_wallclock_min to be declared - no unbounded default is permitted. Re-invoke with both fields set."` Exit.
- `dry_run`, if present, must be literal `true`/`false`; absent defaults to `false`. No refusal on absence.

**Contract C check (before any write):** apply the broadened Contract C check above (Fresh init is one of the three triggering create-paths) - refuse verbatim if `batch-state.json` is active/foreign-session/recent. Exit on refusal.

**On successful validation (Contract A fresh write):**
1. Initialize `.agentic/batch-state.json`: `mode:"open_goal"`, `batch_id:"open-goal-<ISO8601>-<4hex>"`, `wallclock_cap_min:<max_wallclock_min>`, `wallclock_started_at:now`, `tickets:[]`, `open_goal:{active:true, goal_condition:<string>, iteration:1, max_iterations:<int>, risk_declared:null, termination_reason:null, dry_run:<bool>}`.
2. `loop-state-$LOOP_KEY.json` NOT touched here - initialized normally at Phase 6 loop init exactly as any ordinary iteration (no open-goal fields).
3. Breadcrumb: `[phase: open-goal-init | goal_condition="<condition>" | max_iterations=<N> | max_wallclock_min=<M> | dry_run=<bool>]`.
4. Fall through to Phase 1 for iteration 1.

**Off-by-one note (Minor):** at init, `iteration=1` but `tickets=[]` (len 0) - SOLE momentary exception to `iteration==len(tickets[])`, closed the moment Phase 1 of iteration 1 appends the first synthetic entry. From Phase 1 of iteration 1 onward, the invariant holds continuously.

**Per-iteration ticket lifecycle.** Each iteration's synthetic `tickets[]` entry (`ticket_id:"<goal-slug>-iter-N"`, `cluster_id:"open-goal"`) follows the SAME transition-write pattern ordinary batch tickets use: `pending → in_progress` at Phase 1 start, `in_progress → complete` at Phase 12, or `→ blocked` via "Batch-mode escalation routing" (Phase 6). Every transition applies Contract A + Contract B.

**Interaction with top-level "Resume check (before setup)".** That check derives `LOOP_KEY` and reads `loop-state-$LOOP_KEY.json` before Phase 0, independent of this phase. A mid-iteration interrupted resume jumps to that iteration's resume entry point; Phase 0a-open-goal is never re-entered that session. Step 0 fires only on a normal Phase 0 pass reaching `goal_mode=open_goal`.

---

## Phase 0a-pre: Batch resume check

> Run this phase BEFORE the per-ticket Resume check below. This is the composition anchor: batch-level resume picks the ticket cursor first; the per-ticket Resume check then runs unmodified scoped to that ticket's branch and its own `loop-state-$LOOP_KEY.json` (`LOOP_KEY` derived from the picked ticket id).

**Trigger:** Phase 0 normalization produced ≥ 2 entries (same trigger as Phase 0a). Skip otherwise.

**Single-ticket wallclock carve-out.** Single-entry invocations bypass this phase entirely - no `.agentic/batch-state.json` is read or created - EXCEPT when `max_wallclock_min` is declared on a single-entry invocation with no `goal_mode`. In that case: apply the Contract C refusal check (broadened per the Contract C definition above) ONLY - do NOT also run the separate N=1 foreign-batch warning first; both checks share the identical trigger (active + different session + ≤10min), so the softer warning first would be dead code (Contract C refusal always overrides any yes/proceed). This differs from the ordinary N=1 path, which never creates batch-state and never needs Contract C. On success (Contract A fresh write): create `.agentic/batch-state.json{mode:"single_ticket_capped", tickets:[{ticket_id:<the one entry>, status:"pending", cluster_id:null, depends_on:[]}], wallclock_cap_min:<max_wallclock_min>, wallclock_started_at:now}`. **This is the ONLY N=1 path that creates `batch-state.json`.**

**Read** `.agentic/batch-state.json` if present. Apply the decision table below.

| `batch-state.json` state | Action |
|---|---|
| absent | Skip Phase 0a-pre. Fall through to the existing per-ticket Resume check, then Setup, then Phase 0a (which initializes `batch-state.json`). |
| `status=complete` | Print: "Prior batch complete; clearing." Delete the file. Fall through to the existing per-ticket Resume check. |
| `status=stalled` | Print stalled summary (tickets + reasons). Prompt: `resume / fresh / abandon`. On `abandon`: delete file and exit. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration (below) and pick next pending ticket. |
| `status=paused` | Print: `"Batch paused at operator request: [last_summary]."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=interrupted` | Print: `"Batch interrupted (reason: [interrupt_reason]). N completed, M pending/blocked."` Prompt: `resume / fresh`. On `fresh`: delete file and fall through. On `resume`: apply re-plan migration and pick next pending ticket. |
| `status=active` AND `updated_at > 10 min` ago | Treat as implicit interrupt. Same prompt as `interrupted` row. |
| `status=active` AND `updated_at ≤ 10 min` AND `session_id` matches current | Silent re-entry resume (rare; e.g. `/ds-implement-ticket` re-invoked within the same session). Pick next pending ticket from `tickets[]`. |
| `status=active` AND `updated_at ≤ 10 min` AND `session_id` is null/absent AND the CURRENT session's own id is ALSO null (self-ownership carve-out - see Contract A step 3) | Treat as self-owned: same as the row above (silent re-entry resume). Do NOT force-takeover-prompt or refuse - on a harness that cannot produce a matching session id, two nulls are indistinguishable by construction, so this is the only branch that lets such a harness resume its own batch at all. |
| `status=active` AND `updated_at ≤ 10 min` AND (`session_id` differs OR (`session_id` is null/absent AND the CURRENT session HAS its own non-null id, i.e. the self-ownership carve-out row above does NOT apply)) | If Phase 0 produced ≥ 2 entries: refuse with the verbatim Contract C message. If Phase 0 produced exactly 1 entry: see "N=1 foreign-batch warning" below; this row does not apply (Phase 0a-pre runs only when Phase 0 produced ≥ 2 entries). For N≥2 force-takeover prompts: print `"WARNING: another session (session_id=<X>, updated_at=<Y>) may still be active. Force takeover? (yes/no). Identify the live session via .agentic/batch-state.json updated_at."` and require explicit operator confirmation. |
| Parse failure | Print warning. Prompt: `delete-and-fresh / abort`. On `abort`: exit. On `delete-and-fresh`: delete file and fall through. |
| Inconsistent pair (`batch-state.json` says `active`, the PICKED ticket's own `loop-state-$LOOP_KEY.json` says `interrupted`) | Trust the non-active file. If both are stale-active (>10 min), treat as implicit interrupt for both. Scope this row to the picked ticket's keyed file only - another ticket's keyed file is not part of this pair and must not be consulted. |

**Move ordering hazard (resume case).** On resume, `batch-state.json.tickets[]` is the authoritative ticket cursor and supersedes any Phase 0 output produced in the resuming session. If the operator re-supplied input, compare Phase 0 entries[] against on-disk tickets[]:

- **SUBSET match (all tickets[] IDs are present in entries[], but entries[] has extras):** this is NOT a hazard. The extras were deferred or excluded at original triage time. Note: extras beyond the original deferred set that were not part of the original input are not auto-added on resume - surface them to the operator or run them separately; they are never mis-run. Proceed silently with `batch-state.json.tickets[]` as the cursor.
- **GENUINE divergence (tickets[] contains IDs NOT present in entries[]):** surface the warning below.

```
WARNING: resumed batch tickets[] = [<list>] contain ticket IDs not present in this invocation's Phase 0 entries[] = [<list>].
The on-disk batch state takes precedence on resume. Continue resuming the prior batch, or abandon resume and use the new input?
(continue-resume / abandon-resume-and-use-new-input)
```

On `continue-resume`: discard Phase 0 output, use `batch-state.json.tickets[]`. On `abandon-resume-and-use-new-input`: delete `batch-state.json` and re-run Phase 0a from the new entries.

**Resume composition rule (binding).** If Phase 0a-pre confirms resume of an active batch, it sets the in-memory ticket cursor to the next pending ticket from `tickets[]` BEFORE falling through to the existing per-ticket Resume check. The per-ticket Resume check then runs UNMODIFIED but scoped to the picked ticket's branch and its own `loop-state-$LOOP_KEY.json`, with `LOOP_KEY` derived from the picked ticket id. The two state mechanisms compose: batch resume picks the ticket; per-ticket resume picks the phase within that ticket. They have non-overlapping scopes.

**Re-plan migration on resume.** When the operator confirms resume of any non-active batch state (`stalled`, `paused`, `interrupted`, or stale-`active` treated as interrupted):

1. `git fetch origin`.
2. For each ticket in `tickets[]` with `status` `pending` or `blocked`: re-fetch the tracker record. If the ticket has been merged elsewhere (per tracker status, or per `gh pr list --state merged --head <branch>` returning a non-empty result), append a `replan_log` entry `{ts, action: "drop_merged", ticket_id, detail}` and set the ticket's `status` to `skipped_already_merged`.
3. Run /ds-ticket-triage Phases 1-3 over the surviving pending/blocked tickets to re-sequence. Level 2 investigator (Phase 2b) is gated on `replan_count >= 2`: count `replan_log` entries with `action: "investigator_rerun"`; if the count is >= 2, spawn a real background investigator (including the functional-duplicate brief); otherwise run Level 1 only (conductor-direct). Append the `replan_log` entry `{ts, action: "investigator_rerun", ticket_id: null, detail: "replan #N"}` BEFORE spawning the investigator when it fires. Map the resulting lanes back to the surviving tickets' `cluster_id` and `depends_on` fields (array order); deferred or in-progress-excluded tickets discovered during re-plan are surfaced to the operator and excluded from tickets[].
4. All writes apply Contract A (per-write `session_id` gate) and Contract B (`replan_log[]` read-merge-write preservation). See "Batch state contracts" below.
5. Bump `status` back to `active`. Preserve `wallclock_started_at` from the prior batch (the wallclock cap is per-batch lifetime, not per-session - a batch resumed in a later session continues counting against the original `wallclock_started_at`).

Emit breadcrumb: `[phase: batch-resume | tickets_remaining=K]`.

---

## Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries)

<!--
Phase 0a manifest:
  Purpose: run /ds-ticket-triage Phases 1-3 (algorithm by reference) over the Phase 0
           entries[], surface triage results to the operator, map lane-assigned tickets
           to batch-state.json, then iterate per-ticket phases 1-12 in array order.
  Public API: reads Phase 0 entries[]; writes .agentic/batch-state.json tickets[]
              (lane-assigned only; deferred and in-progress-excluded are NOT written).
  Upstream deps: /ds-ticket-triage Phases 1-3 (algorithm reference - no copy);
                 investigator (Phase 2b Level 2, conditional on len(entries) <= 20);
                 Phase 0 entries[] (already normalized, no re-normalization).
  Downstream consumers: Phase 0a-pre (resume), Phase 12a (handoff), all per-ticket
                        phases (1-12) which iterate tickets[] in array order.
  Failure modes: soft-fail per ticket in Phase 1 metadata fetch; HEURISTIC_ONLY=true
                 when len(entries)>20; functional-duplicate defer prompts are
                 operator-gated (one prompt per pair after Phase 3).
-->

**Trigger:** Phase 0 normalization produced ≥ 2 entries.

**Skip:** Phase 0 produced exactly 1 entry. Mixed-form inputs that Phase 0 normalized down to a single entry count as single-entry and skip Phase 0a.

**Flow:**

1. **Run the /ds-ticket-triage planning algorithm (Phases 1-3) conductor-orchestrated.** Phase 0a feeds its OWN already-normalized `entries[]` directly into triage Phase 1 - triage Phase 0 is NOT re-run (entries are already normalized).

   - **Phase 1 (metadata fetch, conductor-direct, soft-fail):** for each entry, fetch priority, status, story_points, labels, components, assignee, and issuelinks from the tracker (same per-ticket fetch as /ds-ticket-triage Phase 1). Soft-fail per ticket (mark `fetch_failed: true` and proceed). Detect `terminal: true` (Done/Cancelled) and `in_progress: true` (active workflow state) per the /ds-ticket-triage Phase 1 rules.

   - **Phase 2a (DAG + cycle handling, conductor-direct):** build the dependency graph from `blocks`/`is-blocked-by` links, detect cycles (break at lowest-confidence link, defer both with `cycle_warning: true`). External deps noted but not used for lane assignment.

   - **Phase 2b conflict-surface analysis:** Level 1 is always conductor-direct (shared component/label overlap check). Level 2 applies when `len(entries) <= 20`: spawn ONE real background investigator with the full /ds-ticket-triage Phase 2b brief, including the functional-duplicate detection task (bar: "a reasonable engineer would implement them with exactly the same change"). When `len(entries) > 20`: set `HEURISTIC_ONLY=true` and proceed WITHOUT prompting - rationale: the batch was already committed via Phase 0, and prompting mid-initialization wastes operator context.

   - **Phase 3 (Rules 1-4, conductor-direct):** distribute surviving tickets across lanes using the /ds-ticket-triage Phase 3 consume-and-remainder pipeline. Lane cap is fixed at 3 on this path (`--lanes` override is not available for the /ds-implement-ticket integration path).

   The result is an in-memory `triage_result` containing:
   `{lanes[], deferred[], in_progress_excluded[], functional_duplicates[], conflict_warnings[], heuristic_only}`.

2. **Surface triage findings to the operator BEFORE building tickets[].** Present a structured summary covering:

   - **Functional duplicate warnings** (when `functional_duplicates[]` is non-empty): for each pair, print the ticket IDs and the one-sentence reason. Prompt the operator PER PAIR (after all lane assignments are known, since Phase 3 has already run):

     ```
     Functional duplicate detected: <A> + <B> - <summary>
     Both tickets appear to describe the same functional work.
     Action: (defer-first / defer-second / keep-both)
     ```

     On `defer-first`: add ticket A to `deferred[]`, remove it from its lane. On `defer-second`: add ticket B to `deferred[]`, remove it from its lane. On `keep-both`: no change. Do NOT recompute the lane distribution after a defer choice - surgically remove the deferred ticket from its lane only.

   - **Deferred tickets** (from Phase 3 Rule 1 + any operator-deferred duplicates): list each with its reason.

   - **In-progress tickets** (from Phase 1): list each. These are excluded from tickets[] and kickoff.

   - **HEURISTIC_ONLY notice** (when `HEURISTIC_ONLY=true`): "Conflict analysis: Level 1 only (component/label overlap; >20 tickets, investigator pass skipped). Functional-duplicate detection was also skipped."

   After surfacing, map ONLY the lane-assigned tickets to `tickets[]` (deferred and in-progress-excluded tickets are NOT written to tickets[]).

   Map in ARRAY ORDER: lane 1 first, lane 2 next, lane 3 last. Within each lane, chains are topo-sorted (blockers first); parallel tickets within the same lane are sorted priority-descending then ticket_id-ascending. Each entry:
   - `status: "pending"`
   - `cluster_id: "lane-N"` (where N is the lane number)
   - `depends_on: ["<prev-ticket-id>"]` (chain) or `[]` (parallel lane head or independent)

   No `merge_order` field. Array position is the execution cursor.

   Emit breadcrumb: `[phase: batch-triage | triage_algorithm=ticket-triage-phases-1-3 | N tickets | lanes=K | lane_cap=3 | deferred=P | excluded_in_progress=Q | heuristic_only=<bool>]`.

3. **Initialize `.agentic/batch-state.json`** (persistent batch cursor). First apply the Contract C concurrent-batch refusal: if the file already exists with `status=active`, a different `session_id`, and `updated_at` within the last 10 minutes, REFUSE with the verbatim Contract C message and exit. Otherwise, write the initial skeleton:
   - `schema_version: 1`
   - `session_id: <current>`
   - `batch_id: "<first ticket's TICKET_PREFIX>-batch-<ISO8601>-<4hex>"`
   - `status: "active"`
   - `tickets[]`: triage-derived executable cursor; contains only lane-assigned tickets (deferred and in-progress-excluded tickets are not included); in array order as described in step 2 above
   - `wallclock_started_at: now`, `wallclock_cap_min: <env AGENTIC_BATCH_MAX_WALLCLOCK_MIN or 90>`
   - `replan_log: []`
   - `created_at: now`, `updated_at: now`

   Atomic tmp+rename. Apply Contract A on the write (this is a fresh write so no prior `session_id`; the gate effectively passes).

4. Conductor iterates through tickets[] in array order (tickets[] contains only lane-assigned executable tickets; deferred and in-progress-excluded tickets were surfaced in step 2 and are not present), running existing per-ticket phases (1 → 12) for each ticket. **Per-ticket transition writes to `batch-state.json`** (each via Contract A + Contract B):
   - At ticket start: `status: "pending" → "in_progress"`, set `started_at`, update `updated_at`.
   - At ticket complete: `status: "in_progress" → "complete"`, set `ended_at`, `last_summary`, `pr_number`, `branch`.
   - At ticket block: `status → "blocked"` with detail in `last_summary`.
   - At ticket merged-elsewhere skip: `status → "skipped_already_merged"` with `replan_log` append.

**Persistent batch state lives in `.agentic/batch-state.json`. See Phase 0a-pre for the resume protocol.**

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
  Skeptic variant (completeness-only review per `content/commands/ds-brief.md` Section 6).
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

3. **New invocations (no in-flight state) hard-fail per architect plan.** Fresh `/ds-implement-ticket` invocations on Elevated tickets without a `qa_criteria` block in the Brief or architect plan emit a Critical Skeptic finding on the architect plan; the conductor does not proceed past Phase 3 until the architect plan supplies the block. The on-resume bypass option is exclusively for tickets that started before this requirement existed.

---

## Phase 1: Understand the ticket

(Setup has already resolved TRACKER. Execute exactly one of the sub-sections below.)

**Iteration:** Phase 1 runs once per `entry` in `normalized_input.entries`. The current `[TICKET_ID]` refers to `entry.ticket_id`. When `normalized_input.entries` is empty AND `normalized_input.freeform_task` is set, only the `TRACKER is none` sub-section executes, with `freeform_task` as the description. When `entries` is non-empty, the `TRACKER is none` sub-section is skipped regardless of TRACKER value.

When `normalized_input.additional_operator_context` is non-null, append it verbatim to every entry's downstream architect (Phase 3) and engineer (Phase 5) brief, prefixed with `"Additional operator context (applied to all entries):"`. This routes mixed-input residue into the per-entry brief without dropping operator intent.

### Per-ticket variable reset (binding, runs FIRST on every entry)

**Before the tracker sub-section dispatch below, clear every in-context variable that feeds the Phase 9 ticket-rework ledger write or the rework notice:**

```bash
# Phase 1: per-ticket variable reset (runs first on EVERY entry, before sub-section dispatch).
# These three have exactly one definition site each, on one path. A ticket that does not take
# that path inherits the previous batch ticket's value - see the table below.
RISK_CLASS=""
SKEPTIC_ROUNDS=""
QA_STATUS=""
```

**Why this is binding rather than housekeeping.** The conductor carries ONE variable scope across an entire batch; Phase 1 iterates per entry but nothing else in this command resets anything. Every one of these three variables has exactly one definition site on one path, so a ticket that does not take that path silently inherits the previous ticket's value. The failure is always an affirmative false statement, never an error:

| Variable | Set only on | Batch failure without this reset |
|---|---|---|
| `SKEPTIC_ROUNDS` | Phase 6 clean exit | Trivial ticket 2 inherits Elevated ticket 1's round count - the notice reports adversarial review that never happened. **It also disables the Phase 9 disk-fallback guards**, which are gated on `[ -z "$TRL_ROUNDS" ]` and never execute when a stale value is present. |
| `QA_STATUS` | Phase 6b (both branches) | Trivial ticket 2 skips Phase 6b entirely and inherits `PASS` - the notice reports that QA passed when no QA ran. |
| `RISK_CLASS` | Phase 2 declaration | Ticket 2 inherits ticket 1's class, or writes `""` if ticket 1 never set it - an empty slot the null-render rule forbids. |

This is the same hazard the Phase 9 write already hardens `pr_number` against by deriving it live rather than reading `$PR_NUMBER` (see "Ticket-rework ledger write"). `pr_number` can be re-derived from an external source; these three cannot, so they are reset at the per-ticket entry point instead. **Any future in-context variable that feeds the ledger or the notice belongs in this reset block** - the hazard is structural to a single scope spanning a batch, not specific to these three names.

**Full sweep of the Phase 9 write's external reads**, so a future editor can see the analysis rather than redo it. Every variable the write block reads without assigning locally, and why it is or is not exposed:

| Variable | Scope | Exposed to batch carry-over? |
|---|---|---|
| `RISK_CLASS`, `SKEPTIC_ROUNDS`, `QA_STATUS` | per-ticket, single definition path | **Yes** - reset above |
| `TICKET_ID` | per-entry, from Phase 1 iteration | No - re-bound on every entry by construction |
| `BRANCH_NAME` | per-ticket | No - Phase 4 resolves it "regardless of path", so every ticket re-sets it before Phase 9 |
| `GH_REPO`, `REWORK_DETECTION` | session constants from Setup | No - batch-scoped is correct for both |
| `PR_NUMBER` | per-ticket | Not read - the write derives `pr_number` live precisely to avoid it |

Clearing rather than leaving unset is deliberate: it makes the Phase 9 disk fallback for `SKEPTIC_ROUNDS` reachable (its `[ -z "$TRL_ROUNDS" ]` gate now passes on a ticket that never reached Phase 6), so the `ticket_id` and `loop_state.phase` guards actually run in the batch scenario they exist to prevent.

#### If TRACKER is `linear`

1. Call `mcp__linear__get_issue` with the ticket ID and `includeRelations: true`.
2. Read the full description — specifically the **Implementation**, **Files**, and **QA** sections.
3. Note any blocking tickets (`blockedBy`) — confirm they are done before proceeding.
4. Note the ticket type (feature vs bug) — this drives branch naming.
5. **Comment thread fetch.** Call `mcp__linear__list_comments` with the UUID `issueId` of the issue (graceful-skip if the tool name differs or the call fails). Collect all returned comment bodies. Scan each comment: if the body contains the string `"QA"` AND at least one of `FAIL`, `PARTIAL`, `BLOCKED`, `failed`, `re-work`, flag that comment as a prior-QA-failure comment. Accumulate flagged comments in `PRIOR_QA_COMMENTS` (array of comment bodies). Build `COMMENT_THREAD_SUMMARY` as the concatenation of all comment bodies, truncated to 2000 characters. If the call is not available or returns an error, set both to empty (graceful no-op).

#### If TRACKER is `jira`

1. Call `mcp__mcp-atlassian__jira_get_issue` with `issue_key: "[TICKET_PREFIX]-NNN"` and `fields: "*all"` to get the full issue including description and current status.
2. Read the full description — note any **Acceptance Criteria**, **Implementation Notes**, and **QA** content in the description or sub-tasks.
3. Note any blocking issues — confirm they are resolved before proceeding.
4. Note the issue type (Story, Bug, Task) — this drives branch naming.
5. **Comment thread parse.** Parse `issue.fields.comment.comments` from the EXISTING `jira_get_issue fields:*all` response fetched in step 1 above. **Do NOT make a second Jira API call.** The `comment` field is included in the default `fields=*all` response. For each comment, extract the plain-text content (collapse ADF nodes to text). Scan each comment: if the body contains the string `"QA"` AND at least one of `FAIL`, `PARTIAL`, `BLOCKED`, `failed`, `re-work`, flag that comment as a prior-QA-failure comment. Accumulate flagged comments in `PRIOR_QA_COMMENTS` (array of comment bodies). Build `COMMENT_THREAD_SUMMARY` as the concatenation of all comment bodies, truncated to 2000 characters. If the `comment` field is absent or empty, set both to empty (graceful no-op).

#### If TRACKER is `none`

No ticket to fetch. **Use `normalized_input.freeform_task` as the ticket content** for all downstream phases. The pre-existing operator prompt is superseded by Phase 0's freeform fast path. Set ticket type to "feature" unless the operator's description indicates otherwise. Set `PRIOR_QA_COMMENTS=[]` and `COMMENT_THREAD_SUMMARY=""`.

---

### Ticket-rework detection (per-entry, runs after the sub-section dispatch above)

**Anchoring (binding).** This step sits at the per-entry level, AFTER the three mutually exclusive tracker sub-sections above have dispatched - so it runs exactly once per entry regardless of which sub-section executed. The `TRACKER is none` sub-section only executes when `entries` is empty and `freeform_task` is set; anchoring detection inside any single sub-section would skip it for the other paths. Do not move it into one.

Detection makes **zero tracker calls and zero network calls** - it is a single local file read, so it behaves identically at `TRACKER=none` as it does with a tracker configured. `TRACKER=none` is in fact the case the ledger matters most for: there is no tracker comment thread to carry prior-attempt signal.

1. If `REWORK_DETECTION` is `false`, or the current `[TICKET_ID]` is null/empty: skip detection entirely. Set `PRIOR_ATTEMPTS = 0`, `IS_REWORK = false`, `PRIOR_COMPLETED = []`. Emit nothing.
2. Otherwise read `.agentic/ticket-ledger.jsonl` and collect every record whose `ticket_id` is an **exact string match** for the current `[TICKET_ID]`. Dedupe the collected records by `pr_number`, keeping the record with the **latest `opened_ts`** within each duplicate group (read-side dedupe is what makes the lockless append at Phase 9 safe - a benign duplicate collapses here rather than inflating the count). Latest-wins matters: a duplicate `pr_number` arises from a Phase 9 replay, and the later record is the one carrying the resolved `qa_status` and the higher `skeptic_rounds`. Keeping the earliest would show the operator the staler of the two.
3. Set `PRIOR_COMPLETED` to the deduped record set ordered by `opened_ts` ascending, `PRIOR_ATTEMPTS` to its size, and `IS_REWORK` to `PRIOR_ATTEMPTS >= 1`.
4. **Soft-fail, per line.** If the ledger is absent or unreadable, resolve to `PRIOR_ATTEMPTS = 0`. If an individual line is malformed, **skip that line and keep going** - a single partial write must not disable detection for every other ticket in the file. A missing or corrupt ledger must never block the ticket it exists to help with.

```bash
# Phase 1: ticket-rework detection (soft-fail; zero tracker/network calls - one local file read).
# Emits the deduped prior-attempt records, most recent last.
PRIOR_COMPLETED_JSON='[]'
PRIOR_ATTEMPTS=0
if [ "$REWORK_DETECTION" != "false" ] && [ -n "$TICKET_ID" ] && [ -f .agentic/ticket-ledger.jsonl ]; then
  # `-Rn` + `inputs` + `fromjson? // empty` parses PER LINE and drops only the lines that fail.
  # Do NOT use `-s` (slurp) here: slurp aborts the whole parse on the first malformed line, so
  # one partial write from a concurrent appender would silently disable detection for every
  # ticket in the file, permanently and with no operator signal. The ledger is written
  # locklessly and O_APPEND is not atomic over NFS, so a torn line is a real, expected input.
  #
  # `X=$(...) || X=default` puts the fallback on jq's own exit status and discards any partial
  # output. Do NOT use `$(jq ... || echo '[]')`: on an unreadable file some jq builds emit a
  # result AND fail, so the fallback would concatenate onto it.
  PRIOR_COMPLETED_JSON=$(jq -Rn --arg t "$TICKET_ID" '
    [ inputs
      | fromjson? // empty
      | select(type == "object" and .ticket_id == $t and (.pr_number != null)) ]
    | group_by(.pr_number)
    | map(max_by(.opened_ts // ""))
    | sort_by(.opened_ts // "")
  ' .agentic/ticket-ledger.jsonl 2>/dev/null) || PRIOR_COMPLETED_JSON='[]'
  [ -n "$PRIOR_COMPLETED_JSON" ] || PRIOR_COMPLETED_JSON='[]'
  PRIOR_ATTEMPTS=$(printf '%s' "$PRIOR_COMPLETED_JSON" | jq 'length' 2>/dev/null) || PRIOR_ATTEMPTS=0
  case "$PRIOR_ATTEMPTS" in ''|*[!0-9]*) PRIOR_ATTEMPTS=0 ;; esac
fi
if [ "$PRIOR_ATTEMPTS" -ge 1 ]; then IS_REWORK=true; else IS_REWORK=false; fi
```

`PRIOR_COMPLETED_JSON` is the shell-variable form of the conductor's in-context `PRIOR_COMPLETED` record set, matching the existing `$BRANCH_NAME` / `$GH_REPO` pattern used elsewhere in this command.

`group_by | map(max_by(...))` is used in place of `unique_by(.pr_number)` deliberately: jq's `unique_by` is `group_by | map(.[0])` over a stable sort, so it keeps the *earliest* member of each duplicate group - the opposite of what a replay duplicate calls for.

Regression coverage for this block lives in `bin/tests/test_ticket_rework_ledger.sh`.

**The REWORK notice.** When `IS_REWORK` is true, emit this at the conductor's first user-facing turn after Phase 1, before any spawn:

```
REWORK: ticket <ID> has <N> prior AE attempt(s) that opened a PR - prior work on this ticket may need verification.
  Last attempt: PR #<n> (<date>), risk <class>, <r> Skeptic round(s), QA <status>, <u> unit(s).
Risk floored to Elevated; architect and Skeptic briefed on the prior attempt.
Manual verification of PR #<n> is recommended.
[phase: rework-detected]
```

- `<n>`, `<date>`, `<class>`, `<r>`, `<status>`, `<u>` come from the **most recent** record in `PRIOR_COMPLETED` (the highest `opened_ts`); `<date>` renders that record's `opened_ts` as a date.
- **Null-render rule.** A null field renders `n/a` - never a bare `null`, never an empty slot. `<r>` renders `n/a` when `skeptic_rounds` is null (the prior attempt took the Trivial path and never entered the Skeptic loop). `<status>` is the one exception: it prefers the record's skip rationale (`skipped:<rationale>`) over `n/a`, because "QA never ran, and here is why" is exactly what an operator doing manual verification needs; only a genuinely absent `qa_status` with no rationale renders `n/a`. A Trivial-path prior record therefore reads `risk Trivial, n/a Skeptic round(s), QA skipped:Trivial path`.
- When `PRIOR_ATTEMPTS > 1`, append `(+<N-1> earlier: PR #<a>, #<b>)` to the `Last attempt:` line, listing the older attempts by PR number only. Only the most recent attempt is described inline.

This notice is **command-scoped**: it fires inside Phase 1, once per ticket, for this specific ticket. It is not one of the stacked session-start first-user-turn notices enumerated in `content/rules/conventions.md` and does not add to that count.

The notice's third line asserts an escalation. That escalation is applied at the risk-classification declaration point, in the Phase 3 architect brief, and in the Phase 6 Skeptic brief - see "Ticket-rework escalation" in each. Full rationale, schema, and limitations: `content/references/ticket-rework.md`.

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
- The project's `MEMORY.md` (already in context via the `@MEMORY.md` import in the project root `CLAUDE.md`, added by `/ds-init-project`) for architectural decisions and rationale; if the project maintains a custom decision log, read that too
- Any `[track]/AGENTS.md` files for tracks touched by this ticket - track-specific conventions, stack, and gotchas

Focus on understanding enough to make a solid plan - don't over-read.

**Investigator conditional:** If the task risk is **Low or above AND** the code area touched by this ticket is unfamiliar to the current session (files not yet read, subsystems not yet traced), spawn an `investigator` agent first. Pass its brief to the Architect in Phase 3. Skip this step if Phase 2 reads already covered the relevant area.

Trivial-classified tickets skip the investigator (not required); the shippable change is still performed by a worktree-isolated `engineer` (no Skeptic, no brief) per METHODOLOGY.md §Risk Classification - the conductor does not edit the shippable tree directly.

### Ticket-rework escalation: Elevated risk floor

**Applies at the risk-classification declaration point** - the classification the conductor declares here is what Phase 2b, Phase 3, Phase 5, Phase 6, and Phase 9 all consume, so the floor must be applied before that declaration is made, not retrofitted downstream. One consumer sits *upstream* of this point and is therefore not covered: Phase 0b's `qa.md` snapshot, which reads the classification before Phase 1 detection has run. See the known gap at the end of this section.

When `IS_REWORK` is true (Phase 1 detection found one or more prior PR-opening attempts on this ticket), the risk classification for this ticket is **floored to Elevated**. It is never Trivial and never Low, regardless of how small the change looks and regardless of any profile-level Low override that would otherwise apply (`relaxed`-profile single-file behavioral edits, the bounded 2-3-file override, UI-only copy, and so on). A ticket that already came back once is, by construction, a ticket where the previous classification was not conservative enough.

The floor raises the classification only. A ticket independently classified Elevated stays Elevated; the floor never lowers anything.

Apply the floor to the classification *before* it is declared in the next subsection, which is where `RISK_CLASS` is actually set.

Placing the floor here puts it upstream of the Phase 2b gate, which applies only when risk is Elevated - a floored ticket therefore correctly receives the pre-architect ambiguity scan it would have skipped as Trivial or Low.

**Known gap - the Phase 0b qa.md snapshot is not retroactive.** Phase 0b's `qa.md` snapshot is Elevated-only and runs *before* Phase 1, so it has already been skipped by the time the floor fires. A would-be-Trivial ticket floored to Elevated here therefore has no `.agentic/qa.md.snapshot-<ticket_id>`, and Phase 11b's `qa_md_diff` comes back empty for it. This is bounded and degrades gracefully - `wrap-ticket` already handles an absent snapshot - so the floor does not attempt to reach backwards and create one. The consequence is a missing qa.md-additions summary on floored tickets, nothing more.

This is a **command-scoped** trigger. It does not add an entry to the global Elevated-signal list in `content/sections/04-risk-classification.md`, and nothing outside `/ds-implement-ticket` reads it. When `REWORK_DETECTION` is `false`, `IS_REWORK` is always false and the floor never fires.

### Risk classification declaration (unconditional - runs on every ticket)

**This subsection is NOT gated on `IS_REWORK`, `REWORK_DETECTION`, or anything else. It runs for every ticket on every path**, including when the rework floor above did not fire and when the feature is switched off entirely. It is a sibling of the floor section, not part of it: the floor *adjusts* the classification, this *records* it.

Declare the risk classification and set:

```
RISK_CLASS="<Trivial | Low | Elevated>"     # post-floor
```

**When the declared classification is `Trivial`, also set:**

```
QA_STATUS="skipped:Trivial path"
```

**This is the only point in the command a Trivial ticket can record that rationale.** Phase 6b's skip branch carries the same string, but Phase 6b is unreachable on the Trivial path - "The Trivial path never enters Phase 6b" - so that branch only ever fires for an Elevated ticket with a non-null `qa_skip`. Setting it there alone would leave every Trivial ticket writing `qa_status: null`, and the notice rendering `QA n/a` for precisely the record `content/references/ticket-rework.md` uses as its canonical worked example.

Both assignments are unconditional in the sense that matters: they do not depend on the rework feature being active. A ticket whose ledger write is later skipped simply never reads them.

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

**Prior ticket context (inject only when `COMMENT_THREAD_SUMMARY` is non-empty):**

Append the following section to the architect spawn brief when `COMMENT_THREAD_SUMMARY` is non-empty:

```
## Prior ticket context

The following is a summary of comments on this ticket (up to 2000 characters):

[COMMENT_THREAD_SUMMARY]
```

When `PRIOR_QA_COMMENTS` is non-empty, prepend the following callout immediately before the comment summary:

```
PRIOR QA FAILURES DETECTED. The following comments indicate prior QA failures on this ticket:
[bullet list of each PRIOR_QA_COMMENTS entry]

Factor these into the implementation plan. Ensure the plan explicitly addresses each prior QA failure point.
```

Omit this entire section when `COMMENT_THREAD_SUMMARY` is empty (TRACKER=none, empty thread, or comment fetch failed).

**Ticket-rework callout (inject only when `IS_REWORK` is true) — independent top-level block:**

**This block is gated SOLELY on `IS_REWORK`. It is deliberately NOT part of the "Prior ticket context" section above and is NOT subject to that section's omit rule.** The two signals are unrelated: "Prior ticket context" is omitted when `COMMENT_THREAD_SUMMARY` is empty, which is exactly the `TRACKER=none` case - and `TRACKER=none` is precisely where the ledger is the only prior-attempt signal that exists, because there is no comment thread to carry one. Nesting this callout inside that section would drop it in the single case it matters most. Inject it whenever `IS_REWORK` is true, whether or not "Prior ticket context" was injected, and in either order.

Append the following block to the architect spawn brief when `IS_REWORK` is true:

```
## PRIOR ATTEMPT(S) OPENED A PR - THIS IS REWORK

AE has already carried this ticket to an opened PR [PRIOR_ATTEMPTS] time(s). The most recent attempt:

- PR: #[pr_number] ([opened_ts])
- Risk class: [risk_class]
- Skeptic rounds: [skeptic_rounds, or "n/a" when null]
- QA: [qa_status, or its "skipped:<rationale>" value, or "n/a"]
- Units: [unit_count]
[when PRIOR_ATTEMPTS > 1: - Earlier attempts: PR #<a>, #<b>]

Something about the prior attempt was insufficient, OR this ticket was always going to need
another wave - AE cannot tell which, and does not guess. Treat it as the former.

Your plan MUST:
1. Identify what the prior attempt missed, got wrong, or left incomplete. Read the prior PR's
   diff before planning. State your conclusion explicitly, even if it is "the prior attempt
   looks complete and this appears to be planned continuation" - that is a finding, not a
   non-answer, and the Skeptic will grade it.
2. Include at least one `qa_criteria` scenario that exercises the specific regression or gap
   you identified. A rework plan whose QA criteria do not cover the failure mode that brought
   the ticket back has not addressed the rework.
```

Apply the null-render rule when filling this block: a null `skeptic_rounds` renders `n/a`; a null `qa_status` renders its `skipped:<rationale>` value when one exists, otherwise `n/a`. Never emit a bare `null` into a spawn brief.

**Architect plan Skeptic review (mandatory):** After the Architect returns its plan, spawn a Skeptic with the "Document synthesis, architecture, and planning" adversarial brief plus the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5) - this is a pre-implementation review, so field 6 (diff under review) lists the file paths the plan proposes to modify rather than a git diff, field 1 (architect plan) is the plan itself under review, and field 2 (Brief/Plan artifact) is `n/a - Skeptic-on-plan (Brief authoring gated on this sign-off)` when no Brief exists yet. Do not proceed to Phase 3b or Phase 4 until the Skeptic grants sign-off. If the Skeptic-approved plan contains a non-empty "Open questions" section, resolve every genuine Open Question before proceeding - see `METHODOLOGY.md` for resolution paths. A plan with only a "Deferred defaults" section (empty or non-empty) and an empty "Open questions" section does not block. For the full adversarial brief menu, see `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

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

**Read the orchestration-planner's structured JSONL block** (the `## Task entries (machine-readable)` section at the end of the plan output). For each entry in that block, append a `pending` entry to `.agentic/tasks.jsonl`. Write tasks in dependency order - independent tasks (empty `depends_on`) first, dependent tasks after. Each entry must include the fields from the schema: `task_id`, `session_id`, `ticket_id`, `unit_slug`, `status: pending`, `depends_on`, `created_at`, `updated_at`, `author_model` (set to `null` at init; populated by the conductor at engineer spawn in Phase 5 with the model id the engineer runs under), and the full `inputs` object (`description`, `acceptance_criteria`, `files_in_scope`, `quality_cmd`, `repo_path`, `base_branch`).

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

See `content/references/planning-artifacts.md` §Gate semantics for where this step sits relative to the Skeptic-on-Brief.

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

**Module manifests:** Files modified must carry module manifests per `~/DinoStack/.claude/skills/agentic-engineering/rules/module-manifest.md` when non-trivial. Skeptic enforcement is tiered in Phase 6: missing manifests are flagged as Minor (does not block sign-off), stale manifests as Major (blocks sign-off absent a compelling documented reason to defer), and stale manifests whose inaccuracy could mislead a caller on a correctness or security path as Critical. When modifying an existing manifested file, update the manifest in the same change if purpose, public API, upstream dependencies, downstream consumers, or failure/retry semantics shift.

### If work is a single logical unit (or units must be sequential):

**Tracker writeback (W1):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_IN_PROGRESS`, `forward_only_guard: true`. Fire-and-forget; do NOT wait for return. Continue immediately to the engineer spawn below.

[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS]

Spawn one `engineer` agent per unit in sequence. Each agent prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, filling in fields from the architect's plan / orchestration-planner output for this unit
- The plan for this unit: if Phase 3b ran, use the orchestration-planner's output for this unit; if Phase 3b was skipped, use the architect's plan for this unit
- The branch name to work on
- The repo path: `$REPO`
- Instruction to run `$QUALITY_CMD` from the repo root before finishing and fix any errors

**Prior ticket context (inject only when `COMMENT_THREAD_SUMMARY` is non-empty):**

When `COMMENT_THREAD_SUMMARY` is non-empty, append the following section to the engineer spawn brief:

```
## Prior ticket context

The following is a summary of comments on this ticket (up to 2000 characters):

[COMMENT_THREAD_SUMMARY]
```

When `PRIOR_QA_COMMENTS` is non-empty, prepend the following callout immediately before the comment summary:

```
PRIOR QA FAILURES DETECTED. The following comments indicate prior QA failures on this ticket:
[bullet list of each PRIOR_QA_COMMENTS entry]

Ensure your implementation addresses each prior QA failure point explicitly.
```

Omit this entire section when `COMMENT_THREAD_SUMMARY` is empty (TRACKER=none, empty thread, or comment fetch failed).

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

- `worktree_setup`: `{ branch_name, base_branch, worktree_path, create_commands }` — the engineer creates the branch and worktree (or in-place branch if no worktree) using these literal git commands. The conductor populates `branch_name` and `base_branch`; `worktree_path` is set when worktree isolation is in use, otherwise null; `create_commands` is the literal `git -C $REPO checkout -b ...` (or `git -C $REPO worktree add ...`) sequence. The engineer return shape echoes `worktree_setup.worktree_path` back as `worktree_path` so Phase 8 cleanup can resolve the worktree even after branch renames.
- `quality_gates`: `{ command, cwd, must_pass: true }` — the engineer runs `$QUALITY_CMD` itself before declaring done. The conductor never re-runs gates on this path (Phase 7 verifies from the return shape; see Phase 7).
- `git_finalization`: `{ commit_message_template, files_to_stage, push }` — the engineer commits and pushes. `push: true` for the Elevated path. `commit_message_template` MUST include a `Signed-off-by: $SO_NAME <$SO_EMAIL>` line populated from `git config user.name` / `git config user.email` (required for DCO CI gate). When developer identity is confirmed (non-provisional - `agentic-identity show` emits no `provisional:   true` line), also include a `Developer: <handle>` trailer. Use the `NL=$'\n'` pattern for multi-line templates (not `<<'EOF'` heredoc, which blocks variable expansion). Guard: if `git config user.email` returns empty, surface a warning and skip the commit.

Extend `completion_conditions` to include: "quality_gates.command exits 0", "commit and push completed per git_finalization", and "quality_gate_results captured in return".

The engineer return shape on the Elevated path now requires `quality_gate_results: { lint, typecheck, test, smoke_test, raw_output }` (with `raw_output` capped at 4000 chars). This mirrors the binding contract documented in `content/agents/engineer.md`.

**Phase 7 fail path note.** When `DEBUGGER_ON_FAILURE` is `true` (see Setup) and the path is Elevated, Phase 7's gate-failure path interposes a Debugger diagnosis step before the next engineer fix pass. See Phase 7 "If the gate fails" for the full flow.

**Trivial-path solo engineer carve-out.** Trivial solo engineer spawns keep the lightweight contract: no heavy `worktree_setup`/`quality_gates`/`git_finalization` contract block, no `quality_gate_results` return field, no Skeptic, no brief file. But the actor is a worktree-isolated `engineer`, not the conductor: branch creation, the (lightweight) quality check, the commit, and the push are all performed by the Trivial engineer inside its own worktree (`isolation: "worktree"`). The conductor never edits the shippable tree directly. Only the heavy Elevated ceremony is dropped - the actor and execution location are the worktree engineer.

**Tracker writeback (W1 — Trivial path):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_IN_PROGRESS`, `forward_only_guard: true`. Fire-and-forget; do NOT wait for return. Continue immediately to the Trivial engineer spawn.

[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS | path: trivial]

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Task-state reads (multi-unit only, when `.agentic/tasks.jsonl` is in use):**

Before spawning each worker: check the task's `depends_on` field in the file. All dependency `task_id`s must have `status: done` before this task can start. Update the task entry from `pending` -> `in_progress` immediately before spawning. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path if using worktree isolation, null otherwise), `branch_name` (the branch the worker will operate on), and `author_model` (the model id the engineer will run under, recorded so reviewer spawns - Skeptic, security-auditor - can select a different model when role-model routing is active; set to `null` when the model is unknown or role-model routing is off).

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

**Per-unit Skeptic spawning (when `SKEPTIC_STRATEGY: per-unit`).** After each unit's engineer returns `done`, spawn a Skeptic for that unit's diff (unit worktree diff against `BASE_BRANCH`), including the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5, field 6 = the unit's worktree diff) alongside the adversarial brief. Per-unit Skeptics for independent units can be spawned in parallel (single message - they are reviewing non-overlapping diffs). Each unit's Skeptic integrates with the P0 persistence loop (Engineer -> Skeptic -> fix loop within the unit's worktree). A unit is `status: done` only after its Skeptic signs off, not after the engineer's first commit. After each unit's Skeptic/QA loop resolves, update the task entry to terminal status and populate `loop_state`, `outputs.skeptic_status`, and `outputs.skeptic_findings_count`.

**Integration Skeptic (when `SKEPTIC_STRATEGY: integration`).** Do NOT spawn per-unit Skeptics. After all units' engineers return done, merge all unit branches onto a scratch integration branch (not `FEATURE_BRANCH` - the merge is provisional until the Skeptic signs off). Spawn one integration Skeptic reviewing the combined diff from `BASE_BRANCH` to the scratch integration branch, including the Global-context input set (`## Global-context inputs` block per Section 4.5, field 6 = the combined diff). The integration Skeptic IS the Phase 6 gate for this strategy (see Phase 6 guard below). The orchestration-planner's independence annotation (added when the planner classified units) becomes the adversarial brief hint: pass it to the integration Skeptic so it knows the expected interaction boundaries.

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
if [ -z "$(git -C ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} status --porcelain 2>/dev/null)" ]; then
  git -C $REPO worktree remove ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} --force
  git -C $REPO branch -d ${FEATURE_BRANCH}-${unit_slug}
else
  echo "WARNING: worktree ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} has uncommitted changes; skipping cleanup"
fi
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
- **When `IS_REWORK` is true:** the same `## PRIOR ATTEMPT(S) OPENED A PR - THIS IS REWORK` block injected into the Phase 3 architect brief, verbatim (same fields, same null-render rule), followed by: `Verify that the failure mode which brought this ticket back is actually addressed. Reviewing only whether the new diff is internally sound is insufficient - a diff can be clean on its own terms and still repeat or fail to fix what the prior attempt got wrong. Read the prior PR's diff. Withholding sign-off because the new diff does not demonstrably close the prior gap is a correct outcome.` Gated solely on `IS_REWORK` - this bullet is independent of `COMMENT_THREAD_SUMMARY` and fires at `TRACKER=none`.
- **The Global-context input set** (`## Global-context inputs` block, required per `content/references/skeptic-protocol.md` Section 4.5): field 1 = `$ARCHITECT_PLAN_PATH` (or its `n/a - <reason>` per the enumerated set if the architect was skipped); field 2 = `$BRIEF_PATH` (or `n/a - single Elevated unit (no Brief required by the promotion gate)` when no Brief tier applied); field 3 = the unit's `qa_criteria` block verbatim (from the Brief, or the architect plan if no Brief; `n/a - <reason>` only when genuinely absent per the Phase 0a-pre migration); field 4 = the per-consumer impact table verbatim if the architect plan produced one for a shared-utility surface, else `n/a - non-shared-utility surface (importer count below 5 threshold)`; field 5 = the related files list from the architect plan / orchestration-planner unit boundary; field 6 = the full diff command already listed above.

For the full adversarial brief menu (security, logic, performance, data integrity, etc.), see `~/DinoStack/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Ticket-rework tier escalation.** When `PRIOR_ATTEMPTS >= 2` — two or more prior attempts, not one — declare `Tier: 3` for this Skeptic spawn and pass an explicit `model: opus` on the Agent tool call. At `PRIOR_ATTEMPTS == 1` the tier is unchanged (Tier 2, role default, omit the model param): one prior attempt gets the callout and the Elevated floor, not an Opus Skeptic. A ticket that has come back twice has had a review-depth problem, not just an implementation problem.

This trigger is **command-scoped and advisory-only — there is no mechanical backstop.** `hooks/enforce-tier.py` backstops Tier-3 by matching the five *global* escalation signals against the spawn brief's text; `PRIOR_ATTEMPTS >= 2` is conductor-computed state that appears in no marker pattern the hook recognises, so the hook will neither detect this trigger nor deny a sub-Opus spawn under it. The conductor's explicit `model: opus` is the only enforcement. Omitting it silently downgrades the review with no error anywhere. This also does not add to the Mandatory Tier-3 escalation category count in `content/references/risk-config-and-tiers.md`.

Known cost: a genuinely multi-wave ticket (big, always needed three passes, never actually regressed) draws an Opus Skeptic from its third wave onward, because `PRIOR_ATTEMPTS` cannot distinguish that from a ticket that came back twice. This is accepted; if it proves expensive the fix is raising this threshold, not adding a discriminator. See `content/references/ticket-rework.md` §Known limitations.

**Findings handling - loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state-$LOOP_KEY.json` (create `.agentic/` directory if absent). **Use atomic write: write to `.agentic/loop-state-$LOOP_KEY.json.tmp` first, then rename to `.agentic/loop-state-$LOOP_KEY.json`.**

**Full P2 schema (extends the P0 in-context schema with cross-session resume fields):**

```json
{
  "schema_version": 1,
  "session_id": "<current session uuid or null>",
  "ticket_id": "<string | null>",
  "loop_key": "<the resolved key this file is stored under>",
  "resume_count": 0,
  "last_phase_iteration": null,
  "branch": "<string>",
  "repo": "<string>",
  "base_branch": "<string>",
  "status": "active",
  "last_updated": "<ISO8601>",
  "interrupted_at": null,
  "interrupt_reason": null,
  "last_phase": "skeptic",
  "last_phase_action": "spawned",
  "loop_state": {
    "phase": "skeptic",
    "iteration": 1,
    "max_iterations": 3,
    "tier": 2,
    "findings_log": [],
    "qa_failures_log": [],
    "last_engineer_summary": null,
    "termination_reason": null
  }
}
```

**Field notes:**
- `loop_key` is the resolved `LOOP_KEY` this file is stored under - i.e. the file is at `.agentic/loop-state-<loop_key>.json`. **Required on every file this version writes.** It is recorded so that no reader ever re-derives the key: readers use this field, which permanently removes the branch-name temptation (the workflow deletes the branch after merge, so a later rework would derive the same slug and two attempts would look like one). Readers tolerate absence - a file with no `loop_key` is a legacy file and takes the Resume check's legacy-adoption path. If the field is present but disagrees with the filename's key, the filename wins for selection and the field wins for the session's in-context key after an accepted resume; print one warning and do not auto-repair.
- `resume_count` is an integer, default `0`, incremented once per accepted resume - including a legacy adoption. `content/references/planning-artifacts.md` already depends on it ("resume-count tracked in the loop-state file" - loop-key: prose, a verbatim quotation of that document's wording, not a path assertion). Adopted legacy files start at `0` regardless of how many times they were resumed before this version, which is a bounded one-time undercount.
- `last_phase_iteration` is an integer or null, written by the Phase 10a CI fix loop to record which cycle of that loop the file was written at. It was already written by that loop before it was declared here.
- `session_id` is the conductor session uuid - specifically **`$CLAUDE_CODE_SESSION_ID`** (the same value `content/references/events-log.md` binds MUST-equal to the Stop hook's `payload.session_id`), and explicitly **NOT** the `<ISO-date>-<4hex>` id form used for `tasks.jsonl` entries. Every conductor write to `loop-state-$LOOP_KEY.json` includes this field; every write applies Contract A's per-write `session_id`-mismatch abort gate. A harness that cannot produce an id matching this namespace MUST write `session_id: null` rather than synthesizing a value in the wrong namespace (see Contract A's self-ownership carve-out for how writers and readers treat a null value on such a harness). Readers tolerate absence for back-compat with state files written by prior versions. See "Batch state contracts" above.
- `last_updated` is the per-turn liveness timestamp written ONLY by `hooks/lib/state-mark.js`'s `refreshLiveness` (via the Stop hook's `--cadence=turn` dispatch) or by the conductor's own Contract A writes; it is never written by the terminal interrupted-mark (`markInterrupted`, on the SessionEnd hook `hooks/session-end-wrap.js`). `batch-state.json`'s equivalent field is named `updated_at`, not `last_updated` - readers falling back to the wrong file's field name will silently see a stale/absent value. `updated_at` is the CANONICAL field on `batch-state.json` (every staleness gate keys on it, per the batch-state schema's Field semantics above), not a fallback; `last_updated` remains canonical on `loop-state-$LOOP_KEY.json` only.
- `loop_state.tier` is written at loop initialization from the conductor's declared tier for the Skeptic spawn (default 2, per the existing tier-declaration prose). Readers treat an ABSENT `tier` key (pre-DS-87 state files) as `"2 (default, undeclared)"` - the same back-compat pattern used for `session_id` above.
- `last_phase` is the **authoritative resume key** - used exclusively for resume entry selection. Do NOT use `loop_state.phase` for this.
- `loop_state.phase` reflects which loop is active (skeptic or qa) and is used only to reconstruct in-context LOOP_STATE on resume.
- `last_engineer_summary` must be written verbatim to disk when an Engineer returns, capped at 2000 characters if longer. This allows resume to reconstruct the brief for the next Skeptic spawn.
- `status` values: `"active"` (loop running), `"interrupted"` (SessionEnd hook or crash - see Contract D; the Stop hook only refreshes `last_updated` liveness on `--cadence=turn` and never sets this value), `"complete"` (loop exited cleanly), `"stalled"` (cap_reached/convergence_failure/blocked escalation).

**Write triggers for Phase 6 Skeptic loop (overwrite using atomic write at each transition):**
- At loop initialization (before first Skeptic spawn): `last_phase=skeptic`, `last_phase_action=spawned`. The conductor also records its declared tier for this Skeptic spawn into `loop_state.tier` at this same write.
- After Skeptic returns, before Engineer spawn: `last_phase=skeptic`, `last_phase_action=returned`
- After Engineer spawned (fix pass): `last_phase=engineer`, `last_phase_action=spawned`
- After Engineer returns: `last_phase=engineer`, `last_phase_action=returned`; update `loop_state.last_engineer_summary` (verbatim, capped 2000 chars)
- After each `findings_log` update (Steps 2, 3, 5): overwrite with updated `loop_state`
- On clean termination: set `status=complete`, `loop_state.termination_reason=clean`
- On stalled termination (cap_reached, convergence_failure, blocked): set `status=stalled`

**Stability contract:** `.agentic/loop-state-$LOOP_KEY.json` is a stable contract from P0 onward. Any schema change must consider resume readers.

The file is overwritten (not appended) on each iteration state update and at loop exit with `termination_reason` set. It is not deleted on clean termination - the final state is the post-mortem record until **the next loop invocation on the SAME ticket** (i.e. the next invocation that derives the same `LOOP_KEY`) overwrites it. Under per-ticket keying an invocation on a *different* ticket writes a different file and does not overwrite this one; a completed keyed file is therefore reclaimed only by that same ticket's next run, or by Phase 12. Whether `.agentic/` is gitignored is deferred to project convention.

Emit the inline breadcrumb:

```
[loop: skeptic | iteration 1/3 | open findings: -]
```

**Loop entry (repeat until termination):**

**Step 1.** Spawn `skeptic` with adversarial brief. On iteration 2+, prepend the "Prior iteration findings" block to the brief (see `skeptic-protocol.md` Section 4 - findings_log entries map directly to the preflight list format). Format re-invocations (up to 3 per `skeptic-protocol.md` Section 11) do NOT increment `iteration`.

**Telemetry emit (V1):** Bracket the Skeptic `Agent` tool call with:
```
# Every agentic-emit call site exports the resolved key so the event's `phase`
# resolves from THIS ticket's own .agentic/loop-state-$LOOP_KEY.json. Without it, agentic-emit
# falls back to its unset-env rows: with 2+ keyed files present (the whole
# point of this design) it must answer "unknown", so every event in a
# multi-ticket checkout would lose its phase.
export AGENTIC_LOOP_KEY="$LOOP_KEY"
agentic-emit spawn_start skeptic - '{"tier":<tier>,"tool_use_id":"<toolu_id_if_known_else_null>","session_uuid":"'"$CLAUDE_CODE_SESSION_ID"'"}'
# ... Agent tool call ...
# After return, parse subagent transcript for tokens/wall_seconds:
USAGE="$(agentic-parse-subagent-usage <session_uuid> <agent_id>)"
agentic-emit spawn_complete skeptic - "$(printf '{"tier":<tier>,"agent_id":"<agent_id>","status":"ok","session_uuid":"%s",%s}' "$CLAUDE_CODE_SESSION_ID" "${USAGE#\{}")"
```
`export AGENTIC_LOOP_KEY="$LOOP_KEY"` applies at **every** `agentic-emit` call site in this document, not just this one - Phase 6, Phase 6b, the calibration/meta-review emits, and the Phase 7/10a fix-engineer brackets. See `METHODOLOGY.md §Events log` for the full event schema. All conductor emits (`spawn_start`, `spawn_complete`, `meta_review_complete`, `tool_failure_workaround`) must include `"session_uuid":"$CLAUDE_CODE_SESSION_ID"` in the `data` JSON object; the shell expands `$CLAUDE_CODE_SESSION_ID` at emit time. (`conductor_direct` is deprecated and no longer emitted.)

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
- Overwrite `.agentic/loop-state-$LOOP_KEY.json` with the updated LOOP_STATE.

**Meta-divergence surfacing (in-session scan).** Before each turn boundary entering Phase 6 (loop initialization) and after returning from a Worker (after Step 5), the conductor scans `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For any event with non-empty `data.divergence.critical_missed` or `data.divergence.major_missed`, emit a META-DIVERGENCE line at the next user-facing turn boundary and append `original_task_id` to the tracker file:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Tracker append is a single line per `original_task_id`; the file is created if absent (`.agentic/.meta-divergence-surfaced`, gitignored under the `.agentic/` umbrella). Minor-only divergences are NOT surfaced inline. See `content/references/skeptic-protocol.md` Section 14 for the full specification.

**Step 3. Termination check:**
- If no Critical or Major findings: auto-close all `findings_log` entries with `status: open` or `status: addressed` (set to `closed`). Set `termination_reason: clean`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Set `SKEPTIC_ROUNDS` to this loop's final `loop_state.iteration` (in-context variable; see below). **Then run "Learning extraction" below, followed by "Calibration emit + meta-Skeptic sampling".** Exit loop cleanly. Proceed to Phase 6b.

**`SKEPTIC_ROUNDS` must be captured here, at Phase 6 clean exit - not read back later.** Phase 6b initializes its own loop state **overwriting the Phase 6 state** with `phase: qa, iteration: 1`, and Phase 6b fires for every Elevated unit with `qa_skip == null` - the common case. By the time Phase 9 runs, `loop_state.iteration` on disk is the QA iteration count, not the Skeptic round count: a ticket with 3 Skeptic rounds and a first-pass QA reads back as `1`. Capturing at clean exit is the same pattern Phase 6b already uses for `QA_RAN_AND_PASSED`. The Trivial path never reaches Phase 6, so it never sets `SKEPTIC_ROUNDS`, which is exactly why the ledger's `skeptic_rounds` is legitimately null there.
- If `iteration == max_iterations` AND Critical or Major findings remain: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection below. Escalate to human (see Escalation section below). Phase 6b does NOT run.
- If any Critical finding carries `re_raised: true` (same finding re-raised after a claimed fix): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection below. Escalate to human. (This overrides the 2-re-route rule in `skeptic-protocol.md` Section 5 - see that section for the override note. One re-raise after a claimed fix is sufficient within the loop.)

**Learning extraction (clean exit only).** When Step 3 takes the clean-exit branch (sign-off granted), the conductor spawns `learning-extractor` BEFORE calibration emit and meta-Skeptic sampling. This captures durable fix-pattern learnings from the resolved `findings_log` before the loop state is cleaned up.

**Spawn:** `learning-extractor` (Tier 1, background, fire-and-forget).

**Spawn brief inputs:**
- `ticket_id`: the resolved ticket id.
- `findings_log`: the final resolved `findings_log` from `.agentic/loop-state-$LOOP_KEY.json` (all entries with `status: closed` or `status: addressed`).
- `merged_diff`: `git -C $REPO diff origin/$BASE_BRANCH..HEAD` (the full ticket diff).

**Failure semantics:**
- `learning-extractor` failure NEVER blocks the calibration emit, meta-Skeptic sampling, or Phase 6b. Soft-fail silently.
- The conductor does NOT wait for `learning-extractor` to return. It is fire-and-forget.
- On return (asynchronous): if `learning-extractor` returns with a valid JSON shape, the conductor stores the `learning_ids[]` for Phase 11b and prints `operator_summary` to the user at the next turn boundary. If `skipped_reason` is populated (zero-substance, etc.), the conductor notes it silently.
- If `learning-extractor` does not return before Phase 11b, `wrap-ticket` reads whatever entries exist in `.agentic/learnings.md` (may be partial or empty). No warning needed.

**Mandatory capture-sweep declaration (clean exit only).** After spawning `learning-extractor` (fire-and-forget) and BEFORE the calibration emit, the conductor MUST sweep for any mandatory-trigger event (per `content/references/conductor-operating-rules.md §learnings-agent`) that occurred during this task but was not yet evaluated. For each outstanding trigger, emit a `Capture: MUST/SKIP` declaration in the conductor's user-facing output. Apply guardrail-first precedence per `content/references/capture-classification.md` before writing any entry. A trigger with no declaration is a protocol gap. This sweep is the last-resort catch before the Stop-hook backstop fires.

**Calibration emit + meta-Skeptic sampling (clean exit only).** When Step 3 takes the clean-exit branch (sign-off granted), the conductor performs the following before declaring the unit complete:

1. **Build the calibration data block.** Compute `diff_lines` from the reviewed diff (`git -C $REPO diff origin/$BASE_BRANCH..HEAD | wc -l`, or the unit-scoped equivalent for fan-out). Tally `findings_count` from the final Skeptic round's findings list (Critical / Major / Minor counts). Read `iteration` from the loop state.

2. **Emit the extended `spawn_complete` event.** Construct the merged JSON inline (no `bin/agentic-emit` flag changes) and call:

   ```bash
   USAGE_AND_CALIBRATION="$(printf '{"tier":<tier>,"agent_id":"<agent_id>","status":"ok","session_uuid":"%s","wall_seconds":<n>,"tokens":{...},"findings_count":{"critical":<c>,"major":<m>,"minor":<n>},"diff_lines":<d>,"signed_off":true,"iteration":<i>,"meta_review":null}' "$CLAUDE_CODE_SESSION_ID")"
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
   META_DATA="$(printf '{"original_task_id":"<id>","session_uuid":"%s","divergence":{"critical_missed":[...],"major_missed":[...],"minor_missed":[...]},"agreement":<bool>}' "$CLAUDE_CODE_SESSION_ID")"
   agentic-emit meta_review_complete skeptic-meta <original_task_id> "$META_DATA"
   ```

   The next in-session scan or session-start sweep will surface any Critical/Major divergence per the Meta-divergence surfacing block above.

See `content/references/skeptic-protocol.md` Section 14 for the full calibration specification.

**Step 4. Engineer fix pass.** Spawn a fresh `engineer` agent with:
- The open Critical and Major findings from `findings_log` (status=open)
- The `last_engineer_summary` from the prior iteration
- **Iter N (N >= 2) surgical-edit directive.** When `iteration >= 2`, the brief MUST include the iter N-1 Engineer output VERBATIM as input — not a summary, not a paraphrase, not "the prior engineer changed files X, Y, Z". Paste the prior return summary in full (or, when the prior output was committed code, paste the full diff or list the committed files plus their relevant excerpts). Then include this instruction verbatim: *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a Skeptic finding listed below. Each edit you make must trace to a specific finding id."* Rationale: a fresh subagent has no session context, so a brief that says "address findings and return revised outputs" causes the Engineer to regenerate from scratch — producing output that diverges from the scoped change because it has no access to prior-iteration state. Anchoring on the prior output verbatim is the only reliable way to scope a fresh subagent to surgical fixes.
- Instruction: "Address only the findings listed below. Do not expand scope. Do not refactor, rename, or clean up code outside the finding scope. For each finding, confirm in your summary what you changed and why it addresses the finding."
- The branch name and repo path
- Instruction to run `$QUALITY_CMD` before finishing

**Telemetry emit (V1):** Bracket the Engineer `Agent` tool call with `agentic-emit spawn_start engineer <task_id> ...` before, and `agentic-emit spawn_complete engineer <task_id> ...` after - using `agentic-parse-subagent-usage` to populate tokens/model/wall_seconds. Same pattern as the Skeptic emit in Step 1.

**Step 5.** Receive Engineer output.
- If `Status: BLOCKED`: set `termination_reason: blocked`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection below. **Tracker writeback (W4):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W4 | target: $TRACKER_STATE_BLOCKED]` Emit escalation format. Stop. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply the missing context (from codebase, session context, or by asking the human) and re-spawn the Engineer with the same findings brief and the added context. Do NOT increment `iteration`. If the conductor cannot supply the context, escalate to the human with the Engineer's stated gap.
- If `Status: DONE_WITH_CONCERNS`: proceed normally. The Engineer's stated concerns become additional context for the next Skeptic spawn (include them alongside the adversarial brief). Update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Update inline breadcrumb. Go to Step 1.
- Otherwise (`Status: DONE`): update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Update inline breadcrumb. Go to Step 1.

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

### Batch-mode escalation routing (mark-blocked-and-continue)

**Trigger:** `.agentic/batch-state.json` exists with `status:"active"`. Skip (fall through to single-ticket "surface and wait for human") when absent/not active.

**Action:**
1. Print the Escalation format/stalled summary unchanged and visible.
2. Contract A+B write: find this ticket's/iteration's `tickets[]` entry, set `status:"blocked"`, `last_summary`=one-line synopsis.
3. Print `"Ticket <ticket_id> marked blocked; advancing to next pending ticket in the batch."`; skip Phases 7-12 for this ticket.
4. **Batch mode (`mode=="batch"` or absent):** advance to next `pending` ticket, array order, enter at Phase 1.
5. **Open-goal mode (`mode=="open_goal"`):** do NOT auto-advance - write `open_goal.termination_reason` to the triggering reason (`blocked`, `cap_reached_iterations`, or the equivalent) and STOP the outer loop (surface and wait for human); the `blocked` write in step 2 still happens for audit.

**Single-ticket mode (no active batch-state):** unchanged - surface and wait for human.

### Findings curator (loop exit)

At Phase 6 loop exit (both clean termination and stalled termination paths), spawn a findings-curator subagent. **Note:** `findings-curator` does not yet exist as a named agent; use `general-purpose` agent type (Tier 1, fire-and-forget) until the named agent is formally added.

**Brief:**
- Input: the full final-iteration Skeptic output (verbatim), the `ticket_id`, and the curated index path (`.agentic/findings.md`).
- The curator reads from the Skeptic's final return text - NOT from the `findings_log` field in `loop-state-$LOOP_KEY.json`.
- The curator computes `pattern_hash` per the canonicalization spec: lowercase the finding text, collapse whitespace runs (including newlines) to a single space, strip code-block fence markers (` ``` ` and `~~~`), strip leading/trailing whitespace, SHA-256 the result, take the first 16 hex chars.
- De-dup key: `(pattern_hash, ticket_id)`. Skip writing if a matching key already exists in `.agentic/findings.md`.
- The curator is the sole writer of `.agentic/findings.md` (append-only by discipline; the curator is fire-and-forget so the conductor never writes the file).

Fires exactly once per ticket per `/ds-implement-ticket` invocation.

**Limitation:** Cross-iteration semantic-dup within the same ticket where the Skeptic re-words the finding may produce different `pattern_hash` values and result in duplicate entries. Acknowledged.

**Session budget check:** After Round 2 sign-off, check conductor turn count against the soft and hard limits defined in `content/references/subagent-protocol.md` Section 13. If approaching the soft limit, recommend `/ds-wrap` and preserve state before continuing. Do not initiate Round 3 or beyond if the hard limit is within reach.

**Exchange log compression:** After Round 2 sign-off, apply compression when the log would no longer fit in a single spawn prompt alongside the preflight list. Always preserve Round 1 and the most recent round in full. See `content/references/skeptic-protocol.md` Section 3 "Exchange log compression" for the canonical trigger and format.

### Open-goal condition check (clean exit only, `goal_mode=open_goal` invocations only)

1. If `batch-state.json.open_goal.active` is not `true` (or `batch-state.json` absent / `mode != "open_goal"`), skip entirely. **Sole gate scoping the evaluator spawn to open-goal invocations.**
2. Set `batch-state.json.open_goal.risk_declared` to this iteration's classification (`low | elevated | trivial`) - Contract A+B write. Satisfies invariant (c) on the DURABLE record (see `content/references/trigger-catalog.md` §Risk and review discipline (c)).
3. **Scope gate (mirrors invariant (e)):** `risk_declared == "elevated"` → spawn `goal-condition-evaluator` (Tier 1/haiku, omit model param) with `goal_condition`, `iteration_evidence_hint` (finding IDs/files + ≤500-char excerpt of this iteration's `quality_gate_results.raw_output` when `goal_condition` plausibly references gate output), `skeptic_signoff_confirmed:true`; no worktree isolation. `low`/`trivial` → no spawn; conductor evaluates directly.
4. **Return handling:** `GOAL_MET:true` → set `open_goal.termination_reason="goal_met"` (Contract A+B); unit still ships normally UNLESS `dry_run==true`; outer loop exits at Phase 12a. `GOAL_MET:false` → status update only; continue at Phase 12a. `BLOCKED`/unavailable/errored/timeout/malformed → conductor-direct evaluation immediately (invariant (e)); **never** the generic Worker-BLOCKED=`cap_reached` escalation from `content/references/subagent-protocol.md` §Loop transition rules.

---

## Phase 6b: QA Gate (conditional)

**Dry-run skip (open-goal only).** If `batch-state.json.open_goal.active == true` AND `batch-state.json.open_goal.dry_run == true`: skip Phase 6b entirely - no qa-engineer spawn, no dev-server boot. Proceed directly to Phase 12. Never fires for ordinary invocations (no `open_goal.dry_run` field to read).

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

**Phase 6b is per-ticket and in-flow.** Phase 6b runs inside this ticket's loop, before Phase 7. The conductor MUST NOT defer Phase 6b to a final batch-end QA sweep across multiple tickets. If runtime QA cannot run for this ticket at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for THIS ticket, surfaced as `qa_blocked` with the operator's three options (provide the missing input, accept INCONCLUSIVE with `qa_unverified=true`, or abandon the ticket). See `content/references/qa-gate.md` §"Per-ticket, in-flow" for the anti-pattern and `content/references/qa-gate.md` §"INCONCLUSIVE classification" for the no-static-only-auto-pass rule.

**Conductor preflight before any qa-engineer spawn.** Before spawning qa-engineer for this unit, verify the project env file exists at the path the dev server will load (resolved from qa.md `env_file:` + `env_pull_command:` fields, or from project config such as a `package.json` `env:pull:<app>` script). If the env file is missing, do NOT spawn qa-engineer - surface the verbatim message defined in `content/references/qa-gate.md` §"Conductor preflight before any qa-engineer spawn" with the resolved `<env_pull_command>` and wait for the operator. Spawning qa-engineer just to discover the env is missing wastes a worker turn.

**Multi-PR / multi-ticket parallel-by-worktree.** When more than one PR or unit is awaiting QA, default to spawning one qa-engineer per worktree in parallel (single message, background, each on a unique port `PORT=$((3000 + N))`). See `content/references/qa-gate.md` §"Multi-PR / multi-ticket parallel-by-worktree".

- **If trigger conditions hold (QA fires) - UI-visible changes (concurrent path):** when the unit's diff is UI-visible, `qa-engineer` was already spawned IN PARALLEL with the Skeptic during Phase 6 (single message, both background). If QA passed concurrently, Phase 6b is already satisfied - skip to Phase 7. If QA failed concurrently or was deferred, proceed with the QA loop contract below. See `content/references/qa-gate.md` §"QA gate flow (UI-visible - concurrent)" for the full concurrent QA spec.
- **If trigger conditions hold (QA fires) - non-UI changes (sequential path):** proceed with the QA loop contract below.
- **If trigger conditions do not hold (QA skipped):** record the skip rationale (`qa_skip` value or "Trivial path") in the conductor's status update and proceed directly to Phase 7. Also set `QA_STATUS="skipped:<rationale>"` using that same rationale (in-context variable consumed by the Phase 9 ticket-rework ledger write). Writing the rationale rather than leaving it empty is what lets the rework notice distinguish "QA was deliberately skipped, here is why" from "QA status unavailable".

For full QA gate rules, see `METHODOLOGY.md §QA Gate`.

**QA loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state-$LOOP_KEY.json` (overwriting the Phase 6 state). **Use atomic write (tmp+rename).** Reset `last_phase=qa`, `last_phase_action=spawned`. Same write-trigger pattern as Phase 6 applies here: write at every phase transition (QA spawn, QA return, Engineer spawn, Engineer return). On clean exit set `status=complete`; on stalled exit set `status=stalled`.

```
LOOP_STATE initialized:
  phase: qa
  iteration: 1
  max_iterations: 3
  qa_failures_log: []
  last_engineer_summary: null
  termination_reason: null
```

Write as JSON to `.agentic/loop-state-$LOOP_KEY.json` (same stability contract as Phase 6 - see above).

Emit the inline breadcrumb:

```
[loop: qa | iteration 1/3 | open failures: -]
```

**Loop entry (repeat until termination):**

**Tracker writeback (W3)** — fires on iteration 1 only: if `TRACKER != none` AND this is the first qa-engineer spawn in Phase 6b, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_QA`, `forward_only_guard: true`. Fire-and-forget.

[phase: tracker-writeback | site: W3 | target: $TRACKER_STATE_QA | iter: 1]

**Step 1.** Spawn `qa-engineer` with ticket context, the diff, the unit's `qa_criteria` block (required input - the authoritative test plan), the `ticket_id` (for knowledge attribution), and the resolved qa.md config as supplemental context (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). The Agent tool call MUST set `isolation: "worktree"` (mandatory per METHODOLOGY.md §Delegation > Worker preamble). On iteration 2+, prepend the "Prior QA failures" section to the brief:

**Telemetry emit (V1):** Bracket the QA `Agent` tool call with `agentic-emit spawn_start qa-engineer <task_id> ...` before and `agentic-emit spawn_complete qa-engineer <task_id> ...` after. Same pattern as Phase 6 emits.

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
- Overwrite `.agentic/loop-state-$LOOP_KEY.json` with the updated LOOP_STATE.

**Step 3. Termination check:**
- If PASS (all acceptance criteria met): auto-close all `qa_failures_log` entries. Set `termination_reason: clean`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Set `QA_RAN_AND_PASSED="true"` (in-context variable used by Phase 9 QA Evidence section) and `QA_STATUS="PASS"` (in-context variable used by the Phase 9 ticket-rework ledger write). **Parse QA screenshot evidence (see below).** Exit loop cleanly. Proceed to Phase 7.

**`QA_STATUS` on every other terminal QA outcome.** Whenever Phase 6b reaches a terminal verdict for this ticket by any route, set `QA_STATUS` to that verdict - one of `PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`INCONCLUSIVE`. In particular, when the operator accepts INCONCLUSIVE with `qa_unverified=true` on the `qa_blocked` path and the ticket continues to Phase 9, set `QA_STATUS="INCONCLUSIVE"`. A known verdict must never be discarded to null: the ledger's contract reserves null for the case where *neither* a result *nor* a rationale can be resolved, and "the operator looked at this and accepted that QA could not verify it" is a result. Recording it as `n/a` would tell a later rework attempt that QA status was simply unavailable, hiding an accepted-unverified ticket - the exact class of silent downgrade this field exists to surface.
- If `iteration == max_iterations` AND still failing: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. Escalate to human with the `qa_failures_log`. Phase 7 does NOT run.
- If same failure recurs unchanged after a claimed fix (`re_raised: true`): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. Escalate to human with convergence note.

**QA screenshot evidence capture (PASS exit only).** On clean PASS exit, parse the `qa-screenshots-json` fenced block from the qa-engineer return text:

```
Look for a fenced block whose info string is exactly `qa-screenshots-json`, regardless of whether
the fence character is backticks (```) or tildes (~~~). Either of the following forms is valid:

  ```qa-screenshots-json
  [{"path": "...", "description": "...", "criterion_id": "...", "result": "..."}]
  ```

  ~~~qa-screenshots-json
  [{"path": "...", "description": "...", "criterion_id": "...", "result": "..."}]
  ~~~

Match by the info string `qa-screenshots-json`; do not require a specific fence character.
```

Parse the JSON array into `QA_SCREENSHOT_PATHS` (array of `{path, description, criterion_id, result}` objects). Retain only entries where `result == "PASS"` on overall PASS. If the block is absent, malformed, or the JSON fails to parse, set `QA_SCREENSHOT_PATHS=()` and continue without error. This is an in-context variable only - do NOT write `QA_SCREENSHOT_PATHS` to `.agentic/loop-state-$LOOP_KEY.json` or any other state file.

**Step 4. Engineer fix pass.** Spawn `engineer` with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. The fix engineer spawn brief MUST cite `content/references/qa-regression-obligation.md` - the engineer adds a regression test that targets the failing scenario (id, description) or, if a regression test is genuinely infeasible, appends a documented exception entry to `.agentic/qa-regressions.md` using the canonical schema in that reference. A missing test with no explanation and no curated-index entry is a Major Skeptic finding on the QA-fix iteration. **Iter N (N >= 2) surgical-edit directive.** When `iteration >= 2`, the brief MUST include the iter N-1 Engineer output VERBATIM as input - not a summary, not a paraphrase. Paste the prior return summary in full (or the prior diff plus committed-file excerpts when the prior output was code). Then include this instruction verbatim: *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a QA failure listed below. Each edit you make must trace to a specific failure id."* Same rationale as Phase 6: a fresh subagent without prior-iteration context regenerates from scratch and diverges from the scoped change; anchoring on the prior output verbatim is the only reliable way to scope a fresh subagent to surgical fixes. Bracket the **Agent call** with `agentic-emit spawn_start engineer <task_id> ...` and `agentic-emit spawn_complete engineer <task_id> ...` per the Phase 6 emit pattern. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6:
- If `Status: BLOCKED`: set `termination_reason: blocked`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. **Tracker writeback (W5):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W5 | target: $TRACKER_STATE_BLOCKED]` Escalate immediately. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply context and re-spawn without incrementing `iteration`. If context cannot be supplied, escalate to human.

**Step 5.** Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT (whether `Status: DONE` or `Status: DONE_WITH_CONCERNS`): update `qa_failures_log` entries the Engineer claims to have fixed to `status: addressed`. Update `last_engineer_summary`. Increment `iteration`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Update inline breadcrumb. Go to Step 1.

### QA regressions curator (Phase 6b clean exit)

At Phase 6b clean exit, if any iteration of this Phase 6b loop involved a QA FAIL (i.e., `qa_failures_log` was non-empty at any point before the final PASS), spawn a qa-regressions-curator subagent. **Note:** `qa-regressions-curator` does not yet exist as a named agent; use `general-purpose` agent type (Tier 1, fire-and-forget) until the named agent is formally added. Mirrors the Phase 6 findings curator pattern (see "Findings curator (loop exit)" above).

**Brief:**
- Input: the qa-engineer's last FAIL report containing the `## Regression draft (for .agentic/qa-regressions.md)` block (verbatim), any fix-engineer documented-exception block from the QA-fix iteration, the `ticket_id`, and the curated index path (`.agentic/qa-regressions.md`).
- The curator computes the dedupe key `(surface, claim)` from each draft entry: lowercase the `Surface` and `What broke` values, collapse whitespace runs to a single space, strip leading/trailing whitespace, concatenate with a `|` separator.
- Dedupe rule: if a matching `(surface, claim)` key already exists in `.agentic/qa-regressions.md`, skip the write for that entry.
- The curator is the sole writer of `.agentic/qa-regressions.md` (append-only by discipline; the curator is fire-and-forget so the conductor never writes the file).
- Schema reference: `content/references/qa-regression-obligation.md` §`.agentic/qa-regressions.md` schema (canonical).

Fires exactly once per ticket per `/ds-implement-ticket` invocation. Skipped entirely if Phase 6b never recorded a FAIL (clean PASS on iteration 1 with no failures).

---

## Phase 7: Quality gate

**Elevated path: verify from engineer return, do not re-execute.**

The Elevated-path engineer ran `$QUALITY_CMD` itself (per the `quality_gates` contract field in Phase 5) and reported `quality_gate_results: { lint, typecheck, test, smoke_test, raw_output }` in its return summary. Phase 7 verifies this return shape - the conductor does NOT invoke `$QUALITY_CMD` directly on this path.

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

1. Before spawning the Phase 7 engineer: write `.agentic/loop-state-$LOOP_KEY.json` with `last_phase=quality_gate`, `last_phase_action=engineer_spawned` (atomic write).
2. Spawn one `engineer` fix pass scoped to the quality gate failure output (passing the captured `raw_output` on the Elevated path). The Skeptic has already signed off on the implementation - this is a targeted quality gate fix, not a Skeptic-loop re-entry. The Agent tool call MUST set `isolation: "worktree"` on the Elevated path (mandatory per METHODOLOGY.md §Delegation > Worker preamble).
3. After the engineer returns and commits: write `last_phase=quality_gate`, `last_phase_action=engineer_returned` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write).
4. Before verifying the re-run: write `last_phase=quality_gate`, `last_phase_action=rerun_pending` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write). On resume from this state, the conductor waits for the fix-engineer return rather than executing `$QUALITY_CMD` itself (Elevated path) - the engineer reports `quality_gate_results` from its own re-run.
5. Verify the fix engineer's `quality_gate_results` (Elevated path) or re-run `$QUALITY_CMD` (Trivial path).
6. If it passes: set `status=complete` in `.agentic/loop-state-$LOOP_KEY.json`. Proceed to Phase 8.
7. If it still fails: set `status=stalled`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. Escalate to the human. Include the quality gate output from both the first run and the post-fix re-run. Do not spawn another Engineer pass.

**No unbounded loop (default path):** Phase 7 failure only ever triggers one Engineer fix pass followed by one re-run. There is no retry loop at this phase.

---

**When `DEBUGGER_ON_FAILURE` is `true` AND the path is Elevated** - interpose a Debugger diagnosis step before each engineer fix pass. Max 3 debug-fix cycles total.

For each debug-fix cycle (cycle count tracked in-context; escalate to human after 3 exhausted cycles with open gate failures):

1. Write `.agentic/loop-state-$LOOP_KEY.json` with `last_phase=quality_gate`, `last_phase_action=debugger_spawned` (atomic write).
2. Spawn `debugger` (read-only; no worktree isolation needed - Debugger never writes files) with:
   - The captured gate failure output (`raw_output` from the failing run)
   - The failing context (branch diff, relevant files, prior cycle summaries if any)
3. After Debugger returns: write `last_phase=quality_gate`, `last_phase_action=debugger_returned` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write).
4. Write `last_phase=quality_gate`, `last_phase_action=engineer_spawned` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write).
5. Spawn one `engineer` fix pass with the Debugger's Fix brief appended to the scoped brief. The Agent tool call MUST set `isolation: "worktree"` (mandatory on Elevated path per METHODOLOGY.md §Delegation > Worker preamble).
6. After the engineer returns and commits: write `last_phase=quality_gate`, `last_phase_action=engineer_returned` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write).
7. Write `last_phase=quality_gate`, `last_phase_action=rerun_pending` to `.agentic/loop-state-$LOOP_KEY.json` (atomic write). The engineer re-runs gates and reports `quality_gate_results`.
8. Verify the fix engineer's `quality_gate_results`.
   - If it passes: set `status=complete` in `.agentic/loop-state-$LOOP_KEY.json`. Proceed to Phase 8.
   - If it still fails AND cycle count < 3: check convergence short-circuit (below), then start the next debug-fix cycle with the new failure output.
   - If it still fails AND cycle count == 3: set `status=stalled`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. **Tracker writeback (W6a):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W6a | target: $TRACKER_STATE_BLOCKED | escalation: quality-gate-cap]` Escalate to the human. Include quality gate output from every cycle run. Do not spawn another pass.

**Convergence short-circuit (test runners only).** If the quality gate is a test runner (pytest, jest, vitest, cargo test, etc.) AND the set of failing test IDs in `quality_gate_results.failures[]` is identical to the set from the immediately preceding cycle (the engineer made no progress on the failing tests), escalate immediately without consuming remaining cycles. Surface the stalled test IDs and both cycle outputs to the human. This short-circuit applies ONLY to test runners with structured `failures[]` output. For lint (eslint, ruff, etc.) and typecheck (tsc, mypy, pyright, etc.) gates, rely solely on the 3-cycle limit - do not attempt a short-circuit.

**Cross-reference:** `content/sections/05-qa-gate.md` Re-route limits section for shared escalation semantics.

---

## Phase 8: Commit and push

**Dry-run skip (open-goal only).** If `batch-state.json.open_goal.active == true` AND `batch-state.json.open_goal.dry_run == true`: skip Phases 8 through 11b entirely - no commit-push, no PR open, no CI wait, no tracker writeback, no wrap-ticket. This iteration's engineer-produced work remains as local, unpushed commits on its worktree-isolated branch. Proceed directly to Phase 12. **What still ran:** Phases 1-7 (understand, read, architect, plan, implement, Skeptic incl. the goal-condition-evaluator spawn at Phase 6, quality gate) - every review-discipline invariant fully exercised; only shipping mechanics skipped, zero external side effects. This is the literal mechanism DC1 exercises: a `dry_run=true` run with `max_iterations=3` performs 3 full review cycles and terminates on the cap with no PR/CI/prompt.

**Sequential path:** Stage specific files and commit as described below.

**Parallel path:** All commits were already made to sub-branches and merged in Phase 5. Phase 8 should only handle any post-merge fixup files that were not captured in the sub-branch commits. Run `git -C $REPO status --short` after the merge to check for any unstaged post-merge fixup files. If output is non-empty, stage and commit those files. If output is empty, skip the stage-and-commit step and proceed directly to push.

**Only run the following commit block if `status --short` was non-empty (parallel path) or on the sequential path:**

Stage specific files - never `git add -A` or `git add .`:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO add [specific files]

# Resolve developer identity for trailer (soft-fail throughout; agentic-identity may not be installed).
# Note: `show` (no --scope) resolves the project-local identity first per the 4-tier ordering.
DEVELOPER=$(agentic-identity show 2>/dev/null | awk '/^developer_id:/{print $2}')
# Clear if provisional (cmd_show emits multi-space "provisional:   true"; use flexible [[:space:]]+ match).
if agentic-identity show 2>/dev/null | grep -qE '^provisional:[[:space:]]+true'; then DEVELOPER=""; fi
DEVTRAILER=${DEVELOPER:+"Developer: ${DEVELOPER}"}

# Resolve DCO Signed-off-by fields (git config inherits from global; check project-local first).
SO_NAME=$(git -C $REPO config user.name 2>/dev/null || git config --global user.name 2>/dev/null || true)
SO_EMAIL=$(git -C $REPO config user.email 2>/dev/null || git config --global user.email 2>/dev/null || true)

if [ -z "$SO_EMAIL" ] || [ -z "$SO_NAME" ]; then
  echo "WARNING: git user.name or user.email not set; skipping commit to avoid malformed DCO trailer."
else
  # NL assigned before the string (not inside a heredoc) so variable expansion works.
  NL=$'
'
  COMMIT_MSG="type(scope): short imperative description${NL}${NL}More detail on what changed and why if needed.${NL}Closes [TICKET_PREFIX]-NNN${NL}${NL}Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>${NL}${DEVTRAILER:+${DEVTRAILER}${NL}}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>"
  git -C $REPO commit -m "$COMMIT_MSG"
fi

# --- Telemetry commit (soft-fail throughout) ---
COMMIT_TELEMETRY=$(python3 -c "
import json, sys
try:
  cfg = json.load(open('$REPO/.agentic/config.json'))
  print('true' if cfg.get('commit_telemetry', True) else 'false')
except: print('true')
" 2>/dev/null || echo 'true')

if [ "$COMMIT_TELEMETRY" = "true" ] && [ -n "$DEVELOPER" ]; then
  SESSION_LOG_SRC="$REPO/.agentic/session-log/${DEVELOPER}.jsonl"

  # Resolve PR_CHECKOUT: the checkout that holds the PR branch.
  # Fan-out path: $REPO is on $FEATURE_BRANCH after the line-977 checkout.
  # Single-engineer paths: engineer return supplies WORKTREE_PATH.
  if [ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BRANCH_NAME" ]; then
    PR_CHECKOUT="$REPO"
  elif [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
    PR_CHECKOUT="$WORKTREE_PATH"
    # Copy file into the worktree (git cannot stage files outside the work tree).
    mkdir -p "$PR_CHECKOUT/.agentic/session-log/"
    cp "$SESSION_LOG_SRC" "$PR_CHECKOUT/.agentic/session-log/${DEVELOPER}.jsonl" 2>/dev/null || true
  else
    echo "WARNING: telemetry commit skipped - cannot resolve PR checkout for branch $BRANCH_NAME"
    PR_CHECKOUT=""
  fi

  # HEAD-branch guard (safety floor: never commit to the wrong branch).
  if [ -n "$PR_CHECKOUT" ]; then
    ACTUAL_HEAD=$(git -C "$PR_CHECKOUT" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ "$ACTUAL_HEAD" != "$BRANCH_NAME" ]; then
      echo "WARNING: telemetry commit skipped - $PR_CHECKOUT is on '$ACTUAL_HEAD', expected '$BRANCH_NAME'"
      PR_CHECKOUT=""
    fi
  fi

  if [ -n "$PR_CHECKOUT" ] && [ -f "$PR_CHECKOUT/.agentic/session-log/${DEVELOPER}.jsonl" ]; then
    git -C "$PR_CHECKOUT" add ".agentic/session-log/${DEVELOPER}.jsonl"
    # Only commit if the index has a diff (avoids empty-commit on no new sessions).
    if ! git -C "$PR_CHECKOUT" diff --cached --quiet; then
      NL=$'
'
      TELEM_MSG="chore(telemetry): add session log for ${DEVELOPER}${NL}${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>${NL}${DEVTRAILER:+${DEVTRAILER}${NL}}"
      git -C "$PR_CHECKOUT" commit -m "$TELEM_MSG" ||         git -C "$PR_CHECKOUT" restore --staged ".agentic/session-log/${DEVELOPER}.jsonl"
    fi
    # Push only on single-engineer paths (fan-out push handled in its own block).
    if [ "$PR_CHECKOUT" != "$REPO" ]; then
      git -C "$PR_CHECKOUT" push -u origin "$BRANCH_NAME" 2>/dev/null || true
    fi
  fi
fi
# --- End telemetry commit ---

git -C $REPO push -u origin [BRANCH_NAME]

# --- Isolation worktree cleanup (post-push) ---
# The branch now lives on origin; the engineer's isolated worktree is redundant.
# Resolve the worktree from the branch name so renames do not break cleanup.
git -C "$REPO" fetch origin "$BRANCH_NAME" 2>/dev/null || true
if git -C "$REPO" ls-remote --heads origin "$BRANCH_NAME" | grep -q "$BRANCH_NAME"; then
  WORKTREE_PATH=$("$REPO_DIR/bin/agentic-resolve-worktree" "$REPO" "$BRANCH_NAME" 2>/dev/null || true)
  if [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
    if [ -z "$(git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null)" ]; then
      git -C "$REPO" worktree remove "$WORKTREE_PATH" 2>/dev/null || true
      git -C "$REPO" branch -D "$BRANCH_NAME" 2>/dev/null || true
      echo "[phase: worktree-cleanup | branch=$BRANCH_NAME | path=$WORKTREE_PATH]"
    else
      echo "WARNING: worktree $WORKTREE_PATH has uncommitted changes; skipping cleanup"
    fi
  fi
fi
# --- End isolation worktree cleanup ---
```

`Signed-off-by` satisfies the DCO CI gate. `Developer:` records the operator handle (omitted when identity is absent or provisional).

**Telemetry commit:** After the main commit, a separate `chore(telemetry):` commit stages `.agentic/session-log/<developer_id>.jsonl` on the PR branch when `commit_telemetry: true` (default in `.agentic/config.json`) and identity is confirmed (non-provisional). The block is path-aware: on the fan-out path `$REPO` is already on the feature branch (after the line-977 `git checkout`), so `$PR_CHECKOUT=$REPO`; on single-engineer paths the conductor must capture `$WORKTREE_PATH` from the engineer's return summary before Phase 8 runs, and the file is copied into the worktree before staging (git cannot stage files outside the work tree). A `rev-parse --abbrev-ref HEAD == $BRANCH_NAME` guard fires before every commit - if `$PR_CHECKOUT` is on a different branch the commit is skipped with a one-line warning and the feature commit is never affected. On single-engineer paths only, the telemetry commit is pushed in the same block; fan-out push is handled in the fan-out push block. **Note on eventual consistency:** the Phase 8 commit contains only sessions that ended before it runs. The current session's line is written by the Stop hook at session end and lands in the next ticket's Phase 8 commit - this is a known property, not a bug.

Commit message types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.

---

## Phase 8.5: QA evidence (conditional)

**Skip conditions (all must be false for phase to run):**
- QA was skipped (`qa_skip != null`) or the ticket is Trivial
- `QA_SCREENSHOT_PATHS` is empty (`()`)
- `gh` or `jq` is unavailable (`which gh jq` fails)

When any skip condition is true, set `QA_EVIDENCE_URLS=()` and proceed directly to Phase 9.

**Goal:** commit PASS screenshots to a long-lived orphan `qa-evidence` branch on GitHub under the deterministic path `<TICKET_SLUG>/<BRANCH_SLUG>/<filename>`, build click-through evidence URLs, and emit them into the PR body. The branch is never merged to main; it is a parallel evidence store.

**Slug derivation:**
- `TICKET_SLUG`: `$TICKET_ID` lowercased, non-alphanum replaced with hyphens (e.g. `eng-123`)
- `BRANCH_SLUG`: `$BRANCH_NAME` with leading `feature/`, `fix/`, `chore/` stripped; remaining slashes replaced with hyphens

**Copy screenshots to a stable temp directory:**

```bash
SCREENSHOTS_SRC="/tmp/qa-evidence-$$"
mkdir -p "$SCREENSHOTS_SRC"
# Copy each path from QA_SCREENSHOT_PATHS into $SCREENSHOTS_SRC
# (QA_SCREENSHOT_PATHS is a bash array; entries are JSON objects from Phase 6b parse)
for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
  SRC_PATH=$(echo "$entry" | jq -r '.path')
  cp "$SRC_PATH" "$SCREENSHOTS_SRC/" 2>/dev/null || true
done
# If nothing copied, treat as skip
[ "$(ls -A "$SCREENSHOTS_SRC")" ] || { QA_EVIDENCE_URLS=(); rm -rf "$SCREENSHOTS_SRC"; proceed to Phase 9; }
```

**Check whether `qa-evidence` branch already exists on remote:**

```bash
REMOTE_EXISTS=$(git -C "$REPO" ls-remote --heads origin qa-evidence | wc -l)
```

**First-create path (branch does not exist on remote):**

Create a scratch clone in `/tmp` to bootstrap the orphan branch. `$SCREENSHOTS_SRC` lives in `/tmp` (outside the clone) so `reset --hard` never destroys the source.

```bash
TEMP_CLONE="/tmp/qa-evidence-clone-$$"
git clone --depth=1 "$REPO" "$TEMP_CLONE"
git -C "$TEMP_CLONE" checkout --orphan qa-evidence
git -C "$TEMP_CLONE" rm -rf . 2>/dev/null || true
mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$TEMP_CLONE" add .
git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# RACE RECOVERY LOOP: handles concurrent first-creators racing on the orphan root
PUSH_SUCCEEDED_FIRST_CREATE=false
for i in 1 2 3; do
  if git -C "$TEMP_CLONE" push origin qa-evidence; then
    PUSH_SUCCEEDED_FIRST_CREATE=true
    break
  fi
  # push rejected — a concurrent creator won; adopt the landed history
  git -C "$TEMP_CLONE" fetch origin qa-evidence
  git -C "$TEMP_CLONE" reset --hard origin/qa-evidence   # adopts remote history; wipes worktree
  mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"      # recreate dest dir destroyed by reset
  cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
  git -C "$TEMP_CLONE" add .
  git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"
done

rm -rf "$TEMP_CLONE"
```

After temp-clone push succeeds, fetch the updated remote-tracking ref into the main repo:

```bash
git -C "$REPO" fetch origin qa-evidence
```

**Steady-state path (branch already exists on remote):**

Add a detached-HEAD worktree pointing at `origin/qa-evidence`, copy files, and push using the `HEAD:qa-evidence` refspec (mandatory because the worktree is on a detached HEAD - `push origin qa-evidence` would be a no-op in this state).

```bash
WORKTREE_PATH="$REPO/.agentic/worktrees/qa-evidence-$$"
git -C "$REPO" fetch origin qa-evidence
git -C "$REPO" worktree add "$WORKTREE_PATH" origin/qa-evidence   # detached HEAD

mkdir -p "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$WORKTREE_PATH" add .
git -C "$WORKTREE_PATH" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# CRITICAL: worktree is on a detached HEAD; must use HEAD:qa-evidence refspec
PUSH_SUCCEEDED_STEADY=false
for i in 1 2 3; do
  if git -C "$WORKTREE_PATH" push origin HEAD:qa-evidence; then
    PUSH_SUCCEEDED_STEADY=true
    break
  fi
  git -C "$WORKTREE_PATH" fetch origin qa-evidence
  git -C "$WORKTREE_PATH" rebase origin/qa-evidence
done

git -C "$REPO" worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
git -C "$REPO" worktree prune 2>/dev/null || true
```

**Build `QA_EVIDENCE_URLS` (only after push succeeds):**

Build `QA_EVIDENCE_URLS` only when the push in the active path succeeded. `$GH_REPO` is the repo slug resolved at Phase 0 setup (e.g. `org/repo-name`, same variable used throughout the command). Use `jq -n --arg` to safely interpolate description strings that may contain quotes or special characters.

```bash
# PUSH_SUCCEEDED is true only if the first-create or steady-state push loop above exited with success
PUSH_SUCCEEDED="${PUSH_SUCCEEDED_FIRST_CREATE:-${PUSH_SUCCEEDED_STEADY:-false}}"

QA_EVIDENCE_URLS=()
if [ "$PUSH_SUCCEEDED" = "true" ]; then
  OWNER=$(echo "$GH_REPO" | cut -d/ -f1)
  REPO_NAME=$(echo "$GH_REPO" | cut -d/ -f2)
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    FNAME=$(basename "$(echo "$entry" | jq -r '.path')")
    CRITERION=$(echo "$entry" | jq -r '.criterion_id')
    DESC=$(echo "$entry" | jq -r '.description')
    RESULT=$(echo "$entry" | jq -r '.result')
    URL="https://github.com/${OWNER}/${REPO_NAME}/blob/qa-evidence/${TICKET_SLUG}/${BRANCH_SLUG}/${FNAME}"
    # Use jq --arg to safely encode description (handles quotes and special chars)
    ENTRY_JSON=$(jq -n --arg url "$URL" --arg cid "$CRITERION" --arg d "$DESC" --arg r "$RESULT" \
      '{"url":$url,"criterion_id":$cid,"description":$d,"result":$r}')
    QA_EVIDENCE_URLS+=("$ENTRY_JSON")
  done
fi
```

If any step in the above sequence fails (push fails after 3 retries, worktree creation fails, copy fails), `QA_EVIDENCE_URLS` remains `()` (empty) and the phase continues. Phase 8.5 is always soft-fail - do not block Phase 9.

Clean up temp dir:

```bash
rm -rf "$SCREENSHOTS_SRC" 2>/dev/null || true
```

Clean up the original `/tmp/qa_*` source files that were consumed. Run this unconditionally after the copy loop and temp-dir cleanup, but only when `QA_SCREENSHOT_PATHS` is non-empty. Use the parsed paths so only copied files are deleted. Guard with `|| true` so Phase 8.5 remains soft-fail.

```bash
if [ "${#QA_SCREENSHOT_PATHS[@]}" -gt 0 ]; then
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    SRC_PATH=$(echo "$entry" | jq -r '.path')
    rm -f "$SRC_PATH" 2>/dev/null || true
  done
fi
```

Also delete `/tmp/qa_devserver.log` if it exists. Run this unconditionally at the end of Phase 8.5, regardless of whether screenshots were consumed:

```bash
rm -f /tmp/qa_devserver.log 2>/dev/null || true
```

Emit breadcrumb: `[phase: qa-evidence | screenshots=<N> | urls=<M> | branch=qa-evidence]`

---

## Phase 9: Open the PR

**UNIT_IS_BEHAVIOR_VISIBLE derivation.** Set this variable before composing the PR body. It is "true" only when ALL hold:
- `QA_RAN_AND_PASSED == "true"` (Phase 6b clean exit)
- `QA_EVIDENCE_URLS` is non-empty
- the unit's risk class - taken from the conductor's in-context risk classification (declared at Phase 2/3) and the architect plan - is NOT one of: security, auth, crypto, payments, or Elevated-correctness

Default is "false". When the risk class is ambiguous, use "false". (Conservative: a false default just keeps the existing append-after-Summary behavior; it never leads with evidence on a security/correctness unit.) This is derived in-context by the conductor; it is not stored in or read from a state file.

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

Authoring rule: §External Comment Discipline in `content/rules/conventions.md` applies - lead with the result, bullets over prose, cut anything the diff already shows.

Run:

```bash
# Resolve identity for PR Developer: field (may already be set from Phase 8).
# Re-derive here if Phase 8 was skipped (e.g., parallel path with no fixup files).
# Note: `show` (no --scope) resolves the project-local identity first per the 4-tier ordering.
DEVELOPER=${DEVELOPER:-$(agentic-identity show 2>/dev/null | awk '/^developer_id:/{print $2}')}
if agentic-identity show 2>/dev/null | grep -qE '^provisional:[[:space:]]+true'; then DEVELOPER=""; fi

# UNIT_IS_BEHAVIOR_VISIBLE: true only when QA ran+passed, evidence URLs exist, AND risk class is
# not security/auth/crypto/payments/Elevated-correctness (derived in-context from Phase 2/3
# risk classification and architect plan; default false when risk class is ambiguous).
UNIT_IS_BEHAVIOR_VISIBLE="false"
if [ "$QA_RAN_AND_PASSED" = "true" ] && [ "${#QA_EVIDENCE_URLS[@]}" -gt 0 ]; then
  # Set to "true" only when the conductor's in-context risk class is behavior-visible Elevated
  # (UI changes, behavioral feature additions). Must remain "false" for security, auth, crypto,
  # payments, or Elevated-correctness units regardless of QA state.
  UNIT_IS_BEHAVIOR_VISIBLE="[true|false - conductor sets based on in-context risk class]"
fi
```

**Case A - behavior-visible unit with QA evidence (`UNIT_IS_BEHAVIOR_VISIBLE == "true"`):**

Lead the PR body with `## QA Evidence` so reviewers see runtime confirmation first.

**Case B - all else (UNIT_IS_BEHAVIOR_VISIBLE false, or QA_EVIDENCE_URLS empty, or QA_RAN_AND_PASSED != "true"):**

Use the existing Summary-first body and append QA evidence after PR creation.

```bash
if [ "$UNIT_IS_BEHAVIOR_VISIBLE" = "true" ] && [ "${#QA_EVIDENCE_URLS[@]}" -gt 0 ]; then
  # Case A: behavior-visible unit - lead with QA Evidence so reviewers see runtime confirmation first
  EVIDENCE_WRITTEN_TO_BODY="true"
  PR_BODY_FILE="/tmp/pr-body-$$"
  printf "## QA Evidence\n\n" > "$PR_BODY_FILE"
  for entry in "${QA_EVIDENCE_URLS[@]}"; do
    CRITERION=$(echo "$entry" | jq -r '.criterion_id')
    DESC=$(echo "$entry" | jq -r '.description')
    RESULT=$(echo "$entry" | jq -r '.result')
    URL=$(echo "$entry" | jq -r '.url')
    printf -- "- **%s** %s - [screenshot](%s)\n" "$CRITERION" "$RESULT" "$URL" >> "$PR_BODY_FILE"
  done
  cat >> "$PR_BODY_FILE" <<PRBODY

## Summary
- [bullet 1]
- [bullet 2]

[TRACKER_REFERENCE_BLOCK]

## Test plan
- [ ] [step 1]
- [ ] [step 2]
PRBODY
  [ -n "$DEVELOPER" ] && printf "\nDeveloper: %s\n" "$DEVELOPER" >> "$PR_BODY_FILE"

  gh pr create \
    --repo [GH_REPO] \
    --base [BASE_BRANCH] \
    --head [BRANCH_NAME] \
    --draft \
    --title "[TICKET_PREFIX]-NNN: [ticket title]" \
    --body-file "$PR_BODY_FILE"
  rm -f "$PR_BODY_FILE"
else
  # Case B: all else - Summary-first body; QA evidence appended after PR creation
  EVIDENCE_WRITTEN_TO_BODY="false"
  PR_BODY_FILE="/tmp/pr-body-$$"
  cat > "$PR_BODY_FILE" <<PRBODY
## Summary
- [bullet 1]
- [bullet 2]

[TRACKER_REFERENCE_BLOCK]

## Test plan
- [ ] [step 1]
- [ ] [step 2]
PRBODY
  # Append Developer: line when identity is confirmed (survives --squash via PR body).
  [ -n "$DEVELOPER" ] && printf "\nDeveloper: %s\n" "$DEVELOPER" >> "$PR_BODY_FILE"

  gh pr create \
    --repo [GH_REPO] \
    --base [BASE_BRANCH] \
    --head [BRANCH_NAME] \
    --draft \
    --title "[TICKET_PREFIX]-NNN: [ticket title]" \
    --body-file "$PR_BODY_FILE"
  rm -f "$PR_BODY_FILE"
fi
```

For `TRACKER=none`, omit the tracker reference block line and drop the `[TICKET_PREFIX]-NNN:` prefix from `--title`.

Capture the PR number from the URL printed by `gh pr create`.

### Ticket-rework ledger write

**Anchoring (binding).** This write sits HERE - after the Case A / Case B `if`/`else` above has closed, at the PR-number capture point - precisely because it must fire downstream of BOTH `gh pr create` calls. Case B is not a fallback: it is the branch every Trivial ticket takes, since a Trivial ticket never produces QA evidence. Anchoring this write inside Case A would silently drop every Trivial ticket's record. Do not move it into either branch. See `content/references/ticket-rework.md` §The dual-branch anchoring pattern.

**Skip conditions.** Skip the write entirely (no file created, no line appended) when either holds:
- `REWORK_DETECTION` is `false`.
- `TICKET_ID` is null or empty (pure-freeform work has nothing to key a ledger record on).

**`pr_number` is derived at the write site, never read from `$PR_NUMBER`.** `$PR_NUMBER` is an in-context variable that is not reset between tickets in a batch; a failed `gh pr create` on ticket 2 would leave ticket 1's number in it and record the wrong PR against ticket 2. Derive it live from the currently-resolved `$BRANCH_NAME` using the same `gh pr view` lookup pattern Phase 11c uses. If the derivation yields nothing, skip the write - a record with no PR number is not a record. `$BRANCH_NAME` is a lookup key only; it is recorded in the `branch` field for forensics and is never an identity key (see `content/references/ticket-rework.md` §`pr_number` as the sole identity key).

**One line, one `write()`.** The record is appended as a single `O_APPEND` write of one complete line. Never compose the line from multiple appends - the offset-atomicity guarantee that makes a lockless append safe is per-`write()`-call, not per-logical-record. There is no write-time lock and no read-before-write; all deduplication happens on read, keyed on `pr_number`.

**Soft-fail throughout.** Any failure in this block (missing `jq`, unwritable `.agentic/`, failed `gh` lookup) is swallowed. It must never block Phase 9 or anything downstream.

Field derivation:
- `risk_class` - `$RISK_CLASS`, **set at the Phase 2 "Risk classification declaration (unconditional)" subsection** to the conductor's declared classification, post-floor: `Trivial` | `Low` | `Elevated`. All three of `risk_class`, `skeptic_rounds`, and `qa_status` normalize an empty value to `null` in the record builder. For `risk_class` this is defence-in-depth rather than a reachable path - the Phase 2 declaration is unconditional, so an empty value would mean the declaration was skipped - but the three fields are read from the same per-ticket-reset in-context variables and are handled identically, so that a bug upstream produces an explicit `null` (which the null-render rule renders `n/a`) rather than an empty string, which that rule has nothing sensible to render.
- `skeptic_rounds` - `$SKEPTIC_ROUNDS`, **captured at Phase 6 clean exit**, before Phase 6b overwrites the loop state. Do **not** read `loop_state.iteration` at this point unguarded: Phase 6b reinitializes that file with `phase: qa, iteration: 1`, so a post-QA read returns the QA iteration count, not the Skeptic round count. **Null on the Trivial path**, which never reaches Phase 6 and therefore never sets the variable. The disk fallback below exists only for a resumed session that lost the in-context variable, and it is doubly guarded - on `ticket_id` *and* on `loop_state.phase == "skeptic"`.
- `qa_status` - the QA result (`PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`INCONCLUSIVE`) when QA reached a terminal verdict; otherwise the skip rationale as `"skipped:<rationale>"`, where `<rationale>` is the `qa_criteria.qa_skip` enum value (set on Phase 6b's skip branch) or the literal `Trivial path` (set at the **Phase 2 declaration**, because Phase 6b is unreachable on the Trivial path). **Both non-QA paths - Trivial, and Elevated with a non-null `qa_skip` - write the rationale, not null.** That is the whole point of the field: a bare null renders `n/a` in the notice, which tells an operator doing manual verification that QA is *unavailable* when the truth is that QA was *deliberately skipped, for a stated reason*. Null is reserved for the degenerate case where neither a result nor a rationale can be resolved at all.
- `unit_count` - **derived, not read**; there is no `unit_count` variable in this command. Count of `.agentic/tasks.jsonl` records whose `ticket_id` matches this ticket (the Phase 5 fan-out path). `1` on a single-engineer path, and `1` when `tasks.jsonl` is absent or unreadable.

**Variable definition sites.** `RISK_CLASS` and `QA_STATUS` carry the record's semantic content, so unlike `$BRANCH_NAME` / `$GH_REPO` they are stated explicitly rather than assumed:

| Variable | Reset | Set where | Value |
|---|---|---|---|
| `RISK_CLASS` | Phase 1, per-ticket reset | Phase 2 "Risk classification declaration (unconditional)" | `Trivial` \| `Low` \| `Elevated`, post-floor |
| `SKEPTIC_ROUNDS` | Phase 1, per-ticket reset | Phase 6, Step 3 clean exit | final `loop_state.iteration`; stays empty on the Trivial path, which never reaches Phase 6 |
| `QA_STATUS` | Phase 1, per-ticket reset | **Three** sites: Phase 2 declaration (`skipped:Trivial path`, the only Trivial-reachable one); Phase 6b skip branch (`skipped:<qa_skip enum>`); Phase 6b terminal outcome (the QA verdict) | see the bullet above |

Every row is cleared at the Phase 1 per-ticket reset and re-set on this ticket's own path. Without that reset each variable's single definition site would leak the previous batch ticket's value into any ticket that does not take that path - see "Per-ticket variable reset" in Phase 1.

```bash
# Phase 9: ticket-rework ledger write (soft-fail; never blocks Phase 9 or anything downstream).
# Anchored AFTER the Case A / Case B if/else above - fires for both branches, Trivial included.
# REWORK_DETECTION / TICKET_ID / RISK_CLASS / SKEPTIC_ROUNDS / QA_STATUS are the shell-variable
# form of the conductor's in-context state (definition sites in the table above).
# QA_STATUS holds the QA result when QA ran, and "skipped:<qa_skip enum>" or
# "skipped:Trivial path" when it did not. It is empty ONLY in the degenerate case where neither
# a result nor a rationale exists - the two ordinary non-QA paths both carry a rationale.
if [ "$REWORK_DETECTION" != "false" ] && [ -n "$TICKET_ID" ]; then
  # pr_number derived live from the ticket currently in flight's own branch - never $PR_NUMBER.
  TRL_PR_NUMBER=$(gh pr view "$BRANCH_NAME" --repo "$GH_REPO" --json number -q .number 2>/dev/null || true)

  if [ -n "$TRL_PR_NUMBER" ]; then
    # skeptic_rounds: prefer the value captured at Phase 6 clean exit. Empty on the Trivial
    # path, which never reaches Phase 6 - that is a correct null, not a missing read.
    TRL_ROUNDS="${SKEPTIC_ROUNDS:-}"

    # Disk fallback for a resumed session that lost the in-context variable. TWO guards, both
    # KEPT, for different reasons:
    #   ticket_id  - now redundant BY CONSTRUCTION, because the file is keyed per ticket and
    #                a wrong-ticket file is not at this path at all. Kept deliberately: it is
    #                one jq clause, and a MIS-DERIVED $LOOP_KEY presents as exactly the
    #                cross-ticket round-count leak this clause prevents (Trivial ticket 2
    #                inheriting Elevated ticket 1's round count, telling the operator a
    #                Trivial attempt got three rounds of review when it got none). Removing a
    #                defence in the same change that introduces a new key-derivation
    #                mechanism is the wrong direction.
    #   phase      - Phase 6b overwrites the file with phase:qa, iteration:1. Without this
    #                guard, an Elevated ticket that passed QA on the first try records 1
    #                Skeptic round regardless of how many it actually took. Keying does NOT
    #                fix this: same ticket, same key, same file.
    if [ -z "$TRL_ROUNDS" ] && [ -f .agentic/loop-state-$LOOP_KEY.json ]; then
      TRL_ROUNDS=$(jq -r --arg t "$TICKET_ID" '
        select(.ticket_id == $t and .loop_state.phase == "skeptic")
        | .loop_state.iteration // empty
      ' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null) || TRL_ROUNDS=""
    fi
    case "$TRL_ROUNDS" in ''|*[!0-9]*) TRL_ROUNDS="" ;; esac

    # unit_count: derived from tasks.jsonl; 1 when absent, unreadable, or no matching records.
    TRL_UNITS=$(jq -r --arg t "$TICKET_ID" 'select(.ticket_id == $t) | .task_id' \
      .agentic/tasks.jsonl 2>/dev/null | grep -c . || true)
    case "$TRL_UNITS" in ''|0|*[!0-9]*) TRL_UNITS=1 ;; esac

    # Build the whole record first, then append it with ONE write. Do not split this append.
    TRL_LINE=$(jq -cn \
      --arg tid "$TICKET_ID" \
      --argjson pr "$TRL_PR_NUMBER" \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg br "$BRANCH_NAME" \
      --arg rc "$RISK_CLASS" \
      --arg sr "${TRL_ROUNDS:-}" \
      --arg qs "${QA_STATUS:-}" \
      --argjson uc "$TRL_UNITS" \
      '{ticket_id:$tid, pr_number:$pr, opened_ts:$ts, branch:$br,
        risk_class:(if $rc == "" then null else $rc end),
        skeptic_rounds:(if $sr == "" then null else ($sr|tonumber) end),
        qa_status:(if $qs == "" then null else $qs end),
        unit_count:$uc}' 2>/dev/null || true)

    if [ -n "$TRL_LINE" ]; then
      mkdir -p .agentic 2>/dev/null || true
      printf '%s\n' "$TRL_LINE" >> .agentic/ticket-ledger.jsonl 2>/dev/null || true
    fi
  fi
fi
```

`.agentic/ticket-ledger.jsonl` is append-only and gitignored under the existing `.agentic/` umbrella (machine-local; no `.gitignore` change needed). It is never truncated or rewritten by this command, and Phase 12 cleanup does not remove it - the history is the point.

**QA Evidence section (append to PR body after `gh pr create` - Case B only).**

Skip this block when `EVIDENCE_WRITTEN_TO_BODY="true"` (Case A already included evidence in the body). For Case B, append a `## QA Evidence` section based on the state of `QA_EVIDENCE_URLS`. Use a temp file (not stdin) to avoid shell escaping issues:

```bash
if [ "$EVIDENCE_WRITTEN_TO_BODY" != "true" ]; then
  PR_BODY_APPEND_FILE="/tmp/qa-evidence-pr-body-$$"

  # B1: QA ran and evidence URLs are available
  if [ "${#QA_EVIDENCE_URLS[@]}" -gt 0 ]; then
    printf "## QA Evidence\n\n" > "$PR_BODY_APPEND_FILE"
    for entry in "${QA_EVIDENCE_URLS[@]}"; do
      CRITERION=$(echo "$entry" | jq -r '.criterion_id')
      DESC=$(echo "$entry" | jq -r '.description')
      RESULT=$(echo "$entry" | jq -r '.result')
      URL=$(echo "$entry" | jq -r '.url')
      printf -- "- **%s** %s - [screenshot](%s)\n" "$CRITERION" "$RESULT" "$URL" >> "$PR_BODY_APPEND_FILE"
    done

  # B2: QA ran (PASS) but no evidence URLs (push failed, or ran with no screenshots captured).
  # Covers: push failed after retries, AND the case where QA passed but captured zero screenshots.
  # Also catches Case A candidates (behavior-visible) whose Phase 8.5 produced no URLs.
  # Does NOT fire when QA was skipped (QA_RAN_AND_PASSED is "false" in that case).
  elif [ "$QA_RAN_AND_PASSED" = "true" ]; then
    printf "> QA ran (PASS) but no screenshot evidence is available (push failed or no screenshots were captured).\n" > "$PR_BODY_APPEND_FILE"

  # B3: QA was skipped or not configured (QA_RAN_AND_PASSED is "false")
  else
    printf "> QA skipped or not configured for this ticket (see qa_criteria in architect plan).\n" > "$PR_BODY_APPEND_FILE"
  fi

  # Fetch existing body and append
  EXISTING_BODY=$(gh pr view "$PR_NUMBER" --repo "$GH_REPO" --json body --jq '.body' 2>/dev/null || echo "")
  printf "%s\n\n%s" "$EXISTING_BODY" "$(cat "$PR_BODY_APPEND_FILE")" > "/tmp/qa-evidence-full-body-$$"
  gh pr edit "$PR_NUMBER" --repo "$GH_REPO" --body-file "/tmp/qa-evidence-full-body-$$" 2>/dev/null || true
  rm -f "$PR_BODY_APPEND_FILE" "/tmp/qa-evidence-full-body-$$" 2>/dev/null || true
fi
```

`QA_RAN_AND_PASSED` is set to `"true"` when Phase 6b exited cleanly (`termination_reason: clean`). Set it in Phase 6b on clean exit, alongside the `QA_SCREENSHOT_PATHS` parse. Soft-fail: if any step fails (gh pr edit, body fetch), do not block Phase 10.

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
- Loop hit `TIMEOUT_POLLS` without all-complete: emit `[phase: ci-wait | result: timeout]`. Write `last_phase: ci_wait, last_phase_action: timeout` to `.agentic/loop-state-$LOOP_KEY.json`. Surface to human and STOP (do NOT auto-fix, do NOT proceed). Human decides whether to extend the wait or escalate.

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

   The `tail -300` truncation targets the relevant failure output. CI failure output is almost always in the last 300 lines; earlier lines are setup/install noise. If the truncated log misses the failure (extremely rare), the next cycle will retry with the next failure run's log.

2. **Write `.agentic/loop-state-$LOOP_KEY.json`:** `last_phase: ci_loop, last_phase_action: fix_engineer_spawned, last_phase_iteration: N`.

3. **Spawn engineer** (worktree-isolated, Elevated path). Brief includes:
   - The failure log (`$FAILURE_LOG`, last-300 truncated)
   - Prior cycle summaries (iter N >= 2 surgical-edit directive: paste iter N-1 verbatim, instruction "APPLY SURGICAL EDITS, do not regenerate")
   - Instruction to commit and push to the same branch

4. **After engineer returns:** Write `last_phase: ci_loop, last_phase_action: fix_engineer_returned, last_phase_iteration: N` to `.agentic/loop-state-$LOOP_KEY.json`. Re-enter Phase 10 poll. Write `last_phase: ci_loop, last_phase_action: ci_poll_pending, last_phase_iteration: N` to `.agentic/loop-state-$LOOP_KEY.json` while polling.

5. **Convergence short-circuit:** If failing check-name set in cycle N equals cycle N-1 (engineer made no progress), escalate immediately without consuming remaining cycles.

6. **Cap exceeded (3 cycles without all-pass):**
   - Write `last_phase: ci_loop, last_phase_action: cap_exceeded` to `.agentic/loop-state-$LOOP_KEY.json`.
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
> - `qa_summary`: Per §External Comment Discipline in `content/rules/conventions.md`: lead with status + PR link, then bullet only what the reviewer cannot see from the PR itself (QA caveats, known limitations, what to focus testing on). Omit restating the ticket.
> - `target_state`: `$TRACKER_STATE_QA` (resolved in Setup; defaults to `"Testing"` for Linear, `"QA"` for Jira)
> - `forward_only_guard`: `true`
> - `tracker_state_values`: `{ "IN_PROGRESS": "$TRACKER_STATE_IN_PROGRESS", "IN_REVIEW": "$TRACKER_STATE_IN_REVIEW", "QA": "$TRACKER_STATE_QA", "BLOCKED": "$TRACKER_STATE_BLOCKED", "DONE": "$TRACKER_STATE_DONE" }`
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

**Screenshot attachment upload (Linear and Jira, opt-in).** After the main tracker comment is posted, if `screenshot_upload: true` is set in `.agentic/qa.md` AND `QA_SCREENSHOT_PATHS` is non-empty, the tracker-writeback subagent also uploads the PASS screenshots as native attachments. Pass the following additional inputs to the subagent:

- `screenshot_upload: true` (flag; only when qa.md `screenshot_upload: true` AND paths non-empty)
- `qa_screenshot_paths`: the `QA_SCREENSHOT_PATHS` array (PASS entries only)

**Subagent behavior for screenshot upload:**

**Linear upload (when `TRACKER=linear`):**
1. For each screenshot in `qa_screenshot_paths`, call the `fileUpload` mutation with `contentType: "image/png"` and `filename: <basename>`. Fields requested: `uploadFile { uploadUrl assetUrl headers { key value } }`. The token is `LINEAR_API_KEY` (env var).
2. PUT the file bytes to `uploadFile.uploadUrl` with all headers from `uploadFile.headers` (e.g. `Content-Type`).
3. Build a comment body containing `![<description>](<uploadFile.assetUrl>)` for each screenshot - uses `assetUrl` (the permanent URL), never `uploadUrl` (which is the expiring PUT target). Post the comment via `mcp__linear__save_comment`.
4. Graceful-skip on any `fileUpload` mutation error (the mutation is schema-confirmed but behavioral details may change). If upload fails, post a plain comment noting that screenshots were available but upload failed.

**Jira upload (when `TRACKER=jira`):**
1. For each screenshot in `qa_screenshot_paths`, `POST /rest/api/3/issue/{key}/attachments` as multipart form data. Required headers: `X-Atlassian-Token: no-check`, `Authorization: Basic base64(<JIRA_USER_EMAIL>:<JIRA_API_TOKEN>)`. The response is an array of `Attachment` objects; capture `attachment[0].content` (authenticated download URL) and `attachment[0].filename`.
2. ADF inline embedding is NOT attempted (Atlassian Media API UUID is not available from standard Jira REST v3 credentials - see plan §Verified API facts). Instead, post an ADF comment with a plain-text paragraph for each screenshot:
   ```json
   {"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"QA Evidence - PASS: <filename> (<content_url>)"}]}]}}
   ```
   The `content_url` is `attachment[0].content` (authenticated download URL, click-through for Jira users - NOT an inline image). This is the maximum fidelity achievable without a separate Media API integration.
3. Credentials absent (`JIRA_USER_EMAIL` or `JIRA_API_TOKEN` env var missing): skip upload, post a plain comment noting skipped upload.

**Gating:** upload only fires when BOTH `screenshot_upload: true` (qa.md field) AND `qa_screenshot_paths` is non-empty AND credentials/tool are available. Credentials or capability absent: skip upload, the main tracker comment still posts with a note: `"(QA screenshots available but upload skipped - set JIRA_USER_EMAIL+JIRA_API_TOKEN or LINEAR_API_KEY env vars and screenshot_upload: true in qa.md to enable attachment upload.)"`. Soft-fail throughout: upload errors never block the tracker comment.

#### If TRACKER is `none`

Skip Phase 11 entirely. Print: "No tracker configured - skipping ticket update. PR is open at: https://github.com/[GH_REPO]/pull/[PR_NUMBER]"

(This sub-section is conductor-direct - it is a print, not delegable.)

**qa.md `screenshot_upload` field.** The `screenshot_upload: true` field in `.agentic/qa.md` opts the project in to native tracker attachment upload of QA screenshots. When absent or `false`, Phase 11 screenshot upload is skipped. Example qa.md entry:

```yaml
screenshot_upload: true
```

Required env vars for upload:
- Linear: `LINEAR_API_KEY`
- Jira: `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`

These are the same credentials used for existing tracker writebacks. No new credential types are introduced.

---

## Phase 11b: Wrap learnings (per-ticket capture)

**Trigger:** every PR opened, subject to skip conditions below. Fires AFTER Phase 11 completes and BEFORE Phase 12 cleanup. Phase 11b reads `findings_log` from `.agentic/loop-state-$LOOP_KEY.json` BEFORE Phase 12 clears it - explicit ordering. The findings-curator at Phase 6 exit reads `findings_log` but does NOT clear it; Phase 12 is the only clearer.

**Skip conditions:**
- Phase 9 was skipped (no PR was opened): skip Phase 11b entirely. Lock acquisition below is never attempted - there is nothing to release.
- The current ticket was Trivial: skip with `skipped_reason: "trivial-no-brief"`. Do NOT spawn `wrap-ticket`. Lock acquisition below is never attempted - there is nothing to release.

**Spawn:** `wrap-ticket` (Tier 1, foreground, blocking, 60-second timeout).

**Lock acquisition:** before spawning, attempt to acquire `.agentic/wrap/lock` (atomic `mkdir`). The lock is shared with `/ds-wrap` to prevent concurrent writes to MEMORY.md, decisions.md, and `.agentic/_wrap.md` - each a genuine read-modify-write of a curated file. It is NOT and never was mutual exclusion for `.agentic/context.md`: that file is now a derived rollup, deliberately written WITHOUT the lock, because it is recomposed from `_wrap.md` plus the per-session shards and a lost update self-heals on the next turn. (Naming `context.md` here was a false claim even before that change - the two hooks that "protected" it CHECKED the lock and neither ACQUIRED it, so it gave them no exclusion against each other. See `content/references/conductor-operating-rules.md` under "`.agentic/context.md` writer contract".)

- **If the lock is held by another session** (e.g., `/ds-wrap` is running concurrently in another session): skip Phase 11b with the operator note: `"Phase 11b skipped: /ds-wrap is running in another session."` Do NOT spawn `wrap-ticket`. Do NOT release the lock (this session never acquired it).
- **If the lock is acquired:** spawn `wrap-ticket` with the inputs below. The conductor releases the lock on every exit path (success, timeout, soft-fail) before proceeding to Phase 12.

**`wrap-ticket` spawn brief inputs:**

- `ticket_id`: the resolved ticket id.
- `ticket_title`: the ticket title.
- `ticket_description`: the full ticket description.
- `architect_plan_path`: absolute path to the architect's plan output (or in-context if no path).
- `brief_path`: absolute path to the Brief (or "n/a" if no Brief).
- `findings_log`: read from `.agentic/loop-state-$LOOP_KEY.json` `loop_state.findings_log` BEFORE Phase 12 clears the file.
- `qa_md_diff`: the diff between `.agentic/qa.md.snapshot-<ticket_id>` (created at Phase 0b for Elevated tickets) and the current working-tree `.agentic/qa.md`. Empty if no snapshot exists or qa.md is unchanged.
- `merged_diff`: `git -C $REPO diff origin/$BASE_BRANCH..HEAD` (the full ticket diff).
- `pr_url`: the PR URL captured at Phase 9.
- `conversation_summary`: a brief recap of the conductor's session covering this ticket.
- `learnings_extracted`: the `learning_ids[]` array from the `learning-extractor` return at Phase 6 clean exit (or `[]` if learning extraction was skipped/soft-failed).

**Failure semantics:**

- `wrap-ticket` failure NEVER blocks Phase 12 cleanup or PR completion. Soft-fail with a warning line printed to the operator.
- If `wrap-ticket` returns within 60s with a valid JSON shape: conductor parses the JSON and prints `operator_summary` to the user. If `size_advisory` is non-null, print it as a separate line.
- If `wrap-ticket` returns within 60s but the output is not parseable as JSON: conductor warns the operator (`"Phase 11b: wrap-ticket return was not valid JSON; proceeding without learnings capture."`) and proceeds.
- If `wrap-ticket` exceeds the 60s timeout: conductor warns the operator (`"Phase 11b: wrap-ticket exceeded 60s timeout; proceeding without learnings capture."`) and proceeds. Lock release for this outcome happens after the timeout fires, per the scoped release sentence below.
- If `wrap-ticket` returns with `skipped_reason` populated (zero-substance, wrap-lock-contention, etc.): conductor prints the `operator_summary` and proceeds without warning.

Lock release: this applies ONLY within the "If the lock is acquired" branch above - the conductor runs `agentic-wrap-release-lock` (PATH-wired helper) unconditionally on every `wrap-ticket` outcome in that branch (success, non-JSON return, timeout, soft-fail) before advancing to Phase 12. The two skip-conditions paths and the lock-held-by-another-session path never acquired the lock in this session and must NOT call the release helper.

**Post-return skill-candidate merge (conductor-side, runs AFTER lock release, soft-fail):**

After releasing the lock and after wrap-ticket has returned (or been skipped), the conductor performs this step if ALL of the following hold:
- wrap-ticket returned a valid JSON shape (not a timeout, not a non-JSON return).
- `cluster_results` in the return is a non-empty array.
- `skill_candidate_detection` is not `false` in `.agentic/config.json` (default true when absent or config missing).
- `$CLAUDE_CODE_SESSION_ID` is set and non-empty.

If any condition is not met, skip silently. This step is soft-fail and MUST NOT block or delay Phase 12 in any way.

```bash
# Conductor-side skill-candidate deep-cluster merge (post-return, soft-fail)
CLUSTER_TMP=$(mktemp /tmp/wrap-ticket-clusters-XXXXXX.json 2>/dev/null) && \
printf '%s' '<cluster_results JSON from wrap-ticket return>' > "$CLUSTER_TMP" && \
node hooks/lib/skill-candidate-deep-cluster.js "$REPO_CWD" "$CLAUDE_CODE_SESSION_ID" "$CLUSTER_TMP" 2>/dev/null || true
rm -f "$CLUSTER_TMP" 2>/dev/null || true
```

Where `$REPO_CWD` is the absolute project root and the `cluster_results` value from the wrap-ticket return is written to the temp file as a JSON array. Any failure (node not found, helper error, write error) is silently swallowed. This call is fire-and-forget; Phase 12 proceeds immediately after without waiting for any result.

**Post-return path parse (conductor-side, after skill-candidate merge):**

After the skill-candidate deep-cluster merge, parse the wrap-ticket return JSON into in-context variables for use by Phase 11c:

```bash
MEMORY_MD_PATH=$(printf '%s' "$WRAP_TICKET_RETURN" | jq -r '.resolved_paths.memory_md // empty' 2>/dev/null || true)
DECISIONS_MD_PATH=$(printf '%s' "$WRAP_TICKET_RETURN" | jq -r '.resolved_paths.decisions_md // empty' 2>/dev/null || true)
MEMORY_APPENDS_JSON=$(printf '%s' "$WRAP_TICKET_RETURN" | jq -c '.memory_md_appends // []' 2>/dev/null || printf '[]')
DECISIONS_APPENDS_JSON=$(printf '%s' "$WRAP_TICKET_RETURN" | jq -c '.decisions_md_appends // []' 2>/dev/null || printf '[]')
```

Where `$WRAP_TICKET_RETURN` is the raw JSON string returned by the wrap-ticket agent. On skip (Phase 11b skipped, timeout, or non-JSON return), all four variables are empty/`[]` and Phase 11c no-ops.

Emit breadcrumb: `[phase: wrap-ticket | ticket=<ticket_id> | status=<ok|skipped|failed>]`

---

## Phase 11c: Knowledge-file commit (soft-fail)

**Trigger:** runs after Phase 11b (and after the post-return path parse). Skip entirely when Phase 9 was skipped (no PR) or when the current ticket was Trivial (11b was skipped). No-ops when `MEMORY_MD_PATH` and `DECISIONS_MD_PATH` are both empty (wrap-ticket captured nothing or was skipped).

**Purpose:** the entries wrap-ticket appended to `MEMORY.md` and `decisions.md` live in the conductor's `$REPO` checkout (which is on the base branch on single-engineer paths). This phase appends those same entries to the feature branch so they appear in the PR diff as a `chore(knowledge):` commit. Append-based (never overwrites); idempotent on resume.

This entire phase runs in a **single Bash invocation** so `$$`, `KNOW_COMMITTED`, `CHECKOUT`, and `KNOW_WORKTREE` persist across steps.

```bash
# Phase 11c: Knowledge-file commit (soft-fail)
# Append helper: NUL-delimited whole-entry iteration (prevents line-splitting multi-line entries)
_ae_append_entries() {
  local target_file="$1" appends_json="$2" checkout="$3"
  local full_path="$checkout/$target_file"
  mkdir -p "$checkout/$(dirname "$target_file")" 2>/dev/null || true
  local existing_content=""
  [ -f "$full_path" ] && existing_content=$(cat "$full_path" 2>/dev/null) || true
  local norm_existing
  norm_existing=$(printf '%s' "$existing_content" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
  while IFS= read -r -d '' entry; do
    [ -z "$entry" ] && continue
    local norm_entry
    norm_entry=$(printf '%s' "$entry" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ' | sed 's/ *$//')
    if printf '%s' "$norm_existing" | grep -qFe "$norm_entry" 2>/dev/null; then continue; fi
    printf '%s\n' "$entry" >> "$full_path"
    norm_existing="$norm_existing $norm_entry"
  done < <(printf '%s' "$appends_json" | jq -j '.[] | . + "\u0000"' 2>/dev/null)
}

# 0. Nothing to do?
if [ -z "$MEMORY_MD_PATH" ] && [ -z "$DECISIONS_MD_PATH" ]; then
  STATUS=skipped
  echo "[phase: knowledge-commit | ticket=$TICKET_ID | status=$STATUS]"
else
  # 1. Resolve the checkout that is (or will be) on the feature branch.
  KNOW_WORKTREE=""
  if [ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BRANCH_NAME" ]; then
    CHECKOUT="$REPO"                      # fan-out: $REPO already on feature branch
  else
    git -C "$REPO" worktree prune 2>/dev/null || true
    KNOW_WORKTREE="$REPO/.agentic/worktrees/knowledge-commit-$$"
    git -C "$REPO" fetch origin "$BRANCH_NAME" 2>/dev/null || true
    if git -C "$REPO" worktree add "$KNOW_WORKTREE" "$BRANCH_NAME" 2>/dev/null; then
      CHECKOUT="$KNOW_WORKTREE"
    else
      CHECKOUT=""
      echo "WARNING: Phase 11c skipped - could not create worktree for $BRANCH_NAME"
    fi
  fi

  if [ -n "$CHECKOUT" ]; then
    KNOW_COMMITTED=false

    # 2. Append each new entry to its target file if not already present.
    #    Presence check mirrors wrap-ticket dedup: lowercase + whitespace-collapse + substring.
    for pair in "MEMORY_MD_PATH:MEMORY_APPENDS_JSON" "DECISIONS_MD_PATH:DECISIONS_APPENDS_JSON"; do
      f_var="${pair%%:*}"; a_var="${pair##*:}"
      KFILE="${!f_var}"; AJSON="${!a_var}"
      [ -z "$KFILE" ] && continue
      # Safety floor: never touch .agentic/ runtime state files on the feature branch.
      case "$KFILE" in .agentic/*) continue ;; esac
      _ae_append_entries "$KFILE" "$AJSON" "$CHECKOUT"
      git -C "$CHECKOUT" add "$KFILE" 2>/dev/null || true
    done

    # 3. Commit only if staging produced a diff (no empty commit; idempotent on resume).
    if ! git -C "$CHECKOUT" diff --cached --quiet 2>/dev/null; then
      DEVELOPER=$(agentic-identity show 2>/dev/null | awk '/^developer_id:/{print $2}')
      if agentic-identity show 2>/dev/null | grep -qE '^provisional:[[:space:]]+true'; then DEVELOPER=""; fi
      DEVTRAILER=${DEVELOPER:+"Developer: ${DEVELOPER}"}
      SO_NAME=$(git -C "$CHECKOUT" config user.name 2>/dev/null || git config --global user.name 2>/dev/null || true)
      SO_EMAIL=$(git -C "$CHECKOUT" config user.email 2>/dev/null || git config --global user.email 2>/dev/null || true)
      if [ -n "$SO_NAME" ] && [ -n "$SO_EMAIL" ]; then
        NL=$'\n'
        MSG="chore(knowledge): capture MEMORY.md and decisions.md for ${TICKET_ID}${NL}${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>${NL}${DEVTRAILER:+${DEVTRAILER}${NL}}"
        if git -C "$CHECKOUT" commit -m "$MSG" 2>/dev/null; then
          KNOW_COMMITTED=true
        else
          git -C "$CHECKOUT" restore --staged . 2>/dev/null || true
          echo "WARNING: Phase 11c commit failed"
        fi
      else
        git -C "$CHECKOUT" restore --staged . 2>/dev/null || true
        echo "WARNING: Phase 11c commit skipped - git user.name/email not set"
      fi
    fi

    # 4. Push only if a commit was made (fast-forward over Phase 8 HEAD; no force).
    if [ "$KNOW_COMMITTED" = "true" ]; then
      git -C "$CHECKOUT" push -u origin "$BRANCH_NAME" 2>/dev/null || \
        echo "WARNING: Phase 11c push failed - commit is local only"
    fi

    # 5. Cleanup ephemeral worktree (only when we created one). Always soft-fail.
    if [ -n "$KNOW_WORKTREE" ]; then
      git -C "$REPO" worktree remove "$KNOW_WORKTREE" --force 2>/dev/null || true
      git -C "$REPO" worktree prune 2>/dev/null || true
    fi

    if [ "$KNOW_COMMITTED" = "true" ]; then STATUS=committed; else STATUS=no-changes; fi
    echo "[phase: knowledge-commit | ticket=$TICKET_ID | status=$STATUS]"
  fi
fi
```

Note on `worktree prune`: prune clears stale git administration entries (dead symlinks) for worktrees whose directories no longer exist. It does NOT remove PID-suffixed directories left behind by interrupted runs - those must be manually removed or will be reused/overwritten by a subsequent `worktree add` with the same path. The `$$`-suffixed path ensures unique naming per run, limiting orphan accumulation.

**Failure semantics:** every git op soft-fails. Phase 11c NEVER blocks Phase 12 or PR completion. Does NOT write `loop-state-$LOOP_KEY.json`.

### Review-rigor PR-body evidence (soft-fail)

**This is an INDEPENDENT top-level step - it is NOT nested inside, and NOT gated by, the knowledge-file-commit block above.** It does not check `MEMORY_MD_PATH`, `DECISIONS_MD_PATH`, or the knowledge-commit block's `STATUS` variable. Most tickets produce no `MEMORY.md`/`decisions.md` appends (`STATUS=skipped` is the common case) - nesting this step inside that block's emptiness check would skip review-rigor evidence on the majority of PRs, reproducing the exact coverage gap DS-87 closes. This step fires on every PR where Phase 9 ran, whether or not wrap-ticket captured anything.

**Trigger:** runs after the knowledge-file-commit step above (same Phase 11c). Skip entirely when Phase 9 was skipped (no PR was opened) - same top-level Phase 11c trigger.

**Purpose:** appends a `## Review rigor` section to the PR body recording the Brief/Plan path, Skeptic round count and tier, and the final findings tally, so a reviewer can see review depth without reconstructing it from `loop-state-$LOOP_KEY.json` or the session transcript.

**Ordering dependency:** this step reads `.agentic/loop-state-$LOOP_KEY.json` `loop_state.findings_log` in its final (all-closed) state - the clean-exit auto-close at Phase 6 Step 3 sets every entry to `status: closed` before the loop exits. It must run BEFORE Phase 12 clears the file. Phase 11c as a whole already precedes Phase 12 (see the Phase 11b trigger note above), so this step inherits that ordering as long as it stays inside Phase 11c.

**Ticket scoping (closes a pre-existing latent bug).** The five `jq` reads below had **no ticket scoping at all** before per-ticket keying: they read one shared `.agentic/loop-state.json`, so in a batch they reported whichever ticket last wrote it. Every PR's `## Review rigor` section could therefore attribute another ticket's round count, tier, and findings tally to this ticket, with no gate able to fail on it. Reading `.agentic/loop-state-$LOOP_KEY.json` scopes them to this ticket by construction. Every read stays soft-fail (`2>/dev/null` plus a literal default) - an absent keyed file yields the same `n/a` / `0` defaults as before, never an error.

```bash
# Phase 11c: Review-rigor PR-body evidence (soft-fail, independent of knowledge-commit)
# BRIEF_PATH / ARCHITECT_PLAN_PATH are the shell-variable form of the conductor's in-context
# brief_path / architect_plan_path state (the same values passed to wrap-ticket's Phase 11b
# spawn inputs above) - "n/a" when absent, matching the existing $BRANCH_NAME / $GH_REPO pattern.

# Gate 1: PR resolvability only.
RR_PR_NUMBER=$(gh pr view "$BRANCH_NAME" --repo "$GH_REPO" --json number -q .number 2>/dev/null || true)

if [ -n "$RR_PR_NUMBER" ]; then
  RR_EXISTING_BODY=$(gh pr view "$RR_PR_NUMBER" --repo "$GH_REPO" --json body --jq '.body' 2>/dev/null || echo "")

  # Gate 2: idempotency - skip if body already has a filled contract line.
  if ! printf '%s' "$RR_EXISTING_BODY" | grep -qE '^- (Brief / Plan path|Skeptic rounds \(tier\)|Findings summary):[[:space:]]*[^[:space:]]'; then
    RR_BRIEF_OR_PLAN="n/a - single-unit Elevated"
    if [ -n "$BRIEF_PATH" ] && [ "$BRIEF_PATH" != "n/a" ]; then
      RR_BRIEF_OR_PLAN="$BRIEF_PATH"
    elif [ -n "$ARCHITECT_PLAN_PATH" ] && [ "$ARCHITECT_PLAN_PATH" != "n/a" ]; then
      RR_BRIEF_OR_PLAN="$ARCHITECT_PLAN_PATH"
    fi

    TIER_DISPLAY=$(jq -r 'if (.loop_state | has("tier")) then (.loop_state.tier|tostring) else "2 (default, undeclared)" end' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null || echo "2 (default, undeclared)")
    ROUNDS=$(jq -r '.loop_state.iteration // "n/a"' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null || echo "n/a")

    # Findings tally: count final findings_log entries by severity (all should be status:closed here).
    RR_CRITICAL=$(jq '[.loop_state.findings_log[]? | select(.severity=="Critical")] | length' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null || echo 0)
    RR_MAJOR=$(jq '[.loop_state.findings_log[]? | select(.severity=="Major")] | length' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null || echo 0)
    RR_MINOR=$(jq '[.loop_state.findings_log[]? | select(.severity=="Minor")] | length' .agentic/loop-state-$LOOP_KEY.json 2>/dev/null || echo 0)
    if [ "${RR_CRITICAL:-0}" = "0" ] && [ "${RR_MAJOR:-0}" = "0" ] && [ "${RR_MINOR:-0}" = "0" ]; then
      RR_FINDINGS_SUMMARY="No findings"
    else
      RR_FINDINGS_SUMMARY="Critical: ${RR_CRITICAL:-0}, Major: ${RR_MAJOR:-0}, Minor: ${RR_MINOR:-0}"
    fi

    RR_APPEND_FILE="/tmp/review-rigor-pr-body-$$"
    {
      printf '\n\n## Review rigor\n\n'
      printf -- '- Brief / Plan path: %s\n' "$RR_BRIEF_OR_PLAN"
      printf -- '- Skeptic rounds (tier): %s (Tier: %s)\n' "$ROUNDS" "$TIER_DISPLAY"
      printf -- '- Findings summary: %s\n' "$RR_FINDINGS_SUMMARY"
    } > "$RR_APPEND_FILE"

    printf '%s%s' "$RR_EXISTING_BODY" "$(cat "$RR_APPEND_FILE")" > "/tmp/review-rigor-full-body-$$"
    gh pr edit "$RR_PR_NUMBER" --repo "$GH_REPO" --body-file "/tmp/review-rigor-full-body-$$" 2>/dev/null || true
    rm -f "$RR_APPEND_FILE" "/tmp/review-rigor-full-body-$$" 2>/dev/null || true
  fi
fi
```

**Failure semantics:** every step soft-fails (`|| true` / `2>/dev/null`, matching Phase 11c conventions above). A missing `gh`, an unresolvable PR, or a malformed `loop-state-$LOOP_KEY.json` never blocks Phase 12. Does NOT write `loop-state-$LOOP_KEY.json`.

---

## Phase 12: Loop state cleanup

After the PR is open (Phase 9 complete) and Phase 11b has run (or been skipped), set `.agentic/loop-state-$LOOP_KEY.json` to `status: "complete"` using atomic write (tmp+rename), or delete the file. This prevents the next `/ds-implement-ticket` invocation on this project from presenting a stale completed loop as a resume candidate. The write applies Contract A (per-write `session_id` gate); abort with the verbatim warning on mismatch.

If the file does not exist (it was never written, e.g. loop never started), skip silently.

**`findings_log` clearing.** Phase 12 is the ONLY clearer of `findings_log`. The findings-curator at Phase 6 exit reads `findings_log` from `.agentic/loop-state-$LOOP_KEY.json` but does NOT clear it. Phase 11b's `wrap-ticket` reads `findings_log` BEFORE this Phase 12 cleanup. Setting `status: "complete"` (or deleting the file) is the moment `findings_log` is dropped.

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
  echo "Note: If auto-merge is off (default), run \`/ds-ticket-status-sync TICKET_ID\` after manual merge to push the Done transition to the tracker."
fi
```

**Tracker writeback (W7):** fires only if `gh pr merge` exits 0 (inside the `AUTO_MERGE_ON_CI_GREEN` gate and the isDraft/mergeable/reviewDecision inner check). If `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_DONE`, `forward_only_guard: true`. Fire-and-forget.

[phase: tracker-writeback | site: W7 | target: $TRACKER_STATE_DONE | trigger: auto-merge-success]

Note: W7 fires ONLY on the auto-merge success path (`AUTO_MERGE_ON_CI_GREEN=true` AND merge succeeds). On the default human-merge path (`AUTO_MERGE_ON_CI_GREEN=false`), W7 does NOT fire here. Run `/ds-ticket-status-sync <TICKET_ID>` after the PR is merged to push the Done transition to the tracker.

**Dry-run note (open-goal only).** When `batch-state.json.open_goal.dry_run == true`, `$PR_NUMBER` was never set (Phase 9 skipped) - skip the "Conditional auto-merge" block entirely (no PR). `loop-state-$LOOP_KEY.json` cleanup and qa.md snapshot cleanup run unmodified (both local-only).

---

## Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)

**Trigger:** `.agentic/batch-state.json` exists (set by Phase 0a when Phase 0 produced ≥ 2 entries during this session) OR set by Phase 0a-open-goal (`goal_mode=open_goal`) OR by the Phase 0a-pre single-ticket-capped carve-out (`max_wallclock_min` alone). Skip when batch-state.json is absent - covers ordinary uncapped single-ticket invocations, unchanged.

After Phase 12 completes for a ticket and BEFORE the conductor advances to the next ticket in the batch, first apply the goal-met short-circuit below, then (if it did not fire) evaluate the four handoff triggers. If a trigger fires, gracefully pause the batch and exit cleanly; if none fire, continue to the next ticket.

**Goal-met short-circuit (open-goal mode, evaluated before triggers 1-4).** If `batch-state.json.mode == "open_goal"` AND `batch-state.json.open_goal.termination_reason == "goal_met"` (set this iteration by Phase 6 "Open-goal condition check"): take the clean COMPLETE exit immediately - set `status: "complete"` on both `batch-state.json` and `.agentic/loop-state-$LOOP_KEY.json` (Contract A), print `OPEN-GOAL LOOP COMPLETE - goal_condition met after N iterations`, and exit the outer loop. Do NOT evaluate triggers 1-4. This guarantees a goal met on the final budgeted iteration (or coincident with a wallclock/iteration cap) records `goal_met`, not `cap_reached_*`, and the operator is not falsely told the goal was unmet. Rationale: `goal_met` is a success terminal state and always takes precedence over any cap/pause trigger that would otherwise fire on the same iteration.

**Triggers (exactly FOUR; any one fires; not evaluated when the goal-met short-circuit above already fired):**

1. **Stale-pace pattern.** The last 2 completed tickets each took more than 2× the median wallclock of completed tickets in this batch. Requires ≥5 completed tickets to be meaningful (below this threshold, sample size is too small to be a reliable signal). `pause_reason: "stale_pace"`. **In open-goal mode:** applies UNMODIFIED - `tickets[]` accumulates one synthetic entry per completed iteration, so the ≥5-completed threshold is satisfied by the same array. For `max_iterations < 5` (e.g. a dry-run test with `max_iterations=3`), trigger 1 is structurally inert (never reaches 5) - expected/correct (a loop capped below 5 is too short for a meaningful pace signal, matching the threshold's own rationale). **In single-ticket-capped mode:** structurally inert (one entry, no pace signal past a single completion).
2. **Operator literal "pause the batch".** Case-insensitive substring match against the most recent operator message. `pause_reason: "operator_pause"`. **In open-goal mode:** applies UNMODIFIED - substring match is orthogonal to mode. **In single-ticket-capped mode:** mode-orthogonal and DOES apply - the operator can still pause a single capped run.

   **Invariant (binding).** The conductor MUST NOT write `pause_reason: "operator_pause"` to `batch-state.json` unless the operator's most recent message contains the literal substring `pause the batch` (case-insensitive). Conductor self-doubt about remaining wallclock, context pressure, perceived pace, or "feeling like the operator might want a break" is NOT a valid `operator_pause` trigger. The correct conductor behavior in those subjective cases is to spawn the next ticket and let `wallclock_cap` (trigger 3) fire mechanically if the cap is actually hit. A conductor that paraphrases the operator, infers intent from "I'm tired" / "let's stop soon" / "we're running long", or pauses preemptively to avoid a future cap hit is violating this invariant - the operator's literal words are the authoritative trigger. If an operator phrases a pause request differently (e.g. "stop after this one"), the correct response is to surface a one-line confirmation (`Proceeding to pause the batch after the current ticket - confirm with 'pause the batch' or override with 'continue'.`) and continue executing until the literal substring arrives.
3. **Wallclock cap.** `now - wallclock_started_at >= wallclock_cap_min` (default 90 min unless `AGENTIC_BATCH_MAX_WALLCLOCK_MIN` env override). `wallclock_started_at` is preserved across resume, so the cap is per-batch lifetime, not per-session. `pause_reason: "wallclock_cap"`. **Single-ticket-capped mode:** trigger 3 is the reason this mode exists - same wallclock-blocked-write action as before.
4. **Open-goal iteration cap** (`mode=="open_goal"` only; inert for `batch`/`single_ticket_capped`). `batch-state.json.open_goal.iteration >= batch-state.json.open_goal.max_iterations`. `pause_reason: "open_goal_iteration_cap"`.

**Single-ticket-capped mode summary:** triggers 1 and 4 are structurally inert (no pace signal past a single entry; no iteration concept). Trigger 2 (operator literal "pause the batch") is mode-orthogonal and DOES apply - the operator can still pause a single capped run. Trigger 3 (wallclock cap) is the reason this mode exists.

(Context-pressure auto-detection is explicitly NOT a trigger; the conductor cannot read its own context %. Operators use trigger 2 if context pressure is observed.)

**On trigger - batch and single-ticket-capped modes (`mode != "open_goal"`):** apply Contract A + Contract B and write `batch-state.json` with:
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
Resume: /ds-implement-ticket from this directory
```

**Single-ticket-capped mode, trigger 3 only** (triggers 1/4 structurally inert): reuse the "Batch-mode escalation routing" blocked-write, print `SINGLE-TICKET WALLCLOCK CAP REACHED - pause_reason: wallclock_cap`, `status: "paused"`, exit cleanly.

Note: N is the executable-cursor count (lane-assigned tickets only). Deferred and in-progress-excluded tickets were surfaced in Phase 0a step 2 and are not included in N.

Exit cleanly. Do NOT advance to the next ticket. Emit breadcrumb: `[phase: batch-paused | reason=<trigger>]`.

**On trigger - open-goal mode (`mode=="open_goal"`), ANY of the four triggers:** in addition to the existing `batch-state.json{status:"paused", paused_at, pause_reason:<trigger>, last_summary}` write (Contract A+B, unchanged, applies to all 4 as above), ALSO write `open_goal.termination_reason`: trigger 1 → `"paused_stale_pace"`, trigger 2 → `"paused_operator_request"`, trigger 3 → `"cap_reached_wallclock"`, trigger 4 → `"cap_reached_iterations"`. Print header (all 4 triggers): `OPEN-GOAL LOOP PAUSED - pause_reason: <trigger>` (replacing `BATCH PAUSED`); resume line: `Resume: /ds-implement-ticket ... goal_mode=open_goal ... (raise max_iterations/max_wallclock_min to continue, or accept the goal as unmet)`. Single mode-conditional branch covering all four triggers.

**On no trigger, batch and single-ticket-capped modes:** continue to the next ticket in the batch.

**On no trigger, open-goal mode:** the goal-met short-circuit above already handles the `termination_reason == "goal_met"` case before triggers are evaluated, so reaching this branch means the goal was not yet met on this iteration. Apply the "Advance to next iteration" write from Phase 0a-open-goal - Contract A+B write incrementing `open_goal.iteration` AND appending the next `pending` synthetic `tickets[]` entry IN THE SAME WRITE (keeps `iteration == len(tickets[])` intact) - and continue the outer loop at Phase 1.

> Note: `paused_at` and `pause_reason` are written by Phase 12a on graceful handoff. `interrupted_at` and `interrupt_reason` are written by the SessionEnd hook (`hooks/session-end-wrap.js`, once per session, on a terminal reason) or on crash - see Contract D. These are two distinct paths; `last_summary` is only populated on graceful pause (the SessionEnd hook cannot synthesize it).

---

## Phase 12b: Operator Runbook

**Trigger:** fires once per session, at the point the session's ticket-processing work concludes - not once per ticket. Single-ticket mode: once, after Phase 12a for the one ticket. Batch mode (including single-ticket-capped and open-goal): once, after the LAST ticket processed in this session, when the outer loop is about to exit because all tickets in `batch-state.json.tickets[]` have reached a terminal state (no `pending` or `in_progress` remaining) and Phase 12a did not pause the batch. Do NOT print the runbook after every individual ticket's Phase 12a evaluation while more tickets remain to process in this session - a 5-ticket batch prints ONE runbook, not five.

**Skip conditions:**
- Phase 9 was skipped (no PR was opened, e.g. open-goal dry-run): skip silently.
- Phase 12a already exited the outer loop (goal-met short-circuit fired): skip - the goal-met exit already prints a terminal summary.
- Phase 12a triggered a pause this session (any of the four triggers, any mode - batch, single-ticket-capped, or open-goal): skip - Phase 12a's own pause summary (`BATCH PAUSED` / `OPEN-GOAL LOOP PAUSED` / `SINGLE-TICKET WALLCLOCK CAP REACHED`) already states what completed so far and the correct resume command; a second, differently-worded next-command block from Phase 12b would contradict it (12a's `Resume: /ds-implement-ticket from this directory` resumes the paused batch cursor - a different operation from a fresh `/ds-implement-ticket <ticket_id>` invocation).

**Failure semantics:** soft-fail throughout. Any error reading state files is swallowed; the runbook degrades gracefully to whatever information is available. Phase 12b NEVER blocks Phase 12 cleanup, PR completion, or batch advancement.

**Output format:** the runbook is printed as plain operator-readable text, not structured JSON. It is plan-only - it suggests commands, never invokes them (yolo-guard applies). All file paths in pasted command lines are absolute (operator handoff convention).

---

**What to render:**

### 1. What landed

For each PR opened this session (collected from Phase 9 across all completed tickets), print one line:

```
✓  PR #<number>  <ticket_id>  → <pr_url>
```

Derive the list from the session's completed `tickets[]` entries in `.agentic/batch-state.json` (fields `pr_number` and `ticket_id` - the actual schema; there is no `pr_url` or `ticket_title` field). Construct `pr_url` as `https://github.com/$GH_REPO/pull/<pr_number>`, matching the pattern used at Phase 11 (`PR_URL`: `https://github.com/[GH_REPO]/pull/[PR_NUMBER]`). Do not print a ticket title - it is not a `batch-state.json` field, and adding one is a schema change out of scope for this change. For single-ticket mode (no `batch-state.json`), derive from the in-context `PR_NUMBER` set at Phase 9 and the `PR_URL` constructed at Phase 11.

### 2. Next command

This phase's own trigger condition (see above) guarantees every ticket in `.agentic/batch-state.json.tickets[]`, when the file exists, has already reached a terminal state - no `pending` or `in_progress` entries remain to resume. So the next command is always derived from a triage artifact, never from an in-batch "remaining tickets" scan.

Check for a triage artifact: glob `docs/planning/triage-*.md` - pick the newest by mtime. `.agentic/triage-*.md` is not a valid fallback path: `/ds-ticket-triage` explicitly writes no `.agentic/` state (`content/commands/ds-ticket-triage.md`'s header and Phase 0 both state "No `.agentic/` state writes"), so no file can ever exist there. If a triage artifact is found, extract the next recommended lane's ticket IDs from its "## Kickoff prompts" section (heuristic: first lane block not covered by tickets already landed this session). Each lane block already contains a literal copy-pasteable `/ds-implement-ticket <ticket_ids>` code fence (see `content/commands/ds-ticket-triage.md` Phase 4a artifact skeleton) - reuse it verbatim rather than reconstructing the command. Do not look for a `lanes[]` field on the artifact: `lanes[]` is the in-memory `triage_result` structure Phase 0a builds during triage (`{lanes[], deferred[], in_progress_excluded[], functional_duplicates[], conflict_warnings[], heuristic_only}`), not a field of the rendered markdown - the on-disk artifact has no such field.

```
Next:  /ds-implement-ticket <lane_tickets>
       (from: <absolute_path_to_repo>)
       Triage artifact: <absolute_path_to_triage_file>
```

If no triage artifact exists, print:

```
Next:  /ds-ticket-triage   # no outstanding work detected; re-triage to pick next batch
       (from: <absolute_path_to_repo>)
```

### 3. Blockers and deferred items

Collect any blockers surfaced during this session:

- QA-blocked units: any ticket in this session whose Phase 6b QA gate resulted in `qa_blocked` or INCONCLUSIVE (`qa_unverified=true`), per `content/references/qa-gate.md` §"Per-ticket, in-flow" and §"INCONCLUSIVE classification". Track these in-context as they occur during this session's Phase 6b runs - do not re-read them from `findings_log` (which holds Skeptic findings only, status `open`/`addressed`, and is never written a `qa_blocked` entry) or from `.agentic/qa.md` (supplemental QA project-knowledge - dev server config and project quirks - not a per-ticket status log). **Known gap:** neither `qa_blocked` nor `qa_unverified=true` is written to any durable state file (`.agentic/loop-state-$LOOP_KEY.json`'s `qa_failures_log` tracks Skeptic-visible QA fail/retry cycles, not the blocked/INCONCLUSIVE terminal outcome, and it is ticket-scoped - cleared at that ticket's own Phase 12, before this phase runs. Under per-ticket keying it is **no longer overwritten by the next ticket** - the next ticket writes its own keyed file - but that changes nothing about this gap, whose cause is that the outcome is never written at all). This item is therefore best-effort within the current session only and does not survive a resumed session: a batch that hits `qa_blocked` in session A and is resumed and finished in session B will not re-surface that blocker here.
- Batch-escalated tickets: any ticket in `.agentic/batch-state.json.tickets[]` with `status: "blocked"` (written by the "Batch-mode escalation routing (mark-blocked-and-continue)" path on Skeptic/QA `cap_reached`) - print the ticket ID and its `last_summary`. This is the one blocker class that IS durable (written directly to `tickets[]`), so include it even on a resumed session.

Print:

```
Blockers / deferred:
  · <item description>
```

If no blockers, omit this section entirely (keep output clean for smooth runs).

---

**Full runbook example output:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPERATOR RUNBOOK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What landed:
  ✓  PR #451  DS-69  → https://github.com/…/pull/451
  ✓  PR #452  DS-52  → https://github.com/…/pull/452

Next:
  /ds-implement-ticket DS-45, DS-50
  (from: /Users/dev/project)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Emit breadcrumb: `[phase: operator-runbook | tickets_landed=<k> | blockers=<n>]`
