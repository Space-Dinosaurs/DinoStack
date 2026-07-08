#!/usr/bin/env python3
"""
Purpose: Shared activation guard for agentic-engineering Python hooks. Decides
         whether the methodology is ACTIVE for a given project cwd via pure
         filesystem stat checks (no JSON parse on the hot path). Every enforce-*
         hook calls is_active(cwd) as its first side-effect gate: when a project
         is dormant the hook exits 0 with no output, so the methodology's
         globally-registered hooks become instant no-ops in projects that never
         opted in.

Activation layers (first hit wins):
  1. <cwd>/.agentic/active         (explicit /ds activate)         -> ACTIVE
  2. <cwd>/.agentic/active.session (explicit /ds activate --session)-> ACTIVE
  3. <cwd>/.agentic/dormant        (explicit /ds deactivate tombstone)-> DORMANT
  4. <cwd>/.agentic/  (dir exists) (zero-migration auto-detect)     -> ACTIVE
  5. cwd listed in ~/.agentic/activation.list (installer allowlist) -> ACTIVE
  6. none of the above                                              -> DORMANT

Public API:
  is_active(cwd) -> bool
    True  = methodology active (hook should run).
    False = dormant (hook should no-op / exit 0).
    FAIL-ACTIVE: an indeterminate cwd (None / non-str / blank) OR any stat/read
    error returns True. A guard bug must never silently kill methodology for
    active users (plan R3); an over-active guard merely preserves prior
    always-on behavior.

Upstream deps: Python 3 stdlib only (os). No JSON, no imports off the hot path.

Downstream consumers: all hooks/enforce-*.py, loaded via SourceFileLoader from
                      hooks/lib/activation.py (sibling-of-parent path).

Failure modes: never raises. Returns True on any error (fail-ACTIVE).
Performance: <10ms - at most 4 os.path.exists calls plus one small line scan of
             ~/.agentic/activation.list (only reached when no project marker).
"""

from __future__ import annotations

import os


def _in_allowlist(cwd: str) -> bool:
    """True if realpath(cwd) matches a realpath'd line in ~/.agentic/activation.list.

    The flat .list is the shell-guard fast path; the structured activation.json
    is managed by bin/_activation.py but not read here (hot path stays parse-free).
    Any error -> False (allowlist simply doesn't match; the caller's fail-ACTIVE
    only applies to the top-level guard, not to a missing optional allowlist).
    """
    try:
        list_path = os.path.join(os.path.expanduser("~"), ".agentic", "activation.list")
        target = os.path.realpath(cwd)
        with open(list_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and os.path.realpath(line) == target:
                    return True
    except Exception:
        pass
    return False


def is_active(cwd) -> bool:
    """Return True if the methodology is active for *cwd* (see module docstring)."""
    try:
        if not isinstance(cwd, str) or not cwd.strip():
            return True  # indeterminate cwd -> fail ACTIVE
        agentic = os.path.join(cwd.strip(), ".agentic")
        if os.path.exists(os.path.join(agentic, "active")):
            return True
        if os.path.exists(os.path.join(agentic, "active.session")):
            return True
        if os.path.exists(os.path.join(agentic, "dormant")):
            return False  # explicit tombstone overrides auto-detect
        if os.path.isdir(agentic):
            return True  # zero-migration auto-detect
        if _in_allowlist(cwd.strip()):
            return True
        return False  # dormant
    except Exception:
        return True  # fail ACTIVE - never silently kill methodology
