# Implement Ticket

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

> **Context-size preflight (right after Activation).** Check the session against `content/references/subagent-protocol.md` Section 13. **At the hard limit (13.2)** there is no override: print `Context-size hard limit reached (Subagent Protocol 13.2): no further implementation, Skeptic rounds, or spawns this session. Next: /ds-wrap, start a new session, then /ds-implement-ticket <your input>.`, invoke `/ds-wrap` (or tell the operator to), and exit. **Below it**, when the turn count is at the soft limit with substantive results in context, or a substantive prior subagent result from before this invocation is visible, print `Context-size warning: this session carries significant prior context. Safe pattern: /ds-wrap, new session, /ds-implement-ticket <your input>. Proceed anyway? (yes / no)` and wait. `no`: exit. `yes`: print `Context-size warning acknowledged - proceeding in large session.` Otherwise continue silently.

Take a ticket (Linear, Jira, or none) from description to merged PR: Architect, Orchestration Planner (conditional), Engineer, Skeptic, QA, PR, CI, tracker post.

## Invocation

`/ds-implement-ticket <input>`: a ticket ID (`DINO-639`), a comma/space list, a tracker issue URL (Jira `/browse/DINO-639`, Linear `/issue/ENG-42/...`), a tracker search/filter URL, a pasted board screenshot, a freeform description, any mixture, or a `.agentic/phase0-classifiers.yml` match.

**Trailing key=value parameters (optional):** `goal_mode=open_goal`, `goal_condition="<string>"`, `max_iterations=<int>`, `max_wallclock_min=<int>`, `dry_run=true`. Strip them (`\w+=(\S+|"[^"]*")`) before Phase 0 classifies. `dry_run` only means anything with `goal_mode=open_goal`; elsewhere it is ignored.

---

## Conductor rules (binding)

- **Conductor-owned, never delegated:** risk classification before any spawn; Brief/Plan authoring at the promotion gate; every stop-and-ask; all `.agentic/*.json[l]` writes (sole writer across agents; `tasks.jsonl` is append-only and read through the task-state fold, `content/references/task-state-file.md`); loop history and re-route limits; `[phase: ...]`/`[loop: ...]` breadcrumbs; dispatch; summary synthesis (PR body, tracker comment: `conventions-detail.md` §External Comment Discipline); Setup; `gh pr create`; the CI wait; fan-out worktree creation.
- **The conductor never edits the shippable tree.** Every change, Trivial included, is made by a worktree-isolated `engineer`.
- **Spawn shape.** Keep the background default of `run_in_background` (never pass `false`) and wait for the completion notification; only `wrap-ticket` (Phase 11b) is synchronous. `engineer` and `qa-engineer` spawns set `isolation: "worktree"`. Use the named agents. Canonical: `content/sections/02-delegation.md`.
- **Skeptic spawns** carry the `## Global-context inputs` block (`content/references/skeptic-protocol.md` Section 4.5, 7 fields). Field 6 leads with the stable unit key and `| ` (`${LOOP_KEY}-plan`, `$UNIT_KEY`, BASE`-single`, `-meta`); the round-cap hook keys on it, and past the cap only an operator grant reopens the unit. Every brief field is a slot (`subagent-protocol.md` §11): no conductor conclusion about the artifact under review.
- **Telemetry.** Hooks emit `spawn_start`/`spawn_complete` for every spawn. At each conductor `ds-emit` call site `export AGENTIC_LOOP_KEY="$LOOP_KEY"` first and put `"session_uuid":"$CLAUDE_CODE_SESSION_ID"` in the data (`METHODOLOGY.md` §Events log).

- **Never:** `git add -A`/`git add .`; force-push; defer a Major on an engineer's say-so; deliver a fix pass via `SendMessage` (fix passes are fresh spawns); re-derive `LOOP_KEY` or derive it from a branch name; fire `TRACKER_STATE_DONE` automatically; synthesize fix suggestions in an escalation; put a bare `null` in a spawn brief (render `n/a`).
- **Act and report.** Take the default and proceed when a source can supply it (`02-delegation.md` default-and-proceed); stop only for a fact only the operator holds, a stop condition below, or a destructive or grant-gated step.

---

## Setup call (runs first)

Run once, before anything else, from `$REPO`. On a harness without `$CLAUDE_CODE_SESSION_ID`, add `--session-id <SESSION_ID>`. Put `<input>` verbatim inside the quoted heredoc only, so no shell expands it; if it has a line reading `DS_INPUT`, pick another delimiter.

```bash
# Setup call: ds-ticket-setup
REPO_DIR="$(jq -r '.repo_dir // empty' "$HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"
[ -x "$REPO_DIR/bin/ds-ticket-setup" ] || REPO_DIR="$HOME/DinoStack"
"$REPO_DIR/bin/ds-ticket-setup" --stdin <<'DS_INPUT'
<input>
DS_INPUT
```

If it exits non-zero or line 1 is not a JSON object with a non-empty `loop_key`, stop and report its stderr; never proceed without a `loop_key`. Line 1: `repo_dir` (`REPO_DIR`), `base_branch` (`BASE_BRANCH`; print `BASE_BRANCH resolved to: [value]`), `tracker` (the `ds-tracker resolve --json` object), `ticket_id` (or null), `loop_key` (`LOOP_KEY`, derived once; never re-derived), `resume` (`keyed`, `legacy`, `others`, each with a `verdict` of `resumable|live|clear|parse_error|unknown`, plus `recommended`), `mode` (`open_goal`, `batch`, `resume` or `single`), `rework` (`rework_detection`, `prior_attempts`, `is_rework`, `prior_completed`, most recent last).

**Mode dispatch.** For `batch` and `open_goal` the output continues after a `--- procedure: <path> ---` line with that mode's procedure (`batch-mode.md`, `open-goal-loop.md`): that is the Read the Phase 0a-pre / 0a / 0a-open-goal pointers call for. `resume` continues with `cross-session-loop-resume.md`; apply Resume below. `single`: Phase 0. A batch only Phase 0 can see (a search URL, a screenshot) takes the pointer Read.

**Rework re-run.** When Phase 0 resolves a single entry whose id differs from `ticket_id` (or `ticket_id` is null), and for each batch entry at Phase 1, re-run with that id and take its `rework`; the first call's `loop_key` and `resume` stand. Non-zero exit or no `rework`: stop and report stderr.

```bash
# Setup call: rework re-run
REPO_DIR="$(jq -r '.repo_dir // empty' "$HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"
[ -x "$REPO_DIR/bin/ds-ticket-setup" ] || REPO_DIR="$HOME/DinoStack"
"$REPO_DIR/bin/ds-ticket-setup" --rework-only --ticket - <<'DS_INPUT'
<ticket id>
DS_INPUT
```

A batch entry's own `LOOP_KEY`, `resume` and `rework` come from:

```bash
# Setup call: batch entry
REPO_DIR="$(jq -r '.repo_dir // empty' "$HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"
[ -x "$REPO_DIR/bin/ds-ticket-setup" ] || REPO_DIR="$HOME/DinoStack"
"$REPO_DIR/bin/ds-ticket-setup" --ticket - <<'DS_INPUT'
<ticket id>
DS_INPUT
```

### Resume

Only `.agentic/loop-state-$LOOP_KEY.json` is recommended (`resume.recommended`); key match, never freshness, selects it. For other resumable keys print one line, `N other resumable loops exist: <up to 3 keys>[, +M more]. Re-invoke with that ticket id to resume one.`, never a ballot.

- **Resumable** (`interrupted`, or `active` with `last_updated` over 10 minutes old): print branch, ticket, `last_phase`/`last_phase_action`, iteration, open findings; ask `Resume this loop or start fresh? (resume / fresh)`. `fresh`: delete **only** `.agentic/loop-state-$LOOP_KEY.json` and proceed. `resume`: on `interrupt_reason == "rate_limit"` wait out 60s from `interrupted_at`; increment `resume_count`; enter per the table.
- **Live** (`active`, fresh): no prompt. **`complete`/`stalled`:** print a clearing line and delete that keyed file only. **Parse failure:** warn and offer to delete that one candidate.
- **Legacy `.agentic/loop-state.json`**, resumable with no keyed file: adopt it under its `ticket_id`, else `session-<its session_id>`, else `legacy` (atomic keyed copy with `loop_key` set and `resume_count` incremented, then `rm -f .agentic/loop-state.json` (loop-key: legacy)), then resume. A resumable keyed file wins over legacy. A `session-*` candidate adopted on a null ticket keeps its own `loop_key`. A `loop_key` field disagreeing with its filename: the filename selects, the field is the key; warn once.
- **After resuming - resolve and print `TRACKER_TRANSITIONS_MODE` before jumping to any entry point.** Also run `git -C $REPO diff origin/$BASE_BRANCH..HEAD` before any spawn (empty with open findings: the work was lost; tell the operator) and re-read any Brief/Plan.

**Entry by `last_phase`/`last_phase_action`:** a `spawned` agent is re-spawned with its prior brief (Skeptic on the current diff, with the prior-iteration findings block; an engineer only on a clean `git status --porcelain`, else ask "discard and re-run, or commit and re-run Skeptic?"); after a `returned` agent its next step runs (Skeptic: the fix pass on open findings; engineer: the Skeptic with `last_engineer_summary`; QA: its fix pass; Debugger: the fix pass with its Fix brief). `quality_gate|engineer_returned` or `rerun_pending`: verify `quality_gate_results` (Trivial: re-run `$QUALITY_CMD`). `ci_wait|timeout`: with `auto_merge_queued` true run `gh pr view $PR_NUMBER --json state -q .state` first (`MERGED` skips to Phase 10b; never re-queue), else re-run the Phase 10 call once. `ci_loop`: re-spawn the fix engineer or re-run the Phase 10 call at cycle N; `cap_exceeded` never auto-resumes. In the `skeptic` loop `max_iterations` 2 means `ELEVATED_ROUTE=single-review`.

### Project config

From `AGENTS.md` and `.agentic/config.json` (default in parentheses):

- `REPO` (repo root), `GH_REPO` (slug), `QUALITY_CMD`, `PR_WORKFLOW_REVIEWERS` (`## PR Workflow` `Reviewers:`, empty).
- `DEBUGGER_ON_FAILURE` (`debugger_on_failure`, false), `AUTO_MERGE_ON_CI_GREEN` (`auto_merge_on_ci_green`, false), `REWORK_DETECTION` (`rework_detection`, true; false turns off the ledger write, detection, notice and escalation).
- `TRACKER_STATE_DIAGNOSTIC` - `tracker_state_diagnostic` (true); false skips the writeback subagent's diagnostic enrichment.

