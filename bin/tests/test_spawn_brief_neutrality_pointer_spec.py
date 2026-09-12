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
anywhere else in the suite.

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


def test_live_repo_pointer_is_byte_identical_across_four_files() -> None:
    pointers = _read_pointers(REPO_ROOT)
    values = list(pointers.values())
    first = values[0]
    for rel_path, value in pointers.items():
        assert value == first, (
            f"{rel_path} carries a Spawn-brief neutrality pointer that "
            "differs from content/agents/engineer.md's copy - the four "
            "pointer sentences must be byte-identical"
        )


def test_live_repo_pointer_cites_subagent_protocol_section_11() -> None:
    pointers = _read_pointers(REPO_ROOT)
    for rel_path, value in pointers.items():
        assert "content/references/subagent-protocol.md" in value, (
            f"{rel_path}'s pointer no longer cites subagent-protocol.md"
        )
        assert "11" in value, (
            f"{rel_path}'s pointer no longer cites Section 11"
        )


def test_mutation_diverging_one_copy_fails(tmp_path: Path) -> None:
    """Copy all four agent files into a pytest tmp_path root (never the
    repo itself), mutate ONE copy's pointer sentence with a trivial
    wording change, and assert the byte-identity check catches it."""
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
    values_before = list(pointers_before.values())
    assert all(v == values_before[0] for v in values_before), (
        "fixture setup is already non-identical before mutation"
    )

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
    values_after = list(pointers_after.values())
    with pytest.raises(AssertionError):
        first = values_after[0]
        for rel_path, value in pointers_after.items():
            assert value == first, (
                f"{rel_path} carries a Spawn-brief neutrality pointer that "
                "differs from content/agents/engineer.md's copy - the four "
                "pointer sentences must be byte-identical"
            )
