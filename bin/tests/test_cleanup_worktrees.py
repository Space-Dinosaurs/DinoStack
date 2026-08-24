#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-cleanup-worktrees. Builds synthetic git
         repositories (with a real bare `origin` remote) in tmp_path and
         drives the CLI end-to-end via subprocess, covering the round-2
         rewrite: the removal predicate delegated to `worktree_model.
         disposition_for` (never a second copy of evidence semantics), the
         self-worktree and age-floor safety guards, the gitignored-content
         guard, `--count-only`, and the dry-run/degraded mode-string
         composition bug class documented in this repo's MEMORY.md
         ("Reporting fields are a separate axis from behavior" -
         bin/ds-branch-prune shipped a bug printing mode=live during a
         dry run).

         Every scenario passes `--min-age-hours 0` UNLESS it is
         specifically exercising the age floor - every worktree this suite
         creates is freshly minted (mtime = now), so the real default
         (24h) would otherwise mask every other gate under test.

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-cleanup-worktrees (module under test, invoked as a
               subprocess CLI); real `git` CLI (subprocess, incl.
               `git worktree add/lock/prune`). No REAL `gh` invocation in
               any scenario - every scenario either runs with `--no-gh`
               (no network/auth dependency at all) or, for the
               `--archive-unproven` scenarios that now require gh evidence
               to run (round 6), against a `_fake_gh_dir`-generated stub
               `gh` executable prepended onto PATH (a tiny bash script
               answering `gh auth status`/`gh pr view` locally) - never
               real `gh` binary, network, or auth state.

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`).

Failure modes: each scenario builds its own isolated tmp_path repo/origin
               pair; no real DinoStack checkout, worktree, or branch state
               is ever touched by this file.

Performance: each scenario performs a handful of real `git` subprocess
             calls (init, bare-clone remote, worktree add/lock/prune) plus
             one `ds-cleanup-worktrees` subprocess invocation. Sub-second per
             test.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ds-cleanup-worktrees"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib.machinery as _ilm  # noqa: E402
import importlib.util as _ilu  # noqa: E402

_loader = _ilm.SourceFileLoader("ds_cleanup_worktrees", str(SCRIPT))
_spec = _ilu.spec_from_loader("ds_cleanup_worktrees", _loader)
ds_cleanup_worktrees = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_loader.exec_module(ds_cleanup_worktrees)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}\n{proc.stdout}"
    return proc


def init_repo_with_origin(tmp_path: Path, name: str = "repo") -> tuple:
    """Returns (repo_path, origin_path). `repo` has a real bare `origin`
    remote and one commit on `main`, pushed."""
    origin = tmp_path / f"{name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)

    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, origin


def commit_gitignore_on_main(repo: Path, pattern: str) -> None:
    """Commits a `.gitignore` containing `pattern` directly onto `repo`'s
    checked-out `main` branch and pushes it, BEFORE any worktree branch is
    created from it - so a worktree branched afterward inherits the
    ignore rule with ZERO unique commits of its own (preserving the
    ancestor-of-base / zero-unique-commits precondition other scenarios in
    this file rely on)."""
    (repo / ".gitignore").write_text(pattern)
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "add gitignore")
    _git(repo, "push", "-q", "origin", "main")


def add_worktree(repo: Path, rel_path: str, branch: str, *, push: bool = False) -> Path:
    """Creates a new branch + worktree at <repo>/<rel_path>. When `push` is
    True, pushes the branch to origin (so ls-remote resolves "pushed")."""
    wt_path = repo / rel_path
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(wt_path), "-b", branch)
    if push:
        _git(repo, "push", "-q", "-u", "origin", branch)
    return wt_path


def run_reap(
    repo: Path,
    *,
    dry_run: bool = True,
    no_gh: bool = True,
    base: str = "main",
    min_age_hours: str = "0",
    extra=None,
    cwd: Path = None,
    gh_dir: Path = None,
    git_dir: Path = None,
):
    """`gh_dir`, when given, is prepended onto PATH (round-6: `gh_dir` is
    normally the output of `_fake_gh_dir` below) so `_gh_available()`
    resolves a real, present, authenticated `gh` without any actual
    network/API dependency - required for any `--archive-unproven`
    scenario now that it refuses to run in degraded gh mode (Skeptic
    Major 2). `git_dir`, when given (normally the output of
    `_fake_git_dir_remove_fails` below), is prepended ahead of `gh_dir` so a
    stub `git` that intercepts only `git worktree remove` (passing every
    other invocation through to the real binary) can force a removal
    failure deterministically."""
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--explain"]
    if dry_run:
        cmd.append("--dry-run")
    if no_gh:
        cmd.append("--no-gh")
    if min_age_hours is not None:
        cmd += ["--min-age-hours", min_age_hours]
    if extra:
        cmd += extra
    env = None
    prepend_dirs = [d for d in (git_dir, gh_dir) if d is not None]
    if prepend_dirs:
        env = dict(os.environ)
        prefix = os.pathsep.join(str(d) for d in prepend_dirs)
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None, env=env)


def _fake_gh_dir(tmp_path: Path, *, pr_state: str = "", pr_list_fails: bool = False) -> Path:
    """Round-6 (extended by round-N): a directory containing a stub `gh`
    executable answering `gh auth status` with success and `gh pr list
    --head <branch> --state all --json number,state` (NO `--limit` - the
    round-N Major fix removed it from the real script; see `_pr_state`'s
    docstring for why) per `pr_list_fails`/`pr_state`:

      - `pr_list_fails=True`: the `pr list` invocation exits nonzero (a
        stderr message, no stdout) - simulates a transient query failure
        (rate limit, auth hiccup, network blip) that is DISTINCT from "no
        PR exists" - see `_pr_state`'s own docstring for why this must
        never be collapsed into a `pr_state="NONE"` reading. `gh auth
        status` still succeeds, matching the real-world shape of the bug:
        the PROCESS-level gh-availability gate cannot see this, only a
        PER-ENTRY query can fail this way.
      - `pr_state` non-empty: returns a single-row JSON array
        `[{"number": 1, "state": "<pr_state>"}]`, matching a real `gh pr
        list` for a branch with exactly one PR in that state.
      - `pr_state` empty (default) and `pr_list_fails=False`: returns `[]`,
        matching a real `gh pr list` for a branch with no PR at all.

    Zero real network/API dependency in any case - used only by scenarios
    that need `--archive-unproven` to actually run, since it refuses in
    degraded gh mode (see `--archive-unproven requires PR evidence`).

    For a MULTI-row response (more than one PR on the same head branch),
    use `_fake_gh_dir_multi_pr` below instead."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    if pr_list_fails:
        pr_list_body = 'echo "gh: API rate limit exceeded" >&2; exit 1'
    elif pr_state:
        pr_list_body = f"echo '[{{\"number\": 1, \"state\": \"{pr_state}\"}}]'; exit 0"
    else:
        pr_list_body = "echo '[]'; exit 0"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\n'
        f'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then {pr_list_body}; fi\n'
        "exit 1\n"
    )
    gh.chmod(0o755)
    return bin_dir


def _fake_gh_dir_multi_pr(tmp_path: Path, rows) -> Path:
    """Round-N Major regression coverage: a stub `gh` returning MULTIPLE
    rows for a single `gh pr list --head <branch> --state all --json
    number,state` call, in the EXACT order given by `rows` (a list of
    `(number, state)` tuples) - mirroring a real `gh pr list`'s own
    CREATED_AT DESC ordering, where the caller controls which row is
    "newest" by list position. This is the fixture that pins the fix: the
    tool under test must select `OPEN` from anywhere in this list, never
    merely `rows[0]`.

    Also asserts the REAL script's argv contains no `--limit` - a stub
    honoring a `--limit N` the real command still (incorrectly) passed
    would silently truncate `rows` before this fixture's multi-row
    property could ever matter, masking a regression of the `--limit 1`
    removal itself. The stub does this by ignoring any `--limit` flag
    entirely (always returns the full `rows` list) - a real `gh` would
    NOT ignore `--limit`, so this fixture's own end-to-end test would
    still catch a caller that reintroduces `--limit 1` (a truncated
    single-row array would no longer contain a later-listed OPEN row that
    an untruncated call requires for the assertion to hold, in the
    `[{CLOSED},{OPEN}]`/`[{MERGED},{OPEN}]` orderings this fixture is used
    to build)."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    payload = "[" + ", ".join(f'{{"number": {n}, "state": "{s}"}}' for n, s in rows) + "]"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\n'
        f"if [ \"$1\" = \"pr\" ] && [ \"$2\" = \"list\" ]; then echo '{payload}'; exit 0; fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)
    return bin_dir


def _fake_git_dir_remove_fails(tmp_path: Path) -> Path:
    """Round-N Minor (a) regression coverage: a directory containing a stub
    `git` that intercepts ONLY a `worktree remove` invocation (anywhere in
    its argv, so it matches regardless of a preceding `-C <repo>`) and
    fails it deterministically, passing every other invocation through to
    the REAL `git` binary (resolved once, at generation time, via
    `shutil.which` - so the stub's own `exec` call can never recurse into
    itself even though its directory is prepended onto PATH ahead of the
    real `git`)."""
    real_git = shutil.which("git")
    assert real_git, "real `git` must be on PATH to build this stub"
    bin_dir = tmp_path / "fakegitbin"
    bin_dir.mkdir(exist_ok=True)
    git_stub = bin_dir / "git"
    git_stub.write_text(
        "#!/usr/bin/env bash\n"
        'args=("$@")\n'
        'for i in "${!args[@]}"; do\n'
        '  if [ "${args[$i]}" = "worktree" ] && [ "${args[$((i+1))]}" = "remove" ]; then\n'
        '    echo "fatal: simulated worktree remove failure" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "done\n"
        f'exec "{real_git}" "$@"\n'
    )
    git_stub.chmod(0o755)
    return bin_dir


def outcomes(stdout: str) -> dict:
    """Maps worktree path -> outcome string from the --explain block."""
    result = {}
    in_explain = False
    for line in stdout.splitlines():
        if line.strip() == "-- per-entry --":
            in_explain = True
            continue
        if in_explain and "] branch=" in line:
            path = line.split(" [", 1)[0]
            result[path] = line.split(": ", 1)[1].strip()
    return result


def summary_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("ds-cleanup-worktrees:"):
            return line
    return ""


def bucket_counts(line: str) -> dict:
    """Parses `key=value` pairs out of a summary line into a dict of ints,
    skipping the non-numeric `base=`/`mode=` fields (mode can itself
    contain `=`-free commas/parens, so only fields matching `key=<digits>`
    are kept)."""
    counts = {}
    for tok in line.split():
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        if val.isdigit():
            counts[key] = int(val)
    return counts


def worktree_paths(repo: Path) -> set:
    proc = _git(repo, "worktree", "list", "--porcelain")
    paths = set()
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(line[len("worktree ") :])
    return paths


# --------------------------------------------------------------------------
# 1. Branch never pushed to origin WITH unique commits -> SKIP_UNPROVEN,
#    never REMOVE (round-2 Major 1: v1's bespoke "branch-gone-from-origin"
#    leg alone is no longer sufficient - the shared normative
#    disposition_for maps ls_remote_status="not_pushed" to a terminal SKIP,
#    never ELIGIBLE, and this tool no longer shadows that with a second,
#    more permissive copy of the semantics).
# --------------------------------------------------------------------------


def test_unpushed_branch_with_unique_commits_is_unproven(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-1", "worktree-agent-1", push=False)
    (wt / "extra.txt").write_text("diverging local work - never pushed anywhere\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unpushed extra commit")

    # no_gh=False so `git ls-remote` genuinely runs and resolves
    # "not_pushed" -> SKIP_NOT_PUSHED specifically (a --no-gh run
    # correctly degrades this same leg to "not_checked" -> the more
    # generic SKIP_AMBIGUOUS_NO_PR fallback instead - both are SKIP_UNPROVEN
    # on display, but this scenario is testing the ls-remote leg itself).
    # gh_dir pins the PR-state leg to a deterministic, genuine "no PR"
    # answer (round-N fix): without it, this scenario's outcome depends on
    # whether the machine running the suite happens to have a real,
    # authenticated `gh` on PATH - and, if so, on that `gh pr list` call
    # failing (this is not a real GitHub repo) now correctly resolving to
    # `SKIP_PR_QUERY_ERROR` rather than being silently swallowed as before.
    proc = run_reap(repo, dry_run=False, no_gh=False, gh_dir=_fake_gh_dir(tmp_path))
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_NOT_PUSHED)"
    # Never removed - the branch's sole copy of this work is this worktree.
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 1b. Same unpushed-with-unique-commits scenario, but genuinely offline
#     (--no-gh) - the ls-remote leg degrades to "not_checked" rather than
#     being queried, so the fallback is the more generic
#     SKIP_AMBIGUOUS_NO_PR - still SKIP_UNPROVEN on display, never REMOVE.
#     Pins round-2 Major 4's "--no-gh must suppress ls-remote too".
# --------------------------------------------------------------------------


def test_unpushed_branch_with_unique_commits_is_unproven_offline(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-1c", "worktree-agent-1c", push=False)
    (wt / "extra.txt").write_text("diverging local work - never pushed anywhere\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unpushed extra commit")

    proc = run_reap(repo, dry_run=False, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_AMBIGUOUS_NO_PR)"
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 2. Branch never pushed but ZERO unique commits (identical to base) ->
#    REMOVE via ancestor-of-base. This is the trivially-safe case: the
#    branch carries no content base doesn't already have, so removing the
#    WORKTREE (never the branch itself) cannot lose anything.
# --------------------------------------------------------------------------


def test_unpushed_branch_zero_unique_commits_removed_via_ancestor(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-1b", "worktree-agent-1b", push=False)
    # No commits added - the branch tip is exactly `main`'s tip.

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 3. Branch pushed AND ancestor of base -> REMOVE via ancestor-of-base.
# --------------------------------------------------------------------------


def test_pushed_ancestor_branch_removed_via_ancestor_of_base(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-2", "feature/already-merged", push=True)
    # No new commits on the branch - it is exactly `main`'s tip, i.e. an
    # ancestor of base by construction.

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 4. Dirty worktree -> SKIP_DIRTY, regardless of otherwise-resolvable
#    branch state. Never removed under any circumstance.
# --------------------------------------------------------------------------


def test_dirty_worktree_never_removed(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-3", "worktree-agent-3", push=False)
    (wt / "uncommitted.txt").write_text("dirty\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_DIRTY"
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 5. Locked worktree whose directory still exists -> SKIP_LOCKED, never
#    unlocked or force-removed (the harness-lock guardrail).
# --------------------------------------------------------------------------


def test_locked_worktree_with_directory_never_removed(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-4", "worktree-agent-4", push=False)
    _git(repo, "worktree", "lock", str(wt))

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_LOCKED"
    assert str(wt) in worktree_paths(repo)

    # Confirm it is still genuinely locked afterward - this tool must never
    # call `git worktree unlock` on a directory that still exists.
    list_proc = _git(repo, "worktree", "list", "--porcelain")
    assert "locked" in list_proc.stdout


# --------------------------------------------------------------------------
# 6. Locked worktree whose directory is already gone -> SKIP_MISSING_LOCKED
#    on a dry run, and reclaimed (unlocked + pruned) on a real run - the
#    ONLY case the guardrail permits an unlock.
# --------------------------------------------------------------------------


def test_locked_but_directory_missing_is_reclaimed(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-5", "worktree-agent-5", push=False)
    _git(repo, "worktree", "lock", str(wt))
    shutil.rmtree(wt)

    dry_proc = run_reap(repo, dry_run=True)
    assert dry_proc.returncode == 0, dry_proc.stderr
    dry_result = outcomes(dry_proc.stdout)
    assert dry_result[str(wt)] == "SKIP_MISSING_LOCKED"
    # A dry run must not have unlocked or pruned anything.
    assert str(wt) in worktree_paths(repo)
    # pruned-admin is 0 under --dry-run (round-2 Minor c: it reports an
    # ACTION TAKEN, never a candidate count) even though a missing-locked
    # entry is present.
    assert "pruned-admin=0" in summary_line(dry_proc.stdout)

    real_proc = run_reap(repo, dry_run=False)
    assert real_proc.returncode == 0, real_proc.stderr
    assert str(wt) not in worktree_paths(repo)
    assert "pruned-admin=1" in summary_line(real_proc.stdout)


# --------------------------------------------------------------------------
# 7. evals/.worktrees/* is always UNMANAGED and never removed, even with
#    an otherwise fully-resolvable branch (repo decision #203 pin).
# --------------------------------------------------------------------------


def test_evals_worktrees_never_removed(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, "evals/.worktrees/wt-1", "wt-1", push=False)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNMANAGED"
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 8. --dry-run removes nothing, even for an eligible worktree.
# --------------------------------------------------------------------------


def test_dry_run_removes_nothing(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-7", "worktree-agent-7", push=False)

    proc = run_reap(repo, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    # Still present - the outcome table shows what WOULD happen, not what did.
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 9. Mode-string composition: dry-run AND degraded are independent axes
#    that must both be visible when both hold - the exact bug class
#    ds-branch-prune shipped once (printing bare "mode=live" during a dry
#    run). --no-gh is default in this suite's run_reap helper, so any
#    dry-run invocation must show BOTH "degraded" and "dry-run".
# --------------------------------------------------------------------------


def test_mode_string_composes_both_axes(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-8", "worktree-agent-8", push=False)

    proc = run_reap(repo, dry_run=True, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    line = summary_line(proc.stdout)
    assert "mode=degraded (gh unavailable), dry-run" in line, line


# --------------------------------------------------------------------------
# 10. CONDUCTOR_CREATED classification (.agentic/worktrees/) resolves via
#     the same predicate as ISOLATION.
# --------------------------------------------------------------------------


def test_conductor_created_worktree_removed_same_predicate(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".agentic/worktrees/some-feature", "feature/some-feature", push=False)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 11. --repo pointing to a non-git directory is a usage error (exit 1),
#     never a silent no-op.
# --------------------------------------------------------------------------


def test_non_git_repo_is_usage_error(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    proc = run_reap(not_a_repo, dry_run=True)
    assert proc.returncode == 1
    assert "not a git repository" in proc.stderr


# --------------------------------------------------------------------------
# 12. (round-2 Major 2a) Self-worktree guard: invoking the tool with cwd
#     INSIDE a worktree that is otherwise trivially REMOVE-eligible must
#     never remove it. This is the exact incident a v1 dry run reproduced -
#     the tool flagged its own live worktree as REMOVE.
# --------------------------------------------------------------------------


def test_self_worktree_never_removed_even_when_otherwise_eligible(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-self", "worktree-agent-self", push=False)
    # Zero unique commits - otherwise ancestor-of-base REMOVE-eligible, per
    # scenario 2 above. Invoked with cwd INSIDE the worktree itself.

    proc = run_reap(repo, dry_run=False, cwd=wt)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_SELF"
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 13. (round-2 Major 2b) Age floor: a worktree younger than --min-age-hours
#     is never removed regardless of how otherwise-eligible it is. Default
#     run_reap() passes --min-age-hours 0 (bypassing the floor for every
#     OTHER scenario in this file); this scenario explicitly asserts the
#     floor itself using a non-zero threshold against a freshly-created
#     (mtime = now) worktree.
# --------------------------------------------------------------------------


def test_age_floor_blocks_a_young_otherwise_eligible_worktree(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-young", "worktree-agent-young", push=False)
    # Zero unique commits - otherwise ancestor-of-base REMOVE-eligible.

    proc = run_reap(repo, dry_run=False, min_age_hours="24")
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_TOO_YOUNG"
    assert str(wt) in worktree_paths(repo)

    # An explicit --min-age-hours 0 on the SAME (now slightly older, but
    # still well under 24h) worktree clears the floor and resolves REMOVE -
    # proving this is genuinely the age gate and not a permanent block.
    proc2 = run_reap(repo, dry_run=False, min_age_hours="0")
    assert proc2.returncode == 0, proc2.stderr
    result2 = outcomes(proc2.stdout)
    assert result2[str(wt)] == "REMOVE (ancestor-of-base)"


# --------------------------------------------------------------------------
# 14. (round-3 operator decision) DEFAULT mode is now a PROTECTED DENYLIST:
#     `.agentic/**` blocks removal (SKIP_PROTECTED_CONTENT), even though
#     `git status --porcelain` (no --ignored flag) reports the worktree as
#     CLEAN. Reproduces the exact empirical finding: a worktree holding
#     only a gitignored `.agentic/plan.md` would otherwise be silently
#     destroyed by a non-force `git worktree remove` - the highest-value
#     entry in the protected set, per the operator decision.
# --------------------------------------------------------------------------


def test_agentic_directory_content_blocks_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-ignored", "worktree-agent-ignored", push=False)
    # Zero unique commits beyond the .gitignore already on `main` -
    # otherwise ancestor-of-base REMOVE-eligible, isolating this scenario
    # to the protected-content gate alone.
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "plan.md").write_text("irreplaceable session plan\n")

    # Precondition proving the hazard: plain `git status --porcelain`
    # reports this worktree as CLEAN despite the irreplaceable content.
    plain_status = subprocess.run(
        ["git", "-C", str(wt), "status", "--porcelain"], capture_output=True, text=True
    )
    assert plain_status.stdout.strip() == "", "precondition: plain porcelain must show clean despite ignored content"

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert ".agentic/" in result[str(wt)]
    assert str(wt) in worktree_paths(repo)
    assert (wt / ".agentic" / "plan.md").exists(), "the irreplaceable file must survive"


# --------------------------------------------------------------------------
# 14b. Same fixture, nested individually-ignored file (not a wholesale
#      directory ignore) - proves the `.agentic` prefix match catches a
#      nested path too, not only the collapsed directory-form entry.
# --------------------------------------------------------------------------


def test_agentic_nested_file_blocks_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    # Only files INSIDE .agentic/ are ignored (not the directory itself),
    # so `git status --ignored=matching` reports the individual nested
    # path rather than a collapsed `.agentic/` entry.
    commit_gitignore_on_main(repo, ".agentic/*\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-nested", "worktree-agent-nested", push=False)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "plan.md").write_text("irreplaceable session plan\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert ".agentic/plan.md" in result[str(wt)]
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 14c. `docs/planning/**` and `.env*`/`*.local` are also protected.
# --------------------------------------------------------------------------


def test_docs_planning_content_blocks_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, "docs/planning/\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-planning", "worktree-agent-planning", push=False)
    (wt / "docs" / "planning").mkdir(parents=True)
    (wt / "docs" / "planning" / "roadmap.md").write_text("plan\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert str(wt) in worktree_paths(repo)


def test_env_and_local_files_block_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".env*\n*.local\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-secrets", "worktree-agent-secrets", push=False)
    (wt / ".env.local").write_text("SECRET=1\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 14d. (round-4 operator correction) The rule INSIDE `.agentic/` is
#      INVERTED relative to everywhere else: protected by default, EXCEPT
#      a named disposable set (routine telemetry, generated adapter
#      sub-dirs, cache dirs). `events.jsonl`-only content is the exact
#      case that drove round 3's `removed=0` measurement (this repo
#      dogfoods its own methodology, so every worktree accumulates it) -
#      it must now be disposable, not blocking.
# --------------------------------------------------------------------------


def test_agentic_events_jsonl_only_is_disposable_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-telemetry", "worktree-agent-telemetry", push=False)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "test"}\n')

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


@pytest.mark.parametrize(
    "rel_path,content",
    [
        (".agentic/wrap/lock", "lock\n"),
        (".agentic/codex-prompt-generation/scratch.txt", "scratch\n"),
        (".agentic/hud/worker-1.json", "{}\n"),
        (".agentic/tracker-states.json", "{}\n"),
        (".agentic/.skill-candidate-tally.json", "{}\n"),
        (".agentic/worktree-cleanup-skips.jsonl", '{"skip": true}\n'),
        (".agentic/some-other-log.jsonl", '{"line": 1}\n'),
    ],
)
def test_agentic_disposable_set_does_not_block_removal(tmp_path, rel_path, content):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-disposable", "worktree-agent-disposable", push=False)
    dest = wt / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)", f"{rel_path} should be disposable: {result[str(wt)]}"
    assert str(wt) not in worktree_paths(repo)


@pytest.mark.parametrize(
    "rel_path,content",
    [
        (".agentic/plan.md", "plan\n"),
        (".agentic/plans/roadmap.md", "plan\n"),
        (".agentic/learnings.md", "learnings\n"),
        (".agentic/decisions.md", "decisions\n"),
        (".agentic/qa.md", "qa\n"),
        (".agentic/findings-2026.md", "findings\n"),
        (".agentic/memory.md", "memory\n"),
        (".agentic/context.md", "context\n"),
        (".agentic/_wrap.md", "wrap\n"),
        (".agentic/tracker.yml", "tracker: {}\n"),
        (".agentic/branch-archive/notes.txt", "archive\n"),
        # Fail-safe default: an UNANTICIPATED new file under .agentic/ that
        # matches neither the disposable nor an explicitly-named protected
        # pattern must still block - this is the whole point of the
        # inverted-inside-.agentic polarity (a new file blocks, never
        # silently vanishes).
        (".agentic/some-brand-new-thing.txt", "unanticipated\n"),
    ],
)
def test_agentic_protected_set_still_blocks_removal(tmp_path, rel_path, content):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-protected", "worktree-agent-protected", push=False)
    dest = wt / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT"), f"{rel_path} should still block: {result[str(wt)]}"
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 14e. (round-4) Telemetry salvage: `.agentic/events.jsonl` is copied into
#      the PRIMARY repo's `.agentic/reaped-telemetry/<branch>-<ts>.jsonl`
#      BEFORE the worktree is removed, and the copy is verified non-empty.
# --------------------------------------------------------------------------


def test_salvage_success_copies_telemetry_before_removal(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-salvage-ok"
    wt = add_worktree(repo, ".claude/worktrees/agent-salvage-ok", branch, push=False)
    (wt / ".agentic").mkdir()
    payload = '{"event": "session-end", "tokens": 1234}\n'
    (wt / ".agentic" / "events.jsonl").write_text(payload)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)

    salvage_dir = repo / ".agentic" / "reaped-telemetry"
    salvaged_files = sorted(salvage_dir.glob(f"{branch}-*.jsonl"))
    assert len(salvaged_files) == 1, f"expected exactly one salvaged file, found {salvaged_files}"
    assert salvaged_files[0].stat().st_size > 0
    assert salvaged_files[0].read_text() == payload
    assert "salvaged=1" in summary_line(proc.stdout)


def test_salvage_skipped_cleanly_under_dry_run_but_reported(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-salvage-dry"
    wt = add_worktree(repo, ".claude/worktrees/agent-salvage-dry", branch, push=False)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "x"}\n')

    proc = run_reap(repo, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    # Dry run: nothing actually salvaged or removed.
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "reaped-telemetry").exists()
    assert "salvaged=0" in summary_line(proc.stdout)
    assert "1 .agentic/events.jsonl file(s) would be salvaged" in proc.stdout


def test_reaped_telemetry_dir_is_covered_by_existing_gitignore(tmp_path):
    """Round-4 requirement: `.agentic/reaped-telemetry/` needs no new
    `.gitignore` carve-out - the existing `.agentic/*`-style umbrella
    already covers any new top-level entry under `.agentic/`."""
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    salvage_dir = repo / ".agentic" / "reaped-telemetry"
    salvage_dir.mkdir(parents=True)
    (salvage_dir / "some-branch-20260101T000000Z.jsonl").write_text('{"x": 1}\n')

    check = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", str(salvage_dir / "some-branch-20260101T000000Z.jsonl")],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, "reaped-telemetry content must already be covered by the existing .agentic ignore rule"


# --------------------------------------------------------------------------
# 14f. (round-4) Salvage FAILURE must block removal entirely - never a
#      silent deletion of the telemetry the salvage step was trying to
#      preserve. Forces a real failure (an unwritable destination
#      directory in the PRIMARY repo), not a mock.
# --------------------------------------------------------------------------


def test_salvage_failure_blocks_removal_and_reports(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-salvage-fail"
    wt = add_worktree(repo, ".claude/worktrees/agent-salvage-fail", branch, push=False)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "will-not-survive-a-bug"}\n')

    # Force the salvage destination to be uncreatable: make the PRIMARY
    # repo's own .agentic/ directory read-only so
    # mkdir(".agentic/reaped-telemetry") raises OSError.
    primary_agentic = repo / ".agentic"
    primary_agentic.mkdir(exist_ok=True)
    os.chmod(primary_agentic, 0o555)
    try:
        proc = run_reap(repo, dry_run=False)
        assert proc.returncode == 0, proc.stderr
        result = outcomes(proc.stdout)
        assert result[str(wt)].startswith("SKIP_PROTECTED_CONTENT"), result[str(wt)]
        assert "salvage-failed" in result[str(wt)]
        assert str(wt) in worktree_paths(repo), "a failed salvage must NEVER become a silent deletion"
        assert "WARNING: telemetry salvage failed" in proc.stderr
        assert "worktree NOT removed" in proc.stderr
    finally:
        os.chmod(primary_agentic, 0o755)


# --------------------------------------------------------------------------
# 15. (round-3 operator decision) DEFAULT mode treats generated adapter
#     output and the round-2 ephemeral set as DISPOSABLE - it does NOT
#     block removal, even though it would have under round-2's fail-safe
#     allowlist (`.kimi/skills/*/` is not a "build artifact" by name and
#     was exactly what drove round-2's `removed=0` measurement).
# --------------------------------------------------------------------------


def test_generated_adapter_output_does_not_block_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".kimi/skills/*/\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-adapter", "worktree-agent-adapter", push=False)
    (wt / ".kimi" / "skills" / "ds-brief").mkdir(parents=True)
    (wt / ".kimi" / "skills" / "ds-brief" / "SKILL.md").write_text("generated\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


def test_ephemeral_content_does_not_block_removal_by_default(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, "node_modules/\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-allowlisted", "worktree-agent-allowlisted", push=False)
    (wt / "node_modules").mkdir()
    (wt / "node_modules" / "some-package.js").write_text("// regenerable\n")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (ancestor-of-base)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 15b. `--strict-ignored` restores the round-2 fail-safe-allowlist
#      behavior: the SAME generated-adapter-output fixture that is
#      disposable by default now blocks, because `.kimi/skills/*/` is not
#      on the ephemeral allowlist. Proves the escape hatch genuinely
#      preserves the old, more conservative polarity end-to-end.
# --------------------------------------------------------------------------


def test_strict_ignored_restores_round2_allowlist_behavior(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".kimi/skills/*/\nnode_modules/\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-strict", "worktree-agent-strict", push=False)
    (wt / ".kimi" / "skills" / "ds-brief").mkdir(parents=True)
    (wt / ".kimi" / "skills" / "ds-brief" / "SKILL.md").write_text("generated\n")

    # Default mode: disposable, REMOVE-eligible.
    default_proc = run_reap(repo, dry_run=True)
    assert default_proc.returncode == 0, default_proc.stderr
    default_result = outcomes(default_proc.stdout)
    assert default_result[str(wt)] == "REMOVE (ancestor-of-base)"

    # --strict-ignored: NOT on the ephemeral allowlist -> blocks.
    strict_proc = run_reap(repo, dry_run=True, extra=["--strict-ignored"])
    assert strict_proc.returncode == 0, strict_proc.stderr
    strict_result = outcomes(strict_proc.stdout)
    assert strict_result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert ".kimi/skills/ds-brief/" in strict_result[str(wt)]

    # --strict-ignored on an ephemeral-allowlisted path (node_modules/)
    # still resolves REMOVE - the escape hatch is the round-2 ALLOWLIST,
    # not a blanket block-everything-ignored mode.
    wt2 = add_worktree(repo, ".claude/worktrees/agent-strict-nm", "worktree-agent-strict-nm", push=False)
    (wt2 / "node_modules").mkdir()
    (wt2 / "node_modules" / "pkg.js").write_text("// regenerable\n")
    strict_nm_proc = run_reap(repo, dry_run=True, extra=["--strict-ignored"])
    assert strict_nm_proc.returncode == 0, strict_nm_proc.stderr
    strict_nm_result = outcomes(strict_nm_proc.stdout)
    assert strict_nm_result[str(wt2)] == "REMOVE (ancestor-of-base)"


