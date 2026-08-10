#!/usr/bin/env python3
"""
Spec tests for the Tracker Writeback Helper's forward-only guard ranking rule.

DS split unit 1: the "## Tracker Writeback Helper" block itself moved out of
content/commands/ds-implement-ticket.md into content/references/tracker-
writeback.md behind a trigger-pointer. Tests that examine the block's own
content now read HELPER_PATH; tests that examine content that stayed inline
(Setup, Phase 2c, Phase 11's own Inputs list) still read CANONICAL_PATH.

Covers:
  - (a) the canonical block contains the pipeline sub-rank prose, the fixed
    IN_PROGRESS(0) < IN_REVIEW(1) < QA(2) sequence, the Blocked
    always-permitted-both-directions language, the tracker_state_values
    parameter, the never-reads-cache invariant, single-L 'canceled',
    'duplicate', the field-absence phrase, and the fire-and-forget-vs-
    awaiting-caller distinction.
  - (a2) semantic-inversion coverage: the central pipeline_rank comparator is
    literally `<` (not `>` or `<=`), and steps 4.a/4.b/4.c/4.d.i/4.d.ii/4.d.iii/
    4.d.iv resolve to the specific permit/skip outcome the algorithm requires,
    the pipeline sequence (default IN_PROGRESS < IN_REVIEW < QA, declarable
    per Gap 2 below) and the Linear category-rank sequence are pinned as
    ORDERED literals (not just unordered token presence), and the invocation
    contract's tracker_state_values and forward_only_guard parameters are
    checked against a scoped window (the pass-list itself), not the whole
    block. These pin outcomes byte-identity (b) cannot catch a reversal
    applied uniformly to the canonical block and every adapter copy at once.
  - (b) the canonical block is byte-identical across all adapter copies.
  - (c) a spelling heuristic: any line in the canonical block that mentions
    3+ of the category-rank tokens (backlog/unstarted/started/completed/
    duplicate) must spell any cancel(l)ed-shaped token on that line single-L,
    unless immediately followed by a "(double L)" parenthetical.
  - (d) content/commands/ds-ticket-triage.md's already-correct single-L
    enumeration is untouched.
  - (e) content/commands/ds-ticket-status-sync.md no longer restates the
    ranking inline, and each of its 2 tracker-writeback spawn sites carries
    an explicit forward_only_guard: true and tracker_state_values alongside
    target_state (checked via a bounded window after the spawn-site sentence,
    not same-line co-location).
  - (f) content/commands/ds-wrap.md's Part F Gate line resolves the 5
    TRACKER_STATE_* values (regression guard against a future edit silently
    dropping the Gate extension).
  - (g) Gap 1 (loud diagnostic on a misconfigured TRACKER_STATE_* name) and
    Gap 2 (declarable pipeline order) - tracker-state-reconciliation work,
    roughly 50 assertions across both gaps:
      * Gap 1: the diagnostic-enrichment sub-step runs strictly AFTER a
        transition attempt (no happy-path round trip), its own failure is
        always swallowed, Jira relabels from the already-fetched
        jira_get_transitions result (no new call), Linear's relabel check
        only inspects live states after its own list_workflow_states call
        has itself succeeded, the return-payload schema's status enum union
        specifically (not just the line) carries skipped_unconfigured_state,
        the failure-logging line defines both FAILED and SKIPPED forms, the
        Phase 2c warning no longer claims a silent skip, the Setup/pass-list/
        Phase 11 additions for TRACKER_STATE_DIAGNOSTIC/diagnostic_enabled/
        linear_team_key reference step 5 (never a stale step 6), the
        ds-ticket-status-sync.md and ds-wrap.md comment-gate clauses are
        byte-identical across files (with a non-empty guard so a
        simultaneous drop in both files cannot pass vacuously on "" == ""),
        both files' output blocks carry exactly 3 indented line forms, the
        single-ticket-mode Output section prints the diagnostic on its own
        line, the 8-site toggle-doc-sync checklist and bin/agentic-config
        registration (plus its functional CLI round-trip in
        bin/tests/test_agentic_config.py) hold, § Pending-merge sweep (g)
        preserves closed_unmerged and adds the skipped_unconfigured_state ->
        retryable-failing mapping, and a dedicated guard sweeps the whole
        block for substitution-indicating vocabulary (closest match/nearest/
        substitut*) to pin that the mechanism never writes an unconfigured
        state.
      * Gap 2: the pass-list's pipeline_order bullet is line-scoped and
        references TRACKER_PIPELINE_ORDER/step 4.d.iv; Setup resolves the
        override on both the Jira and Linear paths (including the
        Linear-shaped `## Tracker` path, which previously only inherited
        state-name overrides by cross-reference) with a stated default and
        a malformed-value fallback; TRACKER=none sets the default
        explicitly; the print summary gains a TRACKER_PIPELINE_ORDER line;
        step 4.d.iv's rank source is pipeline_order (not a hardcoded
        literal), while its two sibling bullets remain byte-identical to
        origin/main; the "Rejected: fully tracker-derived pipeline order"
        rationale paragraph is present; Phase 11's own Inputs list and
        summary sentence, ds-ticket-status-sync.md's Preflight and both
        spawn sites, and ds-wrap.md's Part F Gate/Reconcile all resolve and
        pass pipeline_order; and ds-init-project.md's two AGENTS.md
        templates show the commented-out override line under its own
        heading.
  - (h) DS-117 (split dev-complete from terminal Done): the canonical block's
    pipeline sequence is extended with `DEV_COMPLETE` (rank 3); the pass-list
    scope check for `pipeline_order` still holds after the insertion; the
    Setup Jira/Linear pipeline-order sentences state the new warning text
    naming DEV_COMPLETE as an optional token; step 4.d.iv's rank-source line
    still names `pipeline_order` (not a hardcoded literal) and now also
    covers the implied-trailing-DEV_COMPLETE rule; `ds-wrap.md`'s Part F
    Gate line resolves `TRACKER_STATE_DEV_COMPLETE` alongside the other 5
    values; and the `ds-init-project.md` AGENTS.md templates show both the
    Dev Complete override line and the pipeline-order override line together
    under one anchored window per template. The remaining DS-117 pins (the
    bare-`TRACKER_STATE_` prefix trap, the AC-3 target-shape scan, the
    inherited-carries-no-rank guard, and the tracker_state_values
    byte-identity check) live in the new bin/tests/test_tracker_dev_complete_spec.py.

Run with: python3 -m pytest bin/tests/test_tracker_writeback_ranking_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# CANONICAL_PATH still holds content that was NOT moved out of
# ds-implement-ticket.md (Setup, Phase 2c, Phase 11's own Inputs list) -
# tests that examine those sections keep reading it. HELPER_PATH is the
# split destination for the "## Tracker Writeback Helper" block itself
# (content/references/tracker-writeback.md, DS split unit 1) - tests that
# examine the block's own content read HELPER_PATH instead.
CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
HELPER_PATH = REPO_ROOT / "content" / "references" / "tracker-writeback.md"

# All adapter copies expected to carry a byte-identical extraction of the
# "## Tracker Writeback Helper" block, post-split. .cursor/build.sh,
# .gemini/build.sh, and .copilot/build.sh each hardlink their references/
# files from content/references/ via `ln` (same-inode ONLY after that
# build.sh has run locally - git itself does not track hardlinks, so a
# fresh clone or a git worktree checkout gives content/references/,
# .cursor/references/, .gemini/references/, and .copilot/references/ four
# distinct inodes carrying an identical git blob until rebuilt);
# .codex/references/ files are per-file SYMLINKS into content/references/
# (git mode 120000) instead. Kept as separate entries because the aliasing
# mechanism is a build-time property that could change, not because these
# are 5 independent surfaces - all five entries resolve to a single
# build-time source (content/references/), so this list asserts over
# exactly one independent surface.
# .claude/skills/dinostack/references/ is a symlink DIR (not a
# per-file symlink) and is deliberately excluded.
ADAPTER_PATHS = [
    HELPER_PATH,
    REPO_ROOT / ".codex" / "references" / "tracker-writeback.md",
    REPO_ROOT / ".cursor" / "references" / "tracker-writeback.md",
    REPO_ROOT / ".gemini" / "references" / "tracker-writeback.md",
    REPO_ROOT / ".copilot" / "references" / "tracker-writeback.md",
]

# COMMAND_MIRROR_PATHS below lists 7 paths, but only 6 are independent
# committed mirrors that no longer carry the "## Tracker Writeback Helper"
# block itself (it moved out to HELPER_PATH) and must still carry a pointer
# to it: .codex/commands/ds-implement-ticket.md is a git symlink (mode
# 120000) resolving to content/commands/ds-implement-ticket.md, the same
# source CANONICAL_PATH already reads - asserting on it re-checks the
# source, not an independent copy. So this test asserts over 6 independent
# committed mirrors plus 1 (redundant but harmless) source-file assertion,
# not "7 mirrors." check-adapter-sync diffs regenerated-vs-committed content -
# both operands come from the same build run, so a build regression that
# drops the pointer produces identical operands and stays green; this
# assertion tests the property that gate structurally cannot.
#
# POINTER_TEXT is anchored on the extraction-site sentence fragment, not the
# bare "content/references/tracker-writeback.md" path - that path string
# recurs 8x (14x in .hermes/SKILL.md) across other cross-references inside
# each mirror's canonical block, so a literal-path anchor cannot go false
# even when the extraction-site pointer line itself is deleted. Verified
# unique (exactly 1 occurrence per mirror) before adoption.
POINTER_TEXT = "Full reference (invocation contract"

COMMAND_MIRROR_PATHS = [
    REPO_ROOT / ".claude" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".codex" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".cursor" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".opencode" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".github" / "prompts" / "ds-implement-ticket.prompt.md",
    REPO_ROOT / ".openclaw" / "skills" / "ds-implement-ticket" / "SKILL.md",
    REPO_ROOT / ".hermes" / "SKILL.md",
]

HEADING = "## Tracker Writeback Helper"

# Category-rank tokens that trigger the spelling heuristic in (c).
_TRIGGER_TOKENS = ("backlog", "unstarted", "started", "completed", "duplicate")
_CANCEL_RE = re.compile(r"cancell?ed", re.IGNORECASE)


def _extract_block(text: str) -> str:
    """Extract the '## Tracker Writeback Helper' section: from the exact
    heading line up to (exclusive) the next line that is itself a top-level
    '## ' heading. Matches on an exact-stripped heading line so inline
    backtick mentions of the same phrase elsewhere in the file (e.g. in a
    fused multi-command embed like .hermes/SKILL.md) are not mistaken for
    the heading itself."""
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
# (a) canonical block content assertions
# ---------------------------------------------------------------------------

def test_canonical_block_contains_pipeline_subrank_language(canonical_block):
    assert "pipeline sub-rank" in canonical_block


def test_canonical_block_contains_fixed_pipeline_ranks(canonical_block):
    assert "IN_PROGRESS" in canonical_block and "rank 0" in canonical_block
    assert "IN_REVIEW" in canonical_block and "rank 1" in canonical_block
    assert "QA" in canonical_block and "rank 2" in canonical_block
    assert "DEV_COMPLETE" in canonical_block and "rank 3" in canonical_block


def test_canonical_block_permits_blocked_both_directions(canonical_block):
    # target is BLOCKED -> permit unconditionally
    assert "matches `BLOCKED`: **permit** unconditionally" in canonical_block
    # both directions must be covered: target==BLOCKED and current==BLOCKED
    blocked_permits = re.findall(r"matches `BLOCKED`: \*\*permit\*\* unconditionally", canonical_block)
    assert len(blocked_permits) >= 2, "expected both target==BLOCKED and current==BLOCKED permit clauses"


def test_canonical_block_has_tracker_state_values_param(canonical_block):
    assert "tracker_state_values" in canonical_block


def test_phase_11_input_list_includes_tracker_state_values():
    # Phase 11 enumerates its own inputs rather than inheriting the shared
    # "## Tracker Writeback Helper" invocation-contract list, so it needs its
    # own separate tracker_state_values entry (Step 3 of the spec). Locate the
    # Phase 11 QA-writeback spawn brief's `target_state` line and confirm
    # tracker_state_values appears in the same Inputs block.
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    anchor = '`target_state`: `$TRACKER_STATE_QA`'
    assert anchor in text, "Phase 11 spawn brief target_state line not found"
    idx = text.index(anchor)
    window = text[max(0, idx - 400):idx + 400]
    assert "tracker_state_values" in window, (
        "Phase 11's own Inputs list is missing tracker_state_values alongside target_state/forward_only_guard"
    )


def test_canonical_block_never_reads_cache_invariant(canonical_block):
    assert ".agentic/tracker-states.json" in canonical_block
    assert "never reads" in canonical_block.lower()


def test_canonical_block_single_l_canceled(canonical_block):
    assert "canceled" in canonical_block


def test_canonical_block_has_duplicate_terminal_state(canonical_block):
    assert "duplicate" in canonical_block


def test_canonical_block_field_absence_phrase(canonical_block):
    assert "pre-read succeeded but response omitted" in canonical_block


def test_canonical_block_fire_and_forget_vs_awaiting_caller(canonical_block):
    assert "Fire-and-forget call sites" in canonical_block
    assert "Callers that await the result" in canonical_block


# ---------------------------------------------------------------------------
# (a2) semantic-inversion coverage - literal comparison/branch outcomes.
# Byte-identity (b) alone cannot catch a reversal applied uniformly to the
# canonical block AND all 9 adapter copies together (the shape a real edit
# plus build-all.sh produces); these assertions pin the literal outcome of
# each branch so a flipped comparator or swapped permit/skip fails here.
# ---------------------------------------------------------------------------

def test_canonical_block_pipeline_rank_comparison_is_strictly_less_than(canonical_block):
    assert (
        "**permit** iff `pipeline_rank(current) < pipeline_rank(target)`" in canonical_block
    ), "the central pipeline-rank comparison must be permit iff current < target"


def test_canonical_block_step_4a_terminal_current_state_skips(canonical_block):
    # Line-scoped (not a `.*?` span over the whole block): a wildcard gap that
    # can cross newlines would happily jump to some LATER, unrelated
    # "**skip**" elsewhere in the block and pass even if this exact branch
    # were flipped to permit - exactly the vacuous-guard failure mode these
    # tests exist to close.
    step_4a_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("a. If current state is terminal")
    ]
    assert step_4a_lines, "step 4.a (terminal current state) line not found"
    assert all("**skip** unconditionally" in line for line in step_4a_lines), (
        "step 4.a (terminal current state) must resolve to skip"
    )


def test_canonical_block_step_4c_backward_category_move_skips(canonical_block):
    assert re.search(
        r"c\. If `category_rank\(current\) > category_rank\(target\)`: \*\*skip\*\*",
        canonical_block,
    ), "step 4.c (backward category move) must resolve to skip"


def test_canonical_block_step_4d_ii_and_iii_permit(canonical_block):
    assert re.search(
        r"ii\. Else if `target_state` matches `BLOCKED`: \*\*permit\*\* unconditionally",
        canonical_block,
    ), "step 4.d.ii (target is BLOCKED) must resolve to permit"
    assert re.search(
        r"iii\. Else if the CURRENT state's name matches `BLOCKED`: \*\*permit\*\* unconditionally",
        canonical_block,
    ), "step 4.d.iii (current is BLOCKED) must resolve to permit"


def test_canonical_block_step_4d_i_idempotent_skips(canonical_block):
    # Line-scoped, same rationale as 4.a above: a `.*?`/DOTALL span could
    # jump forward to an unrelated later "**skip**" and pass even if this
    # exact branch were flipped to permit.
    step_4d_i_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith(
            "- i. If `target_state`'s name case-insensitive-exact-matches the CURRENT state's name"
        )
    ]
    assert step_4d_i_lines, "step 4.d.i (idempotent no-op) line not found"
    assert all("**skip**" in line for line in step_4d_i_lines), (
        "step 4.d.i (idempotent no-op, target name == current name) must resolve to skip"
    )


def test_canonical_block_step_4b_forward_category_move_permits(canonical_block):
    # No DOTALL, no wildcard spanning lines - `category_rank(current) <
    # category_rank(target)` is a unique literal phrase (its ">" counterpart
    # is step 4.c, tested separately below), so this cannot match anywhere
    # but the intended 4.b branch.
    assert re.search(
        r"b\. If `category_rank\(current\) < category_rank\(target\)`: \*\*permit\*\*",
        canonical_block,
    ), "step 4.b (forward category move) must resolve to permit"


def test_canonical_block_step_4d_iv_fallthrough_skips(canonical_block):
    # Line-scoped: the "Otherwise (at least one name does not resolve..." bullet
    # is a single (long) markdown line in the source file. Scoping the check to
    # that exact line - rather than a block-wide substring or a cross-line
    # wildcard - means a flip of THIS branch's verdict to permit cannot be
    # masked by the "**skip**"/"**permit**" tokens that appear in neighboring
    # branches or in the fire-and-forget/awaiting-caller prose later in the
    # same sentence.
    fallthrough_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith(
            "- Otherwise (at least one name does not resolve to a pipeline rank"
        )
    ]
    assert fallthrough_lines, "step 4.d.iv fall-through (unmatched pipeline rank) line not found"
    assert all("**skip** unconditionally" in line for line in fallthrough_lines), (
        "step 4.d.iv fall-through (name does not resolve to a pipeline rank) must resolve to skip unconditionally"
    )


def test_canonical_block_pipeline_sequence_is_ordered_literal(canonical_block):
    # M13: an earlier version of this suite only checked unordered token/rank
    # presence (test_canonical_block_contains_fixed_pipeline_ranks above),
    # which a full permutation of the sequence (e.g. QA(0) < IN_REVIEW(1) <
    # IN_PROGRESS(2)) satisfies without any diff to that test. Pin the exact
    # ordered clause as one literal substring - a permutation changes this
    # exact string and cannot pass.
    #
    # Gap 2 (declarable pipeline order): the wording changed from "the fixed
    # pipeline sequence" to "the ordered sequence" since the sequence is now
    # only the DEFAULT (a project may override it via JIRA_PIPELINE_ORDER /
    # Pipeline order:), not a hardcoded constant. DS-117 extends the ordered
    # literal itself with a fourth, optional DEV_COMPLETE token at rank 3.
    assert (
        "the ordered sequence `IN_PROGRESS` (rank 0) < `IN_REVIEW` (rank 1) < `QA` (rank 2) < `DEV_COMPLETE` (rank 3)"
        in canonical_block
    ), "the pipeline sequence must be the literal ordered IN_PROGRESS(0) < IN_REVIEW(1) < QA(2) < DEV_COMPLETE(3) clause"


def test_canonical_block_category_rank_sequence_is_ordered_literal(canonical_block):
    # Same M13-class fix applied to the Linear category-rank order: pin the
    # ordered literal, not just presence of each token.
    assert (
        "`backlog` < `unstarted` < `started` < `completed` < `canceled` < `duplicate`"
        in canonical_block
    ), "the Linear category-rank sequence must be the literal ordered backlog<unstarted<started<completed<canceled<duplicate clause"


def test_spelling_heuristic_fires_on_at_least_one_line(canonical_block):
    # Regression against a silent-vacuity regression: the heuristic in
    # test_spelling_heuristic_single_l_on_trigger_lines only asserts the
    # ABSENCE of violations. If a future rewording of the trigger line ever
    # drops its category-rank-token count below the 3-token threshold, that
    # test would keep passing having checked zero lines. This asserts the
    # heuristic actually evaluates at least one qualifying line.
    triggered = any(
        sum(1 for tok in _TRIGGER_TOKENS if _token_present(line.lower(), tok)) >= 3
        for line in canonical_block.splitlines()
    )
    assert triggered, (
        "no line in the canonical block triggers the spelling heuristic "
        "(3+ category-rank tokens) - the heuristic is vacuous"
    )


# ---------------------------------------------------------------------------
# Invocation-contract pass-list scoping (M10/M11) - the block-wide substring
# checks in (a) above (test_canonical_block_has_tracker_state_values_param)
# pass even when the parameter is stripped from the pass-list itself, because
# the same token/phrase also appears in step 4's prose elsewhere in the block.
# These assertions scope the check to the pass-list window: from the literal
# "3. Pass to the subagent:" line up to (exclusive) the literal
# "**Subagent responsibilities" heading that immediately follows it. Both
# anchors are unique literal strings within the canonical block, so the
# window cannot expand to swallow unrelated later content.
# ---------------------------------------------------------------------------

def test_invocation_contract_pass_list_has_tracker_state_values_param(canonical_block):
    start = canonical_block.index("3. Pass to the subagent:")
    end = canonical_block.index("**Subagent responsibilities", start)
    pass_list_window = canonical_block[start:end]
    assert "tracker_state_values" in pass_list_window, (
        "tracker_state_values is missing from the invocation contract's pass-list (step 3) - "
        "block-wide presence alone is not sufficient, it also appears in step 4's prose"
    )


def test_invocation_contract_forward_only_guard_covers_every_writeback_caller(canonical_block):
    # M11: the broadened forward_only_guard line (covering ALL writeback
    # callers - the 7 new sites, Phase 11, and the awaiting callers, i.e. 3
    # modes of /ds-ticket-status-sync plus /ds-wrap Part F - not just the
    # original 7 new sites) had no regression test; reverting to the
    # narrower original phrasing passed the rest of the suite. Line-scoped on
    # the literal pass-list bullet.
    guard_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("- `forward_only_guard`: `true`")
    ]
    assert guard_lines, "forward_only_guard pass-list line not found"
    assert all(
        "for every writeback caller" in line and "awaiting callers" in line
        for line in guard_lines
    ), (
        "forward_only_guard pass-list line must cover every writeback caller "
        "(including the awaiting callers), not just the 7 new sites"
    )


# ---------------------------------------------------------------------------
# (b) byte-identity of the extracted block across all adapter copies
# ---------------------------------------------------------------------------

def test_block_byte_identical_across_adapters(canonical_block):
    missing = [p for p in ADAPTER_PATHS if not p.exists()]
    assert not missing, f"expected adapter files missing: {missing}"

    mismatches = []
    for path in ADAPTER_PATHS:
        text = path.read_text(encoding="utf-8")
        block = _extract_block(text)
        if block != canonical_block:
            mismatches.append(str(path.relative_to(REPO_ROOT)))
    assert not mismatches, (
        f"'## Tracker Writeback Helper' block diverges from canonical in: {mismatches}"
    )


def test_command_mirrors_carry_pointer_to_helper_reference():
    """COMMAND_MIRROR_PATHS enumerates 6 independent committed mirrors plus
    1 (.codex, a git symlink to the same source CANONICAL_PATH) - see the
    comment above ADAPTER_PATHS. None of the 7 entries carries the '##
    Tracker Writeback Helper' block itself post-split - it moved to
    HELPER_PATH. check-adapter-sync diffs regenerated-vs-committed content,
    so both operands come from the same build run: a build regression that
    silently drops the trigger-pointer produces identical operands on both
    sides and stays green. This assertion tests the property that gate
    structurally cannot - that the pointer (the literal path string, not
    just prose naming the helper) actually propagated to every entry in
    COMMAND_MIRROR_PATHS."""
    missing = [p for p in COMMAND_MIRROR_PATHS if not p.exists()]
    assert not missing, f"expected command mirror files missing: {missing}"

    without_pointer = [
        str(p.relative_to(REPO_ROOT))
        for p in COMMAND_MIRROR_PATHS
        if POINTER_TEXT not in p.read_text(encoding="utf-8")
    ]
    assert not without_pointer, (
        f"missing the '{POINTER_TEXT}' pointer literal: {without_pointer}"
    )


def test_helper_block_survives_in_hermes_aggregate(canonical_block):
    """`.hermes/SKILL.md` re-embeds every content/references/*.md file, each
    wrapped in `### <name>` (`.hermes/build.sh:100-107`), NOT `## `.
    `_extract_block` terminates on `## ` and therefore over-runs past this
    block's end into the alphabetically-next reference doc. Containment is
    the correct property here, not block-boundary equality.

    FORBIDDEN REPAIRS - do not reach for either instead:
      1. Deleting this assertion. The block genuinely survives here and that
         must stay tested.
      2. Weakening `_extract_block` to also stop on `### `. That function is
         shared by tests scanning the canonical file and the command mirrors,
         none of which use `### ` as a delimiter; narrowing its termination
         condition for one aggregate silently narrows correctness elsewhere.
    """
    text = (REPO_ROOT / ".hermes" / "SKILL.md").read_text(encoding="utf-8")
    assert canonical_block in text


# ---------------------------------------------------------------------------
# (c) spelling heuristic on the canonical block
# ---------------------------------------------------------------------------

def test_spelling_heuristic_single_l_on_trigger_lines(canonical_block):
    violations = []
    for line in canonical_block.splitlines():
        lower = line.lower()
        hit_count = sum(1 for tok in _TRIGGER_TOKENS if _token_present(lower, tok))
        if hit_count < 3:
            continue
        for m in _CANCEL_RE.finditer(line):
            word = m.group(0)
            tail = line[m.end():m.end() + 12]
            if word.lower() == "cancelled" and "(double L)" not in tail:
                violations.append(line)
    assert not violations, f"double-L 'cancelled' without a (double L) exemption on trigger line(s): {violations}"


def _token_present(lower_line: str, token: str) -> bool:
    """A trigger token counts only when it appears as a separated token
    (comma/pipe/angle-bracket/'<'-delimited), matching the spec's heuristic
    scope - not as a substring of unrelated prose."""
    pattern = r"(?:^|[\s,|<`])" + re.escape(token) + r"(?:$|[\s,|>`.;:])"
    return re.search(pattern, lower_line) is not None


# ---------------------------------------------------------------------------
# (d) ds-ticket-triage.md untouched literal check
# ---------------------------------------------------------------------------

def test_ticket_triage_already_correct_enumeration_untouched():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-triage.md"
    text = path.read_text(encoding="utf-8")
    assert "(completed, canceled)" in text


# ---------------------------------------------------------------------------
# (e) ds-ticket-status-sync.md no stale enumeration / restated ranking
# ---------------------------------------------------------------------------

def test_ticket_status_sync_each_spawn_site_has_forward_only_guard_and_tracker_state_values():
    """Each `/ds-ticket-status-sync` tracker-writeback spawn site (single-ticket
    step 6 and `--all` step 6) must carry an explicit `forward_only_guard: true`
    and `tracker_state_values` alongside `target_state` - not just a bare
    pointer to the shared contract. Anchored on the literal spawn-site
    sentence (which appears exactly once per call site) and a bounded window
    after it, rather than a same-line co-location check - the same-line check
    silently stopped firing once the parameter enumeration was replaced by a
    pointer sentence with no parameters on the line at all."""
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    anchor = (
        "spawn the tracker-writeback subagent using the "
        "`## Tracker Writeback Helper` invocation contract"
    )
    positions = [m.start() for m in re.finditer(re.escape(anchor), text)]
    assert len(positions) == 2, (
        f"expected exactly 2 tracker-writeback spawn sites in ds-ticket-status-sync.md, found {len(positions)}"
    )
    for pos in positions:
        window = text[pos:pos + 500]
        assert "forward_only_guard: true" in window, (
            f"spawn site at offset {pos} is missing an explicit forward_only_guard: true"
        )
        assert "tracker_state_values" in window, (
            f"spawn site at offset {pos} is missing tracker_state_values"
        )
        assert "target_state: <expected>" in window, (
            f"spawn site at offset {pos} is missing target_state: <expected>"
        )


def test_ticket_status_sync_no_stale_inline_ranking_restatement():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    assert "backlog` < `unstarted` < `started` < `completed`" not in text
    assert "cancelled` terminal" not in text


# ---------------------------------------------------------------------------
# (f) ds-wrap.md Part F Gate regression guard
# ---------------------------------------------------------------------------

def test_wrap_part_f_gate_resolves_tracker_state_values():
    path = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
    text = path.read_text(encoding="utf-8")
    gate_lines = [l for l in text.splitlines() if l.strip().startswith("**Gate.**")]
    assert gate_lines, "Part F Gate line not found in ds-wrap.md"
    assert any("TRACKER_STATE_IN_PROGRESS" in l for l in gate_lines), (
        "Part F Gate line no longer resolves TRACKER_STATE_IN_PROGRESS"
    )
    assert any("TRACKER_STATE_DEV_COMPLETE" in l for l in gate_lines), (
        "Part F Gate line no longer resolves TRACKER_STATE_DEV_COMPLETE"
    )


# ---------------------------------------------------------------------------
# Tracker-state reconciliation: Gap 1 diagnostic-enrichment mechanism
# (content/references/tracker-writeback.md ## Tracker Writeback Helper step 5)
# ---------------------------------------------------------------------------

def test_canonical_block_step5_diagnostic_runs_after_attempt(canonical_block):
    assert "runs strictly AFTER a transition attempt, never before" in canonical_block
    assert "no new round-trip on the happy path" in canonical_block


def test_canonical_block_diagnostic_failure_is_swallowed(canonical_block):
    idx = canonical_block.index("Any failure of this enrichment step itself is swallowed")
    window = canonical_block[idx:idx + 200]
    assert "`diagnostic` stays `null`" in window
    assert "never changes" in window


def test_canonical_block_jira_relabel_uses_already_fetched_data(canonical_block):
    assert (
        "jira_get_transitions` result already fetched during the attempt above (no new call)"
        in canonical_block
    )


def test_canonical_block_linear_relabel_only_after_own_check_succeeds(canonical_block):
    linear_bullet_idx = canonical_block.index("**Linear** - make ONE best-effort call")
    linear_bullet = canonical_block[linear_bullet_idx:linear_bullet_idx + 900]
    fail_idx = linear_bullet.index("If this call itself fails: swallow it")
    succeed_idx = linear_bullet.index("If it succeeds: check whether")
    assert fail_idx < succeed_idx, (
        "the Linear diagnostic bullet must check the enrichment call's own failure "
        "BEFORE checking whether the live states resolve target_state"
    )


def test_return_payload_schema_has_new_status_and_diagnostic_field():
    """Regression test for a false-negative: the Returns line contains
    'skipped_unconfigured_state' TWICE (once in the status enum union, once
    in trailing prose explaining the status). A bare substring check on the
    whole line stays green even if the enum union itself drops the new
    value, as long as the prose sentence still mentions it. Scope the
    assertion to the enum union specifically - the backtick-fenced type
    literal immediately after 'status:' - not the whole line."""
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    returns_lines = [l for l in text.splitlines() if l.strip().startswith("> **Returns:**")]
    assert returns_lines, "Returns line not found"
    for line in returns_lines:
        assert (
            'status: "ok" | "partial" | "failed" | "skipped_unconfigured_state"'
            in line
        ), "the status enum union itself must include skipped_unconfigured_state"
        assert "diagnostic: <string|null>" in line, (
            "the return payload type literal must include the diagnostic field"
        )


def test_line_508_failure_logging_has_both_forms():
    text = HELPER_PATH.read_text(encoding="utf-8")
    failure_logging_lines = [
        l for l in text.splitlines() if l.strip().startswith("**Failure logging:**")
    ]
    assert failure_logging_lines, "Failure logging line not found"
    assert all(
        "FAILED: <error>" in l and "SKIPPED: <diagnostic>" in l
        for l in failure_logging_lines
    ), "the canonical Failure logging line must define both the FAILED and SKIPPED forms"


def test_phase_2c_warning_updated_without_stale_silently_skipped_claim():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    heading = "## Phase 2c: Tracker state discovery (conditional)"
    start = text.index(heading)
    end = text.index("\n## ", start + len(heading))
    section = text[start:end]
    assert "attempted with this exact name first" in section
    assert "transition may be silently skipped at runtime" not in section


def test_phase_11_line_510_notes_qa_transition_unaffected():
    text = HELPER_PATH.read_text(encoding="utf-8")
    anchor = "For full details of the Phase 11 writeback subagent brief shape"
    idx = text.index(anchor)
    window = text[idx:idx + 700]
    assert "diagnostic-enrichment behavior from" in window
    assert "unaffected, unedited by this plan" in window


def test_comment_gate_clauses_are_byte_identical_across_files():
    status_sync_path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    wrap_path = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
    status_sync_text = status_sync_path.read_text(encoding="utf-8")
    wrap_text = wrap_path.read_text(encoding="utf-8")

    status_sync_anchor = "Evidence comment (only when the transition succeeded)"
    wrap_anchor = "Reconcile each detected key"
    clause_re = re.compile(r"\*\*Gate the comment on the Writeback Helper's return payload having `transitioned: true`\.\*\*")

    status_sync_idx = status_sync_text.index(status_sync_anchor)
    status_sync_window = status_sync_text[status_sync_idx:status_sync_idx + 1200]
    status_sync_match = clause_re.search(status_sync_window)

    wrap_idx = wrap_text.index(wrap_anchor)
    wrap_window = wrap_text[wrap_idx:wrap_idx + 1200]
    wrap_match = clause_re.search(wrap_window)

    clause_a = status_sync_match.group(0) if status_sync_match else ""
    clause_b = wrap_match.group(0) if wrap_match else ""

    # Non-empty guard BEFORE the equality assertion: a future edit that
    # drifted BOTH files identically to drop the clause entirely would have
    # both extractions return an empty string, and "" == "" would pass
    # vacuously without this guard.
    assert clause_a, "comment-gate clause not found in ds-ticket-status-sync.md"
    assert clause_b, "comment-gate clause not found in ds-wrap.md"
    assert clause_a == clause_b, (
        "the comment-gate clause must be byte-identical across "
        "ds-ticket-status-sync.md and ds-wrap.md"
    )


def test_ticket_status_sync_step8_has_exactly_three_indented_lines():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    start = text.index(
        "**Operator-visible line per transition attempt (mandatory, never silent"
    )
    block = text[start:start + 700]
    indented_lines = [l for l in block.splitlines() if l.startswith("       [ticket-status-sync]")]
    assert len(indented_lines) == 3, (
        f"expected exactly 3 indented output-line forms, found {len(indented_lines)}"
    )
    assert any(l.endswith("- transitioned") for l in indented_lines)
    assert any("FAILED: <error>" in l for l in indented_lines)
    assert any("SKIPPED: <diagnostic>" in l for l in indented_lines)


def test_ticket_status_sync_single_ticket_mode_prints_diagnostic_on_skip():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    anchor = "In single-ticket mode, print the before/after state."
    idx = text.index(anchor)
    window = text[idx:idx + 600]
    assert "skipped_unconfigured_state" in window
    assert "[ticket-status-sync] <KEY>: SKIPPED - <diagnostic>" in window


def test_wrap_part_f_output_has_exactly_three_indented_lines():
    path = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
    text = path.read_text(encoding="utf-8")
    start = text.index("print one operator-visible line per transition attempt so failures stay visible:")
    block = text[start:start + 700]
    indented_lines = [l for l in block.splitlines() if l.startswith("    [wrap: Part F]")]
    assert len(indented_lines) == 3, (
        f"expected exactly 3 indented Part F output-line forms, found {len(indented_lines)}"
    )
    assert any(l.endswith("- transitioned") for l in indented_lines)
    assert any("FAILED: <error>" in l for l in indented_lines)
    assert any("SKIPPED: <diagnostic>" in l for l in indented_lines)


def test_pending_merge_sweep_g_preserves_closed_unmerged_and_adds_three_way_rule():
    """§ Pending-merge sweep (g) must still map closed_unmerged from (c), and
    must additionally map a skipped_unconfigured_state writeback outcome to
    the RETRYABLE `failing` state (never `guard_skipped`, which is terminal).
    Fails if closed_unmerged is dropped OR if the new status's mapping is
    removed or changed to a terminal state."""
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    anchor = "**g. Record the determination.**"
    idx = text.index(anchor)
    window = text[idx:idx + 1600]

    # closed_unmerged from (c) must still be present, unchanged.
    assert "`closed_unmerged` from (c)" in window, (
        "the closed_unmerged mapping from (c) must be preserved"
    )

    # skipped_unconfigured_state must map to failing, and the sentence must
    # explicitly rule out guard_skipped for this case.
    mapping_idx = window.index(
        'Record `failing` (NOT `guard_skipped`) when the Writeback Helper\'s '
        'return payload has `status == "skipped_unconfigured_state"`'
    )
    mapping_window = window[mapping_idx:mapping_idx + 400]
    assert "retryable misconfiguration" in mapping_window
    assert "terminalizes via the same `attempts`/`abandoned` rule as any other `failing` entry" in mapping_window

    # The state enum sentence itself must be unchanged: still exactly 5
    # values, guard_skipped still listed as terminal (not silently dropped
    # or redefined as non-terminal to "fix" this some other way).
    assert (
        "`state` enum: `done` | `guard_skipped` | `closed_unmerged` | `abandoned` | `failing`. "
        "The first four are **terminal**"
        in text
    )


def test_setup_has_tracker_state_diagnostic_toggle():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    setup_lines = [
        l for l in text.splitlines() if l.strip().startswith("- `TRACKER_STATE_DIAGNOSTIC`")
    ]
    assert setup_lines, "TRACKER_STATE_DIAGNOSTIC Setup bullet not found"
    assert all("tracker_state_diagnostic" in l for l in setup_lines)


def test_invocation_contract_pass_list_has_diagnostic_and_team_params_referencing_step5(canonical_block):
    diagnostic_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("- `diagnostic_enabled`:")
    ]
    team_key_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("- `linear_team_key`:")
    ]
    assert diagnostic_lines, "diagnostic_enabled pass-list line not found"
    assert team_key_lines, "linear_team_key pass-list line not found"
    for line in diagnostic_lines + team_key_lines:
        assert "step 5" in line, f"expected 'step 5' reference in: {line}"
        assert "step 6" not in line, f"stale 'step 6' reference found in: {line}"


# Each entry is (path, expected substring). The expected substring includes
# enough surrounding context to anchor on the SPECIFIC toggle-count sentence
# rather than a bare word, since some files (README.md) restate the count in
# more than one sentence - a bare "twenty in text" presence check would stay
# green even if only one of the two sentences were bumped.
TOGGLE_COUNT_FILES = [
    (REPO_ROOT / "README.md", "seeded by `/ds-init-project` and holds twenty-one methodology toggles"),
    (REPO_ROOT / "README.md", "`.agentic/config.json` holds twenty-one methodology toggles (one reserved/inert"),
    (REPO_ROOT / "content" / "sections" / "04-risk-classification.md", "resolve twenty-one project-level orchestration toggles"),
    (REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md", "twenty-one-toggle project config catalog"),
    (REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md", "resolve twenty-one project-level orchestration toggles"),
    (REPO_ROOT / "content" / "references" / "conventions-detail.md", "seeded with defaults by `/ds-init-project`. Twenty-one toggles"),
    (REPO_ROOT / "docs" / "components.md", "the committed `.agentic/config.json` holds twenty-one methodology toggles"),
    (REPO_ROOT / "docs" / "configuration-reference.md", "no behavior change. The 21 behavioral toggles"),
]

TOGGLE_SEED_FILES = [
    REPO_ROOT / "content" / "templates" / ".agentic" / "config.json",
    REPO_ROOT / "content" / "commands" / "ds-init-project.md",
]

TOGGLE_BULLET_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
    REPO_ROOT / "content" / "references" / "conventions-detail.md",
    REPO_ROOT / "content" / "commands" / "ds-init-project.md",
]


def test_toggle_doc_sync_full_eight_site_checklist():
    for path, expected in TOGGLE_COUNT_FILES:
        text = path.read_text(encoding="utf-8")
        assert expected in text, f"{path.relative_to(REPO_ROOT)} missing '{expected}' toggle count"

    for path in TOGGLE_SEED_FILES:
        text = path.read_text(encoding="utf-8")
        assert '"pending_merge_sweep": true,\n  "tracker_state_diagnostic": true' in text, (
            f"{path.relative_to(REPO_ROOT)} seed JSON missing tracker_state_diagnostic "
            "immediately after pending_merge_sweep"
        )


# The log_fire() enforcer-caller subcount ("N of the M enforce-*.py hooks
# call lib/enforcement_log.py") is restated across hooks/AGENTS.md and
# content/references/events-log.md in at least FOUR different grammatical
# forms - "six of the seven", the bare cardinal "the six enforce-*.py
# hooks", "one of the six consumer hooks", and a decomposed enumeration
# ("(five hooks) ... (`enforce-planning-artifact-spawn.py`)" that sums to
# the same total without using the word "six" or "seven" at all - none of
# which a single-phrasing sweep catches as a set. This is why sites kept
# surviving prior sweeps: a check keyed to one exact string, or even one
# regex shape, finds only the sites written in that exact form.
#
# Site inventory (all reference the same fact: 8 enforce-*.py hooks post-
# merge with the sibling turn-shape-hook unit, 7 of them call log_fire,
# split 5 deny + 2 allow_advisory - `enforce-planning-artifact-spawn.py`
# and `enforce-turn-shape.py`):
#   hooks/AGENTS.md:43  - "N of the M enforce-*.py hooks" (table cell)
#   hooks/AGENTS.md:48  - bare cardinal "the N enforce-*.py hooks'"
#   hooks/AGENTS.md:81  - "N of the M enforce-*.py hooks" (prose)
#   events-log.md:120   - "N of the M `hooks/enforce-*.py` ... hooks"
#   events-log.md:129   - "one of the N consumer hooks enumerated below"
#   events-log.md:130   - decomposed enumeration: 5 deny + 2 allow_advisory,
#                         pinned by the FULL LITERAL - cardinals ("five
#                         hooks", "two hooks") AND named members together.
#                         This is deliberately count- AND membership-bound:
#                         a ninth enforcer added later (denying or advisory)
#                         changes either the cardinal or the member list, so
#                         either change breaks this exact-substring pin and
#                         forces the enumeration to be revisited by hand -
#                         it is not a count-agnostic pin that tolerates a
#                         stale number as long as names are unchanged.
_ENFORCER_SUBCOUNT_SITES = [
    (
        REPO_ROOT / "hooks" / "AGENTS.md",
        "by seven of the eight enforce-*.py hooks - every one except `enforce-no-abdication.py`",
    ),
    (
        REPO_ROOT / "hooks" / "AGENTS.md",
        "for the seven enforce-*.py hooks' best-effort dynamic import",
    ),
    (
        REPO_ROOT / "hooks" / "AGENTS.md",
        "Seven of the eight enforce-*.py hooks additionally",
    ),
    (
        REPO_ROOT / "content" / "references" / "events-log.md",
        "seven of the eight `hooks/enforce-*.py` PreToolUse/Stop hooks",
    ),
    (
        REPO_ROOT / "content" / "references" / "events-log.md",
        "one of the seven consumer hooks enumerated below",
    ),
    (
        REPO_ROOT / "content" / "references" / "events-log.md",
        '`"deny"` (six hooks - `enforce-askuserquestion-default.py`, '
        "`enforce-background-spawn.py`, `enforce-orchestrator-singularity.py`, "
        "`enforce-shippable-edit.py`, `enforce-tier.py`, `enforce-turn-shape.py`) "
        'and `"allow_advisory"` '
        "(two hooks - `enforce-planning-artifact-spawn.py`, `enforce-turn-shape.py`)",
    ),
]

# Bidirectional and case-insensitive: "six" followed by "enforce" within one
# sentence (catches "six of the seven enforce-*.py", "the six enforce-*.py
# hooks", and the capitalized "Six of the seven enforce-*.py hooks"), OR
# "enforce" followed by "six" within one sentence (catches "...enforce-
# shippable-edit" - one of the six consumer hooks"). The `[^.]{0,80}` bound
# stops the match from crossing a sentence boundary into an unrelated "six".
# Known limitation (tracked as a follow-up, not fixed here): this sweep is
# lowercase/capitalized-word-form and value-keyed to "six" - it goes silent
# once the live count moves past seven (when "seven" itself becomes stale),
# and it does not catch numeral ("6 of the 7") or decomposed-enumeration
# forms (the events-log.md:130 defect this pass fixed is pinned by exact
# membership text above, not by this regex).
_STALE_ENFORCER_SUBCOUNT_RE = re.compile(
    r"\bsix\b[^.]{0,80}\benforce|\benforce[^.]{0,80}\bsix\b",
    re.IGNORECASE,
)


def test_enforcer_subcount_is_current_across_all_known_sites():
    # Positive: every known site carries the current 7-caller / 8-enforcer
    # phrasing, in its own grammatical form.
    for path, expected in _ENFORCER_SUBCOUNT_SITES:
        text = path.read_text(encoding="utf-8")
        assert expected in text, (
            f"{path.relative_to(REPO_ROOT)} missing updated enforcer-subcount "
            f"phrasing: '{expected}'"
        )

    # Negative, phrasing-agnostic: no stale "six ... enforce" (or reversed)
    # survives in either file, regardless of which of the three grammatical
    # forms it was written in. This is the part a positive-only pin cannot
    # do - a half-fix that bumps the count-table cell but leaves a bare-
    # cardinal restatement stale elsewhere in the same file still fails here.
    for path in {p for p, _ in _ENFORCER_SUBCOUNT_SITES}:
        text = path.read_text(encoding="utf-8")
        match = _STALE_ENFORCER_SUBCOUNT_RE.search(text)
        assert match is None, (
            f"{path.relative_to(REPO_ROOT)} still has a stale enforcer-subcount "
            f"phrasing near: {match.group(0)!r}"
        )


def test_toggle_catalog_has_tracker_state_diagnostic_bullet_in_all_locations():
    for path in TOGGLE_BULLET_FILES:
        text = path.read_text(encoding="utf-8")
        pending_idx = text.index("pending_merge_sweep")
        tracker_idx = text.index("tracker_state_diagnostic")
        assert tracker_idx > pending_idx, (
            f"{path.relative_to(REPO_ROOT)}: tracker_state_diagnostic bullet must follow "
            "the pending_merge_sweep bullet"
        )

    components_text = (REPO_ROOT / "docs" / "components.md").read_text(encoding="utf-8")
    components_pending_idx = components_text.index("pending_merge_sweep")
    components_tracker_idx = components_text.index("tracker_state_diagnostic")
    assert components_tracker_idx > components_pending_idx

    config_ref_text = (REPO_ROOT / "docs" / "configuration-reference.md").read_text(encoding="utf-8")
    config_ref_pending_idx = config_ref_text.index("| `pending_merge_sweep` |")
    config_ref_tracker_idx = config_ref_text.index("| `tracker_state_diagnostic` |")
    assert config_ref_tracker_idx > config_ref_pending_idx

    ds_config_text = (REPO_ROOT / "content" / "commands" / "ds-config.md").read_text(encoding="utf-8")
    ds_config_bullet_lines = [
        l for l in ds_config_text.splitlines()
        if l.strip().endswith("and any additional config-file toggles.")
    ]
    assert ds_config_bullet_lines, "ds-config.md setting-selection bullet line not found"
    bullet_line = ds_config_bullet_lines[0]
    assert bullet_line.index("pending_merge_sweep") < bullet_line.index("tracker_state_diagnostic")

    ds_config_pending_row_idx = ds_config_text.index("| Pending-merge sweep |")
    ds_config_tracker_row_idx = ds_config_text.index("| Tracker state diagnostic |")
    assert ds_config_tracker_row_idx > ds_config_pending_row_idx


# Every catalog the toggle COUNT governs, as (path, anchor-for-the-predecessor,
# anchor-for-the-new-toggle). The predecessor is `commit_telemetry`, which is
# where all six catalogs place the new entry.
#
# This is MEMBERSHIP coverage, and it is deliberately separate from
# TOGGLE_COUNT_FILES above, which is COUNT coverage. The distinction is the
# whole point: a count sweep verifies the numeral in each of its four
# grammatical forms and reports all-clear while a catalog is short an entry -
# exactly how `knowledge_commit_on_pr` reached README.md's "twenty-one"
# sentence with only 20 bullets under it. A numeral and its list are two
# different claims and need two different assertions.
_KNOWLEDGE_TOGGLE_CATALOGS = [
    # (path, predecessor anchor, new-toggle anchor)
    (REPO_ROOT / "README.md", "- `commit_telemetry`", "- `knowledge_commit_on_pr`"),
    (REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
     "- `commit_telemetry`", "- `knowledge_commit_on_pr`"),
    (REPO_ROOT / "content" / "references" / "conventions-detail.md",
     "- `commit_telemetry`", "- `knowledge_commit_on_pr`"),
    (REPO_ROOT / "content" / "commands" / "ds-init-project.md",
     "- `commit_telemetry`", "- `knowledge_commit_on_pr`"),
    (REPO_ROOT / "docs" / "components.md",
     "`commit_telemetry` (", "`knowledge_commit_on_pr` ("),
    (REPO_ROOT / "docs" / "configuration-reference.md",
     "| `commit_telemetry` |", "| `knowledge_commit_on_pr` |"),
    (REPO_ROOT / "content" / "templates" / ".agentic" / "config.json",
     '"commit_telemetry": true,', '"knowledge_commit_on_pr": true,'),
    (REPO_ROOT / "content" / "commands" / "ds-init-project.md",
     '"commit_telemetry": true,', '"knowledge_commit_on_pr": true,'),
]


def test_toggle_catalog_has_knowledge_commit_on_pr_entry_in_all_locations():
    """Membership + position for `knowledge_commit_on_pr` in every catalog the
    toggle count governs - the four TOGGLE_BULLET_FILES bullet catalogs, the
    two prose/table catalogs, and both seed JSONs.

    Same shape as
    test_toggle_catalog_has_tracker_state_diagnostic_bullet_in_all_locations
    above. Asserted per-file with the path in the message, so a catalog that is
    short the entry names ITSELF rather than failing anonymously."""
    bullet_paths = {p for p, _, _ in _KNOWLEDGE_TOGGLE_CATALOGS}
    for path in TOGGLE_BULLET_FILES:
        assert path in bullet_paths, (
            f"{path.relative_to(REPO_ROOT)} is in TOGGLE_BULLET_FILES but is not "
            "covered by this membership check - every bullet catalog the count "
            "governs must be checked, or the next toggle repeats the README miss"
        )

    for path, predecessor, entry in _KNOWLEDGE_TOGGLE_CATALOGS:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        assert entry in text, (
            f"{rel}: missing the `knowledge_commit_on_pr` entry ({entry!r}). "
            "The toggle count in this file (or governing it) says 21 - a "
            "catalog with 20 entries makes that numeral false."
        )
        assert text.count(entry) == 1, (
            f"{rel}: `knowledge_commit_on_pr` entry appears {text.count(entry)} "
            f"times ({entry!r}); expected exactly 1 - a duplicate inflates the "
            "catalog against its own count."
        )
        assert predecessor in text, (
            f"{rel}: predecessor anchor {predecessor!r} not found - this check's "
            "position assertion cannot be evaluated, so it must not silently pass"
        )
        assert text.index(entry) > text.index(predecessor), (
            f"{rel}: the `knowledge_commit_on_pr` entry must follow "
            f"`commit_telemetry`, matching its position in every other catalog"
        )


def test_agentic_config_settings_registers_tracker_state_diagnostic():
    path = REPO_ROOT / "bin" / "agentic-config"
    text = path.read_text(encoding="utf-8")
    rework_idx = text.index('"rework_detection": {"target": "project_config", "type": "bool"},')
    tracker_idx = text.index('"tracker_state_diagnostic": {"target": "project_config", "type": "bool"},')
    assert tracker_idx > rework_idx, (
        "tracker_state_diagnostic must be registered in _SETTINGS immediately after rework_detection"
    )


def test_canonical_block_never_substitutes_a_different_write_target(canonical_block):
    """Guards the invariant behind outcome rubric R4: the mechanism never
    writes a tracker state outside the 6 configured TRACKER_STATE_* values -
    no substitution, no guessing, ever, on either tracker. Two prior review
    rounds' Criticals were about exactly this invariant. This is a genuine
    guard, not a bare
    keyword-presence check, but its coverage is bounded and stated honestly
    here rather than overclaimed: it pins BOTH write call sites to their
    single literal form (so swapping `target_state` for a derived/nearest/
    closest value at either the Linear or Jira call site fails), AND sweeps
    the whole canonical block for a specific, closed vocabulary list
    (`closest match`, `nearest`, `substitut*`) that a substitution mechanism
    described in THOSE WORDS would need to use, wherever in the block it
    appears. It does NOT catch every conceivable phrasing of a fallback-write
    mechanism - a future edit introducing substitution logic under novel
    wording that avoids this specific vocabulary (verifier-confirmed: e.g.
    'retry with the semantically equivalent live state name') would not be
    caught by this test alone. Treat this as a guard against regression of
    the two known call sites plus the vocabulary this invariant has
    historically been described with, not as an exhaustive proof."""
    # Positive proof: the ONLY two write call sites are pinned to their
    # single literal form. Linear writes target_state directly; Jira writes
    # "the matching transition id" - selected from the tracker's own live
    # transitions list by exact name match against target_state (see the
    # Jira relabel bullet's "did not match any available transition's target
    # name" framing - an exact-match test, not a nearest/closest choice).
    assert "`mcp__linear__save_issue` call with `state: target_state`" in canonical_block, (
        "the Linear write call must pass target_state literally"
    )
    assert (
        "call `mcp__mcp-atlassian__jira_transition_issue` for the matching transition id"
        in canonical_block
    ), "the Jira write call must use the id of the transition matching target_state, not a derived value"

    # The relabeling invariant: diagnostic enrichment can only ever downgrade
    # a status label after the fact - it can never redirect what gets written
    # or manufacture a fake success.
    assert (
        'it can never convert `"failed"` into `"ok"`, and it can never prevent, delay, or retry the '
        "original transition attempt."
        in canonical_block
    ), "the diagnostic-enrichment sub-step must state it can never convert failed into ok"

    # Negative sweep: none of the vocabulary a write-time substitution
    # mechanism would need is present anywhere in the block. "closest match"
    # and "nearest" are reserved for Phase 2c's READ-ONLY validation warning
    # (outside this block, and itself explicitly disclaiming any write - see
    # "never writes to an unconfigured state" below), never for a write
    # decision inside the Tracker Writeback Helper itself.
    lowered = canonical_block.lower()
    for forbidden in ("closest match", "nearest", "substitut"):
        assert forbidden not in lowered, (
            f"found substitution-indicating vocabulary {forbidden!r} inside the "
            "Tracker Writeback Helper block - this is the exact invariant two "
            "prior review rounds' Criticals were about"
        )

    # Companion check on Phase 2c's own read-only closest-match warning: it
    # must explicitly disclaim writing to an unconfigured state, so the ONE
    # place "closest match" legitimately appears in the file is pinned as
    # non-write.
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    assert (
        "Closest match: '<closest>'. Proceeding with configured name" in text
    ), "Phase 2c's closest-match warning line not found"
    warning_idx = text.index("Closest match: '<closest>'. Proceeding with configured name")
    warning_window = text[warning_idx:warning_idx + 400]
    assert "never writes to an unconfigured state" in warning_window, (
        "Phase 2c's closest-match warning must explicitly disclaim writing to an unconfigured state"
    )


# ---------------------------------------------------------------------------
# Gap 2: declarable pipeline order (content/commands/ds-implement-ticket.md
# ## Tracker Writeback Helper step 4.d.iv, and its downstream consumers)
# ---------------------------------------------------------------------------

def test_invocation_contract_pass_list_has_pipeline_order_param(canonical_block):
    pipeline_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("- `pipeline_order`:")
    ]
    assert pipeline_lines, "pipeline_order pass-list line not found"
    assert all(
        "TRACKER_PIPELINE_ORDER" in line and "step 4.d.iv" in line
        for line in pipeline_lines
    ), "pipeline_order pass-list line must name TRACKER_PIPELINE_ORDER and reference step 4.d.iv"

    # Re-run the pre-existing pass-list assertions to confirm this insertion
    # did not silently widen the window an earlier test scopes to (the
    # vacuity trap named in the spec: a new bullet landing inside an existing
    # scoped window must not make that window's own checks pass vacuously).
    start = canonical_block.index("3. Pass to the subagent:")
    end = canonical_block.index("**Subagent responsibilities", start)
    pass_list_window = canonical_block[start:end]
    assert "tracker_state_values" in pass_list_window
    assert "pipeline_order" in pass_list_window
    diagnostic_lines_in_window = [
        line for line in pass_list_window.splitlines()
        if line.strip().startswith("- `diagnostic_enabled`:")
    ]
    assert diagnostic_lines_in_window, (
        "diagnostic_enabled pass-list line must still be present after the "
        "pipeline_order insertion"
    )


def test_setup_resolves_tracker_pipeline_order_with_default():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    assert "JIRA_PIPELINE_ORDER" in text
    assert "TRACKER_PIPELINE_ORDER" in text
    # Both the Jira item-1 sentence and the Linear item-3 sentence must state
    # the default and the malformed-value fallback.
    jira_idx = text.index("Also extract an optional pipeline-order override: `JIRA_PIPELINE_ORDER`")
    # Widened from 500 to 1200: DS-117's warning literal names the optional
    # DEV_COMPLETE token, pushing the anchor's tail (through "using the
    # default order.") to about 710 chars - the 500-char window truncated it.
    jira_window = text[jira_idx:jira_idx + 1200]
    assert "default `IN_PROGRESS, IN_REVIEW, QA` when absent" in jira_window
    assert (
        "is not a valid ordering of IN_PROGRESS/IN_REVIEW/QA with optional "
        "DEV_COMPLETE - using the default order"
        in jira_window
    )

    linear_idx = text.index("Also extract an optional pipeline-order override: `Pipeline order:`")
    linear_window = text[linear_idx:linear_idx + 300]
    assert "same syntax, validation, and default as the Jira `JIRA_PIPELINE_ORDER` field above" in linear_window


def test_setup_item2_linear_shaped_tracker_path_covers_pipeline_order():
    # M-class fix: item 2 (the `TRACKER: linear` under `## Tracker`) inherits
    # only the state-name override fields by cross-reference to item 3's
    # prose; that cross-reference sentence must ALSO now cover pipeline
    # order, or a project using this path never picks up a declared order.
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    item2_lines = [
        l for l in text.splitlines()
        if l.strip().startswith("2. Else if a `## Tracker` section exists with `TRACKER: linear`")
    ]
    assert item2_lines, "Setup item 2 (Linear-shaped ## Tracker path) line not found"
    assert all("Pipeline order" in l for l in item2_lines), (
        "Setup item 2 must explicitly cover the Pipeline order override field, "
        "not just state-name overrides"
    )


def test_setup_item4_tracker_none_sets_default_pipeline_order():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    item4_lines = [
        l for l in text.splitlines()
        if l.strip().startswith("4. Else: set `TRACKER=none`.")
    ]
    assert item4_lines, "Setup item 4 (TRACKER=none) line not found"
    assert all(
        'TRACKER_PIPELINE_ORDER` to its default `IN_PROGRESS, IN_REVIEW, QA`' in l
        for l in item4_lines
    ), "Setup item 4 must set TRACKER_PIPELINE_ORDER to its default"


def test_setup_print_summary_has_tracker_pipeline_order_line():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    summary_lines = [
        l for l in text.splitlines() if l.startswith("TRACKER_PIPELINE_ORDER:")
    ]
    assert summary_lines, "Setup print summary is missing the TRACKER_PIPELINE_ORDER line"


def test_step_4d_iv_uses_pipeline_order_as_rank_source(canonical_block):
    # Line/paragraph-scoped: the ONLY line starting with the step 4.d.iv
    # marker must reference pipeline_order as the rank source, and must not
    # still claim the order is fixed/hardcoded - an inversion (reverting to
    # the hardcoded constant) must fail this, not just pass on unordered
    # token presence.
    step_4d_iv_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith("- iv. Else, look up current and target against")
    ]
    assert step_4d_iv_lines, "step 4.d.iv line not found"
    assert len(step_4d_iv_lines) == 1, "expected exactly one step 4.d.iv line"
    line = step_4d_iv_lines[0]
    assert "`pipeline_order`" in line
    assert "rank = index within `pipeline_order`" in line
    assert "declares `JIRA_PIPELINE_ORDER` / `Pipeline order:` in `AGENTS.md`" in line
    assert "the declared order governs instead" in line
    assert "not read from any tracker API and does not depend on operator-configured board/column order" not in line, (
        "step 4.d.iv must not still claim the order is fixed/unconfigurable - that is the exact "
        "claim Gap 2 makes false"
    )
    # DS-117: DEV_COMPLETE is now the fourth pipeline token, and a declared
    # order may omit it (implied trailing position, appended before ranking).
    assert "DEV_COMPLETE" in line
    assert "IN_PROGRESS`/`IN_REVIEW`/`QA`/`DEV_COMPLETE`" in line
    assert "may omit `DEV_COMPLETE`" in line
    assert "appended at the trailing position" in line

    # The two sibling bullets that follow are unchanged verbatim per the
    # spec - confirm they are still present and still resolve to their
    # original permit/skip outcomes (regression guard against this edit
    # accidentally touching them).
    assert re.search(
        r"If BOTH names resolve to a pipeline rank: \*\*permit\*\* iff `pipeline_rank\(current\) < pipeline_rank\(target\)`",
        canonical_block,
    )
    fallthrough_lines = [
        line for line in canonical_block.splitlines()
        if line.strip().startswith(
            "- Otherwise (at least one name does not resolve to a pipeline rank"
        )
    ]
    assert fallthrough_lines
    assert all("**skip** unconditionally" in line for line in fallthrough_lines)


def test_canonical_block_rejects_fully_tracker_derived_pipeline_order(canonical_block):
    assert "**Rejected: fully tracker-derived pipeline order.**" in canonical_block
    idx = canonical_block.index("**Rejected: fully tracker-derived pipeline order.**")
    window = canonical_block[idx:idx + 700]
    assert "edge-local view of the workflow graph, not a global ordering of all states" in window
    assert "cross-tracker-symmetric live-derived order" in window
    assert "breaks universality" in window


def test_phase_11_inputs_list_includes_pipeline_order():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    anchor = '`target_state`: `$TRACKER_STATE_QA`'
    idx = text.index(anchor)
    window = text[max(0, idx - 400):idx + 500]
    assert "pipeline_order" in window, (
        "Phase 11's own Inputs list is missing pipeline_order alongside target_state/tracker_state_values"
    )


def test_phase_11_summary_sentence_names_pipeline_order():
    text = HELPER_PATH.read_text(encoding="utf-8")
    anchor = "For full details of the Phase 11 writeback subagent brief shape"
    idx = text.index(anchor)
    window = text[idx:idx + 300]
    assert "`pipeline_order`" in window
    # Must not claim Phase 11 gains diagnostic/fallback behavior beyond what
    # Gap 1 already granted - this edit is a pipeline_order addition only.
    assert "gains" not in window.split("Phase 11's own Jira")[0]


def test_ticket_status_sync_preflight_resolves_pipeline_order():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    assert (
        "Additionally resolve `TRACKER_PIPELINE_ORDER` from the same `AGENTS.md` fields "
        "as `/ds-implement-ticket` Setup"
        in text
    )


def test_ticket_status_sync_spawn_sites_have_pipeline_order():
    path = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
    text = path.read_text(encoding="utf-8")
    anchor = (
        "spawn the tracker-writeback subagent using the "
        "`## Tracker Writeback Helper` invocation contract"
    )
    positions = [m.start() for m in re.finditer(re.escape(anchor), text)]
    assert len(positions) == 2, (
        f"expected exactly 2 tracker-writeback spawn sites, found {len(positions)}"
    )
    for pos in positions:
        window = text[pos:pos + 700]
        assert "pipeline_order" in window, (
            f"spawn site at offset {pos} is missing pipeline_order"
        )
        # Regression guard: the pre-existing site checks must still hold in
        # this same widened window.
        assert "forward_only_guard: true" in window
        assert "tracker_state_values" in window


def test_wrap_part_f_gate_resolves_pipeline_order():
    path = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
    text = path.read_text(encoding="utf-8")
    assert (
        "Also resolve `TRACKER_PIPELINE_ORDER` (same fields and default as "
        "`/ds-implement-ticket` Setup)."
        in text
    )
    reconcile_idx = text.index("**Reconcile each detected key.**")
    reconcile_window = text[reconcile_idx:reconcile_idx + 700]
    assert "pipeline_order" in reconcile_window
    assert "diagnostic_enabled" in reconcile_window
    assert "linear_team_key" in reconcile_window


def test_init_project_templates_show_pipeline_order_under_own_heading():
    path = REPO_ROOT / "content" / "commands" / "ds-init-project.md"
    text = path.read_text(encoding="utf-8")

    # Anchored on the FIRST state line of each block, not on the Done line:
    # `# State Dev Complete:` precedes `# State Done:`, so a window opened at
    # Done can never contain it. Both anchors below are unique in the file.
    linear_idx = text.index("# State In Progress: In Progress")
    linear_window = text[linear_idx:linear_idx + 400]
    assert "# State Dev Complete: Done" in linear_window
    assert "# State Done: Done" in linear_window
    assert "# Optional pipeline-order override (default shown; uncomment to override):" in linear_window
    assert "# Pipeline order: IN_PROGRESS, IN_REVIEW, QA" in linear_window

    jira_idx = text.index("# JIRA_STATE_IN_PROGRESS: In Progress")
    jira_window = text[jira_idx:jira_idx + 400]
    assert "# JIRA_STATE_DEV_COMPLETE: Done" in jira_window
    assert "# JIRA_STATE_DONE: Done" in jira_window
    assert "# Optional pipeline-order override (default shown; uncomment to override):" in jira_window
    assert "# JIRA_PIPELINE_ORDER: IN_PROGRESS, IN_REVIEW, QA" in jira_window
