"""
Purpose: Scorer registry - loads per-dimension scorers and weights, enforces
         the symmetric-dimset invariant, and computes per-condition primary
         aggregate scores.

Public API:
  load_registry(weights_path: Path | None = None) -> ScorerRegistry
  ScorerRegistry.score_result(result: dict, ticket: dict) -> dict
    Returns TicketScore-shaped dict.
  ScorerRegistry.assert_symmetric_dimset(ae_score: dict, icl_score: dict) -> None
    Raises AssertionError if DIMENSIONS differ between the two conditions.
  DIMENSIONS: list[str]  -- the 6 canonical dimension names

Upstream deps: scoring/correctness.py, scope_discipline.py, quality_gate_pass.py,
               regression_test_presence.py, verification_realism.py,
               output_coherence.py; pyyaml; stdlib.

Downstream consumers: runner.py.

Failure modes: individual scorer errors are caught and returned as status="floored"
               score=0.0; the registry continues. Symmetric-dimset invariant
               violation (different DIMENSIONS on two conditions of the same ticket)
               is an AssertionError - callers abort the ticket with status=
               "invariant-violation". Weights not summing to 1.0 raises AssertionError
               at load time.

Performance: O(dimensions * scorer_complexity); standard.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from . import (
    correctness,
    output_coherence,
    quality_gate_pass,
    regression_test_presence,
    scope_discipline,
    verification_realism,
)

_LOG = logging.getLogger(__name__)

DIMENSIONS: list[str] = [
    "correctness",
    "scope-discipline",
    "quality-gate-pass",
    "regression-test-presence",
    "verification-realism",
    "output-coherence",
]

_SCORER_MAP = {
    "correctness": correctness,
    "scope-discipline": scope_discipline,
    "quality-gate-pass": quality_gate_pass,
    "regression-test-presence": regression_test_presence,
    "verification-realism": verification_realism,
    "output-coherence": output_coherence,
}

_DEFAULT_WEIGHTS = {
    "correctness": 0.30,
    "scope-discipline": 0.15,
    "quality-gate-pass": 0.20,
    "regression-test-presence": 0.10,
    "verification-realism": 0.15,
    "output-coherence": 0.10,
}


def _validate_weights(weights: dict) -> None:
    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-9, (
        f"Scorer weights must sum to 1.0; got {total}. "
        f"Weights: {weights}"
    )
    for dim in DIMENSIONS:
        assert dim in weights, (
            f"Missing weight for dimension '{dim}'. "
            f"All dimensions must have a weight: {DIMENSIONS}"
        )


class ScorerRegistry:
    """Registry of per-dimension scorers with aggregation."""

    def __init__(self, weights: dict) -> None:
        _validate_weights(weights)
        self._weights = weights

    def score_result(self, result: dict, ticket: dict) -> dict:
        """Score one ConditionResult and return a TicketScore dict."""
        ticket_id = result.get("ticket_id", "unknown")
        condition_id = result.get("condition_id", "unknown")

        dim_scores: dict[str, dict] = {}
        weights_used: dict[str, float] = {}
        floored_dims: list[str] = []
        na_dims: list[str] = []

        for dim in DIMENSIONS:
            scorer = _SCORER_MAP.get(dim)
            if scorer is None:
                _LOG.warning("No scorer for dimension '%s'; flooring.", dim)
                dim_scores[dim] = {
                    "score": 0.0,
                    "diagnostic": {"note": "No scorer registered."},
                    "scorer_version": "missing",
                    "status": "floored",
                }
                floored_dims.append(dim)
                continue
            try:
                dim_result = scorer.score(result, ticket)
            except Exception as e:
                _LOG.warning(
                    "Scorer for '%s' raised %s: %s; flooring.", dim, type(e).__name__, e
                )
                dim_result = {
                    "score": 0.0,
                    "diagnostic": {"error": str(e)},
                    "scorer_version": "error",
                    "status": "floored",
                }
            dim_scores[dim] = dim_result
            status = dim_result.get("status", "scored")
            if status == "floored":
                floored_dims.append(dim)
            elif status == "not-applicable":
                na_dims.append(dim)

        # Aggregate: symmetric-dimset; floored dims stay in aggregate with 0.0
        # not-applicable dims are excluded from the symmetric check (must match
        # across both conditions - enforced by caller via assert_symmetric_dimset)
        active_dims = [d for d in DIMENSIONS if d not in na_dims]
        active_weights = {d: self._weights[d] for d in active_dims}

        # Renormalize weights for active dims (only for primary computation)
        total_active_weight = sum(active_weights.values())
        renormalized = total_active_weight < 0.99
        if total_active_weight > 0:
            norm_factor = 1.0 / total_active_weight
        else:
            norm_factor = 1.0

        primary = 0.0
        for dim in active_dims:
            w = active_weights[dim] * norm_factor
            weights_used[dim] = w
            s = dim_scores[dim].get("score", 0.0)
            primary += w * s

        return {
            "ticket_id": ticket_id,
            "condition_id": condition_id,
            "dimensions": dim_scores,
            "primary": round(primary, 4),
            "primary_method": "symmetric-fixed-dimset",
            "status": "ok",
            "floored_dims": floored_dims,
            "na_dims": na_dims,
            "weights_renormalized": renormalized,
        }

    def assert_symmetric_dimset(self, ae_score: dict, icl_score: dict) -> None:
        """Assert both conditions have the same not-applicable dimensions.

        Per architect plan: 'not-applicable' is reserved for ticket-level absences
        that apply identically to BOTH conditions. Any mismatch is an
        invariant violation - the ticker's status is set to 'invariant-violation'.
        """
        ae_na = set(ae_score.get("na_dims", []))
        icl_na = set(icl_score.get("na_dims", []))
        if ae_na != icl_na:
            raise AssertionError(
                f"Symmetric-dimset invariant violated for ticket "
                f"'{ae_score.get('ticket_id')}': "
                f"AE N/A dims={sorted(ae_na)}, ICL N/A dims={sorted(icl_na)}. "
                "Both conditions must have identical not-applicable dimensions."
            )


def load_registry(weights_path: Path | None = None) -> ScorerRegistry:
    """Load the scorer registry with weights from YAML or use defaults."""
    if weights_path is not None and weights_path.exists():
        with weights_path.open() as f:
            weights = yaml.safe_load(f)
        if not isinstance(weights, dict):
            raise ValueError(
                f"Weights file at {weights_path} must be a YAML dict mapping "
                "dimension names to floats."
            )
    else:
        weights = dict(_DEFAULT_WEIGHTS)
    return ScorerRegistry(weights)
