#!/usr/bin/env python3
"""
Purpose: ADVISORY Claude Code Stop hook (DS-122) that checks the SHAPE of
         the conductor's final assistant message against the three-part
         turn-shape contract in content/sections/02-delegation.md /
         content/rules/conventions.md ("Operator decisions go last in the
         turn", "Waiting:" forced-yield shape, and the identity/phase
         breadcrumb convention). It NEVER blocks - this is the single most
         important property of this hook, unlike its sibling
         enforce-no-abdication.py, which does block. A finding here is
         surfaced purely as feedback text so the conductor can self-correct
         on its next turn.

         Three checks, run in this fixed order:

         1. Identity-line check: the first non-blank line of the message
            should loosely match a "<token> . <token> . <token> [phase:
            ...]" breadcrumb shape (three middle-dot-separated tokens plus
            a bracketed phase tag). A missing/malformed identity line is
            flagged.

         2. Warrant classification (RUNS FIRST relative to check 3 below,
            and is AUTHORITATIVE over it): classifies which of four
            warrants justify the turn's content -
              - decision:   an "## Operator decisions" heading is present.
              - stoppage:   at least one "Waiting:" line is present.
              - completion: "[phase: complete]" or an unambiguous terminal-
                             completion phrase. A bare past-participle
                             "done"/"shipped"/"merged" does NOT count - this
                             repo's canonical non-warranted status-ping
                             vocabulary ("unit 2 merged", "PR merged,
                             pulling main") must not accidentally launder
                             into a completion warrant.
              - answer:     a quoted fragment of the operator's immediately
                             preceding message. Best-effort and deliberately
                             the weakest of the four detectors.

         3a. Status-only flag: fires when the message has MORE than ~1-2
             lines of prose outside the identity line AND has NONE of the
             four warrants above.

         3b. Forced-yield shape check - STRICTLY SUBORDINATE to (2). Runs
             ONLY when `stoppage` is the SOLE warrant present (a "Waiting:"
             line exists and none of decision/completion/answer is
             present). When that gate passes, the message must be exactly
             the identity line plus one or more "Waiting:" lines and
             nothing else; any extra content flags "forced-yield: extra
             content". When a "Waiting:" line co-occurs with ANY other
             warrant, this check is skipped entirely - no flag, regardless
             of how much other prose accompanies it.

         This ordering (warrant classification is authoritative; the shape
         check is strictly subordinate to it) is the whole design. Two
         prior review rounds rejected an earlier version of this hook that
         fired on correct, fully-warranted turns - a guard that fires on
         correct behavior trains the conductor to ignore its own feedback
         channel, which is worse than no hook at all.

         Two residual false positives are ACCEPTED and INTENTIONAL, not
         bugs to chase:
           (1) a stoppage-only turn with a separate explanatory sentence
               next to the "Waiting:" line is flagged (the fix is to fold
               the reason into the "Waiting:" line itself, not to relax
               this check).
           (2) a "Waiting:" turn that also answers the operator, where the
               weak `answer` heuristic fails to detect the answer, is
               flagged.

         `background_tasks[]` in the Stop payload is deliberately NOT read
         at all. An earlier design used it and was rejected: harness state
         cannot distinguish "the conductor is yielding" from "the
         conductor is doing something else while agents happen to be
         running in the background" - only the shape of the message text
         itself can.

         A two-layer loop guard bounds how often an advisory can re-invoke
         the model, mirroring the sibling enforce-no-abdication.py. On the
         Claude Code harness, a Stop hook's `additionalContext` re-invokes
         the model immediately (it does not wait for a user turn); when the
         conductor is blocked on a user decision it has nothing substantive
         to say, so it writes a short status turn, the hook flags it, the
         advisory re-invokes the model, and the pair loops until the
         harness's own 9-consecutive-block override fires. Layer 1: the
         `stop_hook_active` payload flag - set by CC when this Stop event
         itself was triggered by a prior Stop-hook action - exits silently
         right after stdin parse. Layer 2: a counter-cap backstop for CC bug
         #54360 (stop_hook_active can fail to propagate when a
         UserPromptSubmit hook interleaves system reminders), state at
         <cwd>/.agentic/.turn-shape-guard-fire-count; the counter increments
         and persists BEFORE each advisory (an advisory whose count cannot
         be persisted is NOT emitted - it would lose its loop bound) and
         resets on a clean turn and on a genuine new user message, so a
         blocked conductor gets at most CONSECUTIVE_BLOCK_CAP advisories
         before this hook goes silent. The counter + user-message-counting
         machinery lives in the shared module hooks/lib/loop_guard.py,
         loaded lazily via _load_loop_guard(); when cwd is absent (synthetic
         payloads only - the CC Stop payload always carries cwd) the counter
         cannot be scoped, so this hook falls through to its legacy
         advisory-only behavior rather than silently swallowing findings.
         This hook NEVER blocks - the guard only suppresses advisories; every
         exit stays 0.

Public API: Run as a Claude Code Stop hook (matcher: "*"). Reads JSON from
            stdin. ALWAYS exits 0. On a clean turn (no findings), emits
            nothing on stdout. On a flagged turn, emits exactly one JSON
            object:
              {"hookSpecificOutput": {"hookEventName": "Stop",
                                       "additionalContext": "TURN-SHAPE: <finding>"}}
            `additionalContext` (not `systemMessage`) is used deliberately -
            it reaches the model as a system reminder on its next turn,
            giving the conductor a chance to self-correct, whereas
            `systemMessage` is operator-only and invisible to the model.

Upstream deps: Python 3 stdlib only (json, os, re, sys) plus the shared
               hooks/lib/loop_guard.py module (counter + user-message-
               counting machinery for the loop guard), loaded lazily via
               _load_loop_guard(). Lazily imports the shared fire-logging
               helper hooks/lib/enforcement_log.py (log_fire) only on the
               branch that emits a finding - see _load_log_fire().

Downstream consumers: Claude Code hook runner (Stop event, matcher "*").
                      Wired via ~/.claude/settings.json by
                      .claude/install.sh, registered AFTER
                      enforce-no-abdication.py (order: stop-context.js ->
                      enforce-no-abdication.py -> enforce-turn-shape.py).
                      Because a revert of this file would otherwise leave a
                      dangling registration that blocks every stop
                      (`python3 <missing path>` exits 2, the BLOCKING Stop
                      code), install.sh registers this hook via a guarded
                      command string
                      (`test -f ... && python3 ... || exit 0`), not the
                      bare `python3 {path}` form its siblings use.

Failure modes:
    - Malformed/unparseable stdin: fail-open (exit 0, emit nothing).
    - AE_TURN_SHAPE_GUARD_DISABLE=1: short-circuits to exit 0 before any
      other processing, checked FIRST in main() (mirrors
      enforce-no-abdication.py's KILL_SWITCH_ENV idiom).
    - Config toggle is turn_shape_guard_enabled in .agentic/config.json,
      and its polarity is DELIBERATELY INVERTED from the sibling
      abdication_guard_enabled: this hook's guard is `config.get(
      "turn_shape_guard_enabled") is not False` - i.e. default ON when the
      key or the whole config file is absent. This is intentional, not an
      oversight to "fix" into matching the sibling: unlike
      enforce-no-abdication.py, this hook NEVER blocks, so there is no
      opt-in-only safety rationale for defaulting it off. A missing or
      unreadable config.json is treated as an empty {} (i.e. the guard
      stays ON), not as a disable signal.
    - Empty/unavailable message text (last_assistant_message absent and
      the transcript fallback yields nothing): fail-open (exit 0, emit
      nothing) - there is nothing to classify.
    - Any exception anywhere in main(): fail-open via an outer
      try/except wrapping the entire body (exit 0), matching
      enforce-no-abdication.py's defense-in-depth pattern.
    - stop_hook_active=true: exit 0 silently (Layer 1 primary re-entrancy
      guard) - a re-invocation must never re-flag the same turn.
    - Counter >= CONSECUTIVE_BLOCK_CAP: exit 0 silently, no advisory
      (Layer 2 backstop for CC bug #54360) - the loop is bounded.
    - Counter write fails (unwritable .agentic/, full disk, corrupt tmp,
      etc.): exit 0 silently, no advisory. Rationale: an advisory whose
      count cannot be recorded loses its loop bound; the safe degradation
      is "don't flag" (never an unbounded advisory loop). Only advisories
      after the incremented count has been successfully persisted are
      emitted.
    - hooks/lib/loop_guard.py cannot be loaded, or cwd is absent so the
      counter cannot be scoped: when cwd is absent this hook falls through
      to its legacy advisory-only behavior (synthetic payloads only); when
      cwd is present but the module cannot load, exit 0 silently (same
      rationale as a failed counter write - never emit an advisory without
      a loop bound).
    - This hook can NEVER return a blocking decision - there is no code
      path that emits {"decision": "block", ...}. Every exit is exit 0
      with either no stdout or an advisory `additionalContext` object.

Performance: < 5 ms per call on typical transcripts - one optional config
             file read and, only when last_assistant_message is absent, a
             single reverse scan of the transcript JSONL to recover the
             most recent assistant message's text.
"""

