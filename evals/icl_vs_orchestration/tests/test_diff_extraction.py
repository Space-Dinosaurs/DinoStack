"""Tests for diff extraction and file inference heuristics.

Covers the three scoring bugs fixed in May 2026:
1. _extract_diff only captured the first file's diff (missing multi-file changes)
2. _infer_files_touched returned [] for git diff --stat blocks
3. _extract_gates_from_text didn't match path-qualified test signals
"""
from __future__ import annotations

import pytest

from evals.icl_vs_orchestration.conditions.ae_orchestrated.single_shot import (
    _extract_diff,
    _infer_files_touched,
)
from evals.icl_vs_orchestration.scoring.quality_gate_pass import _extract_gates_from_text


# ---------------------------------------------------------------------------
# _extract_diff
# ---------------------------------------------------------------------------

MULTI_FILE_DIFF = """\
## Diff

```diff
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,3 @@
- old
+ new
 context

--- a/file2.py
+++ b/file2.py
@@ -5,2 +5,2 @@
- remove
+ add
```
"""

RAW_DIFF_TWO_FILES = """\
--- a/src/main.py
+++ b/src/main.py
@@ -10,3 +10,4 @@
 def foo():
+    pass
     return 1

--- a/src/utils.py
+++ b/src/utils.py
@@ -1,2 +1,3 @@
+import os
 def bar():
"""

SINGLE_FILE_DIFF = """\
```diff
--- a/only.py
+++ b/only.py
@@ -1 +1 @@
-1
+2
```
"""

NO_DIFF = "No changes needed. The code is correct."


class TestExtractDiff:
    def test_multi_file_code_block(self):
        diff = _extract_diff(MULTI_FILE_DIFF)
        assert diff is not None
        assert "--- a/file1.py" in diff
        assert "--- a/file2.py" in diff
        assert "+++ b/file1.py" in diff
        assert "+++ b/file2.py" in diff

    def test_raw_unified_diff_two_files(self):
        diff = _extract_diff(RAW_DIFF_TWO_FILES)
        assert diff is not None
        assert "src/main.py" in diff
        assert "src/utils.py" in diff

    def test_single_file_code_block(self):
        diff = _extract_diff(SINGLE_FILE_DIFF)
        assert diff is not None
        assert "--- a/only.py" in diff

    def test_no_diff_returns_none(self):
        assert _extract_diff(NO_DIFF) is None

    def test_empty_string_returns_none(self):
        assert _extract_diff("") is None


# ---------------------------------------------------------------------------
# _infer_files_touched
# ---------------------------------------------------------------------------

GIT_DIFF_STAT = """\
 src/main.py | 10 ++++++
 src/utils.py |  5 -----
 2 files changed, 10 insertions(+), 5 deletions(-)
"""

STANDARD_UNIFIED_DIFF = """\
+++ b/src/app.py
@@ -1 +1 @@
-1
+2
+++ b/src/config.py
@@ -1 +1 @@
-a
+b
"""

MIXED_STAT_AND_UNIFIED = """\
+++ b/src/app.py
@@ -1 +1 @@
-1
+2

--- a/src/other.py
+++ b/src/other.py
@@ -1 +1 @@
-x
+y
"""


class TestInferFilesTouched:
    def test_git_diff_stat_format(self):
        files = _infer_files_touched(GIT_DIFF_STAT)
        assert "src/main.py" in files
        assert "src/utils.py" in files

    def test_standard_unified_diff(self):
        files = _infer_files_touched(STANDARD_UNIFIED_DIFF)
        assert "src/app.py" in files
        assert "src/config.py" in files

    def test_mixed_stat_and_unified(self):
        files = _infer_files_touched(MIXED_STAT_AND_UNIFIED)
        assert "src/app.py" in files
        assert "src/other.py" in files

    def test_none_input(self):
        assert _infer_files_touched(None) == []

    def test_empty_string(self):
        assert _infer_files_touched("") == []

    def test_no_files_returns_empty(self):
        assert _infer_files_touched("just some text") == []


# ---------------------------------------------------------------------------
# _extract_gates_from_text
# ---------------------------------------------------------------------------

class TestExtractGatesFromText:
    def test_simple_tests_pass(self):
        gates = _extract_gates_from_text("tests: pass")
        assert gates["tests"]["passed"] is True

    def test_simple_tests_fail(self):
        gates = _extract_gates_from_text("tests: fail")
        assert gates["tests"]["passed"] is False

    def test_path_qualified_tests_pass(self):
        gates = _extract_gates_from_text("evals/auto/tests/test_apply.py pass")
        assert gates["tests"]["passed"] is True

    def test_path_qualified_tests_fail(self):
        gates = _extract_gates_from_text("tests/test_runner.py fail")
        assert gates["tests"]["passed"] is False

    def test_lint_pass(self):
        gates = _extract_gates_from_text("lint: pass")
        assert gates["lint"]["passed"] is True

    def test_lint_fail(self):
        gates = _extract_gates_from_text("lint: fail")
        assert gates["lint"]["passed"] is False

    def test_typecheck_pass(self):
        gates = _extract_gates_from_text("typecheck: pass")
        assert gates["typecheck"]["passed"] is True

    def test_checkmark_lint(self):
        gates = _extract_gates_from_text("✓ lint")
        assert gates["lint"]["passed"] is True

    def test_no_gates_returns_empty(self):
        assert _extract_gates_from_text("no quality information here") == {}
