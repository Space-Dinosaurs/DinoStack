#!/usr/bin/env python3
"""
Regression guard for the `dinostack` output style's rule-set drift (DS-171
round-3 Skeptic Major 3).

DS-171 moved four turn-shape rules (status-only, volume, answer relevance,
self-narrating candor) out of `hooks/enforce-turn-shape.py` and into the
always-injected `dinostack` Claude Code output style
(`content/output-styles/dinostack.md`). That rule set is then RESTATED, by
name, at four separate sites with no mechanical check tying them together:
`docs/index.html`, `README.md`, `hooks/enforce-turn-shape.py`'s module
docstring, and `content/references/conductor-turn-format.md`'s DS-171 note.
This is exactly the shape that caused DS-171 round 2's Skeptic Critical (a
stale cross-file assertion nothing pinned) - this spec closes the same gap
for the rule-SET NAME, not just the retired-mechanism prose already fixed in
round 3.

The derived source of truth is `content/output-styles/dinostack.md` itself:
its YAML frontmatter `description:` field states the rule set as a
parenthesized, comma-separated list, and its body states the same count as
numbered rule headers (`**1. ...**` through `**N. ...**`). Both are asserted
to agree with each other, and each named topic is asserted present (modulo
hyphen/space normalization) at each of the four sites above.

Run with: python3 -m pytest bin/tests/test_output_style_rule_set_sync.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STYLE_PATH = REPO_ROOT / "content" / "output-styles" / "dinostack.md"
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
README_PATH = REPO_ROOT / "README.md"
HOOK_PATH = REPO_ROOT / "hooks" / "enforce-turn-shape.py"
CTF_PATH = REPO_ROOT / "content" / "references" / "conductor-turn-format.md"

# How many leading lines of the hook file count as "the module docstring"
# for this guard's purposes - generous enough to cover the whole Purpose
# section without pulling in unrelated later code.
HOOK_DOCSTRING_LINE_BUDGET = 60


def _normalize(text: str) -> str:
    """Lowercase, and fold hyphens/underscores to spaces so "status-only",
    "status_only", and "status only" all compare equal."""
    text = text.lower()
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


@pytest.fixture(scope="module")
def style_text() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rule_set_topics(style_text) -> list[str]:
    """Derived from the style's own YAML frontmatter description, e.g.
    'DinoStack conductor turn-shape discipline (status-only, volume,
    answer relevance, self-narrating candor)' -> the 4 parenthesized
    topics. Never hardcoded - this is the thing every other site must
    agree with."""
    match = re.search(r"^description:.*\(([^)]*)\)", style_text, re.MULTILINE)
    assert match, (
        f"{STYLE_PATH} frontmatter 'description:' must state the rule set "
        "as a parenthesized, comma-separated list"
    )
    topics = [t.strip() for t in match.group(1).split(",")]
    assert all(topics), f"{STYLE_PATH} frontmatter rule-set list has an empty entry: {topics}"
    return topics


@pytest.fixture(scope="module")
def rule_header_count(style_text) -> int:
    """Derived from the style body's own numbered rule headers
    ('**1. ...**' etc.) - the second independent count this spec cross-
    checks against the frontmatter topic count."""
    return len(re.findall(r"^\*\*\d+\.\s", style_text, re.MULTILINE))


def test_frontmatter_topic_count_matches_body_rule_count(rule_set_topics, rule_header_count):
    assert rule_header_count == len(rule_set_topics), (
        f"{STYLE_PATH} frontmatter names {len(rule_set_topics)} topics "
        f"{rule_set_topics} but the body has {rule_header_count} numbered "
        "rule headers - these must stay in sync"
    )


def test_rule_set_is_plausible(rule_set_topics):
    # Sanity floor: catches an accidentally-emptied description field.
    assert len(rule_set_topics) >= 2, (
        f"{STYLE_PATH} frontmatter rule-set list is implausibly short: {rule_set_topics}"
    )


def _assert_topics_present(site_path: Path, site_text: str, topics: list[str]) -> None:
    normalized_site = _normalize(site_text)
    missing = [t for t in topics if _normalize(t) not in normalized_site]
    assert not missing, (
        f"{site_path} is missing rule-set topic(s) {missing} from "
        f"{STYLE_PATH}'s frontmatter rule set {topics} - update it to match "
        "or correct the drift"
    )


def test_index_html_names_full_rule_set(rule_set_topics):
    text = INDEX_PATH.read_text(encoding="utf-8")
    marker = "Claude Code turn-shape output style"
    assert marker in text, (
        f"{INDEX_PATH} must contain the '{marker}' card describing the "
        "dinostack output style"
    )
    card_text = text[text.index(marker):]
    _assert_topics_present(INDEX_PATH, card_text, rule_set_topics)


def test_readme_names_full_rule_set(rule_set_topics):
    text = README_PATH.read_text(encoding="utf-8")
    marker = "turn_shape_guard_enabled"
    assert marker in text, (
        f"{README_PATH} must contain the '{marker}' config entry describing "
        "what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one bullet, not the whole rest of the file.
    next_bullet = entry_text.find("\n- `", 1)
    if next_bullet != -1:
        entry_text = entry_text[:next_bullet]
    _assert_topics_present(README_PATH, entry_text, rule_set_topics)


def test_hook_docstring_names_full_rule_set(rule_set_topics):
    lines = HOOK_PATH.read_text(encoding="utf-8").splitlines()
    docstring_text = "\n".join(lines[:HOOK_DOCSTRING_LINE_BUDGET])
    _assert_topics_present(HOOK_PATH, docstring_text, rule_set_topics)


def test_conductor_turn_format_names_full_rule_set(rule_set_topics):
    text = CTF_PATH.read_text(encoding="utf-8")
    marker = "DS-171: bans 2 and 5"
    assert marker in text, (
        f"{CTF_PATH} must contain the DS-171 note describing what moved to "
        "the dinostack output style"
    )
    note_text = text[text.index(marker):]
    # Scope to this paragraph plus the immediately following one (the
    # self-narrating-candor addendum), not the whole rest of the file.
    next_para = note_text.find("\n\n", 1)
    if next_para != -1:
        note_text = note_text[:next_para]
    _assert_topics_present(CTF_PATH, note_text, rule_set_topics)
