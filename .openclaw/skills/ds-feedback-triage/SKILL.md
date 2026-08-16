---
name: ds-feedback-triage
description: "Standalone, operator-run batch triage of the home-dir feedback store"
user-invocable: true
---
# /ds-feedback-triage

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Standalone, operator-run batch triage of the home-dir feedback store
(`~/.agentic/feedback.jsonl`) - the accumulated backlog of tool-friction,
process-escalation, guardrail-fire, and operator-correction signals that
`/ds-wrap` Part D.5 appends at the end of sessions across every project on this
machine. This command reads the open backlog, presents it grouped for
review, and creates tracker tickets ONLY for items the operator explicitly
greenlights. Ticket creation is the single deliberate human-in-the-loop
point in this command - batch, never automatic.

Conductor-direct throughout: a read-queue -> greenlight -> create-ticket
loop, not a multi-phase pipeline. No subagent spawns, no new config toggles.

## Invocation

`/ds-feedback-triage` - no args, no flags.

## Step 1 - Load open items

Run `ds-feedback list --status open` (prints a JSON array; empty store
or file-absent prints `[]`). If the array is empty, print:

```
No open feedback items in ~/.agentic/feedback.jsonl.
```

and exit. Nothing further runs.

## Step 2 - Group and present

Group the open items by `scope` (`methodology` first, then `project`). Within
each group, order by `severity` (`high` > `medium` > `low`) then `category`,
for readability - this ordering is presentational only, it does not gate
anything.

Present each item with a stable index number so the operator can reference
it in Step 3:

```
Open feedback  (~/.agentic/feedback.jsonl)

METHODOLOGY
  [1] high   process-escalation   repo: /Users/x/DinoStack
      evidence: "Skeptic re-route cap hit twice in one session with no escalation surfaced"
      suggested: "Escalate Skeptic re-route cap to operator before silently continuing"
      captured: 2026-06-30T14:02:11Z

PROJECT
  [2] medium tool-friction        repo: /Users/x/some-app
      evidence: "dev server boot command in qa.md was stale, wasted 3 QA cycles"
      suggested: "Update qa.md boot command for some-app"
      captured: 2026-06-29T09:41:03Z
  [3] low    operator-correction  repo: /Users/x/some-app
      evidence: "operator corrected the conductor's assumed default twice on the same call site"
      suggested: "Document the correct default for X in AGENTS.md"
      captured: 2026-06-28T11:15:47Z
```

Show `suggested_body` only if the operator asks to expand an item - the
one-line `suggested_title` plus `evidence` is enough for the greenlight
decision in the common case.

## Step 3 - Greenlight

Ask the operator which indices to greenlight for ticket creation:

```
Which items should be triaged into tickets? (comma-separated indices, "all", or "none")
```

This is a free-form data-selection prompt, not a binary confirmation - do
not route it through a multiple-choice tool. Wait for the operator's reply.
Indices not selected here are left untouched (still `open`) and can be
picked up on a future run, or explicitly dismissed (Step 5).

## Step 4 - Per-item ticket creation

For each greenlit item, in order:

### 4a. Resolve TICKET_TYPE

- `category` is `tool-friction`, `process-escalation`, or `guardrail-fire`:
  default `TICKET_TYPE=task`. If the evidence clearly describes broken or
  incorrect behavior rather than friction/process gap, `bug` is a reasonable
  judgment call instead.
- `category` is `operator-correction`: judgment call between `feature` (the
  suggested_title/body describes a new capability or convention that did not
  exist) and `task` (it describes an adjustment to existing behavior).

### 4b. Resolve the tracker for THIS ITEM - not the invoking project

**This is the critical step.** `~/.agentic/feedback.jsonl` is a global store
spanning every project the operator has run `/ds-wrap` in. An operator
triaging their whole backlog from inside one project's session must file
each item against the tracker of the project it actually came from - never
the tracker of the project the `/ds-feedback-triage` session happens to be
running in, and never a hardcoded tracker or workspace (Universality
pillar).

Resolve `TRACKER` / `TICKET_PREFIX` / `JIRA_BASE_URL` / `LINEAR_WORKSPACE`
(and the other tracker-config fields) by reading `<item.repo>/AGENTS.md` -
if that project uses the Claude Code `@AGENTS.md` import pattern, resolve
through to the actual `AGENTS.md` first, same as the Activation preflight
does. Then apply the exact same fallback chain `/ds-implement-ticket`'s
"Setup: Read project config" section uses under "Tracker resolution" (the
`## Tracker` / `## Linear` section checks, in that priority order), rooted
at `<item.repo>` instead of the current session's own project. Do this
resolution independently for every item - items in the same batch can
legitimately resolve to different trackers.

