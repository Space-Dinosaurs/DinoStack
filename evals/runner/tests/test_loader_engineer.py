"""
Purpose: Regression tests for evals.runner.loader._validate_engineer_fixture -
         the fixture-schema validator for the engineer component eval.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.loader (_validate_engineer_fixture).

Downstream consumers: pytest runner (evals/ test suite).

Failure modes: test isolation only; no I/O side effects.

Performance: standard; all tests run against in-memory dicts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# _validate_engineer_fixture is a module-private helper. Import it directly
# for unit testing; it is not exported via __all__ but is accessible.
from evals.runner.loader import _validate_engineer_fixture  # type: ignore[attr-defined]

_FAKE_PATH = Path("evals/fixtures/engineer/test-fixture.yaml")

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def _make_valid() -> dict:
    return {
        "id": "eng-001",
        "component": "engineer",
        "protocol_sha": "abc123",
        "inputs": {
            "task_description": "Add a validate() method to src/foo.py.",
            "acceptance_keywords": ["validate", "src/foo.py"],
            "forbidden_patterns": ["refactor"],
        },
        "expected_outputs": {
            "must_mention": ["Status: DONE"],
            "must_not_mention": ["rm -rf"],
        },
    }


def test_valid_fixture_passes() -> None:
    """Happy path: all required fields present and correctly typed."""
    _validate_engineer_fixture(_make_valid(), _FAKE_PATH)  # must not raise


# ---------------------------------------------------------------------------
# Missing required top-level keys
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_key", ["id", "component", "protocol_sha", "inputs", "expected_outputs"])
def test_missing_top_level_key_raises(missing_key: str) -> None:
    data = _make_valid()
    del data[missing_key]
    with pytest.raises(ValueError, match=missing_key):
        _validate_engineer_fixture(data, _FAKE_PATH)


# ---------------------------------------------------------------------------
# inputs.task_description required
# ---------------------------------------------------------------------------

def test_missing_task_description_raises_with_message() -> None:
    data = _make_valid()
    del data["inputs"]["task_description"]
    with pytest.raises(ValueError, match="task_description"):
        _validate_engineer_fixture(data, _FAKE_PATH)


def test_empty_task_description_raises() -> None:
    data = _make_valid()
    data["inputs"]["task_description"] = ""
    with pytest.raises(ValueError, match="task_description"):
        _validate_engineer_fixture(data, _FAKE_PATH)


# ---------------------------------------------------------------------------
# inputs.acceptance_keywords must be a list (not a string)
# ---------------------------------------------------------------------------

def test_acceptance_keywords_as_string_raises() -> None:
    """acceptance_keywords must be a list, not a bare string."""
    data = _make_valid()
    data["inputs"]["acceptance_keywords"] = "validate"  # wrong type
    with pytest.raises(ValueError, match="acceptance_keywords"):
        _validate_engineer_fixture(data, _FAKE_PATH)


def test_acceptance_keywords_as_list_passes() -> None:
    data = _make_valid()
    data["inputs"]["acceptance_keywords"] = ["validate"]
    _validate_engineer_fixture(data, _FAKE_PATH)  # must not raise


def test_acceptance_keywords_absent_passes() -> None:
    """acceptance_keywords is optional."""
    data = _make_valid()
    del data["inputs"]["acceptance_keywords"]
    _validate_engineer_fixture(data, _FAKE_PATH)  # must not raise


# ---------------------------------------------------------------------------
# inputs.forbidden_patterns must be a list
# ---------------------------------------------------------------------------

def test_forbidden_patterns_as_string_raises() -> None:
    data = _make_valid()
    data["inputs"]["forbidden_patterns"] = "refactor"  # wrong type
    with pytest.raises(ValueError, match="forbidden_patterns"):
        _validate_engineer_fixture(data, _FAKE_PATH)


# ---------------------------------------------------------------------------
# expected_outputs must be a mapping
# ---------------------------------------------------------------------------

def test_expected_outputs_not_mapping_raises() -> None:
    data = _make_valid()
    data["expected_outputs"] = ["should be a dict"]
    with pytest.raises(ValueError, match="expected_outputs"):
        _validate_engineer_fixture(data, _FAKE_PATH)


# ---------------------------------------------------------------------------
# expected_outputs.must_mention and must_not_mention must be lists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["must_mention", "must_not_mention"])
def test_expected_output_field_as_string_raises(field: str) -> None:
    data = _make_valid()
    data["expected_outputs"][field] = "Status: DONE"  # wrong type
    with pytest.raises(ValueError, match=field):
        _validate_engineer_fixture(data, _FAKE_PATH)
