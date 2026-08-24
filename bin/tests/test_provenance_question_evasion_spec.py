#!/usr/bin/env python3
"""
Regression guard for DS-195: the "convert it to a question" remedy for an
untagged directive-shaped spawn-brief claim has been deleted from
content/sections/04-risk-classification.md, and the worked example in
content/references/subagent-protocol.md that prescribed the same remedy
("...as a question, not as a directive...") has been replaced with an
attribution-based instruction.

Rephrasing an untagged conductor belief as a question does not make it
verified input - it launders the belief into the spawn brief unchanged.
This test pins both deletions and a positive pin on the surrounding text
that must survive untouched.

Run with:
    python3 -m pytest bin/tests/test_provenance_question_evasion_spec.py -q
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RISK_CLASSIFICATION_REL = Path("content/sections/04-risk-classification.md")
SUBAGENT_PROTOCOL_REL = Path("content/references/subagent-protocol.md")

# Strings that must be ABSENT post-fix (the deleted/replaced remedy).
REMOVED_RISK_PHRASE = "convert it to a question"
REMOVED_SUBAGENT_PHRASE = "to the engineer as a question"

# Strings that must be PRESENT post-fix (positive pins).
RETAINED_RISK_SENTENCE = (
    "An untagged directive-shaped claim in a spawn brief is a protocol violation."
)
RETAINED_RISK_NEIGHBOR_1 = "A verified-by-read tag never downgrades risk classification"
RETAINED_RISK_NEIGHBOR_2 = "**Exception:** a Skeptic/reviewer brief bars"
RETAINED_SUBAGENT_PHRASE = "attributed to the Skeptic that raised it"


def _assert_files_and_content(root: Path) -> None:
    """Shared assertion body, called against both the live repo root and a
    mutation root, so both exercise the identical code path."""
    risk_path = root / RISK_CLASSIFICATION_REL
    subagent_path = root / SUBAGENT_PROTOCOL_REL

    # Existence + non-empty checks BEFORE any string assertion. An absence
    # assertion against a missing/misspelled path passes vacuously.
    assert risk_path.is_file(), f"missing file: {risk_path}"
    assert risk_path.stat().st_size > 0, f"empty file: {risk_path}"
    assert subagent_path.is_file(), f"missing file: {subagent_path}"
    assert subagent_path.stat().st_size > 0, f"empty file: {subagent_path}"

    risk_text = risk_path.read_text(encoding="utf-8")
    subagent_text = subagent_path.read_text(encoding="utf-8")

    # The deleted remedy must not exist.
    assert REMOVED_RISK_PHRASE not in risk_text, (
        f"{risk_path} still contains the deleted remedy phrase "
        f"'{REMOVED_RISK_PHRASE}'"
    )
    assert REMOVED_SUBAGENT_PHRASE not in subagent_text, (
        f"{subagent_path} still contains the deleted remedy phrase "
        f"'{REMOVED_SUBAGENT_PHRASE}'"
    )

    # Positive pins: the retained sentence/neighbours must survive, so a
    # silent over-deletion (e.g. deleting the whole sentence rather than
    # just the trailing clause) fails this test.
    assert RETAINED_RISK_SENTENCE in risk_text, (
        f"{risk_path} is missing the retained sentence "
        f"'{RETAINED_RISK_SENTENCE}'"
    )
    assert RETAINED_RISK_NEIGHBOR_1 in risk_text, (
        f"{risk_path} is missing the retained neighbour sentence "
        f"'{RETAINED_RISK_NEIGHBOR_1}'"
    )
    assert RETAINED_RISK_NEIGHBOR_2 in risk_text, (
        f"{risk_path} is missing the retained Exception clause "
        f"'{RETAINED_RISK_NEIGHBOR_2}'"
    )
    assert RETAINED_SUBAGENT_PHRASE in subagent_text, (
        f"{subagent_path} is missing the replacement phrase "
        f"'{RETAINED_SUBAGENT_PHRASE}'"
    )


def test_live_repo_has_no_question_conversion_remedy() -> None:
    _assert_files_and_content(REPO_ROOT)


def _copy_targets_into(mutated_root: Path) -> tuple[Path, Path]:
    risk_dst = mutated_root / RISK_CLASSIFICATION_REL
    subagent_dst = mutated_root / SUBAGENT_PROTOCOL_REL
    risk_dst.parent.mkdir(parents=True, exist_ok=True)
    subagent_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / RISK_CLASSIFICATION_REL, risk_dst)
    shutil.copyfile(REPO_ROOT / SUBAGENT_PROTOCOL_REL, subagent_dst)
    return risk_dst, subagent_dst


def test_mutation_reintroducing_question_conversion_fails(tmp_path: Path) -> None:
    """Copy the two target files into a pytest tmp_path root (never the
    repo itself), substitute the post-edit text back to the pre-edit text,
    and assert the shared helper raises. This exercises the
    REMOVED_*_PHRASE and RETAINED_RISK_SENTENCE/RETAINED_SUBAGENT_PHRASE
    assertions - reinstating the old clause makes the retained-sentence
    substring no longer match (it now runs on into the reinstated clause
    instead of ending in a period), so both the "absent" and "present"
    checks flip to failing."""
    mutated_root = tmp_path / "mutated-repo-question-conversion"
    risk_dst, subagent_dst = _copy_targets_into(mutated_root)

    risk_text = risk_dst.read_text(encoding="utf-8")
    mutated_risk_text = risk_text.replace(
        RETAINED_RISK_SENTENCE,
        "An untagged directive-shaped claim in a spawn brief is a protocol "
        'violation - convert it to a question ("investigate whether...") '
        "rather than asserting it.",
    )
    assert mutated_risk_text != risk_text, "mutation substitution did not apply"
    risk_dst.write_text(mutated_risk_text, encoding="utf-8")

    subagent_text = subagent_dst.read_text(encoding="utf-8")
    mutated_subagent_text = subagent_text.replace(
        RETAINED_SUBAGENT_PHRASE
        + ", and never with a rationale the conductor did not itself verify.",
        "as a question, not as a directive with an invented cause.",
    )
    assert mutated_subagent_text != subagent_text, (
        "mutation substitution did not apply"
    )
    subagent_dst.write_text(mutated_subagent_text, encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_files_and_content(mutated_root)


def test_mutation_over_deletion_of_neighbors_fails(tmp_path: Path) -> None:
    """A fix that deletes the whole sentence (or its neighbours) instead of
    just the trailing question-conversion clause must also be caught.
    Exercises RETAINED_RISK_NEIGHBOR_1 and RETAINED_RISK_NEIGHBOR_2, which
    the question-conversion mutation above does not touch."""
    mutated_root = tmp_path / "mutated-repo-over-deletion"
    risk_dst, _subagent_dst = _copy_targets_into(mutated_root)

    risk_text = risk_dst.read_text(encoding="utf-8")
    mutated_risk_text = risk_text.replace(RETAINED_RISK_NEIGHBOR_1, "").replace(
        RETAINED_RISK_NEIGHBOR_2, ""
    )
    assert mutated_risk_text != risk_text, "mutation substitution did not apply"
    risk_dst.write_text(mutated_risk_text, encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_files_and_content(mutated_root)
