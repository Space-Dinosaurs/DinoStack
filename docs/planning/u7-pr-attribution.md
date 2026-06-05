# Technical Plan: U7 PR-Attribution Fast-Follow

<!-- Architect plan - do not edit directly; update via re-spawn if design changes. -->

## Approach

Add three coupled pieces to the already-shipped ae-identity-v1: (1) commit each developer's `.agentic/session-log/<dev>.jsonl` to the feature branch via a conductor-direct `git checkout $BRANCH_NAME` + `git add` + `git commit` on the main checkout at Phase 8 (mechanism (c) - existing pattern on the parallel path); (2) add a conditional `Developer: <handle>` git trailer to the Phase 8 commit and to the Phase 9 PR body when identity is confirmed; (3) fix the missing `Signed-off-by:` DCO trailer across the Phase 8 commit template and the Phase 5 `git_finalization` contract prose. No changes to `bin/agentic-identity` or `hooks/stop-context.js` - main already ships the full ae-identity-v1 with `provisional`, `auto`, `confirm`, `flushPendingBuffer`, and `writeSessionLogGlobal`.

## Codebase context

**Verified on main (a066510):**

`/Users/tyson/Documents/Development/ai-tools/agentic-engineering/bin/agentic-identity`:
- Ships `auto`, `confirm`, `provisional`, `flushPendingBuffer` - full ae-identity-v1.
- `cmd_show` emits `provisional:   true` (3 spaces, via f-string) when `identity.yml` has `provisional: true`.
- `_read_identity()` parses `provisional` field from identity.yml (present and `true` = provisional; absent = confirmed).
- No changes needed.

`/Users/tyson/Documents/Development/ai-tools/agentic-engineering/hooks/stop-context.js`:
- Ships `writeSessionLog` (per-project), `writeSessionLogGlobal` (global mirror), `writePendingBuffer` (provisional/absent path).
- Gate: `if (identity && !identity.provisional)` - session-log is written ONLY for confirmed identities.
- Session-log written to `<cwd>/.agentic/session-log/<dev>.jsonl` (project-local, committable from main checkout).
- No changes needed.

`/Users/tyson/Documents/Development/ai-tools/agentic-engineering/content/commands/implement-ticket.md`:
- Phase 8 commit template (lines ~1454-1467): has `Co-Authored-By:` but NO `Signed-off-by:`. No session-log commit step. No `Developer:` trailer.
- Phase 8 sequential path: no `git checkout $BRANCH_NAME` step (parallel path has this at line 977).
- Phase 9 PR body: no `Developer:` field.
- Phase 5 `git_finalization` contract prose (line 898): does not specify `Signed-off-by:` or `Developer:` in the template.
- **This is the only source file that needs editing.**

**Gitignore verification (tested with `git check-ignore`):**
- `.agentic/session-log/` is carved out via negation in `.gitignore` - committable FROM MAIN CHECKOUT.
- Files under `.agentic/worktrees/<branch>/.agentic/session-log/` are IGNORED inside worktrees because `.agentic/worktrees/` is gitignored. Same for `.claude/worktrees/`.
- Consequence: session-log is ONLY committable via `git -C $REPO` from the main checkout, not from within the engineer's worktree. This is the crossing mechanism constraint.

**DCO enforcement:**
- `.github/workflows/dco.yml` requires `Signed-off-by: <name> <email>` matching commit author on EVERY commit in every PR.
- Current Phase 8 template lacks `Signed-off-by:`. Any PR opened today would fail DCO.

**cmd_show output format (confirmed on main):**
```
developer_id:  <handle>        # always, 2-space pad
display_name:  <name>          # optional
created_at:    <ISO8601>       # always
provisional:   true            # only when provisional: true in identity.yml; 3-space pad
```
The grep must use `grep -E '^provisional:[[:space:]]+true'` (flexible whitespace) not `grep '^provisional: true'` (1 space would not match 3 spaces). This is the cmd_show-grep contract fix.

**Adapter rebuild:**
8 adapters need rebuild after any `content/commands/` edit: `.claude/`, `.cursor/`, `.codex/`, `.gemini/`, `.kimi/`, `.opencode/`, `.omp/`, `.pi/`. The methodology-drift baseline covers only `content/sections/` - no baseline regen needed for this change.

## Data model

