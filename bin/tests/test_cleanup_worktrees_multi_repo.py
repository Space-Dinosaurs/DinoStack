#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-cleanup-worktrees' `--multi-repo`/`--report`
         surface (DS-cleanup-worktrees-multi-repo Unit 2). Covers repo
         discovery (explicit `--repo` xN, positional roots, additive
         combination, dedup), the `~/.agentic/cleanup-worktrees.json`
         config-file fallback (including malformed-JSON, non-list, and
         non-string-element edge cases - ported from the now-retired
         bin/tests/test_ds_reap_all.py, whose coverage this suite fully
         subsumed), per-repo base
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
import os
import subprocess
import sys
import time
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


def test_nonexistent_root_only_cli_exits_1_with_summary_and_stderr(tmp_path):
    """Round-2 rework Major 2: the deleted bin/tests/test_ds_reap_all.py's
    `test_nonexistent_root_is_reported_error_exit_1` asserted three
    CLI-observable things for a bad-root-only invocation: exit code 1, the
    composed summary line, and the stderr diagnostic. The unit-level
    replacement above (`test_nonexistent_root_is_a_root_error`) only
    asserts `discover_repos_multi`'s return value and is mutation-provably
    blind to the exit-code contract: changing `_run_multi_repo`'s
    `if not targets and not root_errors:` guard (bin/ds-cleanup-worktrees)
    to `if not targets:` flips this exact scenario from the documented
    exit 1 to exit 2 while every other test in this suite (including
    `test_one_bad_root_among_good_ones_still_sweeps_the_rest`, which always
    has a good repo and so never reaches this guard) stays green. This
    test drives the real CLI end to end so that guard is caught."""
    bad_root = tmp_path / "definitely-not-here-12345"
    assert not bad_root.exists()

    result = run_cli(["--multi-repo", str(bad_root)])

    assert result.returncode == 1
    summary_line = [
        ln for ln in result.stdout.splitlines() if ln.startswith("ds-cleanup-worktrees: repos=")
    ][-1]
    assert "repos=0 swept=0 errored=0 root-errors=1 skipped-not-git=0" in summary_line
    assert f"root not a directory: {bad_root}" in result.stderr


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


def test_config_malformed_json_cli_reports_could_not_read_config(tmp_path, monkeypatch):
    """Round-2 rework Major 1: the deleted bin/tests/test_ds_reap_all.py's
    `test_malformed_config_json_reports_parse_failure_and_exits_2` asserted
    the CLI-observable stderr diagnostic (config path plus "could not read
    config") - its own comment noted this guards against malformed JSON
    having previously been SILENTLY SWALLOWED. The unit-level replacement
    above (`test_config_malformed_json_reported_and_treated_as_empty`) only
    asserts `discover_repos_multi`'s return value and is mutation-provably
    blind to that regression: deleting the `print(...)` in
    `_load_multi_repo_config` (bin/ds-cleanup-worktrees) leaves it green.
    This test drives the real CLI end to end so that print is guarded."""
    fake_home = tmp_path / "home"
    agentic_dir = fake_home / ".agentic"
    agentic_dir.mkdir(parents=True)
    config_path = agentic_dir / "cleanup-worktrees.json"
    # Trailing comma - invalid JSON, previously silently swallowed to {}
    # with no hint at all.
    config_path.write_text('{"repos": ["/tmp/a",],}')

    monkeypatch.setenv("HOME", str(fake_home))
    result = run_cli(["--multi-repo"])

    assert result.returncode == 2
    assert str(config_path) in result.stderr
    assert "could not read config" in result.stderr
    assert "no repos discovered" in result.stderr.lower()


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


