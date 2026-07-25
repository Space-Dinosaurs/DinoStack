> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

<!--
Purpose: Strategic triage command that takes a ticket list or tracker input,
         analyses dependencies and conflicts, distributes work across parallel
         lanes, and emits a paste-ready game plan. Plan-only: no code edits,
         no tracker mutations, no .agentic/ state writes, no /ds-implement-ticket
         invocations.

Public API: /ds-ticket-triage                         -- triage operator's open assigned tickets (tracker required)
            /ds-ticket-triage <input>                 -- triage list, default 3 lanes
            /ds-ticket-triage --lanes <N> <input>     -- override lane cap
            <input> accepts any form that /ds-implement-ticket Phase 0 accepts
            (ticket IDs, URLs, JQL, screenshots, comma/space lists).
            No-args behavior: resolves the operator's open assigned tickets
            from the configured tracker (read-only query, no tracker writes).
            source: "assigned" is a triage-local source label used only in
            the no-args path; it extends (does not match) /ds-implement-ticket
            Phase 0's source vocabulary - do not assume the source enums
            are identical between the two commands.

Upstream deps: content/commands/ds-implement-ticket.md Phase 0 (input normalizer,
               invoked by reference - no copy) and Phase 1 Ticket-rework
               detection (per-entry ledger read, invoked by reference - no
               fork of the jq algorithm); METHODOLOGY.md (activation
               preflight); AGENTS.md ## Tracker / ## Linear sections (TRACKER
               resolution chain, same as implement-ticket Setup); Jira MCP
               (mcp__mcp-atlassian__jira_get_issue / jira_search); Linear MCP
               (mcp__linear__get_issue); content/references/trigger-catalog.md
               (yolo-guard, §d); .agentic/ticket-ledger.jsonl (local,
               gitignored, tracker-independent read - see content/references/
               ticket-rework.md for schema and algorithm).

Downstream consumers: operator-invoked only (standalone) OR /ds-implement-ticket
                      Phase 0a (integration path - algorithm reused by reference,
                      no copy). Output artifact (standalone path only) is
                      docs/planning/triage-<YYYYMMDD>-<4hex>.md (gitignored by
                      convention; gitignore status is project-dependent in
                      consumer repos). Kickoff prompts in the artifact are inputs
                      for the conductor on the operator's next /ds-implement-ticket
                      session; they do not bypass risk classification or Skeptic
                      review.

Output description: triage_result {lanes[], deferred[], in_progress_excluded[],
                    functional_duplicates[], conflict_warnings[], heuristic_only}
                    where functional_duplicates[] contains
                    {ticket_ids: [A, B], summary: "<one-sentence why same work>"}
                    entries (empty array when none). Level-1-only / HEURISTIC_ONLY
                    runs skip functional-duplicate detection (no ticket content
                    read at Level 1).

Failure modes: soft-fail per ticket throughout; fetch failures treated as
               independent tickets, not as aborts. Single-ticket degenerate
               exits before Phase 1. No-tracker exits after Phase 0 with
               heuristic-only notice; no-args + no-tracker exits immediately
               (explicit list required). 0 assigned tickets exits immediately.
               Phase 4b Skeptic skipped when artifact contains zero lanes and
               zero chains (all deferred / in-progress). Ticket-rework ledger
               read soft-fails per line (absent/unreadable ledger or a single
               malformed line never blocks triage of the remaining set - see
               Ticket-rework detection below).

Performance: one tracker API call per ticket in Phase 1 (conductor-direct);
             one background investigator in Phase 2b when !HEURISTIC_ONLY;
             one background Skeptic in Phase 4b. Proportional to ticket count.
             >20 tickets: investigator pass skipped (HEURISTIC_ONLY=true) after
             a proceed prompt.
-->

# /ds-ticket-triage

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Strategic triage for a set of tickets. Produces a lane-distributed game plan with paste-ready `/ds-implement-ticket` kickoff prompts. Stops at the plan; does not invoke `/ds-implement-ticket`, touch the tracker, or write any `.agentic/` state.

