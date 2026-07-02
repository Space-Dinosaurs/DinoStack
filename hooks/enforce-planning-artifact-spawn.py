#!/usr/bin/env python3
"""
Purpose: PreToolUse advisory hook that surfaces a decision-point reminder when
         a planning artifact (any file under docs/planning/) is being written
         without a recent architect spawn on record. This is a WARN-ONLY hook -
         it NEVER blocks or denies any write. It surfaces an advisory to the
         model context when the sentinel .agentic/.last-architect-spawn is absent
         or older than 4 hours, signalling that the conductor may be authoring a
         Brief/Plan without first going through architect + Skeptic review.

         CRITICAL: This hook MUST NOT block legitimate writes. Cross-session
         resume, operator-confirmed Briefs, and any session where the architect
         ran more than 4h ago are all valid - the advisory is a reminder, not
         a gate. The hook always exits 0.

Trigger: PreToolUse on tool_name in {"Write", "Edit"}.

Inputs:  JSON payload from stdin (PreToolUse hook contract). Relevant fields:
           payload.cwd               - working directory (string)
           payload.tool_input.file_path  - target file path (Write and Edit)

Behavior:
  1. Kill-switch: AE_PLANNING_GUARD_DISABLE=1 -> exit 0 silently.
  2. Parse stdin; fail-open on any error (exit 0).
  3. Only act on tool_name in {"Write", "Edit"}; otherwise exit 0.
  4. Resolve target path from tool_input.file_path; absent -> exit 0.
  5. Canonicalize both cwd and target with os.path.realpath (resolves
     /tmp vs /private/tmp symlink drift on macOS).
  6. Only act if the realpath'd target is under <realpath cwd>/docs/planning/.
     Otherwise exit 0.
  7. Check .agentic/.last-architect-spawn mtime. If the file exists and
     (time.time() - mtime) < 14400 (4h), exit 0 silently (recent spawn on
     record; legitimate Brief authoring).
  8. Emit advisory JSON with permissionDecision "allow" and advisory text in
     permissionDecisionReason so the model sees it in context without a human
     permission prompt and without denying the write.

Failure mode: Fully fail-open. Any parse error, missing key, os error, or
              unexpected exception -> exit 0 (allow). NEVER denies. NEVER
              writes to stdout with permissionDecision "deny". NEVER writes
              to stdout with permissionDecision "ask" (no human prompt).

Kill-switch: Set AE_PLANNING_GUARD_DISABLE=1 in the environment that launches
             Claude Code and restart. The hook silently exits 0 on every call
             when the kill-switch is active.
"""

import json
import os
import sys
import time


def main():
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_PLANNING_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        # Only act on Write or Edit.
        tool_name = data.get("tool_name")
        if tool_name not in ("Write", "Edit"):
            sys.exit(0)

        # Resolve cwd; fail-open if absent or not a string.
        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd.strip():
            sys.exit(0)
        cwd = cwd.strip()

        # Resolve target path from tool_input.file_path.
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            sys.exit(0)
        file_path = file_path.strip()

        # Canonicalize both paths to resolve symlinks (handles /tmp vs
        # /private/tmp on macOS and similar drift).
        real_cwd = os.path.realpath(cwd)
        # Resolve target: if relative, join with cwd first.
        if not os.path.isabs(file_path):
            file_path = os.path.join(cwd, file_path)
        real_target = os.path.realpath(file_path)

        # Only act on paths under <cwd>/docs/planning/.
        planning_dir = os.path.join(real_cwd, "docs", "planning") + os.sep
        if not real_target.startswith(planning_dir):
            sys.exit(0)

        # Check sentinel mtime.
        sentinel_path = os.path.join(real_cwd, ".agentic", ".last-architect-spawn")
        try:
            mtime = os.path.getmtime(sentinel_path)
            age = time.time() - mtime
            if age < 14400:  # 4 hours in seconds
                # Recent architect spawn on record - allow silently.
                sys.exit(0)
        except OSError:
            # Sentinel absent or unreadable - fall through to advisory.
            pass

        # Emit advisory: allow the write but surface the warning to the model.
        advisory_msg = (
            "ADVISORY: writing a planning artifact ("
            + real_target
            + ") with no architect spawn on record in the last 4h. "
            "Per the delegation protocol, spawn an architect and get Skeptic "
            "sign-off before authoring a Brief/Plan/spec. If an architect "
            "already ran this session, ignore. "
            "Silence with AE_PLANNING_GUARD_DISABLE=1."
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": advisory_msg,
                    }
                }
            )
        )
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
