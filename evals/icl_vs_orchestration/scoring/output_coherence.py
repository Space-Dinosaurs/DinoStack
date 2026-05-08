"""
Purpose: Output-coherence dimension scorer. Implements the binarized-per-type
         formula resolved in architect-plan round 4 (Major #1):

         TAXONOMY of contradiction types:
           ["file-mismatch", "symbol-mismatch", "op-mismatch",
            "scope-mismatch", "claimed-vs-actual-files-mismatch"]

         count = number of DISTINCT contradiction types from TAXONOMY that
                 fired at least once in the (rationale_or_plan, diff) pair.
                 Multiple instances of the same type contribute 1 to count, not N.
                 Range: [0, len(TAXONOMY)] = [0, 5].

         score = 1.0 - count / len(TAXONOMY)
                 Range: [0.0, 1.0] by construction; no clamp needed.
                 count > len(TAXONOMY) is unreachable by construction.

         scorer_version = "fixed-common-pair-binarized-v1"
         output_coherence_taxonomy_version = "v1"

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict with diagnostic.contradictions list.

  TAXONOMY: list[str]  -- the 5 contradiction type names
  TAXONOMY_VERSION: str = "v1"
  SCORER_VERSION: str = "fixed-common-pair-binarized-v1"

Upstream deps: stdlib re; conditions/base.py (ConditionArtifacts shape).

Downstream consumers: scoring/registry.py.

Failure modes: returns score=1.0 (no contradictions detected) on any parse
               error rather than returning a false-negative floor. All
               detected contradiction instances recorded in diagnostic but do
               NOT enter the score count (only distinct types count).

Performance: O(rationale_size * contradiction_patterns); standard regex.
"""
from __future__ import annotations

import re

TAXONOMY: list[str] = [
    "file-mismatch",
    "symbol-mismatch",
    "op-mismatch",
    "scope-mismatch",
    "claimed-vs-actual-files-mismatch",
]
TAXONOMY_VERSION = "v1"
SCORER_VERSION = "fixed-common-pair-binarized-v1"

# Patterns for each contradiction type.
# Each pattern searches the plan text for a claim, then checks whether
# the diff contradicts it. v1 uses heuristic regex patterns.

def _detect_file_mismatch(rationale: str, diff: str) -> list[dict]:
    """Detect when rationale mentions a file that does not appear in diff."""
    instances = []
    # Files mentioned in plan
    plan_files = re.findall(r"`([a-zA-Z0-9_./-]+\.[a-zA-Z]{1,6})`", rationale)
    # Files in diff
    diff_files = set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE))
    for fname in plan_files:
        # Normalize: check if any diff file ends with the mentioned name
        if diff_files and not any(
            df.endswith(fname) or fname in df for df in diff_files
        ):
            instances.append(
                {
                    "type": "file-mismatch",
                    "plan_excerpt": f"`{fname}`",
                    "diff_excerpt": f"diff_files={sorted(diff_files)[:5]}",
                }
            )
    return instances


def _detect_symbol_mismatch(rationale: str, diff: str) -> list[dict]:
    """Detect when a function/class name in the plan is absent from diff."""
    instances = []
    # Backtick-quoted identifiers (function/class names)
    plan_symbols = re.findall(r"`([a-zA-Z_][a-zA-Z0-9_]+)`", rationale)
    for sym in plan_symbols:
        # Skip short identifiers and common keywords
        if len(sym) < 4 or sym.lower() in {
            "true", "false", "none", "null", "this", "self", "type", "dict",
            "list", "str", "int", "bool", "path", "file", "data", "name",
        }:
            continue
        if sym not in diff:
            instances.append(
                {
                    "type": "symbol-mismatch",
                    "plan_excerpt": f"`{sym}`",
                    "diff_excerpt": "(symbol absent from diff)",
                }
            )
    return instances[:3]  # Cap to avoid noise on verbose plans


def _detect_op_mismatch(rationale: str, diff: str) -> list[dict]:
    """Detect when a described operation (add/remove/rename) contradicts diff."""
    instances = []
    # "add X" but X is removed in diff
    add_claims = re.findall(r"\badd(?:s|ing|ed)?\s+`?([a-zA-Z_][a-zA-Z0-9_]+)`?", rationale, re.IGNORECASE)
    for claimed_add in add_claims:
        # Check if diff shows removal of that symbol
        if re.search(r"^-.*\b" + re.escape(claimed_add) + r"\b", diff, re.MULTILINE):
            if not re.search(r"^\+.*\b" + re.escape(claimed_add) + r"\b", diff, re.MULTILINE):
                instances.append(
                    {
                        "type": "op-mismatch",
                        "plan_excerpt": f"add {claimed_add}",
                        "diff_excerpt": f"diff removes '{claimed_add}' without adding",
                    }
                )
    return instances[:2]