**Tracker.** Take the Setup call's `tracker` object (`ds-tracker resolve --json`, which applies the AGENTS.md chain, the `.agentic/tracker.yml` overlay merge, its four states `ok`/`absent`/`no_tracker`/`unusable`, and the `## Linear` shape guard): `TRACKER` (`linear|jira|none`), `TICKET_PREFIX`, `LINEAR_WORKSPACE`/`JIRA_BASE_URL`, the optional QA assignee/transition, the six `TRACKER_STATE_*` values, `TRACKER_DEV_COMPLETE_DECLARED`, `TRACKER_PIPELINE_ORDER`, and `TRACKER_TRANSITIONS_MODE` (`auto|manual`; `no_tracker` still honors it). When `tracker` is null, resolve by hand:

1. If a `## Tracker` section exists in `AGENTS.md` and contains `TRACKER: jira`: `TRACKER=jira`; read `TICKET_PREFIX`, `JIRA_BASE_URL`, optional `JIRA_QA_ASSIGNEE_ACCOUNT_ID`/`JIRA_QA_TRANSITION`, and optional `JIRA_STATE_IN_PROGRESS`/`_IN_REVIEW`/`_QA`/`_DEV_COMPLETE`/`_BLOCKED`/`_DONE` (defaults `In Progress`, `In Review`, `QA`, the RESOLVED `TRACKER_STATE_DONE` value for this project, `Blocked`, `Done`). `TRACKER_DEV_COMPLETE_DECLARED` is `true` when `JIRA_STATE_DEV_COMPLETE` (or overlay `state_dev_complete`) is declared, tested BEFORE applying the inherited default. A dev-complete lane that sits BEFORE your QA lane needs `JIRA_PIPELINE_ORDER` (e.g. `IN_PROGRESS, IN_REVIEW, DEV_COMPLETE, QA`). Also extract an optional pipeline-order override: `JIRA_PIPELINE_ORDER` -> `TRACKER_PIPELINE_ORDER` (3 or 4 distinct tokens: `IN_PROGRESS`, `IN_REVIEW`, `QA`, optional `DEV_COMPLETE`; default `IN_PROGRESS, IN_REVIEW, QA` when absent); a malformed value prints `WARNING: JIRA_PIPELINE_ORDER '<value>' is not a valid ordering of IN_PROGRESS/IN_REVIEW/QA with optional DEV_COMPLETE - using the default order.`
2. Else if a `## Tracker` section exists with `TRACKER: linear`: as item 3, reading the same fields (state overrides and `Pipeline order:`) from `## Tracker`.
3. Else if a `## Linear` section exists: `TRACKER=linear`; `Team` -> `TICKET_PREFIX`, `Workspace` -> `LINEAR_WORKSPACE`, optional `QA assignee ID`, and optional `State In Progress:`/`State In Review:`/`State QA:` (default `Testing`)/`State Dev Complete:` (default the RESOLVED `TRACKER_STATE_DONE` value for this project)/`State Blocked:`/`State Done:`. `TRACKER_DEV_COMPLETE_DECLARED` is `true` when `State Dev Complete:` (or overlay `state_dev_complete`) is declared, tested BEFORE applying the inherited default; a dev-complete lane that sits BEFORE your QA lane needs `Pipeline order:`. Also extract an optional pipeline-order override: `Pipeline order:` -> `TRACKER_PIPELINE_ORDER`, same syntax, validation, and default as the Jira `JIRA_PIPELINE_ORDER` field above.
4. Else: set `TRACKER=none`. States take their defaults (QA `Testing`, `TRACKER_STATE_DEV_COMPLETE="Done"` (the resolved `TRACKER_STATE_DONE` value)); `TRACKER_DEV_COMPLETE_DECLARED=false`; set `TRACKER_PIPELINE_ORDER` to its default `IN_PROGRESS, IN_REVIEW, QA`.

 A `## Linear` section with no `Workspace:` stops the run: `Your tracker config is missing fields /ds-implement-ticket needs. Run /ds-init-project to update it.`

Print before Phase 1:

```
Tracker:                    [linear | jira | none, or "none (.agentic/tracker.yml present but unusable: <reason>)"]
Tracker config source:      [.agentic/tracker.yml (overrides: <fields>) | (n/a - AGENTS.md only)]
TICKET_PREFIX:              [value or "n/a"]
BASE_BRANCH:                [value]
AUTO_MERGE_ON_CI_GREEN:     [true | false]
PR_WORKFLOW_REVIEWERS:      [usernames or "(none)"]
TRACKER_STATE_*:            [IN_PROGRESS / IN_REVIEW / QA / DEV_COMPLETE / BLOCKED / DONE values]
TRACKER_PIPELINE_ORDER:     [value]
TRACKER_TRANSITIONS_MODE:   [auto | manual]
```

When `manual`, the last line reads `TRACKER_TRANSITIONS_MODE:   manual - no automatic tracker state transition will fire this run. Run `ds-tracker set transitions auto` to re-enable.` This print (and its resume-path twin) is the run's only kill-switch notice.

## Tracker Writeback Helper

Full reference (invocation contract, forward-only guard, diagnostic enrichment, failure logging): `content/references/tracker-writeback.md` `## Tracker Writeback Helper`; Read it before the first writeback. Gated on `TRACKER != none`.

**Caller enumeration:** W1-W7 and Phase 11 are fire-and-forget; every caller passes `forward_only_guard: true`, `tracker_state_values` (the six values), `pipeline_order`, `dev_complete_declared` and `transitions_mode: $TRACKER_TRANSITIONS_MODE`. Statuses: `ok | partial | failed | skipped_unconfigured_state | skipped_transitions_manual`. Fire-and-forget sites print one `SKIPPED:` stderr line per `skipped_unconfigured_state` and emit NO stderr line for this status `skipped_transitions_manual` (the Setup print already says it). The ranking never reads `.agentic/tracker-states.json`.

## Tracker Create Helper

Synchronous; for the ticket-offer gate (`content/sections/02-delegation.md` §Ticket-offer gate); any other ticket needs an explicit operator yes.

**Collision pre-check (runs BEFORE the create branches):** scan in-flight tickets in the same tracker project/team (open and in progress) for overlapping files, symbols, tables or shared config. On overlap append a binding `## Scope boundary` section naming who owns what; with no clean split, stop and surface it. Then Read `$REPO_DIR/content/references/tracker-create.md` §Tracker Create Helper before any step here; follow it.

---

## Phase 0: Input normalization

Produce in-memory `normalized_input {entries[], freeform_task, additional_operator_context, resolution_notes[]}`; no disk writes.

**Fast paths (silent):** a single token matching `^[A-Z][A-Z0-9_]+-\d+$` and `TICKET_PREFIX`; or `TRACKER == none` with freeform text only (`freeform_task=<input>`).

**Classifiers, in order:** bare IDs `^[A-Z][A-Z0-9_]+-\d+$` and lists; Jira `/browse/<ID>` and JQL URLs (`mcp__mcp-atlassian__jira_search`); Linear `/issue/<ID>` and filter URLs (`mcp__linear__list_issues`); an attached image (read it yourself, never spawn OCR); then `.agentic/phase0-classifiers.yml` on what fell through. That file runs with conductor privileges (review it on an untrusted branch): shell-escape capture groups (`'` as `'\''`); stdout JSON `{ticket_id, title?}` or an array; non-zero exit or 10s timeout means no entries.

**Limits:** cap 50 per URL (`narrow / proceed`); over 200 entries is a hard refusal; dedupe by `ticket_id`, first seen wins.

**Confirm only for:** a screenshot (`proceed / abort`); entries plus residue (`attach-to-all / drop / abort`, default attach as `additional_operator_context`); a cap hit; no IDs with a tracker (`freeform / abort`). JQL results and lists over 5 print the IDs and proceed. A JQL auth failure aborts; nothing at all exits. `[phase: input-normalization | entries=<N> | freeform=<bool> | extra_context=<bool>]`

Carry a ticket's `## Scope boundary` section into the architect and engineer briefs; when absent and the tracker supports queries, run the Create Helper's overlap scan before the architect spawn (best-effort).

## Phase 0a-open-goal: Open-goal loop init or resume (conditional)

**Trigger:** `goal_mode=open_goal`; skips Phase 0a-pre and 0a. Read `$REPO_DIR/content/references/open-goal-loop.md` §Phase 0a-open-goal: Open-goal loop init or resume (conditional) before any step here; the Setup output carrying it is that Read.

## Phase 0a-pre: Batch resume check

**Trigger:** Phase 0 produced 2+ entries. A single entry with `max_wallclock_min` and no `goal_mode` applies Contract C only, then creates `batch-state.json{mode:"single_ticket_capped", tickets:[<the entry>], wallclock_cap_min, wallclock_started_at}` (the only N=1 path that creates it). Read `$REPO_DIR/content/references/batch-mode.md` §Phase 0a-pre: Batch resume check before any step here; the Setup output carrying it is that Read.

## Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries)

Read `$REPO_DIR/content/references/batch-mode.md` §Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries) before any step here; the Setup output carrying it is that Read.

## Phase 0b: Brief check + qa.md snapshot

- **Brief:** slug = kebab-case title without the ticket prefix. `docs/planning/<slug>.md` exists, or `.agentic/brief-session.json` is `complete` for it: set `brief_path`, skip the conductor-authored Brief at the promotion gate, use the operator-confirmed Skeptic variant (`ds-brief.md` Section 6); with `brief_source: operator` set `operator_brief_injectionable: true`.
- **qa.md snapshot (Elevated only, once risk is known):** copy `.agentic/qa.md` atomically to `.agentic/qa.md.snapshot-<ticket_id>` unless that exists. Trivial never touches it.
- A fresh Elevated ticket without `qa_criteria` is a Critical plan finding. A resumed one: copy the plan's block into the Brief, else ask `(a) paste a qa_criteria block / (b) one-time bypass`.

---

## Phase 1: Understand the ticket

Once per entry. With no entries and a `freeform_task`, only the `none` branch runs. Prefix any `additional_operator_context` to every architect and engineer brief as `Additional operator context (applied to all entries):`.

### Per-ticket variable reset (binding, runs FIRST on every entry)

One variable scope spans a batch; each value feeding the ledger, the REWORK notice or the W1 breadcrumb has one definition site, so clear them per entry:

```bash
# Phase 1: per-ticket variable reset (runs first on EVERY entry, before sub-section dispatch).
RISK_CLASS=""
SKEPTIC_ROUNDS=""
QA_STATUS=""
W1_FETCH_FAILED=false
W1_DISPATCH_OUTCOME=""
ELEVATED_ROUTE=""
```

#### If TRACKER is `linear`

`mcp__linear__get_issue` (`includeRelations: true`); on error `W1_FETCH_FAILED=true`. Read Implementation, Files and QA; confirm `blockedBy` tickets are done; the type drives branch naming. `mcp__linear__list_comments`: comments containing `QA` and one of `FAIL`, `PARTIAL`, `BLOCKED`, `failed`, `re-work` go to `PRIOR_QA_COMMENTS`; `COMMENT_THREAD_SUMMARY` = all bodies, 2000 chars max; both empty on error.

