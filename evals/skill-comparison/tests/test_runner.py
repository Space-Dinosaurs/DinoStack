"""
Tests for evals/skill-comparison/runner.py.

Coverage:
- Dry-run 1 task x 8 conditions x n=1 produces a valid TSV with correct schema.
- Each TSV row has the expected columns and correct condition value.
- BudgetExceeded path: mocked CostGate raises BudgetExceeded; run_matrix returns
  budget_breached=True, partial=True, and exit code 3 (tested via report fields).
- Wall-clock ceiling: mocked time causes immediate wall-clock breach on second cell.
- TSV append mode: a pre-existing TSV gains rows without losing header.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# conftest.py inserts skill-comparison/ into sys.path.
from runner import (
    CONDITION_LABELS,
    RunReport,
    _TSV_HEADER,
    _append_tsv_row,
    _ensure_tsv_header,
    run_matrix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_tsv(path: Path) -> list[dict]:
    """Read the TSV ledger and return a list of row dicts."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [dict(r) for r in reader]


# ---------------------------------------------------------------------------
# Corpus / tasks fixture
# ---------------------------------------------------------------------------

_MINIMAL_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate_for_non_transactional_databases (migrations.test_commands.MigrateTests)"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: >
      sqlmigrate wraps output in BEGIN/COMMIT even when the database does not
      support transactional DDL.
