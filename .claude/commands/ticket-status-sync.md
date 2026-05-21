> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /ticket-status-sync

> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

<!--
Purpose: Reconciles a ticket's tracker column with the actual state of its code. Fires the Done
         (or other appropriate) transition that /implement-ticket leaves unfired on the default
         human-merge path (AUTO_MERGE_ON_CI_GREEN=false).

Public API: /ticket-status-sync <TICKET_ID>    — reconcile one ticket, prompts before transitioning
            /ticket-status-sync --all           — reconcile every non-terminal ticket in .agentic/tasks.jsonl
            /ticket-status-sync --all --force   — same as --all (--force is a no-op in v1, reserved for forward compat)

Upstream deps: .agentic/tasks.jsonl (task state and pr_number/branch fields);
               gh CLI (pr view — state, isDraft, mergeable, reviewDecision);
               AGENTS.md ## Linear / ## Tracker sections (TRACKER resolution chain, same as implement-ticket.md Setup);
               content/commands/implement-ticket.md ## Tracker Writeback Helper (subagent invocation shape, forward-only guard semantics);
               METHODOLOGY.md (activation preflight).

Downstream consumers: operator-invoked only; no programmatic consumers.

Failure modes: soft-fail throughout — every tracker/gh/git call logs and continues on error; a single
               ticket's reconciliation failure never aborts an --all sweep. The command never errors
               out on an external API failure.

Performance: one gh CLI call + one tracker-writeback subagent spawn per ticket that requires a transition.
             State-read calls are Tier-1 fast; --all sweeps are proportional to non-terminal ticket count.
-->

Reconcile a ticket's tracker status (column) with the actual state of its code. Use after `/implement-ticket` exits before merge - the default human-merge flow leaves the final Done transition unfired until a human merges the PR, so the tracker can lag behind reality. This command computes the correct state and pushes the transition.

## When to use

- After manually merging a PR that `/implement-ticket` opened (the default no-auto-merge flow).
- After a `/implement-ticket` run was interrupted (rate limit, crash) and the ticket is stuck in a stale column.
- As a periodic reconciliation sweep across recent tickets (`--all`).

## Invocation

- `/ticket-status-sync <TICKET_ID>` - reconcile one ticket. Prompts before transitioning.
- `/ticket-status-sync --all` - reconcile every non-terminal ticket in `.agentic/tasks.jsonl`. Transitions without prompting.
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

If `.agentic/tasks.jsonl` is absent, print "No task state found; nothing to sync." and exit cleanly (soft-success, not an error).

Iterate every non-terminal ticket in `.agentic/tasks.jsonl` (skip entries whose `status` is a terminal value already reconciled). Run the single-ticket algorithm for each. Transition without prompting. Aggregate counts.

## Soft-fail discipline

Every tracker/gh/git call soft-fails: log and continue. A single ticket's reconciliation failure does not abort an `--all` sweep. The command never errors out on an external API failure.

## Output

Emit one breadcrumb: `[phase: ticket-status-sync | mode=<single|all> | transitions=<N> | skipped=<N>]`

In single-ticket mode, print the before/after state. In `--all` mode, print a one-line-per-ticket summary table.
