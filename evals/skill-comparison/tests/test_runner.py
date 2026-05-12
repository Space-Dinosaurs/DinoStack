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
