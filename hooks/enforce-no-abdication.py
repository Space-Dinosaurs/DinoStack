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

         Also detects a PROSE co-equal ballot: an `## Operator decisions`
         section (content/sections/02-delegation.md) presenting 2+ decision
         items where 2+ carry no derived recommendation marker. This closes
         a gap the tool-path hook (enforce-askuserquestion-default.py) cannot
         see - that hook only inspects AskUserQuestion tool_input, and a
         conductor can write the same forbidden ballot as plain prose instead
         of calling the tool. See content/sections/02-delegation.md
         "AskUserQuestion precondition" and "Operator decisions go last in
         the turn" - both state the ban applies identically to prose, and
         the latter now MANDATES the `(Recommended)`/`Recommendation:`
         marker on every item so a spec-compliant author is never punished
         by this check.

         Ballot item detection is structured-marker-only (markdown bullet,
         plain numbered, bold-numbered) with NO leading-whitespace tolerance
         (an indented sub-bullet is not a new top-level item) and NO
         paragraph-mode fallback (an earlier version had one; it was
         unpinned by any test and over-fired on ordinary multi-paragraph
         prose - see _split_decision_items). Fenced code blocks are masked
         out of the FULL message before the heading is even searched for,
         so a fenced example quoting this rule's own syntax cannot trigger
         it. Known, documented, unfixed evasions: a non-literal heading
         wording, items formatted as a markdown table, and a negated
         "No recommendation:" phrase suppressing the marker check - see the
         KNOWN RESIDUAL EVASION comments at each pattern's definition.

         Scoped to the MAIN session Stop event only (not SubagentStop), so
         it governs the conductor, not Workers.

         Two loop-guard layers are required due to CC bug #54360 (stop_hook_active
         can fail to propagate when a UserPromptSubmit hook interleaves system
         reminders - and this repo has such a hook). Layer 1: check stop_hook_active
         flag (primary). Layer 2: counter-based cap (backstop) that counts
         consecutive blocks since the last new user message and halts at CAP.
         Both the permission-phrase check and the prose-ballot check share this
         same counter and cap.

         Detection is precision-biased (false-negative-biased): a missed
         abdication leaves the conductor as-is (status quo); a false positive
         forces continuation on a turn the conductor genuinely intended to stop,
         which is recoverable but annoying. Negative gate token set chosen to
         match legitimate stop conditions: destructive operations, hard-stop
         branch signals, and correct surface-and-proceed markers. The
         prose-ballot check is DELIBERATELY NOT subject to that negative gate -
         see _is_prose_ballot docstring for why.

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
    - Missing transcript file or unparseable JSONL: fail-open (exit 0).
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
# Presence of any of these tokens suppresses the block even if a permission
# phrase is present. Three groups:
#   (a) destructive/irreversible signals - blocking here would force the
#       conductor to execute an irreversible action it correctly paused on.
#   (b) product-judgment / design-fork signals - genuine "I need your
#       judgment" questions the conductor cannot derive a default for.
#   (c) correct surface-and-proceed markers ("(recommended)", "proceeding
#       with", "unless you say otherwise") - already-compliant behavior.
_NEGATIVE_GATE_PATTERNS = re.compile(
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
    # --- (c) correct surface-and-proceed markers ---
    r"|\(recommended\)"
    r"|proceeding with"
    r"|unless you say otherwise"
    r")",
    re.IGNORECASE,
)


# Sentence boundary: split right after a terminator (./?/!) that is followed
# by whitespace. Deliberately naive (does not special-case abbreviations or
# numbered-list markers like "1.") - false splits only produce extra sentence
# chunks, they never merge a question with unrelated text, so they cannot
# cause a false negative or false positive here.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


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


# ---------------------------------------------------------------------------
# Prose-ballot detection
# ---------------------------------------------------------------------------