## When to use

- Before starting a sprint or batch of related tickets: understand dependencies and safe parallelization before opening sessions.
- When you have a backlog dump (JQL URL, Linear filter, screenshot) and want a sequenced execution order before committing resources.
- As a reality-check before splitting work across multiple developer sessions.

## Invocation

- `/ds-ticket-triage` - (no args) resolve the operator's open assigned tickets from the configured tracker and triage them. Requires `TRACKER != none`; see Phase 0 no-args behavior below.
- `/ds-ticket-triage <input>` - triage the ticket set, distribute across 3 lanes (default).
- `/ds-ticket-triage --lanes <N> <input>` - override the lane cap.
- `<input>` accepts any form that `/ds-implement-ticket Phase 0` accepts: bare ticket IDs, comma/space-separated lists, Jira/Linear URLs, JQL search URLs, pasted screenshots, or any mixture.
- **Single-ticket degenerate:** if Phase 0 normalizes to exactly one entry, print "Single ticket: run /ds-implement-ticket <id> directly." and exit. Phase 4 is not reached.
- **No-tracker:** if `TRACKER == none`, skip Phase 1 metadata fetch; run Phase 2a on structural links only (none available) and Phase 2b at Level 1 only (no components/labels); print "No tracker configured - heuristic-only analysis, no metadata." before Phase 1.

## Preflight

Run the activation preflight (see `METHODOLOGY.md`). If inactive, no-op and exit.

Resolve `TRACKER`, `TICKET_PREFIX`, and `JIRA_BASE_URL` using the SAME resolution chain as `/ds-implement-ticket` Setup (AGENTS.md `## Tracker` / `## Linear` sections). Cache results in-context for the session; do not re-resolve mid-command.

Resolve `REWORK_DETECTION` the SAME way as `/ds-implement-ticket` Setup: read `.agentic/config.json` key `rework_detection` (boolean, default `true`; absent key resolves to `true`). This governs the per-entry ledger read below - see `content/references/ticket-rework.md`.

## Phase 0: Input normalization

**No-args default (invoked with no `<input>` argument).**

When `/ds-ticket-triage` is invoked with no input, resolve the operator's open assigned tickets from the configured tracker (read-only query; no tracker writes):

- **`TRACKER == none`:** print "No tracker configured - an explicit ticket list or URL is required when no tracker is connected." and exit.
- **Jira:** query `project = <TICKET_PREFIX> AND assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC` in the configured project using `mcp__mcp-atlassian__jira_search`, where `<TICKET_PREFIX>` is the project key resolved by the Preflight. Use the same pagination cap (50 results) as Phase 0's JQL resolver. Collect entries as `{ticket_id, source: "assigned"}`.
- **Linear:** query issues where `assignee: me`, team = the resolved team (from `Team`/`TICKET_PREFIX` in the tracker resolution), and state type not in `(completed, canceled)` using `mcp__linear__list_issues`. Collect entries as `{ticket_id, source: "assigned"}`.
- **0 results:** print "No open tickets assigned to you." and exit.
- **1 result:** fall through to the single-ticket degenerate path (print "Single ticket: run /ds-implement-ticket <id> directly." and exit).
- **>=2 results:** proceed into Phase 1+ exactly as for an explicit list input. Print the resolved ticket IDs (one per line) before proceeding so the operator can confirm the scope.

`[phase: ticket-triage | phase=resolve-assigned]`

**Explicit input (any `<input>` argument provided).**

Reuse `/ds-implement-ticket` Phase 0 by reference - invoke the same normalization logic verbatim without forking or copying the classifier table. Output is the in-memory `normalized_input.entries[]` list.

**No `.agentic/` state writes.** Phase 0 here is read-only: do NOT invoke Phase 0a-pre, Phase 0a, or any batch-state / loop-state write that implement-ticket's Phase 0 may chain into. Normalization only.

