"""
Purpose: Aggregate per-run scores into median/stdev and assemble the TSV row
         dict for a (component, fixture) execution.

Public API: aggregate(per_run_scores: list[dict], fixture, manifest, commit,
                      component_content_hash) -> dict
            (dict keys match evals.runner.tsv_writer.TSV_HEADER; includes
             fixture_id sourced from fixture.id).

Upstream deps: stdlib statistics, json; evals.runner.loader types.

Downstream consumers: evals.runner.cli.

Failure modes: empty per_run_scores yields status="no_runs" with median=0.0,
               stdev=0.0, n_runs=0, fixture_id from fixture.id. If any per-run
               score has status other than "ok" the aggregated status becomes
               the first non-ok status.

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
            "fixture_id": fixture.id,
            "primary_score_median": 0.0,
            "primary_score_stdev": 0.0,
            "n_runs": 0,
            "status": "no_runs",
            "diagnostic_json": {},
            "description": fixture.description,
        }

    primaries = [float(s.get("primary", 0.0)) for s in per_run_scores]
    median = statistics.median(primaries)
    # Sample stdev (N-1 divisor). With n < 2 the sample stdev is undefined, so
    # we report 0.0 explicitly rather than raising. The TSV stdev column is
    # documented as "sample stdev (N-1)" in evals/README.md.
    stdev = statistics.stdev(primaries) if len(primaries) >= 2 else 0.0

    statuses = [s.get("status", "ok") for s in per_run_scores]
    agg_status = "ok"
    for st in statuses:
        if st != "ok":
            agg_status = st
            break

    # Surface scorer_version at the top of the aggregated diagnostic so TSV
    # readers can tell at a glance which scorer produced a row. The field is
    # sourced from whichever per-run score declared it; if multiple runs
    # report different versions (should not happen within a single
    # fixture-run invocation) we record the first one and flag a mismatch.
    scorer_versions = [
        s.get("scorer_version") or s.get("diagnostic", {}).get("scorer_version")
        for s in per_run_scores
    ]
    scorer_versions_nonnull = [v for v in scorer_versions if v]
    scorer_version = scorer_versions_nonnull[0] if scorer_versions_nonnull else None
    scorer_version_mismatch = (
        len(set(scorer_versions_nonnull)) > 1 if scorer_versions_nonnull else False
    )

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
    if scorer_version is not None:
        diagnostic["scorer_version"] = scorer_version
    if scorer_version_mismatch:
        diagnostic["scorer_version_mismatch"] = True

    return {
        "commit": commit,
        "component_content_hash": component_content_hash,
        "fixture_hash": compute_fixture_hash(fixture.path),
        "fixture_id": fixture.id,
        "primary_score_median": round(median, 6),
        "primary_score_stdev": round(stdev, 6),
        "n_runs": len(per_run_scores),
        "status": agg_status,
        "diagnostic_json": diagnostic,
        "description": fixture.description,
    }
