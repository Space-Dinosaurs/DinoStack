#!/usr/bin/env python3
"""
Spec tests for DS-117: splitting the automatic merge/complete writeback
target from the terminal `TRACKER_STATE_DONE` state into a new, non-terminal
`TRACKER_STATE_DEV_COMPLETE` state (content/commands/ds-implement-ticket.md
## Tracker Writeback Helper, content/commands/ds-ticket-status-sync.md,
content/commands/ds-wrap.md, content/commands/ds-init-project.md).

Covers:
  - The prefix trap: `TRACKER_STATE_DIAGNOSTIC` is a config toggle, not one
    of the 6 states, so no test in bin/tests/ may pattern-match the bare
    `TRACKER_STATE_` prefix. A sweep over every bin/tests/*.py file pins
    this open with a non-vacuity guard, plus a supplementary spot-check on
    the two state enumerations in the canonical file.
  - SC3 (AE never automatically fires terminal Done): a count-zero check
    that content/commands/ds-ticket-status-sync.md contains zero occurrences
    of `TRACKER_STATE_DONE`, plus a widened, narrowed, and universe-closed
    target-shape scan (`TARGET_RE`) over every content/ file that names any
    `TRACKER_STATE_*` variable at all - the file set is DERIVED from the
    tree rather than hardcoded, so a new content/ file naming
    `TRACKER_STATE_` fails the universe-closure test rather than escaping
    the scan unnoticed.
  - SC1 (declarable on all four surfaces): Jira `JIRA_STATE_DEV_COMPLETE`,
    Linear `State Dev Complete:`, the `.agentic/tracker.yml` overlay's
    `state_dev_complete` key, and the `TRACKER=none` branch (nothing
    declarable).
  - SC2 (default behavior unchanged for a declares-nothing project): each of
    the three Setup branch lines (Jira, Linear, none) states the inherited
    default explicitly, qualified as the RESOLVED Done value rather than a
    bare literal.
  - M1: `TRACKER_DEV_COMPLETE_DECLARED` is actually resolved in Setup on all
    three branches, with the presence test evaluated BEFORE the inherited
    default is applied.
  - M5: the Jira and Linear Setup branch lines instruct declaring
    `JIRA_PIPELINE_ORDER` / `Pipeline order:` when the dev-complete lane
    sits before the QA lane, naming the backward-move consequence.
  - SC3 prose: neither command file still promises an automatic terminal
    Done transition in operator-facing prose; each repaired phrase is
    paired with a positive assertion that its dev-complete replacement
    landed, so a bare deletion cannot pass.
  - SC4 (forward-only guard ranks a non-terminal dev-complete correctly):
    the default pipeline rank places DEV_COMPLETE last, and a declared name
    collision resolves to the HIGHEST matching pipeline rank.
  - SC2/R7 (the round-2 Major pin): an INHERITED dev-complete value carries
    no pipeline rank at all, closed-vocabulary-swept against 8 distinct
    phrasings that would grant it one.
  - `dev_complete_declared` appears in BOTH the Tracker Writeback Helper
    pass-list and the Phase 11 pass-list, each scoped to its own window.
  - Phase 11's `pipeline_order` bullet states the arity is 4 tokens and no
    longer claims a stale 3-element arity.
  - The `pending_merge_sweep` toggle DESCRIPTION names the dev-complete
    transition at all 6 prose sites plus docs/index.html's own sentence.
  - An enumeration audit: every "N of the M `TRACKER_STATE_*` values"-shaped
    sentence bumped from 5 to 6, with the stale 5-value phrasing at zero
    occurrences everywhere it used to appear.
  - The `tracker_state_values` JSON literal is byte-identical at the
    Tracker Writeback Helper pass-list site and the Phase 11 Inputs site
    (extracted from the backticked literal itself, not the surrounding
    line, since the two lines differ by prefix and trailing prose).

Run with: python3 -m pytest bin/tests/test_tracker_dev_complete_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
STATUS_SYNC_PATH = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
WRAP_PATH = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
INIT_PROJECT_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"

# DS split unit 1: the "## Tracker Writeback Helper" block itself moved out
# of CANONICAL_PATH into HELPER_PATH behind a trigger-pointer. Tests that
# examine the block's own content read HELPER_PATH; tests that examine
# content that stayed inline (Setup, Phase 2c, Phase 11's own Inputs list)
# still read CANONICAL_PATH.
HELPER_PATH = REPO_ROOT / "content" / "references" / "tracker-writeback.md"

HEADING = "## Tracker Writeback Helper"


def _extract_block(text: str) -> str:
    """Extract the '## Tracker Writeback Helper' section: from the exact
    heading line up to (exclusive) the next line that is itself a top-level
    '## ' heading. Matches on an exact-stripped heading line, mirroring
    test_tracker_writeback_ranking_spec.py's own helper of the same name."""
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
    return _extract_block(HELPER_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The prefix trap: TRACKER_STATE_DIAGNOSTIC is a config toggle, not a state.
# No test may pattern-match the bare TRACKER_STATE_ prefix - such a pattern
# silently swallows the toggle into every state enumeration.
# ---------------------------------------------------------------------------

# What a BARE-prefix pattern looks like: an open bracket, a backslash-w /
# backslash-S / backslash-D shorthand, or a dot-quantifier immediately
# after the prefix - OR any of those wrapped in a group, plain OR
# non-capturing OR named. Illustrated below with a single space inserted
# between the prefix and the tail, purely so this documentation comment
# does not itself trip the very sweep it describes - the sweep requires
# the tail to sit IMMEDIATELY after the prefix, so the space is enough to
# make each example inert as documentation while still being unambiguous:
#     TRACKER_STATE_ (\w+)          <- must be caught (no space, in real code)
#     TRACKER_STATE_ (?:\w+)        <- must be caught
#     TRACKER_STATE_ (?P<s>\w+)     <- must be caught
#     TRACKER_STATE_ [A-Z_]+        <- must be caught (the v2 offender)
# A closed alternation - "(" followed immediately by a literal state name -
# is the sanctioned form and is deliberately NOT flagged, which is why this
# module's own TARGET_RE does not self-trip. The discriminator is what
# follows the paren, not the paren itself.
_BARE_TAIL = r"(?:\[|\\w|\\S|\\D|\.[*+?])"
BARE_PREFIX_PATTERN_RE = re.compile(
    r"TRACKER_STATE_(?:" + _BARE_TAIL
    + r"|\((?:\?:|\?P<\w+>)?" + _BARE_TAIL + r")"
)


def test_no_test_pattern_matches_the_bare_tracker_state_prefix():
    """Brief hard constraint: TRACKER_STATE_DIAGNOSTIC is a boolean config
    toggle, not one of the 6 states, so no test may pattern-match the bare
    TRACKER_STATE_ prefix - such a pattern silently swallows the toggle into
    every state enumeration. Sweeps every bin/tests/*.py, not just the two
    lines a spot-check would cover.
    """
    scanned = 0
    saw_prefix = False
    offenders = []
    for p in sorted((REPO_ROOT / "bin" / "tests").glob("*.py")):
        scanned += 1
        text = p.read_text(encoding="utf-8")
        if "TRACKER_STATE_" in text:
            saw_prefix = True
        for i, line in enumerate(text.splitlines(), 1):
            if BARE_PREFIX_PATTERN_RE.search(line):
                offenders.append(f"{p.name}:{i}: {line.strip()}")
    # non-vacuity: a broken glob or a moved test dir must fail, not pass.
    assert scanned >= 3, f"bare-prefix sweep read only {scanned} test file(s)"
    assert saw_prefix, "bare-prefix sweep saw no TRACKER_STATE_ at all - glob is wrong"
    assert not offenders, (
        "bare TRACKER_STATE_ prefix pattern found (use a closed alternation "
        "of the 6 state names instead):\n" + "\n".join(offenders)
    )


def test_diagnostic_toggle_absent_from_the_two_state_enumerations():
    """Supplementary spot-check, NOT the pin - the pin is the sweep above.
    Two-way split post-DS-split-unit-1: the tracker_state_values pass-list
    bullet moved to HELPER_PATH with the rest of the block; the Setup
    TRACKER=none branch stayed inline in CANONICAL_PATH."""
    block = _extract_block(HELPER_PATH.read_text(encoding="utf-8"))
    tsv_line = next(l for l in block.splitlines()
                    if l.strip().startswith("- `tracker_state_values`:"))
    assert "DIAGNOSTIC" not in tsv_line

    text = CANONICAL_PATH.read_text(encoding="utf-8")
    setup_none = next(l for l in text.splitlines()
                      if l.strip().startswith("4. Else: set `TRACKER=none`."))
    assert "TRACKER_STATE_DIAGNOSTIC" not in setup_none


# ---------------------------------------------------------------------------
# SC3 part 1 - count-zero: ds-ticket-status-sync.md never constructs a
# target_state of $TRACKER_STATE_DONE.
# ---------------------------------------------------------------------------

def test_ac3_status_sync_has_zero_tracker_state_done_occurrences():
    text = STATUS_SYNC_PATH.read_text(encoding="utf-8")
    assert text.count("TRACKER_STATE_DONE") == 0
    assert text.count("TRACKER_STATE_DEV_COMPLETE") >= 4   # non-vacuity


# ---------------------------------------------------------------------------
# SC3 part 2 - widened, narrowed, AND universe-closed target-shape scan.
#
# R3's mechanism, stated honestly: "No automatic code path in AE constructs
# a target_state of $TRACKER_STATE_DONE. Verifiable by exhaustive search,
# not by inspection of the changed sites alone." The scan DERIVES its file
# set from the tree instead of hardcoding it, and asserts the derived set
# matches the expected one - a seventh content/** file acquiring
# TRACKER_STATE_ fails the test loudly instead of being silently unscanned.
# ---------------------------------------------------------------------------

_STATE_TOKEN = r"(?:IN_PROGRESS|IN_REVIEW|QA|DEV_COMPLETE|BLOCKED|DONE)"
TARGET_RE = re.compile(
    r"target(?:_state)?`?:\s*`?\$?(TRACKER_STATE_" + _STATE_TOKEN + r")\b"
)

# Derived, not hardcoded: every content/ file that names any TRACKER_STATE_
# variable at all. A grep of a hardcoded list can only confirm the members
# already in it, never surface the one that is missing. Measured against the
# live tree: SEVEN files, not three. The last three match only on the literal
# TRACKER_STATE_* inside the tracker_state_diagnostic and pending_merge_sweep
# toggle descriptions; they contain zero TARGET_RE matches before or after
# this change, so including them widens the universe without changing the
# scan's outcome. content/references/events-log.md (DS-163) documents the W1
# `tracker_writeback` breadcrumb's `target_state` field descriptively
# ("the resolved `$TRACKER_STATE_IN_PROGRESS` value)") with no colon between
# `target_state` and the value, so it also contributes zero TARGET_RE matches.
EXPECTED_TRACKER_STATE_FILES = {
    "content/commands/ds-implement-ticket.md",
    "content/commands/ds-init-project.md",
    "content/commands/ds-ticket-status-sync.md",
    "content/commands/ds-wrap.md",
    "content/references/conventions-detail.md",
    "content/references/events-log.md",
    "content/references/risk-config-and-tiers.md",
    "content/references/tracker-writeback.md",
}


def _content_files_naming_tracker_state():
    out = set()
    for p in sorted((REPO_ROOT / "content").rglob("*.md")):
        if "TRACKER_STATE_" in p.read_text(encoding="utf-8"):
            out.add(p.relative_to(REPO_ROOT).as_posix())
    return out


def test_ac3_target_scan_universe_is_closed():
    """R3 says 'verifiable by exhaustive search'. This is what makes the
    search exhaustive over the prose surface: the scanned file set is
    DERIVED from the tree, and a new content/ file naming TRACKER_STATE_
    fails here rather than escaping the scan below unnoticed.
    """
    found = _content_files_naming_tracker_state()
    assert found, "universe derivation found no files - the glob is broken"
    assert found == EXPECTED_TRACKER_STATE_FILES, (
        "the set of content/ files naming TRACKER_STATE_ changed; add the new "
        "file to EXPECTED_TRACKER_STATE_FILES and confirm the target-shape "
        f"scan covers it. found={sorted(found)}"
    )


def test_ac3_no_automatic_writeback_targets_terminal_done():
    hits = []
    for rel in sorted(EXPECTED_TRACKER_STATE_FILES):
        lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            for m in TARGET_RE.finditer(line):
                hits.append((rel, i, m.group(1), line))

    # Non-vacuity 1: a pattern typo that matches nothing must fail, not pass.
    assert hits, "target-shape scan collected zero lines - the pattern is broken"

    # Non-vacuity 2: the WIDENING itself must be verified. Phase 11 passes its
    # target as a backticked `target_state`: `$TRACKER_STATE_QA`. The narrower
    # pre-DS-117 pattern (colon abutting target_state, no backtick) missed that
    # line entirely, so a future edit retargeting Phase 11 at
    # $TRACKER_STATE_DONE would have passed this suite green. Asserting on the
    # SHAPE rather than a line number keeps this drift-proof.
    assert any("`target_state`:" in line for _, _, _, line in hits), (
        "widened target scan never matched a backticked `target_state`: form - "
        "the widening is unverified and Phase 11's target line is invisible"
    )

    # Non-vacuity 3: the scan must see the NEW state, or the edit is missing.
    assert any(s == "TRACKER_STATE_DEV_COMPLETE" for _, _, s, _ in hits), \
        "target-shape scan never saw TRACKER_STATE_DEV_COMPLETE - pattern or edit is wrong"

    offenders = [(f, i) for f, i, s, _ in hits if s == "TRACKER_STATE_DONE"]
    assert not offenders, f"automatic writeback target still fires terminal Done at {offenders}"


def test_ac3_wrap_gate_resolution_list_entry_survives_scan_unmatched():
    """ds-wrap.md's Gate line legitimately retains TRACKER_STATE_DONE as a
    resolution-list entry, not a writeback target. It is now inside the
    scanned universe (proving the exemption rather than assuming it by
    omission), and it must not match TARGET_RE - it carries no target_state/
    target: shape."""
    text = WRAP_PATH.read_text(encoding="utf-8")
    assert "TRACKER_STATE_DONE" in text, (
        "ds-wrap.md's Gate resolution list should still name TRACKER_STATE_DONE"
    )
    hits = [
        (i, line) for i, line in enumerate(text.splitlines(), 1)
        for m in TARGET_RE.finditer(line)
        if m.group(1) == "TRACKER_STATE_DONE"
    ]
    assert not hits, f"ds-wrap.md's Gate line unexpectedly matched TARGET_RE: {hits}"


# ---------------------------------------------------------------------------
# Setup branch lines, located by their stable leading literals.
# ---------------------------------------------------------------------------

BRANCH_ANCHORS = {
    "jira": "1. If a `## Tracker` section exists in `AGENTS.md` and contains `TRACKER: jira`",
    "linear": "3. Else if a `## Linear` section exists:",
    "none": "4. Else: set `TRACKER=none`.",
}


def _setup_branch_lines(text: str) -> dict:
    found = {}
    for name, anchor in BRANCH_ANCHORS.items():
        found[name] = next(
            (l for l in text.splitlines() if l.strip().startswith(anchor)), None
        )
    return found


# ---------------------------------------------------------------------------
# SC1 - declarable on all four surfaces.
# ---------------------------------------------------------------------------

def test_dev_complete_declarable_on_all_four_surfaces():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    branches = _setup_branch_lines(text)
    assert branches["jira"] is not None, "Jira Setup branch line not found"
    assert "JIRA_STATE_DEV_COMPLETE" in branches["jira"]
    assert branches["linear"] is not None, "Linear Setup branch line not found"
    assert "State Dev Complete:" in branches["linear"]
    assert branches["none"] is not None, "TRACKER=none Setup branch line not found"
    assert "TRACKER_DEV_COMPLETE_DECLARED=false" in branches["none"], (
        "TRACKER=none must set the declared flag false unconditionally - "
        "nothing is declarable on this branch"
    )

    tracker_bin = (REPO_ROOT / "bin" / "agentic-tracker").read_text(encoding="utf-8")
    assert '"state_dev_complete"' in tracker_bin, (
        "the .agentic/tracker.yml overlay must accept a state_dev_complete key"
    )


# ---------------------------------------------------------------------------
# SC2 - default behavior for a declares-nothing project is unchanged: every
# branch states the inherited default, qualified as the resolved Done value.
# ---------------------------------------------------------------------------

def test_dev_complete_default_is_resolved_done_on_every_setup_branch():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    branches = _setup_branch_lines(text)
    for name in ("jira", "linear"):
        line = branches[name]
        assert line is not None, f"{name} Setup branch line not found"
        assert "the RESOLVED `TRACKER_STATE_DONE` value for this project" in line, (
            f"{name} branch must default TRACKER_STATE_DEV_COMPLETE to the "
            "resolved Done value, not a bare literal"
        )
    none_line = branches["none"]
    assert none_line is not None, "TRACKER=none Setup branch line not found"
    assert (
        'TRACKER_STATE_DEV_COMPLETE="Done"` (the resolved `TRACKER_STATE_DONE` value'
        in none_line
    ), "TRACKER=none branch must state its Dev Complete default is the resolved Done value"


# ---------------------------------------------------------------------------
# M1 pin - the flag the Helper pass-list and step 4.d.iv both consume must
# actually be resolved in Setup, or SC4 regresses silently.
# ---------------------------------------------------------------------------

def test_setup_resolves_dev_complete_declared_on_every_branch():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    branches = _setup_branch_lines(text)
    for name, line in branches.items():
        # Non-vacuity: an anchor that stopped matching fails rather than
        # passing.
        assert line is not None, f"{name} Setup branch line not found"
        assert "TRACKER_DEV_COMPLETE_DECLARED" in line, (
            f"{name} branch must resolve TRACKER_DEV_COMPLETE_DECLARED"
        )
    for name in ("jira", "linear"):
        assert "BEFORE applying the inherited default" in branches[name], (
            f"{name} branch must evaluate the presence test BEFORE the "
            "inherited default is applied"
        )
    assert "TRACKER_DEV_COMPLETE_DECLARED=false" in branches["none"]


# ---------------------------------------------------------------------------
# M5 pin - the Setup prose is the only guard against the "declared but no
# pipeline_order, and the lane sits before QA" backward-move hazard.
# ---------------------------------------------------------------------------

def test_setup_instructs_declaring_pipeline_order_for_an_early_lane():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    branches = _setup_branch_lines(text)
    jira_line = branches["jira"]
    linear_line = branches["linear"]
    assert jira_line is not None and linear_line is not None
    assert "sits BEFORE your QA lane" in jira_line
    assert "JIRA_PIPELINE_ORDER" in jira_line
    assert "sits BEFORE your QA lane" in linear_line
    assert "Pipeline order" in linear_line


# ---------------------------------------------------------------------------
# SC3 prose - no shipped prose still promises an automatic terminal Done
# transition. Each repaired phrase is paired with a positive assertion that
# its dev-complete replacement is present, so a deletion cannot pass.
# ---------------------------------------------------------------------------

def test_no_shipped_prose_promises_an_automatic_terminal_done():
    status_sync_text = STATUS_SYNC_PATH.read_text(encoding="utf-8")
    implement_ticket_text = CANONICAL_PATH.read_text(encoding="utf-8")

    # 1. ds-ticket-status-sync.md's opening description.
    assert "leaves the final Done transition unfired" not in status_sync_text
    assert "leaves the final dev-complete transition unfired" in status_sync_text

    # 2. ds-implement-ticket.md's W7 operator-facing echo note.
    assert (
        'the Done transition is pushed automatically by the session-start '
        'pending-merge sweep' not in implement_ticket_text
    )
    assert (
        "the dev-complete transition is pushed automatically by the "
        "session-start pending-merge sweep within one session boot of the merge"
        in implement_ticket_text
    )

    # 3. ds-implement-ticket.md's W7 Note (the human-merge-path fallback
    # explanation).
    assert (
        "the dev-complete transition is pushed automatically by the "
        "session-start pending-merge sweep instead"
        in implement_ticket_text
    )

    # 4. ds-ticket-status-sync.md's "writes a ticket to Done only via" guard
    # sentence.
    assert "writes a ticket to Done only via" not in status_sync_text
    assert (
        "writes a ticket to its dev-complete state "
        "(`$TRACKER_STATE_DEV_COMPLETE`) only via"
        in status_sync_text
    )

    # 5. ds-ticket-status-sync.md's open-PR block preamble.
    assert "Before mapping a merged candidate to Done, run" not in status_sync_text
    assert (
        "Before mapping a merged candidate to the dev-complete state, run"
        in status_sync_text
    )


# ---------------------------------------------------------------------------
# SC4 - the forward-only guard correctly ranks a non-terminal dev-complete.
# ---------------------------------------------------------------------------

def test_guard_ranks_dev_complete_last_by_default(canonical_block):
    assert (
        "the ordered sequence `IN_PROGRESS` (rank 0) < `IN_REVIEW` (rank 1) "
        "< `QA` (rank 2) < `DEV_COMPLETE` (rank 3)"
        in canonical_block
    )


def test_guard_names_collision_resolution(canonical_block):
    assert "**Name collision.**" in canonical_block
    idx = canonical_block.index("**Name collision.**")
    window = canonical_block[idx:idx + 600]
    assert "resolves to the HIGHEST such rank" in window
    assert "This rule applies only to a DECLARED `DEV_COMPLETE`" in window


# ---------------------------------------------------------------------------
# SC2/R7 - the round-2 Major pin: an inherited dev-complete carries no
# pipeline rank, closed-vocabulary swept against 8 distinct phrasings.
# ---------------------------------------------------------------------------

FORBIDDEN_INHERITED_RANK_PHRASES = (
    "inherited dev-complete is ranked",
    "inherited value is ranked",
    "an inherited dev-complete ranks",
    "an inherited value ranks",
    "inherited dev-complete participates",
    "an inherited one is ranked",
    "regardless of whether it was declared",
    "declared or inherited",
)


def test_guard_states_inherited_dev_complete_carries_no_rank():
    text = HELPER_PATH.read_text(encoding="utf-8")
    block = _extract_block(text)

    # Non-vacuity: assert the block is non-empty and contains
    # dev_complete_declared FIRST, so an extraction failure cannot pass the
    # negative half trivially.
    assert block, "canonical block extraction returned empty"
    assert "dev_complete_declared" in block

    assert (
        "participates in this sub-rank ONLY when the project DECLARED a "
        "dev-complete field"
        in block
    )
    assert "Absent or unparseable is treated as `false`" in block

    lowered = block.lower()
    offenders = [p for p in FORBIDDEN_INHERITED_RANK_PHRASES if p in lowered]
    assert not offenders, (
        "the pinned block grants an inherited dev-complete a pipeline rank "
        f"via forbidden phrasing: {offenders}"
    )


def test_dev_complete_declared_param_in_both_pass_lists(canonical_block):
    # Helper pass-list, scoped to the "3. Pass to the subagent:" window.
    start = canonical_block.index("3. Pass to the subagent:")
    end = canonical_block.index("**Subagent responsibilities", start)
    helper_window = canonical_block[start:end]
    assert "dev_complete_declared" in helper_window, (
        "dev_complete_declared missing from the Tracker Writeback Helper pass-list"
    )

    # Phase 11 pass-list, scoped to its own Inputs window.
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    phase11_start = text.index("**Inputs (resolved by conductor and passed in):**")
    phase11_end = text.index(
        "For the full brief shape governing this subagent", phase11_start
    )
    phase11_window = text[phase11_start:phase11_end]
    assert "dev_complete_declared" in phase11_window, (
        "dev_complete_declared missing from Phase 11's own Inputs pass-list"
    )


def test_phase_11_pipeline_order_bullet_states_four_token_arity():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    anchor = "- `pipeline_order`: the ordered list of pipeline tokens resolved once in Setup (`TRACKER_PIPELINE_ORDER`)"
    matching = [l for l in text.splitlines() if anchor in l]
    assert matching, "Phase 11 pipeline_order bullet not found"
    assert len(matching) == 1, f"expected exactly one Phase 11 pipeline_order bullet, found {len(matching)}"
    line = matching[0]
    assert "4 tokens" in line
    assert "3-element" not in line


# ---------------------------------------------------------------------------
# pending_merge_sweep description - 6 prose sites plus docs/index.html.
# ---------------------------------------------------------------------------

_PENDING_MERGE_SWEEP_SITES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "configuration-reference.md",
    REPO_ROOT / "docs" / "components.md",
    REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
    REPO_ROOT / "content" / "references" / "conventions-detail.md",
    REPO_ROOT / "content" / "commands" / "ds-init-project.md",
]

