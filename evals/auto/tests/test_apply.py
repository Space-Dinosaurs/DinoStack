"""Unit tests for evals.auto.apply - glob validation, LOC counting, extraction."""
from __future__ import annotations

from evals.auto.apply import (
    apply_whole_file,
    count_changed_loc,
    count_changed_loc_for_whole_file,
    extract_diff,
    extract_whole_file,
    normalise_heading,
    validate_paths,
    validate_single_path,
)


def test_extract_diff_finds_fenced_block():
    text = "prelude\n```diff\n--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-x\n+y\n```\ntrailer"
    d = extract_diff(text)
    assert d is not None
    assert "--- a/foo" in d
    assert "+y" in d


def test_extract_diff_absent_returns_none():
    assert extract_diff("no fence here") is None
    assert extract_diff("") is None


def test_count_changed_loc_ignores_headers():
    diff = (
        "--- a/x\n+++ b/x\n@@ -1,3 +1,4 @@\n"
        " ctx\n-old\n+new1\n+new2\n ctx2\n"
    )
    # 1 removal + 2 additions = 3; header lines and hunk line and context ignored.
    assert count_changed_loc(diff) == 3


def test_validate_paths_accepts_editable():
    diff = "--- a/content/agents/skeptic.md\n+++ b/content/agents/skeptic.md\n@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["content/agents/skeptic.md"], locked=["evals/**"])
    assert r["ok"] is True
    assert "content/agents/skeptic.md" in r["paths"]


def test_validate_paths_rejects_non_editable():
    diff = "--- a/content/agents/worker.md\n+++ b/content/agents/worker.md\n@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["content/agents/skeptic.md"], locked=[])
    assert r["ok"] is False
    assert "not_in_editable_allowlist" in r["reason"]


def test_validate_paths_rejects_locked_even_if_editable_has_recursive_glob():
    # Defense-in-depth: if editable is overly permissive, locked still bites.
    diff = "--- a/evals/scoring/skeptic_lite.py\n+++ b/evals/scoring/skeptic_lite.py\n@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["evals/scoring/skeptic_lite.py"], locked=["evals/**"])
    assert r["ok"] is False
    assert "locked_path" in r["reason"]


def test_validate_paths_rejects_path_traversal():
    diff = "--- a/../etc/passwd\n+++ b/../etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["**"], locked=[])
    assert r["ok"] is False
    assert "path_traversal_rejected" in r["reason"]


def test_validate_paths_rejects_empty_diff():
    assert validate_paths("", editable=["x"], locked=[])["ok"] is False
    assert validate_paths("   \n", editable=["x"], locked=[])["ok"] is False


def test_validate_paths_rejects_diff_without_headers():
    diff = "@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["**"], locked=[])
    assert r["ok"] is False
    assert "no_file_headers_found" in r["reason"]


def test_locked_double_star_matches_subpath():
    diff = "--- a/evals/fixtures/skeptic/sk-001/x\n+++ b/evals/fixtures/skeptic/sk-001/x\n@@ -1 +1 @@\n-x\n+y\n"
    r = validate_paths(diff, editable=["**"], locked=["evals/**"])
    assert r["ok"] is False


def test_extract_whole_file_bare_path():
    text = "prelude\n```markdown\npath/to/file.md\n# Header\ncontent\n```\ntrailer"
    r = extract_whole_file(text)
    assert r == ("path/to/file.md", "# Header\ncontent")


def test_extract_whole_file_comment_path():
    text = "```md\n<!-- file: foo/bar.md -->\nhello\n```"
    r = extract_whole_file(text)
    assert r == ("foo/bar.md", "hello")


def test_extract_whole_file_hash_path():
    text = "```markdown\n# foo/bar.md\nhello\n```"
    r = extract_whole_file(text)
    assert r == ("foo/bar.md", "hello")


def test_extract_whole_file_absent_returns_none():
    assert extract_whole_file("no fence") is None
    assert extract_whole_file("") is None


def test_validate_single_path_accepts_editable():
    r = validate_single_path(
        "content/agents/skeptic.md",
        editable=["content/agents/skeptic.md"],
        locked=["evals/**"],
    )
    assert r["ok"] is True
    assert r["paths"] == ["content/agents/skeptic.md"]


def test_validate_single_path_rejects_locked():
    r = validate_single_path("evals/x", editable=["**"], locked=["evals/**"])
    assert r["ok"] is False
    assert "locked_path" in r["reason"]


def test_validate_single_path_rejects_empty():
    r = validate_single_path("", editable=["x"], locked=[])
    assert r["ok"] is False
    assert r["reason"] == "empty_path"


def test_validate_single_path_rejects_traversal():
    r = validate_single_path("a/../b", editable=["**"], locked=[])
    assert r["ok"] is False
    assert "path_traversal_rejected" in r["reason"]


def test_count_changed_loc_for_whole_file_existing():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "test.md").write_text("line1\nline2\nline3\n")
        loc = count_changed_loc_for_whole_file(root, "test.md", "line1\nline2b\nline3\n")
        assert loc == 2


def test_count_changed_loc_for_whole_file_new():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        loc = count_changed_loc_for_whole_file(root, "new.md", "a\nb\nc")
        assert loc == 3


def test_apply_whole_file_writes_and_stages():
    import tempfile
    import subprocess
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
        r = apply_whole_file(root, "dir/file.md", "hello world")
        assert r["ok"] is True
        assert r["reason"] == "whole_file_written"
        assert (root / "dir/file.md").read_text() == "hello world"


def test_apply_whole_file_rejects_empty_path():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        r = apply_whole_file(Path(tmp), "", "x")
        assert r["ok"] is False


def test_apply_whole_file_rejects_traversal():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        r = apply_whole_file(Path(tmp), "../x", "y")
        assert r["ok"] is False


def test_extract_whole_file_heading_not_path():
    """A markdown heading like '# Introduction' must NOT be treated as a path."""
    text = "```markdown\n# Introduction\nBody text\n```"
    r = extract_whole_file(text)
    assert r == ("", "# Introduction\nBody text")


# ---------------------------------------------------------------------------
# normalise_heading
# ---------------------------------------------------------------------------

def test_normalise_heading_hash_markers():
    assert normalise_heading("## Diff") == "diff"
    assert normalise_heading("# Foo Bar") == "foo bar"
    assert normalise_heading("### SECTION") == "section"


def test_normalise_heading_bold_markers():
    assert normalise_heading("**Overfitting Rule:**") == "overfitting rule"
    assert normalise_heading("**Diff**") == "diff"
    assert normalise_heading("**Foo Bar**:") == "foo bar"


def test_normalise_heading_trailing_colon_only():
    assert normalise_heading("Verdict:") == "verdict"
    assert normalise_heading("## Result:") == "result"


def test_normalise_heading_plain_text():
    assert normalise_heading("just text") == "just text"
    assert normalise_heading("  spaced  ") == "spaced"


def test_normalise_heading_empty():
    assert normalise_heading("") == ""
    assert normalise_heading("   ") == ""


# ---------------------------------------------------------------------------
# Fix 2: CRLF-tolerant extraction (regression tests)
# test_extract_diff_crlf_line_endings_normalised FAILS against the OLD regex
# (r"```diff\s*\n(.*?)\n```") because the old pattern does not allow \r before
# the closing fence when the file uses CRLF line endings (\r\n```).
# test_extract_diff_trailing_whitespace_on_closing_fence does NOT discriminate
# old vs new - the old regex also passes it because trailing spaces appear
# *after* the ``` fence, outside the match boundary. It is retained here as a
# current-behavior conformance test.
# ---------------------------------------------------------------------------

def test_extract_diff_trailing_whitespace_on_closing_fence():
    """Closing fence with trailing spaces after it must still extract correctly.

    Note: this test passes both old and new regex because trailing spaces appear
    after the closing fence token, not before it. It is a conformance test for
    current behavior, not a regression discriminator.
    """
    body = "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-x\n+y"
    text = f"```diff\n{body}\n```   "  # trailing spaces after closing fence
    d = extract_diff(text)
    assert d is not None, "extraction failed with trailing whitespace on closing fence"
    assert "--- a/foo" in d
    assert "+y" in d


def test_extract_diff_crlf_line_endings_normalised():
    """CRLF line endings in the diff body are normalised to LF.

    This test FAILS against the old regex (r"```diff\\s*\\n(.*?)\\n```") because
    \\r\\n``` does not match \\n```. It PASSES against the fixed \\n\\r?```.
    """
    body_crlf = "--- a/foo\r\n+++ b/foo\r\n@@ -1 +1 @@\r\n-x\r\n+y"
    text = f"```diff\r\n{body_crlf}\r\n```"
    d = extract_diff(text)
    assert d is not None, "extraction failed with CRLF line endings"
    # Result must contain only LF, not CRLF.
    assert "\r" not in d, "CRLF not normalised to LF"
    assert "--- a/foo" in d
    assert "+y" in d


def test_extract_diff_no_diff_returns_none():
    """Regression guard: no diff fence -> None."""
    assert extract_diff("plain text, no fence") is None
    assert extract_diff("") is None


def test_extract_diff_empty_fence_returns_none():
    """An empty diff fence (no-op signal) returns None."""
    assert extract_diff("```diff\n```") is None
    assert extract_diff("```diff\n\n```") is None


# ---------------------------------------------------------------------------
# MAJOR 1 regression: space-prefixed context line " ```" does not truncate diff
# This test FAILS against the old [ \t\r]* closing pattern because (.*?) is
# non-greedy and terminates at the first " ```" context line inside the body.
# It PASSES against the corrected \n\r?``` pattern.
# ---------------------------------------------------------------------------

def test_extract_diff_space_prefixed_fence_context_line_not_truncated():
    """A diff context line ' ```' must not prematurely close the outer fence.

    Fails against r"```diff\\s*\\n(.*?)\\n[ \\t\\r]*```" (old pattern with
    [ \\t\\r]* allowing leading space) because the non-greedy (.*?) terminates
    at the first space-prefixed ``` context line. Passes against \\n\\r?```.
    """
    body = (
        "--- a/content/commands/implement-ticket.md\n"
        "+++ b/content/commands/implement-ticket.md\n"
        "@@ -10,7 +10,8 @@\n"
        " some prose line\n"
        " ```diff\n"          # context line: space + ``` - triggers premature match in old regex
        " --- a/example\n"
        " +++ b/example\n"
        " ```\n"              # context line: space + ``` - also a potential early terminator
        "+new added line\n"
        " final context line"
    )
    text = f"```diff\n{body}\n```"
    d = extract_diff(text)
    assert d is not None, "extraction returned None - diff was truncated at space-prefixed context fence"
    assert "+new added line" in d, "content after space-prefixed ``` context line was truncated"
    assert "final context line" in d, "final context line was truncated"


# ---------------------------------------------------------------------------
# extract_diff-level: backtick diff-content lines do not corrupt apply.py
# (Note: this tests the apply.py extract_diff function directly, NOT the Fix-4
# loop.py reorder. For the loop.py Fix-4 coverage, see test_loop.py.)
# ---------------------------------------------------------------------------

def test_extract_diff_backtick_content_line_not_corrupted():
    """A diff line like '+```bash' is extracted intact by apply.extract_diff."""
    body = (
        "--- a/content/agents/skeptic.md\n"
        "+++ b/content/agents/skeptic.md\n"
        "@@ -1,3 +1,4 @@\n"
        " existing line\n"
        "+```bash\n"
        "+echo hello\n"
        "+```\n"
        " existing line"
    )
    text = f"```diff\n{body}\n```"
    d = extract_diff(text)
    assert d is not None, "extraction returned None when diff contains backtick lines"
    assert "+```bash" in d, "backtick diff-content line was dropped"
    assert "+echo hello" in d
