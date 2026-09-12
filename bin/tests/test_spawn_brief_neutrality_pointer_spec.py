#!/usr/bin/env python3
"""
Regression guard for the spawn-brief-neutrality recipient-scope generalization
(content/sections/04-risk-classification.md line 9, content/references/
subagent-protocol.md Section 11 "Spawn-brief provenance"): four agent
contract files - engineer.md, investigator.md, architect.md, qa-engineer.md -
each carry a byte-identical "Spawn-brief neutrality" pointer sentence, since
Section 11's full rule cannot reach any of these four roles without a
per-file pointer (none of the four cited subagent-protocol.md's Section 11
before this change).

A one-canonical-site design (the full rule lives only in Section 11) is only
safe if the four pointers stay byte-identical - if one copy silently drifts
(a paraphrase, a dropped clause, a stale reference), the affected role's
neutrality self-check duty diverges from the other three with no signal
anywhere else in the suite. The pointer itself is deliberately generic
("using this file's own return-format mechanism") rather than mandating a
literal `Provenance check:` line for every role - qa-engineer.md's return is
a single fenced schema block (Shape 2) with no room for a freestanding prose
line, so it satisfies the same pointer via a `provenance_check`/
`provenance_check_note` schema field pair instead (see qa-engineer.md's
pointer-return section). That per-file divergence lives OUTSIDE the pointer
sentence this test extracts, which is why the pointer itself can still stay
byte-identical across all four files.

Round 2 fix: the mutation test now calls the SAME assertion helper the live
test uses (`_assert_pointers_identical`) rather than re-implementing the
byte-identity loop inline - a prior version's inline copy meant weakening or
deleting the live assertion would leave the mutation test green. The
Section-11 citation test also now requires the literal `§11` marker
immediately after the `subagent-protocol.md` citation, not merely the
digit pair "11" occurring anywhere in the pointer text.

Retirement condition: none while the four-file pointer design is in place.
If a future change consolidates the pointer into a single shared include
mechanism, this test's byte-identity assertion becomes structurally
unnecessary and can be retired then - not before.

Run with:
    python3 -m pytest bin/tests/test_spawn_brief_neutrality_pointer_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

AGENT_FILES = [
    Path("content/agents/engineer.md"),
    Path("content/agents/investigator.md"),
    Path("content/agents/architect.md"),
    Path("content/agents/qa-engineer.md"),
]

# Matches from the pointer's leading bold label through its closing
# sentence, non-greedy so it stops at the first "disregarded one." rather
# than running on into any later text that happens to repeat the phrase.
POINTER_PATTERN = re.compile(
    r"\*\*Spawn-brief neutrality\.\*\*.*?disregarded one\.",
    re.DOTALL,
)

# Requires the literal section-symbol citation directly after the file
# path, not merely the digit pair "11" occurring anywhere in the pointer
# (which would be satisfied by, e.g., an unrelated "within 11 words").
SECTION_11_CITATION_RE = re.compile(
    r"subagent-protocol\.md`\s*§11\b"
)


def _extract_pointer(text: str, path: Path) -> str:
    match = POINTER_PATTERN.search(text)
    assert match is not None, f"{path} is missing the Spawn-brief neutrality pointer sentence"
    return match.group(0)


def _read_pointers(root: Path) -> dict[Path, str]:
    pointers: dict[Path, str] = {}
    for rel_path in AGENT_FILES:
        full_path = root / rel_path
        assert full_path.is_file(), f"missing file: {full_path}"
        assert full_path.stat().st_size > 0, f"empty file: {full_path}"
        text = full_path.read_text(encoding="utf-8")
        pointers[rel_path] = _extract_pointer(text, full_path)
    return pointers


def _assert_pointers_identical(pointers: dict[Path, str]) -> None:
    values = list(pointers.values())
    first = values[0]
    for rel_path, value in pointers.items():
        assert value == first, (
            f"{rel_path} carries a Spawn-brief neutrality pointer that "
            "differs from content/agents/engineer.md's copy - the four "
            "pointer sentences must be byte-identical"
        )


def test_live_repo_pointer_is_byte_identical_across_four_files() -> None:
    pointers = _read_pointers(REPO_ROOT)
    _assert_pointers_identical(pointers)


def test_live_repo_pointer_cites_subagent_protocol_section_11() -> None:
    pointers = _read_pointers(REPO_ROOT)
    for rel_path, value in pointers.items():
        assert "content/references/subagent-protocol.md" in value, (
            f"{rel_path}'s pointer no longer cites subagent-protocol.md"
        )
        assert SECTION_11_CITATION_RE.search(value), (
            f"{rel_path}'s pointer no longer cites subagent-protocol.md "
            "§11 with the literal section-symbol form"
        )


def test_mutation_diverging_one_copy_fails(tmp_path: Path) -> None:
    """Copy all four agent files into a pytest tmp_path root (never the
    repo itself), mutate ONE copy's pointer sentence with a trivial
    wording change, and assert the SAME assertion helper the live test
    uses (`_assert_pointers_identical`) catches it - not a re-implemented
    copy of the byte-identity loop, which could pass even if the live
    assertion were weakened or deleted."""
    mutated_root = tmp_path / "mutated-repo-neutrality-pointer"
    for rel_path in AGENT_FILES:
        dst = mutated_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            (REPO_ROOT / rel_path).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    # Baseline: the freshly-copied fixture passes the identity check.
    pointers_before = _read_pointers(mutated_root)
    _assert_pointers_identical(pointers_before)

    engineer_path = mutated_root / AGENT_FILES[0]
    text = engineer_path.read_text(encoding="utf-8")
    mutated_text = text.replace(
        "treat any untagged conductor conclusion",
        "treat any conductor conclusion",
        1,
    )
    assert mutated_text != text, "mutation substitution did not apply"
    engineer_path.write_text(mutated_text, encoding="utf-8")

    pointers_after = _read_pointers(mutated_root)
    with pytest.raises(AssertionError):
        _assert_pointers_identical(pointers_after)
