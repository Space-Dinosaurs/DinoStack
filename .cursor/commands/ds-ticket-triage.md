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
               ticket-rework.md for schema and algorithm); gh CLI (pr list
               --state open, one call per run, repo inferred from git remote).

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
               Phase 4b Skeptic skipped when artifact contains zero lanes,
               zero chains, and no IN_FLIGHT-sourced exclusions (all deferred
               / in-progress with no open-PR evidence). Ticket-rework ledger
               read soft-fails per line (absent/unreadable ledger or a single
               malformed line never blocks triage of the remaining set - see
               Ticket-rework detection below). In-flight code detection's
               `gh pr list` call degrades to a total no-op (no flags set) when
               `gh` is absent, unauthenticated, has no remote, or the call
               fails - see In-flight code detection below.

Performance: one tracker API call per ticket in Phase 1 (conductor-direct);
             one background investigator in Phase 2b when !HEURISTIC_ONLY;
             one background Skeptic in Phase 4b. Proportional to ticket count.
             >20 tickets: investigator pass skipped (HEURISTIC_ONLY=true) after
             a proceed prompt. Ticket-rework detection adds N entries x one
             full-file jq parse of the local `.agentic/ticket-ledger.jsonl`
             (no network, no tracker call) once per triage run. In-flight code
             detection adds exactly one `gh pr list` call per triage run, not
             per ticket.
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
- **>=2 results:** proceed into Ticket-rework detection, In-flight code detection, and Phase 1+ exactly as for an explicit list input. Print the resolved ticket IDs (one per line) before proceeding so the operator can confirm the scope.

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

## In-flight code detection (cross-checkout, runs after entries[] resolves via EITHER Phase 0 branch)

**Anchoring (binding).** Phase 0 above has two mutually exclusive branches - the no-args default (terminal breadcrumb `phase=resolve-assigned`) and explicit input (terminal breadcrumb `phase=normalize`) - each ending in its own breadcrumb. This detection step sits downstream of BOTH: it runs once `entries[]` has been resolved and Ticket-rework detection above has completed, regardless of which Phase 0 branch produced the list, and before Phase 1 begins - see the dual-branch anchoring pattern in `content/references/ticket-rework.md` §Anchoring Instance 2.

**Phase-siting ruling.** This section sits before `## Phase 1: Metadata fetch` and is therefore NOT executed on the `/ds-implement-ticket` Phase 0a integration path: Phase 0a feeds its OWN already-normalized `entries[]` directly into triage Phase 1. Consequence (a): no self-detection - a triage run reached via Phase 0a never checks its own tickets for in-flight PRs. Consequence (b), **stated as a LIMITATION, not a compensation**: `/ds-implement-ticket A, B, C` - the exact comma-list form the Kickoff prompts section emits - receives **no** in-flight code detection. `## Tracker Create Helper` does not cover this gap (it runs at create time, is tracker-status-based, and reads no PR); `## Scope boundary` is a ticket-body block, not a backstop. Closing this gap is a follow-up unit, named here so it is not mistaken for already-covered ground.

**The call - one network call per run, O(1), zero shell `git` calls:**

```
gh pr list --state open --limit 100 --json number,title,headRefName,isDraft,url
```

No `--repo` flag: `gh` infers the repository from the git remote, so no `AGENTS.md` value is required.

