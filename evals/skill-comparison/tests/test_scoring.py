"""
Tests for evals/skill-comparison/scoring.py.

Coverage:
- extract_diff_from_transcript: fenced block, raw diff, empty transcript.
- compute_diff_hygiene: lines_touched, files_touched, scope_creep_flag across
  fixture diffs including edge cases (empty diff, diff within known files,
  diff outside known files, mixed).
- _parse_pytest_failures: summary section extraction, fallback scanning.
- score_cell: pass (returncode=0), fail (returncode=1), empty transcript.
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
