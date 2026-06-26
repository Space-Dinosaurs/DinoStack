#!/usr/bin/env python3
"""
Internal shared helpers for agentic-engineering bin/ CLIs.
NOT a public CLI - do not invoke directly.

Purpose: Provide two cross-process primitives reused by multiple CLIs:
  1. acquire_exclusive_lock - fcntl.LOCK_EX context manager with sleep-retry
     until timeout; used for multi-process coordination (e.g. flush lock).
  2. atomic_write - write content to <path>.tmp then rename; cleans up .tmp on
     failure; optional chmod mode.

Public API:
  acquire_exclusive_lock(lock_path, timeout=30.0)
    Context manager. Opens lock_path as a Python file object (buffered), acquires
    fcntl.LOCK_EX | LOCK_NB via a 0.1s sleep-retry loop until timeout, yields the
    file object, releases (LOCK_UN) and closes on exit. Raises RuntimeError on
    timeout so callers can distinguish "another holder" from a filesystem error.
    Caller is responsible for ensuring lock_path and its parent exist before entry.

  atomic_write(path, content, mode=0o600)
    Writes str content to path.with_suffix('<ext>.tmp') then renames into place.
    When mode is not None, applies os.chmod to the tmp file before rename.
    On any exception, unlinks the tmp file (missing_ok) and re-raises.
    path must be a pathlib.Path.

Upstream deps: Python 3 stdlib only (contextlib, fcntl, os, time, pathlib).

Downstream consumers: bin/agentic-identity (both helpers),
                      bin/agentic-migrate (atomic_write).

Failure modes:
  acquire_exclusive_lock: raises RuntimeError("lock timeout") after timeout seconds
    with no lock held; the underlying fd is always closed before raising.
    OS errors opening the lock file propagate to the caller unchanged (the file
    must exist before calling; existence is the caller's responsibility).
  atomic_write: on any write/chmod/rename failure, removes the .tmp file
    (missing_ok semantics) and re-raises the original exception. The destination
    file is never partially written. The .tmp suffix is appended to the full
    filename (e.g. identity.yml -> identity.yml.tmp) to stay in the same
    directory and on the same filesystem as the destination.

Performance: Standard. acquire_exclusive_lock sleeps 0.1s per retry (~300 retries
  over 30s); atomic_write is a single write + fsync-less rename (same filesystem).
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


@contextmanager
def acquire_exclusive_lock(
    lock_path: Path,
    timeout: float = 30.0,
) -> Generator[object, None, None]:
    """Context manager: acquire fcntl.LOCK_EX on lock_path.

    Opens lock_path as a Python file object ('r' mode - the file must already
    exist), retries with 0.1s sleep until timeout, yields the file object,
    then releases LOCK_UN and closes on exit.

    Raises RuntimeError on timeout (lock not acquired; fd is closed before
    raising). OS errors on open propagate unchanged.

    Usage:
        with acquire_exclusive_lock(lock_path) as fd:
            # critical section
            ...
    """
    fd = open(lock_path, "r")  # noqa: SIM115 - intentional: file stays open for flock
    try:
        deadline = time.monotonic() + timeout
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)

        if not acquired:
            fd.close()
            raise RuntimeError(f"acquire_exclusive_lock: timeout after {timeout}s on {lock_path}")

        try:
            yield fd
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    except RuntimeError:
        raise
    except BaseException:
        # Covers exceptions from open() after fd is assigned but before acquired.
        # If fd was opened but flock not yet attempted (shouldn't happen in normal
        # flow but guard anyway), close it.
        try:
            fd.close()
        except Exception:
            pass
        raise


def atomic_write(path: Path, content: str, mode: int | None = 0o600) -> None:
    """Write content to path atomically via a .tmp sibling.

    Steps:
      1. Write content to <path>.tmp (text, utf-8).
      2. If mode is not None, chmod <path>.tmp to mode.
      3. Rename <path>.tmp -> path.

    On any failure, unlinks <path>.tmp (missing_ok) and re-raises. The
    destination file is never partially overwritten.

    path.parent must already exist (no mkdir here - callers handle that).
    """
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
