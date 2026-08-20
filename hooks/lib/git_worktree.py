#!/usr/bin/env python3
"""
Purpose: Shared helper that classifies whether a given directory is a
         GENUINE LINKED git worktree of some other repo (as opposed to an
         ordinary subdirectory, a submodule, or an independent nested
         clone). This is the discriminator both enforce-worktree-read.py
         and enforce-worktree-write.py need before they may treat a
         subagent's `cwd` as isolation-worktree-isolated: without it, both
         hooks would (or, in the read guard's case, did) treat ANY proper
         subdirectory of CLAUDE_PROJECT_DIR as worktree-isolated, denying
         legitimate reads/writes from a subagent whose cwd happens to be
         an ordinary repo subdirectory, a submodule, or a nested clone.

         Ported from enforce-worktree-write.py's `_is_git_worktree()`
         (PR #736, feat/enforce-worktree-write-guard-v3,
         commit d8ff78859b96551bb83698e44370669b68a8922d, merged to main
         as a860ac62) into this shared module so both hooks share
         identical semantics instead of two copies drifting.

Public API (module-level functions, no class):
    is_git_worktree(caller_root: str) -> bool
        Returns True iff caller_root's `.git` entry indicates it is a
        GENUINE LINKED git worktree - not a submodule, and not an
        independent nested clone that merely happens to live inside some
        primary_root.

    resolve_worktree_primary_root(caller_root: str) -> str | None
        Given the same `.git`-entry discriminator as is_git_worktree()
        above, returns the PRIMARY checkout root a genuine linked worktree
        was created from (parsed from the `gitdir:` pointer's
        `.../.git/worktrees/<name>` admin-dir path), or None on any
        non-worktree shape, unparseable content, relative-pointer
        resolution failure, or a resolved path that does not exist as a
        real directory with its own `.git`. Added for
        hooks/lib/enforcement_log.py (DS: enforcement-fire-log
        aggregation) so fire-log rows written by a subagent running inside
        an isolation worktree land in the PRIMARY checkout's
        `.agentic/.enforcement-fires.jsonl` instead of a worktree-local
        copy that is discarded when the worktree is removed. Deliberately
        NOT wired into is_git_worktree() or resolve_agentic_cwd() (see
        hooks/lib/repo_root.py) - those two are pinned against the shared
        cross-language fixture hooks/tests/fixtures/repo-root-cases.json,
        whose worktree-shaped cases (worktree-root-git-as-file,
        drift-inside-worktree) intentionally assert resolve_agentic_cwd()
        stops AT the worktree root rather than following the pointer, and
        several OTHER resolve_agentic_cwd() callers (e.g.
        enforce-skeptic-round-cap.py's round counter) may depend on that
        per-worktree scoping; changing it would be a much larger-blast-
        radius change than this ticket's fire-log-only fix calls for.

        A real linked worktree's `.git` is a FILE containing a line of the
        form `gitdir: <path>`, where <path> contains a `/worktrees/`
        segment (it points into the shared repo's
        `.git/worktrees/<name>` admin dir). A submodule's `.git` is also a
        FILE, but its gitdir pointer contains a `/modules/` segment
        instead (`.git/modules/<name>`) - a submodule is not isolation-
        worktree-isolated and callers must treat it as NOT a worktree. A
        plain nested clone (an independent `git init`/`git clone` some
        subagent happened to run inside caller_root's ancestor tree) has
        `.git` as a real DIRECTORY - also not a worktree of the ancestor
        repo.

        Fails to False (treated as NOT a worktree) on any directory-vs-
        file ambiguity, read error, or unparseable content - this
        function only ever NARROWS a caller's deny path, never widens it.
        Callers relying on this for a fail-open enforcement hook must
        preserve that property: False from this function must always map
        to the caller's ALLOW branch, never DENY.

Upstream deps: Python 3 stdlib only (os). No imports of any other
               hooks/lib module. Reads only the `.git` entry directly
               under caller_root (isdir/isfile/open); never writes
               anything, never reads any other path.

Downstream consumers: hooks/enforce-worktree-read.py (via its
                       `_load_is_git_worktree()` dynamic-import wrapper,
                       gating the cross-boundary Read deny path) and
                       hooks/enforce-worktree-write.py (same wrapper
                       pattern, same role for Write/Edit/MultiEdit), both
                       using is_git_worktree() only. hooks/lib/
                       enforcement_log.py's `_load_git_worktree()` dynamic-
                       import wrapper uses resolve_worktree_primary_root()
                       only, to redirect the fire-log write target. Not an
                       enforce-*.py hook itself and not a PreToolUse/Stop
                       entry point - not registered in
                       ~/.claude/settings.json and not subject to
                       bin/ds-doctor's MANAGED_HOOK_BASENAMES or any
                       enforcer subcount (it has no `main()`, is never
                       invoked as a script, and fires on nothing).

Failure modes: Every failure mode below resolves to `return False`
               (never raises to a caller):
    - caller_root's `.git` is a real directory: False (primary checkout's
      own `.git`, or an independent nested clone - not a worktree).
    - caller_root has no `.git` entry at all: False.
    - `.git` exists but is neither a file nor a directory (e.g. a broken
      symlink loop), or cannot be opened/decoded: False (caught by the
      surrounding try/except).
    - `.git` is a file but contains no parseable `gitdir:` line: False.
    - `.git` is a file with a `gitdir:` line whose path contains neither
      `/worktrees/` nor `/modules/`: False (only `/worktrees/` returns
      True; everything else, including this ambiguous case, is False).

    resolve_worktree_primary_root() mirrors this to `return None` on every
    equivalent case, plus: the `gitdir:` path lacks a `.git/worktrees/`
    admin-dir marker at all; a relative pointer that does not resolve to
    an existing directory once joined to caller_root; or a resolved path
    whose own `.git` does not exist (a stale/removed primary checkout).

Performance: A handful of os.path/open calls per invocation, no
             subprocess, no network. Negligible relative to the calling
             hook's own per-invocation cost.
"""

