#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-reap-all, the cross-repo sweep wrapper
         around bin/ds-cleanup-worktrees. Covers discovery (explicit --repo,
         root-directory scan, config-file fallback, dedup by canonical
         path), pass-through flag forwarding, per-repo error isolation,
         and summary-line composition - never a real reap: every scenario
         that exercises the underlying-tool call substitutes a fake stub
         via the `DS_REAP_ALL_UNDERLYING_TOOL` test-only env-var hook (see
         `_resolve_cleanup_worktrees`'s docstring in ds-reap-all itself), so
         no real `git worktree remove` ever runs from this file.

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-reap-all (module under test, invoked both as a
               subprocess CLI and, for discovery-only unit tests, imported
               directly via SourceFileLoader - mirrors the pattern
               bin/tests/test_reap_worktrees.py's `_load_module_directly`
               already established). Real `git` CLI (subprocess, `git
               init` only - to build minimal repos for the discovery
               scenarios). A fake stub `ds-cleanup-worktrees` executable
               written per-test into tmp_path, never the real binary.

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`).

Failure modes: each scenario builds its own isolated tmp_path repo/root
               tree; no real DinoStack checkout, worktree, or branch state
               is ever touched by this file. No real `~/.agentic/
               reap-all.json` is ever read - the config-fallback scenario
               monkeypatches `_CONFIG_PATH` on the directly-imported module
               rather than touching the real home-dir file.

Performance: each scenario performs a handful of `git init` calls plus at
             most a few `ds-reap-all` subprocess invocations against a
             fake stub tool. Sub-second per test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ds-reap-all"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _load_module_directly():
    """Imports bin/ds-reap-all as a Python module (not a subprocess) for
    discovery-only unit tests that need to monkeypatch internals (notably
    `_CONFIG_PATH`, to avoid ever touching the real
    `~/.agentic/reap-all.json`). Mirrors
    bin/tests/test_reap_worktrees.py's `_load_module_directly`."""
    import importlib.machinery as _ilm
    import importlib.util as _ilu

    loader = _ilm.SourceFileLoader("ds_reap_all_direct", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_reap_all_direct", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def init_bare_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)


FAKE_TOOL_SOURCE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    # Fake ds-cleanup-worktrees stub for bin/tests/test_ds_reap_all.py. Never
    # touches real git worktree state. Behavior is driven entirely by env
    # vars so each test can configure it independently:
    #   FAKE_REAP_LOG        - path to append one line per invocation's argv
    #   FAKE_REAP_FAIL_REPOS - comma-separated repo basenames to fail (exit 1)
    #   FAKE_REAP_SLEEP_REPOS - comma-separated repo basenames to sleep-then-succeed
    #   FAKE_REAP_SLEEP_SECONDS - how long to sleep for a matched repo
    import os
    import sys
    import time

    argv = sys.argv[1:]
    log_path = os.environ.get("FAKE_REAP_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(" ".join(argv) + "\\n")

    repo = None
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    basename = os.path.basename(repo) if repo else ""

    fail_repos = set(filter(None, os.environ.get("FAKE_REAP_FAIL_REPOS", "").split(",")))
    sleep_repos = set(filter(None, os.environ.get("FAKE_REAP_SLEEP_REPOS", "").split(",")))

    if basename in sleep_repos:
        time.sleep(float(os.environ.get("FAKE_REAP_SLEEP_SECONDS", "1")))

    mode = "dry-run" if "--dry-run" in argv else "live"
    print(f"ds-cleanup-worktrees: base=main mode={mode} entries=1 removed=0")

    if basename in fail_repos:
        print("ds-cleanup-worktrees: simulated failure", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
    """
)


def write_fake_tool(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-ds-cleanup-worktrees.py"
    fake.write_text(FAKE_TOOL_SOURCE)
    fake.chmod(0o755)
    return fake


def run_reap_all(
    args,
    *,
    cwd: Path = None,
    fake_tool: Path = None,
    extra_env: dict = None,
):
    cmd = [sys.executable, str(SCRIPT), *args]
    env = dict(os.environ)
    if fake_tool is not None:
        # fake_tool is chmod'd executable with its own #!/usr/bin/env
        # python3 shebang - pass its path directly, no shell splitting
        # needed (ds-reap-all invokes it as a single argv[0]).
        env["DS_REAP_ALL_UNDERLYING_TOOL"] = str(fake_tool)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None, env=env)


# --------------------------------------------------------------------------
# 1. Discovery: explicit --repo
# --------------------------------------------------------------------------


def test_explicit_repo_list_used_directly(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    init_bare_git_repo(repo_a)
    init_bare_git_repo(repo_b)

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(repo=[str(repo_a), str(repo_b)], roots=[], depth=1)
    targets, skipped_not_git, root_errors = mod.discover_repos(args)

    assert not root_errors
    assert skipped_not_git == 0
    resolved = {t.canonical for t in targets}
    assert resolved == {repo_a.resolve(), repo_b.resolve()}
    assert all(t.source == "explicit" for t in targets)
    assert all(t.discovery_error is None for t in targets)


def test_explicit_repo_not_a_git_repo_reports_error():
    mod = _load_module_directly()
    import argparse
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        non_git = Path(tmp) / "not-a-repo"
        non_git.mkdir()
        args = argparse.Namespace(repo=[str(non_git)], roots=[], depth=1)
        targets, _skipped, _errors = mod.discover_repos(args)

    assert len(targets) == 1
    assert targets[0].discovery_error is not None
    assert "not a git repository" in targets[0].discovery_error


# --------------------------------------------------------------------------
# 2. Discovery: root scan (depth default 1, skips non-git dirs)
# --------------------------------------------------------------------------


def test_root_scan_finds_git_children_and_skips_non_git(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    git_child = root / "project-one"
    non_git_child = root / "just-a-folder"
    init_bare_git_repo(git_child)
    non_git_child.mkdir()

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(repo=[], roots=[str(root)], depth=1)
    targets, skipped_not_git, root_errors = mod.discover_repos(args)

    assert not root_errors
    resolved = {t.canonical for t in targets}
    assert resolved == {git_child.resolve()}
    assert skipped_not_git == 1


def test_root_scan_depth_default_is_one_does_not_descend(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    nested_parent = root / "container"
    nested_parent.mkdir()
    nested_repo = nested_parent / "deep-project"
    init_bare_git_repo(nested_repo)

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(repo=[], roots=[str(root)], depth=1)
    targets, _skipped, _errors = mod.discover_repos(args)

    assert targets == []


def test_root_scan_depth_two_descends_one_level_further(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    nested_parent = root / "container"
    nested_parent.mkdir()
    nested_repo = nested_parent / "deep-project"
    init_bare_git_repo(nested_repo)

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(repo=[], roots=[str(root)], depth=2)
    targets, _skipped, _errors = mod.discover_repos(args)

    resolved = {t.canonical for t in targets}
    assert resolved == {nested_repo.resolve()}


# --------------------------------------------------------------------------
# 3. Discovery: config-file fallback (only when no args)
# --------------------------------------------------------------------------


def test_config_fallback_used_only_when_no_args(tmp_path, monkeypatch):
    repo_a = tmp_path / "config-repo"
    init_bare_git_repo(repo_a)

    config_path = tmp_path / "reap-all.json"
    config_path.write_text(json.dumps({"repos": [str(repo_a)]}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

    import argparse

    # No --repo, no roots -> config is consulted.
    args = argparse.Namespace(repo=[], roots=[], depth=1)
    targets, _skipped, _errors = mod.discover_repos(args)
    resolved = {t.canonical for t in targets}
    assert resolved == {repo_a.resolve()}

    # An explicit --repo present -> config must NOT be consulted, even
    # though it names a real, different repo.
    other_repo = tmp_path / "explicit-only"
    init_bare_git_repo(other_repo)
    args_explicit = argparse.Namespace(repo=[str(other_repo)], roots=[], depth=1)
    targets2, _skipped2, _errors2 = mod.discover_repos(args_explicit)
    resolved2 = {t.canonical for t in targets2}
    assert resolved2 == {other_repo.resolve()}


def test_empty_discovery_exits_2_with_usage(tmp_path, monkeypatch):
    fake_home_config = tmp_path / "nonexistent-reap-all.json"
    result = run_reap_all([], extra_env={"HOME": str(tmp_path)})
    # No --repo, no roots, and (very likely) no real ~/.agentic/reap-all.json
    # under the test HOME override - the tool must refuse cleanly.
    assert not fake_home_config.exists()
    assert result.returncode == 2
    assert "no repos discovered" in result.stderr.lower() or "usage" in result.stderr.lower()


# --------------------------------------------------------------------------
# 4. Dedupe by canonical path
# --------------------------------------------------------------------------


def test_dedupe_explicit_repo_and_root_scan_same_repo_runs_once(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    repo = root / "shared-project"
    init_bare_git_repo(repo)

    mod = _load_module_directly()
    import argparse

    args = argparse.Namespace(repo=[str(repo)], roots=[str(root)], depth=1)
    targets, _skipped, _errors = mod.discover_repos(args)
    deduped = mod.dedupe(targets)

    matching = [t for t in deduped if t.canonical == repo.resolve()]
    assert len(matching) == 1


# --------------------------------------------------------------------------
# 5. Pass-through: forwarded flags reach the underlying tool invocation
# --------------------------------------------------------------------------


def test_forwarded_flags_appear_in_subprocess_invocation(tmp_path):
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)
    fake_tool = write_fake_tool(tmp_path)
    log_path = tmp_path / "invocations.log"

    result = run_reap_all(
        [
            "--repo",
            str(repo),
            "--dry-run",
            "--no-gh",
            "--min-age-hours",
            "3",
            "--strict-ignored",
            "--base",
            "origin/main",
        ],
        fake_tool=fake_tool,
        extra_env={"FAKE_REAP_LOG": str(log_path)},
    )

    assert result.returncode == 0, result.stderr
    logged = log_path.read_text()
    assert "--dry-run" in logged
    assert "--no-gh" in logged
    assert "--min-age-hours 3" in logged
    assert "--strict-ignored" in logged
    assert "--base origin/main" in logged
    # A flag that was never passed must never be forwarded either.
    assert "--archive-unproven" not in logged
    assert "--count-only" not in logged


# --------------------------------------------------------------------------
# 6. Error isolation: one repo failing does not stop later repos
# --------------------------------------------------------------------------


def test_one_repo_failure_does_not_stop_the_sweep(tmp_path):
    repo_good_a = tmp_path / "good-a"
    repo_bad = tmp_path / "bad-repo"
    repo_good_b = tmp_path / "good-b"
    for r in (repo_good_a, repo_bad, repo_good_b):
        init_bare_git_repo(r)

    fake_tool = write_fake_tool(tmp_path)
    log_path = tmp_path / "invocations.log"

    result = run_reap_all(
        ["--repo", str(repo_good_a), "--repo", str(repo_bad), "--repo", str(repo_good_b), "--dry-run"],
        fake_tool=fake_tool,
        extra_env={"FAKE_REAP_LOG": str(log_path), "FAKE_REAP_FAIL_REPOS": "bad-repo"},
    )

    logged = log_path.read_text()
    # All three were invoked - the failure did not short-circuit later repos.
    assert logged.count(str(repo_good_a)) + logged.count("good-a") >= 1
    assert "bad-repo" in logged
    assert "good-b" in logged
    assert result.returncode == 1
    assert "errored=1" in result.stdout


def test_summary_counts_correct_with_mixed_outcomes(tmp_path):
    repo_good = tmp_path / "good-repo"
    repo_bad = tmp_path / "bad-repo"
    init_bare_git_repo(repo_good)
    init_bare_git_repo(repo_bad)

    fake_tool = write_fake_tool(tmp_path)
    result = run_reap_all(
        ["--repo", str(repo_good), "--repo", str(repo_bad), "--dry-run"],
        fake_tool=fake_tool,
        extra_env={"FAKE_REAP_FAIL_REPOS": "bad-repo"},
    )

    assert "repos=2" in result.stdout
    assert "swept=2" in result.stdout
    assert "errored=1" in result.stdout
    assert result.returncode == 1


# --------------------------------------------------------------------------
# 7. Summary composition: mode/flag axis anchored, never a bare substring
# --------------------------------------------------------------------------


def test_dry_run_flag_shown_in_forwarded_flags_field_on_summary_line(tmp_path):
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)
    fake_tool = write_fake_tool(tmp_path)

    dry_result = run_reap_all(["--repo", str(repo), "--dry-run"], fake_tool=fake_tool)
    live_result = run_reap_all(["--repo", str(repo)], fake_tool=fake_tool)

    # Anchor on the composed field PLUS an adjacent field on the same
    # summary line, never a bare substring - a bare "flags=--dry-run"
    # match could otherwise be satisfied by unrelated log noise. Would
    # this assertion survive deleting the print() entirely? No: with the
    # print gone, `errored=0 root-errors=0 skipped-not-git=0 flags=--dry-run`
    # cannot appear in stdout at all, so the assertion correctly fails -
    # the anchor is meaningful.
    dry_line = [ln for ln in dry_result.stdout.splitlines() if ln.startswith("ds-reap-all:")][-1]
    live_line = [ln for ln in live_result.stdout.splitlines() if ln.startswith("ds-reap-all:")][-1]

    assert "errored=0 root-errors=0 skipped-not-git=0 flags=--dry-run" in dry_line
    assert "errored=0 root-errors=0 skipped-not-git=0 flags=(none)" in live_line
    assert dry_line != live_line


# --------------------------------------------------------------------------
# 8. Timeout: a per-repo timeout is reported as that repo's error, sweep continues
# --------------------------------------------------------------------------


def test_timeout_reported_as_repo_error_and_sweep_continues(tmp_path):
    repo_slow = tmp_path / "slow-repo"
    repo_fast = tmp_path / "fast-repo"
    init_bare_git_repo(repo_slow)
    init_bare_git_repo(repo_fast)

    fake_tool = write_fake_tool(tmp_path)
    log_path = tmp_path / "invocations.log"

    result = run_reap_all(
        ["--repo", str(repo_slow), "--repo", str(repo_fast), "--dry-run", "--timeout", "1"],
        fake_tool=fake_tool,
        extra_env={
            "FAKE_REAP_LOG": str(log_path),
            "FAKE_REAP_SLEEP_REPOS": "slow-repo",
            "FAKE_REAP_SLEEP_SECONDS": "5",
        },
    )

    assert result.returncode == 1
    assert "errored=1" in result.stdout
    # The fast repo still ran despite the slow one timing out.
    assert "fast-repo" in log_path.read_text()


# --------------------------------------------------------------------------
# 9. Symlink invocation: through a real os.symlink, resolving the real
#    sibling ds-cleanup-worktrees (DS-66 class regression guard).
# --------------------------------------------------------------------------


def test_cli_runs_through_path_symlink_and_finds_sibling_tool(tmp_path):
    real_bin_path = SCRIPT
    assert real_bin_path.is_file()

    fake_local_bin = tmp_path / "local-bin"
    fake_local_bin.mkdir()
    symlink_path = fake_local_bin / "ds-reap-all"
    os.symlink(real_bin_path.resolve(), symlink_path)

    repo = tmp_path / "symlink-target-repo"
    init_bare_git_repo(repo)
    # Round-4 rework: ds-cleanup-worktrees now resolves its own --base when
    # omitted (this test's PATH-symlink invocation passes none), so the
    # fixture repo needs a real commit and a real `origin` remote with a
    # `main` branch for the main-fallback resolution tier to succeed -
    # `init_bare_git_repo` alone (no commits, no remote) leaves every
    # resolution candidate unresolvable and the run correctly (fail-safe)
    # skips with no per-entry summary at all, which is what this test was
    # observed to hit before this fixture addition.
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "spec@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "spec"], check=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    origin = tmp_path / "symlink-target-repo-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(origin)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "-u", "origin", "main"], check=True)

    result = subprocess.run(
        [
            sys.executable,
            str(symlink_path),
            "--repo",
            str(repo),
            "--dry-run",
            "--no-gh",
            "--min-age-hours",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    # A genuine end-to-end run: through the symlink, ds-reap-all resolves
    # the REAL sibling ds-cleanup-worktrees (no fake-tool override here) and
    # invokes it successfully against a real (trivial) git repo.
    assert result.returncode == 0, result.stderr
    assert "== " in result.stdout
    assert "ds-cleanup-worktrees:" in result.stdout


# --------------------------------------------------------------------------
# 10. (Skeptic round-1 Major 1) A nonexistent root is a reported error, not
#     a silent no-op - exit 1, never exit 0.
# --------------------------------------------------------------------------


def test_nonexistent_root_is_reported_error_exit_1(tmp_path):
    bad_root = tmp_path / "definitely-not-here-12345"
    assert not bad_root.exists()

    result = run_reap_all([str(bad_root)])

    # Anchored on the composed field plus an adjacent field on the same
    # summary line, never a bare substring - would this survive deleting
    # the print()? No: with the print gone, "root-errors=1 skipped-not-git=0"
    # cannot appear in stdout at all, so the assertion correctly fails.
    summary_line = [ln for ln in result.stdout.splitlines() if ln.startswith("ds-reap-all:")][-1]
    assert "repos=0 swept=0 errored=0 root-errors=1 skipped-not-git=0" in summary_line
    assert result.returncode == 1
    assert "root not a directory" in result.stderr


def test_one_bad_root_among_good_ones_still_sweeps_the_rest(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    good_repo = root / "good-project"
    init_bare_git_repo(good_repo)
    bad_root = tmp_path / "does-not-exist-at-all"

    fake_tool = write_fake_tool(tmp_path)
    result = run_reap_all([str(root), str(bad_root), "--dry-run"], fake_tool=fake_tool)

    assert result.returncode == 1
    summary_line = [ln for ln in result.stdout.splitlines() if ln.startswith("ds-reap-all:")][-1]
    assert "repos=1 swept=1 errored=0 root-errors=1" in summary_line


# --------------------------------------------------------------------------
# 11. (Skeptic round-1 Minor a) Malformed config values never crash -
#     {"repos": null} and {"repos": "/tmp"} are both reported and ignored,
#     never an uncaught traceback or silent per-character expansion.
# --------------------------------------------------------------------------


def test_config_repos_null_does_not_crash(tmp_path, monkeypatch):
    config_path = tmp_path / "reap-all.json"
    config_path.write_text(json.dumps({"repos": None}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

    import argparse

    args = argparse.Namespace(repo=[], roots=[], depth=1)
    # Must not raise - a bare `list(None)` would.
    targets, _skipped, root_errors = mod.discover_repos(args)
    assert targets == []
    assert root_errors == []


def test_config_repos_bare_string_is_not_exploded_per_character(tmp_path, monkeypatch):
    config_path = tmp_path / "reap-all.json"
    config_path.write_text(json.dumps({"repos": "/tmp"}))

    mod = _load_module_directly()
    monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

    import argparse

    args = argparse.Namespace(repo=[], roots=[], depth=1)
    targets, _skipped, _root_errors = mod.discover_repos(args)
    # A bare string must never be treated as an iterable of characters
    # (list("/tmp") -> ["/", "t", "m", "p"], each a bogus one-char "repo").
    assert targets == []


# --------------------------------------------------------------------------
# 12. (Skeptic round-1 Minor c) The DS_REAP_ALL_UNDERLYING_TOOL test-only
#     override is never silently active - a loud NOTE is printed whenever
#     it is set.
# --------------------------------------------------------------------------


def test_malformed_config_json_reports_parse_failure_and_exits_2(tmp_path):
    fake_home = tmp_path / "home"
    agentic_dir = fake_home / ".agentic"
    agentic_dir.mkdir(parents=True)
    config_path = agentic_dir / "reap-all.json"
    # Trailing comma - invalid JSON. Previously silently swallowed to {}
    # with no hint, leaving the operator staring at a bare "no repos
    # discovered" usage message and no clue why.
    config_path.write_text('{"repos": ["/tmp/a",],}')

    result = run_reap_all([], extra_env={"HOME": str(fake_home)})

    assert result.returncode == 2
    assert str(config_path) in result.stderr
    assert "could not read config" in result.stderr
    assert "no repos discovered" in result.stderr.lower()


def test_underlying_tool_override_is_visibly_announced(tmp_path):
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)
    fake_tool = write_fake_tool(tmp_path)

    result = run_reap_all(["--repo", str(repo), "--dry-run"], fake_tool=fake_tool)

    assert f"underlying-tool override active: {fake_tool}" in result.stderr


def test_no_override_note_when_env_var_unset(tmp_path):
    repo = tmp_path / "repo"
    init_bare_git_repo(repo)

    # No fake_tool passed -> DS_REAP_ALL_UNDERLYING_TOOL is not set; this
    # genuinely invokes the real sibling ds-cleanup-worktrees.
    result = run_reap_all(["--repo", str(repo), "--dry-run", "--no-gh", "--min-age-hours", "0"])

    assert "underlying-tool override active" not in result.stderr


# --------------------------------------------------------------------------
# 13. (Skeptic round-1 Major 4) content/ wiring: ds-reap-all must be
#     mentioned in content/commands/ds-cleanup-worktrees.md, the prose home
#     of ds-cleanup-worktrees - "a new module is not done until something in
#     content/ invokes it" (repo AGENTS.md rule; precedent:
#     check_prose_wiring() in bin/tests/test_worktree_lifecycle_spec.sh).
# --------------------------------------------------------------------------


def test_ds_reap_all_is_wired_into_cleanup_worktrees_command_doc():
    doc_path = Path(__file__).resolve().parent.parent.parent / "content" / "commands" / "ds-cleanup-worktrees.md"
    assert doc_path.is_file(), f"expected {doc_path} to exist"
    text = doc_path.read_text(encoding="utf-8")
    assert "ds-reap-all" in text