def test_config_repos_non_string_element_reported_and_ignored(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "cleanup-worktrees.json"
    config_path.write_text(json.dumps({"repos": ["/tmp/a", 5]}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_MULTI_REPO_CONFIG_PATH", config_path)

    targets, _skipped, _errors = mod.discover_repos_multi([], [], 1)
    assert targets == []
    # The name says "reported" - assert the stderr report actually happens,
    # not just that the malformed field was ignored (round-2 rework Minor 2:
    # the prior version of this test asserted only `targets == []`, which
    # survives deleting the `print(...)` in `_config_string_list` entirely).
    captured = capsys.readouterr()
    assert '"repos"' in captured.err
    assert "must be a list of strings" in captured.err


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


def test_dedupe_collapses_two_subdirectories_of_the_same_repo(tmp_path):
    """Round-N Major 3: `RepoTarget.canonical` is the resolved GIT TOPLEVEL,
    not the operator-supplied path resolved on its own - two different
    subdirectories of the same repo must dedupe to ONE target, not two."""
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)
    sub_a = repo / "sub-a"
    sub_b = repo / "sub-b"
    sub_a.mkdir()
    sub_b.mkdir()

    mod = _load_module_directly()
    targets, _skipped, _errors = mod.discover_repos_multi([str(sub_a), str(sub_b)], [], 1)
    assert {t.canonical for t in targets} == {repo.resolve()}
    deduped = mod.dedupe(targets)
    assert len(deduped) == 1
    assert deduped[0].canonical == repo.resolve()


def test_repo_target_canonical_is_git_toplevel_not_raw_subdirectory(tmp_path):
    """Round-N Major 3 direct regression: `RepoTarget(subdir).canonical`
    must be the repo's TOPLEVEL, not the subdirectory itself - the bug was
    `RepoTarget.__init__` running `git rev-parse --show-toplevel` only to
    check its return code, discarding stdout, and leaving `canonical` as
    `Path(subdir).resolve()`."""
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)
    sub = repo / "sub"
    sub.mkdir()

    mod = _load_module_directly()
    target = mod.RepoTarget(str(sub), "explicit")
    assert target.discovery_error is None
    assert target.canonical == repo.resolve()


def test_subdirectory_repo_arg_resolves_identically_in_single_and_multi_repo_mode(tmp_path):
    """Round-N Major 3 end-to-end reproduction: identical `--repo
    <repo>/sub` input must produce the SAME verdict counts under
    single-repo mode and `--multi-repo` - before the fix, single-repo mode
    gave `removed=1 skipped-dirty=1` while multi-repo mode gave `removed=0
    skipped-unmanaged=2` for the identical input, because multi-repo mode
    ran every `git -C` call against the raw subdirectory instead of the
    repo's toplevel."""
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-eligible", "worktree-agent-eligible", push=False)
    dirty_wt = add_worktree(repo, ".claude/worktrees/agent-dirty", "worktree-agent-dirty", push=False)
    (dirty_wt / "uncommitted.txt").write_text("dirty\n")
    sub = repo / "sub"
    sub.mkdir()

    single = run_cli(["--repo", str(sub), "--dry-run", "--no-gh", "--min-age-hours", "0"])
    assert single.returncode == 0, single.stderr
    assert "removed=1" in single.stdout
    assert "skipped-dirty=1" in single.stdout

    multi = run_cli(["--multi-repo", "--repo", str(sub), "--dry-run", "--no-gh", "--min-age-hours", "0"])
    assert multi.returncode == 0, multi.stderr
    assert "removed=1" in multi.stdout
    assert "skipped-dirty=1" in multi.stdout


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


# Round-N Minor fix: a `--report --dry-run` combination test used to live
# here, but it was VACUOUS for its own docstring's claim - it passed
# unchanged under a mutation deleting `main()`'s `if args.report: return
# _run_report(...)` short-circuit, because `--dry-run` alone already
# suppresses removal regardless of whether `--report`'s own early-return
# ever ran (the removal loop still computes `removed = len(remove_results)`
# but never calls `_salvage_and_remove` under `--dry-run`, so nothing is
# ever destroyed either way - the mutation is invisible from this angle).
# `test_report_never_removes_even_with_eligible_and_dirty_entries` above
# (no `--dry-run`) is the test that actually exercises and did go RED
# against that same mutation; the dry-run combination added no coverage
# beyond it, so it is deleted rather than kept as false confidence.


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
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"tier", "rows", "truncated"}
    assert payload["tier"] == "fast"
    assert payload["truncated"] is False
    rows = payload["rows"]
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
    payload = json.loads(result.stdout)
    assert payload["tier"] == "deep"
    rows = payload["rows"]
    assert rows[0]["eligible"] == 1
    # Round-N Minor fix: the deep tier now populates oldest_age_hours too
    # (previously hardcoded None, contradicting the documented shape).
    assert isinstance(rows[0]["oldest_age_hours"], float)


def test_json_tier_marker_present_and_correct_for_both_tiers(tmp_path):
    """Round-N Major 5: a machine JSON consumer must be able to tell a
    fast-tier approximation from a deep-tier result without separately
    tracking which flags produced it."""
    repo = init_repo_with_origin(tmp_path)
    add_worktree(repo, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)

    fast = run_cli(["--multi-repo", "--repo", str(repo), "--report", "--count-only", "--json"])
    assert json.loads(fast.stdout)["tier"] == "fast"

    deep = run_cli(
        ["--multi-repo", "--repo", str(repo), "--report", "--json", "--no-gh", "--min-age-hours", "0"]
    )
    assert json.loads(deep.stdout)["tier"] == "deep"


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


