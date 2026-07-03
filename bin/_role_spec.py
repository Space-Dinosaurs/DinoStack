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

# Canonical set of known harness labels.  Single source of truth imported by
# both agentic-configure and agentic-team; neither file declares its own copy.
KNOWN_HARNESSES: frozenset[str] = frozenset({
    "codex", "gemini", "cursor-agent", "kimi", "pi", "omp", "claude",
    "opencode", "copilot",
})

# Canonical set of known role names (mirrors ROLES in agentic-configure).
KNOWN_ROLES: frozenset[str] = frozenset({
    "conductor", "investigator", "architect", "orchestration-planner",
    "engineer", "debugger", "qa-engineer", "skeptic", "security-auditor",
})


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


def resolve_reviewer_model(
    authored_role: str,
    author_model: object,
    reviewers: object,
    task_kind: str | None = None,
) -> str | None:
    """Resolve the adversarial-reviewer model for *authored_role*.

    Precedence (first that yields a model distinct from *author_model* wins):

      1. reviewers.by_role[<authored_role>]  -- per-role reviewer (new; D-3)
      2. reviewers.by_task[<task_kind>]      -- when task_kind given
      3. reviewers.pool[*]                   -- first pool entry != author_model
      4. reviewers.fallback                  -- last resort

    The distinct-from-author guarantee is applied at every step: a candidate
    equal to *author_model* is skipped, falling through to the next source.
    Each source value is a scalar-or-mapping role-spec (normalize_role_spec
    extracts its "model"). Returns None when nothing resolves -- the caller
    then omits the reviewer model and the reviewer uses its session default,
    exactly the pre-D-3 behavior when no reviewers config matched.

    *reviewers* is the parsed ``reviewers:`` mapping from role-models.yml.
    Passing a non-mapping (or None) returns None.
    """
    if not isinstance(reviewers, dict):
        return None

    def _model_of(spec: object) -> str | None:
        norm = normalize_role_spec(spec) if spec else {}
        m = norm.get("model")
        return m if isinstance(m, str) and m else None

    author = author_model if isinstance(author_model, str) else None

    # 1. Per-role reviewer (new).
    by_role = reviewers.get("by_role")
    if isinstance(by_role, dict):
        cand = _model_of(by_role.get(authored_role))
        if cand and cand != author:
            return cand

    # 2. Per-task-kind reviewer.
    by_task = reviewers.get("by_task")
    if task_kind and isinstance(by_task, dict):
        cand = _model_of(by_task.get(task_kind))
        if cand and cand != author:
            return cand
        cand = _model_of(by_task.get("default"))
        if cand and cand != author:
            return cand

    # 3. Pool: first entry distinct from the author.
    pool = reviewers.get("pool")
    if isinstance(pool, (list, tuple)):
        for entry in pool:
            cand = _model_of(entry)
            if cand and cand != author:
                return cand

    # 4. Fallback.
    cand = _model_of(reviewers.get("fallback"))
    if cand and cand != author:
        return cand
    return None
