"""Tests for scoring/correctness.score().

Covers the first-path test-execution branch (units A+E) and fallback to
ac-keyword when test_execution is absent.

Regression: verifies that the test_execution first-path is taken when
result["test_execution"] is present, and that no fallback to keyword occurs
even for outcome="error".
"""
from __future__ import annotations

import pytest

from evals.icl_vs_orchestration.scoring.correctness import score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_result(**kwargs) -> dict:
    """Minimal ConditionResult-shaped dict."""
    return {
        "final_text": "",
        "artifacts": {"diff": "", "rationale_extraction_method": "structured"},
        **kwargs,
    }


def _make_ticket(ticket_id: str = "t1") -> dict:
    return {
        "ticket_id": ticket_id,
        "ticket_yaml": {
            "ticket_id": ticket_id,
            "ticket_class": "trivial",
            "description": "test",
        },
    }


# ---------------------------------------------------------------------------
# First-path: test_execution present
# ---------------------------------------------------------------------------

def test_score_uses_test_execution_when_present_pass():
    """outcome='pass' -> score=1.0, method='test-pass-real'."""
    result = _base_result(
        test_execution={
            "outcome": "pass",
            "returncode": 0,
            "stdout_tail": "1 passed",
            "duration_seconds": 0.5,
            "error": None,
        }
    )
    out = score(result, _make_ticket())
    assert out["score"] == 1.0, f"expected 1.0, got {out['score']}"
    assert out["diagnostic"]["method"] == "test-pass-real"
    assert out["status"] == "scored"


def test_score_uses_test_execution_when_present_fail():
    """outcome='fail' -> score=0.0, method='test-pass-real'."""
    result = _base_result(
        test_execution={
            "outcome": "fail",
            "returncode": 1,
            "stdout_tail": "1 failed",
            "duration_seconds": 0.5,
            "error": None,
        }
    )
    out = score(result, _make_ticket())
    assert out["score"] == 0.0, f"expected 0.0, got {out['score']}"
    assert out["diagnostic"]["method"] == "test-pass-real"


def test_score_uses_test_execution_when_present_error():
    """outcome='error' -> score=0.0, method='test-pass-real'; NO fallback to keyword."""
    result = _base_result(
        # Include AC-pass keywords in final_text to confirm they are NOT used
        final_text="all tests pass PASSED",
        test_execution={
            "outcome": "error",
            "returncode": None,
            "stdout_tail": "",
            "duration_seconds": 1.0,
            "error": "timed out after 30s",
        }
    )
    out = score(result, _make_ticket())
    assert out["score"] == 0.0, (
        f"error outcome must score 0.0, got {out['score']}"
    )
    assert out["diagnostic"]["method"] == "test-pass-real", (
        f"must use test-pass-real even for error; got {out['diagnostic']['method']}"
    )


# ---------------------------------------------------------------------------
# Fallback: test_execution absent -> ac-keyword
# ---------------------------------------------------------------------------

def test_score_falls_back_to_keyword_when_test_execution_absent():
    """No test_execution key -> falls back to ac-keyword method."""
    # Use a result with a clear AC-pass signal and no test output
    result = _base_result(
        final_text="acceptance criteria met",
    )
    # Ensure no test_execution key
    assert "test_execution" not in result

    out = score(result, _make_ticket())
    # Method must be either "ac-keyword" or "test-pass" (the intermediate
    # text-extraction path); it must NOT be "test-pass-real".
    assert out["diagnostic"]["method"] != "test-pass-real", (
        "should not use test-pass-real when test_execution is absent"
    )
    # The ac-keyword branch should match "acceptance criteria met"
    # Score may be 1.0 (pass keyword found, no fail keywords)
    assert out["score"] in (0.0, 0.5, 1.0), f"unexpected score: {out['score']}"
