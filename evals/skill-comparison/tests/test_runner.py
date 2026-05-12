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
        """Running twice in a row appends rows, doesn't overwrite."""
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
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        rows = _read_tsv(results_tsv)
        assert len(rows) == 2, "Second run should append, not overwrite"

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
