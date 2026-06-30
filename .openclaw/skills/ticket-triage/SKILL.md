---
name: ticket-triage
description: "Purpose: Strategic triage command that takes a ticket list or tracker input,"
user-invocable: true
---
<!--
Purpose: Strategic triage command that takes a ticket list or tracker input,
         analyses dependencies and conflicts, distributes work across parallel
         lanes, and emits a paste-ready game plan. Plan-only: no code edits,
         no tracker mutations, no .agentic/ state writes, no /implement-ticket
         invocations.

Public API: /ticket-triage                         -- triage operator's open assigned tickets (tracker required)
            /ticket-triage <input>                 -- triage list, default 3 lanes
            /ticket-triage --lanes <N> <input>     -- override lane cap
            <input> accepts any form that /implement-ticket Phase 0 accepts
            (ticket IDs, URLs, JQL, screenshots, comma/space lists).
            No-args behavior: resolves the operator's open assigned tickets
            from the configured tracker (read-only query, no tracker writes).
            source: "assigned" is a triage-local source label used only in
            the no-args path; it extends (does not match) /implement-ticket
            Phase 0's source vocabulary - do not assume the source enums
            are identical between the two commands.

Upstream deps: content/commands/implement-ticket.md Phase 0 (input normalizer,
               invoked by reference - no copy); METHODOLOGY.md (activation
               preflight); AGENTS.md ## Tracker / ## Linear sections (TRACKER
               resolution chain, same as implement-ticket Setup); Jira MCP
               (mcp__mcp-atlassian__jira_get_issue / jira_search); Linear MCP
               (mcp__linear__get_issue); content/references/trigger-catalog.md
               (yolo-guard, §d).

Downstream consumers: operator-invoked only (standalone) OR /implement-ticket
                      Phase 0a (integration path - algorithm reused by reference,
                      no copy). Output artifact (standalone path only) is
                      docs/planning/triage-<YYYYMMDD>-<4hex>.md (gitignored by
                      convention; gitignore status is project-dependent in
                      consumer repos). Kickoff prompts in the artifact are inputs
                      for the conductor on the operator's next /implement-ticket
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
               zero chains (all deferred / in-progress).

Performance: one tracker API call per ticket in Phase 1 (conductor-direct);
             one background investigator in Phase 2b when !HEURISTIC_ONLY;
             one background Skeptic in Phase 4b. Proportional to ticket count.
             >20 tickets: investigator pass skipped (HEURISTIC_ONLY=true) after
             a proceed prompt.
-->

# /ticket-triage

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Strategic triage for a set of tickets. Produces a lane-distributed game plan with paste-ready `/implement-ticket` kickoff prompts. Stops at the plan; does not invoke `/implement-ticket`, touch the tracker, or write any `.agentic/` state.

## When to use

- Before starting a sprint or batch of related tickets: understand dependencies and safe parallelization before opening sessions.
- When you have a backlog dump (JQL URL, Linear filter, screenshot) and want a sequenced execution order before committing resources.
- As a reality-check before splitting work across multiple developer sessions.

## Invocation

- `/ticket-triage` - (no args) resolve the operator's open assigned tickets from the configured tracker and triage them. Requires `TRACKER != none`; see Phase 0 no-args behavior below.
- `/ticket-triage <input>` - triage the ticket set, distribute across 3 lanes (default).
- `/ticket-triage --lanes <N> <input>` - override the lane cap.
- `<input>` accepts any form that `/implement-ticket Phase 0` accepts: bare ticket IDs, comma/space-separated lists, Jira/Linear URLs, JQL search URLs, pasted screenshots, or any mixture.
- **Single-ticket degenerate:** if Phase 0 normalizes to exactly one entry, print "Single ticket: run /implement-ticket <id> directly." and exit. Phase 4 is not reached.
- **No-tracker:** if `TRACKER == none`, skip Phase 1 metadata fetch; run Phase 2a on structural links only (none available) and Phase 2b at Level 1 only (no components/labels); print "No tracker configured - heuristic-only analysis, no metadata." before Phase 1.

## Preflight

Run the activation preflight (see `METHODOLOGY.md`). If inactive, no-op and exit.

Resolve `TRACKER`, `TICKET_PREFIX`, and `JIRA_BASE_URL` using the SAME resolution chain as `/implement-ticket` Setup (AGENTS.md `## Tracker` / `## Linear` sections). Cache results in-context for the session; do not re-resolve mid-command.

## Phase 0: Input normalization

**No-args default (invoked with no `<input>` argument).**

When `/ticket-triage` is invoked with no input, resolve the operator's open assigned tickets from the configured tracker (read-only query; no tracker writes):

- **`TRACKER == none`:** print "No tracker configured - an explicit ticket list or URL is required when no tracker is connected." and exit.
- **Jira:** query `assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC` in the configured project using `mcp__mcp-atlassian__jira_search`. Use the same pagination cap (50 results) as Phase 0's JQL resolver. Collect entries as `{ticket_id, source: "assigned"}`.
- **Linear:** query issues where `assignee: me` and state type not in `(completed, canceled)` using `mcp__linear__list_issues`. Collect entries as `{ticket_id, source: "assigned"}`.
- **0 results:** print "No open tickets assigned to you." and exit.
- **1 result:** fall through to the single-ticket degenerate path (print "Single ticket: run /implement-ticket <id> directly." and exit).
- **>=2 results:** proceed into Phase 1+ exactly as for an explicit list input. Print the resolved ticket IDs (one per line) before proceeding so the operator can confirm the scope.

`[phase: ticket-triage | phase=resolve-assigned]`

**Explicit input (any `<input>` argument provided).**

Reuse `/implement-ticket` Phase 0 by reference - invoke the same normalization logic verbatim without forking or copying the classifier table. Output is the in-memory `normalized_input.entries[]` list.

**No `.agentic/` state writes.** Phase 0 here is read-only: do NOT invoke Phase 0a-pre, Phase 0a, or any batch-state / loop-state write that implement-ticket's Phase 0 may chain into. Normalization only.

**Large-list gate:** if `len(entries) > 20`, prompt: "Ticket count exceeds 20 - investigator pass will be skipped (HEURISTIC_ONLY=true). Conflict analysis will be Level 1 only (component/label overlap). Continue? [y/N]". On `y`: set `HEURISTIC_ONLY=true` and proceed. On `n`: exit.

`[phase: ticket-triage | phase=normalize]`

## Phase 1: Metadata fetch

Conductor-direct (no subagent). For each entry in `normalized_input.entries[]`, fetch:
- **Jira:** `mcp__mcp-atlassian__jira_get_issue` - capture `priority`, `status`, `story_points` (or `timeestimate`), `labels`, `components`, `assignee`, and `issuelinks` (blocks / is-blocked-by / relates-to).
- **Linear:** `mcp__linear__get_issue` - capture `priority`, `state`, `estimate`, `labels`, `assignee`, and relations (blocks / blocked-by / related).

The captured estimate (`story_points` / `timeestimate` / Linear `estimate`) populates only the display-only "Est" column in the Phase 4a per-ticket summary table. No distribution rule consumes it; estimate-aware lane sizing is a deferred default.

**Soft-fail per ticket:** on any fetch error, mark `fetch_failed: true` on that entry and proceed. Fetch-failed tickets are treated as independent (no known deps, no known metadata) in all downstream phases.

**Terminal-status detection:** tickets whose status maps to a Done/Cancelled/Won't-do state are marked `terminal: true`. They are added to the deferred set in Phase 3 Rule 1 without further analysis.

**In-progress detection:** tickets whose status maps to an active/started/in-progress workflow state are marked `in_progress: true`. They are carried through Phase 2 analysis but removed from lane assignment after Rule 1 (shown badged `[IN PROGRESS]` in the artifact; excluded from kickoff prompts).

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

**Conductor handling:** store `functional_duplicates[]` from the investigator output into `triage_result.functional_duplicates[]`. Surface this in Phase 4a artifact and, on the /implement-ticket integration path, in Phase 0a step 2.

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

**Rule 2 - Sequential chains (consume DAG-connected components with edges):**

For every connected component of the DAG that has at least one internal edge, topo-sort its members (blockers first) and assign the chain as a single lane (run as an ordered comma-list `/implement-ticket A, B, C` batch). Non-linear components (multiple paths) are still serialized in topological order. All members of a chained component are consumed by Rule 2.

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
| ...   | ...  | ...  | ... |

## Per-ticket summary

<!-- Est column: shows the captured estimate (story points / time estimate) or "-" when absent.
     Display-only; no distribution rule consumes it. -->

| Ticket | Priority | Status | Est | Lane | Notes |
|--------|----------|--------|-----|------|-------|
| A | High | To Do | 3 | Lane 1 | |
| B | Med | To Do | 2 | Lane 1 | blocked by A |
| C | High | To Do | - | Lane 2 | |
| ... | | | | | |

## Dependency notes

<!-- List external_deps and any cycle_warning entries. -->

## Conflict warnings

<!-- Only present when one or more tickets were placed by overflow (Rule 3 step 3)
     or when chains exceed the cap (Rule 4). Always include the fixed caveat below
     when this block is non-empty. -->

Parallel-safe grouping is heuristic - based on ticket metadata and directory-level
analysis, not file-level diffing. Verify before running lanes truly concurrently;
each /implement-ticket session's own Skeptic chain still catches collisions at
merge time.

