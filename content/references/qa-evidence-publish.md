<!--
Purpose: Full procedures for QA evidence publishing in
         `/ds-implement-ticket`, moved verbatim out of
         content/commands/ds-implement-ticket.md so a run with no QA
         screenshots or QA failures does not carry them. Covers the
         Phase 6b QA regressions curator brief, the Phase 8.5 body
         (slug derivation, the orphan `qa-evidence` branch commit and
         push, evidence URLs, cleanup), and the Phase 11 native
         screenshot attachment upload for Linear and Jira.

Public API: Read-only reference document, addressed by its retained
            headings. The QA regressions curator heading and its
            fires-once/skip paragraph, the Phase 8.5 heading and Skip
            conditions, and the Phase 11 tracker spawn brief and
            `screenshot_upload` qa.md field stay inline in
            content/commands/ds-implement-ticket.md, each followed by a
            one-line `**Procedure:**` pointer to this file. The Phase 6b
            and Phase 11 headings below are parents of the moved text
            only.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes content/references/qa-regression-obligation.md and
               the Phase 6b, Phase 9, and Phase 11 sections of
               content/commands/ds-implement-ticket.md are in context.

Downstream consumers: content/commands/ds-implement-ticket.md (three
                      pointer lines; Phase 9 reads `QA_EVIDENCE_URLS`
                      set here).

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

**Copy screenshots to a stable temp directory:**

```bash
SCREENSHOTS_SRC="/tmp/qa-evidence-$$"
mkdir -p "$SCREENSHOTS_SRC"
# Copy each path from QA_SCREENSHOT_PATHS into $SCREENSHOTS_SRC
# (QA_SCREENSHOT_PATHS is a bash array; entries are JSON objects from Phase 6b parse)
for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
  SRC_PATH=$(echo "$entry" | jq -r '.path')
  cp "$SRC_PATH" "$SCREENSHOTS_SRC/" 2>/dev/null || true
done
# If nothing copied, treat as skip
[ "$(ls -A "$SCREENSHOTS_SRC")" ] || { QA_EVIDENCE_URLS=(); rmdir "$SCREENSHOTS_SRC"; proceed to Phase 9; }
```

**Check whether `qa-evidence` branch already exists on remote:**

```bash
REMOTE_EXISTS=$(git -C "$REPO" ls-remote --heads origin qa-evidence | wc -l)
```

**First-create path (branch does not exist on remote):**

Create a scratch clone in `/tmp` to bootstrap the orphan branch. `$SCREENSHOTS_SRC` lives in `/tmp` (outside the clone) so `reset --hard` never destroys the source.

```bash
TEMP_CLONE="/tmp/qa-evidence-clone-$$"
git clone --depth=1 "$REPO" "$TEMP_CLONE"
git -C "$TEMP_CLONE" checkout --orphan qa-evidence
git -C "$TEMP_CLONE" rm -rf . 2>/dev/null || true
mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$TEMP_CLONE" add .
git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# RACE RECOVERY LOOP: handles concurrent first-creators racing on the orphan root
PUSH_SUCCEEDED_FIRST_CREATE=false
for i in 1 2 3; do
  if git -C "$TEMP_CLONE" push origin qa-evidence; then
    PUSH_SUCCEEDED_FIRST_CREATE=true
    break
  fi
  # push rejected - a concurrent creator won; adopt the landed history
  git -C "$TEMP_CLONE" fetch origin qa-evidence
  git -C "$TEMP_CLONE" reset --hard origin/qa-evidence   # adopts remote history; wipes worktree
  mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"      # recreate dest dir destroyed by reset
  cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
  git -C "$TEMP_CLONE" add .
  git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"
done

find "$TEMP_CLONE" -delete 2>/dev/null || true
```

After temp-clone push succeeds, fetch the updated remote-tracking ref into the main repo:

```bash
git -C "$REPO" fetch origin qa-evidence
```

**Steady-state path (branch already exists on remote):**

Add a detached-HEAD worktree pointing at `origin/qa-evidence`, copy files, and push using the `HEAD:qa-evidence` refspec (mandatory because the worktree is on a detached HEAD - `push origin qa-evidence` would be a no-op in this state).

