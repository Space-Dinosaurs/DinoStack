# Deprecated in v1 eval; not registered. May return in v2 with corpus tickets that ship qa_criteria.
"""
Purpose: Verification-realism dimension scorer. Checks whether the condition
         produced an architect plan with qa_criteria. ICL-baseline floors at
         0.0 (no architect plan by design); AE-orchestrated scores based on
         qa_criteria presence and quality.

         Flooring rule (binding per architect-plan-eval-harness-v1.md):
         status="floored", score=0.0 when no architect plan OR no qa_criteria
         block. status="floored" is the ONLY fallback status for this dimension;
         status="not-applicable" is NEVER used here (this asymmetry is by design
         and is reflected in COVERAGE.md: ICL is always floored, AE is scored
         when plan+qa_criteria present).

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict.

Upstream deps: stdlib re.

Downstream consumers: scoring/registry.py.

Failure modes: always returns scored or floored; never raises.

Performance: O(final_text_size); regex-based.
"""
from __future__ import annotations

import re

SCORER_VERSION = "verification-realism-v1"

_QA_CRITERIA_RE = re.compile(
    r"(?:qa_criteria\s*:|##\s*qa.criteria)", re.IGNORECASE
)
_QA_SKIP_NULL_RE = re.compile(
    r"qa_skip\s*:\s*null", re.IGNORECASE
)
_SCENARIOS_RE = re.compile(
    r"scenarios\s*:", re.IGNORECASE
)


def score(result: dict, ticket: dict) -> dict:
    """Score verification realism: does the output include qa_criteria?

    AE-orchestrated: checks architect plan artifact for qa_criteria block.
    ICL-baseline: no architect plan by design -> floored at 0.0.
    """
    condition_id = result.get("condition_id", "")
    artifacts = result.get("artifacts", {})
    final_text = result.get("final_text", "")

    # Determine plan text to check
    plan_text = ""
    # AE: check for architect plan artifact
    if condition_id == "ae-orchestrated":
        arch_path = artifacts.get("architect_plan_path")
        if arch_path:
            import pathlib
            p = pathlib.Path(arch_path)
            if p.exists():
                plan_text = p.read_text()
        if not plan_text:
            # Fall back to looking for plan content in final_text
            plan_text = final_text
    # ICL: no architect plan by design
    else:
        plan_text = ""

    if not plan_text:
        return _floored("No architect plan artifact.")

    has_qa_criteria = bool(_QA_CRITERIA_RE.search(plan_text))
    if not has_qa_criteria:
        return _floored("No qa_criteria block found in architect plan.")

    # Check qa_criteria quality
    has_scenarios = bool(_SCENARIOS_RE.search(plan_text))
    has_qa_skip_null = bool(_QA_SKIP_NULL_RE.search(plan_text))

    if has_scenarios:
        score_val = 1.0
        note = "qa_criteria with scenarios present."
    elif has_qa_skip_null:
        score_val = 0.8
        note = "qa_criteria present with qa_skip=null (no explicit scenarios)."
    else:
        score_val = 0.6
        note = "qa_criteria block present but incomplete."

    return {
        "score": round(score_val, 4),
        "diagnostic": {
            "has_qa_criteria": has_qa_criteria,
            "has_scenarios": has_scenarios,
            "has_qa_skip_null": has_qa_skip_null,
            "note": note,
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }


def _floored(note: str) -> dict:
    return {
        "score": 0.0,
        "diagnostic": {"note": note},
        "scorer_version": SCORER_VERSION,
        "status": "floored",
    }
