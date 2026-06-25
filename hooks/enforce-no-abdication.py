#!/usr/bin/env python3
"""
Purpose: Stop hook that mechanically reduces conductor abdication - ending a
         turn by asking the user permission to proceed with an obvious
         non-destructive next step. Detects permission-seeking interrogatives
         in the final assistant message and blocks the stop, injecting a
         "proceed" directive. Mechanizes the prose in
         content/sections/02-delegation.md (Proactive autonomy /
         default-and-proceed), exactly as enforce-background-spawn.py
         mechanized its rule.

         Scoped to the MAIN session Stop event only (not SubagentStop), so
         it governs the conductor, not Workers.

         Two loop-guard layers are required due to CC bug #54360 (stop_hook_active
         can fail to propagate when a UserPromptSubmit hook interleaves system
         reminders - and this repo has such a hook). Layer 1: check stop_hook_active
         flag (primary). Layer 2: counter-based cap (backstop) that counts
         consecutive blocks since the last new user message and halts at CAP.

         Detection is precision-biased (false-negative-biased): a missed
         abdication leaves the conductor as-is (status quo); a false positive
         forces continuation on a turn the conductor genuinely intended to stop,
         which is recoverable but annoying. Negative gate token set chosen to
         match legitimate stop conditions: destructive operations, hard-stop
         branch signals, and correct surface-and-proceed markers.

Public API: Run as a Claude Code Stop hook (matcher: "*"). Reads JSON from
            stdin, writes {"decision":"block","reason":"<directive>"} to stdout
            when blocking, exits 0 always. Writes nothing when allowing. Emits
            EITHER exactly one valid JSON object OR nothing - never partial or
            garbage stdout (guarded per CC issue #55754 which causes infinite
            loops on invalid Stop hook output).

Upstream deps: Python 3 stdlib only (json, os, re, sys). No external dependencies.

Downstream consumers: Claude Code hook runner (Stop event, matcher "*"). Wired
                      via ~/.claude/settings.json by .claude/install.sh AFTER
                      stop-context.js so the context writer runs first.

Failure modes:
    - Malformed stdin: fail-open (exit 0, emit nothing). Hook bugs must never
      brick the session - fail-open preserves default CC behavior.
    - Missing or malformed config.json: fail-open (exit 0). Default is opt-out
      (abdication_guard_enabled not exactly true = exit 0).
    - Missing transcript file or unparseable JSONL: fail-open (exit 0).
    - Any exception: fail-open via outer try/except (exit 0).
    - stop_hook_active=true: exit 0 immediately (primary re-entrancy guard).
    - Counter >= CAP: exit 0 without block (backstop for CC bug #54360).
    - Invalid/garbage stdout: guarded via atomic print-then-exit pattern;
      any exception before the print results in no stdout = allow.

Performance: < 5 ms per call on typical transcripts (one file read for config,
             a small counter file read/write, and up to two full-file scans of
             the transcript JSONL - one forward scan to count genuine human
             turns, and one reverse-from-readlines scan for the
             last-assistant-message fallback). Both transcript scans are skipped
             when transcript_path is absent; the fallback scan is skipped when
             last_assistant_message is already populated.
"""

import json
import os
import re
import sys

# Kill-switch: set this env var to 1 to disable enforcement entirely.
KILL_SWITCH_ENV = "AE_ABDICATION_GUARD_DISABLE"

# Max consecutive blocks since the last new user message before we stop blocking.
# Keeps the loop guard reachable even when CC bug #54360 prevents
# stop_hook_active from propagating.
CONSECUTIVE_BLOCK_CAP = 2

# Tail length (characters) of the assistant message to examine. Only the tail
# matters for permission-seeking interrogatives - they appear at the end.
TAIL_LENGTH = 600

# Counter state file (under .agentic/ which is gitignored).
COUNTER_FILENAME = ".abdication-guard-fire-count"
# State file format: single JSON object {"count": N, "last_user_msg_count": M}

# ---------------------------------------------------------------------------
# Classifier patterns
# ---------------------------------------------------------------------------

# Tier 1 (positive): permission-seeking phrases. Word-boundary anchored to
# avoid partial matches. Case-insensitive.
_PERMISSION_PHRASES = re.compile(
    r'\b(?:'
    r"want me to"
    r"|should i"
    r"|shall i"
    r"|would you like me to"
    r"|do you want me to"
    r"|let me know if you(?:'d| (?:like|want))"
    r"|ready (?:for me )?to proceed"
    r"|should i go ahead"
    r"|want me to go ahead"
    r')\b',
    re.IGNORECASE,
)

