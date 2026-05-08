"""
Purpose: Quality-gate-pass dimension scorer. Reads result.quality_gates dict
         (populated by the condition adapter) and scores pass rate. Symmetric
         N/A applies when the ticket has no quality-gate runners configured.

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict.

Upstream deps: stdlib only.

Downstream consumers: scoring/registry.py.

Failure modes: returns neutral score=0.5 when no quality_gates data is present.
               Returns not-applicable (via registry) when the N/A condition
               applies identically to both conditions.

Performance: standard; O(gates_count).
"""
from __future__ import annotations

SCORER_VERSION = "quality-gate-pass-v1"


def score(result: dict, ticket: dict) -> dict:
    """Score quality-gate pass rate from result.quality_gates."""
    quality_gates = result.get("quality_gates", {})
    final_text = result.get("final_text", "")

    # Try to extract gate signals from final_text if quality_gates is empty
    if not quality_gates:
        text_gates = _extract_gates_from_text(final_text)
        if text_gates:
            quality_gates = text_gates

    if not quality_gates:
        return {
            "score": 0.5,
            "diagnostic": {
                "note": "No quality_gates data from condition adapter or text extraction.",
                "quality_gates": {},
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    # Count passed/failed gates
    passed = 0
    failed = 0
    gate_details = {}
    for gate_name, gate_result in quality_gates.items():
        if isinstance(gate_result, dict):
            gate_pass = gate_result.get("passed", gate_result.get("status") == "pass")
        elif isinstance(gate_result, bool):
            gate_pass = gate_result
        else:
            gate_pass = False
        gate_details[gate_name] = gate_pass
        if gate_pass:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    gate_score = passed / total if total > 0 else 0.5

    return {
        "score": round(gate_score, 4),
        "diagnostic": {
            "gates": gate_details,
            "passed": passed,
            "failed": failed,
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }


def _extract_gates_from_text(text: str) -> dict:
    """Heuristically extract quality gate signals from final_text."""
    import re
    gates = {}

    # Look for lint/typecheck/test pass/fail signals
    patterns = [
        (r"lint[:\s]+pass", "lint", True),
        (r"lint[:\s]+fail", "lint", False),
        (r"typecheck[:\s]+pass", "typecheck", True),
        (r"typecheck[:\s]+fail", "typecheck", False),
        (r"test[s]?[:\s]+pass", "tests", True),
        (r"test[s]?[:\s]+fail", "tests", False),
        (r"✓\s*lint", "lint", True),
        (r"✗\s*lint", "lint", False),
    ]
    for pattern, gate_name, passed in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            gates[gate_name] = {"passed": passed}

    return gates
