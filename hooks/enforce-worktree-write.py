#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that detects a worktree-isolated subagent writing a
         file into the PRIMARY checkout instead of its own isolation
         worktree. A subagent branched via `isolation: "worktree"` is meant
         to make every change inside its own worktree branch; a
         Write/Edit/MultiEdit that reaches into the primary checkout
         defeats isolation silently - the shippable-edit guard cannot catch
         this because it only gates on whether `agent_id` is ABSENT (the
         conductor-vs-subagent axis); a worktree-isolated subagent that has
         silently fallen back to the primary checkout still carries a
         present, non-blank `agent_id` and sails straight through that
         guard. This is a different axis: subagent-in-its-own-worktree vs
         subagent-writing-outside-it. Real instances of this failure mode
         landed shippable edits directly on `main` (commits `1577c984`,
         `3142a803`, `530ad687`) via exactly the mechanism AGENTS.md:61
         documents - across sequential spawns in one task the worktree is
         cleaned up between them and a later Worker silently falls back to
         the main tree, indistinguishable in the hook payload from a
         legitimate isolated engineer without this check.

         This hook mirrors hooks/enforce-worktree-read.py field-for-field
         (same measured-fact record; see hooks/AGENTS.md sections "Spawn
         payload mechanics" and "Worktree isolation scope" for the full
         detail this hook also relies on) but gates Write/Edit/MultiEdit
         instead of Read, and uses a SEPARATE config exemption key
         (`worktree_write_guard_exemptions`, not
         `worktree_read_guard_exemptions`) because writes carry a different
         risk profile than reads and an operator may want to exempt one
         axis without the other.

         Deliberately NOT merged into enforce-shippable-edit.py: that hook
         denies a conductor-direct (agent_id absent) edit against a
         shippable file, is fail-open-CRITICAL (a false deny there blocks
         every conductor Write/Edit/MultiEdit for the whole session), and
         must not be perturbed by a second, unrelated deny axis.

         Design is pinned by the same live payload measurement
         (Claude Code v2.1.220, 4 records, 2 sessions, Read + Bash) that
         hooks/enforce-worktree-read.py's docstring records:
         - The top-level payload key set is CONDITIONAL on caller. A
           subagent call carries agent_id/agent_type; a main-session call
           does not carry either key at all (absent, not null). The
           ABSENCE of agent_id/agent_type is the main-session marker.
         - For a worktree-isolated subagent, the payload's `cwd` field is
           the agent's OWN worktree root; `CLAUDE_PROJECT_DIR` (an env var,
           not a payload field) is the PRIMARY checkout root. The two are
           complementary, never interchangeable - caller_root always comes
           from the payload's cwd, never from CLAUDE_PROJECT_DIR and never
           from os.getcwd().
         - Isolation worktrees live INSIDE the primary root, so a naive
           unnormalized prefix test on the two roots is not sufficient;
           all three operands (target, caller_root, primary_root) are
           realpath-normalized before the containment test.

         Accepted limitations (intentional, not oversights):
         - Only fires on Write/Edit/MultiEdit. Bash (e.g. a redirect or
           `sed -i` against a primary-checkout path) is an equally unguarded
           write path and should not be assumed covered.
         - Config-driven exemption list ships EMPTY - no built-in entries.
         - Kill-switch: AE_WORKTREE_WRITE_GUARD_DISABLE=1 disables the
           guard entirely (fail-open before stdin is even read).

Trigger: PreToolUse on tool_name in {"Write", "Edit", "MultiEdit"}.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Write",
            "Edit", and "MultiEdit"). Reads JSON from stdin, writes
            hookSpecificOutput JSON to stdout only when denying, exits 0
            always.

Upstream deps: Python 3 stdlib only (json, os, sys, pathlib, importlib.util).
               Reads CLAUDE_PROJECT_DIR from the process environment (the
               primary checkout root, per Claude Code hooks docs). Reads
               an optional exemption list from
               <CLAUDE_PROJECT_DIR>/.agentic/config.json's
               "worktree_write_guard_exemptions" key (a list of strings,
               each a path prefix relative to the primary root; matching
               is a normalized-path prefix test). Absent/malformed config
               is treated as an empty exemption list. Also a soft-
               dependency on the sibling hooks/lib/enforcement_log.py
               fire-logging helper (dynamic import, fails open to a no-op).

Downstream consumers: Claude Code hook runner (PreToolUse event for Write,
                      Edit, and MultiEdit). Wired via ~/.claude/settings.json
                      by .claude/install.sh (three matcher blocks: "Write",
                      "Edit", "MultiEdit"). Documented in hooks/AGENTS.md
                      §Entry points and content/references/delegation-detail.md.

