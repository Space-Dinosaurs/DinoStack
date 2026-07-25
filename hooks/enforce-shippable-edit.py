#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically backstops the METHODOLOGY
         §Git Workflow shippable/exempt classifier for the CONDUCTOR: it
         denies a Write/Edit/MultiEdit issued directly by the main conductor
         session (agent_id absent) against a shippable file inside the
         DinoStack checkout, while ALLOWING the same edit from an engineer
         subagent (agent_id present). This converts the prose rule
         "the conductor never edits shippable artifacts directly" into a
         hard gate on Claude Code, mirroring how enforce-orchestrator-
         singularity.py backstops the sole-orchestrator invariant.

         Predecessor note (DS-94): an earlier version of this guard was
         never committed and crashed-to-block (raised an uncaught exception
         on a missing repo-root file), which took down Write/Edit globally
         for the whole session. This version is committed, snapshot-
         included (installed via the session-stable hooks snapshot per
         DS-54), and structurally incapable of blocking on internal error -
         every code path that is not an affirmative, fully-resolved "this
         is a conductor-direct shippable edit inside this repo" match falls
         through to allow.

         Accepted limitations (intentional, not oversights):
         - Residual: conductor hand-edits to the instruction-layer files
           (AGENTS.md / MEMORY.md / CLAUDE.md) made OUTSIDE the /wrap
           command are mechanically UNGUARDED by design - this hook exempts
           those basenames unconditionally. The instruction layer trades
           this backstop for the sanctioned /wrap conductor-write workflow,
           which performs its own internal Skeptic review (see wrap.md).
           A conductor that hand-edits AGENTS.md outside /wrap is not
           caught here; that discipline remains a prose rule.
         - NotebookEdit is intentionally NOT matched. Its payload shape
           (notebook_path, not tool_input.file_path) differs from
           Write/Edit/MultiEdit, notebook surface area in this repo is
           near-zero, and the fail-open direction of skipping an
           unmatched tool is always the safe default for this hook.
         - Kill-switch: AE_SHIPPABLE_GUARD_DISABLE=1 disables the guard for
           the rare conductor-direct scaffold-repair write (e.g. hand-
           patching a corrupted .agentic/ file that happens to sit outside
           the .agentic/** exemption due to a symlink quirk).

Trigger: PreToolUse on tool_name in {"Write", "Edit", "MultiEdit"}.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Write", "Edit",
            or "MultiEdit"). Reads JSON from stdin, writes hookSpecificOutput
            JSON to stdout only when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, sys, pathlib). Reads
               <hooks-dir>/../.snapshot-meta.json (optional; DS-54 session-
               stable snapshot metadata) to resolve the live repo root when
               running from a snapshot copy instead of the checkout itself.

Downstream consumers: Claude Code hook runner (PreToolUse event for Write,
                      Edit, and MultiEdit). Wired via ~/.claude/settings.json
                      by .claude/install.sh (three matcher blocks: "Write",
                      "Edit", "MultiEdit"). Referenced by bin/agentic-doctor
                      (MANAGED_HOOK_BASENAMES) and content/rules/
                      conventions.md §Git Workflow.

Failure modes: FAIL-OPEN IS THE WHOLE POINT. Every failure mode below
               resolves to sys.exit(0) with no deny output:
    - Malformed/empty stdin: fail-open.
    - Kill-switch (AE_SHIPPABLE_GUARD_DISABLE=1): fail-open immediately,
      before reading stdin.
    - agent_id present at the top level (a subagent, e.g. an engineer
      Worker): fail-open (ALLOW) - subagents are the sanctioned writers of
      shippable files.
    - Non-Write/Edit/MultiEdit tool_name: passthrough (exit 0).
    - Missing/non-dict tool_input, missing/blank file_path: fail-open.
    - repo_root unresolvable (no snapshot meta and the hook's own directory
      is not a real dir), or target path resolution raises: fail-open (the
      raise is caught by the outer try/except).
    - target resolves outside repo_root: fail-open (not this repo's
      concern).
    - target is under .agentic/**, docs/planning/**, or is named
      AGENTS.md/MEMORY.md/CLAUDE.md at any depth: fail-open (exempt by the
      classifier).
    - Any other unexpected exception anywhere in the body: caught by the
      outer try/except, fail-open.
               The single deny path requires ALL of: no kill-switch, valid
               JSON, matcher tool, no agent_id, valid tool_input.file_path,
               a resolvable repo_root, a target inside repo_root, and the
               target NOT matching any exemption.

Performance: < 2 ms per call (in-memory JSON parse, a handful of path
             operations, optional single small JSON file read for
             .snapshot-meta.json, no network).
"""

# Kill-switch + recovery:
#   To temporarily disable this guard:
#     1. Set AE_SHIPPABLE_GUARD_DISABLE=1 in your environment, then restart
#        Claude Code so the hook process inherits the variable.
#     2. Alternatively, remove the "enforce-shippable-edit" entries from the
#        Write/Edit/MultiEdit PreToolUse blocks in ~/.claude/settings.json,
#        then restart.
#   To re-enable: unset the variable (or re-run .claude/install.sh).
#
# agent_id semantics (per official Claude Code hooks docs,
# https://code.claude.com/docs/en/hooks):
#   "Present only when the hook fires inside a subagent call."
#   - Main/conductor session: agent_id is ABSENT from the payload.
#   - Subagent session (e.g. an engineer Worker): agent_id is PRESENT.
#   Therefore: deny only when agent_id is ABSENT (or blank) at the TOP
#   LEVEL of the parsed JSON (NOT inside tool_input) - i.e. only the
#   conductor is ever a deny candidate.

import json
import os
import sys
from pathlib import Path

DENY_MESSAGE_TEMPLATE = (
    "Shippable-edit guard: the conductor must not edit shippable files "
    "directly ({path}). Delegate this edit to a worktree-isolated engineer "
    "subagent (see METHODOLOGY Git Workflow). Exempt: .agentic/**, "
    "docs/planning/**, paths outside the repo. Kill-switch: "
    "AE_SHIPPABLE_GUARD_DISABLE=1."
)

INSTRUCTION_LAYER_BASENAMES = {"AGENTS.md", "MEMORY.md", "CLAUDE.md"}


def _resolve_repo_root() -> str | None:
    """Resolve the live repo root, preferring DS-54 snapshot metadata.

    When this hook is invoked from the session-stable hooks snapshot
    (AE_HOOKS_SNAPSHOT_DIR wiring in install.sh), <snapshot>/hooks/ is a
    copy, not the checkout - .snapshot-meta.json's source_repo_dir points
    back at the real checkout. Falls back to the hook's own grandparent
    directory (../../ from hooks/enforce-shippable-edit.py) when no
    snapshot metadata is present, i.e. running directly from the checkout.
    Returns None (never raises) when neither resolution yields a directory.
    """
    here = Path(__file__).resolve().parent.parent
    meta_path = here / ".snapshot-meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = None
        if isinstance(meta, dict):
            source_repo_dir = meta.get("source_repo_dir")
            if isinstance(source_repo_dir, str) and source_repo_dir.strip():
                candidate = os.path.realpath(source_repo_dir)
                if os.path.isdir(candidate):
                    return candidate
    candidate = str(here)
    if os.path.isdir(candidate):
        return candidate
    return None


def main() -> None:
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_SHIPPABLE_GUARD_DISABLE") == "1":
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

        # agent_id present (non-empty string) at the TOP LEVEL means this is
        # a subagent (e.g. an engineer Worker) - always allow.
        agent_id = data.get("agent_id")
        if isinstance(agent_id, str) and agent_id.strip():
            sys.exit(0)

        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)

        file_path = tool_input.get("file_path")
        if not (isinstance(file_path, str) and file_path.strip()):
            sys.exit(0)
        file_path = file_path.strip()

        repo_root = _resolve_repo_root()
        if not repo_root:
            sys.exit(0)

        # Resolve the target: join with cwd first if relative. Any failure
        # here is caught by the outer except -> fail-open.
        cwd = data.get("cwd", "")
        if not os.path.isabs(file_path):
            joined = os.path.join(cwd, file_path) if cwd else file_path
        else:
            joined = file_path
        target = os.path.realpath(joined)

        rel = os.path.relpath(target, repo_root)
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            # Outside the repo entirely - not this hook's concern.
            sys.exit(0)

        parts = rel.split(os.sep)

        # Exemption 1: .agentic/** (conductor sole-writer).
        if parts and parts[0] == ".agentic":
            sys.exit(0)

        # Exemption 2: docs/planning/** (Briefs/Plans/ADRs).
        if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "planning":
            sys.exit(0)

        # Exemption 3: instruction-layer basenames, any depth - the
        # sanctioned /wrap conductor-write workflow.
        if os.path.basename(target) in INSTRUCTION_LAYER_BASENAMES:
            sys.exit(0)

        # Everything else tracked inside the repo is a shippable file the
        # conductor must not edit directly - deny.
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": DENY_MESSAGE_TEMPLATE.format(
                            path=target
                        ),
                    }
                }
            )
        )
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open). This
        # is the exact failure mode the predecessor version got wrong.
        sys.exit(0)


if __name__ == "__main__":
    main()
