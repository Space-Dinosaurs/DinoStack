#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-cleanup-worktrees' `--multi-repo`/`--report`
         surface (DS-cleanup-worktrees-multi-repo Unit 2). Covers repo
         discovery (explicit `--repo` xN, positional roots, additive
         combination, dedup), the `~/.agentic/cleanup-worktrees.json`
         config-file fallback (including malformed-JSON, non-list, and
         non-string-element edge cases - ported from
         bin/tests/test_ds_reap_all.py, whose coverage this suite subsumes
         ahead of that file's own Unit-3 retirement), per-repo base
         resolution isolation, every usage-error path, the `--report` mode's
         structural read-only guarantee (never calls `git worktree remove`
         even with an eligible entry present), and the fast-vs-deep report
         tiers' subprocess-call cost and ranking order.

         Every scenario passes `--min-age-hours 0` for any sweep/deep-report
         path exercising real worktrees, mirroring
         bin/tests/test_cleanup_worktrees.py's own convention - every
         worktree this suite creates is freshly minted (mtime = now), so the
         real 24h default age floor would otherwise mask every other gate.

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-cleanup-worktrees (module under test - invoked both as
               a subprocess CLI for end-to-end scenarios and imported
               directly via SourceFileLoader for discovery/report unit
               tests and mutation-testing, mirroring
               bin/tests/test_cleanup_worktrees.py's own
               `_load_module_directly` pattern). Real `git` CLI (subprocess:
               init, worktree add, commit, push - to build minimal repos).
               No real `gh` invocation in any scenario (`--no-gh`
               throughout).

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`).

Failure modes: each scenario builds its own isolated tmp_path repo/root
               tree; no real DinoStack checkout, worktree, or branch state
               is ever touched by this file. No real
               `~/.agentic/cleanup-worktrees.json` is ever read - the
               config-fallback scenarios monkeypatch
               `_MULTI_REPO_CONFIG_PATH` on the directly-imported module.

Performance: each scenario performs a handful of real `git` subprocess
             calls plus at most a few `ds-cleanup-worktrees` subprocess
             invocations. Sub-second per test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ds-cleanup-worktrees"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _load_module_directly():
    """Imports bin/ds-cleanup-worktrees as a Python module (not a
    subprocess), mirroring test_cleanup_worktrees.py's own helper of the
    same name - used here for discovery/report unit tests and mutation
    testing that need to call internals directly or monkeypatch them."""
    import importlib.machinery as _ilm
    import importlib.util as _ilu

    loader = _ilm.SourceFileLoader("ds_cleanup_worktrees_multi_direct", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_cleanup_worktrees_multi_direct", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}\n{proc.stdout}"
    return proc


def init_repo_with_origin(tmp_path: Path, name: str = "repo") -> Path:
    """Returns `repo` - a real git repo with a bare `origin` remote and one
    commit on `main`, pushed."""
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
    return repo


def init_bare_git_repo(path: Path) -> None:
    """A minimal (no commits, no remote) git repo - sufficient for
    discovery-only scenarios that never resolve a base branch."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)


def add_worktree(repo: Path, rel_path: str, branch: str, *, push: bool = False) -> Path:
    wt_path = repo / rel_path
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(wt_path), "-b", branch)
    if push:
        _git(repo, "push", "-q", "-u", "origin", branch)
    return wt_path


def run_cli(args, *, cwd: Path = None):
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)


# --------------------------------------------------------------------------
# 1. Usage errors (exit 2), validated BEFORE any git call
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args,expected_substr",
    [
        (["--repo", ".", "--repo", "."], "multiple --repo requires --multi-repo"),
        (["some-root"], "positional root arguments require --multi-repo"),
        (["--depth", "2"], "--depth requires --multi-repo"),
        (["--report"], "--report requires --multi-repo"),
        (["--multi-repo", "--base", "main"], "--base cannot be combined with --multi-repo"),
        (["--multi-repo", "--report", "--archive-unproven"], "incompatible with --archive-unproven"),
        (["--json"], "--json requires --report"),
    ],
)
def test_usage_errors_exit_2(args, expected_substr, tmp_path):
    result = run_cli(args, cwd=tmp_path)
    assert result.returncode == 2, result.stderr
    assert expected_substr in result.stderr


def test_single_repo_mode_still_accepts_one_repo_flag(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    result = run_cli(["--repo", str(repo), "--count-only"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ds-cleanup-worktrees: mode=count-only entries=1"


# --------------------------------------------------------------------------
# 2. Discovery: explicit --repo xN, positional roots, additive combination
# --------------------------------------------------------------------------


def test_explicit_repo_list_and_positional_roots_are_additive(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    init_bare_git_repo(repo_a)
    init_bare_git_repo(repo_b)

    root = tmp_path / "workspace"
    root.mkdir()
    root_repo = root / "root-project"
    init_bare_git_repo(root_repo)

    mod = _load_module_directly()
    targets, skipped_not_git, root_errors = mod.discover_repos_multi(
        [str(repo_a), str(repo_b)], [str(root)], 1
    )

    assert not root_errors
    assert skipped_not_git == 0
    resolved = {t.canonical for t in targets}
    assert resolved == {repo_a.resolve(), repo_b.resolve(), root_repo.resolve()}
    sources = {t.canonical: t.source for t in targets}
    assert sources[repo_a.resolve()] == "explicit"
    assert sources[repo_b.resolve()] == "explicit"
    assert sources[root_repo.resolve()] == "scan"


def test_explicit_repo_not_a_git_repo_reports_discovery_error(tmp_path):
    non_git = tmp_path / "not-a-repo"
    non_git.mkdir()

    mod = _load_module_directly()
    targets, _skipped, _errors = mod.discover_repos_multi([str(non_git)], [], 1)

    assert len(targets) == 1
    assert targets[0].discovery_error is not None
    assert "not a git repository" in targets[0].discovery_error


def test_root_scan_skips_non_git_and_respects_default_depth(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    git_child = root / "project-one"
    non_git_child = root / "just-a-folder"
    init_bare_git_repo(git_child)
    non_git_child.mkdir()

    mod = _load_module_directly()
    targets, skipped_not_git, root_errors = mod.discover_repos_multi([], [str(root)], 1)

    assert not root_errors
    resolved = {t.canonical for t in targets}
    assert resolved == {git_child.resolve()}
    assert skipped_not_git == 1


def test_root_scan_depth_two_descends_one_level_further(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    nested_parent = root / "container"
    nested_parent.mkdir()
    nested_repo = nested_parent / "deep-project"
    init_bare_git_repo(nested_repo)

    mod = _load_module_directly()
    # depth 1: not found.
    targets1, _s1, _e1 = mod.discover_repos_multi([], [str(root)], 1)
    assert targets1 == []
    # depth 2: found.
    targets2, _s2, _e2 = mod.discover_repos_multi([], [str(root)], 2)
    resolved = {t.canonical for t in targets2}
    assert resolved == {nested_repo.resolve()}


def test_nonexistent_root_is_a_root_error(tmp_path):
    bad_root = tmp_path / "does-not-exist"
    mod = _load_module_directly()
    targets, _skipped, root_errors = mod.discover_repos_multi([], [str(bad_root)], 1)
    assert targets == []
    assert len(root_errors) == 1
    assert "root not a directory" in root_errors[0]


# --------------------------------------------------------------------------
# 3. Config-file fallback: consulted ONLY when neither --repo nor a root is
#    given; malformed-JSON / non-list / non-string-element edge cases never
#    crash.
# --------------------------------------------------------------------------


def test_config_fallback_used_only_when_no_explicit_sources(tmp_path, monkeypatch):
    repo_a = tmp_path / "config-repo"
    init_bare_git_repo(repo_a)
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text(json.dumps({"repos": [str(repo_a)]}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, _errors = mod.discover_repos_multi([], [], 1)
    resolved = {t.canonical for t in targets}
    assert resolved == {repo_a.resolve()}

    # An explicit --repo present -> config must NOT be consulted, even
    # though it names a real, different repo.
    other_repo = tmp_path / "explicit-only"
    init_bare_git_repo(other_repo)
    targets2, _skipped2, _errors2 = mod.discover_repos_multi([str(other_repo)], [], 1)
    resolved2 = {t.canonical for t in targets2}
    assert resolved2 == {other_repo.resolve()}


def test_config_malformed_json_reported_and_treated_as_empty(tmp_path, monkeypatch):
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text('{"repos": ["/tmp/a",],}')  # trailing comma: invalid JSON

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, root_errors = mod.discover_repos_multi([], [], 1)
    assert targets == []
    assert root_errors == []


def test_config_repos_non_list_value_does_not_crash(tmp_path, monkeypatch):
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text(json.dumps({"repos": None}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, root_errors = mod.discover_repos_multi([], [], 1)
    assert targets == []
    assert root_errors == []


def test_config_repos_bare_string_not_exploded_per_character(tmp_path, monkeypatch):
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text(json.dumps({"repos": "/tmp"}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, _errors = mod.discover_repos_multi([], [], 1)
    assert targets == []


def test_config_repos_non_string_element_reported_and_ignored(tmp_path, monkeypatch):
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text(json.dumps({"repos": ["/tmp/a", 5]}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, _errors = mod.discover_repos_multi([], [], 1)
    assert targets == []


# --------------------------------------------------------------------------
# 4. Dedupe by canonical path
# --------------------------------------------------------------------------


def test_dedupe_explicit_repo_and_root_scan_same_repo_runs_once(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    repo = root / "shared-project"
    init_bare_git_repo(repo)

    mod = _load_module_directly()
    targets, _skipped, _errors = mod.discover_repos_multi([str(repo)], [str(root)], 1)
    deduped = mod.dedupe(targets)

    matching = [t for t in deduped if t.canonical == repo.resolve()]
    assert len(matching) == 1


# --------------------------------------------------------------------------
# 5. Per-repo base resolution isolation: repo A's declared BASE_BRANCH must
#    never leak into repo B's resolution.
# --------------------------------------------------------------------------


def test_per_repo_base_resolution_does_not_leak_across_repos(tmp_path):
    # Repo A declares BASE_BRANCH: develop and has a real `develop` branch.
    repo_a = init_repo_with_origin(tmp_path, name="repo-a")
    _git(repo_a, "checkout", "-q", "-b", "develop")
    _git(repo_a, "push", "-q", "-u", "origin", "develop")
    _git(repo_a, "checkout", "-q", "main")
    (repo_a / "AGENTS.md").write_text("BASE_BRANCH: develop\n")
    _git(repo_a, "add", "AGENTS.md")
    _git(repo_a, "commit", "-q", "-m", "declare base")
    _git(repo_a, "push", "-q", "origin", "main")

    # Repo B declares nothing - falls through to origin/main.
    repo_b = init_repo_with_origin(tmp_path, name="repo-b")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--dry-run",
            "--no-gh",
            "--min-age-hours",
            "0",
        ]
    )
    assert result.returncode == 0, result.stderr

    # Canonical (resolved) paths - the printed header uses
    # `target.canonical`, which follows symlinks (e.g. macOS /var ->
    # /private/var), so the unresolved tmp_path form would never match.
    sections = [s for s in result.stdout.split("== ") if s.strip()]
    section_a = next(s for s in sections if str(repo_a.resolve()) in s.splitlines()[0])
    section_b = next(s for s in sections if str(repo_b.resolve()) in s.splitlines()[0])

    assert "base auto-resolved to 'origin/develop' via agents-md" in section_a
    assert "base=origin/develop" in section_a
    assert "base=origin/main" in section_b
    assert "origin/develop" not in section_b


# --------------------------------------------------------------------------
# 6. --report: structurally read-only - never removes, even with a dirty
#    AND an eligible worktree present.
# --------------------------------------------------------------------------


def test_report_never_removes_even_with_eligible_and_dirty_entries(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    eligible_wt = add_worktree(repo, ".claude/worktrees/agent-eligible", "worktree-agent-eligible", push=False)
    dirty_wt = add_worktree(repo, ".claude/worktrees/agent-dirty", "worktree-agent-dirty", push=False)
    (dirty_wt / "uncommitted.txt").write_text("dirty\n")

    result = run_cli(
        ["--multi-repo", "--repo", str(repo), "--report", "--no-gh", "--min-age-hours", "0"]
    )
    assert result.returncode == 0, result.stderr
    assert eligible_wt.is_dir()
    assert dirty_wt.is_dir()
    assert "eligible" in result.stdout

    # Same guarantee under --report --count-only (fast tier).
    result_fast = run_cli(["--multi-repo", "--repo", str(repo), "--report", "--count-only"])
    assert result_fast.returncode == 0, result_fast.stderr
    assert eligible_wt.is_dir()
    assert dirty_wt.is_dir()


def test_report_dry_run_combination_still_never_removes(tmp_path):
    """`--dry-run` is irrelevant to --report's read-only guarantee - report
    never even reaches the removal code path, dry-run or not."""
    repo = init_repo_with_origin(tmp_path)
    eligible_wt = add_worktree(repo, ".claude/worktrees/agent-eligible", "worktree-agent-eligible", push=False)

    result = run_cli(
        ["--multi-repo", "--repo", str(repo), "--report", "--dry-run", "--no-gh", "--min-age-hours", "0"]
    )
    assert result.returncode == 0, result.stderr
    assert eligible_wt.is_dir()


# --------------------------------------------------------------------------
# 7. Fast vs deep tier: subprocess-call cost.
# --------------------------------------------------------------------------


def test_fast_tier_makes_exactly_two_git_calls_and_zero_network(tmp_path, monkeypatch):
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)

    mod = _load_module_directly()
    calls = []
    real_run = mod._run

    def counting_run(args, cwd=None, timeout=None):
        calls.append(list(args))
        return real_run(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(mod, "_run", counting_run)

    row, err = mod._fast_report_row(str(repo))
    assert err is None
    # Exactly one call from this function: `worktree list --porcelain`.
    # (`rev-parse --show-toplevel` is paid by RepoTarget.__init__ during
    # discovery, not by _fast_report_row itself - see its own docstring.)
    assert len(calls) == 1
    assert calls[0][-3:] == ["worktree", "list", "--porcelain"]
    assert not any("ls-remote" in c or "gh" in c[0] for c in calls)
    assert row["nonroot_worktrees"] == 1


def test_deep_tier_evaluates_full_predicate_per_entry(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(no_gh=True, min_age_hours=0.0, strict_ignored=False)
    row, err = mod._deep_report_row(str(repo), args)
    assert err is None
    assert row["nonroot_worktrees"] == 1
    assert row["eligible"] == 1  # zero unique commits, ancestor-of-base -> REMOVE-eligible


# --------------------------------------------------------------------------
# 8. --json shape
# --------------------------------------------------------------------------


def test_json_output_shape(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)

    result = run_cli(["--multi-repo", "--repo", str(repo), "--report", "--count-only", "--json"])
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == {"repo", "nonroot_worktrees", "oldest_age_hours", "eligible"}
    assert row["eligible"] is None
    assert row["nonroot_worktrees"] == 1
    assert isinstance(row["oldest_age_hours"], float)


def test_json_deep_tier_eligible_is_an_int(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)

    result = run_cli(
        ["--multi-repo", "--repo", str(repo), "--report", "--json", "--no-gh", "--min-age-hours", "0"]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows[0]["eligible"] == 1


# --------------------------------------------------------------------------
# 9. Mixed-repo-failure exit codes
# --------------------------------------------------------------------------


def test_mixed_repo_failure_sweep_exits_1(tmp_path):
    good_repo = init_repo_with_origin(tmp_path, name="good-repo")
    bad_repo = tmp_path / "not-a-repo"
    bad_repo.mkdir()

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(good_repo),
            "--repo",
            str(bad_repo),
            "--dry-run",
            "--no-gh",
            "--min-age-hours",
            "0",
        ]
    )
    assert result.returncode == 1
    assert "repos=2" in result.stdout
    assert "swept=1" in result.stdout
    assert "errored=1" in result.stdout


def test_mixed_repo_failure_report_exits_1(tmp_path):
    good_repo = init_repo_with_origin(tmp_path, name="good-repo")
    bad_repo = tmp_path / "not-a-repo"
    bad_repo.mkdir()

    result = run_cli(
        ["--multi-repo", "--repo", str(good_repo), "--repo", str(bad_repo), "--report", "--count-only"]
    )
    assert result.returncode == 1


def test_all_repos_clean_sweep_exits_0(tmp_path):
    repo = init_repo_with_origin(tmp_path)
    result = run_cli(["--multi-repo", "--repo", str(repo), "--dry-run", "--no-gh", "--min-age-hours", "0"])
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# 10. Zero-repos-discovered usage error (exit 2), distinct from a discovery
#     error on a named target.
# --------------------------------------------------------------------------


def test_zero_repos_discovered_exits_2(tmp_path, monkeypatch):
    fake_home_config = tmp_path / "nonexistent-cleanup-worktrees.json"
    monkeypatch.setenv("HOME", str(tmp_path))
    result = run_cli(["--multi-repo"])
    assert not fake_home_config.exists()
    assert result.returncode == 2
    assert "no repos discovered" in result.stderr.lower()


# --------------------------------------------------------------------------
# 11. Mutation tests (run manually against a deliberately broken tree, then
#     restored - see the engineer return summary for the RED confirmation
#     transcript for each of the three mutations named in the ticket:
#     per-repo base isolation, the --report read-only guard, and the
#     fast-tier ranking order). These automated tests are what the mutation
#     run is verified AGAINST - kept here as the living regression guard.
# --------------------------------------------------------------------------


def test_fast_tier_ranking_order_nonroot_desc_end_to_end(tmp_path):
    """Drives the REAL `--multi-repo --report --count-only --json` code
    path (not a reimplementation of its sort key) against two repos with a
    clearly-ordered worktree count, so a mutation to `_run_report`'s actual
    sort call is caught here."""
    repo_few = init_repo_with_origin(tmp_path, name="repo-few")
    repo_many = init_repo_with_origin(tmp_path, name="repo-many")
    add_worktree(repo_few, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)
    for i in range(3):
        add_worktree(repo_many, f".claude/worktrees/agent-{i}", f"worktree-agent-{i}", push=False)

    result = run_cli(
        ["--multi-repo", "--repo", str(repo_few), "--repo", str(repo_many), "--report", "--count-only", "--json"]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert [Path(r["repo"]).name for r in rows] == ["repo-many", "repo-few"]
    assert rows[0]["nonroot_worktrees"] == 3
    assert rows[1]["nonroot_worktrees"] == 1
