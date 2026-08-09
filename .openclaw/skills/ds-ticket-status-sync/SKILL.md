---
name: ds-ticket-status-sync
description: "Purpose: Reconciles a ticket's tracker column with the actual state of its code. Fires the Done"
user-invocable: true
---
# /ds-ticket-status-sync
<!--
Purpose: Reconciles a ticket's tracker column with the actual state of its code. Fires the Done
         (or other appropriate) transition that /ds-implement-ticket leaves unfired on the default
         human-merge path (AUTO_MERGE_ON_CI_GREEN=false). --all mode additionally sweeps the whole
         tracker (not just .agentic/tasks.jsonl) for tickets whose work shipped in conductor-led
         sessions outside /ds-implement-ticket, where the tasks.jsonl pass alone can't see them.

Public API: /ds-ticket-status-sync <TICKET_ID>    — reconcile one ticket, prompts before transitioning
            /ds-ticket-status-sync --all           - reconcile every non-terminal ticket in .agentic/tasks.jsonl,
                                                    then sweep the tracker-wide non-terminal ticket set for
                                                    deterministic ID-match evidence (Tier 1, may transition)
                                                    and report unmatched shipped-looking candidates (Tier 2,
                                                    report-only, never transitions)
            /ds-ticket-status-sync --all --force   — same as --all (--force is a no-op in v1, reserved for forward compat)
            /ds-ticket-status-sync --pending-merge — reconcile only tickets whose recorded PR (from
                                                    .agentic/ticket-ledger.jsonl) has since merged; transitions
                                                    without prompting; identity is pr_number-only, never a
                                                    title/branch text match

