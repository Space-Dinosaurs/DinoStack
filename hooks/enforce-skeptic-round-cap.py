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

         Persists round state at `.agentic/skeptic-round-<unit-key>.json`
         under the payload's `cwd`. **The key is deliberately NOT the
         conductor's own git branch.** In this repo's workflow the conductor
         stays on `main` for the whole session while engineers work in
         isolation worktrees, so every Skeptic spawn - across every unit,
         across the whole session - would share one `skeptic-round-main.json`
         counter if keyed off `cwd`'s branch: unit A's rounds would exhaust
         unit B's budget. Instead the key is derived from the "Diff under
         review" line that `content/references/skeptic-protocol.md` Section
         4.5 mandates in EVERY Skeptic spawn prompt (the `## Global-context
         inputs` block, item 6) - the one field that identifies the actual
         artifact under review and stays stable across re-review rounds of
         the SAME unit, even though the rest of the prompt (the pasted
         Worker output) changes every round. See `_extract_unit_identity()`.
         When that line cannot be found, the hook fails open (allows, writes
         no state) rather than falling back to a weaker key that could
         collide across unrelated units - see Failure modes below.

         Decision algorithm (see `_decide()`):
           - round_count is the number of Skeptic rounds already recorded
             for this unit. On a spawn attempt, next_round = round_count + 1.
           - Round fingerprint coalescing: a `skeptic_strategy:
             multi-dimensional` fan-out (correctness-Skeptic +
             security-auditor + perf-analyst, all `subagent_type ==
             "skeptic"`, spawned in a single conductor message onto the
             SAME diff and the SAME Worker output) shares this hook's unit
             key, since all three prompts carry the same "Diff under
             review" line. Deliberately NOT time-window based (a fixed
             wall-clock window cannot distinguish "3 parallel companion
             spawns of one round" from "3 genuinely sequential rounds fired
             back-to-back," and is flaky under test). Instead, `_decide()`
             hashes the "What to review:" section of the prompt (the pasted
             Worker output) into a `round_fingerprint`: fan-out companions
             review the identical Worker output, so their fingerprints
             match and the call reuses the first spawn's cached ALLOW/DENY
             outcome verbatim instead of re-running the decision. A
             genuinely new round always carries new Worker output (the
             engineer's latest fix), so its fingerprint differs and the
             round advances normally. When no "What to review:" section is
             present, coalescing never triggers (every call is treated as
             its own round) - a conservative default that never
             under-counts a real cap violation. This does not add real
             cross-process locking; a true simultaneous race can still
             double-charge a round - see Failure modes below.
           - next_round <= 3: ALLOW. Persist round_count = next_round and
             clear any stale `decision` (a new round supersedes a prior
             ship/escalate record - each cap hit needs its own decision).
           - next_round >= 4 (cap reached):
               - decision == "escalate": ALLOW (human explicitly authorized
                 another round). Consumed on use - persist round_count =
                 next_round, decision reset to null, so a later cap hit
                 needs a fresh escalate record.
               - decision == "ship" AND NOT unresolved_critical: ALLOW,
                 and CONSUMED on use exactly like escalate - persist
                 round_count = next_round, decision reset to null. A stale
                 `ship` decision must never be a permanent global bypass:
                 before this fix, `ship` left round_count and decision
                 unchanged, so every subsequent spawn for that unit (or,
                 combined with the branch-keying bug above, every
                 subsequent spawn for ANY unit) was allowed forever with no
                 further check.
               - decision == "ship" AND unresolved_critical: DENY. This is
                 the literal enforcement of "an unresolved Critical always
                 blocks - the cap never ships a Critical" - a recorded ship
                 decision is invalid while a Critical is still open,
                 regardless of round count. NOT consumed (state unchanged) -
                 the conductor must still resolve the Critical or record
                 escalate.
               - decision is null/absent: DENY, naming the round count and
                 the exact two permitted actions (never a paraphrase the
                 conductor could satisfy by rewording).
         `unresolved_critical` and `decision` are written to the state file
         by the conductor directly (a plain Edit under `.agentic/`, which is
         exempt from `enforce-shippable-edit.py`'s shippable-file gate) -
         this hook only reads and advances `round_count`. Consequently
         `unresolved_critical` is conductor-attested, not independently
         derived from any actual Skeptic finding: the hook enforces that a
         recorded `ship` decision cannot silently bypass a Critical the
         conductor has already flagged, not that no Critical exists. Do not
         cite this hook as proof no Critical was missed - only that a
         flagged one cannot be shipped past.

         Scope: fires ONLY on `subagent_type == "skeptic"` Task/Agent spawns.
         Never denies conductor Read/Grep/Glob (those tools are never
         Task/Agent, so they never reach this hook's logic at all) and never
         gates on inferred session capability - flat prohibitions in
         hooks/AGENTS.md §No gating on inferred session capability.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or
            "Agent"). Reads JSON from stdin, writes hookSpecificOutput JSON
            to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (hashlib, json, os, re, sys, time,
               importlib.util for the best-effort `lib/enforcement_log.py`
               import). No external deps, no subprocess (the fix that
               dropped `_current_branch()`'s `git rev-parse` call also
               dropped the only subprocess dependency this hook had).

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
    - `cwd` absent from payload: fail-open (exit 0) - the hook cannot
      determine where to persist state.
    - No "Diff under review:" line found in the spawn prompt (unit identity
      unextractable): fail-open (exit 0), no state written. This never
      falls back to a weaker key (e.g. the conductor's own branch) that
      could collide across unrelated units - see the CRITICAL fix note at
      the top of this docstring.
    - State file present but unparsable JSON: treated as absent (round 0,
      no decision, no unresolved_critical) - a corrupt state file must
      never turn into a permanent block.
    - State file write failure (permissions, disk full): the ALLOW/DENY
      decision for THIS call still fires correctly; only the persisted
      round_count advance may be lost, so a retried call may see a stale
      (lower) round_count and be permitted again - fail-open, not fail-shut.
    - Concurrent invocations (near-simultaneous parallel fan-out spawns
      landing close enough that one process's write has not yet landed
      before another process's read): fingerprint coalescing handles the
      common case (each companion spawn's hook invocation runs to
      completion - read, decide, write - well within the harness's
      per-spawn dispatch latency) but this hook has no real file lock - a
      true simultaneous race can still double-charge a round. This is a
      known residual risk, not claimed to be closed; it fails toward
      over-counting (extra rounds charged), never toward under-counting a
      genuine cap violation, and never toward a deny on malfunction.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching every
      other enforce-*.py hook's fire-logging pattern.

Performance: < 5 ms per call (no subprocess; one small JSON read/write
             under `.agentic/`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

_ROUND_CAP = 3
_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_KEY_LEN = 80
_DIFF_UNDER_REVIEW_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\.\s*)?Diff under review:\s*(\S.*?)\s*$"
)
_WHAT_TO_REVIEW_RE = re.compile(r"(?is)what to review:?\**\s*(.*)")


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


def _sanitize_key(raw: str) -> str:
    """Map arbitrary text to a safe, bounded .agentic/ filename fragment."""
    safe = _KEY_SAFE_RE.sub("-", raw.strip())
    return safe or "unknown"


def _extract_unit_identity(tinput: dict) -> str | None:
    """Extract a stable per-unit identity string from the Skeptic spawn's
    prompt text.

    Uses the "Diff under review:" line that `content/references/
    skeptic-protocol.md` Section 4.5 mandates in every Skeptic spawn's
    `## Global-context inputs` block (item 6) - the field that identifies
    the actual reviewed artifact (a branch, a PR, a SHA range, or file
    paths) and is the one part of the prompt that stays constant across
    re-review rounds of the SAME unit, even though everything else in the
    prompt (the pasted Worker output under "What to review") changes every
    round. Falls back to `description` (also often unit-scoped) only when
    no such line exists in `prompt`. Returns None when neither yields
    anything - the caller must fail open, never falling back to a weaker
    key such as the conductor's own branch.
    """
    for field in ("prompt", "description"):
        value = tinput.get(field)
        text = value if isinstance(value, str) else ""
        if not text:
            continue
        match = _DIFF_UNDER_REVIEW_RE.search(text)
        if match:
            identity = match.group(1).strip()
            if identity:
                return identity
    return None


def _unit_key(tinput: dict) -> str | None:
    """Return a safe, bounded, collision-resistant .agentic/ key for the
    unit under review, or None when it cannot be determined."""
    identity = _extract_unit_identity(tinput)
    if not identity:
        return None
    sanitized = _sanitize_key(identity)[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _round_fingerprint(tinput: dict) -> str | None:
    """Hash of the "What to review:" section (the pasted Worker output) of
    the spawn prompt, or None when that section is absent.

    Two Skeptic spawns reviewing the SAME Worker output (a
    `skeptic_strategy: multi-dimensional` fan-out: correctness-Skeptic +
    security-auditor + perf-analyst reviewing one round's diff from three
    angles) produce identical fingerprints and are companions of the same
    round. A genuinely new round always carries new Worker output (the
    latest engineer fix), so its fingerprint differs. Absence (None) means
    coalescing never triggers for that call - every call is its own round,
    the conservative default that never under-counts a real cap violation.
    """
    prompt = tinput.get("prompt")
    text = prompt if isinstance(prompt, str) else ""
    if not text:
        return None
    match = _WHAT_TO_REVIEW_RE.search(text)
    if not match:
        return None
    body = match.group(1).strip()
    if not body:
        return None
    return hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()


def _state_path(cwd: str, key: str) -> Path:
    return Path(cwd) / ".agentic" / f"skeptic-round-{key}.json"


def _load_state(path: Path) -> dict:
    default = {
        "round_count": 0,
        "decision": None,
        "unresolved_critical": False,
        "last_round_fingerprint": None,
        "last_decision_allow": None,
        "last_decision_reason": "",
    }
    try:
        if not path.is_file():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        fingerprint = raw.get("last_round_fingerprint")
        return {
            "round_count": raw.get("round_count", 0) if isinstance(raw.get("round_count"), int) else 0,
            "decision": raw.get("decision") if raw.get("decision") in ("ship", "escalate") else None,
            "unresolved_critical": bool(raw.get("unresolved_critical", False)),
            "last_round_fingerprint": fingerprint if isinstance(fingerprint, str) else None,
            "last_decision_allow": raw.get("last_decision_allow") if isinstance(raw.get("last_decision_allow"), bool) else None,
            "last_decision_reason": raw.get("last_decision_reason") if isinstance(raw.get("last_decision_reason"), str) else "",
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


_DENY_NO_DECISION_TEMPLATE = (
    "Skeptic round cap reached: {round_count} rounds already spent on "
    "this unit (max {cap}). Take exactly one of two actions "
    "before spawning another round: (a) record decision:\"ship\" in "
    "the .agentic/skeptic-round-*.json state file and ship, recording "
    "every unresolved non-Critical finding in the PR body as accepted "
    "debt (an unresolved Critical always blocks - never ship one), or "
    "(b) record decision:\"escalate\" stating cost-to-date and what "
    "the next round is expected to buy, then retry the spawn."
)

_DENY_SHIP_CRITICAL_TEMPLATE = (
    "Skeptic round cap: {round_count} rounds already spent on this "
    "unit (max {cap}), and a `ship` decision is recorded, "
    "but `unresolved_critical` is still true. An unresolved "
    "Critical always blocks - the cap never ships a Critical. "
    "Fix the Critical (set unresolved_critical:false once "
    "resolved) or record decision:\"escalate\" instead of "
    "\"ship\" in the .agentic/skeptic-round-*.json state file."
)


def _decide(state: dict, round_fingerprint: str | None) -> tuple[bool, dict, str]:
    """Return (allow, new_state, reason). reason is "" when allow is True
    and the round advanced normally (nothing informative to log)."""
    round_count = state["round_count"]
    decision = state["decision"]
    unresolved_critical = state["unresolved_critical"]

    # Fingerprint coalescing: a parallel multi-dimensional fan-out
    # (correctness-Skeptic + security-auditor + perf-analyst, all sharing
    # this unit's key because they all review the same diff AND the same
    # Worker output) must consume ONE round, not one per spawn. A call
    # whose "What to review" fingerprint matches the round this state
    # already recorded reuses that round's cached outcome verbatim instead
    # of re-deciding (and, on the allow-and-mutate paths, re-advancing
    # round_count or re-consuming a decision). `round_fingerprint is None`
    # (no "What to review:" section found) never coalesces - every such
    # call is treated as its own round.
    if (
        round_fingerprint is not None
        and state.get("last_round_fingerprint") == round_fingerprint
        and state.get("last_decision_allow") is not None
    ):
        return bool(state["last_decision_allow"]), state, state.get("last_decision_reason", "")

    next_round = round_count + 1

    if next_round <= _ROUND_CAP:
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    # Cap reached (next_round >= _ROUND_CAP + 1).
    if decision == "ship":
        if unresolved_critical:
            reason = _DENY_SHIP_CRITICAL_TEMPLATE.format(round_count=round_count, cap=_ROUND_CAP)
            # Not consumed: the conductor must still resolve the Critical
            # or record escalate before another spawn is possible.
            return False, state, reason
        # Ship, like escalate, is single-use: consume it so a *subsequent*
        # spawn for this unit does not fall through to an unconditional
        # bypass. Before this fix, `ship` left round_count/decision
        # unchanged, making every later spawn for this unit ALLOW forever
        # with no further check.
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    if decision == "escalate":
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    reason = _DENY_NO_DECISION_TEMPLATE.format(round_count=round_count, cap=_ROUND_CAP)
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

        unit_key = _unit_key(tinput)
        if unit_key is None:
            # Cannot determine which unit is under review - fail open.
            # Never fall back to a weaker key (e.g. the conductor's own
            # branch) that could collide across unrelated units.
            sys.exit(0)

        path = _state_path(cwd, unit_key)
        state = _load_state(path)

        allow, new_state, reason = _decide(state, _round_fingerprint(tinput))

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
