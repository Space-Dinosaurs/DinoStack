#!/usr/bin/env python3
"""
Internal shared helpers for dinostack bin/ CLIs.
NOT a public CLI - do not invoke directly.

Purpose: Provide two cross-process primitives reused by multiple CLIs:
  1. acquire_exclusive_lock - fcntl.LOCK_EX context manager with sleep-retry
     until timeout; used for multi-process coordination (e.g. flush lock).
  2. atomic_write - write content to a pid-suffixed <path>.tmp.<pid> sibling
     then rename; cleans up OUR OWN pid-suffixed .tmp on failure; optional
     chmod mode. Atomic for a single writer only - the pid suffix exists to
     stop two concurrent writers from colliding on one staging path.

Public API:
  acquire_exclusive_lock(lock_path, timeout=30.0)
    Context manager. Opens lock_path as a Python file object (buffered), acquires
    fcntl.LOCK_EX | LOCK_NB via a 0.1s sleep-retry loop until timeout, yields the
    file object, releases (LOCK_UN) and closes on exit. Raises RuntimeError on
    timeout so callers can distinguish "another holder" from a filesystem error.
    Caller is responsible for ensuring lock_path and its parent exist before entry.

  atomic_write(path, content, mode=0o600)
    Writes str content to a pid-suffixed <path>.tmp.<pid> sibling then renames
    into place. When mode is not None, applies os.chmod to the tmp file before
    rename. On any exception, unlinks OUR OWN pid-suffixed tmp file
    (missing_ok) and re-raises - never a shared/fixed name another concurrent
    caller could own. path must be a pathlib.Path.

  resolve_claude_config_dir()
    Returns the active harness config dir as an absolute pathlib.Path,
    honoring the same env-var precedence as bin/ds-identity's
    PROFILE_CONFIG_DIR_ENV: AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR >
    CODEX_HOME > PI_CODING_AGENT_DIR, first non-empty wins. Falls back to
    ~/.claude when none is set. A `~`-prefixed value is expanded, and the
    result is absolutized via os.path.abspath() (round-2 fix: kept in sync
    with the Node sibling, hooks/lib/config-dir.js's
    resolveClaudeConfigDir(), which now applies the same two steps). This
    is a READ-ONLY lookup (transcript discovery), not a write target -
    unlike ds-identity's _profile_config_dir(), it deliberately does NOT
    apply a $HOME-containment check or symlink-component check; those
    guards exist there to stop an identity WRITE from escaping the user
    tree, which does not apply to a read-only glob/stat lookup here.

Upstream deps: Python 3 stdlib only (contextlib, fcntl, os, time, pathlib).

Downstream consumers: bin/ds-config (atomic_write), bin/ds-defer (both
                      helpers), bin/ds-feedback (both helpers),
                      bin/ds-learning-shard (both helpers),
                      bin/ds-migrate (atomic_write), bin/ds-tracker
                      (atomic_write), bin/ds-parse-subagent-usage
                      (resolve_claude_config_dir). bin/ds-identity does NOT
                      use this module - it ships its own
                      _atomic_write_identity, its own lock contextmanager,
                      and its own (containment-checked) _profile_config_dir.

Failure modes:
  acquire_exclusive_lock: raises RuntimeError("lock timeout") after timeout seconds
    with no lock held; the underlying fd is always closed before raising.
    OS errors opening the lock file propagate to the caller unchanged (the file
    must exist before calling; existence is the caller's responsibility).
  atomic_write: on any write/chmod/rename failure, removes OUR OWN pid-suffixed
    .tmp.<pid> file (missing_ok semantics) and re-raises the original exception.
    The destination file is never partially written. The .tmp.<pid> suffix is
    appended to the full filename (e.g. identity.yml -> identity.yml.tmp.12345)
    to stay in the same directory and on the same filesystem as the
    destination, AND to guarantee two concurrent callers never share one
    staging path (single-writer atomicity only - see rename semantics; the
    pid suffix prevents cross-process tmp collision/cleanup, not a
    last-write-wins race on the final destination itself).
  resolve_claude_config_dir: never raises. An unset/blank/whitespace-only env
    var is treated as absent; the first non-blank value wins even if the
    resulting path does not exist on disk - callers must handle a
    nonexistent config dir themselves (e.g. by falling through to a glob).
    `~` expansion and abspath absolutization happen unconditionally on the
    winning value; neither can raise (os.path.expanduser/abspath are pure
    string operations that never touch the filesystem).

Performance: Standard. acquire_exclusive_lock sleeps 0.1s per retry (~300 retries
  over 30s); atomic_write is a single write + fsync-less rename (same filesystem).
  resolve_claude_config_dir is a handful of os.environ.get() calls - negligible.
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


# Harness-standard config-dir env vars, in detection precedence order. Kept
# in sync with bin/ds-identity's PROFILE_CONFIG_DIR_ENV (same precedence,
# same four vars) - see that file's comment for why each one is listed.
CONFIG_DIR_ENV: tuple[str, ...] = (
    "AGENTIC_CONFIG_DIR",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "PI_CODING_AGENT_DIR",
)


def resolve_claude_config_dir() -> Path:
    """Return the active harness config dir, or ~/.claude when none is set.

    Read-only lookup: no $HOME-containment or symlink check (contrast with
    bin/ds-identity's _profile_config_dir(), which guards a WRITE target).
    Round-2 fix: applies os.path.abspath() in addition to expanduser() so
    a relative env-var value absolutizes the same way the Node sibling
    (hooks/lib/config-dir.js's resolveClaudeConfigDir()) now does.
    """
    for var in CONFIG_DIR_ENV:
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(os.path.abspath(os.path.expanduser(raw)))
    return Path(os.path.expanduser("~/.claude"))


def atomic_write(path: Path, content: str, mode: int | None = 0o600) -> None:
    """Write content to path atomically via a .tmp sibling.

    Steps:
      1. Write content to <path>.tmp.<pid> (text, utf-8).
      2. If mode is not None, chmod <path>.tmp.<pid> to mode.
      3. Rename <path>.tmp.<pid> -> path.

    On any failure, unlinks OUR OWN pid-suffixed <path>.tmp.<pid> (missing_ok)
    and re-raises. The destination file is never partially overwritten.
    Atomic for a single writer only: the pid suffix guarantees two concurrent
    callers never share one staging path, but it does not add cross-process
    locking around the final rename - a last-write-wins race on the
    destination itself is still possible if two writers target the same path.

    The tmp filename is suffixed with the current pid so two concurrent
    callers (e.g. two ds-identity invocations) never share one staging
    path - a fixed tmp name would let one process's crash-cleanup unlink
    another process's still-in-flight write, or let two writers collide on
    the same tmp file.

    path.parent must already exist (no mkdir here - callers handle that).
    """
    tmp = path.parent / (path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(content, encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