# --------------------------------------------------------------------------
# 15c. (round-4 requirement: --strict-ignored semantics UNCHANGED) The
#      round-4 `.agentic/` disposable set is a DEFAULT-mode-only bypass -
#      under --strict-ignored, `.agentic/events.jsonl` still blocks
#      exactly like round 2 (it is not on the ephemeral allowlist).
# --------------------------------------------------------------------------


def test_strict_ignored_leaves_agentic_events_jsonl_blocking_unchanged(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    wt = add_worktree(repo, ".claude/worktrees/agent-strict-agentic", "worktree-agent-strict-agentic", push=False)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "x"}\n')

    # Default mode (round 4): events.jsonl-only content is disposable now.
    default_proc = run_reap(repo, dry_run=True)
    assert default_proc.returncode == 0, default_proc.stderr
    default_result = outcomes(default_proc.stdout)
    assert default_result[str(wt)] == "REMOVE (ancestor-of-base)"

    # --strict-ignored: unchanged from round 2 - blocks, since
    # .agentic/events.jsonl is not on the ephemeral allowlist.
    strict_proc = run_reap(repo, dry_run=True, extra=["--strict-ignored"])
    assert strict_proc.returncode == 0, strict_proc.stderr
    strict_result = outcomes(strict_proc.stdout)
    assert strict_result[str(wt)].startswith("SKIP_PROTECTED_CONTENT")
    assert ".agentic/events.jsonl" in strict_result[str(wt)]


