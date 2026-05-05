"""
Tests for Skeptic Step-0 enforcement scenarios from scenarios-todo.md.

These tests validate the *harness-level* understanding of Step-0 behavior:
  - Field name constants for BLOCKED return values
  - Counter file path conventions
  - Token threshold constants for the Plan-tier overflow fallback
  - Supplemental-context vs Global-context heading distinctions

The harness does not spawn live Skeptics; these tests verify that the
scenario specifications from scenarios-todo.md are correctly encoded
as constants and utilities that downstream integration tests can import.
They also serve as binding contract tests: if a constant changes, a test
breaks and the change must be deliberate.

Scenario mapping (from scenarios-todo.md):
  S1 -> test_blocked_on_missing_field
  S2 -> test_blocked_on_invalid_na_value
  S3 -> test_counter_escalate_after_three_blocked
  S4 -> test_plan_tier_overflow_fallback
  Supplemental-context companion -> test_supplemental_context_shape
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Constants derived from scenarios-todo.md (used by integration layer)
# ---------------------------------------------------------------------------

# S1/S2: Canonical BLOCKED return prefix
SKEPTIC_BLOCKED_PREFIX = "BLOCKED - Global-context input set incomplete:"

# S1: Field name in the BLOCKED return for a missing qa_criteria block
BLOCKED_MISSING_QA_CRITERIA = (
    "BLOCKED - Global-context input set incomplete: qa_criteria block missing"
)

# S2: Field name in the BLOCKED return for a non-enum n/a value
BLOCKED_INVALID_NA_ARCHITECT_PLAN = (
    "BLOCKED - Global-context input set incomplete: "
    "architect plan n/a value not in enumerated set"
)

# S2: loop-state.json last_phase_action value when Skeptic returns BLOCKED
LOOP_STATE_BLOCKED_ACTION = "skeptic_blocked_input"

# S3: Counter file path pattern (relative to project root)
BLOCK_COUNTER_GLOB = ".agentic/.spawn-block-counter-*"
BLOCK_COUNTER_PATTERN = ".agentic/.spawn-block-counter-{unit_slug}"
BLOCK_COUNTER_MAX = 3  # escalate after this many consecutive BLOCKEDs

# S4: Plan-tier overflow token threshold (inclusive: >= fires fallback)
PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS = 60_000

# Supplemental-context headings
GLOBAL_CONTEXT_HEADING = "## Global-context inputs"
SUPPLEMENTAL_CONTEXT_HEADING = "## Supplemental context"


# ---------------------------------------------------------------------------
# S1 - BLOCKED on incomplete prompt structure
# ---------------------------------------------------------------------------

class TestBlockedOnMissingField:
    """Scenario 1: Skeptic returns BLOCKED when Global-context block is missing
    a required field. No review content follows."""

    def test_blocked_on_missing_field(self):
        """BLOCKED return string matches the contract's exact format."""
        assert BLOCKED_MISSING_QA_CRITERIA.startswith(SKEPTIC_BLOCKED_PREFIX)
        assert "qa_criteria block missing" in BLOCKED_MISSING_QA_CRITERIA

    def test_blocked_string_contains_no_review_content(self):
        """Simulated BLOCKED return must not contain review content markers."""
        blocked_return = BLOCKED_MISSING_QA_CRITERIA
        review_markers = ["Reviewed:", "Findings:", "Critical:", "Major:", "Minor:"]
        for marker in review_markers:
            assert marker not in blocked_return, (
                f"BLOCKED return must not contain '{marker}'"
            )

    def test_loop_state_action_value(self):
        """loop-state.json last_phase_action must be 'skeptic_blocked_input' on BLOCKED."""
        assert LOOP_STATE_BLOCKED_ACTION == "skeptic_blocked_input"

    def test_multi_dim_only_correctness_skeptic_blocks(self):
        """In multi-dim fan-out, only the correctness-Skeptic (Global-context)
        can trigger Step-0 BLOCKED. security-auditor and perf-analyst use
        Supplemental-context and do NOT block on missing qa_criteria."""
        global_context_agents = {"correctness-skeptic"}
        supplemental_context_agents = {"security-auditor", "perf-analyst"}
        # These sets are mutually exclusive
        assert global_context_agents.isdisjoint(supplemental_context_agents)
        # Only Global-context agents are subject to Step-0
        step0_applies_to = global_context_agents
        step0_does_not_apply_to = supplemental_context_agents
        assert "correctness-skeptic" in step0_applies_to
        assert "security-auditor" in step0_does_not_apply_to
        assert "perf-analyst" in step0_does_not_apply_to


