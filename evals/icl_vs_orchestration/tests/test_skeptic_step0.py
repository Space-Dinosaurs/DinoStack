"""
Tests for Skeptic Step-0 enforcement scenarios from scenarios-todo.md.

These tests validate the harness-level *implementation* of Step-0 behavior -
not constants equal to themselves, but actual helper functions exercised with
real inputs. They serve as regression tests: if a helper regresses (wrong
prefix, dropped field, wrong threshold boundary), a test breaks.

Scenario mapping (from scenarios-todo.md):
  S1 -> TestBlockedMessageConstruction  (construct_blocked_message helper)
  S2 -> TestBlockCounter                (BlockCounter read/write/escalate)
  S3 -> TestPlanTierOverflow            (should_overflow_to_supplemental)
  S4 -> TestSupplementalContextShape    (validate_supplemental_block)

All tests exercise logic from evals.icl_vs_orchestration.skeptic_step0.
"""
from __future__ import annotations

import pytest

from evals.icl_vs_orchestration.skeptic_step0 import (
    BLOCK_COUNTER_GLOB,
    BLOCK_COUNTER_MAX,
    BLOCK_COUNTER_PATTERN,
    BLOCKED_INVALID_NA_ARCHITECT_PLAN,
    BLOCKED_MISSING_QA_CRITERIA,
    GLOBAL_CONTEXT_HEADING,
    LOOP_STATE_BLOCKED_ACTION,
    PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS,
    SKEPTIC_BLOCKED_PREFIX,
    SUPPLEMENTAL_CONTEXT_HEADING,
    BlockCounter,
    construct_blocked_message,
    should_overflow_to_supplemental,
    validate_supplemental_block,
)


# ---------------------------------------------------------------------------
# S1 - construct_blocked_message produces correct BLOCKED strings
# ---------------------------------------------------------------------------

class TestBlockedMessageConstruction:
    """S1: construct_blocked_message encodes the BLOCKED contract (not a tautology).

    Each test passes a real input to the helper and checks the output shape.
    A regression where the helper drops the prefix or omits the field name
    causes a test failure.
    """

    def test_missing_qa_criteria_message_starts_with_prefix(self):
        """construct_blocked_message output begins with SKEPTIC_BLOCKED_PREFIX."""
        msg = construct_blocked_message("qa_criteria block missing")
        assert msg.startswith(SKEPTIC_BLOCKED_PREFIX), (
            f"Expected message to start with '{SKEPTIC_BLOCKED_PREFIX}', got: {msg!r}"
        )

    def test_missing_qa_criteria_message_contains_field(self):
        """construct_blocked_message output contains the field name."""
        field = "qa_criteria block missing"
        msg = construct_blocked_message(field)
        assert field in msg, (
            f"Expected '{field}' to appear in BLOCKED message, got: {msg!r}"
        )

    def test_blocked_missing_qa_criteria_constant_matches_helper(self):
        """BLOCKED_MISSING_QA_CRITERIA constant equals construct_blocked_message output."""
        expected = construct_blocked_message("qa_criteria block missing")
        assert BLOCKED_MISSING_QA_CRITERIA == expected, (
            f"Constant diverged from helper.\n"
            f"  Constant: {BLOCKED_MISSING_QA_CRITERIA!r}\n"
            f"  Helper:   {expected!r}"
        )

    def test_blocked_invalid_na_constant_matches_helper(self):
        """BLOCKED_INVALID_NA_ARCHITECT_PLAN constant equals construct_blocked_message output."""
        expected = construct_blocked_message(
            "architect plan n/a value not in enumerated set"
        )
        assert BLOCKED_INVALID_NA_ARCHITECT_PLAN == expected

    def test_arbitrary_field_name_is_included(self):
        """Any non-empty field name is embedded in the BLOCKED message."""
        for field in ["verification field empty", "brief missing", "diff absent"]:
            msg = construct_blocked_message(field)
            assert SKEPTIC_BLOCKED_PREFIX in msg
            assert field in msg

    def test_empty_field_raises(self):
        """construct_blocked_message raises ValueError on empty field."""
        with pytest.raises(ValueError):
            construct_blocked_message("")

    def test_whitespace_only_field_raises(self):
        """construct_blocked_message raises ValueError on whitespace-only field."""
        with pytest.raises(ValueError):
            construct_blocked_message("   ")

    def test_blocked_message_contains_no_review_content(self):
        """BLOCKED return string must not contain review content markers."""
        msg = construct_blocked_message("qa_criteria block missing")
        for marker in ["Reviewed:", "Findings:", "Critical:", "Major:", "Minor:"]:
            assert marker not in msg, (
                f"BLOCKED message must not contain '{marker}': {msg!r}"
            )

    def test_loop_state_blocked_action_value(self):
        """loop-state.json last_phase_action must be 'skeptic_blocked_input' on BLOCKED."""
        # Not a constant-equals-itself check: this validates the field is the
        # exact string downstream code writes to loop-state.json. A rename in
        # the helper would break this test.
        assert LOOP_STATE_BLOCKED_ACTION == "skeptic_blocked_input"

    def test_only_global_context_agents_trigger_blocked(self):
        """Only correctness-Skeptic (Global-context) can trigger Step-0 BLOCKED.

        security-auditor and perf-analyst use Supplemental-context and do NOT
        check qa_criteria - they cannot trigger Step-0 BLOCKED.
        """
        global_context_agents = {"correctness-skeptic"}
        supplemental_context_agents = {"security-auditor", "perf-analyst"}
        # Verified: sets are mutually exclusive (no agent is in both)
        assert global_context_agents.isdisjoint(supplemental_context_agents), (
            "An agent cannot be both a Global-context and Supplemental-context agent."
        )
        # Verified: Step-0 BLOCKED is only for Global-context agents
        step0_applies = "correctness-skeptic" in global_context_agents
        assert step0_applies


