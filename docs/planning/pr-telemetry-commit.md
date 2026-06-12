# Design: Commit per-developer telemetry on PR create/update (U7 fast-follow)

Status: **DESIGN DRAFT (Skeptic-revised, iteration 1) - implementation deferred to a future session.**
Skeptic withheld sign-off with 1 Major + 2 Minors; all three addressed in this revision. Re-run the architect-plan Skeptic gate before implementing, then proceed through the standard Brief/engineer flow.
Tracking ticket: DS-15.
Related prior design: `docs/planning/auto-identity-tracking.md` (U7 reference), `docs/planning/u7-pr-attribution.md` (exact code-level spec), `docs/planning/team-telemetry-aggregation-adr.md` (Stage 1 MVP framing).

## Problem / intent (operator's words)

"We need to make use of the telemetry data. If it's only on an operator's machine that can't happen. Bake into the methodology that IF there is a handle AND telemetry is captured, it should be a SEPARATE COMMIT when any PR is created or updated."

Goal: make per-session telemetry durable and team-visible by committing it to the repo, as a distinct commit, triggered in the PR flow - so `agentic-cost team` works across machines instead of only on the operator's local checkout.

## Approach (chosen)

Implement the already-designed U7 fast-follow: at **Phase 8 of `/implement-ticket`**, the conductor runs a path-aware telemetry commit targeting the PR branch's checkout, staging ONLY `.agentic/session-log/<dev>.jsonl`, when a confirmed identity exists and `commit_telemetry` is on. The committed artifact is the per-developer session-log JSONL already written by `hooks/stop-context.js` - no new schema, no Stop-hook change. The only infrastructure gaps are the gitignore carve-out that makes the file trackable and the path-aware targeting logic described in the Phase 8 branch-targeting model section below.

## Committed artifact

- Path: `.agentic/session-log/<dev>.jsonl` (already produced by the Stop hook; already consumed by `agentic-cost team`).
- Wire format (source of truth: `hooks/stop-context.js:430-441`; one JSON line per session): `{ ts, phase, event, agent, task_id, developer_id, session_uuid, project_slug, branch, data: { wall_seconds, tokens: { input, output, cache_creation, cache_read }, spawn_count, by_agent } }`.
- Contains no prompts, tool I/O, file contents, findings text, URLs, or credentials. Only `branch` is mildly sensitive (may encode ticket/feature names).

## Phase 8 branch-targeting model (Major fix - replaces underspecified original)

### Git model facts (sourced from codebase)

Three distinct paths exist through `/implement-ticket` and each has a different checkout state at Phase 8:

**Fan-out path.** Before Phase 8, the conductor explicitly runs `git -C $REPO checkout $FEATURE_BRANCH` (`content/commands/implement-ticket.md:977`). `$REPO` is therefore on the feature branch when Phase 8 runs. `git -C $REPO add/commit` is correct on this path. No file copy needed: the session-log file is already at `$REPO/.agentic/session-log/$DEVELOPER.jsonl`.

**Single-engineer Elevated path.** The conductor does NOT run `git checkout -b` (`content/commands/implement-ticket.md:822`). Branch and worktree creation are delegated to the engineer via the `worktree_setup` contract field (`content/commands/implement-ticket.md:896`), which includes `worktree_path`. The engineer also commits AND pushes per `git_finalization: { push: true }` (`content/commands/implement-ticket.md:898`). The conductor's `$REPO` checkout stays on `BASE_BRANCH` throughout. The feature branch lives exclusively in the engineer's isolated worktree at `$WORKTREE_PATH`. The session-log file is written by the Stop hook to `$REPO/.agentic/session-log/$DEVELOPER.jsonl` (`hooks/stop-context.js:443-446`) - it is in `$REPO`, not in the engineer's worktree. `git add` cannot stage a file outside the work tree, so a file copy is required before staging.

**Trivial path.** Same model as single-engineer Elevated: the Trivial engineer creates the branch, commits, and pushes in its own isolated worktree; `$REPO` stays on `BASE_BRANCH`. Same copy-and-commit-via-worktree mechanism applies.

### Chosen mechanism: path-aware PR-checkout resolution with HEAD-branch guard

At Phase 8, after the main commit block, resolve `$PR_CHECKOUT` based on path and commit there. Safety floor: verify `git -C $PR_CHECKOUT rev-parse --abbrev-ref HEAD == $BRANCH_NAME` before committing; soft-fail with a one-line warning if it does not match (never commit to the wrong branch).

Full telemetry-commit block (insert after main commit block in Phase 8, before push):

