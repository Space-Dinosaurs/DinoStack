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
               content/references/conventions-detail.md.

Downstream consumers: the `bin-tests` CI job.

Failure modes: Prose pins. A rewrite that preserves meaning but changes
               wording reddens these; that is intended - the wording is the
               interface here.

Performance: Two file reads, pure string work. Sub-millisecond.
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

CONVENTIONS_PATH = REPO_ROOT / "content" / "rules" / "conventions.md"
CONVENTIONS_DETAIL_PATH = (
    REPO_ROOT / "content" / "references" / "conventions-detail.md"
)

# RESIDENT_RULE_MAX_BYTES is a ceiling on this one paragraph, independent of
# the whole-artifact skill-embed gate. It ratchets DOWNWARD like every other
# budget in this repo. Current measured size is 1542 B; this leaves ~10%
# headroom for a genuinely necessary correction without silently blowing the
# skill-embed ceiling one clause at a time.
RESIDENT_RULE_MAX_BYTES = 1700

RESIDENT_LABEL = "**Auto-merge follow-through.**"
DETAIL_HEADING = "## Auto-merge follow-through"


def _resident_rule() -> str:
    text = CONVENTIONS_PATH.read_text(encoding="utf-8")
    idx = text.index(RESIDENT_LABEL)
    return text[idx : text.index("\n\n", idx)]


def _detail_section() -> str:
    text = CONVENTIONS_DETAIL_PATH.read_text(encoding="utf-8")
    start = text.index(DETAIL_HEADING)
    end = text.index("\n## ", start + len(DETAIL_HEADING))
    return text[start:end]


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
    # 3. Re-draft-on-failure compensation (round-6 Minor).
    assert "`gh pr ready --undo`" in rule
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
    assert "Phase 12" in section and "Phase 10" in section
    assert "### Phase 10 timeout call site" in section
    assert "@harness:phase10-timeout-auto-merge-queue" in section
