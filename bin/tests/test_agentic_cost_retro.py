#!/usr/bin/env python3
"""
Smoke tests for `agentic-cost retro` subcommand.

Creates a temp git repo, seeds commits across 2 authors with mixed ticket
prefixes, then verifies aggregation, ticket-prefix scan, gh-absent fallback,
edge cases (empty range, date out of range, malformed date).

Run with: python3 -m pytest bin/tests/test_agentic_cost_retro.py
(collects the test_* functions; the legacy run_tests() block runs only via
python3 bin/tests/test_agentic_cost_retro.py)
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


def _one_commit_repo(tmpdir: str, subject: str, origin_main: bool = True) -> str:
    repo = os.path.join(tmpdir, "prrepo")
    os.makedirs(repo)
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "carol@example.com"], cwd=repo)
    _git(["config", "user.name", "carol"], cwd=repo)
    Path(repo, "f.txt").write_text("x\n")
    _git(["add", "f.txt"], cwd=repo)
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-05-01T10:00:00",
               GIT_COMMITTER_DATE="2026-05-01T10:00:00")
    subprocess.run(["git", "commit", "--message", subject], cwd=repo, env=env,
                   capture_output=True, check=True)
    if origin_main:
        _git(["update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo)
    return repo


def _retro_with_gh(repo: str, gh_available: bool, prs: list, as_json: bool = False,
                   gh_warn: str | None = None) -> str:
    orig_gh, orig_fetch = _mod._gh_available, _mod._fetch_gh_prs
    _mod._gh_available = lambda: gh_available
    _mod._fetch_gh_prs = lambda *a, **k: (prs, gh_warn)
    try:
        rc, out = _capture_retro(_make_args(**{"json": as_json}), repo)
    finally:
        _mod._gh_available, _mod._fetch_gh_prs = orig_gh, orig_fetch
    assert rc == 0
    return out


def _total_row(out: str) -> list[str]:
    (row,) = [line.split() for line in out.splitlines() if line.strip().startswith("TOTAL")]
    return row


def test_retro_gh_empty_with_git_pr_merge_prints_na():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "feat: add thing (#12)")
        out = _retro_with_gh(repo, True, [])
        assert _total_row(out) == ["TOTAL", "1", "n/a", "n/a", "n/a", "1"], out
        assert "(#N)" in out
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True))
        carol = data["authors"]["carol"]
        assert carol["prs"] is None and carol["merged"] is None, carol
        assert carol["avg_merge_time_days"] is None
        assert "(#N)" in data["prs_absent_reason"]


def test_retro_gh_empty_without_git_pr_merge_reports_zero():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "plain commit")
        out = _retro_with_gh(repo, True, [])
        assert _total_row(out) == ["TOTAL", "1", "0", "0", "n/a", "1"], out
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True))
        assert data["authors"]["carol"]["prs"] == 0
        assert data["prs_absent_reason"] is None


def test_retro_gh_unavailable_prints_na():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "plain commit")
        out = _retro_with_gh(repo, False, [])
        assert _total_row(out) == ["TOTAL", "1", "n/a", "n/a", "n/a", "1"], out
        data = json.loads(_retro_with_gh(repo, False, [], as_json=True))
        assert data["authors"]["carol"]["prs"] is None
        assert "gh not available" in data["prs_absent_reason"]


def test_retro_gh_ok_prints_pr_counts():
    pr = {"author": {"login": "carol"}, "createdAt": "2026-05-01T00:00:00Z",
          "mergedAt": "2026-05-03T00:00:00Z", "files": []}
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "feat: add thing (#12)")
        out = _retro_with_gh(repo, True, [pr])
        assert _total_row(out) == ["TOTAL", "1", "1", "1", "2.0", "d", "1"], out


def test_retro_gh_empty_with_dangling_origin_head_prints_na():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "feat: thing (#12)", origin_main=False)
        _git(["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master"], cwd=repo)
        out = _retro_with_gh(repo, True, [])
        assert _total_row(out) == ["TOTAL", "1", "n/a", "n/a", "n/a", "1"], out
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True))
        assert data["authors"]["carol"]["prs"] is None
        assert "no base branch resolved" in data["prs_absent_reason"]


def test_retro_gh_empty_with_git_log_failure_prints_na():
    # origin/main names a missing object: rev-parse --verify accepts it, so
    # the resolver returns it, but `git log origin/main` exits 128.
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "plain commit", origin_main=False)
        ref = Path(repo, ".git", "refs", "remotes", "origin", "main")
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("1" * 40 + "\n")
        out = _retro_with_gh(repo, True, [])
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True))
    assert _total_row(out) == ["TOTAL", "1", "n/a", "n/a", "n/a", "1"], out
    assert "git log on origin/main failed" in data["prs_absent_reason"]


def test_retro_base_branch_declaration_beats_origin_head():
    # origin/HEAD -> origin/main has no (#N) merge; the declared origin/release
    # does, so only a resolver honoring AGENTS.md reports PR data absent.
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "plain commit")
        _git(["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], cwd=repo)
        _git(["checkout", "-q", "-b", "release"], cwd=repo)
        Path(repo, "g.txt").write_text("y\n")
        _git(["add", "g.txt"], cwd=repo)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-05-02T10:00:00",
                   GIT_COMMITTER_DATE="2026-05-02T10:00:00")
        subprocess.run(["git", "commit", "--message", "feat: release thing (#7)"], cwd=repo,
                       env=env, capture_output=True, check=True)
        _git(["update-ref", "refs/remotes/origin/release", "HEAD"], cwd=repo)
        _git(["checkout", "-q", "main"], cwd=repo)
        Path(repo, "AGENTS.md").write_text("BASE_BRANCH: release\n")
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True))
    assert data["authors"]["carol"]["prs"] is None, data
    assert "on origin/release" in data["prs_absent_reason"]


def test_retro_gh_failure_prints_na():
    warn = "gh pr list failed; PR data omitted."
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _one_commit_repo(tmpdir, "plain commit")
        out = _retro_with_gh(repo, True, [], gh_warn=warn)
        assert _total_row(out) == ["TOTAL", "1", "n/a", "n/a", "n/a", "1"], out
        data = json.loads(_retro_with_gh(repo, True, [], as_json=True, gh_warn=warn))
        assert data["authors"]["carol"]["prs"] is None
        assert data["prs_absent_reason"] == warn


if __name__ == "__main__":
    run_tests()