def test_base_unresolvable_repo_is_skipped_not_swept_and_exits_1(tmp_path):
    """Round-N Major 1: a repo whose declared BASE_BRANCH cannot be
    resolved must NOT be silently counted as `swept`, and the sweep exit
    code must agree with `--report`'s own identical-condition exit 1."""
    repo_a = init_repo_with_origin(tmp_path, name="repo-a")
    (repo_a / "AGENTS.md").write_text("BASE_BRANCH: nonexistent-base\n")
    _git(repo_a, "add", "AGENTS.md")
    _git(repo_a, "commit", "-q", "-m", "declare unresolvable base")
    _git(repo_a, "push", "-q", "origin", "main")

    repo_b = init_repo_with_origin(tmp_path, name="repo-b")

    sweep = run_cli(
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
    assert sweep.returncode == 1, sweep.stderr
    summary_line = [ln for ln in sweep.stdout.splitlines() if ln.startswith("ds-cleanup-worktrees: repos=")][-1]
    assert "repos=2" in summary_line
    assert "swept=1" in summary_line  # only repo_b, not repo_a
    assert "skipped-base-unresolved=1" in summary_line

    # --report agrees with the sweep on this exact condition (both exit 1).
    report = run_cli(
        ["--multi-repo", "--repo", str(repo_a), "--repo", str(repo_b), "--report", "--no-gh", "--min-age-hours", "0"]
    )
    assert report.returncode == 1, report.stderr


def test_one_bad_root_among_good_ones_still_sweeps_the_rest(tmp_path):
    """Ported from the now-retired bin/tests/test_ds_reap_all.py's own test
    of the same name (Skeptic-mapped coverage-subsumption gap): a root that
    is not a directory must not halt the sweep of every other good
    root/repo, and the root error is reported distinctly from a repo-level
    error."""
    root = tmp_path / "workspace"
    root.mkdir()
    good_repo = init_repo_with_origin(root, name="good-project")
    bad_root = tmp_path / "does-not-exist-at-all"

    result = run_cli(["--multi-repo", str(root), str(bad_root), "--dry-run", "--no-gh", "--min-age-hours", "0"])

    assert result.returncode == 1
    summary_line = [ln for ln in result.stdout.splitlines() if ln.startswith("ds-cleanup-worktrees: repos=")][-1]
    assert "repos=1" in summary_line
    assert "swept=1" in summary_line
    assert "errored=0" in summary_line
    assert "root-errors=1" in summary_line


def test_runtime_repo_failure_mid_sweep_continues_and_errors(tmp_path, monkeypatch, capsys):
    """Round-3 rework (Skeptic Major): recovers the now-retired
    bin/tests/test_ds_reap_all.py's `test_one_repo_failure_does_not_stop_the_sweep`
    / `test_summary_counts_correct_with_mixed_outcomes` coverage, adapted for
    the in-process `_run_repo` call now that the old subprocess-per-repo
    boundary (the `FAKE_REAP_FAIL_REPOS` fake-tool env var mechanism) is
    gone. Every OTHER multi-repo failure test in this file (see
    `test_mixed_repo_failure_sweep_exits_1`,
    `test_one_bad_root_among_good_ones_still_sweeps_the_rest`) fails at
    DISCOVERY (`target.discovery_error is not None`, bin/ds-cleanup-worktrees
    `_run_multi_repo`'s `continue` branch) and never enters `_run_repo`'s own
    error handling - proven unreachable by the Skeptic both by mutating
    `if rc != 0: repos_errored += 1` to `if False:` (suite stayed green) and
    by marker-file instrumentation of that branch (marker never created).

    This test instead monkeypatches `_worktree_list` - the first real `git`
    call INSIDE `_run_repo` (bin/ds-cleanup-worktrees:2137), reached only
    after discovery already succeeded for that repo (`target.discovery_error`
    is None) - to raise for one named repo only. That is a genuine RUNTIME
    failure, not a discovery failure, and drives `_run_repo`'s
    `except (RuntimeError, ValueError)` handler at :2139-2141 (`return 1`),
    which is the path `_run_multi_repo`'s `if rc != 0: repos_errored += 1`
    (:2534-2536) exists to aggregate."""
    mod = _load_module_directly()

    good_a = init_repo_with_origin(tmp_path, name="good-a")
    bad_b = init_repo_with_origin(tmp_path, name="bad-b")
    good_c = init_repo_with_origin(tmp_path, name="good-c")

    real_worktree_list = mod._worktree_list
    calls = []

    def fake_worktree_list(repo):
        calls.append(Path(repo).name)
        if Path(repo).name == "bad-b":
            raise RuntimeError("simulated runtime failure for bad-b")
        return real_worktree_list(repo)

    monkeypatch.setattr(mod, "_worktree_list", fake_worktree_list)

    args = mod.parse_args(
        [
            "--multi-repo",
            "--repo",
            str(good_a),
            "--repo",
            str(bad_b),
            "--repo",
            str(good_c),
            "--dry-run",
            "--no-gh",
            "--min-age-hours",
            "0",
        ]
    )

    rc = mod._run_multi_repo(args)
    captured = capsys.readouterr()

    # The sweep did not halt at bad-b - good-c was still reached.
    assert calls == ["good-a", "bad-b", "good-c"]

    assert rc == 1
    summary_line = [
        ln for ln in captured.out.splitlines() if ln.startswith("ds-cleanup-worktrees: repos=")
    ][-1]
    assert "repos=3" in summary_line
    assert "swept=3" in summary_line  # all 3 entered _run_repo (discovery succeeded for all)
    assert "errored=1" in summary_line


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
    rows = json.loads(result.stdout)["rows"]
    assert [Path(r["repo"]).name for r in rows] == ["repo-many", "repo-few"]
    assert rows[0]["nonroot_worktrees"] == 3
    assert rows[1]["nonroot_worktrees"] == 1


def test_deep_tier_ranking_order_reflects_eligible_not_raw_count(tmp_path):
    """Round-N Major 2: two repos with EQUAL raw nonroot_worktrees but
    genuinely different REMOVE-eligible counts must rank by eligible, not
    by the tied raw count - drives the real `--multi-repo --report --json`
    (deep tier) end to end so a mutation to `_run_report`'s actual sort key
    (`rows.sort(key=lambda r: -(r["eligible"] or 0))`) is caught here, not
    just at the sort-helper level.

    Round-4 Major 2 fix: `--repo` is passed LESS-eligible-first, the
    OPPOSITE of the expected ranked order - a round-3 version of this test
    passed `--repo` more-eligible-first (matching the expected order), so a
    stable sort with the deep-tier `rows.sort(...)` call deleted entirely,
    or reverted to the round-2 pre-fix line `rows.sort(key=lambda r:
    -(r["eligible"] or 0))` (no tiebreak - irrelevant here since there is
    no tie), still emitted the correct-looking order by discovery order
    alone. With the argument order reversed, only the real sort call
    produces the expected ranking."""
    repo_more_eligible = init_repo_with_origin(tmp_path, name="repo-more-eligible")
    add_worktree(repo_more_eligible, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)
    add_worktree(repo_more_eligible, ".claude/worktrees/agent-b", "worktree-agent-b", push=False)
    # Both worktrees clean, never pushed, no unique commits -> both
    # ancestor-of-base -> both REMOVE-eligible. eligible=2, nonroot=2.

    repo_less_eligible = init_repo_with_origin(tmp_path, name="repo-less-eligible")
    add_worktree(repo_less_eligible, ".claude/worktrees/agent-a", "worktree-agent-a", push=False)
    dirty_wt = add_worktree(repo_less_eligible, ".claude/worktrees/agent-b", "worktree-agent-b", push=False)
    (dirty_wt / "uncommitted.txt").write_text("dirty\n")
    # One clean+eligible, one dirty (never eligible). eligible=1, nonroot=2
    # - SAME raw count as repo_more_eligible, so a raw-count-based ranking
    # (or an inverted eligible sort) cannot distinguish them correctly.

    result = run_cli(
        [
            "--multi-repo",
            # Discovery order is LESS-eligible-first, opposite of the
            # expected ranked order - see the docstring above.
            "--repo",
            str(repo_less_eligible),
            "--repo",
            str(repo_more_eligible),
            "--report",
            "--json",
            "--no-gh",
            "--min-age-hours",
            "0",
        ]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["rows"]
    assert {r["nonroot_worktrees"] for r in rows} == {2}  # raw counts tied
    assert [Path(r["repo"]).name for r in rows] == ["repo-more-eligible", "repo-less-eligible"]
    assert rows[0]["eligible"] == 2
    assert rows[1]["eligible"] == 1


# --------------------------------------------------------------------------
# 12. Round-N Major 2/Minor 3: every ordering decision this module makes
#     that is capable of changing observable output must be pinned by a
#     fixture in which the WRONG order would be visible - a test that
#     passes when the sort is inverted is not a test of the sort. Each test
#     below was run against a deliberate one-line mutation flipping the
#     ordering decision under test and confirmed RED before being kept; see
#     the engineer return summary for the full enumeration and the RED
#     transcript for each mutation.
# --------------------------------------------------------------------------


def _backdate(path: Path, hours_ago: float) -> None:
    """Sets `path`'s mtime `hours_ago` hours in the past - the same
    `os.stat().st_mtime` signal `_worktree_age_hours` reads."""
    target = time.time() - hours_ago * 3600
    os.utime(path, (target, target))


def test_fast_tier_tiebreak_by_oldest_age_desc_on_count_tie(tmp_path):
    """Round-N Major 2: two repos TIED on nonroot_worktrees=1 must rank by
    oldest_age_hours DESC (the repo whose one worktree has accumulated MORE
    age ranks first/worse) - drives the real `--multi-repo --report
    --count-only --json` path end to end so a mutation to the tiebreak's
    sign (DESC -> ASC) is caught here. Before this test, all 138 tests in
    this suite stayed green under exactly that mutation.

    Round-4 Major 2 fix: `--repo` is passed YOUNGEST-first, the OPPOSITE of
    the expected ranked order (oldest-first) - a round-3 version passed
    `--repo` oldest-first (matching the expected order), so a stable sort
    with the fast-tier `rows.sort(...)` call deleted entirely still emitted
    the correct-looking order by discovery order alone."""
    repo_old = init_repo_with_origin(tmp_path, name="repo-old-worktree")
    old_wt = add_worktree(repo_old, ".claude/worktrees/agent-old", "worktree-agent-old", push=False)
    _backdate(old_wt, hours_ago=500)

    repo_young = init_repo_with_origin(tmp_path, name="repo-young-worktree")
    young_wt = add_worktree(repo_young, ".claude/worktrees/agent-young", "worktree-agent-young", push=False)
    _backdate(young_wt, hours_ago=1)

    result = run_cli(
        [
            "--multi-repo",
            # Discovery order is YOUNGEST-first, opposite of the expected
            # ranked order - see the docstring above.
            "--repo",
            str(repo_young),
            "--repo",
            str(repo_old),
            "--report",
            "--count-only",
            "--json",
        ]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["rows"]
    assert {r["nonroot_worktrees"] for r in rows} == {1}  # raw counts tied
    assert [Path(r["repo"]).name for r in rows] == ["repo-old-worktree", "repo-young-worktree"]
    assert rows[0]["oldest_age_hours"] > rows[1]["oldest_age_hours"]


def test_deep_tier_tiebreak_by_oldest_age_desc_on_eligible_tie(tmp_path):
    """Round-N Minor 3: two repos TIED on eligible=1 must rank by
    oldest_age_hours DESC too - the deep tier previously had no documented
    or implemented tiebreak at all, so a tie fell back to undocumented
    discovery order. Drives the real `--multi-repo --report --json` (deep
    tier) end to end so a mutation to `_run_report`'s deep-tier sort key
    that drops or inverts the tiebreak is caught here.

    Round-4 Major 2 fix: `--repo` is passed YOUNGEST-first, the OPPOSITE of
    the expected ranked order (oldest-first) - a round-3 version passed
    `--repo` oldest-first (matching the expected order), so a stable sort
    with the deep-tier `rows.sort(...)` call deleted entirely, or reverted
    to the round-2 pre-fix line `rows.sort(key=lambda r: -(r["eligible"] or
    0))` (no tiebreak - irrelevant here since eligible is tied at 1), still
    emitted the correct-looking order by discovery order alone."""
    repo_old = init_repo_with_origin(tmp_path, name="repo-old-eligible")
    old_wt = add_worktree(repo_old, ".claude/worktrees/agent-old", "worktree-agent-old", push=False)
    _backdate(old_wt, hours_ago=500)

    repo_young = init_repo_with_origin(tmp_path, name="repo-young-eligible")
    young_wt = add_worktree(repo_young, ".claude/worktrees/agent-young", "worktree-agent-young", push=False)
    _backdate(young_wt, hours_ago=1)

    result = run_cli(
        [
            "--multi-repo",
            # Discovery order is YOUNGEST-first, opposite of the expected
            # ranked order - see the docstring above.
            "--repo",
            str(repo_young),
            "--repo",
            str(repo_old),
            "--report",
            "--json",
            "--no-gh",
            "--min-age-hours",
            "0",
        ]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["rows"]
    assert {r["eligible"] for r in rows} == {1}  # eligible counts tied
    assert [Path(r["repo"]).name for r in rows] == ["repo-old-eligible", "repo-young-eligible"]
    assert rows[0]["oldest_age_hours"] > rows[1]["oldest_age_hours"]


def _add_three_mixed_age_worktrees(repo: Path) -> None:
    """Adds three worktrees to `repo` whose AGES and whose alphabetical
    NAME order deliberately disagree, so neither `ages[0]` nor `ages[-1]`
    (whatever order `git worktree list --porcelain` happens to enumerate
    them in - measured empirically to be alphabetical by path on this
    entry's fixture naming) can accidentally equal the true max. Only a
    genuine `max(ages)` reduction produces the correct answer:
      - agent-1 (alphabetically FIRST)  -> 10h  (youngest)
      - agent-2 (alphabetically MIDDLE) -> 500h (oldest - the true max)
      - agent-3 (alphabetically LAST)   -> 50h  (middling)
    """
    wt1 = add_worktree(repo, ".claude/worktrees/agent-1", "worktree-agent-1", push=False)
    _backdate(wt1, hours_ago=10)
    wt2 = add_worktree(repo, ".claude/worktrees/agent-2", "worktree-agent-2", push=False)
    _backdate(wt2, hours_ago=500)
    wt3 = add_worktree(repo, ".claude/worktrees/agent-3", "worktree-agent-3", push=False)
    _backdate(wt3, hours_ago=50)


def test_fast_tier_oldest_age_is_max_not_min_across_worktrees(tmp_path):
    """Round-4 Major 1: `_fast_report_row`'s `oldest_age = max(ages) if ages
    else None` (bin/ds-cleanup-worktrees:1902) is an unpinned ordering
    decision - every prior fixture in this suite gave a repo exactly ONE
    worktree, so `min(ages) == max(ages)` and mutating `max` to `min` left
    every test in the suite GREEN. This repo has THREE worktrees whose
    alphabetical order deliberately disagrees with their age order (see
    `_add_three_mixed_age_worktrees`), so neither `min(ages)` NOR a
    non-reducing "pick one element" mutation (`ages[0]`, `ages[-1]`) can
    accidentally satisfy this test the way a two-worktree, alphabetically-
    aligned fixture could - confirmed by execution: an `ages[0]`/`ages[-1]`
    mutation against a two-worktree version of this fixture passed
    (alphabetical == age order there), motivating this three-worktree
    redesign."""
    repo = init_repo_with_origin(tmp_path, name="repo-mixed-ages-fast")
    _add_three_mixed_age_worktrees(repo)

    result = run_cli(["--multi-repo", "--repo", str(repo), "--report", "--count-only", "--json"])
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["rows"]
    assert rows[0]["nonroot_worktrees"] == 3
    # The true max (~500h) must win over both the min (~10h) and the
    # middling third value (~50h) - only a real max() reduction lands here.
    assert 400 < rows[0]["oldest_age_hours"] < 600, rows[0]


def test_deep_tier_oldest_age_is_max_not_min_across_worktrees(tmp_path):
    """Round-4 Major 1: same defect as the fast-tier test above, but for
    `_deep_report_row`'s identical `oldest_age = max(ages) if ages else
    None` (bin/ds-cleanup-worktrees:1936) - mutating that `max` to `min`
    also left every prior test in this suite GREEN, because every prior
    deep-tier fixture likewise gave each repo exactly one worktree per
    repo. Uses the same three-worktree, alphabetically-disagreeing fixture
    as the fast-tier test above so a non-reducing "pick one element"
    mutation cannot accidentally pass either."""
    repo = init_repo_with_origin(tmp_path, name="repo-mixed-ages-deep")
    _add_three_mixed_age_worktrees(repo)

    result = run_cli(
        ["--multi-repo", "--repo", str(repo), "--report", "--json", "--no-gh", "--min-age-hours", "0"]
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["rows"]
    assert rows[0]["nonroot_worktrees"] == 3
    assert 400 < rows[0]["oldest_age_hours"] < 600, rows[0]


def test_scan_root_discovers_children_in_alphabetical_order(tmp_path):
    """Round-N Major 2: `_scan_root`'s `sorted(p for p in directory.iterdir()
    ...)` is a real ordering decision - it fixes discovery order, which
    `dedupe`'s first-seen-wins and the deep tier's tie fallback both depend
    on being deterministic. Calls `_scan_root` directly (not through the
    CLI) so a mutation removing `sorted(...)` or reversing it is caught
    here regardless of the filesystem's own raw iteration order, which
    `pathlib.Path.iterdir()` does NOT guarantee is alphabetical."""
    root = tmp_path / "workspace"
    root.mkdir()
    # Named so a filesystem's natural (non-sorted) iteration order would be
    # unlikely to already match alphabetical order by coincidence.
    for name in ("zzz-repo", "mmm-repo", "aaa-repo"):
        init_bare_git_repo(root / name)

    mod = _load_module_directly()
    found, _skipped = mod._scan_root(root, 1)
    assert [p.name for p in found] == ["aaa-repo", "mmm-repo", "zzz-repo"]


def test_dedupe_keeps_first_seen_source_explicit_before_scan(tmp_path):
    """Round-N Major 2: `dedupe`'s first-seen-wins is order-dependent on
    how `discover_repos_multi` concatenates targets (explicit `--repo`
    entries before scanned roots - see that function's own docstring), and
    `.source` IS observable output (`_run_multi_repo` prints
    `== <path> (<source>) ==` per repo). The existing dedup test at #4
    above only asserts survivor COUNT, which passes identically whichever
    duplicate wins since both point at the same path - this test asserts
    WHICH one wins, which a last-seen-wins mutation would flip."""
    root = tmp_path / "workspace"
    root.mkdir()
    repo = root / "shared-project"
    init_bare_git_repo(repo)

    mod = _load_module_directly()
    targets, _skipped, _errors = mod.discover_repos_multi([str(repo)], [str(root)], 1)
    deduped = mod.dedupe(targets)

    matching = [t for t in deduped if t.canonical == repo.resolve()]
    assert len(matching) == 1
    assert matching[0].source == "explicit"


# --------------------------------------------------------------------------
# 13. Round-N Major 1: the no-remote base-resolution diagnostic. All 11
#     live `skipped-base-unresolved` failures measured against this
#     machine's checkouts were repos with ZERO git remotes, not an
#     AGENTS.md BASE_BRANCH: failure - the generic "declare BASE_BRANCH, or
#     pass --base" remediation is a dead end for that case (a declaration
#     still resolves against origin/<name>, and --base is a hard usage
#     error under --multi-repo). These tests pin the corrected diagnostic
#     text and its mode-awareness directly against `resolve_base_branch`.
# --------------------------------------------------------------------------


def test_resolve_base_branch_names_no_remote_case_specifically(tmp_path):
    repo = tmp_path / "no-remote-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)

    mod = _load_module_directly()
    resolved, source, diagnostics = mod.resolve_base_branch(str(repo), None, multi_repo=False)
    assert resolved is None
    assert source == "unresolved"
    joined = "\n".join(diagnostics)
    assert "no git remotes configured" in joined
    assert "declaring BASE_BRANCH in AGENTS.md will not help" in joined
    # Single-repo mode: --base IS a legitimate suggestion here (it bypasses
    # remote resolution entirely and is accepted verbatim).
    assert "pass --base" in joined


def test_resolve_base_branch_no_remote_omits_base_suggestion_under_multi_repo(tmp_path):
    """Round-N Major 1: --base is a hard usage error under --multi-repo
    (see the usage-error test above), so the no-remote diagnostic must NOT
    suggest it there - a mutation that always includes the --base
    suggestion regardless of `multi_repo` is caught by this test."""
    repo = tmp_path / "no-remote-repo-multi"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)

    mod = _load_module_directly()
    resolved, source, diagnostics = mod.resolve_base_branch(str(repo), None, multi_repo=True)
    assert resolved is None
    assert source == "unresolved"
    joined = "\n".join(diagnostics)
    assert "no git remotes configured" in joined
    assert "--base" not in joined


def test_resolve_base_branch_with_remote_still_uses_generic_message(tmp_path):
    """A repo that DOES have a remote, but where every candidate genuinely
    fails validation (e.g. unfetched/stale refs), must keep getting the
    generic "every candidate failed" message, not the no-remote one - the
    no-remote branch must not fire for a repo that has a remote."""
    repo = init_repo_with_origin(tmp_path, name="repo-with-remote-no-candidates")
    # Remove the only ref this repo would otherwise resolve against so
    # every automatic candidate fails, without deleting the remote itself.
    subprocess.run(["git", "-C", str(repo), "branch", "-D", "main"], check=False)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "-d", "refs/remotes/origin/main"], check=False
    )
    subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-d", "refs/remotes/origin/HEAD"], check=False
    )

    mod = _load_module_directly()
    resolved, source, diagnostics = mod.resolve_base_branch(str(repo), None, multi_repo=True)
    assert resolved is None
    assert source == "unresolved"
    joined = "\n".join(diagnostics)
    assert "no git remotes configured" not in joined
    assert "every candidate failed" in joined


# --------------------------------------------------------------------------
# 15. DS-189 Unit A: `--max-repos` truncates the discovered-and-deduped
#     target list AFTER dedup, BEFORE any per-repo evaluation - bounding
#     git-call cost, not just display. Absent = unbounded (back-compat).
# --------------------------------------------------------------------------


def test_max_repos_truncates_before_evaluation_preserving_order(tmp_path, monkeypatch):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")
    repo_c = init_repo_with_origin(tmp_path, "repo-c")

    mod = _load_module_directly()
    evaluated = []
    real_fast = mod._fast_report_row

    def counting_fast(repo):
        evaluated.append(repo)
        return real_fast(repo)

    monkeypatch.setattr(mod, "_fast_report_row", counting_fast)

    args = mod.parse_args(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--repo",
            str(repo_c),
            "--report",
            "--count-only",
            "--max-repos",
            "2",
        ]
    )
    rc = mod._run_multi_repo(args)
    assert rc == 0
    # Per-repo evaluation cost is bounded to exactly N=2 calls - the 3rd
    # repo is never evaluated at all, not merely hidden from display.
    assert len(evaluated) == 2
    assert evaluated == [str(repo_a.resolve()), str(repo_b.resolve())]


