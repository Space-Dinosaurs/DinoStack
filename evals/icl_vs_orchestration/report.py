"""
Purpose: Assemble and validate the results-v1.json report. Consumed by both
         Stage 3 (pre-restructure baseline) and Stage 6 (post-restructure
         comparison) - same harness SHA, different content_sha.

Public API:
  build_summary(ticket_scores: dict) -> dict
  validate_report(report: dict) -> None
    Raises ValueError on missing required top-level fields.
  REQUIRED_REPORT_FIELDS: frozenset[str]

Upstream deps: scoring/output_coherence.py (TAXONOMY_VERSION); stdlib.

Downstream consumers: runner.py, cli.py.

Failure modes: validate_report raises ValueError with the missing fields listed.
               build_summary returns an empty-but-valid summary on empty input.

Performance: O(tickets * conditions * dimensions); standard.

NOTE: cost-confounder normalization fields are stubbed pending delivery of
cost-normalization-contract.md from the skeptic-global-context engineer.
Once that file is available, implement the normalization contract here and
in cost_gate.py, then remove the cost_normalization_pending=True marker.
"""
from __future__ import annotations

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
        "summary",
        "tickets",
    ]
)


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
