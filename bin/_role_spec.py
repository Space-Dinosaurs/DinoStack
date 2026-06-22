"""
Purpose: Shared normalizer for role spec values used in agentic config files.
         Converts scalar-or-mapping role spec entries into a canonical dict
         so both agentic-configure and agentic-team share identical parse logic.

Public API: normalize_role_spec(value) -> dict
            Input is either a plain string (scalar model id) or a dict with
            at least a "model" key. Returns a dict with whichever of "model",
            "effort", "reasoning" are present; absent keys are not included.
            Returns {} for falsy input.

Upstream deps: Python 3.11 stdlib only.

Downstream consumers: bin/agentic-configure, bin/agentic-team.

Failure modes: Invalid types (not str, not dict, not None/falsy) raise
               TypeError with a descriptive message. Missing "model" key in a
               dict input returns the dict minus unknown keys (caller validates
               schema completeness).

Performance: Pure in-memory normalization; no I/O.
"""

from __future__ import annotations

_KNOWN_KEYS = frozenset({"model", "effort", "reasoning"})


def normalize_role_spec(value: object) -> dict:
    """Normalize a scalar-or-mapping role spec value to a canonical dict.

    Parameters
    ----------
    value:
        - str  -> {"model": value}
        - dict -> filtered to known keys ("model", "effort", "reasoning");
                  keys with falsy values are preserved as-is (caller decides)
        - None / empty string / empty dict -> {}

    Returns
    -------
    dict with subset of keys {"model", "effort", "reasoning"}.
    """
    if not value:
        return {}
    if isinstance(value, str):
        return {"model": value}
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k in _KNOWN_KEYS}
    raise TypeError(
        f"normalize_role_spec: expected str or dict, got {type(value).__name__!r}"
    )