# Tier 2 (negative gate): hard-stop or legitimate-question signals.
# Presence of any of these tokens suppresses the block even if a permission
# phrase is present. Three groups:
#   (a) destructive/irreversible signals - blocking here would force the
#       conductor to execute an irreversible action it correctly paused on.
#   (b) product-judgment / design-fork signals - genuine "I need your
#       judgment" questions the conductor cannot derive a default for.
#   (c) correct surface-and-proceed markers ("(recommended)", "proceeding
#       with", "unless you say otherwise") - already-compliant behavior.
_NEGATIVE_GATE_PATTERNS = re.compile(
    r'(?:'
    # --- (a) destructive / irreversible ---
    r'\bdestructive\b'
    r'|\birreversible\b'
    r'|\bforce push\b'
    r'|\bforce-push\b'
    r'|\bdelete\b'
    r'|\bdrop table\b'
    r'|\bschema migration\b'
    r'|\bproduction deploy\b'
    r'|\bpermanently (?:remove|delete)\b'
    r'|\bpermanently\b'
    r'|\bcan(?:not|\'t|not) be undone\b'
    r'|\bno undo\b'
    r'|\bunrecoverable\b'
    r'|\bdata loss\b'
    r'|\bwipe\b'
    r'|\boverwrite\b'
    # --- (b) cannot-derive / credential / target-selection ---
    r'|\bcannot derive\b'
    r'|\bmissing credential\b'
    r'|\bapi key\b'
    r'|\bwhich environment\b'
    r'|\bwhich workspace\b'
    r'|\bmerge to main\b'
    # --- (b cont.) product-judgment / design-fork signals ---
    r'|\bwhich direction\b'
    r'|\bwhich approach\b'
    r'|\bwhich option\b'
    r'|\bwhich of these\b'
    r'|\bchanges the (?:data model|schema|api|contract)\b'
    r'|\bload-bearing\b'
    r'|\bdesign (?:decision|fork|choice)\b'
    # --- (c) correct surface-and-proceed markers ---
    r'|\(recommended\)'
    r'|proceeding with'
    r'|unless you say otherwise'
    r')',
    re.IGNORECASE,
)


def _is_abdication(text: str) -> bool:
    """Return True if the tail of text looks like a permission-seeking abdication.

    Precision-biased (false-negative-biased): only fire when BOTH conditions hold
    and NO negative-gate token is present. A missed abdication leaves the conductor
    as-is (status quo); a false positive forces continuation on a legitimately
    intended stop, which is recoverable but annoying.
    """
    tail = text[-TAIL_LENGTH:]

    # Negative gate first (cheaper than full regex scan).
    if _NEGATIVE_GATE_PATTERNS.search(tail):
        return False

    # Require a permission phrase.
    if not _PERMISSION_PHRASES.search(tail):
        return False

    # Require the final non-empty sentence to end with "?".
    lines = tail.splitlines()
    # Scan backwards for a non-empty line ending with "?"
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped.endswith("?")

    return False


# ---------------------------------------------------------------------------
# Counter file helpers
# ---------------------------------------------------------------------------

def _counter_path(cwd: str) -> str:
    return os.path.join(cwd, ".agentic", COUNTER_FILENAME)


def _read_counter(cwd: str) -> dict:
    """Read {"count": N, "last_user_msg_count": M}. Returns zeros on any error."""
    try:
        path = _counter_path(cwd)
        if not os.path.exists(path):
            return {"count": 0, "last_user_msg_count": 0}
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"count": 0, "last_user_msg_count": 0}
        return {
            "count": int(data.get("count", 0)),
            "last_user_msg_count": int(data.get("last_user_msg_count", 0)),
        }
    except Exception:
        return {"count": 0, "last_user_msg_count": 0}


def _write_counter(cwd: str, count: int, last_user_msg_count: int) -> None:
    """Write counter state. Fail silently."""
    try:
        agentic_dir = os.path.join(cwd, ".agentic")
        os.makedirs(agentic_dir, exist_ok=True)
        path = _counter_path(cwd)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"count": count, "last_user_msg_count": last_user_msg_count}, f)
        os.replace(tmp, path)
    except Exception:
        pass


def _reset_counter(cwd: str, current_user_msg_count: int) -> None:
    """Reset consecutive block count (new user turn detected)."""
    _write_counter(cwd, 0, current_user_msg_count)


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------

def _is_genuine_user_turn(obj: dict) -> bool:
    """Return True only for a GENUINE human turn line in a CC transcript.

    Critical loop-safety constraint: in real Claude Code transcripts EVERY
    tool_result is recorded as a `type:"user"` line (the model running a tool
    while "proceeding" produces tool_result lines with type=="user"). If those
    counted as user turns, the #54360 backstop counter would reset on every
    re-entry that ran a tool, pinning count at 1 and never reaching the cap -
    an infinite block loop. So a genuine human turn is a `type:"user"` line
    that carries real text content and is NEITHER a tool_result NOR a meta line.
    """
    if not isinstance(obj, dict):
        return False
    # Top-level role in CC transcripts is typically absent for user lines;
    # the discriminator is `type`. Accept either shape defensively.
    role = obj.get("role") or obj.get("type", "")
    if role != "user":
        return False
    # Exclude meta/system-injected lines (e.g. interleaved system reminders).
    if obj.get("isMeta") is True:
        return False

    # Locate the message content. CC shape: {"type":"user","message":{"content":...}}
    msg = obj.get("message")
    content = None
    if isinstance(msg, dict):
        content = msg.get("content")
    if content is None:
        content = obj.get("content")

    # A tool_result line is NOT a human turn. content may be:
    #   - a list of blocks, any of which has type=="tool_result"
    #   - (defensively) a single dict block with type=="tool_result"
    if isinstance(content, list):
        has_tool_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
        if has_tool_result:
            return False
        # Genuine turn requires at least one real text block with text.
        has_text = any(
            (isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip())
            or (isinstance(b, str) and b.strip())
            for b in content
        )
        return has_text
    if isinstance(content, dict):
        if content.get("type") == "tool_result":
            return False
        if content.get("type") == "text":
            return bool(content.get("text", "").strip())
        return False
    if isinstance(content, str):
        return bool(content.strip())
    return False