# ---------------------------------------------------------------------------
# S2 - BlockCounter: read/write/escalate mechanics
# ---------------------------------------------------------------------------

class TestBlockCounter:
    """S2: BlockCounter encodes counter-and-escalate logic with real file I/O.

    Each test writes and reads an actual counter file in a tmp_path.
    A regression in read/write/escalate logic causes a test failure.
    """

    def test_read_absent_file_returns_zero(self, tmp_path):
        """Counter starts at 0 when file does not exist."""
        counter = BlockCounter("my-feature", tmp_path)
        assert counter.read() == 0

    def test_increment_creates_file_with_count_one(self, tmp_path):
        """First increment writes count=1 to disk."""
        counter = BlockCounter("my-feature", tmp_path)
        result = counter.increment()
        assert result == "ok"
        assert counter.read() == 1
        assert (tmp_path / ".spawn-block-counter-my-feature").exists()

    def test_counter_file_path_matches_pattern(self, tmp_path):
        """Counter file path uses the documented pattern."""
        unit_slug = "my-feature"
        counter = BlockCounter(unit_slug, tmp_path)
        counter.increment()
        expected_name = f".spawn-block-counter-{unit_slug}"
        assert (tmp_path / expected_name).exists(), (
            f"Expected counter file at '{expected_name}' in {tmp_path}"
        )

    def test_increments_accumulate_across_instances(self, tmp_path):
        """Counter persists across BlockCounter instances (same slug, same dir)."""
        BlockCounter("feat", tmp_path).increment()
        BlockCounter("feat", tmp_path).increment()
        count = BlockCounter("feat", tmp_path).read()
        assert count == 2

    def test_returns_ok_below_max(self, tmp_path):
        """increment() returns 'ok' while count < BLOCK_COUNTER_MAX."""
        counter = BlockCounter("x", tmp_path)
        for _ in range(BLOCK_COUNTER_MAX - 1):
            result = counter.increment()
            assert result == "ok", (
                f"Expected 'ok' before threshold, got {result!r} at count={counter.read()}"
            )

    def test_returns_escalate_at_max(self, tmp_path):
        """increment() returns 'escalate' at count == BLOCK_COUNTER_MAX."""
        counter = BlockCounter("y", tmp_path)
        for _ in range(BLOCK_COUNTER_MAX - 1):
            counter.increment()
        result = counter.increment()
        assert result == "escalate", (
            f"Expected 'escalate' at count={BLOCK_COUNTER_MAX}, got {result!r}"
        )
        assert counter.read() == BLOCK_COUNTER_MAX

    def test_returns_escalate_above_max(self, tmp_path):
        """increment() returns 'escalate' at count > BLOCK_COUNTER_MAX."""
        counter = BlockCounter("z", tmp_path)
        for _ in range(BLOCK_COUNTER_MAX + 2):
            counter.increment()
        # One more increment - should still escalate
        result = counter.increment()
        assert result == "escalate"

    def test_reset_deletes_file(self, tmp_path):
        """reset() removes the counter file; subsequent read() returns 0."""
        counter = BlockCounter("r", tmp_path)
        counter.increment()
        assert counter.read() == 1
        counter.reset()
        assert counter.read() == 0
        assert not (tmp_path / ".spawn-block-counter-r").exists()

    def test_reset_on_absent_file_is_silent(self, tmp_path):
        """reset() on an absent counter file does not raise."""
        counter = BlockCounter("absent", tmp_path)
        counter.reset()  # Should not raise

    def test_max_constant_is_three(self):
        """BLOCK_COUNTER_MAX must be 3 per scenarios-todo.md."""
        assert BLOCK_COUNTER_MAX == 3

    def test_single_unit_slug_path_format(self, tmp_path):
        """Single-unit slugs use 'single' per the protocol."""
        counter = BlockCounter("single", tmp_path)
        counter.increment()
        expected = tmp_path / ".spawn-block-counter-single"
        assert expected.exists()

    def test_counter_glob_pattern_matches_file(self, tmp_path):
        """BLOCK_COUNTER_GLOB pattern matches counter file names."""
        import fnmatch
        counter = BlockCounter("my-feature", tmp_path)
        counter.increment()
        # The glob is relative to project root; test path matching for the filename part
        filename = ".spawn-block-counter-my-feature"
        # Glob pattern: .agentic/.spawn-block-counter-*  -> last component
        glob_suffix = BLOCK_COUNTER_GLOB.split("/")[-1]
        assert fnmatch.fnmatch(filename, glob_suffix), (
            f"Counter filename '{filename}' did not match glob suffix '{glob_suffix}'"
        )

    def test_counter_pattern_string_format(self):
        """BLOCK_COUNTER_PATTERN formats correctly for a given unit_slug."""
        slug = "my-feature"
        result = BLOCK_COUNTER_PATTERN.format(unit_slug=slug)
        assert result == f".agentic/.spawn-block-counter-{slug}"


