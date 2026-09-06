"""DS-202 - merge-time tracker writeback spec pins.

Purpose: Pin the shipped prose that makes an agent-performed `gh pr merge` fire the
         dev-complete transition immediately, instead of deferring it to the
         session-start `--pending-merge` sweep. Covers both flag-enumeration sites in
         `/ds-ticket-status-sync`, the single canonical rule paragraph in
         `content/rules/conventions.md` § Git Workflow, the pointer-not-copy discipline
         in `content/references/conventions-detail.md`, and BOTH `/ds-implement-ticket`
         Phase 12 sites (the bash echo and the prose Note).

Public API: pytest test module - auto-discovered by `pytest bin/tests/`.

Upstream deps: content/commands/ds-ticket-status-sync.md;
               content/rules/conventions.md;
               content/references/conventions-detail.md;
               content/commands/ds-implement-ticket.md;
               bin/tests/lib/resident_rule_extract.py (shared
               resident-rule/detail-section extraction, round 7 - extracted
               here from byte-identical inline logic once duplicated with
               bin/tests/test_auto_merge_followthrough_resident_spec.py).

Downstream consumers: the `bin-tests` CI job.

Failure modes: Prose pins. A rewrite that preserves meaning but changes wording reddens
               these; that is intended - the wording is the interface here. This module
               deliberately asserts NOTHING about `$TRACKER_STATE_DONE` being written,
               because AE must never write that value at any site.

Performance: Four file reads, pure string work. Sub-millisecond.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.resident_rule_extract import detail_section, resident_rule  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

STATUS_SYNC_PATH = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
IMPLEMENT_TICKET_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
CONVENTIONS_PATH = REPO_ROOT / "content" / "rules" / "conventions.md"
CONVENTIONS_DETAIL_PATH = (
    REPO_ROOT / "content" / "references" / "conventions-detail.md"
)


def _status_sync() -> str:
    return STATUS_SYNC_PATH.read_text(encoding="utf-8")


def _implement_ticket() -> str:
    return IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")


def _manifest_block(text: str) -> str:
    """The leading <!-- ... --> module manifest of a content/ markdown file."""
    start = text.index("<!--")
    end = text.index("-->", start)
    return text[start:end]


def _public_api_block(text: str) -> str:
    """The manifest's `Public API:` field only - NOT the whole manifest.

    Scoping matters: the manifest's `Purpose:` and `Downstream consumers:` fields
    also name `--pr <PR_NUMBER>` and `--no-confirm`, so a whole-manifest substring
    check passes even after the Public API enumeration entry is deleted. Measured:
    that exact mutation ran green against the unscoped form.
    """
    manifest = _manifest_block(text)
    start = manifest.index("Public API:")
    end = manifest.index("Upstream deps:", start)
    return manifest[start:end]


def _invocation_section(text: str) -> str:
    start = text.index("## Invocation")
    end = text.index("## Preflight", start)
    return text[start:end]


def _invocation_bullets(text: str) -> list:
    return [
        ln for ln in _invocation_section(text).splitlines() if ln.startswith("- ")
    ]


# ---------------------------------------------------------------------------
# A1 - both flags documented at BOTH enumeration sites.
# ---------------------------------------------------------------------------

def test_manifest_public_api_documents_both_new_flags():
    """Reddening mutation: delete either new `Public API:` entry from the manifest.

    Verified reddening: deleting only the `--pr <PR_NUMBER>` entry fails here.
    """
    api = _public_api_block(_status_sync())
    assert "/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER>" in api
    assert "/ds-ticket-status-sync <TICKET_ID> --no-confirm" in api


def test_invocation_section_documents_both_new_flags():
    """Reddening mutation: delete either new bullet from the `## Invocation` list.

    Asserted per-bullet, not as a bare substring over the section: the `--force`
    bullet also names `--no-confirm`, so a section-wide substring check survives
    deletion of the `--no-confirm` bullet. Measured: that mutation ran green
    against the substring form.
    """
    bullets = _invocation_bullets(_status_sync())
    assert any(
        b.startswith("- `/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER>`")
        for b in bullets
    ), bullets
    assert any(
        b.startswith("- `/ds-ticket-status-sync <TICKET_ID> --no-confirm`")
        for b in bullets
    ), bullets


def test_both_enumeration_sites_scope_new_flags_to_single_ticket_mode():
    """Reddening mutation: drop the `single-ticket mode only` qualifier, or the
    no-op-under-other-modes qualifier, from EITHER site's own entries.

    Both sites must independently carry the scope; documenting it at one site
    leaves the other stale, which is the exact defect this pair exists to catch.
    Each site is sliced to its own new entries so an adjacent unrelated mention
    of the same flag cannot satisfy the assertion.
    """
    text = _status_sync()

    api = _public_api_block(text)
    api_entries = api[api.index("/ds-ticket-status-sync <TICKET_ID> --pr"):]
    # The manifest hard-wraps its entries, so normalize whitespace before
    # counting - otherwise a wrapped phrase silently fails to match.
    api_flat = " ".join(api_entries.split())
    assert api_flat.lower().count("single-ticket mode only") == 2, api_flat
    assert api_flat.count("no-op when passed with --all or --pending-merge") == 2, (
        api_flat
    )

    new_bullets = [
        b
        for b in _invocation_bullets(text)
        if b.startswith("- `/ds-ticket-status-sync <TICKET_ID> --")
    ]
    assert len(new_bullets) == 2, new_bullets
    for bullet in new_bullets:
        assert "**single-ticket mode only.**" in bullet, bullet
        assert "**silent no-op**" in bullet, bullet
        assert "`--all`" in bullet and "`--pending-merge`" in bullet, bullet


# ---------------------------------------------------------------------------
# A2 - `--pr` precedence over a folded tasks.jsonl pr_number.
# ---------------------------------------------------------------------------

def test_pr_flag_takes_precedence_over_recorded_pr_number():
    """Reddening mutation: delete the precedence sentence from step 1."""
    text = _status_sync()
    assert "takes precedence over any `pr_number` the fold recorded" in text
    assert "--pr <N> overrides recorded pr_number <M>" in text


def test_step_1_still_says_task_state_is_optional():
    """Reddening mutation: delete or reword the pre-existing optionality sentence.

    A2 is additive-only: the existing task-state-is-optional guarantee must survive.
    """
    assert (
        "Task-state is an optimization, not a requirement, for single-ticket mode."
        in _status_sync()
    )


# ---------------------------------------------------------------------------
# A3 - confirmation still required absent --no-confirm.
# ---------------------------------------------------------------------------

def test_step_6_still_requires_confirmation_without_the_flag():
    """Reddening mutation: replace the exception clause with an unconditional
    `single-ticket mode no longer prompts`, or delete the `[y/N]` prompt string."""
    text = _status_sync()
    assert (
        "Transition <TICKET_ID> from '<current>' to '<expected>'? [y/N]" in text
    )
    assert (
        "Absent `--no-confirm`, confirmation remains required in single-ticket mode"
        in text
    )


def test_no_confirm_waives_only_the_prompt_not_the_guard():
    """Reddening mutation: delete the clause preserving the step-5 forward-only guard."""
    assert (
        "the forward-only guard in step 5 still applies unchanged" in _status_sync()
    )


# ---------------------------------------------------------------------------
# A6 - --force and --no-confirm are distinct, not aliases.
# ---------------------------------------------------------------------------

def test_force_and_no_confirm_are_documented_as_distinct():
    """Reddening mutation: delete the distinction sentence, or repurpose `--force`
    as the single-ticket bypass (which would drop the reserved-alias wording)."""
    text = _status_sync()
    assert (
        "`--force` remains the reserved `--all` confirmation-bypass alias and is "
        "unrelated to `--no-confirm`, which is single-ticket only"
        in text
    )
    assert "neither flag is an alias, a synonym, or a replacement for the other" in text


# ---------------------------------------------------------------------------
# A7 - step 3 skips when no branch name is known.
# ---------------------------------------------------------------------------

def test_step_3_guards_the_no_branch_path():
    """Reddening mutation: delete the skip sentence, so `git log origin/<branch>`
    is left with no defined operand on the `--pr`-only path."""
    text = _status_sync()
    assert "**Skip this step entirely when no branch name is known**" in text
    assert "The `gh pr view <N>` result from step 2 alone is sufficient" in text


def test_step_3_guard_does_not_reintroduce_branch_name_identity():
    """Reddening mutation: replace the guard with a `derive the branch from the
    ticket ID / headRefName` fallback - forbidden by the identity-source rule."""
    assert (
        "never substitutes a ticket-ID-derived or `headRefName`-derived branch name"
        in _status_sync()
    )


# ---------------------------------------------------------------------------
# A8 - the manifest no longer claims "no programmatic consumers".
# ---------------------------------------------------------------------------

def test_manifest_no_longer_claims_no_programmatic_consumers():
    """Reddening mutation: restore the original
    `single-ticket and --all modes remain operator-invoked only; no programmatic
    consumers.` sentence."""
    manifest = _manifest_block(_status_sync())
    assert "no programmatic consumers" not in manifest
    assert (
        "single-ticket and --all modes remain operator-invoked only" not in manifest
    )
    assert "auto-invoked" in manifest
    assert "--all remains operator-invoked only." in manifest


# ---------------------------------------------------------------------------
# A5 - the --pending-merge sweep is documented as a backstop, and its stale
# "Phase 9 auto-merge branch" reference is corrected to Phase 12.
# ---------------------------------------------------------------------------

def test_pending_merge_purpose_names_itself_a_backstop():
    """Reddening mutation: delete the appended backstop paragraph."""
    text = _status_sync()
    assert "This sweep is the **backstop**, not the primary path" in text
    assert "a merge AE did not itself perform" in text
    assert "the ticket ID or the PR number was unknown at merge time" in text


def test_pending_merge_purpose_cites_phase_12_not_phase_9():
    """Reddening mutation: revert `Phase 12 auto-merge branch` to `Phase 9`."""
    text = _status_sync()
    assert "only via its Phase 12 auto-merge branch" in text
    assert "only via its Phase 9 auto-merge branch" not in text


# ---------------------------------------------------------------------------
# B1/B2 - the rule is ONE rule split across two load tiers.
#
# The resident tier (content/rules/conventions.md § Git Workflow) is embedded
# verbatim into the generated .claude/skills/dinostack/SKILL.md and is therefore
# charged against scripts/check-skill-embed-budget.sh's CEILING. The full-text
# tier (content/references/conventions-detail.md) is trigger-loaded and is NOT
# embedded. Measured on this branch: the full 1,005 B rule in the resident tier
# put SKILL.md 445 B ABOVE CEILING, with only 560 B of headroom available on
# origin/main. That is why the split exists, and why the size cap below is a
# real assertion rather than style policing.
#
# RESIDENT_RULE_MAX_BYTES is a ceiling on this one paragraph, independent of the
# whole-artifact gate. It ratchets DOWNWARD like every other budget in this repo.
# ---------------------------------------------------------------------------

RESIDENT_RULE_MAX_BYTES = 350

RESIDENT_LABEL = "**Merge-time tracker writeback.**"
DETAIL_HEADING = "## Merge-Time Tracker Writeback"


def _resident_rule() -> str:
    return resident_rule(CONVENTIONS_PATH, RESIDENT_LABEL)


def _detail_section() -> str:
    return detail_section(CONVENTIONS_DETAIL_PATH, DETAIL_HEADING)


def test_resident_rule_carries_the_four_resident_tier_clauses():
    """Reddening mutation: delete any one of the four clauses from the resident
    rule - the trigger, the exact invocation, the `--auto` carve-out, or the
    pointer. Each is asserted separately, so no single deletion passes."""
    rule = _resident_rule()
    # 1. Trigger.
    assert "`gh pr merge` exiting 0 outside" in rule
    assert "Phase 12 auto-merge" in rule
    # 2. Exact invocation.
    assert (
        "`/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER> --no-confirm`" in rule
    )
    # 3. --auto carve-out.
    assert "`--auto` exiting 0 means QUEUED, not merged, and does not fire it" in rule
    # 4. Pointer to the full rule.
    assert "`content/references/conventions-detail.md`" in rule
    assert DETAIL_HEADING.removeprefix("## ") in rule


def test_resident_rule_stays_within_its_byte_ceiling():
    """Reddening mutation: paste the full rule text back into § Git Workflow.

    That is the exact regression this guards - it is what put the generated
    SKILL.md 445 B above the skill-embed CEILING on this branch's first attempt.
    """
    size = len(_resident_rule().encode("utf-8")) + 2  # + blank-line separator
    assert size <= RESIDENT_RULE_MAX_BYTES, (
        f"resident rule is {size} B, over the {RESIDENT_RULE_MAX_BYTES} B ceiling; "
        "move detail into content/references/conventions-detail.md rather than "
        "raising this number"
    )


def test_detail_holds_the_full_rule_not_a_pointer():
    """Reddening mutation: replace the detail section with a one-sentence pointer
    back to conventions.md - every clause below would then live nowhere."""
    section = _detail_section()
    assert (
        "immediately run `/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER> "
        "--no-confirm`"
        in section
    )


def test_detail_carries_the_auto_is_not_merged_carve_out():
    """Reddening mutation: delete the `--auto` sentence from the detail section -
    the full rule would then permit firing on a merge that was only QUEUED."""
    assert (
        "A `gh pr merge --auto` call exiting 0 means QUEUED, not merged, and does "
        "NOT trigger this rule."
        in _detail_section()
    )


def test_detail_carries_the_phase_12_exclusion():
    """Reddening mutation: delete the Phase 12 exclusion - W7 would then double-fire."""
    section = _detail_section()
    assert "outside** `/ds-implement-ticket` Phase 12's auto-merge block" in section
    assert "MUST NOT also fire this rule" in section


def test_detail_carries_the_unknown_operand_backstop():
    """Reddening mutation: delete the unknown-operand sentence - the rule would
    then be silent on what happens when the ticket ID or PR number is missing."""
    section = _detail_section()
    assert "If either the ticket ID or the PR number is unknown, do nothing here" in section
    assert "the automatic backstop is the session-start `--pending-merge` sweep" in section


def test_detail_is_soft_fail_and_no_op_without_a_tracker():
    """Reddening mutation: delete the soft-fail sentence, making a tracker outage
    able to block the merge."""
    section = _detail_section()
    assert "never blocks the merge or any following step" in section
    assert "`TRACKER == none` is a silent no-op." in section


def test_detail_does_not_change_the_target_state():
    """Reddening mutation: change the stated target to the terminal Done state.

    AE never writes `TRACKER_STATE_DONE`; this pin exists so a future edit cannot
    quietly retarget the merge-time path at it.
    """
    section = _detail_section()
    assert "the transition target is still `$TRACKER_STATE_DEV_COMPLETE`" in section
    assert (
        "AE still never writes the terminal `TRACKER_STATE_DONE` at any site"
        in section
    )


def test_no_normative_clause_was_dropped_in_the_split():
    """Reddening mutation: delete any clause from the detail section without
    moving it into the resident rule.

    The split was a relocation, not a reduction. Every clause of the original
    single-paragraph rule must be present in exactly one of the two tiers.
    """
    combined = _resident_rule() + "\n" + _detail_section()
    for clause in (
        "Phase 12",                       # trigger scope
        "--pr <PR_NUMBER> --no-confirm",  # exact invocation
        "QUEUED, not merged",             # --auto carve-out
        "MUST NOT also fire this rule",   # W7 double-fire exclusion
        "is unknown, do nothing here",    # unknown-operand behavior
        "--pending-merge` sweep",         # backstop
        "remains available on operator invocation",   # --all escape hatch
        "never blocks the merge",         # soft-fail
        "`TRACKER == none` is a silent no-op",        # no-tracker no-op
        "$TRACKER_STATE_DEV_COMPLETE",    # unchanged target
        "terminal `TRACKER_STATE_DONE`",  # never-written terminal state
    ):
        assert clause in combined, f"clause lost in the split: {clause!r}"


def test_resident_label_appears_exactly_once_across_content():
    """Reddening mutation: paste a second copy of the bolded rule label into
    another content/ file - two rule-statements drift silently."""
    hits = [
        p
        for p in (REPO_ROOT / "content").rglob("*.md")
        if RESIDENT_LABEL in p.read_text(encoding="utf-8")
    ]
    assert hits == [CONVENTIONS_PATH], hits


def test_the_two_tiers_point_at_each_other():
    """Reddening mutation: delete either direction of the cross-reference - a
    reader landing on one tier would not learn the other exists."""
    assert "`content/references/conventions-detail.md`" in _resident_rule()
    section = _detail_section()
    assert "content/rules/conventions.md` §Git Workflow" in section
    assert "one rule split by load tier" in section


# ---------------------------------------------------------------------------
# B3/B4 - BOTH Phase 12 sites. Asserting one offset only is the exact defect
# this pair exists to catch, so each site is located independently and checked
# on its own.
# ---------------------------------------------------------------------------

_ECHO_MARKER = "the dev-complete transition is pushed automatically by the session-start pending-merge sweep within one session boot of the merge"
_NOTE_MARKER = "the dev-complete transition is pushed automatically by the session-start pending-merge sweep instead"


def _site_window(text: str, marker: str) -> str:
    """The full line (echo statement or prose Note) containing `marker`."""
    idx = text.index(marker)
    start = text.rfind("\n", 0, idx) + 1
    end = text.index("\n", idx)
    return text[start:end]


def test_both_phase_12_sites_are_present_and_distinct():
    """Reddening mutation: delete either site, or collapse them into one."""
    text = _implement_ticket()
    assert text.count(_ECHO_MARKER) == 1
    assert text.count(_NOTE_MARKER) == 1
    assert text.index(_ECHO_MARKER) != text.index(_NOTE_MARKER)


def test_both_phase_12_sites_carry_the_merge_time_exception():
    """Reddening mutation: remove the exception clause from EITHER site - the
    surviving one would still promise an unconditional deferral."""
    text = _implement_ticket()
    for marker, name in ((_ECHO_MARKER, "echo"), (_NOTE_MARKER, "Note")):
        window = _site_window(text, marker)
        assert "outside this auto-merge block" in window, name
        assert "fires immediately at merge time" in window, name


def test_both_phase_12_sites_point_at_git_workflow_for_the_new_rule():
    """Reddening mutation: change either site's new pointer to
    `§Session Context and Memory` - the wrong section for this rule."""
    text = _implement_ticket()
    for marker, name in ((_ECHO_MARKER, "echo"), (_NOTE_MARKER, "Note")):
        window = _site_window(text, marker)
        head = window[:window.index(marker)]
        assert "§Git Workflow" in head, name


def test_both_phase_12_sites_narrow_the_rework_detection_claim():
    """Reddening mutation: restore either site's unconditional
    `there are no candidates and no automatic dev-complete transition` wording.

    That claim went false with this change: the merge-time rule never consults
    the ledger and fires regardless of `rework_detection`.
    """
    text = _implement_ticket()
    for marker, name in ((_ECHO_MARKER, "echo"), (_NOTE_MARKER, "Note")):
        window = _site_window(text, marker)
        assert "rework_detection" in window, name
        assert "never consults the ledger" in window, name
        assert (
            "the agent did not perform itself" in window
            or "a merge the agent did not perform itself" in window
        ), name


def test_both_phase_12_sites_retain_their_pinned_substrings():
    """Reddening mutation: rewrite either site's deferral sentence - which is also
    what `test_no_shipped_prose_promises_an_automatic_terminal_done` guards.

    Restated here so this module fails on its own if a DS-202 edit ever becomes a
    rewrite rather than an append.
    """
    text = _implement_ticket()
    assert _ECHO_MARKER in text
    assert _NOTE_MARKER in text
    assert (
        "the Done transition is pushed automatically by the session-start "
        "pending-merge sweep" not in text
    )
