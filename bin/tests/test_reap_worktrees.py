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

import os
import shutil
import subprocess
import sys
import time
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
):
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--explain"]
    if dry_run:
        cmd.append("--dry-run")
    if no_gh:
        cmd.append("--no-gh")
    if min_age_hours is not None:
        cmd += ["--min-age-hours", min_age_hours]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)


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
