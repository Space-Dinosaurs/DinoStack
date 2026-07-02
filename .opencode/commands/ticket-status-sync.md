---
description: /ticket-status-sync
agent: build
---
# /ticket-status-sync
<!--
Purpose: Reconciles a ticket's tracker column with the actual state of its code. Fires the Done
         (or other appropriate) transition that /implement-ticket leaves unfired on the default
         human-merge path (AUTO_MERGE_ON_CI_GREEN=false). --all mode additionally sweeps the whole
         tracker (not just .agentic/tasks.jsonl) for tickets whose work shipped in conductor-led
         sessions outside /implement-ticket, where the tasks.jsonl pass alone can't see them.

Public API: /ticket-status-sync <TICKET_ID>    — reconcile one ticket, prompts before transitioning
            /ticket-status-sync --all           - reconcile every non-terminal ticket in .agentic/tasks.jsonl,
                                                    then sweep the tracker-wide non-terminal ticket set for
                                                    deterministic ID-match evidence (Tier 1, may transition)
                                                    and report unmatched shipped-looking candidates (Tier 2,
                                                    report-only, never transitions)
            /ticket-status-sync --all --force   — same as --all (--force is a no-op in v1, reserved for forward compat)

Upstream deps: .agentic/tasks.jsonl (task state and pr_number/branch fields);
               gh CLI (pr view - state, isDraft, mergeable, reviewDecision; pr list --search / --state merged|open
               for the tracker-wide sweep and the last-100-merged-PRs Tier 2 candidate scan);
               git log --grep (default-branch commit evidence for the tracker-wide sweep);
               AGENTS.md ## Linear / ## Tracker sections (TRACKER resolution chain, same as implement-ticket.md Setup);
               tracker query tools for the non-terminal ticket set (Jira mcp__mcp-atlassian__jira_search JQL;
               Linear mcp__linear__list_issues);
               content/commands/implement-ticket.md ## Tracker Writeback Helper (subagent invocation shape, forward-only guard semantics);
               METHODOLOGY.md (activation preflight).

Downstream consumers: operator-invoked only; no programmatic consumers.

Failure modes: soft-fail throughout — every tracker/gh/git call logs and continues on error; a single
               ticket's reconciliation failure never aborts an --all sweep. The command never errors
               out on an external API failure. Tier 2 (unmatched candidates) never writes anything -
               a Tier 2 false positive is a wrong report line, never a wrong transition.

Performance: one gh CLI call + one tracker-writeback subagent spawn per ticket that requires a transition.
             State-read calls are Tier-1 fast; --all sweeps are proportional to non-terminal ticket count.
             The tracker-wide sweep caps its non-terminal ticket query at 100 (most recently updated);
             a capped run prints how many tickets were skipped rather than truncating silently.
-->

Reconcile a ticket's tracker status (column) with the actual state of its code. Use after `/implement-ticket` exits before merge - the default human-merge flow leaves the final Done transition unfired until a human merges the PR, so the tracker can lag behind reality. This command computes the correct state and pushes the transition. `--all` mode also sweeps the whole tracker so tickets worked outside `/implement-ticket` (conductor-led sessions with no `.agentic/tasks.jsonl` entry) don't silently drift.

## When to use

- After manually merging a PR that `/implement-ticket` opened (the default no-auto-merge flow).
- After a `/implement-ticket` run was interrupted (rate limit, crash) and the ticket is stuck in a stale column.
- As a periodic reconciliation sweep across recent tickets (`--all`).

## Invocation

- `/ticket-status-sync <TICKET_ID>` - reconcile one ticket. Prompts before transitioning.
- `/ticket-status-sync --all` - reconcile every non-terminal ticket in `.agentic/tasks.jsonl`, then sweep the tracker itself for non-terminal tickets outside that file (deterministic ID-match may transition; unmatched candidates are report-only). Transitions without prompting.
- `--force` - reserved future-proofing alias for `--all` confirmation bypass. In v1, `--all` already transitions without prompt, so `--force` is currently a no-op modifier documented for forward compatibility.

## Preflight

Run the activation preflight (see METHODOLOGY.md). If inactive, no-op and exit.

Resolve `TRACKER` and the 5 `TRACKER_STATE_*` values using the SAME resolution chain as `/implement-ticket` Setup (AGENTS.md `## Linear` / `## Tracker` sections). If `TRACKER == none`, print "No tracker configured; nothing to sync." and exit.

## Resolution algorithm (single ticket)

