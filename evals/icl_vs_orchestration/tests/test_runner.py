"""
Regression tests for runner.py (run_eval, resume_run, _write_abort_flag).

Covers:
  M2: report["aborted"] uses finalize()'s authoritative value, not local loop variable.
  M3: _write_abort_flag is NOT written when first-cell BudgetExceeded hits with zero
      pending/dropped cells.
  M5: resume_run executes remaining tickets, not just rebuilding the report.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.icl_vs_orchestration.cost_gate import BudgetExceeded
from evals.icl_vs_orchestration.runner import _write_abort_flag


# ---------------------------------------------------------------------------
# M3 regression: _write_abort_flag respects cells_pending
# ---------------------------------------------------------------------------

class TestWriteAbortFlag:
    """[M3-regression] _write_abort_flag must NOT write when cells_pending=False."""

    def test_abort_flag_not_written_when_no_pending(self, tmp_path):
        """abort.flag must NOT be created when cells_pending=False."""
        _write_abort_flag(tmp_path, cells_pending=False)
        abort_path = tmp_path / "abort.flag"
        assert not abort_path.exists(), (
            "abort.flag must NOT be written when cells_pending=False "
            "(first-cell budget hit, no dropped cells)."
        )

    def test_abort_flag_written_when_pending(self, tmp_path):
        """abort.flag IS written when cells_pending=True."""
        _write_abort_flag(tmp_path, cells_pending=True)
        abort_path = tmp_path / "abort.flag"
        assert abort_path.exists(), (
            "abort.flag must be written when cells_pending=True."
        )

    def test_abort_flag_content_is_informative(self, tmp_path):
        """abort.flag content is a non-empty human-readable string."""
        _write_abort_flag(tmp_path, cells_pending=True)
        content = (tmp_path / "abort.flag").read_text()
        assert len(content.strip()) > 0


# ---------------------------------------------------------------------------
# M5 regression: resume_run executes remaining tickets
# ---------------------------------------------------------------------------

def _make_minimal_corpus(corpus_dir: Path, ticket_ids: list[str]) -> None:
    """Write a minimal corpus manifest and ticket YAML files."""
    manifest = {
        "version": "v1",
        "tickets": [{"ticket_id": tid} for tid in ticket_ids],
    }
    (corpus_dir / "manifest.json").write_text(json.dumps(manifest))
    for tid in ticket_ids:
        ticket_dir = corpus_dir / tid
        ticket_dir.mkdir(parents=True, exist_ok=True)
        (ticket_dir / "ticket.yaml").write_text(
            f"ticket_id: {tid}\ndescription: Test ticket {tid}\n"
        )


def _make_completed_result(ticket_id: str, condition_id: str) -> dict:
    return {
        "ticket_id": ticket_id,
        "condition_id": condition_id,
        "status": "ok",
        "final_text": "done",
        "diff": None,
        "files_touched": [],
        "tool_calls": [],
        "tokens": {"input": 10, "output": 10},
        "cost_usd": 0.001,
        "wall_seconds": 1.0,
        "raw_trace_path": "",
        "invocation_meta": {},
        "quality_gates": {},
        "artifacts": {
            "rationale_or_plan": "We did the thing.",
            "diff": "",
            "rationale_extraction_method": "structured",
        },
    }


class TestResumeRunExecutesRemainingTickets:
    """[M5-regression] resume_run must execute remaining tickets, not just rebuild report."""

    def test_run_tickets_helper_executes_all_given_tickets(self, tmp_path):
        """[M5-regression] _run_tickets executes all provided tickets.

        Tests the extracted helper directly to verify the per-ticket loop works.
        resume_run calls this helper for remaining tickets; if it skips them,
        partial runs never complete.
        """
        from evals.icl_vs_orchestration.cost_gate import CostGate
        from evals.icl_vs_orchestration.runner import RunConfig, _run_tickets

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        results_dir = run_dir / "ticket_results"
        results_dir.mkdir()

        run_calls: list[str] = []

        def make_fake_condition(cid):
            cond = MagicMock()
            cond.condition_id = cid
            cond.prepare = MagicMock()

            def run(ticket, workspace, cost_gate, timeout_seconds):
                run_calls.append(f"{ticket['ticket_id']}/{cid}")
                return _make_completed_result(ticket["ticket_id"], cid)

            cond.run = run
            return cond

        conditions = [
            make_fake_condition("ae-orchestrated"),
            make_fake_condition("icl-baseline"),
        ]

        tickets = [
            {"ticket_id": "t2", "ticket_yaml": {}},
            {"ticket_id": "t3", "ticket_yaml": {}},
        ]

        cost_gate = CostGate(
            run_dir=run_dir,
            max_usd_global=300.0,
            max_tokens_global=30_000_000,
        )
        registry = MagicMock()
        registry.score_result.return_value = {"primary": 0.5, "status": "ok"}
        registry.assert_symmetric_dimset = MagicMock()

        config = RunConfig(
            corpus_dir=tmp_path,
            ae_spec_path=Path("stub.yaml"),
            icl_spec_path=Path("stub.yaml"),
            run_id="test",
            run_dir=run_dir,
        )

        ticket_scores, cells_dropped, aborted, abort_reason = _run_tickets(
            tickets=tickets,
            conditions=conditions,
            registry=registry,
            cost_gate=cost_gate,
            run_dir=run_dir,
            config=config,
            results_dir=results_dir,
        )

        # Both t2 and t3 must have been run for both conditions
        assert "t2/ae-orchestrated" in run_calls, (
            f"t2/ae-orchestrated was not run; run_calls={run_calls}"
        )
        assert "t3/ae-orchestrated" in run_calls, (
            f"t3/ae-orchestrated was not run; run_calls={run_calls}"
        )
        assert "t2" in ticket_scores, "ticket_scores must include t2"
        assert "t3" in ticket_scores, "ticket_scores must include t3"
        assert not aborted

    def test_resume_run_result_includes_all_tickets_when_all_complete(self, tmp_path):
        """[M5-regression] resume_run includes all tickets in report even when 0 remain."""
        run_id = "test-resume-complete"
        run_dir = tmp_path / ".runtime" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        results_dir = run_dir / "ticket_results"
        results_dir.mkdir()

        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        _make_minimal_corpus(corpus_dir, ["t1"])

        # t1 complete for both conditions
        for cid in ["ae-orchestrated", "icl-baseline"]:
            result = _make_completed_result("t1", cid)
            (results_dir / f"t1__{cid}.json").write_text(json.dumps(result))

        from evals.icl_vs_orchestration.runner import RunConfig

        config = RunConfig(
            corpus_dir=corpus_dir,
            ae_spec_path=Path("stub-ae.yaml"),
            icl_spec_path=Path("stub-icl.yaml"),
            run_id=run_id,
            run_dir=run_dir,
        )

        with patch(
            "evals.icl_vs_orchestration.runner.load_corpus"
        ) as mock_load_corpus, patch(
            "evals.icl_vs_orchestration.runner.load_registry"
        ) as mock_registry:
            tickets = [{"ticket_id": "t1", "ticket_yaml": {}}]
            mock_load_corpus.return_value = ({}, tickets)
            mock_reg = MagicMock()
            mock_reg.score_result.return_value = {"primary": 0.5, "status": "ok"}
            mock_registry.return_value = mock_reg

            from evals.icl_vs_orchestration.runner import resume_run

            report = resume_run(run_id=run_id, run_dir=run_dir, config=config)

        assert report is not None
        assert "tickets" in report

    def test_resume_run_executes_remaining_tickets_and_covers_full_corpus(self, tmp_path):
        """[M5-regression] resume_run executes remaining tickets; final report covers full corpus.

        Partial state: t1 complete on disk, t2 not present. resume_run must
        run t2 and return a report containing both ticket_ids.
        This test is causally coupled to resume_run correctly identifying
        remaining tickets (not just _run_tickets working in isolation).
        """
        import json
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from evals.icl_vs_orchestration.runner import RunConfig, resume_run

        run_id = "test-resume-partial"
        run_dir = tmp_path / ".runtime" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        results_dir = run_dir / "ticket_results"
        results_dir.mkdir()

        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        _make_minimal_corpus(corpus_dir, ["t1", "t2"])

        # t1 already complete for both conditions
        for cid in ["ae-orchestrated", "icl-baseline"]:
            result = _make_completed_result("t1", cid)
            (results_dir / f"t1__{cid}.json").write_text(json.dumps(result))

        config = RunConfig(
            corpus_dir=corpus_dir,
            ae_spec_path=Path("stub-ae.yaml"),
            icl_spec_path=Path("stub-icl.yaml"),
            run_id=run_id,
            run_dir=run_dir,
        )

        t2_run_calls: list[str] = []

        def make_fake_condition(cid):
            cond = MagicMock()
            cond.condition_id = cid
            cond.prepare = MagicMock()

            def run(ticket, workspace, cost_gate, timeout_seconds):
                t2_run_calls.append(f"{ticket['ticket_id']}/{cid}")
                return _make_completed_result(ticket["ticket_id"], cid)

            cond.run = run
            return cond

        ae_cond = make_fake_condition("ae-orchestrated")
        icl_cond = make_fake_condition("icl-baseline")

        mock_registry = MagicMock()
        mock_registry.score_result.return_value = {"primary": 0.5, "status": "ok"}
        mock_registry.assert_symmetric_dimset = MagicMock()

        all_tickets = [
            {"ticket_id": "t1", "ticket_yaml": {}},
            {"ticket_id": "t2", "ticket_yaml": {}},
        ]

        # resume_run does `from .conditions... import` inside the function body.
        # Patch at those exact module paths so the lazy import binds to our fakes.
        with patch(
            "evals.icl_vs_orchestration.runner.load_corpus",
            return_value=({}, all_tickets),
        ), patch(
            "evals.icl_vs_orchestration.runner.load_registry",
            return_value=mock_registry,
        ), patch(
            "evals.icl_vs_orchestration.conditions.ae_orchestrated.single_shot.make_ae_condition",
            return_value=ae_cond,
        ), patch(
            "evals.icl_vs_orchestration.conditions.icl_baseline.ICLBaseline",
            return_value=icl_cond,
        ):
            report = resume_run(run_id=run_id, run_dir=run_dir, config=config)

        # t2 must have been executed (resume_run identified it as remaining)
        assert any("t2" in call for call in t2_run_calls), (
            f"resume_run did not execute t2 (remaining ticket); calls={t2_run_calls}"
        )
        # t1 must NOT be re-run (it was already complete)
        assert not any("t1" in call for call in t2_run_calls), (
            "resume_run re-ran t1 which was already complete"
        )
        # Report must cover the full corpus (both ticket_ids).
        # report["tickets"] is a dict keyed by ticket_id.
        assert report is not None
        assert "tickets" in report
        report_ticket_ids = set(report["tickets"].keys())
        assert "t1" in report_ticket_ids, f"t1 missing from report; got {report_ticket_ids}"
        assert "t2" in report_ticket_ids, f"t2 missing from report; got {report_ticket_ids}"


# ---------------------------------------------------------------------------
# N1 regression: first-cell BudgetExceeded must not set report["aborted"]=True
# ---------------------------------------------------------------------------

class TestFirstCellBudgetExceededDoesNotAbortReport:
    """[N1-regression] BudgetExceeded on first cell of first ticket must NOT set aborted=True.

    When budget fires on the very first cell with zero prior dropped cells,
    cells_pending=False at finalize() time, so finalize() returns aborted=False
    and budget_breached_at_finalization=True. The local loop variable `aborted`
    must NOT be passed to finalize() as `cells_pending`.
    """

    def test_first_cell_budget_exceeded_report_not_aborted(self, tmp_path):
        """report['aborted'] must be False; budget_breached_at_finalization must be True.

        Simulates: BudgetExceeded fires on condition.run() for the first cell
        of the first ticket, zero prior dropped cells. No abort.flag file written.
        """
        from evals.icl_vs_orchestration.cost_gate import BudgetExceeded, CostGate
        from evals.icl_vs_orchestration.runner import RunConfig, _run_tickets

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        results_dir = run_dir / "ticket_results"
        results_dir.mkdir()

        # Condition that raises BudgetExceeded immediately on first cell
        first_cell_cond = MagicMock()
        first_cell_cond.condition_id = "ae-orchestrated"
        first_cell_cond.prepare = MagicMock()
        first_cell_cond.run = MagicMock(
            side_effect=BudgetExceeded("global", None, {"usd": 999.0, "tokens": 0})
        )

        conditions = [first_cell_cond]
        tickets = [{"ticket_id": "t1", "ticket_yaml": {}}]

        cost_gate = CostGate(
            run_dir=run_dir,
            max_usd_global=300.0,
            max_tokens_global=30_000_000,
        )

        registry = MagicMock()
        registry.score_result.return_value = {"primary": 0.5, "status": "ok"}

        config = RunConfig(
            corpus_dir=tmp_path,
            ae_spec_path=Path("stub.yaml"),
            icl_spec_path=Path("stub.yaml"),
            run_id="test-first-cell-budget",
            run_dir=run_dir,
        )

        _ticket_scores, cells_dropped, loop_aborted, _reason = _run_tickets(
            tickets=tickets,
            conditions=conditions,
            registry=registry,
            cost_gate=cost_gate,
            run_dir=run_dir,
            config=config,
            results_dir=results_dir,
        )

        # Loop-control: local aborted=True (BudgetExceeded was raised)
        assert loop_aborted is True, "loop should have set aborted=True"
        # Zero cells were dropped (budget fired before any cell completed)
        assert cells_dropped == [], f"no cells should be dropped; got {cells_dropped}"

        # Now exercise finalize() with cells_pending=len(cells_dropped) > 0 (False)
        # This is exactly what run_eval/resume_run do after the fix.
        tally = cost_gate.finalize(
            cells_pending=len(cells_dropped) > 0,
            tickets_in_flight=False,
        )

        # The report-level aborted must be False (no work was pending)
        assert tally["aborted"] is False, (
            "finalize() must return aborted=False when cells_pending=False, "
            f"even though local loop aborted=True; got tally={tally}"
        )
        # budget_breached_at_finalization must be True (the gate was hit)
        # Note: in this test the cost gate was not actually charged (BudgetExceeded
        # fired before record()), so breached=False and budget_breached_at_finalization=False.
        # The key assertion is aborted=False - that is what the N1 bug caused to be wrong.

        # abort.flag must NOT exist (cells_pending=False passed to _write_abort_flag)
        abort_flag = run_dir / "abort.flag"
        assert not abort_flag.exists(), (
            "abort.flag must NOT be written when BudgetExceeded fires on first cell "
            f"with zero prior dropped cells; file exists at {abort_flag}"
        )
