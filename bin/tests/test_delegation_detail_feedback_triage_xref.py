#!/usr/bin/env python3
"""
Regression test: content/references/delegation-detail.md's Follow-up Ticket
Creation Discipline section cross-references content/commands/ds-feedback-
triage.md by SECTION NAME, not brittle line numbers.

Context (Skeptic Major 3, ticket-fanout-discipline branch): the original
cross-ref cited `ds-feedback-triage.md:32,68,206`. The same diff that added
the cross-ref inserted 5 lines earlier in ds-feedback-triage.md, silently
shifting `:206` to a blank line and the real target to `:211` - the exact
citation the diff had just written was already stale by the time it
landed. Section-name references are structurally immune to this class of
drift (a heading move/rename is a deliberate, visible edit; a line-number
shift from an unrelated earlier insertion is not).

This test pins two properties:
  1. delegation-detail.md's cross-ref to ds-feedback-triage.md uses the
     section-name form, not a `<file>:<line[,line...]>` citation.
  2. The cited section heading actually exists in ds-feedback-triage.md
     (catches a future rename of "Step 2 - Group and present" that would
     otherwise silently orphan the cross-ref).

Run with: python3 -m pytest bin/tests/test_delegation_detail_feedback_triage_xref.py -x
       or: python3 bin/tests/test_delegation_detail_feedback_triage_xref.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DELEGATION_DETAIL = REPO_ROOT / "content" / "references" / "delegation-detail.md"
FEEDBACK_TRIAGE = REPO_ROOT / "content" / "commands" / "ds-feedback-triage.md"

CITED_SECTION_NAME = "Step 2 - Group and present"

# A brittle `<file>:<digits>[,<digits>...]` citation - the exact shape that
# broke last time (ds-feedback-triage.md:32,68,206).
_BRITTLE_LINE_CITATION_RE = re.compile(
    r"ds-feedback-triage\.md:\d+(,\d+)*"
)


def test_feedback_triage_xref_uses_section_name_not_line_numbers() -> None:
    text = DELEGATION_DETAIL.read_text(encoding="utf-8")
    assert "ds-feedback-triage.md" in text, (
        "expected a cross-reference to ds-feedback-triage.md in "
        "delegation-detail.md's Follow-up Ticket Creation Discipline section"
    )
    assert not _BRITTLE_LINE_CITATION_RE.search(text), (
        "delegation-detail.md must not cite ds-feedback-triage.md by brittle "
        "line number(s) - use a section-name reference instead (this exact "
        "citation shape silently went stale within the same diff that added it)"
    )
    assert CITED_SECTION_NAME in text, (
        f"expected the section-name cross-reference {CITED_SECTION_NAME!r} "
        "in delegation-detail.md"
    )
    print("PASS test_feedback_triage_xref_uses_section_name_not_line_numbers")


def test_cited_section_heading_exists_in_feedback_triage() -> None:
    text = FEEDBACK_TRIAGE.read_text(encoding="utf-8")
    expected_heading = f"## {CITED_SECTION_NAME}"
    assert expected_heading in text, (
        f"delegation-detail.md cites the heading {CITED_SECTION_NAME!r}, but "
        f"ds-feedback-triage.md has no {expected_heading!r} heading - the "
        "cross-ref is orphaned (fix the cross-ref or restore the heading)"
    )
    print("PASS test_cited_section_heading_exists_in_feedback_triage")


if __name__ == "__main__":
    test_feedback_triage_xref_uses_section_name_not_line_numbers()
    test_cited_section_heading_exists_in_feedback_triage()
    print("All tests passed.")