1. **Read task state.** Look up the ticket in `.agentic/tasks.jsonl` (most recent entry for that `ticket_id`). Capture `status` (pending | in_progress | complete | blocked | skipped_already_merged) and `pr_number` / `branch` if recorded. If `.agentic/tasks.jsonl` is absent or has no entry for this ticket, proceed with no task-state: derive PR/branch state directly from `gh` (by ticket-ID-derived branch name or an explicit PR number if the operator supplies one). Task-state is an optimization, not a requirement, for single-ticket mode.
2. **Read PR state.** If a PR number/branch is known: `gh pr view <N> --repo <GH_REPO> --json state,isDraft,mergeable,reviewDecision 2>/dev/null`. Determine: no PR / draft / open-ready / merged / closed.
3. **Read branch state.** `git log origin/<branch> 2>/dev/null` to confirm the branch exists / was deleted (deleted often implies merged).
4. **Compute expected tracker state** using this mapping (same target states as the `/implement-ticket` writeback sites W1-W7):

   | Observed code state | Expected tracker state |
   |---|---|
   | task `blocked` | `$TRACKER_STATE_BLOCKED` |
   | PR merged (or branch deleted after a known PR) | `$TRACKER_STATE_DONE` |
   | PR open + ready, not merged | `$TRACKER_STATE_QA` (in review/QA window) |
   | PR draft | `$TRACKER_STATE_IN_REVIEW` |
   | task `in_progress`, no PR yet | `$TRACKER_STATE_IN_PROGRESS` |
   | task `complete` but no PR found | `$TRACKER_STATE_DONE` (work finished) |
   | task `pending` / unknown | no transition (leave as-is) |

5. **Apply forward-only guard.** Read the ticket's current tracker state. Use the SAME ranking as the Tracker Writeback Helper: Linear `state.type` (`backlog` < `unstarted` < `started` < `completed`; `cancelled` terminal); Jira `statusCategory.key` (`new` < `indeterminate` < `done`; cancellation-semantic categories terminal). If the current rank >= expected rank, or the ticket is in a terminal/cancelled state, skip (no transition). State-read failure - skip silently.
6. **Transition.** If a transition is warranted and (single-ticket mode) the operator confirms at the prompt `"Transition <TICKET_ID> from '<current>' to '<expected>'? [y/N]"`, spawn the tracker-writeback subagent (reuse the `## Tracker Writeback Helper` invocation from `/implement-ticket`: Tier 1, `general-purpose`, `target_state: <expected>`, `forward_only_guard: true`). Soft-fail.

## `--all` mode

If `.agentic/tasks.jsonl` is absent, print "No task state found; nothing to sync." and continue - do NOT exit the whole `--all` invocation on this condition. Only the tasks.jsonl pass itself is skipped; the tracker-wide sweep below still runs whenever `TRACKER != none`.

Iterate every non-terminal ticket in `.agentic/tasks.jsonl` (skip entries whose `status` is a terminal value already reconciled). Run the single-ticket algorithm for each. Transition without prompting. Aggregate counts.

After the tasks.jsonl pass completes, run the tracker-wide sweep below (Tier 1, then Tier 2) as part of the same `--all` invocation.

## Tracker-wide sweep (`--all` mode, Tier 1 - deterministic ID-match, may transition)

Purpose: catch tickets whose work shipped in a conductor-led session outside `/implement-ticket` - no `.agentic/tasks.jsonl` entry exists for them at all, so the tasks.jsonl pass above can't see them, but their ticket key appears in merged commit or PR titles (e.g. DS-48-class: PRs #374/#376/#388 reference the key, the ticket itself never moved off To Do).

**Skip condition.** If `TRACKER == none`, skip this entire sweep (same top-level gate as the rest of the command) - print nothing extra.

1. **Query non-terminal tickets in the configured project.**
   - Jira: `mcp__mcp-atlassian__jira_search` with JQL `project = <TICKET_PREFIX> AND statusCategory != Done`, ordered most-recently-updated first.
   - Linear: `mcp__linear__list_issues` filtered to the team resolved as `TICKET_PREFIX`, excluding state types `completed` and `cancelled`, ordered most-recently-updated first.

   **Cap: 100 most recently updated tickets.** Never truncate silently. If the query returns more than 100 non-terminal tickets, take the 100 most recently updated and print: `[ticket-status-sync] tracker-wide sweep capped at 100 most-recently-updated tickets; N older tickets skipped this run.`

2. **Exclude already-reconciled tickets.** Drop any ticket key that was already processed by the tasks.jsonl pass above (its `ticket_id` appears in `.agentic/tasks.jsonl`) - that pass already evaluated it (transitioned or correctly left alone); re-evaluating it here is redundant, not wrong, but is skipped to keep the sweep focused on what the tasks.jsonl pass structurally cannot see.

3. **Gather deterministic evidence per remaining ticket key `<KEY>`:**
   - `git log --grep "<KEY>" --oneline` on `BASE_BRANCH`.
   - `gh pr list --repo <GH_REPO> --state merged --search "<KEY>" --json number,title,mergedAt`.
   - `gh pr list --repo <GH_REPO> --state open --search "<KEY>"`.

   Each call soft-fails independently: a failure for one ticket's evidence gathering logs and moves to the next ticket; it never aborts the sweep.

4. **Zero evidence found** (no commits, no merged PRs, no open PRs reference `<KEY>`): do NOT transition. This ticket flows into the Tier 2 unmatched-candidates pass below instead. Tier 1 only ever acts on positive ID-match evidence.

