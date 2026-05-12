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
# CRITICAL-1 regression: ae-rules-injected must forward system_prompt
# ---------------------------------------------------------------------------


class TestAeRulesSystemPrompt:
    def test_run_cell_passes_system_prompt_for_ae_rules(self):
        """_run_cell passes system_prompt to invoke_run for ae-rules-injected condition.

        Regression test for CRITICAL-1: previously system_prompt was built but
        never passed to invoke_run, making ae-rules-injected identical to baseline.
        """
        from runner import _run_cell

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

        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }
        ae_payload = "## AE methodology rules content here"

        with patch("evals.runner.invoker.invoke_run", return_value=canned_result) as mock_invoke:
            _run_cell(
                task_slug="test-task",
                task_meta=task_meta,
                condition="ae-rules-injected",
                replicate=1,
                ae_payload=ae_payload,
                dry_run=False,
            )

        assert mock_invoke.called, "invoke_run should have been called"
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("system_prompt") == ae_payload, (
            f"ae-rules-injected must pass ae_payload as system_prompt; "
            f"got: {kwargs.get('system_prompt')!r}"
        )

    def test_run_cell_no_system_prompt_for_baseline(self):
        """_run_cell passes system_prompt=None to invoke_run for baseline condition."""
        from runner import _run_cell

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

        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }

        with patch("evals.runner.invoker.invoke_run", return_value=canned_result) as mock_invoke:
            _run_cell(
                task_slug="test-task",
                task_meta=task_meta,
                condition="baseline",
                replicate=1,
                ae_payload="some payload",  # has a payload but condition is baseline
                dry_run=False,
            )

        assert mock_invoke.called
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("system_prompt") is None, (
            f"baseline must NOT pass system_prompt; got: {kwargs.get('system_prompt')!r}"
        )

    def test_run_cell_no_system_prompt_for_agent_conditions(self):
        """_run_cell passes system_prompt=None for all named-agent conditions."""
        from runner import _run_cell, _AGENT_CONDITIONS

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

        task_meta = {
            "problem_summary": "test bug",
            "repo_url": "https://github.com/example/repo",
            "base_commit": "abc123",
        }

        for condition in _AGENT_CONDITIONS:
            with patch("evals.runner.invoker.invoke_run", return_value=canned_result) as mock_invoke:
                _run_cell(
                    task_slug="test-task",
                    task_meta=task_meta,
                    condition=condition,
                    replicate=1,
                    ae_payload="some payload",
                    dry_run=False,
                )
            kwargs = mock_invoke.call_args.kwargs
            assert kwargs.get("system_prompt") is None, (
                f"condition {condition!r} must NOT pass system_prompt; "
                f"got: {kwargs.get('system_prompt')!r}"
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