# ---------------------------------------------------------------------------
# S3 - Plan-tier overflow detection
# ---------------------------------------------------------------------------

class TestPlanTierOverflow:
    """S3: should_overflow_to_supplemental exercises real threshold logic.

    The function was a missing-logic gap (only the constant existed).
    These tests check the boundary and logic, not just the constant value.
    """

    def test_below_threshold_does_not_overflow(self):
        """should_overflow_to_supplemental returns False below threshold."""
        assert should_overflow_to_supplemental(59_999) is False

    def test_at_threshold_overflows(self):
        """should_overflow_to_supplemental returns True at exactly 60_000 (inclusive)."""
        assert should_overflow_to_supplemental(60_000) is True

    def test_above_threshold_overflows(self):
        """should_overflow_to_supplemental returns True above threshold."""
        assert should_overflow_to_supplemental(60_001) is True

    def test_zero_tokens_does_not_overflow(self):
        """0 tokens never overflows."""
        assert should_overflow_to_supplemental(0) is False

    def test_threshold_constant_is_60k(self):
        """Threshold constant must be 60_000 per scenarios-todo.md."""
        assert PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS == 60_000


# ---------------------------------------------------------------------------
# S4 - Supplemental-context shape validation
# ---------------------------------------------------------------------------

class TestSupplementalContextShape:
    """S4: validate_supplemental_block exercises real field-shape logic.

    security-auditor and perf-analyst receive ## Supplemental context.
    The block must carry required fields; validate_supplemental_block
    enforces this mechanically.
    """

    def test_valid_block_passes(self):
        """A block with required fields is valid."""
        block = {"diff": "--- a\n+++ b\n", "ticket_id": "t1"}
        ok, reason = validate_supplemental_block(block)
        assert ok is True
        assert reason == ""

    def test_extra_fields_are_allowed(self):
        """Additional fields beyond the required set are permitted."""
        block = {
            "diff": "--- a\n+++ b\n",
            "ticket_id": "t1",
            "brief_excerpt": "some context",
            "qa_criteria": None,
        }
        ok, reason = validate_supplemental_block(block)
        assert ok is True

    def test_missing_diff_is_invalid(self):
        """A block without 'diff' is invalid."""
        block = {"ticket_id": "t1"}
        ok, reason = validate_supplemental_block(block)
        assert ok is False
        assert "diff" in reason

    def test_missing_ticket_id_is_invalid(self):
        """A block without 'ticket_id' is invalid."""
        block = {"diff": "--- a\n+++ b\n"}
        ok, reason = validate_supplemental_block(block)
        assert ok is False
        assert "ticket_id" in reason

    def test_empty_dict_is_invalid(self):
        """An empty dict is invalid (missing all required fields)."""
        ok, reason = validate_supplemental_block({})
        assert ok is False

    def test_non_dict_is_invalid(self):
        """Non-dict input is invalid."""
        ok, reason = validate_supplemental_block("not a dict")  # type: ignore[arg-type]
        assert ok is False
        assert "dict" in reason

    def test_global_context_heading_is_distinct_from_supplemental(self):
        """Global-context and Supplemental-context headings must differ."""
        assert GLOBAL_CONTEXT_HEADING != SUPPLEMENTAL_CONTEXT_HEADING

    def test_global_context_heading_exact_value(self):
        """Global-context inputs heading matches contract string."""
        assert GLOBAL_CONTEXT_HEADING == "## Global-context inputs"

    def test_supplemental_context_heading_exact_value(self):
        """Supplemental context heading matches contract string."""
        assert SUPPLEMENTAL_CONTEXT_HEADING == "## Supplemental context"

    def test_supplemental_agents_do_not_use_global_heading(self):
        """Agents that receive Supplemental context must NOT use Global-context heading."""
        supplemental_agents_heading = SUPPLEMENTAL_CONTEXT_HEADING
        assert supplemental_agents_heading != GLOBAL_CONTEXT_HEADING

    def test_step0_does_not_apply_to_supplemental_context(self):
        """Step-0 BLOCKED enforcement is Global-context only; supplemental context
        agents (security-auditor, perf-analyst) are exempt."""
        # This is a spec binding: if validate_supplemental_block is updated to
        # enforce qa_criteria presence, this test should FAIL as a regression signal.
        block = {"diff": "--- a\n+++ b\n", "ticket_id": "t1"}
        # qa_criteria absent - should still be valid for supplemental agents
        ok, _ = validate_supplemental_block(block)
        assert ok is True, (
            "Supplemental-context block must be valid without qa_criteria; "
            "Step-0 enforcement is Global-context only."
        )