"""


@pytest.fixture
def corpus_yaml(tmp_path: Path) -> Path:
    """Write a minimal corpus YAML with one task to tmp_path."""
    p = tmp_path / "corpus.yaml"
    p.write_text(_MINIMAL_CORPUS_YAML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _ensure_tsv_header / _append_tsv_row
# ---------------------------------------------------------------------------


class TestTsvHelpers:
    def test_ensure_tsv_header_creates_file(self, tmp_path: Path):
        path = tmp_path / "results" / "test.tsv"
        _ensure_tsv_header(path)
        assert path.exists()
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            header = next(reader)
        assert list(header) == list(_TSV_HEADER)

    def test_ensure_tsv_header_idempotent(self, tmp_path: Path):
        """Calling twice on a non-empty file does not add a second header."""
        path = tmp_path / "test.tsv"
        _ensure_tsv_header(path)
        # Append a data row manually to make it non-empty.
        _append_tsv_row(
            path,
            {col: "x" for col in _TSV_HEADER},
        )
        _ensure_tsv_header(path)  # should be a no-op
        rows = _read_tsv(path)
        assert len(rows) == 1  # exactly one data row, not two

    def test_append_row_adds_to_existing(self, tmp_path: Path):
        path = tmp_path / "test.tsv"
        _ensure_tsv_header(path)
        for i in range(3):
            _append_tsv_row(
                path,
                {col: str(i) for col in _TSV_HEADER},
            )
        rows = _read_tsv(path)
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# run_matrix dry-run: 1 task x 8 conditions x n=1
# ---------------------------------------------------------------------------


class TestRunMatrixDryRun:
    def test_1_task_8_conditions_n1_produces_valid_tsv(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Dry-run 1 task x 8 conditions x n=1 produces 8 TSV rows."""
        results_tsv = tmp_path / "skill-comparison.tsv"

        # Patch score_cell to avoid subprocess calls.
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True,
            score_primary=1.0,
            lines_touched=2,
            files_touched=1,
            scope_creep_flag=False,
            held_out_failures=[],
            pytest_returncode=0,
            diff_text="diff --git a/f.py b/f.py",
            diagnostics={},
        )

        with patch("runner.score_cell", return_value=canned_score):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=CONDITION_LABELS,
            )

        assert report.rows_written == 8, (
            f"Expected 8 rows (1 task x 8 conditions x n=1), got {report.rows_written}"
        )
        assert report.budget_breached is False
        assert report.partial is False

        rows = _read_tsv(results_tsv)
        assert len(rows) == 8

        # Check schema - every row has all expected columns.
        for row in rows:
            for col in _TSV_HEADER:
                assert col in row, f"Missing column {col!r} in row {row}"

        # Check all 8 conditions appear.
        conditions_seen = {r["condition"] for r in rows}
        assert conditions_seen == set(CONDITION_LABELS)

        # task_slug is correct.
        for row in rows:
            assert row["task_slug"] == "django-11039"

        # replicate is "1" for all (n=1).
        for row in rows:
            assert row["replicate"] == "1"

        # pass_fail populated.
        for row in rows:
            assert row["pass_fail"] in ("0", "1")

    def test_tsv_append_mode_preserves_prior_rows(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Running twice with force=True appends rows rather than overwriting."""
        results_tsv = tmp_path / "skill-comparison.tsv"

        from scoring import ScoringResult

        canned = ScoringResult(
            pass_fail=False,
            score_primary=0.0,
            lines_touched=0,
            files_touched=0,
            scope_creep_flag=False,
        )

        with patch("runner.score_cell", return_value=canned):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )
            # force=True bypasses resume; this tests that the file is opened
            # in append mode (not truncated / overwritten).
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                force=True,
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, "Second force run should append, not overwrite"

    def test_methodology_pair_uses_higher_n(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """baseline and ae-rules-injected use n_replicates_methodology, others use n_replicates."""
        results_tsv = tmp_path / "skill-comparison.tsv"

        from scoring import ScoringResult

        canned = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        with patch("runner.score_cell", return_value=canned):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=2,
                n_replicates_methodology=3,
                dry_run=True,
                conditions=["baseline", "engineer-direct"],
            )

        rows = _read_tsv(results_tsv)
        baseline_rows = [r for r in rows if r["condition"] == "baseline"]
        engineer_rows = [r for r in rows if r["condition"] == "engineer-direct"]

        assert len(baseline_rows) == 3, "baseline should use n_replicates_methodology=3"
        assert len(engineer_rows) == 2, "engineer-direct should use n_replicates=2"


# ---------------------------------------------------------------------------
# BudgetExceeded path
# ---------------------------------------------------------------------------


class TestBudgetExceeded:
    def test_budget_exceeded_sets_partial_and_error(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When CostGate raises BudgetExceeded, run_matrix returns budget_breached=True."""
        from evals.icl_vs_orchestration.cost_gate import BudgetExceeded

        results_tsv = tmp_path / "skill-comparison.tsv"

        from scoring import ScoringResult

        canned = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        # Raise BudgetExceeded on the first record call.
        budget_error = BudgetExceeded(
            scope="global",
            cell_id=None,
            totals={"global_usd": 300.0, "limit_usd": 250.0,
                    "global_tokens": 0, "limit_tokens": 75_000_000},
        )

        with (
            patch("runner.score_cell", return_value=canned),
            patch(
                "evals.icl_vs_orchestration.cost_gate.CostGate.record",
                side_effect=budget_error,
            ),
        ):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        assert report.budget_breached is True
        assert report.partial is True
        assert report.error is not None
        assert "Budget exceeded" in report.error or "global" in report.error.lower()

    def test_budget_exceeded_exit3_semantics(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Confirms the RunReport signals that __main__ should sys.exit(3)."""
        from evals.icl_vs_orchestration.cost_gate import BudgetExceeded

        results_tsv = tmp_path / "skill-comparison.tsv"
        from scoring import ScoringResult

        canned = ScoringResult(
            pass_fail=False, score_primary=0.0,
            lines_touched=0, files_touched=0, scope_creep_flag=False,
        )

        budget_error = BudgetExceeded(
            scope="global",
            cell_id=None,
            totals={"global_usd": 300.0, "limit_usd": 250.0,
                    "global_tokens": 0, "limit_tokens": 75_000_000},
        )

        with (
            patch("runner.score_cell", return_value=canned),
            patch(
                "evals.icl_vs_orchestration.cost_gate.CostGate.record",
                side_effect=budget_error,
            ),
        ):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        # The caller (main) checks budget_breached and calls sys.exit(3).
        assert report.budget_breached is True


# ---------------------------------------------------------------------------
# Wall-clock ceiling
# ---------------------------------------------------------------------------


class TestWallClockCeiling:
    def test_wall_clock_breach_halts_matrix(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When elapsed time exceeds max_wall_seconds, partial=True is returned."""
        results_tsv = tmp_path / "skill-comparison.tsv"
        from scoring import ScoringResult

        canned = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        # First call to time.monotonic returns 0 (start), subsequent calls
        # return a value larger than max_wall_seconds so the check fires on
        # the second cell.
        time_sequence = iter([0.0, 99999.0])

        def mock_monotonic():
            try:
                return next(time_sequence)
            except StopIteration:
                return 99999.0

        with (
            patch("runner.score_cell", return_value=canned),
            patch("runner.time.monotonic", side_effect=mock_monotonic),
        ):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=2,
                n_replicates_methodology=2,
                dry_run=True,
                conditions=["baseline"],
                max_wall_seconds=10.0,
            )

        assert report.partial is True


# ---------------------------------------------------------------------------
# CRITICAL-1 regression: ae-rules-injected must reach subprocess CLI cmd
# ---------------------------------------------------------------------------


def _make_completed_process(stdout: str = "", returncode: int = 0) -> MagicMock:
    """Return a fake CompletedProcess for subprocess.run mocks."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = ""
    return cp


class TestAeRulesSystemPrompt:
    """End-to-end regression suite for CRITICAL-1.

    These tests mock subprocess.run (the actual CLI invocation boundary) rather
    than invoke_run. This proves the --append-system-prompt flag reaches the
    subprocess cmd list - a wholesale invoke_run mock would hide any kwarg
    mismatch between runner._run_cell and invoker.invoke_run.
    """

    def test_ae_rules_injected_appends_system_prompt_flag_to_cmd(self, tmp_path: Path):
        """ae-rules-injected condition causes --append-system-prompt to appear in CLI cmd.

        Regression test for CRITICAL-1: verifies end-to-end that the ae_payload
        reaches the subprocess invocation, not just that invoke_run is called with
        the right kwarg.
        """
        from runner import _run_cell

        ae_payload = "## AE methodology rules content here"
        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }

        captured_cmds: list[list[str]] = []

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return _make_completed_process(stdout="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            _run_cell(
                task_slug="test-task",
                task_meta=task_meta,
                condition="ae-rules-injected",
                replicate=1,
                ae_payload=ae_payload,
                dry_run=False,
            )

        assert captured_cmds, "subprocess.run must have been called"
        # The CLI invocation is the last captured cmd (probe_claude_cli may fire
        # too, but we care that at least one cmd contains the flag).
        invoke_cmd = captured_cmds[-1]
        assert "--append-system-prompt" in invoke_cmd, (
            f"--append-system-prompt must appear in CLI cmd; cmd was: {invoke_cmd}"
        )
        flag_idx = invoke_cmd.index("--append-system-prompt")
        assert invoke_cmd[flag_idx + 1] == ae_payload, (
            f"--append-system-prompt value must be ae_payload; "
            f"got: {invoke_cmd[flag_idx + 1]!r}"
        )

    def test_baseline_has_no_append_system_prompt_flag(self, tmp_path: Path):
        """baseline condition must NOT pass --append-system-prompt to the CLI."""
        from runner import _run_cell

        ae_payload = "some payload"
        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }

        captured_cmds: list[list[str]] = []

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return _make_completed_process(stdout="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            _run_cell(
                task_slug="test-task",
                task_meta=task_meta,
                condition="baseline",
                replicate=1,
                ae_payload=ae_payload,
                dry_run=False,
            )

        assert captured_cmds, "subprocess.run must have been called"
        invoke_cmd = captured_cmds[-1]
        assert "--append-system-prompt" not in invoke_cmd, (
            f"baseline must NOT include --append-system-prompt; cmd was: {invoke_cmd}"
        )

    def test_agent_direct_conditions_have_no_append_system_prompt_flag(self, tmp_path: Path):
        """All named-agent conditions (xxx-direct) must NOT pass --append-system-prompt."""
        from runner import _run_cell, _AGENT_CONDITIONS

        ae_payload = "some payload"
        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }

        for condition in _AGENT_CONDITIONS:
            captured_cmds: list[list[str]] = []

            def fake_subprocess_run(cmd, **kwargs):
                captured_cmds.append(list(cmd))
                return _make_completed_process(stdout="")

            with patch("subprocess.run", side_effect=fake_subprocess_run):
                _run_cell(
                    task_slug="test-task",
                    task_meta=task_meta,
                    condition=condition,
                    replicate=1,
                    ae_payload=ae_payload,
                    dry_run=False,
                )

            assert captured_cmds, f"subprocess.run must have been called for {condition}"
            invoke_cmd = captured_cmds[-1]
            assert "--append-system-prompt" not in invoke_cmd, (
                f"condition {condition!r} must NOT include --append-system-prompt; "
                f"cmd was: {invoke_cmd}"
            )


# ---------------------------------------------------------------------------
# CRITICAL-2 regression: Tier3Docker instantiated in production path
# ---------------------------------------------------------------------------


class TestTier3Instantiation:
    def test_tier3_instantiated_when_auto_mode_not_dry_run(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Tier3Docker is instantiated when tier3_mode='auto' and dry_run=False.

        Regression test for CRITICAL-2: previously tier3_ctx=None was passed
        unconditionally, bypassing the Tier 3 Docker isolator entirely.
        """
        from scoring import ScoringResult
        from unittest.mock import MagicMock
        from evals.runner.isolator import Tier3Context

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        canned_result = {
            "final_text": "Fixed.",
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {},
            "latency_ms": 0,
            "invocation_mode": "agent",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
        }

        # Mock Tier3Docker so docker subprocess is never actually called.
        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag="ae-eval-swebench:latest",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3 = MagicMock()
        mock_tier3.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3.__exit__ = MagicMock(return_value=None)
        mock_tier3_cls = MagicMock(return_value=mock_tier3)

        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._run_cell", return_value=canned_result),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,  # production path
                conditions=["baseline"],
                tier3_mode="auto",
            )

        assert mock_tier3_cls.called, (
            "Tier3Docker must be instantiated when tier3_mode='auto' and dry_run=False"
        )
        assert mock_tier3.__enter__.called, "Tier3Docker.__enter__ must be called"
        assert mock_tier3.__exit__.called, "Tier3Docker.__exit__ must be called (cleanup)"

    def test_tier3_skipped_when_dry_run(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Tier3Docker is NOT instantiated when dry_run=True."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        mock_tier3_cls = MagicMock()
        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tier3_mode="auto",  # auto but dry_run overrides to off
            )

        assert not mock_tier3_cls.called, (
            "Tier3Docker must NOT be instantiated when dry_run=True"
        )

    def test_tier3_skipped_when_mode_off(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Tier3Docker is NOT instantiated when tier3_mode='off'."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        mock_tier3_cls = MagicMock()
        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tier3_mode="off",
            )

        assert not mock_tier3_cls.called, (
            "Tier3Docker must NOT be instantiated when tier3_mode='off'"
        )