**Large-list gate:** if `len(entries) > 20`, prompt: "Ticket count exceeds 20 - investigator pass will be skipped (HEURISTIC_ONLY=true). Conflict analysis will be Level 1 only (component/label overlap). Continue? [y/N]". On `y`: set `HEURISTIC_ONLY=true` and proceed. On `n`: exit.

`[phase: ticket-triage | phase=normalize]`

## Ticket-rework detection (per-entry, runs after entries[] resolves via EITHER Phase 0 branch)

**Anchoring (binding).** Phase 0 above has two mutually exclusive branches - the no-args default (terminal breadcrumb `phase=resolve-assigned`) and explicit input (terminal breadcrumb `phase=normalize`) - each ending in its own breadcrumb. This detection step sits downstream of BOTH: it runs once `entries[]` has been resolved, regardless of which branch produced the list, and before Phase 1 begins. Anchoring to the `normalize` breadcrumb alone would silently skip the badge for every no-args invocation, which is the documented default form for a tracker-connected operator - see the dual-branch anchoring pattern in `content/references/ticket-rework.md`.

**Outside the Phase 1 tracker gate, deliberately.** This step does NOT sit inside Phase 1 and is NOT gated on `TRACKER != none`. Detection makes zero tracker and zero network calls - it is a single local file read, so it works identically whether a tracker is configured or not. Phase 1's no-tracker skip ("if `TRACKER == none`, skip Phase 1 metadata fetch") would, if this read were nested inside Phase 1, hide the badge at exactly the state most consumer repos are in. `TRACKER=none` is in fact the case this ledger matters most for - there is no tracker comment thread to carry prior-attempt signal.

For each entry in the resolved `entries[]`, reuse `/ds-implement-ticket` Phase 1's "Ticket-rework detection" sub-section by reference - same file (`.agentic/ticket-ledger.jsonl`), same exact-`ticket_id`-match + dedupe-by-`pr_number`-latest-wins jq algorithm, same soft-fail-per-line discipline (one malformed line is skipped, not fatal to the whole read; an absent or unreadable ledger resolves to zero prior attempts rather than erroring). Do not fork or re-derive that algorithm here.

1. If `REWORK_DETECTION` is `false` (see Preflight), or a given entry's `ticket_id` is null/empty (a freeform/local entry with no ticket reference), skip detection for that entry: `entry.PRIOR_ATTEMPTS = 0`, `entry.IS_REWORK = false`. No badge, no lane-rule effect.
2. Otherwise set `entry.PRIOR_ATTEMPTS`, `entry.IS_REWORK`, and `entry.LATEST_PR` (the `pr_number` of the most recent deduped prior record) exactly as the implement-ticket detection produces `PRIOR_ATTEMPTS` / `IS_REWORK` / the last element of `PRIOR_COMPLETED`.

`entry.IS_REWORK` feeds the `[REWORK xN]` badge (Phase 4a) and the never-parallel lane rule (Phase 3) below.

`[phase: ticket-triage | phase=rework-detect]`

## Phase 1: Metadata fetch

Conductor-direct (no subagent). For each entry in `normalized_input.entries[]`, fetch:
- **Jira:** `mcp__mcp-atlassian__jira_get_issue` - capture `priority`, `status`, `story_points` (or `timeestimate`), `labels`, `components`, `assignee`, and `issuelinks` (blocks / is-blocked-by / relates-to).
- **Linear:** `mcp__linear__get_issue` - capture `priority`, `state`, `estimate`, `labels`, `assignee`, and relations (blocks / blocked-by / related).

The captured estimate (`story_points` / `timeestimate` / Linear `estimate`) populates the display-only "Est" column in the Phase 4a per-ticket summary table; no distribution rule consumes it, and estimate-aware lane sizing is a deferred default. Only `story_points` and Linear `estimate` trigger the story-size preflight below - `timeestimate` is Jira's time-tracking field (denominated in seconds), display-only, and is never compared against the preflight threshold.

