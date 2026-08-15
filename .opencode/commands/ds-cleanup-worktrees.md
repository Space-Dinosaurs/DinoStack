---
description: "/ds-cleanup-worktrees"
agent: build
---
# /ds-cleanup-worktrees

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Clean up stale git worktrees and local branches in the current repository. Covers both worktree removal and local branch prune - see `content/references/worktree-lifecycle.md` §Branch prune for the canonical branch-prune command block.

`bin/ds-reap-worktrees` is the executable, machine-invocable form of the classify -> lock/dirty -> merge-evidence -> disposition predicate this command runs in Step 2 below - it delegates classification to `classify_entry` and the LOCKED/DIRTY/branch-evidence decision to `disposition_for` itself (both `bin/tests/worktree_model.py`), the single normative definition of both, so it can no longer diverge from a hand-authored predicate the way a bespoke reimplementation could (a round-2 Skeptic Critical/Major review caught exactly that divergence in an earlier version of this command file and required this delegation). It additionally applies three safety floors a bare classify/disposition read does not: a self-worktree guard (never reaps the worktree the invoking process is running inside), an age floor (default 24h - a worktree can be unlocked yet still belong to a resumable session), and a gitignored-content guard - a worktree can report CLEAN under plain `git status --porcelain` while holding irreplaceable ignored content, e.g. `.agentic/plan.md`. By OPERATOR DECISION (round 3) this guard is a PROTECTED DENYLIST, not a fail-safe allowlist: `docs/planning/**`, `.env*`, and `*.local` block removal; everything else ignored - including generated adapter output (`.kimi/`, `.codex/`, `.claude/skills/`) - is disposable and does not block (a round-2 fail-safe allowlist shipped first and measured `removed=0` against the live checkout). `.agentic/**` is a special case with INVERTED polarity (round-4 correction): protected by default inside `.agentic/` - EXCEPT a small named disposable set (routine telemetry like `events.jsonl`, `wrap/`, `codex-prompt-generation/`, `hud/`, cache dirs). Round 3's blanket `.agentic/**` protection also measured `removed=0`, because this repo dogfoods its own methodology and every worktree that has ever hosted an agent accumulates routine telemetry; `.agentic/**` was only ever meant to protect AUTHORED work (plans, notes, decisions), not session logs. Before any worktree is actually removed, its `.agentic/events.jsonl` (if present) is salvaged into the primary repo's `.agentic/reaped-telemetry/` first and the copy is verified - a failed salvage blocks removal rather than becoming a silent deletion. `--strict-ignored` restores the round-2 allowlist behavior UNCHANGED (including for `.agentic/`, where it still blocks `events.jsonl` exactly like round 2) for an operator who wants the more conservative (and less effective) polarity instead. These floors (self-worktree, age, gitignored-content) can only make the tool remove FEWER worktrees than the bare `disposition_for` predicate alone would, never more. See `bin/ds-reap-worktrees`'s own module docstring for the full rationale, disposable-set definitions, and salvage mechanics. Both `ds-base-sync`'s advisory note and the SessionStart worktree-count nudge invoke it in `--count-only` mode (a raw count, zero network, zero per-entry evaluation - not a removal forecast).

