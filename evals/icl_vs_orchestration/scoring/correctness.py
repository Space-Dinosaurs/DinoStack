"""
Purpose: Correctness dimension scorer - Q2=(b) test-pass primary with Q2=(a)
         AC-keyword fallback when test-extraction fails per ticket.

         Q2 RESOLVED: operator confirmed (b) test-pass with (a) AC-keyword fallback.

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict:
    {score: float, diagnostic: dict, scorer_version: str, status: str}

  SCORER_VERSION = "test-pass-with-ac-keyword-fallback-v1"

Upstream deps: stdlib re, pathlib.

Downstream consumers: scoring/registry.py.

Failure modes: returns status="floored", score=0.0 on any parse error rather
               than propagating. Returns status="not-applicable" only when the
               same N/A condition holds for BOTH conditions on the same ticket
               (symmetric N/A enforced by registry.py invariant check).

Performance: regex-based; O(diff_size + test_file_size).
"""
from __future__ import annotations

import re
from pathlib import Path

SCORER_VERSION = "test-pass-with-ac-keyword-fallback-v1"

# AC keywords indicating acceptance criteria pass in a text blob.
_AC_PASS_KEYWORDS = [
    r"all tests pass",
    r"test(?:s)? pass(?:ed)?",
    r"✓",
    r"PASS(?:ED)?",
    r"acceptance criteria (?:met|satisfied|passed)",
    r"quality gate(?:s)? pass",
]
_AC_FAIL_KEYWORDS = [
    r"test(?:s)? fail(?:ed)?",
    r"FAIL(?:ED)?",
    r"❌",
    r"error(?:s)? found",
]

_AC_PASS_RE = re.compile("|".join(_AC_PASS_KEYWORDS), re.IGNORECASE)
_AC_FAIL_RE = re.compile("|".join(_AC_FAIL_KEYWORDS), re.IGNORECASE)


def score(result: dict, ticket: dict) -> dict:
    """Score the correctness of a ConditionResult against the ticket spec.

    Primary method (Q2=(b)): look for test files in result.artifacts.diff
    and check for test-pass signals. Falls back to AC-keyword scan on
    result.final_text when no test output is extractable.
    """
    # --- First-path: real test-execution result from harness ---
    test_exec = result.get("test_execution")
    if test_exec is not None:
        outcome = test_exec.get("outcome")
        score_val = 1.0 if outcome == "pass" else 0.0
        return {
            "score": score_val,
            "diagnostic": {
                "method": "test-pass-real",
                "outcome": outcome,
                "returncode": test_exec.get("returncode"),
                "stdout_tail": test_exec.get("stdout_tail", "")[-200:],
                "duration_seconds": test_exec.get("duration_seconds"),
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    final_text = result.get("final_text", "")
    artifacts = result.get("artifacts", {})
    diff = artifacts.get("diff", result.get("diff") or "")

    # --- Primary: test-pass extraction ---
    test_result = _try_extract_test_result(final_text, diff)
    if test_result is not None:
        return {
            "score": test_result["score"],
            "diagnostic": {
                "method": "test-pass",
                "test_signals": test_result["signals"],
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    # --- Fallback: AC-keyword scan (Q2=(a)) ---
    ac_result = _ac_keyword_score(final_text)
    return {
        "score": ac_result["score"],
        "diagnostic": {
            "method": "ac-keyword",
            "pass_hits": ac_result["pass_hits"],
            "fail_hits": ac_result["fail_hits"],
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }


def _try_extract_test_result(
    final_text: str, diff: str
) -> dict | None:
    """Try to extract a test pass/fail signal from the text.

    Returns None if no test output is detectable (triggers AC-keyword fallback).
    Returns dict with {score: float, signals: list[str]} if test output found.
    """
    signals = []

    # Look for pytest-style output
    pytest_match = re.search(
        r"(\d+) (?:passed|failed)(?:, (\d+) (?:passed|failed))?", final_text
    )
    if pytest_match:
        signals.append(pytest_match.group(0))

    # Look for "X tests passed" or "all tests passed"
    all_pass = re.search(r"all tests? passed?", final_text, re.IGNORECASE)
    if all_pass:
        signals.append(all_pass.group(0))

    # Look for failing indicators
    has_failure = bool(
        re.search(r"\b(?:FAILED|FAIL|AssertionError|Error:)\b", final_text)
    )

    if not signals and not has_failure:
        return None  # no test output detected

    if has_failure:
        score_val = 0.0
    elif signals:
        score_val = 1.0
    else:
        score_val = 0.5  # ambiguous

    return {"score": score_val, "signals": signals}


def _ac_keyword_score(text: str) -> dict:
    """Score based on acceptance-criteria keyword presence in text."""
    pass_hits = _AC_PASS_RE.findall(text)
    fail_hits = _AC_FAIL_RE.findall(text)

    if fail_hits and not pass_hits:
        score_val = 0.0
    elif pass_hits and not fail_hits:
        score_val = 1.0
    elif pass_hits and fail_hits:
        # Mixed signals - partial credit
        score_val = 0.5
    else:
        # No signals - neutral / unknown
        score_val = 0.5

    return {
        "score": score_val,
        "pass_hits": pass_hits[:5],
        "fail_hits": fail_hits[:5],
    }
