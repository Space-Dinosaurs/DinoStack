#!/usr/bin/env python3
"""
Purpose: Shared two-layer loop-guard machinery for AE's Python Stop hooks
         that act on the conductor's final assistant message
         (enforce-no-abdication.py and enforce-turn-shape.py). On the Claude
         Code harness, a Stop hook's output - a block decision (abdication)
         or an `additionalContext` advisory (turn-shape) - re-invokes the
         model immediately, without waiting for a user turn. When the
         conductor is blocked on a user decision it has nothing substantive
         to say, so it writes the same non-conforming turn again, the hook
         fires again, and the pair loops until the harness's own 9-
         consecutive-block override kicks in. Two layers bound that loop:

           Layer 1: the `stop_hook_active` payload flag - set by CC when this
                    Stop event itself was triggered by a prior Stop-hook
                    action. Checked right after stdin parse, exits the hook
                    silently. This is the primary re-entrancy guard.
           Layer 2: a counter-cap backstop for CC bug #54360 (stop_hook_active
                    can fail to propagate when a UserPromptSubmit hook
                    interleaves system reminders - and this repo has such a
                    hook). State lives at <cwd>/.agentic/<COUNTER_FILENAME>.
                    The counter increments and persists BEFORE each action is
                    emitted; an action whose count cannot be persisted is NOT
                    emitted (fail-open toward allow, so a block/advisory that
                    loses its loop bound never fires). The counter resets on
                    a clean turn and on a genuine new user message (counted
                    via count_user_messages, which filters out tool_result
                    lines, meta lines, and harness-injected notifications -
                    see is_genuine_user_turn and is_harness_injected_text).

         Each hook parameterizes its own COUNTER_FILENAME and
         CONSECUTIVE_BLOCK_CAP so the two guards never share state; the
         counter file is under .agentic/, which is gitignored.

Public API (module-level functions, no class):
    counter_path(cwd, counter_filename) -> str
        Path to the counter state file: <cwd>/.agentic/<counter_filename>.
    read_counter(cwd, counter_filename) -> dict
        Reads {"count": N, "last_user_msg_count": M}. Returns zeros on any
        error (missing file, unparseable JSON, non-dict value).
    write_counter(cwd, counter_filename, count, last_user_msg_count) -> bool
        Persists counter state via a per-process pid-suffixed tmp file plus
        os.replace (atomic). Returns True on success, False on any failure.
        Callers MUST check the return value when deciding whether to emit an
        action: an action emitted without a successful counter write loses
        its loop bound and can cause an infinite loop when stop_hook_active
        also fails (CC bug #54360). Fail toward allow on any write failure.
    reset_counter(cwd, counter_filename, current_user_msg_count) -> None
        Resets the consecutive-action count to 0, recording the current
        genuine-user-message count so the reset is not re-triggered by the
        same user turn. Best-effort (return value intentionally ignored).
    is_genuine_user_turn(obj) -> bool
        True only for a GENUINE human turn line in a CC transcript. See the
        function docstring for the tool_result / meta / harness-injected
        exclusions that are load-bearing for the #54360 backstop.
    count_user_messages(transcript_path) -> int
        Counts genuine human turns in the transcript JSONL. Returns 0 on any
        error. Never counts tool_result or meta lines.
    last_genuine_user_text(transcript_path) -> str
        Returns the text of the most recent genuine human turn (reverse
        scan), or "" on any error or when none is found. Added DS-155 for
        enforce-turn-shape.py's answer-warrant detector. Shares the same
        tool_result / meta / harness-injected exclusions as
        is_genuine_user_turn via the private _extract_genuine_user_text
        helper - never duplicate that parsing logic at a call site.
    is_harness_injected_text(text) -> bool
        True iff the text carries one of the harness-injected markers that
        arrive as `type:"user"` lines without isMeta (background task-
        completion notifications, <system-reminder>, <command-name>) and
        must not be mistaken for a genuine human turn.

Upstream deps: Python 3 stdlib only (json, os). Imports the sibling
               hooks/lib/repo_root.py module via an isolated
               importlib.util.spec_from_file_location load (_load_repo_root
               - round-2 rework: was a `sys.path.insert(0, ...)` + `from
               repo_root import ...` pair, a global process-wide side
               effect for every caller that dynamically loads this file)
               - anchors every .agentic/ path below to the repo root
               instead of the raw cwd argument, since __file__ resolves
               correctly however this module itself was loaded (plain
               import or the dynamic importlib loader below). Writes ONLY
               [resolved root]/.agentic/<counter_filename> (creates that
               .agentic/ dir with os.makedirs(exist_ok=True) if absent).
               Reads ONLY that file and, in count_user_messages and
               last_genuine_user_text, a transcript JSONL path.

Downstream consumers: hooks/enforce-no-abdication.py (counter filename
                       .abdication-guard-fire-count, cap 2) and
                       hooks/enforce-turn-shape.py (counter filename
                       .turn-shape-guard-fire-count, cap 2). Both load this
                       module lazily via a per-hook `_load_loop_guard()`
                       helper (mirroring the hooks/lib/enforcement_log.py
                       precedent) and exit 0 silently if it cannot be loaded
                       - never emitting a block/advisory without the loop
                       bound this module provides.

Failure modes: Fully fail-open and silent, matching every enforce-*.py
               hook's own contract.
    - read_counter: any error (missing file, corrupt JSON, non-dict) returns
      {"count": 0, "last_user_msg_count": 0} - never raises.
    - write_counter: any error (unwritable .agentic/, full disk, corrupt
      tmp, os.replace failure) returns False - never raises. The caller
      decides what False means (both consumers treat it as "do not emit").
    - reset_counter: swallows write_counter's failure (the next emit attempt
      re-reads the persisted count and re-applies the reset check).
    - count_user_messages: any error returns 0 - never raises.
    - last_genuine_user_text: any error (missing file, unparseable JSON on
      every line, no genuine turn found) returns "" - never raises.
    - Concurrent hook invocations: each write uses a pid-suffixed tmp name
      (`<counter>.tmp.<os.getpid()>`) so two concurrent processes never
      share a staging path; os.replace makes the final rename atomic. A
      peer's in-flight tmp (a legacy fixed name or a different pid's
      suffixed name) is never opened, truncated, or renamed away by this
      module.

Performance: < 1 ms per call on typical transcripts - one optional state
             file read/write and, only when count_user_messages is called,
             a single forward scan of the transcript JSONL. Both hooks call
             the counter functions on every invocation that reaches their
             loop-guard section, so the module is loaded once per process at
             hook startup and reused.
"""

