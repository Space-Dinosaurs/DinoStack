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

Public API (module-level function, no class):
    is_git_worktree(caller_root: str) -> bool
        Returns True iff caller_root's `.git` entry indicates it is a
        GENUINE LINKED git worktree - not a submodule, and not an
        independent nested clone that merely happens to live inside some
        primary_root.

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
                       pattern, same role for Write/Edit/MultiEdit). Not
                       an enforce-*.py hook itself and not a
                       PreToolUse/Stop entry point - not registered in
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

Performance: A handful of os.path/open calls per invocation, no
             subprocess, no network. Negligible relative to the calling
             hook's own per-invocation cost.
"""

from __future__ import annotations

import os


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
        if not os.path.isfile(git_path):
            return False
        with open(git_path, "r", encoding="utf-8", errors="strict") as f:
            content = f.read()
    except Exception:
        return False

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("gitdir:"):
            gitdir = line[len("gitdir:"):].strip()
            normalized = gitdir.replace("\\", "/")
            return "/worktrees/" in normalized
    # No "gitdir:" line found - unparseable content, fail open.
    return False
