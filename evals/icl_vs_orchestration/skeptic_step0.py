"""
Purpose: Harness-level helpers for Skeptic Step-0 enforcement scenarios
         from scenarios-todo.md. These encode the mechanical contract for
         BLOCKED return values, per-unit block counters, Plan-tier overflow
         detection, and supplemental-context shape validation.

Public API:
  construct_blocked_message(missing_field: str) -> str
    Build the canonical BLOCKED return string for a missing Global-context
    field. The conductor checks that Skeptic output equals this string when
    a required input is absent.

  SKEPTIC_BLOCKED_PREFIX: str
    The common prefix shared by all BLOCKED return values (S1, S2).

  BlockCounter(unit_slug: str, counter_dir: Path)
    Read/write helper for the per-unit-slug block counter file. Increments
    on each call to .increment() and returns "escalate" when count >= MAX.

  should_overflow_to_supplemental(token_count: int) -> bool
    Returns True when combined Global-context input set is >= 60_000 tokens,
    triggering the Plan-tier overflow fallback (S4).

  validate_supplemental_block(block: dict) -> tuple[bool, str]
    Validates the shape of a supplemental-context block (S4 companion).
    Returns (True, "") on valid; (False, reason) on invalid.

  BLOCK_COUNTER_MAX: int = 3
  BLOCK_COUNTER_PATTERN: str
  BLOCK_COUNTER_GLOB: str
  PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS: int = 60_000

Upstream deps: stdlib pathlib, typing.

Downstream consumers: tests/test_skeptic_step0.py, integration harness.

Failure modes: BlockCounter.increment() raises OSError only on genuine
               filesystem failures (permission denied, disk full). Counter
               read on absent file is treated as count=0 (first increment).
               construct_blocked_message raises ValueError on empty field.

Performance: O(1) for all operations; counter file I/O is small.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# S1 / S2 - BLOCKED return construction
# ---------------------------------------------------------------------------

# Canonical BLOCKED return prefix; must match exactly what the Skeptic emits.
SKEPTIC_BLOCKED_PREFIX = "BLOCKED - Global-context input set incomplete:"

# loop-state.json last_phase_action value when Skeptic returns BLOCKED.
LOOP_STATE_BLOCKED_ACTION = "skeptic_blocked_input"


def construct_blocked_message(missing_field: str) -> str:
    """Build the canonical BLOCKED return string for a missing Global-context field.

    Args:
        missing_field: Human-readable name of the missing or invalid field.
            Must be non-empty.

    Returns:
        The full BLOCKED string the Skeptic emits, beginning with
        SKEPTIC_BLOCKED_PREFIX followed by the field description.

    Raises:
        ValueError: if missing_field is empty or whitespace-only.
    """
    if not missing_field or not missing_field.strip():
        raise ValueError(
            "missing_field must be a non-empty string describing the missing "
            "Global-context input."
        )
    return f"{SKEPTIC_BLOCKED_PREFIX} {missing_field.strip()}"


# Pre-built canonical BLOCKED messages for common cases.
BLOCKED_MISSING_QA_CRITERIA = construct_blocked_message(
    "qa_criteria block missing"
)
BLOCKED_INVALID_NA_ARCHITECT_PLAN = construct_blocked_message(
    "architect plan n/a value not in enumerated set"
)

# ---------------------------------------------------------------------------
# S3 - BlockCounter: read/write per-unit-slug counter file
# ---------------------------------------------------------------------------

# Counter file constants (from scenarios-todo.md).
BLOCK_COUNTER_GLOB = ".agentic/.spawn-block-counter-*"
BLOCK_COUNTER_PATTERN = ".agentic/.spawn-block-counter-{unit_slug}"
BLOCK_COUNTER_MAX = 3  # Escalate after this many consecutive BLOCKEDs.


class BlockCounter:
    """Read/write helper for the per-unit-slug Skeptic-BLOCKED counter file.

    The counter lives at <counter_dir>/<slug_filename>. The conductor
    creates or increments it on each skeptic_blocked_input return, and
    resets it (by deleting the file) on Skeptic sign-off.

    Usage:
        counter = BlockCounter("my-feature", Path(".agentic"))
        result = counter.increment()  # "ok" | "escalate"
        count = counter.read()        # int, 0 if file absent
        counter.reset()               # delete the counter file
    """

    def __init__(self, unit_slug: str, counter_dir: Path) -> None:
        self.unit_slug = unit_slug
        self._path = counter_dir / f".spawn-block-counter-{unit_slug}"

    def read(self) -> int:
        """Return current counter value; 0 if file absent or unreadable."""
        try:
            return int(self._path.read_text().strip())
        except (OSError, ValueError):
            return 0

    def increment(self) -> str:
        """Increment counter by 1; return 'escalate' if count >= BLOCK_COUNTER_MAX, else 'ok'.

        Writes the new count atomically (overwrite-in-place for simplicity;
        single-threaded conductor context so no locking needed).
        """
        new_count = self.read() + 1
        self._path.write_text(str(new_count))
        if new_count >= BLOCK_COUNTER_MAX:
            return "escalate"
        return "ok"

    def reset(self) -> None:
        """Delete the counter file, resetting count to 0."""
        try:
            self._path.unlink()
        except OSError:
            pass  # Already absent; that's fine.

# ---------------------------------------------------------------------------
# S4 - Plan-tier overflow detection
# ---------------------------------------------------------------------------

# Token threshold at which the conductor switches from single combined Skeptic
# to per-unit Skeptics + lightweight integration Skeptic.
PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS = 60_000

# Context heading constants
GLOBAL_CONTEXT_HEADING = "## Global-context inputs"
SUPPLEMENTAL_CONTEXT_HEADING = "## Supplemental context"

# Required fields for a supplemental-context block (used by security-auditor
# and perf-analyst in multi-dim fan-out).
_SUPPLEMENTAL_BLOCK_REQUIRED_FIELDS = frozenset(["diff", "ticket_id"])


def should_overflow_to_supplemental(token_count: int) -> bool:
    """Return True when combined Global-context input set is >= threshold tokens.

    When True, the conductor must switch to per-unit Skeptics plus a
    lightweight integration Skeptic that receives findings-list only.

    Args:
        token_count: Estimated total token count of the combined Global-context
            input set (brief + architect plan + diff + all context).

    Returns:
        True if token_count >= PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS.
    """
    return token_count >= PLAN_TIER_OVERFLOW_THRESHOLD_TOKENS


def validate_supplemental_block(block: dict) -> tuple[bool, str]:
    """Validate the shape of a supplemental-context block.

    A valid supplemental block must contain at minimum the required fields
    defined in _SUPPLEMENTAL_BLOCK_REQUIRED_FIELDS. Additional fields are
    permitted.

    Args:
        block: The supplemental-context dict to validate.

    Returns:
        (True, "") on valid shape.
        (False, reason_string) on invalid shape.
    """
    if not isinstance(block, dict):
        return False, f"supplemental block must be a dict, got {type(block).__name__}"
    missing = _SUPPLEMENTAL_BLOCK_REQUIRED_FIELDS - set(block.keys())
    if missing:
        return False, f"supplemental block missing required fields: {sorted(missing)}"
    return True, ""
