<!--
Purpose: Create branches of the Tracker Create Helper of
         `/ds-implement-ticket` - the per-tracker calls that create a
         tracker ticket and return its ID - moved verbatim out of
         content/commands/ds-implement-ticket.md so a run that never
         creates a ticket does not carry them. Covers the Linear, Jira,
         and unsupported-tracker branches and the loud failure line.

Public API: Read-only reference document, addressed by its retained
            `## Tracker Create Helper` heading. The heading, its caller
            paragraph, the invocation contract, and the collision
            pre-check stay inline in
            content/commands/ds-implement-ticket.md (Phase 0's
            consume-time collision backstop reuses that scan), followed
            by a one-line `**Procedure:**` pointer to this file.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes the Tracker Create Helper's invocation contract and
               collision pre-check, and the Setup tracker resolution
               (`TRACKER`, `TICKET_PREFIX`, `JIRA_BASE_URL`), in
               content/commands/ds-implement-ticket.md are in context.

Downstream consumers: content/commands/ds-implement-ticket.md (pointer
                      line); callers of the Helper, all of which enter
                      through the command's inline section:
                      content/sections/02-delegation.md (ticket-offer
                      gate, offer and require modes),
                      content/commands/ds-brief.md (ticket_driven
                      offer/require step), and
                      content/commands/ds-feedback-triage.md (Step 4d).

Failure modes: Prose reference; does not auto-execute. A caller that
               skips the pointer creates no ticket and emits no loud
               failure line.

Performance: n/a (static reference document).
-->

## Tracker Create Helper

**Branch on TRACKER:**

- **`TRACKER == linear`**: call `mcp__linear__save_issue` with NO `id` field (save_issue creates when no id is supplied - this matches the repo's existing Linear convention; do NOT use a `createIssue` tool, it does not exist). Pass `title`=TICKET_TITLE, `description`=TICKET_BODY, and the Linear team. IMPORTANT team-source note: the `## Linear` section's `Team:` field resolves to `TICKET_PREFIX` (e.g. "DS"), but save_issue needs the Linear team key/id - if only a prefix is available, resolve the actual team via the Linear team-list tool. Do NOT invent a `## Linear Team` heading; reuse the existing `Team:` resolution. On success read `issue.identifier` -> CREATED_TICKET_ID, `issue.url` -> CREATED_TICKET_URL, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed, CREATE_ERROR=\<msg\>.

- **`TRACKER == jira`**: call `mcp__mcp-atlassian__jira_create_issue` (naming-consistent with the existing `mcp__mcp-atlassian__jira_*` family used elsewhere in ds-implement-ticket.md). Pass `project_key`=TICKET_PREFIX, `summary`=TICKET_TITLE, `description`=TICKET_BODY, `issue_type` mapped from TICKET_TYPE (feature -> "Story", bug -> "Bug", task -> "Task"; omit to accept project default if uncertain). On success read the returned issue key -> CREATED_TICKET_ID, construct CREATED_TICKET_URL as `<JIRA_BASE_URL>/browse/<CREATED_TICKET_ID>`, CREATE_STATUS=created. On MCP error: CREATE_STATUS=failed.

- **`TRACKER` has no built-in create branch (forward-looking fall-through)**: CREATE_STATUS=skipped. Emit one operator line: `ticket_driven: create not supported for this tracker - proceeding ad-hoc.` Do NOT run any shell command from `.agentic/phase0-classifiers.yml` as a create operation - the classifier contract is read-only; creation is a write operation outside that contract. This branch is the extension point for trackers not yet integrated: adding a new tracker means adding a create branch above; until then it falls through here. Adding a project-local classifier does NOT constitute a create integration.

**LOUD failure (NOT silent):** on CREATE_STATUS=failed, emit an operator-visible line mirroring the Writeback Helper's failure line format: `tracker-create: '<TICKET_TITLE>' FAILED: <CREATE_ERROR>`. Do not block the caller; the caller (the gate) decides: offer mode proceeds ad-hoc AFTER emitting the warning; require mode surfaces and waits.