```bash
# --- Telemetry commit (soft-fail throughout) ---
COMMIT_TELEMETRY=$(python3 -c "
import json, sys
try:
  cfg = json.load(open('$REPO/.agentic/config.json'))
  print('true' if cfg.get('commit_telemetry', True) else 'false')
except: print('true')
" 2>/dev/null || echo 'true')

if [ "$COMMIT_TELEMETRY" = "true" ] && [ -n "$DEVELOPER" ]; then
  SESSION_LOG_SRC="$REPO/.agentic/session-log/${DEVELOPER}.jsonl"

  # Resolve PR_CHECKOUT: the checkout that holds the PR branch.
  # Fan-out path: $REPO is on $FEATURE_BRANCH after the line-977 checkout.
  # Single-engineer paths: engineer return supplies WORKTREE_PATH.
  if [ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BRANCH_NAME" ]; then
    PR_CHECKOUT="$REPO"
  elif [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
    PR_CHECKOUT="$WORKTREE_PATH"
    # Copy file into the worktree (git cannot stage files outside the work tree).
    mkdir -p "$PR_CHECKOUT/.agentic/session-log/"
    cp "$SESSION_LOG_SRC" "$PR_CHECKOUT/.agentic/session-log/${DEVELOPER}.jsonl" 2>/dev/null || true
  else
    echo "WARNING: telemetry commit skipped - cannot resolve PR checkout for branch $BRANCH_NAME"
    PR_CHECKOUT=""
  fi

  # HEAD-branch guard (safety floor: never commit to the wrong branch).
  if [ -n "$PR_CHECKOUT" ]; then
    ACTUAL_HEAD=$(git -C "$PR_CHECKOUT" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ "$ACTUAL_HEAD" != "$BRANCH_NAME" ]; then
      echo "WARNING: telemetry commit skipped - $PR_CHECKOUT is on '$ACTUAL_HEAD', expected '$BRANCH_NAME'"
      PR_CHECKOUT=""
    fi
  fi

  if [ -n "$PR_CHECKOUT" ] && [ -f "$PR_CHECKOUT/.agentic/session-log/${DEVELOPER}.jsonl" ]; then
    git -C "$PR_CHECKOUT" add ".agentic/session-log/${DEVELOPER}.jsonl"
    # Only commit if the index has a diff (avoids empty-commit on no new sessions).
    if ! git -C "$PR_CHECKOUT" diff --cached --quiet; then
      NL=$'
'
      TELEM_MSG="chore(telemetry): add session log for ${DEVELOPER}${NL}${NL}Signed-off-by: ${SO_NAME} <${SO_EMAIL}>${NL}${DEVTRAILER:+${DEVTRAILER}${NL}}"
      git -C "$PR_CHECKOUT" commit -m "$TELEM_MSG" ||         git -C "$PR_CHECKOUT" restore --staged ".agentic/session-log/${DEVELOPER}.jsonl"
    fi
    # Push only on single-engineer paths (fan-out push handled in its own block).
    if [ "$PR_CHECKOUT" != "$REPO" ]; then
      git -C "$PR_CHECKOUT" push -u origin "$BRANCH_NAME" 2>/dev/null || true
    fi
  fi
fi
# --- End telemetry commit ---
```

### Guarantee

The telemetry commit reaches the PR if and only if `git -C $PR_CHECKOUT rev-parse --abbrev-ref HEAD` equals `$BRANCH_NAME` at commit time. On any mismatch, the commit is skipped with a one-line warning; the feature commit is unaffected. The feature branch can never receive a spurious commit from this block.

### Single-engineer path: conductor responsibility for WORKTREE_PATH

The conductor must capture `$WORKTREE_PATH` from the engineer's return summary before Phase 8 runs. The engineer return already includes this field (it is part of the execution contract at `content/commands/implement-ticket.md:896`). If the engineer return does not include `worktree_path` (e.g., older brief format), `$WORKTREE_PATH` is empty and the guard above produces a soft-fail warning without committing.

## Resolution of the six hard tensions

1. **Squash-merge erases the commit boundary - chosen: accept it.** Under `gh pr merge --squash` the separate commit's message/SHA is lost, but its file diff is included in the squash, so `.agentic/session-log/<dev>.jsonl` lands on `main`. Persistence guarantee is via the file diff, not the commit identity. The separate commit is still visible in the PR diff (auditable), like QA-evidence commits. Rejected: post-merge append (extra CI run, breaks auto-merge), git notes/orphan ref (invisible to `agentic-cost`), scheduled aggregation (deferred complexity).
2. **What gets committed - the existing per-developer session-log JSONL**, not a per-PR rollup, not raw `events.jsonl`. Per-developer files are conflict-free (each dev appends only to their own; append-only merges trivially). Low churn (~500 bytes/session).
3. **Gitignore - add one carve-out** `!.agentic/session-log/` after the existing carve-outs; update the "intentionally local-only" comment. All other `.agentic/*` runtime files stay ignored. The `~/.agentic/session-log/` global mirror stays local (not a repo path).
4. **Trigger - `content/commands/implement-ticket.md` Phase 8**, after the main commit block, before `push`. The telemetry block reuses already-resolved `DEVELOPER`/`SO_NAME`/`SO_EMAIL`. The target checkout depends on the path: `$REPO` on fan-out (already on the feature branch after the line-977 `git checkout`), or `$WORKTREE_PATH` on single-engineer paths (see §Phase 8 branch-targeting model above). "PR update" is covered because Phase 8 runs per-invocation, capturing session lines accumulated since the last run. PRs opened outside `/implement-ticket` are not covered (documented limitation).
5. **Privacy/consent - `commit_telemetry` toggle in `.agentic/config.json`, default `true`** ("bake it in"); set `false` to opt out. Gated on confirmed identity, so first-session/provisional users never accidentally commit.
6. **No-handle / provisional - skip silently.** Same soft-fail posture as the existing `Developer:` trailer suppression; `[ -f $SESSION_LOG_FILE ]` guards the first-run no-file case.

