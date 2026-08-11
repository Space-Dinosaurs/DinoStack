#!/usr/bin/env python3
"""
Spec tests for the tracker-lifecycle site relocation (W1 into Phase 1) and
the --pending-merge sweep addition.

Tracker-free: every assertion here reads static repo files only - no
network calls, no live tracker state, no dependency on TRACKER != none.
This repo resolves TRACKER=none, so any tracker-dependent assertion would
be untestable here by construction.

Covers:
  - content/commands/ds-implement-ticket.md:
      * exactly one `site: W1` occurrence, located inside Phase 1 (between
        the `## Phase 1:` and `## Phase 2:` headings).
      * ordering invariant across the four tracker-writeback site markers:
        W1 < W2 < W3 < W7 by byte offset.
      * zero occurrences of `path: trivial` (the deleted Trivial-path W1
        fire site).
      * the W1 subsection carries the accept-regex guard AND an explicit
        citation of the pre-existing Phase 0 regex site, rather than
        restating the regex as a fresh, driftable literal.
  - content/commands/ds-ticket-status-sync.md:
      * `--pending-merge` mode exists.
      * the pending-merge section states no-prompting and the 60-minute
        throttle.
      * the two-tracker-writeback-spawn-sites invariant still holds
        (unchanged by this unit - regression guard).
      * the pending-merge section names `.agentic/ticket-ledger.jsonl` as
        its sole candidate/identity source, and does NOT reintroduce
        title/branch-text matching as an identity signal (regression guard
        against a previously-rejected design - see the "Why the ledger is
        the identity source" prose in that section).
      * the pending-merge section defines an unconditional end-of-sweep
        cursor advance and an attempts cap.
  - content/rules/conventions.md:
      * the pending-merge sweep pointer is present, and the sweep is
        explicitly excluded from the stacked first-user-turn notice count.
  - the `pending_merge_sweep` toggle is registered on the template and
    across all eight documented enumeration surfaces.
  - the changed Phase 1 W1 block is byte-identical across adapter copies
    of content/commands/ds-implement-ticket.md (excluding the .pi stub,
    which is a 7-line pointer with no such block).
  - content/commands/ds-init-project.md Step 9 gitignore block:
      * `.agentic/tracker.yml` sits between the `.agentic/compression-state.json`
        and `.agentic/tracker-states.json` anchor lines inside the ignore-pattern
        run, and NOT under the `# Tracked (explicitly NOT ignored):` comment
        block - this is the consumer-protection line added ahead of the
        `.agentic/tracker.yml` overlay file landing in a later PR (DS-74).
        Placed under the tracked-comment block, it would read as though
        `tracker.yml` were one of the tracked files instead of ignored.
      * the Step 9 enumeration paragraph names `tracker.yml` explicitly
        (`per-operator local tracker config; never committed`), not just the
        updated count.
      * the count word in that paragraph ("sixteen") matches the number of
        ignore-pattern lines the paragraph is counting.

Run with: python3 -m pytest bin/tests/test_tracker_lifecycle_sites_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

IMPLEMENT_TICKET_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
STATUS_SYNC_PATH = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
CONVENTIONS_PATH = REPO_ROOT / "content" / "rules" / "conventions.md"
INIT_PROJECT_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"
WRAP_PATH = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
TICKET_TRIAGE_PATH = REPO_ROOT / "content" / "commands" / "ds-ticket-triage.md"
CONFIG_CMD_PATH = REPO_ROOT / "content" / "commands" / "ds-config.md"

# The four entry points that must disclose the .agentic/tracker.yml overlay
# source (prose row 4 - DS-74 PR2).
TRACKER_DISCLOSURE_ENTRY_POINTS = [
    IMPLEMENT_TICKET_PATH,
    STATUS_SYNC_PATH,
    WRAP_PATH,
    TICKET_TRIAGE_PATH,
]

# All adapter copies expected to carry a byte-identical extraction of the
# "### Tracker writeback (W1)" subsection. .pi/prompts/ds-implement-ticket.md
# is deliberately excluded - it is a 7-line pointer stub with no such block
# (see bin/tests/test_tracker_writeback_ranking_spec.py ADAPTER_PATHS for the
# precedent this list follows).
ADAPTER_PATHS = [
    IMPLEMENT_TICKET_PATH,
    REPO_ROOT / ".claude" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".codex" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".cursor" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".opencode" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".github" / "prompts" / "ds-implement-ticket.prompt.md",
    REPO_ROOT / ".openclaw" / "skills" / "ds-implement-ticket" / "SKILL.md",
    REPO_ROOT / ".gemini" / "commands" / "ds-implement-ticket.toml",
    REPO_ROOT / ".hermes" / "SKILL.md",
]

W1_HEADING = "### Tracker writeback (W1)"

# Eight documented enumeration surfaces for the pending_merge_sweep toggle.
TOGGLE_SURFACES = [
    REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
    REPO_ROOT / "content" / "references" / "conventions-detail.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "components.md",
    REPO_ROOT / "docs" / "configuration-reference.md",
    REPO_ROOT / "content" / "templates" / ".agentic" / "config.json",
    REPO_ROOT / "content" / "commands" / "ds-init-project.md",
    REPO_ROOT / "content" / "commands" / "ds-config.md",
]


def _extract_subsection(text: str, heading: str) -> str:
    """Extract a subsection: from the exact heading line up to (exclusive)
    the next line that is itself a '## ' or '### ' heading. Matches on an
    exact-stripped heading line so inline backtick mentions elsewhere (e.g.
    in a fused multi-command embed like .hermes/SKILL.md) are not mistaken
    for the heading itself."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        raise AssertionError(f"heading {heading!r} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            end = j
            break
    return "\n".join(lines[start:end])