## Functional duplicate warnings

<!-- Only present when functional_duplicates[] is non-empty (Level 2 investigator ran).
     List each pair and its one-sentence rationale. Omit this section entirely when
     the array is empty or when HEURISTIC_ONLY=true (investigator was skipped). -->

| Pair | Why same work |
|------|---------------|
| A + B | Both implement the same email validation rule in the same form handler |

Consider deferring one ticket of each pair or merging them into a single ticket before
running /implement-ticket. Running both risks a merge conflict or duplicated effort.

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
/implement-ticket A, B
```

**Lane 2** (parallel - can run concurrently with other lanes):
```
/implement-ticket C, D
```
```

`[phase: ticket-triage | phase=draft]`

## Phase 4b: Skeptic review

**Skip condition:** if the artifact contains zero lanes AND zero chains (e.g. all tickets are deferred or in-progress), skip Phase 4b entirely and proceed to output.

Otherwise: spawn a fresh background Skeptic on the artifact with this adversarial brief:

> "Review this triage artifact. Check: (1) Dependency ordering - are blockers placed before the tickets they block within each chain? (2) Parallel safety - are tickets in the same lane genuinely non-conflicting per the Phase 2b analysis? (3) Deferral justification - is each deferred ticket's reason accurate and not overcautious? (4) Kickoff prompt completeness - does every non-deferred, non-in-progress ticket appear in exactly one lane's kickoff prompt? (5) Cap reconciliation - if Rule 4 fired, was the merge post-pass applied correctly and documented?"

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
- Invoke `/implement-ticket` or spawn any implementation agent.
- Create branches, PRs, worktrees, or commits.
- Write to `.agentic/batch-state.json`, `.agentic/loop-state.json`, `.agentic/tasks.jsonl`, or any other `.agentic/` state file.
- Mutate tracker tickets (no status transitions, no comment posts).
- Produce Briefs, Plans, or ADRs.
- Perform file-level conflict analysis (directory-level only via the Phase 2b investigator).

**Distinction from related commands:**
- `/implement-ticket` - executes a ticket through to a merged PR; `/ticket-triage` is upstream planning only.
- `orchestration-planner` - decomposes a single architect plan into ordered units; `/ticket-triage` operates on a tracker-sourced ticket list before any architect runs.

**Yolo-guard:** the kickoff prompts in the artifact are conductor inputs, not execution bypasses. Pasting a kickoff prompt into a session still invokes the full `/implement-ticket` flow: risk classification, architect, Skeptic, engineer, QA gate. See `content/references/trigger-catalog.md` §d.

## Edge cases

| Condition | Behavior |
|-----------|----------|
| No args, no tracker | Print "No tracker configured - an explicit ticket list or URL is required when no tracker is connected." and exit. |
| No args, 0 assigned | Print "No open tickets assigned to you." and exit. |
| No args, 1 assigned | Print "Single ticket: run /implement-ticket <id> directly." and exit. |
| No args, >=2 assigned | Print resolved ticket IDs, then proceed into Phase 1+ as for an explicit list. |
| Single ticket | Print "run /implement-ticket <id> directly." and exit before Phase 1. |
| All tickets independent (no DAG edges) | Rule 2 is a no-op; all tickets go to Rule 3 parallel grouping. |
| Circular dependency | Break at lowest-confidence link; defer both with `cycle_warning`. Do not abort. |
| Multi-prefix input (Jira + Linear IDs) | Phase 0 normalizes as usual; Phase 1 routes each ID to the correct MCP tool. Conflict analysis treats all tickets uniformly. |
| JQL returns many results | Phase 0's 50-result cap applies first (truncate + warning). Then, on the surviving set: if count >20, the HEURISTIC_ONLY gate fires (Level 1 conflict analysis only; header stamped). Both rules sequence in that order; a 60-result JQL trips both. |
| Terminal-status ticket (Done/Cancelled) | Deferred via Rule 1 with reason "terminal". Not included in lane assignment or kickoff prompts. |
| In-progress ticket | Carried through analysis; removed from lane assignment after Rule 1. Shown badged `[IN PROGRESS]`. Excluded from kickoff prompts. |
| No tracker configured (with explicit input) | Skip Phase 1; run Phase 2a with zero link data; run Phase 2b Level 1 with zero component/label data; print notice. |

## Soft-fail discipline

Every tracker and MCP call soft-fails: log and continue. A fetch failure on one ticket never aborts the triage of the remaining set. Fetch-failed tickets are treated as independent with no known metadata. The command never errors out on external API failure.

Emit one breadcrumb per phase as shown in each section above. The terminal breadcrumb is `[phase: ticket-triage | phase=complete]`.
