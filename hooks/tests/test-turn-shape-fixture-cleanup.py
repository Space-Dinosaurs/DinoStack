# Run with: python3 hooks/tests/test-turn-shape-fixture-cleanup.py
"""
Purpose: hooks/tests/test-enforce-turn-shape.py runs every hook subprocess
         from a scratch cwd (`_HOOK_CWD`) and left that directory behind on
         each run, one more `test-turn-shape-cwd-*` entry in the system temp
         dir per CI job and per local gate run. This runs that test with
         TMPDIR pointed at a scratch directory and asserts no such entry
         survives its exit. Retire with `_HOOK_CWD`.

Upstream deps: Python 3 stdlib; hooks/tests/test-enforce-turn-shape.py.

Failure modes: exits 1 with the surviving paths when the directory is left
         behind, or with the child's output when the child itself fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-enforce-turn-shape.py")
PREFIX = "test-turn-shape-cwd-"


def main() -> int:
    with open(TARGET, encoding="utf-8") as handle:
        if f'mkdtemp(prefix="{PREFIX}")' not in handle.read():
            print(f"  [FAIL] {os.path.basename(TARGET)} no longer creates a {PREFIX}* dir; this test checks nothing")
            return 1
    scratch = tempfile.mkdtemp(prefix="turn-shape-cleanup-")
    try:
        proc = subprocess.run([sys.executable, TARGET], env={**os.environ, "TMPDIR": scratch},
                              capture_output=True, text=True, timeout=240)
        if proc.returncode != 0:
            print(f"  [FAIL] {os.path.basename(TARGET)} exited {proc.returncode}\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
            return 1
        left = sorted(name for name in os.listdir(scratch) if name.startswith(PREFIX))
        if left:
            print(f"  [FAIL] _HOOK_CWD left behind: {left}")
            return 1
        print("  [PASS] _HOOK_CWD is removed at exit")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
