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
# smoke-bugs-r2 regression: score_cell must use fail_to_pass node-ids
# ---------------------------------------------------------------------------


_TASK_META_WITH_FAIL_TO_PASS = {
    "known_affected_files": ["requests/utils.py"],
    "estimated_test_seconds": 15,
    "difficulty": "single-file",
    "fail_to_pass": [
        "tests/test_requests.py::TestRequests::test_response_decode_unicode",
    ],
}


class TestScoreCellUseFailToPassNodeIds:
    """Regression for smoke-bugs-r2 Bug 2: scoring must use fail_to_pass node-ids.

    Previously score_cell passed the held_out_dir directory path to pytest.
    When that directory does not exist under fix_phase_dir, pytest collects
    0 tests. The fix uses fail_to_pass entries (specific node-ids) instead.
    """

    def test_score_cell_passes_fail_to_pass_ids_to_pytest(self, tmp_path: Path):
        """score_cell must pass fail_to_pass node-ids to pytest, not held_out_dir path."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        held_dir = tmp_path / "held"
        held_dir.mkdir()

        captured_cmds: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 1
            mock.stdout = "1 failed"
            mock.stderr = ""
            return mock

        with patch("scoring.subprocess.run", side_effect=fake_run):
            score_cell(
                task_slug="requests-3362",
                transcript="",
                task_meta=_TASK_META_WITH_FAIL_TO_PASS,
                fix_phase_dir=fix_dir,
                held_out_dir=held_dir,
                pytest_timeout=30,
            )

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        node_id = "tests/test_requests.py::TestRequests::test_response_decode_unicode"
        assert node_id in cmd, (
            f"pytest cmd must include the fail_to_pass node-id {node_id!r}; "
            f"got cmd: {cmd}. Passing only the file path causes 0 tests collected."
        )
        # Must NOT pass the held_out_dir as the sole test argument (that was the bug).
        assert str(held_dir) not in cmd, (
            f"pytest cmd must NOT include held_out_dir {held_dir!r} when "
            f"fail_to_pass is populated; got cmd: {cmd}"
        )

    def test_run_pytest_local_uses_fail_to_pass_when_provided(self, tmp_path: Path):
        """_run_pytest_local must substitute fail_to_pass for held_out_dir."""
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

        node_ids = [
            "tests/test_requests.py::TestRequests::test_response_decode_unicode"
        ]
        with patch("scoring.subprocess.run", side_effect=fake_run):
            _run_pytest_local(held_dir, fix_dir, timeout=30, fail_to_pass=node_ids)

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        assert node_ids[0] in cmd, (
            f"fail_to_pass node-id must appear in pytest cmd; got: {cmd}"
        )
        assert str(held_dir) not in cmd, (
            f"held_out_dir path must NOT appear in cmd when fail_to_pass supplied; "
            f"got: {cmd}"
        )

    def test_run_pytest_local_falls_back_to_held_dir_when_no_fail_to_pass(
        self, tmp_path: Path
    ):
        """_run_pytest_local falls back to held_out_dir when fail_to_pass is empty."""
        held_dir = tmp_path / "held"
        held_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        captured_cmds: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = "0 passed"
            mock.stderr = ""
            return mock

        import warnings
        with patch("scoring.subprocess.run", side_effect=fake_run):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                _run_pytest_local(held_dir, fix_dir, timeout=30, fail_to_pass=[])

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        assert str(held_dir) in cmd, (
            f"held_out_dir must appear in cmd when fail_to_pass is empty; got: {cmd}"
        )
        # A RuntimeWarning must have been emitted to surface the fallback.
        warning_types = [x.category for x in w]
        assert RuntimeWarning in warning_types, (
            "A RuntimeWarning must be emitted when falling back to held_out_dir"
        )
