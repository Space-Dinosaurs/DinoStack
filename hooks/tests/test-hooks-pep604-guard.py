# Run with: python3 hooks/tests/test-hooks-pep604-guard.py
"""
Regression guard for the whole hooks subsystem's PEP 604 / Python 3.9
import-time crash class.

CPython evaluates function and variable annotations EAGERLY at def-time
unless the module carries `from __future__ import annotations` (PEP 563).
PEP 604 union syntax (`X | None`) on a builtin type in annotation position
raises `TypeError` the instant such a module is imported under Python
3.8/3.9 - before main(), before any try/except fail-open guard. This bites
ONLY on 3.8/3.9; 3.10+ interprets `X | None` as a runtime `types.UnionType`
and never crashes, so a purely dynamic "run the file and check exit code"
test would pass silently on any 3.10+ CI runner (this project's
hooks-python-tests CI job runs Python 3.11) and fail to protect 3.9 users.

Scope: this guard covers top-level hooks/*.py (the hooks themselves, e.g.
hooks/enforce-background-spawn.py), hooks/tests/*.py (the test helper
files, e.g. hooks/tests/test-enforce-tier.py - these carry their own
`run_hook(payload, extra_env: dict | None = None)`-style helper signatures
and are just as import-time-fragile as the hooks they test), AND
hooks/lib/*.py (the shared modules those hooks dynamically import, e.g.
hooks/lib/enforcement_log.py - added when the fire-logging telemetry lib
landed; hooks/lib/ was EXCLUDED BY CONSTRUCTION before that, back when it
had no .py files at all, only .js/.sh - this scope note is what closed
that gap; if a new .py file is added to hooks/lib/, _lib_files() below
already covers it).

This test is therefore STATIC and version-independent: it parses every
covered file with `ast`, and for any module that does NOT declare
`from __future__ import annotations`, walks the WHOLE tree (function
parameter/return annotations and variable annotations, at
module/class/nested-function scope - all of which are eagerly evaluated at
def-time) looking for a BinOp using the `|` operator (PEP 604 union) in
annotation position. Any hit is a regression regardless of which Python
version runs this test.

A secondary runtime smoke check (executes each covered file with empty
stdin and asserts no import-time traceback under the CURRENT interpreter)
is included as a belt-and-suspenders check, but it is NOT the primary
guard - it cannot detect the bug when this test itself runs under
Python 3.10+. The smoke check excludes THIS file from its own subprocess
loop (see _smoke_targets()) - including it would spawn a copy of this
script as a subprocess, which would then try to smoke-test itself again,
recursing without termination.
"""

import ast
import os
import subprocess
import sys

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..")
TESTS_DIR = os.path.join(HOOKS_DIR, "tests")
LIB_DIR = os.path.join(HOOKS_DIR, "lib")
SELF_PATH = os.path.realpath(__file__)


def _hook_files():
    """Top-level hooks/*.py files only (not hooks/tests/, not hooks/lib/)."""
    return sorted(
        f for f in os.listdir(HOOKS_DIR)
        if f.endswith(".py") and os.path.isfile(os.path.join(HOOKS_DIR, f))
    )


def _test_files():
    """hooks/tests/*.py files (the test helpers, including this guard
    itself - static scanning is safe for self-inclusion; the runtime smoke
    loop excludes self separately, see _smoke_targets())."""
    return sorted(
        f for f in os.listdir(TESTS_DIR)
        if f.endswith(".py") and os.path.isfile(os.path.join(TESTS_DIR, f))
    )


def _lib_files():
    """hooks/lib/*.py files (shared modules dynamically imported by the
    enforce-*.py hooks, e.g. hooks/lib/enforcement_log.py). Absent
    directory returns [] rather than raising - this guard must never
    itself crash if hooks/lib/ is ever removed."""
    if not os.path.isdir(LIB_DIR):
        return []
    return sorted(
        f for f in os.listdir(LIB_DIR)
        if f.endswith(".py") and os.path.isfile(os.path.join(LIB_DIR, f))
    )


