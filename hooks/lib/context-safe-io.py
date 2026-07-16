#!/usr/bin/env python3
"""
Purpose: Own the descriptor-safe wrap lock and project context filesystem
         transactions shared by every DinoStack adapter.

Public API: acquire_lock, inspect_lock, release_lock, read_context,
            commit_context, transact_context, and the sorted-JSON CLI surfaces
            lock acquire/inspect/release and context read/commit/transact.

Upstream deps: Python standard library and a caller-owned absolute project root.

Downstream consumers: hooks/lib/wrap-marker.js, the wrap lock CLI helpers, and
                      adapter context writers migrated by the dependent unit.

Failure modes: rejects symlinks, non-directories, non-regular files, multiply
               linked files, invalid owners, wrong tokens, and replacement
               inodes. Mutations are descriptor-relative and fsynced. A valid
               dead-owner lock may be quarantined and reclaimed; ambiguous
               locks are retained. Context transaction callers may retry.
               Failed publication retains the verified original at its
               randomized hold path.

Performance: local synchronous filesystem I/O. Lock inspection is constant
             work and context operations are linear in the context body size.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime as dt
import errno
import json
import os
import secrets
import stat
import sys
from typing import Any, Dict, Iterator, Optional, Tuple


LOCK_MAGIC = "DINOSTACK_CONTEXT_LOCK"
LOCK_SCHEMA_VERSION = 1
WRAP_HEADER_PREFIX = "# Session Context\n*Written by /wrap"
ACTIVITY_SENTINEL = "\n\n---\n\n## Session Activity\n"
OWNER_NAME = "owner"
LOCK_NAME = "lock"
CONTEXT_NAME = "context.md"
SPILL_NAME = "deferred-activity.jsonl"
MAX_OWNER_BYTES = 16 * 1024
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_SPILL_BYTES = 1024 * 1024
MAX_CLI_INPUT_BYTES = (6 * (MAX_CONTEXT_BYTES + MAX_SPILL_BYTES)) + (64 * 1024)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
RENAME_NOREPLACE_LINUX = 1
RENAME_EXCL_DARWIN = 0x00000004
CONTEXT_COMMIT_RETRIES = 3


class SafeIOError(RuntimeError):
    """A fail-closed path, identity, token, or filesystem validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _json_bytes(value: Dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SafeIOError("invalid-json-value", "value is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_project_root(project_root: str) -> str:
    if not isinstance(project_root, str) or not os.path.isabs(project_root):
        raise SafeIOError("invalid-project-root", "project root must be an absolute path")
    normalized = os.path.normpath(project_root)
    if normalized == os.path.sep:
        raise SafeIOError("invalid-project-root", "filesystem root cannot be a project root")
    return normalized


def _open_dir(name: str, parent_fd: Optional[int] = None) -> int:
    try:
        if parent_fd is None:
            return os.open(name, DIR_FLAGS)
        return os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise SafeIOError("missing-directory", f"directory {name!r} is absent") from exc
    except OSError as exc:
        raise SafeIOError("unsafe-directory", f"refusing directory {name!r}: {exc.strerror}") from exc


def _open_or_create_dir(parent_fd: int, name: str, mode: int = 0o700) -> int:
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise SafeIOError("directory-create-failed", f"cannot create {name!r}: {exc.strerror}") from exc
    return _open_dir(name, parent_fd)


def _open_project_root(project_root: str) -> int:
    """Open the final project inode through pinned canonical parent descriptors."""
    normalized = _validate_project_root(project_root)
    try:
        original_st = os.stat(normalized, follow_symlinks=False)
    except OSError as exc:
        raise SafeIOError("unsafe-directory", f"cannot inspect project root: {exc.strerror}") from exc
    if not stat.S_ISDIR(original_st.st_mode):
        raise SafeIOError("unsafe-directory", "project root must be a real directory")

    canonical_parent = os.path.realpath(os.path.dirname(normalized))
    components = [part for part in canonical_parent.split(os.path.sep) if part]
    components.append(os.path.basename(normalized))
    current_fd = os.open(os.path.sep, DIR_FLAGS)
    try:
        for component in components:
            next_fd = _open_dir(component, current_fd)
            os.close(current_fd)
            current_fd = next_fd
        pinned = os.fstat(current_fd)
        if (pinned.st_dev, pinned.st_ino) != (original_st.st_dev, original_st.st_ino):
            raise SafeIOError("replacement-inode", "project root changed while opening")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


@contextlib.contextmanager
def _project_dirs(project_root: str, create: bool = True) -> Iterator[Tuple[int, int, int]]:
    root_fd = agentic_fd = wrap_fd = -1
    try:
        root_fd = _open_project_root(project_root)
        if create:
            agentic_fd = _open_or_create_dir(root_fd, ".agentic")
            wrap_fd = _open_or_create_dir(agentic_fd, "wrap")
        else:
            agentic_fd = _open_dir(".agentic", root_fd)
            wrap_fd = _open_dir("wrap", agentic_fd)
        yield root_fd, agentic_fd, wrap_fd
    finally:
        for fd in (wrap_fd, agentic_fd, root_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _lstat_at(parent_fd: int, name: str) -> Optional[os.stat_result]:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SafeIOError("stat-failed", f"cannot inspect {name!r}: {exc.strerror}") from exc


def _require_regular_single_link(st: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise SafeIOError("unsafe-file-type", f"{label} must be a regular file")
    if st.st_nlink != 1:
        raise SafeIOError("unsafe-link-count", f"{label} must have link count one")


def _read_all(fd: int, max_bytes: int, label: str) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise SafeIOError("oversized-file", f"{label} exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _open_owner(lock_fd: int) -> Tuple[int, os.stat_result, bytes, Dict[str, Any]]:
    before = _lstat_at(lock_fd, OWNER_NAME)
    if before is None:
        raise SafeIOError("invalid-owner", "lock owner is absent")
    _require_regular_single_link(before, "lock owner")
    try:
        fd = os.open(OWNER_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=lock_fd)
    except OSError as exc:
        raise SafeIOError("invalid-owner", f"cannot open lock owner: {exc.strerror}") from exc
    try:
        st = os.fstat(fd)
        _require_regular_single_link(st, "lock owner")
        if (st.st_dev, st.st_ino) != (before.st_dev, before.st_ino):
            raise SafeIOError("replacement-owner", "lock owner changed while opening")
        raw = _read_all(fd, MAX_OWNER_BYTES, "lock owner")
        try:
            owner = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SafeIOError("invalid-owner", "lock owner is not valid UTF-8 JSON") from exc
        if not isinstance(owner, dict):
            raise SafeIOError("invalid-owner", "lock owner must be a JSON object")
        return fd, st, raw, owner
    except Exception:
        os.close(fd)
        raise


def _validate_owner(owner: Dict[str, Any], lock_st: os.stat_result) -> None:
    required = {
        "acquired_at",
        "lock_dev",
        "lock_ino",
        "magic",
        "owner_kind",
        "owner_pid",
        "schema_version",
        "token",
    }
    if set(owner) != required:
        raise SafeIOError("invalid-owner", "lock owner fields do not match schema")
    if owner.get("magic") != LOCK_MAGIC or owner.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise SafeIOError("invalid-owner", "lock owner magic or schema is invalid")
    if owner.get("lock_dev") != lock_st.st_dev or owner.get("lock_ino") != lock_st.st_ino:
        raise SafeIOError("replacement-inode", "lock owner does not match lock inode")
    token = owner.get("token")
    if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise SafeIOError("invalid-owner", "lock owner token is invalid")
    pid = owner.get("owner_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise SafeIOError("invalid-owner", "lock owner PID is invalid")
    if not isinstance(owner.get("owner_kind"), str) or not owner["owner_kind"]:
        raise SafeIOError("invalid-owner", "lock owner kind is invalid")
    acquired_at = owner.get("acquired_at")
    if not isinstance(acquired_at, str):
        raise SafeIOError("invalid-owner", "lock acquisition time is invalid")
    try:
        dt.datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SafeIOError("invalid-owner", "lock acquisition time is invalid") from exc


def _pid_state(pid: int) -> str:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "permission-denied"
    except OSError:
        return "unknown"
    return "alive"


def _inspect_with_wrap(wrap_fd: int, include_token: bool = False) -> Dict[str, Any]:
    lock_st = _lstat_at(wrap_fd, LOCK_NAME)
    if lock_st is None:
        return {"status": "absent"}
    if not stat.S_ISDIR(lock_st.st_mode):
        return {"status": "invalid", "reason": "lock-is-not-directory"}
    lock_fd = -1
    owner_fd = -1
    try:
        lock_fd = _open_dir(LOCK_NAME, wrap_fd)
        pinned = os.fstat(lock_fd)
        if (pinned.st_dev, pinned.st_ino) != (lock_st.st_dev, lock_st.st_ino):
            return {"status": "invalid", "reason": "replacement-inode"}
        owner_fd, owner_st, raw, owner = _open_owner(lock_fd)
        _validate_owner(owner, pinned)
        result = {
            "status": "held",
            "acquired_at": owner["acquired_at"],
            "lock_dev": pinned.st_dev,
            "lock_ino": pinned.st_ino,
            "owner_kind": owner["owner_kind"],
            "owner_pid": owner["owner_pid"],
            "owner_state": _pid_state(owner["owner_pid"]),
            "owner_bytes": raw,
            "owner_dev": owner_st.st_dev,
            "owner_ino": owner_st.st_ino,
        }
        if include_token:
            result["token"] = owner["token"]
        return result
    except SafeIOError as exc:
        return {"status": "invalid", "reason": exc.code}
    finally:
        if owner_fd >= 0:
            os.close(owner_fd)
        if lock_fd >= 0:
            os.close(lock_fd)


def inspect_lock(project_root: str, include_token: bool = False) -> Dict[str, Any]:
    try:
        with _project_dirs(project_root, create=False) as (_, _, wrap_fd):
            return _inspect_with_wrap(wrap_fd, include_token=include_token)
    except SafeIOError as exc:
        if exc.code == "missing-directory":
            return {"status": "absent"}
        return {"status": "invalid", "reason": exc.code}


def _lock_path_matches(wrap_fd: int, expected_dev: int, expected_ino: int) -> bool:
    st = _lstat_at(wrap_fd, LOCK_NAME)
    return bool(
        st is not None
        and stat.S_ISDIR(st.st_mode)
        and (st.st_dev, st.st_ino) == (expected_dev, expected_ino)
    )


def _verified_lock(wrap_fd: int, token: str) -> Tuple[int, Dict[str, Any], bytes, os.stat_result]:
    lock_fd = _open_dir(LOCK_NAME, wrap_fd)
    owner_fd = -1
    try:
        lock_st = os.fstat(lock_fd)
        if not _lock_path_matches(wrap_fd, lock_st.st_dev, lock_st.st_ino):
            raise SafeIOError("replacement-inode", "lock path changed during verification")
        owner_fd, owner_st, raw, owner = _open_owner(lock_fd)
        _validate_owner(owner, lock_st)
        if not secrets.compare_digest(owner["token"], token):
            raise SafeIOError("wrong-token", "lock token does not match owner")
        os.close(owner_fd)
        owner_fd = -1
        return lock_fd, owner, raw, owner_st
    except Exception:
        if owner_fd >= 0:
            os.close(owner_fd)
        os.close(lock_fd)
        raise


def _remove_verified_lock(wrap_fd: int, token: str, purpose: str) -> bool:
    lock_fd, owner, owner_raw, owner_st = _verified_lock(wrap_fd, token)
    quarantine = f"lock.{purpose}.{secrets.token_hex(16)}"
    try:
        if _lstat_at(wrap_fd, quarantine) is not None:
            raise SafeIOError("quarantine-conflict", "lock quarantine path already exists")
        if not _lock_path_matches(wrap_fd, owner["lock_dev"], owner["lock_ino"]):
            raise SafeIOError("replacement-inode", "lock path changed before quarantine")
        os.rename(LOCK_NAME, quarantine, src_dir_fd=wrap_fd, dst_dir_fd=wrap_fd)
        quarantined_st = _lstat_at(wrap_fd, quarantine)
        if quarantined_st is None or (quarantined_st.st_dev, quarantined_st.st_ino) != (
            owner["lock_dev"], owner["lock_ino"]
        ):
            raise SafeIOError("replacement-inode", "quarantined lock identity changed")
        current_lock_st = os.fstat(lock_fd)
        if (current_lock_st.st_dev, current_lock_st.st_ino) != (
            owner["lock_dev"], owner["lock_ino"]
        ):
            raise SafeIOError("replacement-inode", "pinned lock identity changed")
        verify_fd, verify_st, verify_raw, verify_owner = _open_owner(lock_fd)
        try:
            _validate_owner(verify_owner, current_lock_st)
            if verify_raw != owner_raw or (verify_st.st_dev, verify_st.st_ino) != (
                owner_st.st_dev, owner_st.st_ino
            ):
                raise SafeIOError("replacement-owner", "lock owner changed before removal")
        finally:
            os.close(verify_fd)
        if os.listdir(lock_fd) != [OWNER_NAME]:
            raise SafeIOError("unexpected-lock-content", "lock contains unexpected entries")
        os.unlink(OWNER_NAME, dir_fd=lock_fd)
        os.fsync(lock_fd)
        os.rmdir(quarantine, dir_fd=wrap_fd)
        os.fsync(wrap_fd)
        return True
    finally:
        os.close(lock_fd)


def _reclaim_if_dead(wrap_fd: int) -> bool:
    inspected = _inspect_with_wrap(wrap_fd, include_token=True)
    if inspected.get("status") != "held" or inspected.get("owner_state") != "dead":
        return False
    return _remove_verified_lock(wrap_fd, inspected["token"], "reclaim")


def _acquire_with_wrap(wrap_fd: int, owner_pid: int, owner_kind: str) -> Dict[str, Any]:
    if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
        raise SafeIOError("invalid-owner-pid", "owner PID must be a positive integer")
    if not isinstance(owner_kind, str) or not owner_kind or len(owner_kind) > 128:
        raise SafeIOError("invalid-owner-kind", "owner kind must be a non-empty string")

    for attempt in range(2):
        try:
            os.mkdir(LOCK_NAME, 0o700, dir_fd=wrap_fd)
            os.fsync(wrap_fd)
        except FileExistsError:
            if attempt == 0 and _reclaim_if_dead(wrap_fd):
                continue
            return _inspect_with_wrap(wrap_fd, include_token=False)
        except OSError as exc:
            raise SafeIOError("lock-create-failed", f"cannot create lock: {exc.strerror}") from exc

        lock_fd = -1
        owner_fd = -1
        token = secrets.token_hex(32)
        try:
            lock_fd = _open_dir(LOCK_NAME, wrap_fd)
            lock_st = os.fstat(lock_fd)
            if not _lock_path_matches(wrap_fd, lock_st.st_dev, lock_st.st_ino):
                raise SafeIOError("replacement-inode", "new lock path changed")
            if os.listdir(lock_fd):
                raise SafeIOError("unexpected-lock-content", "new lock is not empty")
            owner = {
                "acquired_at": _utc_now(),
                "lock_dev": lock_st.st_dev,
                "lock_ino": lock_st.st_ino,
                "magic": LOCK_MAGIC,
                "owner_kind": owner_kind,
                "owner_pid": owner_pid,
                "schema_version": LOCK_SCHEMA_VERSION,
                "token": token,
            }
            owner_raw = _json_bytes(owner)
            owner_fd = os.open(
                OWNER_NAME,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=lock_fd,
            )
            owner_st = os.fstat(owner_fd)
            _require_regular_single_link(owner_st, "new lock owner")
            written = os.write(owner_fd, owner_raw)
            if written != len(owner_raw):
                raise SafeIOError("short-write", "lock owner write was incomplete")
            os.fsync(owner_fd)
            os.fsync(lock_fd)
            os.fsync(wrap_fd)
            return {
                "status": "acquired",
                "token": token,
                "lock_dev": lock_st.st_dev,
                "lock_ino": lock_st.st_ino,
                "owner_pid": owner_pid,
                "owner_kind": owner_kind,
                "acquired_at": owner["acquired_at"],
            }
        except Exception:
            if owner_fd >= 0:
                os.close(owner_fd)
                owner_fd = -1
            if lock_fd >= 0:
                try:
                    if _lock_path_matches(wrap_fd, os.fstat(lock_fd).st_dev, os.fstat(lock_fd).st_ino):
                        entries = os.listdir(lock_fd)
                        if entries == [OWNER_NAME]:
                            try:
                                os.unlink(OWNER_NAME, dir_fd=lock_fd)
                            except OSError:
                                pass
                        if not os.listdir(lock_fd):
                            os.rmdir(LOCK_NAME, dir_fd=wrap_fd)
                            os.fsync(wrap_fd)
                except OSError:
                    pass
            raise
        finally:
            if owner_fd >= 0:
                os.close(owner_fd)
            if lock_fd >= 0:
                os.close(lock_fd)
    raise SafeIOError("lock-create-failed", "lock acquisition did not converge")


def acquire_lock(project_root: str, owner_kind: str, owner_pid: Optional[int] = None) -> Dict[str, Any]:
    pid = os.getpid() if owner_pid is None else owner_pid
    with _project_dirs(project_root, create=True) as (_, _, wrap_fd):
        return _acquire_with_wrap(wrap_fd, pid, owner_kind)


def release_lock(project_root: str, token: str) -> Dict[str, Any]:
    if not isinstance(token, str) or not token:
        raise SafeIOError("missing-token", "lock release requires the acquisition token")
    if inspect_lock(project_root, include_token=False).get("status") == "absent":
        return {"status": "absent", "released": False}
    with _project_dirs(project_root, create=False) as (_, _, wrap_fd):
        if _lstat_at(wrap_fd, LOCK_NAME) is None:
            return {"status": "absent", "released": False}
        removed = _remove_verified_lock(wrap_fd, token, "release")
        return {"status": "released", "released": removed}


def _read_context_at(agentic_fd: int) -> Tuple[str, Optional[Tuple[int, int]]]:
    st = _lstat_at(agentic_fd, CONTEXT_NAME)
    if st is None:
        return "", None
    _require_regular_single_link(st, "context.md")
    try:
        fd = os.open(
            CONTEXT_NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=agentic_fd,
        )
    except OSError as exc:
        raise SafeIOError("context-open-failed", f"cannot open context.md: {exc.strerror}") from exc
    try:
        pinned = os.fstat(fd)
        _require_regular_single_link(pinned, "context.md")
        if (pinned.st_dev, pinned.st_ino) != (st.st_dev, st.st_ino):
            raise SafeIOError("replacement-inode", "context.md changed while opening")
        raw = _read_all(fd, MAX_CONTEXT_BYTES, "context.md")
        try:
            return raw.decode("utf-8"), (pinned.st_dev, pinned.st_ino)
        except UnicodeDecodeError as exc:
            raise SafeIOError("invalid-context", "context.md is not valid UTF-8") from exc
    finally:
        os.close(fd)


def _verify_context_identity(agentic_fd: int, identity: Optional[Tuple[int, int]]) -> None:
    current = _lstat_at(agentic_fd, CONTEXT_NAME)
    if identity is None:
        if current is not None:
            raise SafeIOError("replacement-inode", "context.md appeared before commit")
        return
    if current is None or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
        raise SafeIOError("replacement-inode", "context.md changed before commit")
    if (current.st_dev, current.st_ino) != identity:
        raise SafeIOError("replacement-inode", "context.md inode changed before commit")


def _rename_noreplace(
    src_dir_fd: int,
    src_name: str,
    dst_dir_fd: int,
    dst_name: str,
) -> None:
    """Descriptor-relative atomic rename that refuses an existing destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    src = os.fsencode(src_name)
    dst = os.fsencode(dst_name)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise SafeIOError(
                "noreplace-unsupported",
                "renameat2(RENAME_NOREPLACE) is unavailable",
            )
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            src_dir_fd,
            src,
            dst_dir_fd,
            dst,
            RENAME_NOREPLACE_LINUX,
        )
    elif sys.platform == "darwin":
        rename = getattr(libc, "renameatx_np", None)
        if rename is None:
            raise SafeIOError(
                "noreplace-unsupported",
                "renameatx_np(RENAME_EXCL) is unavailable",
            )
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            src_dir_fd,
            src,
            dst_dir_fd,
            dst,
            RENAME_EXCL_DARWIN,
        )
    else:
        raise SafeIOError(
            "noreplace-unsupported",
            f"atomic no-replace rename is unsupported on {sys.platform}",
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(error_number, os.strerror(error_number), dst_name)
    if error_number == errno.ENOENT:
        raise FileNotFoundError(error_number, os.strerror(error_number), src_name)
    raise OSError(error_number, os.strerror(error_number), src_name, dst_name)


def _verified_regular_identity_at(
    parent_fd: int,
    name: str,
    label: str,
) -> Tuple[int, int]:
    before = _lstat_at(parent_fd, name)
    if before is None:
        raise SafeIOError("replacement-inode", f"{label} disappeared")
    _require_regular_single_link(before, label)
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise SafeIOError(
            "replacement-inode",
            f"cannot pin {label}: {exc.strerror}",
        ) from exc
    try:
        pinned = os.fstat(fd)
        _require_regular_single_link(pinned, label)
        if (pinned.st_dev, pinned.st_ino) != (before.st_dev, before.st_ino):
            raise SafeIOError("replacement-inode", f"{label} changed while opening")
        return pinned.st_dev, pinned.st_ino
    finally:
        os.close(fd)


def _restore_displaced_context(agentic_fd: int, hold_name: str) -> None:
    try:
        _rename_noreplace(agentic_fd, hold_name, agentic_fd, CONTEXT_NAME)
    except FileExistsError as exc:
        raise SafeIOError(
            "replacement-preserved",
            f"concurrent context replacement retained at {hold_name!r}",
        ) from exc
    except FileNotFoundError as exc:
        raise SafeIOError(
            "replacement-inode",
            "displaced context disappeared before restoration",
        ) from exc
    os.fsync(agentic_fd)


def _publish_context_no_clobber(
    agentic_fd: int,
    temp_name: str,
    expected_identity: Optional[Tuple[int, int]],
) -> None:
    """
    Publish without overwriting a path that changed after verification.

    An absent destination is handled directly with no-replace rename. For an
    existing destination, first move the current entry to a unique no-replace
    hold, pin and verify that displaced inode, then publish the temp with a
    second no-replace rename. A raced replacement is restored and retained.
    """
    if expected_identity is None:
        try:
            _rename_noreplace(agentic_fd, temp_name, agentic_fd, CONTEXT_NAME)
        except FileExistsError as exc:
            raise SafeIOError(
                "replacement-inode",
                "context.md appeared during no-clobber publication",
            ) from exc
        except FileNotFoundError as exc:
            raise SafeIOError(
                "replacement-inode",
                "context temp disappeared before publication",
            ) from exc
        os.fsync(agentic_fd)
        return

    hold_name = f".context.md.hold.{secrets.token_hex(24)}"
    hold_contains_original = False
    try:
        try:
            _rename_noreplace(agentic_fd, CONTEXT_NAME, agentic_fd, hold_name)
        except FileExistsError as exc:
            raise SafeIOError(
                "quarantine-conflict",
                "context publication hold unexpectedly exists",
            ) from exc
        except FileNotFoundError as exc:
            raise SafeIOError(
                "replacement-inode",
                "context.md disappeared before publication",
            ) from exc
        os.fsync(agentic_fd)

        displaced_identity = _verified_regular_identity_at(
            agentic_fd,
            hold_name,
            "displaced context.md",
        )
        if displaced_identity != expected_identity:
            _restore_displaced_context(agentic_fd, hold_name)
            hold_name = ""
            raise SafeIOError(
                "replacement-inode",
                "context.md changed in the verification-to-publication window",
            )
        hold_contains_original = True

        try:
            _rename_noreplace(agentic_fd, temp_name, agentic_fd, CONTEXT_NAME)
        except FileExistsError as exc:
            raise SafeIOError(
                "replacement-preserved",
                f"context.md reappeared; verified original retained at {hold_name!r}",
            ) from exc
        except FileNotFoundError as exc:
            _restore_displaced_context(agentic_fd, hold_name)
            hold_name = ""
            raise SafeIOError(
                "replacement-inode",
                "context temp disappeared before publication",
            ) from exc

        os.unlink(hold_name, dir_fd=agentic_fd)
        hold_name = ""
        os.fsync(agentic_fd)
    except Exception:
        if hold_name and hold_contains_original:
            current = _lstat_at(agentic_fd, CONTEXT_NAME)
            if current is None:
                try:
                    _restore_displaced_context(agentic_fd, hold_name)
                    hold_name = ""
                except SafeIOError:
                    pass
        raise


def _commit_at(agentic_fd: int, wrap_fd: int, token: str, body: str) -> Dict[str, Any]:
    if not isinstance(body, str):
        raise SafeIOError("invalid-body", "context body must be a string")
    body_raw = body.encode("utf-8")
    if len(body_raw) > MAX_CONTEXT_BYTES:
        raise SafeIOError("oversized-context", "context body exceeds size limit")
    lock_fd, _, _, _ = _verified_lock(wrap_fd, token)
    temp_name = f".context.md.tmp.{secrets.token_hex(24)}"
    temp_fd = -1
    try:
        _, identity = _read_context_at(agentic_fd)
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=agentic_fd,
        )
        temp_st = os.fstat(temp_fd)
        _require_regular_single_link(temp_st, "context temp")
        written = os.write(temp_fd, body_raw)
        if written != len(body_raw):
            raise SafeIOError("short-write", "context write was incomplete")
        os.fsync(temp_fd)
        _verify_context_identity(agentic_fd, identity)
        if not _lock_path_matches(wrap_fd, os.fstat(lock_fd).st_dev, os.fstat(lock_fd).st_ino):
            raise SafeIOError("replacement-inode", "lock changed before context commit")
        _publish_context_no_clobber(agentic_fd, temp_name, identity)
        temp_name = ""
        return {"status": "written", "written": True, "bytes": len(body_raw)}
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=agentic_fd)
            except OSError:
                pass
        os.close(lock_fd)


def read_context(project_root: str, token: str) -> Dict[str, Any]:
    with _project_dirs(project_root, create=False) as (_, agentic_fd, wrap_fd):
        lock_fd, _, _, _ = _verified_lock(wrap_fd, token)
        try:
            content, identity = _read_context_at(agentic_fd)
            return {"status": "read", "content": content, "identity": identity}
        finally:
            os.close(lock_fd)


def commit_context(project_root: str, token: str, body: str) -> Dict[str, Any]:
    with _project_dirs(project_root, create=False) as (_, agentic_fd, wrap_fd):
        return _commit_at(agentic_fd, wrap_fd, token, body)


def _append_spill(wrap_fd: int, record: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise SafeIOError("invalid-spill", "spill record must be an object")
    raw = _json_bytes(record)
    if len(raw) > MAX_SPILL_BYTES:
        raise SafeIOError("oversized-spill", "spill record exceeds size limit")
    try:
        fd = os.open(
            SPILL_NAME,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=wrap_fd,
        )
    except OSError as exc:
        raise SafeIOError("spill-open-failed", f"cannot open spill log: {exc.strerror}") from exc
    try:
        st = os.fstat(fd)
        _require_regular_single_link(st, "spill log")
        written = os.write(fd, raw)
        if written != len(raw):
            raise SafeIOError("short-write", "spill append was incomplete")
        os.fsync(fd)
        os.fsync(wrap_fd)
        return {"status": "spilled", "spilled": True, "bytes": len(raw)}
    finally:
        os.close(fd)


def _merge_context(existing: str, request: Dict[str, Any]) -> str:
    mode = request.get("mode", "replace")
    fallback = request.get("body")
    if not isinstance(fallback, str):
        raise SafeIOError("invalid-body", "transaction body must be a string")
    if mode == "replace":
        return fallback
    if mode != "coexist":
        raise SafeIOError("invalid-mode", "transaction mode must be replace or coexist")
    activity = request.get("activity_block")
    if not isinstance(activity, str):
        raise SafeIOError("invalid-activity", "coexist transaction needs an activity block")
    if not existing.startswith(WRAP_HEADER_PREFIX):
        return fallback
    sentinel_index = existing.find(ACTIVITY_SENTINEL)
    wrap_base = existing[:sentinel_index] if sentinel_index >= 0 else existing.rstrip()
    if activity.startswith(ACTIVITY_SENTINEL):
        activity = activity[len(ACTIVITY_SENTINEL) :]
    return wrap_base + ACTIVITY_SENTINEL + activity


def transact_context(
    project_root: str,
    request: Dict[str, Any],
    owner_kind: str = "context-writer",
    owner_pid: Optional[int] = None,
) -> Dict[str, Any]:
    pid = os.getpid() if owner_pid is None else owner_pid
    with _project_dirs(project_root, create=True) as (_, agentic_fd, wrap_fd):
        acquired = _acquire_with_wrap(wrap_fd, pid, owner_kind)
        if acquired.get("status") != "acquired":
            spill = request.get("spillover_record")
            if not isinstance(spill, dict):
                return {"status": "contended", "written": False, "spilled": False}
            result = _append_spill(wrap_fd, spill)
            result["written"] = False
            return result
        token = acquired["token"]
        try:
            for attempt in range(CONTEXT_COMMIT_RETRIES):
                existing, _ = _read_context_at(agentic_fd)
                body = _merge_context(existing, request)
                try:
                    return _commit_at(agentic_fd, wrap_fd, token, body)
                except SafeIOError as exc:
                    if (
                        exc.code != "replacement-inode"
                        or attempt + 1 >= CONTEXT_COMMIT_RETRIES
                    ):
                        raise
            raise SafeIOError("replacement-inode", "context transaction did not converge")
        finally:
            try:
                _remove_verified_lock(wrap_fd, token, "release")
            except SafeIOError:
                pass


def _emit(value: Dict[str, Any]) -> None:
    safe = dict(value)
    safe.pop("owner_bytes", None)
    sys.stdout.write(json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n")


def _read_request() -> Dict[str, Any]:
    try:
        raw = sys.stdin.buffer.read(MAX_CLI_INPUT_BYTES + 1)
    except OSError as exc:
        raise SafeIOError("invalid-input", "cannot read JSON request") from exc
    if len(raw) > MAX_CLI_INPUT_BYTES:
        raise SafeIOError("oversized-input", "stdin JSON request exceeds size limit")
    try:
        text = raw.decode("utf-8")
        request = text.lstrip()
        value, end = json.JSONDecoder().raw_decode(request)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeIOError("invalid-input", "stdin must contain one JSON object") from exc
    if request[end:].strip():
        raise SafeIOError("invalid-input", "stdin contains trailing data")
    if not isinstance(value, dict):
        raise SafeIOError("invalid-input", "stdin must contain one JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context-safe-io.py")
    parser.add_argument("--project-root", required=True)
    top = parser.add_subparsers(dest="surface", required=True)

    lock = top.add_parser("lock")
    lock_sub = lock.add_subparsers(dest="action", required=True)
    acquire = lock_sub.add_parser("acquire")
    acquire.add_argument("--owner-pid", required=True, type=int)
    acquire.add_argument("--owner-kind", required=True)
    lock_sub.add_parser("inspect")
    release = lock_sub.add_parser("release")
    release.add_argument("--token", required=True)

    context = top.add_parser("context")
    context_sub = context.add_subparsers(dest="action", required=True)
    read = context_sub.add_parser("read")
    read.add_argument("--token", required=True)
    commit = context_sub.add_parser("commit")
    commit.add_argument("--token", required=True)
    transact = context_sub.add_parser("transact")
    transact.add_argument("--owner-pid", required=True, type=int)
    transact.add_argument("--owner-kind", default="context-writer")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.surface == "lock" and args.action == "acquire":
            if args.owner_pid != os.getppid():
                raise SafeIOError("owner-pid-mismatch", "CLI owner PID must equal the helper parent PID")
            _emit(acquire_lock(args.project_root, args.owner_kind, args.owner_pid))
        elif args.surface == "lock" and args.action == "inspect":
            _emit(inspect_lock(args.project_root, include_token=False))
        elif args.surface == "lock" and args.action == "release":
            _emit(release_lock(args.project_root, args.token))
        elif args.surface == "context" and args.action == "read":
            _emit(read_context(args.project_root, args.token))
        elif args.surface == "context" and args.action == "commit":
            _emit(commit_context(args.project_root, args.token, _read_request().get("body")))
        elif args.surface == "context" and args.action == "transact":
            if args.owner_pid != os.getppid():
                raise SafeIOError("owner-pid-mismatch", "CLI owner PID must equal the helper parent PID")
            _emit(transact_context(args.project_root, _read_request(), args.owner_kind, args.owner_pid))
        else:
            raise SafeIOError("invalid-command", "unsupported command")
        return 0
    except SafeIOError as exc:
        _emit({"ok": False, "error": exc.code, "message": str(exc)})
        return 1
    except Exception as exc:  # Defensive CLI boundary, never expose a traceback to hooks.
        _emit({"ok": False, "error": "unexpected-error", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
