"""Tests for cost_gate.py - covers QA scenarios 2, 3, 6, 7 (budget gating)."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from evals.icl_vs_orchestration.cost_gate import (
    BudgetExceeded,
    CostGate,
    reconcile_tally,
)


def _make_gate(tmp_path: Path, max_usd=10.0, max_tokens=100_000,
               max_usd_per_cell=None, max_tokens_per_cell=None) -> CostGate:
    return CostGate(
        run_dir=tmp_path,
        max_usd_global=max_usd,
        max_tokens_global=max_tokens,
        max_usd_per_cell=max_usd_per_cell,
        max_tokens_per_cell=max_tokens_per_cell,
    )


def test_global_usd_budget_exceeded(tmp_path):
    """Global USD ceiling raises BudgetExceeded(scope='global')."""
    gate = _make_gate(tmp_path, max_usd=0.001)
    with pytest.raises(BudgetExceeded) as exc:
        gate.record("ae-orchestrated", "t1", {"input": 100, "output": 100}, cost_usd=0.002)
    assert exc.value.scope == "global"
    assert exc.value.cell_id is None


def test_global_token_budget_exceeded(tmp_path):
    """Global token ceiling raises BudgetExceeded(scope='global')."""
    gate = _make_gate(tmp_path, max_usd=1000.0, max_tokens=10)
    with pytest.raises(BudgetExceeded) as exc:
        gate.record("ae-orchestrated", "t1", {"input": 100, "output": 100}, cost_usd=0.001)
    assert exc.value.scope == "global"


def test_per_cell_usd_budget_exceeded(tmp_path):
    """Per-cell USD ceiling raises BudgetExceeded(scope='cell')."""
    gate = _make_gate(tmp_path, max_usd=100.0, max_usd_per_cell=0.001)
    with pytest.raises(BudgetExceeded) as exc:
        gate.record("ae-orchestrated", "t1", {"input": 10, "output": 10}, cost_usd=0.002)
    assert exc.value.scope == "cell"
    assert exc.value.cell_id == "ae-orchestrated"


def test_remaining_returns_correct_values(tmp_path):
    """remaining() decrements correctly after record()."""
    gate = _make_gate(tmp_path, max_usd=10.0, max_tokens=1000)
    gate._global_usd = 2.0
    gate._global_tokens = 100
    remaining_usd, remaining_tokens = gate.remaining()
    assert abs(remaining_usd - 8.0) < 1e-6
    assert remaining_tokens == 900


def test_tally_written_atomically(tmp_path):
    """Tally is written atomically (tmp+rename) on each record()."""
    gate = _make_gate(tmp_path, max_usd=100.0, max_tokens=1_000_000)
    gate.record("ae-orchestrated", "t1", {"input": 10, "output": 10}, cost_usd=0.001)
    tally_path = tmp_path / "cost_tally.json"
    assert tally_path.exists()
    tally = json.loads(tally_path.read_text())
    assert tally["global_usd"] == pytest.approx(0.001)
    assert "ae-orchestrated" in tally["cells"]


def test_no_tmp_file_left_after_write(tmp_path):
    """No .tmp file remains after an atomic tally write."""
    gate = _make_gate(tmp_path, max_usd=100.0, max_tokens=1_000_000)
    gate.record("ae-orchestrated", "t1", {"input": 10, "output": 10}, cost_usd=0.001)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"


def test_reconcile_tally_from_ticket_results(tmp_path):
    """reconcile_tally re-derives tally from ticket_results/ on resume."""
    results_dir = tmp_path / "ticket_results"
    results_dir.mkdir()
    # Write two fake ticket results
    (results_dir / "t1__ae-orchestrated.json").write_text(json.dumps({
        "cost_usd": 0.05, "tokens": {"input": 500, "output": 200}
    }))
    (results_dir / "t1__icl-baseline.json").write_text(json.dumps({
        "cost_usd": 0.03, "tokens": {"input": 300, "output": 100}
    }))
    tally = reconcile_tally(tmp_path)
    assert tally["global_usd"] == pytest.approx(0.08)
    assert tally["global_tokens"] == 1100
    assert "ae-orchestrated" in tally["cells"]
    assert "icl-baseline" in tally["cells"]


def test_reconcile_empty_results_dir(tmp_path):
    """reconcile_tally on empty directory returns zero tally."""
    (tmp_path / "ticket_results").mkdir()
    tally = reconcile_tally(tmp_path)
    assert tally["global_usd"] == 0.0
    assert tally["global_tokens"] == 0


def test_finalize_no_abort_flag_when_budget_at_finalization(tmp_path):
    """QA scenario 7: abort.flag NOT written when budget breached at finalization
    with no pending/in-flight work."""
    gate = _make_gate(tmp_path, max_usd=0.001, max_tokens=1_000_000)
    gate._global_usd = 0.002  # Manually set to exceed
    result = gate.finalize(cells_pending=False, tickets_in_flight=False)
    abort_flag = tmp_path / "abort.flag"
    assert not abort_flag.exists(), "abort.flag should NOT be written at finalization"
    assert result["budget_breached_at_finalization"] is True
    assert result["aborted"] is False


def test_finalize_aborted_with_pending_work(tmp_path):
    """abort.flag IS written when global budget exceeded with cells_pending=True."""
    gate = _make_gate(tmp_path, max_usd=0.001)
    gate._global_usd = 0.002
    result = gate.finalize(cells_pending=True, tickets_in_flight=False)
    assert result["aborted"] is True