_PENDING_MERGE_SWEEP_NEW = (
    "the session-start pending-merge sweep that pushes the dev-complete "
    "transition (`TRACKER_STATE_DEV_COMPLETE`, which defaults to the "
    "resolved `TRACKER_STATE_DONE` value) to the tracker once a ticket's "
    "PR merges"
)
_PENDING_MERGE_SWEEP_OLD = (
    "the session-start pending-merge sweep that pushes the Done transition "
    "to the tracker once a ticket's PR merges"
)


@pytest.mark.parametrize("path", _PENDING_MERGE_SWEEP_SITES)
def test_pending_merge_sweep_description_names_dev_complete(path):
    text = path.read_text(encoding="utf-8")
    assert _PENDING_MERGE_SWEEP_NEW in text, (
        f"{path.relative_to(REPO_ROOT)} missing the dev-complete "
        "pending_merge_sweep description"
    )
    assert text.count(_PENDING_MERGE_SWEEP_OLD) == 0, (
        f"{path.relative_to(REPO_ROOT)} still carries the stale Done-only "
        "pending_merge_sweep description"
    )


def test_pending_merge_sweep_description_names_dev_complete_docs_index():
    text = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "pushes the dev-complete transition once a ticket's PR merges" in text
    assert text.count("pushes the Done transition once a ticket's PR merges") == 0


