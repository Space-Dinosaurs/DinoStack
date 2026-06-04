# Automatic Identity Derivation + Three-Dimension Session Tracking

Status: V1 scope = 8 units (U1-U6, U8, U9), design Skeptic-vetted. U7 (team-distribution commit) DESCOPED to a fast-follow (see "Fast-follow" below).
Risk: Elevated, multi-unit - Plan/Brief tier (per orchestration-planner count)
Track: agentic-engineering (single track)

## Fast-follow (PR-attribution bundle - NOT in this V1 build)
Three coupled pieces, deferred together because they form one "PR attribution" story and share the cmd_show↔grep contract:
1. **Team-for-a-project distribution** (was U7): committing each developer's `.agentic/session-log/<dev>.jsonl` so teammates receive it. Operator directive (2026-06-04): **the session-log commit must happen in the ENGINEER's worktree on the feature branch (where the work happens), NOT on the conductor's main checkout.** That makes it ride the PR naturally - no commit-to-main, no extra CI cycle. Open design point: the Stop hook writes the session-log in the main checkout, so the mechanism must get the lines into the engineer's worktree/branch (or have the worktree own its telemetry).
2. **PR `Developer:` trailer + commit-template DCO `-s` fix** (operator Decision #1): the `content/commands/implement-ticket.md` commit block emits `Developer: <handle>` (when confirmed) composed with `Co-Authored-By` + an always-present `Signed-off-by`. Moved here from V1 because the trailer is part of the same attribution story and depends on piece 3. (DCO is not broken in the interim - engineers add `git commit -s` explicitly.)
3. **`cmd_show` ↔ grep contract**: `cmd_show` currently prints `provisional:   true` (aligned, multi-space) for humans; the commit-template grep needs a stable single-space/whitespace-tolerant match. The fast-follow normalizes this (single-space emit + `grep -E '^provisional:[[:space:]]+true'`) so the trailer suppression actually fires for provisional identities. **V1 does NOT ship the commit template, so V1 docs must NOT claim cmd_show output is grepped by a commit template.**

Until shipped, the TEAM dimension is *enabled* (committed per-dev files aggregate via `agentic-cost team`) but not *auto-distributed*, and there is no PR `Developer:` trailer.

## Goal (operator-stated)
Automatic per-operator token+time tracking (no manual `agentic-identity init`), unified across three dimensions:
- **PROJECT** - per-repo, committed `.agentic/session-log/<dev>.jsonl`, readable locally.
- **TEAM** - that same committed per-project log, pulled by teammates via git (cross-developer, for a given project). REQ B. V1 ENABLES this (per-dev files aggregate via `agentic-cost team` once committed) but the AUTO-commit/distribution is the U7 fast-follow.
- **OPERATOR** - one human across all their repos, global `~/.agentic/session-log/` mirror, machine-local (acceptable).

## Approved decisions (locked - do not relitigate)
1. **DCO commit-template fix** (operator-approved): commit template always emits `Signed-off-by` composed with `Co-Authored-By` + the conditional `Developer:` trailer.
2. `NL=$'\n'` heredoc fix (real newline between trailers; empty DEVTRAILER -> only Signed-off-by).
3. git-config guard: `||--global` fallback then loud abort if name/email empty (never a malformed signoff).
4. Provisional-gate: auto-derive writes `provisional: true`; telemetry/PR-stamp deferred until confirmed.
5. Confirmation at the conductor first-user-turn (conventions.md + METHODOLOGY.md), NOT in the mechanical preflight (which stays fast/silent, only reads the provisional field).
6. Two new command docs (`agentic-identity.md`, `agentic-cost.md` operator section).
7. **One-session gap ELIMINATED** by the pending buffer (REQ A) - supersedes the prior "accepted gap".

## Data model

`~/.agentic/identity.yml` - additive `provisional`, `derived_from`. Absent `provisional` == confirmed (zero migration). Python `.get('provisional', False)`; JS `provisional === true`.

`~/.agentic/session-log/<dev>.jsonl` - global operator mirror; same schema as per-project line.

`<repo>/.agentic/session-log/<dev>.jsonl` - per-project committed log (gitignore-negated, `.gitignore` lines 28-29; per-dev files are conflict-free).

**NEW `~/.agentic/session-log/.pending/<session_uuid>.json`** - pending buffer, one file per session, written atomically:
```json
{ "schema_version": 1, "session_uuid": "<uuid>", "ts": "<ISO8601>",
  "project_slug": "<basename>", "repo_root": "<abs cwd>", "branch": "<branch>",
  "data": { "wall_seconds": 0, "tokens": {"input":0,"output":0,"cache_creation":0,"cache_read":0}, "spawn_count": 0, "by_agent": {} } }
```
No `developer_id` (unattributed until flush). `agentic-cost` MUST NOT read `.pending/`. Cap 100: when exceeding, delete oldest by `ts`, one stderr notice.

## Interfaces (binding)

### bin/agentic-identity
- `auto [--force]` - `gh api user --jq .login` (5s), lowercase+regex-validate; failure->exit1 (gh login hint); invalid handle->exit1 (manual init hint); existing confirmed w/o --force->exit2; existing provisional->overwrite silent; writes provisional+derived_from via tmp+rename.
- `confirm` - strip `provisional:`/`derived_from:` (tmp+rename), then `flushPendingBuffer(dev_id)`.
- `init <handle> [--force]` - existing behavior + call `flushPendingBuffer(new_handle)` when writing over a provisional identity or writing fresh (picks up pre-identity pending sessions).
- `show` - MUST print `provisional: true` when set (commit template greps it).
- `_read_identity()` - returns `provisional` (absent=False).
- `flushPendingBuffer(confirmed_dev_id) -> int` - **LOCKED** (race-safe). Acquire exclusive `fcntl.flock(LOCK_EX)` on `~/.agentic/session-log/.flush.lock` (create file/mkdirs first) for the WHOLE flush loop (blocking acquire, 30s timeout via SIGALRM or LOCK_NB+sleep loop; on timeout print stderr warning + exit 0, buffer intact). While locked, per `.pending/*.json` record: (1) dedup - scan global `<dev>.jsonl` for matching `session_uuid`; if present, unlink + skip. (2) build attributed line (pending fields + `developer_id`, preserve original `ts`). (3) **repo_root validation** - `git -C <repo_root> rev-parse --show-toplevel` (3s timeout) AND `basename(toplevel) == project_slug`; on success append `<repo_root>/.agentic/session-log/<dev>.jsonl` (mkdirs); on mismatch/failure skip per-project + one-line stderr warning. (4) ALWAYS append global `~/.agentic/session-log/<dev>.jsonl` (mkdirs). (5) unlink pending file only after all attempted appends succeed (per-project skippable; global-fail leaves file for retry). Lock covers both per-project and global appends (no interleave). Release fd after loop. Prints "Flushed N pending session(s)".

### hooks/stop-context.js
- `getIdentity()` -> `{ developer_id, provisional } | null`.
- Gate (replaces current block):
  ```
  if (identity && !identity.provisional) {
    writeSessionLog(cwd, identity, sessionId);        // per-project
    writeSessionLogGlobal(identity, sessionId, data); // global mirror
  } else {
    writePendingBuffer(cwd, sessionId);               // provisional AND null
    if (!identity) appendIdentityNudgeToContextMd(cwd); // nudge only when no identity at all
  }
  ```
- `writePendingBuffer(cwd, sessionId)` - compute totals; atomic tmp+rename to `.pending/<uuid>.json` (uuid v4 if sessionId null); enforce cap-100 (drop oldest by ts + stderr notice) before write; silent-fail.
- `writeSessionLogGlobal(...)` - global mirror, recursive mkdir, silent-fail independent of per-project.

### Commit template (content/commands/implement-ticket.md) - tested
```bash
NL=$'\n'
DEVELOPER=$(agentic-identity show 2>/dev/null | awk '/^developer_id:/{print $2}')
if agentic-identity show 2>/dev/null | grep -q '^provisional: true'; then DEVELOPER=""; fi
DEVTRAILER=${DEVELOPER:+"Developer: ${DEVELOPER}"}
SO_NAME=$(git config user.name 2>/dev/null || git config --global user.name 2>/dev/null)
SO_EMAIL=$(git config user.email 2>/dev/null || git config --global user.email 2>/dev/null)
if [ -z "$SO_NAME" ] || [ -z "$SO_EMAIL" ]; then
  echo "ERROR: git user.name / user.email not set." >&2; exit 1
fi
SIGNOFF="Signed-off-by: ${SO_NAME} <${SO_EMAIL}>"
git -C "$REPO" commit -m "$(cat <<EOF
type(scope): summary

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
${DEVTRAILER:+${DEVTRAILER}${NL}}${SIGNOFF}
EOF
)"
```

### Session-start confirmation (conductor first-user-turn, NOT preflight)
Preflight (sections/01) Step 1 only READS provisional (no prompt/shell-out). Conductor surfaces at first user turn (conventions.md + METHODOLOGY.md, meta-divergence-sweep pattern): non-blocking notice "tracking handle 'X' auto-derived (provisional) - confirm or correct; telemetry paused until you do." Confirm -> `agentic-identity confirm`; correct -> `init <handle> --force`. CI/headless never reaches a user turn -> stays deferred, buffered (not lost). Re-surfaces next session if ignored.

### agentic-cost operator [--since YYYY-MM-DD] [--json]
Reads `~/.agentic/session-log/*.jsonl` (mkdir -p; `.pending/` NOT globbed by top-level `*.jsonl`). Aggregates by dev+project. "Operator rollup (all projects)" table. `team` unchanged (project-local, already multi-dev correct).

### Session-log commit - DESCOPED to fast-follow (NOT built in V1)
The snippet below is retained as design reference only. It must be relocated into the engineer's worktree/feature-branch finalization (operator directive), not run on the conductor's main checkout. Do NOT implement in V1.

```bash
SESSION_DEV=$(agentic-identity show 2>/dev/null | awk '/^developer_id:/{print $2}')
SESSION_LOG_FILE=".agentic/session-log/${SESSION_DEV}.jsonl"
if [ -n "$SESSION_DEV" ] && ! (agentic-identity show 2>/dev/null | grep -q '^provisional: true') && [ -f "$SESSION_LOG_FILE" ]; then
  git add "$SESSION_LOG_FILE"
  if ! git diff --cached --quiet; then
    NL=$'\n'
    SO_NAME=$(git config user.name 2>/dev/null || git config --global user.name 2>/dev/null)
    SO_EMAIL=$(git config user.email 2>/dev/null || git config --global user.email 2>/dev/null)
    if [ -z "$SO_NAME" ] || [ -z "$SO_EMAIL" ]; then
      echo "WARNING: git user.name/email not set - skipping session-log commit (non-blocking)." >&2
      git restore --staged "$SESSION_LOG_FILE" 2>/dev/null || true
    else
      git commit -m "chore: update session log for ${SESSION_DEV}${NL}${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>"
    fi
  fi
fi
```
Invariants: exact-path stage only (never `-A`); guarded SO_NAME/SO_EMAIL (`||--global`; SKIP + unstage if empty, never a malformed signoff); idempotent (skip if no staged diff); non-blocking; committed on the feature branch BEFORE CI runs so NO second CI cycle / no `auto_merge_on_ci_green` stall; file lives in main worktree (conductor state), no engineer-worktree conflict; gitignore negation makes exact-path `git add` work.

**Eventual-consistency:** the Stop hook writes the current session's line at SESSION END (after this ticket's PR is opened/merged), so the Phase 4 commit contains PRIOR-session lines only; the current session's line lands in the NEXT ticket's Phase 4 commit. Per-project + global logs are eventually-consistent across sessions by design, not real-time.

