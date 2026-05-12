"""
Purpose: N-condition rollup for the skill-comparison eval matrix. Produces
         per-condition medians, per-condition delta-vs-baseline, and a
         baseline noise envelope derived from baseline-vs-baseline replicate
         stdev. Handles missing cells (NaN/None) without crashing.

Public API:
    aggregate_conditions(
        runs: dict[str, list[float | None]],
        baseline_key: str = "baseline",
    ) -> list[ConditionRow]

    ConditionRow (dataclass):
        condition: str
        n: int
        median: float | None
        stdev: float | None
        delta_vs_baseline: float | None   # None for baseline itself
        envelope: float | None            # populated only on baseline row

Upstream deps: stdlib statistics, dataclasses, math.

Downstream consumers: evals/skill-comparison/runner.py (calls aggregate_conditions
                      then writes rows to the TSV via evals/runner/tsv_writer).

Failure modes: all-None cell yields median=None, stdev=None. Baseline cell with
               n<2 yields envelope=None (stdev undefined; documented). Does not
               raise on empty runs or fully-missing conditions - degrades
               gracefully to None fields so the caller can decide how to surface
               the gap.

Performance: O(total runs); pure in-memory arithmetic. Negligible overhead.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

# The canonical condition order for display. aggregate_conditions respects this
# order when it appears in the input; unknown conditions are appended after it.
CANONICAL_CONDITION_ORDER: list[str] = [
    "baseline",
    "ae-rules-injected",
    "engineer-direct",
    "architect-direct",
    "investigator-direct",
    "debugger-direct",
    "skeptic-direct",
    "qa-engineer-direct",
]


@dataclass
class ConditionRow:
    """Aggregated stats for one condition across all its runs."""

    condition: str
    n: int  # number of non-None runs included in the aggregation
    median: Optional[float]  # None if no non-None runs
    stdev: Optional[float]   # None if n < 2 or no non-None runs
    delta_vs_baseline: Optional[float]  # None for baseline or if baseline median unavailable
    envelope: Optional[float]  # baseline noise stdev; populated only on the baseline row
    raw_scores: list[Optional[float]] = field(default_factory=list, repr=False)


def _safe_median(values: list[float]) -> Optional[float]:
    """Return median of values, or None if values is empty."""
    if not values:
        return None
    return statistics.median(values)


def _safe_stdev(values: list[float]) -> Optional[float]:
    """Return sample stdev (N-1) of values, or None if len < 2."""
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def _non_none(scores: list[Optional[float]]) -> list[float]:
    """Filter out None/NaN entries from a score list."""
    result: list[float] = []
    for s in scores:
        if s is None:
            continue
        try:
            if not math.isnan(float(s)):
                result.append(float(s))
        except (TypeError, ValueError):
            continue
    return result


def aggregate_conditions(
    runs: dict[str, list[Optional[float]]],
    baseline_key: str = "baseline",
) -> list[ConditionRow]:
    """Aggregate N conditions into ConditionRow entries.

    Args:
        runs: mapping of condition_name -> list of per-run scores. Scores may
              be float, int (coerced), None, or float('nan') - all non-numeric
              entries are treated as missing and excluded from aggregation.
        baseline_key: name of the baseline condition used for delta computation
                      and envelope derivation. Defaults to "baseline".

    Returns:
        List of ConditionRow, one per condition, in CANONICAL_CONDITION_ORDER
        first then any remaining conditions in dict insertion order.
    """
    if not runs:
        return []

    # Sort conditions: canonical order first, then anything else in insertion order.
    canonical_set = {c: i for i, c in enumerate(CANONICAL_CONDITION_ORDER)}
    extra: list[str] = [c for c in runs if c not in canonical_set]
    ordered_conditions: list[str] = [
        c for c in CANONICAL_CONDITION_ORDER if c in runs
    ] + extra

    # Compute baseline stats first so we can subtract them.
    baseline_scores = _non_none(runs.get(baseline_key, []))
    baseline_median = _safe_median(baseline_scores)
    baseline_envelope = _safe_stdev(baseline_scores)  # noise envelope from replicates

    rows: list[ConditionRow] = []
    for condition in ordered_conditions:
        raw = runs[condition]
        valid = _non_none(raw)
        med = _safe_median(valid)
        std = _safe_stdev(valid)

        if condition == baseline_key:
            delta = None
            envelope = baseline_envelope
        else:
            # delta = condition_median - baseline_median; None if either is missing.
            if med is not None and baseline_median is not None:
                delta = med - baseline_median
            else:
                delta = None
            envelope = None

        rows.append(
            ConditionRow(
                condition=condition,
                n=len(valid),
                median=round(med, 6) if med is not None else None,
                stdev=round(std, 6) if std is not None else None,
                delta_vs_baseline=round(delta, 6) if delta is not None else None,
                envelope=round(envelope, 6) if envelope is not None else None,
                raw_scores=raw,
            )
        )

    return rows


def rows_to_tsv(rows: list[ConditionRow], task_id: str = "") -> str:
    """Render ConditionRow list as a TSV string (header + data rows).

    Primarily for smoke-checking and manual inspection. The runner writes to
    the shared TSV via evals/runner/tsv_writer; this helper is for standalone
    use and testing.

    Args:
        rows: output of aggregate_conditions.
        task_id: optional task identifier prepended as the first column.

    Returns:
        TSV string with header line followed by one data line per condition.
    """
    header_cols = ["condition", "n", "median", "stdev", "delta_vs_baseline", "envelope"]
    if task_id:
        header_cols = ["task_id"] + header_cols

    lines = ["\t".join(header_cols)]
    for row in rows:
        data = [
            row.condition,
            str(row.n),
            "" if row.median is None else str(row.median),
            "" if row.stdev is None else str(row.stdev),
            "" if row.delta_vs_baseline is None else str(row.delta_vs_baseline),
            "" if row.envelope is None else str(row.envelope),
        ]
        if task_id:
            data = [task_id] + data
        lines.append("\t".join(data))

    return "\n".join(lines)