def test_max_repos_json_truncated_key_true_when_truncated(tmp_path):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")
    repo_c = init_repo_with_origin(tmp_path, "repo-c")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--repo",
            str(repo_c),
            "--report",
            "--count-only",
            "--json",
            "--max-repos",
            "2",
        ]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["truncated"] is True
    assert len(payload["rows"]) == 2


def test_max_repos_json_truncated_key_false_when_not_exceeded(tmp_path):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--report",
            "--count-only",
            "--json",
            "--max-repos",
            "5",
        ]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["truncated"] is False
    assert len(payload["rows"]) == 2


def test_max_repos_absent_is_unbounded(tmp_path):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")
    repo_c = init_repo_with_origin(tmp_path, "repo-c")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--repo",
            str(repo_c),
            "--report",
            "--count-only",
            "--json",
        ]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["truncated"] is False
    assert len(payload["rows"]) == 3


def test_max_repos_without_multi_repo_is_usage_error(tmp_path):
    result = run_cli(["--max-repos", "2"], cwd=tmp_path)
    assert result.returncode == 2, result.stderr
    assert "--max-repos requires --multi-repo" in result.stderr


# --------------------------------------------------------------------------
# 15b. Round-2 Major fix: `--max-repos` must reject 0 and negative values -
#     `targets[: args.max_repos]` with a negative N silently drops the LAST
#     entries (not the intended "cap at N") while still reporting
#     `truncated: true`, and 0 empties the target list, producing the
#     misleading "no repos discovered" usage error instead of a clear
#     complaint about the flag itself. Both must exit 2 with a message
#     naming the constraint, and neither may run any per-repo evaluation.
# --------------------------------------------------------------------------


