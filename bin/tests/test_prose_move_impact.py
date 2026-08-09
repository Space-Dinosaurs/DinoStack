#!/usr/bin/env python3
"""
Purpose: Known-answer, regression, mutation, and DIFFERENTIAL tests for
         scripts/prose-move-impact.py - the mechanical "what breaks if I
         move these line ranges" enumerator built to replace four failed
         prose-only review rounds on splitting
         content/commands/ds-implement-ticket.md. Each known-answer case
         below is a REAL, previously-verified miss from those rounds, not a
         synthetic example. The differential test at the bottom
         (test_differential_against_ground_truth_post_move_gates) is the
         load-bearing one: it simulates the actual post-move tree in a
         scratch git repo and runs the REAL executable gates against it,
         comparing their real pass/fail to the tool's prediction - the
         check with the best chance of catching a NEW under-report class
         rather than re-confirming a named one, though it is currently
         scoped to only 2 of the 7 tool-clean consumers a manual run can
         differential-test in ~40s wall time (see SCRATCH_GATES below);
         the other 5 are not yet covered by this automated check.

Public API: pytest test module. Run with
              python3 -m pytest bin/tests/test_prose_move_impact.py -q
            (auto-discovered by `.github/workflows/bin-tests.yml`'s
            `python3 -m pytest bin/tests/ -q` invocation - no separate CI
            wiring required).

Upstream deps: scripts/prose-move-impact.py (imported by path, since
               scripts/ is not a package); the live content of
               content/commands/ds-implement-ticket.md and its four fixture
               consumers (bin/tests/test_tracker_dev_complete_spec.py,
               bin/tests/test_tasks_jsonl_fold.sh,
               bin/tests/test_batch_state_timestamp_field.sh,
               bin/tests/test_loop_state_site_coverage.sh); the entire
               content/ tree and the two scratch-copied shell gates named
               in `SCRATCH_GATES` (differential test only, via a scratch
               git repo under pytest's `tmp_path`).

Downstream consumers: none (leaf test module).

Failure modes: a known-answer test failing means either the tool regressed,
               or the live target file's line numbers drifted out from
               under one of the fixture's proposed ranges - re-verify the
               range against a fresh `grep -n '^## '` before assuming the
               tool is at fault. The mutation test intentionally breaks the
               tool's own discovery step and asserts the suite goes red;
               a green mutation test means the tool would silently report
               "nothing breaks" on total discovery failure - exactly the
               failure mode design constraint prohibits. The differential
               test failing means the tool reported a consumer CLEAN that
               actually fails against the real, simulated post-move tree -
               disqualifying by design; it never fails on the opposite
               (over-report) direction, which is recorded but tolerated.

Performance: single-digit seconds; a handful of `git grep` subprocess calls,
             small in-repo file reads, and (differential test only) one
             `content/`-tree copy (~2 MB) plus two real shell-gate runs
             against a scratch git repo under `tmp_path`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "prose-move-impact.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prose_move_impact", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prose_move_impact"] = mod
    spec.loader.exec_module(mod)
    return mod


pmi = _load_module()

TARGET = "content/commands/ds-implement-ticket.md"


# ---------------------------------------------------------------------------
# Heading-derived ranges (regression: Major 3, r2 Skeptic finding) - every
# proposed move range below is now located by HEADING TEXT, never a
# hardcoded absolute line number. A hardcoded number silently goes stale
# the moment any unrelated edit lands above it anywhere in the 3600-line
# target file: the reviewer demonstrated that inserting one sentence at
# line 20 reddens a hardcoded-number test with a diagnostic about a refactor
# that hasn't happened, which would block merge on this repo's REQUIRED
# `python-bin-tests` check for every unrelated PR that happens to touch the
# target file above the highest hardcoded line. Deriving from
# `fence_aware_headings()` (the tool's own heading index) instead means the
# range tracks the heading wherever it lives today - the test only fails
# when the heading's TEXT genuinely disappears, which is the real structural
# premise this fixture is pinning.
# ---------------------------------------------------------------------------


def _heading_index() -> dict[str, "pmi.Heading"]:
    target_path = REPO_ROOT / TARGET
    lines = target_path.read_text(encoding="utf-8").split("\n")
    return {h.text: h for h in pmi.fence_aware_headings(lines)}


_HEADINGS = _heading_index()


def _range_for_heading(heading_text: str, dest: str) -> "pmi.MoveRange":
    h = _HEADINGS.get(heading_text)
    if h is None:
        raise AssertionError(
            f"proposed range heading no longer exists in the live target: {heading_text!r} "
            "- the split proposal's structural premise has changed, re-verify against a "
            "fresh `grep -n '^#' ...` before assuming this fixture is stale for no reason"
        )
    return pmi.MoveRange(start=h.line, end=h.end_line, dest=dest)


# The 9 proposed-split headings from the ticket brief, by heading text (see
# module docstring above for why text, not line number).
_HEADING_TRACKER_WRITEBACK = "## Tracker Writeback Helper"
_HEADING_OPEN_GOAL_LOOP = "## Phase 0a-open-goal: Open-goal loop init or resume (conditional)"
_HEADING_BATCH_RESUME_CHECK = "## Phase 0a-pre: Batch resume check"
_HEADING_BATCH_TRIAGE = "## Phase 0a: Batch triage (Phase 0 produced ≥ 2 entries)"
_HEADING_ORCHESTRATION_PLAN = "## Phase 3b: Orchestration plan (conditional)"
_HEADING_PARALLEL_UNITS = "### If parallel independent units were identified:"
_HEADING_QA_GATE = "## Phase 6b: QA Gate (conditional)"
_HEADING_QA_EVIDENCE = "## Phase 8.5: QA evidence (conditional)"
_HEADING_HANDOFF_EVAL = "## Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)"


# ---------------------------------------------------------------------------
# Fence-aware heading index sanity
# ---------------------------------------------------------------------------


def test_fence_aware_headings_skip_fenced_pseudo_headings():
    target_path = REPO_ROOT / TARGET
    lines = target_path.read_text(encoding="utf-8").split("\n")
    headings = pmi.fence_aware_headings(lines)
    # non-vacuity: real target has dozens of top-level headings
    assert len(headings) > 20
    for h in headings:
        assert lines[h.line - 1].lstrip().startswith("#")


def test_known_move_ranges_align_exactly_with_heading_boundaries():
    """The 9 proposed headings from the ticket brief, re-verified against
    the live target BY TEXT (not a hardcoded line number - see the
    heading-derived-ranges block above): each named heading must still
    exist as a live heading. `_range_for_heading` already asserts this
    per-heading with a specific diagnostic; this test asserts it in one
    place for all 9 so a single failure enumerates every heading that
    vanished, not just the first one a fixture happens to touch."""
    proposed_heading_texts = {
        _HEADING_TRACKER_WRITEBACK,
        _HEADING_OPEN_GOAL_LOOP,
        _HEADING_BATCH_RESUME_CHECK,
        _HEADING_BATCH_TRIAGE,
        _HEADING_ORCHESTRATION_PLAN,
        _HEADING_PARALLEL_UNITS,
        _HEADING_QA_GATE,
        _HEADING_QA_EVIDENCE,
        _HEADING_HANDOFF_EVAL,
    }
    missing = proposed_heading_texts - set(_HEADINGS)
    assert not missing, f"proposed range heading(s) no longer exist in the live target: {missing}"


# ---------------------------------------------------------------------------
# Known-answer 1: test_tracker_dev_complete_spec.py's _extract_block reader
# breaks when 480-548 (## Tracker Writeback Helper) moves.
# ---------------------------------------------------------------------------


def test_known_answer_tracker_dev_complete_heading_block_breaks():
    ranges = [_range_for_heading(_HEADING_TRACKER_WRITEBACK, "content/references/tracker-writeback.md")]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_tracker_dev_complete_spec.py" and a.kind == "heading_block"
    ]
    assert hits, "expected a heading_block assertion for test_tracker_dev_complete_spec.py"
    assert all(a.breaks for a in hits), "moving 480-548 must break the _extract_block reader"
    assert not report.ok


def test_known_answer_tracker_dev_complete_heading_block_does_not_break_when_untouched():
    """Sanity control: a move range that does NOT touch 480-548 must not
    falsely flag this consumer's heading_block assertion."""
    ranges = [_range_for_heading(_HEADING_HANDOFF_EVAL, "content/references/handoff-evaluation.md")]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_tracker_dev_complete_spec.py" and a.kind == "heading_block"
    ]
    assert hits
    assert not any(a.breaks for a in hits)