# ---------------------------------------------------------------------------
# MAJOR-1 regression: resume skips completed cells
# ---------------------------------------------------------------------------


class TestResumeSemantics:
    def test_resume_skips_completed_cells(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Re-running with a pre-existing TSV only adds missing cells.

        Regression test for MAJOR-1: previously all cells were re-run on
        resume, causing duplicate (task_slug, condition, replicate) rows.
        """
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        # First run: write baseline replicate 1.
        with patch("runner.score_cell", return_value=canned_score):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        rows_after_first = _read_tsv(results_tsv)
        assert len(rows_after_first) == 1

        # Second run: same conditions. Resume should skip the already-done cell.
        with patch("runner.score_cell", return_value=canned_score):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        rows_after_second = _read_tsv(results_tsv)
        assert len(rows_after_second) == 1, (
            "Resume must not add duplicate rows for already-completed cells; "
            f"expected 1 row, got {len(rows_after_second)}"
        )
        assert report.rows_written == 0, (
            f"rows_written should be 0 (all cells skipped), got {report.rows_written}"
        )

    def test_force_reruns_completed_cells(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """force=True bypasses resume and re-runs completed cells."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        # First run.
        with patch("runner.score_cell", return_value=canned_score):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        # Second run with force=True: should add a second row.
        with patch("runner.score_cell", return_value=canned_score):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                force=True,
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"force=True should re-run and append; expected 2 rows, got {len(rows)}"
        )
        assert report.rows_written == 1

    def test_resume_adds_missing_cells(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Resume adds cells not yet present while skipping completed ones."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        # First run: only baseline.
        with patch("runner.score_cell", return_value=canned_score):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        assert len(_read_tsv(results_tsv)) == 1

        # Second run: baseline + engineer-direct.
        # baseline is already done; engineer-direct is missing.
        with patch("runner.score_cell", return_value=canned_score):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline", "engineer-direct"],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"Resume should add engineer-direct but skip baseline; expected 2, got {len(rows)}"
        )
        assert report.rows_written == 1, (
            f"Only 1 new cell should have been written (engineer-direct), got {report.rows_written}"
        )


# ---------------------------------------------------------------------------
# Bug-2 regression: score_cell raise -> status="score_error", not "ok"
# ---------------------------------------------------------------------------


