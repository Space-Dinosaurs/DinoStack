#!/usr/bin/env python3
"""
Tests for DS-204 unit B: each of the FLIPPED adapters (.claude, .gemini)
ships a genuinely reachable full-corpus sibling next to its minimal-corpus
SKILL.md embed. .kimi and .copilot/.github were held back at runtime QA
(Kimi/Copilot INCONCLUSIVE - no drivable runtime on host) per the signed
plan's per-adapter hold-back clause and ship the FULL corpus unconditionally
- .kimi's METHODOLOGY.md sibling is asserted separately below (it ships
regardless of the flip, so it still deserves a presence/health check), and
.copilot carries no corpus machinery at all (reverted, no separate assertion
needed).

Covers, per FLIPPED adapter:
  - the sibling full-text file exists and is non-empty
  - the sibling contains ZERO "Deferred at this corpus" occurrences (it is
    the full corpus, nothing should be deferred within it)
  - the sibling's basename matches every `--full-text-name` value baked
    into that adapter's build.sh (the value the built SKILL.md's pointer
    blocks actually name)
  - all 12 section files' (+ the 2 rules files, where the sibling carries
    them) first top-level headings are present in the sibling

Covers, for .kimi (held back, not flipped):
  - METHODOLOGY.md exists, is non-empty, carries zero deferred markers, and
    carries every section heading (it is always the full corpus - .kimi's
    SKILL.md embed is ALSO the full corpus post-hold-back, so there is no
    separate minimal/full distinction to assert there).

All assertions read the already-committed adapter artifacts as-is; this
suite never invokes an adapter build.sh (DS-204 round-1 Skeptic finding
tests-mutate-live-repo, Major - doing so regenerates tracked artifacts in
the live checkout, silently repairing adapter drift and defeating a later
`git diff --exit-code` adapter-drift check). Any missing artifact is a
refusal naming the exact rebuild command, matching
bin/tests/test_command_picker_descriptions.py's convention.

Run with: python3 bin/tests/test_corpus_full_text_reachable.py
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent.parent
_SECTIONS_DIR = _REPO_DIR / "content" / "sections"
_RULES_DIR = _REPO_DIR / "content" / "rules"

# FLIPPED adapters only (claude, gemini) - kimi and copilot were held back
# at runtime QA (DS-204 hold-back round) and ship the full corpus
# unconditionally with no pointer-block/sibling machinery for copilot, and
# no minimal/full distinction on kimi's own SKILL.md embed.
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
        "name": "gemini",
        "build_sh": _REPO_DIR / ".gemini" / "build.sh",
        "skill_md": _REPO_DIR / ".gemini" / "skills" / "dinostack" / "SKILL.md",
        "full_sibling": _REPO_DIR / ".gemini" / "skills" / "dinostack" / "SKILL.full.md",
        "full_sibling_basename": "SKILL.full.md",
        "sibling_carries_rules": True,
    },
]

# Held-back adapter whose full-corpus sibling still ships unconditionally
# (kimi's SKILL.md embed reverted to full too, but METHODOLOGY.md remains a
# distinct sibling file worth a presence/health check).
_KIMI_METHODOLOGY_MD = _REPO_DIR / ".kimi" / "skills" / "dinostack" / "METHODOLOGY.md"
_KIMI_BUILD_SH = _REPO_DIR / ".kimi" / "build.sh"

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
    """Reads the already-committed adapter artifacts as-is; never builds
    them (see module docstring - tests-mutate-live-repo, Major)."""


def _make_exists_nonempty_test(adapter):
    def test(self):
        sibling = adapter["full_sibling"]
        self.assertTrue(
            sibling.is_file(),
            f"{adapter['name']}: missing sibling {sibling} - run "
            f"`bash {adapter['build_sh'].relative_to(_REPO_DIR)}` before this test",
        )
        self.assertGreater(sibling.stat().st_size, 0, f"{adapter['name']}: empty sibling {sibling}")

    return test


def _read_sibling_or_fail(self, adapter):
    """Reads the committed sibling artifact, refusing (never building) if
    it is missing - shared by every test factory below that reads it."""
    sibling = adapter["full_sibling"]
    self.assertTrue(
        sibling.is_file(),
        f"{adapter['name']}: missing sibling {sibling} - run "
        f"`bash {adapter['build_sh'].relative_to(_REPO_DIR)}` before this test",
    )
    return sibling.read_text(encoding="utf-8")


def _make_zero_deferred_test(adapter):
    def test(self):
        text = _read_sibling_or_fail(self, adapter)
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
        text = _read_sibling_or_fail(self, adapter)
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


class KimiMethodologyMdTests(unittest.TestCase):
    """.kimi was held back (INCONCLUSIVE runtime QA) - its SKILL.md embed
    is the full corpus, same as METHODOLOGY.md. No basename/pointer-block
    assertions apply here (kimi carries no corpus:begin machinery post
    hold-back); this class only confirms the sibling file itself is healthy
    since it still ships unconditionally."""

    def test_methodology_md_exists_nonempty(self):
        self.assertTrue(
            _KIMI_METHODOLOGY_MD.is_file(),
            f"missing {_KIMI_METHODOLOGY_MD} - run `bash .kimi/build.sh` before this test",
        )
        self.assertGreater(_KIMI_METHODOLOGY_MD.stat().st_size, 0)

    def test_methodology_md_zero_deferred(self):
        text = _KIMI_METHODOLOGY_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("Deferred at this corpus"), 0)

    def test_methodology_md_headings_present(self):
        text = _KIMI_METHODOLOGY_MD.read_text(encoding="utf-8")
        for section_file in sorted(_SECTIONS_DIR.glob("[0-9][0-9]-*.md")):
            heading = _first_top_level_heading(section_file.read_text(encoding="utf-8"))
            self.assertIn(heading, text, f"kimi: {section_file.name}'s heading {heading!r} missing")

    def test_kimi_build_sh_carries_no_corpus_flag(self):
        # DS-204 hold-back: kimi's build.sh must not pass --corpus to
        # build-methodology.sh anywhere - a stray flag would silently
        # re-introduce the minimal-corpus embed this round reverted.
        text = _KIMI_BUILD_SH.read_text(encoding="utf-8")
        self.assertNotIn("--corpus", text)


if __name__ == "__main__":
    unittest.main()