Failure modes: FAIL-OPEN IS THE WHOLE POINT. Every failure mode below
               resolves to sys.exit(0) with no deny output:
    - Kill-switch (AE_WORKTREE_WRITE_GUARD_DISABLE=1): fail-open
      immediately, before reading stdin.
    - Malformed/empty stdin, JSON that is not an object: fail-open.
    - tool_name not in {"Write", "Edit", "MultiEdit"}: passthrough (exit 0).
    - agent_id absent or blank at the TOP LEVEL (a main-session call, per
      the measured absence-is-the-marker rule): fail-open (ALLOW) -
      never gate on inferred session capability, only on payload facts.
    - Missing/non-dict tool_input, missing/blank file_path: fail-open.
    - CLAUDE_PROJECT_DIR unset/blank, or not a real directory: fail-open
      (cannot resolve primary_root).
    - cwd (payload field) unset/blank, or not a real directory: fail-open
      (cannot resolve caller_root).
    - caller_root == primary_root (a subagent that is NOT worktree-
      isolated, e.g. a foreground non-worktree spawn): fail-open (ALLOW) -
      there is no isolation boundary to defeat.
    - caller_root not a proper subdirectory of primary_root (an
      unexpected topology): fail-open (ALLOW) - the "isolation worktrees
      live inside the primary root" assumption does not hold, so this
      hook has nothing reliable to enforce.
    - target path resolution raises (e.g. embedded null byte): fail-open
      (caught by the outer try/except).
    - target resolves outside primary_root entirely: fail-open - not
      this hook's concern, no isolation boundary is at stake.
    - target resolves inside caller_root (the agent's own worktree):
      fail-open (ALLOW) - this is exactly what isolation intends.
    - target matches a configured exemption prefix: fail-open (ALLOW).
    - Any other unexpected exception anywhere in the body: caught by the
      outer try/except, fail-open.
               The single deny path requires ALL of: no kill-switch, valid
               JSON, tool_name in {Write, Edit, MultiEdit}, agent_id
               present (subagent), valid tool_input.file_path, a
               resolvable primary_root, a resolvable caller_root that is a
               proper subdirectory of primary_root (genuine worktree
               isolation), a target inside primary_root but NOT inside
               caller_root, and no matching exemption.

Performance: < 2 ms per call (in-memory JSON parse, a handful of path
             operations, one optional small JSON config read, no network).
"""

# Kill-switch + recovery:
#   To temporarily disable this guard:
#     1. Set AE_WORKTREE_WRITE_GUARD_DISABLE=1 in your environment, then
#        restart Claude Code so the hook process inherits the variable.
#     2. Alternatively, remove the "enforce-worktree-write" entry from the
#        Write/Edit/MultiEdit PreToolUse blocks in ~/.claude/settings.json,
#        then restart.
#   To re-enable: unset the variable (or re-run .claude/install.sh).
#
# agent_id / agent_type semantics: see hooks/enforce-worktree-read.py's
# module docstring and hooks/AGENTS.md §Spawn payload mechanics for the
# full measured-fact record this hook shares.

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DENY_MESSAGE_TEMPLATE = (
    "Worktree-write guard: this worktree-isolated subagent (agent_id={agent_id!r}"
    "{agent_type_suffix}) attempted to {tool_name} {path}, which resolves inside "
    "the PRIMARY checkout ({primary_root}) rather than this agent's own worktree "
    "({caller_root}). This subagent appears to have fallen back to the primary "
    "checkout instead of its own isolation worktree - act only on the files "
    "inside your own branch. Verify the spawn's worktree_setup/create_commands "
    "actually populated {caller_root} as a real worktree branch; if this write "
    "is genuinely needed against the primary checkout, ask an operator to add "
    "its path to worktree_write_guard_exemptions in "
    "<primary_root>/.agentic/config.json."
)


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so
    the overwhelming majority of invocations - every silent allow - never
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


def _load_exemptions(primary_root: str) -> list:
    """Read the config-driven exemption list. Ships empty - no built-in
    entries. Absent/malformed config.json is treated as [] (never raises).

    Each entry is a path prefix relative to primary_root; a target whose
    normalized-relative-path starts with an exempt prefix (path-segment
    aware, not a raw string prefix) is allowed even when it would otherwise
    be a cross-boundary violation.
    """
    config_path = os.path.join(primary_root, ".agentic", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        raw = config.get("worktree_write_guard_exemptions", [])
        if not isinstance(raw, list):
            return []
        return [str(e).strip() for e in raw if isinstance(e, str) and e.strip()]
    except Exception:
        return []


def _is_exempt(rel_target: str, exemptions: list) -> bool:
    """Path-segment-aware prefix match: rel_target == prefix, or
    rel_target starts with prefix + os.sep. Prevents a prefix like "docs"
    from wrongly matching "docs-internal"."""
    for prefix in exemptions:
        norm_prefix = prefix.strip(os.sep)
        if not norm_prefix:
            continue
        if rel_target == norm_prefix or rel_target.startswith(
            norm_prefix + os.sep
        ):
            return True
    return False


def _resolve_target(file_path: str, cwd: str) -> str:
    """Join a relative file_path against cwd (when cwd is provided), then
    realpath-normalize. May raise (e.g. embedded null byte) - callers must
    catch."""
    if not os.path.isabs(file_path):
        joined = os.path.join(cwd, file_path) if cwd else file_path
    else:
        joined = file_path
    return os.path.realpath(joined)


def _relpath_or_none(target: str, root: str):
    """Return the relpath of target under root, or None if target is not
    contained in root (including target == root, which returns '.')."""
    rel = os.path.relpath(target, root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel


def main() -> None:
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_WORKTREE_WRITE_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            sys.exit(0)

        # agent_id present (non-empty string) at the TOP LEVEL means this
        # is a subagent call - only subagents can violate worktree
        # isolation, so a main-session call always allows.
        agent_id = data.get("agent_id")
        if not (isinstance(agent_id, str) and agent_id.strip()):
            sys.exit(0)

        # agent_type is read ONLY inside this subagent branch, per the
        # measured payload rule - it is absent on a main-session call and
        # must never be evaluated unconditionally.
        agent_type = data.get("agent_type")
        agent_type_suffix = ""
        if isinstance(agent_type, str) and agent_type.strip():
            agent_type_suffix = ", agent_type=" + repr(agent_type.strip())

        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)

        file_path = tool_input.get("file_path")
        if not (isinstance(file_path, str) and file_path.strip()):
            sys.exit(0)
        file_path = file_path.strip()

        # primary_root: CLAUDE_PROJECT_DIR only - never the payload cwd.
        raw_primary = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if not (isinstance(raw_primary, str) and raw_primary.strip()):
            sys.exit(0)
        if not os.path.isdir(raw_primary):
            sys.exit(0)
        primary_root = os.path.realpath(raw_primary)

        # caller_root: the payload's cwd field only - never CLAUDE_PROJECT_DIR
        # (that would compare primary_root against itself) and never
        # os.getcwd() (the payload field is authoritative even where the two
        # happen to agree in a given capture).
        raw_cwd = data.get("cwd", "")
        if not (isinstance(raw_cwd, str) and raw_cwd.strip()):
            sys.exit(0)
        if not os.path.isdir(raw_cwd):
            sys.exit(0)
        caller_root = os.path.realpath(raw_cwd)

        if caller_root == primary_root:
            # Subagent is not worktree-isolated - no isolation boundary to
            # defeat.
            sys.exit(0)

        rel_caller = _relpath_or_none(caller_root, primary_root)
        if rel_caller is None or rel_caller == os.curdir:
            # caller_root is not (or is trivially) inside primary_root -
            # the "worktrees live inside the primary root" assumption this
            # hook relies on does not hold here. Fail open.
            sys.exit(0)

        # Resolve the write target. Any failure here is caught by the outer
        # except -> fail-open.
        target = _resolve_target(file_path, raw_cwd)

        rel_target = _relpath_or_none(target, primary_root)
        if rel_target is None:
            # Target is outside the primary root entirely - not this
            # hook's concern.
            sys.exit(0)

        rel_of_target_in_caller = _relpath_or_none(target, caller_root)
        if rel_of_target_in_caller is not None:
            # Target is inside the agent's own worktree - exactly what
            # isolation intends.
            sys.exit(0)

        exemptions = _load_exemptions(primary_root)
        if _is_exempt(rel_target, exemptions):
            sys.exit(0)

        # Violation: target is inside primary_root, outside caller_root,
        # and caller_root is a genuine worktree-isolated subdirectory of
        # primary_root.
        deny_reason = DENY_MESSAGE_TEMPLATE.format(
            agent_id=agent_id,
            agent_type_suffix=agent_type_suffix,
            tool_name=tool_name,
            path=target,
            primary_root=primary_root,
            caller_root=caller_root,
        )
        # Decision print comes FIRST, unconditionally. Telemetry is loaded
        # and called only after the decision has reached stdout, and is
        # wrapped in its own try/except so a raising log_fire (e.g. a
        # signature mismatch from a half-applied lib snapshot) can never
        # suppress or follow this deny - see hooks/lib/enforcement_log.py
        # manifest "Failure modes".
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": deny_reason,
                    }
                }
            )
        )
        try:
            _load_log_fire()(data, "enforce-worktree-write", "deny", deny_reason)
        except Exception:
            pass
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open). This
        # is the same discipline enforce-shippable-edit.py's predecessor
        # got wrong.
        sys.exit(0)


if __name__ == "__main__":
    main()