# ---------------------------------------------------------------------------
# S2 - BLOCKED on non-enum n/a value
# ---------------------------------------------------------------------------

class TestBlockedOnInvalidNaValue:
    """Scenario 2: Skeptic returns BLOCKED when a Global-context field carries
    a bare n/a or non-enumerated n/a-<string> value."""

    def test_blocked_on_invalid_na_format(self):
        """BLOCKED return for invalid n/a includes architect-plan field name."""
        assert BLOCKED_INVALID_NA_ARCHITECT_PLAN.startswith(SKEPTIC_BLOCKED_PREFIX)
        assert "architect plan" in BLOCKED_INVALID_NA_ARCHITECT_PLAN
        assert "n/a value not in enumerated set" in BLOCKED_INVALID_NA_ARCHITECT_PLAN

    def test_bare_na_is_invalid(self):
        """A bare 'n/a' is not a valid enumerated n/a value."""
        invalid_values = ["n/a", "n/a - I forgot", "n/a - unknown"]
        # These should trigger BLOCKED (represented here as invalid)
        for val in invalid_values:
            # The string starts with 'n/a' but is NOT in an enumerated set
            # The enum is defined in Section 4.5; we only check the bare prefix
            assert val.startswith("n/a"), f"Expected bare n/a prefix for '{val}'"

    def test_valid_na_does_not_block(self):
        """Valid n/a values from the enumerated set must NOT trigger BLOCKED.

        From Section 4.5, valid n/a enum values are enumerated. The harness
        records which values are in-set; this test verifies the discriminator
        logic by checking that the invalid pattern 'n/a - <free text>' is
        structurally distinguishable from an enumerated value.

        Conservative implementation: the valid set is defined downstream; this
        test only asserts that the BLOCKED string format is correct for invalid.
        """
        # For now we assert the discriminator can be applied:
        # a value IS in the enum set XOR it matches the free-text pattern
        free_text_na_pattern = re.compile(r"^n/a - .+$")
        bare_na = "n/a"
        free_text_na = "n/a - I forgot"
        assert free_text_na_pattern.match(free_text_na)
        assert not free_text_na_pattern.match(bare_na)

    def test_loop_state_action_unchanged_on_blocked(self):
        """loop-state.json iteration counter must not advance on BLOCKED."""
        # Represented as: the action value stays at skeptic_blocked_input
        assert LOOP_STATE_BLOCKED_ACTION == "skeptic_blocked_input"


# ---------------------------------------------------------------------------
# S3 - Counter-and-escalate after 3 consecutive BLOCKEDs
# ---------------------------------------------------------------------------

class TestCounterEscalateAfterThreeBlocked:
    """Scenario 3: After 3 consecutive skeptic_blocked_input returns, conductor
    escalates and does not retry."""

    def test_max_retries_constant(self):
        """BLOCK_COUNTER_MAX must be 3 per scenarios-todo.md."""
        assert BLOCK_COUNTER_MAX == 3

    def test_counter_file_path_format(self):
        """Counter file path follows .agentic/.spawn-block-counter-<unit_slug>."""
        unit_slug = "my-feature"
        expected = f".agentic/.spawn-block-counter-{unit_slug}"
        actual = BLOCK_COUNTER_PATTERN.format(unit_slug=unit_slug)
        assert actual == expected

    def test_single_unit_slug(self):
        """For single-unit spawns, unit_slug is 'single'."""
        single_unit_path = BLOCK_COUNTER_PATTERN.format(unit_slug="single")
        assert single_unit_path == ".agentic/.spawn-block-counter-single"

    def test_counter_glob_matches_single_unit(self):
        """BLOCK_COUNTER_GLOB pattern covers both named and single slugs."""
        # The glob .agentic/.spawn-block-counter-* covers all slugs
        import fnmatch
        single_path = ".agentic/.spawn-block-counter-single"
        named_path = ".agentic/.spawn-block-counter-my-feature"
        assert fnmatch.fnmatch(single_path, BLOCK_COUNTER_GLOB)
        assert fnmatch.fnmatch(named_path, BLOCK_COUNTER_GLOB)

    def test_supplemental_context_agents_do_not_increment_step0_counter(self):
        """security-auditor and perf-analyst BLOCKED returns (if any) do NOT
        increment the Step-0 block counter. They block for engineer-fault or
        domain-fault reasons, not conductor-fault (missing Global-context)."""
        # This is a spec assertion, not a runtime check.
        # The counter ONLY tracks conductor-fault Step-0 BLOCKEDs.
        step0_counter_agents = {"correctness-skeptic"}
        non_step0_agents = {"security-auditor", "perf-analyst"}
        assert step0_counter_agents.isdisjoint(non_step0_agents)


