<!--
Purpose: Full procedures for QA evidence publishing in
         `/ds-implement-ticket`, moved verbatim out of
         content/commands/ds-implement-ticket.md so a run with no QA
         screenshots or QA failures does not carry them. Covers the
         Phase 6b QA regressions curator brief, the Phase 8.5 call to
         bin/ds-qa-evidence-publish (which holds the orphan `qa-evidence`
         branch commit and push, evidence URLs and cleanup), and the
         Phase 11 native screenshot attachment upload for Linear and
         Jira.

Public API: Read-only reference document, addressed by its retained
            headings. The QA regressions curator heading and its
            fires-once/skip paragraph, the Phase 8.5 heading and Skip
            conditions, and the Phase 11 tracker spawn brief and
            `screenshot_upload` qa.md field stay inline in
            content/commands/ds-implement-ticket.md, each followed by a
            one-line `**Procedure:**` pointer to this file. The Phase 6b
            and Phase 11 headings below are parents of the moved text
            only.

Upstream deps: bin/ds-qa-evidence-publish (Phase 8.5). Assumes
               content/references/qa-regression-obligation.md and the
               Phase 6b, Phase 9, and Phase 11 sections of
               content/commands/ds-implement-ticket.md are in context.

Downstream consumers: content/commands/ds-implement-ticket.md (three
                      pointer lines; Phase 9 reads `QA_EVIDENCE_URLS`
                      set here); bin/tests/test_worktree_lifecycle_spec.sh
                      (pins the Phase 8.5 call and its flags).

Failure modes: Prose reference; does not auto-execute. A conductor that
               skips a pointer publishes no QA evidence, writes no
               `.agentic/qa-regressions.md` entry, or uploads no tracker
               screenshots; every procedure here is soft-fail.

Performance: n/a (static reference document).
-->

## Phase 6b: QA Gate (conditional)

### QA regressions curator (Phase 6b clean exit)

At Phase 6b clean exit, if any iteration of this Phase 6b loop involved a QA FAIL (i.e., `qa_failures_log` was non-empty at any point before the final PASS), spawn a qa-regressions-curator subagent. **Note:** `qa-regressions-curator` does not yet exist as a named agent; use `general-purpose` agent type (Tier 1, fire-and-forget) until the named agent is formally added. Mirrors the Phase 6 findings curator pattern (see ds-implement-ticket.md §Findings curator (loop exit)).

**Brief:**
- Input: the `## Regression draft (for .agentic/qa-regressions.md)` block (verbatim) from the last FAIL iteration's qa-engineer report - it lives in the written report file at `report_path` (the pointer object's `report_path` field), not the return text itself; read the file at that path before the "Report/screenshot-JSON cleanup" step in ds-implement-ticket.md §Phase 6b: QA Gate (conditional) deletes it. Also include any fix-engineer documented-exception block from the QA-fix iteration, the `ticket_id`, and the curated index path (`.agentic/qa-regressions.md`).
- The curator computes the dedupe key `(surface, claim)` from each draft entry: lowercase the `Surface` and `What broke` values, collapse whitespace runs to a single space, strip leading/trailing whitespace, concatenate with a `|` separator.
- Dedupe rule: if a matching `(surface, claim)` key already exists in `.agentic/qa-regressions.md`, skip the write for that entry.
- The curator is the sole writer of `.agentic/qa-regressions.md` (append-only by discipline; the curator is fire-and-forget so the conductor never writes the file).
- Schema reference: `content/references/qa-regression-obligation.md` §`.agentic/qa-regressions.md` schema (canonical).

## Phase 8.5: QA evidence (conditional)

**Goal:** commit PASS screenshots to a long-lived orphan `qa-evidence` branch on GitHub under the deterministic path `<TICKET_SLUG>/<BRANCH_SLUG>/<filename>`, build click-through evidence URLs, and emit them into the PR body. The branch is never merged to main; it is a parallel evidence store.

**Slug derivation:**
- `TICKET_SLUG`: `$TICKET_ID` lowercased, non-alphanum replaced with hyphens (e.g. `eng-123`)
- `BRANCH_SLUG`: `$BRANCH_NAME` with leading `feature/`, `fix/`, `chore/` stripped; remaining slashes replaced with hyphens

Run `$REPO_DIR/bin/ds-qa-evidence-publish`, passing each `QA_SCREENSHOT_PATHS` entry (a JSON object) as its own argument after `--`:

```bash
"$REPO_DIR/bin/ds-qa-evidence-publish" --repo "$REPO" --ticket "$TICKET_ID" \
  --branch "$BRANCH_NAME" --gh-repo "$GH_REPO" -- "${QA_SCREENSHOT_PATHS[@]}"
```

The script commits the screenshots to `qa-evidence` and pushes it, deletes the consumed screenshot files and `/tmp/qa_devserver.log`, and prints the `[phase: qa-evidence | screenshots=<N> | urls=<M> | branch=qa-evidence]` breadcrumb on stderr. Its stdout is one JSON object `{url, criterion_id, description, result}` per published screenshot: set `QA_EVIDENCE_URLS` to those lines, one entry each. Stdout is empty when the push did not succeed or `$REPO` has no usable origin (a `WARNING` line says which); Phase 8.5 is always soft-fail - do not block Phase 9. Exit 2 is a usage error; 127 means the script is missing at `$REPO_DIR/bin/`.

## Phase 11: Post to tracker

#### If TRACKER is `linear` or `jira`

**Screenshot attachment upload (Linear and Jira, opt-in).** After the main tracker comment is posted, if `screenshot_upload: true` is set in `.agentic/qa.md` AND `QA_SCREENSHOT_PATHS` is non-empty, the tracker-writeback subagent also uploads the PASS screenshots as native attachments. Pass the following additional inputs to the subagent:

- `screenshot_upload: true` (flag; only when qa.md `screenshot_upload: true` AND paths non-empty)
- `qa_screenshot_paths`: the `QA_SCREENSHOT_PATHS` array (PASS entries only)

**Subagent behavior for screenshot upload:**

**Linear upload (when `TRACKER=linear`):**
1. For each screenshot in `qa_screenshot_paths`, call the `fileUpload` mutation with `contentType: "image/png"` and `filename: <basename>`. Fields requested: `uploadFile { uploadUrl assetUrl headers { key value } }`. The token is `LINEAR_API_KEY` (env var).
2. PUT the file bytes to `uploadFile.uploadUrl` with all headers from `uploadFile.headers` (e.g. `Content-Type`).
3. Build a comment body containing `![<description>](<uploadFile.assetUrl>)` for each screenshot - uses `assetUrl` (the permanent URL), never `uploadUrl` (which is the expiring PUT target). Post the comment via `mcp__linear__save_comment`.
4. Graceful-skip on any `fileUpload` mutation error (the mutation is schema-confirmed but behavioral details may change). If upload fails, post a plain comment noting that screenshots were available but upload failed.

**Jira upload (when `TRACKER=jira`):**
1. For each screenshot in `qa_screenshot_paths`, `POST /rest/api/3/issue/{key}/attachments` as multipart form data. Required headers: `X-Atlassian-Token: no-check`, `Authorization: Basic base64(<JIRA_USER_EMAIL>:<JIRA_API_TOKEN>)`. The response is an array of `Attachment` objects; capture `attachment[0].content` (authenticated download URL) and `attachment[0].filename`.
2. ADF inline embedding is NOT attempted (Atlassian Media API UUID is not available from standard Jira REST v3 credentials - see plan §Verified API facts). Instead, post an ADF comment with a link-marked paragraph for each screenshot:
   ```json
   {"body":{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"QA Evidence - PASS: "},{"type":"text","text":"<filename>","marks":[{"type":"link","attrs":{"href":"<content_url>"}}]}]}]}}
   ```
   The `content_url` is `attachment[0].content` (authenticated download URL, click-through for Jira users - NOT an inline image). This is the maximum fidelity achievable without a separate Media API integration.
3. Credentials absent (`JIRA_USER_EMAIL` or `JIRA_API_TOKEN` env var missing): skip upload, post a plain comment noting skipped upload.

**Gating:** upload only fires when BOTH `screenshot_upload: true` (qa.md field) AND `qa_screenshot_paths` is non-empty AND credentials/tool are available. Credentials or capability absent: skip upload, the main tracker comment still posts with a note: `"(QA screenshots available but upload skipped - set JIRA_USER_EMAIL+JIRA_API_TOKEN or LINEAR_API_KEY env vars and screenshot_upload: true in qa.md to enable attachment upload.)"`. Soft-fail throughout: upload errors never block the tracker comment.