# --------------------------------------------------------------------------
# 16. (round-2 Major 4) --count-only prints only entries=N, works even
#     against a repo with NO origin remote at all - proving zero network
#     dependency (a non-count-only run against this same fixture would
#     attempt `git ls-remote` against a nonexistent origin and degrade,
#     never crash, but --count-only must not even try).
# --------------------------------------------------------------------------


def test_count_only_zero_network_dependency(tmp_path):
    repo = tmp_path / "repo-no-origin"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    add_worktree(repo, ".claude/worktrees/agent-count", "worktree-agent-count", push=False)

    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--count-only"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ds-cleanup-worktrees: mode=count-only entries=2"
    # --explain must be irrelevant/absent in this mode - no per-entry work done.
    assert "-- per-entry --" not in proc.stdout


# --------------------------------------------------------------------------
# 17. (round-2 Minor a) Bucket-sum-equals-entries invariant: every entry in
#     a mixed-outcome repo must land in exactly one reported bucket, and
#     the buckets must sum to `entries`.
# --------------------------------------------------------------------------


def test_bucket_sum_equals_entries(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)  # REMOVE-eligible
    dirty_wt = add_worktree(repo, ".claude/worktrees/agent-b", "worktree-agent-b", push=False)
    (dirty_wt / "uncommitted.txt").write_text("dirty\n")  # SKIP_DIRTY
    locked_wt = add_worktree(repo, ".claude/worktrees/agent-c", "worktree-agent-c", push=False)
    _git(repo, "worktree", "lock", str(locked_wt))  # SKIP_LOCKED
    add_worktree(repo, "evals/.worktrees/wt-x", "wt-x", push=False)  # SKIP_UNMANAGED

    proc = run_reap(repo, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    line = summary_line(proc.stdout)
    counts = bucket_counts(line)
    entries = counts.pop("entries")
    removed = counts.pop("removed")
    counts.pop("pruned-admin", None)  # action report, not a partition member
    skip_sum = sum(v for k, v in counts.items() if k.startswith("skipped-"))
    assert removed + skip_sum == entries, f"bucket sum {removed + skip_sum} != entries {entries} (line: {line})"


# --------------------------------------------------------------------------
# 18. `_run`'s subprocess timeout wrapper (round-2 Major 4) actually bounds
#     a slow command rather than blocking indefinitely - a direct unit
#     check of the wrapper function itself.
# --------------------------------------------------------------------------


def test_run_timeout_wrapper_bounds_a_slow_command():
    import importlib.machinery as _ilm
    import importlib.util as _ilu

    loader = _ilm.SourceFileLoader("ds_cleanup_worktrees", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_cleanup_worktrees", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)

    start = time.monotonic()
    proc = mod._run(["sleep", "5"], timeout=1)
    elapsed = time.monotonic() - start
    assert proc.returncode != 0
    assert elapsed < 4.0, f"timeout wrapper did not bound the slow command (elapsed={elapsed:.2f}s)"


def _load_module_directly():
    """Imports bin/ds-cleanup-worktrees as a Python module (not a subprocess)
    for tests that need to monkeypatch its internals - notably forcing a
    `git bundle verify` failure specifically, which cannot be triggered
    reliably by any real filesystem manipulation (a bundle `git bundle
    create` just wrote in the SAME repo will always verify successfully;
    its prerequisites are trivially satisfied)."""
    import importlib.machinery as _ilm
    import importlib.util as _ilu

    loader = _ilm.SourceFileLoader("ds_cleanup_worktrees_direct", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_cleanup_worktrees_direct", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _make_unproven_branch_worktree(repo: Path, rel_path: str, branch: str) -> Path:
    """A worktree on a NEVER-PUSHED branch carrying a genuine unique
    commit - resolves SKIP_UNPROVEN under the default (offline-leaning)
    predicate, the exact class --archive-unproven targets."""
    wt = add_worktree(repo, rel_path, branch, push=False)
    (wt / "unique-work.txt").write_text(f"real work on {branch}\n")
    _git(wt, "add", "unique-work.txt")
    _git(wt, "commit", "-q", "-m", f"unique commit on {branch}")
    return wt


# --------------------------------------------------------------------------
# 19. (round-5) --archive-unproven is OPT-IN: without the flag, an unproven
#     branch is reported and untouched, exactly as before round 5.
# --------------------------------------------------------------------------


def test_archive_unproven_is_opt_in_default_behavior_unchanged(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-no-flag"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-no-flag", branch)

    proc = run_reap(repo, dry_run=False)  # no --archive-unproven
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_AMBIGUOUS_NO_PR)"
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "worktree-archive").exists()


# --------------------------------------------------------------------------
# 20. (round-5) --archive-unproven success path: the branch is archived
#     into a verified bundle, the worktree is removed, the entry lands in
#     the archived-and-removed bucket, and the exact restore command is
#     printed.
# --------------------------------------------------------------------------


def test_archive_unproven_success_archives_and_removes(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-archive-ok"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-archive-ok", branch)

    proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")
    assert str(wt) not in worktree_paths(repo)

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1, f"expected exactly one bundle, found {bundles}"
    verify = subprocess.run(
        ["git", "-C", str(repo), "bundle", "verify", str(bundles[0])], capture_output=True, text=True
    )
    assert verify.returncode == 0, verify.stderr

    assert "archived-and-removed=1" in summary_line(proc.stdout)
    assert "ARCHIVED+REMOVED" in proc.stdout
    assert "restore with:" in proc.stdout
    assert f'"refs/heads/{branch}:refs/heads/{branch}"' in proc.stdout, "restore refspec must be braced (zsh gotcha)"


# --------------------------------------------------------------------------
# 20b. (round-6, Skeptic Major 1) The --archive-unproven path runs the SAME
#      telemetry-salvage-then-remove sequence the plain REMOVE loop runs -
#      round 5 shipped the archive loop calling `git worktree remove`
#      directly, bypassing `_salvage_telemetry` entirely, so an unproven
#      worktree's own .agentic/events.jsonl was silently destroyed
#      (measured `archived-and-removed=1 salvaged=0`, no reaped-telemetry/
#      file written). This is the direct regression test for that defect,
#      confirmed to fail against the pre-fix code (see the fix summary for
#      the exact mutation-test observation).
# --------------------------------------------------------------------------


def test_archive_unproven_salvages_telemetry_before_removal(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-archive-salvage"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-archive-salvage", branch)
    (wt / ".agentic").mkdir()
    payload = '{"event": "session-end", "tokens": 42}\n'
    (wt / ".agentic" / "events.jsonl").write_text(payload)

    proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")
    assert str(wt) not in worktree_paths(repo)

    salvage_dir = repo / ".agentic" / "reaped-telemetry"
    salvaged_files = sorted(salvage_dir.glob(f"{branch}-*.jsonl"))
    assert len(salvaged_files) == 1, (
        f"expected exactly one salvaged telemetry file from the archive path, found {salvaged_files} - "
        "the archive loop must run the same salvage-then-remove sequence the plain REMOVE loop runs"
    )
    assert salvaged_files[0].stat().st_size > 0
    assert salvaged_files[0].read_text() == payload
    assert "salvaged=1" in summary_line(proc.stdout)

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1, f"expected exactly one bundle, found {bundles}"


def test_archive_unproven_salvage_failure_blocks_removal(tmp_path):
    """(round-6, Skeptic Major 1) The archive path's salvage failure must
    block removal exactly like the plain REMOVE loop's own salvage-failure
    guard - the entry stays SKIP_UNPROVEN, the already-verified bundle from
    the successful archive step is left in place (not undone), and the
    worktree is never removed."""
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-archive-salvage-fail"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-archive-salvage-fail", branch)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "will-not-survive-a-bug"}\n')

    # Pre-create the archive directory (so `git bundle create` still
    # succeeds - `mkdir(parents=True, exist_ok=True)` on an already-existing
    # directory needs no write permission on its parent), THEN lock down
    # the primary repo's own .agentic/ so the LATER
    # reaped-telemetry/ mkdir (which does not yet exist) fails - isolating
    # the failure to salvage specifically, after a successful archive.
    primary_agentic = repo / ".agentic"
    (primary_agentic / "worktree-archive").mkdir(parents=True, exist_ok=True)
    os.chmod(primary_agentic, 0o555)
    try:
        proc = run_reap(
            repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
        )
        assert proc.returncode == 0, proc.stderr
        result = outcomes(proc.stdout)
        assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_NOT_PUSHED)", result[str(wt)]
        assert str(wt) in worktree_paths(repo), "a failed archive-path salvage must NEVER become a silent deletion"
        assert "WARNING: telemetry salvage failed" in proc.stderr
        assert "worktree NOT removed" in proc.stderr
    finally:
        os.chmod(primary_agentic, 0o755)


