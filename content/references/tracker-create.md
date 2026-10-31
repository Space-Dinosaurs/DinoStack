<!--
Purpose: Full procedure for the Tracker Create Helper of
         `/ds-implement-ticket` - the synchronous pattern that creates a
         tracker ticket and returns its ID - moved verbatim out of
         content/commands/ds-implement-ticket.md so a run that never
         creates a ticket does not carry it. Covers the invocation
         contract, the collision pre-check and its `## Scope boundary`
         append, the per-tracker create branches, and the loud failure
         line.

Public API: Read-only reference document, addressed by its retained
            `## Tracker Create Helper` heading. The heading and its
            caller paragraph (the ticket-offer gate, and operator-approved
            creation per content/references/delegation-detail.md
            §Follow-up Ticket Creation Discipline) stay inline in
            content/commands/ds-implement-ticket.md, followed by a
            one-line `**Procedure:**` pointer to this file.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes the Setup tracker resolution (`TRACKER`,
               `TICKET_PREFIX`, `JIRA_BASE_URL`) in
               content/commands/ds-implement-ticket.md is in context.

Downstream consumers: content/commands/ds-implement-ticket.md (pointer
                      line); content/commands/ds-brief.md and
                      content/commands/ds-feedback-triage.md (callers);
                      content/references/conventions-detail.md
                      (`## Scope boundary` budget exclusion).

Failure modes: Prose reference; does not auto-execute. A caller that
               skips the pointer creates a ticket without the collision
               pre-check or the loud failure line.

Performance: n/a (static reference document).
-->

## Tracker Create Helper

**Invocation contract:**

Caller supplies:
- `TICKET_TITLE` - one-line summary of the work
- `TICKET_BODY` - markdown description; Problem + Acceptance Criteria mandatory (conventions-detail.md §Ticket descriptions)
- `TICKET_TYPE` - `feature` | `bug` | `task`

Helper returns:
- `CREATED_TICKET_ID` - e.g. DS-42; empty on failure
- `CREATED_TICKET_URL` - empty on failure
- `CREATE_STATUS` - `created` | `skipped` | `failed`
- `CREATE_ERROR` - error message, or null on success
**Collision pre-check (runs BEFORE the create branches):**

Before calling any tracker create API, scan in-flight tickets in the same tracker project/team for overlapping output surfaces. Overlap surface = same source files, exported symbols, DB tables/migrations, or shared utility/config the proposed TICKET_BODY scope touches. This is the cross-ticket boundary analysis: agree the boundary at creation, don't retrofit it after the ticket exists.

Scan target: open AND in-progress tickets in the same project/team. For Linear: `mcp__linear__list_issues` filtered by team, excluding state types completed, canceled, and duplicate. For Jira: `mcp__mcp-atlassian__jira_search` with project JQL scoped to statusCategory != Done. For trackers with no query branch: skip silently (fail-safe - the boundary-in-body rule below still applies via the conductor's scope knowledge rather than a scan).

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

The scan is a single tracker query (one API roundtrip, paginated to the project/team), cheap, create-time only - not on every phase transition.

**Branch on TRACKER:**

- **`TRACKER == linear`**: call `mcp__linear__save_issue` with NO `id` field (save_issue creates when no id is supplied - this matches the repo's existing Linear convention; do NOT use a `createIssue` tool, it does not exist). Pass `title`=TICKET_TITLE, `description`=TICKET_BODY, and the Linear team. IMPORTANT team-source note: the `## Linear` section's `Team:` field resolves to `TICKET_PREFIX` (e.g. "DS"), but save_issue needs the Linear team key/id - if only a prefix is available, resolve the actual team via the Linear team-list tool. Do NOT invent a `## Linear Team` heading; reuse the existing `Team:` resolution. On success read `issue.identifier` -> CREATED_TICKET_ID, `issue.url` -> CREATED_TICKET_URL, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed, CREATE_ERROR=\<msg\>.

- **`TRACKER == jira`**: call `mcp__mcp-atlassian__jira_create_issue` (naming-consistent with the existing `mcp__mcp-atlassian__jira_*` family used elsewhere in ds-implement-ticket.md). Pass `project_key`=TICKET_PREFIX, `summary`=TICKET_TITLE, `description`=TICKET_BODY, `issue_type` mapped from TICKET_TYPE (feature -> "Story", bug -> "Bug", task -> "Task"; omit to accept project default if uncertain). On success read the returned issue key -> CREATED_TICKET_ID, construct CREATED_TICKET_URL as `<JIRA_BASE_URL>/browse/<CREATED_TICKET_ID>`, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed.

- **`TRACKER` has no built-in create branch (forward-looking fall-through)**: CREATE_STATUS=skipped. Emit one operator line: `ticket_driven: create not supported for this tracker - proceeding ad-hoc.` Do NOT run any shell command from `.agentic/phase0-classifiers.yml` as a create operation - the classifier contract is read-only; creation is a write operation outside that contract. This branch is the extension point for trackers not yet integrated: adding a new tracker means adding a create branch above; until then it falls through here. Adding a project-local classifier does NOT constitute a create integration.

**LOUD failure (NOT silent):** on CREATE_STATUS=failed, emit an operator-visible line mirroring the Writeback Helper's failure line format: `tracker-create: '<TICKET_TITLE>' FAILED: <CREATE_ERROR>`. Do not block the caller; the caller (the gate) decides: offer mode proceeds ad-hoc AFTER emitting the warning; require mode surfaces and waits.