**The `SKIP_UNPROVEN` class and `--archive-unproven` (round 5).** A worktree can pass every other gate (clean, unlocked, past the age floor, not self, not protected-content) and STILL never resolve, because its branch carries real, unmerged commits that were never pushed anywhere and have no matching PR - `disposition_for` correctly refuses to call that `ELIGIBLE` (the round-4 measurement against this repo's own live checkout found this to be the dominant remaining blocker once the `.agentic/` correction landed: `skipped-protected-content` dropped to 0, but `removed` stayed 0 because most of the remaining worktrees carry exactly this class of branch - default-named `worktree-agent-<id>` branches and legacy `ds-round8`..`ds-round12` rework branches). Left alone, `SKIP_UNPROVEN` worktrees accumulate indefinitely - nothing ever resolves them. `--archive-unproven` (OPT-IN, NEVER the default) extends this repo's own precedent for the identical problem on BRANCHES - `bin/ds-branch-prune` archived 75 unprovable branches into one verified `git bundle` before deleting them (DS-153, `.agentic/branch-archive/`) - to WORKTREES, but only to an explicit whitelist within `SKIP_UNPROVEN`, never the whole bucket (round 6 correction): only `SKIP_NOT_PUSHED` and `SKIP_AMBIGUOUS_NO_PR` qualify - `SKIP_PR_OPEN` (a hard safety override) and `SKIP_LS_REMOTE_ERROR` (a transient failure) are NEVER archived, even with the flag set. Separately, a PER-ENTRY `gh pr list` query failure (auth fine, that one call errored/timed out/rate-limited) is reported as its OWN `SKIP_PR_QUERY_ERROR` outcome - never `SKIP_UNPROVEN` at all - so it is never eligible for `--archive-unproven` in the first place, not merely excluded from the whitelist: a query failure is a distinct fact from "no PR exists" and must never be treated as proof of anything (round-7/8 correction; see `bin/ds-reap-worktrees`'s own module docstring, Removal predicate gate 9). It also refuses to run at all in degraded gh mode (`--no-gh`, or `gh` unavailable/unauthenticated) - without PR evidence it cannot distinguish a genuinely-unprovable branch from one behind an open PR. For every whitelisted entry, it archives the full branch into a verified `git bundle` under `.agentic/worktree-archive/` (never removing anything if the bundle create or verify fails), salvages telemetry (same guard as the plain removal path - a failed salvage also blocks removal), then removes the worktree and prints the exact restore command. It removes the worktree only, never the branch - branch deletion remains `bin/ds-branch-prune`'s job. `.agentic/worktree-archive/` is gitignored (same `/.agentic/*` umbrella as `.agentic/reaped-telemetry/`, no new carve-out) and grows unbounded - pruning it is the operator's own responsibility, exactly like `.agentic/branch-archive/`. See `bin/ds-reap-worktrees`'s own module docstring ("Archiving unproven branches") for the full mechanism.

**Sweeping multiple repos: `bin/ds-reap-all`.** `ds-reap-worktrees` operates on exactly one repo per invocation (`--repo <path>`, default cwd). `ds-reap-all` is a thin wrapper for an operator with several project checkouts: it discovers a set of repos - explicit `--repo <path>` (repeatable), a root-directory scan (positional root args, depth-1 children by default, `--depth` up to 3), or a `~/.agentic/reap-all.json` fallback (`{"roots": [...], "repos": [...]}`), consulted when neither `--repo` nor a positional root is given - then invokes `ds-reap-worktrees` once per repo sequentially, forwarding every pass-through flag (`--dry-run`, `--explain`, `--count-only`, `--no-gh`, `--min-age-hours`, `--strict-ignored`, `--archive-unproven`, `--base`) verbatim. It contains no removal logic of its own; every safety gate described above remains entirely owned by `ds-reap-worktrees` and is reused unmodified. One repo's failure (bad path, timeout, nonzero exit) never halts the sweep - it is reported and the remaining repos are still attempted.

Use proactively when worktrees are accumulating or any time you want to confirm the repo is in a clean state. **Not immediate post-merge cleanup at the default settings:** Step 2's 24h age floor means a worktree from a PR merged minutes or hours ago is reported as `SKIP_TOO_YOUNG`, not removed - the floor is a genuine safety default (an unlocked worktree can still belong to a resumable session), not a bug, and Step 2 below documents the `--min-age-hours 0` escape for an operator who wants that specific worktree gone right now. Also invoke when the user says "prune worktrees", "clean up branches", "tidy the repo", or "remove stale worktrees". Works in any git repo.

## Execution model

Run all steps directly in the conductor session via Bash - do NOT spawn background agents. Worktree cleanup is sequential and fast.

---

## Step 1: Fetch and prune metadata

```bash
git fetch origin 2>/dev/null || true
git worktree prune
```

`git fetch origin` is non-fatal - repos without a remote (local test repos, offline environments) will fail here and that is fine. Always continue. `git worktree prune` removes entries pointing to directories that no longer exist on disk.

---

## Step 2: Reap worktrees

Resolve `bin/ds-reap-worktrees`: check `$REPO_DIR/bin/ds-reap-worktrees` first (the `REPO_DIR` env var, when the operator's shell happens to have it set), else fall back to PATH. This is NOT the same mechanism `hooks/session-start-wrap.sh` uses (it resolves `AE_REPO_DIR` via `resolve_ae_repo_dir_with_fallback`, sourced relative to that script's own on-disk location - a trick this inline Bash block, run ad hoc with no stable file location of its own, cannot reproduce) or `bin/ds-base-sync` (which resolves its colocated `$SCRIPT_DIR/ds-reap-worktrees` directly, with no PATH fallback at all). `REPO_DIR` is rarely set in an interactive or conductor shell, so this almost always lands on the PATH fallback - which is exactly why every adapter's install script wires `bin/` onto PATH. This single call replaces the entire manual classify (`classify_entry`) -> lock/dirty -> merge-evidence -> disposition (`disposition_for`) walk a hand-authored version of this step used to spell out here: same normative predicate, no second copy to drift.

Derive the project's base branch the same non-interactive way the rest of the methodology does (`content/rules/conventions.md` §Base branch resolution, steps 1-3 and 5 - no interactive prompt here): a `BASE_BRANCH:` declaration in `AGENTS.md` wins; else a local `develop` branch; else a local `development` branch; else `main` (falling back to `master` if `main` does not exist locally). Pass the result explicitly via `--base` - leaving it at the tool's own `origin/main` default silently evaluates merge evidence against the wrong branch on a `develop`-based repo.

```bash
DS_REAP_BIN=""
if [[ -n "${REPO_DIR:-}" ]] && [[ -x "$REPO_DIR/bin/ds-reap-worktrees" ]]; then
  DS_REAP_BIN="$REPO_DIR/bin/ds-reap-worktrees"
elif command -v ds-reap-worktrees >/dev/null 2>&1; then
  DS_REAP_BIN="$(command -v ds-reap-worktrees)"
fi

if [[ -n "$DS_REAP_BIN" ]]; then
  # Declaration extraction is anchored to end-of-line (modulo an optional
  # surrounding backtick/quote/trailing period) so a prose sentence that
  # merely MENTIONS `BASE_BRANCH:` (e.g. "BASE_BRANCH: resolution rules.")
  # can never match - only a genuine one-token declaration line can reach
  # end-of-line before a second word appears. Fenced code blocks are
  # stripped first so an illustrative example inside a ```-fence can never
  # beat a real declaration via `head -1`. Quotes and a leading `origin/`
  # prefix (an operator writing `BASE_BRANCH: origin/develop`) are both
  # stripped from the extracted value before use, since this value is
  # concatenated after our own `origin/` prefix below (round-3 Skeptic
  # Minor 2).
  DS_BASE_BRANCH="$(awk '/^```/{f=!f;next} !f' AGENTS.md 2>/dev/null \
    | grep -oE '`?BASE_BRANCH:[[:space:]]*"?[A-Za-z0-9_./-]+"?`?\.?[[:space:]]*$' \
    | head -1 \
    | sed -E 's/^`?BASE_BRANCH:[[:space:]]*//; s/"//g; s/`//g; s/\.[[:space:]]*$//; s/^origin\///')"
  if [[ -z "$DS_BASE_BRANCH" ]] && git show-ref --verify --quiet refs/heads/develop; then
    DS_BASE_BRANCH="develop"
  elif [[ -z "$DS_BASE_BRANCH" ]] && git show-ref --verify --quiet refs/heads/development; then
    DS_BASE_BRANCH="development"
  fi
  if [[ -z "$DS_BASE_BRANCH" ]]; then
    DS_BASE_BRANCH="main"
    git show-ref --verify --quiet refs/heads/main || DS_BASE_BRANCH="master"
  fi

  # Validate the resolved ref actually exists on origin before using it -
  # a bogus/misresolved base (malformed declaration, typo, renamed branch)
  # otherwise fails SAFE inside ds-reap-worktrees (merge evidence silently
  # reads "unmerged" for everything, `removed=0`, no error) which is the
  # same silent-no-op operator-attention defect the round-1 age-floor NOTE
  # was added to close (round-3 Skeptic Minor 2).
  if ! git rev-parse --verify --quiet "origin/$DS_BASE_BRANCH" >/dev/null 2>&1; then
    echo "WARNING: resolved base branch 'origin/$DS_BASE_BRANCH' does not exist on origin - check AGENTS.md's BASE_BRANCH: declaration (or the local develop/development/main fallback) for a typo or a renamed branch. Skipping the reap this session rather than running it against a base that would silently evaluate every branch as unmerged (removed=0 with no explanation)." >&2
  else
    # Default: actually remove, with a full per-entry breakdown. If the
    # operator asked for a preview/dry run instead ("show me what would be
    # removed", "don't delete anything yet"), add --dry-run - --explain
    # stays on either way so the report below has real detail to work from.
    # `--explain` alone does NOT imply `--dry-run`: without --dry-run this
    # invocation deletes.
    "$DS_REAP_BIN" --base "origin/$DS_BASE_BRANCH" --explain
    DS_REAP_STATUS=$?
    if [[ "$DS_REAP_STATUS" -ne 0 ]]; then
      echo "ERROR: ds-reap-worktrees exited $DS_REAP_STATUS - do NOT treat this as a completed reap. Stop and report the failure output above instead of proceeding to Steps 3/4 as though removal succeeded." >&2
      exit "$DS_REAP_STATUS"
    fi
  fi
else
  echo "WARNING: ds-reap-worktrees not found (REPO_DIR/bin or PATH) - re-run your harness's DinoStack install script (<repo>/.claude/install.sh for Claude Code, the equivalent script under your adapter directory otherwise) to wire bin/ onto PATH. Worktree reap skipped this session." >&2
fi
```

This removes worktrees only - both isolation (`.claude/worktrees/*`) and feature/conductor-created (`.agentic/worktrees/*`) entries, per `classify_entry`'s path-prefix classification - never a branch. Branch deletion is Step 3's job, below, on its own separate proof: a bare `MERGE_EVIDENCE=merged`/PR-`MERGED` read is sufficient to reclaim a worktree (`git worktree remove` does not destroy commits) but is NOT sufficient evidence for `git branch -D` (DS-153 Amendment B1 - see the Notes section below). An `UNMANAGED` entry (a bare-repo entry, a path outside this repo's own host, or a path under neither admin directory, e.g. `evals/.worktrees/wt-*`) is always reported, never touched.

**The default 24h age floor and its escape.** A worktree younger than `--min-age-hours` (default 24) resolves `SKIP_TOO_YOUNG`, never `REMOVE`, regardless of how otherwise-eligible it is - the binary itself now prints an unconditional `NOTE:` line naming the count and the escape whenever that bucket is nonzero, so a `removed=0` run is never left unexplained. If the operator explicitly wants a specific, just-merged worktree gone right now, pass `--min-age-hours 0` for that invocation. State the tradeoff when doing so: this removes the protection against reaping a concurrent session's still-in-flight worktree (unlocked does not mean idle - a resumable session can leave its worktree unlocked between tool calls). Otherwise leave every flag but `--base`/`--explain`/`--dry-run` at its default.

---

## Step 3: Prune stale local branches

Run the canonical branch prune from `content/references/worktree-lifecycle.md §Branch prune (stale local branches)` - `bin/ds-branch-prune` (DS-153). It deletes a local branch only when a four-layer, first-match-wins subsumption predicate (ancestry, squash-patch equivalence, tip-subsumption, content-on-main) proves that branch's tip content is on `origin/main`; absence of proof is always `SKIP_UNPROVEN`, reported for manual review, never force-deleted. When `gh` is unavailable or errors, the predicate degrades to ancestry and content-on-main evidence only (L1/L4) - a strict subset, never a superset, of what a full run would delete - and the run names the degradation rather than staying silent.

---

## Step 4: Final state report

```bash
git worktree prune
git worktree list
```

Report a summary:
- What was removed (worktree path + branch name for each)
- What was skipped (branch name + reason: dirty, PR open, no PR, too young, unknown type)
- If Step 2 printed a `NOTE: N worktree(s) skipped because they are younger than the ... age floor` line, surface it prominently in this summary rather than letting `removed=0` stand unexplained - name the count and the `--min-age-hours 0` escape
- Final worktree count

---

## Notes

- **Safety first:** never remove a worktree with uncommitted changes without explicit user confirmation. `disposition_for`'s dirty check in Step 2 is not optional.
- Never remove a feature worktree whose PR is still OPEN. For a live worktree's own removal (Step 2, `disposition_for`), a MERGED PR alone remains sufficient evidence - `git worktree remove` does not destroy commits, so the worst case is already covered by `SKIP_DIRTY`/`SKIP_LOCKED` (DS-153 Amendment B1). This does NOT extend to local branch DELETION: `bin/ds-branch-prune` (Step 3, `disposition_for_orphan_branch`) treats a bare MERGED PR as terminally insufficient (`SKIP_PR_MERGED_UNPROVEN`) and requires the subsumption predicate to prove the tip's content is on `origin/main` before deleting.
- The main worktree (first entry in `git worktree list`) is always skipped.
- Works on the repository in the current working directory - not project-specific.
- If `gh` is not available, flag feature worktrees for manual review and continue.