**Soft-fail per ticket:** on any fetch error, mark `fetch_failed: true` on that entry and proceed. Fetch-failed tickets are treated as independent (no known deps, no known metadata) in all downstream phases.

**Terminal-status detection:** tickets whose status maps to a Done/Cancelled/Won't-do state are marked `terminal: true`. They are added to the deferred set in Phase 3 Rule 1 without further analysis.

**In-progress detection:** tickets whose status maps to an active/started/in-progress workflow state are marked `in_progress: true`. They are carried through Phase 2 analysis but removed from lane assignment after Rule 1 (shown badged `[IN PROGRESS]` in the artifact; excluded from kickoff prompts).

> **Story-size preflight** - runs once, immediately after all metadata is collected.
>
> For each ticket whose estimate is available (`story_points` or Linear `estimate` is a number) AND that is not `terminal: true` or `in_progress: true` (those are deferred / excluded from lane assignment regardless of size - warning them here would flag tickets that never reach `/ds-implement-ticket`), check:
> - **≥ 5 points:** print the following warning (once per oversized ticket):
>   ```
>   ⚠ [DS-XX] Est: N pts - large story. Recommend decomposing into ≤ 3-point sub-tickets
>     before running /ds-implement-ticket. A single 5+ point story can exhaust the context
>     window before the loop completes. Split strategy: one sub-ticket per independent
>     deliverable; use /ds-ticket-triage on the sub-set to re-sequence.
>   ```
>   Then append a `context_risk: high` flag to that entry. Lane assignment proceeds normally; the operator decides whether to decompose.
>
> - **3-4 points:** no warning. `context_risk` is unset.
> - **≤ 2 points or estimate absent:** no warning. Safe to run as-is.
>
> **Token-reduction reminder** - if any ticket has `context_risk: high`, append this one-time callout at the end of the story-size preflight output:
> ```
> 💡 Token-reduction tools: if your harness supports ctx_* context-mode tools
>    (ctx_execute, ctx_batch_execute), prefer them over raw shell output for any
>    operation producing > 20 lines - they reduce context consumption by ~98%
>    (see content/rules/code-standards.md §Context Window Management).
>    If context fills mid-session, /ds-wrap → /clear → re-invoke /ds-implement-ticket
>    with the remaining ticket IDs to continue in a fresh window.
> ```
>
> **Silent on clean sets:** if no ticket has `context_risk: high`, print nothing. No output on safe sessions.
>
> The `context_risk` flags are display-only; no distribution rule consumes them.

`[phase: ticket-triage | phase=metadata]`

## Phase 2a: DAG construction

From the `blocks` / `is-blocked-by` link fields, build a directed acyclic graph over the ticket set. Links pointing to tickets outside the set are recorded as `external_deps[]` (noted in the artifact but not used for lane assignment).

**Cycle detection:** if a cycle is found, break it at the lowest-confidence link (`relates-to` < `blocks` < `is-blocked-by`). Defer both endpoints with `cycle_warning: true`. Do not abort - continue with the remaining graph.

`[phase: ticket-triage | phase=dag]`

## Phase 2b: Conflict-surface analysis

**Level 1 (always, conductor-direct):** for each pair of tickets, check for shared `components[]` or `labels[]`. Mark any overlapping pair as in the same conflict group. Functional-duplicate detection is NOT performed at Level 1 (no ticket content is read).

**Level 2 (when `!HEURISTIC_ONLY` and `len(entries) <= 20`):** spawn one background investigator over all tickets. The investigator reads only:
- root `AGENTS.md` and any track-level `AGENTS.md` for tracks whose names appear in ticket titles/descriptions.
- A top-level directory listing of the repo.
- The title and description of each ticket in the set.

The investigator brief MUST include the following two tasks:

1. **Conflict analysis.** Return `{ticket_id -> affected_areas[]}`. Two tickets conflict if their `affected_areas[]` overlap OR they share a Level 1 conflict group.

