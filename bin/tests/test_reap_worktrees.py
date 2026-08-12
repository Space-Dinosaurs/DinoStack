#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-reap-worktrees. Builds synthetic git
         repositories (with a real bare `origin` remote) in tmp_path and
         drives the CLI end-to-end via subprocess, covering the removal
         predicate's every leg (branch-gone-from-origin, ancestor-of-base),
         every safety gate (dirty, locked-present, locked-missing,
         UNMANAGED/evals exclusion), and the dry-run/degraded mode-string
         composition bug class documented in this repo's MEMORY.md
         ("Reporting fields are a separate axis from behavior" -
         bin/ds-branch-prune shipped a bug printing mode=live during a
         dry run).

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-reap-worktrees (module under test, invoked as a
               subprocess CLI); real `git` CLI (subprocess, incl.
               `git worktree add/lock/prune`); no `gh` invocation in any
               scenario here - every scenario runs with `--no-gh` so
               these tests never depend on network or `gh` auth state.

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`).

Failure modes: each scenario builds its own isolated tmp_path repo/origin
               pair; no real DinoStack checkout, worktree, or branch state
               is ever touched by this file.

Performance: each scenario performs a handful of real `git` subprocess
             calls (init, bare-clone remote, worktree add/lock/prune) plus
             one `ds-reap-worktrees` subprocess invocation. Sub-second per
             test.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ds-reap-worktrees"


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


def add_worktree(repo: Path, rel_path: str, branch: str, *, push: bool = False) -> Path:
    """Creates a new branch + worktree at <repo>/<rel_path>. When `push` is
    True, pushes the branch to origin (so ls-remote resolves "pushed")."""
    wt_path = repo / rel_path
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(wt_path), "-b", branch)
    if push:
        _git(repo, "push", "-q", "-u", "origin", branch)
    return wt_path


def run_reap(repo: Path, *, dry_run: bool = True, no_gh: bool = True, base: str = "main", extra=None):
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--explain"]
    if dry_run:
        cmd.append("--dry-run")
    if no_gh:
        cmd.append("--no-gh")
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True)


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
        if line.startswith("ds-reap-worktrees:"):
            return line
    return ""


def worktree_paths(repo: Path) -> set:
    proc = _git(repo, "worktree", "list", "--porcelain")
    paths = set()
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(line[len("worktree ") :])
    return paths


# --------------------------------------------------------------------------
# 1. Branch never pushed to origin -> REMOVE via branch-gone-from-origin,
#    even when the branch has local commits diverging from base (the
#    worktree-removal-not-branch-deletion safety rationale).
# --------------------------------------------------------------------------


def test_unpushed_branch_removed_via_branch_gone_from_origin(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-1", "worktree-agent-1", push=False)
    (wt / "extra.txt").write_text("diverging local work\n")
    _git(wt, "add", "extra.txt")
    _git(wt, "commit", "-q", "-m", "unpushed extra commit")

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (branch-gone-from-origin)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 2. Branch pushed AND ancestor of base -> REMOVE via ancestor-of-base
#    (the branch-gone-from-origin leg does NOT fire here because the
#    branch was pushed).
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
# 3. Dirty worktree -> SKIP_DIRTY, regardless of otherwise-resolvable
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
# 4. Locked worktree whose directory still exists -> SKIP_LOCKED, never
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
# 5. Locked worktree whose directory is already gone -> SKIP_MISSING_LOCKED
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

    real_proc = run_reap(repo, dry_run=False)
    assert real_proc.returncode == 0, real_proc.stderr
    assert str(wt) not in worktree_paths(repo)
    assert "pruned-admin=1" in summary_line(real_proc.stdout)


# --------------------------------------------------------------------------
# 6. evals/.worktrees/* is always UNMANAGED and never removed, even with
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
# 7. --dry-run removes nothing, even for an eligible worktree.
# --------------------------------------------------------------------------


def test_dry_run_removes_nothing(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".claude/worktrees/agent-7", "worktree-agent-7", push=False)

    proc = run_reap(repo, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (branch-gone-from-origin)"
    # Still present - the outcome table shows what WOULD happen, not what did.
    assert str(wt) in worktree_paths(repo)


# --------------------------------------------------------------------------
# 8. Mode-string composition: dry-run AND degraded are independent axes
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
# 9. CONDUCTOR_CREATED classification (.agentic/worktrees/) resolves via
#    the same predicate as ISOLATION.
# --------------------------------------------------------------------------


def test_conductor_created_worktree_removed_same_predicate(tmp_path):
    repo, _origin = init_repo_with_origin(tmp_path)
    wt = add_worktree(repo, ".agentic/worktrees/some-feature", "feature/some-feature", push=False)

    proc = run_reap(repo, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result[str(wt)] == "REMOVE (branch-gone-from-origin)"
    assert str(wt) not in worktree_paths(repo)


# --------------------------------------------------------------------------
# 10. --repo pointing to a non-git directory is a usage error (exit 1),
#     never a silent no-op.
# --------------------------------------------------------------------------


def test_non_git_repo_is_usage_error(tmp_path):
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()
    proc = run_reap(not_a_repo, dry_run=True)
    assert proc.returncode == 1
    assert "not a git repository" in proc.stderr