#### If TRACKER is `jira`

`mcp__mcp-atlassian__jira_get_issue` (`fields: "*all"`); on error `W1_FETCH_FAILED=true`. Same reads; parse comments from that response (no second call) the same way.

#### If TRACKER is `none`

Use `freeform_task` as the ticket; type `feature` unless stated; `PRIOR_QA_COMMENTS=[]`, `COMMENT_THREAD_SUMMARY=""`.

### Ticket-rework detection

Once per entry, after the branch above: the Setup `rework` object (or the re-run's) gives `PRIOR_ATTEMPTS`, `IS_REWORK`, `PRIOR_COMPLETED` from `.agentic/ticket-ledger.jsonl` (exact `ticket_id`, deduped by `pr_number` keeping the latest `opened_ts`; no ledger is 0). When `IS_REWORK`, print before any spawn:

```
REWORK: ticket <ID> has <N> prior AE attempt(s) that opened a PR - prior work on this ticket may need verification.
  Last attempt: PR #<n> (<date>), risk <class>, <r> Skeptic round(s), QA <status>, <u> unit(s).
Risk floored to Elevated; architect and Skeptic briefed on the prior attempt.
Manual verification of PR #<n> is recommended.
[phase: rework-detected]
```

Fields from the most recent record; null renders `n/a` (QA prefers `skipped:<rationale>`); with more attempts append `(+<N-1> earlier: PR #<a>, #<b>)`. Detail: `content/references/ticket-rework.md`.

### Tracker writeback (W1)

**Gate:** `TRACKER != none`, `[TICKET_ID]` matches the Phase 0 bare-ID regex `^[A-Z][A-Z0-9_]+-\d+$`, and `TICKET_PREFIX` is unset or prefixes it (open-goal synthetic ids never pass). A failed fetch means no In Progress write. Every evaluation emits exactly one soft-fail `tracker_writeback` event:

```bash
# Phase 1 W1: resolve outcome + reason before dispatch.
W1_REASON=""
if [ "$TRACKER" = "none" ]; then
  W1_REASON="tracker_none"
elif ! printf '%s' "${TICKET_ID:-}" | grep -qE '^[A-Z][A-Z0-9_]+-[0-9]+$'; then
  W1_REASON="ticket_id_format"
elif [ -n "${TICKET_PREFIX:-}" ] && ! printf '%s' "${TICKET_ID:-}" | grep -q "^${TICKET_PREFIX}-"; then
  W1_REASON="prefix_mismatch"
elif [ "${W1_FETCH_FAILED:-false}" = "true" ]; then
  W1_REASON="fetch_failed"
fi
```

```bash
export AGENTIC_LOOP_KEY="${LOOP_KEY:-}"
if [ -n "$W1_REASON" ]; then
  ds-emit tracker_writeback - "${TICKET_ID:--}" "{\"site\":\"W1\",\"outcome\":\"skipped\",\"reason\":\"$W1_REASON\",\"target_state\":\"${TRACKER_STATE_IN_PROGRESS:-}\"}" 2>/dev/null || true
fi
```

On `tracker_none` only, print once before any spawn: `NOTE: [phase: tracker-writeback-w1] TRACKER is none for this project - <ID> was not moved to In Progress. Configure a tracker in AGENTS.md to enable ticket-state writeback.` No advisory line fires for the other three reasons.

With `W1_REASON` empty, invoke the Helper with `target_state: $TRACKER_STATE_IN_PROGRESS`, fire-and-forget. Set `W1_DISPATCH_OUTCOME="dispatch_failed"` if the `Agent` call errored before spawning, else `W1_DISPATCH_OUTCOME="dispatched"`, then:

```bash
export AGENTIC_LOOP_KEY="${LOOP_KEY:-}"
if [ -z "$W1_REASON" ]; then
  ds-emit tracker_writeback - "${TICKET_ID:--}" "{\"site\":\"W1\",\"outcome\":\"${W1_DISPATCH_OUTCOME:-dispatch_failed}\",\"reason\":null,\"target_state\":\"${TRACKER_STATE_IN_PROGRESS:-}\"}" 2>/dev/null || true
fi
```

`[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS]`. A ticket abandoned after this stays In Progress (the guard never moves backward).

---

## Phase 2: Read the codebase

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO fetch origin $BASE_BRANCH --quiet
```

Read the files the ticket names, their siblings, `$REPO/AGENTS.md` and touched tracks' `AGENTS.md`, and `MEMORY.md` for decisions (follow the session-start hook's directive, else grep it on demand and Read bounded windows around hits). Enough to plan, no more. Full route, Low or above, unfamiliar area: spawn `investigator` first and pass its brief to the architect.

### Risk classification declaration (unconditional - runs on every ticket)

Classify per `content/sections/04-risk-classification.md`. **Rework floor:** when `IS_REWORK`, the class is at least Elevated, overriding any profile Low override (a floor never lowers). Then declare:

```
RISK_CLASS="<Trivial | Low | Elevated>"     # post-floor
ELEVATED_ROUTE="<full | single-review>"
```

| Route | Spawns | When QA does not run |
|---|---|---|
| Trivial | one worktree `engineer`, lightweight contract; no investigator, architect, planner, Skeptic, QA | `QA_STATUS="skipped:Trivial path"`, set now (Phase 6b never runs) |
| Low, small single-concern override (04 §Profile deltas) | Trivial branches; Phase 6b still runs after the engineer for user-visible UI, the acceptance text as criteria; QA fix passes use the Trivial round-N form | `QA_STATUS="skipped:Low path"` |
| Elevated `single-review` (04 §Elevated routes) | one Elevated-contract `engineer`, no investigator/architect/planner; Phase 2b; one Phase 6 pass keyed BASE`-single`; Phases 7 and 11b; Phase 6b as on Low | `QA_STATUS="skipped:single-review path"` |
| Elevated `full` | Phases 2b-12 below | set at Phase 6b |

All non-QA paths (Trivial, Low, single-review, a set `qa_skip`) write the rationale, not null.

**Escalation (binding).** A Low or single-review brief states its bounds: on a diff that breaks one, or a risk-surface touch the engineer or Skeptic reports, the engineer pushes to `$BRANCH_NAME`, stops and reports. Then set `RISK_CLASS="Elevated"`, `ELEVATED_ROUTE="full"`, clear `QA_STATUS`, delete `.agentic/loop-state-$LOOP_KEY.json` (single-review), and re-enter Phase 3 with that diff as architect input (skipping Phase 0b's snapshot and 2b). The pushed branch is this ticket's own work: the stale-branch preflight's own-work row applies and Phase 5 takes the branch-exists-on-origin form, whose already-checked-out guard covers the Low worktree; never a `-v2` rename or a create from `origin/$BASE_BRANCH`. `SKEPTIC_ROUNDS` counts full-route rounds only.

## Phase 2b: Pre-architect ambiguity scan

Elevated (full or single-review), no `brief_path`, single unit, not an escalation re-entry. Look for vague scope, no done condition, two incompatible readings, or an unstated value the design branches on. Default each from the six sources (`02-delegation.md`), recorded under `Conductor defaults applied:` in the architect brief (single-review: the engineer brief); ask (1-3 questions, one turn) only what only the operator knows, folding answers under `Operator clarifications:`. Exempt from the stop budget.

## Phase 2c: Tracker state discovery (conditional)

`TRACKER != none`, soft-fail. Use `.agentic/tracker-states.json` when under 24h old for the same tracker and workspace; else fetch (`mcp__linear__list_workflow_states`, or Jira transitions on a probe ticket) and write it atomically. For each of the 6 resolved `TRACKER_STATE_*` values with no case-insensitive match warn `WARNING: configured state '<name>' not found in <tracker> workflow. Closest match: '<closest>'. Proceeding with configured name - at write time, the transition is attempted with this exact name first; on failure a live diagnostic names what IS available. It never blocks and never writes to an unconfigured state.` `[phase: tracker-state-discovery | cached=<true|false> | misses=<N>]`

---

## Phase 3: Architecture plan

**Full route only.** Spawn `architect` with the ticket (labeled `[per ticket-body, unverified]`, `delegation-detail.md` §Ticket-Body Content Is a Closed List To Re-Derive), relevant code, conventions and MEMORY.md decisions. Ask for the plan (what, which files, what order), parallel vs sequential units, risks and ambiguities, the adversarial brief type for review, a `qa_criteria` block, and the `docs/overview/vision.md` pillars supporting and cutting against the change.

- **Operator Brief** (`operator_brief_injectionable`): prepend its Problem as `Committed problem statement (from operator Brief - do not redefine):`, Success criteria as `Committed success criteria - your plan MUST demonstrably address every one of these:`, Non-goals as `Out of scope (do not design for these):`, Constraints as `Hard constraints (a design that violates any of these is rejected):`. An uncovered criterion is a Critical plan finding.
- **Prior ticket context** (when `COMMENT_THREAD_SUMMARY` is non-empty): append `## Prior ticket context` with the summary, preceded when `PRIOR_QA_COMMENTS` is non-empty by `PRIOR QA FAILURES DETECTED.` and those comments, asking the plan to address each.
- **Rework** (when `IS_REWORK`, independent of the above): append

```
## PRIOR ATTEMPT(S) OPENED A PR - THIS IS REWORK

AE has already carried this ticket to an opened PR [PRIOR_ATTEMPTS] time(s). The most recent attempt:
- PR: #[pr_number] ([opened_ts]); risk [risk_class]; Skeptic rounds [skeptic_rounds or n/a]; QA [qa_status, skipped:<rationale>, or n/a]; units [unit_count]
[when PRIOR_ATTEMPTS > 1: - Earlier attempts: PR #<a>, #<b>]

Treat the prior attempt as insufficient. Your plan MUST:
1. Identify what it missed, got wrong, or left incomplete. Read its diff and reviews
   (`gh pr view N --json reviews,comments`, `gh api repos/{owner}/{repo}/pulls/N/comments`), plan a
   per-comment sweep (`skeptic-protocol.md` §Round budget item 6), and state your conclusion explicitly.
2. Include at least one `qa_criteria` scenario exercising that regression or gap.
```

**Plan Skeptic (mandatory).** Spawn `skeptic` with the "Document synthesis, architecture, and planning" brief and the `## Global-context inputs` block: field 1 the plan, field 2 the Brief or `n/a - Skeptic-on-plan (Brief authoring gated on this sign-off)`, field 6 `${LOOP_KEY}-plan | ` plus the plan's file paths, field 7 per §4.5. No Phase 3b or 4 before sign-off. Resolve every genuine "Open questions" entry first (`METHODOLOGY.md`); "Deferred defaults" alone does not block.

## Phase 3b: Orchestration plan (conditional)

**Trigger:** the architect found parallel units, or the change spans 3+ directories/modules, or the plan has 3+ units or flags sequencing/agent ambiguity. Read `$REPO_DIR/content/references/orchestration-units.md` §Phase 3b: Orchestration plan (conditional) before any step here; it covers the promotion gate, Brief/Plan authoring and `tasks.jsonl` pending records.

---

## Phase 4: Create the branch

Resolve `BRANCH_NAME` from the AGENTS.md convention (ticket type plus a 4-5 word slug) on every path.

**Stale remote branch preflight** (before passing a branch to any engineer or cutting fan-out sub-branches; with a Brief/Plan, once here before the plan push, not again in Phase 5): `git -C $REPO ls-remote --heads origin "$BRANCH_NAME"`. Empty, or this ticket's own work (a SHA reachable from its resume state, or the branch a Low/single-review engineer pushed before escalating): proceed. A foreign SHA: rename to `-v2` (or `-<7-char HEAD sha>` if taken), re-check, and log `branch_collision: <original> → <renamed> (remote SHA <sha>)` to `resolution_notes`.

**Commit and push the planning artifact** (only when `brief_path` or `plan_path` is set; always set `PLAN_PRESEEDED`):

```bash
ARTIFACT_REL="${plan_path:-$brief_path}"
if git -C "${REPO}" check-ignore -q -- "${ARTIFACT_REL}"; then
  echo "[phase: plan-commit-skipped | docs/planning/ is gitignored in this repo (repo policy: plans stay local) - not committing or pushing.]"
else
  git -C "${REPO}" fetch -q origin
  if git -C "${REPO}" ls-remote --exit-code --heads origin "${BRANCH_NAME}" >/dev/null 2>&1; then
    BASE_REF="origin/${BRANCH_NAME}"; VERB="revise"
  else
    BASE_REF="origin/${BASE_BRANCH}"; VERB="add"
  fi
  TMP_INDEX="$(git -C "${REPO}" rev-parse --absolute-git-dir)/plan-commit-index-$$"
  export GIT_INDEX_FILE="${TMP_INDEX}"
  git -C "${REPO}" read-tree "${BASE_REF}" && git -C "${REPO}" add -- "${ARTIFACT_REL}" && NEW_TREE=$(git -C "${REPO}" write-tree)
  unset GIT_INDEX_FILE; rm -f "${TMP_INDEX}"
  SO_NAME="$(git -C "${REPO}" config user.name)"; SO_EMAIL="$(git -C "${REPO}" config user.email)"
  if [ -n "${NEW_TREE:-}" ] && [ -n "${SO_NAME}" ] && [ -n "${SO_EMAIL}" ]; then
    NEW_COMMIT=$(git -C "${REPO}" commit-tree "${NEW_TREE}" -p "${BASE_REF}" -m "$(printf 'docs(plan): %s %s\n\nSigned-off-by: %s <%s>' "${VERB}" "${ARTIFACT_REL}" "${SO_NAME}" "${SO_EMAIL}")")
    git -C "${REPO}" push origin "${NEW_COMMIT}:refs/heads/${BRANCH_NAME}" || echo "Conductor push rejected (non-fast-forward) - re-run this block once."
  else
    echo "WARNING: plan commit skipped (git add failed or user.name/user.email empty)."
  fi
fi
```

`PLAN_PRESEEDED=true` only when it pushed. Single-engineer and Trivial engineers create their own branch and worktree (Phase 5); fan-out worktrees are conductor-created per `orchestration-units.md`.

---

## Phase 5: Implement

Drive spawns from the planner output when Phase 3b ran (it supersedes the architect's), else the architect plan; single-review: the acceptance text. Phase 5 deliberately has no W1 site. Do not re-add one.

### If work is a single logical unit (or units must be sequential):

One `engineer` per unit, in order, `isolation: "worktree"`, briefed with: the execution contract (`METHODOLOGY.md` §Delegation > Worker preamble), `brief_path`/`plan_path` absolute; the unit's plan; `BRANCH_NAME`; `$REPO`; run `$QUALITY_CMD`; `.agentic/learnings.md` `reviewer-bar` entries verbatim; the Prior ticket context block; on review rework, sweep the diff for each comment's class and list fixed sites beyond those cited.

**Elevated contract fields:**

- `worktree_setup: { branch_name, base_branch, worktree_path, create_commands }`; the return echoes `worktree_path` (Phase 8 needs it). **This bullet is the single canonical definition of `create_commands`** (`worktree-lifecycle.md` §Round-N rework mechanic points here); existence check `git ls-remote --exit-code --heads origin "$BRANCH_NAME"`. **Not on origin** (`PLAN_PRESEEDED == false`): `git -C $REPO worktree add $WORKTREE_PATH -b $BRANCH_NAME origin/$BASE_BRANCH`. **On origin** (`PLAN_PRESEEDED == true`, the re-entry after a Low/single-review escalation, and every round N>=2 fix pass in Phases 6, 6b, 7, 10a): `git -C $REPO fetch origin && git -C $REPO worktree add $WORKTREE_PATH -B $BRANCH_NAME origin/$BRANCH_NAME` (`-B` starts from the origin tip whatever the local ref says; never a bare `worktree add` or a `--track origin/...` positional, exit 129). Apply the already-checked-out guard below first.
- `quality_gates: { command, cwd, must_pass: true }`: the engineer runs `$QUALITY_CMD`; the conductor never re-runs it on this path.
- `git_finalization: { commit_message_template, files_to_stage, push: true }`: `Signed-off-by: $SO_NAME <$SO_EMAIL>` from `git config`, plus `Developer: <handle>` when identity is confirmed (`ds-identity show` has no `provisional:   true`); build with `NL=$'\n'`; empty `user.email` means warn and skip the commit. On a non-fast-forward push the engineer runs once `git -C <worktree> fetch origin $BRANCH_NAME`, `git -C <worktree> rebase origin/$BRANCH_NAME`, `git -C <worktree> push origin HEAD:refs/heads/$BRANCH_NAME`; a conflict aborts the rebase and returns BLOCKED, as does a second rejection.
- `completion_conditions` add "quality_gates.command exits 0", "commit and push completed per git_finalization", "quality_gate_results captured in return"; the return carries `quality_gate_results: { lint, typecheck, test, smoke_test, raw_output }` (`content/agents/engineer.md`).

**Guard (already checked out).** `worktree add` refuses (`already checked out at ...`, or `already used by worktree at ...` on newer git) when another worktree holds the branch. Find it, fetch FIRST, then evaluate fail-closed:

```bash
EXISTING_WT=""
_wt_path=""
while IFS= read -r _wt_line; do
  case "$_wt_line" in
    "worktree "*) _wt_path="${_wt_line#worktree }" ;;
    "branch refs/heads/$BRANCH_NAME") EXISTING_WT="$_wt_path" ;;
  esac
done < <(git -C $REPO worktree list --porcelain)
```

```bash
git -C $EXISTING_WT fetch origin
DIRTY="$(git -C $EXISTING_WT status --porcelain)"
UNPUSHED="$(git -C $EXISTING_WT log origin/$BRANCH_NAME..HEAD --oneline)"
UNPUSHED_RC=$?
```

Empty `EXISTING_WT`: add normally. `UNPUSHED_RC` non-zero: do not reset; follow §Recovery procedure in `worktree-lifecycle.md` and escalate. `DIRTY` non-empty: leave it untouched and escalate. `UNPUSHED` non-empty: push that `HEAD` onto `$BRANCH_NAME` per the Recovery procedure, then escalate. Both empty: `git -C $EXISTING_WT reset --hard origin/$BRANCH_NAME`.

**BLOCKED with an unpushed commit:** never clean that worktree; record `"$REPO_DIR/bin/ds-retire-carrier" --hold --reason "BLOCKED: unpushed commit" --revisit "operator resolves the push rejection" <worktree>`.

**Trivial (and small-change Low) engineer:** lightweight contract (no `worktree_setup`/`quality_gates`/`git_finalization`, no `quality_gate_results`, no brief file), still worktree-isolated; it branches, runs the quality check, commits and pushes. The brief carries the nvm line and `git -C $REPO checkout -b $BRANCH_NAME origin/$BASE_BRANCH`, or on a round-N fix of a branch on origin `git -C $REPO checkout -B $BRANCH_NAME origin/$BRANCH_NAME`. `checkout -B`'s already-checked-out behavior is git-version-dependent: OLDER git (2.39.5) does NOT refuse and drags the other worktree's HEAD, dropping its unpushed commit; NEWER git (2.55.0) now refuses. The guard above is MANDATORY before `checkout -B` under BOTH behaviors. It also says: "Docs currency: follow this repo's own doc-sync rule (its AGENTS.md/CONTRIBUTING.md) and, in the same commit, update any doc your diff makes stale."

**Task state (multi-unit, `.agentic/tasks.jsonl`).** Before each spawn apply the task-state fold (`content/references/task-state-file.md`); every `depends_on` must fold to `done`. Then append a `pending` -> `in_progress` transition; this append is the ownership claim. It carries `assigned_agent`, `worktree_path`, `branch_name`, `author_model` (the engineer's model id, or `null`), and `ticket_id`. On return append an output-only entry (`worker_summary`, `commit_sha`, `files_modified`, `quality_gate_passed`) with no `status` field: under the task-state fold a status field would be a fresh claim. After the Skeptic/QA loop append the terminal status with `loop_state`, `outputs.skeptic_status` and `outputs.skeptic_findings_count`.

### If parallel independent units were identified:

One planner unit falls through to the path above. **Mandatory:** Read `$REPO_DIR/content/references/orchestration-units.md` §If parallel independent units were identified: before any step here; it defines the worktrees, claims (appends under the task-state fold), merge, `SKEPTIC_STRATEGY` and `$INTEGRATION_WORKTREE`.

---

## Phase 6: Skeptic review

**Fan-out guard:** with `SKEPTIC_STRATEGY: integration` the Phase 5 integration Skeptic is this gate; with `per-unit` or `multi-dimensional` Phase 6 still reviews the combined diff (`git -C $INTEGRATION_WORKTREE diff origin/$BASE_BRANCH..HEAD`).

**W2** (first Skeptic spawn only): Helper with `target_state: $TRACKER_STATE_IN_REVIEW`. `[phase: tracker-writeback | site: W2 | target: $TRACKER_STATE_IN_REVIEW | iter: 1]`

**Skeptic brief:** the architect's adversarial brief type (single-review: §8 General code review, flag risk surfaces); the diff `git -C $REPO diff origin/$BASE_BRANCH..HEAD`; the ticket as success criteria and its QA section as acceptance tests; when `IS_REWORK`, the Phase 3 rework block verbatim plus `Verify that the failure mode which brought this ticket back is actually addressed. Read the prior PR's diff. Withholding sign-off because the new diff does not demonstrably close the prior gap is a correct outcome.`; and the `## Global-context inputs` block: field 1 `$ARCHITECT_PLAN_PATH` (or an `n/a - <reason>`), field 2 `$BRIEF_PATH` or `n/a - single Elevated unit (no Brief required by the promotion gate)`, field 3 the unit's `qa_criteria` verbatim, field 4 the per-consumer impact table or `n/a - non-shared-utility surface (importer count below 5 threshold)`, field 5 related files (single-review: changed files) plus the `.agentic/learnings.md` path when it holds `reviewer-bar` entries and base-branch refs when behavior changes, field 6 `$UNIT_KEY | ` plus the diff, field 7 per §4.5 (single-review: acceptance text).

**Seed `findings_log`** with one `H<n>` entry (`severity: Major`, `status: open`) per human CHANGES_REQUESTED comment the rework addresses, and from the open PR's automated-reviewer threads (`skeptic-protocol.md` §Automated-reviewer threads).

**Tier:** role default. With `PRIOR_ATTEMPTS >= 2`, declare `Tier: 3` and pass `model: fable` when `availableModels` is absent or lists it, else `model: opus`.

**Loop init:** write `.agentic/loop-state-$LOOP_KEY.json` atomically (via `.agentic/loop-state-$LOOP_KEY.json.tmp`) with `last_phase=skeptic`, `last_phase_action=spawned`, `loop_state.tier`, `max_iterations` 3 (single-review 2). `[loop: skeptic | iteration 1/3 | open findings: -]`. Overwrite `.agentic/loop-state-$LOOP_KEY.json` at every transition: `skeptic|returned`, `engineer|spawned`, `engineer|returned`, each `findings_log` update, `status=complete` on clean exit, `status=stalled` on cap/convergence/blocked.

**Step 1.** Spawn the Skeptic; for a UI-visible diff that Phase 6b would QA, spawn `qa-engineer` in the same message (both background; `qa-gate.md` §"QA gate flow (UI-visible - concurrent)"), and a concurrent PASS satisfies Phase 6b. When `findings_log` has open or addressed entries, put this before the brief:

```
## Prior iteration findings

The following findings were raised earlier or by a human review. For each:
- If the current diff shows the finding was addressed: mark it CLOSED with a one-line confirmation.
- If the current diff does NOT show the finding was addressed: re-raise it using [PREV: <id>] prefix in the finding title.
- Do not invent new instances of a closed finding without new evidence.

[paste the id and description of each open or addressed entry]
```

Add the engineer's `fix_pass` (the Skeptic re-runs each `check:` before closing). Format re-invocations (up to 3, `skeptic-protocol.md` Section 11) are not iterations. Add the draft PR body free text (Summary, North Star, Test plan) to the Worker output on iteration 1, updated when a round changes what it describes; apply `Comment discipline:` findings on that draft yourself.

**Step 2.** Update `findings_log` (durable record - log every finding, every severity, including all-Minor/sign-off rounds): slug `id`, `description` (verbatim, `check:` included), `severity`, `first_raised`, `status: open`; `[PREV: <id>]` sets `re_raised: true`; a CLOSED entry becomes `closed`. Mark every `Beyond AC:` Minor `deferred`; other out-of-scope Minors may be deferred (never `Scope drift:`); deferred Minors are documented in the PR description. A Major is deferred only on operator approval or the cap ship decision. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. After each Worker return, surface unrecorded Critical/Major `meta_review_complete` misses from `.agentic/events.jsonl` as `META-DIVERGENCE: ...` lines and record their ids in `.agentic/.meta-divergence-surfaced` (`skeptic-protocol.md` Section 14).

**Step 3. Termination check:**
- **Single-review:** no open Critical: one Steps 4-5 pass on all open findings but deferred Minors, then the clean exit (no re-review); fixed Majors stay `addressed` and `SKEPTIC_ROUNDS` is the rounds run. A round-1 Critical: Steps 4-5, round 2, then Escalate if still open.
- **No Critical or Major:** fix open `Scope drift:` Minors and code-span `Comment discipline:` Minors in one Steps 4-5 pass (no re-review); close every open/addressed entry (never exit clean with an empty `findings_log` when this loop had findings); set `termination_reason: clean`; overwrite `.agentic/loop-state-$LOOP_KEY.json`; Set `SKEPTIC_ROUNDS` to this loop's final `loop_state.iteration` now (Phase 6b overwrites the file); run the clean-exit steps; go to Phase 6b.
- **Cap** (`iteration == max_iterations`, Critical or Major open): per `content/sections/05-qa-gate.md` §Re-route limits; an open Critical forces Escalate. **Ship:** mark the rest `deferred` (this ship decision at cap is the explicit approval Step 2 requires), set `termination_reason: clean`, and take the clean-exit branch above. **Escalate:** `termination_reason: cap_reached`, overwrite, batch routing, escalation format; no Phase 6b.
- **A Critical with `re_raised: true`:** `termination_reason: convergence_failure`, overwrite, batch routing, escalate (one re-raise suffices).

**Clean-exit steps.** (1) Spawn `learning-extractor` (Tier 1, background) with `ticket_id`, the resolved `findings_log` and the full diff; keep its `learning_ids[]` for Phase 11b; its failure never blocks. (2) Capture sweep: declare `Capture: MUST/SKIP` for each unevaluated mandatory trigger (`conductor-operating-rules.md` §learnings-agent), guardrail-first (`capture-classification.md`). (3) Emit `spawn_complete skeptic <task_id>` with the usage fields merged with `findings_count`, `diff_lines`, `signed_off:true`, `iteration`, `meta_review:null`. (4) Bucket `python3 -c 'import hashlib,sys; print(int(hashlib.sha256(sys.argv[1].encode()).hexdigest(),16) % 100)' "<task_id><iteration>"`; under 5, spawn a background meta-Skeptic with the original diff, findings, sign-off, brief and `## Global-context inputs` block (field 7 included, `-meta` on field 6) asking for a text divergence report; on return emit `ds-emit meta_review_complete skeptic-meta <original_task_id> "$META_DATA"` (`skeptic-protocol.md` Section 14).

**Step 4. Engineer fix pass** (round N>=2; "on origin" `create_commands`). Fresh `engineer` with: the open Critical and Major findings verbatim, never a prescribed design; each finding's class with every instance in scope and fixed sites beyond those cited listed (`skeptic-protocol.md` §Round budget item 6; from round 3, item 7); branch, repo and pushed head SHA; `$QUALITY_CMD`; from iteration 2 the prior engineer output verbatim plus *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a Skeptic finding listed below. Each edit you make must trace to a specific finding id."*; and "Address only the findings listed below. Do not expand scope. Do not refactor, rename, or clean up code outside the finding scope. For each finding, confirm in your summary what you changed and why it addresses the finding."

**Step 5.** `last_engineer_summary` (verbatim, 2000 chars) starts with its `fix_pass`. `BLOCKED`: `termination_reason: blocked`, overwrite, batch routing, **W4** (Helper, `target_state: $TRACKER_STATE_BLOCKED`; `[phase: tracker-writeback | site: W4 | target: $TRACKER_STATE_BLOCKED]`), escalate, stop. `NEEDS_CONTEXT`: supply it and re-spawn (no increment), or escalate the gap. `DONE`/`DONE_WITH_CONCERNS`: claimed fixes become `addressed`, concerns go to the next Skeptic, increment `iteration`, overwrite, update the breadcrumb, Step 1.

**Escalation format:**

```
LOOP STALLED - [reason: cap_reached | convergence_failure | blocked]
Iteration: [N] of [cap]
Open findings that could not be resolved:
[findings_log entries with status=open]
[convergence_failure: finding id, original raise, claimed fix, re-raise note]
[blocked: the engineer's blocker verbatim]
Recommended action: (a) direct the engineer on [finding id], (b) accept it as a known limitation, or (c) scope a follow-on ticket.
```

### Batch-mode escalation routing (mark-blocked-and-continue)

**Trigger:** `.agentic/batch-state.json` is `active`. Read `$REPO_DIR/content/references/batch-mode.md` §Batch-mode escalation routing (mark-blocked-and-continue) before any step here; without an active batch: surface and wait for the operator.

### Findings curator (loop exit)

On every Phase 6 exit spawn `general-purpose` (Tier 1, background) with the final Skeptic output verbatim, `ticket_id` and `.agentic/findings.md`: `pattern_hash` = first 16 hex of SHA-256 over the lowercased, whitespace-collapsed, fence-stripped, trimmed finding text; skip existing `(pattern_hash, ticket_id)`; the curator is the file's sole writer. Once per ticket. After round 2, check the Section 13 limits and compress the exchange log (`skeptic-protocol.md` Section 3).

### Open-goal condition check (clean exit only, `goal_mode=open_goal` invocations only)

Skip unless `batch-state.json.open_goal.active` is `true`. Read `$REPO_DIR/content/references/open-goal-loop.md` §Open-goal condition check (clean exit only, `goal_mode=open_goal` invocations only) before any step here; follow it.

---

## Phase 6b: QA Gate (conditional)

Skipped when open-goal `dry_run` is true (go to Phase 12). **Full route:** fires when Phase 6 exited clean, `qa_criteria` exists, `qa_skip == null` and `scenarios[]` is non-empty. **Low and single-review routes:** fires after the engineer (single-review: after Phase 6) whenever the change has user-visible UI behavior, with the ticket's acceptance text or the operator's request as the criteria; the Elevated, `qa_criteria` and Phase 6 triggers are waived. A `qa_skip` outside `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only` becomes null with `WARNING: qa_skip value '<X>' is not a valid enum. Treating as null; QA will fire.` qa.md supplements, never gates. QA cap 3, separate from the Skeptic cap.

**Skipped:** record the rationale in the status update and set `QA_STATUS="skipped:<rationale>"`.

**Per-ticket, in-flow** (`qa-gate.md`): never defer QA to a batch-end sweep. A missing dev-server env file: print the §"Conductor preflight before any qa-engineer spawn" message and wait. QA that cannot run is `qa_blocked`: provide the input, accept INCONCLUSIVE (`qa_unverified=true`), or abandon. A UI-visible diff's QA already started with the Skeptic (Phase 6 Step 1): its PASS skips to Phase 7, else this loop continues. Parallel PRs get one per worktree on `PORT=$((3000 + N))`.

**Loop:** write `.agentic/loop-state-$LOOP_KEY.json`, overwriting the Phase 6 state (`last_phase=qa|spawned`, `loop_state.phase: qa`, `iteration: 1`, `max_iterations: 3`, `qa_failures_log: []`), and at each transition; `[loop: qa | iteration 1/3 | open failures: -]`. **W3** (first QA spawn): Helper with `target_state: $TRACKER_STATE_QA`, `[phase: tracker-writeback | site: W3 | target: $TRACKER_STATE_QA | iter: 1]`.

1. Spawn `qa-engineer` (`isolation: "worktree"`) with the ticket, the diff, the `qa_criteria` block (the test plan), `ticket_id` and the qa.md config; from iteration 2 prepend `## Prior QA failures` (mark fixed criteria CLOSED, re-raise with `[PREV: <id>]`) listing the open/addressed `qa_failures_log` entries.
2. Log each failure (`id`, `description`, `first_raised`, `status: open`, `re_raised`), overwrite `.agentic/loop-state-$LOOP_KEY.json`, and run the QA knowledge capture (`qa-gate.md` §"QA knowledge capture (canonical procedure)").
3. **PASS:** close all, `termination_reason: clean`, `QA_RAN_AND_PASSED="true"`, `QA_STATUS="PASS"`. Assign `SCREENSHOT_JSON_PATH` from the pointer's `screenshot_evidence_json_path` (never inline it) and load `QA_SCREENSHOT_PATHS` from that file, keeping `result == "PASS"` entries (missing or malformed: empty), in-context only. Any other terminal verdict sets `QA_STATUS` to it (`FAIL`/`PARTIAL`/`BLOCKED`/`INCONCLUSIVE`); an accepted INCONCLUSIVE sets `QA_STATUS="INCONCLUSIVE"`, never null. **Cap:** `cap_reached`, batch routing, escalate with the log; no Phase 7. **Re-raised failure:** `convergence_failure`, batch routing, escalate.
4. **Fix pass** ("on origin" form; Low route: the Trivial round-N form): the failures, the prior summary, fix only the failing criteria, cite `content/references/qa-regression-obligation.md` (a regression test, or a `.agentic/qa-regressions.md` exception), and from iteration 2 the surgical-edit directive (tied to a QA failure id). `BLOCKED`: `blocked`, batch routing, **W5** (`target_state: $TRACKER_STATE_BLOCKED`; `[phase: tracker-writeback | site: W5 | target: $TRACKER_STATE_BLOCKED]`), escalate. `NEEDS_CONTEXT` as Phase 6.
5. Claimed fixes `addressed`, increment, overwrite, back to 1.

After each terminal outcome, once the curator below has read the report: `rm -f "${SCREENSHOT_JSON_PATH:-}" "${QA_REPORT_PATH:-}" 2>/dev/null || true`.

### QA regressions curator (Phase 6b clean exit)

When any iteration recorded a FAIL: Read `$REPO_DIR/content/references/qa-evidence-publish.md` §QA regressions curator (Phase 6b clean exit) before any step here; once per ticket.

---

## Phase 7: Quality gate

Runs after 6/6b exit clean; never re-enters the Phase 6 counter. Every write below goes to `.agentic/loop-state-$LOOP_KEY.json` with `last_phase=quality_gate`.

- **Elevated:** verify the return; never run `$QUALITY_CMD` yourself. lint, typecheck and test all `pass`: Phase 8. Any `fail` or `vacuous`, or no block (a Major): fix pass with `raw_output`.
- **Trivial:** run `cd $REPO && $QUALITY_CMD` after the nvm line. Zero or ignored inputs is a failure; never suppress a check.

**On failure, `DEBUGGER_ON_FAILURE` false or Trivial:** write `last_phase_action=engineer_spawned`; spawn one fix engineer (Elevated: worktree, "on origin" form; Trivial: its own round-N form); write `engineer_returned`, then `rerun_pending`; verify again. Pass: `status=complete`, Phase 8. Fail: `status=stalled`, batch routing, escalate with both outputs. One pass only.

**`DEBUGGER_ON_FAILURE` true and Elevated** (Trivial never uses the Debugger): up to 3 cycles of `debugger_spawned`, `debugger` (read-only, with `raw_output`, diff, prior cycles), `debugger_returned`, `engineer_spawned`, fix engineer with the Fix brief, `engineer_returned`, `rerun_pending`, verify. An identical failing test-ID set in two cycles (test runners only) escalates at once. After cycle 3: `status=stalled`, batch routing, **W6a** (`target_state: $TRACKER_STATE_BLOCKED`; `[phase: tracker-writeback | site: W6a | target: $TRACKER_STATE_BLOCKED | escalation: quality-gate-cap]`), escalate with every cycle's output.

---

## Phase 8: Commit and push

Open-goal `dry_run`: skip Phases 8-11b (commits stay local), go to Phase 12.

Pass `-- [specific files]` and `--message` only when the conductor commits: the sequential path in `$REPO`, or fan-out fixups shown by `git -C "$INTEGRATION_WORKTREE" status --short`. When the engineer already committed, omit both. Never `git add -A`. Subject at most 50 chars, imperative; no AI-attribution trailer.

```bash
"$REPO_DIR/bin/ds-ticket-commit" --repo "$REPO" --branch "$BRANCH_NAME" \
  --worktree-path "$WORKTREE_PATH" --integration-worktree "$INTEGRATION_WORKTREE" \
  --message "type(scope): short imperative description

Closes [TICKET_PREFIX]-NNN" \
  -- [specific files]
```

Exit **0** pushed and the worktree retired (a `HELD` line means the checkout was kept); **1** push failed or unverified (a carrier gets a `BLOCKED: unpushed commit` hold; `ERROR: BLOCKED hold NOT recorded` means record it by hand); **2** usage error; **3** feature commit failed (files passed on the wrong checkout branch, a bad pathspec, or a rejecting hook); **127** script missing. Every non-zero exit stops Phase 8: report BLOCKED with the output.

**Telemetry commit:** the script adds the `Developer:` and `Signed-off-by:` trailers and, when `commit_telemetry` is on and identity is confirmed, a `chore(telemetry):` commit of `.agentic/session-log/<developer_id>.jsonl` on the PR branch.

## Phase 8.5: QA evidence (conditional)

Skip when QA was skipped or Trivial, `QA_SCREENSHOT_PATHS` is empty, or `gh`/`jq` is missing (`QA_EVIDENCE_URLS=()`). Otherwise Read `$REPO_DIR/content/references/qa-evidence-publish.md` §Phase 8.5: QA evidence (conditional) before any step here; follow it.

---

## Phase 9: Open the PR

**UNIT_IS_BEHAVIOR_VISIBLE** is `true` only when `QA_RAN_AND_PASSED == "true"`, `QA_EVIDENCE_URLS` is non-empty, and the class is not security, auth, crypto, payments or Elevated-correctness; default `false`. It puts QA evidence first; otherwise it follows the Test plan.

**Tracker reference block:** Linear `## Linear` / `Closes [[TICKET_PREFIX]-NNN](https://linear.app/[LINEAR_WORKSPACE]/issue/[TICKET_PREFIX]-NNN)`; Jira `## Jira` / `Closes [[TICKET_PREFIX]-NNN]([JIRA_BASE_URL]/browse/[TICKET_PREFIX]-NNN)`; `none`: omit it and drop the `[TICKET_PREFIX]-NNN:` title prefix.

**Free text (binding):** start from the Phase 6-reviewed draft. Summary at most 5 single-line bullets, result first, no review-round narration (`conventions.md` §Writing Style, `conventions-detail.md` §Assembled PR bodies). **`## North Star alignment`**: never leave `[pillar]` literal; with no `docs/overview/vision.md` write `N/A - no docs/overview/vision.md in this repository`, else the plan's pillars, those cutting against the change included. It must be in the body at create time (`--body-file` bypasses the PR template). The `Model:` line reads `author_model` from this ticket's engineer claims. Set `DELIVERY_RECORD_OWNER` to the PR owner. Open as draft; reviewers come at Phase 10b.

```bash
DEVELOPER=${DEVELOPER:-$(ds-identity show 2>/dev/null | awk '/^developer_id:/{print $NF}')}
if ds-identity show 2>/dev/null | grep -qE '^provisional:[[:space:]]+true'; then DEVELOPER=""; fi
ENGINEER_MODEL=$(jq -sr --arg t "$TICKET_ID" '
  [.[] | select(.ticket_id == $t and .assigned_agent == "engineer"
    and .author_model != null and (.status == "in_progress" or .status == "done"))
    | .author_model]
  | unique | join(", ")' .agentic/tasks.jsonl 2>/dev/null || true)
EVIDENCE_FILE="/tmp/pr-evidence-$$"
if [ "${#QA_EVIDENCE_URLS[@]}" -gt 0 ]; then
  printf "## QA Evidence\n\n" > "$EVIDENCE_FILE"
  for entry in "${QA_EVIDENCE_URLS[@]}"; do
    printf -- "- **%s** %s - [screenshot](%s)\n" "$(echo "$entry" | jq -r '.criterion_id')" "$(echo "$entry" | jq -r '.result')" "$(echo "$entry" | jq -r '.url')" >> "$EVIDENCE_FILE"
  done
elif [ "${QA_RAN_AND_PASSED:-}" = "true" ]; then
  printf "> QA ran (PASS) but no screenshot evidence is available (push failed or no screenshots were captured).\n" > "$EVIDENCE_FILE"
else
  printf "> QA skipped or not configured for this ticket (see qa_criteria in architect plan).\n" > "$EVIDENCE_FILE"
fi
PR_BODY_FILE="/tmp/pr-body-$$"
: > "$PR_BODY_FILE"
[ "$UNIT_IS_BEHAVIOR_VISIBLE" = "true" ] && { cat "$EVIDENCE_FILE"; echo; } >> "$PR_BODY_FILE"
cat >> "$PR_BODY_FILE" <<PRBODY
## Summary
- [bullet 1]
- [bullet 2]

[TRACKER_REFERENCE_BLOCK]

## North Star alignment

- Pillar(s) advanced (see docs/overview/vision.md): [pillar]
- Trade-off or pillar this could regress, if any: [trade-off, or "none identified"]

<!-- ds-delivery-record:v1:start -->
## Delivery record (provisional)

Owner: $DELIVERY_RECORD_OWNER. Remote SHA binding follows PR creation.
- Human approval: PENDING - owner must establish actual approval policy/evidence.
- Protocol review: PENDING - owner must collect applicable review evidence/exemptions.
- CI: PENDING - owner/platform must observe current checks.
- QA: PENDING - owner must collect scoped QA evidence/exemptions.
- Human UAT: PENDING - owner must establish request/policy; N/A if neither requires it.

Procedure: content/references/delivery-record.md
<!-- ds-delivery-record:v1:end -->

## Test plan
- [ ] [step 1]
- [ ] [step 2]
PRBODY
[ "$UNIT_IS_BEHAVIOR_VISIBLE" = "true" ] || { echo; cat "$EVIDENCE_FILE"; } >> "$PR_BODY_FILE"
[ -n "$DEVELOPER" ] && printf "\nDeveloper: %s\n" "$DEVELOPER" >> "$PR_BODY_FILE"
[ -n "$ENGINEER_MODEL" ] && printf "\nModel: %s\n" "$ENGINEER_MODEL" >> "$PR_BODY_FILE"
gh pr create \
  --repo [GH_REPO] \
  --base [BASE_BRANCH] \
  --head [BRANCH_NAME] \
  --draft \
  --title "[TICKET_PREFIX]-NNN: [ticket title]" \
  --body-file "$PR_BODY_FILE"
rm -f "$PR_BODY_FILE" "$EVIDENCE_FILE"
```

Capture `PR_NUMBER` from the printed URL, then collect and publish the provisional remote-SHA record per `content/references/delivery-record.md`; keep pending checks owned.

### Ticket-rework ledger write

Runs after the PR opens on every path, Trivial included. The script skips it when `REWORK_DETECTION` is false or `TICKET_ID` is empty, derives `pr_number` live from the branch, and appends one line; `unit_count` is the count of distinct `task_id`s for this ticket in `.agentic/tasks.jsonl` under the task-state fold (1 without the file). Soft-fail.

```bash
# Phase 9: ticket-rework ledger write (soft-fail; every path, Trivial included)
"$REPO_DIR/bin/ds-ticket-finish" ledger --repo "$REPO" --ticket "$TICKET_ID" --branch "$BRANCH_NAME" \
  --gh-repo "$GH_REPO" --loop-key "$LOOP_KEY" --rework-detection "$REWORK_DETECTION" \
  --risk-class "$RISK_CLASS" --skeptic-rounds "$SKEPTIC_ROUNDS" --qa-status "$QA_STATUS"
```

Exit 2 or 127 means it did not run: stop and report. The ledger is append-only.

---

## Phase 10: Wait for CI checks

Run in the background (default budget 30 minutes) and read its output on exit. It passes only when every required check of the base branch is registered and green and the count holds across two polls; it never merges or marks ready. `preview_blocked: true` in qa.md suppresses preview-URL polling only (Phase 11 Test URL: "Preview deploy blocked - verify with local QA.").

```bash
TIMEOUT_POLLS=60
"$REPO_DIR/bin/ds-ticket-ci" --pr "$PR_NUMBER" --gh-repo "$GH_REPO" --polls "$TIMEOUT_POLLS"
```

**Outcome routing (exit code):**
- **0** passed: (or `passed-by-default | no-checks`) proceed to Phase 10b.
- **1** failed: `failing-checks: <names>`. Enter Phase 10a.
- **2** timeout: write `last_phase: ci_wait, last_phase_action: timeout, auto_merge_queued: <bool>` to `.agentic/loop-state-$LOOP_KEY.json` and STOP. With `auto_merge_on_ci_green` true, follow `conventions-detail.md` §Auto-merge follow-through -> "Phase 10 timeout call site (full procedure)" (`gh pr merge --auto` exit 0 sets `auto_merge_queued: true`).
- **3** usage or **4** unreadable checks (for the latter re-run with `--required NAME` per required check): BLOCKED with the output. **127**: script missing. No `[phase: ci-wait | result: ...]` line: run it again.

## Phase 10a: CI fix loop (conditional on Phase 10 result: failed)

Up to 3 cycles. Each: `RUN_ID=$(gh run list --pr "$PR_NUMBER" --repo "$GH_REPO" --status failure --limit 1 --json databaseId 2>/dev/null | jq -r '.[0].databaseId')` and `FAILURE_LOG=$(gh run view "$RUN_ID" --repo "$GH_REPO" --log-failed 2>/dev/null | tail -300)`; write `last_phase: ci_loop, last_phase_action: fix_engineer_spawned, last_phase_iteration: N` to `.agentic/loop-state-$LOOP_KEY.json`; spawn a worktree fix engineer ("on origin" form) with the log, prior cycles (surgical-edit directive from cycle 2) and "commit and push to the same branch"; write `fix_engineer_returned`, then `ci_poll_pending`, and re-run the Phase 10 call. The same failing check names in two cycles escalate at once. After 3: write `cap_exceeded`, print each cycle's outcome, **W6b** (`target_state: $TRACKER_STATE_BLOCKED`; `[phase: tracker-writeback | site: W6b | target: $TRACKER_STATE_BLOCKED | escalation: ci-fix-loop-cap]`), STOP. `[phase: ci-fix-loop | iteration N/3 | failing: <check-names>]`

## Phase 10b: Mark ready + assign reviewers (conditional on Phase 10 result: passed)

**Thread rule:** first apply `content/references/conventions-detail.md` §Unanswered review threads before re-request (a no-op with no review threads).

**Mark ready-for-review:**

```bash
gh pr ready "$PR_NUMBER" --repo "$GH_REPO" 2>/dev/null
```

Soft-fail. **Reviewers:** a CODEOWNERS file (`.github/`, `docs/` or root) routes them; else `gh pr edit "$PR_NUMBER" --repo "$GH_REPO" --add-reviewer "$PR_WORKFLOW_REVIEWERS"` when set; else print `No reviewers assigned: no CODEOWNERS file found and no Reviewers: in AGENTS.md ## PR Workflow.` `[phase: pr-ready | reviewers: auto|assigned|none]`

---

## Phase 11: Post to tracker

#### If TRACKER is `linear` or `jira`

Spawn a Tier 1 `general-purpose` writeback subagent; the conductor makes no tracker MCP calls here. Brief:

> Post a tracker comment with the PR and Test URLs and, where configured, transition the ticket and set the assignee.
>
> **Inputs (resolved by conductor and passed in):**
> - `TRACKER`, `TICKET_ID`, `PR_URL` (`https://github.com/[GH_REPO]/pull/[PR_NUMBER]`), `TEST_URL` (from CI, or `pending - see PR` after a timeout)
> - `qa_summary`: status and PR link first, then only what the PR does not show (QA caveats, limits, what to test); about 1500 chars, for a phone
> - `target_state`: `$TRACKER_STATE_QA`
> - `forward_only_guard`: `true`
> - `tracker_state_values`: `{ "IN_PROGRESS": "$TRACKER_STATE_IN_PROGRESS", "IN_REVIEW": "$TRACKER_STATE_IN_REVIEW", "QA": "$TRACKER_STATE_QA", "DEV_COMPLETE": "$TRACKER_STATE_DEV_COMPLETE", "BLOCKED": "$TRACKER_STATE_BLOCKED", "DONE": "$TRACKER_STATE_DONE" }`
> - `pipeline_order`: the ordered list of pipeline tokens resolved once in Setup (`TRACKER_PIPELINE_ORDER`), always 4 tokens (`DEV_COMPLETE` appended when undeclared)
> - `dev_complete_declared`: `TRACKER_DEV_COMPLETE_DECLARED` (absent counts as `false`)
> - `transitions_mode`: `$TRACKER_TRANSITIONS_MODE` from Setup - kill switch; `manual` yields `skipped_transitions_manual`
> - optional: Linear `LINEAR_QA_ASSIGNEE_ID`; Jira `JIRA_QA_TRANSITION`, `JIRA_QA_ASSIGNEE_ACCOUNT_ID`
>
> For the full brief shape governing this subagent, see `content/references/tracker-writeback.md` `## Tracker Writeback Helper`.
>
> **Behavior:**
> - **Kill switch first:** `manual` suppresses the STATE TRANSITION only (no pre-read, no transition); the comment and the assignee update still fire.
> - **Linear:** forward-only guard, then `mcp__linear__save_issue` with `state` (and `assigneeId` when configured), then `mcp__linear__save_comment`. Under `manual`: one assignee-only `save_issue` (no `state`) when an assignee is configured, else none.
> - **Jira:** forward-only guard, `jira_get_transitions`, `jira_transition_issue` (only with `JIRA_QA_TRANSITION` matching), `jira_update_issue` for the assignee, `jira_add_comment`; transition or assignee failures are logged and the comment still posts. Under `manual`: skip the guard and transition calls; assignee and comment fire as under `auto`.
>
> Comment: `Implementation complete. Ready for QA.` / `Test URL: [TEST_URL]` / `PR: [PR_URL]` / `[qa_summary]` (Jira links as `link` marks; a pending `TEST_URL` unlinked).
>
> **Returns:** `{ transitioned, assigned, comment_posted, status: "ok" | "partial" | "failed" | "skipped_unconfigured_state" | "skipped_transitions_manual", diagnostic: <string|null>, errors: [<string>] }`. `status: "skipped_transitions_manual"` means only the transition was suppressed; `transitioned` is `false` but `comment_posted`/`assigned` still reflect reality.

With `screenshot_upload: true` in `.agentic/qa.md` and screenshots present: Read `$REPO_DIR/content/references/qa-evidence-publish.md` §If TRACKER is `linear` or `jira` before any step here; follow it.

#### If TRACKER is `none`

Print `No tracker configured - skipping ticket update. PR is open at: https://github.com/[GH_REPO]/pull/[PR_NUMBER]`.

## Phase 11b: Wrap learnings (per-ticket capture)

**Skip** when no PR was opened, or the ticket was Trivial or small-change Low (`skipped_reason: "trivial-no-brief"`); neither path attempts the lock. **Spawn:** `wrap-ticket` (Tier 1, foreground, blocking, 60-second timeout). `.agentic/wrap/lock` is shared with `/ds-wrap`; take it only through `ds-wrap-acquire-lock`, never a manual `mkdir`.

1. `ds-wrap-acquire-lock "$REPO" --role=agent --no-wait --session-id="$CLAUDE_CODE_SESSION_ID"`:
   - **0** - acquired.
   - **5** - busy: step 2.
   - **1** - fatal: print the WARNING and skip with `skipped_reason: "wrap-lock-contention"`. Do NOT release the lock (this session never acquired it).
   - **any other exit code**, including not found on PATH (never a `mkdir` fallback): skip the same way; when missing, note `Phase 11b skipped: ds-wrap-acquire-lock not found on PATH - re-run your harness's DinoStack install script to wire bin/ onto PATH.`
2. `ds-wrap-acquire-lock "$REPO" --role=agent --timeout-ms=45000 --session-id="$CLAUDE_CODE_SESSION_ID"` with `run_in_background: true`. The conductor holds at this step: it MUST NOT advance to Phase 11d or Phase 12 while this attempt is outstanding, so a pending `wrap-ticket` never races their reads of `.agentic/loop-state-$LOOP_KEY.json`. **0** acquired; **2** - timeout: skip with `Phase 11b skipped: wrap-lock-contention (lock still held after 45s bounded wait).`; **1** or any other: print it and skip. None of these releases.
- **If the lock is acquired:** spawn `wrap-ticket` with the inputs below. The conductor releases the lock on every exit path (success, timeout, soft-fail) before proceeding to Phase 12.

Inputs: `ticket_id`, `ticket_title`, `ticket_description`, `architect_plan_path` (single-review: `n/a`), `brief_path` (or `n/a`), `findings_log` from `.agentic/loop-state-$LOOP_KEY.json`, `qa_md_diff` (snapshot vs `.agentic/qa.md`; empty without a snapshot), `merged_diff`, `pr_url`, `conversation_summary`, `learnings_extracted` (`learning_ids[]` or `[]`), and:
- `memory_mode`: `compiled` in compiled mode (memory-shard-convention.md: `detect`, else the `^index:` grep); else omit.

A valid JSON return prints `operator_summary`; non-JSON, a timeout or a failure warns and proceeds; nothing here blocks Phase 12. Compiled mode: before release run `ds-memory-capture flush --dir "$REPO"` (soft-fail) and print its `captured:`/`flush:` lines with `operator_summary`.

Lock release: this applies ONLY within the "If the lock is acquired" branch above - the conductor runs `ds-wrap-release-lock "$REPO"` (PATH-wired helper) unconditionally on every `wrap-ticket` outcome in that branch (success, non-JSON return, timeout, soft-fail) before advancing to Phase 12. The release root MUST match the root passed to the acquire calls in step 1 and step 2 above - a bare `ds-wrap-release-lock` resolves against the conductor's cwd instead, and if cwd differs from `$REPO` the release is a silent no-op that leaks the lock for the rest of the session. The two skip-conditions paths and every lock-acquisition-failed path (the first attempt's non-0/non-5 exit code, and the bounded-wait attempt's 45s timeout or non-0/non-2 exit code) never acquired the lock in this session and must NOT call the release helper.

**After release (soft-fail, silent).** With a non-empty `cluster_results`, `skill_candidate_detection` not false and `$CLAUDE_CODE_SESSION_ID` set, write it to a temp file and run `node hooks/lib/skill-candidate-deep-cluster.js "$REPO_CWD" "$CLAUDE_CODE_SESSION_ID" "$CLUSTER_TMP" 2>/dev/null || true`. Then the Part E gate: **Skip entirely** in compiled mode, on `wrap-lock-contention`, or when `.agentic/wrap/lock` exists; else apply `/ds-wrap` Part E's gate to `MEMORY.md` and `.agentic/compression-state.json`, and on trip spawn the Part E curation Worker in the background and run its chain per Part E's "Async-path amendment", swallowing every failure. `[phase: wrap-ticket | ticket=<ticket_id> | status=<ok|skipped|failed>]`

## Phase 11d: Delivery record and Review rigor

Whenever a PR exists: collect this ticket's review/findings, QA, CI, approval policy and UAT evidence per `content/references/delivery-record.md`; fill the three Review rigor labels (Brief / Plan path, Skeptic rounds (tier), Findings summary) from the keyed loop state (missing findings stay unknown, never "No findings"); keep exemptions with reasons; publish the SHA-bound record from `DELIVERY_RECORD_INPUT`. Repeat after Phase 11e and right before any merge or queue. A publication failure blocks an agent merge until resolved.

## Phase 11e: Knowledge commit onto the PR branch (soft-fail)

Whenever a PR exists (not on dry run) and `knowledge_commit_on_pr` is not false, Trivial tickets included: Read `$REPO_DIR/content/references/knowledge-commit.md` §Phase 11e: Knowledge commit onto the PR branch (soft-fail) before any step here; `/ds-wrap` Part G is the backstop.

---

## Phase 12: Loop state cleanup

Set `.agentic/loop-state-$LOOP_KEY.json` to `status: "complete"` atomically under Contract A (skip if absent). The `status: "complete"` write MUST be read-modify-write, preserving every other `loop_state` field - including `findings_log` - unchanged; a write that emits only `{"status":"complete"}` violates this step and destroys the log. Then always:

```bash
"$REPO_DIR/bin/ds-ticket-finish" merge --repo "$REPO" --branch "$BRANCH_NAME" --ticket "$TICKET_ID" \
  --gh-repo "$GH_REPO" --pr "$PR_NUMBER" --delivery-record-input "$DELIVERY_RECORD_INPUT" \
  --auto-merge "$AUTO_MERGE_ON_CI_GREEN" --base-branch "$BASE_BRANCH"
```

Exit 2 or 127 means it did not run: stop and report. It removes the qa.md snapshot, auto-merges when `auto_merge_on_ci_green` is true (after a knowledge commit it queues with `--auto`: QUEUED, not MERGED), runs `ds-base-sync` (non-zero statuses are warnings), and retires carriers. It prints `[phase: auto-merged | pr=N]`, `auto-merge-queued`, `auto-merge-deferred`, `auto-merge-failed`, `auto-merge-skipped`, or the PR-open notice. On dry run (`--pr` empty) it skips only the merge.

**Tracker writeback (W7):** only on `[phase: auto-merged | pr=N]` (or a fallback confirming `MERGED`), Helper with `target_state: $TRACKER_STATE_DEV_COMPLETE`. `[phase: tracker-writeback | site: W7 | target: $TRACKER_STATE_DEV_COMPLETE | trigger: auto-merge-success]`

Note: W7 fires ONLY on the auto-merge success path (`AUTO_MERGE_ON_CI_GREEN=true` AND merge succeeds). If an agent merges this PR itself later, outside this auto-merge block, the dev-complete transition fires immediately at merge time under the **Merge-time tracker writeback** rule in `content/rules/conventions.md` §Git Workflow, and the deferred path described next does not apply. On the default human-merge path (`AUTO_MERGE_ON_CI_GREEN=false`), W7 does NOT fire here - the dev-complete transition is pushed automatically by the session-start pending-merge sweep instead (see `content/rules/conventions.md` §Session Context and Memory) within one session boot of the merge. AE never fires the terminal `TRACKER_STATE_DONE` state automatically at any site. The sweep is driven by the ticket ledger, so when `rework_detection` is `false` there are no candidates and no automatic dev-complete transition **for a merge the agent did not perform itself, or where the ticket ID or PR number was unknown at merge time** - the merge-time rule above never consults the ledger and still fires regardless of `rework_detection`; run `/ds-ticket-status-sync <TICKET_ID>` after merge in that configuration.

## Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)

When `.agentic/batch-state.json` exists, before advancing to the next ticket: Read `content/references/handoff-evaluation.md`, apply the goal-met short-circuit, then the four triggers (pause and exit cleanly, or continue).

**Resume banners:** `Resume: /ds-implement-ticket from this directory` (batch, single-ticket-capped); `Resume: /ds-implement-ticket ... goal_mode=open_goal ... (raise max_iterations/max_wallclock_min to continue, or accept the goal as unmet)`.

**Interrupt vs. pause path note:** 12a writes `paused_at`/`pause_reason` (and `last_summary`); `hooks/session-end-wrap.js` writes `interrupted_at`/`interrupt_reason` (Contract D). On goal-met, also set `.agentic/loop-state-$LOOP_KEY.json` to `complete` (Contract A).

## Phase 12b: Operator Runbook

Once per session, after the last ticket (not per ticket); skip when no PR opened, on goal-met, or when 12a paused. Plain text, plan-only, absolute paths, soft-fail:

What landed (`PR #<n>  <ticket_id>  → <url>` per PR); Next (the first unlanded lane's `/ds-implement-ticket` line, verbatim from the newest `docs/planning/triage-*.md` "## Kickoff prompts", with `(from: <repo path>)`; else `/ds-ticket-triage`); Blockers / deferred (this session's `qa_blocked`/INCONCLUSIVE tickets, batch `blocked` tickets with `last_summary`; omit when none). `[phase: operator-runbook | tickets_landed=<k> | blockers=<n>]`

---

## Batch state contracts (binding)

Every conductor write to `.agentic/batch-state.json` or `.agentic/loop-state-$LOOP_KEY.json` applies these.

**Contract A - per-write `session_id` gate.** Read the file first. Abort, printing `WARNING: write to .agentic/<file> aborted - another session (session_id=<X>, <field>=<Y>) appears to own this file. Identify the live session via .agentic/*.json's liveness-timestamp field. Resolve manually (kill the other session, or remove the file) and retry.`, when its `session_id` is non-empty, differs from ours, and its liveness-timestamp field (`last_updated` for `loop-state-$LOOP_KEY.json`, `updated_at` for `batch-state.json`; absent counts as stale) is within the last 10 minutes - EXCEPT that on `batch-state.json` ONLY, this condition additionally requires `status` to be `active`. A null/empty on-disk id is a mismatch (warn; takeover-eligible) unless our own id is also null (self-owned: write silently). Otherwise write, setting `session_id` and the liveness field. The hooks (`hooks/lib/state-mark.js`) use their own asymmetric predicates.

**Contract B - `replan_log[]`:** read-merge-write, append-only, never reorder or drop.

**Contract C - one batch per project root.** Creating a batch (2+ entries, open-goal Fresh init, or single-ticket-capped) over a file with `status=active`, a different `session_id`, and `updated_at` within the last 10 minutes: REFUSE with `Another batch session is active for this project root (session_id=<X>, updated_at=<Y>). Wait for it to finish, kill it and re-invoke, or remove .agentic/batch-state.json and re-invoke.` A single-ticket run over a file with `status=active` + different `session_id` + `updated_at` within the last 10 minutes prints `NOTE: a batch session is active for this project root (session_id=<X>, updated_at=<Y>). Single-ticket invocations are not refused; per-ticket loop state is keyed separately so bookkeeping will not collide. Continue? (yes/no)`.

**Contract D — Stop hook / SessionEnd hook mirror.**

The Claude Code Stop hook (`--cadence=turn`) only refreshes `last_updated`/`updated_at` on `active` files whose `session_id` positively matches. The SessionEnd hook's `markInterrupted` sets `status=interrupted`, `interrupted_at`, `interrupt_reason="unknown"` (plus `updated_at` on batch-state only; never `last_updated`, which Resume reads). Neither derives a key: `candidatePaths(cwd)` takes every `.agentic/loop-state-*.json` plus batch-state and the legacy file.

**`loop-state-$LOOP_KEY.json` fields:** `schema_version: 1`, `session_id` (`$CLAUDE_CODE_SESSION_ID`, or null on a harness that cannot match the hook namespace), `ticket_id`, `loop_key` (required; the file's own key), `resume_count`, `last_phase_iteration` (Phase 10a cycle), `branch`, `repo`, `base_branch`, `status` (`active|interrupted|complete|stalled`), `last_updated`, `interrupted_at`, `interrupt_reason`, `last_phase` (the authoritative resume key), `last_phase_action`, `auto_merge_queued` (written only by Phase 10's timeout), `loop_state {phase, iteration, max_iterations, tier, findings_log, qa_failures_log, last_engineer_summary, termination_reason}`. Overwritten at each transition, kept after clean exit; a stable contract for resume readers.

**`batch-state.json`** (skeleton in `batch-mode.md`): `status` `active|paused|interrupted|complete|stalled`; `mode` `batch|open_goal|single_ticket_capped` (absent = `batch`); `pause_reason` `stale_pace|operator_pause|wallclock_cap|open_goal_iteration_cap|null`; `wallclock_cap_min` 90 (env `AGENTIC_BATCH_MAX_WALLCLOCK_MIN`), per batch lifetime; `tickets[].status` `pending|in_progress|complete|blocked|skipped_already_merged`; `replan_log[]` (Contract B); `open_goal {active, goal_condition, iteration, max_iterations, risk_declared, termination_reason, dry_run}`.
