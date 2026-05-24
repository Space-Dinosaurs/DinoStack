"""Regression tests for evals.auto.loop._normalise_headings.

Focuses on the fenced-code state machine: the high-blast-radius path where a
bug could silently corrupt the diff the harness applies.
"""
from __future__ import annotations

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
