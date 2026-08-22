#!/usr/bin/env python3
"""
Purpose: PreToolUse ADVISORY-ONLY hook (DS-190) that warns, once per
         session, when a Task/Agent spawn is issued from a conductor
         session whose own `cwd` is itself inside a git worktree rather
         than the primary checkout. Conductor-driving from inside a
         worktree was present during the 2026-08-22 ~144G worktree-
         accumulation incident: an already-worktree-scoped session kept
         spawning further isolation worktrees from inside its own
         worktree, compounding disk usage instead of driving from the
         primary checkout. This hook NEVER denies - Claude Code's live
         PreToolUse payload carries no field confirming whether a
         worktree-cwd session is itself a deliberately reopened feature
         worktree (a legitimate case) versus an accidental nested spawn,
         so a blocking rule here would break the former. The advisory
         gives the model the chance to self-correct or confirm intent
         without breaking either case.

Trigger: PreToolUse on tool_name in {"Task", "Agent"}.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task", "Agent").
            Reads JSON from stdin, writes hookSpecificOutput JSON to
            stdout (permissionDecision "allow" with an advisory reason)
            at most once per session, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, sys, importlib.util,
               pathlib). Soft-dependency on the sibling
               hooks/lib/git_worktree.py::is_git_worktree() (dynamic
               import via a `_load_is_git_worktree()` wrapper mirroring
               hooks/enforce-worktree-read.py's, fails open to a function
               that always returns False - i.e. "not a worktree", which
               routes to this hook's silent-exit branch). Also a soft-
               dependency on the sibling hooks/lib/enforcement_log.py
               fire-logging helper (dynamic import, same fallback-to-no-op
               pattern).

Downstream consumers: Claude Code hook runner (PreToolUse event for Task
                      and Agent). Wired via ~/.claude/settings.json by
                      .claude/install.sh, inside the same
                      `for spawn_matcher in ("Task", "Agent"):` loop that
                      registers hooks/enforce-background-spawn.py and
                      hooks/enforce-orchestrator-singularity.py.
                      Documented in hooks/AGENTS.md §Entry points.

Failure modes: ADVISORY-ONLY - there is no deny branch anywhere in this
               file (grep for "deny" finds none as a decision). Every
               failure mode below resolves to a silent exit 0:
    - Kill-switch (AE_NESTED_WORKTREE_GUARD_DISABLE=1): exit 0
      immediately, before reading stdin.
    - Malformed/empty stdin, JSON that is not an object: exit 0.
    - tool_name not in {"Task", "Agent"}: passthrough (exit 0).
    - agent_id truthy at the TOP LEVEL (a subagent call, not the main
      session per the measured absence-is-the-marker rule): exit 0 - this
      hook only ever concerns itself with the conductor's own spawn axis,
      never a subagent's.
    - cwd (payload field) not a non-empty string: exit 0 - nothing to
      classify.
    - session_id not a non-empty string: exit 0 - no dedup key means no
      way to enforce "once per session", matching
      enforce-ticket-batching.py's documented fail-open on the same
      condition.
    - is_git_worktree(cwd) is False (main checkout, an ordinary
      subdirectory, a submodule, or an independent nested clone - see
      hooks/lib/git_worktree.py's discriminator): exit 0 - the whole
      point of this hook is a worktree-cwd conductor session, so a
      negative result here is simply the common case.
    - `Path(cwd, ".agentic").mkdir(parents=True, exist_ok=True)` OR the
      subsequent state-file existence check raises for any reason
      (permission error, read-only filesystem, etc.): the exception is
      swallowed and the hook proceeds to emit the advisory WITHOUT
      persisting a state file - fail open TOWARD emitting the advisory
      (worst case: the warning repeats every spawn this session instead
      of firing exactly once), never toward silently skipping it.
    - The best-effort state-file write itself fails (same class of I/O
      error): swallowed, the hook still proceeds to emit the advisory.
    - Why the raw payload `cwd` is safe to use directly as the state-path
      base with no repo-root anchoring (unlike e.g.
      enforce-background-spawn.py's sentinel path, which DOES need
      git-root anchoring - see that hook's DS-175 note): this hook's own
      gate at step 7 above already calls
      `is_git_worktree(cwd)` via `os.path.join(caller_root, ".git")`
      directly against the raw `cwd`. That check returns False for ANY
      subdirectory of a worktree root (a `.git` entry only exists AT the
      worktree root itself, never in a subdirectory of it), so by the
      time execution reaches the state-file write, `cwd` is GUARANTEED to
      already be resolved to the worktree root - there is no drift class
      to anchor against. A repo-root walk-up here would be redundant
      machinery solving a problem this hook's own precondition already
      eliminates.

Performance: < 5 ms per call (in-memory JSON parse, a `.git`-file read via
             is_git_worktree(), one mkdir, one stat, one best-effort small
             JSON write, no network I/O).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ADVISORY_TEMPLATE = (
    "Spawn is being issued from a session whose cwd is itself inside a git "
    "worktree, not the primary checkout. Per METHODOLOGY §Worktree "
    "Lifecycle, worktrees are reserved for isolated subagents; a "
    "conductor should drive spawns from the primary checkout. Confirm "
    "this is intentional (e.g. a session deliberately reopened inside a "
    "feature worktree) before continuing to spawn from here - "
    "conductor-driving from inside a worktree was present during the "
    "2026-08-22 ~144G worktree-accumulation incident (DS-190). This "
    "warning fires once per session."
)


def _load_is_git_worktree():
    """Dynamic import of the shared hooks/lib/git_worktree.py helper,
    mirroring hooks/enforce-worktree-read.py's `_load_is_git_worktree()`.
    Falls back to a function that always returns False (fail-open: treats
    cwd as NOT a worktree, which routes to this hook's silent-exit branch)
    if the sibling module cannot be loaded."""
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "git_worktree.py"
        spec = _ilu.spec_from_file_location("git_worktree", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.is_git_worktree
    except Exception:
        return lambda *a, **k: False


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the advisory itself.

    Called lazily from inside the advisory branch (never at module scope)
    so the overwhelming majority of invocations - every silent exit - never
    read, compile, or exec this file at all.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _emit(data: dict, reason: str, decision: str) -> None:
    # Decision print comes FIRST, unconditionally, matching the convention
    # in every other enforce-*.py hook carrying this same note (see
    # hooks/lib/enforcement_log.py manifest "Failure modes"). Telemetry is
    # loaded and called only after the decision has reached stdout, wrapped
    # in its own try/except so a raising log_fire can never suppress or
    # follow this advisory.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-nested-worktree-spawn", decision, reason)
    except Exception:
        pass


def main() -> None:
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_NESTED_WORKTREE_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        if tool_name not in ("Task", "Agent"):
            sys.exit(0)

        # agent_id truthy at the TOP LEVEL means this is a subagent call,
        # not the main session - this hook only concerns the conductor's
        # own spawn axis.
        if data.get("agent_id"):
            sys.exit(0)

        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            sys.exit(0)

        session_id = data.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            # No dedup key -> skip enforcement, matching
            # enforce-ticket-batching.py's documented fail-open on the
            # same condition.
            sys.exit(0)

        if not _load_is_git_worktree()(cwd):
            sys.exit(0)

        state_dir = Path(cwd, ".agentic")
        state_path = state_dir / f".nested-worktree-spawn-{session_id}.json"
        try:
            # Fresh worktrees have no .agentic/ dir at all (gitignored) -
            # create it before the exists-check below, not after.
            state_dir.mkdir(parents=True, exist_ok=True)
            if state_path.exists():
                # Already warned this session.
                sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            # mkdir/stat failure: proceed to the advisory WITHOUT
            # persistence - fail open toward emitting, never toward
            # silently skipping it.
            pass

        try:
            state_path.write_text(
                json.dumps({"session_id": session_id, "cwd": cwd}),
                encoding="utf-8",
            )
        except Exception:
            # Best-effort only - a write failure still proceeds to the
            # advisory below.
            pass

        _emit(data, ADVISORY_TEMPLATE.format(cwd=cwd), "allow_advisory")
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