## Units
- **U1** `bin/agentic-identity`: provisional parse; `cmd_auto`; `cmd_confirm`(+flush); `cmd_show` prints provisional; `flushPendingBuffer`; `cmd_init`(+flush); subparsers; manifest.
- **U2** `hooks/stop-context.js`: `getIdentity` provisional; new three-branch gate; `writePendingBuffer` (atomic, cap-100); `writeSessionLogGlobal`; manifest.
- **U3** `bin/agentic-cost`: `cmd_operator` (global glob, mkdir -p, aggregate, table, --json; `.pending/` not globbed); subparser; manifest.
- **U4** `content/sections/01-activation-preflight.md` (read provisional field only) + `content/rules/conventions.md` §Session Context + METHODOLOGY.md mirror (first-turn confirm behavior; remove old "gap accepted"; note telemetry buffered not lost). For the TEAM dimension, state it is enabled (committed per-dev files aggregate) but auto-distribution is a fast-follow - do NOT document an auto-commit that V1 does not ship.
- **U5** `content/commands/agentic-cost.md`: document `operator`.
- **U6** `content/commands/agentic-identity.md` (NEW): init/show/auto/confirm, pending-buffer behavior + cap, schema incl. provisional/derived_from, back-compat; manifest header.
- **U7** DESCOPED to fast-follow (see top). Team-distribution commit must run in the engineer's worktree/feature branch, not the conductor's main checkout - designed separately. NOT built in this V1.
- **U8** `content/sections/09-events-log.md`: one-paragraph note - pending buffer is a pre-attribution staging area, NOT an events.jsonl event.
- **U9** All 8 adapter build scripts + regenerate `scripts/.methodology-baseline.sha256`. Baseline-feeding (sections/) edits: sections/01 (U4), sections/09 (U8) -> regen required. content/ but not sections/ (adapter-rebuild only): conventions.md (U4), agentic-cost.md (U5), agentic-identity.md (U6). (implement-ticket.md is no longer touched - U7 descoped.) Same commit.