from __future__ import annotations

import os


def _read_normalized_gitdir_pointer(caller_root: str) -> "str | None":
    """Shared groundwork for both public functions below: if caller_root's
    `.git` entry is a FILE with a parseable `gitdir:` line, return that
    line's value with backslashes normalized to forward slashes. Returns
    None on every other shape - `.git` missing, `.git` a directory, an
    unreadable/undecodable file, or a file with no `gitdir:` line - so
    both callers share one fail-to-None read path instead of two copies
    of the same open/read/parse sequence drifting apart."""
    git_path = os.path.join(caller_root, ".git")
    try:
        if not os.path.isfile(git_path):
            return None
        with open(git_path, "r", encoding="utf-8", errors="strict") as f:
            content = f.read()
    except Exception:
        return None

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("gitdir:"):
            gitdir = line[len("gitdir:"):].strip()
            return gitdir.replace("\\", "/")
    return None


def is_git_worktree(caller_root: str) -> bool:
    """Return True iff caller_root's `.git` entry indicates it is a
    GENUINE LINKED git worktree - not a submodule, and not an independent
    nested clone that merely happens to live inside some ancestor root.

    See module docstring for the full discriminator rules and the
    fail-open discipline callers must preserve.
    """
    git_path = os.path.join(caller_root, ".git")
    try:
        if os.path.isdir(git_path):
            # Either the ancestor repo's own .git (already excluded by
            # the caller before this is reached) or an independent nested
            # clone - neither is a linked worktree.
            return False
    except Exception:
        return False
    normalized = _read_normalized_gitdir_pointer(caller_root)
    if normalized is None:
        # Either `.git` does not exist/is unreadable, or it exists but has
        # no parseable `gitdir:` line - both fail open to False.
        return False
    return "/worktrees/" in normalized


def resolve_worktree_primary_root(caller_root: str) -> "str | None":
    """Return the PRIMARY checkout root a genuine linked worktree at
    caller_root was created from, or None on any non-worktree shape.

    See module docstring's Public API and Failure modes sections for the
    full discriminator rules. Never raises.
    """
    normalized = _read_normalized_gitdir_pointer(caller_root)
    if normalized is None:
        return None

    marker = "/.git/worktrees/"
    idx = normalized.find(marker)
    if idx == -1:
        return None
    primary = normalized[:idx]
    if not os.path.isabs(primary):
        # A relative gitdir pointer (some git versions, and hand-built
        # test fixtures, write one) is relative to caller_root itself.
        primary = os.path.normpath(os.path.join(caller_root, primary))
    try:
        if os.path.isdir(primary) and os.path.isdir(os.path.join(primary, ".git")):
            return primary
    except OSError:
        return None
    return None