Upstream deps: .agentic/tasks.jsonl (task state and pr_number/branch fields);
               gh CLI (pr view - state, isDraft, mergeable, reviewDecision; pr list --search / --state merged|open
               for the tracker-wide sweep and the last-100-merged-PRs Tier 2 candidate scan);
               git log --grep (default-branch commit evidence for the tracker-wide sweep);
               AGENTS.md ## Linear / ## Tracker sections plus the .agentic/tracker.yml local overlay
               (TRACKER resolution chain, same as implement-ticket.md Setup);
               tracker query tools for the non-terminal ticket set (Jira mcp__mcp-atlassian__jira_search JQL;
               Linear mcp__linear__list_issues);
               content/references/tracker-writeback.md ## Tracker Writeback Helper (subagent invocation shape incl. tracker_state_values, diagnostic_enabled, linear_team_key, pipeline_order; forward-only guard incl. same-category pipeline sub-rank; no dependency on .agentic/tracker-states.json);
               METHODOLOGY.md (activation preflight);
               .agentic/ticket-ledger.jsonl (read-only; sole identity source for --pending-merge - see
               content/references/ticket-rework.md § pr_number as the sole identity key);
               .agentic/.pending-merge-last-sweep (60-minute throttle cursor for --pending-merge);
               .agentic/pending-merge-state.jsonl (per-(ticket_id, pr_number) terminal/non-terminal
               record for --pending-merge);
               .agentic/config.json key pending_merge_sweep (boolean toggle gating --pending-merge);
               .agentic/config.json key tracker_state_diagnostic (boolean toggle gating the writeback
               subagent's diagnostic-enrichment sub-step, read in Preflight).

Downstream consumers: single-ticket and --all modes remain operator-invoked only; no programmatic consumers.
                      --pending-merge is additionally auto-invoked at session start by the conductor - see
                      content/rules/conventions.md § Session Context and Memory - and remains
                      operator-invokable on demand.

Failure modes: soft-fail throughout — every tracker/gh/git call logs and continues on error; a single
               ticket's reconciliation failure never aborts an --all sweep. The command never errors
               out on an external API failure. Tier 2 (unmatched candidates) never writes anything -
               a Tier 2 false positive is a wrong report line, never a wrong transition. For
               --pending-merge: a confirmation-call or reconcile-call error leaves the (ticket_id,
               pr_number) pair non-terminal in .agentic/pending-merge-state.jsonl with `attempts`
               incremented; 3 accumulated failures terminate the pair as `abandoned` (operator must
               retry manually via single-ticket mode). The 60-minute cursor
               (.agentic/.pending-merge-last-sweep) advances unconditionally at the end of every sweep
               that ran, regardless of any per-candidate failure - no failure mode pins the sweep itself.

Performance: one gh CLI call + one tracker-writeback subagent spawn per ticket that requires a transition.
             State-read calls are Tier-1 fast; --all sweeps are proportional to non-terminal ticket count.
             The tracker-wide sweep caps its non-terminal ticket query at 100 (most recently updated);
             a capped run prints how many tickets were skipped rather than truncating silently.
             --pending-merge: at most one sweep per 60 minutes (cursor-throttled); at most 20 candidates
             per sweep (older excess reported, never silently dropped); one `gh pr view` call per
             candidate, plus one `gh pr list --search` open-PR check but only for candidates confirmed
             merged; a tracker pre-read plus at most one writeback spawn only for candidates confirmed
             merged and unblocked by an open PR. Zero cost when .agentic/ticket-ledger.jsonl is absent
             or every recorded pair is already terminal.
-->

Reconcile a ticket's tracker status (column) with the actual state of its code. Use after `/ds-implement-ticket` exits before merge - the default human-merge flow leaves the final dev-complete transition unfired until a human merges the PR, so the tracker can lag behind reality. This command computes the correct state and pushes the transition. `--all` mode also sweeps the whole tracker so tickets worked outside `/ds-implement-ticket` (conductor-led sessions with no `.agentic/tasks.jsonl` entry) don't silently drift.

## When to use

- After manually merging a PR that `/ds-implement-ticket` opened (the default no-auto-merge flow).
- After a `/ds-implement-ticket` run was interrupted (rate limit, crash) and the ticket is stuck in a stale column.
- As a periodic reconciliation sweep across recent tickets (`--all`).

## Invocation

- `/ds-ticket-status-sync <TICKET_ID>` - reconcile one ticket. Prompts before transitioning.
- `/ds-ticket-status-sync --all` - reconcile every non-terminal ticket in `.agentic/tasks.jsonl`, then sweep the tracker itself for non-terminal tickets outside that file (deterministic ID-match may transition; unmatched candidates are report-only). Transitions without prompting.
- `--force` - reserved future-proofing alias for `--all` confirmation bypass. In v1, `--all` already transitions without prompt, so `--force` is currently a no-op modifier documented for forward compatibility.
- `/ds-ticket-status-sync --pending-merge` - reconcile only tickets whose PR was recorded in `.agentic/ticket-ledger.jsonl` and has since merged. Transitions without prompting. Auto-invoked at session start by the conductor (see `content/rules/conventions.md` § Session Context and Memory); also operator-invokable at any time. See `## Pending-merge sweep (--pending-merge mode)` below.

## Preflight

Run the activation preflight (see METHODOLOGY.md). If inactive, no-op and exit.

Resolve `TRACKER` and the 6 `TRACKER_STATE_*` values using the SAME resolution chain as `/ds-implement-ticket` Setup (AGENTS.md `## Linear` / `## Tracker` sections, plus the `.agentic/tracker.yml` local overlay). If `TRACKER == none`, print "No tracker configured; nothing to sync." and exit. When `_source` is `overlay` or `merged`, print a `Tracker config source:` line the same way as `/ds-implement-ticket` Setup.

Additionally resolve `TRACKER_STATE_DIAGNOSTIC` using the same Setup field as `/ds-implement-ticket`
(`.agentic/config.json` key `tracker_state_diagnostic`, default `true`).

Additionally resolve `TRACKER_PIPELINE_ORDER` from the same `AGENTS.md` fields as `/ds-implement-ticket` Setup (`JIRA_PIPELINE_ORDER` / `Pipeline order:`, default `IN_PROGRESS, IN_REVIEW, QA`).

## Resolution algorithm (single ticket)

1. **Read task state.** Apply the **task-state fold** (`content/references/task-state-file.md`) to `.agentic/tasks.jsonl` and read the folded record for that `ticket_id` - never the most recent raw line, which can be a rejected or superseded transition under the fold. Capture `status` (pending | in_progress | done | failed | blocked | abandoned - the `tasks.jsonl` **writer** enum per `content/commands/ds-implement-ticket.md`, distinct from `batch-state.json`'s `tickets[]` enum) and `pr_number` / `branch` if recorded. If `.agentic/tasks.jsonl` is absent or the fold has no record for this ticket, proceed with no task-state: derive PR/branch state directly from `gh` (by ticket-ID-derived branch name or an explicit PR number if the operator supplies one). Task-state is an optimization, not a requirement, for single-ticket mode.
2. **Read PR state.** If a PR number/branch is known: `gh pr view <N> --repo <GH_REPO> --json state,isDraft,mergeable,reviewDecision 2>/dev/null`. Determine: no PR / draft / open-ready / merged / closed.
3. **Read branch state.** `git log origin/<branch> 2>/dev/null` to confirm the branch exists / was deleted (deleted often implies merged).
4. **Compute expected tracker state** using this mapping (same target states as the `/ds-implement-ticket` writeback sites W1-W7):

   | Observed code state | Expected tracker state |
   |---|---|
   | task `blocked` | `$TRACKER_STATE_BLOCKED` |
   | PR merged (or branch deleted after a known PR) | `$TRACKER_STATE_DEV_COMPLETE` |
   | PR open + ready, not merged | `$TRACKER_STATE_QA` (in review/QA window) |
   | PR draft | `$TRACKER_STATE_IN_REVIEW` |
   | task `in_progress`, no PR yet | `$TRACKER_STATE_IN_PROGRESS` |
   | task `done` but no PR found | `$TRACKER_STATE_DEV_COMPLETE` (work finished) |
   | task `pending` / unknown | no transition (leave as-is) |

5. **Apply forward-only guard.** Read the ticket's current tracker state (name AND category - both are required). **Do not restate or approximate the ranking rule here.** Read `content/references/tracker-writeback.md` `## Tracker Writeback Helper` -> "Subagent responsibilities" steps 1-5 in full and apply that algorithm exactly, including the same-category pipeline sub-rank and the Blocked always-permitted exception in both directions. This command already resolves all 6 `TRACKER_STATE_*` values in Preflight - pass them as `tracker_state_values` the same way the Tracker Writeback Helper does. State-read failure - skip silently.
6. **Transition.** If a transition is warranted and (single-ticket mode) the operator confirms at the prompt `"Transition <TICKET_ID> from '<current>' to '<expected>'? [y/N]"`, spawn the tracker-writeback subagent using the `## Tracker Writeback Helper` invocation contract in `content/references/tracker-writeback.md` verbatim - read that contract, do not re-enumerate its parameters here beyond the following call-site-specific values: `target_state: <expected>`, `forward_only_guard: true`, `tracker_state_values` (the 6 values resolved in Preflight), `diagnostic_enabled` (`$TRACKER_STATE_DIAGNOSTIC` resolved in Preflight), `linear_team_key` (Linear only, `$TICKET_PREFIX`), and `pipeline_order` (`$TRACKER_PIPELINE_ORDER` resolved in Preflight). Soft-fail. Additionally, if the guard returns `unmatched_state_name` for this ticket, print the aggregate line (see Output section) - in single-ticket mode the "aggregate" is exactly this one ticket.

## `--all` mode

If `.agentic/tasks.jsonl` is absent, print "No task state found; nothing to sync." and continue - do NOT exit the whole `--all` invocation on this condition. Only the tasks.jsonl pass itself is skipped; the tracker-wide sweep below still runs whenever `TRACKER != none`.

Apply the **task-state fold** to `.agentic/tasks.jsonl` and iterate every non-terminal ticket over the **folded records** (skip entries whose folded `status` is already in the **sync-terminal** set - `{done, failed, blocked, abandoned}`, the full writer terminal set per `content/commands/ds-implement-ticket.md` - not just `{done}`; a `{done}`-only reading would re-reconcile every `abandoned` or `failed` task on every run, forever. This is a distinct set from the fold's own **fold-absorbing** set `{done}`, which governs whether a status can be regressed, not whether `--all` re-sweeps it). Run the single-ticket algorithm for each. Transition without prompting. Aggregate counts.

After the tasks.jsonl pass completes, run the tracker-wide sweep below (Tier 1, then Tier 2) as part of the same `--all` invocation.

## Tracker-wide sweep (`--all` mode, Tier 1 - deterministic ID-match, may transition)

Purpose: catch tickets whose work shipped in a conductor-led session outside `/ds-implement-ticket` - no `.agentic/tasks.jsonl` entry exists for them at all, so the tasks.jsonl pass above can't see them, but their ticket key appears in merged commit or PR titles (e.g. DS-48-class: PRs #374/#376/#388 reference the key, the ticket itself never moved off To Do).

**Skip condition.** If `TRACKER == none`, skip this entire sweep (same top-level gate as the rest of the command) - print nothing extra.

1. **Query non-terminal tickets in the configured project.**
   - Jira: `mcp__mcp-atlassian__jira_search` with JQL `project = <TICKET_PREFIX> AND statusCategory != Done`, ordered most-recently-updated first.
   - Linear: `mcp__linear__list_issues` filtered to the team resolved as `TICKET_PREFIX`, excluding state types completed, canceled, and duplicate, ordered most-recently-updated first.

   **Cap: 100 most recently updated tickets.** Never truncate silently. If the query returns more than 100 non-terminal tickets, take the 100 most recently updated and print: `[ticket-status-sync] tracker-wide sweep capped at 100 most-recently-updated tickets; N older tickets skipped this run.`

2. **Exclude already-reconciled tickets.** Drop any ticket key that was already processed by the tasks.jsonl pass above (its `ticket_id` appears in the **folded** record set from that pass) - that pass already evaluated it (transitioned or correctly left alone); re-evaluating it here is redundant, not wrong, but is skipped to keep the sweep focused on what the tasks.jsonl pass structurally cannot see.

3. **Gather deterministic evidence per remaining ticket key `<KEY>`:**
   - `git log --grep "<KEY>" --oneline` on `BASE_BRANCH`.
   - `gh pr list --repo <GH_REPO> --state merged --search "<KEY>" --json number,title,mergedAt`.
   - `gh pr list --repo <GH_REPO> --state open --search "<KEY>"`.

   Each call soft-fails independently: a failure for one ticket's evidence gathering logs and moves to the next ticket; it never aborts the sweep.

4. **Zero evidence found** (no commits, no merged PRs, no open PRs reference `<KEY>`): do NOT transition. This ticket flows into the Tier 2 unmatched-candidates pass below instead. Tier 1 only ever acts on positive ID-match evidence.

5. **Evidence found - compute target state.** Do NOT invent a new state machine here. Feed the gathered evidence into the SAME "Resolution algorithm (single ticket)" mapping table above (step 4): a merged PR referencing `<KEY>` (and no open PR still referencing it) maps to the "PR merged" row -> `$TRACKER_STATE_DEV_COMPLETE`; an open PR referencing `<KEY>` maps to "PR open + ready" or "PR draft" per its `isDraft`/`reviewDecision` -> `$TRACKER_STATE_QA` / `$TRACKER_STATE_IN_REVIEW`; commits referencing `<KEY>` on `BASE_BRANCH` with no PR record at all (a direct conductor commit) map to the "task done but no PR found" row -> `$TRACKER_STATE_DEV_COMPLETE`.

6. **Apply forward-only guard, then transition.** Identical to single-ticket steps 5-6: read the ticket's current tracker state and apply the SAME algorithm - do not restate it here, read `content/references/tracker-writeback.md` `## Tracker Writeback Helper`. If a transition is warranted, spawn the tracker-writeback subagent using the `## Tracker Writeback Helper` invocation contract in `content/references/tracker-writeback.md` verbatim - read that contract, do not re-enumerate its parameters here beyond the following call-site-specific values: `target_state: <expected>`, `forward_only_guard: true`, `tracker_state_values` (the 6 values resolved in Preflight), `diagnostic_enabled` (`$TRACKER_STATE_DIAGNOSTIC` resolved in Preflight), `linear_team_key` (Linear only, `$TICKET_PREFIX`), and `pipeline_order` (`$TRACKER_PIPELINE_ORDER` resolved in Preflight). Soft-fail: a spawn or API failure logs and moves to the next ticket. Additionally, accumulate any `unmatched_state_name` returned by the guard across this sweep; if the tally is non-empty at the end of the `--all` pass, print ONE aggregate line (see Output section) instead of one line per ticket.

7. **Evidence comment (only when the transition succeeded).** Post a comment on the ticket citing the deterministic evidence - PR number(s) and merge commit SHA(s) - e.g. `Reconciled by /ds-ticket-status-sync: shipped in PR #388, commit db2fc08.` Use `mcp__linear__save_comment` (Linear) or `mcp__mcp-atlassian__jira_add_comment` (Jira), the same tools the Tracker Writeback Helper already uses elsewhere. List every referencing PR if more than one. **Gate the comment on the Writeback Helper's return payload having `transitioned: true`.** If the forward-only guard skipped the transition, the transition failed, or `status == "skipped_unconfigured_state"`, do NOT post a comment - a repeatedly non-transitioning attempt would otherwise re-post the same comment on every `--all` run. A failed comment call (on an otherwise-successful transition) logs and continues independently - it never rolls back or retries the transition.

8. **Operator-visible line per transition attempt (mandatory, never silent - unconditional regardless of comment outcome):**

       [ticket-status-sync] <KEY>: '<current>' -> '<expected>' (evidence: PR #<N> merged @<sha>) - transitioned
       [ticket-status-sync] <KEY>: '<current>' -> '<expected>' (evidence: PR #<N> merged @<sha>) - FAILED: <error>
       [ticket-status-sync] <KEY>: '<current>' -> '<expected>' - SKIPPED: <diagnostic>

## Unmatched candidates (`--all` mode, Tier 2 - report-only, NEVER transitions)

Runs immediately after the Tier 1 sweep, over the non-terminal ticket set gathered in Tier 1 step 1 (post-cap, post-exclusion) minus every ticket Tier 1 found ID-match evidence for. These are tickets with ZERO ID-match evidence anywhere in git history or PR search results - e.g. a ticket filed retroactively for work that already shipped before the ticket existed, so its key never appears in git history at all (DS-53-class: PR #338 merged 5 days before the ticket was created).

**Absolute rule: Tier 2 never writes.** No tracker transition, no evidence comment, no state mutation of any kind, ever. Report-only.

1. Fetch the last 100 merged PRs in one call: `gh pr list --repo <GH_REPO> --state merged --limit 100 --json number,title,mergedAt`.
2. For each Tier 2 candidate ticket, compare its tracker summary/title against the fetched PR titles using judgment (semantic similarity, not just substring match - e.g. ticket "Tracker status drift" plausibly matches PR "fix(tracker): status drift correction"). This is a best-effort judgment call, not a deterministic algorithm; false positives are acceptable because Tier 2 never writes anything.
3. For each plausible match, print exactly one report-only line and take no other action:

       candidate: <KEY> looks shipped in PR #<N> - confirm and run /ds-ticket-status-sync <KEY>, or close manually

4. Tickets with no plausible match print nothing - Tier 2 output is opt-in signal, not an exhaustive audit list.

## Pending-merge sweep (--pending-merge mode)

Purpose: close the gap `/ds-implement-ticket` leaves on the default human-merge path. That command writes a ticket to its dev-complete state (`$TRACKER_STATE_DEV_COMPLETE`) only via its Phase 9 auto-merge branch; with `AUTO_MERGE_ON_CI_GREEN=false` (the default), a ticket parks at QA until something reconciles it. This mode reconciles it automatically at session start, on a strict identity rule.

**Why the ledger is the identity source and a text/title match is not.** An earlier design discovered ticket keys by regex-matching merged PR titles and branch names. That was rejected on verified counterexamples: a docs PR can mention several ticket keys it does not implement (a survey/index PR listing DS-71/DS-69/DS-52 while implementing none of them); one ticket can span several merged PRs, so the first to merge would close it with the rest of its work unwritten; and a PR can self-declare partial completion in its own title. The dev-complete state sits at the top of the forward-only guard's ranking (see step 5 below), so the guard *permits* every one of those wrong transitions, and it equally forbids an automatic move back once wrongly applied - each wrong dev-complete becomes a manual operator repair in the tracker. **A dev-complete transition for ticket `<KEY>` may be driven ONLY by a `pr_number` recorded against `<KEY>` in `.agentic/ticket-ledger.jsonl`.** A ticket key appearing in a PR title, branch name, or commit message is never sufficient on its own here, and no future edit to this section may add title or `headRefName` extraction as even a corroborating signal. This is sound because the ledger's Phase 9 write derives `pr_number` live from the in-flight branch and skips the write entirely when that derivation yields nothing (`content/commands/ds-implement-ticket.md` § Ticket-rework ledger write) - every ledger record therefore carries a real PR number for a real ticket, never an inferred one.

**a. Skip conditions.** These conditions govern the automatic session-start invocation specifically (see `content/rules/conventions.md` § Session Context and Memory), where the sweep is expected to be silent unless it has a transition to report. Any one of the following skips the entire sweep silently (no output) on that path: `TRACKER == none`; the `pending_merge_sweep` config toggle is `false`; less than 60 minutes have elapsed since the timestamp recorded in `.agentic/.pending-merge-last-sweep` (file absent = never skipped on this ground); `.agentic/ticket-ledger.jsonl` is absent or unreadable; the candidate set is empty after the exclusions in (b). A direct operator invocation of `/ds-ticket-status-sync --pending-merge` still runs `## Preflight` above first, so `TRACKER == none` prints "No tracker configured; nothing to sync." and exits rather than skipping silently - the silent form of that specific condition applies only to the automatic path.

**b. Candidate set.** Read `.agentic/ticket-ledger.jsonl` line by line, treating each line as `fromjson? // empty` so a malformed line is skipped rather than aborting the read (same discipline as the ledger read in `content/commands/ds-implement-ticket.md` § Ticket-rework ledger read). Take every record with a non-null `pr_number`. Dedupe to distinct `(ticket_id, pr_number)` pairs. Exclude any pair whose latest entry in `.agentic/pending-merge-state.jsonl` (see (g)) is terminal. Order the remainder by `opened_ts` descending and cap at 20.

**Never truncate silently.** When the eligible set exceeds 20, print one line naming how many older pairs were cut off this sweep:

    [ticket-status-sync] pending-merge sweep capped at 20 candidates; N older pair(s) skipped this run.

Without this line, a project with more than 20 permanently non-terminal pairs would starve the oldest ones - never re-examined, never terminalized, and invisible, since `blocked_by_open_pr` in the breadcrumb (see (j)) only counts what was actually examined this sweep.

**c. Merge-state confirmation.** For each candidate `(ticket_id, pr_number)`: `gh pr view <pr_number> --repo <GH_REPO> --json number,state,mergedAt`. Three outcomes:

   - `MERGED` - proceed to (d).
   - `CLOSED` (not merged) - **terminal**. Record `closed_unmerged` per (g); no transition.
   - `OPEN` - non-terminal this sweep. No state record is written; no further calls for this candidate this sweep.

**d. Open-PR block.** Before mapping a merged candidate to the dev-complete state, run `gh pr list --repo <GH_REPO> --state open --search "<TICKET_ID>"`. If **any** open PR matches, do **not** transition and do **not** record a terminal state - the ticket has a *concurrently open* sibling PR in flight (a merged first PR with at least one still-open, already-opened sibling). The candidate is deferred to a later sweep, untouched. This block only sees siblings that exist as open PRs at sweep time; it does not detect a multi-PR ticket whose later PRs have not been opened yet - see "Known limitations" below.

This search is a **blocking** signal, so a spurious match costs a deferred transition (safe) and a missed match costs a premature Done (unsafe) - therefore treat an **error** on this call as "blocked" (do not transition), not as "clear."

GitHub's `--search` matches title and body case-insensitively, so the uppercase ticket key matches regardless of branch-name casing. No regex is applied to `headRefName` anywhere in this mode - see the identity-source rule above.

**e. Relationship to Tier 1 - not evidence-shape equivalent.** Tier 1 (`## Tracker-wide sweep`) gathers three calls (commits, merged-PR search, open-PR search) and conditions its Done mapping on the open-PR result. This mode uses a **different identity source** - a recorded `pr_number` rather than a text search - and **retains** Tier 1's open-PR precondition unchanged. It does not "mirror Tier 1 narrowed to one call"; the identity mechanism is different, only the open-PR precondition is shared.

**f. Reconcile.** For a candidate confirmed merged and unblocked by (d), run steps 4-5 of "Resolution algorithm (single ticket)" above (landing on the PR-merged row -> `$TRACKER_STATE_DEV_COMPLETE`, applying the forward-only guard by reference per step 5), then spawn per step 6.

**No prompting.** `--pending-merge` transitions without prompting, exactly as `--all` does. The `[y/N]` confirmation in step 6 of "Resolution algorithm (single ticket)" is scoped to single-ticket mode and MUST NOT be inherited here - a session-start sweep that blocked on a prompt would block session boot.

**g. Record the determination.** Append one line to `.agentic/pending-merge-state.jsonl` (single `O_APPEND` write per line; read with latest-wins dedupe on `(ticket_id, pr_number)` ordered by `ts` - same contract as `content/references/ticket-rework.md` § Concurrency rationale). Shape:

```json
{"ticket_id":"DS-87","pr_number":458,"state":"done","attempts":1,"ts":"<ISO8601>","detail":null}
```

`state` enum: `done` | `guard_skipped` | `closed_unmerged` | `abandoned` | `failing`. The first four are **terminal** - the pair is never reconsidered as a candidate again. `failing` is **non-terminal** and carries the running `attempts` counter.

Record `done` on a successful transition; `guard_skipped` when the forward-only guard in step (f) skipped the transition; `closed_unmerged` from (c). Record `failing` (NOT `guard_skipped`) when the Writeback Helper's return payload has `status == "skipped_unconfigured_state"` - this is a retryable misconfiguration, not a permanent guard decision, so the pair must remain a candidate on future sweeps until the operator fixes `AGENTS.md`; it terminalizes via the same `attempts`/`abandoned` rule as any other `failing` entry below, not immediately. On any other error in (c), (d), (f), or the writeback spawn: append `failing` with `attempts` incremented from the prior latest entry for this pair (starting at 1) and `detail` set to the error string. When `attempts` reaches **3**, append `abandoned` instead and print:

    [ticket-status-sync] <KEY> (PR #<n>) abandoned after 3 failed sweeps: <detail> - run /ds-ticket-status-sync <KEY> to retry manually.

**h. Cursor.** Advance `.agentic/.pending-merge-last-sweep` to `now` at the end of **every** sweep that ran, unconditionally, via atomic tmp-file + `mv`. Per-candidate progress lives entirely in `.agentic/pending-merge-state.jsonl`, so no failure mode pins the sweep - a candidate stuck in `failing` still lets the cursor advance and the next sweep still runs on schedule. The cursor's sole reader is the 60-minute throttle in (a).

**Cost.** Worst case per sweep: 20 `gh pr view` calls, plus up to 20 `gh pr list --search` open-PR checks, plus a tracker pre-read and writeback spawn only for candidates confirmed merged and unblocked - at most once per 60 minutes. Steady state on a repo with no newly-merged AE PRs since the last sweep is 20 cheap `gh pr view` calls and zero tracker traffic, shrinking toward zero as pairs terminalize.

**i. Soft-fail.** Identical discipline to `## Soft-fail discipline` below: every call logs and continues; the sweep never blocks the session; it never retries with backoff; it never errors out.

**j. Output.** One line per transition attempt in the existing `[ticket-status-sync] <KEY>: '<current>' -> '<expected>' ...` format (see step 8 above), one line per abandonment per (g), one line if the cap in (b) truncated, plus this breadcrumb:

    [phase: ticket-status-sync | mode=pending-merge | candidates=<N> | confirmed_merged=<N> | blocked_by_open_pr=<N> | transitions=<N> | skipped=<N>]

**Known limitations.** The sweep only sees PRs AE opened and recorded on this machine - `.agentic/ticket-ledger.jsonl` is gitignored and machine-local, so work shipped by hand, by a teammate, or outside `/ds-implement-ticket` is invisible to it; `--all` remains the catch-all for those. A ticket with any *concurrently open* PR mentioning its key is deferred indefinitely by (d) - correct for a multi-PR ticket whose later PRs are already open when the first merges, but it also means an unrelated open PR that happens to mention the key prevents auto-close until that PR closes or merges. (d) does **not** cover the sequential case: a multi-PR ticket whose later PRs have not been opened yet at the time the first PR merges. In that shape, zero open PRs match the search, the candidate is treated as unblocked, and the sweep fires Done on the first merge - the tracker then reads Done while implementation work remains, and the forward-only guard forbids the automatic backward correction, so it becomes a manual operator repair. This matches the existing risk on the `/ds-implement-ticket` auto-merge (W7) path for the same shape, and this sweep is strictly more conservative than W7 (it additionally defers on concurrently-open siblings, which W7 does not check) - but it does not eliminate the sequential gap.

## Soft-fail discipline

Every tracker/gh/git call soft-fails: log and continue. A single ticket's reconciliation failure does not abort an `--all` sweep, and applies equally to the tasks.jsonl pass and the tracker-wide sweep (Tier 1 and Tier 2). The command never errors out on an external API failure.

## Output

Emit one breadcrumb per pass: `[phase: ticket-status-sync | mode=<single|all> | transitions=<N> | skipped=<N>]` for the single-ticket / tasks.jsonl-pass counts, and, when the tracker-wide sweep ran, a second breadcrumb: `[phase: ticket-status-sync | mode=all | pass=tracker-sweep | transitions=<N> | skipped=<N> | capped=<N> | candidates=<N>]`. When `--pending-merge` ran, emit the breadcrumb defined in `## Pending-merge sweep (--pending-merge mode)` (j): `[phase: ticket-status-sync | mode=pending-merge | candidates=<N> | confirmed_merged=<N> | blocked_by_open_pr=<N> | transitions=<N> | skipped=<N>]`.

In single-ticket mode, print the before/after state. When the Writeback Helper's return payload has `status == "skipped_unconfigured_state"`, additionally print the diagnostic on its own line: `[ticket-status-sync] <KEY>: SKIPPED - <diagnostic>` - this is the one interactive, operator-present mode, and it is also the exact remedy the pending-merge abandon message (see § Pending-merge sweep (g)) directs the operator to when a persistent misconfiguration abandons a candidate, so it must explain itself rather than showing an unchanged before/after state with no reason given. In `--all` mode, print a one-line-per-ticket summary table for the tasks.jsonl pass, then the Tier 1 operator-visible transition lines, then the Tier 2 candidate lines (if any). In `--pending-merge` mode, print one transition/abandonment line per candidate as described in `## Pending-merge sweep (--pending-merge mode)` (j).

When any ticket in a pass - including a `--pending-merge` sweep - returned `unmatched_state_name`, print one additional aggregate line after that pass's breadcrumb: `[ticket-status-sync] N ticket(s) had a current state that did not match any configured TRACKER_STATE_* value (distinct states seen: <name1>, <name2>, ...) - same-category comparison skipped for these.`