2. **Functional-duplicate detection.** For every pair of DISTINCT tickets in the set, assess whether a reasonable engineer would implement them with exactly the same change. The bar is strict: related-but-distinct work (e.g. add-login vs add-logout, two separate bug fixes in the same file) is NOT a duplicate. A duplicate pair is only flagged when the descriptions define the same functional requirement such that a single implementation resolves both. Return `functional_duplicates: [{ticket_ids: [A, B], summary: "<one-sentence explanation of why the same change resolves both>"}]` (empty array when none).

The investigator output contract is `{ticket_id -> affected_areas[], functional_duplicates[{ticket_ids, summary}]}`.

**Conductor handling:** store `functional_duplicates[]` from the investigator output into `triage_result.functional_duplicates[]`. Surface this in Phase 4a artifact and, on the /ds-implement-ticket integration path, in Phase 0a step 2.

**HEURISTIC_ONLY stamp:** when `HEURISTIC_ONLY=true`, Phase 2b runs Level 1 only. The artifact header is stamped: "Conflict analysis: Level 1 only (component/label overlap; >20 tickets, investigator pass skipped). Functional-duplicate detection was also skipped."

`[phase: ticket-triage | phase=conflict]`

## Phase 3: Distribution synthesis

Conductor-direct, pure reasoning. Implements the **consume-and-remainder pipeline**: each rule consumes the tickets it assigns; later rules see only the remainder. Every input ticket lands in exactly one category: `deferred`, `in-progress-excluded`, or `lane-assigned`.

**Rule 1 - Deferral (terminal, consumes first):**

Defer the following; they are removed from all downstream rules:
- Tickets with `terminal: true` (Done / Cancelled).
- Tickets with unresolved `external_dep` that blocks them (the blocker is outside the set).
- Fetch-failed tickets where no metadata is available (unplannable).
- Tickets with `cycle_warning: true`.
- Lowest-priority tickets with no dependents when `num_entries > lanes * 4` (documented overflow deferral; use judgment and document reason).

**In-progress removal (after Rule 1):** tickets with `in_progress: true` are removed from lane assignment. They appear in the artifact badged `[IN PROGRESS]` and are excluded from kickoff prompts. They are NOT deferred and NOT lane-assigned.

**Rework isolation (after in-progress removal, before Rule 2):** every remaining ticket with `entry.IS_REWORK: true` (see Ticket-rework detection above) is consumed here, unconditionally, and assigned its own single-ticket chain lane - **never** `parallel`, regardless of Phase 2a's DAG or Phase 2b's conflict-group findings for it. A rework ticket carries a forced Elevated risk floor and may draw a Tier-3 Skeptic (`content/references/ticket-rework.md` §Escalation table); folding it into a same-lane parallel batch with other tickets would misrepresent its cost as parallel-safe filler. It is neither deferred nor excluded from kickoff - it runs, just never batched with anything else. Its Notes cell (At-a-glance and Per-ticket summary tables) records `rework xN - Elevated floor, may draw Tier-3 Skeptic; verify PR #<n>`, where `N = entry.PRIOR_ATTEMPTS` and `<n> = entry.LATEST_PR`. Each isolated rework ticket = one lane slot consumed in the Rule 4 cap accounting, same as a Rule 2 chain.

Accepted trade-off: a rework ticket that also has a DAG edge to another remaining ticket (it blocks, or is blocked by, a non-rework ticket) loses Rule 2's chain-ordering guarantee for that edge, because rework isolation removes it from the DAG-chain pool before Rule 2 runs. This is deliberate given the never-parallel mandate above; if it proves to lose real dependency information in practice, the fix is to special-case DAG-connected rework tickets, not to weaken the isolation rule for the common (no-DAG-edge) case.

**Rule 2 - Sequential chains (consume DAG-connected components with edges, from the remainder after rework isolation):**