def _count_user_messages(transcript_path: str) -> int:
    """Count GENUINE human turns in the transcript. Returns 0 on error.

    Counts only real human messages - NOT tool_result lines (which CC records
    as type:"user") and NOT meta lines. See _is_genuine_user_turn for the
    rationale: counting tool_results here would break the #54360 loop backstop.
    """
    try:
        count = 0
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if _is_genuine_user_turn(obj):
                    count += 1
        return count
    except Exception:
        return 0


def _last_assistant_text_from_transcript(transcript_path: str) -> str:
    """Extract the last assistant message text from the transcript JSONL.

    Reads lines in reverse (tail-first) to avoid scanning the full file.
    Returns empty string on any error.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            # Handle two common transcript shapes:
            # Shape 1: {"role": "assistant", "content": [...]}
            # Shape 2: {"type": "assistant", "message": {"content": [...]}}
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
                return " ".join(parts)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        # Kill-switch: operator escape hatch.
        if os.environ.get(KILL_SWITCH_ENV) == "1":
            sys.exit(0)

        # Parse stdin JSON payload. Fail-open on any parse error.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        # Primary re-entrancy guard: stop_hook_active is set by CC when this
        # Stop event itself was triggered by a prior Stop-hook block.
        if data.get("stop_hook_active") is True:
            sys.exit(0)

        cwd = data.get("cwd", "")
        if not cwd:
            sys.exit(0)

        # Read project config. Default off (abdication_guard_enabled not exactly
        # true = exit 0). Fail-open on any read/parse error.
        config_path = os.path.join(cwd, ".agentic", "config.json")
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            if config.get("abdication_guard_enabled") is not True:
                sys.exit(0)
        except Exception:
            sys.exit(0)

        # Counter backstop (CC bug #54360 defence): read the current count and
        # the user-message count at the last block. If a new user message has
        # arrived since the last block, reset the counter (genuine new turn).
        transcript_path = data.get("transcript_path", "")
        current_user_msg_count = 0
        if transcript_path:
            current_user_msg_count = _count_user_messages(transcript_path)

        state = _read_counter(cwd)
        # If the user has sent a new message since the last block, reset.
        if current_user_msg_count > state["last_user_msg_count"]:
            _reset_counter(cwd, current_user_msg_count)
            state = {"count": 0, "last_user_msg_count": current_user_msg_count}

        if state["count"] >= CONSECUTIVE_BLOCK_CAP:
            # CAP reached - do not block further. Prevents infinite loop when
            # stop_hook_active fails to propagate (CC bug #54360).
            sys.exit(0)

        # Resolve the last assistant message text. Prefer pre-extracted field;
        # fall back to transcript scan.
        msg_text = data.get("last_assistant_message", "")
        if not isinstance(msg_text, str):
            msg_text = ""
        if not msg_text.strip() and transcript_path:
            msg_text = _last_assistant_text_from_transcript(transcript_path)

        if not msg_text.strip():
            # No message text available - cannot classify.
            sys.exit(0)

        # Run classifier.
        if not _is_abdication(msg_text):
            # Not abdication - reset counter (clean turn) and allow.
            _reset_counter(cwd, current_user_msg_count)
            sys.exit(0)

        # Abdication detected. Increment counter and block.
        new_count = state["count"] + 1
        _write_counter(cwd, new_count, current_user_msg_count)

        reason = (
            "ABDICATION GUARD: You ended your turn by asking the user permission "
            "to proceed with a non-destructive next step. The METHODOLOGY §Delegation "
            "(Proactive autonomy) rule requires you to act, not ask. Proceed with the "
            "next logical step now. Do not ask 'want me to', 'should I', 'shall I', "
            "or similar permission-seeking phrases for non-destructive work. "
            "Consult the five default sources (codebase patterns, MEMORY.md, "
            "architect plan, AGENTS.md, conservative ticket interpretation) and act. "
            "Surface a question ONLY for: (1) genuinely irreversible/destructive "
            "actions not pre-authorized, (2) information you cannot derive "
            "(credentials, product judgments), (3) ambiguous acceptance criteria "
            "with no inferable default. Everything else: proceed."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
