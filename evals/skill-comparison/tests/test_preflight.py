"""
Tests for evals/skill-comparison/preflight.py.

Coverage:
- classify_status: infra_fail detection (bad returncodes, infra patterns),
  unexpected_pass detection, ok detection.
- _format_table and _format_json: human-readable and JSON output.
- _build_parser: CLI argument parsing and defaults.
- check_task: seed_error path (mocked seeding failure).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# conftest.py inserts skill-comparison/ into sys.path.
from preflight import (
    PreflightResult,
    _build_parser,
    _docker_available,
    _format_json,
    _format_table,
    _is_infra_failure,
    check_task,
    classify_status,
    main,
)
from seeding import SeedError


# ---------------------------------------------------------------------------
# classify_status / _is_infra_failure
# ---------------------------------------------------------------------------


class TestClassifyStatus:
    def test_ok_on_returncode_1(self):
        assert classify_status(1, "some test failures") == "ok"

    def test_unexpected_pass_on_returncode_0(self):
        assert classify_status(0, "all tests passed") == "unexpected_pass"

    def test_infra_fail_on_returncode_2(self):
        assert classify_status(2, "some output") == "infra_fail"

    def test_infra_fail_on_returncode_3(self):
        assert classify_status(3, "some output") == "infra_fail"

    def test_infra_fail_on_negative_returncode(self):
        assert classify_status(-1, "some output") == "infra_fail"

    def test_infra_fail_import_error(self):
        output = "ImportError: No module named 'astropy'"
        assert classify_status(1, output) == "infra_fail"

    def test_infra_fail_module_not_found(self):
        output = "ModuleNotFoundError: No module named 'sphinx'"
        assert classify_status(1, output) == "infra_fail"

    def test_infra_fail_pytest_usage_error(self):
        output = "pytest.UsageError: no such option: --unknown"
        assert classify_status(1, output) == "infra_fail"

    def test_infra_fail_unrecognized_arguments(self):
        output = "pytest: error: unrecognized arguments: --foo"
        assert classify_status(1, output) == "infra_fail"

    def test_infra_fail_config_error(self):
        output = "error: invocation failed\npytest configuration issue"
        assert classify_status(1, output) == "infra_fail"

    def test_infra_fail_patterns_are_case_insensitive(self):
        output = "importerror: No module named 'foo'"
        assert classify_status(1, output) == "infra_fail"

    def test_ok_when_no_infra_patterns_and_rc_1(self):
        output = "FAILED test_foo.py::test_bar - assertion error"
        assert classify_status(1, output) == "ok"


class TestIsInfraFailure:
    def test_true_for_nonzero_nonone_rc(self):
        assert _is_infra_failure(2, "") is True

    def test_false_for_rc_0(self):
        assert _is_infra_failure(0, "") is False

    def test_false_for_rc_1(self):
        assert _is_infra_failure(1, "") is False

    def test_true_for_import_error_in_output(self):
        assert _is_infra_failure(1, "ImportError: foo") is True


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_empty_results(self):
        table = _format_table([])
        assert "0/0 tasks ok" in table

    def test_shows_ok_task(self):
        results = [PreflightResult("django-11039", "ok", returncode=1)]
        table = _format_table(results)
        assert "django-11039" in table
        assert "ok" in table
        assert "1/1 tasks ok" in table

    def test_shows_seed_error_task(self):
        results = [
            PreflightResult(
                "astropy-12907",
                "seed_error",
                seed_error="clone_failed: network unreachable",
            ),
        ]
        table = _format_table(results)
        assert "astropy-12907" in table
        assert "seed_error" in table
        assert "clone_failed" in table

    def test_shows_infra_fail_task(self):
        results = [PreflightResult("sphinx-7686", "infra_fail", returncode=2)]
        table = _format_table(results)
        assert "sphinx-7686" in table
        assert "infra_fail" in table
        assert "infrastructure error" in table

    def test_shows_unexpected_pass_task(self):
        results = [PreflightResult("requests-3362", "unexpected_pass", returncode=0)]
        table = _format_table(results)
        assert "requests-3362" in table
        assert "unexpected_pass" in table
        assert "tests pass on base commit" in table

    def test_summary_counts(self):
        results = [
            PreflightResult("a", "ok", returncode=1),
            PreflightResult("b", "ok", returncode=1),
            PreflightResult("c", "infra_fail", returncode=2),
        ]
        table = _format_table(results)
        assert "2/3 tasks ok" in table


class TestFormatJson:
    def test_serializes_all_fields(self):
        results = [
            PreflightResult(
                task_slug="django-11039",
                status="ok",
                returncode=1,
                pytest_output="some output",
                seed_error="",
                diagnostics={"seed_commit": "abc123"},
            ),
        ]
        raw = _format_json(results)
        parsed = json.loads(raw)
        assert len(parsed) == 1
        assert parsed[0]["task_slug"] == "django-11039"
        assert parsed[0]["status"] == "ok"
        assert parsed[0]["returncode"] == 1
        assert parsed[0]["pytest_output"] == "some output"
        assert parsed[0]["diagnostics"]["seed_commit"] == "abc123"

    def test_empty_list(self):
        raw = _format_json([])
        assert json.loads(raw) == []


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["--tasks-yaml", "tasks/corpus.yaml"])
        assert args.tasks_yaml == Path("tasks/corpus.yaml")
        assert args.tasks is None
        assert args.tier3 == "auto"
        assert args.rebuild_image is False
        assert args.timeout == 120
        assert args.json is False

    def test_tasks_list(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--tasks-yaml", "tasks/corpus.yaml", "--tasks", "a", "b", "c"]
        )
        assert args.tasks == ["a", "b", "c"]

    def test_tier3_off(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--tasks-yaml", "tasks/corpus.yaml", "--tier3", "off"]
        )
        assert args.tier3 == "off"

    def test_json_flag(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--tasks-yaml", "tasks/corpus.yaml", "--json"]
        )
        assert args.json is True

    def test_rebuild_image_flag(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--tasks-yaml", "tasks/corpus.yaml", "--rebuild-image"]
        )
        assert args.rebuild_image is True

    def test_timeout_override(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--tasks-yaml", "tasks/corpus.yaml", "--timeout", "60"]
        )
        assert args.timeout == 60

    def test_missing_tasks_yaml_errors(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ---------------------------------------------------------------------------
# check_task seed_error path
# ---------------------------------------------------------------------------


class TestCheckTask:
    def test_seed_error_returned_on_seed_failure(self):
        """When seed_fix_phase raises SeedError, check_task returns seed_error."""
        with patch("preflight.seed_fix_phase") as mock_seed:
            mock_seed.side_effect = SeedError(
                step="clone_failed", stderr="network unreachable"
            )
            result = check_task(
                task_slug="bad-task",
                task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                tasks_root=Path("/tmp/tasks"),
                tier3=False,
                timeout=120,
                rebuild_image=False,
            )
        assert result.status == "seed_error"
        assert result.task_slug == "bad-task"
        assert "clone_failed" in result.seed_error

    def test_seed_error_on_file_not_found(self):
        """When test_patch.diff is missing, check_task returns seed_error."""
        with patch("preflight.seed_fix_phase") as mock_seed:
            mock_seed.side_effect = FileNotFoundError("test_patch.diff not found")
            result = check_task(
                task_slug="missing-patch",
                task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                tasks_root=Path("/tmp/tasks"),
                tier3=False,
                timeout=120,
                rebuild_image=False,
            )
        assert result.status == "seed_error"
        assert "test_patch.diff" in result.seed_error

    def test_ok_on_local_pytest_failure(self):
        """When local pytest exits 1, check_task returns ok."""
        with patch("preflight.seed_fix_phase") as mock_seed:
            mock_seed.return_value = {"seed_commit": "abc123"}
            with patch("preflight._run_pytest_local") as mock_pytest:
                mock_pytest.return_value = (1, "FAILED test_foo.py::test_bar")
                result = check_task(
                    task_slug="django-11039",
                    task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                    tasks_root=Path("/tmp/tasks"),
                    tier3=False,
                    timeout=120,
                    rebuild_image=False,
                )
        assert result.status == "ok"
        assert result.returncode == 1

    def test_unexpected_pass_on_local_pytest_exit_0(self):
        """When local pytest exits 0, check_task returns unexpected_pass."""
        with patch("preflight.seed_fix_phase") as mock_seed:
            mock_seed.return_value = {"seed_commit": "abc123"}
            with patch("preflight._run_pytest_local") as mock_pytest:
                mock_pytest.return_value = (0, "1 passed")
                result = check_task(
                    task_slug="django-11039",
                    task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                    tasks_root=Path("/tmp/tasks"),
                    tier3=False,
                    timeout=120,
                    rebuild_image=False,
                )
        assert result.status == "unexpected_pass"
        assert result.returncode == 0

    def test_infra_fail_on_local_pytest_exit_2(self):
        """When local pytest exits 2, check_task returns infra_fail."""
        with patch("preflight.seed_fix_phase") as mock_seed:
            mock_seed.return_value = {"seed_commit": "abc123"}
            with patch("preflight._run_pytest_local") as mock_pytest:
                mock_pytest.return_value = (2, "internal error")
                result = check_task(
                    task_slug="django-11039",
                    task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                    tasks_root=Path("/tmp/tasks"),
                    tier3=False,
                    timeout=120,
                    rebuild_image=False,
                )
        assert result.status == "infra_fail"
        assert result.returncode == 2

    def test_tier3_path_runs_pytest_tier3(self):
        """When tier3=True, check_task uses _run_pytest_tier3."""
        mock_ctx = MagicMock()
        mock_ctx.fix_phase_dir = Path("/tmp/fix")

        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_instance.__exit__ = MagicMock(return_value=None)

        with patch("evals.runner.isolator.Tier3Docker") as MockTier3:
            MockTier3.ensure_image = MagicMock()
            MockTier3.return_value = mock_instance
            with patch("preflight.seed_fix_phase") as mock_seed:
                mock_seed.return_value = {"seed_commit": "abc123"}
                with patch("preflight._run_pytest_tier3") as mock_pytest:
                    mock_pytest.return_value = (1, "FAILED test.py::test")
                    result = check_task(
                        task_slug="django-11039",
                        task_meta={"repo_url": "https://example.com/repo", "base_commit": "abc"},
                        tasks_root=Path("/tmp/tasks"),
                        tier3=True,
                        timeout=120,
                        rebuild_image=False,
                    )
        assert result.status == "ok"
        mock_pytest.assert_called_once_with(mock_ctx, 120, fail_to_pass=[])
        mock_instance.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_yaml_exits_2(self):
        with patch("sys.stderr", new=io.StringIO()):
            rc = main(["--tasks-yaml", "/nonexistent/corpus.yaml"])
        assert rc == 2

    def test_unknown_task_exits_2(self):
        with patch.object(Path, "read_text", return_value=""):
            with patch("preflight.yaml.safe_load", return_value={"tasks": {"django-11039": {}}}):
                with patch("sys.stderr", new=io.StringIO()):
                    rc = main([
                        "--tasks-yaml", "tasks/corpus.yaml",
                        "--tasks", "unknown-task",
                    ])
        assert rc == 2

    def test_all_ok_returns_0(self):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value=""):
                with patch("preflight.yaml.safe_load", return_value={"tasks": {"django-11039": {}}}):
                    with patch("preflight.check_task") as mock_check:
                        mock_check.return_value = PreflightResult("django-11039", "ok", returncode=1)
                        with patch("preflight._docker_available", return_value=False):
                            rc = main([
                                "--tasks-yaml", "tasks/corpus.yaml",
                                "--tier3", "off",
                            ])
        assert rc == 0

    def test_any_not_ok_returns_1(self):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value=""):
                with patch("preflight.yaml.safe_load", return_value={"tasks": {"django-11039": {}}}):
                    with patch("preflight.check_task") as mock_check:
                        mock_check.return_value = PreflightResult(
                            "django-11039", "infra_fail", returncode=2
                        )
                        with patch("preflight._docker_available", return_value=False):
                            rc = main([
                                "--tasks-yaml", "tasks/corpus.yaml",
                                "--tier3", "off",
                            ])
        assert rc == 1

    def test_json_output_flag(self):
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value=""):
                with patch("preflight.yaml.safe_load", return_value={"tasks": {"django-11039": {}}}):
                    with patch("preflight.check_task") as mock_check:
                        mock_check.return_value = PreflightResult("django-11039", "ok", returncode=1)
                        with patch("preflight._docker_available", return_value=False):
                            with patch("builtins.print") as mock_print:
                                rc = main([
                                    "--tasks-yaml", "tasks/corpus.yaml",
                                    "--tier3", "off",
                                    "--json",
                                ])
        assert rc == 0
        printed = mock_print.call_args[0][0]
        parsed = json.loads(printed)
        assert parsed[0]["task_slug"] == "django-11039"
