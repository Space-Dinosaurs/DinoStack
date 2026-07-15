#!/usr/bin/env python3
"""
Purpose: Regression tests for the Python activation guard hooks/lib/activation.py
         (is_active). Covers every activation layer plus the fail-ACTIVE contract
         and the <10ms timing assertion from the plan (Unit 10, risk R3).

Public API: python3 hooks/tests/test_activation_guard.py
            Exits 0 on all pass, 1 on any failure. Hermetic: uses tempfile
            sandboxes and a fake HOME so the real ~/.agentic is never touched.

Upstream deps: the guard module loaded by path; Python 3 stdlib only.
"""

from __future__ import annotations

import importlib.machinery as ilm
import importlib.util as ilu
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "lib" / "activation.py"

_loader = ilm.SourceFileLoader("activation", str(GUARD))
_spec = ilu.spec_from_loader("activation", _loader)
mod = ilu.module_from_spec(_spec)
_loader.exec_module(mod)

FAILS = 0


def check(label, cond):
    global FAILS
    if cond:
        print(f"  ok: {label}")
    else:
        print(f"  FAIL: {label}", file=sys.stderr)
        FAILS += 1


def main() -> int:
    # --- Layer 6: dormant (no marker) ---
    d = tempfile.mkdtemp()
    check("no .agentic -> dormant", mod.is_active(d) is False)

    # --- Layer 4: auto-detect (dir exists, no explicit marker) ---
    os.makedirs(os.path.join(d, ".agentic"), exist_ok=True)
    check("auto-detect .agentic dir -> active", mod.is_active(d) is True)

    # --- Layer 3: tombstone overrides auto-detect ---
    tomb = os.path.join(d, ".agentic", "dormant")
    open(tomb, "w").close()
    check("tombstone overrides auto-detect -> dormant", mod.is_active(d) is False)

    # --- Layer 1: explicit active file overrides tombstone ---
    open(os.path.join(d, ".agentic", "active"), "w").close()
    check("active file overrides tombstone -> active", mod.is_active(d) is True)

    # --- Layer 2: session file (fresh dir + tombstone + session) ---
    d2 = tempfile.mkdtemp()
    os.makedirs(os.path.join(d2, ".agentic"))
    open(os.path.join(d2, ".agentic", "dormant"), "w").close()
    open(os.path.join(d2, ".agentic", "active.session"), "w").close()
    check("active.session overrides tombstone -> active", mod.is_active(d2) is True)

    # --- Layer 5: allowlist (fake HOME, no project marker) ---
    d3 = tempfile.mkdtemp()  # no .agentic
    fake_home = tempfile.mkdtemp()
    os.makedirs(os.path.join(fake_home, ".agentic"))
    with open(os.path.join(fake_home, ".agentic", "activation.list"), "w") as fh:
        fh.write(os.path.realpath(d3) + "\n")
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = fake_home
    try:
        check("allowlisted cwd -> active", mod.is_active(d3) is True)
        # A non-listed sibling is still dormant.
        d4 = tempfile.mkdtemp()
        check("non-listed cwd -> dormant", mod.is_active(d4) is False)
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)

    # --- Never-activated projects emit a distinct "inactive" notice once ---
    # (Regression: previously they exited silently, giving no signal that every
    # enforcement hook is a no-op - only the explicit-tombstone path warned.)
    import io
    import contextlib
    d5 = tempfile.mkdtemp()  # no .agentic, not allowlisted
    fake_home2 = tempfile.mkdtemp()
    os.makedirs(os.path.join(fake_home2, ".agentic"))
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = fake_home2
    try:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            r1 = mod.is_active(d5)
        first = buf.getvalue()
        check("never-activated -> dormant", r1 is False)
        check("never-activated emits INACTIVE notice", "INACTIVE" in first)
        check("inactive notice names /ds activate", "/ds activate" in first)
        # Second call for the same project is silent (once-per-project marker).
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            mod.is_active(d5)
        check("inactive notice emitted only once", "INACTIVE" not in buf2.getvalue())
        # A tombstone project still gets the DORMANT (not INACTIVE) wording.
        d6 = tempfile.mkdtemp()
        os.makedirs(os.path.join(d6, ".agentic"))
        open(os.path.join(d6, ".agentic", "dormant"), "w").close()
        buf3 = io.StringIO()
        with contextlib.redirect_stderr(buf3):
            mod.is_active(d6)
        out3 = buf3.getvalue()
        check("tombstone project -> DORMANT wording, not INACTIVE",
              "DORMANT" in out3 and "INACTIVE" not in out3)
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("HOME", None)

    # --- Fail-ACTIVE: indeterminate cwd ---
    check("None cwd -> fail-ACTIVE", mod.is_active(None) is True)
    check("blank cwd -> fail-ACTIVE", mod.is_active("   ") is True)
    check("non-str cwd -> fail-ACTIVE", mod.is_active(12345) is True)

    # --- Timing: <10ms on the hot (dormant) path ---
    dt = tempfile.mkdtemp()
    n = 200
    start = time.perf_counter()
    for _ in range(n):
        mod.is_active(dt)
    per_call_ms = (time.perf_counter() - start) / n * 1000.0
    check(f"dormant path <10ms/call (measured {per_call_ms:.3f}ms)", per_call_ms < 10.0)

    if FAILS:
        print(f"\n{FAILS} FAILED", file=sys.stderr)
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
