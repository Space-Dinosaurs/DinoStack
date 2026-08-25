#!/usr/bin/env python3
"""
Tests for DS-204 unit B: every section's and rules-file's first top-level
heading survives at the minimal corpus.

Covers:
  - each of the 12 content/sections/[0-9][0-9]-*.md files' first top-level
    heading is present in `bash scripts/build-methodology.sh --corpus
    minimal` output (the heading itself must never be wrapped in a
    corpus:begin block that could exclude it)
  - each of the 2 content/rules/*.md files (code-standards.md,
    conventions.md) - which are embedded verbatim by each adapter build.sh,
    never corpus-filtered - has its first top-level heading present in the
    built .claude/skills/dinostack/SKILL.md (the minimal-corpus embed, after
    DS-204 unit B flips it)

A redden-able mutation exists for each of the 14: temporarily removing (or
renaming) the heading line in its source file drops the assertion for that
file specifically, without affecting the other 13.

DS-204 round-1 Skeptic finding (tests-mutate-live-repo, Major): this suite
must never invoke an adapter build.sh - doing so regenerates tracked
artifacts in the live checkout (and can prune stale files), silently
repairing adapter drift and defeating a later `git diff --exit-code`
adapter-drift check. `RulesHeadingsInBuiltSkillTests` therefore READS the
already-committed `.claude/skills/dinostack/SKILL.md` as-is and refuses
(asserts, naming the exact rebuild command) if it is missing, rather than
building it. `SectionHeadingsAtMinimalTests` was already safe - it invokes
`scripts/build-methodology.sh --corpus minimal` with no `--output`, which
writes only to stdout and touches no file on disk - and is unchanged.

Run with: python3 bin/tests/test_corpus_headings_retained.py
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent.parent
_SECTIONS_DIR = _REPO_DIR / "content" / "sections"
_RULES_DIR = _REPO_DIR / "content" / "rules"
_BUILD_METHODOLOGY = _REPO_DIR / "scripts" / "build-methodology.sh"
_CLAUDE_SKILL_MD = _REPO_DIR / ".claude" / "skills" / "dinostack" / "SKILL.md"


def _first_top_level_heading(text: str) -> str:
    """Returns the first line starting with '# ' or '## ', skipping any
    leading corpora: marker or HTML-comment manifest block."""
    lines = text.splitlines()
    idx = 0
    if lines and lines[0].strip().startswith("<!-- corpora:"):
        idx = 1
    for line in lines[idx:]:
        if line.startswith("## ") or line.startswith("# "):
            return line
    raise AssertionError("no top-level heading found")


class SectionHeadingsAtMinimalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proc = subprocess.run(
            ["bash", str(_BUILD_METHODOLOGY), "--corpus", "minimal"],
            capture_output=True,
            text=True,
            check=True,
        )
        cls.minimal_output = proc.stdout

    def test_all_twelve_section_files_present(self):
        section_files = sorted(_SECTIONS_DIR.glob("[0-9][0-9]-*.md"))
        self.assertEqual(len(section_files), 12, f"expected 12 section files, found {len(section_files)}")


def _make_heading_test(section_file: Path):
    def test(self):
        text = section_file.read_text(encoding="utf-8")
        heading = _first_top_level_heading(text)
        self.assertIn(
            heading,
            self.minimal_output,
            f"{section_file.name}'s first top-level heading {heading!r} is missing from "
            "the minimal-corpus build - it must never be wrapped in a corpus:begin block",
        )

    return test


for _section_file in sorted(_SECTIONS_DIR.glob("[0-9][0-9]-*.md")):
    _test_name = f"test_heading_retained_{_section_file.stem.replace('-', '_')}"
    setattr(SectionHeadingsAtMinimalTests, _test_name, _make_heading_test(_section_file))


class RulesHeadingsInBuiltSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read the already-committed artifact as-is; never build it here
        # (see module docstring - tests-mutate-live-repo, Major).
        assert _CLAUDE_SKILL_MD.is_file(), (
            f"{_CLAUDE_SKILL_MD} does not exist - run `bash .claude/build.sh` "
            "before this test"
        )
        cls.skill_md = _CLAUDE_SKILL_MD.read_text(encoding="utf-8")

    def test_code_standards_heading_present(self):
        text = (_RULES_DIR / "code-standards.md").read_text(encoding="utf-8")
        heading = _first_top_level_heading(text)
        self.assertIn(heading, self.skill_md)

    def test_conventions_heading_present(self):
        text = (_RULES_DIR / "conventions.md").read_text(encoding="utf-8")
        heading = _first_top_level_heading(text)
        self.assertIn(heading, self.skill_md)

    def test_both_rules_files_are_embedded_sections(self):
        self.assertIn("### rules/code-standards.md", self.skill_md)
        self.assertIn("### rules/conventions.md", self.skill_md)


if __name__ == "__main__":
    unittest.main()