No schema changes. The session-log schema is already defined and shipped. The `identity.yml` schema (including `provisional` field) is already shipped. The only new committed artifact is `.agentic/session-log/<dev>.jsonl` appearing in feature-branch commits (it was already gitignore-carved-out).

## API / interface design

**Identity resolution block (Phase 8, before any commits - shared by main commit and session-log commit):**

```bash
# Resolve developer identity for trailer and session-log commit.
# agentic-identity may not be installed; soft-fail throughout.
IDENTITY_SHOW=$(agentic-identity show 2>/dev/null || true)
DEV_ID=$(echo "$IDENTITY_SHOW" | grep -E '^developer_id:[[:space:]]+' | awk '{print $NF}')
IS_PROVISIONAL=$(echo "$IDENTITY_SHOW" | grep -qE '^provisional:[[:space:]]+true' && echo "true" || echo "false")
SO_NAME=$(git -C $REPO config user.name 2>/dev/null || true)
SO_EMAIL=$(git -C $REPO config user.email 2>/dev/null || true)
```

**Phase 8 main commit template (DCO fix + Developer trailer - binding):**

Use `NL=$'\n'` pattern instead of `<<'EOF'` heredoc to allow variable expansion:

```bash
NL=$'\n'
COMMIT_MSG="type(scope): short imperative description${NL}${NL}More detail if needed.${NL}Closes [TICKET_PREFIX]-NNN${NL}${NL}Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>"
if [ -n "$DEV_ID" ] && [ "$IS_PROVISIONAL" = "false" ]; then
  COMMIT_MSG="${COMMIT_MSG}${NL}Developer: ${DEV_ID}"
fi
git -C $REPO commit -m "$COMMIT_MSG"
```

Guard: if `SO_EMAIL` is empty, skip the entire Phase 8 commit block with a one-line warning and continue to push. This prevents a DCO-failing commit from being created.

**Phase 8 session-log commit block (new, runs AFTER main fixup commit, BEFORE push - soft-fail):**

```bash
SESSION_LOG_FILE="$REPO/.agentic/session-log/${DEV_ID}.jsonl"
if [ -n "$DEV_ID" ] && [ "$IS_PROVISIONAL" = "false" ] && [ -f "$SESSION_LOG_FILE" ] && [ -n "$SO_EMAIL" ]; then
  # Check if the file has any uncommitted changes relative to HEAD on BRANCH_NAME
  if ! git -C $REPO diff --quiet HEAD -- ".agentic/session-log/${DEV_ID}.jsonl" 2>/dev/null \
     || git -C $REPO ls-files --others --exclude-standard ".agentic/session-log/${DEV_ID}.jsonl" | grep -q .; then
    git -C $REPO add ".agentic/session-log/${DEV_ID}.jsonl"
    NL=$'\n'
    SESSION_COMMIT_MSG="chore(telemetry): add session log for ${DEV_ID}${NL}${NL}Eventual-consistency: captures prior sessions only.${NL}Current session line is written by the Stop hook after this session ends.${NL}${NL}Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>${NL}Developer: ${DEV_ID}"
    git -C $REPO commit -m "$SESSION_COMMIT_MSG" || true  # soft-fail
  fi
fi
```

**Phase 9 PR body `Developer:` field (binding when identity is confirmed):**

Build PR body via temp file (same pattern as QA Evidence) to allow variable expansion. Add to the body template:

```
Developer: $DEV_ID
```

As the last line of the initial `--body` content, before QA Evidence gets appended. Only when `DEV_ID` non-empty AND `IS_PROVISIONAL == "false"`.

**Phase 5 `git_finalization` contract prose (binding - clarifies engineer obligation):**

Replace the line 898 prose with:

> `git_finalization`: `{ commit_message_template, files_to_stage, push }` - the engineer commits and pushes. `push: true` for the Elevated path. `commit_message_template` MUST include a `Signed-off-by: $SO_NAME <$SO_EMAIL>` line populated from `git config user.name` / `git config user.email` (required for DCO CI gate). When developer identity is confirmed (non-provisional - `agentic-identity show` emits no `provisional:   true` line), also include a `Developer: <handle>` trailer. Use the `NL=$'\n'` pattern for multi-line templates (not `<<'EOF'` heredoc, which blocks variable expansion). Guard: if `git config user.email` returns empty, surface a warning and skip the commit.