**Truncation notice.** `--limit 100` truncates silently unless flagged, and this file already establishes the opposite convention (Phase 0's 50-result JQL cap emits a truncate-plus-warning - see the Edge cases table below). Follow it here: if the call returns exactly 100 PRs (the cap reached), print `In-flight evidence truncated at 100 open PRs - recall may be incomplete for repos with more open PRs than that.` once, immediately after the call, before matching proceeds.

**Precondition (binding).** Detection is skipped for any entry whose `ticket_id` is null or empty - mirroring the Ticket-rework detection guard above (a freeform/local entry with no ticket reference). Sets `entry.IN_FLIGHT = false`, leaves `entry.in_progress` untouched.

**Match predicate (binding).** For non-empty `<KEY>` and candidate `S`: occurs case-insensitively, the following character is **non-alphanumeric or absent**, and the preceding character is **non-alphanumeric or absent**. Candidates: each open PR's `title` and `headRefName`.

**Precedence rule (binding).** `entry.IN_FLIGHT` (this section) and `entry.IN_PROGRESS_TRACKER` (Phase 1's tracker-column mapping, below) are **independent** sources of `entry.in_progress` - neither suppresses the other, and both are commonly true at once (a developer moves the column and opens a PR in the same workflow). `entry.IS_REWORK` is **orthogonal** to both. There is no single "both-true" format - see the **Notes-cell composition** rule immediately below for how every combination renders.

**Notes-cell composition (binding).** The In-progress tickets table's Notes cell is composed, not a fixed string per source combination. Render these clauses in order, joined by `; `:
1. **Base** (always): `Excluded from kickoff prompts`.
2. **In-flight clause** (when `entry.IN_FLIGHT`): `in flight: open PR #<n>` (the highest-numbered evidence entry), followed by ` (+N more)` when `entry.IN_FLIGHT_EVIDENCE[]` exceeds the Evidence cap below.
3. **Rework clause** (when `entry.IS_REWORK`): if clause 2 rendered, append `prior attempt PR #<m> - verify both once back from in-progress`; otherwise append `verify PR #<m> once back from in-progress`.
4. **Tracker-column qualifier** (when `entry.IN_FLIGHT` is true AND `entry.IN_PROGRESS_TRACKER` is false - the column genuinely did not move): append `detected from an open PR, not the tracker column`. Omit this qualifier whenever `entry.IN_PROGRESS_TRACKER` is also true - claiming the column did not move would be false in the common overlap case.

All combinations of (`entry.IN_PROGRESS_TRACKER`, `entry.IN_FLIGHT`, `entry.IS_REWORK`) that reach this table (i.e. `entry.in_progress` is true) render under this rule; none is a fixed three-way branch. See the In-progress tickets table below for a worked example of each combination.

**Degradation** (all silent-and-continue):

| Condition | Behavior |
|---|---|
| `gh` absent, unauthenticated, no remote, or call fails | total no-op; no flags set; print `In-flight code detection skipped: <reason>` once, immediately after the failed/skipped call, before Phase 1 begins - the same emission point as Phase 0's "No tracker configured" notice; output otherwise identical to today's |
| `HEURISTIC_ONLY == true` | step still runs - O(1), not per-ticket; the >20-ticket lever does not apply |

**Evidence cap:** at most 3 entries per ticket, descending PR number, then `(+N more)`.

**Assignment rule.** On a match, set `entry.IN_FLIGHT = true`, append the matching PR to `entry.IN_FLIGHT_EVIDENCE[]` (`{kind: "pr", ref, title, is_draft, url}`), and set `entry.in_progress = true` (see **In-progress detection** in Phase 1 below, which sets the separate `entry.IN_PROGRESS_TRACKER` provenance flag from its own source). This creates **no new category** - it feeds the existing `in_progress` machinery through a second source. Four consumers inherit this assignment unchanged: (1) Phase 3's removal from lane assignment before Rule 2 / Rework isolation - **except** when Rule 1 already deferred the ticket for an unrelated reason first, see the Interaction-with-Rule-1-deferral note below; (2) the Phase 1 story-size preflight, which suppresses size warnings for `in_progress: true` tickets; (3) the Phase 4a In-progress table and kickoff-prompt exclusion, rendered per the Notes-cell composition rule above; (4) `triage_result.in_progress_excluded[]` and the `## Output` count - **except** when Rule 1 already deferred the ticket for an unrelated reason first (same carve-out as (1)): such a ticket is counted only in `deferred[]`, never also in `in_progress_excluded[]` - see the Interaction-with-Rule-1-deferral note below. All four are intended under open-PR evidence.

**Interaction with Rule 1 deferral (binding).** Detection runs before Phase 1, so `entry.IN_FLIGHT` can be set on a ticket that Phase 3 Rule 1 later defers for an unrelated reason (`terminal: true`, an outside-the-set `external_dep`, `fetch_failed: true`, or `cycle_warning: true`). Rule 1 deferred tickets do not reach a Notes cell at all. Rule 1's deferral takes precedence: such a ticket is removed by Rule 1 before the In-progress-removal step ever runs, so it never reaches the In-progress tickets table, Rule 2, or Rework isolation, and Phase 4b item (7)'s Notes-cell obligation does not apply to it - `entry.in_progress` and `entry.IN_FLIGHT` remain set as data, but the only place this surfaces is the `## Deferred tickets` table's Reason-cell extension below.

**Why *remote-ref enumeration* is not evidence.** What is dropped is enumerating `git branch -r`: stale refs persist with `fetch.prune` unset (82 remote-tracking refs vs 76 live heads vs 7 open PRs measured), so a bare ref name is near-noise, and a merged prior-attempt ref would flag every rework ticket. What is **kept** is `headRefName` as a match candidate above - the head branch of an open PR is live by construction, and dropping it would halve recall for no precision gain.

**Disclaimer.** A pushed branch with no PR yet is an accepted false negative. Three false-positive paths remain, all visible via the printed evidence so the operator can dismiss them by hand: a stale *open* PR (abandoned, author departed); a title match on unrelated wording (e.g. a PR titled "revert DS-34 change"); and a dotted-key over-match (`DS-4.1` matches key `DS-4` - dotted keys do not occur in this ticket-numbering convention, so this is accepted).

**Reserved for Unit 2.** A future unit may enrich this same `IN_FLIGHT` flag with additional evidence sources - do not build a third enumerator; extend this one.

`[phase: ticket-triage | phase=inflight-detect]`

## Phase 1: Metadata fetch

Conductor-direct (no subagent). For each entry in `normalized_input.entries[]`, fetch:
- **Jira:** `mcp__mcp-atlassian__jira_get_issue` - capture `priority`, `status`, `story_points` (or `timeestimate`), `labels`, `components`, `assignee`, and `issuelinks` (blocks / is-blocked-by / relates-to).
- **Linear:** `mcp__linear__get_issue` - capture `priority`, `state`, `estimate`, `labels`, `assignee`, and relations (blocks / blocked-by / related).

The captured estimate (`story_points` / `timeestimate` / Linear `estimate`) populates the display-only "Est" column in the Phase 4a per-ticket summary table; no distribution rule consumes it, and estimate-aware lane sizing is a deferred default. Only `story_points` and Linear `estimate` trigger the story-size preflight below - `timeestimate` is Jira's time-tracking field (denominated in seconds), display-only, and is never compared against the preflight threshold.

**Soft-fail per ticket:** on any fetch error, mark `fetch_failed: true` on that entry and proceed. Fetch-failed tickets are treated as independent (no known deps, no known metadata) in all downstream phases.

**Terminal-status detection:** tickets whose status maps to a Done/Cancelled/Won't-do state are marked `terminal: true`. They are added to the deferred set in Phase 3 Rule 1 without further analysis.

**In-progress detection:** tickets whose status maps to an active/started/in-progress workflow state are marked `in_progress: true` and `entry.IN_PROGRESS_TRACKER = true` - the tracker-column provenance flag consumed by the Notes-cell composition rule in In-flight code detection above. They are carried through Phase 2 analysis but removed from lane assignment after Rule 1 (shown badged `[IN PROGRESS]` in the artifact; excluded from kickoff prompts). When `entry.IS_REWORK` is also true (see Ticket-rework detection above), the badge becomes `[IN PROGRESS] [REWORK xN]` in the In-progress tickets table - the only place that ticket's rework signal appears, since in-progress removal happens before Rule 2 and Rework isolation and the ticket never reaches a lane. `in_progress: true` has two independent sources - this tracker-column mapping (`entry.IN_PROGRESS_TRACKER`) and In-flight code detection above (`entry.IN_FLIGHT`, open-PR evidence) - and BOTH are commonly true at once (a developer moves the column and opens a PR in the same workflow). The In-flight section's Notes-cell composition rule renders every combination; it does not assume the two sources are mutually exclusive.

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

**In-progress removal (after Rule 1):** tickets with `in_progress: true` are removed from lane assignment. They appear in the artifact badged `[IN PROGRESS]` (combined as `[IN PROGRESS] [REWORK xN]` when `entry.IS_REWORK` is also true - see the In-progress tickets table below) and are excluded from kickoff prompts. They are NOT deferred and NOT lane-assigned, and they never reach Rule 2 or Rework isolation below.

**Rule 2 - Sequential chains (consume DAG-connected components with edges):**

For every connected component of the DAG that has at least one internal edge, topo-sort its members (blockers first) and assign the chain as a single lane (run as an ordered comma-list `/ds-implement-ticket A, B, C` batch). Non-linear components (multiple paths) are still serialized in topological order. All members of a chained component are consumed by Rule 2 - **including any member separately flagged `entry.IS_REWORK: true`.**

**Why a DAG-connected rework ticket is consumed HERE, not by Rework isolation below.** Rule 2 is the only mechanism in this command that honours an in-set dependency edge at all - Rule 1 defers a ticket only when its blocker is *outside* the set. Isolating a rework ticket before Rule 2 ran would remove it from the DAG-chain pool, silently severing that edge: its blocker (or the ticket it blocks) would then fall through to Rule 3 with zero remaining internal edges and could land in a different, possibly-`parallel` lane - telling the operator to run a blocked ticket concurrently with its own blocker. A chain is not a `parallel` lane, so consuming the rework ticket in its topo-sorted chain here already satisfies the never-parallel mandate without needing to special-case Rule 2 itself. See the Notes-cell rule below for how the dependency edge stays visible in the artifact for this case.

Each chain = one lane slot consumed in the cap accounting. `num_dep_chains` is the count of chains assigned here (referenced by Rule 4 below).

**Rework isolation (after Rule 2, before Rule 3):** every remaining ticket with `entry.IS_REWORK: true` that Rule 2 did **not** already consume above - i.e. it has zero in-set DAG edges, or its only edges point to a ticket that was deferred, in-progress-removed, or otherwise outside the surviving DAG component - is assigned its own single-ticket chain lane here, **never** `parallel`. A rework ticket carries a forced Elevated risk floor and may draw a Tier-3 Skeptic (`content/references/ticket-rework.md` §Escalation table); folding it into a same-lane parallel batch with other tickets would misrepresent its cost as parallel-safe filler. It is neither deferred nor excluded from kickoff - it runs, just never batched with anything else. `num_rework_lanes` is the count of lanes assigned here (referenced by Rule 4 below); each is one lane slot consumed in the cap accounting, same as a Rule 2 chain. `num_chains` (the total Rule 4 uses for cap accounting) = `num_dep_chains + num_rework_lanes`.

**Notes-cell annotation (applies to every `entry.IS_REWORK: true` ticket, regardless of which rule consumed it):** its Notes cell (At-a-glance and Per-ticket summary tables) always carries `rework xN - Elevated floor, may draw Tier-3 Skeptic; verify PR #<n>`, where `N = entry.PRIOR_ATTEMPTS` and `<n> = entry.LATEST_PR`. When Rule 2 consumed the ticket (it is DAG-connected), the Notes cell leads with its in-set blocker/blocked-by relationship first - the same convention Rule 2 already uses for its non-rework chain members (e.g. `blocked by A`) - separated from the rework annotation by `; `, so the dependency edge stays visible in the artifact rather than only implied by lane structure. Example: `blocked by A; rework x2 - Elevated floor, may draw Tier-3 Skeptic; verify PR #458`. When Rework isolation consumed the ticket instead (no in-set edge), the Notes cell carries the rework annotation alone.

**Rule 3 - Parallel grouping (sees only the remainder: tickets with zero internal DAG edges AND `entry.IS_REWORK: false`):**

1. Sort candidates by **priority descending, then ticket_id ascending** (total order; deterministic).
2. For each candidate in that order: place it in the **lowest-index existing lane** that has no conflict with it (conflict = shared conflict group per Phase 2b). If no existing lane is conflict-free AND current lane count < cap: open a new lane. If cap is reached: hold for the overflow step.
3. **Overflow (cap reached, candidate unplaced):** place the candidate in the lane with the fewest conflicts with it; ties broken by lowest lane index. Emit a per-ticket `conflict-warning` entry in the artifact.

**Rule 4 - Cap reconciliation (reorganizes lanes; never reassigns ticket categories):**

Cap = `--lanes N` (default 3).

- If `num_chains > cap`: do NOT merge chains (they are hard dependency units, and a rework-isolated lane is equally never merged into a parallel batch - see Rework isolation above). Report in the artifact:
  - When `num_rework_lanes == 0`: "Dependency structure requires `<num_chains>` sequential lanes, exceeding the cap of `<cap>`. Raise --lanes to `<num_chains>` or accept `<num_chains>` concurrent sessions."
  - When `num_rework_lanes > 0`: "`<num_dep_chains>` dependency chain(s) plus `<num_rework_lanes>` rework-isolated ticket(s) require `<num_chains>` sequential lane(s) total, exceeding the cap of `<cap>`. Raise --lanes to `<num_chains>` or accept `<num_chains>` concurrent sessions." Distinguishing the two counts matters: without it, an operator with several rework tickets and zero real dependency chains would be told "dependency structure" forces the lane count, when the actual cause is the never-parallel mandate.

  Proceed with `num_chains` lanes for chains either way.
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

<!-- Type column: a lane containing a DAG-connected rework ticket (Rule 2 consumed it) is still
     "chain", never "parallel" - see Rule 2's rework-handling note and the Notes-cell rule in
     Phase 3. Lane 4 below illustrates this: G is rework AND blocked by F, so Rule 2 (not
     Rework isolation) assigned the chain, and G's Notes lead with the in-set blocker. -->

| Lane | Tickets | Type | Notes |
|------|---------|------|-------|
| Lane 1 | A, B | chain | B blocked by A |
| Lane 2 | C, D | parallel | independent |
| Lane 3 | E | chain | rework x2 - Elevated floor, may draw Tier-3 Skeptic; verify PR #458 |
| Lane 4 | F, G | chain | G blocked by F; G rework x1 - Elevated floor, may draw Tier-3 Skeptic; verify PR #500 |
| ...   | ...  | ...  | ... |

## Per-ticket summary

<!-- Est column: shows the captured estimate (story points / time estimate) or "-" when absent.
     Display-only; no distribution rule consumes it.
     ⚠ column: populated with "⚠ large" when context_risk: high (≥5 pts); otherwise empty.
     Ticket column: append "[REWORK xN]" when entry.IS_REWORK is true, N = entry.PRIOR_ATTEMPTS
     (see Ticket-rework detection above). Never combined with a `parallel` Lane/Type value - a
     rework ticket's lane always shows Type "chain": its own single-ticket chain (Rework
     isolation) when it has no in-set DAG edge, or the DAG-connected chain Rule 2 already
     assigned it when it does. Its Notes cell always carries the "rework xN - ...; verify PR
     #<n>" annotation; when Rule 2 consumed it (DAG-connected), the Notes cell leads with the
     in-set blocker relationship first, separated by "; " (see G below). -->

| Ticket | Priority | Status | Est | ⚠ | Lane | Notes |
|--------|----------|--------|-----|---|------|-------|
| A | High | To Do | 3 | | Lane 1 | |
| B | Med | To Do | 2 | | Lane 1 | blocked by A |
| C | High | To Do | 8 | ⚠ large | Lane 2 | |
| E [REWORK x2] | High | To Do | 3 | | Lane 3 | rework x2 - Elevated floor, may draw Tier-3 Skeptic; verify PR #458 |
| F | Med | To Do | 2 | | Lane 4 | |
| G [REWORK x1] | Med | To Do | 3 | | Lane 4 | blocked by F; rework x1 - Elevated floor, may draw Tier-3 Skeptic; verify PR #500 |
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

<!-- Reason cell IN_FLIGHT extension: when a Rule-1-deferred ticket also carries entry.IN_FLIGHT:
     true (see the Interaction-with-Rule-1-deferral note in In-flight code detection above),
     append "; in flight: open PR #<n>" (with the "(+N more)" cap, same rendering as the
     in-flight clause in the Notes-cell composition rule) to the Reason cell. This does NOT
     count as an IN_FLIGHT-sourced kickoff exclusion (Phase 4b skip condition / Output item 7
     below) - the ticket was already deferred for its own Rule 1 reason; the PR mention is
     context only, since Rule 1 deferred tickets do not reach a Notes-bearing table. -->

| Ticket | Reason |
|--------|--------|
| X | terminal (Done) |
| Y | external blocker outside set |
| V | terminal (Done); in flight: open PR #440 |

## In-progress tickets

<!-- Ticket column: append "[REWORK xN]" after "[IN PROGRESS]" when entry.IS_REWORK is true - see
     Ticket-rework detection above. This is the ONLY place an in-progress rework ticket's signal
     appears: in-progress removal happens before Rule 2 and Rework isolation, so it never gets a
     lane, a Per-ticket-summary badge, or a Notes-cell annotation elsewhere.
     Notes cell: composed per the Notes-cell composition rule in In-flight code detection above -
     base clause, then an in-flight clause (when entry.IN_FLIGHT, cap-rendered), then a rework
     clause (when entry.IS_REWORK - its wording depends on whether an in-flight clause rendered),
     then the tracker-column qualifier (only when entry.IN_FLIGHT is true AND
     entry.IN_PROGRESS_TRACKER is false - i.e. the tracker column genuinely did not move). The
     rows below cover all six combinations of (tracker-moved, PR-open, rework) that reach this
     table: Z is tracker-only; W is tracker+rework; DS-12 is PR-only (qualifier present); DS-34
     is tracker+PR overlap (qualifier correctly OMITTED - the column DID move); DS-40 is
     PR+rework (qualifier present); DS-41 is tracker+PR+rework (qualifier omitted). -->

| Ticket | Assignee | Notes |
|--------|----------|-------|
| Z [IN PROGRESS] | ... | Excluded from kickoff prompts |
| W [IN PROGRESS] [REWORK x1] | ... | Excluded from kickoff prompts; verify PR #501 once back from in-progress |
| DS-12 [IN PROGRESS] | ... | Excluded from kickoff prompts; in flight: open PR #430 (+1 more); detected from an open PR, not the tracker column |
| DS-34 [IN PROGRESS] | ... | Excluded from kickoff prompts; in flight: open PR #420 |
| DS-40 [IN PROGRESS] [REWORK x1] | ... | Excluded from kickoff prompts; in flight: open PR #421; prior attempt PR #388 - verify both once back from in-progress; detected from an open PR, not the tracker column |
| DS-41 [IN PROGRESS] [REWORK x1] | ... | Excluded from kickoff prompts; in flight: open PR #422; prior attempt PR #390 - verify both once back from in-progress |

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

**Lane 4** (sequential chain, includes a DAG-connected rework ticket - never parallel; verify PR #500 before running):
```
/ds-implement-ticket F, G
```
```

`[phase: ticket-triage | phase=draft]`

## Phase 4b: Skeptic review

**Skip condition:** if the artifact contains zero lanes AND zero chains AND no IN_FLIGHT-sourced exclusions - meaning every entry in `## In-progress tickets` carries `entry.IN_PROGRESS_TRACKER: true` or `entry.IN_FLIGHT: false` (a ticket with both true reached the table via the tracker column regardless, so it is not IN_FLIGHT-sourced; a Rule-1-deferred ticket that also carries `entry.IN_FLIGHT` does NOT count here either - it is annotated in the Deferred tickets table's Reason cell instead, per the Interaction-with-Rule-1-deferral note in In-flight code detection above) - skip Phase 4b entirely and proceed to output.

Otherwise: spawn a fresh background Skeptic on the artifact with this adversarial brief, followed by the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5 - fields 1-4 are `n/a - internal scaffolding artifact review (no code diff, no architect plan/Brief/qa_criteria applies)`; field 5 is the tracker query/source data the artifact was built from; field 6 is the triage artifact's file path):

> "Review this triage artifact. Check: (1) Dependency ordering - are blockers placed before the tickets they block within each chain? (2) Parallel safety - are tickets in the same lane genuinely non-conflicting per the Phase 2b analysis? (3) Deferral justification - is each deferred ticket's reason accurate and not overcautious? (4) Kickoff prompt completeness - does every non-deferred, non-in-progress ticket appear in exactly one lane's kickoff prompt? (5) Cap reconciliation - if Rule 4 fired, was the merge post-pass applied correctly and documented? (6) Rework annotation - was every ticket with `IS_REWORK: true` given the `[REWORK xN]` badge and a Notes-cell annotation naming the prior PR? Is it placed in a chain, never `parallel` - either its own single-ticket rework-isolated chain, or the DAG-connected chain Rule 2 already assigned it, with the in-set blocker relationship preserved first in that case? (7) In-flight provenance - for every ticket reaching the In-progress tickets table (Notes-bearing) with `entry.IN_FLIGHT: true`, does its Notes cell render per the Notes-cell composition rule, correctly OMITTING the tracker-column qualifier whenever `entry.IN_PROGRESS_TRACKER` is also true? For every ticket Rule 1 deferred (no Notes cell in that table) that also carries `entry.IN_FLIGHT: true`, does its Reason cell in `## Deferred tickets` name the causing PR instead - see the Interaction-with-Rule-1-deferral note?"

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
7. **Zero lanes with in-flight exclusions.** When the artifact contains zero lanes AND zero chains AND every non-lane-assigned ticket is an IN_FLIGHT-sourced exclusion as defined in the Phase 4b skip condition above (equivalently: `## Deferred tickets` is empty AND every entry in `## In-progress tickets` carries `entry.IN_PROGRESS_TRACKER: false` AND `entry.IN_FLIGHT: true`) AND at least one such ticket exists, print: `All candidate tickets are already in flight (open PRs: <keys>). No lanes to recommend. Recommended next action: review those PRs before starting new work - or re-invoke with an explicit ticket id to override.` If `## Deferred tickets` is non-empty, or any In-progress ticket carries `entry.IN_PROGRESS_TRACKER: true` or lacks `entry.IN_FLIGHT: true`, use the ordinary one-line summary (item 4) instead - do not claim ALL tickets are in flight when some are not (a terminal-plus-open-PR ticket lands in `## Deferred tickets`, so its presence alone routes here, not to the special print; a ticket with both flags true reached the table via the tracker column regardless of IN_FLIGHT, so it is not IN_FLIGHT-sourced and also routes here). Note the Phase 4b Skeptic does still run in this case, per the extended skip condition.

`[phase: ticket-triage | phase=complete]`

## Composition and non-goals

**Non-goals (this command intentionally does NOT):**
- Invoke `/ds-implement-ticket` or spawn any implementation agent.
- Create branches, PRs, worktrees, or commits.
- Write to `.agentic/batch-state.json`, any loop-state file (the per-ticket `.agentic/loop-state-<LOOP_KEY>.json` as well as the legacy `.agentic/loop-state.json` - the keyed form is a new filename class and this prohibition covers it too), `.agentic/tasks.jsonl`, or any other `.agentic/` state file.
- Mutate tracker tickets (no status transitions, no comment posts).
- Produce Briefs, Plans, or ADRs.
- Perform file-level conflict analysis (directory-level only via the Phase 2b investigator).
- Perform any .agentic/ state read for in-flight detection (no batch-state, loop-state, or tasks.jsonl read - those are gitignored and cannot cross a checkout boundary).

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
| No args, >=2 assigned | Print resolved ticket IDs, then proceed into Ticket-rework detection, In-flight code detection, and Phase 1+ as for an explicit list. |
| Single ticket | Print "run /ds-implement-ticket <id> directly." and exit before Phase 1. |
| All tickets independent (no DAG edges) | Rule 2 is a no-op; all tickets go to Rule 3 parallel grouping. |
| Circular dependency | Break at lowest-confidence link; defer both with `cycle_warning`. Do not abort. |
| Multi-prefix input (Jira + Linear IDs) | Phase 0 normalizes as usual; Phase 1 routes each ID to the correct MCP tool. Conflict analysis treats all tickets uniformly. |
| JQL returns many results | Phase 0's 50-result cap applies first (truncate + warning). Then, on the surviving set: if count >20, the HEURISTIC_ONLY gate fires (Level 1 conflict analysis only; header stamped). Both rules sequence in that order; a 60-result JQL trips both. |
| Terminal-status ticket (Done/Cancelled) | Deferred via Rule 1 with reason "terminal". Not included in lane assignment or kickoff prompts. |
| In-progress ticket | Carried through analysis; removed from lane assignment after Rule 1. Shown badged `[IN PROGRESS]`. Excluded from kickoff prompts. |
| Ticket with an open PR naming its key, tracker column not moved | Badged `[IN PROGRESS]` via In-flight code detection (open-PR evidence); Notes cell states `in flight: open PR #<n>...; detected from an open PR, not the tracker column`. Excluded from kickoff prompts, same as a tracker-sourced in-progress ticket. |
| Ticket with an open PR naming its key, tracker column ALSO moved (both sources true) | Badged `[IN PROGRESS]`; Notes cell renders the in-flight clause WITHOUT the "not the tracker column" qualifier (`entry.IN_PROGRESS_TRACKER` is true) - see the Notes-cell composition rule in In-flight code detection above. |
| Ticket deferred by Rule 1 (terminal / external blocker / fetch-failed / cycle) that also has an open PR naming its key | Appears in `## Deferred tickets` with its normal Rule 1 reason. Reason cell additionally names the open PR (`; in flight: open PR #<n>`, cap-rendered). Does NOT count as an IN_FLIGHT-sourced kickoff exclusion and does NOT reach the In-progress tickets table - see the Interaction-with-Rule-1-deferral note in In-flight code detection above. |
| No tracker configured (with explicit input) | Skip Phase 1; run Phase 2a with zero link data; run Phase 2b Level 1 with zero component/label data; print notice. |
| Ticket with `IS_REWORK: true`, no in-set DAG edge | Badged `[REWORK xN]`. Given its own single-ticket chain lane by Rework isolation (never `parallel`). NOT deferred, NOT excluded from kickoff. Notes cell names the prior PR. Runs identically at `TRACKER=none` - detection is tracker-independent. |
| Ticket with `IS_REWORK: true` AND an in-set DAG edge (blocks or is blocked by another surviving ticket) | Badged `[REWORK xN]`. Consumed by Rule 2, not Rework isolation - stays in its topo-sorted chain (Type `chain`, never `parallel`) so the dependency edge is preserved. Notes cell leads with the in-set blocker relationship, then the rework annotation (e.g. `blocked by F; rework x1 - ...`). |
| Ticket with `IS_REWORK: true` AND `in_progress: true` | In-progress removal runs before Rule 2 and Rework isolation, so the ticket never reaches a lane. Badged `[IN PROGRESS] [REWORK xN]` in the In-progress tickets table only - the sole place this signal appears. Excluded from kickoff prompts, same as any in-progress ticket. |
| `rework_detection` disabled, or ledger absent/unreadable | Detection soft-fails to `PRIOR_ATTEMPTS = 0` for every entry; no badge, no lane-rule effect. Triage proceeds unaffected. |

## Soft-fail discipline

Every tracker and MCP call soft-fails: log and continue. A fetch failure on one ticket never aborts the triage of the remaining set. Fetch-failed tickets are treated as independent with no known metadata. The command never errors out on external API failure. The ticket-rework ledger read (a local file, not a tracker/MCP call) follows the same discipline: an absent or unreadable ledger, or a single malformed line within it, resolves to zero prior attempts for the affected entry(ies) rather than erroring - see Ticket-rework detection above. The In-flight code detection `gh pr list` call (neither a tracker call nor an MCP call) follows the same discipline: `gh` absent, unauthenticated, having no remote, or the call failing all degrade to a total no-op with one notice line - see In-flight code detection above.

Emit one breadcrumb per phase as shown in each section above. The terminal breadcrumb is `[phase: ticket-triage | phase=complete]`.