# ---------------------------------------------------------------------------
# Known-answer 2: test_tasks_jsonl_fold.sh's FOLDSPEC per-file floor (>= 7)
# drops to 4 when 1369-1458 and 1651-1763 move.
# ---------------------------------------------------------------------------


def test_known_answer_tasks_jsonl_fold_heredoc_floor_breaks():
    ranges = [
        _range_for_heading(_HEADING_ORCHESTRATION_PLAN, "content/references/orchestration-units.md"),
        _range_for_heading(_HEADING_PARALLEL_UNITS, "content/references/orchestration-units.md"),
    ]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_tasks_jsonl_fold.sh" and a.kind == "grep_count_floor"
    ]
    assert hits, "expected a grep_count_floor assertion for test_tasks_jsonl_fold.sh"
    breaking = [a for a in hits if a.breaks]
    assert breaking, "FOLDSPEC per-file floor for the target file must break: before=14, after=4, floor>=7"
    foldspec_hits = [a for a in breaking if "FOLDSPEC" in a.detail]
    assert foldspec_hits, f"expected the FOLDSPEC heredoc floor among breaking hits, got: {[a.detail for a in breaking]}"
    assert "after=4" in foldspec_hits[0].detail
    assert "floor >= 7" in foldspec_hits[0].detail
    # G6's own simple `VAR="$(git grep -cE ... -- "$DIT")"` floor (>= 1) is a
    # SEPARATE grep_count_floor assertion from the FOLDSPEC heredoc table
    # above - its only occurrence (line 1448) sits inside the 1369-1458
    # move range, so before=1/after=0 must ALSO break. This was silently
    # dropped pre-fix: `_VAR_ASSIGN_RE` required the `$(...)` to end the
    # line, but this exact call site has a trailing `; [ -n "$G6" ] ||
    # G6=0` statement after it.
    g6_hits = [a for a in breaking if "G6" in a.detail and "is in_progress under another session" in a.detail]
    assert g6_hits, f"expected G6's own floor among breaking hits, got: {[a.detail for a in breaking]}"
    assert "before=1" in g6_hits[0].detail and "after=0" in g6_hits[0].detail
    assert not report.ok


def test_known_answer_tasks_jsonl_fold_heredoc_floor_stays_green_when_untouched():
    ranges = [_range_for_heading(_HEADING_HANDOFF_EVAL, "content/references/handoff-evaluation.md")]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_tasks_jsonl_fold.sh" and a.kind == "grep_count_floor"
    ]
    assert hits
    assert not any(a.breaks for a in hits)


# ---------------------------------------------------------------------------
# Known-answer 3: test_batch_state_timestamp_field.sh really does carry 8
# `_absent(` call sites, not 2 - a non-vacuity pin on the fixture premise
# itself (and on this tool's shell-continuation joiner, which must see all
# 8 rather than only the ones that happen to fit on one physical line).
# ---------------------------------------------------------------------------


def test_known_answer_batch_state_timestamp_field_has_8_absent_calls():
    path = REPO_ROOT / "bin" / "tests" / "test_batch_state_timestamp_field.sh"
    text = path.read_text(encoding="utf-8")
    joined = [logical for _, logical in pmi.join_shell_continuations(text)]
    absent_calls = [l for l in joined if "_absent(" in l or l.strip().startswith("_absent ")]
    # The function DEFINITION line ("_absent() { ...") also matches
    # "_absent(" - exclude it explicitly rather than fudge the count.
    absent_calls = [l for l in absent_calls if not l.strip().startswith("_absent()")]
    assert len(absent_calls) == 8, (
        f"expected 8 _absent call sites in test_batch_state_timestamp_field.sh, "
        f"found {len(absent_calls)}: {absent_calls}"
    )


def test_known_answer_batch_state_timestamp_field_joiner_actually_joins_continuations():
    """Non-vacuity guard for `join_shell_continuations` itself, not just for
    the fixture's call count above: the previous version of this fixture
    (`l.strip().startswith("_absent ")`) is satisfied by the UNjoined first
    physical line of every split call too - `_absent "$SPEC" "label" \\`
    already starts with `_absent ` before any joining happens, so disabling
    the continuation loop (`while False:`) left the suite green (14 passed,
    confirmed by the reviewer). This predicate additionally requires the
    logical line to END with the pattern's closing quote - true only when
    the trailing-backslash continuation line (which carries the quoted
    pattern, not the `_absent` keyword) has actually been joined onto the
    call line. Disabling the joiner leaves the pattern on its own orphan
    physical line, which never starts with `_absent `, so the count below
    drops to 0 and this test goes red - unlike its predecessor."""
    path = REPO_ROOT / "bin" / "tests" / "test_batch_state_timestamp_field.sh"
    text = path.read_text(encoding="utf-8")
    joined = [logical for _, logical in pmi.join_shell_continuations(text)]
    absent_calls = [
        l
        for l in joined
        if l.strip().startswith("_absent ") and l.rstrip().endswith(("'", '"'))
    ]
    absent_calls = [l for l in absent_calls if not l.strip().startswith("_absent()")]
    assert len(absent_calls) == 8, (
        f"expected 8 joined _absent call sites (call + closing quote of its "
        f"continuation line) in test_batch_state_timestamp_field.sh, "
        f"found {len(absent_calls)}: {absent_calls}"
    )


# ---------------------------------------------------------------------------
# Known-answer 4: test_loop_state_site_coverage.sh hardcodes FILE=<target>
# with no content/**-wide fallback - moving content into content/references/*
# leaves its scanned set even though its own numeric floors (which this
# tool does not separately re-derive for this consumer) still clear.
# ---------------------------------------------------------------------------


def test_known_answer_loop_state_site_coverage_leaves_scanned_set():
    ranges = [
        _range_for_heading(_HEADING_QA_GATE, "content/references/qa-loop-state.md"),
        _range_for_heading(_HEADING_QA_EVIDENCE, "content/references/qa-loop-state.md"),
    ]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [s for s in report.scanned_sets if s.consumer == "bin/tests/test_loop_state_site_coverage.sh"]
    assert hits, "expected a scanned-set finding for test_loop_state_site_coverage.sh"
    assert hits[0].scope == "single-file"
    assert hits[0].leaves_scanned_set is True


def test_loop_state_site_coverage_hardcodes_file_equals_target():
    """Pin on the fixture premise: FILE=<target>, single hardcoded file,
    no content/**-wide fallback anywhere in the gate."""
    path = REPO_ROOT / "bin" / "tests" / "test_loop_state_site_coverage.sh"
    text = path.read_text(encoding="utf-8")
    assert f"FILE={TARGET}" in text
    assert ".rglob(" not in text


# ---------------------------------------------------------------------------
# The 9-range run from the ticket brief: overall verdict must be FAIL
# (multiple known-answer breaks above), and both known-answer breaking
# consumers must be present, in one combined run.
# ---------------------------------------------------------------------------

NINE_RANGES = [
    _range_for_heading(_HEADING_TRACKER_WRITEBACK, "content/references/tracker-writeback.md"),
    _range_for_heading(_HEADING_OPEN_GOAL_LOOP, "content/references/open-goal-loop.md"),
    _range_for_heading(_HEADING_BATCH_RESUME_CHECK, "content/references/batch-mode.md"),
    _range_for_heading(_HEADING_BATCH_TRIAGE, "content/references/batch-mode.md"),
    _range_for_heading(_HEADING_ORCHESTRATION_PLAN, "content/references/orchestration-units.md"),
    _range_for_heading(_HEADING_PARALLEL_UNITS, "content/references/orchestration-units.md"),
    _range_for_heading(_HEADING_QA_GATE, "content/references/qa-loop-state.md"),
    _range_for_heading(_HEADING_QA_EVIDENCE, "content/references/qa-loop-state.md"),
    _range_for_heading(_HEADING_HANDOFF_EVAL, "content/references/handoff-evaluation.md"),
]


def test_nine_range_run_is_not_ok_and_covers_both_known_breaks():
    report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    assert not report.ok
    breaking_consumers = {a.consumer for a in report.assertions if a.breaks}
    assert "bin/tests/test_tracker_dev_complete_spec.py" in breaking_consumers
    assert "bin/tests/test_tasks_jsonl_fold.sh" in breaking_consumers
    leaving_scanned_set = {s.consumer for s in report.scanned_sets if s.leaves_scanned_set}
    assert "bin/tests/test_loop_state_site_coverage.sh" in leaving_scanned_set


def test_cli_exit_code_nonzero_on_the_nine_ranges():
    argv = []
    for r in NINE_RANGES:
        argv += ["--range", f"{r.start}:{r.end}:{r.dest}"]
    rc = pmi.main(argv)
    assert rc == 1


# ---------------------------------------------------------------------------
# Doc-consumer scoping: an arbitrary short word shared with the target's
# prose in a NON-checked file (e.g. a .github/prompts/*.md doc) must never
# be reported as a BREAKING assertion - this was the tool's first working
# version's dominant false-positive class (hundreds of rows on words like
# "default"/"status"/"worktree").
# ---------------------------------------------------------------------------


def test_doc_consumers_are_not_mechanically_gated_as_breaking():
    report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    doc_like = [c for c in report.doc_consumers if c.startswith(".github/") or c.startswith("content/commands/")]
    assert doc_like, "expected at least one doc-like consumer to be discovered"
    breaking_consumers = {a.consumer for a in report.assertions if a.breaks}
    assert not (set(doc_like) & breaking_consumers), (
        "a doc/prose consumer was mechanically flagged as BREAKING - "
        "checked-consumer scoping regressed"
    )


# ---------------------------------------------------------------------------
# Regression: Critical 1 (r1 Skeptic finding) - ERE grep patterns with
# regex metacharacters (`.`, `\+`) were matched via a naive literal
# substring find(), silently dropped when that found zero occurrences even
# though `grep -qiE` matches the same pattern against the live target fine.
# Confirmed failing pre-fix: this exact assertion produced ZERO BREAKING
# rows and ZERO UNRESOLVED entries for test_batch_state_timestamp_field.sh
# before the `_target_regex_occurrences`/`_resolve_literal_in_target` fix.
# ---------------------------------------------------------------------------


def test_regression_ere_metachar_pattern_resolves_via_regex_not_literal_find():
    ranges = [
        _range_for_heading(_HEADING_BATCH_RESUME_CHECK, "content/references/batch-mode.md"),
        _range_for_heading(_HEADING_BATCH_TRIAGE, "content/references/batch-mode.md"),
    ]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_batch_state_timestamp_field.sh"
        and "status=active" in a.detail
        and "10 min" in a.detail
    ]
    assert hits, (
        "expected the ERE-metachar patterns ('status=active. AND .updated_at "
        "> 10 min. ago' / '...<=10 min...') to resolve as literal_presence "
        "assertions, not vanish silently"
    )
    assert any(a.breaks for a in hits), "these patterns' only target lines fall inside the move range"
    assert any("resolved via ERE match" in a.detail for a in hits), (
        "expected at least one hit to be explicitly tagged as ERE-resolved "
        "(not a literal substring match)"
    )


def test_regression_ere_pattern_with_backslash_escaped_parens_is_extracted_at_all():
    """A stricter regression than the above: this pattern's backslash-
    escaped parens (`\\(session_id=<X>, updated_at=<Y>\\)`) made the OLD
    `_STR_RE` never even extract it as a candidate literal in the first
    place (its single-quote branch excluded any backslash from quoted
    content) - a distinct, earlier failure than the literal-vs-regex
    resolution gap the other regression test above covers."""
    ranges = [_range_for_heading(_HEADING_BATCH_RESUME_CHECK, "content/references/batch-mode.md")]
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_batch_state_timestamp_field.sh"
        and "session_id=<X>, updated_at=<Y>" in a.detail
    ]
    assert hits, "backslash-escaped-paren ERE pattern must be extracted and resolved, not silently dropped"


# ---------------------------------------------------------------------------
# Regression: Major 1 (r2 Skeptic finding) - `_is_meaningful_literal`'s
# short-token noise filter ran BEFORE `is_pattern_slot` was computed, so a
# pattern-slot literal (the actual `<pattern>` payload of a `_present`/
# `_absent` shell call) that happens to be short with no `[`:/=$]`
# punctuation was silently dropped with NO Assertion and NO Unresolved row -
# the identical silent-drop class as r1's Critical, one filter earlier in
# the same function. Confirmed failing pre-fix: `'mark-blocked-and-
# continue'`, `'fail-open'`, and `'<ISO8601>'` (three live pattern-slot
# literals in test_batch_state_timestamp_field.sh, none of which contain a
# backtick/colon/slash/equals/dollar) produced zero assertions and zero
# unresolved rows for that consumer under the 9-range run.
# ---------------------------------------------------------------------------


def test_regression_pattern_slot_literal_not_dropped_by_meaningfulness_filter():
    report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    hits = {
        a.detail: a
        for a in report.assertions
        if a.consumer == "bin/tests/test_batch_state_timestamp_field.sh"
        and a.kind == "literal_presence"
        and ("mark-blocked-and-continue" in a.detail or "fail-open" in a.detail or "<ISO8601>" in a.detail)
    }
    assert hits, (
        "expected literal_presence assertions for the 'mark-blocked-and-"
        "continue' / 'fail-open' / '<ISO8601>' pattern-slot literals - these "
        "must never be silently dropped by the meaningfulness filter"
    )
    mark_blocked = [a for d, a in hits.items() if "mark-blocked-and-continue" in d and d.startswith("asserts")]
    assert mark_blocked, f"expected a 'mark-blocked-and-continue' hit, got: {list(hits)}"
    assert any(a.breaks for a in mark_blocked), (
        "'mark-blocked-and-continue' has 3 of its 11 target occurrences inside "
        "a move range and must break"
    )


# ---------------------------------------------------------------------------
# Regression: Major 2 (r2 Skeptic finding) - `extract_regex_assertions`
# dropped `re.compile(...)`'s own compile-time FLAGS (re-compiled the
# pattern with no flags at all) and matched per-line instead of against the
# consumer's actual whole-text search, so a case-insensitive or newline-
# spanning pattern could report ZERO pre-move matches (silently
# reclassified as "cannot break") even though the real, flag-honoring
# match count is nonzero. Confirmed failing pre-fix via a synthetic
# consumer mirroring `_STALE_ENFORCER_SUBCOUNT_RE` (compiled
# `re.IGNORECASE`): matching 'ENFORCE THE SIX GATES' (uppercase) against a
# lowercase target line resolved to zero matches pre-fix, and a pattern
# containing `\n` inside a `[^.]{0,80}` character class never matched
# per-line even when its match spans two adjacent target lines that DO
# concatenate to a real cross-line match in the consumer's own whole-text
# `.search()`.
# ---------------------------------------------------------------------------


def test_regression_regex_assertion_honors_compile_flags_and_whole_text_match():
    """Pre-fix, `re.compile(pat)` re-compiled with no flags at all, so this
    IGNORECASE pattern found ZERO matches against the mixed-case target
    line and was reclassified as a resolved, non-breaking Assertion ('...
    matches ZERO lines in the pre-move target') instead of the correct
    UNRESOLVED-with-real-matches outcome below - silently converting a
    genuinely live, move-affected assertion into a false-clean pass."""
    consumer_text = (
        "import re\n"
        "_PATTERN_RE = re.compile(r'enforce the six gates', re.IGNORECASE)\n"
        "def check(text):\n"
        "    return bool(_PATTERN_RE.search(text))\n"
    )
    target_text = "line one\nEnforce the SIX gates now.\nline three\n"
    line_starts = pmi.build_line_starts(target_text)
    ranges = [pmi.MoveRange(start=2, end=2, dest="content/references/scratch.md")]
    assertions, unresolved = pmi.extract_regex_assertions(
        "scratch_consumer.py", consumer_text, target_text, line_starts, ranges
    )
    assert not assertions, "must not be resolved as a zero-match, non-breaking assertion"
    hits = [u for u in unresolved if "_PATTERN_RE" in u.detail]
    assert hits, "expected an UNRESOLVED row for _PATTERN_RE"
    assert "target lines [2]" in hits[0].detail, (
        f"expected the IGNORECASE-flagged pattern to actually match line 2, got: {hits[0].detail!r}"
    )
    assert "fall inside a proposed move range" in hits[0].detail


def test_regression_regex_assertion_matches_across_a_newline():
    """Pre-fix, a per-line scan never sees a DOTALL pattern that spans the
    boundary between two target lines - it was reclassified as a resolved,
    non-breaking 'matches ZERO lines' assertion even though the consumer's
    own whole-text `.search()` matches it fine."""
    consumer_text = (
        "import re\n"
        "_SPAN_RE = re.compile(r'alpha[^.]{0,20}beta', re.DOTALL)\n"
        "def check(text):\n"
        "    return bool(_SPAN_RE.search(text))\n"
    )
    target_text = "alpha\nbeta appears on the next line.\n"
    line_starts = pmi.build_line_starts(target_text)
    ranges = [pmi.MoveRange(start=2, end=2, dest="content/references/scratch.md")]
    assertions, unresolved = pmi.extract_regex_assertions(
        "scratch_consumer.py", consumer_text, target_text, line_starts, ranges
    )
    assert not assertions, "must not be resolved as a zero-match, non-breaking assertion"
    hits = [u for u in unresolved if "_SPAN_RE" in u.detail]
    assert hits, "expected an UNRESOLVED row for _SPAN_RE"
    assert "ZERO" not in hits[0].detail, (
        "a DOTALL pattern spanning the alpha/beta newline must match against "
        "the whole target text - a per-line scan sees zero matches here"
    )


# ---------------------------------------------------------------------------
# Regression: Minor (r2 Skeptic finding) - `Report.ok` ignored
# `scanned_sets` entirely, so a run whose ONLY finding was
# `leaves_scanned_set=True` (nothing broken, nothing unresolved) exited 0
# and printed `Verdict: OK` - the exact finding class the scanned-set
# column exists to surface, silently unenforced. Confirmed failing pre-fix
# by constructing a Report with zero assertions/unresolved and one
# leaves_scanned_set=True finding: `.ok` returned True.
# ---------------------------------------------------------------------------


def test_regression_scanned_set_only_finding_is_not_a_silent_ok():
    report = pmi.Report(
        target=TARGET,
        ranges=[],
        consumers=["bin/tests/test_loop_state_site_coverage.sh"],
        scanned_sets=[
            pmi.ScannedSetFinding(
                consumer="bin/tests/test_loop_state_site_coverage.sh",
                scope="single-file",
                detail="leaves scanned set",
                leaves_scanned_set=True,
            )
        ],
    )
    assert not report.assertions and not report.unresolved, "test setup sanity: nothing else should be flagging"
    assert not report.ok, (
        "a Report whose only finding is a left-behind scanned set must not "
        "report OK - this is the signature finding class the scanned-set "
        "column exists to surface"
    )


def test_known_answer_loop_state_site_coverage_makes_nine_range_report_fail():
    """Non-mocked confirmation of the Minor fix above against the real 9-
    range run: test_loop_state_site_coverage.sh's own scanned-set finding
    (already asserted separately above) must, on its own, be sufficient to
    flip the overall verdict - independent of whatever else in the 9-range
    run also breaks."""
    report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    scanned_only = [s for s in report.scanned_sets if s.leaves_scanned_set]
    assert scanned_only
    assert not report.ok


# ---------------------------------------------------------------------------
# Regression: Major 4 (r1 Skeptic finding) - analyze() returned a vacuous
# "OK" report when discovery found consumers but ZERO of them matched
# `_is_checked_consumer` (e.g. a bin/tests/ rename or SEARCH_DIRS drift).
# ---------------------------------------------------------------------------


def test_regression_zero_checked_consumers_is_not_a_silent_pass():
    with mock.patch.object(pmi, "_is_checked_consumer", return_value=False):
        report = pmi.analyze(
            REPO_ROOT,
            TARGET,
            [_range_for_heading(_HEADING_TRACKER_WRITEBACK, "content/references/tracker-writeback.md")],
        )
    assert not report.ok, (
        "zero CHECKED consumers (as opposed to zero discovered consumers, "
        "already covered by the mutation test below) must not silently "
        "report OK - this is the second, narrower non-vacuity guard"
    )
    assert any(
        u.consumer == "<discovery>" and "checked-consumer" in u.detail for u in report.unresolved
    )


# ---------------------------------------------------------------------------
# Mutation test: neuter discovery, confirm the suite goes red rather than
# silently reporting OK. This is the tool's own "fail loud, never silently
# skip" design constraint, made executable.
# ---------------------------------------------------------------------------


def test_mutation_zero_discovered_consumers_is_not_a_silent_pass():
    with mock.patch.object(pmi, "discover_consumers", return_value=[]):
        report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    assert not report.ok, (
        "neutering discover_consumers() to return zero consumers must NOT "
        "produce an OK report - a tool that reports 'nothing breaks' "
        "because it found nothing reproduces the exact failure mode it "
        "exists to prevent"
    )
    assert any(u.consumer == "<discovery>" for u in report.unresolved)


def test_mutation_known_answer_tests_would_fail_under_neutered_discovery():
    """Confirms the specific known-answer assertions above are NOT
    vacuously satisfied - re-run known-answer #1 and #2 under neutered
    discovery and show they lose their evidence entirely (no assertions
    found for that consumer at all), rather than happening to still pass."""
    with mock.patch.object(pmi, "discover_consumers", return_value=[]):
        report = pmi.analyze(
            REPO_ROOT,
            TARGET,
            [_range_for_heading(_HEADING_TRACKER_WRITEBACK, "content/references/tracker-writeback.md")],
        )
    hits = [a for a in report.assertions if a.consumer == "bin/tests/test_tracker_dev_complete_spec.py"]
    assert not hits, "neutered discovery must find zero evidence for the known-answer consumer"


# ---------------------------------------------------------------------------
# Differential test against GROUND TRUTH: simulate the post-move tree (the
# 9 ranges actually deleted from the target, their content actually
# written to the 6 destination files) and run the REAL executable gates
# against it, then compare their real pass/fail to this tool's prediction.
# Every other test here pins a specific extraction mechanism; this one
# pins the tool's actual JOB - but only for the 2 consumers in
# SCRATCH_GATES below, not the whole tool-clean set. A change to
# extraction logic that under-reports one of the other 5 tool-clean
# consumers (of the 7 the reviewer manually differential-tested) is NOT
# caught by this automated suite.
#
# Scope: the two shell gates that are the ground-truth consumers for this
# ticket's Critical findings - test_batch_state_timestamp_field.sh
# (Critical 1: ERE metachar patterns) and test_tasks_jsonl_fold.sh
# (Critical 2: the G6 floor). Both honor `GATE_REPO`/derive their root
# from their own `$0`, so they run unmodified against a scratch copy.
# Intentionally NOT run here: the other 5 tool-clean shell/pytest gates
# the reviewer additionally differential-tested by hand (6 of 7 candidates
# qualified automatically - pre-move-red skipped as environment-unfit,
# post-move rc compared to the tool's prediction for the survivors) - each
# has its own path-resolution and environment assumptions (jq
# availability, REPO_DIR conventions, fixture imports) that would need
# individual verification to include safely here, and the two included
# are sufficient to prove the differential-testing APPROACH works and to
# directly regression-guard the two Critical fixes. Extending
# SCRATCH_GATES below to cover more consumers is straightforward once each
# one's assumptions are checked - candidates: run each gate against a
# pre-move scratch copy first, skip any already red as environment-unfit,
# then compare only the survivors' post-move rc against this tool's
# prediction, exactly as the reviewer did manually.
# ---------------------------------------------------------------------------

SCRATCH_GATES = (
    "test_batch_state_timestamp_field.sh",
    "test_tasks_jsonl_fold.sh",
)


def _write_split_target(repo_root: Path, scratch_root: Path, target_rel: str, ranges: list) -> None:
    """Delete each range (1-indexed, inclusive) from a scratch copy of the
    target file, and append its content verbatim to the corresponding
    destination file (creating it - the destinations are all NEW files
    that don't exist on main yet, this being a proposed future split)."""
    lines = (repo_root / target_rel).read_text(encoding="utf-8").split("\n")
    sorted_ranges = sorted(ranges, key=lambda r: r.start)
    dest_content: dict[str, list[str]] = {}
    keep: list[str] = []
    cursor = 1
    for r in sorted_ranges:
        keep.extend(lines[cursor - 1 : r.start - 1])
        dest_content.setdefault(r.dest, []).extend(lines[r.start - 1 : r.end])
        cursor = r.end + 1
    keep.extend(lines[cursor - 1 :])
    (scratch_root / target_rel).write_text("\n".join(keep), encoding="utf-8")
    for dest, dest_lines in dest_content.items():
        dest_path = scratch_root / dest
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("\n".join(dest_lines) + "\n", encoding="utf-8")


def test_differential_against_ground_truth_post_move_gates(tmp_path):
    import os
    import shutil
    import subprocess

    scratch = tmp_path / "repo"
    # The whole content/ tree (~2 MB, ~100 files) rather than a hand-picked
    # subset: several of these gates scan `-- content` (a whole-directory
    # `git grep`), so cherry-picking files would silently under-populate
    # their scanned set and produce a false ground truth, not a faster one.
    shutil.copytree(REPO_ROOT / "content", scratch / "content")
    (scratch / "bin" / "tests").mkdir(parents=True)
    for script in SCRATCH_GATES:
        shutil.copy2(REPO_ROOT / "bin" / "tests" / script, scratch / "bin" / "tests" / script)

    _write_split_target(REPO_ROOT, scratch, TARGET, NINE_RANGES)

    subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
    subprocess.run(["git", "config", "user.email", "differential-test@example.com"], cwd=scratch, check=True)
    subprocess.run(["git", "config", "user.name", "differential-test"], cwd=scratch, check=True)
    subprocess.run(["git", "add", "-A"], cwd=scratch, check=True)

    report = pmi.analyze(REPO_ROOT, TARGET, NINE_RANGES)
    tool_breaking = {a.consumer for a in report.assertions if a.breaks}
    tool_unresolved = {u.consumer for u in report.unresolved}
    # UNRESOLVED is an acceptable verdict for either real outcome (fail-loud
    # by design) - a tool-flagged consumer is anything NOT reported clean.
    tool_flagged = tool_breaking | tool_unresolved

    under_reports = []
    over_reports = []
    for script in SCRATCH_GATES:
        consumer = f"bin/tests/{script}"
        env = dict(os.environ)
        env["GATE_REPO"] = str(scratch)
        proc = subprocess.run(
            ["bash", str(scratch / "bin" / "tests" / script)],
            cwd=scratch,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        really_fails = proc.returncode != 0
        tool_says_clean = consumer not in tool_flagged
        if really_fails and tool_says_clean:
            under_reports.append((consumer, proc.returncode, proc.stdout[-1500:], proc.stderr[-500:]))
        elif not really_fails and consumer in tool_breaking:
            # Over-report: the tool flagged it BREAKING but the real gate
            # still passes post-move. Tolerated (the reviewer measured
            # ~5%) - record it, do not fail the test on it.
            over_reports.append(consumer)

    assert not under_reports, (
        "DISQUALIFYING: the tool reported a consumer clean that actually "
        "fails against the real, simulated post-move tree:\n"
        + "\n".join(
            f"  {c}: rc={rc}\n    stdout(tail)={out!r}\n    stderr(tail)={err!r}"
            for c, rc, out, err in under_reports
        )
    )
    # over_reports is intentionally not asserted on - see docstring above.
    del over_reports


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
