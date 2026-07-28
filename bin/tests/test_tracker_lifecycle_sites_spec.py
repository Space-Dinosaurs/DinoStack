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


def _extract_w1_block(text: str) -> str:
    """Extract the '### Tracker writeback (W1)' subsection: from the exact
    heading line up to (exclusive) the next line that is itself a '## ' or
    '### ' heading. Matches on an exact-stripped heading line so inline
    backtick mentions elsewhere (e.g. in a fused multi-command embed like
    .hermes/SKILL.md) are not mistaken for the heading itself."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == W1_HEADING:
            start = i
            break
    if start is None:
        raise AssertionError(f"heading {W1_HEADING!r} not found")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            end = j
            break
    return "\n".join(lines[start:end])


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
    assert "attempts" in pending_merge_section, (
        "pending-merge section must define an attempts cap"
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
