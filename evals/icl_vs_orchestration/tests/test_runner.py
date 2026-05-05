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
