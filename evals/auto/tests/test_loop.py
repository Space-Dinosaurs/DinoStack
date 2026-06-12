"""Regression tests for evals.auto.loop._normalise_headings and Fix-4 seam.

Focuses on the fenced-code state machine: the high-blast-radius path where a
bug could silently corrupt the diff the harness applies.

Fix-4 context: loop.py was changed to call extract_diff(raw_text) BEFORE
_normalise_headings(raw_text). Without this order, a diff containing lines
like '+```bash' would flip _normalise_headings' fence toggle, causing heading
normalisation to run inside the diff block and potentially corrupt hunk content
or alter verdict parsing.
"""
from __future__ import annotations

from evals.auto.apply import extract_diff
from evals.auto.loop import _normalise_headings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lines(text: str) -> list[str]:
    return text.splitlines()


# ---------------------------------------------------------------------------
# Headings OUTSIDE fences are normalised
# ---------------------------------------------------------------------------

def test_heading_outside_fence_is_normalised():
    """## Diff outside any fence becomes a plain heading."""
    inp = "## Diff\nsome prose\n"
    out = _normalise_headings(inp)
    # The heading line is lowercased / normalised; it must not keep '## Diff'
    assert "## Diff" not in out
    # Prose is preserved verbatim
    assert "some prose\n" in out


def test_bold_heading_outside_fence_is_normalised():
    """**Section:** style is normalised outside a fence."""
    inp = "**Changes:**\nsome content\n"
    out = _normalise_headings(inp)
    assert "**Changes:**" not in out
    assert "some content\n" in out


# ---------------------------------------------------------------------------
# Content INSIDE fences is preserved verbatim
# ---------------------------------------------------------------------------

def test_heading_inside_fence_preserved_verbatim():
    """A line that looks like a heading inside a ```diff fence must not be altered."""
    inp = (
        "## Preamble\n"
        "```diff\n"
        "--- a/content/agents/skeptic.md\n"
        "+++ b/content/agents/skeptic.md\n"
        "@@ -1,3 +1,4 @@\n"
        " existing line\n"
        "+## new section heading in diff\n"
        " existing line\n"
        "```\n"
        "## Postamble\n"
    )
    out = _normalise_headings(inp)
    lines = _lines(out)

    # Inside-fence diff content is verbatim
    assert "+## new section heading in diff" in lines

    # The fence delimiters themselves are preserved
    assert "```diff" in lines
    assert "```" in lines

    # Outside-fence headings ARE normalised
    assert "## Preamble" not in lines
    assert "## Postamble" not in lines


def test_diff_marker_lines_inside_fence_preserved():
    """Diff +/- marker lines inside a fence are not touched."""
    inp = (
        "```diff\n"
        "+## Added heading in content\n"
        "-## Removed heading in content\n"
        "```\n"
    )
    out = _normalise_headings(inp)
    lines = _lines(out)
    assert "+## Added heading in content" in lines
    assert "-## Removed heading in content" in lines


# ---------------------------------------------------------------------------
# Language-tagged fences are recognised
# ---------------------------------------------------------------------------

def test_language_tagged_fence_preserves_content():
    """```python fence: content inside preserved, including heading-looking lines."""
    inp = (
        "## Outside\n"
        "```python\n"
        "## this is a comment, not a heading\n"
        "x = 1\n"
        "```\n"
    )
    out = _normalise_headings(inp)
    lines = _lines(out)
    assert "## this is a comment, not a heading" in lines
    assert "x = 1" in lines
    assert "## Outside" not in lines


def test_diff_tagged_fence_preserves_all_content():
    """```diff fence with realistic unified diff content is preserved verbatim."""
    diff_body = (
        "--- a/evals/auto/loop.py\n"
        "+++ b/evals/auto/loop.py\n"
        "@@ -10,3 +10,4 @@\n"
        " existing line\n"
        "+new line\n"
        " existing line\n"
    )
    inp = f"prose heading here\n```diff\n{diff_body}```\n"
    out = _normalise_headings(inp)
    for diff_line in diff_body.splitlines():
        assert diff_line in _lines(out), f"diff line missing from output: {diff_line!r}"


# ---------------------------------------------------------------------------
# Unclosed fence: safe direction (preserve subsequent lines)
# ---------------------------------------------------------------------------

