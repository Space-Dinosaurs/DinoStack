"""
Purpose: Shared normalizer for role spec values used in agentic config files.
         Converts scalar-or-mapping role spec entries into a canonical dict
         so both ds-configure and ds-team share identical parse logic.

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

            looks_like_secret(value: str) -> bool
            True when a string contains a key-shaped token anywhere in it
            (a known key prefix, a Bearer credential, or a 32+ character
            alphanumeric run with a letter and a digit). A floor, not a
            scanner.

            validate_backends(backends, roles) -> list[str]
            Validate team.yml's top-level `backends:` presets and every
            roles.<role>.backend reference. Never raises; messages never
            include an env value.

Upstream deps: Python 3.11 stdlib only. validate_backends reads
               _DISPATCHABLE_ROLES from hooks/enforce-background-spawn.py
               (loaded by path, only when a role carries a backend).

Downstream consumers: bin/ds-configure, bin/ds-team.

Failure modes: Invalid types (not str, not dict, not None/falsy) raise
               TypeError with a descriptive message. Missing "model" key in a
               dict input returns the dict minus unknown keys (caller validates
               schema completeness).

Performance: Pure in-memory normalization; no I/O.
"""

from __future__ import annotations

import re
from pathlib import Path

_KNOWN_KEYS = frozenset({"model", "effort", "reasoning"})

# Canonical set of known harness labels.  Single source of truth imported by
# both ds-configure and ds-team; neither file declares its own copy.
KNOWN_HARNESSES: frozenset[str] = frozenset({
    "codex", "gemini", "cursor-agent", "kimi", "pi", "omp", "claude",
    "opencode", "copilot",
})

# Canonical set of known role names (mirrors ROLES in ds-configure).
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
      supplies the durable index (see ds-team's rotation cursor); when it
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
        except (TypeError, ValueError) as exc:
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


_SECRET_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-|sk_|ghp_|gho_|ghs_|ghu_|github_pat_|xoxb-|xoxp-|AKIA|AIza)"
    r"[A-Za-z0-9_\-]{16,}"
)
_SECRET_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}")
_SECRET_SPLIT_RE = re.compile(r"[^A-Za-z0-9+_]+")
_BACKEND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def looks_like_secret(value: str) -> bool:
    """Return True when *value* contains a key-shaped token anywhere in it."""
    if _SECRET_PREFIX_RE.search(value) or _SECRET_BEARER_RE.search(value):
        return True
    for piece in _SECRET_SPLIT_RE.split(value):
        if (
            len(piece) >= 32
            and any(c.isalpha() for c in piece)
            and any(c.isdigit() for c in piece)
        ):
            return True
    return False


def _dispatchable_roles() -> frozenset[str] | None:
    """Return the hook's _DISPATCHABLE_ROLES, or None when it cannot load."""
    try:
        import importlib.machinery as _im
        import importlib.util as _ilu

        hook_path = (
            Path(__file__).resolve().parent.parent / "hooks" / "enforce-background-spawn.py"
        )
        loader = _im.SourceFileLoader("_ds_enforce_background_spawn", str(hook_path))
        spec = _ilu.spec_from_loader("_ds_enforce_background_spawn", loader)
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        loader.exec_module(mod)
        return frozenset(mod._DISPATCHABLE_ROLES)
    except Exception:
        return None


def validate_backends(backends: object, roles: object) -> list[str]:
    """Validate team.yml `backends:` presets and roles.<role>.backend references.

    Returns a list of error strings (empty when valid). Never raises, and no
    message ever includes an env value; a name or env key that itself looks
    like a secret is redacted.
    """
    errors: list[str] = []
    defined: set[str] = set()

    if backends is not None and not isinstance(backends, dict):
        errors.append("backends: must be a mapping of preset name -> {env: {...}}")
        backends = None

    for name, preset in (backends or {}).items():
        if not isinstance(name, str) or looks_like_secret(name):
            label = "backends.<redacted>"
            errors.append(f"{label}: preset name looks like a secret (redacted)")
            continue
        label = f"backends.{name}"
        defined.add(name)
        if not _BACKEND_NAME_RE.match(name):
            errors.append(
                f"{label}: invalid preset name (use lowercase letters, digits, '-' or '_')"
            )
        if not isinstance(preset, dict):
            errors.append(f"{label}: must be a mapping with a single 'env' key")
            continue
        extra = sorted(str(k) for k in preset if k != "env")
        if extra:
            errors.append(f"{label}: unknown key(s) {', '.join(extra)} (only 'env' is allowed)")
        env = preset.get("env")
        if not isinstance(env, dict):
            errors.append(f"{label}.env: must be a mapping of VAR -> \"string\"")
            continue
        for key, value in env.items():
            if not isinstance(key, str) or looks_like_secret(key):
                errors.append(f"{label}.env.<redacted>: env key looks like a secret (redacted)")
                continue
            if not _ENV_KEY_RE.match(key):
                errors.append(f"{label}.env.{key}: invalid environment variable name")
                continue
            if key == "PATH":
                errors.append(f"{label}.env.PATH: PATH cannot be set by a backend preset")
                continue
            if not isinstance(value, str):
                errors.append(
                    f"{label}.env.{key}: value must be a string (quote it in team.yml)"
                )
                continue
            if looks_like_secret(value):
                errors.append(f"{label}.env.{key}: value looks like a secret (redacted)")

    if not isinstance(roles, dict):
        return errors
    dispatchable: frozenset[str] | None = None
    for role, spec in roles.items():
        if not isinstance(spec, dict) or "backend" not in spec:
            continue
        ref = spec.get("backend")
        if not isinstance(ref, str) or not ref:
            errors.append(f"roles.{role}.backend: must be a non-empty preset name")
            continue
        if ref not in defined:
            errors.append(
                f"roles.{role}.backend: preset is not defined under backends: "
                f"in the global ~/.agentic/team.yml"
            )
        if dispatchable is None:
            dispatchable = _dispatchable_roles()
        if dispatchable is None:
            errors.append(
                f"roles.{role}.backend: cannot load the dispatchable-role list "
                f"from hooks/enforce-background-spawn.py"
            )
        elif role not in dispatchable:
            errors.append(
                f"roles.{role}.backend: backend applies only to dispatchable roles "
                f"({', '.join(sorted(dispatchable))})"
            )
    return errors
