"""
Purpose: Scope-discipline dimension scorer - option (b) file-set inclusion check.
         Verifies that the files touched by the condition's diff match the
         files expected by the ticket spec.

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict:
    {score: float, diagnostic: dict, scorer_version: str, status: str}

Upstream deps: stdlib re.

Downstream consumers: scoring/registry.py.

Failure modes: returns score=0.5 (neutral) when ticket has no expected_files
               spec (symmetric N/A via registry invariant check). Returns
               status="scored" always (never "not-applicable" on its own;
               registry enforces symmetric N/A).

Performance: O(files_touched); standard.
"""
from __future__ import annotations

import re

SCORER_VERSION = "file-set-inclusion-v1"


def score(result: dict, ticket: dict) -> dict:
    """Score scope discipline: did the condition touch only expected files?"""
    ticket_yaml = ticket.get("ticket_yaml", {})
    expected_files = ticket_yaml.get("expected_files", None)

    artifacts = result.get("artifacts", {})
    diff = artifacts.get("diff", result.get("diff") or "")
    files_touched = result.get("files_touched", [])

    if not files_touched and diff:
        files_touched = _extract_files_from_diff(diff)

    if not expected_files:
        # No spec to check against; return neutral
        return {
            "score": 0.5,
            "diagnostic": {
                "method": "file-set-inclusion",
                "note": "No expected_files in ticket spec; neutral score.",
                "files_touched": files_touched,
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    expected_set = set(expected_files)
    touched_set = set(files_touched)

    # Precision: fraction of touched files that are expected
    if touched_set:
        precision = len(touched_set & expected_set) / len(touched_set)
    else:
        precision = 0.0

    # Recall: fraction of expected files that were touched
    if expected_set:
        recall = len(touched_set & expected_set) / len(expected_set)
    else:
        recall = 1.0

    # Harmonic mean (F1)
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    extra_files = sorted(touched_set - expected_set)
    missing_files = sorted(expected_set - touched_set)

    return {
        "score": round(f1, 4),
        "diagnostic": {
            "method": "file-set-inclusion",
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "extra_files": extra_files,
            "missing_files": missing_files,
            "files_touched": sorted(touched_set),
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }


def _extract_files_from_diff(diff: str) -> list[str]:
    """Extract file paths from a unified diff."""
    files = re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)
    return list(dict.fromkeys(files))