class TestScoreCellRaiseProducesScoreErrorStatus:
    """Regression test for Bug-2: when score_cell raises, the TSV row must
    record status='score_error', not the engineer run_status ('ok').

    Previously the except branch only populated `scored` with a sentinel
    ScoringResult but left run_status unchanged, so every scoring failure
    appeared as status='ok' in the TSV - indistinguishable from a clean run.
    """

    def test_score_cell_exception_sets_score_error_status(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When score_cell raises, the appended TSV row has status='score_error'."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", side_effect=RuntimeError("pytest binary not found")):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        assert report.rows_written == 1, "Row must still be written even when scoring fails"
        rows = _read_tsv(results_tsv)
        assert len(rows) == 1
        assert rows[0]["status"] == "score_error", (
            f"Expected status='score_error' when score_cell raises; "
            f"got status={rows[0]['status']!r}. "
            "Misleading 'ok' status was the pre-fix behaviour."
        )

    def test_score_cell_ok_run_keeps_original_status(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When score_cell succeeds, run_status from the engineer phase is preserved."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=canned_score):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1
        # dry-run _run_cell returns status="ok"; that must be preserved when scoring succeeds.
        assert rows[0]["status"] == "ok", (
            f"Expected status='ok' when both engineer and scoring succeed; "
            f"got {rows[0]['status']!r}"
        )


# ---------------------------------------------------------------------------
# MAJOR-3 regression: Tier3Docker.run_fix_phase invoked in production path
# ---------------------------------------------------------------------------


class TestTier3RunFixPhaseInvoked:
    """Regression suite for MAJOR-3.

    Verifies that Tier3Docker.run_fix_phase is called (NOT invoke_run directly)
    when tier3_mode='auto' and dry_run=False.  Mocks at the subprocess boundary
    (not at the Tier3Docker class level) to catch invocation-path bypasses.
    """

    _MINIMAL_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate_for_non_transactional_databases"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: >
      sqlmigrate wraps output in BEGIN/COMMIT even when the database does not
      support transactional DDL.
"""

    def test_run_fix_phase_called_not_invoke_run_when_tier3_auto(
        self, tmp_path: Path
    ):
        """run_fix_phase is called (not invoke_run directly) when tier3_mode='auto'.

        Regression test for MAJOR-3: previously _run_cell called invoke_run
        directly, bypassing run_fix_phase entirely so --network none, --cap-drop,
        --read-only rootfs, and memory limits were all bypassed.

        Mock strategy: we mock the Tier3Docker class that runner imports at
        runtime (via `from evals.runner.isolator import Tier3Docker as _Tier3Docker`).
        The mock class's run_fix_phase is tracked to verify it is called.
        We do NOT mock invoke_run - if run_fix_phase delegates to it internally
        that is fine; what matters is that run_fix_phase is the entry point used
        by the runner, not a raw invoke_run call bypassing the isolator.
        """
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        import json as _json, subprocess as _sp
        canned_invoker = {
            "final_text": "Fixed.",
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {},
            "latency_ms": 0,
            "invocation_mode": "agent",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
            "stderr_tail": "",
        }
        canned_cp = _sp.CompletedProcess(
            args=[], returncode=0,
            stdout=_json.dumps(canned_invoker), stderr="",
        )

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag="ae-eval-swebench:latest",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)

        run_fix_phase_calls: list = []

        def fake_run_fix_phase(ctx, **kwargs):
            run_fix_phase_calls.append({"ctx": ctx, "kwargs": kwargs})
            return canned_cp

        # The mock Tier3Docker class: instantiation returns mock_tier3_instance,
        # and the static run_fix_phase method is tracked.
        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.run_fix_phase = MagicMock(side_effect=fake_run_fix_phase)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),  # skip actual seeding
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        assert len(run_fix_phase_calls) == 1, (
            f"Tier3Docker.run_fix_phase must be called exactly once per cell when "
            f"tier3_mode='auto'; got {len(run_fix_phase_calls)} calls. "
            "MAJOR-3 regression: if this fails, invoke_run is being called directly, "
            "bypassing the Tier3 isolator entirely."
        )
        # The prompt kwarg must be populated (prompt path, not command path).
        assert "prompt" in run_fix_phase_calls[0]["kwargs"], (
            "run_fix_phase must be called with a prompt= kwarg (prompt path)"
        )
        assert run_fix_phase_calls[0]["kwargs"]["prompt"], (
            "prompt= kwarg must be non-empty"
        )

    def test_run_fix_phase_not_called_when_dry_run(
        self, tmp_path: Path
    ):
        """Tier3Docker.run_fix_phase is NOT called when dry_run=True."""
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Docker

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch.object(Tier3Docker, "run_fix_phase") as mock_rfp,
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        mock_rfp.assert_not_called()

    def test_run_fix_phase_not_called_when_tier3_off(
        self, tmp_path: Path
    ):
        """Tier3Docker.run_fix_phase is NOT called when tier3_mode='off'."""
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Docker

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("runner._run_cell", return_value={
                "final_text": "", "status": "ok", "cost_usd": 0.0, "usage": {},
                "latency_ms": 0, "invocation_mode": "agent", "tool_calls": [],
                "turns_used": 1, "_parse_warnings": [],
            }),
            patch.object(Tier3Docker, "run_fix_phase") as mock_rfp,
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        mock_rfp.assert_not_called()


# ---------------------------------------------------------------------------
# MAJOR-2 regression: seed_error rows excluded from aggregator median
# ---------------------------------------------------------------------------


class TestSeedErrorAggregatorExclusion:
    """Regression suite for MAJOR-2.

    seed_error rows must write score_primary="" (empty string) so the
    aggregator's _non_none filter discards them.  A 0.0 value would inflate
    apparent failure rates and skew the median.
    """

    def test_seed_error_row_writes_empty_score_primary(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When seeding fails, the TSV row has score_primary='' (empty string).

        Regression test for MAJOR-2: previously score_primary=0.0 was written
        for seed_error rows, which the aggregator would silently include in
        median calculations, inflating apparent failure rates.
        """
        from seeding import SeedError
        results_tsv = tmp_path / "results.tsv"

        def raise_seed_error(**kwargs):
            raise SeedError(step="clone_failed", stderr="git error")

        with patch("runner.seed_fix_phase", side_effect=raise_seed_error):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1
        assert rows[0]["status"] == "seed_error"
        assert rows[0]["score_primary"] == "", (
            f"seed_error rows must write score_primary='' (empty string) so the "
            f"aggregator excludes them from median; got {rows[0]['score_primary']!r}. "
            "MAJOR-2 regression: 0.0 was written before this fix."
        )

    def test_aggregator_excludes_empty_score_primary_from_median(self):
        """aggregate_conditions treats empty-string scores as None (excluded from median).

        Regression test for MAJOR-2 (aggregator side): seed_error rows in the
        TSV have score_primary=''; when the TSV is parsed and fed to the
        aggregator, those empty strings must be excluded from the median.
        """
        from aggregate import aggregate_conditions

        # Simulate TSV parsing: score_primary is a string after csv.DictReader.
        # A mix of real scores and seed_error empties.
        runs = {
            "baseline": ["1.0", "0.8", "", "0.6", ""],  # 2 seed_error empties
        }
        rows = aggregate_conditions(runs)
        assert len(rows) == 1
        row = rows[0]
        # Only 3 valid scores: [1.0, 0.8, 0.6]. median = 0.8
        assert row.n == 3, (
            f"aggregate_conditions must count only non-empty scores; "
            f"expected n=3, got n={row.n}. "
            "MAJOR-2 regression: empty-string seed_error rows were being counted."
        )
        import statistics
        assert row.median == statistics.median([1.0, 0.8, 0.6]), (
            f"Median must be computed from valid scores only; "
            f"expected {statistics.median([1.0, 0.8, 0.6])}, got {row.median}"
        )


# ---------------------------------------------------------------------------
# --tasks / tasks_filter and --max-cells tests
# ---------------------------------------------------------------------------

# Corpus with two tasks so we can verify slug-based filtering.
_TWO_TASK_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate_for_non_transactional_databases"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: Bug in sqlmigrate.
  requests-3362:
    swebench_instance_id: "psf__requests-3362"
    repo_url: "https://github.com/psf/requests"
    base_commit: "abc000"
    held_out_tests:
      - "tests/test_utils.py"
    fail_to_pass:
      - "test_something"
    estimated_test_seconds: 10
    difficulty: single-file
    known_affected_files:
      - "requests/utils.py"
    problem_summary: Bug in requests utils.
"""


@pytest.fixture
def two_task_corpus_yaml(tmp_path: Path) -> Path:
    """Write a two-task corpus YAML to tmp_path."""
    p = tmp_path / "corpus.yaml"
    p.write_text(_TWO_TASK_CORPUS_YAML, encoding="utf-8")
    return p


def _canned_score():
    from scoring import ScoringResult
    return ScoringResult(
        pass_fail=True,
        score_primary=1.0,
        lines_touched=1,
        files_touched=1,
        scope_creep_flag=False,
    )


class TestTasksFilter:
    """Tests for the tasks_filter parameter (--tasks CLI flag)."""

    def test_single_slug_filter_runs_only_that_task(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """When tasks_filter=['requests-3362'], only that task's cells appear in TSV."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tasks_filter=["requests-3362"],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1, (
            f"Only 1 row expected (requests-3362 x baseline x n=1); got {len(rows)}"
        )
        assert rows[0]["task_slug"] == "requests-3362"
        assert report.rows_written == 1

    def test_empty_tasks_filter_runs_all(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """When tasks_filter=[] (empty list), all tasks run (same as None)."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tasks_filter=None,  # same as absent
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"Both tasks should run when tasks_filter=None; got {len(rows)}"
        )

    def test_empty_list_tasks_filter_runs_all(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """When tasks_filter=[] (empty list), all tasks run (same as None)."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tasks_filter=[],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"Both tasks should run when tasks_filter=[]; got {len(rows)}"
        )

    def test_unknown_slug_raises_before_any_cell(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """An unknown task slug raises ValueError before any cell executes."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            with pytest.raises(ValueError, match="Unknown task slug"):
                run_matrix(
                    tasks_yaml=two_task_corpus_yaml,
                    results_tsv=results_tsv,
                    n_replicates=1,
                    n_replicates_methodology=1,
                    dry_run=True,
                    conditions=["baseline"],
                    tasks_filter=["does-not-exist"],
                )

        # No rows should have been written.
        rows = _read_tsv(results_tsv)
        assert len(rows) == 0, "No rows must be written when slug validation fails"

    def test_multiple_slugs_filter(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """tasks_filter with multiple valid slugs runs exactly those tasks."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tasks_filter=["django-11039", "requests-3362"],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2
        slugs_seen = {r["task_slug"] for r in rows}
        assert slugs_seen == {"django-11039", "requests-3362"}


class TestMaxCells:
    """Tests for the max_cells parameter (--max-cells CLI flag)."""

    def test_max_cells_1_stops_after_one_row(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """max_cells=1 stops after writing one row and sets partial=True."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=2,
                n_replicates_methodology=2,
                dry_run=True,
                conditions=["baseline"],
                max_cells=1,
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1, (
            f"max_cells=1 must stop after exactly 1 row; got {len(rows)}"
        )
        assert report.partial is True, "partial must be True when max_cells is reached"
        assert report.rows_written == 1

    def test_max_cells_resume_respects_ceiling(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """Second invocation with max_cells=1 stops after writing 1 new row
        even when prior rows exist in the TSV."""
        results_tsv = tmp_path / "results.tsv"

        # First run: write 1 row (django-11039 baseline rep1).
        with patch("runner.score_cell", return_value=_canned_score()):
            run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tasks_filter=["django-11039"],
            )

        assert len(_read_tsv(results_tsv)) == 1

        # Second run: force=True so the first row is not counted as
        # completed; max_cells=1 means only 1 more row should be written.
        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline", "engineer-direct"],
                tasks_filter=["django-11039"],
                max_cells=1,
                force=True,
            )

        # The TSV now has the original row plus 1 new row.
        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"Expected 2 total rows (1 prior + 1 new from max_cells=1); got {len(rows)}"
        )
        assert report.rows_written == 1
        assert report.partial is True

    def test_max_cells_none_runs_all(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """max_cells=None (default) does not truncate the run."""
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                max_cells=None,
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, "Both tasks should run when max_cells=None"
        assert report.partial is False

    def test_tasks_filter_and_max_cells_additive(
        self, tmp_path: Path, two_task_corpus_yaml: Path
    ):
        """tasks_filter limits the task set; max_cells limits total rows written.
        The more restrictive wins per cell iteration."""
        results_tsv = tmp_path / "results.tsv"

        # tasks_filter=['requests-3362'] with n=3 replicates and 2 conditions
        # would produce 6 rows. max_cells=2 cuts to 2.
        with patch("runner.score_cell", return_value=_canned_score()):
            report = run_matrix(
                tasks_yaml=two_task_corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=3,
                n_replicates_methodology=3,
                dry_run=True,
                conditions=["baseline", "engineer-direct"],
                tasks_filter=["requests-3362"],
                max_cells=2,
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, (
            f"tasks_filter + max_cells=2 should yield exactly 2 rows; got {len(rows)}"
        )
        # All rows must be from the filtered task.
        for row in rows:
            assert row["task_slug"] == "requests-3362"
        assert report.partial is True


# ---------------------------------------------------------------------------
# Bug-1 regression: --rebuild-image invalidates the image digest cache
# ---------------------------------------------------------------------------


class TestRebuildImage:
    """Regression suite for Bug-1 (--rebuild-image flag).

    Verifies that rebuild_image=True evicts the cached digest from
    _IMAGE_DIGEST_CACHE before ensure_image() is called, forcing a fresh
    docker build on the next invocation.
    """

    def test_rebuild_image_evicts_cache_entry(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """rebuild_image=True removes the cached digest before ensure_image().

        Regression test for Bug-1: previously the cache was never invalidated,
        so a stale ae-eval-swebench:latest image (missing pytest-timeout) would
        be reused silently even after Dockerfile.swebench changed.
        """
        from evals.runner.isolator import _IMAGE_DIGEST_CACHE, _DOCKER_IMAGE_TAG
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        # Pre-populate the cache with a fake digest to simulate a stale image.
        _IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = "sha256:stale_digest_before_rebuild"

        ensure_image_calls: list[dict] = []

        # Capture whether the cache was empty at ensure_image() call time.
        original_ensure_image = None

        def fake_ensure_image(image_tag=_DOCKER_IMAGE_TAG, **kwargs):
            ensure_image_calls.append({
                "image_tag": image_tag,
                "cache_had_entry": image_tag in _IMAGE_DIGEST_CACHE,
            })
            # Simulate ensure_image caching the new digest.
            _IMAGE_DIGEST_CACHE[image_tag] = "sha256:fresh_digest_after_rebuild"
            return "sha256:fresh_digest_after_rebuild"

        mock_tier3_ctx_enter = MagicMock()
        from evals.runner.isolator import Tier3Context
        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag=_DOCKER_IMAGE_TAG,
            image_digest="sha256:fresh_digest_after_rebuild",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)
        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.ensure_image = MagicMock(side_effect=fake_ensure_image)
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=MagicMock(
            returncode=0,
            stdout='{"final_text":"ok","status":"ok","cost_usd":0.0,"usage":{},'
                   '"latency_ms":0,"invocation_mode":"agent","tool_calls":[],'
                   '"turns_used":1,"_parse_warnings":[]}',
            stderr="",
        ))

        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
                rebuild_image=True,
            )

        assert len(ensure_image_calls) == 1, (
            "ensure_image must be called exactly once in production path"
        )
        assert not ensure_image_calls[0]["cache_had_entry"], (
            "rebuild_image=True must evict the cache entry BEFORE ensure_image() "
            "is called. Cache still had the stale entry when ensure_image() ran - "
            "Bug-1 regression: stale image would be reused without rebuilding."
        )
        # Restore cache to clean state.
        _IMAGE_DIGEST_CACHE.pop(_DOCKER_IMAGE_TAG, None)

    def test_rebuild_image_false_preserves_cache(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """rebuild_image=False (default) does NOT evict the cache entry."""
        from evals.runner.isolator import _IMAGE_DIGEST_CACHE, _DOCKER_IMAGE_TAG
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        # Pre-populate the cache.
        _IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = "sha256:existing_digest"

        ensure_image_calls: list[dict] = []

        def fake_ensure_image(image_tag=_DOCKER_IMAGE_TAG, **kwargs):
            ensure_image_calls.append({
                "image_tag": image_tag,
                "cache_had_entry": image_tag in _IMAGE_DIGEST_CACHE,
            })
            return _IMAGE_DIGEST_CACHE.get(image_tag, "sha256:existing_digest")

        from evals.runner.isolator import Tier3Context
        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag=_DOCKER_IMAGE_TAG,
            image_digest="sha256:existing_digest",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)
        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.ensure_image = MagicMock(side_effect=fake_ensure_image)
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=MagicMock(
            returncode=0,
            stdout='{"final_text":"ok","status":"ok","cost_usd":0.0,"usage":{},'
                   '"latency_ms":0,"invocation_mode":"agent","tool_calls":[],'
                   '"turns_used":1,"_parse_warnings":[]}',
            stderr="",
        ))

        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
                rebuild_image=False,  # default - do not evict
            )

        assert len(ensure_image_calls) == 1
        assert ensure_image_calls[0]["cache_had_entry"], (
            "rebuild_image=False must NOT evict the cache; the cached entry "
            "should still be present when ensure_image() is called."
        )
        # Restore cache.
        _IMAGE_DIGEST_CACHE.pop(_DOCKER_IMAGE_TAG, None)

    def test_rebuild_image_no_effect_when_dry_run(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """rebuild_image=True is a no-op when dry_run=True (no Tier3 used)."""
        from evals.runner.isolator import _IMAGE_DIGEST_CACHE, _DOCKER_IMAGE_TAG
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        _IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = "sha256:should_not_be_evicted"

        mock_tier3_cls = MagicMock()
        results_tsv = tmp_path / "results.tsv"

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tier3_mode="auto",
                rebuild_image=True,  # ignored because dry_run=True
            )

        # Cache entry must not have been evicted (use_tier3 is False for dry_run).
        assert _IMAGE_DIGEST_CACHE.get(_DOCKER_IMAGE_TAG) == "sha256:should_not_be_evicted", (
            "rebuild_image=True must have no effect when dry_run=True "
            "(Tier3 is not used in dry-run mode)."
        )
        assert not mock_tier3_cls.called, "Tier3Docker must not be instantiated in dry-run"
        # Restore.
        _IMAGE_DIGEST_CACHE.pop(_DOCKER_IMAGE_TAG, None)


# ---------------------------------------------------------------------------
# Bug-2 regression: engineer transcripts persisted on every cell
# ---------------------------------------------------------------------------


class TestTranscriptPersistence:
    """Regression suite for Bug-2 (engineer transcript persistence).

    Verifies that the engineer CLI stdout+stderr is persisted to
    <results_tsv_dir>/transcripts/<task_slug>__<condition>__rep<N>.log on
    every cell, and that cli_exit_* status rows include the transcript path
    in diagnostics_json.
    """

    def test_transcript_file_created_for_dry_run_cell(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """A transcript file is created for each cell even in dry-run mode."""
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        with patch("runner.score_cell", return_value=canned_score):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        transcript_dir = tmp_path / "transcripts"
        assert transcript_dir.exists(), "transcripts/ directory must be created"
        transcript_file = transcript_dir / "django-11039__baseline__rep1.log"
        assert transcript_file.exists(), (
            f"Transcript file must be created at {transcript_file}; "
            "Bug-2 regression: transcript was not persisted."
        )

    def test_transcript_path_in_diagnostics_on_cli_exit(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """On cli_exit_1, diagnostics_json includes cli_exit_transcript path.

        Regression test for Bug-2: the transcript path was not recorded in
        diagnostics_json, making post-mortem impossible without knowing the
        file naming convention.
        """
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context

        canned_score = ScoringResult(
            pass_fail=False, score_primary=0.0,
            lines_touched=0, files_touched=0, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        # Produce a cli_exit_1 result from run_fix_phase.
        import json as _json
        import subprocess as _sp

        canned_invoker_fail = {
            "final_text": "Error: some CLI failure output",
            "status": "cli_exit_1",
            "cost_usd": 0.0,
            "usage": {"input_tokens": 26, "output_tokens": 0},
            "latency_ms": 100,
            "invocation_mode": "tier3",
            "tool_calls": [],
            "turns_used": 0,
            "_parse_warnings": [],
            "stderr_tail": "fatal: not a git repository",
        }
        canned_cp = _sp.CompletedProcess(
            args=[], returncode=1,
            stdout=_json.dumps(canned_invoker_fail), stderr="",
        )

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag="ae-eval-swebench:latest",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)
        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.ensure_image = MagicMock(return_value="sha256:abc123")
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=canned_cp)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1
        assert rows[0]["status"] == "cli_exit_1", (
            f"Expected status='cli_exit_1', got {rows[0]['status']!r}"
        )

        diagnostics = _json.loads(rows[0]["diagnostics_json"])
        assert "cli_exit_transcript" in diagnostics, (
            "diagnostics_json must include 'cli_exit_transcript' key on cli_exit_* rows. "
            "Bug-2 regression: transcript path was not recorded in diagnostics."
        )
        assert "transcript_path" in diagnostics, (
            "diagnostics_json must include 'transcript_path' for every cell."
        )

        # The transcript file must actually exist.
        transcript_path = Path(diagnostics["cli_exit_transcript"])
        assert transcript_path.exists(), (
            f"Transcript file {transcript_path} must exist after cli_exit_1. "
            "Bug-2 regression: transcript was not written to disk."
        )
        content = transcript_path.read_text(encoding="utf-8")
        assert "Error: some CLI failure output" in content, (
            "Transcript file must contain the engineer's stdout output."
        )
        assert "fatal: not a git repository" in content, (
            "Transcript file must contain the stderr_tail."
        )

    def test_transcript_stderr_tail_printed_to_stderr_on_cli_exit(
        self, tmp_path: Path, corpus_yaml: Path, capsys
    ):
        """On cli_exit_*, the last 500 chars of transcript are printed to stderr."""
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context

        canned_score = ScoringResult(
            pass_fail=False, score_primary=0.0,
            lines_touched=0, files_touched=0, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        import json as _json, subprocess as _sp

        long_output = "X" * 600
        canned_invoker_fail = {
            "final_text": long_output,
            "status": "cli_exit_1",
            "cost_usd": 0.0,
            "usage": {},
            "latency_ms": 0,
            "invocation_mode": "tier3",
            "tool_calls": [],
            "turns_used": 0,
            "_parse_warnings": [],
        }
        canned_cp = _sp.CompletedProcess(
            args=[], returncode=1,
            stdout=_json.dumps(canned_invoker_fail), stderr="",
        )

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "held",
            image_tag="ae-eval-swebench:latest",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)
        (tmp_path / "held").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)
        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.ensure_image = MagicMock(return_value="sha256:abc123")
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=canned_cp)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        captured = capsys.readouterr()
        assert "[cli_exit]" in captured.err, (
            "On cli_exit_1, last 500 chars must be printed to stderr for "
            "quick post-mortem. Bug-2 regression: nothing was printed."
        )
        # The tail (last 500 chars of a 600-char string) should appear.
        assert "X" * 500 in captured.err, (
            "The last 500 chars of the transcript must appear in stderr output."
        )


# ---------------------------------------------------------------------------
# smoke-bugs-r2 regression: transcript file must be non-empty (Bug 1)
# ---------------------------------------------------------------------------


class TestTranscriptFileNonEmpty:
    """Regression for smoke-bugs-r2 Bug 1: transcript file was 0 bytes.

    Previously runner.py wrote `final_text` to the transcript file.
    `final_text` is parsed from stream-json events and may be empty when
    the run produced only tool-use events (no assistant text blocks).
    `cli_stdout` is the raw pipe capture and is always populated when the
    CLI ran; the fix uses cli_stdout for transcript persistence.
    """

    def test_transcript_file_non_empty_when_cli_produces_output(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """Transcript file must contain cli_stdout content, not just final_text."""
        from scoring import ScoringResult

        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=False, score_primary=0.0,
            lines_touched=0, files_touched=0, scope_creep_flag=False,
        )

        # Simulate: cli_stdout is populated (raw pipe output), final_text is empty
        # (stream-json had tool-use events only, no assistant text).
        # This is the smoke v4 regression case: 693 output tokens but empty final_text.
        cli_stdout_content = (
            '{"type":"system","subtype":"init"}\n'
            '{"type":"assistant","message":{"role":"assistant","content":'
            '[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}\n'
            '{"type":"result","subtype":"success","total_cost_usd":0.01}\n'
        )
        canned_result = {
            "final_text": "",  # empty - the bug condition
            "cli_stdout": cli_stdout_content,  # populated - the fix
            "status": "ok",
            "cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 693},
            "latency_ms": 500,
            "invocation_mode": "dry-run-mock",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
        }

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._run_cell", return_value=canned_result),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        # The transcript directory is <results_tsv_dir>/transcripts/
        transcript_dir = results_tsv.parent / "transcripts"
        log_files = list(transcript_dir.glob("*.log"))
        assert log_files, "At least one transcript .log file must be written"
        transcript_path = log_files[0]
        content = transcript_path.read_text(encoding="utf-8")
        assert len(content) > 0, (
            f"Transcript file {transcript_path} is 0 bytes. "
            "runner.py must write cli_stdout to the transcript file, not final_text. "
            "final_text may be empty when the CLI run produced only tool-use events."
        )
        # Verify the raw cli_stdout content is present, not just stderr.
        assert '{"type":"system"' in content, (
            "cli_stdout stream-json content must appear in the transcript file. "
            f"Got: {content[:200]!r}"
        )

    def test_transcript_falls_back_to_final_text_when_cli_stdout_absent(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """When cli_stdout is absent from result, fall back to final_text gracefully."""
        from scoring import ScoringResult

        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=False, score_primary=0.0,
            lines_touched=0, files_touched=0, scope_creep_flag=False,
        )

        # Old-format result dict (no cli_stdout key) - backward compat test.
        canned_result = {
            "final_text": "Fixed the bug.\n```diff\n---\n```",
            # no cli_stdout key
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {"input_tokens": 50, "output_tokens": 20},
            "latency_ms": 100,
            "invocation_mode": "dry-run-mock",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
        }

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._run_cell", return_value=canned_result),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        transcript_dir = results_tsv.parent / "transcripts"
        log_files = list(transcript_dir.glob("*.log"))
        assert log_files, "Transcript .log file must be written"
        content = log_files[0].read_text(encoding="utf-8")
        assert len(content) > 0, (
            "Transcript file must be non-empty even when cli_stdout key is absent; "
            "final_text fallback must be used."
        )
        assert "Fixed the bug." in content


# ---------------------------------------------------------------------------
# smoke-v6 regression: fail_to_pass forwarded from task_meta to score_cell
# ---------------------------------------------------------------------------


class TestFailToPassForwarded:
    """Regression test for smoke-v6 bug: runner.run_matrix was not passing
    fail_to_pass from task_meta to score_cell, so _run_pytest_tier3 received
    fail_to_pass=None and collected 0 tests from the /scoring/tests directory.

    This test mocks score_cell at the boundary and inspects the captured kwargs
    to verify fail_to_pass is forwarded correctly.
    """

    def test_run_matrix_forwards_fail_to_pass_to_score_cell(
        self, tmp_path: Path, corpus_yaml: Path
    ):
        """run_matrix must pass task_meta['fail_to_pass'] to score_cell.

        Regression for smoke-v6: previously score_cell was called without the
        fail_to_pass kwarg, so pytest ran against the entire /scoring/tests tree
        and collected 0 tests (the tree had no tests at that path).
        """
        from scoring import ScoringResult

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        results_tsv = tmp_path / "results.tsv"

        captured_kwargs: list[dict] = []

        def capturing_score_cell(**kwargs):
            captured_kwargs.append(kwargs)
            return canned_score

        with patch("runner.score_cell", side_effect=capturing_score_cell):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        assert captured_kwargs, "score_cell must have been called"
        for call_kwargs in captured_kwargs:
            assert "fail_to_pass" in call_kwargs, (
                "score_cell must receive fail_to_pass kwarg; "
                "smoke-v6 showed it was missing, causing 0 tests collected."
            )
            # The corpus_yaml fixture has exactly one fail_to_pass entry.
            ftp = call_kwargs["fail_to_pass"]
            assert isinstance(ftp, list), (
                f"fail_to_pass must be a list, got {type(ftp)}"
            )
            assert len(ftp) == 1, (
                f"Expected 1 fail_to_pass entry (from fixture corpus), got {len(ftp)}: {ftp}"
            )

    def test_run_matrix_forwards_empty_fail_to_pass_when_absent(
        self, tmp_path: Path
    ):
        """When task_meta has no fail_to_pass key, score_cell receives an empty list."""
        from scoring import ScoringResult

        # Corpus with no fail_to_pass field.
        corpus_no_ftp = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: test task with no fail_to_pass
"""
        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(corpus_no_ftp, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        captured_kwargs: list[dict] = []

        def capturing_score_cell(**kwargs):
            captured_kwargs.append(kwargs)
            return canned_score

        with patch("runner.score_cell", side_effect=capturing_score_cell):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        assert captured_kwargs, "score_cell must have been called"
        for call_kwargs in captured_kwargs:
            ftp = call_kwargs.get("fail_to_pass")
            assert ftp == [] or ftp is None or ftp == [], (
                f"fail_to_pass must be [] when absent from task_meta, got {ftp!r}"
            )


# ---------------------------------------------------------------------------
# held-out-mount regression: held_out_from_fix_dir=True passed in production
# ---------------------------------------------------------------------------


class TestHeldOutFromFixDir:
    """Regression test for the held-out-mount bug.

    When no held_out_dir is passed to Tier3Docker, __enter__ used to create an
    empty tmpdir for /scoring/tests. pytest inside the score container found no
    tests and exited with 'file or directory not found'.

    Fix: runner passes held_out_from_fix_dir=True so Tier3Docker sets
    held_out_dir = fix_phase_dir at __enter__ time, where seed_fix_phase has
    placed the test files.
    """

    _MINIMAL_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate_for_non_transactional_databases"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: >
      sqlmigrate wraps output in BEGIN/COMMIT even when the database does not
      support transactional DDL.
"""

    def test_runner_passes_held_out_from_fix_dir_true_in_production(
        self, tmp_path: Path
    ):
        """run_matrix passes held_out_from_fix_dir=True when tier3_mode='auto'.

        Regression test for held-out-mount bug: previously Tier3Docker was
        instantiated without held_out_from_fix_dir, so __enter__ created an
        empty tmpdir for /scoring/tests - pytest found no tests and exited with
        'file or directory not found'. This test captures the kwargs passed to
        Tier3Docker.__init__ and asserts held_out_from_fix_dir=True is present.
        """
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context
        import json as _json, subprocess as _sp

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        canned_invoker = {
            "final_text": "Fixed.",
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {},
            "latency_ms": 0,
            "invocation_mode": "agent",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
            "stderr_tail": "",
        }
        canned_cp = _sp.CompletedProcess(
            args=[], returncode=0,
            stdout=_json.dumps(canned_invoker), stderr="",
        )

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "fix",  # same dir, as held_out_from_fix_dir would set
            image_tag="ae-eval-swebench:latest",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)

        captured_init_kwargs: list[dict] = []

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)

        def capturing_tier3_cls(*args, **kwargs):
            captured_init_kwargs.append(kwargs)
            return mock_tier3_instance

        mock_tier3_cls = MagicMock(side_effect=capturing_tier3_cls)
        mock_tier3_cls.ensure_image = MagicMock(return_value="sha256:abc123")
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=canned_cp)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        assert captured_init_kwargs, "Tier3Docker must have been instantiated"
        for kwargs in captured_init_kwargs:
            assert kwargs.get("held_out_from_fix_dir") is True, (
                f"Tier3Docker must be instantiated with held_out_from_fix_dir=True; "
                f"got kwargs={kwargs!r}. "
                "held-out-mount regression: without this flag, __enter__ creates an "
                "empty tmpdir for /scoring/tests and pytest finds no test files."
            )


# ---------------------------------------------------------------------------
# Per-task dockerfile routing
# ---------------------------------------------------------------------------


_CORPUS_WITH_CUSTOM_DOCKERFILE = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate_for_non_transactional_databases"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: Bug in sqlmigrate.
  astropy-12907:
    swebench_instance_id: "astropy__astropy-12907"
    repo_url: "https://github.com/astropy/astropy"
    base_commit: "d16bfe05a744909de4b27f5875fe0d4ed41ce607"
    held_out_tests:
      - "astropy/modeling/tests/test_separable.py"
    fail_to_pass:
      - "test_separable"
    estimated_test_seconds: 25
    difficulty: single-file
    known_affected_files:
      - "astropy/modeling/separable.py"
    problem_summary: Bug in separability.
    dockerfile: "Dockerfile.swebench-py310"
"""


class TestPerTaskDockerfileRouting:
    """Tests for per-task dockerfile selection and image_tag derivation."""

    def test_ensure_image_called_with_custom_dockerfile(self, tmp_path: Path):
        """Tasks with a custom dockerfile trigger ensure_image with the right params."""
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(_CORPUS_WITH_CUSTOM_DOCKERFILE, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        canned_cp = _make_completed_process(stdout="")

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "fix",
            image_tag="ae-eval-swebench:py310",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)

        ensure_image_calls: list[dict] = []

        def fake_ensure_image(*, image_tag, dockerfile, force_rebuild=False):
            ensure_image_calls.append({
                "image_tag": image_tag,
                "dockerfile_name": dockerfile.name,
                "force_rebuild": force_rebuild,
            })
            return "sha256:abc123"

        mock_tier3_cls = MagicMock(return_value=mock_tier3_instance)
        mock_tier3_cls.ensure_image = MagicMock(side_effect=fake_ensure_image)
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=canned_cp)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        # Two unique dockerfiles in the corpus -> two ensure_image calls.
        assert len(ensure_image_calls) == 2, (
            f"Expected 2 ensure_image calls (one per unique dockerfile), got {ensure_image_calls}"
        )

        tags = {c["image_tag"] for c in ensure_image_calls}
        assert tags == {"ae-eval-swebench:latest", "ae-eval-swebench:py310"}, (
            f"Expected both default and py310 tags; got {tags}"
        )

        # Verify the custom dockerfile call used the correct filename.
        py310_calls = [c for c in ensure_image_calls if c["image_tag"] == "ae-eval-swebench:py310"]
        assert len(py310_calls) == 1
        assert py310_calls[0]["dockerfile_name"] == "Dockerfile.swebench-py310"

    def test_tier3_init_uses_derived_image_tag(self, tmp_path: Path):
        """Per-cell Tier3Docker is instantiated with the task's derived image_tag."""
        from scoring import ScoringResult
        from evals.runner.isolator import Tier3Context

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(_CORPUS_WITH_CUSTOM_DOCKERFILE, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        canned_cp = _make_completed_process(stdout="")

        mock_ctx = Tier3Context(
            fix_phase_dir=tmp_path / "fix",
            held_out_dir=tmp_path / "fix",
            image_tag="ae-eval-swebench:py310",
            image_digest="sha256:abc123",
        )
        (tmp_path / "fix").mkdir(parents=True, exist_ok=True)

        captured_init_kwargs: list[dict] = []

        mock_tier3_instance = MagicMock()
        mock_tier3_instance.__enter__ = MagicMock(return_value=mock_ctx)
        mock_tier3_instance.__exit__ = MagicMock(return_value=None)

        def capturing_tier3_cls(*args, **kwargs):
            captured_init_kwargs.append(kwargs)
            return mock_tier3_instance

        mock_tier3_cls = MagicMock(side_effect=capturing_tier3_cls)
        mock_tier3_cls.ensure_image = MagicMock(return_value="sha256:abc123")
        mock_tier3_cls.run_fix_phase = MagicMock(return_value=canned_cp)

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase"),
            patch("evals.runner.isolator.Tier3Docker", mock_tier3_cls),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="auto",
                tasks_filter=["astropy-12907"],
            )

        assert len(captured_init_kwargs) == 1, (
            f"Expected 1 Tier3Docker init, got {len(captured_init_kwargs)}"
        )
        assert captured_init_kwargs[0].get("image_tag") == "ae-eval-swebench:py310", (
            f"astropy-12907 must use py310 image tag; got {captured_init_kwargs[0]}"
        )


# ---------------------------------------------------------------------------
# Post-seed command execution
# ---------------------------------------------------------------------------


class TestPostSeedCommands:
    """Tests for post_seed_commands execution and failure handling."""

    def test_post_seed_command_runs_after_seeding(self, tmp_path: Path):
        """post_seed_commands are executed after seed_fix_phase succeeds."""
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(_MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        # Inject a post_seed_commands into the task meta by patching _load_tasks
        modified_tasks = {
            "django-11039": {
                "swebench_instance_id": "django__django-11039",
                "repo_url": "https://github.com/django/django",
                "base_commit": "d5276398046ce4a102776a1e67dcac2884d80dfe",
                "held_out_tests": ["tests/migrations/test_commands.py"],
                "fail_to_pass": ["test_sqlmigrate_for_non_transactional_databases"],
                "estimated_test_seconds": 30,
                "difficulty": "single-file",
                "known_affected_files": ["django/core/management/commands/sqlmigrate.py"],
                "problem_summary": "Bug in sqlmigrate.",
                "post_seed_commands": ["echo 'post-seed-ok'"],
            }
        }

        run_commands: list[str] = []

        def fake_subprocess_run(cmd, *, shell=False, cwd=None, **kwargs):
            if shell and cmd == "echo 'post-seed-ok'":
                run_commands.append(cmd)
                return _make_completed_process(stdout="post-seed-ok\n")
            return _make_completed_process(stdout="")

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._load_tasks", return_value=modified_tasks),
            patch("subprocess.run", side_effect=fake_subprocess_run),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        assert run_commands == ["echo 'post-seed-ok'"], (
            f"post_seed_command must run after seeding; got {run_commands}"
        )

    def test_post_seed_command_failure_becomes_seed_error(self, tmp_path: Path):
        """If a post_seed_command fails, the cell records status='seed_error'."""
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(_MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        modified_tasks = {
            "django-11039": {
                "swebench_instance_id": "django__django-11039",
                "repo_url": "https://github.com/django/django",
                "base_commit": "d5276398046ce4a102776a1e67dcac2884d80dfe",
                "held_out_tests": ["tests/migrations/test_commands.py"],
                "fail_to_pass": ["test_sqlmigrate_for_non_transactional_databases"],
                "estimated_test_seconds": 30,
                "difficulty": "single-file",
                "known_affected_files": ["django/core/management/commands/sqlmigrate.py"],
                "problem_summary": "Bug in sqlmigrate.",
                "post_seed_commands": ["exit 1"],
            }
        }

        def fake_subprocess_run(cmd, *, shell=False, cwd=None, **kwargs):
            if shell and cmd == "exit 1":
                cp = _make_completed_process(stdout="")
                cp.returncode = 1
                cp.stderr = "intentional failure"
                return cp
            return _make_completed_process(stdout="")

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._load_tasks", return_value=modified_tasks),
            patch("subprocess.run", side_effect=fake_subprocess_run),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 1
        assert rows[0]["status"] == "seed_error", (
            f"Expected status='seed_error' when post_seed_command fails; got {rows[0]['status']!r}"
        )
        assert rows[0]["score_primary"] == "", (
            "seed_error rows must have empty score_primary"
        )

    def test_post_seed_commands_not_run_on_dry_run(self, tmp_path: Path):
        """post_seed_commands are skipped in dry_run mode."""
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(_MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        modified_tasks = {
            "django-11039": {
                "swebench_instance_id": "django__django-11039",
                "repo_url": "https://github.com/django/django",
                "base_commit": "d5276398046ce4a102776a1e67dcac2884d80dfe",
                "held_out_tests": ["tests/migrations/test_commands.py"],
                "fail_to_pass": ["test_sqlmigrate_for_non_transactional_databases"],
                "estimated_test_seconds": 30,
                "difficulty": "single-file",
                "known_affected_files": ["django/core/management/commands/sqlmigrate.py"],
                "problem_summary": "Bug in sqlmigrate.",
                "post_seed_commands": ["echo 'should-not-run'"],
            }
        }

        run_commands: list[str] = []

        def fake_subprocess_run(cmd, *, shell=False, cwd=None, **kwargs):
            if shell:
                run_commands.append(cmd)
            return _make_completed_process(stdout="")

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._load_tasks", return_value=modified_tasks),
            patch("subprocess.run", side_effect=fake_subprocess_run),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
                tier3_mode="auto",
            )

        assert run_commands == [], (
            f"post_seed_commands must NOT run in dry_run mode; got {run_commands}"
        )