Dependency order: U1,U2,U3 parallel. U4 after U1 (refs `confirm`). U5 after U3. U6 after U1. U7 independent. U8 independent. U9 last (all content/ done).

## Per-consumer impact (shared: getIdentity / writeSessionLog / _read_identity)
| consumer | current | new |
|---|---|---|
| stop-context.js ~659 (wrap path) | writes per-project for any non-null identity | skips if provisional; else writePendingBuffer |
| stop-context.js ~709 (normal path) | same | same new gate |
| stop-context.js writeSessionLog() | per-project only | + writeSessionLogGlobal (recursive mkdir) |
| stop-context.js null-identity nudge | fires when null | unchanged; writePendingBuffer also fires |
| agentic-identity _read_identity() callers (show/init/auto) | dict w/o provisional | + provisional (absent=False); dev_id-only readers unaffected |
| agentic-cost cmd_team() | project-local glob | unchanged; `.pending/` not reached |
| implement-ticket | no session-log commit | UNCHANGED in V1 (U7 team-distribution commit descoped to fast-follow) |
| conventions.md §Session Context | documents accepted gap | gap eliminated; telemetry buffered until confirm |

getIdentity importers: 2 sites (both addressed). writeSessionLog: same 2. _read_identity: internal to bin/agentic-identity only.