5. **Evidence found - compute target state.** Do NOT invent a new state machine here. Feed the gathered evidence into the SAME "Resolution algorithm (single ticket)" mapping table above (step 4): a merged PR referencing `<KEY>` (and no open PR still referencing it) maps to the "PR merged" row -> `$TRACKER_STATE_DONE`; an open PR referencing `<KEY>` maps to "PR open + ready" or "PR draft" per its `isDraft`/`reviewDecision` -> `$TRACKER_STATE_QA` / `$TRACKER_STATE_IN_REVIEW`; commits referencing `<KEY>` on `BASE_BRANCH` with no PR record at all (a direct conductor commit) map to the "task complete but no PR found" row -> `$TRACKER_STATE_DONE`.

6. **Apply forward-only guard, then transition.** Identical to single-ticket steps 5-6: read the ticket's current tracker state, apply the same rank comparison (Linear `state.type` ranking / Jira `statusCategory.key` ranking), skip if current rank >= target rank or the ticket is terminal/cancelled. If a transition is warranted, spawn the tracker-writeback subagent (reuse `## Tracker Writeback Helper` from `implement-ticket.md`: Tier 1, `general-purpose`, `target_state: <expected>`, `forward_only_guard: true`). Soft-fail: a spawn or API failure logs and moves to the next ticket.

7. **Evidence comment (only when the transition succeeded).** Post a comment on the ticket citing the deterministic evidence - PR number(s) and merge commit SHA(s) - e.g. `Reconciled by /ticket-status-sync: shipped in PR #388, commit db2fc08.` Use `mcp__linear__save_comment` (Linear) or `mcp__mcp-atlassian__jira_add_comment` (Jira), the same tools the Tracker Writeback Helper already uses elsewhere. List every referencing PR if more than one. **Gate the comment on the Writeback Helper reporting the transition applied.** If the forward-only guard skipped the transition, or the transition failed, do NOT post a comment - a repeatedly soft-failing transition would otherwise re-post the same comment on every `--all` run. A failed comment call (on an otherwise-successful transition) logs and continues independently - it never rolls back or retries the transition.

8. **Operator-visible line per transition attempt (mandatory, never silent - unconditional regardless of comment outcome):**

       [ticket-status-sync] <KEY>: '<current>' -> '<expected>' (evidence: PR #<N> merged @<sha>) - transitioned
       [ticket-status-sync] <KEY>: '<current>' -> '<expected>' (evidence: PR #<N> merged @<sha>) - FAILED: <error>

## Unmatched candidates (`--all` mode, Tier 2 - report-only, NEVER transitions)

Runs immediately after the Tier 1 sweep, over the non-terminal ticket set gathered in Tier 1 step 1 (post-cap, post-exclusion) minus every ticket Tier 1 found ID-match evidence for. These are tickets with ZERO ID-match evidence anywhere in git history or PR search results - e.g. a ticket filed retroactively for work that already shipped before the ticket existed, so its key never appears in git history at all (DS-53-class: PR #338 merged 5 days before the ticket was created).

**Absolute rule: Tier 2 never writes.** No tracker transition, no evidence comment, no state mutation of any kind, ever. Report-only.

1. Fetch the last 100 merged PRs in one call: `gh pr list --repo <GH_REPO> --state merged --limit 100 --json number,title,mergedAt`.
2. For each Tier 2 candidate ticket, compare its tracker summary/title against the fetched PR titles using judgment (semantic similarity, not just substring match - e.g. ticket "Tracker status drift" plausibly matches PR "fix(tracker): status drift correction"). This is a best-effort judgment call, not a deterministic algorithm; false positives are acceptable because Tier 2 never writes anything.
3. For each plausible match, print exactly one report-only line and take no other action:

       candidate: <KEY> looks shipped in PR #<N> - confirm and run /ticket-status-sync <KEY>, or close manually

4. Tickets with no plausible match print nothing - Tier 2 output is opt-in signal, not an exhaustive audit list.

## Soft-fail discipline

Every tracker/gh/git call soft-fails: log and continue. A single ticket's reconciliation failure does not abort an `--all` sweep, and applies equally to the tasks.jsonl pass and the tracker-wide sweep (Tier 1 and Tier 2). The command never errors out on an external API failure.

## Output

Emit one breadcrumb per pass: `[phase: ticket-status-sync | mode=<single|all> | transitions=<N> | skipped=<N>]` for the single-ticket / tasks.jsonl-pass counts, and, when the tracker-wide sweep ran, a second breadcrumb: `[phase: ticket-status-sync | mode=all | pass=tracker-sweep | transitions=<N> | skipped=<N> | capped=<N> | candidates=<N>]`.

In single-ticket mode, print the before/after state. In `--all` mode, print a one-line-per-ticket summary table for the tasks.jsonl pass, then the Tier 1 operator-visible transition lines, then the Tier 2 candidate lines (if any).