def _extract_w1_block(text: str) -> str:
    """Extract the '### Tracker writeback (W1)' subsection. See
    _extract_subsection for the extraction rule."""
    return _extract_subsection(text, W1_HEADING)


def _section(text: str, heading: str) -> str:
    """Extract a top-level '## <heading>' section up to the next '## '
    heading (or EOF). Matches on a line that, once stripped, is exactly
    the given heading text (so partial-heading collisions do not occur)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        raise AssertionError(f"heading {heading!r} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def implement_ticket_text() -> str:
    return IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def status_sync_text() -> str:
    return STATUS_SYNC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def w1_block(implement_ticket_text) -> str:
    return _extract_w1_block(implement_ticket_text)


@pytest.fixture(scope="module")
def per_ticket_reset_block(implement_ticket_text) -> str:
    return _extract_subsection(
        implement_ticket_text,
        "### Per-ticket variable reset (binding, runs FIRST on every entry)",
    )


@pytest.fixture(scope="module")
def pending_merge_section(status_sync_text) -> str:
    return _section(status_sync_text, "## Pending-merge sweep (--pending-merge mode)")


# ---------------------------------------------------------------------------
# content/commands/ds-implement-ticket.md: W1 relocation
# ---------------------------------------------------------------------------

def test_exactly_one_site_w1_occurrence(implement_ticket_text):
    occurrences = re.findall(r"site: W1\b", implement_ticket_text)
    assert len(occurrences) == 1, (
        f"expected exactly one 'site: W1' occurrence, found {len(occurrences)}"
    )


def test_site_w1_lies_within_phase_1(implement_ticket_text):
    phase1_idx = implement_ticket_text.index("## Phase 1:")
    phase2_idx = implement_ticket_text.index("## Phase 2:")
    assert phase1_idx < phase2_idx, "Phase 1 heading must precede Phase 2 heading"
    w1_idx = implement_ticket_text.index("site: W1")
    assert phase1_idx < w1_idx < phase2_idx, (
        "'site: W1' must lie strictly between the Phase 1 and Phase 2 headings"
    )


def test_tracker_writeback_site_ordering(implement_ticket_text):
    text = implement_ticket_text
    w1_idx = text.index("site: W1")
    w2_idx = text.index("site: W2")
    w3_idx = text.index("site: W3")
    # W7 appears twice: once inside a commented-out example block, once at
    # the real Phase 12 fire site. Use the LAST occurrence - the real,
    # active fire site - so a comment block placed earlier in the file
    # cannot mask an actual ordering regression at the real site.
    w7_idx = text.rindex("site: W7")
    assert w1_idx < w2_idx < w3_idx < w7_idx, (
        f"expected offset ordering W1({w1_idx}) < W2({w2_idx}) < W3({w3_idx}) "
        f"< W7({w7_idx})"
    )


def test_no_path_trivial_fire_site_remains(implement_ticket_text):
    assert "path: trivial" not in implement_ticket_text, (
        "the deleted Trivial-path W1 fire site ('path: trivial') must not "
        "reappear anywhere in the file"
    )


def test_w1_subsection_has_guard_and_cites_phase_0_regex_site(w1_block):
    # The accept-regex literal itself must be present as the guard.
    assert "^[A-Z][A-Z0-9_]+-\\d+$" in w1_block, (
        "W1 subsection is missing the bare-ticket-ID accept-regex guard"
    )
    # It must be an explicit citation of the pre-existing Phase 0 site, not
    # a bare restatement with no cross-reference - this is what stops a
    # future edit to one copy from silently drifting from the other.
    assert "Phase 0" in w1_block, (
        "W1 subsection must explicitly cite Phase 0 as the source of the "
        "accept-regex, not merely restate the regex as a fresh literal"
    )
    assert "TICKET_PREFIX" in w1_block, (
        "W1 subsection's regex citation should name the TICKET_PREFIX sites "
        "it is cross-referencing"
    )


def test_site_w1_precedes_phase_3_3b_5_headings(implement_ticket_text):
    # DS-163 observability follow-up: W1 must fire before the architect
    # (Phase 3), orchestration-planner (Phase 3b), and engineer (Phase 5)
    # spawn sites - the ordering fix this pins is already shipped (PR #517);
    # this test is a regression guard against it silently moving back.
    w1_idx = implement_ticket_text.index("site: W1")
    phase3_idx = implement_ticket_text.index("## Phase 3: Architecture plan")
    phase3b_idx = implement_ticket_text.index("## Phase 3b: Orchestration plan")
    phase5_idx = implement_ticket_text.index("## Phase 5: Implement")
    assert w1_idx < phase3_idx < phase3b_idx < phase5_idx, (
        f"expected offset ordering W1({w1_idx}) < Phase 3({phase3_idx}) < "
        f"Phase 3b({phase3b_idx}) < Phase 5({phase5_idx})"
    )


def test_phase_5_has_no_w1_site_and_carries_the_anti_regression_note(implement_ticket_text):
    phase5_idx = implement_ticket_text.index("## Phase 5: Implement")
    phase6_idx = implement_ticket_text.index("## Phase 6:")
    phase5_text = implement_ticket_text[phase5_idx:phase6_idx]
    assert "site: W1" not in phase5_text, (
        "Phase 5 must not carry a 'site: W1' fire site - In Progress is "
        "written at Phase 1 only"
    )
    assert (
        "Phase 5 deliberately has no W1 site. Do not re-add one."
        in phase5_text
    ), (
        "Phase 5 must retain the anti-regression note against re-adding a "
        "W1 fire site"
    )


def _assert_no_w1_site_in_phase5(text: str) -> None:
    """The real production assertion: Phase 5 must not carry a 'site: W1'
    fire site. Extracted into a standalone function (rather than inlined in
    a test body) so a mutation test can call it directly against a poisoned
    fixture and confirm it actually raises - see
    test_phase_5_no_w1_site_guard_catches_reintroduction below. The prior
    version of this guard built a `poisoned` string and asserted against
    that same string - a same-source tautology that could never redden."""
    phase5_idx = text.index("## Phase 5: Implement")
    phase6_idx = text.index("## Phase 6:")
    phase5_text = text[phase5_idx:phase6_idx]
    assert "site: W1" not in phase5_text, (
        "Phase 5 must not carry a 'site: W1' fire site - In Progress is "
        "written at Phase 1 only"
    )


def test_phase_5_has_no_w1_site_and_carries_the_anti_regression_note(implement_ticket_text):
    _assert_no_w1_site_in_phase5(implement_ticket_text)
    phase5_idx = implement_ticket_text.index("## Phase 5: Implement")
    phase6_idx = implement_ticket_text.index("## Phase 6:")
    phase5_text = implement_ticket_text[phase5_idx:phase6_idx]
    assert (
        "Phase 5 deliberately has no W1 site. Do not re-add one."
        in phase5_text
    ), (
        "Phase 5 must retain the anti-regression note against re-adding a "
        "W1 fire site"
    )


def test_phase_5_no_w1_site_guard_catches_reintroduction():
    # Non-vacuous proof: call the REAL production assertion helper
    # (_assert_no_w1_site_in_phase5, the same function the passing test
    # above calls) against a poisoned fixture that DOES re-add a Phase-5
    # W1 site, and confirm it actually raises AssertionError. Unlike the
    # prior version of this test, both operands here do not trace to the
    # same source: the helper is the live production check, and the
    # fixture is a synthetic input constructed independently of it.
    poisoned = (
        "## Phase 5: Implement\n\n"
        "[phase: tracker-writeback | site: W1 | target: $TRACKER_STATE_IN_PROGRESS]\n\n"
        "## Phase 6: Something\n"
    )
    with pytest.raises(AssertionError):
        _assert_no_w1_site_in_phase5(poisoned)


def _assert_w1_outcome_mechanism(w1_block: str, reset_block: str) -> None:
    """The real production assertion: pins the MECHANISM that produces each
    outcome/reason, not merely the English prose that names it. Extracted
    into a standalone function so a mutation test can call it directly -
    see test_w1_outcome_breadcrumb_mechanism_mutation_guard below.

    A prior version of this check asserted only bare substring membership
    (e.g. `"prefix_mismatch" in w1_block`), which the surrounding English
    prose already satisfies even with the entire W1 resolution block
    deleted, a single elif branch deleted, or every reason code renamed
    throughout. This version pins the literal shell assignment statements
    that actually produce each value."""
    assert "ds-emit tracker_writeback" in w1_block, (
        "W1 subsection must invoke `ds-emit tracker_writeback`"
    )

    # --- skip-reason mechanism: each reason must be an actual elif-branch
    # assignment, in the correct mutually-exclusive if/elif chain, not just
    # a word appearing anywhere in prose.
    reason_assignments = [
        ('W1_REASON="tracker_none"', 'if [ "$TRACKER" = "none" ]'),
        (
            'W1_REASON="ticket_id_format"',
            "elif ! printf '%s' \"$TICKET_ID\" | grep -qE",
        ),
        (
            'W1_REASON="prefix_mismatch"',
            'elif [ -n "${TICKET_PREFIX:-}" ]',
        ),
        (
            'W1_REASON="fetch_failed"',
            'elif [ "${W1_FETCH_FAILED:-false}" = "true" ]',
        ),
    ]
    for assignment, guarding_condition in reason_assignments:
        assert assignment in w1_block, (
            f"W1 subsection must contain the literal assignment {assignment!r} "
            "- prose naming the reason is not sufficient"
        )
        assert guarding_condition in w1_block, (
            f"W1 subsection must contain the literal guarding condition "
            f"{guarding_condition!r} that produces {assignment!r}"
        )

    # --- skip-outcome mechanism: the skip emit line must fire only inside
    # the `if [ -n "$W1_REASON" ]` guard and carry the literal "skipped"
    # outcome plus the resolved $W1_REASON as its reason.
    assert 'if [ -n "$W1_REASON" ]' in w1_block, (
        "W1 subsection must gate the skip emit on a non-empty $W1_REASON"
    )
    assert (
        '\\"outcome\\":\\"skipped\\",\\"reason\\":\\"$W1_REASON\\"' in w1_block
    ), (
        "W1 subsection's skip emit line must carry outcome:skipped paired "
        "with the resolved $W1_REASON as reason"
    )

    # --- dispatch-outcome mechanism (the Critical finding): both branches
    # of W1_DISPATCH_OUTCOME must be explicit literal assignments, and the
    # emit line's expansion must be set -u-safe (a bare $W1_DISPATCH_OUTCOME
    # would abort the whole step under `set -u` if either assignment above
    # were ever skipped).
    assert 'W1_DISPATCH_OUTCOME="dispatched"' in w1_block, (
        "W1 subsection must explicitly assign W1_DISPATCH_OUTCOME=\"dispatched\" "
        "on the tool-call-accepted branch"
    )
    assert 'W1_DISPATCH_OUTCOME="dispatch_failed"' in w1_block, (
        "W1 subsection must explicitly assign W1_DISPATCH_OUTCOME=\"dispatch_failed\" "
        "on the tool-call-error branch"
    )
    assert (
        '\\"outcome\\":\\"${W1_DISPATCH_OUTCOME:-dispatch_failed}\\"' in w1_block
    ), (
        "the dispatch emit line must use the set -u-safe "
        "${W1_DISPATCH_OUTCOME:-dispatch_failed} expansion, not a bare "
        "$W1_DISPATCH_OUTCOME reference"
    )
    assert "$W1_DISPATCH_OUTCOME}" not in w1_block.replace(
        "${W1_DISPATCH_OUTCOME:-dispatch_failed}", ""
    ), (
        "found a bare, non-defaulted $W1_DISPATCH_OUTCOME expansion outside "
        "the set -u-safe form - this is exactly the unassigned-reference "
        "defect the Critical finding flagged"
    )

    # --- per-ticket reset: W1_DISPATCH_OUTCOME (like W1_FETCH_FAILED) must
    # be reset at the top of every entry, or a batch ticket that never
    # reaches the dispatch branch inherits the previous ticket's value.
    assert 'W1_DISPATCH_OUTCOME=""' in reset_block, (
        "the per-ticket variable reset block must reset W1_DISPATCH_OUTCOME "
        "alongside W1_FETCH_FAILED"
    )
    assert "W1_FETCH_FAILED=false" in reset_block, (
        "sanity check: the per-ticket variable reset block must still reset "
        "W1_FETCH_FAILED"
    )


def test_w1_outcome_breadcrumb_covers_all_three_outcomes(w1_block, per_ticket_reset_block):
    # DS-163 (round 2): every W1 evaluation must emit exactly one ds-emit
    # `tracker_writeback` breadcrumb, distinctly covering all three
    # outcomes - skipped, dispatched, and dispatch_failed - via the actual
    # assignment mechanism, not prose that merely names the outcome.
    _assert_w1_outcome_mechanism(w1_block, per_ticket_reset_block)


def test_w1_outcome_breadcrumb_mechanism_mutation_guard():
    # Non-vacuous proof: call the REAL production assertion helper
    # (_assert_w1_outcome_mechanism, the same function the passing test
    # above calls) against poisoned fixtures that preserve the surrounding
    # prose but break the mechanism, and confirm each one actually raises.
    real_w1_block = _extract_w1_block(
        IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")
    )
    real_reset_block = _extract_subsection(
        IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8"),
        "### Per-ticket variable reset (binding, runs FIRST on every entry)",
    )

    # Mutation 1: delete the entire W1_REASON resolution block (the exact
    # class of deletion the Skeptic used to falsify the round-1 assertions).
    poisoned_1 = real_w1_block.replace(
        'W1_REASON="tracker_none"', "# deleted"
    ).replace(
        'W1_REASON="ticket_id_format"', "# deleted"
    ).replace(
        'W1_REASON="prefix_mismatch"', "# deleted"
    ).replace(
        'W1_REASON="fetch_failed"', "# deleted"
    )
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_1, real_reset_block)

    # Mutation 2: delete just the prefix_mismatch elif branch's assignment.
    poisoned_2 = real_w1_block.replace('W1_REASON="prefix_mismatch"', "# deleted")
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_2, real_reset_block)

    # Mutation 3: rename prefix_mismatch throughout (simulates the
    # substring-satisfying-prose failure mode the Skeptic identified).
    poisoned_3 = real_w1_block.replace("prefix_mismatch", "prefix_mismatch_renamed")
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_3, real_reset_block)

    # Mutation 4 (the Critical finding): delete the dispatched-branch
    # assignment, leaving only the bare set -u-safe fallback.
    poisoned_4 = real_w1_block.replace('W1_DISPATCH_OUTCOME="dispatched"', "# deleted")
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_4, real_reset_block)

    # Mutation 5: delete the dispatch_failed-branch assignment.
    poisoned_5 = real_w1_block.replace(
        'W1_DISPATCH_OUTCOME="dispatch_failed"', "# deleted"
    )
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_5, real_reset_block)

    # Mutation 6: revert the emit line to a bare, non-defaulted expansion
    # (the exact shape the Critical finding was filed against).
    poisoned_6 = real_w1_block.replace(
        '${W1_DISPATCH_OUTCOME:-dispatch_failed}', "$W1_DISPATCH_OUTCOME"
    )
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(poisoned_6, real_reset_block)

    # Mutation 7: drop the per-ticket reset for W1_DISPATCH_OUTCOME.
    poisoned_reset = real_reset_block.replace('W1_DISPATCH_OUTCOME=""', "")
    with pytest.raises(AssertionError):
        _assert_w1_outcome_mechanism(real_w1_block, poisoned_reset)

    # Sanity: the unmodified real blocks must pass (proves the helper is
    # not simply always-raising).
    _assert_w1_outcome_mechanism(real_w1_block, real_reset_block)


def test_w1_tracker_none_advisory_present_and_scoped(w1_block):
    # The tracker_none skip must be operator-visible via a one-line advisory,
    # and that advisory must be scoped to tracker_none only (not fired for
    # the other three skip reasons).
    assert "TRACKER is none for this project" in w1_block, (
        "W1 subsection must carry the tracker_none advisory line"
    )
    assert (
        "No advisory line fires for the other three reasons" in w1_block
    ), (
        "W1 subsection must explicitly scope the advisory to tracker_none "
        "only, not the other three skip reasons"
    )


def test_w1_outcome_breadcrumb_soft_fail(w1_block):
    # A missing or failing ds-emit must never block Phase 1 - every emit
    # call site must be soft-failed.
    emit_lines = [
        line for line in w1_block.splitlines() if "ds-emit tracker_writeback" in line
    ]
    assert emit_lines, "expected at least one ds-emit tracker_writeback call site"
    for line in emit_lines:
        assert "2>/dev/null || true" in line, (
            f"ds-emit tracker_writeback call site must be soft-failed: {line!r}"
        )


def test_w1_subsection_cited_phase_0_sites_actually_exist(implement_ticket_text):
    # Non-vacuous check: confirm the two Phase 0 sites the W1 subsection
    # claims to cite actually carry the same regex literal. If a future
    # edit changes the Phase 0 regex without updating the citation (or vice
    # versa), this fails.
    phase0_idx = implement_ticket_text.index("## Phase 0:")
    phase1_idx = implement_ticket_text.index("## Phase 1:")
    phase0_text = implement_ticket_text[phase0_idx:phase1_idx]
    regex_occurrences = phase0_text.count("^[A-Z][A-Z0-9_]+-\\d+$")
    assert regex_occurrences >= 2, (
        "expected at least 2 occurrences of the accept-regex literal in "
        f"Phase 0 (the two TICKET_PREFIX sites the W1 subsection cites), "
        f"found {regex_occurrences}"
    )


# ---------------------------------------------------------------------------
# content/commands/ds-ticket-status-sync.md: --pending-merge mode
# ---------------------------------------------------------------------------

def test_pending_merge_flag_present(status_sync_text):
    assert "--pending-merge" in status_sync_text


def test_pending_merge_section_no_prompt_and_throttle(pending_merge_section):
    assert "No prompting" in pending_merge_section or "without prompting" in pending_merge_section, (
        "pending-merge section must state that it transitions without prompting"
    )
    assert "60-minute" in pending_merge_section or "60 minutes" in pending_merge_section, (
        "pending-merge section must state the 60-minute throttle"
    )


def test_exactly_two_tracker_writeback_spawn_sites(status_sync_text):
    sentence = (
        "spawn the tracker-writeback subagent using the "
        "`## Tracker Writeback Helper` invocation contract"
    )
    occurrences = status_sync_text.count(sentence)
    assert occurrences == 2, (
        f"expected exactly 2 tracker-writeback spawn sites, found {occurrences}"
    )


def test_pending_merge_names_ledger_as_candidate_source(pending_merge_section):
    assert ".agentic/ticket-ledger.jsonl" in pending_merge_section, (
        "pending-merge section must name .agentic/ticket-ledger.jsonl as its "
        "candidate source"
    )


def test_pending_merge_does_not_reintroduce_title_or_branch_matching(pending_merge_section):
    # Regression guard: an earlier, rejected design keyed ticket identity
    # off substring matches in PR titles and branch names (headRefName).
    # That design permitted false-positive Done transitions on tickets a
    # PR merely mentioned without implementing. It must never come back as
    # even a corroborating signal.
    #
    # 'headRefName' appears exactly TWICE in the live section - both inside
    # sanctioned negation/prohibition prose: the "no future edit ... may
    # add title or `headRefName` extraction" prohibition sentence, and the
    # "No regex is applied to `headRefName` anywhere in this mode"
    # confirmation sentence. A THIRD occurrence would mean a real (re-)use
    # of headRefName for identity has been added.
    head_ref_occurrences = pending_merge_section.count("headRefName")
    assert head_ref_occurrences == 2, (
        f"expected exactly 2 'headRefName' occurrences (the two sanctioned "
        f"negation/prohibition sentences), found {head_ref_occurrences} - a "
        f"third occurrence signals title/branch-text matching may have been "
        f"reintroduced as an identity signal"
    )
    # No PR-title-extraction regex construct (e.g. 'extract group ... from
    # ... title') should be present anywhere in the section.
    assert "extract group" not in pending_merge_section, (
        "pending-merge section must not contain a title/branch "
        "extract-group regex construct - identity is ledger pr_number only"
    )
    # The explicit prohibition sentence itself must survive.
    assert (
        "no future edit to this section may add title or `headRefName` "
        "extraction as even a corroborating signal" in pending_merge_section
    ), "the explicit anti-reintroduction prohibition sentence must be present verbatim"


def test_pending_merge_non_vacuous_headref_guard_catches_reintroduction():
    # Non-vacuous proof: simulate a reintroduction and confirm the guard
    # above would actually fail against it, rather than passing regardless
    # of section content.
    poisoned = (
        "## Pending-merge sweep (--pending-merge mode)\n\n"
        "no future edit to this section may add title or `headRefName` "
        "extraction as even a corroborating signal.\n"
        "No regex is applied to `headRefName` anywhere in this mode.\n"
        "Match ticket keys against headRefName using a regex.\n"
    )
    head_ref_occurrences = poisoned.count("headRefName")
    assert head_ref_occurrences == 3, (
        "sanity check: the poisoned fixture should contain 3 occurrences "
        "(the 2 sanctioned ones plus 1 reintroduction)"
    )
    assert head_ref_occurrences != 2, (
        "the guard assertion (== 2) must fail against a reintroduction - "
        "this pins that the assertion is not vacuously true"
    )


def test_pending_merge_cursor_advance_and_attempts_cap(pending_merge_section):
    assert "unconditionally" in pending_merge_section, (
        "pending-merge section must state the cursor advances unconditionally"
    )
    # Pin the specific cap value and the terminal state it produces, not
    # merely the presence of the word "attempts" - a change to the cap
    # value or a dropped `abandoned` terminalization must fail this test.
    assert "attempts` reaches **3**" in pending_merge_section, (
        "pending-merge section must define the attempts cap as exactly 3"
    )
    assert "append `abandoned`" in pending_merge_section, (
        "pending-merge section must terminalize an exhausted pair as "
        "`abandoned` when the attempts cap is reached"
    )


def test_pending_merge_open_pr_check_present(pending_merge_section):
    # Pins Skeptic finding MAJOR 1: the open-PR safety control that stops a
    # multi-PR ticket being marked Done by its first merged PR (DS-56 shape
    # for concurrently-open siblings). Both halves are asserted
    # independently of the headRefName-prohibition count above, so neither
    # assertion passes by coupling to the other.
    assert '--state open --search "<TICKET_ID>"' in pending_merge_section, (
        "pending-merge section must run the open-PR search "
        "(`gh pr list --state open --search`) before mapping a merged "
        "candidate to Done"
    )
    assert (
        'therefore treat an **error** on this call as "blocked" '
        '(do not transition), not as "clear."' in pending_merge_section
    ), (
        "pending-merge section must state the fail-closed rule: an error "
        "on the open-PR search is treated as blocked, not clear"
    )


def test_pending_merge_never_truncate_silently_pinned(pending_merge_section):
    # Pins Skeptic finding MINOR 3a: the cap-truncation announcement line
    # (interface contract 7, "never truncate silently") was entirely
    # unpinned - deleting the whole paragraph left the suite green.
    assert "Never truncate silently." in pending_merge_section, (
        "pending-merge section must state the never-truncate-silently rule "
        "for the 20-candidate cap"
    )
    assert (
        "pending-merge sweep capped at 20 candidates" in pending_merge_section
    ), (
        "pending-merge section must print the specific cap-truncation "
        "breadcrumb naming how many older pairs were skipped"
    )


# ---------------------------------------------------------------------------
# content/rules/conventions.md: session-start sweep pointer
# ---------------------------------------------------------------------------

def test_conventions_has_pending_merge_pointer():
    text = CONVENTIONS_PATH.read_text(encoding="utf-8")
    assert "pending-merge" in text.lower()
    assert "does not add to the stacked-notice count" in text or "does not add to that count" in text, (
        "conventions.md must explicitly exclude the pending-merge sweep from "
        "the stacked first-user-turn notice count"
    )


# ---------------------------------------------------------------------------
# pending_merge_sweep toggle registration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", TOGGLE_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_toggle_registered_on_surface(path):
    assert path.exists(), f"missing enumeration surface: {path}"
    text = path.read_text(encoding="utf-8")
    assert "pending_merge_sweep" in text, (
        f"pending_merge_sweep toggle not registered in {path.relative_to(REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# Adapter byte-identity for the W1 block
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", ADAPTER_PATHS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_adapter_file_exists(path):
    assert path.exists(), f"missing adapter copy: {path}"


def test_w1_block_byte_identical_across_adapters():
    canonical = None
    canonical_path = None
    mismatches = []
    for path in ADAPTER_PATHS:
        text = path.read_text(encoding="utf-8")
        block = _extract_w1_block(text)
        # .gemini/commands/*.toml embeds the block inside a TOML
        # triple-quoted basic string, where TOML's own escaping doubles
        # every literal backslash (e.g. the W1 accept-regex's `\d+$`
        # becomes `\\d+$` on disk). That is a format-level encoding
        # difference, not a content divergence, so undo it before
        # comparing - same normalization concern the ranking spec's
        # ADAPTER_PATHS precedent never had to handle because its block
        # happens to contain no backslashes.
        if path.suffix == ".toml":
            block = block.replace("\\\\", "\\")
        if canonical is None:
            canonical = block
            canonical_path = path
            continue
        if block != canonical:
            mismatches.append(str(path.relative_to(REPO_ROOT)))
    assert not mismatches, (
        f"W1 block diverges from {canonical_path.relative_to(REPO_ROOT)} in: "
        f"{mismatches}"
    )


# ---------------------------------------------------------------------------
# content/commands/ds-init-project.md Step 9: .agentic/tracker.yml consumer
# protection (DS-74 - PR1: lands ahead of the .agentic/tracker.yml overlay
# file itself, which lands in a later PR).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def init_project_text() -> str:
    return INIT_PROJECT_PATH.read_text(encoding="utf-8")


def _step9_fenced_block(text: str) -> str:
    # Scope every anchor/position assertion below to the Step 9 gitignore
    # fenced block itself, not the whole file. A file-wide str.index() is
    # sound only as long as every anchor is unique across the entire
    # document; Step 11 (prose row 8) adds a second, later
    # ".agentic/tracker.yml" mention, so scoping here is what keeps this
    # test non-vacuous against that addition (Minor 2, r3 changelog).
    marker = "# Agentic engineering runtime artifacts"
    idx = text.index(marker)
    fence_start = text.rfind("```", 0, idx)
    fence_end = text.index("```", idx)
    return text[fence_start:fence_end]


def test_tracker_yml_ignore_line_between_anchors(init_project_text):
    # Position assertion: `.agentic/tracker.yml` must sit strictly between
    # the two anchor lines, inside the ignore-pattern run of the fenced
    # block. This fails both if the line is dropped entirely AND if it is
    # re-placed under the "# Tracked (explicitly NOT ignored):" comment
    # block, where it would misleadingly read as one of the tracked files.
    block = _step9_fenced_block(init_project_text)
    compression_idx = block.index(".agentic/compression-state.json")
    tracker_states_idx = block.index(".agentic/tracker-states.json")
    assert compression_idx < tracker_states_idx, (
        "anchor ordering assumption violated: .agentic/compression-state.json "
        "must precede .agentic/tracker-states.json"
    )
    tracker_yml_idx = block.index(".agentic/tracker.yml")
    assert compression_idx < tracker_yml_idx < tracker_states_idx, (
        ".agentic/tracker.yml must occur strictly between "
        ".agentic/compression-state.json and .agentic/tracker-states.json "
        "in the Step 9 gitignore block - this is the consumer-protection "
        "line that must land before the .agentic/tracker.yml overlay file "
        "itself exists anywhere (DS-74)"
    )
    tracked_comment_idx = block.index(
        "# Tracked (explicitly NOT ignored):"
    )
    assert tracker_yml_idx < tracked_comment_idx, (
        ".agentic/tracker.yml must appear BEFORE the "
        "'# Tracked (explicitly NOT ignored):' comment block - placed after "
        "it, the line would misleadingly read as one of the tracked files "
        "rather than an ignored one"
    )


def _step9_enumeration_paragraph(text: str) -> str:
    marker = "since none of the"
    idx = text.index(marker)
    # The enumeration paragraph is a single unbroken line in the source
    # (no internal newlines); isolate it by line boundaries around the
    # marker so the paragraph-scoped assertions below are non-vacuous
    # against the rest of the file.
    line_start = text.rfind("\n", 0, idx) + 1
    line_end = text.find("\n", idx)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def test_step9_enumeration_names_tracker_yml(init_project_text):
    paragraph = _step9_enumeration_paragraph(init_project_text)
    assert "`tracker-states.json`" in paragraph, (
        "sanity check: the Step 9 enumeration paragraph anchor must be "
        "present"
    )
    assert (
        "per-operator local tracker config; never committed"
        in paragraph
    ), (
        "the Step 9 enumeration paragraph must name tracker.yml explicitly "
        "('per-operator local tracker config; never committed'), not just "
        "update the count word"
    )


# Word forms for the plausible ignore-pattern-line-count range. Extend this
# map (never re-pin a literal count word) if the block legitimately grows
# past 20 lines.
_NUMBER_WORDS = {
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}


def test_step9_enumeration_count_word_matches_actual_line_count(init_project_text):
    # Derived, not pinned (Minor 1, r3 changelog): parse the actual number
    # of `.agentic/...` ignore-pattern lines in the fenced block and assert
    # the enumeration paragraph's count word matches THAT number - a future
    # 17th ignore line added without updating the prose now fails this
    # assertion instead of silently passing against a stale literal.
    block = _step9_fenced_block(init_project_text)
    ignore_lines = [
        line for line in block.splitlines()
        if re.match(r"^\.agentic/", line.strip())
    ]
    count = len(ignore_lines)
    assert count in _NUMBER_WORDS, (
        f"ignore-pattern-line count {count} is outside the mapped word range; "
        "extend _NUMBER_WORDS"
    )
    expected_word = _NUMBER_WORDS[count]
    paragraph = _step9_enumeration_paragraph(init_project_text)
    assert f"since none of the {expected_word} lines above them" in paragraph, (
        f"the Step 9 enumeration paragraph's count word must match the actual "
        f"count of ignore-pattern lines in the fenced block ({count} -> "
        f"'{expected_word}'); paragraph: {paragraph!r}"
    )


# ---------------------------------------------------------------------------
# PR2 prose assertions (DS-74): the .agentic/tracker.yml overlay merge rule,
# its insertion point in ds-implement-ticket.md Setup, the disclosure line
# at all four entry points, the Step 11 local-overlay prompt, and the
# ds-config.md out-of-scope clause.
# ---------------------------------------------------------------------------

def test_overlay_block_after_dual_shape_note_before_print_summary(implement_ticket_text):
    # Prose row 1.
    dual_shape_idx = implement_ticket_text.index("**Dual-shape note:**")
    print_summary_idx = implement_ticket_text.index(
        "Print a summary of resolved values before Phase 1:"
    )
    tracker_yml_idx = implement_ticket_text.index(
        ".agentic/tracker.yml", dual_shape_idx
    )
    assert dual_shape_idx < tracker_yml_idx < print_summary_idx, (
        "the .agentic/tracker.yml overlay block must occur after the "
        "Dual-shape note and before the Print-summary anchor, inside Setup"
    )


def test_guard_interaction_literal_after_legacy_guard_stop(implement_ticket_text):
    # Prose row 2. Exact literal so the assertion pins the guard
    # interaction wording, not just "some mention" of it.
    stop_anchor = (
        "Do not continue. Do not attempt to write the migration. "
        "All config-mutation logic lives in `/ds-init-project`."
    )
    stop_idx = implement_ticket_text.index(stop_anchor)
    print_summary_idx = implement_ticket_text.index(
        "Print a summary of resolved values before Phase 1:"
    )
    literal = (
        "the legacy `## Linear` shape guard is evaluated before this "
        "overlay and is never suppressed by it"
    )
    literal_idx = implement_ticket_text.index(literal, stop_idx)
    assert stop_idx < literal_idx < print_summary_idx, (
        "the guard-interaction literal must occur after the legacy-guard "
        "stop line and before the Print-summary anchor"
    )


def test_wrap_gate_line_and_file_disclose_tracker_config_source():
    # Prose row 3.
    text = WRAP_PATH.read_text(encoding="utf-8")
    gate_lines = [l for l in text.splitlines() if l.strip().startswith("**Gate.**")]
    assert gate_lines, "Part F Gate line not found in ds-wrap.md"
    assert any("TRACKER_STATE_IN_PROGRESS" in l for l in gate_lines), (
        "Part F Gate line no longer resolves TRACKER_STATE_IN_PROGRESS"
    )
    assert "Tracker config source:" in text, (
        "ds-wrap.md must disclose the .agentic/tracker.yml overlay source"
    )


@pytest.mark.parametrize(
    "path", TRACKER_DISCLOSURE_ENTRY_POINTS, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_tracker_config_source_disclosed_at_every_entry_point(path):
    # Prose row 4.
    text = path.read_text(encoding="utf-8")
    assert "Tracker config source:" in text, (
        f"{path.relative_to(REPO_ROOT)} must disclose the .agentic/tracker.yml "
        "overlay source"
    )


def test_step11_local_overlay_prompt_present(init_project_text):
    # Prose row 8.
    heading_idx = init_project_text.index("### 11. Set up tracker")
    linear_setup_idx = init_project_text.index("**11a. Linear setup**", heading_idx)
    literal = ".agentic/tracker.yml` (local, gitignored)"
    literal_idx = init_project_text.index(literal, heading_idx)
    assert heading_idx < literal_idx < linear_setup_idx, (
        "the Step 11 local-overlay prompt naming .agentic/tracker.yml (local, "
        "gitignored) must occur between the '### 11. Set up tracker' heading "
        "and '**11a. Linear setup**'"
    )


def test_config_cmd_out_of_scope_names_agentic_tracker():
    # Prose row 9.
    text = CONFIG_CMD_PATH.read_text(encoding="utf-8")
    out_of_scope_idx = text.index("**Out of scope:**")
    identity_idx = text.index(
        "identity (owned by `/ds-identity`)", out_of_scope_idx
    )
    tracker_idx = text.index("ds-tracker", out_of_scope_idx)
    assert out_of_scope_idx < identity_idx < tracker_idx, (
        "ds-tracker must be named in the ds-config.md Out-of-scope "
        "clause, after the identity clause it extends"
    )