## Implementation steps

**Unit 1 (Elevated): Edit `content/commands/implement-ticket.md`**

These steps are in the same file and must land in a single commit.

1. **Phase 5 git_finalization prose update (line 898):** Replace the existing one-liner with the expanded prose documented in API / interface design above. This documents the `Signed-off-by:` and `Developer:` obligations for engineers.

2. **Phase 8 preamble - sequential path checkout (before current line 1454):** Add immediately before the `# Only run...` guard block:
   ```
   **Sequential path checkout:** Before any Phase 8 fixup commits, ensure the main checkout is on the feature branch:
   ```bash
   git -C $REPO fetch origin $BRANCH_NAME --quiet
   git -C $REPO checkout $BRANCH_NAME
   ```
   This parallels the parallel path's `git -C $REPO checkout $FEATURE_BRANCH` at line 977. On the parallel path, this step was already done; the conditional checkout is a no-op.

3. **Phase 8 identity resolution block:** After the checkout step (step 2), add the identity resolution block exactly as specified in API / interface design above.

4. **Phase 8 main commit template rewrite:** Replace the existing `git -C $REPO commit -m "$(cat <<'EOF' ... EOF)"` block with the `NL=$'\n'` pattern that expands `$SO_NAME`, `$SO_EMAIL`, `$DEV_ID`, `$IS_PROVISIONAL`. Add the `SO_EMAIL` guard wrapping the entire commit block.

5. **Phase 8 session-log commit block:** After the main fixup commit block and before `git -C $REPO push`, add the session-log conditional commit block exactly as specified in API / interface design above.

6. **Phase 9 PR body Developer field:** Change the `gh pr create --body "$(cat <<'EOF' ... EOF)"` to use a temp file pattern (matching QA Evidence) to allow variable expansion. Add `Developer: $DEV_ID` as the final line of the initial body content (before QA Evidence), guarded by `[ -n "$DEV_ID" ] && [ "$IS_PROVISIONAL" = "false" ]`.

**`content/commands/implement-ticket.md`** - existing file with no manifest header (command files are exempt per module-manifest.md rules).

**Unit 2 (Elevated): Adapter rebuild - runs AFTER Unit 1 is merged to main**

7. Run all 8 adapter build scripts from the repo root:
   ```bash
   bash .claude/build.sh && bash .cursor/build.sh && bash .codex/build.sh && \
   bash .gemini/build.sh && bash .kimi/build.sh && bash .opencode/build.sh && \
   bash .omp/build.sh && bash .pi/build.sh
   ```

8. **CRITICAL gate - verify ONLY generated paths changed before staging:**
   ```bash
   git status --short
   ```
   The output MUST contain ONLY files under `.claude/`, `.cursor/`, `.codex/`, `.gemini/`, `.kimi/`, `.opencode/`, `.omp/`, `.pi/`. If ANY file outside these paths appears (source files, content/, bin/, hooks/, scripts/, docs/), STOP and report. Do NOT commit. This gate exists because the U9 regression (PR #171) silently reverted 51 source files via a stale-worktree adapter rebuild - CI passed because the revert was file-identical.

9. Stage and commit ONLY the adapter directories:
   ```bash
   git add .claude .cursor .codex .gemini .kimi .opencode .omp .pi
   ```
   Never `git add -A` or `git add .`.

10. Verify methodology drift baseline is unchanged:
    ```bash
    bash scripts/check-methodology-drift.sh
    ```
    Expected: OK. If MISMATCH: stop and report - `content/sections/` should not have changed.

**Units are SEQUENTIAL:** Unit 2 depends on Unit 1 merging to main. Do not run adapter rebuild in the same worktree as the Unit 1 edit.

**Per-consumer impact (adapter rebuild):** The change to `content/commands/implement-ticket.md` fans out uniformly to all 8 adapter mirrors. Each adapter is a verbatim copy - no per-adapter behavioral variation. The Phase 8 and Phase 9 additions appear identically in all 8 adapters. No per-consumer impact table required (uniform verbatim mirror, not a shared API with varying call sites).

## QA criteria

```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: >
    Changes are to a command spec document (content/commands/implement-ticket.md)
    and its generated adapter mirrors. There is no runtime UI or API surface.
    Correctness is verified by the adapter-sync CI gate (checks adapter drift)
    and by the DCO workflow passing on a real test PR.
  scenarios: []
  manual_smoke: >
    After Unit 1 merges, open a test PR with one commit that has Signed-off-by
    matching the author and verify the DCO CI check passes (green). On a project
    with confirmed identity (agentic-identity show outputs no provisional line),
    run /implement-ticket on a small ticket through Phase 8 and verify three things:
    (a) .agentic/session-log/<dev>.jsonl is committed on the feature branch with a
    commit message containing both Signed-off-by and Developer: trailers;
    (b) the feature branch's main fixup commit also contains Signed-off-by and
    Developer: trailers; (c) the PR body contains a Developer: line.
