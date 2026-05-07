"""Tests for cost_gate.py - covers QA scenarios 2, 3, 6, 7 (budget gating)
and cost-normalization-contract.md compliance."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from evals.icl_vs_orchestration.cost_gate import (
    BudgetExceeded,
    CostGate,
    build_normalization_block,
    reconcile_tally,
)
from evals.icl_vs_orchestration.metering import estimate_cost_usd


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


# ---------------------------------------------------------------------------
# cost-normalization-contract.md compliance tests
# ---------------------------------------------------------------------------

def test_finalize_includes_normalization_block(tmp_path):
    """finalize() result must contain skeptic_input_cost_normalization per contract."""
    gate = _make_gate(tmp_path)
    result = gate.finalize(cells_pending=False, tickets_in_flight=False)
    assert "skeptic_input_cost_normalization" in result, (
        "finalize() must include skeptic_input_cost_normalization "
        "per cost-normalization-contract.md"
    )


def test_finalize_normalization_block_has_required_fields(tmp_path):
    """normalization block must have applied, method, baseline_tokens,
    post_restructure_tokens per cost-normalization-contract.md."""
    gate = _make_gate(tmp_path)
    result = gate.finalize(cells_pending=False, tickets_in_flight=False)
    norm = result["skeptic_input_cost_normalization"]
    for field in ("applied", "method", "baseline_tokens", "post_restructure_tokens"):
        assert field in norm, f"normalization block missing required field '{field}'"


def test_finalize_no_cost_normalization_pending_flag(tmp_path):
    """finalize() must NOT contain cost_normalization_pending flag (stub removed)."""
    gate = _make_gate(tmp_path)
    result = gate.finalize(cells_pending=False, tickets_in_flight=False)
    assert "cost_normalization_pending" not in result, (
        "cost_normalization_pending stub flag must be removed"
    )


def test_build_normalization_block_default_applied_false():
    """Default normalization block has applied=False (fixed-estimate path)."""
    block = build_normalization_block()
    assert block["applied"] is False


def test_build_normalization_block_baseline_tokens_zero():
    """baseline_tokens must be 0 (pre-restructure Skeptics have no Global-context)."""
    block = build_normalization_block()
    assert block["baseline_tokens"] == 0


def test_build_normalization_block_default_post_restructure_tokens():
    """Default post_restructure_tokens is 5000 (contract's fixed estimate midpoint)."""
    block = build_normalization_block()
    assert block["post_restructure_tokens"] == 5000


def test_build_normalization_block_applied_true_method():
    """When applied=True, method describes normalization applied."""
    block = build_normalization_block(applied=True)
    assert block["applied"] is True
    assert "subtract" in block["method"].lower()


def test_build_normalization_block_applied_false_includes_confounder_language():
    """When applied=False, method must include confounder language per contract."""
    block = build_normalization_block(applied=False)
    method = block["method"]
    # Contract requires the limitations text to include the confounder claim
    assert "Global-context" in method or "global-context" in method.lower()
    assert "verification-surface" in method or "overhead" in method.lower()


def test_build_normalization_block_custom_post_restructure_tokens():
    """post_restructure_tokens can be customized (for empirical measurement)."""
    block = build_normalization_block(post_restructure_tokens=7500)
    assert block["post_restructure_tokens"] == 7500


# ---------------------------------------------------------------------------
# Regression: Minor 3 - cache tokens count toward token ceiling
# ---------------------------------------------------------------------------

def test_cache_tokens_count_toward_global_ceiling(tmp_path):
    """[Minor3-regression] cache_creation and cache_read tokens must trip
    the global token ceiling. Prior bug: only input+output were counted."""
    # Set a low ceiling that only cache tokens will exceed
    gate = _make_gate(tmp_path, max_usd=1000.0, max_tokens=50)
    # input+output = 20, but cache tokens push total to 70 > 50
    with pytest.raises(BudgetExceeded) as exc:
        gate.record(
            "ae-orchestrated",
            "t1",
            {"input": 10, "output": 10, "cache_creation": 25, "cache_read": 25},
            cost_usd=0.001,
        )
    assert exc.value.scope == "global", (
        "cache tokens must push the global token total over the ceiling"
    )


def test_record_without_cache_tokens_not_tripped(tmp_path):
    """Without cache tokens, ceiling not tripped if only input+output are low."""
    gate = _make_gate(tmp_path, max_usd=1000.0, max_tokens=50)
    # input+output = 20, no cache tokens - should NOT raise
    gate.record(
        "ae-orchestrated",
        "t1",
        {"input": 10, "output": 10},
        cost_usd=0.001,
    )
    # No exception means the ceiling was not tripped


def test_reconcile_tally_counts_cache_tokens(tmp_path):
    """[Minor3-regression] reconcile_tally must include cache tokens in total."""
    results_dir = tmp_path / "ticket_results"
    results_dir.mkdir()
    (results_dir / "t1__ae-orchestrated.json").write_text(json.dumps({
        "cost_usd": 0.01,
        "tokens": {
            "input": 100,
            "output": 50,
            "cache_creation": 200,
            "cache_read": 300,
        },
    }))
    tally = reconcile_tally(tmp_path)
    # Prior bug: cache tokens were excluded; total was 150 instead of 650
    assert tally["global_tokens"] == 650, (
        f"Expected global_tokens=650 (all token types), got {tally['global_tokens']}"
    )


# ---------------------------------------------------------------------------
# Regression: M2 - finalize() aborted field is authoritative
# ---------------------------------------------------------------------------

def test_finalize_budget_at_finalization_no_pending_returns_not_aborted(tmp_path):
    """[M2-regression] finalize() returns aborted=False when budget is breached
    at finalization with no pending/in-flight work (cells_pending=False,
    tickets_in_flight=False). Prior bug: runner used local aborted=True."""
    gate = _make_gate(tmp_path, max_usd=0.001, max_tokens=1_000_000)
    gate._global_usd = 0.002  # Manually exceed limit
    tally = gate.finalize(cells_pending=False, tickets_in_flight=False)
    assert tally["aborted"] is False, (
        "aborted must be False when budget breached at finalization with no pending work"
    )
    assert tally["budget_breached_at_finalization"] is True, (
        "budget_breached_at_finalization must be True"
    )


def test_finalize_budget_with_cells_pending_returns_aborted(tmp_path):
    """[M2-regression] finalize() returns aborted=True when cells_pending=True."""
    gate = _make_gate(tmp_path, max_usd=0.001)
    gate._global_usd = 0.002
    tally = gate.finalize(cells_pending=True, tickets_in_flight=False)
    assert tally["aborted"] is True


# ---------------------------------------------------------------------------
# Kimi K2.6 metering rate regression test
# ---------------------------------------------------------------------------

def test_kimi_k2_6_input_rate():
    """[kimi-eval-routing] estimate_cost_usd returns correct input rate for
    claude-kimi-k2.6 (Moonshot public pricing: $0.60/M input tokens).
    Without a _MODEL_RATES entry this returns $0.00 and logs a warning."""
    cost = estimate_cost_usd(
        {"input": 1_000_000, "output": 0, "cache_creation": 0, "cache_read": 0},
        "claude-kimi-k2.6",
    )
    assert cost == pytest.approx(0.60), (
        f"Expected $0.60 for 1M input tokens on claude-kimi-k2.6, got ${cost}. "
        "Ensure metering._MODEL_RATES contains a 'claude-kimi-k2' entry with input=0.60."
    )


def test_kimi_k2_6_output_rate():
    """[kimi-eval-routing] estimate_cost_usd returns correct output rate for
    claude-kimi-k2.6 (Moonshot public pricing: $2.50/M output tokens)."""
    cost = estimate_cost_usd(
        {"input": 0, "output": 1_000_000, "cache_creation": 0, "cache_read": 0},
        "claude-kimi-k2.6",
    )
    assert cost == pytest.approx(2.50), (
        f"Expected $2.50 for 1M output tokens on claude-kimi-k2.6, got ${cost}."
    )


def test_kimi_k2_6_nonzero_for_mixed_tokens():
    """[kimi-eval-routing] estimate_cost_usd returns >0 for any non-zero token count
    on claude-kimi-k2.6 (guards against silent $0 regression)."""
    cost = estimate_cost_usd(
        {"input": 1000, "output": 500, "cache_creation": 0, "cache_read": 0},
        "claude-kimi-k2.6",
    )
    assert cost > 0, (
        "estimate_cost_usd must return >0 for claude-kimi-k2.6 with non-zero tokens. "
        "Got $0 - likely missing _MODEL_RATES entry."
    )
