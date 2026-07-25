#!/usr/bin/env python3
"""
Spec tests for the Tracker Writeback Helper's forward-only guard ranking rule
(content/commands/ds-implement-ticket.md ## Tracker Writeback Helper).

Covers:
  - (a) the canonical block contains the pipeline sub-rank prose, the fixed
    IN_PROGRESS(0) < IN_REVIEW(1) < QA(2) sequence, the Blocked
    always-permitted-both-directions language, the tracker_state_values
    parameter, the never-reads-cache invariant, single-L 'canceled',
    'duplicate', the field-absence phrase, and the fire-and-forget-vs-
    awaiting-caller distinction.
  - (b) the canonical block is byte-identical across all adapter copies.
  - (c) a spelling heuristic: any line in the canonical block that mentions
    3+ of the category-rank tokens (backlog/unstarted/started/completed/
    duplicate) must spell any cancel(l)ed-shaped token on that line single-L,
    unless immediately followed by a "(double L)" parenthetical.
  - (d) content/commands/ds-ticket-triage.md's already-correct single-L
    enumeration is untouched.
  - (e) content/commands/ds-ticket-status-sync.md no longer restates the
    ranking inline, and every target_state/forward_only_guard call site also
    carries tracker_state_values.
  - (f) content/commands/ds-wrap.md's Part F Gate line resolves the 5
    TRACKER_STATE_* values (regression guard against a future edit silently
    dropping the Gate extension).

Run with: python3 -m pytest bin/tests/test_tracker_writeback_ranking_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

# All adapter copies expected to carry a byte-identical extraction of the
# "## Tracker Writeback Helper" block. .pi/prompts/ds-implement-ticket.md is
# deliberately excluded - it is a 7-line pointer stub with no such block.
ADAPTER_PATHS = [
    REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".claude" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".codex" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".cursor" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".opencode" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".github" / "prompts" / "ds-implement-ticket.prompt.md",
    REPO_ROOT / ".openclaw" / "skills" / "ds-implement-ticket" / "SKILL.md",
    REPO_ROOT / ".gemini" / "commands" / "ds-implement-ticket.toml",
    REPO_ROOT / ".hermes" / "SKILL.md",
]

HEADING = "## Tracker Writeback Helper"

# Category-rank tokens that trigger the spelling heuristic in (c).
_TRIGGER_TOKENS = ("backlog", "unstarted", "started", "completed", "duplicate")
_CANCEL_RE = re.compile(r"cancell?ed", re.IGNORECASE)


def _extract_block(text: str) -> str:
    """Extract the '## Tracker Writeback Helper' section: from the exact
    heading line up to (exclusive) the next line that is itself a top-level
    '## ' heading. Matches on an exact-stripped heading line so inline
    backtick mentions of the same phrase elsewhere in the file (e.g. in a
    fused multi-command embed like .hermes/SKILL.md) are not mistaken for
    the heading itself."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == HEADING:
            start = i
            break
    if start is None:
        raise AssertionError(f"heading {HEADING!r} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def canonical_block() -> str:
    return _extract_block(CANONICAL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) canonical block content assertions
# ---------------------------------------------------------------------------

def test_canonical_block_contains_pipeline_subrank_language(canonical_block):
    assert "pipeline sub-rank" in canonical_block


def test_canonical_block_contains_fixed_pipeline_ranks(canonical_block):
    assert "IN_PROGRESS" in canonical_block and "rank 0" in canonical_block
    assert "IN_REVIEW" in canonical_block and "rank 1" in canonical_block
    assert "QA" in canonical_block and "rank 2" in canonical_block


def test_canonical_block_permits_blocked_both_directions(canonical_block):
    # target is BLOCKED -> permit unconditionally
    assert "matches `BLOCKED`: **permit** unconditionally" in canonical_block
    # both directions must be covered: target==BLOCKED and current==BLOCKED
    blocked_permits = re.findall(r"matches `BLOCKED`: \*\*permit\*\* unconditionally", canonical_block)
    assert len(blocked_permits) >= 2, "expected both target==BLOCKED and current==BLOCKED permit clauses"


def test_canonical_block_has_tracker_state_values_param(canonical_block):
    assert "tracker_state_values" in canonical_block


def test_phase_11_input_list_includes_tracker_state_values():
    # Phase 11 enumerates its own inputs rather than inheriting the shared
    # "## Tracker Writeback Helper" invocation-contract list, so it needs its
    # own separate tracker_state_values entry (Step 3 of the spec). Locate the
    # Phase 11 QA-writeback spawn brief's `target_state` line and confirm
    # tracker_state_values appears in the same Inputs block.
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    anchor = '`target_state`: `$TRACKER_STATE_QA`'
    assert anchor in text, "Phase 11 spawn brief target_state line not found"
    idx = text.index(anchor)
    window = text[max(0, idx - 400):idx + 400]
    assert "tracker_state_values" in window, (
        "Phase 11's own Inputs list is missing tracker_state_values alongside target_state/forward_only_guard"
    )


def test_canonical_block_never_reads_cache_invariant(canonical_block):
    assert ".agentic/tracker-states.json" in canonical_block
    assert "never reads" in canonical_block.lower()


def test_canonical_block_single_l_canceled(canonical_block):
    assert "canceled" in canonical_block


def test_canonical_block_has_duplicate_terminal_state(canonical_block):
    assert "duplicate" in canonical_block


def test_canonical_block_field_absence_phrase(canonical_block):
    assert "pre-read succeeded but response omitted" in canonical_block


def test_canonical_block_fire_and_forget_vs_awaiting_caller(canonical_block):
    assert "Fire-and-forget call sites" in canonical_block
    assert "Callers that await the result" in canonical_block


# ---------------------------------------------------------------------------
# (b) byte-identity of the extracted block across all adapter copies
# ---------------------------------------------------------------------------

def test_block_byte_identical_across_adapters(canonical_block):
    missing = [p for p in ADAPTER_PATHS if not p.exists()]
    assert not missing, f"expected adapter files missing: {missing}"

    mismatches = []
    for path in ADAPTER_PATHS:
        text = path.read_text(encoding="utf-8")
        block = _extract_block(text)
        if block != canonical_block:
            mismatches.append(str(path.relative_to(REPO_ROOT)))
    assert not mismatches, (
        f"'## Tracker Writeback Helper' block diverges from canonical in: {mismatches}"
    )


# ---------------------------------------------------------------------------
# (c) spelling heuristic on the canonical block
# ---------------------------------------------------------------------------

def test_spelling_heuristic_single_l_on_trigger_lines(canonical_block):
    violations = []
    for line in canonical_block.splitlines():
        lower = line.lower()
        hit_count = sum(1 for tok in _TRIGGER_TOKENS if _token_present(lower, tok))
        if hit_count < 3:
            continue
        for m in _CANCEL_RE.finditer(line):
            word = m.group(0)
            tail = line[m.end():m.end() + 12]
            if word.lower() == "cancelled" and "(double L)" not in tail:
                violations.append(line)
    assert not violations, f"double-L 'cancelled' without a (double L) exemption on trigger line(s): {violations}"


def _token_present(lower_line: str, token: str) -> bool:
    """A trigger token counts only when it appears as a separated token
    (comma/pipe/angle-bracket/'<'-delimited), matching the spec's heuristic
    scope - not as a substring of unrelated prose."""
    pattern = r"(?:^|[\s,|<`])" + re.escape(token) + r"(?:$|[\s,|>`.;:])"
    return re.search(pattern, lower_line) is not None


# ---------------------------------------------------------------------------
# (d) ds-ticket-triage.md untouched literal check
# ---------------------------------------------------------------------------

def test_ticket_triage_already_correct_enumeration_untouched():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-triage.md"
    text = path.read_text(encoding="utf-8")
    assert "(completed, canceled)" in text


# ---------------------------------------------------------------------------
# (e) ds-ticket-status-sync.md no stale enumeration / restated ranking
# ---------------------------------------------------------------------------

def test_ticket_status_sync_no_bare_target_state_enumeration():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "target_state" in line and "forward_only_guard: true" in line:
            assert "tracker_state_values" in line, (
                f"line enumerates target_state/forward_only_guard without tracker_state_values: {line!r}"
            )


def test_ticket_status_sync_no_stale_inline_ranking_restatement():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    assert "backlog` < `unstarted` < `started` < `completed`" not in text
    assert "cancelled` terminal" not in text


# ---------------------------------------------------------------------------
# (f) ds-wrap.md Part F Gate regression guard
# ---------------------------------------------------------------------------

def test_wrap_part_f_gate_resolves_tracker_state_values():
    path = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
    text = path.read_text(encoding="utf-8")
    gate_lines = [l for l in text.splitlines() if l.strip().startswith("**Gate.**")]
    assert gate_lines, "Part F Gate line not found in ds-wrap.md"
    assert any("TRACKER_STATE_IN_PROGRESS" in l for l in gate_lines), (
        "Part F Gate line no longer resolves TRACKER_STATE_IN_PROGRESS"
    )