```bash
WORKTREE_PATH="$REPO/.agentic/worktrees/qa-evidence-$$"
git -C "$REPO" fetch origin qa-evidence
git -C "$REPO" worktree add "$WORKTREE_PATH" origin/qa-evidence   # detached HEAD

mkdir -p "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$WORKTREE_PATH" add .
git -C "$WORKTREE_PATH" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# CRITICAL: worktree is on a detached HEAD; must use HEAD:qa-evidence refspec
PUSH_SUCCEEDED_STEADY=false
for i in 1 2 3; do
  if git -C "$WORKTREE_PATH" push origin HEAD:qa-evidence; then
    PUSH_SUCCEEDED_STEADY=true
    break
  fi
  git -C "$WORKTREE_PATH" fetch origin qa-evidence
  git -C "$WORKTREE_PATH" rebase origin/qa-evidence
done

if [ -x "$REPO_DIR/bin/ds-retire-carrier" ]; then "$REPO_DIR/bin/ds-retire-carrier" --repo "$REPO" "$WORKTREE_PATH" \
  || echo "WARNING: QA evidence worktree $WORKTREE_PATH not retired (exit $?); see the HELD line above or ds-retire-carrier --list-holds" >&2
else echo "WARNING: $REPO_DIR/bin/ds-retire-carrier missing; QA evidence worktree $WORKTREE_PATH left in place" >&2; fi
git -C "$REPO" worktree prune 2>/dev/null || true
```

**Build `QA_EVIDENCE_URLS` (only after push succeeds):**

Build `QA_EVIDENCE_URLS` only when the push in the active path succeeded. `$GH_REPO` is the repo slug resolved at Phase 0 setup (e.g. `org/repo-name`, same variable used throughout the command). Use `jq -n --arg` to safely interpolate description strings that may contain quotes or special characters.

```bash
# PUSH_SUCCEEDED is true only if the first-create or steady-state push loop above exited with success
PUSH_SUCCEEDED="${PUSH_SUCCEEDED_FIRST_CREATE:-${PUSH_SUCCEEDED_STEADY:-false}}"

QA_EVIDENCE_URLS=()
if [ "$PUSH_SUCCEEDED" = "true" ]; then
  OWNER=$(echo "$GH_REPO" | cut -d/ -f1)
  REPO_NAME=$(echo "$GH_REPO" | cut -d/ -f2)
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    FNAME=$(basename "$(echo "$entry" | jq -r '.path')")
    CRITERION=$(echo "$entry" | jq -r '.criterion_id')
    DESC=$(echo "$entry" | jq -r '.description')
    RESULT=$(echo "$entry" | jq -r '.result')
    URL="https://github.com/${OWNER}/${REPO_NAME}/blob/qa-evidence/${TICKET_SLUG}/${BRANCH_SLUG}/${FNAME}"
    # Use jq --arg to safely encode description (handles quotes and special chars)
    ENTRY_JSON=$(jq -n --arg url "$URL" --arg cid "$CRITERION" --arg d "$DESC" --arg r "$RESULT" \
      '{"url":$url,"criterion_id":$cid,"description":$d,"result":$r}')
    QA_EVIDENCE_URLS+=("$ENTRY_JSON")
  done
fi
```

If any step in the above sequence fails (push fails after 3 retries, worktree creation fails, copy fails), `QA_EVIDENCE_URLS` remains `()` (empty) and the phase continues. Phase 8.5 is always soft-fail - do not block Phase 9.

Clean up temp dir:

```bash
find "$SCREENSHOTS_SRC" -delete 2>/dev/null || true
```

Clean up the original `/tmp/qa_*` source files that were consumed. Run this unconditionally after the copy loop and temp-dir cleanup, but only when `QA_SCREENSHOT_PATHS` is non-empty. Use the parsed paths so only copied files are deleted. Guard with `|| true` so Phase 8.5 remains soft-fail.

```bash
if [ "${#QA_SCREENSHOT_PATHS[@]}" -gt 0 ]; then
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    SRC_PATH=$(echo "$entry" | jq -r '.path')
    rm -f "$SRC_PATH" 2>/dev/null || true
  done
fi
```

Also delete `/tmp/qa_devserver.log` if it exists. Run this unconditionally at the end of Phase 8.5, regardless of whether screenshots were consumed:

```bash
rm -f /tmp/qa_devserver.log 2>/dev/null || true
```

Emit breadcrumb: `[phase: qa-evidence | screenshots=<N> | urls=<M> | branch=qa-evidence]`

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
