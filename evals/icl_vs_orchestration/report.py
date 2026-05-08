"""
Purpose: Assemble and validate the results-v1.json report. Consumed by both
         Stage 3 (pre-restructure baseline) and Stage 6 (post-restructure
         comparison) - same harness SHA, different content_sha.

Public API:
  build_summary(ticket_scores: dict) -> dict
  validate_report(report: dict) -> None
    Raises ValueError on missing required top-level fields.
  build_methodology(normalization_block: dict | None) -> dict
    Returns the methodology top-level block for results-v1.json.
  REQUIRED_REPORT_FIELDS: frozenset[str]

Upstream deps: scoring/output_coherence.py (TAXONOMY_VERSION);
               cost_gate.build_normalization_block; stdlib.

Downstream consumers: runner.py, cli.py.

Failure modes: validate_report raises ValueError with the missing fields listed.
               build_summary returns an empty-but-valid summary on empty input.
               build_methodology uses a default normalization block when none
               is supplied (safe fallback; callers should supply the block from
               CostGate.finalize() for correctness).

Performance: O(tickets * conditions * dimensions); standard.
"""
from __future__ import annotations

from .cost_gate import build_normalization_block
from .scoring.output_coherence import TAXONOMY_VERSION

REQUIRED_REPORT_FIELDS = frozenset(
    [
        "schema_version",
        "run_id",
        "corpus_dir",
        "ae_execution_mode",
        "correctness_method",
        "output_coherence_method",
        "output_coherence_taxonomy_version",
        "smoke",
        "aborted",
        "cells_dropped_by_per_cell_budget",
        "weights_renormalized_count",
        "floored_dim_count_per_condition",
        "rationale_extraction_method_count",
        "cost",
        "methodology",
        "summary",
        "tickets",
    ]
)


def build_methodology(normalization_block: dict | None = None) -> dict:
    """Return the methodology top-level block for results-v1.json.

    Contains the skeptic_input_cost_normalization block per
    cost-normalization-contract.md. If no normalization_block is supplied,
    builds a default (applied=False, fixed-estimate 5,000 tokens).

    Args:
        normalization_block: pre-built normalization dict from
            cost_gate.build_normalization_block() or CostGate.finalize()
            ["skeptic_input_cost_normalization"]. If None, a default is built.

    Returns:
        dict with key "skeptic_input_cost_normalization".
    """
    block = normalization_block if normalization_block is not None else build_normalization_block()
    return {"skeptic_input_cost_normalization": block}


def validate_report(report: dict) -> None:
    """Raise ValueError listing any missing required fields."""
    missing = REQUIRED_REPORT_FIELDS - set(report.keys())
    if missing:
        raise ValueError(
            f"Report is missing required fields: {sorted(missing)}"
        )
    if report.get("output_coherence_taxonomy_version") != TAXONOMY_VERSION:
        raise ValueError(
            f"Report output_coherence_taxonomy_version must be '{TAXONOMY_VERSION}'; "
            f"got '{report.get('output_coherence_taxonomy_version')}'."
        )
    # Validate methodology block contains normalization block per contract.
    methodology = report.get("methodology", {})
    norm = methodology.get("skeptic_input_cost_normalization")
    if norm is None:
        raise ValueError(
            "Report methodology.skeptic_input_cost_normalization is missing. "
            "Per cost-normalization-contract.md, this block is required."
        )
    for field in ("applied", "method", "baseline_tokens", "post_restructure_tokens"):
        if field not in norm:
            raise ValueError(
                f"Report methodology.skeptic_input_cost_normalization missing "
                f"required field '{field}'."
            )


def build_summary(ticket_scores: dict) -> dict:
    """Build the summary section of the report from per-ticket scores.

    Returns:
      {tickets_run, conditions, by_ticket_class, per_condition_primary_mean,
       rationale_extraction_method_count}
    """
    if not ticket_scores:
        return {
            "tickets_run": 0,
            "conditions": [],
            "by_ticket_class": {},
            "per_condition_primary_mean": {},
            "rationale_extraction_method_count": {},
        }

    primaries_by_condition: dict[str, list[float]] = {}
    by_ticket_class: dict[str, dict] = {}
    rationale_method_count: dict[str, dict] = {}

    for ticket_id, scores_by_cid in ticket_scores.items():
        for cid, sc in scores_by_cid.items():
            if not isinstance(sc, dict):
                continue
            primary = sc.get("primary", 0.0)
            primaries_by_condition.setdefault(cid, []).append(primary)

            # Accumulate rationale_extraction_method counts per condition.
            # The runner injects "_rationale_extraction_method" so report.py
            # does not need the raw result artifacts.
            method = sc.get("_rationale_extraction_method")
            if method:
                rc = rationale_method_count.setdefault(cid, {})
                rc[method] = rc.get(method, 0) + 1

            # Ticket class from score metadata (if available)
            # (would need ticket_yaml reference; omit from summary for now)

    per_condition_primary_mean = {
        cid: (sum(ps) / len(ps) if ps else 0.0)
        for cid, ps in primaries_by_condition.items()
    }

    return {
        "tickets_run": len(ticket_scores),
        "conditions": sorted(primaries_by_condition.keys()),
        "by_ticket_class": by_ticket_class,
        "per_condition_primary_mean": per_condition_primary_mean,
        "rationale_extraction_method_count": rationale_method_count,
    }