# ---------------------------------------------------------------------------
# Enumeration audit: every "N of the M TRACKER_STATE_* values"-shaped
# sentence bumped from 5 to 6.
# ---------------------------------------------------------------------------

_ENUMERATION_AUDIT_ROWS = [
    (STATUS_SYNC_PATH, "the 6 `TRACKER_STATE_*` values", 1, "the 5 `TRACKER_STATE_*` values"),
    (STATUS_SYNC_PATH, "all 6 `TRACKER_STATE_*` values", 1, "all 5 `TRACKER_STATE_*` values"),
    (STATUS_SYNC_PATH, "(the 6 values resolved in Preflight)", 2, "(the 5 values resolved in Preflight)"),
    (CANONICAL_PATH, "For each of the 6 resolved", 1, "For each of the 5 resolved"),
    (WRAP_PATH, "(the 6 values resolved in the Gate above)", 1, "(the 5 values resolved in the Gate above)"),
]


@pytest.mark.parametrize("path,new_phrase,expected_count,old_phrase", _ENUMERATION_AUDIT_ROWS)
def test_enumeration_audit_bumped_from_five_to_six(path, new_phrase, expected_count, old_phrase):
    text = path.read_text(encoding="utf-8")
    assert text.count(new_phrase) == expected_count, (
        f"{path.relative_to(REPO_ROOT)}: expected {expected_count} occurrence(s) "
        f"of {new_phrase!r}, found {text.count(new_phrase)}"
    )
    assert text.count(old_phrase) == 0, (
        f"{path.relative_to(REPO_ROOT)}: stale phrase {old_phrase!r} still present"
    )


