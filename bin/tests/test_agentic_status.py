#!/usr/bin/env python3
"""
Regression tests for bin/agentic-status: _is_pi_omp_harness predicate.

Covers PR #249 review M2: the predicate must test 4 env vars
(PI_HARNESS, OMP_HARNESS, OH_MY_PI_HARNESS, AGENTIC_HARNESS)
and treat "truthy" as "set to a non-empty value".

Run with: python3 -m pytest bin/tests/test_agentic_status.py -x
       or: python3 bin/tests/test_agentic_status.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_BIN_PATH = Path(__file__).parent.parent / "agentic-status"
_loader = importlib.machinery.SourceFileLoader("agentic_status", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_status", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-status from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_is_pi_omp_harness = _mod._is_pi_omp_harness
PI_OMP_HARNESS_ENV_VARS = _mod.PI_OMP_HARNESS_ENV_VARS

_EXPECTED_VARS = ("PI_HARNESS", "OMP_HARNESS", "OH_MY_PI_HARNESS", "AGENTIC_HARNESS")


def test_constant_has_four_vars():
    assert tuple(PI_OMP_HARNESS_ENV_VARS) == _EXPECTED_VARS


def _clear_harness_env(monkeypatch):
    for k in _EXPECTED_VARS:
        monkeypatch.delenv(k, raising=False)


def test_each_var_individually_true(monkeypatch):
    for k in _EXPECTED_VARS:
        _clear_harness_env(monkeypatch)
        monkeypatch.setenv(k, "pi")
        assert _is_pi_omp_harness() is True, f"{k}=pi should be truthy"


def test_none_set_is_false(monkeypatch):
    _clear_harness_env(monkeypatch)
    assert _is_pi_omp_harness() is False


def test_empty_string_is_false(monkeypatch):
    _clear_harness_env(monkeypatch)
    for k in _EXPECTED_VARS:
        monkeypatch.setenv(k, "")
    assert _is_pi_omp_harness() is False


def test_one_empty_other_set_is_true(monkeypatch):
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("PI_HARNESS", "")
    monkeypatch.setenv("OMP_HARNESS", "omp")
    assert _is_pi_omp_harness() is True


def main() -> int:
    """Bare-script entry: run only the import-free sanity test.

    The monkeypatch-based tests require the pytest fixture and run via
    `python3 -m pytest bin/tests/test_agentic_status.py -x`. This script-mode
    fallback confirms the module loads and the constant is correct.
    """
    failures = 0
    try:
        test_constant_has_four_vars()
        print("PASS  test_constant_has_four_vars")
    except AssertionError as exc:
        print(f"FAIL  test_constant_has_four_vars: {exc}")
        failures += 1
    print("5 tests registered; run via `python3 -m pytest` for the full suite")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
