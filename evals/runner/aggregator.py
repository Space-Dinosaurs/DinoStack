"""
Purpose: Aggregate per-run scores into median/stdev and assemble the TSV row
         dict for a (component, fixture) execution.

Public API: aggregate(per_run_scores: list[dict], fixture, manifest, commit,
                      component_content_hash) -> dict
            (dict keys match evals.runner.tsv_writer.TSV_HEADER).

Upstream deps: stdlib statistics, json; evals.runner.loader types.

Downstream consumers: evals.runner.cli.

Failure modes: empty per_run_scores yields status="no_runs" with median=0.0,
               stdev=0.0, n_runs=0. If any per-run score has status other than
               "ok" the aggregated status becomes the first non-ok status.

Performance: standard.
"""
from __future__ import annotations

import statistics
from typing import Any

from .loader import ComponentManifest, Fixture, compute_fixture_hash


def aggregate(
    per_run_scores: list[dict],
    fixture: Fixture,
    manifest: ComponentManifest,
    commit: str,
    component_content_hash: str,
) -> dict:
    if not per_run_scores:
        return {
            "commit": commit,
            "component_content_hash": component_content_hash,
            "fixture_hash": compute_fixture_hash(fixture.path),
            "primary_score_median": 0.0,
            "primary_score_stdev": 0.0,
            "n_runs": 0,
            "status": "no_runs",
            "diagnostic_json": {},
            "description": fixture.description,
        }

    primaries = [float(s.get("primary", 0.0)) for s in per_run_scores]
    median = statistics.median(primaries)
    stdev = statistics.pstdev(primaries) if len(primaries) > 1 else 0.0

    statuses = [s.get("status", "ok") for s in per_run_scores]
    agg_status = "ok"
    for st in statuses:
        if st != "ok":
            agg_status = st
            break

    diagnostic: dict[str, Any] = {
        "per_run": [
            {
                "primary": primaries[i],
                "status": statuses[i],
                "diagnostic": per_run_scores[i].get("diagnostic", {}),
            }
            for i in range(len(per_run_scores))
        ],
        "n_runs": len(per_run_scores),
    }

    return {
        "commit": commit,
        "component_content_hash": component_content_hash,
        "fixture_hash": compute_fixture_hash(fixture.path),
        "primary_score_median": round(median, 6),
        "primary_score_stdev": round(stdev, 6),
        "n_runs": len(per_run_scores),
        "status": agg_status,
        "diagnostic_json": diagnostic,
        "description": fixture.description,
    }
