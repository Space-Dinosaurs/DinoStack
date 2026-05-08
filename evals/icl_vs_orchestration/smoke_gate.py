"""
Purpose: Smoke-gate dominance check. After a smoke run (5 tickets/cell minimum),
         checks if one condition dominates by >2x in pass rate AND >2x in cost.
         If so, the dominated condition is dropped from subsequent full-run cells.

Public API:
  check_smoke_dominance(smoke_results: list[dict], cells: list[str]) -> SmokeGateResult
  SmokeGateResult.dominated_cells: list[str]  -- cells to drop
  SmokeGateResult.reason: str               -- human-readable explanation
  SmokeGateResult.dominated: bool

Upstream deps: stdlib.

Downstream consumers: runner.py, cli.py.

Failure modes: always returns a SmokeGateResult; never raises. Returns
               dominated=False if insufficient data to determine dominance.

Performance: O(results); standard.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SmokeGateResult:
    dominated: bool
    dominated_cells: list[str] = field(default_factory=list)
    reason: str = ""
    summary: dict = field(default_factory=dict)


def check_smoke_dominance(
    smoke_results: list[dict], cells: list[str]
) -> SmokeGateResult:
    """Determine if one condition dominates by >2x on both pass rate and cost.

    Per Brief cost-ceiling rule: if smoke pass shows one condition dominating
    by >2x in pass rate AND >2x in cost, the dominated condition is dropped
    from that cell before the full run.

    smoke_results: list of per-condition aggregated results, each with:
      {condition_id, primary_mean, cost_usd_mean, ticket_count}

    Returns SmokeGateResult with dominated cells list and reason.
    """
    if len(smoke_results) < 2:
        return SmokeGateResult(
            dominated=False,
            reason="Insufficient conditions for dominance check.",
        )

    # Build per-condition aggregates
    by_condition: dict[str, dict] = {}
    for r in smoke_results:
        cid = r.get("condition_id", "unknown")
        by_condition[cid] = r

    ae = by_condition.get("ae-orchestrated", {})
    icl = by_condition.get("icl-baseline", {})

    if not ae or not icl:
        return SmokeGateResult(
            dominated=False,
            reason="Missing one or both conditions in smoke results.",
        )

    ae_primary = ae.get("primary_mean", 0.0)
    icl_primary = icl.get("primary_mean", 0.0)
    ae_cost = ae.get("cost_usd_mean", 0.0)
    icl_cost = icl.get("cost_usd_mean", 0.0)

    summary = {
        "ae_primary": ae_primary,
        "icl_primary": icl_primary,
        "ae_cost_usd": ae_cost,
        "icl_cost_usd": icl_cost,
    }

    dominated_cells: list[str] = []
    reason_parts: list[str] = []

    # Check if ICL dominates AE (AE is dominated)
    if _dominates(icl_primary, ae_primary, icl_cost, ae_cost):
        dominated_cells.extend(
            [c for c in cells if "ae-orchestrated" in c]
        )
        reason_parts.append(
            f"ICL dominates AE: pass {icl_primary:.3f} vs {ae_primary:.3f} (>2x), "
            f"cost ${icl_cost:.4f} vs ${ae_cost:.4f} (>2x lower)"
        )

    # Check if AE dominates ICL (ICL is dominated)
    if _dominates(ae_primary, icl_primary, ae_cost, icl_cost):
        dominated_cells.extend(
            [c for c in cells if "icl-baseline" in c]
        )
        reason_parts.append(
            f"AE dominates ICL: pass {ae_primary:.3f} vs {icl_primary:.3f} (>2x), "
            f"cost ${ae_cost:.4f} vs ${icl_cost:.4f} (>2x lower)"
        )

    if dominated_cells:
        return SmokeGateResult(
            dominated=True,
            dominated_cells=dominated_cells,
            reason="; ".join(reason_parts),
            summary=summary,
        )

    return SmokeGateResult(
        dominated=False,
        reason="No condition dominates by >2x on both pass rate and cost.",
        summary=summary,
    )


def _dominates(
    winner_primary: float,
    loser_primary: float,
    winner_cost: float,
    loser_cost: float,
) -> bool:
    """Return True if winner dominates loser by >2x on BOTH metrics."""
    if loser_primary <= 0:
        return False  # Cannot divide by zero; no dominance
    pass_dominance = winner_primary > 2.0 * loser_primary
    # Cost dominance: winner is cheaper (loser costs >2x winner)
    if winner_cost <= 0:
        cost_dominance = loser_cost > 0  # winner is free; definitely cheaper
    else:
        cost_dominance = loser_cost > 2.0 * winner_cost
    return pass_dominance and cost_dominance
