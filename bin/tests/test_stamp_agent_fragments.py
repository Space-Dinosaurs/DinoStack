#!/usr/bin/env python3
"""
Regression spec for scripts/lib/stamp_agent_fragments.py's marker-integrity
guards (unbalanced/nested `<!-- shared: -->` markers, and a fragment body
that itself contains a marker-like string).

Puts the invariant "a `<!-- shared: -->` span in content/agents/*.md is
byte-identical to its `<!-- FRAGMENT: -->` source" on the already-required
`bin-tests` CI check, and proves the two failure-mode guards actually fire
rather than silently no-op'ing on a corrupted span.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
MODULE_PATH = REPO_DIR / "scripts" / "lib" / "stamp_agent_fragments.py"

_spec = importlib.util.spec_from_file_location("stamp_agent_fragments", MODULE_PATH)
stamp_agent_fragments = importlib.util.module_from_spec(_spec)
sys.modules["stamp_agent_fragments"] = stamp_agent_fragments
_spec.loader.exec_module(stamp_agent_fragments)


class TestMarkerBalanceGuard(unittest.TestCase):
    """check_marker_balance() must fail loud on an unbalanced or nested
    `<!-- shared: -->`/`<!-- /shared -->` pair, and pass on a well-formed
    span."""

    def test_balanced_span_does_not_exit(self):
        # Should not raise/exit.
        stamp_agent_fragments.check_marker_balance(
            MODULE_PATH, "<!-- shared:a -->x<!-- /shared -->"
        )

    def test_missing_closer_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            stamp_agent_fragments.check_marker_balance(MODULE_PATH, "<!-- shared:a -->x")
        self.assertNotEqual(ctx.exception.code, 0)

    def test_missing_opener_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            stamp_agent_fragments.check_marker_balance(MODULE_PATH, "x<!-- /shared -->")
        self.assertNotEqual(ctx.exception.code, 0)

    def test_nested_opener_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            stamp_agent_fragments.check_marker_balance(
                MODULE_PATH,
                "<!-- shared:a --><!-- shared:b -->x<!-- /shared --><!-- /shared -->",
            )
        self.assertNotEqual(ctx.exception.code, 0)

    def test_two_sibling_spans_do_not_exit(self):
        # Balanced, non-nested, two separate spans - must NOT be flagged.
        stamp_agent_fragments.check_marker_balance(
            MODULE_PATH,
            "<!-- shared:a -->x<!-- /shared --> <!-- shared:b -->y<!-- /shared -->",
        )


class TestFragmentBodyRejectsMarkerLikeStrings(unittest.TestCase):
    """A fragment body containing a literal `<!-- /shared -->` (or
    `<!-- shared: -->`) makes stamping non-convergent - both agent files
    would grow on every run. load_fragments() must reject this."""

    def test_fragment_body_with_closer_marker_is_rejected(self):
        text = (
            "<!-- FRAGMENT:bad -->\n"
            "some text <!-- /shared --> more text\n"
            "<!-- /FRAGMENT -->\n"
        )
        with self.assertRaises(SystemExit) as ctx:
            stamp_agent_fragments.parse_fragments(text)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_fragment_body_with_opener_marker_is_rejected(self):
        text = (
            "<!-- FRAGMENT:bad -->\n"
            "some text <!-- shared:other --> more text\n"
            "<!-- /FRAGMENT -->\n"
        )
        with self.assertRaises(SystemExit) as ctx:
            stamp_agent_fragments.parse_fragments(text)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_normal_fragment_body_is_accepted(self):
        text = "<!-- FRAGMENT:ok -->\nsome plain text\n<!-- /FRAGMENT -->\n"
        fragments = stamp_agent_fragments.parse_fragments(text)
        self.assertEqual(fragments["ok"], "some plain text")


# Expected `<!-- shared:<id> -->` span-id set per agent file. Pinned here
# (not derived by iterating the live files) so that deleting a span's
# markers entirely - or replacing a whole span with plain prose - reds this
# test instead of silently vanishing from every iteration-based assertion
# below. Without this, a removed span makes SHARED_RE.finditer() yield
# nothing to check, so every other assertion in this class passes vacuously
# ("green means the check did not run"). Derived by reading the live tree;
# update this map in the same commit as any deliberate span addition or
# removal.
EXPECTED_SPAN_IDS = {
    "engineer.md": frozenset(
        {
            "async-primitive-list",
            "identifier-rename-trigger",
            "identifier-type-list",
            "rename-exemption-clause",
            "test-file-glob-list",
        }
    ),
    "skeptic.md": frozenset(
        {
            "async-primitive-list",
            "identifier-rename-trigger",
            "identifier-type-list",
            "rename-exemption-clause",
            "test-file-glob-list",
        }
    ),
}


class TestLiveTreeIsStamped(unittest.TestCase):
    """The committed content/agents/*.md tree must already reflect
    content/fragments/pre-submit-check-kernels.md - re-derives expected
    span content from the fragments file (no shelling out to the stamp
    script) and compares against the live files."""

    def setUp(self):
        kernels_text = stamp_agent_fragments.KERNELS_FILE.read_text(encoding="utf-8")
        self.fragments = stamp_agent_fragments.parse_fragments(kernels_text)

    def test_expected_span_ids_are_present(self):
        """Guard against a span's markers being deleted entirely (or a span
        being replaced with plain prose) - that state is invisible to every
        SHARED_RE.finditer()-based assertion below because there is nothing
        left to iterate."""
        for filename, expected_ids in EXPECTED_SPAN_IDS.items():
            path = stamp_agent_fragments.AGENTS_DIR / filename
            with self.subTest(path=filename):
                text = path.read_text(encoding="utf-8")
                found_ids = {
                    match.group("id")
                    for match in stamp_agent_fragments.SHARED_RE.finditer(text)
                }
                self.assertEqual(
                    found_ids,
                    expected_ids,
                    f"{filename}'s set of '<!-- shared:<id> -->' spans "
                    f"({sorted(found_ids)}) does not match the expected set "
                    f"({sorted(expected_ids)}) - a span's markers may have "
                    "been deleted or a span replaced with unmarked prose. "
                    "If this is a deliberate span addition/removal, update "
                    "EXPECTED_SPAN_IDS in this file in the same commit.",
                )

    def test_every_shared_span_matches_its_fragment_source(self):
        for path in sorted(stamp_agent_fragments.AGENTS_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in stamp_agent_fragments.SHARED_RE.finditer(text):
                frag_id = match.group("id")
                with self.subTest(path=path.name, frag_id=frag_id):
                    self.assertIn(
                        frag_id,
                        self.fragments,
                        f"{path.name} has a shared:{frag_id} span with no matching "
                        "FRAGMENT definition in the kernels file.",
                    )
                    expected = (
                        f"<!-- shared:{frag_id} -->{self.fragments[frag_id]}"
                        "<!-- /shared -->"
                    )
                    self.assertEqual(
                        match.group(0),
                        expected,
                        f"{path.name}'s shared:{frag_id} span is out of sync with "
                        "content/fragments/pre-submit-check-kernels.md - run "
                        "'bash scripts/stamp-agent-fragments.sh' and commit the result.",
                    )

    def test_shared_span_ids_that_recur_are_byte_identical_across_files(self):
        seen = {}
        for path in sorted(stamp_agent_fragments.AGENTS_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in stamp_agent_fragments.SHARED_RE.finditer(text):
                frag_id = match.group("id")
                body = match.group(0)
                interior = body[len(f"<!-- shared:{frag_id} -->") : -len("<!-- /shared -->")]
                if frag_id in seen:
                    prev_path, prev_interior = seen[frag_id]
                    self.assertEqual(
                        interior,
                        prev_interior,
                        f"shared:{frag_id} differs between {prev_path.name} and "
                        f"{path.name} - stamping should make every occurrence of "
                        "the same fragment id byte-identical.",
                    )
                else:
                    seen[frag_id] = (path, interior)


if __name__ == "__main__":
    unittest.main()
