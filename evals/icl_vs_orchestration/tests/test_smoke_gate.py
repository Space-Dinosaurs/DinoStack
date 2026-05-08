"""Tests for smoke_gate dominance check."""
import pytest

from evals.icl_vs_orchestration.smoke_gate import SmokeGateResult, check_smoke_dominance


def test_no_dominance_when_similar():
    """No dominance when pass rates are similar."""
    smoke_results = [
        {"condition_id": "ae-orchestrated", "primary_mean": 0.8, "cost_usd_mean": 0.05},
        {"condition_id": "icl-baseline", "primary_mean": 0.7, "cost_usd_mean": 0.03},
    ]
    result = check_smoke_dominance(smoke_results, ["ae-orchestrated", "icl-baseline"])
    assert not result.dominated


def test_icl_dominates_ae():
    """ICL dominates AE when >2x on both pass rate and cost."""
    smoke_results = [
        {"condition_id": "ae-orchestrated", "primary_mean": 0.3, "cost_usd_mean": 0.10},
        {"condition_id": "icl-baseline", "primary_mean": 0.9, "cost_usd_mean": 0.03},
    ]
    result = check_smoke_dominance(smoke_results, ["ae-orchestrated", "icl-baseline"])
    assert result.dominated
    # ICL wins -> AE cells are dominated
    assert any("ae-orchestrated" in c for c in result.dominated_cells)


def test_ae_dominates_icl():
    """AE dominates ICL when >2x on both metrics."""
    smoke_results = [
        {"condition_id": "ae-orchestrated", "primary_mean": 0.9, "cost_usd_mean": 0.01},
        {"condition_id": "icl-baseline", "primary_mean": 0.3, "cost_usd_mean": 0.05},
    ]
    result = check_smoke_dominance(smoke_results, ["ae-orchestrated", "icl-baseline"])
    assert result.dominated
    assert any("icl-baseline" in c for c in result.dominated_cells)


def test_insufficient_conditions():
    """Single condition returns no dominance."""
    result = check_smoke_dominance(
        [{"condition_id": "ae-orchestrated", "primary_mean": 0.9, "cost_usd_mean": 0.01}],
        ["ae-orchestrated"],
    )
    assert not result.dominated


def test_empty_results():
    """Empty results returns no dominance."""
    result = check_smoke_dominance([], [])
    assert not result.dominated


def test_one_sided_pass_dominance_not_sufficient():
    """Only pass rate dominance (not cost) does not trigger the gate."""
    # ICL has 3x higher pass rate but is also 3x more expensive
    smoke_results = [
        {"condition_id": "ae-orchestrated", "primary_mean": 0.2, "cost_usd_mean": 0.01},
        {"condition_id": "icl-baseline", "primary_mean": 0.9, "cost_usd_mean": 0.10},
    ]
    result = check_smoke_dominance(smoke_results, ["ae-orchestrated", "icl-baseline"])
    # ICL passes but is MORE expensive; should not dominate AE
    assert not result.dominated