# ---------------------------------------------------------------------------
# tracker_state_values byte-identity between the Helper pass-list and the
# Phase 11 Inputs site. The extraction target is the backticked JSON
# literal, not the line - the two lines differ by prefix and trailing prose.
# ---------------------------------------------------------------------------

TSV_LITERAL_RE = re.compile(r"`(\{ \"IN_PROGRESS\":.*?\"\$TRACKER_STATE_DONE\" \})`")


def test_tracker_state_values_literal_identical_at_both_sites():
    helper_text = HELPER_PATH.read_text(encoding="utf-8")
    helper_line = next(l for l in helper_text.splitlines()
                       if l.startswith("   - `tracker_state_values`: `{ \"IN_PROGRESS\""))
    phase11_text = CANONICAL_PATH.read_text(encoding="utf-8")
    phase11_line = next(l for l in phase11_text.splitlines()
                        if l.startswith("> - `tracker_state_values`: `{ \"IN_PROGRESS\""))
    a = TSV_LITERAL_RE.search(helper_line)
    b = TSV_LITERAL_RE.search(phase11_line)
    # Non-empty guard BEFORE equality: two identically-drifted sites that
    # both stopped matching would otherwise compare "" == "" and pass.
    assert a, "tracker_state_values literal not found at the Helper pass-list site"
    assert b, "tracker_state_values literal not found at the Phase 11 site"
    assert "DEV_COMPLETE" in a.group(1), "Helper literal missing DEV_COMPLETE"
    assert a.group(1) == b.group(1), (
        "the tracker_state_values literal must be byte-identical at the "
        "Tracker Writeback Helper pass-list and Phase 11 Inputs sites"
    )
