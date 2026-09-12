#!/usr/bin/env python3
"""
Round-5 regression guard for content/references/subagent-protocol.md
Section 11's "Spawn-brief provenance" paragraph: a durability guard, not a
correctness re-check. A round-4 Skeptic independently re-derived all 18
cells of the paragraph's role/mechanism enumeration and found every one
currently correct - the defect is that nothing in the suite asserts this
mechanically, so a future edit can silently falsify any cell (one of three
consecutive rounds of hand-verification of this exact paragraph was itself
wrong).

Design decision: derive the expected sets FROM Section 11's own prose via
regex, then compare against the actual state of content/agents/*.md -
rather than hand-listing the expected files/fields directly in this test.
A hand-listed test would reproduce the same defect class one level down:
it would pin whatever the test's author currently believes the four agent
files look like, and could pass even after Section 11's own prose drifted
away from that state (the round-3 failure mode this round exists to
close). Deriving from Section 11's text means the test's expectation moves
whenever Section 11's prose moves - what it catches is Section 11's prose
saying something the actual files do not back up, in either direction:
the paragraph claiming a file declares something it does not (round-3's
failure shape), or a file declaring something the paragraph fails to
mention (the mirror-image failure, never previously guarded).

The Notes-declaring file check (`_assert_notes_declaring_files_match`) is
bidirectional set equality, never containment - this repo has a recorded
defect class where a containment check passed while the compared sets had
actually diverged (see AGENTS.md, "Count-sync numeral blind spot" /
KNW-20260818-016 family). The other two checks are narrower by design and
do not claim the same bidirectional coverage: the qa-engineer field check
(`_assert_qa_engineer_fields_present`) confirms only the two fields Section
11 names are still declared in qa-engineer.md, and the architect carve-out
check (`_assert_architect_carveout_consistent`) confirms only architect.md
specifically - membership in the parsed carve-out set, presence of its
cited directive as a real template-directive line (not merely quoted
inline as prose elsewhere in the file), and absence of the Notes heading.
Neither checks the full carve-out enumeration's other 8 entries
(`perf-analyst.md`, `dependency-auditor.md`, `learning-extractor.md`,
`learnings-agent.md`, `wrap-ticket.md`, `adr-drift-detector.md`,
`goal-condition-evaluator.md`, `release-orchestrator.md`) against disk -
that remains unguarded and is not claimed here.

Every parse helper below asserts non-empty/non-None on its own regex match
before returning, so a Section 11 rewrite that breaks a parse pattern
fails loudly with a "could not locate ..." message rather than silently
producing an empty set that would make a bidirectional-equality comparison
pass vacuously.

Retirement condition: none while Section 11 states its role/mechanism
enumeration as prose. If a future change replaces the prose enumeration
with a machine-readable manifest (e.g. a YAML table), this test's parsing
layer becomes unnecessary and should be rewritten against that manifest
directly - not retired outright, since the bidirectional-equality property
itself must still be asserted somehow.

Run with:
    python3 -m pytest bin/tests/test_section11_provenance_enumeration_spec.py -q
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SUBAGENT_PROTOCOL_REL = Path("content/references/subagent-protocol.md")
AGENTS_DIR_REL = Path("content/agents")

NOTES_HEADING = "### Notes [ADVISORY]"

# A real markdown heading occupies its own line; matching only the bare
# substring would also match the heading text quoted inline as prose
# (e.g. a sentence referencing "the `### Notes [ADVISORY]` field" without
# declaring the heading itself) - anchor to line start.
NOTES_HEADING_LINE_RE = re.compile(
    r"^" + re.escape(NOTES_HEADING) + r"\s*$", re.MULTILINE
)

PARAGRAPH_MARKER = "**Spawn-brief provenance:**"

NOTES_LIST_RE = re.compile(
    r"folds it there instead\s*-\s*((?:`[\w.\-]+\.md`(?:,|\s|and)*)+)"
    r"each declare one",
)

QA_FIELDS_RE = re.compile(
    r"`qa-engineer\.md`'s `([\w_]+)`/`([\w_]+)` pair",
)

CARVEOUT_RE = re.compile(
    r"is carved out of this reporting half only.*?duty:\s*(.+?)\)\.\s*"
    r"`adr-generator\.md`",
    re.DOTALL,
)

ARCHITECT_PHRASE_RE = re.compile(
    r"architect\.md`\s*\(Shape 1, its `([^`]+)` template declares no"
)

MD_FILENAME_RE = re.compile(r"`([\w.\-]+\.md)`")


def _load_provenance_paragraph(root: Path) -> str:
    path = root / SUBAGENT_PROTOCOL_REL
    assert path.is_file(), f"missing file: {path}"
    text = path.read_text(encoding="utf-8")
    idx = text.find(PARAGRAPH_MARKER)
    assert idx != -1, (
        "content/references/subagent-protocol.md no longer contains the "
        "'**Spawn-brief provenance:**' paragraph marker - Section 11 may "
        "have been restructured; this test cannot locate the enumeration "
        "it is supposed to derive from"
    )
    rest = text[idx:]
    end = rest.find("\n\n")
    paragraph = rest if end == -1 else rest[:end]
    assert paragraph.strip(), "located an empty Spawn-brief provenance paragraph"
    return paragraph


def _parse_notes_declaring_files(paragraph: str) -> set[str]:
    match = NOTES_LIST_RE.search(paragraph)
    assert match is not None, (
        "could not locate the '... each declare one' Notes-declaring file "
        "list inside Section 11's Spawn-brief provenance paragraph - the "
        "enumeration this test derives from may have been reworded"
    )
    files = set(MD_FILENAME_RE.findall(match.group(1)))
    assert files, "parsed an empty Notes-declaring file set from Section 11"
    return files


def _parse_qa_engineer_fields(paragraph: str) -> tuple[str, str]:
    match = QA_FIELDS_RE.search(paragraph)
    assert match is not None, (
        "could not locate qa-engineer.md's schema-field-pair citation "
        "inside Section 11's Spawn-brief provenance paragraph"
    )
    return match.group(1), match.group(2)


def _parse_carveout_files(paragraph: str) -> set[str]:
    match = CARVEOUT_RE.search(paragraph)
    assert match is not None, (
        "could not locate the reporting-half carve-out file list inside "
        "Section 11's Spawn-brief provenance paragraph"
    )
    files = set(MD_FILENAME_RE.findall(match.group(1)))
    assert files, "parsed an empty carve-out file set from Section 11"
    return files


def _parse_architect_exact_structure_phrase(paragraph: str) -> str:
    match = ARCHITECT_PHRASE_RE.search(paragraph)
    assert match is not None, (
        "could not locate architect.md's exact-structure template phrase "
        "citation inside Section 11's carve-out list"
    )
    return match.group(1)


def _actual_notes_declaring_files(root: Path) -> set[str]:
    agents_dir = root / AGENTS_DIR_REL
    assert agents_dir.is_dir(), f"missing directory: {agents_dir}"
    found: set[str] = set()
    for path in sorted(agents_dir.glob("*.md")):
        if NOTES_HEADING_LINE_RE.search(path.read_text(encoding="utf-8")):
            found.add(path.name)
    return found


def _assert_notes_declaring_files_match(root: Path) -> None:
    paragraph = _load_provenance_paragraph(root)
    claimed = _parse_notes_declaring_files(paragraph)
    actual = _actual_notes_declaring_files(root)
    assert claimed == actual, (
        f"Section 11's Notes-declaring enumeration {sorted(claimed)} does "
        f"not match the actual set of content/agents/*.md files containing "
        f"'{NOTES_HEADING}': {sorted(actual)}"
    )


def _assert_qa_engineer_fields_present(root: Path) -> None:
    paragraph = _load_provenance_paragraph(root)
    field_a, field_b = _parse_qa_engineer_fields(paragraph)
    qa_path = root / AGENTS_DIR_REL / "qa-engineer.md"
    assert qa_path.is_file(), f"missing file: {qa_path}"
    text = qa_path.read_text(encoding="utf-8")
    for field in (field_a, field_b):
        assert re.search(rf"\b{re.escape(field)}\s*:", text), (
            f"qa-engineer.md no longer declares the '{field}' schema field "
            "cited by Section 11's Spawn-brief provenance paragraph"
        )


def _assert_architect_carveout_consistent(root: Path) -> None:
    paragraph = _load_provenance_paragraph(root)
    carveout = _parse_carveout_files(paragraph)
    assert "architect.md" in carveout, (
        "Section 11 no longer lists architect.md in its reporting-half "
        "carve-out enumeration"
    )
    phrase = _parse_architect_exact_structure_phrase(paragraph)
    architect_path = root / AGENTS_DIR_REL / "architect.md"
    assert architect_path.is_file(), f"missing file: {architect_path}"
    text = architect_path.read_text(encoding="utf-8")
    # Plain containment is self-satisfied by architect.md's own round-5
    # "Spawn-brief neutrality" sentence, which quotes this exact phrase
    # inline as prose (`the "..." template below declares no ...`) - that
    # quotation is not the template directive Section 11 cites, so a future
    # edit could delete the real directive line while leaving the inline
    # quotation intact and this assertion would still pass. Anchor to the
    # phrase occupying its own line, the same anchoring the round-5
    # NOTES_HEADING_LINE_RE fix already applies in the mirror direction.
    assert re.search(r"(?m)^" + re.escape(phrase), text), (
        f"architect.md no longer contains the exact-structure phrase "
        f"'{phrase}' as its own template directive line (only an inline "
        f"prose quotation of it, if any, would not count) - Section 11 "
        f"cites this directive as its reason for the carve-out"
    )
    assert not NOTES_HEADING_LINE_RE.search(text), (
        "architect.md now declares '### Notes [ADVISORY]' but Section 11 "
        "still lists architect.md in the carve-out enumeration of files "
        "that declare no such field - the two are now inconsistent"
    )


def test_live_repo_notes_declaring_files_match_section11_enumeration() -> None:
    _assert_notes_declaring_files_match(REPO_ROOT)


def test_live_repo_qa_engineer_declares_both_provenance_schema_fields() -> None:
    _assert_qa_engineer_fields_present(REPO_ROOT)


def test_live_repo_architect_carveout_is_consistent() -> None:
    _assert_architect_carveout_consistent(REPO_ROOT)


def _build_fixture_root(tmp_path: Path) -> Path:
    """Copy subagent-protocol.md and every content/agents/*.md file into a
    pytest tmp_path root (never the repo itself) so mutation tests can
    edit a copy without touching the live tree."""
    fixture_root = tmp_path / "mutated-repo-section11"
    dst_protocol = fixture_root / SUBAGENT_PROTOCOL_REL
    dst_protocol.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / SUBAGENT_PROTOCOL_REL, dst_protocol)

    dst_agents_dir = fixture_root / AGENTS_DIR_REL
    dst_agents_dir.mkdir(parents=True, exist_ok=True)
    for path in (REPO_ROOT / AGENTS_DIR_REL).glob("*.md"):
        shutil.copy2(path, dst_agents_dir / path.name)

    return fixture_root


def test_mutation_removing_notes_heading_from_one_file_fails(tmp_path: Path) -> None:
    fixture_root = _build_fixture_root(tmp_path)

    # Baseline: the freshly-copied fixture passes.
    _assert_notes_declaring_files_match(fixture_root)

    debugger_path = fixture_root / AGENTS_DIR_REL / "debugger.md"
    text = debugger_path.read_text(encoding="utf-8")
    assert NOTES_HEADING in text, "fixture setup assumption violated"
    mutated_text = text.replace(NOTES_HEADING, "### Notes (informal)", 1)
    assert mutated_text != text, "mutation substitution did not apply"
    debugger_path.write_text(mutated_text, encoding="utf-8")

    with pytest.raises(AssertionError) as excinfo:
        _assert_notes_declaring_files_match(fixture_root)
    assert "debugger.md" in str(excinfo.value)


def test_mutation_adding_notes_heading_to_architect_fails(tmp_path: Path) -> None:
    fixture_root = _build_fixture_root(tmp_path)

    _assert_notes_declaring_files_match(fixture_root)
    _assert_architect_carveout_consistent(fixture_root)

    architect_path = fixture_root / AGENTS_DIR_REL / "architect.md"
    text = architect_path.read_text(encoding="utf-8")
    assert not NOTES_HEADING_LINE_RE.search(text), "fixture setup assumption violated"
    mutated_text = text + f"\n{NOTES_HEADING}\n\nSome notes.\n"
    architect_path.write_text(mutated_text, encoding="utf-8")

    with pytest.raises(AssertionError) as excinfo_notes:
        _assert_notes_declaring_files_match(fixture_root)
    assert "architect.md" in str(excinfo_notes.value)

    with pytest.raises(AssertionError) as excinfo_carveout:
        _assert_architect_carveout_consistent(fixture_root)
    assert "architect.md" in str(excinfo_carveout.value)


def test_mutation_removing_one_qa_engineer_schema_field_fails(tmp_path: Path) -> None:
    fixture_root = _build_fixture_root(tmp_path)

    _assert_qa_engineer_fields_present(fixture_root)

    qa_path = fixture_root / AGENTS_DIR_REL / "qa-engineer.md"
    text = qa_path.read_text(encoding="utf-8")
    assert "provenance_check_note:" in text, "fixture setup assumption violated"
    mutated_text = text.replace(
        "provenance_check_note: <cap: 200 chars, only when found-and-disregarded>\n",
        "",
        1,
    )
    assert mutated_text != text, "mutation substitution did not apply"
    qa_path.write_text(mutated_text, encoding="utf-8")

    with pytest.raises(AssertionError) as excinfo:
        _assert_qa_engineer_fields_present(fixture_root)
    assert "provenance_check_note" in str(excinfo.value)


def test_mutation_rewriting_only_architect_directive_line_fails(tmp_path: Path) -> None:
    """Guards the round-6 containment-vs-anchoring fix: architect.md's
    round-5 'Spawn-brief neutrality' sentence quotes the exact-structure
    phrase inline as prose, at a different location from the real template
    directive line the phrase actually names. Rewriting only the real
    directive line (leaving the inline prose quotation untouched) must
    still redden the assertion - a plain `phrase in text` containment check
    would pass here because the inline quotation alone still satisfies it.
    """
    fixture_root = _build_fixture_root(tmp_path)

    _assert_architect_carveout_consistent(fixture_root)

    architect_path = fixture_root / AGENTS_DIR_REL / "architect.md"
    text = architect_path.read_text(encoding="utf-8")
    directive_line = "Use this exact structure. Do not rename or reorder sections.\n"
    assert directive_line in text, "fixture setup assumption violated"
    # Sanity-check the fixture actually carries the phrase twice - once as
    # the real directive line, once quoted inline as prose - before
    # asserting anything about rewriting only one of the two occurrences.
    phrase = "Use this exact structure. Do not rename or reorder sections"
    assert text.count(phrase) == 2, (
        "fixture setup assumption violated: expected the exact-structure "
        "phrase to appear exactly twice in architect.md (the real "
        "directive line plus the round-5 inline prose quotation of it), "
        f"found {text.count(phrase)}"
    )
    mutated_text = text.replace(
        directive_line, "Follow whatever structure seems best.\n", 1
    )
    assert mutated_text != text, "mutation substitution did not apply"
    # The inline prose quotation at the "Spawn-brief neutrality" sentence
    # must survive untouched - that is the whole point of this mutation.
    assert f'"{phrase}"' in mutated_text, (
        "mutation setup error: the inline prose quotation of the phrase "
        "was unexpectedly removed by the directive-line replacement"
    )
    architect_path.write_text(mutated_text, encoding="utf-8")

    with pytest.raises(AssertionError) as excinfo:
        _assert_architect_carveout_consistent(fixture_root)
    assert "exact-structure phrase" in str(excinfo.value)