# --------------------------------------------------------------------------
# 20c. (round-6, Skeptic Major 2) --archive-unproven must NEVER archive an
#      entry behind an OPEN PR, even with the flag set - round 5 filtered
#      on the whole SKIP_UNPROVEN outcome bucket, which silently swept in
#      SKIP_PR_OPEN (a hard safety override, not "unresolved branch
#      content"). This is the direct regression test, confirmed to fail
#      against a mutated whitelist that includes SKIP_PR_OPEN (see the fix
#      summary for the exact mutation-test observation).
# --------------------------------------------------------------------------


def test_archive_unproven_never_archives_open_pr_entry(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-open-pr"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-open-pr", branch)

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        extra=["--archive-unproven"],
        gh_dir=_fake_gh_dir(tmp_path, pr_state="OPEN"),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_PR_OPEN)", result[str(wt)]
    assert str(wt) in worktree_paths(repo), (
        "an entry behind an OPEN PR must NEVER be archived, even with --archive-unproven set"
    )
    assert not (repo / ".agentic" / "worktree-archive").exists()
    assert "archived-and-removed=0" in summary_line(proc.stdout)


# --------------------------------------------------------------------------
# 20d. (round-6, Skeptic Major 2) --archive-unproven refuses to run at all
#      in degraded gh mode (--no-gh, or gh genuinely unavailable) - without
#      PR evidence it cannot distinguish a genuinely-unprovable branch from
#      one behind an open PR, so `--archive-unproven --no-gh` must not
#      silently downgrade to a MORE permissive archive pass than a full
#      run. Exercised in both live and --dry-run mode; the refusal is
#      unconditional on dry-run.
# --------------------------------------------------------------------------


def test_archive_unproven_refuses_in_degraded_gh_mode(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-degraded", "worktree-agent-degraded")

    proc = run_reap(repo, dry_run=False, no_gh=True, extra=["--archive-unproven"])
    assert proc.returncode == 1
    assert "--archive-unproven requires PR evidence" in proc.stderr
    assert not (repo / ".agentic" / "worktree-archive").exists()


def test_archive_unproven_refuses_in_degraded_gh_mode_even_under_dry_run(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-degraded-dry", "worktree-agent-degraded-dry")

    proc = run_reap(repo, dry_run=True, no_gh=True, extra=["--archive-unproven"])
    assert proc.returncode == 1
    assert "--archive-unproven requires PR evidence" in proc.stderr


# --------------------------------------------------------------------------
# 21. (round-5) --dry-run creates NO bundle and removes nothing, but
#     reports the would-be count.
# --------------------------------------------------------------------------


def test_archive_unproven_dry_run_creates_no_bundle(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-archive-dry"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-archive-dry", branch)

    proc = run_reap(
        repo, dry_run=True, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    # With real (faked) gh AND network both enabled (no --no-gh), ls-remote
    # against the local origin resolves this never-pushed branch as
    # SKIP_NOT_PUSHED rather than the --no-gh-degraded SKIP_AMBIGUOUS_NO_PR
    # this same scenario reports elsewhere in this file - both are on the
    # --archive-unproven whitelist, so this is a reason-string difference
    # only, not a behavior change.
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_NOT_PUSHED)"
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "worktree-archive").exists()
    assert "archived-and-removed=0" in summary_line(proc.stdout)
    assert "1 unproven branch(es) would be archived" in proc.stdout


# --------------------------------------------------------------------------
# 22. (round-5) Bucket-sum-equals-entries invariant holds when an entry is
#     reclassified to ARCHIVED_AND_REMOVED.
# --------------------------------------------------------------------------


def test_archive_unproven_bucket_sum_still_reconciles(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-sum-a", "worktree-agent-sum-a")
    add_worktree(repo, ".claude/worktrees/agent-sum-b", "worktree-agent-sum-b", push=False)  # REMOVE-eligible
    dirty_wt = add_worktree(repo, ".claude/worktrees/agent-sum-c", "worktree-agent-sum-c", push=False)
    (dirty_wt / "uncommitted.txt").write_text("dirty\n")

    proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    line = summary_line(proc.stdout)
    counts = bucket_counts(line)
    entries = counts.pop("entries")
    removed = counts.pop("removed")
    counts.pop("pruned-admin", None)
    counts.pop("salvaged", None)
    archived_and_removed = counts.pop("archived-and-removed", 0)
    skip_sum = sum(v for k, v in counts.items() if k.startswith("skipped-"))
    total = removed + archived_and_removed + skip_sum
    assert total == entries, f"bucket sum {total} != entries {entries} (line: {line})"
    assert archived_and_removed == 1


# --------------------------------------------------------------------------
# 23. (round-5) A bundle-verify failure blocks removal entirely - direct
#     unit test of `_archive_branch_bundle`, monkeypatching `_run` to force
#     JUST the `git bundle verify` step to fail after a REAL `git bundle
#     create` succeeds (the only reliable way to trigger this specific
#     failure mode - a bundle just created in the same repo always
#     verifies successfully against real content, so no filesystem trick
#     alone can force this branch). This is the assertion round 5 asks to
#     be mutation-tested specifically.
# --------------------------------------------------------------------------


def test_archive_bundle_verify_failure_blocks_archival():
    mod = _load_module_directly()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo, _origin = init_repo_with_origin(tmp_path)
        branch = "worktree-agent-verify-fail"
        _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-verify-fail", branch)

        real_run = mod._run

        def fake_run(args, cwd=None, timeout=None):
            if "bundle" in args and "verify" in args:
                return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="simulated corrupt bundle")
            return real_run(args, cwd=cwd, timeout=timeout)

        mod._run = fake_run
        try:
            ok, detail, bundle_path, compact = mod._archive_branch_bundle(str(repo), branch, None)
        finally:
            mod._run = real_run

        assert ok is False, f"expected verify failure to block archival, got ok={ok} detail={detail!r}"
        assert "verify" in detail.lower()
        assert bundle_path is None
        assert compact is False


# --------------------------------------------------------------------------
# 24. (round-5) Same failure class end-to-end through the real CLI: an
#     uncreatable archive directory (a real filesystem failure, like
#     round 4's salvage-failure test) blocks removal entirely - the entry
#     stays SKIP_UNPROVEN, never a silent deletion of the only copy of
#     unproven work.
# --------------------------------------------------------------------------


def test_archive_directory_uncreatable_blocks_removal_end_to_end(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-archive-fail"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-archive-fail", branch)

    primary_agentic = repo / ".agentic"
    primary_agentic.mkdir(exist_ok=True)
    os.chmod(primary_agentic, 0o555)
    try:
        proc = run_reap(
            repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
        )
        assert proc.returncode == 0, proc.stderr
        result = outcomes(proc.stdout)
        # Real (faked) gh + real network enabled here (see the dry-run bundle
        # test's comment above for why this differs from the --no-gh reason).
        assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_NOT_PUSHED)"
        assert str(wt) in worktree_paths(repo), "a failed archive must NEVER become a silent deletion"
        assert "WARNING: archive failed" in proc.stderr
        assert "worktree NOT removed" in proc.stderr
    finally:
        os.chmod(primary_agentic, 0o755)


# --------------------------------------------------------------------------
# 25. (round-5) The restore path actually works end-to-end: create a
#     branch with a unique commit, archive it, remove the worktree, THEN
#     restore from the bundle into a fresh clone and assert the restored
#     SHA matches the original exactly - not merely "the bundle file
#     exists".
# --------------------------------------------------------------------------


def test_archive_restore_path_recovers_the_exact_original_sha(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-restore-e2e"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-restore-e2e", branch)
    original_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")
    assert str(wt) not in worktree_paths(repo)
    # The branch ref itself still exists locally (this tool never deletes
    # branches) - remove it too, to prove the restore below is genuinely
    # recovering from the BUNDLE, not just reading the still-present ref.
    _git(repo, "branch", "-D", branch)
    branch_gone = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"refs/heads/{branch}"], capture_output=True, text=True
    )
    assert branch_gone.returncode != 0, "precondition: branch must be genuinely gone before restoring"

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1
    bundle_path = str(bundles[0])

    # The exact restore command this tool prints, executed for real.
    restore_cmd = ["git", "-C", str(repo), "fetch", bundle_path, f"refs/heads/{branch}:refs/heads/{branch}"]
    restore_proc = subprocess.run(restore_cmd, capture_output=True, text=True)
    assert restore_proc.returncode == 0, restore_proc.stderr

    restored_sha = _git(repo, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    assert restored_sha == original_sha, (
        f"restored SHA {restored_sha} does not match the original {original_sha} - "
        "a bundle file merely existing is not proof of a working restore path"
    )


# --------------------------------------------------------------------------
# DS-191. A compact bundle excludes objects already reachable from the
#     resolved base branch, so the bundle is materially smaller than a
#     full-history bundle of the same branch - the actual acceptance
#     criterion this ticket asks for, not merely a header-line proxy.
# --------------------------------------------------------------------------


def test_archive_bundle_excludes_already_on_base_objects(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    # Inflate the base branch with a large blob so a compact bundle (which
    # excludes objects already reachable from resolved_base) is measurably
    # smaller than a full-history bundle of the same branch - mirrors the
    # plan's measured git 2.55.0 figures (202,476 B full vs 368 B compact
    # for a 200 KB base blob + one-commit branch).
    (repo / "big-base-blob.bin").write_bytes(os.urandom(200_000))
    _git(repo, "add", "big-base-blob.bin")
    _git(repo, "commit", "-q", "-m", "large base blob")
    _git(repo, "push", "-q", "origin", "main")

    branch = "worktree-agent-compact"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-compact", branch)

    proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")

    # (round-N Minor 6) The printed restore parenthetical is the operator-
    # facing recovery precondition and previously had ZERO coverage - the
    # bundle bytes were asserted above but never the printed restore line
    # itself. Also (round-N Minor 3) the parenthetical must name the
    # commit git ACTUALLY recorded as the bundle's prerequisite (the
    # boundary/fork-point with the base), never the base ref's own tip -
    # those are measurably different commits in general (a prior wording,
    # "the commit that was at <base> when this bundle was created", was
    # false as written). Mutation that reddens this block: replacing the
    # restore_parenthetical f-string in bin/ds-cleanup-worktrees with ""
    # leaves the rest of this test (and the whole suite) green.
    restore_lines = [line for line in proc.stdout.splitlines() if line.startswith("ARCHIVED+REMOVED")]
    assert len(restore_lines) == 1, proc.stdout
    restore_line = restore_lines[0]
    assert "prerequisite" in restore_line, restore_line
    assert "NOT necessarily that ref's own tip" in restore_line, restore_line
    assert "commit that was at" not in restore_line, (
        f"restore line still claims the prerequisite IS the base tip, which is false: {restore_line!r}"
    )
    assert "git bundle verify" in restore_line, restore_line

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1
    compact_bundle = bundles[0]
    header, _, _ = compact_bundle.read_bytes().partition(b"\n\n")
    header_lines = header.split(b"\n")
    assert any(line.startswith(b"-") for line in header_lines), (
        f"expected a prerequisite (-prefixed) header line in a compact bundle, got: {header_lines!r}"
    )

    full_bundle_path = tmp_path / "full-comparison.bundle"
    full_proc = subprocess.run(
        ["git", "-C", str(repo), "bundle", "create", str(full_bundle_path), branch],
        capture_output=True,
        text=True,
    )
    assert full_proc.returncode == 0, full_proc.stderr

    compact_size = compact_bundle.stat().st_size
    full_size = full_bundle_path.stat().st_size
    assert compact_size < full_size / 10, (
        f"expected compact bundle ({compact_size} B) to be materially smaller than "
        f"full-history bundle ({full_size} B)"
    )


# --------------------------------------------------------------------------
# DS-191. The `unique_count == 0` fallback (a branch fully contained in
#     `exclude_ref`) is defensive-only - unreachable via the real CLI,
#     since merge-evidence ancestor testing already routes such a branch
#     to ELIGIBLE->REMOVE before the archive loop runs. Exercised here via
#     a direct unit-level call that bypasses disposition routing entirely.
# --------------------------------------------------------------------------


def test_archive_bundle_defensive_guard_skips_empty_exclusion(tmp_path):
    mod = _load_module_directly()
    repo, _origin = init_repo_with_origin(tmp_path)
    # `exclude_ref` points at `branch`'s own current tip (main), so
    # `unique_count` relative to it is 0 - the defensive fallback.
    branch = "main"
    exclude_ref = "main"

    captured_argv = []
    real_run = mod._run

    def fake_run(args, cwd=None, timeout=None):
        if "bundle" in args and "create" in args:
            captured_argv.append(list(args))
        return real_run(args, cwd=cwd, timeout=timeout)

    mod._run = fake_run
    try:
        ok, detail, bundle_path, compact = mod._archive_branch_bundle(str(repo), branch, exclude_ref)
    finally:
        mod._run = real_run

    assert ok is True, detail
    assert compact is False
    assert bundle_path is not None and Path(bundle_path).stat().st_size > 0
    assert len(captured_argv) == 1, captured_argv
    assert "--not" not in captured_argv[0], (
        f"expected no --not exclusion when unique_count == 0, got argv: {captured_argv[0]!r}"
    )


# --------------------------------------------------------------------------
# DS-191. A bogus explicit --base (unverifiable locally) produces a
#     full-history bundle plus a trimmed NOTE on stderr, verified via the
#     real CLI end-to-end - not a direct unit-level call.
# --------------------------------------------------------------------------


def test_archive_unproven_prints_full_history_note_for_unverifiable_base(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-bogus-base"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-bogus-base", branch)

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        base="nonexistent-ref",
        extra=["--archive-unproven"],
        gh_dir=_fake_gh_dir(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")
    assert "NOTE:" in proc.stderr
    assert "full-history" in proc.stderr

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1
    header, _, _ = bundles[0].read_bytes().partition(b"\n\n")
    header_lines = header.split(b"\n")
    assert not any(line.startswith(b"-") for line in header_lines), (
        f"expected no prerequisite header line for a full-history bundle, got: {header_lines!r}"
    )


# --------------------------------------------------------------------------
# 26. (round-N MAJOR fix) A transient `gh pr list` QUERY FAILURE is a
#     distinct fact from "no PR exists" and must NEVER be archived, even
#     with --archive-unproven set. Pre-fix, `_pr_state` collapsed a query
#     failure into `pr_state="NONE"`, which - combined with a genuinely
#     pushed branch (so `ls_remote_status="pushed"` is also inconclusive) -
#     fell through to the generic `SKIP_AMBIGUOUS_NO_PR` disposition, which
#     IS on `_ARCHIVABLE_UNPROVEN_DISPOSITIONS`. A worktree behind a REAL
#     OPEN PR whose query merely hit a transient failure on this one run
#     would therefore be silently bundled and removed. `gh auth status`
#     succeeds in this scenario (process-level gh availability is fine) -
#     only the per-branch `gh pr list` call fails, which is exactly the
#     shape the process-level `--no-gh`/degraded-mode refusal cannot see.
# --------------------------------------------------------------------------


def test_archive_unproven_never_archives_pr_query_error_entry(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-prqerr", "worktree-agent-prqerr", push=True)
    (wt / "extra.txt").write_text("unique work behind what would be a live OPEN PR\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(wt, "push", "-q", "origin", "worktree-agent-prqerr")

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        extra=["--archive-unproven"],
        gh_dir=_fake_gh_dir(tmp_path, pr_list_fails=True),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PR_QUERY_ERROR"), result[str(wt)]
    # Never archived, never removed.
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "worktree-archive").exists()
    counts = bucket_counts(summary_line(proc.stdout))
    assert counts.get("archived-and-removed", 0) == 0
    assert counts.get("removed", 0) == 0


def test_pr_query_error_visible_without_archive_flag_too(tmp_path):
    """The reclassification is not gated on --archive-unproven - a plain
    run must also report the query failure visibly (never a silent
    mode=live / SKIP_UNPROVEN read that hides the ambiguity from the
    operator)."""
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-prqerr2", "worktree-agent-prqerr2", push=True)
    (wt / "extra.txt").write_text("unique work - not merely an ancestor-of-base branch\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(wt, "push", "-q", "origin", "worktree-agent-prqerr2")

    proc = run_reap(repo, dry_run=False, no_gh=False, gh_dir=_fake_gh_dir(tmp_path, pr_list_fails=True))
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_PR_QUERY_ERROR"), result[str(wt)]
    assert str(wt) in worktree_paths(repo)
    assert "skipped-pr-query-error=1" in summary_line(proc.stdout)


# --------------------------------------------------------------------------
# 27. (round-N Minor b) `SKIP_LS_REMOTE_ERROR`'s exclusion from the archive
#     whitelist was previously pinned only by the doc's own claim, never by
#     a test forcing the ACTUAL disposition. Corrupts the `origin` remote
#     URL so `git ls-remote` genuinely errors (not merely "not_pushed").
# --------------------------------------------------------------------------


def test_archive_unproven_never_archives_ls_remote_error_entry(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-lsrerr", "worktree-agent-lsrerr", push=False)
    (wt / "extra.txt").write_text("unique unpushed work\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

    proc = run_reap(repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path))
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_LS_REMOTE_ERROR)", result[str(wt)]
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "worktree-archive").exists()
    counts = bucket_counts(summary_line(proc.stdout))
    assert counts.get("archived-and-removed", 0) == 0


# --------------------------------------------------------------------------
# 28. (round-N Minor c) `salvage_would`, under `--dry-run --archive-unproven`,
#     must count telemetry sitting in BOTH the plain REMOVE bucket AND the
#     archive-eligible SKIP_UNPROVEN bucket - the docstring claims the two
#     removal paths are unified, so a dry-run preview must not systematically
#     undercount by ignoring telemetry that would be salvaged via the archive
#     path.
# --------------------------------------------------------------------------


def test_dry_run_salvage_would_counts_archive_candidates_too(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    commit_gitignore_on_main(repo, ".agentic/*\n")
    branch = "worktree-agent-dry-salvage-parity"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-dry-salvage-parity", branch)
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"event": "would-be-salvaged"}\n')

    proc = run_reap(
        repo, dry_run=True, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert proc.returncode == 0, proc.stderr
    assert "1 .agentic/events.jsonl file(s) would be salvaged" in proc.stdout, proc.stdout
    # Real run confirms the same file is genuinely salvageable via the
    # archive path (parity, not merely a matching count by coincidence).
    real_proc = run_reap(
        repo, dry_run=False, no_gh=False, extra=["--archive-unproven"], gh_dir=_fake_gh_dir(tmp_path)
    )
    assert real_proc.returncode == 0, real_proc.stderr
    assert "salvaged=1" in summary_line(real_proc.stdout)


# --------------------------------------------------------------------------
# 29. (round-N Minor a) `SKIP_REMOVE_FAILED` had zero coverage - deleting
#     BOTH `r["outcome"] = "SKIP_REMOVE_FAILED"` assignments left the whole
#     suite green. This forces a REAL `git worktree remove` failure via a
#     `git` stub that intercepts only that one subcommand.
# --------------------------------------------------------------------------


def test_remove_failure_reclassifies_to_skip_remove_failed(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-rmfail", "worktree-agent-rmfail", push=False)
    # No unique commits - ancestor-of-base -> ELIGIBLE/REMOVE under normal
    # evidence resolution, so the ONLY thing standing between this entry
    # and a successful removal is the stubbed `git worktree remove` failure.

    proc = run_reap(repo, dry_run=False, git_dir=_fake_git_dir_remove_fails(tmp_path))
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("SKIP_REMOVE_FAILED"), result[str(wt)]
    assert str(wt) in worktree_paths(repo)
    counts = bucket_counts(summary_line(proc.stdout))
    assert counts.get("skipped-remove-failed", 0) == 1
    assert counts.get("removed", 0) == 0
    assert "WARNING: failed to remove" in proc.stderr


# --------------------------------------------------------------------------
# 30. (round-8 MAJOR fix) A newer non-OPEN PR must never mask a live OPEN
#     PR on the same head branch. `[{2, CLOSED}, {1, OPEN}]` (CLOSED listed
#     first, i.e. "newer") under --archive-unproven must resolve
#     SKIP_PR_OPEN and be preserved - never archived. Pre-fix, `rows[0]`
#     selection (and the `--limit 1` truncation that made it the ONLY row
#     the tool ever saw) picked CLOSED, which is inconclusive, fell through
#     to the generic SKIP_AMBIGUOUS_NO_PR (archive-whitelisted), and
#     archived-and-removed a worktree behind a live PR.
# --------------------------------------------------------------------------


def test_multi_pr_open_masked_by_closed_under_archive_unproven(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-multi-pr-closed", "worktree-agent-multi-pr-closed", push=True)
    (wt / "extra.txt").write_text("unique work behind a live OPEN PR, masked by a newer CLOSED one\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(wt, "push", "-q", "origin", "worktree-agent-multi-pr-closed")

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        extra=["--archive-unproven"],
        gh_dir=_fake_gh_dir_multi_pr(tmp_path, [(2, "CLOSED"), (1, "OPEN")]),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_PR_OPEN)", result[str(wt)]
    assert str(wt) in worktree_paths(repo)
    assert not (repo / ".agentic" / "worktree-archive").exists()
    counts = bucket_counts(summary_line(proc.stdout))
    assert counts.get("archived-and-removed", 0) == 0


# --------------------------------------------------------------------------
# 31. (round-8 MAJOR fix, the more serious half) `[{2, MERGED}, {1, OPEN}]`
#     on a PLAIN DEFAULT RUN (no --archive-unproven, no --dry-run) must
#     resolve SKIP_PR_OPEN and be preserved. Pre-fix, `rows[0]` selection
#     picked MERGED, which the LENIENT worktree-removal pr_state check
#     (`_check_pr_state_lenient`) treats as sufficient for `ELIGIBLE` on
#     its own - so this destroyed a worktree behind a live OPEN PR with NO
#     flags at all, the most dangerous possible manifestation of this bug.
# --------------------------------------------------------------------------


def test_multi_pr_open_masked_by_merged_on_default_run(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-multi-pr-merged", "worktree-agent-multi-pr-merged", push=True)
    (wt / "extra.txt").write_text("unique work behind a live OPEN PR, masked by a newer MERGED one\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(wt, "push", "-q", "origin", "worktree-agent-multi-pr-merged")

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        gh_dir=_fake_gh_dir_multi_pr(tmp_path, [(2, "MERGED"), (1, "OPEN")]),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_PR_OPEN)", result[str(wt)]
    assert str(wt) in worktree_paths(repo), "an entry behind a live OPEN PR must never be REMOVEd, even on a plain default run"
    counts = bucket_counts(summary_line(proc.stdout))
    assert counts.get("removed", 0) == 0


# --------------------------------------------------------------------------
# 32. (round-8 Minor a) A nonzero SKIP_PR_QUERY_ERROR count must be visible
#     via a dedicated NOTE line, matching the existing degraded-mode NOTE
#     shape - not merely the bucket field and --explain.
# --------------------------------------------------------------------------


def test_pr_query_error_note_line_printed_when_nonzero(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-prqerr-note", "worktree-agent-prqerr-note", push=True)
    (wt / "extra.txt").write_text("unique work\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(wt, "push", "-q", "origin", "worktree-agent-prqerr-note")

    proc = run_reap(repo, dry_run=False, no_gh=False, gh_dir=_fake_gh_dir(tmp_path, pr_list_fails=True))
    assert proc.returncode == 0, proc.stderr
    assert "skipped-pr-query-error=1" in summary_line(proc.stdout)
    assert "NOTE:" in proc.stdout and "gh pr list` query failure" in proc.stdout, proc.stdout
    assert "SKIP_PR_QUERY_ERROR" in proc.stdout


# --------------------------------------------------------------------------
# 33. (round-2 rework, Skeptic Major 1) A nonzero SKIP_TOO_YOUNG count must
#     be visible via a dedicated NOTE line, matching the existing
#     SKIP_PR_QUERY_ERROR NOTE shape - a `removed=0` run right after a merge
#     must not leave the age floor buried in the bucket field alone.
#     Confirmed failing pre-fix: before this NOTE was added, this assertion
#     failed with `assert 'NOTE:' in proc.stdout` (stdout carried only the
#     summary line's `skipped-too-young=1` field and no NOTE at all).
# --------------------------------------------------------------------------


def test_too_young_note_line_printed_when_nonzero(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-young-note", "worktree-agent-young-note", push=False)

    proc = run_reap(repo, dry_run=False, min_age_hours="24")
    assert proc.returncode == 0, proc.stderr
    assert "skipped-too-young=1" in summary_line(proc.stdout)
    assert "NOTE:" in proc.stdout and "age floor" in proc.stdout, proc.stdout
    # round-3 Skeptic Minor 4: the prior version of this assertion anchored
    # only on the NOTE's fixed text and the --min-age-hours token, never on
    # the count itself - a NOTE printing a wrong count still passed. Pin
    # the count so a mismatch between too_young_count and the printed
    # number is caught. Confirmed failing pre-fix: mutating the source to
    # print `too_young_count + 1` (a deliberately wrong count) still passed
    # every assertion in the pre-fix version of this test.
    assert "NOTE: 1 worktree(s) skipped because they are younger than" in proc.stdout, proc.stdout
    assert "--min-age-hours 0" in proc.stdout
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 34. Base-branch resolution (round-4 rework, DS-cleanup-worktrees). Moves
#     content/commands/ds-cleanup-worktrees.md's former hand-rolled
#     grep/awk/sed pipeline into `resolve_base_branch` /
#     `_parse_base_branch_declaration` - table-driven, direct unit coverage
#     of every input variant that broke a prior review round, plus a few
#     end-to-end CLI checks confirming the wiring.
# --------------------------------------------------------------------------


def set_origin_head(repo: Path, branch: str) -> None:
    """Sets `refs/remotes/origin/HEAD` locally (no real network query - a
    direct `symbolic-ref` write against the already-pushed local
    remote-tracking ref) so tier (c) is reachable in a test without relying
    on `git remote set-head -a`'s remote-advertisement behavior."""
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")


def write_agents_md(repo: Path, text: str) -> None:
    (repo / "AGENTS.md").write_text(text)


def push_new_branch(repo: Path, branch: str) -> None:
    """Creates and pushes a new branch from current HEAD without checking
    it out (so the repo's own working branch is left untouched) and without
    creating a worktree for it."""
    _git(repo, "branch", branch)
    _git(repo, "push", "-q", "origin", f"{branch}:{branch}")


@pytest.mark.parametrize(
    "agents_md_text,expected",
    [
        pytest.param("BASE_BRANCH: main\n", "main", id="bare_declaration"),
        pytest.param("BASE_BRANCH: develop   \n", "develop", id="trailing_whitespace"),
        pytest.param("   BASE_BRANCH: develop\n", "develop", id="leading_whitespace"),
        pytest.param('BASE_BRANCH: "develop"\n', "develop", id="double_quoted"),
        pytest.param("BASE_BRANCH: 'develop'\n", "develop", id="single_quoted"),
        pytest.param("BASE_BRANCH: `develop`\n", "develop", id="backtick_quoted"),
        pytest.param("BASE_BRANCH: origin/develop\n", "develop", id="origin_prefix"),
        pytest.param("BASE_BRANCH: refs/heads/develop\n", "develop", id="refs_heads_prefix"),
        pytest.param("BASE_BRANCH: staging  # our integration branch\n", "staging", id="trailing_comment"),
        pytest.param(
            "**Base branch:** Declaration: `BASE_BRANCH: main`.\n",
            "main",
            id="whole_phrase_backtick_wrapped_with_period",
        ),
        pytest.param(
            "```\nBASE_BRANCH: wrong-fenced-example\n```\nBASE_BRANCH: staging\n",
            "staging",
            id="fenced_example_then_real_declaration",
        ),
        pytest.param(
            "~~~\nBASE_BRANCH: wrong-tilde-fenced-example\n~~~\nBASE_BRANCH: staging\n",
            "staging",
            id="tilde_fenced_example_then_real_declaration",
        ),
        pytest.param(
            "    BASE_BRANCH: wrong-indented-example\nBASE_BRANCH: staging\n",
            "staging",
            id="indented_fence_then_real_declaration",
        ),
        pytest.param("Some notes.\nBASE_BRANCH: resolution rules.\n", None, id="prose_mention_not_a_declaration"),
        pytest.param("Nothing here about a base branch.\n", None, id="no_base_branch_line_at_all"),
        pytest.param("", None, id="empty_file"),
    ],
)
def test_parse_base_branch_declaration_table(agents_md_text, expected):
    assert ds_cleanup_worktrees._parse_base_branch_declaration(agents_md_text) == expected


def test_resolve_base_branch_explicit_argument_wins_verbatim_no_validation(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    write_agents_md(repo, "BASE_BRANCH: develop\n")
    # A nonexistent explicit ref is used VERBATIM, no fallthrough - this
    # preserves the tool's pre-existing precedence for an operator
    # override, per the ticket brief.
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), "origin/does-not-exist")
    assert (ref, source) == ("origin/does-not-exist", "explicit")
    assert diagnostics == []


def test_resolve_base_branch_agents_md_declaration_wins_over_lower_tiers(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "staging")
    write_agents_md(repo, "BASE_BRANCH: staging\n")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/staging", "agents-md")
    assert diagnostics == []


def test_resolve_base_branch_declared_but_unresolvable_fails_never_falls_through(tmp_path):
    # AGENTS.md's BASE_BRANCH declaration is authoritative (conventions.md:
    # "wins. Highest priority."). A declared-but-unresolvable value must
    # fail resolution outright, never silently substitute a different
    # (possibly perfectly valid) base such as main-fallback - a wrong-but-
    # resolvable substitution is a more dangerous failure than a skipped
    # run, since the substituted base could be a valid ref the operator
    # never declared.
    repo, _origin = init_repo_with_origin(tmp_path)
    write_agents_md(repo, "BASE_BRANCH: totally-made-up-branch\n")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert ref is None
    assert source == "unresolved"
    assert len(diagnostics) == 1
    assert "totally-made-up-branch" in diagnostics[0]
    assert "agents-md" in diagnostics[0]


def test_resolve_base_branch_declared_but_unresolvable_ignores_valid_lower_tiers(tmp_path):
    # Reinforces the test above: even when a LOWER tier (local develop
    # branch) would resolve cleanly, a declared-but-unresolvable AGENTS.md
    # base still fails resolution rather than falling through to it.
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "develop")
    write_agents_md(repo, "BASE_BRANCH: totally-made-up-branch\n")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert ref is None
    assert source == "unresolved"


def test_resolve_base_branch_origin_head_symbolic_ref(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "release")
    set_origin_head(repo, "release")
    # No AGENTS.md at all - origin/HEAD is the next tier.
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/release", "origin-head")
    assert diagnostics == []


def test_resolve_base_branch_agents_md_beats_origin_head(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "release")
    set_origin_head(repo, "release")
    push_new_branch(repo, "staging")
    write_agents_md(repo, "BASE_BRANCH: staging\n")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/staging", "agents-md")


def test_resolve_base_branch_local_develop(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "develop")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/develop", "local-develop")


def test_resolve_base_branch_local_development(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "development")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/development", "local-development")


def test_resolve_base_branch_main_fallback_no_agents_md(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/main", "main-fallback")
    assert diagnostics == []


def test_resolve_base_branch_agents_md_with_no_base_branch_line(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    write_agents_md(repo, "# Some Project\n\nJust ordinary prose, no declaration.\n")
    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert (ref, source) == ("origin/main", "main-fallback")
    assert diagnostics == []


def test_resolve_base_branch_every_candidate_fails_names_all_tried(tmp_path):
    # A repo whose origin has neither main nor master - both fallback
    # candidates fail validation, and (no AGENTS.md, no origin/HEAD symref,
    # no local develop/development) every other tier is simply absent, so
    # this reaches the terminal "every candidate failed" case.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "trunk", str(origin)], check=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "trunk")

    ref, source, diagnostics = ds_cleanup_worktrees.resolve_base_branch(str(repo), None)
    assert ref is None
    assert source == "unresolved"
    assert len(diagnostics) == 3, diagnostics  # main-fallback, master-fallback, final summary
    assert "origin/main" in diagnostics[-1]
    assert "origin/master" in diagnostics[-1]
    assert "main-fallback" in diagnostics[-1]
    assert "master-fallback" in diagnostics[-1]


def test_cli_auto_resolves_base_when_flag_omitted(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    push_new_branch(repo, "staging")
    write_agents_md(repo, "BASE_BRANCH: staging\n")
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--dry-run", "--no-gh", "--min-age-hours", "0"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "base auto-resolved to 'origin/staging' via agents-md" in proc.stdout
    assert "base=origin/staging" in proc.stdout


def test_cli_explicit_base_flag_suppresses_auto_resolve_message(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    cmd = [
        sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "origin/main",
        "--dry-run", "--no-gh", "--min-age-hours", "0",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "auto-resolved" not in proc.stdout
    assert "base=origin/main" in proc.stdout


def test_cli_fails_safe_exit_0_when_every_base_candidate_fails(tmp_path):
    """Preserves the shell pipeline this replaces' deliberate asymmetry: a
    resolved-but-invalid/unresolvable base is a WARNING and a skipped reap
    for the session, never a hard nonzero exit - so a caller (Step 2's
    wrapper) that treats a nonzero `ds-cleanup-worktrees` exit as fatal and
    aborts its remaining steps does NOT abort just because no base could
    be resolved this run. Exit 1 stays reserved for a genuine
    internal/usage error (bad --repo, an unhandled exception)."""
    origin = tmp_path / "origin2.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "trunk", str(origin)], check=True)
    repo = tmp_path / "repo2"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "trunk")

    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--dry-run", "--no-gh", "--min-age-hours", "0"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "could not resolve a base branch" in proc.stderr
    assert "base could not be resolved - reap skipped this run" in proc.stderr
    assert "entries=" not in proc.stdout


def test_count_only_still_makes_zero_base_resolution_git_calls(tmp_path):
    """Regression guard (ticket brief regression #1): --count-only must
    still make ZERO network calls and ZERO per-entry git calls beyond one
    `git worktree list --porcelain` - base resolution must never run on
    this path. A `git` stub that fails any invocation OTHER than `worktree
    list` proves this directly rather than merely timing the call."""
    repo, _origin = init_repo_with_origin(tmp_path)
    real_git = shutil.which("git")
    bin_dir = tmp_path / "onlylistbin"
    bin_dir.mkdir()
    git_stub = bin_dir / "git"
    git_stub.write_text(
        "#!/usr/bin/env bash\n"
        # Allowed: `-C <repo> rev-parse --show-toplevel` (repo resolution,
        # runs unconditionally, before the --count-only check) and
        # `-C <repo> worktree list --porcelain` (entry enumeration). Any
        # OTHER invocation - in particular anything base-resolution-shaped
        # (symbolic-ref, show-ref, rev-parse --verify against a base ref) -
        # fails deterministically, proving base resolution never runs on
        # this path.
        'if [ "$3" = "worktree" ] && [ "$4" = "list" ]; then\n'
        f'  exec "{real_git}" "$@"\n'
        "fi\n"
        'if [ "$3" = "rev-parse" ] && [ "$4" = "--show-toplevel" ]; then\n'
        f'  exec "{real_git}" "$@"\n'
        "fi\n"
        'echo "unexpected git invocation: $@" >&2\n'
        "exit 99\n"
    )
    git_stub.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--count-only"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "entries=" in proc.stdout


_GIT_CALL_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _parse_manifest_git_call_count() -> int:
    """Parses the `--count-only` git-call-count claim out of the module
    docstring's `Performance:` section (e.g. "`--count-only` - two git
    calls total: ...") rather than hand-typing a second copy of the
    figure. This is the fix for Round-4 Major 3: the prior version of this
    test defined `EXPECTED_GIT_CALLS = 2` as a bare literal with a
    "keep in lockstep with the module docstring" comment - a comment is
    not an assertion, and changing the manifest text alone (e.g. to
    "three git calls total") left the suite GREEN, which is precisely the
    class of drift this test claims to guard against (the historical
    defect was manifest-side: the docstring said "one call" while the code
    made two)."""
    source = SCRIPT.read_text()
    match = re.search(r"--count-only`\s*-\s*(\w+)\s+git calls total", source)
    assert match, "could not find the Performance: section's git-call-count claim in the module docstring"
    word = match.group(1).lower()
    assert word in _GIT_CALL_COUNT_WORDS, f"unrecognized count word in manifest: {word!r}"
    return _GIT_CALL_COUNT_WORDS[word]


def test_count_only_git_call_count_matches_manifest(tmp_path):
    """Round-N Major 3 regression guard, corrected in Round 4: mechanically
    derives the actual subprocess-call count for single-repo `--count-only`
    by EXECUTION, rather than trusting a hand count - the module
    docstring's own `Performance:` section claimed "one call, nothing
    else" for over a round while the code genuinely made two
    (`rev-parse --show-toplevel` during repo resolution, then
    `worktree list --porcelain`). A `git` stub logs every invocation's
    argv to a file (delegating to the real `git` so the run still
    succeeds) and this test asserts the derived count against a figure
    PARSED out of the manifest's own stated text (`_parse_manifest_git_call_count`),
    not a second hand-typed count - so the two can never silently diverge
    again in either direction: mutating the manifest text alone, or making
    the code perform an extra/fewer call, both fail this test."""
    repo, _origin = init_repo_with_origin(tmp_path)
    real_git = shutil.which("git")
    assert real_git, "real `git` must be on PATH to build this stub"
    bin_dir = tmp_path / "countingbin"
    bin_dir.mkdir()
    log_path = tmp_path / "git-calls.log"
    git_stub = bin_dir / "git"
    git_stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{log_path}"\n'
        f'exec "{real_git}" "$@"\n'
    )
    git_stub.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--count-only"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)

    calls = log_path.read_text().splitlines() if log_path.exists() else []
    expected = _parse_manifest_git_call_count()
    assert len(calls) == expected, (calls, expected)
    assert any("rev-parse" in c and "--show-toplevel" in c for c in calls), calls
    assert any("worktree" in c and "list" in c for c in calls), calls


def test_manifest_test_name_cross_references_exist():
    """Round-4-review regression guard: the module docstring names specific
    `test_*` functions by name (e.g. the Performance: section's git-call-
    count pointer) as evidence for a claim it makes. Four consecutive rounds
    each let a DIFFERENT field of this manifest go stale (Failure modes,
    Upstream deps, Downstream consumers, and a Performance test-name
    pointer that this round renamed the target of without updating the
    pointer) - this test closes the test-name-pointer class mechanically:
    it extracts every backtick-quoted `test_*` identifier from the module
    docstring and asserts each one is actually collected as a `def test_...`
    function in one of the two test files the docstring's own Downstream
    consumers section names as this tool's CI coverage
    (test_cleanup_worktrees.py, test_cleanup_worktrees_multi_repo.py) -
    so a rename on either side (the pointer or the test) fails this test
    instead of shipping silently, the same discipline
    `test_count_only_git_call_count_matches_manifest` already applies to
    the git-call-count figure it derives from the same section."""
    doc = ds_cleanup_worktrees.__doc__ or ""
    referenced = sorted(set(re.findall(r"`(test_[A-Za-z0-9_]+)`", doc)))
    assert referenced, "expected at least one backtick-quoted test_* reference in the module docstring"

    tests_dir = SCRIPT.resolve().parent / "tests"
    collected: set = set()
    for test_file in ("test_cleanup_worktrees.py", "test_cleanup_worktrees_multi_repo.py"):
        text = (tests_dir / test_file).read_text()
        collected.update(re.findall(r"^def (test_[A-Za-z0-9_]+)\(", text, re.MULTILINE))

    missing = [name for name in referenced if name not in collected]
    assert not missing, (
        f"module docstring references test(s) not collected as def test_...(...) in "
        f"test_cleanup_worktrees.py or test_cleanup_worktrees_multi_repo.py: {missing}"
    )


# --------------------------------------------------------------------------
# DS-189 Unit A: `SKIP_LS_REMOTE_ERROR` aggregate NOTE. `SKIP_LS_REMOTE_ERROR`
# is a Disposition VALUE, not an outcome bucket - `evaluate_entry` folds it
# into {"outcome": "SKIP_UNPROVEN", "reason": "SKIP_LS_REMOTE_ERROR"}, so
# the NOTE predicate must scan `results` for that reason, never read an
# `outcome_counts["SKIP_LS_REMOTE_ERROR"]` bucket (which can never exist -
# see the regression test below). Corrupting the `origin` remote URL forces
# a genuine ls-remote error (not merely "not_pushed"), mirroring
# `test_archive_unproven_never_archives_ls_remote_error_entry` above.
# --------------------------------------------------------------------------


def test_ls_remote_error_note_fires_at_exactly_fifty_percent(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-lsr", "worktree-agent-lsr", push=False)
    (wt / "extra.txt").write_text("unique unpushed work\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

    # Two total entries (SKIP_MAIN + this one SKIP_UNPROVEN/SKIP_LS_REMOTE_ERROR
    # entry) -> 1/2 == 50%, at the ">= 0.5" threshold exactly.
    proc = run_reap(repo, dry_run=True, no_gh=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "SKIP_UNPROVEN (SKIP_LS_REMOTE_ERROR)", result[str(wt)]
    assert "NOTE: 1 of 2 worktree(s) are SKIP_UNPROVEN (SKIP_LS_REMOTE_ERROR)" in proc.stdout, proc.stdout


def test_ls_remote_error_note_absent_below_fifty_percent(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    # One entry that will hit ls-remote error (unpushed, unique commits).
    wt_err = add_worktree(repo, ".claude/worktrees/agent-lsr2", "worktree-agent-lsr2", push=False)
    (wt_err / "extra.txt").write_text("unique unpushed work\n")
    _git(wt_err, "add", "extra.txt")
    _git(wt_err, "commit", "-q", "-m", "unique commit")
    # Three zero-unique-commit (ancestor-of-base) entries: `merge_evidence`
    # resolves "merged" and short-circuits BEFORE the ls-remote leg is
    # consulted at all (see `_check_merge_evidence`), so these are ELIGIBLE
    # regardless of the corrupted origin below.
    for i in range(3):
        add_worktree(repo, f".claude/worktrees/agent-clean{i}", f"worktree-agent-clean{i}", push=False)
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

    # 1 error / 4 total non-main-inclusive... total entries = SKIP_MAIN + 4 = 5;
    # 1/5 == 20%, well below the 50% threshold.
    proc = run_reap(repo, dry_run=True, no_gh=False)
    assert proc.returncode == 0, proc.stderr
    assert not any("SKIP_LS_REMOTE_ERROR" in line for line in proc.stdout.splitlines() if line.startswith("NOTE:"))


def test_ls_remote_error_note_absent_when_zero_errors_no_div_by_zero(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    # No other worktrees at all - only the main entry (SKIP_MAIN). Zero
    # SKIP_LS_REMOTE_ERROR entries; the `ls_remote_error_count and ...`
    # short-circuit must never attempt a division here.
    proc = run_reap(repo, dry_run=True, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    assert not any("SKIP_LS_REMOTE_ERROR" in line for line in proc.stdout.splitlines() if line.startswith("NOTE:"))


def test_ls_remote_error_note_old_bucket_predicate_is_structurally_zero(tmp_path):
    """Regression test proving the OLD predicate shape
    (`outcome_counts.get("SKIP_LS_REMOTE_ERROR", 0)`) is structurally
    ALWAYS 0 against the exact same fixture that makes the real NOTE fire
    above - `SKIP_LS_REMOTE_ERROR` is never a member of `_ALL_OUTCOMES`
    (it is a `Disposition` value folded into the `SKIP_UNPROVEN` outcome
    bucket's `reason` field), so `Counter(r["outcome"] for r in results)`
    can never produce that key at all. Confirmed failing pre-fix: before
    this unit, no NOTE printed at all for this fixture (the aggregate
    signal did not exist), so an `outcome_counts`-style bucket read would
    have silently reported 0 forever with no visible indication anything
    was wrong - this test pins that the reason-scan predicate is the only
    shape that can ever see the real count."""
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-lsr3", "worktree-agent-lsr3", push=False)
    (wt / "extra.txt").write_text("unique unpushed work\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unique commit")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))

    proc = run_reap(repo, dry_run=True, no_gh=False)
    assert proc.returncode == 0, proc.stderr

    # The real, ACTUAL outcome bucketing this tool computes internally
    # (mirroring `Counter(r["outcome"] for r in results)` exactly, built
    # from the same --explain per-entry output the tool prints) - proves
    # the old bucket-read shape reads 0 even though a real
    # SKIP_LS_REMOTE_ERROR entry genuinely exists in this exact run.
    entry_outcomes = list(outcomes(proc.stdout).values())
    outcome_counts = {}
    for full in entry_outcomes:
        bucket = full.split(" ", 1)[0]  # "SKIP_UNPROVEN (SKIP_LS_REMOTE_ERROR)" -> "SKIP_UNPROVEN"
        outcome_counts[bucket] = outcome_counts.get(bucket, 0) + 1
    assert outcome_counts.get("SKIP_LS_REMOTE_ERROR", 0) == 0  # old predicate: always 0, never sees it
    assert outcome_counts.get("SKIP_UNPROVEN", 0) == 1  # the real entry, correctly bucketed
    # And the NOTE fired anyway, via the reason-scan predicate that DOES see it.
    assert "NOTE: 1 of 2 worktree(s) are SKIP_UNPROVEN (SKIP_LS_REMOTE_ERROR)" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------
# DS-189 Unit A: `--init-config` scaffolds `~/.agentic/cleanup-worktrees.json`
# for a first-time `--multi-repo` setup.
# --------------------------------------------------------------------------


def test_init_config_writes_skeleton_on_absent_file(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(ds_cleanup_worktrees, "_MULTI_REPO_CONFIG_PATH", fake_home / ".agentic" / "cleanup-worktrees.json")
    rc = ds_cleanup_worktrees._init_config()
    assert rc == 0
    config_path = fake_home / ".agentic" / "cleanup-worktrees.json"
    assert config_path.is_file()
    import json as _json

    assert _json.loads(config_path.read_text()) == {"roots": [], "repos": []}


def test_init_config_creates_agentic_dir_when_missing(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake-home-2"
    fake_home.mkdir()
    assert not (fake_home / ".agentic").exists()
    monkeypatch.setattr(ds_cleanup_worktrees, "_MULTI_REPO_CONFIG_PATH", fake_home / ".agentic" / "cleanup-worktrees.json")
    rc = ds_cleanup_worktrees._init_config()
    assert rc == 0
    assert (fake_home / ".agentic").is_dir()


def test_init_config_never_overwrites_existing_file(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake-home-3"
    (fake_home / ".agentic").mkdir(parents=True)
    config_path = fake_home / ".agentic" / "cleanup-worktrees.json"
    original_content = '{"roots": ["/some/custom/root"], "repos": []}'
    config_path.write_text(original_content)
    monkeypatch.setattr(ds_cleanup_worktrees, "_MULTI_REPO_CONFIG_PATH", config_path)

    rc = ds_cleanup_worktrees._init_config()
    assert rc == 0
    assert config_path.read_text() == original_content  # byte-identical after a second run


def test_init_config_via_cli_rejects_extra_args(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--init-config", "--dry-run"],
        capture_output=True,
        text=True,
        env=dict(os.environ, HOME=str(tmp_path)),
    )
    assert proc.returncode == 2
    assert "--init-config cannot be combined with any other flag" in proc.stderr


def test_init_config_via_cli_end_to_end(tmp_path):
    fake_home = tmp_path / "cli-home"
    fake_home.mkdir()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--init-config"],
        capture_output=True,
        text=True,
        env=dict(os.environ, HOME=str(fake_home)),
    )
    assert proc.returncode == 0, proc.stderr
    config_path = fake_home / ".agentic" / "cleanup-worktrees.json"
    assert config_path.is_file()
    import json as _json

    assert _json.loads(config_path.read_text()) == {"roots": [], "repos": []}

    # Second run: never overwrites, exits 0, reports current contents.
    proc2 = subprocess.run(
        [sys.executable, str(SCRIPT), "--init-config"],
        capture_output=True,
        text=True,
        env=dict(os.environ, HOME=str(fake_home)),
    )
    assert proc2.returncode == 0, proc2.stderr
    assert "already exists - not overwriting" in proc2.stdout


# --------------------------------------------------------------------------
# DS-191 round-N (Skeptic Minor 5). The TOCTOU retry path had zero coverage:
#     mutating its guard condition to `if False:` left the whole suite at
#     115 passed. Direct unit test of _archive_branch_bundle, monkeypatching
#     _run to force the FIRST `git bundle create ... --not <ref>` call to
#     fail with the EXACT documented race signature (rc=128, "Refusing to
#     create empty bundle") despite a passing pre-check - a concurrent
#     fetch advancing exclude_ref past the branch tip between the rev-list
#     --count measurement and the actual create call.
# --------------------------------------------------------------------------


def test_archive_bundle_toctou_retry_recovers_from_concurrent_fetch_race(tmp_path):
    """Mutation that reddens this test: changing the retry guard
    (`if used_exclusion and proc.returncode == 128 and "Refusing to create
    empty bundle" in proc.stderr:`) to `if False:` in
    `_archive_branch_bundle` makes this test fail with `ok=False` - the
    exact regression this guards against (confirmed by running this
    assertion shape against that mutant before landing the test: with the
    mutant in place, `ok` came back `False` and `detail` contained
    "git bundle create failed" instead of a successful retry)."""
    mod = _load_module_directly()
    repo, _origin = init_repo_with_origin(tmp_path)
    branch = "worktree-agent-toctou"
    _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-toctou", branch)

    real_run = mod._run
    calls = {"bundle_create_attempts": 0}

    def fake_run(args, cwd=None, timeout=None):
        if "bundle" in args and "create" in args:
            calls["bundle_create_attempts"] += 1
            if "--not" in args:
                # Simulate the documented TOCTOU race: exclude_ref
                # advanced past the branch tip between the rev-list
                # pre-check and this call, reproducing the exact failure
                # signature the retry guard keys off.
                return subprocess.CompletedProcess(
                    args, returncode=128, stdout="", stderr="fatal: Refusing to create empty bundle."
                )
        return real_run(args, cwd=cwd, timeout=timeout)

    mod._run = fake_run
    try:
        ok, detail, bundle_path, compact = mod._archive_branch_bundle(str(repo), branch, "main")
    finally:
        mod._run = real_run

    assert ok is True, detail
    assert compact is False, "the retry-without-exclusion path must report compact=False"
    assert bundle_path is not None and Path(bundle_path).stat().st_size > 0
    assert calls["bundle_create_attempts"] == 2, (
        f"expected exactly one failed compact attempt plus one successful retry, got "
        f"{calls['bundle_create_attempts']} bundle create attempts"
    )


# --------------------------------------------------------------------------
# DS-191 round-N (Skeptic Major 2). `resolve_base_branch` returns an
#     explicit --base COMPLETELY UNVALIDATED - nothing constrains it to a
#     durable ref. Compacting against it unconditionally created a NEW
#     permanent-loss path: `--base origin/feat-x` (a real, verifiable ref
#     sharing history with the branch) produced compact=True, and deleting
#     + gc'ing feat-x afterward made the restore fail irrecoverably
#     ("Repository lacks these prerequisite commits"). Fix: compaction is
#     only allowed for an explicit --base when it resolves to the SAME
#     commit this tool's own auto-resolution would have picked.
# --------------------------------------------------------------------------


def test_archive_compaction_base_skips_when_explicit_base_mismatches_auto_resolution(tmp_path):
    mod = _load_module_directly()
    repo, _origin = init_repo_with_origin(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat-x")
    (repo / "feat-x-file.txt").write_text("feature work\n")
    _git(repo, "add", "feat-x-file.txt")
    _git(repo, "commit", "-q", "-m", "feat-x work")
    _git(repo, "push", "-q", "origin", "feat-x")
    _git(repo, "checkout", "-q", "main")

    result = mod._archive_compaction_base(str(repo), "origin/feat-x", "explicit")
    assert result is None, (
        f"expected compaction to be REFUSED for an explicit base that does not match "
        f"auto-resolution, got exclude_ref={result!r}"
    )

    # Sanity: the SAME ref, when base_source is NOT "explicit" (i.e. it
    # came from auto-resolution itself), passes through unchanged - the
    # gate is keyed on base_source, not on the ref's identity.
    result_auto = mod._archive_compaction_base(str(repo), "origin/feat-x", "main-fallback")
    assert result_auto == "origin/feat-x"

    # An explicit base that DOES resolve to the same commit auto-resolution
    # would pick (here "main" and "origin/main" are identical) is allowed
    # through, returned as the durable auto-resolved ref itself.
    result_match = mod._archive_compaction_base(str(repo), "main", "explicit")
    assert result_match == "origin/main"


def test_archive_unproven_explicit_base_mismatch_survives_base_deletion_end_to_end(tmp_path):
    """End-to-end reproduction of the exact scenario the Skeptic
    demonstrated pre-fix: an explicit --base that verifies and shares
    history with the branch, but doesn't match auto-resolution, must
    produce a full-history (self-contained) bundle - proven here by
    deleting and gc'ing the explicit base branch AFTER archiving and
    showing the restore still succeeds, which a compact bundle against
    that base would NOT survive.

    The unproven branch is forked from feat-x's own tip (not from main),
    so feat-x's tip commit is genuinely the bundle's would-be prerequisite
    under compaction. The archived branch ref itself is also deleted
    below, before gc - otherwise it would keep pinning feat-x's tip as an
    ancestor of its own history, making the branch-and-gc sequence unable
    to orphan anything regardless of which base the bundle was built
    against."""
    repo, origin = init_repo_with_origin(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat-x")
    (repo / "feat-x-file.txt").write_text("feature work\n")
    _git(repo, "add", "feat-x-file.txt")
    _git(repo, "commit", "-q", "-m", "feat-x work")
    _git(repo, "push", "-q", "origin", "feat-x")

    branch = "worktree-agent-explicit-base-mismatch"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-explicit-base-mismatch", branch)
    _git(repo, "checkout", "-q", "main")

    proc = run_reap(
        repo,
        dry_run=False,
        no_gh=False,
        base="origin/feat-x",
        extra=["--archive-unproven"],
        gh_dir=_fake_gh_dir(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)].startswith("ARCHIVED_AND_REMOVED")
    assert "NOTE:" in proc.stderr
    assert "explicitly via --base" in proc.stderr
    assert "not guaranteed durable" in proc.stderr

    archive_dir = repo / ".agentic" / "worktree-archive"
    bundles = sorted(archive_dir.glob(f"{branch}-*.bundle"))
    assert len(bundles) == 1
    header, _, _ = bundles[0].read_bytes().partition(b"\n\n")
    header_lines = header.split(b"\n")
    assert not any(line.startswith(b"-") for line in header_lines), (
        f"expected NO prerequisite header line (full-history bundle) when the explicit "
        f"base does not match auto-resolution, got: {header_lines!r}"
    )

    # Delete + gc the explicit base branch everywhere - the exact
    # permanent-loss trigger. A compact bundle against feat-x would now be
    # unrestorable ("Repository lacks these prerequisite commits"); a
    # full-history bundle has no such dependency. The archived branch ref
    # ITSELF must also be deleted here (this tool never deletes it as
    # part of --archive-unproven, by design) - otherwise it keeps
    # feat-x's tip reachable as its own ancestor and gc can never orphan
    # it, regardless of which base the bundle was built against. HEAD's
    # own reflog (populated by the `checkout` calls above) ALSO keeps the
    # deleted commit reachable indefinitely - `git gc --prune=now` on its
    # own does NOT expire reflog entries (measured: a plain `checkout ->
    # branch -D -> gc --prune=now` sequence leaves the deleted commit
    # present), so an explicit `reflog expire` is required first for the
    # prune to actually happen.
    _git(repo, "push", "-q", "origin", "--delete", "feat-x")
    _git(repo, "branch", "-D", "feat-x")
    _git(repo, "branch", "-D", branch)
    subprocess.run(["git", "-C", str(origin), "branch", "-D", "feat-x"], capture_output=True, text=True)
    _git(repo, "remote", "prune", "origin")
    _git(repo, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all")
    subprocess.run(["git", "-C", str(repo), "gc", "--prune=now", "--aggressive"], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(origin), "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all"], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(origin), "gc", "--prune=now", "--aggressive"], capture_output=True, text=True)

    restore_proc = subprocess.run(
        ["git", "-C", str(repo), "fetch", str(bundles[0]), f"refs/heads/{branch}:refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    assert restore_proc.returncode == 0, (
        f"restore must succeed even after the explicit base branch is deleted and gc'd, "
        f"since compaction was correctly refused: {restore_proc.stderr}"
    )


# --------------------------------------------------------------------------
# DS-191 follow-up (closes a regression-test gap in PR #797, `64e4e330`).
#
# The test above proves the guard (`_archive_compaction_base`'s
# explicit-base-mismatch refusal) produces a full-history bundle that
# SURVIVES the mismatched base being destroyed and gc'd. It never proves
# the INVERSE: that had compaction been applied against that same unsafe
# base anyway, the resulting bundle would have become genuinely
# unrestorable. Without that inverse, the guard's refusal is unfalsifiable
# from this suite's point of view - a no-op guard and a load-bearing one
# would both make the sibling test pass.
#
# This test supplies the inverse directly: it calls `_archive_branch_bundle`
# with `exclude_ref` set to the SAME unsafe base (`origin/feat-x`) that
# `_archive_compaction_base` would refuse to use - i.e. it constructs
# exactly the bundle a defect in that guard would produce - then destroys
# and gc's that base (same sequence as the sibling test, both repos) and
# asserts the restore FAILS with git's own prerequisite error. This is an
# observable-restorability assertion, not a return-value or header-line
# proxy (both of those are asserted first, as preconditions, but the
# defect this test guards against is a data-loss defect, so the payoff
# assertion is the actual failed `git fetch` from the bundle).
# --------------------------------------------------------------------------


def test_archive_bundle_compaction_against_unsafe_base_becomes_unrestorable_after_base_destroyed_end_to_end(tmp_path):
    """Fork point: the unproven branch is forked from `feat-x`'s own tip
    (not from `main`), same as the sibling test above and for the same
    reason - `feat-x`'s tip must genuinely be the bundle's prerequisite
    under compaction, or destroying `feat-x` proves nothing."""
    mod = _load_module_directly()
    repo, origin = init_repo_with_origin(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat-x")
    (repo / "feat-x-file.txt").write_text("feature work\n")
    _git(repo, "add", "feat-x-file.txt")
    _git(repo, "commit", "-q", "-m", "feat-x work")
    _git(repo, "push", "-q", "origin", "feat-x")

    branch = "worktree-agent-unsafe-compact"
    wt = _make_unproven_branch_worktree(repo, ".claude/worktrees/agent-unsafe-compact", branch)
    _git(repo, "checkout", "-q", "main")

    # Bypass `_archive_compaction_base` entirely and pass the unsafe base
    # straight through, exactly as a defect in that guard would - this
    # function has no opinion of its own on whether `exclude_ref` is a
    # durable ref.
    ok, detail, bundle_path, compact = mod._archive_branch_bundle(str(repo), branch, "origin/feat-x")
    assert ok, detail
    assert compact is True, "expected genuine compaction against feat-x's tip"

    header, _, _ = Path(bundle_path).read_bytes().partition(b"\n\n")
    header_lines = header.split(b"\n")
    assert any(line.startswith(b"-") for line in header_lines), (
        f"expected a prerequisite (-prefixed) header line for a genuinely compact "
        f"bundle, got: {header_lines!r}"
    )

    # Remove the worktree and branch ref (this function never does either
    # itself), then destroy + gc `feat-x` on both the working repo and the
    # bare origin - the exact permanent-loss trigger. Sequence matches the
    # sibling test's own reflog-expiry discipline: `git gc --prune=now`
    # does NOT expire reflogs on its own, and the `checkout` calls above
    # populated HEAD's reflog with a path back to feat-x's tip, so an
    # explicit `reflog expire` is required before gc on BOTH repos.
    _git(repo, "worktree", "remove", "--force", str(wt))
    _git(repo, "branch", "-D", branch)
    _git(repo, "push", "-q", "origin", "--delete", "feat-x")
    _git(repo, "branch", "-D", "feat-x")
    subprocess.run(["git", "-C", str(origin), "branch", "-D", "feat-x"], capture_output=True, text=True)
    _git(repo, "remote", "prune", "origin")
    _git(repo, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all")
    subprocess.run(["git", "-C", str(repo), "gc", "--prune=now", "--aggressive"], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(origin), "reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all"], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(origin), "gc", "--prune=now", "--aggressive"], capture_output=True, text=True)

    restore_proc = subprocess.run(
        ["git", "-C", str(repo), "fetch", bundle_path, f"refs/heads/{branch}:refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    assert restore_proc.returncode != 0, (
        "expected restore to FAIL once the excluded base (feat-x) is destroyed and "
        "gc'd - this is the exact data-loss failure mode _archive_compaction_base's "
        "explicit-base-mismatch refusal exists to prevent; a restore that succeeds "
        "here would mean the guard defends against nothing"
    )
    assert "prerequisite" in restore_proc.stderr.lower(), restore_proc.stderr


# --------------------------------------------------------------------------
# DS-191 follow-up. `_archive_branch_bundle`'s compaction gate is
# `0 < unique_count < total_count` (bin/ds-cleanup-worktrees:1697). The
# lower bound (`unique_count == 0`, branch fully contained in the exclude
# ref) already has coverage via
# `test_archive_bundle_defensive_guard_skips_empty_exclusion` (a mutation
# widening the gate to admit 0 there is caught because the resulting
# `--not` argv would create an empty bundle, triggering this function's own
# TOCTOU retry path and changing the number of `git bundle create`
# invocations that test asserts on).
#
# The UPPER bound (`unique_count == total_count` - the branch shares NO
# commits with the exclude ref at all, e.g. a genuinely orphaned/disjoint
# history) had no coverage at all: measured directly against this
# checkout, widening the gate to `0 < unique_count <= total_count` left
# all 118 pre-existing tests in this file green. This test closes that
# gap. (It does not assert on restorability, unlike the test above -
# measured separately, a bundle built with `--not <exclude_ref>` against a
# disjoint history records NO prerequisite header line at all, since the
# traversal never reaches a commit reachable from `exclude_ref`; such a
# bundle is already self-contained regardless of whether `--not` was
# applied, so the discriminating observable is the header/compact flag,
# not restorability.)
# --------------------------------------------------------------------------


def test_archive_bundle_skips_exclusion_when_branch_shares_no_history_with_base(tmp_path):
    mod = _load_module_directly()
    repo, _origin = init_repo_with_origin(tmp_path)

    # An orphan branch has no common ancestor with `main` at all, so
    # `unique_count == total_count` relative to `main` - the exact upper
    # boundary this gate must refuse to compact against.
    _git(repo, "checkout", "-q", "--orphan", "disjoint-branch")
    _git(repo, "rm", "-rf", "-q", ".")
    (repo / "disjoint.txt").write_text("no shared history with main\n")
    _git(repo, "add", "disjoint.txt")
    _git(repo, "commit", "-q", "-m", "disjoint work")
    branch = "disjoint-branch"

    unique = _git(repo, "rev-list", "--count", branch, "--not", "main").stdout.strip()
    total = _git(repo, "rev-list", "--count", branch).stdout.strip()
    assert unique == total and int(total) > 0, (
        f"precondition: branch must share zero history with the exclude ref "
        f"(unique={unique}, total={total})"
    )

    ok, detail, bundle_path, compact = mod._archive_branch_bundle(str(repo), branch, "main")
    assert ok, detail
    assert compact is False, (
        "expected compaction to be refused when the branch shares no history with "
        "the exclude ref (unique_count == total_count)"
    )

    header, _, _ = Path(bundle_path).read_bytes().partition(b"\n\n")
    header_lines = header.split(b"\n")
    assert not any(line.startswith(b"-") for line in header_lines), (
        f"expected NO prerequisite header line when the branch shares no history "
        f"with the exclude ref, got: {header_lines!r}"
    )