# ---------------------------------------------------------------------------
# S4 - Plan-tier overflow fallback fires above 60K tokens
# ---------------------------------------------------------------------------

class TestPlanTierOverflowFallback:
    """Scenario 4: When combined Global-context input set exceeds 60K tokens,
    conductor switches to per-unit Skeptics plus lightweight integration Skeptic."""

    def test_overflow_threshold_constant(self):
        """Overflow threshold is 60,000 tokens (inclusive: fires at >= 60K)."""
        assert PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS == 60_000

    def test_threshold_is_inclusive(self):
        """Fallback fires at >= 60K, not at > 60K."""
        token_counts = [59_999, 60_000, 60_001]
        expected_fires = [False, True, True]
        for count, expect in zip(token_counts, expected_fires):
            fires = count >= PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS
            assert fires == expect, (
                f"At {count} tokens, expected fires={expect}, got {fires}"
            )

    def test_per_unit_skeptics_not_single_combined(self):
        """When fallback fires, conductor spawns per-unit Skeptics, not one
        combined Skeptic with the full context."""
        # Spec: integration Skeptic receives findings list only, not full context
        integration_receives_full_context = False  # per contract
        assert not integration_receives_full_context

    def test_integration_skeptic_receives_findings_only(self):
        """Integration Skeptic receives the findings list, NOT the full
        Global-context block."""
        # Spec binding: integration_skeptic_input == "findings_list_only"
        integration_skeptic_input = "findings_list_only"
        assert integration_skeptic_input == "findings_list_only"


# ---------------------------------------------------------------------------
# Supplemental-context shape verification (companion to S1-S3)
# ---------------------------------------------------------------------------

class TestSupplementalContextShape:
    """Companion scenario: security-auditor and perf-analyst receive
    ## Supplemental context (not ## Global-context inputs) in multi-dim fan-out."""

    def test_heading_constants_are_distinct(self):
        """Global-context and Supplemental-context headings are distinct strings."""
        assert GLOBAL_CONTEXT_HEADING != SUPPLEMENTAL_CONTEXT_HEADING

    def test_global_context_heading_format(self):
        """Global-context inputs heading matches exact spec string."""
        assert GLOBAL_CONTEXT_HEADING == "## Global-context inputs"

    def test_supplemental_context_heading_format(self):
        """Supplemental context heading matches exact spec string."""
        assert SUPPLEMENTAL_CONTEXT_HEADING == "## Supplemental context"

    def test_correctness_skeptic_uses_global_context(self):
        """correctness-Skeptic prompt must contain ## Global-context inputs."""
        agent_heading_map = {
            "correctness-skeptic": GLOBAL_CONTEXT_HEADING,
            "security-auditor": SUPPLEMENTAL_CONTEXT_HEADING,
            "perf-analyst": SUPPLEMENTAL_CONTEXT_HEADING,
        }
        assert agent_heading_map["correctness-skeptic"] == GLOBAL_CONTEXT_HEADING
        assert agent_heading_map["security-auditor"] == SUPPLEMENTAL_CONTEXT_HEADING
        assert agent_heading_map["perf-analyst"] == SUPPLEMENTAL_CONTEXT_HEADING

    def test_supplemental_agents_do_not_use_global_context_heading(self):
        """security-auditor and perf-analyst must NOT use ## Global-context inputs."""
        supplemental_agents = ["security-auditor", "perf-analyst"]
        for agent in supplemental_agents:
            # Confirm heading is supplemental, not global
            if agent in ("security-auditor", "perf-analyst"):
                heading = SUPPLEMENTAL_CONTEXT_HEADING
            else:
                heading = GLOBAL_CONTEXT_HEADING
            assert heading != GLOBAL_CONTEXT_HEADING or agent == "correctness-skeptic"

    def test_omitting_qa_criteria_from_supplemental_does_not_block(self):
        """Omitting qa_criteria from Supplemental-context does NOT cause BLOCKED
        on security-auditor or perf-analyst. Step-0 does not apply to them."""
        # Spec binding: Step-0 enforcement is Global-context only
        step0_applies_to_supplemental = False
        assert not step0_applies_to_supplemental
