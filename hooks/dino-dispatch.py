#!/usr/bin/env python3
"""
Purpose: Per-event hook dispatcher for the Claude Code agentic-engineering adapter.
         Reads a single JSON event payload from stdin, discovers ordered leaf scripts
         in hooks/<event>.d/, invokes each via an explicit interpreter (mode-independent,
         no +x requirement), merges their outputs per event-conditional rules, and emits
         ONE merged JSON object to stdout. Always exits 0; a missing/broken/timed-out
         leaf is skipped and logged to stderr - never fatal.

Public API: CLI: python3 hooks/dino-dispatch.py <Event>
            where <Event> in {UserPromptSubmit, Stop, SessionStart, SessionEnd,
            PreToolUse}. Reads JSON from stdin, writes one JSON object to stdout,
            exits 0 always.

            Leaf interface contract (what a leaf author must implement):
              stdin  - the raw JSON event payload (same bytes the dispatcher received)
              stdout - EITHER one JSON object OR plain text (never both)
              exit   - any code; non-zero is logged+skipped, dispatcher continues
              JSON output fields consumed by merger:
                systemMessage          (str) - concatenated in prefix order, \n\n-joined
                additionalContext      (str, top-level or hookSpecificOutput.additionalContext)
                                       - concatenated in prefix order, \n-joined
                decision               (str "block") - block-honoring events only
                reason                 (str) - paired with decision:block
                continue               (bool False) - if any leaf returns false, propagated
                hookSpecificOutput.permissionDecision  - PreToolUse only; strictest wins
                hookSpecificOutput.permissionDecisionReason - concatenated
              Plain-text stdout: treated as additionalContext for context-bearing events
              (UserPromptSubmit, SessionStart); logged+ignored for all other events.
              Empty stdout: fine; pure side-effect leaf.

            PreToolUse matcher header (must appear in the first 20 lines of the leaf):
              # dino-matcher: <regex>
              Example: # dino-matcher: (Task|AskUserQuestion)
              The regex is tested via re.fullmatch against tool_name from the payload.
              A leaf with NO dino-matcher header NEVER matches for PreToolUse
              (non-PreToolUse events ignore the header entirely).

            Event -> leaf dir mapping (all dirs relative to this file's directory):
              UserPromptSubmit -> userpromptsubmit.d/
              Stop             -> stop.d/
              SessionStart     -> sessionstart.d/
              SessionEnd       -> sessionend.d/
              PreToolUse       -> pretooluse.d/
            Leaves are ordered by filename ascending (zero-padded numeric prefixes
            like 010-, 020- control run order). Non-regular files are skipped.

Upstream deps: Python 3 stdlib only (json, os, pathlib, re, subprocess, sys).
               No external dependencies.

Downstream consumers: Claude Code hook runner (all 5 registered events).
                      Wired via ~/.claude/settings.json by .claude/install.sh.

Failure modes:
    - Missing leaf dir: emit empty-merge result (suppressOutput:true or nothing for
      PreToolUse no-match fast-path), exit 0. Never crashes.
    - Leaf non-zero exit / timeout / exec error: logged to stderr, skipped.
    - Leaf unparseable output: plain text routed to additionalContext for
      context-bearing events; logged+ignored for others.
    - Unknown extension + no shebang: leaf skipped with stderr log.
    - Any unexpected dispatcher error: prints safe fallback object and exits 0.

Performance: Dominated by leaf subprocess wall-clock. PER_LEAF_TIMEOUT=10s hard cap
             per leaf. PreToolUse fast-path (zero matching leaves) skips all subprocesses
             and cold-starts - important because PreToolUse fires on EVERY tool call.
             python3 cold-start ~15-30ms; dispatcher adds <5ms overhead per leaf.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum seconds a single leaf may run before being force-killed and skipped.
PER_LEAF_TIMEOUT = 10

# Events where decision:block is honored (from harness docs).
BLOCK_HONORING_EVENTS = {"Stop", "UserPromptSubmit", "PostToolUse", "SubagentStop", "PreCompact"}

# Events where leaf plain-text stdout is treated as additionalContext.
CONTEXT_BEARING_EVENTS = {"UserPromptSubmit", "SessionStart"}

# Mapping from CLI event name to leaf dir name (relative to this file's parent).
EVENT_TO_DIR = {
    "UserPromptSubmit": "userpromptsubmit.d",
    "Stop": "stop.d",
    "SessionStart": "sessionstart.d",
    "SessionEnd": "sessionend.d",
    "PreToolUse": "pretooluse.d",
}

# Extension -> interpreter
EXT_TO_INTERPRETER = {
    ".sh": "bash",
    ".py": "python3",
    ".js": "node",
}

# Number of lines to scan for a shebang or dino-matcher header.
HEADER_SCAN_LINES = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    """Write a single-line diagnostic to stderr (visible under claude --debug)."""
    print(f"[dino-dispatch] {msg}", file=sys.stderr)


def _resolve_interpreter(leaf: Path) -> Optional[str]:
    """
    Return the interpreter string for a leaf, or None if undeterminable.

    Resolution order:
      1. Known extension (.sh, .py, .js).
      2. Shebang line (first non-empty line starting with #!).
    If neither resolves, returns None and the caller skips+logs the leaf.
    """
    interp = EXT_TO_INTERPRETER.get(leaf.suffix)
    if interp:
        return interp
    # Try shebang
    try:
        with leaf.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(HEADER_SCAN_LINES):
                line = fh.readline()
                if not line:
                    break
                line = line.rstrip()
                if line.startswith("#!"):
                    parts = line[2:].strip().split()
                    if parts:
                        # Use only the last path component (e.g. /usr/bin/env python3 -> python3)
                        # or the raw interpreter path.
                        if parts[0].endswith("/env") and len(parts) > 1:
                            return parts[1]
                        return parts[0].split("/")[-1]
    except OSError as exc:
        _log(f"shebang read failed for {leaf.name}: {exc}")
    return None


def _extract_matcher(leaf: Path) -> Optional[str]:
    """
    Return the regex pattern from the first `# dino-matcher: <pattern>` line
    found in the leaf's first HEADER_SCAN_LINES lines, or None if absent.
    """
    try:
        with leaf.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(HEADER_SCAN_LINES):
                line = fh.readline()
                if not line:
                    break
                m = re.match(r"^#\s*dino-matcher:\s*(.+)$", line.rstrip())
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return None


def _discover_leaves(leaf_dir: Path) -> List[Path]:
    """
    Return regular files in leaf_dir sorted by filename ascending.
    Returns [] if the dir is missing or empty (graceful).
    """
    if not leaf_dir.is_dir():
        return []
    leaves = [p for p in leaf_dir.iterdir() if p.is_file()]
    leaves.sort(key=lambda p: p.name)
    return leaves


def _run_leaf(leaf: Path, stdin_bytes: bytes):
    """
    Invoke a single leaf with the given stdin bytes.

    Returns (returncode, stdout_text, stderr_text).
    On subprocess.TimeoutExpired or any OS-level error, returns (-1, "", error_msg).
    The caller is responsible for logging and deciding whether to skip.
    """
    interp = _resolve_interpreter(leaf)
    if interp is None:
        return (-1, "", f"unknown interpreter for {leaf.name}")
    try:
        result = subprocess.run(
            [interp, str(leaf)],
            input=stdin_bytes,
            capture_output=True,
            timeout=PER_LEAF_TIMEOUT,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        return (result.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        return (-1, "", f"timeout after {PER_LEAF_TIMEOUT}s")
    except OSError as exc:
        return (-1, "", str(exc))


# ---------------------------------------------------------------------------
# Permission decision ranking (PreToolUse)
# ---------------------------------------------------------------------------

_PERM_RANK = {"allow": 0, "ask": 1, "defer": 2, "deny": 3}


def _perm_rank(decision) -> int:
    if decision is None:
        return -1
    return _PERM_RANK.get(str(decision).lower(), -1)


# ---------------------------------------------------------------------------
# Merge accumulator
# ---------------------------------------------------------------------------

class Merger:
    """Accumulates leaf outputs and produces the final merged object."""

    def __init__(self, event: str) -> None:
        self.event = event
        self.system_messages: List[str] = []
        self.additional_contexts: List[str] = []
        self.best_perm_decision: Optional[str] = None
        self.best_perm_rank: int = -1
        self.perm_reasons: List[str] = []
        self.block_reason: Optional[str] = None
        self.continue_false: bool = False

    def ingest(self, leaf: Path, stdout: str) -> None:
        """Parse a leaf's stdout and accumulate its contributions."""
        text = stdout.strip()
        parsed: Optional[Dict] = None
        if text:
            try:
                candidate = json.loads(text)
                if isinstance(candidate, dict):
                    parsed = candidate
            except (json.JSONDecodeError, ValueError):
                pass

        if parsed is not None:
            # --- systemMessage ---
            sm = parsed.get("systemMessage")
            if isinstance(sm, str) and sm.strip():
                self.system_messages.append(sm)

            # --- additionalContext (top-level or nested) ---
            ac = parsed.get("additionalContext")
            if not isinstance(ac, str):
                hso = parsed.get("hookSpecificOutput")
                if isinstance(hso, dict):
                    ac = hso.get("additionalContext")
            if isinstance(ac, str) and ac.strip():
                self.additional_contexts.append(ac)

            # --- decision:block (block-honoring events only, never PreToolUse) ---
            if self.event in BLOCK_HONORING_EVENTS and self.event != "PreToolUse":
                decision = parsed.get("decision")
                if decision == "block" and self.block_reason is None:
                    self.block_reason = parsed.get("reason", "")

            # --- continue:false ---
            if parsed.get("continue") is False:
                self.continue_false = True

            # --- permissionDecision (PreToolUse only) ---
            if self.event == "PreToolUse":
                perm = parsed.get("hookSpecificOutput", {})
                perm_decision = None
                perm_reason = None
                if isinstance(perm, dict):
                    perm_decision = perm.get("permissionDecision")
                    perm_reason = perm.get("permissionDecisionReason")
                # Also accept top-level (some leaves may emit flat)
                if perm_decision is None:
                    perm_decision = parsed.get("permissionDecision")
                    perm_reason = parsed.get("permissionDecisionReason")
                rank = _perm_rank(perm_decision)
                if rank > self.best_perm_rank:
                    self.best_perm_rank = rank
                    self.best_perm_decision = perm_decision
                if rank > 0 and isinstance(perm_reason, str) and perm_reason.strip():
                    self.perm_reasons.append(perm_reason)

        else:
            # Plain text output
            if text and self.event in CONTEXT_BEARING_EVENTS:
                self.additional_contexts.append(text)
            elif text:
                _log(f"plain-text output from {leaf.name} ignored for event {self.event}")

    def build(self) -> Dict:
        """Produce the final merged output dict."""
        out = {}

        # systemMessage: concatenated in prefix order, \n\n-joined
        if self.system_messages:
            out["systemMessage"] = "\n\n".join(self.system_messages)

        # additionalContext -> hookSpecificOutput.additionalContext
        hso = {}
        if self.additional_contexts:
            hso["additionalContext"] = "\n".join(self.additional_contexts)

        # permissionDecision (PreToolUse only, omit if no leaf returned one)
        if self.event == "PreToolUse" and self.best_perm_rank >= 0:
            hso["permissionDecision"] = self.best_perm_decision
            if self.perm_reasons:
                hso["permissionDecisionReason"] = "\n".join(self.perm_reasons)

        if hso:
            hso["hookEventName"] = self.event
            out["hookSpecificOutput"] = hso

        # decision:block (never for PreToolUse)
        if self.event != "PreToolUse" and self.block_reason is not None:
            out["decision"] = "block"
            out["reason"] = self.block_reason

        # continue:false propagation
        if self.continue_false:
            out["continue"] = False

        # suppressOutput: true when nothing user-facing was produced and
        # no decision/permissionDecision was set
        has_user_output = bool(self.system_messages or self.additional_contexts)
        has_decision = ("decision" in out) or (
            self.event == "PreToolUse" and self.best_perm_rank >= 0
        )
        if not has_user_output and not has_decision:
            out["suppressOutput"] = True

        return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Resolve event from CLI arg
    if len(sys.argv) < 2:
        _log("no event argument supplied; treating as unknown")
        print(json.dumps({"suppressOutput": True}))
        sys.exit(0)

    event = sys.argv[1]
    if event not in EVENT_TO_DIR:
        _log(f"unknown event '{event}'; emitting suppressOutput")
        print(json.dumps({"suppressOutput": True}))
        sys.exit(0)

    # Buffer stdin ONCE so every leaf receives the same bytes
    try:
        stdin_bytes = sys.stdin.buffer.read()
    except Exception as exc:
        _log(f"stdin read failed: {exc}")
        stdin_bytes = b"{}"

    # Parse tool_name for PreToolUse matcher gating (used only for PreToolUse)
    tool_name = None
    if event == "PreToolUse":
        try:
            payload = json.loads(stdin_bytes.decode("utf-8", errors="replace"))
            tool_name = payload.get("tool_name") if isinstance(payload, dict) else None
        except Exception:
            tool_name = None

    # Discover leaves
    hooks_dir = Path(__file__).resolve().parent
    leaf_dir = hooks_dir / EVENT_TO_DIR[event]
    all_leaves = _discover_leaves(leaf_dir)

    # PreToolUse: filter by dino-matcher; fast-path when nothing matches
    if event == "PreToolUse":
        matched_leaves = []
        for leaf in all_leaves:
            pattern = _extract_matcher(leaf)
            if pattern is None:
                # No header -> never matches
                continue
            if tool_name is not None:
                try:
                    if re.fullmatch(pattern, tool_name):
                        matched_leaves.append(leaf)
                except re.error as exc:
                    _log(f"bad dino-matcher regex in {leaf.name}: {exc}")
        if not matched_leaves:
            # Fast-path: zero leaves matched, emit nothing/empty and exit
            # (no subprocesses spawned - keeps every-tool-call overhead minimal)
            sys.exit(0)
        leaves_to_run = matched_leaves
    else:
        leaves_to_run = all_leaves

    merger = Merger(event)

    for leaf in leaves_to_run:
        rc, stdout, stderr = _run_leaf(leaf, stdin_bytes)
        if rc == -1:
            # exec-level failure (timeout, OS error, unknown interpreter)
            _log(f"leaf {leaf.name} failed: {stderr}")
            continue
        if rc != 0:
            _log(f"leaf {leaf.name} exited {rc}; stderr: {stderr.rstrip()}")
            continue
        if stderr.strip():
            _log(f"leaf {leaf.name} stderr: {stderr.rstrip()}")
        merger.ingest(leaf, stdout)

    result = merger.build()
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Last-resort catch: print a safe object and exit 0 regardless
        _log(f"unexpected dispatcher error: {exc}")
        event_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        if event_arg == "PreToolUse":
            # PreToolUse: emit nothing rather than a suppress object
            pass
        else:
            print(json.dumps({"suppressOutput": True}))
        sys.exit(0)
