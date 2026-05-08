"""Unit tests for evals.auto.apply - glob validation, LOC counting, extraction."""
from __future__ import annotations

from evals.auto.apply import (
    apply_whole_file,
    count_changed_loc,
    count_changed_loc_for_whole_file,
    extract_diff,
    extract_whole_file,
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
