#!/usr/bin/env python3
"""
Purpose: Stop hook that mechanically reduces conductor abdication - ending a
         turn by asking the user permission to proceed with an obvious
         non-destructive next step, OR by announcing a surface-and-proceed
         default ("Proceeding with X unless you say otherwise") and then
         stopping without actually proceeding. Detects both shapes in the
         final assistant message and blocks the stop, injecting a "proceed"
         directive. Mechanizes the prose in content/sections/02-delegation.md
         (Proactive autonomy / default-and-proceed - which requires the
         conductor to act "in the same turn", not merely announce intent),
         exactly as enforce-background-spawn.py mechanized its rule.

         Scoped to the MAIN session Stop event only (not SubagentStop), so
         it governs the conductor, not Workers.

         Two loop-guard layers are required due to CC bug #54360 (stop_hook_active
         can fail to propagate when a UserPromptSubmit hook interleaves system
         reminders - and this repo has such a hook). Layer 1: check stop_hook_active
         flag (primary). Layer 2: counter-based cap (backstop) that counts
         consecutive blocks since the last new user message and halts at CAP.
         Both classifiers below share this same loop-guard machinery.

         Detection is precision-biased (false-negative-biased): a missed
         abdication leaves the conductor as-is (status quo); a false positive
         forces continuation on a turn the conductor genuinely intended to stop,
         which is recoverable but annoying. Two independent classifiers run per
         invocation, and a block fires if EITHER returns true:

         1. _is_abdication(): the classic permission-seeking interrogative
            check (tier1 phrase + same-sentence "?"). Suppressed by
            _HARD_NEGATIVE_GATE_PATTERNS (destructive/irreversible/design-fork
            signals - genuine stop conditions this hook must never override)
            OR by _SURFACE_AND_PROCEED_PATTERNS (unconditionally, matching
            legacy behavior - see rationale below).

         2. _is_stalled_surface_and_proceed(): NEW. A stall-commitment marker
            ("proceeding with", "unless you say otherwise" - NOT a bare
            "(recommended)", which routinely labels an already-derived choice
            with no pending action attached; see below) is only evidence of
            compliant behavior if the conductor actually acted. This
            classifier fires ONLY on POSITIVE proof of a stall: the marker is
            present in the tail, the transcript window was read successfully,
            a genuine prior human-turn boundary was actually located (so the
            scan window is provably scoped to the CURRENT turn), every
            assistant entry inside that window had a recognized content shape
            (a list of blocks or a plain string - anything else cannot be
            proven to lack a tool_use), and zero tool_use blocks were found
            inside that window. Any failure to establish ALL of the above
            (unreadable/unparseable transcript, no boundary found, an
            unrecognized entry shape, or the marker simply absent) means the
            stall is UNPROVEN and this classifier returns False - burden of
            proof is on detecting the stall, not on disproving it.

         Classifier (1) keeps the full marker set (including a bare
         "(recommended)") as an UNCONDITIONAL suppressor of its OWN
         interrogative check - this does not change classifier (2)'s
         independent result. For example "Proceeding with X (recommended).
         Want me to start?" makes _is_abdication() return False on its own,
         but classifier (2) evaluates the same tail against the transcript:
         "proceeding with" is a stall-commitment marker, and if the transcript
         shows no tool call this turn, classifier (2) still fires and the
         overall turn BLOCKs - the marker suppresses classifier (1) alone, it
         is not a blanket exemption from the OR'd result of both classifiers.
         A bare "(recommended)" with no accompanying commitment phrase never
         triggers classifier (2), because labelling a derived choice is not
         itself a promise to act that can go unfulfilled.

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
    - Missing or malformed config.json: fail-open (exit 0). Guard is on by default
      (abdication_guard_enabled defaults to true); corrupt/missing config fails open.
    - Missing transcript file, an unreadable/unparseable JSONL window (no
      lines at all, only garbage lines, only valid-JSON-but-unrecognized-
      schema entries, or a window with no genuine human-turn boundary at
      all - e.g. a compacted transcript), or a recognized boundary containing
      an assistant entry whose content shape cannot be classified as
      list-or-string: fail-open (exit 0). This is a burden-of-proof design,
      not an incidental side effect - _is_stalled_surface_and_proceed() only
      fires on POSITIVE stall evidence (parsed window + located boundary +
      recognized structure + zero tool_use found); anything short of that
      full chain is treated as "stall unproven", never as "stall proven".
    - Any exception: fail-open via outer try/except (exit 0).
    - stop_hook_active=true: exit 0 immediately (primary re-entrancy guard).
    - Counter >= CAP: exit 0 without block (backstop for CC bug #54360).
    - Counter write fails (unwritable .agentic/, full disk, corrupt tmp, etc.):
      exit 0 and ALLOW the stop on that invocation. Rationale: a block whose
      count cannot be recorded loses its loop bound; the safe degradation is
      "don't block" (status quo, never an infinite loop). Only blocks after the
      incremented count has been successfully persisted.
    - Invalid/garbage stdout: guarded via atomic print-then-exit pattern;
      any exception before the print results in no stdout = allow.

Performance: < 5 ms per call on typical transcripts (one file read for config,
             a small counter file read/write, and up to two full-file scans of
             the transcript JSONL - one forward scan to count genuine human
             turns, and one reverse-from-readlines scan, shared by the
             last-assistant-message fallback and the tool-call-since-last-
             turn check). Both transcript scans are skipped when
             transcript_path is absent; the reverse scan is also skipped
             when last_assistant_message is already populated AND either a
             hard negative-gate token is present (neither classifier can fire
             regardless of transcript evidence) or no stall-commitment marker
             is present in it (classifier 2 cannot fire without one) - see
             main().
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
    r"\b(?:"
    r"want me to"
    r"|should i"
    r"|shall i"
    r"|would you like me to"
    r"|do you want me to"
    r"|let me know if you(?:'d| (?:like|want))"
    r"|ready (?:for me )?to proceed"
    r"|should i go ahead"
    r"|want me to go ahead"
    r")\b",
    re.IGNORECASE,
)

# Tier 2 (negative gate): hard-stop or legitimate-question signals.
# Presence of any of these tokens suppresses the classic _is_abdication()
# check even if a permission phrase is present. Two groups, split into two
# separate patterns because they are treated differently by the NEW stall
# classifier (_is_stalled_surface_and_proceed) below:
#   (a)+(b) HARD gate - destructive/irreversible signals and product-judgment
#       / design-fork signals. Blocking here would force the conductor to
#       execute an action it correctly and legitimately paused on. This gate
#       suppresses BOTH classifiers unconditionally - it must never be
#       overridden by tool-call evidence.
#   (c) surface-and-proceed markers ("(recommended)", "proceeding with",
#       "unless you say otherwise"). These suppress the classic
#       _is_abdication() interrogative check unconditionally (legacy
#       behavior preserved - see module docstring), but do NOT by themselves
#       prove the conductor acted: _is_stalled_surface_and_proceed() treats
#       their presence as a POSITIVE stall signal when the transcript shows
#       no tool call since the last human turn.
_HARD_NEGATIVE_GATE_PATTERNS = re.compile(
    r"(?:"
    # --- (a) destructive / irreversible ---
    r"\bdestructive\b"
    r"|\birreversible\b"
    r"|\bforce push\b"
    r"|\bforce-push\b"
    r"|\bdelete\b"
    r"|\bdrop table\b"
    r"|\bschema migration\b"
    r"|\bproduction deploy\b"
    r"|\bpermanently (?:remove|delete)\b"
    r"|\bpermanently\b"
    r"|\bcan(?:not|\'t|not) be undone\b"
    r"|\bno undo\b"
    r"|\bunrecoverable\b"
    r"|\bdata loss\b"
    r"|\bwipe\b"
    r"|\boverwrite\b"
    # --- (a cont.) sending external messages / spending money - the two
    # hard-stop categories from content/sections/02-delegation.md's
    # enumeration ("data loss, force push, production deploy, schema
    # migration, sending external messages, spending money, etc.") that were
    # missing from this gate. Deliberately broad - over-inclusion here is
    # safe because a hard-gate hit only ever ALLOWS.
    r"|\bspend(?:ing)?\b"
    r"|\bspent\b"
    r"|\bcost\b"
    r"|\bcredits?\b"
    r"|\bbilling\b"
    r"|\bsend(?:ing)?\b"
    r"|\bpost(?:ing)?\b"
    r"|\bemail(?:ing)?\b"
    r"|\bpublish(?:ing)?\b"
    r"|\bnotify(?:ing)?\b"
    # --- (b) cannot-derive / credential / target-selection ---
    r"|\bcannot derive\b"
    r"|\bmissing credential\b"
    r"|\bapi key\b"
    r"|\bwhich environment\b"
    r"|\bwhich workspace\b"
    r"|\bmerge to main\b"
    # --- (b cont.) product-judgment / design-fork signals ---
    r"|\bwhich direction\b"
    r"|\bwhich approach\b"
    r"|\bwhich option\b"
    r"|\bwhich of these\b"
    r"|\bchanges the (?:data model|schema|api|contract)\b"
    r"|\bload-bearing\b"
    r"|\bdesign (?:decision|fork|choice)\b"
    r")",
    re.IGNORECASE,
)

# --- (c) surface-and-proceed markers (see comment block above) ---
_SURFACE_AND_PROCEED_PATTERNS = re.compile(
    r"(?:\(recommended\)|proceeding with|unless you say otherwise)",
    re.IGNORECASE,
)

# Narrower subset of (c) used ONLY by _is_stalled_surface_and_proceed()
# (classifier 2) and by main()'s decision to scan the transcript at all.
# A bare "(recommended)" labels an already-derived choice and appears
# routinely with no pending action attached (e.g. "Option B (recommended)
# because it matches src/foo.ts.") - it is not a commitment to a specific
# next action, so it must not by itself prove a stall. "proceeding with" and
# "unless you say otherwise" ARE commitments to a stated default: their
# presence with zero tool-use evidence this turn is the actual stall shape
# this classifier exists to catch. Classifier (1)'s suppression gate above
# deliberately keeps the broader _SURFACE_AND_PROCEED_PATTERNS (including the
# bare "(recommended)") - that is a different, unrelated use of the phrase.
_STALL_TRIGGER_PATTERNS = re.compile(
    r"(?:proceeding with|unless you say otherwise)",
    re.IGNORECASE,
)

# Legacy combined gate, kept ONLY as the union used by _is_abdication() so
# its suppression behavior is byte-for-byte unchanged (hard gate OR
# surface-and-proceed marker both still suppress the classic interrogative
# check, exactly as before this fix).
_NEGATIVE_GATE_PATTERNS = re.compile(
    r"(?:"
    + _HARD_NEGATIVE_GATE_PATTERNS.pattern
    + r"|"
    + _SURFACE_AND_PROCEED_PATTERNS.pattern
    + r")",
    re.IGNORECASE,
)


# Sentence boundary: split right after a terminator (./?/!) that is followed
# by whitespace. Deliberately naive (does not special-case abbreviations or
# numbered-list markers like "1.") - false splits only produce extra sentence
# chunks, they never merge a question with unrelated text, so they cannot
# cause a false negative or false positive here.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")

# Harness-injected `type:"user"` lines that are NOT a genuine human turn even
# though they carry real text content and no isMeta flag. Confirmed against
# live transcripts under ~/.claude/projects/: a completed background-task
# notification arrives as {"type":"user","message":{"content":"<task-
# notification>...</task-notification>"}} with isMeta ABSENT (not True) - in
# one real session this shape occurred 67 times against a handful of genuine
# human turns. Counting it as a human-turn boundary breaks the reverse scan
# in _scan_transcript_tail: it stops at the notification and never reaches
# the tool_use the conductor issued earlier in the SAME human turn, turning
# the single most common compliant conductor shape (spawn -> notification ->
# "Unit N returned; proceeding with unit N+1 unless you say otherwise") into
# a false BLOCK. <system-reminder> and <command-name> blocks were also
# checked directly against real transcripts; in every sample found they
# already carry isMeta:true and are excluded by the existing isMeta check,
# but they are listed here too as a defense-in-depth backstop in case a
# harness version ever omits isMeta on one of these tags.
_HARNESS_INJECTED_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "<system-reminder>",
    "<command-name>",
)


def _is_harness_injected_text(text: str) -> bool:
    return any(marker in text for marker in _HARNESS_INJECTED_MARKERS)


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

    # Require a permission phrase somewhere in the tail (cheap pre-filter
    # before the more expensive sentence segmentation below).
    if not _PERMISSION_PHRASES.search(tail):
        return False

    # Sentence-granularity check: the SAME sentence must both end with "?"
    # AND contain a permission phrase. A permission-seeking question followed
    # by trailing declarative sentences ("Want me to file this? Learnings
    # captured.") must still fire - checking only the final line missed this
    # because trailing text pushed the question mark off the last line.
    # Conversely, a permission phrase appearing in one (non-question)
    # sentence while an unrelated "?" appears in a later sentence must NOT
    # fire.
    for sentence in _SENTENCE_SPLIT_RE.split(tail):
        stripped = sentence.strip()
        if not stripped:
            continue
        if stripped.endswith("?") and _PERMISSION_PHRASES.search(stripped):
            return True

    return False


def _is_stalled_surface_and_proceed(text: str, stall_provable: bool, had_tool_call: bool) -> bool:
    """Return True if the tail announces a surface-and-proceed default AND
    the transcript furnishes POSITIVE proof the conductor took no action on
    it this turn.

    This is the fix for the reported stall bug: a surface-and-proceed marker
    used to be treated as proof of already-compliant behavior regardless of
    whether any action followed it. That is only true when the conductor's
    turn actually made a tool call (spawned an agent, ran a command, edited a
    file) after announcing the default - not merely because the phrase is
    present.

    Burden of proof is inverted from a naive implementation (Finding 2): this
    only fires on POSITIVE stall evidence, never on absence of evidence.
    `stall_provable` (computed by main() from _scan_transcript_tail's result)
    must already encode "the window was read successfully, a genuine human-
    turn boundary was located, and every assistant entry in that window had a
    recognized content shape" - i.e. `had_tool_call` is only meaningful
    (decisive) when `stall_provable` is True. An unreadable/unparseable
    transcript, a window with no located human-turn boundary (e.g. a
    compacted transcript with no user turn at all), or an unrecognized
    assistant content shape all leave `stall_provable` False, and this
    classifier returns False in every one of those cases - an unprovable
    claim must never block.

    Fail-open by construction:
      - A hard negative-gate token (destructive/irreversible/design-fork/
        spend-money/external-message) always suppresses this check - never
        force a stop the conductor correctly paused on for a genuine reason.
      - No stall-commitment marker in the tail (_STALL_TRIGGER_PATTERNS:
        "proceeding with" / "unless you say otherwise" - deliberately NOT a
        bare "(recommended)", see _STALL_TRIGGER_PATTERNS) -> False (nothing
        to evaluate).
      - stall_provable is False -> False. Without a fully-proven scan this
        classifier cannot establish a stall occurred.
      - had_tool_call is True -> False (compliant: the conductor followed
        through in this turn).
    """
    tail = text[-TAIL_LENGTH:]

    if _HARD_NEGATIVE_GATE_PATTERNS.search(tail):
        return False

    if not _STALL_TRIGGER_PATTERNS.search(tail):
        return False

    if not stall_provable:
        return False

    return not had_tool_call


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


def _write_counter(cwd: str, count: int, last_user_msg_count: int) -> bool:
    """Write counter state. Returns True on success, False on any failure.

    The caller MUST check the return value when deciding whether to block:
    a block emitted without a successful counter write loses its loop bound
    and can cause an infinite block loop when stop_hook_active also fails
    (CC bug #54360). Fail toward allow-stop on any write failure.
    """
    try:
        agentic_dir = os.path.join(cwd, ".agentic")
        os.makedirs(agentic_dir, exist_ok=True)
        path = _counter_path(cwd)
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


def _reset_counter(cwd: str, current_user_msg_count: int) -> None:
    """Reset consecutive block count (new user turn detected). Best-effort."""
    _write_counter(cwd, 0, current_user_msg_count)  # return value intentionally ignored


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
    that carries real text content and is NEITHER a tool_result NOR a meta line
    NOR a harness-injected notification (see _HARNESS_INJECTED_MARKERS) -
    background task-completion notifications arrive as exactly this shape
    (type:"user", isMeta absent, plain-string content) and must not be
    mistaken for a human turn boundary.
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
        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        if has_tool_result:
            return False
        # Genuine turn requires at least one real text block with text that
        # is NOT a harness-injected marker (see _HARNESS_INJECTED_MARKERS).
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if t.strip() and not _is_harness_injected_text(t):
                    return True
            elif isinstance(b, str) and b.strip() and not _is_harness_injected_text(b):
                return True
        return False
    if isinstance(content, dict):
        if content.get("type") == "tool_result":
            return False
        if content.get("type") == "text":
            t = content.get("text", "")
            return bool(t.strip()) and not _is_harness_injected_text(t)
        return False
    if isinstance(content, str):
        # Real transcripts show harness task-notifications delivered as a
        # bare string here (type:"user", isMeta absent) - see
        # _HARNESS_INJECTED_MARKERS. These are not genuine human turns.
        return bool(content.strip()) and not _is_harness_injected_text(content)
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


def _scan_transcript_tail(transcript_path: str) -> dict:
    """Single reverse (tail-first) scan of the transcript JSONL, shared by
    both the last-assistant-message fallback and the tool-call-since-last-
    turn check (avoids two separate reverse-scan implementations - see
    module docstring point 2).

    Reads lines in reverse from the end of the file back to (and including)
    the most recent GENUINE human turn line, then stops - everything at or
    before that boundary is a prior turn and irrelevant to either check.

    Returns:
        {"last_assistant_text": str, "had_tool_call": bool,
         "boundary_found": bool, "shape_unrecognized": bool}

    - last_assistant_text: the most recent assistant message's concatenated
      text content (matches the old _last_assistant_text_from_transcript
      behavior exactly - same two transcript shapes, same join semantics).
    - had_tool_call: True iff any assistant message within the scanned
      window (i.e. since the last genuine human turn) contains a
      type=="tool_use" content block in a RECOGNIZED shape - evidence the
      conductor actually acted this turn, not merely announced intent.
    - boundary_found: True iff the reverse scan actually located a genuine
      human-turn line and stopped there (see _is_genuine_user_turn). False
      means the window is NOT provably scoped to "since the current human
      turn" - e.g. the file has no human turn at all (a compacted window),
      is empty, or every line failed to parse.
    - shape_unrecognized: True iff at least one assistant entry INSIDE the
      scanned window had a content shape that is neither a list of blocks
      nor a plain string (e.g. a bare dict) - such a shape cannot be proven
      to lack a tool_use block, so had_tool_call's absence-of-evidence must
      not be read as evidence-of-absence.

    Burden-of-proof inversion (Finding 2): had_tool_call, boundary_found, and
    the negation of shape_unrecognized ALL default to their "unproven" value
    (False, False, False respectively is the *safe* starting state before any
    positive evidence is found) and only flip to the "proven" direction on
    positive evidence encountered during a successful scan. Callers combine
    these into a single `stall_provable` flag (see main()) that requires
    boundary_found AND NOT shape_unrecognized before treating had_tool_call
    as decisive - a stall is asserted only on complete positive proof, never
    inferred from an unparseable or partially-recognized window.

    Fail-open: on any read error (open() failure, or an exception mid-scan),
    returns had_tool_call=False, boundary_found=False, shape_unrecognized=True
    and last_assistant_text="" - i.e. maximally "unproven", so the classifier
    that consumes this result can never treat a read failure as proof of a
    stall.
    """
    result = {
        "last_assistant_text": "",
        "had_tool_call": False,
        "boundary_found": False,
        "shape_unrecognized": False,
    }
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        result["shape_unrecognized"] = True
        return result

    had_tool_call = False
    boundary_found = False
    shape_unrecognized = False
    text_captured = False

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

            # Handle two common transcript shapes:
            # Shape 1: {"role": "assistant"/"user", "content": [...]}
            # Shape 2: {"type": "assistant"/"user", "message": {"content": [...]}}
            role = obj.get("role") or obj.get("type", "")

            if role == "user" and _is_genuine_user_turn(obj):
                # Reached the boundary of the current turn - stop scanning.
                boundary_found = True
                break

            if role != "assistant":
                continue

            content = obj.get("content")
            if content is None:
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content")

            if isinstance(content, str):
                if not text_captured:
                    result["last_assistant_text"] = content
                    text_captured = True
            elif isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                    had_tool_call = True
                if not text_captured:
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    result["last_assistant_text"] = " ".join(parts)
                    text_captured = True
            elif content is None:
                # No content at all - a recognized (empty) shape; nothing to
                # prove or disprove from this entry.
                pass
            else:
                # Unrecognized content shape (e.g. a bare dict, not a list of
                # blocks) - cannot be proven to lack a tool_use, so the
                # absence of a detected tool_use here is not decisive.
                shape_unrecognized = True
    except Exception:
        # Partial-scan failure: the state captured so far is unreliable -
        # treat as fully unproven (fail-open).
        return {
            "last_assistant_text": "",
            "had_tool_call": False,
            "boundary_found": False,
            "shape_unrecognized": True,
        }

    result["had_tool_call"] = had_tool_call
    result["boundary_found"] = boundary_found
    result["shape_unrecognized"] = shape_unrecognized
    return result


# ---------------------------------------------------------------------------
# Block reasons
# ---------------------------------------------------------------------------

_ABDICATION_REASON = (
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

_STALL_REASON = (
    "ABDICATION GUARD: You announced a surface-and-proceed default "
    "(\"proceeding with\" / \"unless you say otherwise\") "
    "and then stopped without taking any action this turn. The METHODOLOGY "
    "§Delegation (surface-and-proceed branch) requires you to proceed with "
    "the stated default IN THE SAME TURN, not merely announce it and wait. "
    "Proceed with the default you already stated now - spawn the agent, run "
    "the command, or make the edit you said you would. Only stop first if "
    "the action is genuinely irreversible/destructive and not pre-authorized."
)


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

        # Read project config. Default on (abdication_guard_enabled defaults to
        # true). Fail-open on any read/parse error.
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
        if not isinstance(transcript_path, str):
            # A non-string value (e.g. a number) would reach open() below,
            # which Python treats as a raw file descriptor - guard it here,
            # mirroring the existing last_assistant_message type check.
            transcript_path = ""
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
        # fall back to transcript scan. A transcript scan is also needed
        # (even when last_assistant_message is already populated) whenever
        # the message contains a stall-commitment marker AND no hard
        # negative-gate token is present, to determine whether a tool call
        # followed it this turn - see _is_stalled_surface_and_proceed(). When
        # msg_text is empty we cannot evaluate the hard gate yet, so the scan
        # runs unconditionally to recover text (Finding 7: this is the only
        # case where we scan without already knowing a marker/gate verdict).
        msg_text = data.get("last_assistant_message", "")
        if not isinstance(msg_text, str):
            msg_text = ""

        if not msg_text.strip():
            needs_transcript_scan = True
        else:
            tail_for_gate = msg_text[-TAIL_LENGTH:]
            if _HARD_NEGATIVE_GATE_PATTERNS.search(tail_for_gate):
                # Neither classifier(2) nor the marker-based checks below can
                # fire once a hard gate token is present - skip the scan.
                needs_transcript_scan = False
            else:
                needs_transcript_scan = bool(_STALL_TRIGGER_PATTERNS.search(tail_for_gate))

        scan = None
        if transcript_path and needs_transcript_scan:
            scan = _scan_transcript_tail(transcript_path)

        if not msg_text.strip() and scan is not None:
            msg_text = scan["last_assistant_text"]

        if not msg_text.strip():
            # No message text available - cannot classify.
            sys.exit(0)

        # stall_provable requires ALL of: a scan was run, the file was read
        # successfully, a genuine human-turn boundary was actually located
        # (so the window is provably scoped to the current turn), and no
        # assistant entry in that window had an unrecognized content shape.
        # Absent any of these, had_tool_call cannot be treated as decisive -
        # see _scan_transcript_tail's docstring (Finding 2: burden of proof
        # is on proving the stall, not on disproving it).
        if scan is not None:
            had_tool_call = scan["had_tool_call"]
            stall_provable = scan["boundary_found"] and not scan["shape_unrecognized"]
        else:
            had_tool_call = False
            stall_provable = False

        # Run both classifiers; a block fires if EITHER returns True.
        is_stall = _is_stalled_surface_and_proceed(msg_text, stall_provable, had_tool_call)
        is_classic_abdication = _is_abdication(msg_text)

        if not is_stall and not is_classic_abdication:
            # Neither classifier fired - reset counter (clean turn) and allow.
            _reset_counter(cwd, current_user_msg_count)
            sys.exit(0)

        # Abdication or stall detected. Only block if we can persist the
        # incremented count. If persistence fails (unwritable .agentic/, full
        # disk, etc.) the loop bound is lost; the safe degradation is
        # allow-stop to avoid an infinite block loop when stop_hook_active
        # also fails (CC bug #54360).
        new_count = state["count"] + 1
        if not _write_counter(cwd, new_count, current_user_msg_count):
            sys.exit(0)

        reason = _STALL_REASON if is_stall else _ABDICATION_REASON
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
