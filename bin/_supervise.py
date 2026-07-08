#!/usr/bin/env python3
"""
Internal worker-process supervision primitives for agentic-team's external-CLI
dispatch. NOT a public CLI - do not invoke directly.

Purpose: give agentic-team a small, testable set of primitives for watching a
spawned worker process group, detecting stalls and hard timeouts, killing the
whole tree, and recording a machine-readable status trail. Integration into
bin/agentic-team is present; this module ships the primitives plus the
agentic-team wiring.

Public API:
  write_status(run_dir, **fields)
    Atomically merge *fields* into <run_dir>/status.json. When the incoming
    "state" differs from the persisted state, appends a transition record
    {"ts","from","to","reason"} to the "transitions" list. Uses atomic_write
    from bin/_lib.py so readers never see a partial file.

  read_status(run_dir) -> dict | None
    Tolerant reader. Returns the parsed dict, or None if the file is missing,
    empty, or corrupt (never raises on bad JSON).

  check_progress(paths, stall_seconds, timeout_seconds, started_at) -> str
    Pure detection. Heartbeat = max mtime of the output files (falling back to
    *started_at* before any output exists). Returns:
      "timed_out"  when now - started_at   > timeout_seconds  (hard cap, wins)
      "stalled"    when now - heartbeat     > stall_seconds    (inactivity)
      "ok"         otherwise.

  kill_process_group(pid, grace_seconds=5)
    SIGTERM the process group of *pid* (os.getpgid), wait up to grace_seconds
    for it to die, then SIGKILL any survivors. Already-dead groups
    (ProcessLookupError) are handled silently. Requires the worker to have been
    spawned with start_new_session=True (its own group), matching the dispatch
    convention in bin/agentic-team.

  supervise(proc, run_dir, stdout_path, stderr_path, stall_seconds,
            timeout_seconds, poll_interval=5.0) -> int
    Blocking watchdog (caller runs it in a thread). Polls every *poll_interval*
    seconds, updating status.json (last_output_ts, output_bytes). On stall or
    timeout it kills the process group and returns the sentinel exit code; on
    natural exit it returns proc.returncode.

Exit-code sentinels (documented convention, shared with bin/agentic-team):
  124 - hard timeout (total wall-clock exceeded timeout_seconds)
  125 - stall (no output for stall_seconds)

Status "state" values: running | stalled | killed | retrying | failed_over |
failed | done.

Per-harness stall overrides live in _STALL_DEFAULTS; interactive-ish harnesses
(claude/gemini/cursor-agent) get a longer default stall window than the module
baseline. Callers pass the resolved value in; the table is exported for them.

Upstream deps: Python 3.11 stdlib (json, os, signal, time, pathlib) + bin/_lib
(atomic_write). Downstream consumer: bin/agentic-team (later wave).
"""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import json
import os
import signal
import subprocess
import sys as _sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Load bin/_lib from the same directory (no-op if already imported by a sibling
# CLI). Mirrors the import shim used by bin/agentic-identity so a bare
# invocation resolves the sibling regardless of cwd / symlinking.
# ---------------------------------------------------------------------------
_LIB_PATH = Path(__file__).resolve().parent / "_lib.py"
if "_lib" in _sys.modules:
    _lib_mod = _sys.modules["_lib"]
else:
    _loader = _ilm.SourceFileLoader("_lib", str(_LIB_PATH))
    _spec = _ilu.spec_from_loader("_lib", _loader)
    _lib_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _loader.exec_module(_lib_mod)
    _sys.modules["_lib"] = _lib_mod
    del _loader, _spec

atomic_write = _lib_mod.atomic_write

# Baseline detection windows (seconds).
DEFAULT_STALL_SECONDS = 120
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_POLL_INTERVAL = 5.0

# Exit sentinels.
EXIT_TIMEOUT = 124
EXIT_STALL = 125

# Per-harness stall overrides. Interactive-leaning CLIs go quiet for longer
# stretches while thinking, so they get a wider inactivity window before we
# call it a stall. Harnesses absent from this table use DEFAULT_STALL_SECONDS.
_STALL_DEFAULTS: dict[str, int] = {
    "claude": 300,
    "gemini": 300,
    "cursor-agent": 300,
}

# Fields that carry their own semantics and must never be treated as a plain
# merge scalar overwrite of the transition history.
_STATUS_FILENAME = "status.json"


def stall_default(harness: str | None) -> int:
    """Resolve the stall window for *harness*, falling back to the baseline."""
    if not harness:
        return DEFAULT_STALL_SECONDS
    return _STALL_DEFAULTS.get(harness, DEFAULT_STALL_SECONDS)


def read_status(run_dir: Path) -> dict | None:
    """Return status.json as a dict, or None if missing / empty / corrupt."""
    path = Path(run_dir) / _STATUS_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_status(run_dir: Path, **fields: object) -> dict:
    """Merge *fields* into status.json atomically, tracking state transitions.

    Reads the current status (if any), merges the new fields on top, and - when
    the incoming ``state`` differs from the persisted one - appends a transition
    record to ``transitions``. A ``reason`` field, if supplied, annotates the
    transition and is not stored as a top-level status key.

    Returns the merged dict that was written.
    """
    run_dir = Path(run_dir)
    current = read_status(run_dir) or {}
    reason = fields.pop("reason", None)

    merged: dict = dict(current)
    transitions = list(merged.get("transitions") or [])

    new_state = fields.get("state")
    old_state = current.get("state")
    if new_state is not None and new_state != old_state:
        transitions.append(
            {
                "ts": time.time(),
                "from": old_state,
                "to": new_state,
                "reason": reason,
            }
        )

    merged.update(fields)
    merged["transitions"] = transitions

    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(
        run_dir / _STATUS_FILENAME,
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        mode=None,
    )
    return merged


def _heartbeat(paths: list[Path], started_at: float) -> float:
    """Latest mtime across *paths*; *started_at* before any output exists."""
    latest = started_at
    for p in paths:
        try:
            mtime = os.stat(p).st_mtime
        except (FileNotFoundError, OSError):
            continue
        if mtime > latest:
            latest = mtime
    return latest


def _total_bytes(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += os.stat(p).st_size
        except (FileNotFoundError, OSError):
            continue
    return total


def check_progress(
    paths: list[Path],
    stall_seconds: float,
    timeout_seconds: float,
    started_at: float,
) -> str:
    """Classify progress as "ok" | "stalled" | "timed_out".

    Timeout is the hard cap and wins over stall when both hold: a run past its
    total budget is timed_out even if it emitted output a second ago.
    """
    now = time.time()
    if now - started_at > timeout_seconds:
        return "timed_out"
    if now - _heartbeat(paths, started_at) > stall_seconds:
        return "stalled"
    return "ok"


def kill_process_group(pid: int, grace_seconds: float = 5.0) -> None:
    """SIGTERM the group of *pid*, wait *grace_seconds*, then SIGKILL survivors.

    Silently tolerates an already-gone group. Both ProcessLookupError (ESRCH,
    no such group) and PermissionError (EPERM) count as gone: for our own
    children EPERM from killpg means only un-signalable zombies remain
    (a macOS quirk - it returns EPERM, not ESRCH, once every live member has
    exited). The target must be a process-group leader
    (spawn with start_new_session=True).
    """
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)  # probe liveness
        except (ProcessLookupError, PermissionError):
            return  # group gone (or only zombies remain)
        time.sleep(0.1)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


def supervise(
    proc: subprocess.Popen,
    run_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> int:
    """Watch *proc* until it exits, stalls, or times out. Blocking.

    Returns proc.returncode on natural exit, EXIT_STALL (125) on stall, or
    EXIT_TIMEOUT (124) on timeout. On stall/timeout the process group is killed
    before returning. status.json is updated on every poll.
    """
    run_dir = Path(run_dir)
    paths = [Path(stdout_path), Path(stderr_path)]
    started_at = time.time()

    while True:
        if proc.poll() is not None:
            code = proc.returncode
            write_status(
                run_dir,
                state="done",
                exit_code=code,
                last_output_ts=_heartbeat(paths, started_at),
                output_bytes=_total_bytes(paths),
                reason="process exited",
            )
            return code

        time.sleep(poll_interval)

        write_status(
            run_dir,
            state="running",
            pid=proc.pid,
            last_output_ts=_heartbeat(paths, started_at),
            output_bytes=_total_bytes(paths),
        )

        progress = check_progress(paths, stall_seconds, timeout_seconds, started_at)
        if progress == "ok":
            continue

        sentinel = EXIT_TIMEOUT if progress == "timed_out" else EXIT_STALL
        write_status(run_dir, state="stalled" if progress == "stalled" else "killed",
                     reason=progress)
        kill_process_group(proc.pid)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
        write_status(
            run_dir,
            state="killed",
            exit_code=sentinel,
            output_bytes=_total_bytes(paths),
            reason=f"killed after {progress}",
        )
        return sentinel