from __future__ import annotations

import json
import os


def _load_repo_root():
    """Best-effort dynamic import of the sibling hooks/lib/repo_root.py
    module. Round-2 rework (Minor): replaces a `sys.path.insert(0, ...)` +
    `from repo_root import ...` pair - a GLOBAL process-wide side effect
    that shadowed any other `repo_root`/`git_worktree`/`loop_guard`/
    `enforcement_log`-named module for the rest of the process, for every
    caller that dynamically loads this file via importlib.util. Uses the
    same isolated importlib.util.spec_from_file_location loader every
    other Python .agentic/ consumer in this repo uses."""
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "repo_root.py")
        spec = _ilu.spec_from_file_location("repo_root", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_REPO_ROOT = _load_repo_root()


def resolve_agentic_cwd(cwd: str) -> str:
    """Thin wrapper preserving this module's pre-existing call shape
    (`resolve_agentic_cwd(cwd)`) for its own callers below. Falls back to
    cwd unchanged if the resolver failed to load, matching this module's
    fully fail-open contract."""
    if _REPO_ROOT is None:
        return cwd
    try:
        return _REPO_ROOT.resolve_agentic_cwd(cwd)
    except Exception:
        return cwd


# Harness-injected `type:"user"` lines that are NOT a genuine human turn even
# though they carry real text content and no isMeta flag. Confirmed against
# live transcripts under ~/.claude/projects/: a completed background-task
# notification arrives as {"type":"user","message":{"content":"<task-
# notification>...</task-notification>"}} with isMeta ABSENT (not True) - a
# single busy session can carry dozens of these against a handful of genuine
# human turns (re-measured over the 120 most recent local transcripts: the
# highest per-session count of <task-notification> occurrences found was 37;
# this figure is corpus-snapshot-dependent and will drift as new transcripts
# accrue - re-measure before relying on an exact number). Counting it as a
# human-turn boundary breaks the reverse scan in enforce-no-abdication.py's
# _scan_transcript_tail: it stops at the notification and never reaches the
# tool_use the conductor issued earlier in the SAME human turn, turning the
# single most common compliant conductor shape (spawn -> notification ->
# "Unit N returned; proceeding with unit N+1 unless you say otherwise") into
# a false BLOCK.
# ALL FOUR markers below are load-bearing - none is a mere backstop.
# <system-reminder> and <command-name> lines were also checked directly
# against real transcripts and FREQUENTLY arrive WITHOUT isMeta:true - this
# is common, not a rare edge case. Removing any entry from this tuple
# reclassifies real harness-injected lines as genuine human turns and
# reintroduces the original Critical this classifier exists to prevent
# (harness notifications treated as human turns, blocking the dominant
# conductor turn shape for any session containing a slash-command
# invocation) - do not prune this tuple without re-verifying against a
# fresh transcript sample first.
_HARNESS_INJECTED_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "<system-reminder>",
    "<command-name>",
)


def is_harness_injected_text(text: str) -> bool:
    return any(marker in text for marker in _HARNESS_INJECTED_MARKERS)


# ---------------------------------------------------------------------------
# Counter file helpers
# ---------------------------------------------------------------------------


def counter_path(cwd: str, counter_filename: str) -> str:
    return os.path.join(resolve_agentic_cwd(cwd), ".agentic", counter_filename)


def read_counter(cwd: str, counter_filename: str) -> dict:
    """Read {"count": N, "last_user_msg_count": M}. Returns zeros on any error."""
    try:
        path = counter_path(cwd, counter_filename)
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


