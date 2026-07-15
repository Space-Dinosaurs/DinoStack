#!/usr/bin/env python3
"""
Purpose: Shared activation guard for agentic-engineering Python hooks. Decides
         whether the methodology is ACTIVE for a given project cwd via pure
         filesystem stat checks (no JSON parse on the hot path). Every enforce-*
         hook calls is_active(cwd) as its first side-effect gate: when a project
         is dormant the hook exits 0 with no output, so the methodology's
         globally-registered hooks become instant no-ops in projects that never
         opted in.

Activation layers (first hit wins), evaluated per candidate root while walking
from cwd up to the outermost git root (so worktree-isolated subagents inherit
the project root's activation instead of going silently dormant):
  1. <root>/.agentic/active         (explicit /ds activate)         -> ACTIVE
  2. <root>/.agentic/active.session (explicit /ds activate --session)-> ACTIVE
  3. <root>/.agentic/dormant        (explicit /ds deactivate tombstone)-> DORMANT
  4. <root>/.agentic/  (dir exists) (zero-migration auto-detect)     -> ACTIVE
  5. any candidate root listed in ~/.agentic/activation.list (allowlist) -> ACTIVE
  6. none of the above                                              -> DORMANT

Worktree-zone hardening: candidate roots at or below
<outermost-git-root>/.agentic/worktrees/ are subagent scratch space, not
operator boundaries. Markers at those levels (active, active.session, dormant)
are IGNORED and the walk continues up: a subagent must not be able to disable
enforce-* hooks by writing its own dormant tombstone, and an active marker in
scratch space is meaningless. The project root's own markers always decide.

Public API:
  is_active(cwd) -> bool
    True  = methodology active (hook should run).
    False = dormant (hook should no-op / exit 0).
    FAIL-ACTIVE: an indeterminate cwd (None / non-str / blank) OR any stat/read
    error returns True. A guard bug must never silently kill methodology for
    active users (plan R3); an over-active guard merely preserves prior
    always-on behavior.

Upstream deps: Python 3 stdlib only (os, hashlib, sys). No JSON, no imports off the hot path beyond the dormant-notice branch.

Downstream consumers: all hooks/enforce-*.py, loaded via SourceFileLoader from
                      hooks/lib/activation.py (sibling-of-parent path).

Failure modes: never raises. Returns True on any error (fail-ACTIVE).
Performance: <10ms - at most 4 os.path.exists calls plus one small line scan of
             ~/.agentic/activation.list (only reached when no project marker).
"""

from __future__ import annotations

import hashlib
import os
import sys

# Process-level short-circuit for dormant-notice emission failures. If writing
# the per-project marker fails (e.g., permissions), repeated is_active() calls
# would otherwise spam stderr on every hook invocation. We record the failed
# cwd key so the warning is attempted only once per process for a given project.
_DORMANT_NOTICE_ATTEMPTED: set[str] = set()


def _dormant_notice_path(cwd: str, kind: str = "dormant") -> str:
    """Return the per-project dormant-notice marker path in ~/.agentic/.

    The marker lives outside the project directory so a repo-local process
    cannot suppress the notice by deleting or overwriting it. *kind*
    ("dormant" tombstone vs "inactive" never-opted-in) keys distinct markers so
    the two notices are emitted independently once each.
    """
    try:
        key = hashlib.sha256(os.path.realpath(cwd).encode("utf-8")).hexdigest()
        return os.path.join(os.path.expanduser("~"), ".agentic", f".{kind}-notice-{key}")
    except Exception:
        # Last-ditch fallback under ~/.agentic; notice emission still attempts.
        return os.path.join(os.path.expanduser("~"), ".agentic", f".{kind}-notice-fallback")


def _emit_dormant_notice(cwd: str, kind: str = "dormant") -> None:
    """Print an unsuppressable activation notice once per project to stderr.

    Tracks "already noticed" in ~/.agentic/ so a repo-local attacker cannot
    silence it. Any marker creation failure still leaves the warning printed,
    but the failure is recorded in a process-level set so a repeated failure
    does not spam stderr on every subsequent hook call.

    *kind* selects the message: "dormant" (explicit .agentic/dormant tombstone)
    or "inactive" (project simply never opted in - no marker, no allowlist
    entry). Both mean the enforcement hooks are no-ops, but they are distinct
    situations an operator may want to act on differently, so each is surfaced
    once per project independently.
    """
    notice_path = _dormant_notice_path(cwd, kind)
    try:
        if os.path.exists(notice_path):
            return
    except Exception:
        pass

    # Rate-limit failed emission attempts to once per process per project+kind.
    cwd_key = f"{kind}:{os.path.realpath(cwd)}"
    if cwd_key in _DORMANT_NOTICE_ATTEMPTED:
        return
    _DORMANT_NOTICE_ATTEMPTED.add(cwd_key)

    try:
        if kind == "inactive":
            msg = (
                f"AGENTIC-ENGINEERING INACTIVE: enforcement hooks are no-ops for {cwd} "
                "- this project has never been activated (no .agentic/ marker, no "
                "allowlist entry). Run `/ds activate` to enable the methodology."
            )
        else:
            msg = (
                f"AGENTIC-ENGINEERING DORMANT: enforcement hooks disabled for {cwd} "
                "by .agentic/dormant tombstone."
            )
        print(msg, file=sys.stderr)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(notice_path), exist_ok=True)
        with open(notice_path, "w", encoding="utf-8"):
            pass
    except Exception:
        pass


