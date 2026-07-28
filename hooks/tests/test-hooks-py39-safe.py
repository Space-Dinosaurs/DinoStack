# Run with: python3 hooks/tests/test-hooks-py39-safe.py
"""
Regression guard: every hooks/enforce-*.py file must stay importable on
Python 3.8/3.9 (macOS system python3 is 3.9 and is the documented
supported floor for these hooks).

A PEP 604 union annotation (`X | Y`, e.g. `str | None`) used in a function
signature or variable annotation is evaluated at MODULE IMPORT TIME on
Python 3.8/3.9 unless the module carries `from __future__ import
annotations` (PEP 563), which defers annotation evaluation to strings.
Without the future import, a PEP 604 union raises TypeError at import -
before any hook's kill-switch or outer try/except can catch it - which
crashes-to-block a PreToolUse hook (the exact failure mode DS-94 exists to
prevent; see hooks/enforce-shippable-edit.py's manifest and MEMORY.md).

This test statically scans every hooks/enforce-*.py file AND every
hooks/lib/*.py file (the shared modules those hooks dynamically import,
e.g. hooks/lib/enforcement_log.py - added when the fire-logging telemetry
lib landed, see hooks/tests/test-hooks-pep604-guard.py's own docstring
which used to warn this glob was scoped to hooks/lib/ by construction) with
`ast`: for each module, it finds `X | Y` (ast.BinOp with ast.BitOr) inside
an annotation context (function argument annotations, function return
annotations, variable annotations) and FAILS if that module lacks
`from __future__ import annotations`. This guards every current and future
sibling hook (and lib module) against the same regression class, not just
this one line.
"""

from __future__ import annotations

import ast
import glob
import os
import sys

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
TARGET_GLOBS = (
    os.path.join(HOOKS_DIR, "enforce-*.py"),
    os.path.join(HOOKS_DIR, "lib", "*.py"),
)


def has_future_annotations(tree: ast.Module) -> bool:
    """True if the module's (leading) import block includes
    `from __future__ import annotations`."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def _contains_bitor(node: ast.AST) -> bool:
    """True if `node` (an annotation expression subtree) contains a
    `X | Y` BinOp anywhere within it."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
            return True
    return False


def find_unguarded_unions(path: str) -> list[str]:
    """Return a list of human-readable descriptions of PEP 604 union
    annotations found in `path` that would crash at import on Python
    3.8/3.9 because the module lacks `from __future__ import annotations`.

    Empty list means: either no PEP 604 unions in annotation position, or
    the module has the future import (safe either way).
    """
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        # A file that doesn't even parse on the AST's own Python version is
        # a separate problem this test isn't scoped to diagnose - surface
        # it distinctly rather than silently passing.
        return [f"SyntaxError parsing {path}: {exc}"]

    if has_future_annotations(tree):
        return []  # annotations are deferred to strings - always safe.

    findings: list[str] = []

    for node in ast.walk(tree):
        # Function argument + return annotations.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_args = (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
            if node.args.vararg:
                all_args.append(node.args.vararg)
            if node.args.kwarg:
                all_args.append(node.args.kwarg)

            for arg in all_args:
                if arg.annotation is not None and _contains_bitor(arg.annotation):
                    findings.append(
                        f"{path}:{arg.lineno}: parameter '{arg.arg}' of "
                        f"'{node.name}' has an unguarded PEP 604 union annotation"
                    )

            if node.returns is not None and _contains_bitor(node.returns):
                findings.append(
                    f"{path}:{node.lineno}: return annotation of '{node.name}' "
                    "has an unguarded PEP 604 union annotation"
                )

        # Variable annotations (module- or function-scoped).
        elif isinstance(node, ast.AnnAssign):
            if node.annotation is not None and _contains_bitor(node.annotation):
                target = (
                    node.target.id
                    if isinstance(node.target, ast.Name)
                    else ast.dump(node.target)
                )
                findings.append(
                    f"{path}:{node.lineno}: variable annotation '{target}' "
                    "has an unguarded PEP 604 union annotation"
                )

    return findings


def main() -> int:
    targets = sorted(
        {p for pattern in TARGET_GLOBS for p in glob.glob(pattern)}
    )
    if not targets:
        print(
            "  [FAIL] no hooks/enforce-*.py or hooks/lib/*.py files found - "
            "glob misconfigured?"
        )
        return 1

    failed = 0
    total = 0
    for path in targets:
        total += 1
        findings = find_unguarded_unions(path)
        rel = os.path.relpath(path, os.path.join(HOOKS_DIR, ".."))
        if findings:
            failed += 1
            print(f"  [FAIL] {rel}")
            for finding in findings:
                print(f"         {finding}")
        else:
            print(f"  [PASS] {rel}")

    print()
    if failed == 0:
        print(
            f"All {total} hooks/enforce-*.py and hooks/lib/*.py files are "
            "Python 3.8/3.9-safe."
        )
        return 0
    else:
        print(
            f"{failed}/{total} hooks/enforce-*.py or hooks/lib/*.py files "
            "have unguarded PEP 604 unions."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