### 4c. Degrade-to-skip fallback (binding)

If any of the following hold for this item, do NOT create a ticket and do
NOT change the item's status (it stays `open`). Print one warning line and
continue to the next greenlit item - a single bad item must never abort the
rest of the batch:

- `<item.repo>` no longer exists on disk, or is unreadable.
- `<item.repo>/AGENTS.md` is missing, or has neither a `## Tracker` nor a
  `## Linear` section (the resolution chain, including the `.agentic/tracker.yml`
  local overlay check, lands on `TRACKER=none`).
- The Tracker Create Helper (Step 4d) returns `CREATE_STATUS=failed` or
  `CREATE_STATUS=skipped`.

Warning format:

```
feedback-triage: skipping item [<index>] (<repo>) - <reason>. Left open for a future run.
```

### 4d. Create the ticket

This step is unaffected by `content/references/delegation-detail.md`
§Follow-up Ticket Creation Discipline - its creates are already gated by
an explicit per-batch human greenlight (Step 2), a stronger control than
anything in that discipline.

Call the Tracker Create Helper (`/ds-implement-ticket` §"Tracker Create
Helper") by reference - do not reimplement its per-tracker branches here.
Supply:

- `TICKET_TITLE` = `item.suggested_title`
- `TICKET_BODY` = Problem built from `item.evidence` (the observed friction - not `item.suggested_body`, which is a proposed fix and derived content per `content/references/conventions-detail.md` §Ticket descriptions). When `item.suggested_body` is present, append it as a separately labeled, unverified line rather than substituting it for the Problem. Then append the traceability block:
  ```

  ---
  Evidence: <item.evidence>
  Source: feedback item <item.id>, captured <item.ts>, session <item.session_uuid>
  ```
- `TICKET_TYPE` = resolved in Step 4a

On `CREATE_STATUS=created`: run
`ds-feedback mark --id <item.id> --status triaged` and record
`CREATED_TICKET_URL` for the closing summary. On `failed`/`skipped`: apply
Step 4c.

## Step 5 - Explicit dismiss (optional)

The operator may dismiss an item without creating a ticket, at any point in
the session:

```
ds-feedback mark --id <id> --status dismissed
```

This is available for indices the operator reviewed in Step 2 and decided
are not actionable - distinct from simply not greenlighting them (which
just leaves them `open` for later).

## Step 6 - Summary

After the batch completes, print:

```
Feedback triage complete: <N> triaged (tickets created), <M> left open, <K> dismissed.
```

List each created ticket's ID and URL under the triaged count. List any
skipped-per-Step-4c items separately so the operator knows which ones need
manual follow-up before they can be triaged.

## Slice-1 boundary (intentional, not an oversight)

`scope: methodology` items are **not** cross-routed to any maintainer's
tracker in this slice. They resolve against `<item.repo>/AGENTS.md` exactly
like `scope: project` items - this preserves the Universality pillar (the
methodology must not phone home to a hardcoded maintainer workspace).
Routing methodology-scope feedback to a shared upstream tracker is a
deferred slice-2 concern, not something this command attempts.

## Edge cases

| Condition | Behavior |
|---|---|
| No open items | Print the empty-backlog message and exit (Step 1). |
| Operator greenlights "none" | Print the Step 6 summary with 0 triaged, 0 dismissed, all items still open. |
| Item's repo path no longer exists | Degrade-to-skip (Step 4c); item stays `open`. |
| Item's repo has no tracker configured (`TRACKER=none`) | Degrade-to-skip (Step 4c); item stays `open`. |
| Tracker Create Helper fails (MCP error) | Degrade-to-skip (Step 4c); item stays `open`; the Helper's own loud failure line is still emitted. |
| Two greenlit items resolve to different trackers | Handled independently per item (Step 4b) - no batching assumption across items. |
| Operator dismisses an item never presented for greenlight | Not applicable - dismiss (Step 5) only targets indices shown in Step 2. |

## Non-goals

This command intentionally does NOT:

- Auto-create tickets without explicit per-batch operator greenlight.
- Cross-route `scope: methodology` items to a maintainer tracker (deferred
  slice-2; see Slice-1 boundary above).
- Mutate `~/.agentic/feedback.jsonl` records other than via `ds-feedback
  mark` (id/ts/status remain CLI-owned per `bin/ds-feedback`).
- Spawn any subagent - the entire flow is conductor-direct.
- Invoke `/ds-implement-ticket` or any implementation agent on the created
  tickets. The ticket is created; working it is a separate, later decision.