## QA criteria
```yaml
qa_skip: pure-backend-library
qa_skip_rationale: CLI tools + hook + doc changes, no browser surface; verified via CLI + filesystem.
scenarios: []
manual_smoke: |
  1. agentic-identity auto (gh authed) -> identity.yml provisional:true, derived_from:gh.
  2. End session unconfirmed -> .pending/<uuid>.json with telemetry, no developer_id.
  3. New session -> first-user-turn confirm prompt; Y -> agentic-identity confirm.
  4. Flush: pending line appears in BOTH global and per-project logs, confirmed dev_id, original ts.
  5. End second session -> appended to BOTH logs (no pending).
  6. agentic-cost operator -> global rollup sums both sessions.
  7. auto without gh -> exit 1, correct message.
  8. empty git user.name + template commit -> abort with identity error (no malformed trailer).
  9. existing manual identity (no provisional) -> direct writes, no pending, no prompt.
  10. implement-ticket Phase 12 (confirmed + new content) -> "chore: update session log for <dev>" commit; exact-path stage only.
  11. cap: 101 pending files -> 100 remain, stderr notice, oldest dropped.
  12. team: two committed dev files -> agentic-cost team sums both.
  13. repo_root gone at flush -> global written, per-project skipped, warning, pending removed.
```

## Known limitations
- Pending buffer machine-local (multi-machine pre-confirm not merged in V1).
- Cap 100 pending: 100+ unconfirmed sessions drop oldest (bounded, noticed).
- Global + per-project logs unbounded (matches events.jsonl non-rotation).
- Phase 4 session-log commit contains prior-session lines only (current session's line lands in the NEXT ticket's commit - eventually-consistent by design). Committed before CI runs, so with `auto_merge_on_ci_green: true` no second CI cycle is triggered.
- Concurrent `agentic-identity confirm` is serialized by an `fcntl.flock` on `~/.agentic/session-log/.flush.lock` (30s blocking acquire) - no double-append to the global log.
- Cross-machine operator merge of global mirror out of V1.

## Open questions
None. Gap eliminated (pending buffer); team path specified (Phase 12 exact-path commit); three dimensions defined; flush owned by agentic-identity; agentic-cost team needs no change for multi-dev.