For every connected component of the DAG that has at least one internal edge, topo-sort its members (blockers first) and assign the chain as a single lane (run as an ordered comma-list `/ds-implement-ticket A, B, C` batch). Non-linear components (multiple paths) are still serialized in topological order. All members of a chained component are consumed by Rule 2.

Each chain = one lane slot consumed in the cap accounting.

**Rule 3 - Parallel grouping (sees only the remainder: tickets with zero internal DAG edges):**

1. Sort candidates by **priority descending, then ticket_id ascending** (total order; deterministic).
2. For each candidate in that order: place it in the **lowest-index existing lane** that has no conflict with it (conflict = shared conflict group per Phase 2b). If no existing lane is conflict-free AND current lane count < cap: open a new lane. If cap is reached: hold for the overflow step.
3. **Overflow (cap reached, candidate unplaced):** place the candidate in the lane with the fewest conflicts with it; ties broken by lowest lane index. Emit a per-ticket `conflict-warning` entry in the artifact.

**Rule 4 - Cap reconciliation (reorganizes lanes; never reassigns ticket categories):**

Cap = `--lanes N` (default 3).

- If `num_chains > cap`: do NOT merge chains (they are hard dependency units). Report in the artifact: "Dependency structure requires `<num_chains>` sequential lanes, exceeding the cap of `<cap>`. Raise --lanes to `<num_chains>` or accept `<num_chains>` concurrent sessions." Proceed with `num_chains` lanes for chains.
- If `num_chains + num_parallel_lanes > cap`: run a deterministic merge post-pass over **parallel lanes only**. Repeatedly merge the pair of parallel lanes that introduces the **fewest new intra-lane conflicts**; ties broken by (smallest combined ticket count, then lexicographically smallest member ticket_id). A merged lane runs its tickets sequentially as a comma-list batch. Each merge strictly reduces lane count, so the loop terminates. Stop when total lanes <= cap OR no parallel lanes remain to merge. If still > cap after exhausting merges, emit a cap-warning recommending a higher `--lanes`. **Rule 3 is NOT recomputed after merges.**

`[phase: ticket-triage | phase=distribute]`

## Phase 4a: Artifact draft

Conductor-direct. Write the artifact to `docs/planning/triage-<YYYYMMDD>-<4hex>.md` using the repo's absolute path. The `<YYYYMMDD>` is today's date; `<4hex>` is 4 random hex characters.

Artifact skeleton:

```markdown
# Ticket Triage - <YYYYMMDD>

<!-- HEURISTIC_ONLY stamp (include only when HEURISTIC_ONLY=true):
Conflict analysis: Level 1 only (component/label overlap; >20 tickets, investigator pass skipped).
-->

## At a glance

| Lane | Tickets | Type | Notes |
|------|---------|------|-------|
| Lane 1 | A, B | chain | B blocked by A |
| Lane 2 | C, D | parallel | independent |
| Lane 3 | E | chain | rework x2 - Elevated floor, may draw Tier-3 Skeptic; verify PR #458 |
| ...   | ...  | ...  | ... |

## Per-ticket summary

<!-- Est column: shows the captured estimate (story points / time estimate) or "-" when absent.
     Display-only; no distribution rule consumes it.
     ⚠ column: populated with "⚠ large" when context_risk: high (≥5 pts); otherwise empty.
     Ticket column: append "[REWORK xN]" when entry.IS_REWORK is true, N = entry.PRIOR_ATTEMPTS
     (see Ticket-rework detection above). Never combined with a `parallel` Lane/Type value -
     a rework ticket's own single-ticket chain lane always shows Type "chain" (Rework isolation
     rule). Its Notes cell carries the same "rework xN - ...; verify PR #<n>" annotation as the
     At-a-glance row for that lane. -->

| Ticket | Priority | Status | Est | ⚠ | Lane | Notes |
|--------|----------|--------|-----|---|------|-------|
| A | High | To Do | 3 | | Lane 1 | |
| B | Med | To Do | 2 | | Lane 1 | blocked by A |
| C | High | To Do | 8 | ⚠ large | Lane 2 | |
| E [REWORK x2] | High | To Do | 3 | | Lane 3 | rework x2 - Elevated floor, may draw Tier-3 Skeptic; verify PR #458 |
| ... | | | | | | |

## Dependency notes

<!-- List external_deps and any cycle_warning entries. -->

## Conflict warnings

<!-- Only present when one or more tickets were placed by overflow (Rule 3 step 3)
     or when chains exceed the cap (Rule 4). Always include the fixed caveat below
     when this block is non-empty. -->

Parallel-safe grouping is heuristic - based on ticket metadata and directory-level
analysis, not file-level diffing. Verify before running lanes truly concurrently;
each /ds-implement-ticket session's own Skeptic chain still catches collisions at
merge time.

## Functional duplicate warnings

<!-- Only present when functional_duplicates[] is non-empty (Level 2 investigator ran).
     List each pair and its one-sentence rationale. Omit this section entirely when
     the array is empty or when HEURISTIC_ONLY=true (investigator was skipped). -->

| Pair | Why same work |
|------|---------------|
| A + B | Both implement the same email validation rule in the same form handler |

Consider deferring one ticket of each pair or merging them into a single ticket before
running /ds-implement-ticket. Running both risks a merge conflict or duplicated effort.

## Deferred tickets

| Ticket | Reason |
|--------|--------|
| X | terminal (Done) |
| Y | external blocker outside set |

## In-progress tickets

| Ticket | Assignee | Notes |
|--------|----------|-------|
| Z [IN PROGRESS] | ... | Excluded from kickoff prompts |

## Kickoff prompts

<!-- One block per lane. Use absolute paths where paths are involved.
     In-progress and deferred tickets are NOT included here. -->

**Lane 1** (sequential chain - run as one session):
```
/ds-implement-ticket A, B
```

**Lane 2** (parallel - can run concurrently with other lanes):
```
/ds-implement-ticket C, D
```

**Lane 3** (rework - single-ticket chain, never parallel; verify PR #458 before running):
```
/ds-implement-ticket E
```
```

`[phase: ticket-triage | phase=draft]`

## Phase 4b: Skeptic review

**Skip condition:** if the artifact contains zero lanes AND zero chains (e.g. all tickets are deferred or in-progress), skip Phase 4b entirely and proceed to output.

Otherwise: spawn a fresh background Skeptic on the artifact with this adversarial brief:

> "Review this triage artifact. Check: (1) Dependency ordering - are blockers placed before the tickets they block within each chain? (2) Parallel safety - are tickets in the same lane genuinely non-conflicting per the Phase 2b analysis? (3) Deferral justification - is each deferred ticket's reason accurate and not overcautious? (4) Kickoff prompt completeness - does every non-deferred, non-in-progress ticket appear in exactly one lane's kickoff prompt? (5) Cap reconciliation - if Rule 4 fired, was the merge post-pass applied correctly and documented? (6) Rework isolation - was every ticket with `IS_REWORK: true` given the `[REWORK xN]` badge, placed in its own single-ticket chain lane (never `parallel`), and is its Notes cell annotated with the prior PR number?"

Max 3 fix passes, then escalate to the operator with open findings listed.

`[phase: ticket-triage | phase=skeptic-review]`

## Output

After Phase 4b sign-off (or after the skip condition triggers), print to chat:

1. The absolute path of the artifact.
2. The at-a-glance table (copy from artifact).
3. The kickoff prompts section (copy from artifact).
4. A one-line summary: "N tickets triaged: M lane-assigned across K lanes, P deferred, Q in-progress."
5. If any conflict warnings were emitted, restate the fixed caveat.
6. If `HEURISTIC_ONLY=true`, restate the Level 1 stamp.

`[phase: ticket-triage | phase=complete]`

## Composition and non-goals

