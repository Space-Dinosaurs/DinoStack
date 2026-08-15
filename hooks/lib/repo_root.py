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
    start_dir unchanged with found_git_ancestor=False.

    ROUND-2 REWORK (adversarial review Major 6): this file previously
    stated an UNCONDITIONAL "callers must SKIP, never silently write at
    the fallback path" contract that no plain `resolve_agentic_cwd()`
    caller in the repo actually implemented - hooks/lib/enforcement_log.py,
    hooks/lib/loop_guard.py, and hooks/enforce-turn-shape.py (at last
    audit) all use the returned path directly and discard
    found_git_ancestor. That is a deliberate, reviewed choice, not an
    unfixed bug: these are enforcement-counter and log-append call sites
    whose worst case on the rare "no .git ancestor anywhere up the tree"
    path (e.g. a harness cwd of $HOME or /tmp - NOT the far more common
    "drifted into a subdirectory of a real repo" case, which
    found_git_ancestor=True already handles correctly) is a degraded,
    recoverable state, not silent corruption of real project state.

    ROUND-3 REWORK (adversarial review Minor 2): the framing above ("a
    non-repo location") understated where the fallback root actually
    lands for the common $HOME case specifically - it is NOT some inert
    throwaway scratch directory. When start_dir has no `.git` ancestor
    anywhere up to and including $HOME, the fallback root IS $HOME
    itself, and these callers' `<root>/.agentic/...` writes then land
    inside the REAL global `~/.agentic/` store (identity.yml,
    session-log/, etc.) - still "degraded, recoverable" in the sense that
    nothing here corrupts a real PROJECT's state (the correctness
    property this section defends), but not the low-stakes "harmless
    scratch write" the prior wording implied. Two callers genuinely DO
    skip on
    found_git_ancestor=False because a write at the wrong location would
    actively corrupt cross-session state: hooks/enforce-skeptic-round-
    cap.py (a round counter) and hooks/session-start-wrap.sh (a shell
    caller of hooks/lib/repo-root.sh, guards every write on
    `-n "$resolved_root"`, zero fallback). bin/ds-identity's
    `write-hook`/`resolve-hook` (the Stop-hook session-log telemetry path,
    which fires on every turn) was added to this stricter category in the
    same round-2 rework: telemetry misattributed to a phantom non-repo
    `.agentic/session-log/` is a correctness bug (wrong developer_id/
    project_slug), not a merely degraded artifact. Callers needing the
    SKIP discipline must consult found_git_ancestor explicitly via
    resolve_agentic_cwd_with_diagnostics and refuse the write themselves
    when it is False - this module never enforces that policy on a
    caller's behalf.

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
