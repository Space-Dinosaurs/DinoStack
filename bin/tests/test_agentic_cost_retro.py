#!/usr/bin/env python3
"""
Smoke tests for `agentic-cost retro` subcommand.

Creates a temp git repo, seeds commits across 2 authors with mixed ticket
prefixes, then verifies aggregation, ticket-prefix scan, gh-absent fallback,
edge cases (empty range, date out of range, malformed date).

Run with: python3 bin/tests/test_agentic_cost_retro.py
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-cost as a module (no .py extension)
# ---------------------------------------------------------------------------
_COST_PATH = Path(__file__).parent.parent / "agentic-cost"
loader = importlib.machinery.SourceFileLoader("agentic_cost", str(_COST_PATH))
spec = importlib.util.spec_from_loader("agentic_cost", loader)
if spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-cost from {_COST_PATH}")
_mod = importlib.util.module_from_spec(spec)
loader.exec_module(_mod)


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _make_repo_with_commits(tmpdir: str) -> str:
    """Init a git repo and seed 5 commits across 2 authors. Returns repo path."""
    repo = os.path.join(tmpdir, "testrepo")
    os.makedirs(repo)
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "alice"], cwd=repo)

    commits = [
        ("alice", "alice@example.com", "DINO-1: add dinosaur feature"),
        ("alice", "alice@example.com", "DINO-2: fix claw rendering"),
        ("alice", "alice@example.com", "FOO-99: refactor wing span calc"),
        ("bob", "bob@example.com", "DINO-3: update habitat data"),
        ("bob", "bob@example.com", "no prefix commit message"),
    ]

    for i, (name, email, msg) in enumerate(commits):
        fname = os.path.join(repo, f"file{i}.txt")
        Path(fname).write_text(f"content {i}\n")
        _git(["config", "user.name", name], cwd=repo)
        _git(["config", "user.email", email], cwd=repo)
        _git(["add", f"file{i}.txt"], cwd=repo)
        _git(["commit", "--message", msg, "--date", "2026-05-01T10:00:00"], cwd=repo)

    return repo


def _capture_retro(args_ns: types.SimpleNamespace, cwd: str) -> tuple[int, str]:
    """Run cmd_retro with given args, capturing stdout. Returns (rc, output)."""
    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured
    try:
        os.chdir(cwd)
        rc = _mod.cmd_retro(args_ns)
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
    return rc, captured.getvalue()


def _make_args(**kwargs) -> types.SimpleNamespace:
    defaults = {
        "since": "2026-04-01",
        "until": "2026-06-01",
        "author": None,
        "json": False,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def _no_gh_env(repo: str) -> dict:
    """Build an env dict with PATH containing only git (no gh)."""
    # Create a temp dir with only a git symlink
    fake_bin = os.path.join(repo, ".fake_bin")
    os.makedirs(fake_bin, exist_ok=True)
    git_path = subprocess.run(
        ["which", "git"], capture_output=True, text=True
    ).stdout.strip()
    fake_git = os.path.join(fake_bin, "git")
    if not os.path.exists(fake_git):
        os.symlink(git_path, fake_git)
    env = os.environ.copy()
    env["PATH"] = fake_bin
    return env


def run_tests():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _make_repo_with_commits(tmpdir)

        # ------------------------------------------------------------------
        # Test 1: basic aggregation - per-author counts correct
        # ------------------------------------------------------------------
        rc, out = _capture_retro(_make_args(), repo)
        assert rc == 0, f"Test 1: expected rc=0, got {rc}"
        # Both authors should appear
        assert "alice" in out, f"Test 1: 'alice' not in output:\n{out}"
        assert "bob" in out, f"Test 1: 'bob' not in output:\n{out}"
        print("Test 1 (basic aggregation): PASS")

        # ------------------------------------------------------------------
        # Test 2: ticket-prefix scan picks up DINO and FOO
        # ------------------------------------------------------------------
        assert "DINO" in out, f"Test 2: 'DINO' not in output:\n{out}"
        assert "FOO" in out, f"Test 2: 'FOO' not in output:\n{out}"
        print("Test 2 (ticket prefix scan): PASS")

        # ------------------------------------------------------------------
        # Test 3: no-prefix commits counted
        # ------------------------------------------------------------------
        assert "no prefix" in out, f"Test 3: '(no prefix)' line missing:\n{out}"
        print("Test 3 (no-prefix commits): PASS")

        # ------------------------------------------------------------------
        # Test 4: WARNING block prominent in output
        # ------------------------------------------------------------------
        assert "WARNING" in out, f"Test 4: WARNING not in output:\n{out}"
        assert "NOT Stage 1 telemetry" in out, (
            f"Test 4: 'NOT Stage 1 telemetry' not in output:\n{out}"
        )
        print("Test 4 (WARNING prominent): PASS")

        # ------------------------------------------------------------------
        # Test 5: gh unavailable - git-only mode, no crash
        # (simulate by patching _gh_available to return False)
        # ------------------------------------------------------------------
        orig_gh = _mod._gh_available
        _mod._gh_available = lambda: False
        try:
            rc5, out5 = _capture_retro(_make_args(), repo)
        finally:
            _mod._gh_available = orig_gh
        assert rc5 == 0, f"Test 5: expected rc=0 when gh absent, got {rc5}"
        assert "PR data omitted" in out5, (
            f"Test 5: expected 'PR data omitted' warning:\n{out5}"
        )
        print("Test 5 (gh unavailable, no crash): PASS")

        # ------------------------------------------------------------------
        # Test 6: --author filter - only alice
        # ------------------------------------------------------------------
        rc6, out6 = _capture_retro(_make_args(author="alice"), repo)
        assert rc6 == 0, f"Test 6: expected rc=0, got {rc6}"
        assert "alice" in out6, f"Test 6: 'alice' not in filtered output"
        # bob should not appear in TOTAL as a named row (only TOTAL row)
        lines_with_bob = [
            l for l in out6.splitlines()
            if "bob" in l.lower() and "TOTAL" not in l
        ]
        assert not lines_with_bob, (
            f"Test 6: bob appears in author-filtered output: {lines_with_bob}"
        )
        print("Test 6 (--author filter): PASS")

        # ------------------------------------------------------------------
        # Test 7: --json mode produces valid JSON
        # ------------------------------------------------------------------
        rc7, out7 = _capture_retro(_make_args(**{"json": True}), repo)
        assert rc7 == 0, f"Test 7: expected rc=0 in JSON mode, got {rc7}"
        try:
            data7 = json.loads(out7)
        except json.JSONDecodeError as exc:
            assert False, f"Test 7: JSON output is invalid: {exc}\n{out7}"
        assert "authors" in data7, f"Test 7: 'authors' key missing from JSON"
        assert "warning" in data7, f"Test 7: 'warning' key missing from JSON"
        print("Test 7 (--json mode valid JSON): PASS")

        # ------------------------------------------------------------------
        # Test 8: edge case - date out of range -> "No activity in range."
        # ------------------------------------------------------------------
        rc8, out8 = _capture_retro(_make_args(since="2020-01-01", until="2020-01-31"), repo)
        assert rc8 == 0, f"Test 8: expected rc=0, got {rc8}"
        assert "No activity in range." in out8, (
            f"Test 8: expected 'No activity in range.' in output:\n{out8}"
        )
        print("Test 8 (date out of range): PASS")

        # ------------------------------------------------------------------
        # Test 9: edge case - empty repo (no commits in range different sense)
        # Already covered by Test 8. Additional: test with fresh empty repo.
        # ------------------------------------------------------------------
        empty_repo = os.path.join(tmpdir, "emptyrepo")
        os.makedirs(empty_repo)
        _git(["init", "-b", "main"], cwd=empty_repo)
        _git(["config", "user.email", "x@x.com"], cwd=empty_repo)
        _git(["config", "user.name", "x"], cwd=empty_repo)
        rc9, out9 = _capture_retro(_make_args(), empty_repo)
        assert rc9 == 0, f"Test 9: expected rc=0 for empty repo, got {rc9}"
        assert "No activity in range." in out9, (
            f"Test 9: expected 'No activity in range.' for empty repo:\n{out9}"
        )
        print("Test 9 (empty repo): PASS")

        # ------------------------------------------------------------------
        # Test 10: malformed date -> exit 1
        # ------------------------------------------------------------------
        bad_args = _make_args(since="not-a-date")
        old_cwd = os.getcwd()
        old_stderr = sys.stderr
        err_cap = StringIO()
        sys.stderr = err_cap
        try:
            os.chdir(repo)
            rc10 = _mod.cmd_retro(bad_args)
        finally:
            os.chdir(old_cwd)
            sys.stderr = old_stderr
        assert rc10 == 1, f"Test 10: expected rc=1 for malformed date, got {rc10}"
        assert "invalid --since date" in err_cap.getvalue(), (
            f"Test 10: expected error message in stderr:\n{err_cap.getvalue()}"
        )
        print("Test 10 (malformed date -> exit 1): PASS")

        # ------------------------------------------------------------------
        # Test 11: empty-range warning - table mode includes WARNING header
        # (regression: early-return used to skip the WARNING header)
        # ------------------------------------------------------------------
        rc11, out11 = _capture_retro(
            _make_args(since="2020-01-01", until="2020-01-31"), repo
        )
        assert rc11 == 0, f"Test 11: expected rc=0, got {rc11}"
        assert "WARNING" in out11, (
            f"Test 11: WARNING header missing in empty-range table output:\n{out11}"
        )
        assert "No activity in range." in out11, (
            f"Test 11: 'No activity in range.' missing in empty-range output:\n{out11}"
        )
        print("Test 11 (empty-range table has WARNING header): PASS")

        # ------------------------------------------------------------------
        # Test 12: empty-range JSON mode includes metadata keys
        # (regression: early-return used to bypass JSON branch entirely)
        # ------------------------------------------------------------------
        rc12, out12 = _capture_retro(
            _make_args(since="2020-01-01", until="2020-01-31", **{"json": True}), repo
        )
        assert rc12 == 0, f"Test 12: expected rc=0, got {rc12}"
        try:
            data12 = json.loads(out12)
        except json.JSONDecodeError as exc:
            assert False, f"Test 12: JSON output invalid: {exc}\n{out12}"
        for key in ("warning", "repo", "since", "until", "authors"):
            assert key in data12, (
                f"Test 12: '{key}' missing from empty-range JSON output:\n{out12}"
            )
        assert data12["authors"] == {}, (
            f"Test 12: 'authors' should be empty dict, got: {data12['authors']}"
        )
        assert data12["since"] == "2020-01-01", (
            f"Test 12: 'since' incorrect in JSON: {data12.get('since')}"
        )
        assert data12["until"] == "2020-01-31", (
            f"Test 12: 'until' incorrect in JSON: {data12.get('until')}"
        )
        print("Test 12 (empty-range JSON has metadata keys): PASS")

        # ------------------------------------------------------------------
        # Test 13: _fetch_gh_prs passes --author flag when author_filter set
        # (regression: gh --limit 500 could silently truncate busy repos)
        # ------------------------------------------------------------------
        captured_cmds: list[list[str]] = []
        orig_run = _mod._run

        def _mock_run(cmd: list[str], **kwargs):
            captured_cmds.append(cmd)
            # Simulate gh returning empty list (no real gh needed in CI)
            return "[]", "", 0

        _mod._run = _mock_run
        orig_gh = _mod._gh_available
        _mod._gh_available = lambda: True
        try:
            rc13, _ = _capture_retro(_make_args(author="alice"), repo)
        finally:
            _mod._run = orig_run
            _mod._gh_available = orig_gh

        assert rc13 == 0, f"Test 13: expected rc=0, got {rc13}"
        gh_calls = [c for c in captured_cmds if c and c[0] == "gh"]
        assert gh_calls, "Test 13: no gh calls captured"
        gh_cmd = gh_calls[0]
        assert "--author" in gh_cmd, (
            f"Test 13: --author flag not passed to gh pr list:\n{gh_cmd}"
        )
        author_idx = gh_cmd.index("--author")
        assert gh_cmd[author_idx + 1] == "alice", (
            f"Test 13: --author value wrong, got: {gh_cmd[author_idx + 1]}"
        )
        print("Test 13 (gh --author flag passed when author_filter set): PASS")

        print("\nAll retro tests passed.")


if __name__ == "__main__":
    run_tests()
