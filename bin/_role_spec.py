"""
Purpose: Shared normalizer for role spec values used in agentic config files.
         Converts scalar-or-mapping role spec entries into a canonical dict
         so both agentic-configure and agentic-team share identical parse logic.

Public API: normalize_role_spec(value) -> dict
            Input is either a plain string (scalar model id) or a dict with
            at least a "model" key. Returns a dict with whichever of "model",
            "effort", "reasoning" are present; absent keys are not included.
            Returns {} for falsy input.

            resolve_reviewer_model(authored_role, author_model, reviewers,
                                   task_kind=None, rotation_index=None) -> str | None
            Resolve the adversarial-reviewer model for an authored role,
            honoring reviewers.strategy (distinct-from-author | by-task |
            round-robin) with a by_role override and a distinct-from-author
            guarantee. Returns None when nothing resolves.

            KNOWN_HARNESSES / KNOWN_ROLES: frozensets of valid names.

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
    rotation_index: int | None = None,
) -> str | None:
    """Resolve the adversarial-reviewer model for *authored_role*.

    Honors ``reviewers.strategy`` (default ``distinct-from-author``):

    * ``by_role[<authored_role>]`` is always checked FIRST regardless of
      strategy -- an explicit per-role reviewer overrides the strategy.
    * ``distinct-from-author`` (default): first ``pool`` entry whose model
      differs from *author_model*, else ``fallback``.
    * ``by-task``: ``by_task[task_kind]`` then ``by_task['default']``, then the
      distinct-from-author pool/fallback chain.
    * ``round-robin``: rotate through ``pool`` starting at *rotation_index*
      (mod len), skipping the author's own model, then ``fallback``. The caller
      supplies the durable index (see agentic-team's rotation cursor); when it
      is None round-robin degrades to distinct-from-author ordering.

    The distinct-from-author guarantee is applied at every step: a candidate
    equal to *author_model* is skipped. Returns None when nothing resolves --
    the caller then omits the reviewer model and the reviewer uses its session
    default. *reviewers* is the parsed ``reviewers:`` mapping; a non-mapping
    (or None) returns None.
    """
    if not isinstance(reviewers, dict):
        return None

    def _model_of(spec: object) -> str | None:
        if not spec:
            return None
        # Malformed config (e.g. int/float in pool/by_role/by_task) must not
        # raise TypeError -- normalize_role_spec has no contract to handle it,
        # and the caller wants a clean None rather than a crash.
        try:
            norm = normalize_role_spec(spec)
        except (TypeError, ValueError):
            return None
        if not isinstance(norm, dict):
            return None
        m = norm.get("model")
        return m if isinstance(m, str) and m else None

    author = author_model if isinstance(author_model, str) else None
    strategy = reviewers.get("strategy") or "distinct-from-author"

    # 0. Per-role reviewer overrides any strategy.
    by_role = reviewers.get("by_role")
    if isinstance(by_role, dict):
        cand = _model_of(by_role.get(authored_role))
        if cand and cand != author:
            return cand

    pool = reviewers.get("pool")
    pool_list = list(pool) if isinstance(pool, (list, tuple)) else []

    def _first_distinct(entries):
        for entry in entries:
            cand = _model_of(entry)
            if cand and cand != author:
                return cand
        return None

    if strategy == "by-task":
        by_task = reviewers.get("by_task")
        if isinstance(by_task, dict):
            if task_kind:
                cand = _model_of(by_task.get(task_kind))
                if cand and cand != author:
                    return cand
            cand = _model_of(by_task.get("default"))
            if cand and cand != author:
                return cand
        cand = _first_distinct(pool_list)
        if cand:
            return cand
    elif strategy == "round-robin":
        if pool_list:
            n = len(pool_list)
            start = (rotation_index or 0) % n
            ordered = [pool_list[(start + i) % n] for i in range(n)]
            cand = _first_distinct(ordered)
            if cand:
                return cand
    else:  # distinct-from-author (default)
        # by_task is still consulted when a task_kind is supplied, preserving
        # the prior precedence, then the pool.
        by_task = reviewers.get("by_task")
        if task_kind and isinstance(by_task, dict):
            cand = _model_of(by_task.get(task_kind))
            if cand and cand != author:
                return cand
            cand = _model_of(by_task.get("default"))
            if cand and cand != author:
                return cand
        cand = _first_distinct(pool_list)
        if cand:
            return cand

    # Fallback (all strategies).
    cand = _model_of(reviewers.get("fallback"))
    if cand and cand != author:
        return cand
    return None