def test_max_repos_zero_is_usage_error_and_runs_no_evaluation(tmp_path, monkeypatch):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")

    mod = _load_module_directly()
    evaluated = []
    monkeypatch.setattr(mod, "_fast_report_row", lambda repo: evaluated.append(repo) or (None, None))

    result = run_cli(
        ["--multi-repo", "--repo", str(repo_a), "--report", "--count-only", "--max-repos", "0"]
    )
    assert result.returncode == 2, result.stderr
    assert "--max-repos must be >= 1" in result.stderr
    assert evaluated == []


def test_max_repos_negative_is_usage_error_and_runs_no_evaluation(tmp_path, monkeypatch):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")

    mod = _load_module_directly()
    evaluated = []
    monkeypatch.setattr(mod, "_fast_report_row", lambda repo: evaluated.append(repo) or (None, None))

    result = run_cli(
        ["--multi-repo", "--repo", str(repo_a), "--report", "--count-only", "--max-repos", "-1"]
    )
    assert result.returncode == 2, result.stderr
    assert "--max-repos must be >= 1" in result.stderr
    assert evaluated == []


# --------------------------------------------------------------------------
# 15c. Round-2 Minor fix: truncation must be visible on human-readable
#     output too, not only `--report --json`'s `"truncated"` key - both the
#     `--report` table and the plain multi-repo sweep path print a NOTE
#     line naming the cap when truncation actually happened, and print
#     nothing when it did not.
# --------------------------------------------------------------------------


def test_max_repos_note_appears_on_truncated_human_report(tmp_path):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")
    repo_c = init_repo_with_origin(tmp_path, "repo-c")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--repo",
            str(repo_c),
            "--report",
            "--count-only",
            "--max-repos",
            "2",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "NOTE: repo discovery truncated to first 2 of 3 discovered repos" in result.stdout


def test_max_repos_note_absent_when_not_truncated(tmp_path):
    repo_a = init_repo_with_origin(tmp_path, "repo-a")
    repo_b = init_repo_with_origin(tmp_path, "repo-b")

    result = run_cli(
        [
            "--multi-repo",
            "--repo",
            str(repo_a),
            "--repo",
            str(repo_b),
            "--report",
            "--count-only",
            "--max-repos",
            "5",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "NOTE: repo discovery truncated" not in result.stdout
