"""Tests for scorer registry - covers QA scenarios 4 (weights sum assertion)
and symmetric-dimset invariant."""
import pytest

from evals.icl_vs_orchestration.scoring.registry import (
    DIMENSIONS,
    ScorerRegistry,
    load_registry,
)


def _minimal_result(condition_id: str = "ae-orchestrated") -> dict:
    return {
        "ticket_id": "test",
        "condition_id": condition_id,
        "final_text": "",
        "diff": None,
        "artifacts": {
            "rationale_or_plan": "",
            "diff": "",
            "rationale_extraction_method": "fallback-full-text",
        },
        "quality_gates": {},
    }


def _minimal_ticket() -> dict:
    return {
        "ticket_id": "test",
        "ticket_yaml": {"ticket_id": "test", "ticket_class": "trivial", "description": "test"},
    }


# ---- QA scenario 4: weights summing != 1.0 raises AssertionError ----

def test_bad_weights_raise_assertion():
    """Weights summing != 1.0 causes registry load to raise AssertionError."""
    bad_weights = {
        "correctness": 0.30,
        "scope-discipline": 0.20,
        "quality-gate-pass": 0.20,
        "regression-test-presence": 0.15,
        "output-coherence": 0.10,  # Total = 0.95, not 1.0
    }
    with pytest.raises(AssertionError, match="sum to 1.0"):
        ScorerRegistry(bad_weights)


def test_good_weights_pass():
    """Weights summing to 1.0 load without error (5-dim v1 set)."""
    good_weights = {
        "correctness": 0.30,
        "scope-discipline": 0.20,
        "quality-gate-pass": 0.20,
        "regression-test-presence": 0.15,
        "output-coherence": 0.15,
    }
    registry = ScorerRegistry(good_weights)
    assert registry is not None


def test_missing_dimension_in_weights_raises():
    """Weights dict missing a dimension raises AssertionError."""
    incomplete_weights = {
        "correctness": 0.40,
        "scope-discipline": 0.30,
        "quality-gate-pass": 0.30,
        # missing regression-test-presence, output-coherence
    }
    with pytest.raises(AssertionError):
        ScorerRegistry(incomplete_weights)


def test_verification_realism_not_in_registered_dims():
    """verification-realism is deprecated in v1 and must NOT appear in DIMENSIONS."""
    assert "verification-realism" not in DIMENSIONS


def test_dimensions_count_is_five():
    """v1 dimset has exactly 5 dimensions."""
    assert len(DIMENSIONS) == 5


# ---- Symmetric-dimset invariant ----

def test_symmetric_dimset_passes_when_equal():
    """assert_symmetric_dimset passes when NA dims are identical."""
    registry = load_registry()
    ae_score = {"ticket_id": "t", "na_dims": ["regression-test-presence"]}
    icl_score = {"ticket_id": "t", "na_dims": ["regression-test-presence"]}
    registry.assert_symmetric_dimset(ae_score, icl_score)  # should not raise


def test_symmetric_dimset_fails_when_different():
    """assert_symmetric_dimset raises AssertionError on mismatch."""
    registry = load_registry()
    ae_score = {"ticket_id": "t", "na_dims": ["regression-test-presence"]}
    icl_score = {"ticket_id": "t", "na_dims": []}  # mismatch
    with pytest.raises(AssertionError, match="Symmetric-dimset invariant violated"):
        registry.assert_symmetric_dimset(ae_score, icl_score)


# ---- score_result returns all DIMENSIONS ----

def test_score_result_returns_all_dimensions():
    """score_result includes all 5 v1 dimensions in its output."""
    registry = load_registry()
    result = _minimal_result()
    ticket = _minimal_ticket()
    score = registry.score_result(result, ticket)
    assert set(score["dimensions"].keys()) == set(DIMENSIONS)


def test_score_result_primary_in_range():
    """Primary score is in [0.0, 1.0]."""
    registry = load_registry()
    result = _minimal_result()
    ticket = _minimal_ticket()
    score = registry.score_result(result, ticket)
    assert 0.0 <= score["primary"] <= 1.0


def test_load_registry_defaults():
    """load_registry() with no weights_path uses default weights."""
    registry = load_registry()
    assert registry is not None
