# Plan: QA screenshot proof - GitHub evidence branch, tracker attachments, comment-thread context

## Goal

Provide robust proof, in the form of images, that QA happened and was validated. Projects use Linear or Jira (per project); all projects use GitHub. Robustness is prioritized over minimal footprint.

## Hard constraint (verified)

GitHub renders PR-body/comment images via an anonymous camo proxy. On a private repo camo cannot authenticate, so no automated method renders inline images in a GitHub PR (committed file, raw URL, release asset all fail; only manual drag-drop user-attachments works, which is not scriptable). Therefore GitHub evidence = click-through links to committed images (renders inline only when the repo is public). Linear and Jira host attachments natively; Linear renders inline to authenticated users. Jira does NOT support ADF inline image embedding via the v3 REST attachment API (see MAJOR-1 note below), so Jira is also click-through. The always-on GitHub layer is the robustness floor.

## Verified API facts (from Linear GraphQL schema and Jira v3 OpenAPI spec)

### Linear `fileUpload` mutation

Response type: `UploadPayload { success, lastSyncId, uploadFile: UploadFile }`.

`UploadFile` fields (authoritative, from Linear's published GraphQL schema):
- `uploadUrl: String!` - the pre-signed S3 PUT target. **Expires.** Use only to PUT the file bytes. Do NOT embed this in comments.
- `assetUrl: String!` - the **permanent** asset URL. Described in schema as "The asset URL for the uploaded file." Embed this in Linear comment markdown: `![desc](assetUrl)`.
- `headers: [UploadFileHeader!]!` - headers the PUT request must include (e.g. `Content-Type`).

Workflow: (1) call `fileUpload` mutation to get `uploadUrl`+`headers`+`assetUrl`; (2) PUT file bytes to `uploadUrl` with required `headers`; (3) embed `assetUrl` in the comment as `![description](assetUrl)`.

### Jira Cloud v3 attachment POST

`POST /rest/api/3/issue/{key}/attachments` returns an array of `Attachment` objects. The `Attachment` schema contains: `id` (numeric attachment ID), `content` (authenticated download URL), `filename`, `mimeType`, `size`, `thumbnail`, `author`, `created`, `self`.

**There is no media UUID in this response.** ADF `mediaSingle` nodes require a `media` node with an `id` field sourced from the Atlassian Media API - a separate service requiring a Media API token obtained via a media auth flow distinct from Basic auth Jira REST credentials. Agents operating with only `JIRA_USER_EMAIL`+`JIRA_API_TOKEN` cannot obtain a Media API token and therefore cannot construct a valid ADF `mediaSingle` node.

**Decision: Jira inline embedding via ADF is infeasible.** Jira behavior is downgraded to: upload attachment + post a plain-text link comment. The comment body is a simple ADF doc with a paragraph node containing a text node linking to `attachment.content` (authenticated URL) alongside descriptive text. No `mediaSingle` attempted.

**Confirmed ADF structure for a plain-text Jira comment** (from Jira v3 OpenAPI example):
```json
{
  "body": {
    "type": "doc",
    "version": 1,
    "content": [
      {
        "type": "paragraph",
        "content": [
          {
            "type": "text",
            "text": "QA Evidence: criterion-id PASS — screenshot: <filename> (<content_url>)"
          }
        ]
      }
    ]
  }
}
```

### Jira `comment` field from `jira_get_issue`

`GET /rest/api/3/issue/{key}` with `fields=*all` (the default) returns ALL fields including `comment`. No second API call or `expand=` parameter needed. The `comment` field is a standard issue field returned in the default `fields=*all` response. Engineers must use the `comment` field from the existing Phase 1 `jira_get_issue fields:*all` response - no additional API call.

## Pieces

### Piece 1 - qa-engineer machine-parseable output (`content/agents/qa-engineer.md`)
Add `## Screenshot Evidence` after `## Screenshots` with a fenced `qa-screenshots-json` block: JSON array of `{path, description, criterion_id, result}`. Emit `[]` if none. PASS-only entries on overall PASS; all entries on FAIL/PARTIAL. Malformed/absent block treated as `[]` downstream (never hard error). Human-readable `## Screenshots` stays.

### Piece 2 - GitHub qa-evidence branch + PR section (`content/commands/implement-ticket.md`)
New Phase 8.5 (between Phase 8 commit/push and Phase 9 open-PR): commit PASS screenshots to a long-lived orphan `qa-evidence` branch (never merged to main, no git tag) under deterministic slugified paths `<ticket_slug>/<branch_slug>/<slug>.png` via a throwaway worktree. ATOMIC: copy all, one commit, push with up-to-3x fetch/rebase/push retry (unique paths => clean rebase). See orphan-create race handling below.

**First-time orphan bootstrap** (branch does not exist on remote): use `git checkout --orphan` in a temp clone (portable to git >= 1.7.2; `git worktree add --orphan` needs >= 2.42, avoided).

`$SCREENSHOTS_SRC` MUST be a path OUTSIDE `$TEMP_CLONE` (the screenshots live in `/tmp/`), so `reset --hard` inside the clone never destroys the source.

```bash
# TEMP_CLONE is a scratch clone of the repo; $SCREENSHOTS_SRC is in /tmp (outside the clone)
git -C "$TEMP_CLONE" checkout --orphan qa-evidence
git -C "$TEMP_CLONE" rm -rf . 2>/dev/null || true
mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$TEMP_CLONE" add .
git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"
# --- RACE RECOVERY LOOP: handles N concurrent first-creators racing on the orphan root ---
for i in 1 2 3; do
  git -C "$TEMP_CLONE" push origin qa-evidence && break
  # push rejected (a concurrent creator won; our local root is unrelated history)
  git -C "$TEMP_CLONE" fetch origin qa-evidence
  git -C "$TEMP_CLONE" reset --hard origin/qa-evidence   # adopt the landed history; wipes worktree
  mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"        # recreate dest dir destroyed by reset
  cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
  git -C "$TEMP_CLONE" add .
  git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"
done
```

**After temp-clone push succeeds** (branch now exists on remote), add the worktree to the main repo for reading `QA_EVIDENCE_URLS`:
```bash
# MUST fetch first - $REPO has no remote-tracking ref for qa-evidence until now
git -C "$REPO" fetch origin qa-evidence
git worktree add "$WORKTREE_PATH" origin/qa-evidence   # detached HEAD - see push refspec note below
```

**Steady-state path** (branch already exists on remote): fetch to update the remote-tracking ref before adding the worktree, then use normal fetch/rebase/push retry loop for committing new screenshots:
```bash
git -C "$REPO" fetch origin qa-evidence
git worktree add "$WORKTREE_PATH" origin/qa-evidence   # creates a DETACHED HEAD worktree
# ... copy files into worktree, commit, then push with retry:
for i in 1 2 3; do
  # CRITICAL: worktree is on a detached HEAD. `push origin qa-evidence` would be a no-op
  # (resolves the branch name, not our new commit). MUST use the explicit HEAD:qa-evidence refspec.
  git -C "$WORKTREE_PATH" push origin HEAD:qa-evidence && break
  git -C "$WORKTREE_PATH" fetch origin qa-evidence
  git -C "$WORKTREE_PATH" rebase origin/qa-evidence
done
```

Note: the steady-state rebase onto `origin/qa-evidence` is safe because all tickets that have previously committed share real history on this branch. Only the first-create path produces an unrelated-history race, handled above. The `HEAD:qa-evidence` push refspec is mandatory in every detached-HEAD worktree push (the worktree is checked out from the remote-tracking ref `origin/qa-evidence`, which is detached, not a local branch).

Build `QA_EVIDENCE_URLS` only after push succeeds; soft-fail empties it. Phase 9 appends `## QA Evidence` to the PR body via `gh pr edit --body-file` (temp file) listing each criterion + PASS + click-through link `https://github.com/<owner>/<repo>/blob/qa-evidence/<path>`.

**Skip conditions**: QA skipped/Trivial, no screenshots, gh/jq unavailable, push failed after retries. Private-repo links are click-through, not inline.

**Phase 9 PR body note - differentiated language:**
- When QA ran but `QA_EVIDENCE_URLS` is empty (push failed / screenshots lost): append `> QA ran (PASS) but screenshot evidence could not be committed to qa-evidence branch (push failed or screenshots unavailable at commit time).`
- When QA was skipped/not configured (TRACKER=none, qa_skip set, Trivial path): append `> QA skipped or not configured for this ticket (see qa_criteria in architect plan).`
- When QA ran and evidence is available: normal `## QA Evidence` section with links.

### Piece 3 - Phase 11 tracker attachment upload (`content/commands/implement-ticket.md`)
Upload the same PASS screenshots as native attachments so they appear in the ticket. DECISION: Option A (direct REST/GraphQL, no new MCP dependency) over Option B (upload-capable MCP servers). Rationale: no runtime dependency added; reuses existing creds. The always-on GitHub layer (Piece 2) is the robustness floor when tracker creds are absent.

**Linear:**
1. Call `fileUpload` mutation (fields: `uploadFile { uploadUrl assetUrl headers { key value } }`).
2. PUT file bytes to `uploadFile.uploadUrl` with all headers from `uploadFile.headers`.
3. Post a comment with body containing `![<description>](<uploadFile.assetUrl>)` - renders inline.
4. Token: `LINEAR_API_KEY`.

**Jira:**
1. `POST /rest/api/3/issue/{key}/attachments` (multipart, `X-Atlassian-Token: no-check`, Basic auth `JIRA_USER_EMAIL:JIRA_API_TOKEN`). Returns array; capture `attachment[0].content` (authenticated download URL) and `attachment[0].filename`.
2. ADF inline embedding is NOT attempted (Media API UUID not available from v3 REST creds - see Verified API facts). Instead post an ADF comment with a plain text paragraph:
   `"QA Evidence — PASS: <filename> <content_url>"` for each screenshot.
3. Spec note: the comment link is click-through for authenticated Jira users. It is NOT an inline image. This is the maximum fidelity achievable without a separate Media API integration.

Gated by `qa.md` field `screenshot_upload: true` (opt-in) AND `QA_SCREENSHOT_PATHS` non-empty. Credentials/capability absent => skip upload, comment still posts with a skipped note. Linear `fileUpload` graceful-skip on error (undocumented mutation, may change). `mcp__linear__list_comments` tool name inferred - graceful-skip if name differs.

**Runtime risk note:** The embedded git/API sequences in Pieces 2 and 3 carry real runtime risk (race conditions, network failures, API changes) that Skeptic spec-review alone cannot fully verify. The first real-world run of Phase 8.5 and Phase 11 upload logic should be observed and any failures treated as bugs to fix, not expected graceful-skips.

### Piece 4 - Phase 1 comment reading (`content/commands/implement-ticket.md`)
Phase 1 currently reads description only. Add comment-thread fetch:
- **Linear**: call `mcp__linear__list_comments` with UUID `issueId`.
- **Jira**: parse `issue.fields.comment` from the EXISTING `jira_get_issue fields:*all` response already fetched in Phase 1. **Do NOT make a second Jira API call.** The `comment` field is included in the default `fields=*all` response (confirmed via Jira v3 OpenAPI spec).

Flag prior-QA-failure comments (contains "QA" and FAIL/PARTIAL/BLOCKED/failed/re-work). Set `PRIOR_QA_COMMENTS` and `COMMENT_THREAD_SUMMARY` (<=2000 chars). Inject a `## Prior ticket context` section into the architect (Phase 3) and engineer (Phase 5) briefs when non-empty, with explicit "PRIOR QA FAILURES DETECTED" callout. Graceful no-op for TRACKER=none or empty thread.

## Units & sequencing

- Unit A: qa-engineer.md output block. Standalone. Elevated.
- Unit B: Phase 1 comment fetch + variables. Standalone. Elevated.
- Unit C: Phase 3 + Phase 5 brief `## Prior ticket context` injection. Depends on B. Elevated.
- Unit D: Phase 6b parse `qa-screenshots-json` -> `QA_SCREENSHOT_PATHS`. Standalone. Elevated.
- Unit E: Phase 8.5 + Phase 9 amendment. Depends on D. Elevated.
- Unit F: Phase 11 attachment upload + qa.md config field. Depends on D. Elevated.

Batch 1 (parallel): A, B, D. Batch 2 (parallel): C, E, F.

## Per-consumer impact
Both files are spec docs read by agent spawns, not imported modules (per-consumer 5-importer trigger does not fire). All changes additive/backward-compatible and gated. Manifest-exempt (spec docs).

## QA criteria
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: >
    Both files are markdown spec documents consumed by AI agents as runtime instructions;
    no compiled artifact, no deployable service, no browser surface. The embedded git/API
    sequences are executable protocol (not inert docs), but correctness is verified by
    Skeptic spec-review against the confirmed API shapes above. First real-world execution
    should be observed; INCONCLUSIVE on initial run is acceptable.
```

## Known limitations
- Linear `fileUpload` mutation is undocumented in public API docs (schema-confirmed but behavioral details may change); graceful-skip on error. GitHub branch is fallback.
- Jira inline image embedding requires a separate Atlassian Media API integration (media token, separate auth flow) - not achievable via standard `JIRA_USER_EMAIL`+`JIRA_API_TOKEN` v3 REST credentials. Jira gets click-through links only.
- `qa-evidence` orphan branch grows unbounded (one commit/ticket); pruning is future work; never merged to main so no CI/history impact.
- `mcp__linear__list_comments` tool name inferred; graceful-skip if it differs.
- `QA_SCREENSHOT_PATHS` kept in-context only (not loop-state); interruption between QA and Phase 8.5 loses evidence (degrades gracefully).
- The concurrent-orphan-create race recovery requires re-copying screenshots after `reset --hard`; engineer must preserve `$SCREENSHOTS_SRC` path until push succeeds.

## Open questions
None.