```

## Trade-offs and constraints

**Alternatives considered (before committing to the chosen approach above):**

- **Mechanism (a): conductor copies session-log into the engineer's worktree before the engineer commits.** Rejected: the engineer commits and pushes before Phase 8 runs; the worktree may no longer be accessible. The Phase 8 conductor-direct approach uses existing precedent (parallel path line 977).

- **Mechanism (d): git plumbing (git hash-object + git update-index + git commit-tree).** Rejected: complex, harder to maintain, unnecessary given the simpler (c) approach.

- **Mechanism (e): separate PR just for session-log.** Rejected: violates operator directive (commit must be on the feature branch, not a separate PR to main).

- **`Developer:` trailer only in commit, not PR body.** Rejected: trailers in individual commits do not survive `--squash` merge. Without the PR body entry, attribution is invisible after merge.

- **`Developer:` trailer only in PR body, not commit.** Considered: simpler, no commit template changes needed. Rejected: the commit-message trailer is a permanent record in feature branch history for auditability.

- **Append `Developer:` AFTER QA Evidence (third `gh pr edit` call) to achieve true git-trailer position.** Rejected: complexity cost exceeds benefit. `Developer:` mid-body is human-readable; true git-trailer semantics in the squash commit are not required for the use case.

- **Change `cmd_show` to emit 1-space padding (`provisional: true`) to simplify grep.** Rejected: breaking change to a shipped tool's output format. The grep fix (`[[:space:]]+`) is backward-compatible and correct.

- **No `SO_EMAIL` guard on the commit block.** Rejected: a commit without `Signed-off-by:` would immediately fail the DCO CI gate. The guard is non-negotiable.

**Known limitations and things to watch out for:**

- **Eventual consistency is structural.** The session-log committed in Phase 8 contains only PRIOR sessions' data. The current session's line is written by the Stop hook after the session ends - it will land on the NEXT ticket's commit. This is a fundamental constraint of the Stop hook model and cannot be fixed without a live-telemetry approach. Document in commit message (already included in the spec).

- **Session-log commit is soft-fail.** If `agentic-identity` is not installed, `SO_EMAIL` is empty, or the session-log file does not exist, the commit is skipped silently with a warning. Phase 9 is never blocked.

- **Squash commit body order.** QA Evidence is appended to the PR body AFTER `gh pr create`. The `Developer:` line added to the initial `--body` will appear BEFORE the QA Evidence section in the squash commit body, not at the very end. Git will not parse it as a git trailer in the squash commit. Human-visible attribution is preserved; machine-parseable trailer semantics are not guaranteed in squash commits.

- **Adapter rebuild contamination risk.** Unit 2 must run in a fresh worktree from the post-Unit-1 main. The `git status` gate at step 8 is mandatory. The prior U9 regression showed that a stale worktree can cause an adapter rebuild to silently revert source files while CI passes. Never skip the status gate.

- **Sequential path now has an explicit checkout.** Adding `git -C $REPO checkout $BRANCH_NAME` to Phase 8's sequential path changes conductor behavior: the main checkout is now explicitly on the feature branch after Phase 8. This is the correct behavior (mirrors parallel path) but may be surprising in sessions that expect the conductor's checkout to remain on the base branch throughout. Document this state change.

- **DCO on engineer commits (not just Phase 8 conductor commits).** The engineer must have `git config user.email` set in its worktree (typically inherits from global git config). If the worktree does not inherit config, the engineer's commits will lack `Signed-off-by:` and DCO will fail. This is an operator configuration concern, not a code concern, but the Phase 5 prose should mention it.

## Open questions

None.