def _detect_scope_mismatch(rationale: str, diff: str) -> list[dict]:
    """Detect explicit scope claims that contradict the diff scope."""
    instances = []
    # "only change X" but diff shows Y
    only_patterns = re.findall(
        r"\bonly\s+(?:change|modify|update|touch)\s+`?([a-zA-Z_][a-zA-Z0-9_./]+)`?",
        rationale, re.IGNORECASE
    )
    diff_files = set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE))
    for claimed_only in only_patterns:
        # If there are other files in diff not matching the claim
        extra = [f for f in diff_files if claimed_only not in f]
        if extra:
            instances.append(
                {
                    "type": "scope-mismatch",
                    "plan_excerpt": f"only change {claimed_only}",
                    "diff_excerpt": f"diff also touches {extra[:3]}",
                }
            )
    return instances[:2]


def _detect_claimed_vs_actual_files(rationale: str, diff: str) -> list[dict]:
    """Detect when a files-changed list in the plan contradicts the diff."""
    instances = []
    # Look for "Files changed: " or "Modified files:" lists in rationale
    list_match = re.search(
        r"(?:files?\s+(?:changed|modified|touched|created)\s*:?\s*)((?:\s*[-*]?\s*`?[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,6}`?\s*)+)",
        rationale, re.IGNORECASE
    )
    if not list_match:
        return instances

    claimed_text = list_match.group(1)
    claimed_files = re.findall(r"`?([a-zA-Z0-9_./-]+\.[a-zA-Z]{1,6})`?", claimed_text)
    diff_files = set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE))

    claimed_set = set(claimed_files)
    if diff_files and claimed_set and not claimed_set.issubset(
        {f.split("/")[-1] for f in diff_files} | diff_files
    ):
        missing_from_diff = claimed_set - diff_files - {f.split("/")[-1] for f in diff_files}
        if missing_from_diff:
            instances.append(
                {
                    "type": "claimed-vs-actual-files-mismatch",
                    "plan_excerpt": f"claimed: {sorted(claimed_set)[:5]}",
                    "diff_excerpt": f"actual: {sorted(diff_files)[:5]}",
                }
            )
    return instances


_DETECTORS = [
    ("file-mismatch", _detect_file_mismatch),
    ("symbol-mismatch", _detect_symbol_mismatch),
    ("op-mismatch", _detect_op_mismatch),
    ("scope-mismatch", _detect_scope_mismatch),
    ("claimed-vs-actual-files-mismatch", _detect_claimed_vs_actual_files),
]


def score(result: dict, ticket: dict) -> dict:
    """Score output coherence using binarized-per-type formula (round-4).

    Checks rationale_or_plan vs diff for the 5 contradiction types in TAXONOMY.
    count = number of DISTINCT types that fired at least once.
    score = 1.0 - count / len(TAXONOMY).
    """
    artifacts = result.get("artifacts", {})
    rationale_or_plan = artifacts.get("rationale_or_plan", "")
    diff = artifacts.get("diff", result.get("diff") or "")

    if not rationale_or_plan:
        return {
            "score": 1.0,
            "diagnostic": {
                "note": "No rationale_or_plan to check; assuming coherent.",
                "contradictions": [],
                "distinct_types_fired": 0,
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    # Run all detectors; collect all instances
    all_contradictions: list[dict] = []
    types_fired: set[str] = set()

    for type_name, detector in _DETECTORS:
        try:
            instances = detector(rationale_or_plan, diff)
        except Exception:
            instances = []
        if instances:
            types_fired.add(type_name)
            all_contradictions.extend(instances)

    count = len(types_fired)
    assert count <= len(TAXONOMY), (
        f"count ({count}) exceeds len(TAXONOMY) ({len(TAXONOMY)}); "
        "unreachable by construction if TAXONOMY is the union of type names."
    )

    score_val = 1.0 - count / len(TAXONOMY)
    # Bounds check (should be guaranteed by construction; belt-and-braces)
    assert 0.0 <= score_val <= 1.0, f"score out of bounds: {score_val}"

    return {
        "score": round(score_val, 4),
        "diagnostic": {
            "distinct_types_fired": count,
            "types_fired": sorted(types_fired),
            # All instances recorded for inspection; do NOT enter score
            "contradictions": all_contradictions[:20],
            "taxonomy": TAXONOMY,
            "taxonomy_version": TAXONOMY_VERSION,
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }
