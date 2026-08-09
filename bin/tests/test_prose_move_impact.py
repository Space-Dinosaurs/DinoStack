#!/usr/bin/env python3
"""
Purpose: Known-answer and mutation tests for scripts/prose-move-impact.py -
         the mechanical "what breaks if I move these line ranges" enumerator
         built to replace four failed prose-only review rounds on splitting
         content/commands/ds-implement-ticket.md. Each known-answer case
         below is a REAL, previously-verified miss from those rounds, not a
         synthetic example.

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
               bin/tests/test_loop_state_site_coverage.sh).

Downstream consumers: none (leaf test module).

Failure modes: a known-answer test failing means either the tool regressed,
               or the live target file's line numbers drifted out from
               under one of the fixture's proposed ranges - re-verify the
               range against a fresh `grep -n '^## '` before assuming the
               tool is at fault. The mutation test intentionally breaks the
               tool's own discovery step and asserts the suite goes red;
               a green mutation test means the tool would silently report
               "nothing breaks" on total discovery failure - exactly the
               failure mode design constraint prohibits.

Performance: single-digit seconds; a handful of `git grep` subprocess calls
             plus small in-repo file reads.
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


def _ranges(*triples):
    return [pmi.MoveRange(start=s, end=e, dest=d) for (s, e, d) in triples]


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
    """The 9 proposed ranges from the ticket brief, re-verified against the
    live target: each range's start is a real heading line and its end is
    the line immediately before the next heading of <= that level."""
    target_path = REPO_ROOT / TARGET
    lines = target_path.read_text(encoding="utf-8").split("\n")
    headings = pmi.fence_aware_headings(lines)
    proposed_starts = {480, 730, 801, 852, 1369, 1651, 2041, 2367, 3495}
    heading_starts = {h.line for h in headings}
    missing = proposed_starts - heading_starts
    assert not missing, f"proposed range start(s) no longer align with a live heading: {missing}"


# ---------------------------------------------------------------------------
# Known-answer 1: test_tracker_dev_complete_spec.py's _extract_block reader
# breaks when 480-548 (## Tracker Writeback Helper) moves.
# ---------------------------------------------------------------------------


def test_known_answer_tracker_dev_complete_heading_block_breaks():
    ranges = _ranges((480, 548, "content/references/tracker-writeback.md"))
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
    ranges = _ranges((3495, 3551, "content/references/handoff-evaluation.md"))
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
    ranges = _ranges(
        (1369, 1458, "content/references/orchestration-units.md"),
        (1651, 1763, "content/references/orchestration-units.md"),
    )
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_tasks_jsonl_fold.sh" and a.kind == "grep_count_floor"
    ]
    assert hits, "expected a grep_count_floor assertion for test_tasks_jsonl_fold.sh"
    breaking = [a for a in hits if a.breaks]
    assert breaking, "FOLDSPEC per-file floor for the target file must break: before=14, after=4, floor>=7"
    assert "after=4" in breaking[0].detail
    assert "floor >= 7" in breaking[0].detail
    assert not report.ok


def test_known_answer_tasks_jsonl_fold_heredoc_floor_stays_green_when_untouched():
    ranges = _ranges((3495, 3551, "content/references/handoff-evaluation.md"))
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


# ---------------------------------------------------------------------------
# Known-answer 4: test_loop_state_site_coverage.sh hardcodes FILE=<target>
# with no content/**-wide fallback - moving content into content/references/*
# leaves its scanned set even though its own numeric floors (which this
# tool does not separately re-derive for this consumer) still clear.
# ---------------------------------------------------------------------------


def test_known_answer_loop_state_site_coverage_leaves_scanned_set():
    ranges = _ranges(
        (2041, 2174, "content/references/qa-loop-state.md"),
        (2367, 2525, "content/references/qa-loop-state.md"),
    )
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

NINE_RANGES = _ranges(
    (480, 548, "content/references/tracker-writeback.md"),
    (730, 800, "content/references/open-goal-loop.md"),
    (801, 851, "content/references/batch-mode.md"),
    (852, 940, "content/references/batch-mode.md"),
    (1369, 1458, "content/references/orchestration-units.md"),
    (1651, 1763, "content/references/orchestration-units.md"),
    (2041, 2174, "content/references/qa-loop-state.md"),
    (2367, 2525, "content/references/qa-loop-state.md"),
    (3495, 3551, "content/references/handoff-evaluation.md"),
)


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
        report = pmi.analyze(REPO_ROOT, TARGET, _ranges((480, 548, "content/references/tracker-writeback.md")))
    hits = [a for a in report.assertions if a.consumer == "bin/tests/test_tracker_dev_complete_spec.py"]
    assert not hits, "neutered discovery must find zero evidence for the known-answer consumer"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