import json
import os
import re
import sys

# Kill-switch: set this env var to 1 to disable enforcement entirely.
KILL_SWITCH_ENV = "AE_TURN_SHAPE_GUARD_DISABLE"

# Max consecutive advisories since the last new user message before this hook
# goes silent. Keeps the loop guard reachable even when CC bug #54360
# prevents stop_hook_active from propagating. This hook NEVER blocks - the
# cap only bounds how many times the advisory can re-invoke the model.
CONSECUTIVE_BLOCK_CAP = 2

# Counter state file (under .agentic/ which is gitignored). Distinct from the
# abdication hook's .abdication-guard-fire-count so the two guards never
# share state.
COUNTER_FILENAME = ".turn-shape-guard-fire-count"
# State file format: single JSON object {"count": N, "last_user_msg_count": M}

# ---------------------------------------------------------------------------
# Classifier patterns
# ---------------------------------------------------------------------------

# Loose identity-line shape: three middle-dot-separated tokens plus a
# bracketed [phase: ...] tag, anchored to the start of the (stripped) line.
# Deliberately loose - ticket IDs, branch names, and phase vocabulary vary
# across projects and sessions; this is a structural check, not a content
# check.
#
# Each `·`-delimited segment is bounded to `[^·\n]*` (not `.*`) so the regex
# cannot backtrack across segment boundaries - a plain `.*·.*·.*` pattern
# backtracks cubically on a long first line with many `·` characters and no
# `[phase:` tag (measured: 3200 dots took 13.8s, exceeding this hook's own
# 10s registered timeout and its "< 5ms per call" manifest claim).
_IDENTITY_LINE_RE = re.compile(r"^\S[^·\n]*·[^·\n]*·.*\[phase:.*\]", re.IGNORECASE)

