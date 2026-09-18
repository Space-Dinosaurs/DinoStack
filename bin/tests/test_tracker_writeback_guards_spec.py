#!/usr/bin/env python3
"""
Spec tests for the Tracker Writeback Helper's guards: the
`transitions: manual` kill switch, guard 4.5 (human-override), and guard 4.6
(reverted-PR). These pin the specific literals and structural invariants
named in the plan - the exact 15-minute tolerance, the three new
return statuses, the null-semantics of `expected_source_state`/
`merged_pr_number`, the kill-switch's position ahead of the state pre-read,
and byte-identity between the kernel's per-call-site binding table and the
reference's pointer back to it.

Covers:
  - steps 4.5 and 4.6 exist, in that order, between step 4 and step 5 (no
    renumbering of the pre-existing 1-5 steps, which are pinned by
    test_tracker_writeback_ranking_spec.py).
  - the 15-minute tolerance literal.
  - the three new return statuses (skipped_human_override,
    skipped_reverted_pr, skipped_transitions_manual) are present in the
    Full return-status set line and in Phase 11's own Returns line.
  - `expected_source_state`/`merged_pr_number` null-semantics: a `null`
    `expected_source_state` makes 4.5 inapplicable; a `null`
    `merged_pr_number` makes 4.6 a no-op.
  - the kill switch is checked before step 1 (the state pre-read), costing
    zero round trips.
  - byte-identity between the kernel's "Caller enumeration" binding table
    and the corresponding pointer/count in the reference document's Note.

Run with: python3 -m pytest bin/tests/test_tracker_writeback_guards_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HELPER_PATH = REPO_ROOT / "content" / "references" / "tracker-writeback.md"
CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

HEADING = "## Tracker Writeback Helper"


def _extract_block(text: str) -> str:
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
def helper_text() -> str:
    return HELPER_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def canonical_text() -> str:
    return CANONICAL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Steps 4.5 / 4.6 exist, in order, between step 4 and step 5
# ---------------------------------------------------------------------------

def test_steps_4_5_and_4_6_present_in_order(helper_text):
    idx_4 = helper_text.index("4. **Apply the guard**")
    idx_45 = helper_text.index("4.5. **Human-override guard")
    idx_46 = helper_text.index("4.6. **Reverted-PR guard")
    idx_5 = helper_text.index('5. **Soft-fail:**')
    assert idx_4 < idx_45 < idx_46 < idx_5, (
        "expected step order: 4 < 4.5 < 4.6 < 5 (no renumbering of 1-5)"
    )


def test_existing_steps_1_through_5_still_numbered_1_to_5(helper_text):
    # Regression guard: 4.5/4.6 must be ADDITIONS, never a renumbering of the
    # pre-existing 5 steps pinned by test_tracker_writeback_ranking_spec.py.
    for n in (1, 2, 3, 4, 5):
        assert re.search(rf"(?m)^{n}\. \*\*", helper_text), f"step {n} missing or renumbered"


# ---------------------------------------------------------------------------
# 15-minute tolerance literal
# ---------------------------------------------------------------------------

def test_15_minute_tolerance_literal_present(helper_text):
    idx = helper_text.index("4.5. **Human-override guard")
    window = helper_text[idx:idx + 1800]
    assert "**15 minutes**" in window
    assert "same-session near-simultaneous" in window
    assert "stale entry from an earlier session must never authorize a fresh push" in window


# ---------------------------------------------------------------------------
# Three new return statuses
# ---------------------------------------------------------------------------

NEW_STATUSES = (
    "skipped_human_override",
    "skipped_reverted_pr",
    "skipped_transitions_manual",
)


def test_full_return_status_set_line_has_all_three(helper_text):
    lines = [
        l for l in helper_text.splitlines() if l.strip().startswith("**Full return-status set:**")
    ]
    assert lines, "Full return-status set line not found"
    for status in NEW_STATUSES:
        assert all(status in l for l in lines), f"{status} missing from Full return-status set line"


def test_phase_11_returns_line_has_all_three(canonical_text):
    returns_lines = [
        l for l in canonical_text.splitlines() if l.strip().startswith("> **Returns:**")
    ]
    assert returns_lines, "Phase 11 Returns line not found"
    for status in NEW_STATUSES:
        assert all(status in l for l in returns_lines), f"{status} missing from Phase 11 Returns line"


def test_each_new_status_has_a_dedicated_skip_reason(helper_text):
    idx_45 = helper_text.index("4.5. **Human-override guard")
    idx_46 = helper_text.index("4.6. **Reverted-PR guard")
    idx_5 = helper_text.index('5. **Soft-fail:**')
    guard_45_text = helper_text[idx_45:idx_46]
    guard_46_text = helper_text[idx_46:idx_5]
    assert 'status: "skipped_human_override"' in guard_45_text
    assert 'status: "skipped_reverted_pr"' in guard_46_text

    kill_switch_idx = helper_text.index("**Kill switch (checked FIRST")
    kill_switch_window = helper_text[kill_switch_idx:kill_switch_idx + 700]
    assert 'status: "skipped_transitions_manual"' in kill_switch_window


# ---------------------------------------------------------------------------
# expected_source_state / merged_pr_number null-semantics
# ---------------------------------------------------------------------------

def test_expected_source_state_null_semantics(helper_text):
    idx_45 = helper_text.index("4.5. **Human-override guard")
    idx_46 = helper_text.index("4.6. **Reverted-PR guard")
    guard_45_text = helper_text[idx_45:idx_46]
    assert "If `expected_source_state`" in guard_45_text
    assert "is `null`: this guard is not applicable at this call site - proceed to 4.6" in guard_45_text


def test_merged_pr_number_null_semantics(helper_text):
    idx_46 = helper_text.index("4.6. **Reverted-PR guard")
    idx_5 = helper_text.index('5. **Soft-fail:**')
    guard_46_text = helper_text[idx_46:idx_5]
    assert "No-op unless `merged_pr_number`" in guard_46_text
    assert "is non-null" in guard_46_text


def test_invocation_contract_declares_both_inputs_as_nullable(helper_text):
    idx = helper_text.index("**Invocation contract:**")
    end = helper_text.index("**Subagent responsibilities", idx)
    window = helper_text[idx:end]
    assert "`expected_source_state`: string|null" in window
    assert "`merged_pr_number`: integer|null" in window


# ---------------------------------------------------------------------------
# Kill switch gate position: before step 1 (the state pre-read)
# ---------------------------------------------------------------------------

def test_kill_switch_precedes_step_1_pre_read(helper_text):
    idx_responsibilities = helper_text.index(
        "**Subagent responsibilities (extended for `forward_only_guard`):**"
    )
    idx_kill_switch = helper_text.index("**Kill switch (checked FIRST")
    idx_step1 = helper_text.index("1. **Pre-read current state:**")
    assert idx_responsibilities < idx_kill_switch < idx_step1, (
        "kill switch must be checked before step 1's state pre-read"
    )


def test_kill_switch_costs_zero_round_trips(helper_text):
    idx = helper_text.index("**Kill switch (checked FIRST")
    window = helper_text[idx:idx + 700]
    assert "costs zero round trips" in window
    assert "make NO pre-read call" in window


# ---------------------------------------------------------------------------
# Byte-identity: kernel binding table <-> reference pointer/count
# ---------------------------------------------------------------------------

BINDING_TABLE_SITES = (
    "| W1 |",
    "| W2 |",
    "| W3 |",
    "| W4 / W5 / W6a / W6b (all target Blocked) |",
    "| W7 |",
    "| Phase 11 |",
    "| Merge-time tracker writeback rule |",
    "| `--pending-merge` sweep (f) |",
    "| `/ds-ticket-status-sync` single / `--all` Tier 1 |",
    "| `/ds-wrap` Part F |",
)


def test_kernel_binding_table_present_and_complete(canonical_text):
    idx = canonical_text.index("**`expected_source_state` / `merged_pr_number` binding table")
    window = canonical_text[idx:idx + 2000]
    for row in BINDING_TABLE_SITES:
        assert row in window, f"binding table missing row {row!r}"


def test_reference_note_count_matches_and_names_binding_table(helper_text):
    note_lines = [l for l in helper_text.splitlines() if l.strip().startswith("> Note: ")]
    assert note_lines, "duplication Note not found"
    note = note_lines[0]
    assert "six statements" in note
    assert "expected_source_state" in note and "merged_pr_number" in note
    assert "if the two ever disagree, the kernel block governs".lower() in note.lower()


def test_kernel_table_not_present_verbatim_in_reference(helper_text):
    # The reference must point back to the kernel table, never re-embed it -
    # this is the exact duplication discipline the Note asserts.
    for row in BINDING_TABLE_SITES:
        assert row not in helper_text, (
            f"reference doc must not re-embed binding table row {row!r} - "
            "it must point back to the kernel instead"
        )
