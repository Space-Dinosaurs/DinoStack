#!/usr/bin/env python3
"""
Dedicated unit tests for bin/_role_spec.py.

Covers normalize_role_spec() exhaustively against its real behavior (read
from source), plus frozenset identity/membership checks for KNOWN_HARNESSES
and KNOWN_ROLES.

Test inventory:
  1. test_scalar_string_returns_model_dict       - str -> {"model": str}
  2. test_scalar_whitespace_string               - " " is truthy -> {"model": " "}
  3. test_mapping_all_known_keys                 - dict with all 3 keys preserved
  4. test_mapping_partial_known_keys             - only present known keys returned
  5. test_mapping_unknown_keys_dropped           - unknown keys filtered out
  6. test_mapping_mixed_known_and_unknown        - known kept, unknown dropped
  7. test_mapping_falsy_values_preserved         - falsy values inside dict NOT dropped
  8. test_empty_dict_returns_empty               - {} -> {}
  9. test_none_returns_empty                     - None -> {}
  10. test_empty_string_returns_empty            - "" -> {}
  11. test_int_raises_typeerror                  - int -> TypeError
  12. test_list_raises_typeerror                 - list -> TypeError
  13. test_float_raises_typeerror                - float -> TypeError
  14. test_typeerror_message_contains_typename   - error text names the bad type
  15. test_known_harnesses_is_frozenset          - KNOWN_HARNESSES type check
  16. test_known_harnesses_exact_members         - all 7 expected members present
  17. test_known_roles_is_frozenset              - KNOWN_ROLES type check
  18. test_known_roles_exact_members             - all 9 expected members present

Run with: python3 -m pytest bin/tests/test__role_spec.py -x
       or: python3 bin/tests/test__role_spec.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load _role_spec.py (has .py extension - use SourceFileLoader directly)
# ---------------------------------------------------------------------------
_BIN = Path(__file__).parent.parent
_ROLE_SPEC_PATH = _BIN / "_role_spec.py"

_loader = importlib.machinery.SourceFileLoader("_role_spec", str(_ROLE_SPEC_PATH))
_spec = importlib.util.spec_from_loader("_role_spec", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for _role_spec from {_ROLE_SPEC_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

normalize_role_spec = _mod.normalize_role_spec
KNOWN_HARNESSES = _mod.KNOWN_HARNESSES
KNOWN_ROLES = _mod.KNOWN_ROLES


# ---------------------------------------------------------------------------
# normalize_role_spec - scalar string input
# ---------------------------------------------------------------------------

def test_scalar_string_returns_model_dict():
    assert normalize_role_spec("sonnet") == {"model": "sonnet"}


def test_scalar_string_arbitrary_value():
    assert normalize_role_spec("claude-opus-4-5") == {"model": "claude-opus-4-5"}


def test_scalar_whitespace_string():
    # " " is truthy - not caught by `if not value`; treated as a model id
    result = normalize_role_spec(" ")
    assert result == {"model": " "}


# ---------------------------------------------------------------------------
# normalize_role_spec - mapping input
# ---------------------------------------------------------------------------

def test_mapping_all_known_keys():
    inp = {"model": "sonnet", "effort": "high", "reasoning": "4096"}
    assert normalize_role_spec(inp) == {"model": "sonnet", "effort": "high", "reasoning": "4096"}


def test_mapping_partial_known_keys_model_only():
    assert normalize_role_spec({"model": "haiku"}) == {"model": "haiku"}


def test_mapping_partial_known_keys_model_and_effort():
    result = normalize_role_spec({"model": "sonnet", "effort": "medium"})
    assert result == {"model": "sonnet", "effort": "medium"}
    assert "reasoning" not in result


def test_mapping_unknown_keys_dropped():
    result = normalize_role_spec({"model": "opus", "tier": "3", "foo": "bar"})
    assert result == {"model": "opus"}
    assert "tier" not in result
    assert "foo" not in result


def test_mapping_mixed_known_and_unknown():
    result = normalize_role_spec({"model": "sonnet", "effort": "low", "unknown_key": "x"})
    assert result == {"model": "sonnet", "effort": "low"}


def test_mapping_only_unknown_keys_returns_empty_dict():
    # All keys are unknown - filtered out, leaving {}
    result = normalize_role_spec({"tier": "2", "foo": "bar"})
    assert result == {}


def test_mapping_falsy_values_preserved():
    # Falsy values inside a dict are NOT dropped - only key membership is checked
    result = normalize_role_spec({"model": "", "effort": None, "reasoning": 0})
    assert result == {"model": "", "effort": None, "reasoning": 0}


# ---------------------------------------------------------------------------
# normalize_role_spec - falsy / empty input
# ---------------------------------------------------------------------------

def test_empty_dict_returns_empty():
    # {} is falsy - caught by `if not value`
    assert normalize_role_spec({}) == {}


def test_none_returns_empty():
    assert normalize_role_spec(None) == {}


def test_empty_string_returns_empty():
    assert normalize_role_spec("") == {}


def test_zero_int_returns_empty():
    # 0 is falsy - caught before the isinstance checks
    assert normalize_role_spec(0) == {}


# ---------------------------------------------------------------------------
# normalize_role_spec - invalid types (truthy non-str non-dict)
# ---------------------------------------------------------------------------

def test_int_raises_typeerror():
    with pytest.raises(TypeError):
        normalize_role_spec(42)


def test_list_raises_typeerror():
    with pytest.raises(TypeError):
        normalize_role_spec(["sonnet"])


def test_float_raises_typeerror():
    with pytest.raises(TypeError):
        normalize_role_spec(3.14)


def test_typeerror_message_contains_typename():
    with pytest.raises(TypeError, match="list"):
        normalize_role_spec(["model", "opus"])


def test_typeerror_message_contains_int_typename():
    with pytest.raises(TypeError, match="int"):
        normalize_role_spec(99)


# ---------------------------------------------------------------------------
# KNOWN_HARNESSES
# ---------------------------------------------------------------------------

def test_known_harnesses_is_frozenset():
    assert isinstance(KNOWN_HARNESSES, frozenset)


def test_known_harnesses_exact_members():
    expected = frozenset({
        "codex", "gemini", "cursor-agent", "kimi", "pi", "omp", "claude",
    })
    assert KNOWN_HARNESSES == expected


def test_known_harnesses_count():
    assert len(KNOWN_HARNESSES) == 7


# ---------------------------------------------------------------------------
# KNOWN_ROLES
# ---------------------------------------------------------------------------

def test_known_roles_is_frozenset():
    assert isinstance(KNOWN_ROLES, frozenset)


def test_known_roles_exact_members():
    expected = frozenset({
        "conductor", "investigator", "architect", "orchestration-planner",
        "engineer", "debugger", "qa-engineer", "skeptic", "security-auditor",
    })
    assert KNOWN_ROLES == expected


def test_known_roles_count():
    assert len(KNOWN_ROLES) == 9
