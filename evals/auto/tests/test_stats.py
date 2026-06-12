"""Unit tests for evals.auto.stats - permutation test, keep gate, pair_deltas."""
from __future__ import annotations

import math

import pytest

from evals.auto.stats import (
    ALPHA,
    EPSILON,
    EXACT_MAX,
    MIN_NONZERO_PAIRS,
    keep_decision,
    pair_deltas,
    signflip_test,
)


# ---------------------------------------------------------------------------
# Case 1: no-tie exact anchor
# ---------------------------------------------------------------------------

def test_exact_k5_all_positive():
    """k=5 distinct positive magnitudes all same sign -> p == 1/32."""
    deltas = [0.1, 0.2, 0.3, 0.4, 0.5]
    result = signflip_test(deltas)
    assert result["method"] == "exact"
    assert result["n_nonzero"] == 5
    assert result["p_value"] == pytest.approx(1 / 32, abs=1e-9)


def test_exact_k6_all_positive():
    """k=6 distinct positive magnitudes all same sign -> p == 1/64."""
    deltas = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    result = signflip_test(deltas)
    assert result["method"] == "exact"
    assert result["n_nonzero"] == 6
    assert result["p_value"] == pytest.approx(1 / 64, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 2: tied-magnitude conditional-null pin
# ---------------------------------------------------------------------------

def test_tied_magnitude_conditional_null():
    """Nine +0.5, two -0.5, four 0.0 -> k=11, w_obs=4.5, p == 67/2048.

    Derivation:
      nz has 11 elements all magnitude 0.5.
      w_obs = 9 * 0.5 = 4.5.
      Under null: W = 0.5 * (#bits set). W >= 4.5 <=> #bits >= 9.
      Count = C(11,9) + C(11,10) + C(11,11) = 55 + 11 + 1 = 67.
      p = 67 / 2048.
    """
    deltas = [0.5] * 9 + [-0.5] * 2 + [0.0] * 4
    result = signflip_test(deltas)
    assert result["method"] == "exact"
    assert result["n_nonzero"] == 11
    assert result["w_obs"] == pytest.approx(4.5, abs=1e-9)
    assert result["p_value"] == pytest.approx(67 / 2048, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 3: min-n guard
# ---------------------------------------------------------------------------

def test_min_n_guard():
    """4 nonzero pairs all +0.5 -> keep=False, reason cites n_nonzero."""
    deltas = [0.5, 0.5, 0.5, 0.5]
    result = keep_decision(deltas)
    assert result["keep"] is False
    assert "n_nonzero" in result["reason"]
    assert result["n_nonzero"] == 4


# ---------------------------------------------------------------------------
# Case 4: epsilon floor
# ---------------------------------------------------------------------------

def test_epsilon_floor():
    """Fifteen +0.01: p may be <=0.05 but effect=0.01 < epsilon=0.02 -> keep=False."""
    deltas = [0.01] * 15
    result = keep_decision(deltas)
    # Verify p is low enough that the epsilon gate is the binding constraint.
    assert result["p_value"] is not None
    assert result["p_value"] <= ALPHA
    assert result["keep"] is False
    assert "effect" in result["reason"]
    assert result["effect_mean_delta"] == pytest.approx(0.01, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 5: zeros retained
# ---------------------------------------------------------------------------

def test_zeros_retained_do_not_change_result():
    """Extra 0.0 entries do not change p_value or n_nonzero."""
    base_deltas = [0.3, 0.1, -0.1, 0.4, 0.2, 0.5]
    with_zeros = base_deltas + [0.0, 0.0, 0.0]
    r_base = signflip_test(base_deltas)
    r_zeros = signflip_test(with_zeros)
    assert r_base["p_value"] == pytest.approx(r_zeros["p_value"], abs=1e-12)
    assert r_base["n_nonzero"] == r_zeros["n_nonzero"]


# ---------------------------------------------------------------------------
# Case 6: normal-approx branch
# ---------------------------------------------------------------------------

def test_normal_approx_branch():
    """k=25 (> EXACT_MAX=22) all-positive deltas -> p_value < 0.05 and finite."""
    deltas = [0.5] * 25
    result = signflip_test(deltas)
    assert result["method"] == "normal_approx"
    assert result["n_nonzero"] == 25
    assert result["p_value"] is not None
    assert math.isfinite(result["p_value"])
    assert result["p_value"] < ALPHA


def test_normal_approx_k_exceeds_exact_max():
    """Confirm EXACT_MAX=22 is respected: k=22 is exact, k=23 is normal_approx."""
    deltas_22 = [0.1] * 22
    deltas_23 = [0.1] * 23
    assert signflip_test(deltas_22)["method"] == "exact"
    assert signflip_test(deltas_23)["method"] == "normal_approx"


# ---------------------------------------------------------------------------
# Case 7: pair_deltas by fixture_id
# ---------------------------------------------------------------------------

def test_pair_deltas_by_fixture_id():
    """Reordered post rows are paired by fixture_id, not position."""
    baseline = [
        {"fixture_id": "sk-001", "primary_score_median": "0.5"},
        {"fixture_id": "sk-002", "primary_score_median": "0.6"},
        {"fixture_id": "sk-003", "primary_score_median": "0.7"},
    ]
    # Post rows in different order.
    post = [
        {"fixture_id": "sk-003", "primary_score_median": "0.9"},
        {"fixture_id": "sk-001", "primary_score_median": "0.8"},
        {"fixture_id": "sk-002", "primary_score_median": "0.7"},
    ]
    deltas = pair_deltas(baseline, post)
    assert len(deltas) == 3
    # Deltas in baseline order: sk-001, sk-002, sk-003.
    assert deltas[0] == pytest.approx(0.8 - 0.5, abs=1e-9)  # sk-001
    assert deltas[1] == pytest.approx(0.7 - 0.6, abs=1e-9)  # sk-002
    assert deltas[2] == pytest.approx(0.9 - 0.7, abs=1e-9)  # sk-003


# ---------------------------------------------------------------------------
# Case 8: pair_deltas mismatched sets
# ---------------------------------------------------------------------------

def test_pair_deltas_mismatched_sets():
    """baseline {sk-001,sk-002,sk-003}, post {sk-002,sk-003,sk-004} -> 2 paired."""
    baseline = [
        {"fixture_id": "sk-001", "primary_score_median": "0.5"},
        {"fixture_id": "sk-002", "primary_score_median": "0.6"},
        {"fixture_id": "sk-003", "primary_score_median": "0.7"},
    ]
    post = [
        {"fixture_id": "sk-002", "primary_score_median": "0.8"},
        {"fixture_id": "sk-003", "primary_score_median": "0.9"},
        {"fixture_id": "sk-004", "primary_score_median": "1.0"},
    ]
    deltas = pair_deltas(baseline, post)
    # sk-001 (baseline-only) and sk-004 (post-only) are dropped.
    assert len(deltas) == 2
    assert deltas[0] == pytest.approx(0.8 - 0.6, abs=1e-9)  # sk-002
    assert deltas[1] == pytest.approx(0.9 - 0.7, abs=1e-9)  # sk-003


# ---------------------------------------------------------------------------
# Additional edge-case guards
# ---------------------------------------------------------------------------

def test_signflip_k0_returns_none():
    """All zeros -> k=0 -> p_value=None, method=undefined."""
    result = signflip_test([0.0, 0.0])
    assert result["p_value"] is None
    assert result["method"] == "undefined"
    assert result["n_nonzero"] == 0
    assert result["w_obs"] == 0.0


def test_keep_decision_empty_deltas():
    """Empty delta list -> keep=False, n_nonzero=0, effect=0.0."""
    result = keep_decision([])
    assert result["keep"] is False
    assert result["n_nonzero"] == 0
    assert result["effect_mean_delta"] == 0.0


def test_keep_decision_returns_correct_keys():
    """keep_decision always returns all required keys."""
    result = keep_decision([0.1] * 10)
    for key in ("keep", "p_value", "effect_mean_delta", "n_nonzero", "method", "reason"):
        assert key in result


def test_keep_true_when_all_gates_pass():
    """Ten strong positives: all gates pass -> keep=True."""
    deltas = [0.1] * 10
    result = keep_decision(deltas)
    assert result["keep"] is True
    assert result["p_value"] is not None
    assert result["p_value"] <= ALPHA
    assert result["effect_mean_delta"] >= EPSILON
    assert result["n_nonzero"] >= MIN_NONZERO_PAIRS
    assert "kept" in result["reason"]