def _git_bound(cwd: str) -> str | None:
    """Return the outermost ancestor (incl. cwd) that contains a .git entry.

    Worktrees carry a `.git` *file* at the worktree top while the main
    checkout carries a `.git` *directory*; the activation markers
    (`.agentic/active`, `.agentic/dormant`, ...) live at the main checkout,
    i.e. the outermost `.git`-bearing ancestor. Bounding the ancestor walk at
    that outermost root keeps subagents running inside the mandated
    `<repo>/.agentic/worktrees/<branch>/` isolation path from escaping above
    the project and accidentally matching an unrelated `~/.agentic` directory
    (which would otherwise auto-detect ACTIVE for every dormant project under
    the home dir). Returns None when no ancestor is a git checkout (callers
    then check cwd only, preserving legacy exact-cwd behavior).
    """
    try:
        cur = os.path.realpath(cwd)
        top: str | None = None
        while True:
            if os.path.exists(os.path.join(cur, ".git")):
                top = cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        return top
    except Exception:
        return None


def _iter_roots(cwd: str) -> list[str]:
    """Candidate project roots from cwd up to the outermost git root (inclusive).

    With no git checkout anywhere above cwd, returns ``[realpath(cwd)]`` so the
    legacy exact-cwd behavior is preserved and the walk never escapes into an
    ancestor ``.agentic`` dir (e.g. ``~/.agentic``).
    """
    try:
        start = os.path.realpath(cwd)
        bound = _git_bound(cwd)
        roots: list[str] = []
        cur = start
        while True:
            roots.append(cur)
            if bound is None or cur == bound:
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        return roots
    except Exception:
        return [cwd]


def _in_worktree_zone(root: str, bound: str | None) -> bool:
    """True if *root* is at or below ``<bound>/.agentic/worktrees/``.

    Subagent isolation worktrees are scratch space, never an operator
    boundary: activation markers found there (active, active.session,
    dormant) must be ignored so a subagent cannot self-disable the enforce-*
    hooks by writing a tombstone inside its own worktree. Only the
    ``.agentic/worktrees`` convention is special-cased; no other worktree
    location exists in the methodology. Returns False when there is no git
    bound (no checkout above cwd) or on any path error.
    """
    if bound is None:
        return False
    try:
        rel = os.path.relpath(root, bound)
    except Exception:
        return False
    parts = rel.split(os.sep)
    return len(parts) >= 2 and parts[0] == ".agentic" and parts[1] == "worktrees"

def _decide_at(root: str) -> bool | None:
    """Return True/False/None for activation markers at a single candidate root.

    Precedence mirrors the legacy single-cwd order so the nearest ancestor
    wins: ``active`` > ``active.session`` > ``dormant`` > ``.agentic``-dir
    auto-detect. Returns None when this root carries no marker (walk up).
    """
    agentic = os.path.join(root, ".agentic")
    if os.path.exists(os.path.join(agentic, "active")):
        return True
    if os.path.exists(os.path.join(agentic, "active.session")):
        return True
    if os.path.exists(os.path.join(agentic, "dormant")):
        # Explicit tombstone overrides auto-detect. Emit an unsuppressable
        # notice the first time this project is observed as dormant, keyed on
        # the root where the tombstone was found (the real project root, not
        # the worktree subdir a subagent may be running in).
        try:
            _emit_dormant_notice(root)
        except Exception:
            pass
        return False
    if os.path.isdir(agentic):
        return True  # zero-migration auto-detect
    return None


def _in_allowlist(roots) -> bool:
    """True if any candidate root realpath matches a realpath'd allowlist line.

    The flat .list is the shell-guard fast path; the structured activation.json
    is managed by bin/_activation.py but not read here (hot path stays
    parse-free). Any error -> False (allowlist simply doesn't match; the
    caller's fail-ACTIVE only applies to the top-level guard, not to a missing
    optional allowlist).
    """
    try:
        list_path = os.path.join(os.path.expanduser("~"), ".agentic", "activation.list")
        targets = {os.path.realpath(r) for r in roots}
        with open(list_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and os.path.realpath(line) in targets:
                    return True
    except Exception:
        pass
    return False


def is_active(cwd) -> bool:
    """Return True if the methodology is active for *cwd* (see module docstring).

    Walks from *cwd* up to the outermost git root (inclusive) so subagents
    running inside ``<repo>/.agentic/worktrees/<branch>/`` inherit the project
    root's activation markers/allowlist instead of silently going dormant.
    """
    try:
        if not isinstance(cwd, str) or not cwd.strip():
            return True  # indeterminate cwd -> fail ACTIVE
        clean = cwd.strip()
        roots = _iter_roots(clean)
        bound = _git_bound(clean)
        for root in roots:
            if _in_worktree_zone(root, bound):
                continue  # subagent scratch space: markers here are ignored
            try:
                decision = _decide_at(root)
            except Exception:
                decision = None
            if decision is not None:
                return decision
        if _in_allowlist(roots):
            return True
        # Never activated: no marker at any root and no allowlist entry. Unlike
        # the explicit-tombstone path (_decide_at), this case previously exited
        # silently, so an operator who expected the methodology to be on got no
        # signal that every enforcement hook is a no-op here. Emit a distinct
        # "inactive" notice once per project, keyed on the project root (the
        # outermost git root, not a worktree subdir a subagent runs in).
        try:
            notice_root = bound or clean
            _emit_dormant_notice(notice_root, kind="inactive")
        except Exception:
            pass
        return False  # dormant (never activated)
    except Exception:
        return True  # fail ACTIVE - never silently kill methodology
