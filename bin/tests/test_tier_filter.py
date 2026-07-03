#!/usr/bin/env python3
"""
Tests for scripts/lib/tier-filter.py.

Drives the filter as a subprocess (stdin -> stdout) so the exercised code path
matches what scripts/build-methodology.sh runs at build time. Covers:

  - byte-identical round-trip for the full tier (with and without trailing
    newline) — a hard requirement documented in the module header
  - file-level `<!-- tiers: ... -->` inclusion / exclusion
  - inline `<!-- tier:begin ... -->` / `<!-- tier:end -->` inclusion / exclusion
  - multi-tier combos (`full medium`)
  - error exit paths (exit 3) with `<stdin>:N:` line numbers:
      * unknown tier name in a file-level marker
      * unknown tier name in an inline block marker
      * stray `<!-- tier:end -->`
      * unclosed `<!-- tier:begin -->`
      * nested `<!-- tier:begin -->`
  - invalid tier argv (exit 2)
  - empty input (no output, exit 0)

Run with: python3 bin/tests/test_tier_filter.py
       or: python3 -m pytest bin/tests/test_tier_filter.py
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FILTER = REPO_ROOT / "scripts" / "lib" / "tier-filter.py"


def run_filter(tier: str, payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(FILTER), tier],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


class TestByteRoundTrip(unittest.TestCase):
    def test_full_tier_preserves_trailing_newline(self):
        payload = "line one\nline two\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, payload)

    def test_full_tier_preserves_absent_trailing_newline(self):
        payload = "line one\nline two"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, payload)

    def test_empty_input_emits_nothing(self):
        proc = run_filter("full", "")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")


class TestFileLevelMarker(unittest.TestCase):
    def test_includes_matching_tier_and_drops_marker(self):
        payload = "<!-- tiers: medium full -->\nbody line\n"
        proc = run_filter("medium", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "body line\n")

    def test_excludes_non_matching_tier(self):
        payload = "<!-- tiers: full -->\nbody line\n"
        proc = run_filter("medium", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_unknown_tier_in_file_marker_exit3_with_lineno(self):
        payload = "<!-- tiers: full bogus -->\nbody\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("unknown tier name 'bogus'", proc.stderr)
        self.assertIn("<stdin>:1:", proc.stderr)


class TestInlineBlock(unittest.TestCase):
    def test_block_included_for_matching_tier(self):
        payload = "before\n<!-- tier:begin medium -->\ninside\n<!-- tier:end -->\nafter\n"
        proc = run_filter("medium", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "before\ninside\nafter\n")

    def test_block_excluded_for_non_matching_tier(self):
        payload = "before\n<!-- tier:begin medium -->\ninside\n<!-- tier:end -->\nafter\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "before\nafter\n")

    def test_markers_never_leak_into_output(self):
        payload = "<!-- tier:begin full -->\ninside\n<!-- tier:end -->\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("tier:begin", proc.stdout)
        self.assertNotIn("tier:end", proc.stdout)

    def test_multi_tier_combo_full_medium(self):
        payload = "a\n<!-- tier:begin full medium -->\nshared\n<!-- tier:end -->\nz\n"
        for tier in ("full", "medium"):
            proc = run_filter(tier, payload)
            self.assertEqual(proc.returncode, 0, msg=tier)
            self.assertEqual(proc.stdout, "a\nshared\nz\n", msg=tier)
        proc_min = run_filter("minimal", payload)
        self.assertEqual(proc_min.returncode, 0)
        self.assertEqual(proc_min.stdout, "a\nz\n")

    def test_unknown_tier_in_block_marker_exit3_with_lineno(self):
        payload = "x\n<!-- tier:begin full bogus -->\ninside\n<!-- tier:end -->\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("unknown tier name 'bogus'", proc.stderr)
        self.assertIn("<stdin>:2:", proc.stderr)


class TestErrorExitPaths(unittest.TestCase):
    def test_stray_end_exit3_with_lineno(self):
        payload = "line one\n<!-- tier:end -->\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("stray", proc.stderr)
        self.assertIn("<stdin>:2:", proc.stderr)

    def test_unclosed_begin_exit3_with_lineno(self):
        payload = "a\n<!-- tier:begin full -->\ninside\n"
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("unclosed", proc.stderr)
        self.assertIn("<stdin>:3:", proc.stderr)

    def test_nested_begin_exit3_with_lineno(self):
        payload = (
            "<!-- tier:begin full -->\n"
            "outer\n"
            "<!-- tier:begin medium -->\n"
            "inner\n"
            "<!-- tier:end -->\n"
            "<!-- tier:end -->\n"
        )
        proc = run_filter("full", payload)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("nested", proc.stderr)
        self.assertIn("<stdin>:3:", proc.stderr)

    def test_invalid_tier_argv_exit2(self):
        proc = run_filter("bogus", "anything\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid tier", proc.stderr)


if __name__ == "__main__":
    unittest.main()