# The literal heading from content/sections/02-delegation.md ("Operator
# decisions go last in the turn"). Case-insensitive, tolerant of surrounding
# whitespace on the heading line and an optional trailing colon, anchored to
# a line start so it cannot match mid-sentence prose that happens to contain
# the words. `#{2,}` (2 OR MORE hashes) rather than a fixed `#{2}` so a
# `### Operator decisions` (3-hash) heading still matches - `#{2}` consumes
# exactly two hashes and leaves the third unmatched against the following
# `\s*`, silently failing to find the heading at all.
#
# KNOWN RESIDUAL EVASION (documented, not fixed - see Skeptic review):
# a heading with different WORDING ("## Decisions for you", "## Open
# items") or items formatted as a markdown table are NOT caught by this
# regex/tokenizer pair. Both would require either free-text heading-intent
# classification or a table parser, neither of which is safe to add as a
# regex without materially raising the false-positive rate on legitimate
# turns. This is a known gap, not an oversight.
_OPERATOR_DECISIONS_HEADING_RE = re.compile(
    r"^[ \t]*#{2,}\s*operator decisions\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# A top-level list item start, anchored to the ABSOLUTE start of the line
# (no leading whitespace permitted before the marker). Three accepted
# shapes, matched by real conductor output rather than an idealized single
# format:
#   - markdown bullet: "- ", "* ", "+ "
#   - plain numbered:  "1. " / "1) "
#   - bold-numbered:   "**1." / "**1)" (no space required after "**" or
#     before the digit - this is the shape conductors actually emit, e.g.
#     "**1. Run one command to unblock PR #516.**")
# The no-leading-whitespace anchor is deliberate: an INDENTED bullet/number
# ("   - the DCO check passed") is a sub-bullet of the enclosing item, not a
# new top-level decision, and must not be counted as one. A genuinely
# top-level markdown list in an Operator decisions block is never indented -
# it starts at column 0 immediately under the heading.
_ITEM_START_RE = re.compile(
    r"^(?:"
    r"[-*+]\s+"
    r"|\d+[.)]\s+"
    r"|\*\*\s*\d+[.)]"
    r")",
    re.MULTILINE,
)

# Fenced code blocks (```...```). Masked out BEFORE the heading search even
# runs (see _mask_fenced_code_blocks / its call site in _is_prose_ballot) so
# that (a) a fenced example that happens to quote the literal heading text
# (a PR body, a /ds-wrap note, a Skeptic digest explaining this very rule)
# is never mistaken for a real Operator decisions block, and (b) diff-style
# '+'/'-' prefixed lines inside a fence are never mistaken for markdown
# bullet item starts. Non-greedy + DOTALL so multiple fences in one message
# are each matched individually rather than spanning from the first opening
# fence to the last closing one.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Marks that an item already carries a derived recommendation, per the
# methodology's own convention: the literal "(Recommended)" suffix used on
# the tool path, or a "Recommendation:" lead-in for the prose path.
#
# KNOWN RESIDUAL EVASION (documented, not fixed - see Skeptic review): this
# matches the word "recommendation" followed by a colon regardless of
# negation, so "No recommendation: you decide." is read as carrying a
# marker. A conductor need only write the word to suppress the check. Low
# severity (requires deliberately gaming the guard's own wording, not an
# accidental miss) and left as a documented gap rather than a regex fix
# that would need negation-scope parsing to do properly.
_RECOMMENDATION_RE = re.compile(r"\(recommended\)|recommendation\s*:", re.IGNORECASE)


def _mask_fenced_code_blocks(text: str) -> str:
    """Replace each fenced code block with a single-line placeholder.

    See _FENCE_RE for why: prevents a fenced example that quotes this rule's
    own heading/list syntax from being misread as a real Operator decisions
    block, and prevents diff/list-like syntax inside a fence from being
    misread as a new item marker.
    """
    return _FENCE_RE.sub("<code-block>", text)


def _extract_operator_decisions_block(masked_text: str) -> str:
    """Return the text following the '## Operator decisions' heading.

    Returns '' if the heading is absent. Per content/sections/02-delegation.md
    the block is always the last thing in the turn (nothing follows the
    heading), so everything after the heading match is the block content -
    there is no closing marker to look for.

    CALLER CONTRACT: masked_text must already have fenced code blocks masked
    out (see _mask_fenced_code_blocks). Extracting from unmasked text lets a
    fenced example that quotes the literal heading text falsely match, and
    the resulting "block" would swallow real content past the fence's
    closing backticks (the block is assumed to run to end-of-message).
    """
    match = _OPERATOR_DECISIONS_HEADING_RE.search(masked_text)
    if not match:
        return ""
    return masked_text[match.end():]


def _split_decision_items(masked_block: str) -> list:
    """Split an already-fence-masked Operator decisions block into items.

    Scans for _ITEM_START_RE markers (bullet, numbered, or bold-numbered).
    Each item runs from its marker to the character before the next marker
    (or end of block), so continuation lines belonging to the same item
    (including a "Recommendation:" line that isn't on the marker's own
    line) stay part of that item's text.

    Returns [] when no structured marker is found anywhere in the block.
    There is deliberately NO paragraph-mode fallback: an earlier version
    tried to also split on blank lines when no marker was present, to catch
    arbitrarily-formatted items, but it was unpinned by any test that
    verified it actually caught the format it was meant for, and it
    over-fired on ordinary non-ballot prose (e.g. two blank-line-separated
    paragraphs of "nothing to decide" narrative). Structured markers only -
    an author who writes a real ballot without any list/number syntax is a
    genuine, currently-uncovered gap (see the heading docstring's KNOWN
    RESIDUAL EVASION note), not a case worth risking false positives on
    every ordinary multi-paragraph turn to catch.

    CALLER CONTRACT: masked_block must already have fenced code blocks
    masked out (see _mask_fenced_code_blocks) - this function does not
    mask internally, so a caller passing unmasked text risks diff-style
    '+'/'-' lines inside a fence being misread as item markers.
    """
    starts = [m.start() for m in _ITEM_START_RE.finditer(masked_block)]
    if not starts:
        return []
    items = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(masked_block)
        items.append(masked_block[start:end])
    return items


def _is_prose_ballot(text: str) -> bool:
    """Return True if text contains a co-equal ballot in an Operator
    decisions block.

    Fires only when: (1) the '## Operator decisions' heading is present,
    (2) the block contains 2 or more list items, AND (3) 2 or more of those
    items carry no derived-recommendation marker. A single item never fires
    (the rule bans co-equal *ballots*, not surfacing one genuine decision -
    content/sections/02-delegation.md "Proactive autonomy" anti-pattern
    list). An item that DOES carry a recommendation does not count toward
    the violation, so a block with one flagged decision plus other already-
    recommended items does not fire - this mirrors the tool-path hook
    (enforce-askuserquestion-default.py), which only denies a 2+-option
    AskUserQuestion call when NO option carries the "(Recommended)" label.
    content/sections/02-delegation.md "Operator decisions go last in the
    turn" now mandates the same marker on the prose path, so a compliant
    author is never punished by this check - only an author who omits the
    marker the spec itself requires is.

    Fenced code blocks are masked FIRST, before the heading search runs -
    see _extract_operator_decisions_block's CALLER CONTRACT for why order
    matters here.

    Deliberately scans the FULL message text, not the TAIL_LENGTH-truncated
    tail _is_abdication uses: the Operator decisions block is, by the same
    section's own convention, the last thing in the turn, and real items
    with one-line reasoning routinely exceed the 600-char tail window.

    Deliberately independent of _NEGATIVE_GATE_PATTERNS. That gate exists to
    let a genuine SINGLE irreversible-action confirmation pass the
    permission-phrase classifier without being mistaken for abdication. A
    multi-item ballot saturated with irreversibility vocabulary
    ("destructive", "cannot be undone", "design decision") is exactly the
    failure mode that motivated this check - the incident this hook was
    added to catch used that exact vocabulary to make the negative gate
    silence the permission-phrase check. Routing this check through the same
    gate would repeat the escape it exists to close.
    """
    masked = _mask_fenced_code_blocks(text)
    block = _extract_operator_decisions_block(masked)
    if not block:
        return False
    items = _split_decision_items(block)
    if len(items) < 2:
        return False
    unrecommended = sum(1 for item in items if not _RECOMMENDATION_RE.search(item))
    return unrecommended >= 2


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
        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
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

        # Run classifiers. Prose-ballot scans the full message; abdication
        # scans only the tail (see _is_abdication / _is_prose_ballot).
        abdication_fired = _is_abdication(msg_text)
        ballot_fired = _is_prose_ballot(msg_text)

        if not (abdication_fired or ballot_fired):
            # Clean turn - reset counter and allow.
            _reset_counter(cwd, current_user_msg_count)
            sys.exit(0)

        # Violation detected. Only block if we can persist the incremented count.
        # If persistence fails (unwritable .agentic/, full disk, etc.) the loop
        # bound is lost; the safe degradation is allow-stop to avoid an infinite
        # block loop when stop_hook_active also fails (CC bug #54360). Both
        # classifiers share this same counter/cap.
        new_count = state["count"] + 1
        if not _write_counter(cwd, new_count, current_user_msg_count):
            sys.exit(0)

        if ballot_fired:
            reason = (
                "ABDICATION GUARD: Your 'Operator decisions' block presents a "
                "co-equal ballot - 2 or more decision items with no derived "
                "recommendation. The METHODOLOGY §Delegation AskUserQuestion "
                "precondition bans co-equal ballots identically whether presented "
                "via the tool or as prose (content/sections/02-delegation.md, "
                "'Operator decisions go last in the turn'). Consult the five "
                "default sources (codebase patterns, MEMORY.md, architect plan, "
                "AGENTS.md, conservative ticket interpretation) for each item: "
                "either pick the best option and proceed, noting the choice, or "
                "surface exactly ONE recommended action per item, marked with a "
                "'Recommendation:' lead-in or a '(Recommended)' suffix. Revise the "
                "Operator decisions block now."
            )
        else:
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
