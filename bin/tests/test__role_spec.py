#!/usr/bin/env python3
"""
Dedicated unit tests for bin/_role_spec.py.

Covers normalize_role_spec() exhaustively against its real behavior (read
from source), plus frozenset identity/membership checks for KNOWN_HARNESSES
and KNOWN_ROLES.

Test coverage (25 tests):
  - normalize_role_spec scalar input: plain string, arbitrary value, whitespace-truthy
  - normalize_role_spec mapping input: all known keys, partial subsets, unknown-key
    dropping, mixed known/unknown, all-unknown -> {}, falsy values preserved
  - normalize_role_spec falsy input (None, "", {}, 0) -> {}
  - normalize_role_spec non-str/non-dict (int, list, float) -> TypeError + message
  - KNOWN_HARNESSES / KNOWN_ROLES: frozenset type, exact membership, counts (7 / 9)
  - looks_like_secret: required True/False vectors (key-shaped ones built at
    runtime so secret scanners do not flag this file)
  - validate_backends: shape, key, value and role-reference errors; values and
    key-shaped names are never echoed

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
resolve_reviewer_model = _mod.resolve_reviewer_model
KNOWN_HARNESSES = _mod.KNOWN_HARNESSES
KNOWN_ROLES = _mod.KNOWN_ROLES
looks_like_secret = _mod.looks_like_secret
validate_backends = _mod.validate_backends


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
        "opencode", "copilot",
    })
    assert KNOWN_HARNESSES == expected


def test_known_harnesses_count():
    assert len(KNOWN_HARNESSES) == 9


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


# ---------------------------------------------------------------------------
# D-3: per-role reviewer models (resolve_reviewer_model).
# ---------------------------------------------------------------------------

def test_reviewer_by_role_hit():
    rev = {"by_role": {"engineer": "cx/gpt-5.5"}, "pool": ["glm/glm-5.2"]}
    assert resolve_reviewer_model("engineer", "kimi/kimi-k2.7", rev) == "cx/gpt-5.5"


def test_reviewer_by_role_miss_falls_to_pool():
    rev = {"by_role": {"architect": "cc/claude-opus-4-8"},
           "pool": ["glm/glm-5.2", "cx/gpt-5.5"]}
    # engineer not in by_role -> first distinct pool entry
    assert resolve_reviewer_model("engineer", "kimi/kimi-k2.7", rev) == "glm/glm-5.2"


def test_reviewer_by_role_equal_author_falls_through():
    # by_role picks the author's own model -> must skip to pool
    rev = {"by_role": {"engineer": "kimi/kimi-k2.7"},
           "pool": ["kimi/kimi-k2.7", "cx/gpt-5.5"]}
    assert resolve_reviewer_model("engineer", "kimi/kimi-k2.7", rev) == "cx/gpt-5.5"


def test_reviewer_by_role_mapping_form():
    rev = {"by_role": {"engineer": {"model": "cx/gpt-5.5", "effort": "high"}}}
    assert resolve_reviewer_model("engineer", "kimi/kimi-k2.7", rev) == "cx/gpt-5.5"


def test_reviewer_by_task_after_by_role_miss():
    rev = {"by_role": {"architect": "x"},
           "by_task": {"security": "cc/claude-opus-4-8", "default": "glm/glm-5.2"}}
    assert resolve_reviewer_model("engineer", "kimi", rev, task_kind="security")         == "cc/claude-opus-4-8"
    # unknown task_kind -> by_task default
    assert resolve_reviewer_model("engineer", "kimi", rev, task_kind="perf")         == "glm/glm-5.2"


def test_reviewer_pool_then_fallback():
    rev = {"pool": ["kimi"], "fallback": "cx/gpt-5.5"}
    # only pool entry equals author -> fallback
    assert resolve_reviewer_model("engineer", "kimi", rev) == "cx/gpt-5.5"


def test_reviewer_absent_config_returns_none():
    assert resolve_reviewer_model("engineer", "kimi", None) is None
    assert resolve_reviewer_model("engineer", "kimi", {}) is None
    # no source yields a distinct model
    assert resolve_reviewer_model("engineer", "kimi", {"pool": ["kimi"]}) is None


# D-3 review: strategy handling (round-robin / by-task / distinct-from-author).

def test_reviewer_strategy_by_task_prioritized():
    rev = {"strategy": "by-task",
           "by_task": {"security": "cx/gpt-5.5", "default": "glm/glm-5.2"},
           "pool": ["kimi/kimi-k2.7"]}
    assert resolve_reviewer_model("engineer", "author", rev,
                                  task_kind="security") == "cx/gpt-5.5"
    # unknown kind -> by_task default
    assert resolve_reviewer_model("engineer", "author", rev,
                                  task_kind="perf") == "glm/glm-5.2"
    # no kind -> falls to default then pool
    assert resolve_reviewer_model("engineer", "author", rev) == "glm/glm-5.2"


def test_reviewer_strategy_round_robin_rotates():
    rev = {"strategy": "round-robin",
           "pool": ["a", "b", "c"]}
    got = [resolve_reviewer_model("engineer", "author", rev, rotation_index=i)
           for i in range(4)]
    assert got == ["a", "b", "c", "a"]


def test_reviewer_round_robin_skips_author():
    rev = {"strategy": "round-robin", "pool": ["a", "b"]}
    # start index points at the author's own model -> must skip to the next
    assert resolve_reviewer_model("engineer", "a", rev, rotation_index=0) == "b"


def test_reviewer_round_robin_no_index_degrades_gracefully():
    rev = {"strategy": "round-robin", "pool": ["a", "b"]}
    # None index -> starts at 0, first distinct entry
    assert resolve_reviewer_model("engineer", "author", rev) == "a"


def test_reviewer_by_role_overrides_strategy():
    rev = {"strategy": "round-robin",
           "by_role": {"engineer": "cx/gpt-5.5"},
           "pool": ["a", "b"]}
    assert resolve_reviewer_model("engineer", "author", rev,
                                  rotation_index=1) == "cx/gpt-5.5"


def test_reviewer_default_strategy_unchanged():
    # No strategy -> distinct-from-author: first distinct pool entry.
    rev = {"pool": ["author", "glm/glm-5.2"], "fallback": "cx/gpt-5.5"}
    assert resolve_reviewer_model("engineer", "author", rev) == "glm/glm-5.2"


# ---------------------------------------------------------------------------
# looks_like_secret / validate_backends (team.yml backend presets)
# ---------------------------------------------------------------------------

def _key(prefix: str, unit: str, n: int) -> str:
    return prefix + unit * n


_SECRET_TRUE = [
    _key("sk-", "a1", 24),
    "x-api-key: " + _key("sk-ant-", "a1", 24),
    "https://h/?key=" + _key("AIza", "b2", 18),
    "Authorization: Bearer " + _key("", "c3", 10),
    "foo=" + _key("", "d4", 20),
]
_SECRET_FALSE = [
    "http://localhost:4000",
    "dinostack-placeholder",
    "true",
    "https://gateway.example.com/v1",
]


@pytest.mark.parametrize("value", _SECRET_TRUE)
def test_looks_like_secret_true_vectors(value):
    assert looks_like_secret(value) is True


@pytest.mark.parametrize("value", _SECRET_FALSE)
def test_looks_like_secret_false_vectors(value):
    assert looks_like_secret(value) is False


def _gateway_roles():
    return {"skeptic": {"harness": "claude", "backend": "gw"}}


def test_validate_backends_accepts_placeholder_preset():
    backends = {"gw": {"env": {
        "ANTHROPIC_BASE_URL": "http://localhost:4000",
        "ANTHROPIC_AUTH_TOKEN": "dinostack-placeholder",
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "true",
    }}}
    assert validate_backends(backends, _gateway_roles()) == []


def test_validate_backends_rejects_key_value_without_echo():
    value = "x-api-key: " + _key("sk-ant-", "a1", 24)
    errors = validate_backends({"gw": {"env": {"ANTHROPIC_AUTH_TOKEN": value}}},
                               _gateway_roles())
    assert errors == ["backends.gw.env.ANTHROPIC_AUTH_TOKEN: value looks like a secret (redacted)"]
    assert all(value not in e and _key("", "a1", 24) not in e for e in errors)


def test_validate_backends_redacts_key_shaped_name_and_env_key():
    secret = _key("sk-", "a1", 24)
    by_name = validate_backends({secret: {"env": {"A": "b"}}}, None)
    by_key = validate_backends({"gw": {"env": {secret: "b"}}}, None)
    assert by_name and by_key
    assert all(secret not in e for e in by_name + by_key)
    assert all("<redacted>" in e for e in by_name + by_key)


def test_validate_backends_none_is_valid():
    assert validate_backends(None, {"skeptic": {"harness": "claude"}}) == []


@pytest.mark.parametrize("backends,fragment", [
    ({"gw": {"env": {"X": 1}}}, "quote it"),
    ({"gw": {"env": {"PATH": "/tmp"}}}, "PATH"),
    ({"gw": {"env": {"X": "y"}, "url": "z"}}, "unknown key"),
    (["gw"], "must be a mapping"),
])
def test_validate_backends_rejects_bad_shapes(backends, fragment):
    errors = validate_backends(backends, None)
    assert any(fragment in e for e in errors), errors


def test_validate_backends_undefined_reference_with_none_backends():
    errors = validate_backends(None, _gateway_roles())
    assert any("roles.skeptic.backend" in e and "not defined" in e for e in errors), errors


def test_validate_backends_rejects_backend_on_non_dispatchable_role():
    errors = validate_backends({"gw": {"env": {"A": "b"}}},
                               {"investigator": {"harness": "claude", "backend": "gw"}})
    assert any("roles.investigator.backend" in e and "dispatchable" in e for e in errors), errors
