"""
Purpose: Resolves the repo-root directory to anchor `.agentic/` state
         writes, instead of trusting the harness-supplied payload `cwd`
         verbatim. Prevents phantom `.agentic/` trees being written at
         whatever directory a stray `cd` (or a drifted payload `cwd`)
         happens to leave the process in. Mirrors hooks/lib/repo-root.js.

Public API: resolve_agentic_cwd_with_diagnostics(start_dir) -> dict with
                "root", "drift_levels", "found_git_ancestor"
            resolve_agentic_cwd(start_dir) -> str

Upstream deps: os.path (realpath, exists, join, dirname)

Downstream consumers: hooks/lib/loop_guard.py, hooks/lib/enforcement_log.py,
    hooks/enforce-no-abdication.py, hooks/enforce-turn-shape.py,
    hooks/enforce-skeptic-round-cap.py, hooks/enforce-planning-artifact-spawn.py,
    bin/ds-status, bin/ds-cost, bin/ds-memory (all three via a lazy
    importlib.util dynamic loader, not a direct import)

Failure modes: never raises. Any OSError (EACCES/ENOENT) while probing a
    given level is treated as "not found here, keep walking". If no
    `.git` ancestor is found within MAX_DEPTH, returns the realpath'd
    start_dir unchanged with found_git_ancestor=False - callers must treat
    that as a resolution failure and SKIP the write, never silently write
    at the fallback path.

Performance: a handful of os.path.exists calls per invocation (at most
    MAX_DEPTH), no subprocess, no network.
"""

from __future__ import annotations

import os

MAX_DEPTH = 64


def resolve_agentic_cwd_with_diagnostics(start_dir: str) -> dict:
    """Realpath-pin start_dir and walk up looking for a `.git` entry
    (file or directory - EXISTENCE ONLY, never os.path.isdir()).
    A linked git worktree's `.git` is a FILE, not a directory, so a
    dir-only check fails in the most common execution environment here.
    """
    try:
        real = os.path.realpath(start_dir)
    except OSError:
        real = start_dir

    current = real
    drift_levels = 0

    for _ in range(MAX_DEPTH + 1):
        has_git = False
        try:
            has_git = os.path.exists(os.path.join(current, ".git"))
        except OSError:
            has_git = False

        if has_git:
            return {
                "root": current,
                "drift_levels": drift_levels,
                "found_git_ancestor": True,
            }

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
        drift_levels += 1
        if drift_levels > MAX_DEPTH:
            break

    return {"root": real, "drift_levels": 0, "found_git_ancestor": False}


def resolve_agentic_cwd(start_dir: str) -> str:
    return resolve_agentic_cwd_with_diagnostics(start_dir)["root"]
