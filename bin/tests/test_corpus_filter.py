#!/usr/bin/env python3
"""
Tests for scripts/lib/corpus-filter.py, the corpus-marker line filter used by
build-methodology.sh (DS-204 unit A).

Covers:
  - balanced/unbalanced corpus:begin / corpus:end markers
  - nested corpus:begin rejection
  - mandatory-trigger rule (present, absent, universal-list exemption)
  - per-corpus inclusion/exclusion of a wrapped block
  - pointer-block generation, trigger de-duplication, and trigger ordering
  - byte-identity property: full-corpus output == source with marker lines
    stripped and all block content retained
  - file-level `corpora:` marker parsing and stripping
  - unknown/duplicate/empty corpus token error paths
  - CLI entry point (stdin -> stdout, exit codes)

Run with: python3 bin/tests/test_corpus_filter.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).parent.parent.parent / "scripts" / "lib" / "corpus-filter.py"

_spec = importlib.util.spec_from_file_location("corpus_filter", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
cf = importlib.util.module_from_spec(_spec)
sys.modules["corpus_filter"] = cf
_spec.loader.exec_module(cf)


def strip_marker_lines(text: str) -> str:
    """Reference implementation of the byte-identity claim: delete every
    corpora:/corpus:begin/corpus:end marker line, retain everything else."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            cf.CORPORA_FILE_RE.match(line)
            or cf.CORPUS_BEGIN_RE.match(line)
            or cf.CORPUS_END_RE.match(line)
        ):
            continue
        out.append(line)
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


