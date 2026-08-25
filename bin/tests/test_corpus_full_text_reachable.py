#!/usr/bin/env python3
"""
Tests for DS-204 unit B: each of the 4 flipped adapters (.claude, .kimi,
.gemini, .copilot/.github) ships a genuinely reachable full-corpus sibling
next to its minimal-corpus SKILL.md embed.

Covers, per adapter:
  - the sibling full-text file exists and is non-empty
  - the sibling contains ZERO "Deferred at this corpus" occurrences (it is
    the full corpus, nothing should be deferred within it)
  - the sibling's basename matches every `--full-text-name` value baked
    into that adapter's build.sh (the value the built SKILL.md's pointer
    blocks actually name)
  - all 12 section files' (+ the 2 rules files, where the sibling carries
    them) first top-level headings are present in the sibling

Run with: python3 bin/tests/test_corpus_full_text_reachable.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent.parent
_SECTIONS_DIR = _REPO_DIR / "content" / "sections"
_RULES_DIR = _REPO_DIR / "content" / "rules"

_ADAPTERS = [
    {
        "name": "claude",
        "build_sh": _REPO_DIR / ".claude" / "build.sh",
        "skill_md": _REPO_DIR / ".claude" / "skills" / "dinostack" / "SKILL.md",
        "full_sibling": _REPO_DIR / ".claude" / "skills" / "dinostack" / "METHODOLOGY.md",
        "full_sibling_basename": "METHODOLOGY.md",
        "sibling_carries_rules": False,
    },
    {
        "name": "kimi",
        "build_sh": _REPO_DIR / ".kimi" / "build.sh",
        "skill_md": _REPO_DIR / ".kimi" / "skills" / "dinostack" / "SKILL.md",
        "full_sibling": _REPO_DIR / ".kimi" / "skills" / "dinostack" / "METHODOLOGY.md",
        "full_sibling_basename": "METHODOLOGY.md",
        "sibling_carries_rules": False,
    },
    {
        "name": "gemini",
        "build_sh": _REPO_DIR / ".gemini" / "build.sh",
        "skill_md": _REPO_DIR / ".gemini" / "skills" / "dinostack" / "SKILL.md",
        "full_sibling": _REPO_DIR / ".gemini" / "skills" / "dinostack" / "SKILL.full.md",
        "full_sibling_basename": "SKILL.full.md",
        "sibling_carries_rules": True,
    },
    {
        "name": "copilot",
        "build_sh": _REPO_DIR / ".copilot" / "build.sh",
        "skill_md": _REPO_DIR / ".github" / "skills" / "dinostack" / "SKILL.md",
        "full_sibling": _REPO_DIR / ".github" / "skills" / "dinostack" / "METHODOLOGY.full.md",
        "full_sibling_basename": "METHODOLOGY.full.md",
        "sibling_carries_rules": False,
    },
]

_FULL_TEXT_NAME_FLAG_RE = re.compile(r"--full-text-name\s+([A-Za-z0-9_.]+)")
# .gemini/build.sh routes --full-text-name through a shell function
# (_build_gemini_skill_body <corpus> <full_text_name> <dst>) rather than a
# literal CLI flag at each call site - extract the literal second positional
# argument from each call instead.
_GEMINI_CALL_SITE_RE = re.compile(r"_build_gemini_skill_body\s+\S+\s+(\S+)\s+")


def _first_top_level_heading(text: str) -> str:
    lines = text.splitlines()
    idx = 0
    if lines and lines[0].strip().startswith("<!-- corpora:"):
        idx = 1
    for line in lines[idx:]:
        if line.startswith("## ") or line.startswith("# "):
            return line
    raise AssertionError("no top-level heading found")


class FullTextReachableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Rebuild all 4 flipped adapters once so the assertions below run
        # against fresh output, not a possibly-stale prior build.
        for adapter in _ADAPTERS:
            subprocess.run(["bash", str(adapter["build_sh"])], check=True, cwd=str(_REPO_DIR))


def _make_exists_nonempty_test(adapter):
    def test(self):
        sibling = adapter["full_sibling"]
        self.assertTrue(sibling.is_file(), f"{adapter['name']}: missing sibling {sibling}")
        self.assertGreater(sibling.stat().st_size, 0, f"{adapter['name']}: empty sibling {sibling}")

    return test


def _make_zero_deferred_test(adapter):
    def test(self):
        text = adapter["full_sibling"].read_text(encoding="utf-8")
        self.assertEqual(
            text.count("Deferred at this corpus"),
            0,
            f"{adapter['name']}: full-corpus sibling must never defer anything",
        )

    return test


def _make_basename_match_test(adapter):
    def test(self):
        build_text = adapter["build_sh"].read_text(encoding="utf-8")
        if adapter["name"] == "gemini":
            values = set(_GEMINI_CALL_SITE_RE.findall(build_text))
        else:
            values = set(_FULL_TEXT_NAME_FLAG_RE.findall(build_text))
        self.assertTrue(values, f"{adapter['name']}: no --full-text-name literal found in build.sh")
        for value in values:
            self.assertEqual(
                value,
                adapter["full_sibling_basename"],
                f"{adapter['name']}: --full-text-name value {value!r} does not match "
                f"the sibling's basename {adapter['full_sibling_basename']!r}",
            )

    return test


def _make_headings_present_test(adapter):
    def test(self):
        text = adapter["full_sibling"].read_text(encoding="utf-8")
        for section_file in sorted(_SECTIONS_DIR.glob("[0-9][0-9]-*.md")):
            heading = _first_top_level_heading(section_file.read_text(encoding="utf-8"))
            self.assertIn(
                heading,
                text,
                f"{adapter['name']}: {section_file.name}'s heading {heading!r} missing from full sibling",
            )
        if adapter["sibling_carries_rules"]:
            for rules_file in ("code-standards.md", "conventions.md"):
                heading = _first_top_level_heading((_RULES_DIR / rules_file).read_text(encoding="utf-8"))
                self.assertIn(
                    heading,
                    text,
                    f"{adapter['name']}: {rules_file}'s heading {heading!r} missing from full sibling",
                )

    return test


for _adapter in _ADAPTERS:
    _n = _adapter["name"]
    setattr(FullTextReachableTests, f"test_{_n}_sibling_exists_nonempty", _make_exists_nonempty_test(_adapter))
    setattr(FullTextReachableTests, f"test_{_n}_sibling_zero_deferred", _make_zero_deferred_test(_adapter))
    setattr(FullTextReachableTests, f"test_{_n}_sibling_basename_matches_pointer", _make_basename_match_test(_adapter))
    setattr(FullTextReachableTests, f"test_{_n}_sibling_headings_present", _make_headings_present_test(_adapter))


if __name__ == "__main__":
    unittest.main()
