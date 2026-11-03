#!/usr/bin/env python3
"""
Spec test for /ds-implement-ticket Phase 5 §Low route step 3: the cleanup
before the quality gate must never delete or restore a file the change
itself created, moved or edited. Step 4 stages those files, so a step 3
that removes untracked entries without that scope deletes the change's own
new files before they are gated.

Run with: python3 -m pytest bin/tests/test_low_route_cleanup_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMMAND_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

KEEP_SENTENCE = "Keep every file the change created, moved or edited."
SCOPE_SENTENCE = "Each other entry"


def _low_route_step(number: int) -> str:
    text = COMMAND_PATH.read_text(encoding="utf-8")
    start = text.index("### Low route (conductor implements)")
    end = text.index("\n### ", start + 1)
    section = text[start:end]
    match = re.search(rf"(?m)^{number}\. .*$", section)
    assert match, f"Low route step {number} not found"
    return match.group(0)


def test_step3_keeps_the_change_before_any_cleanup():
    step = _low_route_step(3)
    assert step.startswith(f"3. {KEEP_SENTENCE}"), (
        "step 3 must open by keeping every file the change created, moved or "
        "edited, so no reading of its cleanup applies to them"
    )


def test_step3_cleanup_applies_only_to_other_entries():
    step = _low_route_step(3)
    scope_idx = step.index(SCOPE_SENTENCE)
    for verb in ("delete", "restore", "clean -fd"):
        for match in re.finditer(re.escape(verb), step):
            assert match.start() > scope_idx, (
                f"step 3 says {verb!r} before scoping the cleanup to entries "
                "that are not part of the change"
            )
