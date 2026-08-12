#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces the ad-hoc Skeptic
         round-budget policy (content/sections/05-qa-gate.md §Re-route
         limits, content/references/skeptic-protocol.md §Round budget and
         value-per-round gate): a max of 3 Skeptic rounds per unit before the
         conductor must record an explicit `ship` or `escalate` decision.
         Before this hook, the cap was enforced only by "the conductor tracks
         re-route count in-context" - unenforced prose. A single session ran
         12 Skeptic rounds / 13 spawns on one unit with no mechanism firing.

         Persists round state at
         `.agentic/skeptic-round-<sanitized-branch>.json`, keyed off the
         current git branch in the payload's `cwd` (never `os.getcwd()` -
         see hooks/AGENTS.md measured-payload note on isolation-worktree
         `cwd` semantics). Mirrors, but does not reuse, the
         `.agentic/loop-state-$LOOP_KEY.json` convention documented in
         content/commands/ds-implement-ticket.md - that file's contracts
         (Contract A-D, session_id staleness gates) govern the mechanical
         Phase 6 loop only; this file is deliberately simpler because it
         governs an ad-hoc, conductor-tracked loop with no phase machinery.

         Decision algorithm (see `_decide()`):
           - round_count is the number of Skeptic rounds already recorded
             for this unit. On a spawn attempt, next_round = round_count + 1.
           - next_round <= 3: ALLOW. Persist round_count = next_round and
             clear any stale `decision` (a new round supersedes a prior
             ship/escalate record - each cap hit needs its own decision).
           - next_round >= 4 (cap reached):
               - decision == "escalate": ALLOW (human explicitly authorized
                 another round). Consumed on use - persist round_count =
                 next_round, decision reset to null, so a later cap hit
                 needs a fresh escalate record.
               - decision == "ship" AND NOT unresolved_critical: ALLOW.
                 (Ship decisions are terminal in normal operation - the
                 conductor should not be spawning further Skeptic rounds
                 after recording ship - but the hook does not infer "this
                 must be a new unit" from a stale recorded ship; it does
                 not deny solely because ship was previously recorded.)
               - decision == "ship" AND unresolved_critical: DENY. This is
                 the literal enforcement of "an unresolved Critical always
                 blocks - the cap never ships a Critical" - a recorded ship
                 decision is invalid while a Critical is still open,
                 regardless of round count.
               - decision is null/absent: DENY, naming the round count and
                 the exact two permitted actions (never a paraphrase the
                 conductor could satisfy by rewording).
         `unresolved_critical` and `decision` are written to the state file
         by the conductor directly (a plain Edit under `.agentic/`, which is
         exempt from `enforce-shippable-edit.py`'s shippable-file gate) -
         this hook only reads and advances `round_count`.

         Scope: fires ONLY on `subagent_type == "skeptic"` Task/Agent spawns.
         Never denies conductor Read/Grep/Glob (those tools are never
         Task/Agent, so they never reach this hook's logic at all) and never
         gates on inferred session capability - flat prohibitions in
         hooks/AGENTS.md §No gating on inferred session capability.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or
            "Agent"). Reads JSON from stdin, writes hookSpecificOutput JSON
            to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, re, subprocess, sys, time,
               importlib.util for the best-effort `lib/enforcement_log.py`
               import). No external deps.

Downstream consumers: Claude Code hook runner (PreToolUse event for Task and
                      Agent tools, matching enforce-tier.py's dual-matcher
                      wiring). Wired via ~/.claude/settings.json by
                      .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded spawn.

Failure modes:
    - Malformed stdin, non-dict tool_input, non-Task/Agent tool_name,
      subagent_type != "skeptic": fail-open (exit 0), no enforcement.
    - `cwd` absent from payload, or `git rev-parse --abbrev-ref HEAD` fails
      (not a git repo, detached HEAD edge cases, git not on PATH, timeout):
      fail-open (exit 0) - the hook cannot safely key rounds without a
      branch name and never falls back to a weaker key that could collide
      across unrelated units.
    - State file present but unparsable JSON: treated as absent (round 0,
      no decision, no unresolved_critical) - a corrupt state file must
      never turn into a permanent block.
    - State file write failure (permissions, disk full): the ALLOW/DENY
      decision for THIS call still fires correctly; only the persisted
      round_count advance may be lost, so a retried call may see a stale
      (lower) round_count and be permitted again - fail-open, not fail-shut.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching every
      other enforce-*.py hook's fire-logging pattern.