def test_unclosed_fence_preserves_subsequent_lines():
    """After an unclosed fence, remaining lines are NOT normalised (safe direction)."""
    inp = (
        "## Before fence\n"
        "```diff\n"
        "--- a/foo\n"
        "+++ b/foo\n"
        "## heading-looking line after unclosed fence\n"
    )
    out = _normalise_headings(inp)
    lines = _lines(out)

    # The outside heading before the fence is normalised
    assert "## Before fence" not in lines

    # Lines after the unclosed fence are left verbatim (in_fence=True state)
    assert "## heading-looking line after unclosed fence" in lines


# ---------------------------------------------------------------------------
# Invariant: fence delimiters are always preserved exactly
# ---------------------------------------------------------------------------

def test_fence_delimiters_preserved():
    """Opening and closing ``` lines are always passed through unchanged."""
    inp = "```diff\nsome content\n```\n"
    out = _normalise_headings(inp)
    assert out == inp


def test_empty_fence_preserved():
    """An empty fence block round-trips exactly."""
    inp = "```\n```\n"
    assert _normalise_headings(inp) == inp


# ---------------------------------------------------------------------------
# Round-trip: no fences -> only headings changed
# ---------------------------------------------------------------------------

def test_plain_prose_without_fences():
    """Non-heading lines outside fences pass through unchanged."""
    inp = "just some prose\nmore prose\n"
    assert _normalise_headings(inp) == inp


# ---------------------------------------------------------------------------
# Fix-4: extract_diff called BEFORE _normalise_headings (loop.py seam)
#
# The bug: if _normalise_headings ran first on text containing a diff with
# lines like '+```bash', its fence-toggle state machine would flip at those
# lines, causing heading normalisation to run inside the diff block and corrupt
# it. The fix is to extract the diff from raw_text first, THEN normalise.
#
# This test exercises the loop.py seam directly: calling extract_diff on
# raw_text and _normalise_headings on raw_text independently (the correct order)
# and verifying the extracted diff is intact even when _normalise_headings on
# the same text would corrupt headings outside the diff.
# ---------------------------------------------------------------------------

def test_fix4_extract_diff_before_normalise_headings_preserves_backtick_lines():
    """Fix-4 seam: extracting diff before heading normalisation preserves diff intact.

    Constructs editor output where:
    - A diff block contains '+```bash' and '+```' lines (backtick diff content)
    - Prose outside the diff has markdown headings

    The correct loop order (extract_diff first) must return the diff with all
    backtick content lines intact. If normalisation ran first and corrupted the
    fence toggle, _normalise_headings would enter the diff block and potentially
    alter its content, and the diff extraction might miss lines.
    """
    diff_body = (
        "--- a/content/agents/skeptic.md\n"
        "+++ b/content/agents/skeptic.md\n"
        "@@ -1,4 +1,7 @@\n"
        " existing line\n"
        "+```bash\n"
        "+echo hello\n"
        "+```\n"
        " ## heading-looking context line in diff\n"
        " existing line"
    )
    raw_text = (
        "## Preamble heading\n"
        "Some prose about the edit.\n"
        f"```diff\n{diff_body}\n```\n"
        "## Verdict heading\n"
        "Overfitting Rule verdict: no because straightforward improvement\n"
    )

    # Step 1: extract diff from raw_text (Fix-4 order - before normalisation).
    diff = extract_diff(raw_text)

    # Step 2: normalise headings on raw_text (for verdict parsing - done after).
    normalised = _normalise_headings(raw_text)

    # The extracted diff must be complete.
    assert diff is not None, "extract_diff returned None"
    assert "+```bash" in diff, "'+```bash' line missing from extracted diff"
    assert "+echo hello" in diff, "'+echo hello' line missing from extracted diff"
    assert "+```" in diff, "closing '+```' line missing from extracted diff"
    assert " ## heading-looking context line in diff" in diff, \
        "context line with heading prefix missing from extracted diff"

    # The normalised text must have transformed prose headings but not diff content.
    assert "## Preamble heading" not in normalised, "outside heading was not normalised"
    assert "## Verdict heading" not in normalised, "outside verdict heading was not normalised"
    # The verdict line itself should survive (it's not a heading pattern).
    assert "overfitting rule verdict" in normalised.lower()