**Non-goals (this command intentionally does NOT):**
- Invoke `/ds-implement-ticket` or spawn any implementation agent.
- Create branches, PRs, worktrees, or commits.
- Write to `.agentic/batch-state.json`, `.agentic/loop-state.json`, `.agentic/tasks.jsonl`, or any other `.agentic/` state file.
- Mutate tracker tickets (no status transitions, no comment posts).
- Produce Briefs, Plans, or ADRs.
- Perform file-level conflict analysis (directory-level only via the Phase 2b investigator).

**Distinction from related commands:**
- `/ds-implement-ticket` - executes a ticket through to a merged PR; `/ds-ticket-triage` is upstream planning only.
- `orchestration-planner` - decomposes a single architect plan into ordered units; `/ds-ticket-triage` operates on a tracker-sourced ticket list before any architect runs.

**Yolo-guard:** the kickoff prompts in the artifact are conductor inputs, not execution bypasses. Pasting a kickoff prompt into a session still invokes the full `/ds-implement-ticket` flow: risk classification, architect, Skeptic, engineer, QA gate. See `content/references/trigger-catalog.md` §d.

## Edge cases

| Condition | Behavior |
|-----------|----------|
| No args, no tracker | Print "No tracker configured - an explicit ticket list or URL is required when no tracker is connected." and exit. |
| No args, 0 assigned | Print "No open tickets assigned to you." and exit. |
| No args, 1 assigned | Print "Single ticket: run /ds-implement-ticket <id> directly." and exit. |
| No args, >=2 assigned | Print resolved ticket IDs, then proceed into Phase 1+ as for an explicit list. |
| Single ticket | Print "run /ds-implement-ticket <id> directly." and exit before Phase 1. |
| All tickets independent (no DAG edges) | Rule 2 is a no-op; all tickets go to Rule 3 parallel grouping. |
| Circular dependency | Break at lowest-confidence link; defer both with `cycle_warning`. Do not abort. |
| Multi-prefix input (Jira + Linear IDs) | Phase 0 normalizes as usual; Phase 1 routes each ID to the correct MCP tool. Conflict analysis treats all tickets uniformly. |
| JQL returns many results | Phase 0's 50-result cap applies first (truncate + warning). Then, on the surviving set: if count >20, the HEURISTIC_ONLY gate fires (Level 1 conflict analysis only; header stamped). Both rules sequence in that order; a 60-result JQL trips both. |
| Terminal-status ticket (Done/Cancelled) | Deferred via Rule 1 with reason "terminal". Not included in lane assignment or kickoff prompts. |
| In-progress ticket | Carried through analysis; removed from lane assignment after Rule 1. Shown badged `[IN PROGRESS]`. Excluded from kickoff prompts. |
| No tracker configured (with explicit input) | Skip Phase 1; run Phase 2a with zero link data; run Phase 2b Level 1 with zero component/label data; print notice. |
| Ticket with `IS_REWORK: true` (one or more prior AE PR-opening attempts recorded in the ledger) | Badged `[REWORK xN]`. Isolated into its own single-ticket chain lane (never `parallel`). NOT deferred, NOT excluded from kickoff. Notes cell names the prior PR. Runs identically at `TRACKER=none` - detection is tracker-independent. |
| `rework_detection` disabled, or ledger absent/unreadable | Detection soft-fails to `PRIOR_ATTEMPTS = 0` for every entry; no badge, no lane-rule effect. Triage proceeds unaffected. |

## Soft-fail discipline

Every tracker and MCP call soft-fails: log and continue. A fetch failure on one ticket never aborts the triage of the remaining set. Fetch-failed tickets are treated as independent with no known metadata. The command never errors out on external API failure. The ticket-rework ledger read (a local file, not a tracker/MCP call) follows the same discipline: an absent or unreadable ledger, or a single malformed line within it, resolves to zero prior attempts for the affected entry(ies) rather than erroring - see Ticket-rework detection above.

Emit one breadcrumb per phase as shown in each section above. The terminal breadcrumb is `[phase: ticket-triage | phase=complete]`.