Performance: < 20 ms per call (one `git rev-parse` subprocess with a bounded
             timeout, one small JSON read/write under `.agentic/`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 3
_ROUND_CAP = 3
_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Mirrors the identical lazy, try/except-wrapped import pattern used by
    every sibling enforce-*.py hook (see enforce-background-spawn.py) - a
    missing or broken sibling module must never crash this hook.
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


def _sanitize_key(branch: str) -> str:
    """Map a git branch name to a safe .agentic/ filename fragment.

    Mirrors `ae_sanitize` in content/commands/ds-implement-ticket.md's
    LOOP_KEY derivation (map unsafe chars to '-'); deliberately independent
    code, not a shared import, because this hook has zero dependency on
    ds-implement-ticket.md's LOOP_KEY machinery.
    """
    safe = _KEY_SAFE_RE.sub("-", branch.strip())
    return safe or "unknown"


def _current_branch(cwd: str) -> str | None:
    """Resolve the current git branch at *cwd*, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        # Empty output or detached HEAD - no stable key available.
        return None
    return branch


def _state_path(cwd: str, key: str) -> Path:
    return Path(cwd) / ".agentic" / f"skeptic-round-{key}.json"


def _load_state(path: Path) -> dict:
    default = {
        "round_count": 0,
        "decision": None,
        "unresolved_critical": False,
    }
    try:
        if not path.is_file():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        return {
            "round_count": raw.get("round_count", 0) if isinstance(raw.get("round_count"), int) else 0,
            "decision": raw.get("decision") if raw.get("decision") in ("ship", "escalate") else None,
            "unresolved_critical": bool(raw.get("unresolved_critical", False)),
        }
    except Exception:
        return default


def _write_state(path: Path, unit_key: str, state: dict) -> None:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["unit_key"] = unit_key
        payload["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        # Fail-open: a lost persist means a retried call may see a stale
        # (lower) round_count and be permitted again - never a false deny.
        pass


def _decide(state: dict) -> tuple[bool, dict, str]:
    """Return (allow, new_state, reason). reason is "" when allow is True
    and the round advanced normally (nothing informative to log)."""
    round_count = state["round_count"]
    decision = state["decision"]
    unresolved_critical = state["unresolved_critical"]
    next_round = round_count + 1

    if next_round <= _ROUND_CAP:
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        return True, new_state, ""

    # Cap reached (next_round >= _ROUND_CAP + 1).
    if decision == "ship":
        if unresolved_critical:
            reason = (
                f"Skeptic round cap: {round_count} rounds already spent on this "
                f"unit (max {_ROUND_CAP}), and a `ship` decision is recorded, "
                "but `unresolved_critical` is still true. An unresolved "
                "Critical always blocks - the cap never ships a Critical. "
                "Fix the Critical (set unresolved_critical:false once "
                "resolved) or record decision:\"escalate\" instead of "
                "\"ship\" in the .agentic/skeptic-round-*.json state file."
            )
            return False, state, reason
        return True, state, ""

    if decision == "escalate":
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        return True, new_state, ""

    reason = (
        f"Skeptic round cap reached: {round_count} rounds already spent on "
        f"this unit (max {_ROUND_CAP}). Take exactly one of two actions "
        "before spawning another round: (a) record decision:\"ship\" in "
        "the .agentic/skeptic-round-*.json state file and ship, recording "
        "every unresolved non-Critical finding in the PR body as accepted "
        "debt (an unresolved Critical always blocks - never ship one), or "
        "(b) record decision:\"escalate\" stating cost-to-date and what "
        "the next round is expected to buy, then retry the spawn."
    )
    return False, state, reason


def _deny(data: dict, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-skeptic-round-cap", "deny", reason)
    except Exception:
        pass
    sys.exit(0)


def main() -> None:
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

        raw_tinput = data.get("tool_input")
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}
        if tinput.get("subagent_type") != "skeptic":
            sys.exit(0)

        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            sys.exit(0)

        branch = _current_branch(cwd)
        if branch is None:
            sys.exit(0)

        unit_key = _sanitize_key(branch)
        path = _state_path(cwd, unit_key)
        state = _load_state(path)

        allow, new_state, reason = _decide(state)

        if not allow:
            _deny(data, reason)
            return

        _write_state(path, unit_key, new_state)
        sys.exit(0)
    except Exception:
        # Any unexpected error anywhere in the decision path fails open -
        # a hook bug must never block Skeptic spawns outright.
        sys.exit(0)


if __name__ == "__main__":
    main()
