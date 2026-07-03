#!/usr/bin/env python3
"""
Internal shared helpers for agentic-engineering bin/ CLIs.
NOT a public CLI - do not invoke directly.

Purpose: Provide two cross-process primitives reused by multiple CLIs:
  1. acquire_exclusive_lock - fcntl.LOCK_EX context manager with sleep-retry
     until timeout; used for multi-process coordination (e.g. flush lock).
  2. atomic_write - write content to a uniquely-named temp sibling (mkstemp)
     then os.replace into place; cleans up the temp file on failure; optional
     chmod mode.

Public API:
  acquire_exclusive_lock(lock_path, timeout=30.0)
    Context manager. Opens lock_path as a Python file object (buffered), acquires
    fcntl.LOCK_EX | LOCK_NB via a 0.1s sleep-retry loop until timeout, yields the
    file object, releases (LOCK_UN) and closes on exit. Raises RuntimeError on
    timeout so callers can distinguish "another holder" from a filesystem error.
    Caller is responsible for ensuring lock_path and its parent exist before entry.

  atomic_write(path, content, mode=0o600)
    Writes str content to a uniquely-named temp sibling (tempfile.mkstemp in
    path.parent, created 0o600) then os.replace into place. When mode is not
    None, applies os.chmod to the temp file before the replace. On any
    exception, unlinks the temp file (missing_ok) and re-raises. The temp name
    is randomized, so there is no predictable "<path>.tmp" sibling to collide
    on or pre-plant as a symlink. path must be a pathlib.Path.

Upstream deps: Python 3 stdlib only (contextlib, fcntl, os, tempfile, time, pathlib).

Downstream consumers: bin/agentic-identity (both helpers),
                      bin/agentic-migrate (atomic_write).

Failure modes:
  acquire_exclusive_lock: raises RuntimeError("lock timeout") after timeout seconds
    with no lock held; the underlying fd is always closed before raising.
    OS errors opening the lock file propagate to the caller unchanged (the file
    must exist before calling; existence is the caller's responsibility).
  atomic_write: on any write/chmod/replace failure, removes the temp file
    (missing_ok semantics) and re-raises the original exception. The destination
    file is never partially written. The temp file is created by mkstemp in the
    destination's directory (same filesystem) with a randomized name
    (e.g. identity.yml.<rand>.tmp), so concurrent writers cannot collide and a
    same-user attacker cannot pre-plant a predictable symlink target.

Performance: Standard. acquire_exclusive_lock sleeps 0.1s per retry (~300 retries
  over 30s); atomic_write is a single write + fsync-less rename (same filesystem).
"""

from __future__ import annotations

import fcntl
import os
import stat
import tempfile
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
    """Write content to path atomically via a unique temp sibling.

    Steps:
      1. ``tempfile.mkstemp`` a uniquely-named temp file in path.parent
         (``<name>.<rand>.tmp``), created 0o600 so the pre-chmod window is not
         world-readable.
      2. Write content (text, utf-8).
      3. If mode is not None, chmod the temp file to mode.
      4. ``os.replace`` the temp file -> path (atomic, overwrites).

    On any failure, unlinks the temp file (missing_ok) and re-raises. The
    destination file is never partially overwritten. Using mkstemp avoids the
    predictable ``<path>.tmp`` sibling name, closing the concurrent-writer
    collision and same-user symlink-TOCTOU races.

    path.parent must already exist (no mkdir here - callers handle that).
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if mode is not None:
            os.chmod(tmp, mode)
        else:
            # Preserve the destination's existing perms (race-free); fall back
            # to 0o644 for brand-new files, matching the old write_text umask
            # default so mode=None callers (e.g. agentic-migrate) do not
            # regress to mkstemp's owner-only 0o600.
            try:
                os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
            except FileNotFoundError:
                os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
