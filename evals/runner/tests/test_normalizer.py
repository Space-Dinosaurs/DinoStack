"""
Purpose: Unit and integration tests for evals.runner.normalizer.parse_stream_json,
         specifically the token-usage capture path added in the Unit-B fix.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.normalizer, evals.icl_vs_orchestration.metering (integration test).

Downstream consumers: pytest runner (evals/ test suite).

Failure modes: test isolation only; no I/O side effects.

Performance: standard; all tests run on in-memory fixture strings.
"""
from __future__ import annotations

import json

import pytest

from evals.runner.normalizer import parse_stream_json
from evals.icl_vs_orchestration.metering import extract_tokens

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_stream(events: list[dict]) -> str:
    """Serialize a list of event dicts to a stream-json-formatted string."""
    return "\n".join(json.dumps(e) for e in events)


_RESULT_EVENT_WITH_USAGE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 1,
    "result": "hi",
    "total_cost_usd": 0.01,
    "usage": {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 50,
    },
}

_RESULT_EVENT_NO_USAGE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 1,
    "result": "hi",
    "total_cost_usd": 0.01,
    # no "usage" key - simulates older CLI version or error exit
}

_ASSISTANT_EVENT = {
    "type": "assistant",
    "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "hi"}],
    },
}

# Fixture stream-json with populated usage - used across multiple tests.
_STREAM_WITH_USAGE = _make_stream([_ASSISTANT_EVENT, _RESULT_EVENT_WITH_USAGE])
_STREAM_WITHOUT_USAGE = _make_stream([_ASSISTANT_EVENT, _RESULT_EVENT_NO_USAGE])


# ---------------------------------------------------------------------------
# Test 1: result event with usage populates run_record["usage"] correctly
# ---------------------------------------------------------------------------

def test_parse_stream_json_usage_populated():
    """result event with usage sub-object correctly populates run_record['usage']."""
    record = parse_stream_json(_STREAM_WITH_USAGE)

    assert "usage" in record, "parse_stream_json must include 'usage' key in return dict"
    usage = record["usage"]
    assert isinstance(usage, dict), "usage must be a dict"
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert usage["cache_creation_input_tokens"] == 200
    assert usage["cache_read_input_tokens"] == 50


# ---------------------------------------------------------------------------
# Test 2: result event without usage produces run_record["usage"] == {}
# ---------------------------------------------------------------------------

def test_parse_stream_json_usage_absent_produces_empty_dict():
    """result event with no usage field produces run_record['usage'] == {} without raising."""
    record = parse_stream_json(_STREAM_WITHOUT_USAGE)

    assert "usage" in record, "parse_stream_json must always include 'usage' key"
    assert record["usage"] == {}, (
        "usage must be empty dict when result event has no usage sub-object"
    )


# ---------------------------------------------------------------------------
# Test 3: integration - extract_tokens reads non-zero counts via parse_stream_json
# ---------------------------------------------------------------------------

def test_extract_tokens_via_parse_stream_json_returns_nonzero_input_tokens():
    """extract_tokens(parse_stream_json(<stream_with_usage>)) returns non-zero input_tokens."""
    record = parse_stream_json(_STREAM_WITH_USAGE)
    tokens = extract_tokens(record)

    assert tokens["input"] > 0, (
        "input_tokens must be non-zero when usage is populated by parse_stream_json"
    )
    assert tokens["input"] == 10
    assert tokens["output"] == 5
    assert tokens["cache_creation"] == 200
    assert tokens["cache_read"] == 50


# ---------------------------------------------------------------------------
# Bonus: empty stream still produces usage key (regression guard)
# ---------------------------------------------------------------------------

def test_parse_stream_json_empty_stream_has_usage_key():
    """Empty stream produces usage={} - key always present."""
    record = parse_stream_json("")
    assert "usage" in record
    assert record["usage"] == {}