class FilterTextTests(unittest.TestCase):
    # --- balanced / unbalanced markers -------------------------------------

    def test_balanced_block_full_corpus_includes_content(self):
        text = (
            "Header.\n"
            "<!-- corpus:begin full medium | trigger: event X -->\n"
            "Block content.\n"
            "<!-- corpus:end -->\n"
            "Footer.\n"
        )
        out = cf.filter_text(text, "full", "s.md")
        self.assertIn("Block content.", out)
        self.assertIn("Header.", out)
        self.assertIn("Footer.", out)
        self.assertNotIn("corpus:begin", out)
        self.assertNotIn("corpus:end", out)

    def test_unbalanced_end_no_begin_raises(self):
        text = "Header.\n<!-- corpus:end -->\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("s.md:2", str(ctx.exception))
        self.assertIn("no matching corpus:begin", str(ctx.exception))

    def test_unbalanced_begin_no_end_raises(self):
        text = "<!-- corpus:begin full medium | trigger: x -->\nBody.\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("s.md:1", str(ctx.exception))
        self.assertIn("unbalanced corpus:begin", str(ctx.exception))

    def test_unbalanced_begin_names_the_begin_line_not_eof(self):
        text = "\n\n<!-- corpus:begin full medium | trigger: x -->\nBody.\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("s.md:3", str(ctx.exception))

    # --- nesting -------------------------------------------------------------

    def test_nested_begin_raises(self):
        text = (
            "<!-- corpus:begin full medium | trigger: outer -->\n"
            "<!-- corpus:begin full medium | trigger: inner -->\n"
            "Body.\n"
            "<!-- corpus:end -->\n"
            "<!-- corpus:end -->\n"
        )
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("nested corpus:begin", str(ctx.exception))
        self.assertIn("s.md:2", str(ctx.exception))

    def test_sequential_non_nested_blocks_are_valid(self):
        text = (
            "<!-- corpus:begin full medium | trigger: a -->\n"
            "A.\n"
            "<!-- corpus:end -->\n"
            "<!-- corpus:begin full medium | trigger: b -->\n"
            "B.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("A.", out)
        self.assertIn("B.", out)

    # --- mandatory trigger rule ----------------------------------------------

    def test_partial_list_without_trigger_raises(self):
        text = "<!-- corpus:begin full medium -->\nBody.\n<!-- corpus:end -->\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("missing the mandatory", str(ctx.exception))

    def test_partial_list_with_trigger_is_valid(self):
        text = (
            "<!-- corpus:begin minimal | trigger: rare event -->\n"
            "Body.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("Body.", out)

    def test_universal_list_exempt_from_trigger_requirement(self):
        text = (
            "<!-- corpus:begin minimal medium full -->\n"
            "Body.\n"
            "<!-- corpus:end -->\n"
        )
        # No trigger clause, and the list is the universal set - must not raise.
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("Body.", out)

    def test_universal_list_any_order_exempt(self):
        text = (
            "<!-- corpus:begin full minimal medium -->\n"
            "Body.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("Body.", out)

    # --- per-corpus inclusion --------------------------------------------------

    def test_minimal_excludes_full_medium_block(self):
        text = (
            "Kept.\n"
            "<!-- corpus:begin full medium | trigger: event -->\n"
            "Excluded.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("Kept.", out)
        self.assertNotIn("Excluded.", out)

    def test_medium_includes_full_medium_block(self):
        text = (
            "<!-- corpus:begin full medium | trigger: event -->\n"
            "Included.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "medium", "s.md", file_label="s.md")
        self.assertIn("Included.", out)

    def test_full_includes_full_medium_block(self):
        text = (
            "<!-- corpus:begin full medium | trigger: event -->\n"
            "Included.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("Included.", out)

    def test_minimal_only_list_excluded_at_full(self):
        text = (
            "<!-- corpus:begin minimal | trigger: e -->\n"
            "OnlyMinimal.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertNotIn("OnlyMinimal.", out)

    def test_content_outside_any_block_always_included(self):
        text = (
            "Always1.\n"
            "<!-- corpus:begin minimal | trigger: e -->\n"
            "Sometimes.\n"
            "<!-- corpus:end -->\n"
            "Always2.\n"
        )
        for corpus in ("minimal", "medium", "full"):
            out = cf.filter_text(text, corpus, "s.md", file_label="s.md")
            self.assertIn("Always1.", out)
            self.assertIn("Always2.", out)

    # --- pointer-block generation ----------------------------------------------

    def test_pointer_block_omitted_when_nothing_deferred(self):
        text = "Header.\nFooter.\n"
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertNotIn("Deferred at this corpus", out)

    def test_pointer_block_present_when_something_deferred(self):
        text = "<!-- corpus:begin full | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("**Deferred at this corpus.**", out)
        self.assertIn("- e", out)

    def test_pointer_block_names_full_text_name_and_source_name(self):
        text = "<!-- corpus:begin full | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        out = cf.filter_text(
            text, "minimal", "02-delegation.md", full_text_name="MY-FULL.md", file_label="s.md"
        )
        self.assertIn("`MY-FULL.md`", out)
        self.assertIn('"02-delegation.md"', out)

    def test_pointer_block_default_full_text_name(self):
        text = "<!-- corpus:begin full | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("`METHODOLOGY.md`", out)

    def test_pointer_block_dedupes_identical_trigger_text(self):
        text = (
            "<!-- corpus:begin full | trigger: same event -->\n"
            "Body1.\n"
            "<!-- corpus:end -->\n"
            "<!-- corpus:begin full | trigger: same event -->\n"
            "Body2.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertEqual(out.count("- same event"), 1)

    def test_pointer_block_preserves_source_order(self):
        text = (
            "<!-- corpus:begin full | trigger: first event -->\n"
            "B1.\n"
            "<!-- corpus:end -->\n"
            "<!-- corpus:begin full | trigger: second event -->\n"
            "B2.\n"
            "<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertLess(out.index("- first event"), out.index("- second event"))

    def test_pointer_block_lists_every_distinct_trigger(self):
        text = (
            "<!-- corpus:begin full | trigger: alpha -->\nA.\n<!-- corpus:end -->\n"
            "<!-- corpus:begin full | trigger: beta -->\nB.\n<!-- corpus:end -->\n"
        )
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertIn("- alpha", out)
        self.assertIn("- beta", out)

    # --- byte-identity property ------------------------------------------------

    def test_full_corpus_byte_identical_to_marker_lines_stripped(self):
        text = (
            "## Heading\n"
            "\n"
            "Always here.\n"
            "\n"
            "<!-- corpus:begin full medium | trigger: something happens -->\n"
            "Deferred content line 1.\n"
            "Deferred content line 2.\n"
            "<!-- corpus:end -->\n"
            "\n"
            "Trailing always-here line.\n"
        )
        full_out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertEqual(full_out, strip_marker_lines(text))

    def test_full_corpus_byte_identical_with_file_level_marker(self):
        text = (
            "<!-- corpora: minimal medium full -->\n"
            "## Heading\n"
            "\n"
            "Body content.\n"
        )
        full_out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertEqual(full_out, strip_marker_lines(text))

    def test_full_corpus_byte_identical_no_markers_at_all(self):
        text = "## Heading\n\nPlain content, no markers anywhere.\n"
        full_out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertEqual(full_out, text)

    def test_full_corpus_byte_identical_multiple_blocks(self):
        text = (
            "A.\n"
            "<!-- corpus:begin full medium | trigger: e1 -->\n"
            "B.\n"
            "<!-- corpus:end -->\n"
            "C.\n"
            "<!-- corpus:begin full medium | trigger: e2 -->\n"
            "D.\n"
            "<!-- corpus:end -->\n"
            "E.\n"
        )
        full_out = cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertEqual(full_out, strip_marker_lines(text))

    # --- file-level corpora: marker --------------------------------------------

    def test_file_level_corpora_marker_stripped_from_output(self):
        text = "<!-- corpora: minimal medium full -->\n## Heading\nBody.\n"
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertNotIn("corpora:", out)
        self.assertIn("## Heading", out)
        self.assertIn("Body.", out)

    def test_file_level_corpora_marker_recognized_on_any_line(self):
        text = "Body before.\n<!-- corpora: minimal medium full -->\nBody after.\n"
        out = cf.filter_text(text, "minimal", "s.md", file_label="s.md")
        self.assertNotIn("corpora:", out)
        self.assertIn("Body before.", out)
        self.assertIn("Body after.", out)

    def test_file_level_corpora_marker_invalid_token_raises(self):
        text = "<!-- corpora: minimal bogus full -->\nBody.\n"
        with self.assertRaises(cf.CorpusFilterError):
            cf.filter_text(text, "minimal", "s.md", file_label="s.md")

    # --- error paths: unknown / duplicate / empty tokens ------------------------

    def test_unknown_corpus_token_in_begin_raises(self):
        text = "<!-- corpus:begin large | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("unknown corpus token 'large'", str(ctx.exception))

    def test_duplicate_corpus_token_in_begin_raises(self):
        text = "<!-- corpus:begin full full | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "s.md", file_label="s.md")
        self.assertIn("duplicate corpus token 'full'", str(ctx.exception))

    def test_unknown_active_corpus_argument_raises(self):
        text = "Body.\n"
        with self.assertRaises(cf.CorpusFilterError):
            cf.filter_text(text, "gigantic", "s.md", file_label="s.md")

    def test_error_names_correct_line_mid_file(self):
        text = "L1\nL2\nL3\n<!-- corpus:end -->\n"
        with self.assertRaises(cf.CorpusFilterError) as ctx:
            cf.filter_text(text, "full", "deep.md", file_label="deep.md")
        self.assertIn("deep.md:4", str(ctx.exception))

    # --- regex module-level surface (single-source-of-truth contract) ----------

    def test_regexes_are_exported_module_level_constants(self):
        self.assertTrue(hasattr(cf, "CORPORA_FILE_RE"))
        self.assertTrue(hasattr(cf, "CORPUS_BEGIN_RE"))
        self.assertTrue(hasattr(cf, "CORPUS_END_RE"))
        self.assertTrue(cf.CORPUS_BEGIN_RE.match("<!-- corpus:begin full | trigger: x -->"))
        self.assertTrue(cf.CORPUS_END_RE.match("<!-- corpus:end -->"))
        self.assertTrue(cf.CORPORA_FILE_RE.match("<!-- corpora: minimal medium full -->"))


class CLITests(unittest.TestCase):
    def _run(self, args, stdin_text):
        return subprocess.run(
            [sys.executable, str(_MODULE_PATH), *args],
            input=stdin_text,
            capture_output=True,
            text=True,
        )

    def test_cli_full_corpus_roundtrip(self):
        stdin_text = "Header.\nBody.\n"
        proc = self._run(
            ["--corpus", "full", "--source-name", "s.md"],
            stdin_text,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, stdin_text)

    def test_cli_minimal_defers_and_exits_zero(self):
        stdin_text = "<!-- corpus:begin full | trigger: e -->\nBody.\n<!-- corpus:end -->\n"
        proc = self._run(
            ["--corpus", "minimal", "--source-name", "s.md"],
            stdin_text,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Deferred at this corpus", proc.stdout)

    def test_cli_error_exits_nonzero_and_names_file(self):
        stdin_text = "<!-- corpus:end -->\n"
        proc = self._run(
            ["--corpus", "full", "--source-name", "broken.md"],
            stdin_text,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("broken.md", proc.stderr)

    def test_cli_rejects_invalid_corpus_choice(self):
        proc = self._run(
            ["--corpus", "bogus", "--source-name", "s.md"],
            "Body.\n",
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_full_text_name_flag_used_in_pointer(self):
        stdin_text = "<!-- corpus:begin full | trigger: e -->\nB.\n<!-- corpus:end -->\n"
        proc = self._run(
            [
                "--corpus",
                "minimal",
                "--source-name",
                "s.md",
                "--full-text-name",
                "CUSTOM.md",
            ],
            stdin_text,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("`CUSTOM.md`", proc.stdout)


if __name__ == "__main__":
    unittest.main()
