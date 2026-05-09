"""
Purpose: Regression test for _preserve_results_across_reset / _restore_results helpers.
         Verifies round-trip preservation of *.tsv and *.runlog.jsonl files that would
         otherwise be destroyed by git reset --hard in evals/auto/loop.py.

         Extracts helper functions from loop.py source via AST so the test works in an
         isolated workspace where loop.py's sibling relative imports are absent.

Public API: pytest test module; no exported symbols.

Upstream deps: evals/auto/loop.py (source text), ast, types, pathlib, pytest (tmp_path)

Downstream consumers: CI quality gate, corpus replay harness

Failure modes: NameError/AttributeError when helpers are absent in loop.py (pre-merge
               state) - expected and tolerated by corpus preflight as deferred-ImportError
               class failures. ModuleNotFoundError on helper extraction is also tolerated.

Performance: <1 ms; AST parse of loop.py + pure in-memory tmp_path fixture.
"""

import ast
import sys
import textwrap
import types
from pathlib import Path


def _extract_helpers(loop_path: Path) -> types.ModuleType:
    """Parse loop.py source and extract _preserve_results_across_reset and
    _restore_results without executing relative imports.

    Raises AttributeError (mapped to pre-merge-tolerable failure) if either
    helper function is not found in the source.
    """
    source = loop_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(loop_path))

    target_names = {"_preserve_results_across_reset", "_restore_results"}
    func_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_names:
            func_nodes.append(node)

    if len(func_nodes) < len(target_names):
        found = {n.name for n in func_nodes}
        missing = target_names - found
        raise AttributeError(
            f"loop.py is missing helpers (pre-merge state): {missing}"
        )

    # Build a minimal module with only the needed imports and the two functions.
    # The helpers only use Path and Dict from stdlib - safe to provide directly.
    helper_src = textwrap.dedent("""\
        from pathlib import Path
        from typing import Dict
    """)
    for node in func_nodes:
        helper_src += "\n" + ast.unparse(node) + "\n"

    mod = types.ModuleType("_loop_helpers")
    exec(compile(helper_src, "<loop_helpers>", "exec"), mod.__dict__)  # noqa: S102
    return mod


def _get_helpers():
    """Return (_preserve, _restore) callables from workspace loop.py."""
    # The harness copies workspace_files into a workspace dir and runs pytest
    # with cwd=workspace. This test file lives at evals/auto/tests/test_*.py
    # inside that workspace, so loop.py is two parents up.
    loop_path = Path(__file__).parent.parent / "loop.py"
    mod = _extract_helpers(loop_path)
    return mod._preserve_results_across_reset, mod._restore_results


def test_round_trip_preservation(tmp_path: Path) -> None:
    """
    AC: _preserve_results_across_reset snapshots *.tsv and *.runlog.jsonl;
    _restore_results writes them back correctly after files are cleared.
    AttributeError means pre-merge (helpers absent) - expected failure.
    """
    _preserve, _restore = _get_helpers()

    results_dir = tmp_path / "evals" / "results"
    results_dir.mkdir(parents=True)

    tsv_file = results_dir / "auto-harness.tsv"
    runlog_file = results_dir / "session-001.runlog.jsonl"

    tsv_content = "ticket_id\tresult\tscore\nr-trivial-preserve-results\tpass\t1.0\n"
    runlog_content = '{"ts": "2026-05-09T00:00:00Z", "event": "iteration", "phase": "run"}\n'

    tsv_file.write_text(tsv_content, encoding="utf-8")
    runlog_file.write_text(runlog_content, encoding="utf-8")

    preserved = _preserve(tmp_path)

    assert len(preserved) == 2, f"Expected 2 files preserved, got {len(preserved)}"

    tsv_file.write_text("", encoding="utf-8")
    runlog_file.write_text("", encoding="utf-8")

    assert tsv_file.read_text(encoding="utf-8") == "", "Sanity: tsv should be empty before restore"
    assert runlog_file.read_text(encoding="utf-8") == "", "Sanity: runlog should be empty before restore"

    _restore(tmp_path, preserved)

    assert tsv_file.read_text(encoding="utf-8") == tsv_content, "TSV content not restored correctly"
    assert runlog_file.read_text(encoding="utf-8") == runlog_content, "Runlog content not restored correctly"


def test_preserve_empty_results_dir(tmp_path: Path) -> None:
    """Edge case: results dir with no matching files returns empty dict."""
    _preserve, _restore = _get_helpers()

    results_dir = tmp_path / "evals" / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "unrelated.txt").write_text("noise", encoding="utf-8")

    preserved = _preserve(tmp_path)
    assert preserved == {}, "No .tsv or .runlog.jsonl should yield empty dict"
    _restore(tmp_path, preserved)


def test_preserve_missing_results_dir(tmp_path: Path) -> None:
    """Edge case: results dir absent - helper returns empty dict without error."""
    _preserve, _restore = _get_helpers()

    preserved = _preserve(tmp_path)
    assert preserved == {}, "Missing results dir should yield empty dict"
    _restore(tmp_path, preserved)
