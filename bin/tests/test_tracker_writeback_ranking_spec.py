#!/usr/bin/env python3
"""
Spec tests for the Tracker Writeback Helper's forward-only guard ranking rule
(content/commands/ds-implement-ticket.md ## Tracker Writeback Helper).

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
    the fixed IN_PROGRESS < IN_REVIEW < QA pipeline sequence and the Linear
    category-rank sequence are pinned as ORDERED literals (not just unordered
    token presence), and the invocation contract's tracker_state_values and
    forward_only_guard parameters are checked against a scoped window (the
    pass-list itself), not the whole block. These pin outcomes byte-identity
    (b) cannot catch a reversal applied uniformly to the canonical block and
    every adapter copy at once.
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

Run with: python3 -m pytest bin/tests/test_tracker_writeback_ranking_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

# All adapter copies expected to carry a byte-identical extraction of the
# "## Tracker Writeback Helper" block. .pi/prompts/ds-implement-ticket.md is
# deliberately excluded - it is a 7-line pointer stub with no such block.
ADAPTER_PATHS = [
    REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".claude" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".codex" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".cursor" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".opencode" / "commands" / "ds-implement-ticket.md",
    REPO_ROOT / ".github" / "prompts" / "ds-implement-ticket.prompt.md",
    REPO_ROOT / ".openclaw" / "skills" / "ds-implement-ticket" / "SKILL.md",
    REPO_ROOT / ".gemini" / "commands" / "ds-implement-ticket.toml",
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
    return _extract_block(CANONICAL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) canonical block content assertions
# ---------------------------------------------------------------------------

def test_canonical_block_contains_pipeline_subrank_language(canonical_block):
    assert "pipeline sub-rank" in canonical_block


def test_canonical_block_contains_fixed_pipeline_ranks(canonical_block):
    assert "IN_PROGRESS" in canonical_block and "rank 0" in canonical_block
    assert "IN_REVIEW" in canonical_block and "rank 1" in canonical_block
    assert "QA" in canonical_block and "rank 2" in canonical_block


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
    assert (
        "the fixed pipeline sequence `IN_PROGRESS` (rank 0) < `IN_REVIEW` (rank 1) < `QA` (rank 2)"
        in canonical_block
    ), "the fixed pipeline sequence must be the literal ordered IN_PROGRESS(0) < IN_REVIEW(1) < QA(2) clause"


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


# ---------------------------------------------------------------------------
# Tracker-state reconciliation: Gap 1 diagnostic-enrichment mechanism
# (content/commands/ds-implement-ticket.md ## Tracker Writeback Helper step 5)
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
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    returns_lines = [l for l in text.splitlines() if l.strip().startswith("> **Returns:**")]
    assert returns_lines, "Returns line not found"
    assert all("skipped_unconfigured_state" in l for l in returns_lines)
    assert all("`diagnostic`" in l for l in returns_lines)


def test_line_508_failure_logging_has_both_forms():
    text = CANONICAL_PATH.read_text(encoding="utf-8")
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
    text = CANONICAL_PATH.read_text(encoding="utf-8")
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
# more than one sentence - a bare "nineteen in text" presence check would stay
# green even if only one of the two sentences were bumped.
TOGGLE_COUNT_FILES = [
    (REPO_ROOT / "README.md", "seeded by `/ds-init-project` and holds nineteen methodology toggles"),
    (REPO_ROOT / "README.md", "`.agentic/config.json` holds nineteen methodology toggles (one reserved/inert"),
    (REPO_ROOT / "content" / "sections" / "04-risk-classification.md", "resolve nineteen project-level orchestration toggles"),
    (REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md", "nineteen-toggle project config catalog"),
    (REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md", "resolve nineteen project-level orchestration toggles"),
    (REPO_ROOT / "content" / "references" / "conventions-detail.md", "seeded with defaults by `/ds-init-project`. Nineteen toggles"),
    (REPO_ROOT / "docs" / "components.md", "the committed `.agentic/config.json` holds nineteen methodology toggles"),
    (REPO_ROOT / "docs" / "configuration-reference.md", "no behavior change. The 19 behavioral toggles"),
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


def test_agentic_config_settings_registers_tracker_state_diagnostic():
    path = REPO_ROOT / "bin" / "agentic-config"
    text = path.read_text(encoding="utf-8")
    rework_idx = text.index('"rework_detection": {"target": "project_config", "type": "bool"},')
    tracker_idx = text.index('"tracker_state_diagnostic": {"target": "project_config", "type": "bool"},')
    assert tracker_idx > rework_idx, (
        "tracker_state_diagnostic must be registered in _SETTINGS immediately after rework_detection"
    )
