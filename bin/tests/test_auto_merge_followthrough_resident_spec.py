"""Round-6 Skeptic Major 2 - resident-rule regression pin for the
Auto-merge follow-through rule.

Purpose: Pin the shipped prose of the "Auto-merge follow-through" resident
         rule in content/rules/conventions.md § Git Workflow, and confirm
         content/references/conventions-detail.md still carries the full
         mechanism rather than a bare pointer. This defect (a subtraction
         pass silently deleting a normative resident clause) already
         happened once inside this same unit - round 4's "subtract surface"
         instruction deleted the ad-hoc-actionable instruction entirely,
         costing a full Critical round to restore. Follows the template at
         bin/tests/test_merge_time_writeback_spec.py (the adjacent resident
         rule in the same § Git Workflow section of the same file):
         test_resident_rule_carries_the_four_resident_tier_clauses,
         test_resident_rule_stays_within_its_byte_ceiling, and
         test_detail_holds_the_full_rule_not_a_pointer.

Public API: pytest test module - auto-discovered by `pytest bin/tests/`.

Upstream deps: content/rules/conventions.md;
               content/references/conventions-detail.md;
               bin/tests/lib/resident_rule_extract.py (shared
               resident-rule/detail-section extraction, round 7 - also used
               by bin/tests/test_merge_time_writeback_spec.py).

Downstream consumers: the `bin-tests` CI job.

Failure modes: Prose pins. A rewrite that preserves meaning but changes
               wording reddens these; that is intended - the wording is the
               interface here.

Performance: Two file reads, pure string work. Sub-millisecond.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.resident_rule_extract import detail_section, resident_rule  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

CONVENTIONS_PATH = REPO_ROOT / "content" / "rules" / "conventions.md"
CONVENTIONS_DETAIL_PATH = (
    REPO_ROOT / "content" / "references" / "conventions-detail.md"
)

# RESIDENT_RULE_MAX_BYTES is a ceiling on the COMPARED quantity in
# test_resident_rule_stays_within_its_byte_ceiling - the rule paragraph's own
# UTF-8 byte length PLUS the +2 blank-line separator that test adds before
# comparing - not the bare paragraph length alone (round-7 Skeptic Minor 2:
# an earlier version of this comment cited the bare paragraph length, making
# a reader's headroom computation off by 2; budget-provenance comments in
# this repo have been found false three separate times, so this one names
# the exact quantity compared rather than a derived one). Independent of the
# whole-artifact skill-embed gate; ratchets DOWNWARD like every other budget
# in this repo. Re-derive with the test itself rather than trusting a cited
# figure.
RESIDENT_RULE_MAX_BYTES = 900

RESIDENT_LABEL = "**Auto-merge follow-through.**"
DETAIL_HEADING = "## Auto-merge follow-through"


def _resident_rule() -> str:
    return resident_rule(CONVENTIONS_PATH, RESIDENT_LABEL)


def _detail_section() -> str:
    return detail_section(CONVENTIONS_DETAIL_PATH, DETAIL_HEADING)


def test_resident_rule_carries_the_five_resident_tier_clauses():
    """Reddening mutation: delete any one of the five clauses from the
    resident rule - the ad-hoc-actionable instruction, the exact invocation,
    the re-draft-on-failure compensation, the QUEUED-not-merged distinction,
    or the honest-report obligation. Each is asserted separately, so no
    single deletion passes. This is the exact defect class round 4's Critical
    was: the instruction clause was deleted entirely while the three named
    call sites remained, leaving an ad-hoc session with nothing to follow."""
    rule = _resident_rule()
    # 1. Ad-hoc-actionable instruction (round-4 Critical: this exact clause
    #    was the one silently deleted).
    assert "IT un-drafts the PR if needed and queues" in rule
    assert "ad-hoc" in rule
    assert "gated on a particular command" in rule
    # 2. Exact invocation.
    assert "`gh pr merge <N> --squash --delete-branch --auto`" in rule
    # 3. Re-draft-on-failure compensation (round-6 Minor), CONDITIONAL on
    #    self-performed un-draft (round-7 Major 1 - commit 2841cf92's
    #    unconditional-undo defect relocated into this prose; an unqualified
    #    "re-draft on queue failure" instructs re-drafting a PR the operator
    #    had already marked ready, since the ad-hoc path has no code and
    #    this sentence is its entire specification).
    assert "`gh pr ready --undo`" in rule
    assert "ONLY IF IT performed that un-draft itself" in rule
    assert "never touching a PR the operator had already marked ready" in rule
    assert "Allow auto-merge" in rule
    # 4. QUEUED-not-merged distinction.
    assert "QUEUED, not merged" in rule
    # 5. Honest-report obligation.
    assert "a turn must state the PR's real state" in rule
    # 6. Pointer to the full rule.
    assert "`content/references/conventions-detail.md`" in rule
    assert DETAIL_HEADING.removeprefix("## ") in rule


def test_resident_rule_stays_within_its_byte_ceiling():
    """Reddening mutation: paste the full three-mechanism enumeration (the
    numbered list in conventions-detail.md's "The trigger is the event, not
    a command" paragraph) back into this resident paragraph."""
    size = len(_resident_rule().encode("utf-8")) + 2  # + blank-line separator
    assert size <= RESIDENT_RULE_MAX_BYTES, (
        f"resident rule is {size} B, over the {RESIDENT_RULE_MAX_BYTES} B "
        "ceiling; move detail into content/references/conventions-detail.md "
        "rather than raising this number"
    )


def test_detail_holds_the_full_rule_not_a_pointer():
    """Reddening mutation: replace the detail section with a one-sentence
    pointer back to conventions.md - the three-mechanism enumeration, the
    Phase 10 timeout procedure, and the sibling-PR sweep detail would then
    live nowhere."""
    section = _detail_section()
    assert "IT un-drafts the PR if needed and queues" in section
    assert "`gh pr ready --undo`" in section
    assert "ONLY IF IT performed that un-draft itself" in section
    assert "Phase 12" in section and "Phase 10" in section
    assert "### Phase 10 timeout call site" in section
    assert "@harness:phase10-timeout-auto-merge-queue" in section
