#!/usr/bin/env python3
"""
Cross-site consistency pins for docs-currency drift classes that PR #719's
manual sweep found but did not mechanically close. Each assertion derives the
expected value from live repo state (a glob or a grep of hooks/), never a
hardcoded literal, so a future change that updates one site and forgets its
sibling now fails here instead of silently drifting.

Drift classes covered:
  - docs/components.md "**Agents** (<N>)"          vs len(content/agents/*.md)
  - docs/components.md "**Commands** (<N>)"        vs len(content/commands/ds-*.md)
  - docs/index.html "Guard kill-switches" card     vs the AE_*_DISABLE env vars
                                                    referenced in hooks/ (the
                                                    card omitted 3 of the 8
                                                    hooks-defined kill-switches)
  - docs/configuration-reference.md section 4      vs the same hooks-derived
    "Environment kill-switches" table              AE_*_DISABLE set
  - README.md deck inventory                       vs docs/slides/*-slides.md
                                                    (the list drifted to ~9 of
                                                    18 decks before #719)
  - docs/index.html "N named agents" claims        vs len(content/agents/*.md)

docs/index.html's Referenced Protocol Documents grid is intentionally NOT
covered here: it is a curated subset, not a full enumeration (see
test_reference_doc_count_sync.py's docstring). The kill-switch card and the
"named agents" claims ARE full assertions of derivable facts, so they are
pinned exactly.

docs/overview/requirements.md is gitignored/absent and is never asserted
against; docs/slides/*.md decks are enumerated from the `*-slides.md` glob
(docs/slides/AGENTS.md is a directory guide, not a deck).

Run with: python3 -m pytest bin/tests/test_docs_currency_sync.py -q
CI wiring: .github/workflows/bin-tests.yml's python-bin-tests job runs
`python3 -m pytest bin/tests/ -q` - full-directory glob discovery, no
per-file wiring required for a new test_*.py file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "content" / "agents"
COMMANDS_DIR = REPO_ROOT / "content" / "commands"
HOOKS_DIR = REPO_ROOT / "hooks"
SLIDES_DIR = REPO_ROOT / "docs" / "slides"
COMPONENTS_PATH = REPO_ROOT / "docs" / "components.md"
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
CONFIG_REF_PATH = REPO_ROOT / "docs" / "configuration-reference.md"
README_PATH = REPO_ROOT / "README.md"

# Every AE_*_DISABLE token is a guard kill-switch env var. Tokens are derived
# from hooks/ source, never a hand-typed literal, so adding a new kill-switch
# to a hook fails the pinning tests until every documented enumeration catches
# up - the exact drift class PR #719 fixed by hand.
_HOOK_KILL_SWITCH_RE = re.compile(r"\b(AE_[A-Z_]+_DISABLE)\b")


@pytest.fixture(scope="module")
def hooks_kill_switches() -> set[str]:
    """Live set of guard kill-switch env vars referenced in hooks/."""
    hook_paths = sorted(HOOKS_DIR.glob("*.py")) + sorted(HOOKS_DIR.glob("*.sh"))
    return {
        name
        for path in hook_paths
        for name in _HOOK_KILL_SWITCH_RE.findall(path.read_text(encoding="utf-8"))
    }


@pytest.fixture(scope="module")
def agent_count() -> int:
    return len(list(AGENTS_DIR.glob("*.md")))


@pytest.fixture(scope="module")
def deck_stems() -> list[str]:
    """Live set of slide-deck basenames (without .md). The `*-slides.md` glob
    excludes docs/slides/AGENTS.md, which is a directory guide, not a deck."""
    return sorted(p.stem for p in SLIDES_DIR.glob("*-slides.md"))


def test_hooks_kill_switch_set_is_plausible(hooks_kill_switches):
    # Sanity floor: the derived set is the ground truth this spec enforces.
    # A collapse below this floor means hooks/ itself lost its kill-switches.
    assert len(hooks_kill_switches) >= 5, (
        f"derived hooks kill-switch set {sorted(hooks_kill_switches)} is "
        "implausibly small"
    )


def test_components_md_agent_count_matches(agent_count):
    text = COMPONENTS_PATH.read_text(encoding="utf-8")
    match = re.search(r"\*\*Agents\*\* \((\d+)\)", text)
    assert match, (
        "docs/components.md must state the agent count as '**Agents** (<N>)'"
    )
    stated = int(match.group(1))
    assert stated == agent_count, (
        f"docs/components.md states {stated} agents, expected {agent_count} "
        "(one per content/agents/*.md file)"
    )


def test_components_md_command_count_matches():
    live = len(list(COMMANDS_DIR.glob("ds-*.md")))
    text = COMPONENTS_PATH.read_text(encoding="utf-8")
    match = re.search(r"\*\*Commands\*\* \((\d+)\)", text)
    assert match, (
        "docs/components.md must state the command count as "
        "'**Commands** (<N>)'"
    )
    stated = int(match.group(1))
    assert stated == live, (
        f"docs/components.md states {stated} commands, expected {live} "
        "(one per content/commands/ds-*.md file)"
    )


def _kill_switch_region(text: str, start_marker: str, end_marker: str) -> str:
    """Substring of `text` that documents a kill-switch enumeration."""
    start = text.index(start_marker)
    nxt = text.find(end_marker, start + len(start_marker))
    if nxt == -1:
        nxt = len(text)
    return text[start:nxt]


def test_index_html_kill_switch_card_matches(hooks_kill_switches):
    text = INDEX_PATH.read_text(encoding="utf-8")
    card = _kill_switch_region(text, "Guard kill-switches", "<h4>")
    card_vars = set(_HOOK_KILL_SWITCH_RE.findall(card))
    assert card_vars == hooks_kill_switches, (
        "docs/index.html 'Guard kill-switches' card disagrees with the "
        "AE_*_DISABLE kill-switches referenced in hooks/.\n"
        f"  missing from card: {sorted(hooks_kill_switches - card_vars)}\n"
        f"  extra in card: {sorted(card_vars - hooks_kill_switches)}"
    )


def test_config_reference_env_kill_switch_table_matches(hooks_kill_switches):
    text = CONFIG_REF_PATH.read_text(encoding="utf-8")
    section = _kill_switch_region(text, "## 4. Environment kill-switches", "\n## ")
    section_vars = set(_HOOK_KILL_SWITCH_RE.findall(section))
    assert section_vars == hooks_kill_switches, (
        "docs/configuration-reference.md 'Environment kill-switches' table "
        "disagrees with the AE_*_DISABLE kill-switches referenced in hooks/.\n"
        f"  missing from table: {sorted(hooks_kill_switches - section_vars)}\n"
        f"  extra in table: {sorted(section_vars - hooks_kill_switches)}"
    )


def test_readme_deck_inventory_matches(deck_stems):
    text = README_PATH.read_text(encoding="utf-8")
    listed = sorted(set(re.findall(r"docs/slides/([a-z0-9-]+)\.html", text)))
    assert listed, "README.md must list slide decks as docs/slides/<deck>.html"
    missing = [stem for stem in deck_stems if stem not in listed]
    assert not missing, (
        f"README.md deck inventory is missing decks: {missing}"
    )
    extra = [stem for stem in listed if stem not in deck_stems]
    assert not extra, (
        f"README.md deck inventory names non-existent decks: {extra}"
    )


def test_index_html_named_agents_claims_match(agent_count):
    text = INDEX_PATH.read_text(encoding="utf-8")
    claims = [int(m) for m in re.findall(r"(\d+) named agents", text)]
    assert claims, (
        "docs/index.html must state the agent-team size as '<N> named agents'"
    )
    assert all(c == agent_count for c in claims), (
        f"docs/index.html states {claims} named agents, expected {agent_count} "
        "(one per content/agents/*.md file)"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