## Binding implementation spec (for the future session)

- **`.gitignore`:** add `!.agentic/session-log/` carve-out + replacement comment; remove the stale "intentionally local-only" comment.
- **`content/commands/implement-ticket.md` Phase 8:** insert the session-log commit shell block from the §Phase 8 branch-targeting model section above. The block is path-aware: resolves `$PR_CHECKOUT` from either `$REPO` (fan-out, already on feature branch after line-977 checkout) or `$WORKTREE_PATH` (single-engineer paths, from engineer return summary); copies session-log file into worktree when `PR_CHECKOUT != REPO` since `git add` cannot stage files outside the work tree; applies HEAD-branch guard before committing; soft-fails with a one-line warning on mismatch; only pushes on single-engineer paths (fan-out push handled in its own block). Conductor must capture `WORKTREE_PATH` from engineer return before Phase 8.
- **`.agentic/config.json`:** add `"commit_telemetry": true`.
- **`content/rules/conventions.md`:** §Session Context "Per-developer session log" paragraph - change "NOT committed" to the committed-via-carve-out description; §Project Config - add the `commit_telemetry` toggle row.
- **`content/sections/` / METHODOLOGY.md §Events log:** update the "NOT committed to git" / "would require a separate mechanism" TEAM-dimension note to match.
- **`content/commands/init-project.md` Step 6f:** add `"commit_telemetry": true` to the `.agentic/config.json` seed block (there is NO `bin/init-project` binary; init-project is a command and seeds config.json in Step 6f at ~line 838). Add the toggle to the seed block and to the toggle-documentation list (~line 853) and the `/agentic-status` print (~line 1140).
- **Adapter rebuild:** any `content/**` edit requires rebuilding all 8 adapters + (if `content/sections/` touched) regenerating `scripts/.methodology-baseline.sha256`; verify the rebuild commit touches ONLY generated paths (revert hazard).

## Known limitations (carry into implementation)

- **Eventual consistency is structural:** the Phase 8 commit contains only sessions that ended BEFORE it runs (prior sessions). The current session's line is written by the Stop hook at session end and lands in the next ticket's Phase 8 commit. Not fixable without a live-telemetry write model.
- Squash loses the commit boundary (data survives, attribution commit does not).
- PRs outside `/implement-ticket` get no telemetry commit.
- Single-engineer path requires `WORKTREE_PATH` from the engineer return; if absent (old brief format), telemetry commit soft-fails - no data loss, not committed on that invocation.
- Adapter-rebuild contamination risk - never skip the `git status` gate after rebuild.

## Open questions - RESOLVED (operator decision 2026-06-12: "do it")

1. **`commit_telemetry` default = `true`.** RESOLVED. The operator's directive is affirmative ("bake into the methodology"), so default-on is correct. The reference repo (`Space-Dinosaurs/DinoStack`) gets the toggle in its `.agentic/config.json` set to `true`; the confirmed-identity gate prevents accidental commits for unconfigured users; the opt-out is the safety valve.
2. **init-project seeding surface.** RESOLVED. There is no `bin/init-project` binary - the `/init-project` COMMAND (`content/commands/init-project.md` Step 6f) seeds `.agentic/config.json`. Add `"commit_telemetry": true` to that seed block + the toggle docs + the `/agentic-status` print.
3. **Global (individual) kill-switch = DESCOPED for MVP.** RESOLVED. Ship the per-project `.agentic/config.json` toggle only. A `~/.agentic/` global opt-out is NOT built in this pass (conservative scope; minimizes blast radius). Captured as a possible follow-up if individual-level privacy becomes a requirement.

No remaining blockers.

## Decomposition (preliminary - re-plan at implementation)

Architect suggested ~4 Elevated units: (1) `.gitignore` + Phase 8 block, (2) config toggle + conventions/METHODOLOGY docs, (3) `content/commands/init-project.md` seed, (4) adapter rebuild + baseline. Likely Brief-tier. QA: `qa_skip: pure-backend-library` (shell/config/prose; verify via CLI + filesystem smoke tests - 13 listed in the architect output).
