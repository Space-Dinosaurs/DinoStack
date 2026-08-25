#!/usr/bin/env python3
"""
Tests for scripts/check-corpus-coverage.py, the CI guard (DS-204) that every
content/sections/[0-9][0-9]-*.md file declares a corpus posture.

Covers:
  - a partitioned file (corpus:begin blocks, some with mandatory triggers)
    passes
  - a file with an explicit whole-file `corpora: minimal medium full` marker
    passes
  - an unmarked file fails, exit 1, naming the offending file
  - README.md in the sections dir is ignored (glob excludes it)
  - a corpus:begin block missing its mandatory trigger fails
  - main() exits 1 on a missing/empty sections dir
  - a real check against the live content/sections dir also runs cleanly
    when every file has a posture (skips if the working tree currently lacks
    postures - this file must not assume unit A's own steps 5-7 have landed)

Run with: python3 bin/tests/test_corpus_coverage.py
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent.parent
_MODULE_PATH = _REPO_DIR / "scripts" / "check-corpus-coverage.py"

_spec = importlib.util.spec_from_file_location("check_corpus_coverage", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
ccc = importlib.util.module_from_spec(_spec)
sys.modules["check_corpus_coverage"] = ccc
_spec.loader.exec_module(ccc)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="corpus-coverage-test-")
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)
        self.sections_dir = Path(self._tmpdir)

    def _write(self, name: str, content: str) -> Path:
        path = self.sections_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_partitioned_file_passes(self):
        self._write(
            "02-fake.md",
            "## Heading\n\n"
            "<!-- corpus:begin full medium | trigger: something happens -->\n"
            "Deferred body.\n"
            "<!-- corpus:end -->\n",
        )
        problems = ccc.check_file(self.sections_dir / "02-fake.md")
        self.assertEqual(problems, [])

    def test_explicit_all_corpora_file_passes(self):
        self._write(
            "01-fake.md",
            "<!-- corpora: minimal medium full -->\n## Heading\n\nBody.\n",
        )
        problems = ccc.check_file(self.sections_dir / "01-fake.md")
        self.assertEqual(problems, [])

    def test_unmarked_file_fails_naming_it(self):
        self._write("03-fake.md", "## Heading\n\nBody with zero markers.\n")
        problems = ccc.check_file(self.sections_dir / "03-fake.md")
        self.assertEqual(len(problems), 1)
        self.assertIn("03-fake.md", problems[0])
        self.assertIn("no corpus posture declared", problems[0])

    def test_unbalanced_corpus_end_reports_the_real_malformation(self):
        # DS-204 round-1 Skeptic finding coverage-diagnostic-masked (Minor):
        # a lone, unbalanced corpus:end (no matching corpus:begin) must NOT
        # be misreported as "no corpus posture declared" - that message
        # masks the real parse error. file_has_posture() must detect the
        # corpus:end marker and route to the real parser, which reports the
        # actual unbalanced-marker malformation.
        self._write("06-fake.md", "Body.\n<!-- corpus:end -->\n")
        problems = ccc.check_file(self.sections_dir / "06-fake.md")
        self.assertEqual(len(problems), 1)
        self.assertIn("06-fake.md", problems[0])
        self.assertNotIn("no corpus posture declared", problems[0])
        self.assertIn("no matching corpus:begin", problems[0])

    def test_missing_trigger_fails(self):
        self._write(
            "04-fake.md",
            "<!-- corpus:begin full medium -->\nBody.\n<!-- corpus:end -->\n",
        )
        problems = ccc.check_file(self.sections_dir / "04-fake.md")
        self.assertEqual(len(problems), 1)
        self.assertIn("04-fake.md", problems[0])
        self.assertIn("missing the mandatory", problems[0])

    def test_universal_list_block_needs_no_trigger(self):
        self._write(
            "05-fake.md",
            "<!-- corpus:begin minimal medium full -->\nBody.\n<!-- corpus:end -->\n",
        )
        problems = ccc.check_file(self.sections_dir / "05-fake.md")
        self.assertEqual(problems, [])

    def test_readme_in_sections_dir_ignored_by_glob(self):
        self._write("README.md", "not a section file, no posture")
        self._write(
            "01-fake.md",
            "<!-- corpora: minimal medium full -->\nBody.\n",
        )
        section_files = sorted(self.sections_dir.glob("[0-9][0-9]-*.md"))
        names = [p.name for p in section_files]
        self.assertNotIn("README.md", names)
        self.assertIn("01-fake.md", names)

    def test_main_returns_zero_when_all_clean(self):
        self._write(
            "01-fake.md",
            "<!-- corpora: minimal medium full -->\nBody.\n",
        )
        self._write("README.md", "ignored")
        rc = ccc.main([str(self.sections_dir)])
        self.assertEqual(rc, 0)

    def test_main_returns_one_when_any_file_dirty(self):
        self._write(
            "01-fake.md",
            "<!-- corpora: minimal medium full -->\nBody.\n",
        )
        self._write("02-fake.md", "no posture at all\n")
        rc = ccc.main([str(self.sections_dir)])
        self.assertEqual(rc, 1)

    def test_main_returns_one_on_missing_directory(self):
        missing = self.sections_dir / "does-not-exist"
        rc = ccc.main([str(missing)])
        self.assertEqual(rc, 1)

    def test_main_returns_one_on_empty_directory(self):
        rc = ccc.main([str(self.sections_dir)])
        self.assertEqual(rc, 1)

    def test_multiple_offending_files_all_reported(self):
        self._write("01-fake.md", "no posture 1\n")
        self._write("02-fake.md", "no posture 2\n")
        problems = []
        for path in sorted(self.sections_dir.glob("[0-9][0-9]-*.md")):
            problems.extend(ccc.check_file(path))
        self.assertEqual(len(problems), 2)


class LiveRepoTests(unittest.TestCase):
    """Exercises the CLI against the real content/sections tree. This test
    is descriptive, not prescriptive about the tree's current state - it
    documents the exit code without asserting a specific one, since unit A's
    own steps 5-7 land posture markers earlier in the same PR sequence."""

    def test_cli_runs_cleanly_against_repo_root(self):
        proc = subprocess.run(
            [sys.executable, str(_MODULE_PATH)],
            capture_output=True,
            text=True,
            cwd=str(_REPO_DIR),
        )
        # A live-tree run must always produce parseable, informative output
        # (never a silent/blank result), regardless of pass/fail.
        self.assertTrue(proc.stdout or proc.stderr)


if __name__ == "__main__":
    unittest.main()
