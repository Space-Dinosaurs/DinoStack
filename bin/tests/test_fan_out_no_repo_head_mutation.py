#!/usr/bin/env python3
"""
Module manifest
Purpose: Regression guard for the "Class 1" primary-checkout HEAD-mutation
         defect closed alongside hooks/enforce-worktree-write.py's Class 2
         fix. The fan-out span of content/commands/ds-implement-ticket.md
         (Phase 5's parallel-units merge phase through the start of Phase
         8.5) must never checkout or merge branches directly in $REPO - the
         primary shared checkout. All such operations must run inside a
         dedicated integration worktree ($INTEGRATION_WORKTREE), so a
         concurrent session's HEAD state (or a concurrent session's
         unmerged work landing in $REPO's working tree) can never leak into
         another session's plan/brief citations the way it did the night
         this guard was written (an architect's [verified-by-read] citation
         against bin/ds-evaluate:130-197 turned out to be reading a
         concurrent session's unmerged feature branch, sitting in $REPO
         because a prior conductor turn had switched $REPO's HEAD there).

Public API: none (standalone script; `pytest bin/tests/test_fan_out_no_repo_head_mutation.py`
            or `python3 bin/tests/test_fan_out_no_repo_head_mutation.py`).

Upstream deps: content/commands/ds-implement-ticket.md (the file under test,
               resolved relative to this script's own repo root - never the
               caller's cwd, so the test is stable when invoked from any
               directory or worktree).

Downstream consumers: CI (bin-tests / pytest suites); any future edit to the
                       fan-out merge phase or Phase 8 push logic in
                       ds-implement-ticket.md.

Failure modes: fails if the fan-out span (bounded by heading anchors, not
               hardcoded line numbers) contains a `git -C $REPO checkout` or
               `git -C $REPO merge` invocation, OR if either anchor heading
               is not found (a structural drift that would otherwise let
               this test silently stop covering anything - see
               test_anchors_present_and_ordered, which is what "prove it is
               not vacuous" cites).

Performance: sub-second; one file read, two regex sweeps.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

START_ANCHOR = "### If parallel independent units were identified:"
END_ANCHOR = "## Phase 8.5: QA evidence (conditional)"

# A primary-checkout HEAD mutation: checking out or merging a branch
# directly in $REPO (as opposed to $INTEGRATION_WORKTREE or a per-unit
# worktree path). Deliberately does NOT match `git -C "$INTEGRATION_WORKTREE"`
# or `git -C ${REPO}/.agentic/worktrees/...` forms - those are the sanctioned
# replacement mechanism this test exists to protect.
FORBIDDEN_PATTERNS = [
    re.compile(r"git\s+-C\s+\$REPO\s+checkout\b"),
    re.compile(r"git\s+-C\s+\$REPO\s+merge\b"),
]


def _read_target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _extract_span(text: str) -> str:
    start_idx = text.index(START_ANCHOR)
    end_idx = text.index(END_ANCHOR, start_idx)
    return text[start_idx:end_idx]


class TestFanOutSpanHasNoRepoHeadMutation(unittest.TestCase):
    def test_target_file_exists(self) -> None:
        self.assertTrue(
            TARGET.is_file(),
            f"expected file at {TARGET} - repo layout drifted?",
        )

    def test_anchors_present_and_ordered(self) -> None:
        """Prove-not-vacuous precondition: both anchors must exist, in order.

        If either heading is renamed or removed, `_extract_span` raises
        ValueError - fail loudly rather than silently matching an empty or
        unbounded span.
        """
        text = _read_target()
        self.assertIn(START_ANCHOR, text, "start anchor heading not found")
        self.assertIn(END_ANCHOR, text, "end anchor heading not found")
        start_idx = text.index(START_ANCHOR)
        end_idx = text.index(END_ANCHOR, start_idx)
        self.assertLess(start_idx, end_idx, "anchors are out of order")
        # Sanity: the span should be substantial (this is the whole fan-out
        # merge + Phase 8 push flow, not a stray one-liner).
        span = text[start_idx:end_idx]
        self.assertGreater(
            len(span), 5000, "fan-out span suspiciously short - anchors drifted?"
        )

    def test_no_repo_checkout_or_merge_in_fan_out_span(self) -> None:
        text = _read_target()
        span = _extract_span(text)
        offenders = []
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(span):
                line_no = span.count("\n", 0, match.start()) + 1
                offenders.append(f"line ~{line_no}: {match.group(0)!r}")
        self.assertEqual(
            offenders,
            [],
            "Found primary-checkout ($REPO) HEAD-mutating git invocation(s) "
            "in the fan-out span - this reintroduces the Class 1 defect "
            "(conductor switching $REPO's HEAD instead of using a dedicated "
            "$INTEGRATION_WORKTREE). Offenders:\n" + "\n".join(offenders),
        )

    def test_integration_worktree_mechanism_present(self) -> None:
        """Positive control: the replacement mechanism must actually be there,
        not just absent-forbidden-pattern (which a wholesale deletion of the
        merge phase would also satisfy vacuously)."""
        text = _read_target()
        span = _extract_span(text)
        self.assertIn("INTEGRATION_WORKTREE", span)
        self.assertRegex(
            span,
            re.compile(r'git\s+-C\s+\$REPO\s+worktree\s+add\s+"\$INTEGRATION_WORKTREE"'),
        )


if __name__ == "__main__":
    unittest.main()