def write_counter(cwd: str, counter_filename: str, count: int, last_user_msg_count: int) -> bool:
    """Write counter state. Returns True on success, False on any failure.

    The caller MUST check the return value when deciding whether to emit a
    block/advisory: an action emitted without a successful counter write
    loses its loop bound and can cause an infinite loop when stop_hook_active
    also fails (CC bug #54360). Fail toward allow on any write failure.
    """
    try:
        agentic_dir = os.path.join(resolve_agentic_cwd(cwd), ".agentic")
        os.makedirs(agentic_dir, exist_ok=True)
        path = counter_path(cwd, counter_filename)
        # Per-process tmp suffix: two concurrent hook invocations must never
        # share a staging path (a fixed name would let one process's write
        # clobber or race the other's os.replace).
        tmp = path + ".tmp." + str(os.getpid())
        with open(tmp, "w") as f:
            json.dump({"count": count, "last_user_msg_count": last_user_msg_count}, f)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def reset_counter(cwd: str, counter_filename: str, current_user_msg_count: int) -> None:
    """Reset consecutive action count (new user turn detected). Best-effort."""
    write_counter(cwd, counter_filename, 0, current_user_msg_count)  # return value intentionally ignored


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def _extract_genuine_user_text(obj: dict):
    """Return the genuine human-turn text for `obj`, or None if `obj` is not
    a genuine human turn line.

    Single source of truth for the tool_result / meta / harness-injected
    exclusions - is_genuine_user_turn and last_genuine_user_text both call
    this rather than re-parsing the transcript shape independently (the same
    single-parser discipline _segment/_regions follow in
    enforce-turn-shape.py, for the same reason: two independent parsers of
    the same shape is exactly how a convergence failure gets introduced).

    Critical loop-safety constraint: in real Claude Code transcripts EVERY
    tool_result is recorded as a `type:"user"` line (the model running a tool
    while "proceeding" produces tool_result lines with type=="user"). If those
    counted as user turns, the #54360 backstop counter would reset on every
    re-entry that ran a tool, pinning count at 1 and never reaching the cap -
    an infinite block loop. So a genuine human turn is a `type:"user"` line
    that carries real text content and is NEITHER a tool_result NOR a meta line
    NOR a harness-injected notification (see _HARNESS_INJECTED_MARKERS) -
    background task-completion notifications arrive as exactly this shape
    (type:"user", isMeta absent, plain-string content) and must not be
    mistaken for a human turn boundary.
    """
    if not isinstance(obj, dict):
        return None
    # Top-level role in CC transcripts is typically absent for user lines;
    # the discriminator is `type`. Accept either shape defensively.
    role = obj.get("role") or obj.get("type", "")
    if role != "user":
        return None
    # Exclude meta/system-injected lines (e.g. interleaved system reminders).
    if obj.get("isMeta") is True:
        return None

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
        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        if has_tool_result:
            return None
        # Genuine turn requires at least one real text block with text that
        # is NOT a harness-injected marker (see _HARNESS_INJECTED_MARKERS).
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if t.strip() and not is_harness_injected_text(t):
                    return t
            elif isinstance(b, str) and b.strip() and not is_harness_injected_text(b):
                return b
        return None
    if isinstance(content, dict):
        if content.get("type") == "tool_result":
            return None
        if content.get("type") == "text":
            t = content.get("text", "")
            if t.strip() and not is_harness_injected_text(t):
                return t
        return None
    if isinstance(content, str):
        # Real transcripts show harness task-notifications delivered as a
        # bare string here (type:"user", isMeta absent) - see
        # _HARNESS_INJECTED_MARKERS. These are not genuine human turns.
        if content.strip() and not is_harness_injected_text(content):
            return content
        return None
    return None


def is_genuine_user_turn(obj: dict) -> bool:
    """Return True only for a GENUINE human turn line in a CC transcript.

    See _extract_genuine_user_text for the tool_result / meta / harness-
    injected exclusion rationale this delegates to.
    """
    return _extract_genuine_user_text(obj) is not None


def count_user_messages(transcript_path: str) -> int:
    """Count GENUINE human turns in the transcript. Returns 0 on error.

    Counts only real human messages - NOT tool_result lines (which CC records
    as type:"user") and NOT meta lines. See is_genuine_user_turn for the
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
                if is_genuine_user_turn(obj):
                    count += 1
        return count
    except Exception:
        return 0


def last_genuine_user_text(transcript_path: str) -> str:
    """Return the text of the most recent GENUINE human turn in the
    transcript, or "" on any error or when none is found.

    Reverse scan (most recent line first), stopping at the first line for
    which _extract_genuine_user_text returns non-None - mirrors
    enforce-no-abdication.py's own reverse-scan pattern
    (_scan_transcript_tail) and enforce-turn-shape.py's
    _last_assistant_text_from_transcript. Used by enforce-turn-shape.py's
    answer-warrant detector (DS-155) to find the operator's actual question,
    filtering out tool_result lines, meta lines, and harness-injected
    notifications the same way count_user_messages does for its boundary.
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
            text = _extract_genuine_user_text(obj)
            if text is not None:
                return text
        return ""
    except Exception:
        return ""