def _scanned_files():
    """Combined, deduped (label, absolute_path) pairs covering top-level
    hooks/*.py, hooks/tests/*.py, and hooks/lib/*.py.

    Dedup is by resolved absolute path: the three directories are disjoint
    today, so no file can currently match more than one glob, but a future
    layout change (e.g. a re-export or symlink) must not cause a file to be
    double-counted by this guard. First-seen label wins (hooks/*.py, then
    hooks/tests/*.py, then hooks/lib/*.py)."""
    seen = {}
    for fname in _hook_files():
        abspath = os.path.realpath(os.path.join(HOOKS_DIR, fname))
        seen.setdefault(abspath, fname)
    for fname in _test_files():
        abspath = os.path.realpath(os.path.join(TESTS_DIR, fname))
        seen.setdefault(abspath, os.path.join("tests", fname))
    for fname in _lib_files():
        abspath = os.path.realpath(os.path.join(LIB_DIR, fname))
        seen.setdefault(abspath, os.path.join("lib", fname))
    pairs = [(label, path) for path, label in seen.items()]
    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _smoke_targets(scanned):
    """*scanned* minus this guard's own file - included in the static AST
    scan (safe, no execution) but excluded from the runtime subprocess
    loop (self-invocation would recurse without termination)."""
    return [(label, path) for label, path in scanned if path != SELF_PATH]


def _module_has_future_annotations(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def _iter_annotation_nodes(tree):
    """Yield (annotation_ast_node, description) for every EAGERLY-EVALUATED
    annotation in the module: function parameter/return annotations (at any
    scope, including nested functions - ast.walk covers all of them) and
    variable annotations (ast.AnnAssign, at module/class/function scope)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arg_group = (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
            for arg in arg_group:
                if arg.annotation is not None:
                    yield arg.annotation, f"{node.name}() param '{arg.arg}'"
            for special in (node.args.vararg, node.args.kwarg):
                if special is not None and special.annotation is not None:
                    yield special.annotation, f"{node.name}() param '{special.arg}'"
            if node.returns is not None:
                yield node.returns, f"{node.name}() return annotation"
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation, "variable annotation"


def _contains_bitor(annotation_node):
    """True if a PEP 604 `X | Y` BinOp appears anywhere within
    *annotation_node* (covers nested generics like `dict[str, int | None]`)."""
    for sub in ast.walk(annotation_node):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
            return True
    return False


def find_pep604_violations(path):
    """Return a list of human-readable violation strings for *path*, or an
    empty list if the module is safe on Python 3.8/3.9."""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)
    if _module_has_future_annotations(tree):
        return []  # annotations deferred to strings - never eagerly evaluated
    violations = []
    for annotation_node, description in _iter_annotation_nodes(tree):
        if _contains_bitor(annotation_node):
            violations.append(
                f"{os.path.basename(path)}:{annotation_node.lineno}: "
                f"{description} uses PEP 604 '|' syntax without "
                "'from __future__ import annotations' - crashes on Python 3.8/3.9"
            )
    return violations


def run_file_smoke(path):
    """Secondary belt-and-suspenders check: run *path* with empty stdin
    under the CURRENT interpreter and confirm no import-time traceback.
    For hooks/*.py this exercises main() with a no-op payload (fail-open
    exit 0). For hooks/tests/*.py this runs the file's own test suite
    (stdin is unused by these files, so it just executes normally) - which
    additionally confirms the file reaches its assertions rather than
    dying at import, per the task's stated preference. NOTE: this does NOT
    catch the PEP 604 bug when this guard itself runs under Python 3.10+
    (see module docstring) - it is not the primary guard."""
    result = subprocess.run(
        [sys.executable, path],
        input="",
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


hook_files = _hook_files()
test_files = _test_files()

if not hook_files:
    print(
        "ERROR: glob hooks/*.py matched zero files - discovery is broken, not clean",
        file=sys.stderr,
    )
    sys.exit(1)

if not test_files:
    print(
        "ERROR: glob hooks/tests/*.py matched zero files - discovery is broken, not clean",
        file=sys.stderr,
    )
    sys.exit(1)

scanned = _scanned_files()
smoke_targets = _smoke_targets(scanned)
failed = 0

print(
    f"Static AST guard: {len(scanned)} file(s) "
    f"({len(hook_files)} in hooks/, {len(test_files)} in hooks/tests/)"
)
for label, path in scanned:
    violations = find_pep604_violations(path)
    ok = len(violations) == 0
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    for v in violations:
        print(f"         {v}")

print()
print(
    f"Runtime smoke check (secondary, python {sys.version.split()[0]}; "
    f"{len(smoke_targets)} file(s), excludes this guard's own file to avoid "
    "self-invocation recursion; does not catch the bug on Python 3.10+):"
)
for label, path in smoke_targets:
    rc, stderr = run_file_smoke(path)
    ok = (rc == 0) and ("Traceback" not in stderr)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         rc:     {rc}")
        print(f"         stderr: {stderr!r}")

total = len(scanned) + len(smoke_targets)
print()
if failed == 0:
    print(f"All {total} checks passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} checks FAILED.")
    sys.exit(1)
