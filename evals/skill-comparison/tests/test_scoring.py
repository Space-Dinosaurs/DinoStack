"""
Tests for evals/skill-comparison/scoring.py.

Coverage:
- extract_diff_from_transcript: fenced block, raw diff, empty transcript.
- compute_diff_hygiene: lines_touched, files_touched, scope_creep_flag across
  fixture diffs including edge cases (empty diff, diff within known files,
  diff outside known files, mixed).
- compute_engineer_diff_from_workdir: absent dir, real git repo diff.
- _parse_pytest_failures: summary section extraction, fallback scanning.
- score_cell: pass (returncode=0), fail (returncode=1), empty transcript,
  workdir diff path (seed_commit provided).
  Uses a mock subprocess so no real pytest is invoked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# conftest.py inserts skill-comparison/ into sys.path.
from scoring import (
    ScoringResult,
    _parse_pytest_failures,
    _run_pytest_local,
    _run_pytest_tier3,
    compute_diff_hygiene,
    compute_engineer_diff_from_workdir,
    extract_diff_from_transcript,
    score_cell,
)


# ---------------------------------------------------------------------------
# extract_diff_from_transcript
# ---------------------------------------------------------------------------


class TestExtractDiffFromTranscript:
    def test_fenced_block(self):
        transcript = (
            "I found the bug and here is the fix:\n\n"
            "```diff\n"
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "```\n"
            "That should fix it."
        )
        result = extract_diff_from_transcript(transcript)
        assert "diff --git" in result
        assert "+new" in result
        assert "-old" in result

    def test_raw_git_diff(self):
        transcript = (
            "Analysis complete.\n"
            "diff --git a/bar.py b/bar.py\n"
            "--- a/bar.py\n"
            "+++ b/bar.py\n"
            "@@ -5 +5 @@\n"
            "-bad\n"
            "+good\n"
        )
        result = extract_diff_from_transcript(transcript)
        assert "diff --git" in result
        assert "+good" in result

    def test_empty_transcript_returns_empty(self):
        assert extract_diff_from_transcript("") == ""

    def test_no_diff_returns_empty(self):
        assert extract_diff_from_transcript("No patch here.") == ""

    def test_fenced_takes_precedence_over_raw(self):
        """If both a fenced block and raw diff exist, fenced wins."""
        transcript = (
            "diff --git a/outer.py b/outer.py\n"
            "--- a/outer.py\n"
            "+++ b/outer.py\n"
            "@@ -1 +1 @@\n"
            "-outer_old\n"
            "+outer_new\n"
            "\n"
            "```diff\n"
            "diff --git a/inner.py b/inner.py\n"
            "--- a/inner.py\n"
            "+++ b/inner.py\n"
            "@@ -1 +1 @@\n"
            "-inner_old\n"
            "+inner_new\n"
            "```"
        )
        result = extract_diff_from_transcript(transcript)
        # Fenced block contains inner.py
        assert "inner.py" in result


# ---------------------------------------------------------------------------
# compute_diff_hygiene
# ---------------------------------------------------------------------------

_DJANGO_KNOWN = ["django/core/management/commands/sqlmigrate.py"]

_DIFF_IN_SCOPE = (
    "diff --git a/django/core/management/commands/sqlmigrate.py "
    "b/django/core/management/commands/sqlmigrate.py\n"
    "--- a/django/core/management/commands/sqlmigrate.py\n"
    "+++ b/django/core/management/commands/sqlmigrate.py\n"
    "@@ -10,6 +10,7 @@\n"
    " unchanged\n"
    "-removed line\n"
    "+added line\n"
    "+another added\n"
)

_DIFF_OUT_OF_SCOPE = (
    "diff --git a/django/core/management/commands/sqlmigrate.py "
    "b/django/core/management/commands/sqlmigrate.py\n"
    "--- a/django/core/management/commands/sqlmigrate.py\n"
    "+++ b/django/core/management/commands/sqlmigrate.py\n"
    "@@ -10 +10 @@\n"
    "-old\n"
    "+new\n"
    "diff --git a/django/other.py b/django/other.py\n"
    "--- a/django/other.py\n"
    "+++ b/django/other.py\n"
    "@@ -1 +1 @@\n"
    "-x\n"
    "+y\n"
)


class TestComputeDiffHygiene:
    def test_empty_diff(self):
        result = compute_diff_hygiene("", [])
        assert result["lines_touched"] == 0
        assert result["files_touched"] == 0
        assert result["scope_creep_flag"] is False
        assert result["touched_files"] == []
        assert result["outside_files"] == []

    def test_in_scope_single_file(self):
        result = compute_diff_hygiene(_DIFF_IN_SCOPE, _DJANGO_KNOWN)
        assert result["files_touched"] == 1
        assert result["lines_touched"] == 3  # one - and two +
        assert result["scope_creep_flag"] is False
        assert result["outside_files"] == []

    def test_out_of_scope_triggers_flag(self):
        result = compute_diff_hygiene(_DIFF_OUT_OF_SCOPE, _DJANGO_KNOWN)
        assert result["files_touched"] == 2
        assert result["scope_creep_flag"] is True
        assert "django/other.py" in result["outside_files"]

    def test_no_known_affected_flags_all(self):
        """If known_affected_files is empty, any touched file triggers scope_creep."""
        result = compute_diff_hygiene(_DIFF_IN_SCOPE, [])
        assert result["scope_creep_flag"] is True
        assert len(result["outside_files"]) == 1

    def test_known_affected_empty_diff_no_flag(self):
        result = compute_diff_hygiene("", ["some/file.py"])
        assert result["scope_creep_flag"] is False

    def test_lines_touched_counts_additions_and_deletions(self):
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-line1\n"
            "-line2\n"
            "+lineA\n"
            "+lineB\n"
            " context\n"
        )
        result = compute_diff_hygiene(diff, ["f.py"])
        assert result["lines_touched"] == 4  # 2 removals + 2 additions


# ---------------------------------------------------------------------------
# _parse_pytest_failures
# ---------------------------------------------------------------------------


class TestParsePytestFailures:
    def test_extracts_from_summary(self):
        stdout = (
            "============================= short test summary info =============================\n"
            "FAILED tests/test_foo.py::TestFoo::test_bar - assert False\n"
            "FAILED tests/test_foo.py::TestFoo::test_baz\n"
            "==================== 2 failed, 3 passed in 1.23s ====================\n"
        )
        failures = _parse_pytest_failures(stdout)
        assert "tests/test_foo.py::TestFoo::test_bar" in failures
        assert "tests/test_foo.py::TestFoo::test_baz" in failures

    def test_empty_on_all_pass(self):
        stdout = "==================== 5 passed in 0.5s ====================\n"
        failures = _parse_pytest_failures(stdout)
        assert failures == []

    def test_fallback_without_summary(self):
        stdout = "FAILED tests/test_x.py::TestX::test_y - assertion error\n"
        failures = _parse_pytest_failures(stdout)
        assert "tests/test_x.py::TestX::test_y" in failures


# ---------------------------------------------------------------------------
# score_cell
# ---------------------------------------------------------------------------


_TASK_META_SINGLE_FILE = {
    "known_affected_files": ["django/core/management/commands/sqlmigrate.py"],
    "estimated_test_seconds": 30,
    "difficulty": "single-file",
}

_PASSING_TRANSCRIPT = (
    "Fixed the issue.\n\n"
    "```diff\n"
    "diff --git a/django/core/management/commands/sqlmigrate.py "
    "b/django/core/management/commands/sqlmigrate.py\n"
    "--- a/django/core/management/commands/sqlmigrate.py\n"
    "+++ b/django/core/management/commands/sqlmigrate.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
    "```"
)

_FAILING_TRANSCRIPT = "Could not identify the bug."


class TestScoreCell:
    def test_pass_when_pytest_returns_zero(self, tmp_path: Path):
        """score_cell returns pass_fail=True when pytest exits 0."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        with patch("scoring.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="5 passed", stderr="")
            result = score_cell(
                task_slug="django-11039",
                transcript=_PASSING_TRANSCRIPT,
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert result.pass_fail is True
        assert result.score_primary == 1.0
        assert result.held_out_failures == []

    def test_fail_when_pytest_returns_nonzero(self, tmp_path: Path):
        """score_cell returns pass_fail=False when pytest exits non-zero."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        pytest_stdout = (
            "============================= short test summary info =============================\n"
            "FAILED tests/test_foo.py::TestFoo::test_bar - assert False\n"
            "==================== 1 failed in 0.5s ====================\n"
        )
        with patch("scoring.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout=pytest_stdout, stderr=""
            )
            result = score_cell(
                task_slug="django-11039",
                transcript=_FAILING_TRANSCRIPT,
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert result.pass_fail is False
        assert result.score_primary == 0.0
        assert len(result.held_out_failures) >= 1

    def test_scope_creep_flag_set_when_outside_files(self, tmp_path: Path):
        """scope_creep_flag is True when the diff touches files outside known_affected."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        # Diff touches an unexpected file.
        transcript = (
            "Fix applied.\n\n"
            "```diff\n"
            "diff --git a/unexpected/module.py b/unexpected/module.py\n"
            "--- a/unexpected/module.py\n"
            "+++ b/unexpected/module.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
            "```"
        )
        with patch("scoring.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = score_cell(
                task_slug="django-11039",
                transcript=transcript,
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert result.scope_creep_flag is True
        assert "unexpected/module.py" in result.diagnostics.get("outside_files", [])

    def test_empty_transcript_yields_zero_diff_metrics(self, tmp_path: Path):
        """Empty transcript -> lines_touched=0, files_touched=0, scope_creep_flag=False."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        with patch("scoring.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = score_cell(
                task_slug="django-11039",
                transcript="",
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert result.lines_touched == 0
        assert result.files_touched == 0
        assert result.scope_creep_flag is False
        assert result.diff_text == ""


# ---------------------------------------------------------------------------
# Bug-1 regression: interpreter selection differs between local and Tier 3
# ---------------------------------------------------------------------------


class TestRunPytestLocalUsesSystemExecutable:
    """Regression: _run_pytest_local must use sys.executable, not a bare name.

    Bare 'python' fails on macOS / envs where only 'python3' exists.
    sys.executable guarantees the caller uses the same interpreter the
    host process is running under.
    """

    def test_cmd_uses_sys_executable(self, tmp_path: Path):
        held_dir = tmp_path / "held"
        held_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        captured_cmds: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "1 passed"
            mock.stderr = ""
            return mock

        with patch("scoring.subprocess.run", side_effect=fake_run):
            _run_pytest_local(held_dir, fix_dir, timeout=30)

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        assert cmd[0] == sys.executable, (
            f"_run_pytest_local cmd[0] must be sys.executable ({sys.executable!r}); "
            f"got {cmd[0]!r}. Host interpreter is required for local invocation."
        )
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"


class TestRunPytestTier3UsesContainerInterpreter:
    """Regression: _run_pytest_tier3 must NOT use sys.executable.

    sys.executable is a host path that does not exist inside the Docker
    container. The python:3.11-slim base image guarantees 'python3' on PATH;
    the cmd must use 'python3' (container-resident) instead.
    """

    def test_cmd_uses_python3_not_sys_executable(self):
        from unittest.mock import MagicMock

        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            # Import after patching so the local import inside _run_pytest_tier3
            # picks up the mock.
            from scoring import _run_pytest_tier3
            _run_pytest_tier3(fake_ctx, timeout=30)

        assert captured_cmds, "Tier3Docker.run_score_phase must have been called"
        cmd = captured_cmds[0]
        assert cmd[0] == "python3", (
            f"_run_pytest_tier3 cmd[0] must be 'python3'; got {cmd[0]!r}. "
            "sys.executable is a host path and does not exist inside the container."
        )
        assert cmd[0] != sys.executable, (
            "cmd[0] must NOT be sys.executable - that path is host-only and "
            "causes ENOENT inside Docker."
        )
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"


class TestScoreCellUsesSystemExecutable:
    """Regression: score_cell (local path) must use sys.executable via _run_pytest_local."""

    def test_score_cell_cmd_uses_sys_executable(self, tmp_path: Path):
        """subprocess.run must be called with sys.executable as cmd[0] on local path."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        captured_cmds: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "1 passed"
            mock.stderr = ""
            return mock

        with patch("scoring.subprocess.run", side_effect=fake_run):
            score_cell(
                task_slug="django-11039",
                transcript=_PASSING_TRANSCRIPT,
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        assert cmd[0] == sys.executable, (
            f"cmd[0] must be sys.executable ({sys.executable!r}); got {cmd[0]!r}. "
            "Hardcoded 'python' fails on macOS / envs without a 'python' symlink."
        )
        assert cmd[1] == "-m"
        assert cmd[2] == "pytest"


# ---------------------------------------------------------------------------
# Regression: fail_to_pass forwarded to BOTH local and tier3 pytest runners
# [smoke-bugs-r3]
# ---------------------------------------------------------------------------


class TestFailToPassForwarding:
    """Regression: fail_to_pass must reach _run_pytest_tier3's pytest cmd.

    Previously, score_cell forwarded fail_to_pass only to _run_pytest_local.
    The tier3 branch called _run_pytest_tier3 without the argument, causing
    it to always run the full /scoring/tests tree regardless of the caller's
    intent. This suite pins the fix.
    """

    def test_tier3_cmd_includes_node_ids_when_fail_to_pass_given(self):
        """_run_pytest_tier3 must use provided node-ids, not /scoring/tests."""
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        node_ids = [
            "tests/test_sqlmigrate.py::TestSqlMigrate::test_forward",
            "tests/test_sqlmigrate.py::TestSqlMigrate::test_backward",
        ]

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds, "Tier3Docker.run_score_phase must have been called"
        cmd = captured_cmds[0]
        # Each node-id must appear in the cmd, prefixed with /scoring/tests/.
        for nid in node_ids:
            expected = f"/scoring/tests/{nid}"
            assert expected in cmd, (
                f"Expected '{expected}' in tier3 pytest cmd; cmd was: {cmd}. "
                "fail_to_pass node-ids must be prefixed with /scoring/tests/ "
                "to match the in-container mount path."
            )
        # The bare /scoring/tests target must NOT appear when node-ids are given.
        assert "/scoring/tests" not in cmd, (
            "When fail_to_pass is provided, the full /scoring/tests tree "
            "must NOT appear in the cmd - only the specific node-ids."
        )

    def test_tier3_cmd_uses_full_tree_when_fail_to_pass_is_none(self):
        """_run_pytest_tier3 must fall back to /scoring/tests when fail_to_pass is None."""
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "5 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=None)

        assert captured_cmds
        cmd = captured_cmds[0]
        assert "/scoring/tests" in cmd, (
            "When fail_to_pass is None, cmd must target the full /scoring/tests tree."
        )

    def test_score_cell_tier3_branch_forwards_fail_to_pass(self, tmp_path: Path):
        """score_cell must forward fail_to_pass to _run_pytest_tier3.

        Regression test for the bug where score_cell passed fail_to_pass to
        _run_pytest_local but NOT to _run_pytest_tier3, causing the tier3
        branch to always run the full /scoring/tests tree.
        """
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        node_ids = ["tests/test_sqlmigrate.py::TestSqlMigrate::test_forward"]

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        fake_tier3_ctx = MagicMock()

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            score_cell(
                task_slug="django-11039",
                transcript=_PASSING_TRANSCRIPT,
                task_meta=_TASK_META_SINGLE_FILE,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                tier3_ctx=fake_tier3_ctx,
                pytest_timeout=30,
                fail_to_pass=node_ids,
            )

        assert captured_cmds, "Tier3Docker.run_score_phase must have been called"
        cmd = captured_cmds[0]
        expected = f"/scoring/tests/{node_ids[0]}"
        assert expected in cmd, (
            f"score_cell must forward fail_to_pass to _run_pytest_tier3; "
            f"expected '{expected}' in cmd, got: {cmd}"
        )
        # Full tree must not be present when specific node-ids are given.
        assert "/scoring/tests" not in [t for t in cmd if t == "/scoring/tests"], (
            "score_cell must not pass the full /scoring/tests target when "
            "fail_to_pass is provided."
        )

    def test_local_cmd_includes_node_ids_when_fail_to_pass_given(self, tmp_path: Path):
        """_run_pytest_local must resolve node-ids against held_out_dir."""
        held_dir = tmp_path / "held"
        held_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        node_ids = ["test_foo.py::TestFoo::test_bar"]

        captured_cmds: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "1 passed"
            mock.stderr = ""
            return mock

        with patch("scoring.subprocess.run", side_effect=fake_run):
            _run_pytest_local(held_dir, fix_dir, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds
        cmd = captured_cmds[0]
        # Node-id must appear resolved against held_dir.
        expected = str(held_dir / node_ids[0])
        assert expected in cmd, (
            f"_run_pytest_local must resolve node-ids against held_out_dir; "
            f"expected '{expected}' in cmd, got: {cmd}"
        )


# ---------------------------------------------------------------------------
# Regression: pytest 0-tests-collected fix [smoke-v5-pytest-collection]
# --noconftest and --rootdir must NOT appear in the cmd when node-ids are given.
# These flags prevent pytest from loading conftest.py needed by SWE-bench tests
# and from finding tests when rootdir does not match the node-id path prefix.
# ---------------------------------------------------------------------------


class TestPytestCollectionFlags:
    """Regression: _run_pytest_tier3 must not use --noconftest or --rootdir
    when specific node-ids are provided (smoke v5 0-tests-collected fix).

    --noconftest blanket-disables all conftest.py including legitimate ones
    in /scoring/tests needed by SWE-bench tests for fixture collection.
    --rootdir conflicts with absolute node-id paths causing 0 tests collected.
    --confcutdir=/scoring is retained (prevents agent conftest at /workspace/repo).
    """

    def test_no_noconftest_flag_when_node_ids_given(self):
        """`--noconftest` must NOT appear in the cmd when fail_to_pass is given."""
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        node_ids = ["tests/test_requests.py::TestRequests::test_response_decode_unicode"]

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds
        cmd = captured_cmds[0]
        assert "--noconftest" not in cmd, (
            "pytest cmd MUST NOT include --noconftest when fail_to_pass is given. "
            "--noconftest blocks legitimate conftest.py in /scoring/tests that "
            "SWE-bench tests require for collection. "
            f"Got cmd: {cmd}"
        )

    def test_no_rootdir_flag_when_node_ids_given(self):
        """`--rootdir` must NOT appear in the cmd when fail_to_pass is given."""
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        node_ids = ["tests/test_requests.py::TestRequests::test_response_decode_unicode"]

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds
        cmd = captured_cmds[0]
        rootdir_flags = [arg for arg in cmd if arg.startswith("--rootdir")]
        assert not rootdir_flags, (
            "pytest cmd MUST NOT include --rootdir when fail_to_pass is given. "
            "--rootdir conflicts with absolute node-id paths and causes "
            "0 tests collected when rootdir != node-id path prefix. "
            f"Got cmd: {cmd}"
        )

    def test_confcutdir_retained_when_node_ids_given(self):
        """`--confcutdir=/scoring` must appear in the cmd when fail_to_pass is given.

        This is the isolation guard that prevents agent-planted conftest.py at
        /workspace/repo from loading. It must be retained even when --noconftest
        and --rootdir are dropped.
        """
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "1 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        node_ids = ["tests/test_requests.py::TestRequests::test_response_decode_unicode"]

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds
        cmd = captured_cmds[0]
        assert "--confcutdir=/scoring" in cmd, (
            "pytest cmd MUST include --confcutdir=/scoring when fail_to_pass is "
            "given. This prevents agent-planted conftest.py at /workspace/repo "
            "from loading during scoring. "
            f"Got cmd: {cmd}"
        )

    def test_node_ids_in_cmd_when_fail_to_pass_given(self):
        """All fail_to_pass node-ids must appear in the cmd prefixed with /scoring/tests/."""
        fake_ctx = MagicMock()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "2 passed"
        fake_result.stderr = ""

        captured_cmds: list[list] = []

        def fake_run_score_phase(ctx, cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return fake_result

        node_ids = [
            "tests/test_requests.py::TestRequests::test_response_decode_unicode",
            "tests/test_requests.py::TestRequests::test_redirect",
        ]

        with patch("evals.runner.isolator.Tier3Docker") as MockDocker:
            MockDocker.run_score_phase.side_effect = fake_run_score_phase
            _run_pytest_tier3(fake_ctx, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds
        cmd = captured_cmds[0]
        for nid in node_ids:
            expected = f"/scoring/tests/{nid}"
            assert expected in cmd, (
                f"Node-id '{nid}' must appear as '{expected}' in the pytest cmd. "
                f"Got cmd: {cmd}"
            )


# ---------------------------------------------------------------------------
# smoke-v6 regression: compute_engineer_diff_from_workdir
# ---------------------------------------------------------------------------


class TestComputeEngineerDiffFromWorkdir:
    """Regression tests for smoke-v6 diff-source fix.

    Previously score_cell called extract_diff_from_transcript which picked up
    tool_use payloads (test_patch content, diff fragments in stream-json) as the
    engineer's patch, producing garbage lines_touched values (e.g. 4115 lines)
    and misleading scope_creep flags even when the engineer made NO changes.

    The fix: use `git diff <seed_commit>` in fix_phase_dir for ground-truth diffs.
    """

    def test_returns_empty_when_dir_absent(self, tmp_path: Path):
        """Returns '' when fix_phase_dir does not exist."""
        from scoring import compute_engineer_diff_from_workdir
        result = compute_engineer_diff_from_workdir(tmp_path / "nonexistent", "abc123")
        assert result == "", (
            "compute_engineer_diff_from_workdir must return '' when dir is absent"
        )

    def test_returns_diff_from_git_diff_in_temp_repo(self, tmp_path: Path):
        """Returns the actual diff between seed_commit and current HEAD in a real git repo.

        This test creates a real minimal git repo, makes two commits, and verifies
        that compute_engineer_diff_from_workdir returns the diff of the second commit.
        """
        from scoring import compute_engineer_diff_from_workdir
        import subprocess as _sp

        repo = tmp_path / "repo"
        repo.mkdir()

        def git(*args, **kwargs):
            return _sp.run(
                ["git"] + list(args),
                cwd=str(repo),
                capture_output=True,
                text=True,
                check=True,
                **kwargs,
            )

        # Init a minimal git repo.
        git("init")
        git("config", "user.email", "test@test.local")
        git("config", "user.name", "test")

        # Seed commit: create base file.
        (repo / "base.py").write_text("x = 1\n")
        git("add", "-A")
        git("commit", "-m", "seed: initial")
        seed_commit_result = _sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        seed_commit = seed_commit_result.stdout.strip()
        assert seed_commit, "Must have a valid seed commit SHA"

        # Engineer commit: modify the file.
        (repo / "base.py").write_text("x = 2\n")
        git("add", "-A")
        git("commit", "-m", "fix: change x to 2")

        # compute_engineer_diff_from_workdir should return the change from seed.
        diff = compute_engineer_diff_from_workdir(repo, seed_commit)

        assert diff, "Diff must be non-empty when engineer changed a file"
        assert "base.py" in diff, f"base.py must appear in diff; got: {diff[:200]}"
        assert "+x = 2" in diff, f"Engineer change (+x = 2) must be in diff; got: {diff[:200]}"
        assert "-x = 1" in diff, f"Seed baseline (-x = 1) must be in diff; got: {diff[:200]}"

    def test_score_cell_uses_workdir_diff_when_seed_commit_provided(self, tmp_path: Path):
        """score_cell uses git diff <seed_commit> when seed_commit is non-empty and .git exists.

        Regression for smoke-v6: previously score_cell always called
        extract_diff_from_transcript regardless of whether a workdir was available,
        causing garbage diff data from stream-json tool_use payloads.

        This test mocks compute_engineer_diff_from_workdir directly to isolate
        the routing logic without triggering subprocess recursion from the pytest
        runner path.
        """
        import subprocess as _sp

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()  # make it look like a git repo for the routing check

        task_meta = {
            "known_affected_files": ["fix.py"],
            "fail_to_pass": [],
        }

        # The workdir diff we want score_cell to use.
        workdir_diff = (
            "diff --git a/fix.py b/fix.py\n"
            "--- a/fix.py\n"
            "+++ b/fix.py\n"
            "@@ -1 +1 @@\n"
            "-old = True\n"
            "+old = False\n"
        )

        # Transcript contains a noisy diff-like fragment (simulates stream-json
        # tool_use payload) that must NOT be used as the engineer diff.
        noisy_transcript = (
            "diff --git a/unrelated.py b/unrelated.py\n"
            "--- a/unrelated.py\n"
            "+++ b/unrelated.py\n"
            "@@ -1 +1 @@\n"
            "-garbage\n"
            "+noise\n"
        )

        seed_sha = "abc123def456abc123def456abc123def456abc1"

        # Mock compute_engineer_diff_from_workdir to return the clean workdir diff,
        # and mock the pytest subprocess to avoid real test execution.
        with (
            patch("scoring.compute_engineer_diff_from_workdir", return_value=workdir_diff),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        ):
            result = score_cell(
                task_slug="test-slug",
                transcript=noisy_transcript,
                task_meta=task_meta,
                fix_phase_dir=repo,
                held_out_dir=repo,
                tier3_ctx=None,
                pytest_timeout=10,
                fail_to_pass=[],
                seed_commit=seed_sha,
            )

        # The diff must come from the workdir (fix.py changed), not the transcript
        # (unrelated.py garbage).
        assert "fix.py" in result.diff_text, (
            f"diff_text must contain fix.py (workdir diff), not transcript noise; "
            f"diff_text was: {result.diff_text[:400]}"
        )
        assert "unrelated.py" not in result.diff_text, (
            "diff_text must NOT contain unrelated.py (noisy transcript); "
            "workdir diff should have been used instead"
        )
