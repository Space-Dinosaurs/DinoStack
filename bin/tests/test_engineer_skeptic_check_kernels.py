#!/usr/bin/env python3
"""
Regression spec for the engineer.md/skeptic.md shared pre-submit-check
fragment transclusion (content/fragments/pre-submit-check-kernels.md,
scripts/stamp-agent-fragments.sh).

Transclusion (the stamp script + agent-fragment-sync CI gate) guarantees the
WORDING inside a `<!-- shared:<id> -->` span stays byte-identical between
content/agents/engineer.md and content/agents/skeptic.md. It cannot guarantee
that a step CITATION embedded in prose ("skeptic.md step 4.5") still points
at a step that exists, or bears the title it did when the citation was
written - a renumber or retitle on the skeptic.md side is invisible to the
stamp script, because the citation text itself is not a `shared:` span.
These two tests cover that address-accuracy gap directly.
"""

import re
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
ENGINEER_MD = REPO_DIR / "content" / "agents" / "engineer.md"
SKEPTIC_MD = REPO_DIR / "content" / "agents" / "skeptic.md"
ARCHITECT_MD = REPO_DIR / "content" / "agents" / "architect.md"

# Maps each "skeptic.md step N.N" citation found in engineer.md's pre-submit
# self-check block to the title keyword that step must still carry in
# skeptic.md. Derived from the live citations in engineer.md's Pre-submit
# self-check bullets as of the content-layer transclusion fix.
CITATION_TO_TITLE_KEYWORD = {
    "4.5": "Cross-file reference-consistency check",
    "4.6": "Async error-handling check",
    "11.5": "New-test-CI-wiring check",
    "7": "Per-consumer impact check",
}


class TestEngineerCitationsLocateSkepticSteps(unittest.TestCase):
    """Step citations in engineer.md ("step 4.5", "step 4.6", "step 11.5",
    "step 7") still locate a step in skeptic.md bearing the expected title
    keyword - catches renumbering/retitling on the skeptic.md side."""

    def setUp(self):
        self.engineer_text = ENGINEER_MD.read_text(encoding="utf-8")
        self.skeptic_text = SKEPTIC_MD.read_text(encoding="utf-8")

    def test_engineer_cites_all_expected_skeptic_steps(self):
        cited = set(re.findall(r"skeptic\.md step ([0-9]+(?:\.[0-9]+)?)", self.engineer_text))
        expected = set(CITATION_TO_TITLE_KEYWORD.keys())
        self.assertEqual(
            cited,
            expected,
            "engineer.md's set of 'skeptic.md step N' citations changed - "
            "update CITATION_TO_TITLE_KEYWORD in this test to match.",
        )

    def test_each_cited_step_exists_in_skeptic_with_expected_title(self):
        for step_number, title_keyword in CITATION_TO_TITLE_KEYWORD.items():
            with self.subTest(step=step_number):
                # Match a numbered step line like "4.5. **Cross-file
                # reference-consistency check.**" or "7. **Per-consumer
                # impact check**" at the start of a line in skeptic.md.
                pattern = re.compile(
                    r"^" + re.escape(step_number) + r"\.\s+\*\*" + re.escape(title_keyword),
                    re.MULTILINE,
                )
                self.assertRegex(
                    self.skeptic_text,
                    pattern,
                    f"engineer.md cites 'skeptic.md step {step_number}' expecting a step "
                    f"titled '{title_keyword}', but no such numbered step exists in "
                    "skeptic.md - it was renumbered, retitled, or removed.",
                )


class TestReferencedSectionsStillExist(unittest.TestCase):
    """skeptic.md still has its per-consumer step and architect.md still has
    its 'Per-consumer impact table' heading - catches a referenced section
    vanishing entirely (not merely being renumbered)."""

    def test_skeptic_has_per_consumer_impact_check_step(self):
        skeptic_text = SKEPTIC_MD.read_text(encoding="utf-8")
        self.assertIn(
            "Per-consumer impact check",
            skeptic_text,
            "skeptic.md no longer has a 'Per-consumer impact check' step - "
            "engineer.md's pre-submit bullet cites this by name.",
        )

    def test_architect_has_per_consumer_impact_table_section(self):
        architect_text = ARCHITECT_MD.read_text(encoding="utf-8")
        self.assertIn(
            "Per-consumer impact table",
            architect_text,
            "architect.md no longer has a 'Per-consumer impact table' section - "
            "engineer.md's pre-submit bullet cites this by name.",
        )


if __name__ == "__main__":
    unittest.main()
