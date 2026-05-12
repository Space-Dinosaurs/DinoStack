"""
Purpose: Regression tests for evals.scoring.engineer_lite - the scorer for
         the engineer component eval.

Public API: pytest test module; no public symbols.

Upstream deps: evals.scoring.engineer_lite.

Downstream consumers: pytest runner (evals/ test suite).

Failure modes: test isolation only; no I/O side effects.

Performance: standard; all tests run on in-memory fixture strings.
"""
from __future__ import annotations

import importlib
import pytest

import evals.scoring.engineer_lite as eng


# ---------------------------------------------------------------------------
# Weight sum assertion fires at import time
# ---------------------------------------------------------------------------

def test_weight_sum_asserted_at_import() -> None:
    """The module-level assert on weight sum fires correctly at import time.

    We re-import the module to confirm the assertion ran and passed. If the
    weights had been edited to not sum to 1.0 this import would raise
    AssertionError - which is the regression we are guarding against.
    """
    # If import succeeded, the assertion passed (it is module-level).
    reloaded = importlib.reload(eng)
    total = reloaded._W_FORMAT + reloaded._W_GATES + reloaded._W_CRITERIA + reloaded._W_SCOPE
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"


# ---------------------------------------------------------------------------
# score() on a trace with no status header -> invalid_format
# ---------------------------------------------------------------------------

def _make_trace(final_text: str) -> dict:
    return {"runs": [{"final_text": final_text}]}


def test_score_no_status_header_returns_invalid_format() -> None:
    trace = _make_trace("This response has no status header at all.")
    fixture: dict = {"inputs": {}}
    result = eng.score(trace, fixture)
    assert result["status"] == "invalid_format"
    assert result["primary"] == 0.0
    assert result["diagnostic"]["reason"] == "no_status_header"


# ---------------------------------------------------------------------------
# score() on empty runs list -> invalid_format
# ---------------------------------------------------------------------------

def test_score_empty_runs_returns_invalid_format() -> None:
    trace: dict = {"runs": []}
    fixture: dict = {"inputs": {}}
    result = eng.score(trace, fixture)
    assert result["status"] == "invalid_format"
    assert result["primary"] == 0.0
    assert result["diagnostic"]["reason"] == "no_runs"


# ---------------------------------------------------------------------------
# score() on a multi-run trace asserts (API misuse guard)
# ---------------------------------------------------------------------------

def test_score_multi_run_asserts() -> None:
    trace = {"runs": [{"final_text": "Status: DONE\n"}, {"final_text": "Status: DONE\n"}]}
    fixture: dict = {"inputs": {}}
    with pytest.raises(AssertionError, match="single-run trace"):
        eng.score(trace, fixture)


# ---------------------------------------------------------------------------
# score() happy path: valid status header yields status="ok"
# ---------------------------------------------------------------------------

_MINIMAL_DONE_RESPONSE = """\
Status: DONE

```yaml
status: DONE
files_modified:
  - path: src/foo.py
    change: modified
    summary: fixed the bug
quality_gate_results:
  lint: pass
  typecheck: pass
  test: pass
  raw_output: |
    All tests passed.
commit_sha: null
branch_name: null
pr_description_body: ""
```

The change was made.
"""


def test_score_valid_response_returns_ok() -> None:
    trace = _make_trace(_MINIMAL_DONE_RESPONSE)
    fixture: dict = {"inputs": {}}
    result = eng.score(trace, fixture)
    assert result["status"] == "ok"
    assert result["primary"] > 0.0
    assert result["scorer_version"] == eng.SCORER_VERSION


# ---------------------------------------------------------------------------
# _score_criteria: keyword hits and misses
# ---------------------------------------------------------------------------

def test_score_criteria_all_hits() -> None:
    text = "Status: DONE\nThe output contains alpha and beta keywords."
    trace = _make_trace(text)
    fixture = {"inputs": {"acceptance_keywords": ["alpha", "beta"]}}
    result = eng.score(trace, fixture)
    assert result["status"] == "ok"
    diag = result["diagnostic"]["criteria"]
    assert diag["hits"] == 2
    assert diag["total"] == 2
    assert diag["missing"] == []


def test_score_criteria_vacuous_full_credit() -> None:
    """No acceptance_keywords -> criteria dimension returns 1.0."""
    trace = _make_trace(_MINIMAL_DONE_RESPONSE)
    fixture = {"inputs": {}}
    result = eng.score(trace, fixture)
    assert result["diagnostic"]["criteria"]["vacuous"] is True


def test_score_criteria_partial_miss() -> None:
    text = "Status: DONE\nOnly alpha is present."
    trace = _make_trace(text)
    fixture = {"inputs": {"acceptance_keywords": ["alpha", "gamma"]}}
    result = eng.score(trace, fixture)
    diag = result["diagnostic"]["criteria"]
    assert diag["hits"] == 1
    assert "gamma" in diag["missing"]


# ---------------------------------------------------------------------------
# _score_scope: forbidden patterns
# ---------------------------------------------------------------------------

def test_score_scope_no_hit_full_credit() -> None:
    text = "Status: DONE\nNo forbidden content here."
    trace = _make_trace(text)
    fixture = {"inputs": {"forbidden_patterns": ["refactor", "cleanup"]}}
    result = eng.score(trace, fixture)
    assert result["diagnostic"]["scope"]["hits"] == []


def test_score_scope_hit_reduces_credit() -> None:
    text = "Status: DONE\nI did a large refactor and cleanup pass."
    trace = _make_trace(text)
    fixture = {"inputs": {"forbidden_patterns": ["refactor", "cleanup"]}}
    result = eng.score(trace, fixture)
    assert len(result["diagnostic"]["scope"]["hits"]) == 2


# ---------------------------------------------------------------------------
# scorer_version field present in all outputs
# ---------------------------------------------------------------------------

def test_scorer_version_always_present() -> None:
    for text in ("no header", _MINIMAL_DONE_RESPONSE):
        trace = _make_trace(text)
        result = eng.score(trace, {"inputs": {}})
        assert result["scorer_version"] == eng.SCORER_VERSION
