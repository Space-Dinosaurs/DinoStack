#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-reap-worktrees. Builds synthetic git
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

Upstream deps: bin/ds-reap-worktrees (module under test, invoked as a
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
             one `ds-reap-worktrees` subprocess invocation. Sub-second per
             test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

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
):
    """`gh_dir`, when given, is prepended onto PATH (round-6: `gh_dir` is
    normally the output of `_fake_gh_dir` below) so `_gh_available()`
    resolves a real, present, authenticated `gh` without any actual
    network/API dependency - required for any `--archive-unproven`
    scenario now that it refuses to run in degraded gh mode (Skeptic
    Major 2)."""
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
    if gh_dir is not None:
        env = dict(os.environ)
        env["PATH"] = f"{gh_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None, env=env)


def _fake_gh_dir(tmp_path: Path, *, pr_state: str = "") -> Path:
    """Round-6: a directory containing a stub `gh` executable answering
    `gh auth status` with success and `gh pr view <branch> --json state
    -q .state` with `pr_state` (empty stdout = no PR found, matching a real
    `gh pr view` on a branch with no PR). Zero real network/API dependency -
    used only by scenarios that need `--archive-unproven` to actually run,
    since it now refuses in degraded gh mode (see `--archive-unproven`
    requires PR evidence)."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\n'
        f'if [ "$1" = "pr" ] && [ "$2" = "view" ]; then echo "{pr_state}"; exit 0; fi\n'
        "exit 1\n"
    )
    gh.chmod(0o755)
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
        if line.startswith("ds-reap-worktrees:"):
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
    proc = run_reap(repo, dry_run=False, no_gh=False)
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
    assert proc.stdout.strip() == "ds-reap-worktrees: mode=count-only entries=2"
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

    loader = _ilm.SourceFileLoader("ds_reap_worktrees", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_reap_worktrees", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)

    start = time.monotonic()
    proc = mod._run(["sleep", "5"], timeout=1)
    elapsed = time.monotonic() - start
    assert proc.returncode != 0
    assert elapsed < 4.0, f"timeout wrapper did not bound the slow command (elapsed={elapsed:.2f}s)"


def _load_module_directly():
    """Imports bin/ds-reap-worktrees as a Python module (not a subprocess)
    for tests that need to monkeypatch its internals - notably forcing a
    `git bundle verify` failure specifically, which cannot be triggered
    reliably by any real filesystem manipulation (a bundle `git bundle
    create` just wrote in the SAME repo will always verify successfully;
    its prerequisites are trivially satisfied)."""
    import importlib.machinery as _ilm
    import importlib.util as _ilu

    loader = _ilm.SourceFileLoader("ds_reap_worktrees_direct", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_reap_worktrees_direct", loader)
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
            ok, detail, bundle_path = mod._archive_branch_bundle(str(repo), branch)
        finally:
            mod._run = real_run

        assert ok is False, f"expected verify failure to block archival, got ok={ok} detail={detail!r}"
        assert "verify" in detail.lower()
        assert bundle_path is None


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