# "## Operator decisions" heading (see content/sections/02-delegation.md
# "Operator decisions go last in the turn"). Case-insensitive, tolerant of
# 2+ leading hashes and an optional trailing colon - mirrors
# enforce-no-abdication.py's _OPERATOR_DECISIONS_HEADING_RE.
_OPERATOR_DECISIONS_HEADING_RE = re.compile(
    r"^[ \t]*#{2,}\s*operator decisions\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# A "Waiting:" line - the forced-yield / hard-stop marker.
_WAITING_LINE_RE = re.compile(r"^\s*waiting\s*:\s*\S", re.IGNORECASE)

# Terminal-completion signal. "[phase: complete]" or an unambiguous
# terminal-completion phrase. Deliberately does NOT match a bare past
# participle ("done", "shipped", "merged") - those are this repo's
# canonical non-warranted status-ping vocabulary ("unit 2 merged", "PR
# merged, pulling main") and must never be laundered into a completion
# warrant.
_COMPLETION_RE = re.compile(
    r"\[phase:\s*complete\]"
    r"|\ball\s+(?:done|complete)\b"
    r"|\bfully\s+complete\b"
    r"|\btask(?:s)?\s+(?:is|are)\s+complete\b"
    r"|\bwork\s+is\s+complete\b"
    r"|\bnothing\s+(?:left|more)\s+to\s+do\b",
    re.IGNORECASE,
)

# Best-effort "answer" warrant: a quoted fragment (>=8 chars inside the
# quote marks) anywhere in the message. Deliberately loose - this is the
# weakest of the four detectors by design (see module docstring). It
# cannot verify the quote actually echoes the operator's preceding
# message; it only recognizes the SHAPE of "I am answering by quoting
# something".
#
# The single-quote alternative is DELIBERATELY OMITTED (Skeptic Major 1):
# `'[^'\n]{8,}'` matches the text between any two apostrophes in ordinary
# English prose - "they're green, that's all", "I don't think we can't
# merge yet" both false-positive as a quoted "answer". A straight-quote
# pair heuristic is not a reliable single-quote detector on prose that
# routinely contains contractions and possessives, and this detector is
# explicitly licensed to be loose only in the "cannot verify an echo"
# sense - not in the sense of matching non-quote punctuation. Double
# quotes and a leading blockquote marker (">") remain, since neither is
# routinely produced by ordinary prose.
_QUOTED_FRAGMENT_RE = re.compile(r'"[^"\n]{8,}"|^>\s*\S.{6,}', re.MULTILINE)


def _first_nonblank_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _body_after_identity_line(text: str) -> list:
    """Return all lines AFTER the first non-blank (identity) line."""
    lines = text.splitlines()
    seen_identity = False
    body = []
    for line in lines:
        if not seen_identity:
            if line.strip():
                seen_identity = True
            continue
        body.append(line)
    return body


def _classify_warrants(text: str) -> dict:
    return {
        "decision": bool(_OPERATOR_DECISIONS_HEADING_RE.search(text)),
        "stoppage": any(_WAITING_LINE_RE.match(line) for line in text.splitlines()),
        "completion": bool(_COMPLETION_RE.search(text)),
        "answer": bool(_QUOTED_FRAGMENT_RE.search(text)),
    }


def _status_only_flag(text: str, warrants: dict) -> bool:
    """Fires when the message exceeds ~1-2 lines of prose outside the
    identity line AND carries none of the four warrants."""
    if any(warrants.values()):
        return False
    body_lines = [ln for ln in _body_after_identity_line(text) if ln.strip()]
    return len(body_lines) > 2


def _forced_yield_flag(text: str, warrants: dict):
    """Return a finding string, or None.

    Runs ONLY when `stoppage` is the SOLE warrant present. When that gate
    passes, every non-blank line after the identity line must itself be a
    "Waiting:" line - any other content flags "forced-yield: extra
    content". When "Waiting:" co-occurs with ANY other warrant, this check
    is skipped entirely (returns None unconditionally).
    """
    if not warrants["stoppage"]:
        return None
    if warrants["decision"] or warrants["completion"] or warrants["answer"]:
        return None

    body_lines = [ln for ln in _body_after_identity_line(text) if ln.strip()]
    for line in body_lines:
        if not _WAITING_LINE_RE.match(line):
            return "forced-yield: extra content beyond identity + Waiting: lines"
    return None


# ---------------------------------------------------------------------------
# Transcript fallback
# ---------------------------------------------------------------------------


def _last_assistant_text_from_transcript(transcript_path: str) -> str:
    """Best-effort reverse scan for the most recent assistant message text.

    Fallback only - used when last_assistant_message is absent/empty from
    the Stop payload. Mirrors the two transcript shapes handled by
    enforce-no-abdication.py's _scan_transcript_tail, but this hook only
    needs the text (no tool-call tracking), so the scan is simpler: stop
    at the first assistant entry found while scanning in reverse.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return ""

    try:
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            role = obj.get("role") or obj.get("type", "")
            if role != "assistant":
                continue

            content = obj.get("content")
            if content is None:
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content")

            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                # Joined with "\n", not " " (Skeptic Minor): a space-join
                # collapses a multi-block message onto a single line, so
                # _body_after_identity_line() sees an empty body and both
                # the status-only and forced-yield checks go silently inert
                # on this fallback path even though they fire correctly on
                # the primary last_assistant_message path for the same
                # text. Under-flagging is the safe failure direction (this
                # hook never blocks), but the fallback should still mirror
                # the primary path's line structure.
                return "\n".join(parts)
            return ""
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------------------
# Loop-guard loader (counter + user-message counting live in loop_guard.py)
# ---------------------------------------------------------------------------


def _load_loop_guard():
    """Best-effort dynamic import of the shared loop-guard module.

    Returns None when the module cannot be loaded (missing file, syntax
    error, snapshot copy drift). main() treats a None load as "exit 0
    silently when a cwd is present" (never emit an advisory without a loop
    bound) and as "fall through to legacy advisory behavior when no cwd is
    present" (synthetic payloads only). Loaded once at module scope; every
    invocation reuses the loaded module.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "loop_guard.py")
        spec = _ilu.spec_from_file_location("loop_guard", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_LOOP_GUARD = _load_loop_guard()


# ---------------------------------------------------------------------------
# Fire-log integration
# ---------------------------------------------------------------------------


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of this hook's advisory output.

    Called lazily from inside the finding-emission branch (never at module
    scope), mirroring enforce-tier.py's own _load_log_fire() - the
    overwhelming majority of invocations (every silent allow, and every
    kill-switched invocation) never read, compile, or exec this file at
    all.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "enforcement_log.py")
        spec = _ilu.spec_from_file_location("enforcement_log", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        # Kill-switch: operator escape hatch, checked first.
        if os.environ.get(KILL_SWITCH_ENV) == "1":
            sys.exit(0)

        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        # Layer 1 (primary re-entrancy guard): stop_hook_active is set by CC
        # when this Stop event itself was triggered by a prior Stop-hook
        # action. A re-invocation must never re-flag the same turn.
        if data.get("stop_hook_active") is True:
            sys.exit(0)

        cwd = data.get("cwd", "")
        if not isinstance(cwd, str):
            cwd = ""

        # Config toggle: DELIBERATELY INVERTED from enforce-no-abdication.py's
        # abdication_guard_enabled (which requires explicit True). This hook
        # never blocks, so it defaults ON - only an explicit `false` disables
        # it. Absent/unreadable/malformed config.json is treated as {} (i.e.
        # stays ON), not as a disable signal.
        config = {}
        if cwd:
            config_path = os.path.join(cwd, ".agentic", "config.json")
            try:
                with open(config_path, "r") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                config = {}
        if config.get("turn_shape_guard_enabled") is False:
            sys.exit(0)

        # Layer 2 (counter cap backstop for CC bug #54360): read the current
        # advisory count and the user-message count at the last advisory. If
        # a new genuine user message has arrived since, reset the counter
        # (genuine new turn). When count >= CONSECUTIVE_BLOCK_CAP, exit 0
        # silently - a blocked conductor gets at most CAP advisories before
        # this hook goes silent. The counter is only engaged when a cwd is
        # available to scope it; the CC Stop payload always carries cwd, so
        # the absent-cwd case is synthetic payloads only, where this hook
        # falls through to its legacy advisory-only behavior rather than
        # silently swallowing findings.
        lg = _LOOP_GUARD
        loop_guard_engaged = False
        current_user_msg_count = 0
        state = {"count": 0, "last_user_msg_count": 0}
        if cwd:
            if lg is None:
                # Loop-guard machinery unavailable - cannot bound an advisory.
                # Fail open (never emit an advisory without a loop bound).
                sys.exit(0)
            loop_guard_engaged = True
            transcript_path = data.get("transcript_path", "")
            if not isinstance(transcript_path, str):
                # A non-string value (e.g. a number) would reach open() in
                # loop_guard.count_user_messages, which Python treats as a raw
                # file descriptor - guard it here, mirroring the sibling hook.
                transcript_path = ""
            if transcript_path:
                current_user_msg_count = lg.count_user_messages(transcript_path)

            state = lg.read_counter(cwd, COUNTER_FILENAME)
            # If the user has sent a new message since the last advisory,
            # reset.
            if current_user_msg_count > state["last_user_msg_count"]:
                lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
                state = {"count": 0, "last_user_msg_count": current_user_msg_count}

            if state["count"] >= CONSECUTIVE_BLOCK_CAP:
                # CAP reached - no more advisories this turn. Prevents the
                # re-invocation loop when stop_hook_active fails to propagate.
                sys.exit(0)

        # Resolve message text: prefer the pre-extracted field, fall back to
        # a transcript scan.
        msg_text = data.get("last_assistant_message", "")
        if not isinstance(msg_text, str):
            msg_text = ""

        if not msg_text.strip():
            transcript_path = data.get("transcript_path", "")
            if isinstance(transcript_path, str) and transcript_path:
                msg_text = _last_assistant_text_from_transcript(transcript_path)

        if not msg_text.strip():
            # No message text available - nothing to classify.
            sys.exit(0)

        findings = []

        # 1. Identity-line check.
        identity_line = _first_nonblank_line(msg_text)
        if not identity_line or not _IDENTITY_LINE_RE.match(identity_line.strip()):
            findings.append(
                "identity line missing or malformed - expected "
                "`DS-123 · fix/foo · [phase: skeptic-review]` "
                "(two `·`-separated tokens then a bracketed [phase: ...] tag)"
            )

        # 2. Warrant classification (authoritative).
        warrants = _classify_warrants(msg_text)

        # 3a. Status-only flag.
        if _status_only_flag(msg_text, warrants):
            findings.append(
                "status-only turn - no decision/stoppage/completion/answer warrant present"
            )

        # 3b. Forced-yield shape check (strictly subordinate to 2).
        forced_yield_finding = _forced_yield_flag(msg_text, warrants)
        if forced_yield_finding:
            findings.append(forced_yield_finding)

        if not findings:
            # Clean turn - reset the advisory counter (when engaged) and
            # silent allow, no telemetry.
            if loop_guard_engaged:
                lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
            sys.exit(0)

        reason = "; ".join(findings)
        # Only emit the advisory if the loop bound can be persisted. When the
        # counter is engaged, persist count+1 BEFORE emitting; if persistence
        # fails (unwritable .agentic/, full disk, etc.), exit 0 silently - an
        # advisory whose count cannot be recorded loses its loop bound and
        # can cause an unbounded advisory loop when stop_hook_active also
        # fails (CC bug #54360).
        if loop_guard_engaged:
            new_count = state["count"] + 1
            if not lg.write_counter(cwd, COUNTER_FILENAME, new_count, current_user_msg_count):
                sys.exit(0)
        # Decision print comes FIRST, unconditionally. Telemetry is loaded
        # and called only after the decision has reached stdout, wrapped in
        # its own try/except so a raising log_fire can never suppress or
        # follow this advisory - matches the enforce-*.py convention (see
        # hooks/lib/enforcement_log.py manifest "Failure modes").
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "Stop",
                        "additionalContext": "TURN-SHAPE: " + reason,
                    }
                }
            )
        )
        try:
            _load_log_fire()(data, "enforce-turn-shape", "allow_advisory", reason)
        except Exception:
            pass
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open). This
        # hook must NEVER block the stop.
        sys.exit(0)


if __name__ == "__main__":
    main()
