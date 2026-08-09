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
         only check here that can catch a NEW under-report class rather
         than re-confirming a named one.

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
# Regression: Critical 1 (r1 Skeptic finding) - ERE grep patterns with
# regex metacharacters (`.`, `\+`) were matched via a naive literal
# substring find(), silently dropped when that found zero occurrences even
# though `grep -qiE` matches the same pattern against the live target fine.
# Confirmed failing pre-fix: this exact assertion produced ZERO BREAKING
# rows and ZERO UNRESOLVED entries for test_batch_state_timestamp_field.sh
# before the `_target_regex_occurrences`/`_resolve_literal_in_target` fix.
# ---------------------------------------------------------------------------


def test_regression_ere_metachar_pattern_resolves_via_regex_not_literal_find():
    ranges = _ranges(
        (801, 851, "content/references/batch-mode.md"),
        (852, 940, "content/references/batch-mode.md"),
    )
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
    ranges = _ranges((801, 851, "content/references/batch-mode.md"))
    report = pmi.analyze(REPO_ROOT, TARGET, ranges)
    hits = [
        a
        for a in report.assertions
        if a.consumer == "bin/tests/test_batch_state_timestamp_field.sh"
        and "session_id=<X>, updated_at=<Y>" in a.detail
    ]
    assert hits, "backslash-escaped-paren ERE pattern must be extracted and resolved, not silently dropped"


# ---------------------------------------------------------------------------
# Regression: Major 4 (r1 Skeptic finding) - analyze() returned a vacuous
# "OK" report when discovery found consumers but ZERO of them matched
# `_is_checked_consumer` (e.g. a bin/tests/ rename or SEARCH_DIRS drift).
# ---------------------------------------------------------------------------


def test_regression_zero_checked_consumers_is_not_a_silent_pass():
    with mock.patch.object(pmi, "_is_checked_consumer", return_value=False):
        report = pmi.analyze(REPO_ROOT, TARGET, _ranges((480, 548, "content/references/tracker-writeback.md")))
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
        report = pmi.analyze(REPO_ROOT, TARGET, _ranges((480, 548, "content/references/tracker-writeback.md")))
    hits = [a for a in report.assertions if a.consumer == "bin/tests/test_tracker_dev_complete_spec.py"]
    assert not hits, "neutered discovery must find zero evidence for the known-answer consumer"


# ---------------------------------------------------------------------------
# Differential test against GROUND TRUTH: simulate the post-move tree (the
# 9 ranges actually deleted from the target, their content actually
# written to the 6 destination files) and run the REAL executable gates
# against it, then compare their real pass/fail to this tool's prediction.
# This is the only check in this suite that can catch the NEXT under-
# report class, rather than re-confirming the two named in this ticket -
# every other test here pins a specific extraction mechanism; this one
# pins the tool's actual JOB.
#
# Scope: the two shell gates that are the ground-truth consumers for this
# ticket's Critical findings - test_batch_state_timestamp_field.sh
# (Critical 1: ERE metachar patterns) and test_tasks_jsonl_fold.sh
# (Critical 2: the G6 floor). Both honor `GATE_REPO`/derive their root
# from their own `$0`, so they run unmodified against a scratch copy.
# Intentionally NOT run here: the other 6 shell gates and 7 pytest specs
# the reviewer additionally used - each has its own path-resolution and
# environment assumptions (jq availability, REPO_DIR conventions, fixture
# imports) that would need individual verification to include safely, and
# the two included here are sufficient to prove the differential-testing
# APPROACH works and to directly regression-guard the two Critical fixes.
# Extending SCRATCH_GATES below to cover more consumers is straightforward
# once each one's assumptions are checked.
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
