"""
Purpose: Regression tests for build_skeptic_prompt() - verifies the assembled
         prompt includes a well-formed ## Global-context inputs block that
         satisfies Skeptic Step 0 validation (per skeptic-protocol.md §4.5).

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.prompt (build_skeptic_prompt),
               evals.runner.loader (Fixture), evals/fixtures/skeptic/sk-001/.

Downstream consumers: pytest runner (evals/ test suite).

Failure modes: test isolation only; no I/O side effects beyond reading
               evals/fixtures/skeptic/sk-001/ (read-only).

Performance: standard; single file read plus string assertions.
"""
from __future__ import annotations

import pytest

from evals.runner.loader import load_component, load_fixtures
from evals.runner.prompt import build_skeptic_prompt


def _get_sk001_fixture():
    """Load sk-001 for prompt assembly tests."""
    manifest = load_component("skeptic")
    fixtures = load_fixtures(manifest)
    for f in fixtures:
        if f.id == "sk-001":
            return f
    pytest.skip("sk-001 fixture not found - cannot run prompt tests")


class TestSkepticPromptGlobalContextBlock:
    """The assembled skeptic prompt must include a valid ## Global-context inputs block."""

    def test_global_context_heading_present(self):
        """Block heading must be present so Skeptic Step 0 does not BLOCK."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "## Global-context inputs" in prompt

    def test_all_six_fields_present(self):
        """All 6 numbered fields must be present."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        for i in range(1, 7):
            assert f"{i}. " in prompt, f"Field {i} missing from prompt"

    def test_field_1_architect_plan(self):
        """Field 1: architect plan must use exact enumerated n/a string."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "1. Architect plan: n/a - Trivial direct edit" in prompt

    def test_field_2_brief_plan_artifact(self):
        """Field 2: Brief/Plan artifact must use exact enumerated n/a string."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "2. Brief / Plan tier artifact: n/a - Trivial direct edit" in prompt

    def test_field_3_qa_criteria(self):
        """Field 3: qa_criteria must use exact enumerated n/a string."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "n/a - Trivial direct edit" in prompt

    def test_field_4_per_consumer_impact(self):
        """Field 4: per-consumer table must use exact enumerated n/a string."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "n/a - non-shared-utility surface (importer count below 5 threshold)" in prompt

    def test_field_5_related_files_references_diff(self):
        """Field 5: related files must reference ./evals-fixture/diff.patch."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "5. Related files" in prompt
        # find field 5 line and assert it contains the diff path
        for line in prompt.splitlines():
            if line.startswith("5. Related files"):
                assert "./evals-fixture/diff.patch" in line, (
                    "Field 5 must reference ./evals-fixture/diff.patch"
                )
                break
        else:
            pytest.fail("Field 5 line not found in prompt")

    def test_field_6_diff_references_diff_file(self):
        """Field 6: diff under review must reference ./evals-fixture/diff.patch."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        assert "6. Diff under review: ./evals-fixture/diff.patch" in prompt

    def test_block_appears_after_resolved_issues_preflight(self):
        """## Global-context inputs must appear AFTER ## Resolved issues preflight."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        preflight_pos = prompt.index("## Resolved issues preflight")
        gci_pos = prompt.index("## Global-context inputs")
        assert gci_pos > preflight_pos, (
            "## Global-context inputs must appear after ## Resolved issues preflight"
        )

    def test_block_appears_before_signoff_instruction(self):
        """## Global-context inputs must appear BEFORE the sign-off instruction."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        gci_pos = prompt.index("## Global-context inputs")
        signoff_pos = prompt.index("Produce your sign-off")
        assert gci_pos < signoff_pos, (
            "## Global-context inputs must appear before the sign-off instruction"
        )

    def test_no_bare_na_strings(self):
        """All n/a values must be enumerated - bare 'n/a' is invalid per §4.5."""
        fixture = _get_sk001_fixture()
        prompt = build_skeptic_prompt(fixture)
        # Extract the GCI block lines
        lines = prompt.splitlines()
        in_gci = False
        gci_lines = []
        for line in lines:
            if line == "## Global-context inputs":
                in_gci = True
                continue
            if in_gci and line.startswith("## "):
                break
            if in_gci:
                gci_lines.append(line)
        for line in gci_lines:
            if "n/a" in line.lower():
                # Must not be a bare 'n/a' (i.e., must have ' - ' after n/a)
                assert "n/a - " in line, (
                    f"Bare 'n/a' found in GCI block (invalid per §4.5): {line!r}"
                )
