#!/usr/bin/env python3
"""
Purpose: Regression guard for the defect fixed in
         content/commands/ds-update-agentic-engineering.md Step 1.5 (the
         vision-alignment check): that step used to hardcode an inline list
         of North Star pillar names, which silently went stale the moment
         docs/overview/vision.md grew from 4 pillars to 7. The fix replaced
         the inline list with an instruction to read the pillar set from
         vision.md itself. This test pins that fix as a durable invariant -
         it derives the CURRENT pillar names from docs/overview/vision.md at
         test time (not a hardcoded list of its own, which would reproduce
         the exact defect it exists to catch) and asserts none of them
         appear inside the Step 1.5 section specifically, plus that the
         "read it from the file" instruction is still present.

         Scope note (honest limitation, not engineered around): the
         resilience here is to a pillar's WORDING changing or a NEW pillar
         being appended - both are covered because the signature list is
         derived from vision.md at test time. It is not resilient to
         someone writing a differently-phrased summary of an existing
         pillar that doesn't share a 4-word prefix with vision.md's bolded
         name (e.g. paraphrasing "Guard operator attention" as "protect
         operator focus"). A targeted prefix-substring check that is
         resilient to the one thing that actually caused this defect
         (pillar count growing) beats a fuzzier semantic check that risks
         failing obscurely.

Public API: pytest test module. Run with
              python3 -m pytest bin/tests/test_ds_update_pillar_check_no_inline_list.py -q
            (auto-discovered by `.github/workflows/bin-tests.yml`'s
            `python3 -m pytest bin/tests/ -q` invocation - no separate CI
            wiring required).

Upstream deps: docs/overview/vision.md (pillar names, read live - never
               hardcoded here); content/commands/ds-update-agentic-engineering.md
               Step 1.5 section.

Downstream consumers: none (leaf test module).

Failure modes: a failure here means either Step 1.5 regressed back to an
               inline pillar enumeration, or the "read the pillar set from
               vision.md" instruction was removed/weakened.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VISION_PATH = REPO_ROOT / "docs" / "overview" / "vision.md"
COMMAND_PATH = REPO_ROOT / "content" / "commands" / "ds-update-agentic-engineering.md"

# How many leading words of each pillar's bolded name to use as a
# staleness signature. Short enough to survive minor rewording of the
# rest of the sentence, long enough not to false-positive on common words.
SIGNATURE_WORD_COUNT = 3

PILLAR_HEADING_RE = re.compile(r"^\d+\.\s+\*\*(.+?)\.\*\*", re.MULTILINE)


def _extract_pillar_signatures() -> list[str]:
    """Derive lowercase word-prefix signatures for every pillar currently
    listed in docs/overview/vision.md. Never hand-maintain this list - that
    is precisely the staleness class this test exists to catch."""
    text = VISION_PATH.read_text(encoding="utf-8")
    names = PILLAR_HEADING_RE.findall(text)
    assert names, (
        "PILLAR_HEADING_RE matched zero pillar headings in vision.md - "
        "the numbered-bold-heading format probably changed; update the "
        "regex, don't skip this test."
    )
    signatures = []
    for name in names:
        # Drop a trailing parenthetical alias, e.g. "Works for everyone
        # (universality)" -> "Works for everyone".
        name = re.sub(r"\s*\(.*?\)\s*$", "", name)
        words = name.lower().split()
        signatures.append(" ".join(words[:SIGNATURE_WORD_COUNT]))
    return signatures


def _extract_step_1_5_section() -> str:
    """Return the normalized (lowercased, whitespace-collapsed) text of
    Step 1.5 only - bounded at the next '## ' heading - so a legitimate
    pillar mention elsewhere in the file can't false-positive this test."""
    text = COMMAND_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## ") and "Step 1.5" in line:
            start = i
            continue
        if start is not None and line.startswith("## "):
            end = i
            break
    assert start is not None, (
        "Could not locate the '## Step 1.5' heading in "
        f"{COMMAND_PATH} - it may have been renamed or renumbered; "
        "update this test's heading match if that was deliberate."
    )
    section = "\n".join(lines[start:end])
    return " ".join(section.lower().split())


def test_step_1_5_has_no_inline_pillar_enumeration():
    signatures = _extract_pillar_signatures()
    section = _extract_step_1_5_section()
    hits = [sig for sig in signatures if sig in section]
    assert not hits, (
        "Step 1.5 of ds-update-agentic-engineering.md contains an inline "
        f"pillar-name fragment ({hits}) derived from the CURRENT "
        "docs/overview/vision.md pillar list. This reproduces the fixed "
        "defect: hardcoding pillar names here goes stale the next time "
        "vision.md's pillar set changes. Point the reader at vision.md's "
        "own list instead of naming pillars inline."
    )


def test_step_1_5_still_instructs_reading_pillars_from_vision_file():
    section = _extract_step_1_5_section()
    assert "pillar set from the file itself" in section, (
        "Step 1.5 no longer instructs the reader to take the pillar set "
        "from docs/overview/vision.md itself. A test that only checks for "
        "the ABSENCE of an inline list would pass even if this whole "
        "instruction were deleted - this is the paired positive assertion."
    )
