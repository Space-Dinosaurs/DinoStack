"""
Purpose: Executes a pytest command in a workspace directory as a subprocess and
         returns a structured outcome dict. Isolates test execution from the
         harness process so failures in generated code do not crash the harness.

Public API: run_tests(test_command, workspace, pythonpath=".", timeout_seconds=30) -> dict

Upstream dependencies:
  - shlex (stdlib) - tokenize test_command string safely without shell=True
  - subprocess (stdlib) - spawn and capture the pytest process
  - os (stdlib) - read and extend PYTHONPATH environment variable
  - time (stdlib) - measure wall-clock duration via monotonic clock
  - pathlib.Path (stdlib) - type for workspace and pythonpath resolution

Downstream consumers:
  - evals/icl_vs_orchestration/runner.py - calls run_tests() per ticket when
    test_command is present in the corpus entry

Failure modes:
  - subprocess.TimeoutExpired: captured; returns outcome="error" with error message,
    never re-raised. Caller does not need to handle it.
  - OSError (e.g. command not found, bad executable): captured; returns
    outcome="error" with str(e), never re-raised.
  - All other exceptions propagate normally (unexpected; indicates harness bug).
  - No shell=True is used; shell injection via test_command is not possible.

Performance: per-call overhead is the test command's own runtime plus ~10 ms for
             subprocess setup. stdout_tail is capped at 500 chars to bound memory.
"""

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


def run_tests(
    test_command: str,
    workspace: Path,
    pythonpath: str = ".",
    timeout_seconds: int = 30,
) -> dict:
    """Run *test_command* inside *workspace* and return a structured outcome dict.

    Parameters
    ----------
    test_command:
        The full pytest invocation string, e.g. ``"pytest tests/ -x -q"``.
        Tokenised with :func:`shlex.split`; never passed to a shell.
    workspace:
        Absolute (or resolvable) path to the directory that serves as the
        working directory for the subprocess.
    pythonpath:
        Relative path (from *workspace*) to prepend to ``PYTHONPATH`` so that
        generated source code can be imported during the test run.
    timeout_seconds:
        Hard wall-clock limit for the subprocess.  Defaults to 30 s.

    Returns
    -------
    dict with keys:
        outcome (str): ``"pass"`` | ``"fail"`` | ``"error"``
        returncode (int | None): process exit code, or ``None`` on error
        stdout_tail (str): last 500 chars of combined stdout+stderr
        duration_seconds (float): elapsed wall-clock time
        error (str | None): human-readable error message when outcome is
            ``"error"``, otherwise ``None``
    """
    args = shlex.split(test_command)
    # If test_command starts with bare "pytest", rewrite to use the current
    # interpreter's pytest module so the harness works regardless of whether
    # the bare `pytest` binary is on PATH.
    if args and args[0] == "pytest":
        args = [sys.executable, "-m", "pytest"] + args[1:]
    env = os.environ.copy()
    abs_pypath = str((workspace / pythonpath).resolve())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{abs_pypath}:{existing}" if existing else abs_pypath

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration = time.monotonic() - t0
        stdout_tail = (proc.stdout + proc.stderr)[-500:]
        outcome = "pass" if proc.returncode == 0 else "fail"
        return {
            "outcome": outcome,
            "returncode": proc.returncode,
            "stdout_tail": stdout_tail,
            "duration_seconds": duration,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "outcome": "error",
            "returncode": None,
            "stdout_tail": "",
            "duration_seconds": float(timeout_seconds),
            "error": f"timed out after {timeout_seconds}s",
        }
    except OSError as e:
        return {
            "outcome": "error",
            "returncode": None,
            "stdout_tail": "",
            "duration_seconds": 0.0,
            "error": str(e),
        }
