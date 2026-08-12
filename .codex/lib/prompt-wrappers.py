#!/usr/bin/env python3
"""
Purpose: Generate repository-owned legacy Codex prompt wrappers from canonical commands.

Public API: ``build --repo ROOT [--output DIR --state-dir DIR]``, ``check`` with
            the same path options, ``inventory --repo ROOT``, and
            ``paths [--config-dir DIR]``.

Upstream deps: the exact direct symlink inventory beneath .codex/commands and
               standard-library filesystem, hashing, JSON, and flock support.

Downstream consumers: .codex/build.sh, scripts/check-codex-skill-sync.sh,
                      pre-commit, and scripts/test/test_codex_skills.py.

Failure modes: fails closed on unsafe topology, unowned or drifted generated
               bytes, malformed recovery state, substitution races, or an
               ambiguous/unexpandable configuration root. Interrupted transactions
               retain ignored evidence and are recovered before new input is read;
               repository rename evidence is schema-closed and bounded.

Performance: linear in the direct command inventory and generated wrappers.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, cast

SCHEMA = 1
PROMPT_MAGIC = "DINOSTACK_CODEX_PROMPT_ROOT"
STATE_MAGIC = "DINOSTACK_CODEX_PROMPT_STATE"
MANIFEST_MAGIC = "DINOSTACK_CODEX_PROMPT_MANIFEST"
RUNTIME_MAGIC = "DINOSTACK_CODEX_PROMPT_RUNTIME"
TRANSACTION_MAGIC = "DINOSTACK_CODEX_PROMPT_TRANSACTION"
PRIVATE_MAGIC = "DINOSTACK_CODEX_PROMPT_PRIVATE_ROOT"
PROMPT_MARKER = ".dinostack-generated-root.json"
STATE_MARKER = ".dinostack-generated-state.json"
PRIVATE_MARKER = ".dinostack-prompt-private-root.json"
MANIFEST_NAME = "manifest.json"
COMMANDS_REL = ".codex/commands"
PROMPTS_REL = ".codex/prompts"
STATE_REL = ".codex/prompt-generation-state"
RUNTIME_REL = ".agentic/codex-prompt-generation"
DEFERRED_COMMAND = "ds-wrap-deferred"
NAME_RE = re.compile(r"^ds-[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
OWNER_EVIDENCE_RE = re.compile(r"^owner-([0-9a-f]{64})(?:-[0-9a-f]{32})?$")
MAX_BASENAME = 128
MAX_INVENTORY = 512
MAX_CONTROL_BYTES = 1024 * 1024
MAX_WRAPPER_BYTES = 16 * 1024
MAX_EVIDENCE_TRANSACTIONS = 64
MAX_OWNER_EVIDENCE = 64
MAX_OUTPUT_ENTRIES = MAX_INVENTORY + 1
MAX_STATE_ENTRIES = 2
MAX_RUNTIME_BINDINGS = 64
MAX_TRANSACTION_ENTRIES = 4
MAX_TRANSACTION_BLOBS = MAX_INVENTORY + 1
MAX_TRANSACTION_EVIDENCE = (MAX_INVENTORY * 2) + 2
INITIAL_OWNER_STAGE = ".owner-initial.stage"
OWNER_WRITE_CHUNK = 128
UID = os.getuid()


class PromptError(RuntimeError):
    """A deterministic prompt-wrapper generation or validation failure."""


@dataclass(frozen=True)
class RootIdentity:
    path: Path
    dev: int
    ino: int
    mode: int
    uid: int


@dataclass(frozen=True)
class Paths:
    repo: Path
    output: Path
    state: Path
    runtime: Path
    canonical: bool


@dataclass(frozen=True)
class Desired:
    wrappers: dict[str, bytes]
    prompt_marker: bytes
    state_marker: bytes
    manifest: bytes
    inventory_hash: str


@dataclass(frozen=True)
class MutationPlan:
    stage: str
    old_evidence: str | None
    placeholder_evidence: str | None
    evidence_root: RootIdentity
    fault_prefix: str


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _closed(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PromptError(f"{label} has an invalid closed schema")
    return value


def _current_schema(value: object) -> bool:
    return type(value) is int and value == SCHEMA


def _load_json(data: bytes, label: str) -> object:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptError(f"{label} is not valid UTF-8 canonical JSON: {exc}") from exc
    if canonical_json(value) != data:
        raise PromptError(f"{label} does not use exact canonical JSON bytes")
    return value


def _safe_regular_info(info: os.stat_result, label: str, *, mode: int | None = None) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != UID
        or info.st_nlink != 1
        or info.st_mode & 0o022
        or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
    ):
        raise PromptError(f"{label} must be a current-user single-link safe regular file")


def _read_fd(
    fd: int,
    label: str,
    *,
    exact_mode: int | None = None,
    max_bytes: int = MAX_CONTROL_BYTES,
) -> tuple[bytes, os.stat_result]:
    opened = os.fstat(fd)
    _safe_regular_info(opened, label, mode=exact_mode)
    if opened.st_size > max_bytes:
        raise PromptError(f"{label} exceeds its byte ceiling")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise PromptError(f"{label} exceeds its byte ceiling")
    after = os.fstat(fd)
    if (
        (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise PromptError(f"{label} changed while reading")
    return data, opened


def _root_identity(path: Path, label: str, *, exact_mode: int | None = None) -> RootIdentity:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise PromptError(f"cannot inspect {label}: {exc}") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != UID
        or info.st_mode & 0o022
        or (exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode)
    ):
        raise PromptError(f"{label} must be a real current-user safe directory")
    return RootIdentity(path, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid)


def _reject_symlink_ancestors(base: Path, target: Path, label: str) -> None:
    try:
        relative = target.relative_to(base)
    except ValueError as exc:
        raise PromptError(f"{label} escapes its trusted base") from exc
    current = base
    for part in relative.parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise PromptError(f"cannot inspect {label} ancestor {current}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise PromptError(f"{label} has a symlinked ancestor: {current}")


def _revalidate(root: RootIdentity, label: str) -> None:
    current = _root_identity(root.path, label, exact_mode=root.mode)
    if (current.dev, current.ino, current.uid) != (root.dev, root.ino, root.uid):
        raise PromptError(f"{label} was substituted during generation")


def _open_root(root: RootIdentity, label: str) -> int:
    _revalidate(root, label)
    try:
        fd = os.open(
            root.path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise PromptError(f"cannot pin {label}: {exc}") from exc
    opened = os.fstat(fd)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino, opened.st_uid)
        != (root.dev, root.ino, root.uid)
        or stat.S_IMODE(opened.st_mode) != root.mode
    ):
        os.close(fd)
        raise PromptError(f"{label} changed while pinning its descriptor")
    return fd


def _read_child(
    dir_fd: int,
    name: str,
    label: str,
    *,
    exact_mode: int,
    max_bytes: int = MAX_CONTROL_BYTES,
) -> tuple[bytes, os.stat_result]:
    try:
        before = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        _safe_regular_info(before, label, mode=exact_mode)
        fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=dir_fd,
        )
    except OSError as exc:
        raise PromptError(f"cannot safely open {label}: {exc}") from exc
    try:
        data, opened = _read_fd(
            fd,
            label,
            exact_mode=exact_mode,
            max_bytes=max_bytes,
        )
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise PromptError(f"{label} changed while opening")
        return data, opened
    finally:
        os.close(fd)


def _read_optional_child(
    dir_fd: int,
    name: str,
    label: str,
    *,
    exact_mode: int,
    max_bytes: int = MAX_CONTROL_BYTES,
) -> tuple[bytes, os.stat_result] | None:
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return _read_child(
        dir_fd,
        name,
        label,
        exact_mode=exact_mode,
        max_bytes=max_bytes,
    )


def _direct_entries(
    dir_fd: int,
    label: str,
    *,
    limit: int,
    overflow_error: str | None = None,
) -> dict[str, os.stat_result]:
    entries: dict[str, os.stat_result] = {}
    try:
        with os.scandir(dir_fd) as iterator:
            for entry in iterator:
                if len(entries) >= limit:
                    raise PromptError(
                        overflow_error or f"{label} exceeds its entry ceiling"
                    )
                if entry.name in entries:
                    raise PromptError(f"{label} contains duplicate direct entries")
                entries[entry.name] = entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise PromptError(f"cannot enumerate {label}: {exc}") from exc
    return entries


def _rename_noreplace(dir_fd: int, source: str, destination: str) -> None:
    _rename_noreplace_between(dir_fd, source, dir_fd, destination)


def _rename_noreplace_between(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    result = -1
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(
            source_fd,
            ctypes.c_char_p(source_bytes),
            destination_fd,
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(0x00000004),
        )
    elif hasattr(libc, "renameat2"):
        result = libc.renameat2(
            source_fd,
            ctypes.c_char_p(source_bytes),
            destination_fd,
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(1),
        )
    else:
        raise PromptError(
            "atomic no-replace rename is unavailable; refusing before mutation"
        )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EXDEV:
            raise PromptError("atomic prompt publication crossed a filesystem boundary")
        raise PromptError(
            f"atomic no-replace publication failed: {os.strerror(error)}"
        )


def _rename_exchange(dir_fd: int, left: str, right: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(
            dir_fd,
            ctypes.c_char_p(left_bytes),
            dir_fd,
            ctypes.c_char_p(right_bytes),
            ctypes.c_uint(0x00000002),
        )
    elif hasattr(libc, "renameat2"):
        result = libc.renameat2(
            dir_fd,
            ctypes.c_char_p(left_bytes),
            dir_fd,
            ctypes.c_char_p(right_bytes),
            ctypes.c_uint(2),
        )
    else:
        raise PromptError("atomic exchange is unavailable on this platform")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EXDEV:
            raise PromptError("atomic prompt exchange crossed a filesystem boundary")
        raise PromptError(f"atomic prompt exchange failed: {os.strerror(error)}")


def _mkdir_private(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    _root_identity(path, str(path), exact_mode=0o700)


def _ensure_private_parent(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        _root_identity(path, str(path))
    else:
        _root_identity(path, str(path), exact_mode=0o700)


def _mkdir_generated(path: Path) -> None:
    try:
        os.mkdir(path, 0o755)
    except FileExistsError:
        pass
    _root_identity(path, str(path))


def _fsync_root(root: RootIdentity, label: str) -> None:
    fd = _open_root(root, label)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _create_leaf(
    root: RootIdentity,
    name: str,
    data: bytes,
    mode: int,
    label: str,
) -> tuple[int, os.stat_result]:
    dir_fd = _open_root(root, str(root.path))
    fd = -1
    try:
        fd = os.open(
            name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            mode,
            dir_fd=dir_fd,
        )
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        opened = os.fstat(fd)
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not _same_inode(opened, current):
            raise PromptError(f"{label} was substituted while being created")
        os.fsync(dir_fd)
        return fd, opened
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise
    finally:
        os.close(dir_fd)


def _read_optional_pinned(
    root: RootIdentity,
    name: str,
    label: str,
    *,
    mode: int,
    max_bytes: int,
) -> tuple[bytes, os.stat_result, int] | None:
    dir_fd = _open_root(root, str(root.path))
    fd = -1
    try:
        try:
            fd = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dir_fd,
            )
        except FileNotFoundError:
            return None
        data, opened = _read_fd(
            fd,
            label,
            exact_mode=mode,
            max_bytes=max_bytes,
        )
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not _same_inode(opened, current):
            raise PromptError(f"{label} changed while being pinned")
        result_fd = fd
        fd = -1
        return data, opened, result_fd
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(dir_fd)


def _validate_owner_evidence(root: RootIdentity) -> dict[str, os.stat_result]:
    runtime = _root_identity(
        root.path.parent,
        "prompt runtime root for owner evidence",
        exact_mode=0o700,
    )
    runtime_fd = _open_root(runtime, "prompt runtime root for owner evidence")
    try:
        evidence_info = os.stat(
            root.path.name,
            dir_fd=runtime_fd,
            follow_symlinks=False,
        )
        if (evidence_info.st_dev, evidence_info.st_ino) != (root.dev, root.ino):
            raise PromptError("prompt runtime evidence root changed while binding owner")
        active_data, _ = _read_child(
            runtime_fd,
            "owner.json",
            "active prompt runtime owner",
            exact_mode=0o600,
        )
    finally:
        os.close(runtime_fd)
    active = _closed(
        _load_json(active_data, "active prompt runtime owner"),
        {
            "binding", "magic", "prompts_root", "repo_dev", "repo_ino",
            "repo_realpath", "schema_version", "state_root",
        },
        "active prompt runtime owner",
    )
    _validate_owner_record(
        active,
        "active prompt runtime owner",
        require_canonical_children=False,
    )
    active_identity = (
        active["binding"],
        active["repo_dev"],
        active["repo_ino"],
    )
    runtime_name = root.path.parent.name
    if runtime_name == "runtime":
        active_mode = "private"
    elif (
        isinstance(active["binding"], str)
        and runtime_name == active["binding"]
        and HEX_RE.fullmatch(runtime_name) is not None
    ):
        active_mode = "canonical"
    else:
        raise PromptError(
            "active prompt runtime owner does not match runtime topology"
        )
    _validate_owner_evidence_paths(active, root, active_mode)
    dir_fd = _open_root(root, "prompt runtime evidence root")
    try:
        entries = _direct_entries(
            dir_fd,
            "prompt runtime evidence root",
            limit=MAX_OWNER_EVIDENCE,
            overflow_error="prompt runtime owner evidence exceeds its bounded cap",
        )
        for name, info in entries.items():
            match = OWNER_EVIDENCE_RE.fullmatch(name)
            _safe_regular_info(info, f"prompt runtime owner evidence {name}", mode=0o600)
            if match is None:
                raise PromptError("prompt runtime owner evidence contains an invalid entry")
            data, _ = _read_child(
                dir_fd,
                name,
                f"prompt runtime owner evidence {name}",
                exact_mode=0o600,
            )
            if digest(data) != match.group(1):
                raise PromptError("prompt runtime owner evidence digest mismatch")
            value = _closed(
                _load_json(data, f"prompt runtime owner evidence {name}"),
                {
                    "binding", "magic", "prompts_root", "repo_dev", "repo_ino",
                    "repo_realpath", "schema_version", "state_root",
                },
                f"prompt runtime owner evidence {name}",
            )
            _validate_owner_record(
                value,
                f"prompt runtime owner evidence {name}",
                require_canonical_children=False,
            )
            _validate_owner_evidence_paths(value, root, active_mode)
            if (
                value["binding"],
                value["repo_dev"],
                value["repo_ino"],
            ) != active_identity:
                raise PromptError(
                    "prompt runtime owner evidence does not match active identity"
                )
        return entries
    finally:
        os.close(dir_fd)


def _quarantine_leaf(
    source_root: RootIdentity,
    source_name: str,
    evidence_root: RootIdentity,
    evidence_name: str,
    expected: bytes,
    mode: int,
    *,
    max_bytes: int,
    fault_prefix: str,
) -> None:
    destination_fd = _open_root(evidence_root, str(evidence_root.path))
    source_fd = _open_root(source_root, str(source_root.path))
    pinned_fd = -1
    try:
        destination = _read_optional_child(
            destination_fd,
            evidence_name,
            f"retained evidence {evidence_name}",
            exact_mode=mode,
            max_bytes=max_bytes,
        )
        source = _read_optional_pinned(
            source_root,
            source_name,
            f"quarantine source {source_name}",
            mode=mode,
            max_bytes=max_bytes,
        )
        if source is None:
            if destination is None or destination[0] != expected:
                raise PromptError(f"missing retained evidence for {source_name}")
            return
        data, opened, pinned_fd = source
        if data != expected:
            raise PromptError(f"ambiguous quarantine state for {source_name}")
        owner_evidence_entries: dict[str, os.stat_result] | None = None
        if fault_prefix == "owner":
            owner_evidence_entries = _validate_owner_evidence(evidence_root)
        if destination is not None:
            if destination[0] != expected or fault_prefix != "owner":
                raise PromptError(f"ambiguous quarantine state for {source_name}")
            assert owner_evidence_entries is not None
            if len(owner_evidence_entries) >= MAX_OWNER_EVIDENCE:
                raise PromptError("prompt runtime owner evidence cap reached")
            evidence_name = f"owner-{digest(expected)}-{secrets.token_hex(16)}"
        elif (
            owner_evidence_entries is not None
            and len(owner_evidence_entries) >= MAX_OWNER_EVIDENCE
        ):
            raise PromptError("prompt runtime owner evidence cap reached")
        _rename_noreplace_between(
            source_fd,
            source_name,
            destination_fd,
            evidence_name,
        )
        _fault(f"{fault_prefix}-after-quarantine-rename")
        published = os.stat(
            evidence_name,
            dir_fd=destination_fd,
            follow_symlinks=False,
        )
        if not _same_inode(opened, published):
            try:
                _rename_noreplace_between(
                    destination_fd,
                    evidence_name,
                    source_fd,
                    source_name,
                )
            except Exception as exc:
                raise PromptError(
                    f"cannot restore substituted quarantine source {source_name}"
                ) from exc
            raise PromptError(f"quarantine source was substituted: {source_name}")
        if os.fstat(pinned_fd).st_nlink != 1:
            raise PromptError(f"retained evidence link count changed: {source_name}")
        os.fsync(destination_fd)
        os.fsync(source_fd)
    finally:
        if pinned_fd >= 0:
            os.close(pinned_fd)
        os.close(source_fd)
        os.close(destination_fd)


def _atomic_bytes(
    root: RootIdentity,
    name: str,
    data: bytes,
    mode: int,
    *,
    expected: bytes | None | object = ...,
    plan: MutationPlan | None = None,
) -> None:
    if "/" in name or name in {"", ".", ".."}:
        raise PromptError(f"atomic output is not a direct child: {name!r}")
    if expected is ...:
        raise PromptError("atomic output requires an explicit ownership expectation")
    dir_fd = _open_root(root, str(root.path))
    target_fd = -1
    stage_fd = -1
    try:
        target = _read_optional_pinned(
            root,
            name,
            f"atomic target {name}",
            mode=mode,
            max_bytes=max(MAX_CONTROL_BYTES, len(data), len(expected or b"")),
        )
        if target is not None:
            target_data, target_info, target_fd = target
            if target_data == data:
                if plan is not None and plan.old_evidence is not None:
                    if expected is None:
                        raise PromptError(f"completed replacement lacks old bytes: {name}")
                    _quarantine_leaf(
                        root,
                        plan.stage,
                        plan.evidence_root,
                        plan.old_evidence,
                        expected,
                        mode,
                        max_bytes=max(MAX_CONTROL_BYTES, len(expected)),
                        fault_prefix=plan.fault_prefix,
                    )
                return
            if expected is None or target_data != expected:
                raise PromptError(f"atomic target has unknown content: {name}")
            if plan is None:
                raise PromptError("replacement requires journaled mutation artifacts")
        elif expected is not None:
            raise PromptError(f"owned output disappeared before replacement: {name}")

        if plan is None:
            try:
                created_fd, _ = _create_leaf(
                    root,
                    name,
                    data,
                    mode,
                    f"atomic output {name}",
                )
            except FileExistsError:
                adopted = _read_optional_pinned(
                    root,
                    name,
                    f"concurrent atomic output {name}",
                    mode=mode,
                    max_bytes=max(MAX_CONTROL_BYTES, len(data)),
                )
                if adopted is None:
                    raise PromptError(
                        f"concurrent atomic output disappeared: {name}"
                    )
                adopted_data, _, adopted_fd = adopted
                try:
                    if adopted_data != data:
                        raise PromptError(
                            f"concurrent atomic output has unknown content: {name}"
                        )
                finally:
                    os.close(adopted_fd)
            else:
                os.close(created_fd)
            return
        stage = _read_optional_pinned(
            root,
            plan.stage,
            f"atomic stage {plan.stage}",
            mode=mode,
            max_bytes=max(MAX_CONTROL_BYTES, len(data)),
        )
        if stage is None:
            stage_fd, stage_info = _create_leaf(
                root,
                plan.stage,
                data,
                mode,
                f"atomic stage {plan.stage}",
            )
        else:
            stage_data, stage_info, stage_fd = stage
            if stage_data != data:
                raise PromptError(f"journaled stage has unknown content: {plan.stage}")
        _fault(f"{plan.fault_prefix}-after-stage")
        if expected is None:
            _rename_noreplace(dir_fd, plan.stage, name)
            published = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            if not _same_inode(published, stage_info):
                try:
                    _rename_noreplace(dir_fd, name, plan.stage)
                except Exception as exc:
                    raise PromptError(f"cannot restore substituted creation: {name}") from exc
                raise PromptError(f"journaled stage was substituted during creation: {name}")
            _fault(f"{plan.fault_prefix}-after-publish")
        else:
            assert target is not None
            _rename_exchange(dir_fd, plan.stage, name)
            _fault(f"{plan.fault_prefix}-after-exchange")
            try:
                published_data, published_info = _read_child(
                    dir_fd,
                    name,
                    f"published output {name}",
                    exact_mode=mode,
                    max_bytes=max(MAX_CONTROL_BYTES, len(data)),
                )
                held_data, held_info = _read_child(
                    dir_fd,
                    plan.stage,
                    f"held output {name}",
                    exact_mode=mode,
                    max_bytes=max(MAX_CONTROL_BYTES, len(expected)),
                )
                if (
                    published_data != data
                    or not _same_inode(published_info, stage_info)
                    or held_data != expected
                    or not _same_inode(held_info, target_info)
                ):
                    raise PromptError(f"replacement identity mismatch: {name}")
            except Exception:
                _rename_exchange(dir_fd, plan.stage, name)
                raise
            _fault(f"{plan.fault_prefix}-before-quarantine")
            assert plan.old_evidence is not None
            _quarantine_leaf(
                root,
                plan.stage,
                plan.evidence_root,
                plan.old_evidence,
                expected,
                mode,
                max_bytes=max(MAX_CONTROL_BYTES, len(expected)),
                fault_prefix=plan.fault_prefix,
            )
        os.fsync(dir_fd)
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if stage_fd >= 0:
            os.close(stage_fd)
        os.close(dir_fd)


def _unlink_owned(
    root: RootIdentity,
    name: str,
    expected: bytes,
    *,
    plan: MutationPlan | None = None,
) -> None:
    if "/" in name or name in {"", ".", ".."}:
        raise PromptError(f"prune output is not a direct child: {name!r}")
    if plan is None or plan.old_evidence is None or plan.placeholder_evidence is None:
        raise PromptError("prune requires journaled mutation artifacts")
    dir_fd = _open_root(root, str(root.path))
    pinned_fds: list[int] = []

    def pin_mode(
        child: str,
        mode: int,
        label: str,
        max_bytes: int,
    ) -> tuple[bytes, os.stat_result, int] | None:
        try:
            info = os.stat(child, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
            return None
        result = _read_optional_pinned(
            root,
            child,
            label,
            mode=mode,
            max_bytes=max_bytes,
        )
        if result is not None:
            pinned_fds.append(result[2])
        return result

    try:
        target = pin_mode(name, 0o644, f"prune target {name}", MAX_WRAPPER_BYTES)
        target_placeholder = pin_mode(
            name,
            0o600,
            f"prune tombstone {name}",
            0,
        )
        hold_old = pin_mode(
            plan.stage,
            0o644,
            f"prune hold {plan.stage}",
            MAX_WRAPPER_BYTES,
        )
        hold_placeholder = pin_mode(
            plan.stage,
            0o600,
            f"prune placeholder {plan.stage}",
            0,
        )

        if target is not None and target[0] == expected:
            if hold_old is not None:
                raise PromptError(f"prune hold unexpectedly contains old bytes: {name}")
            if hold_placeholder is None:
                placeholder_fd, placeholder_info = _create_leaf(
                    root,
                    plan.stage,
                    b"",
                    0o600,
                    f"prune placeholder {plan.stage}",
                )
                pinned_fds.append(placeholder_fd)
            else:
                _, placeholder_info, placeholder_fd = hold_placeholder
            _fault(f"{plan.fault_prefix}-after-placeholder")
            _rename_exchange(dir_fd, plan.stage, name)
            _fault(f"{plan.fault_prefix}-after-exchange")
            try:
                held, held_info = _read_child(
                    dir_fd,
                    plan.stage,
                    f"prune hold {plan.stage}",
                    exact_mode=0o644,
                    max_bytes=MAX_WRAPPER_BYTES,
                )
                tombstone, tombstone_info = _read_child(
                    dir_fd,
                    name,
                    f"prune tombstone {name}",
                    exact_mode=0o600,
                    max_bytes=0,
                )
                if (
                    held != expected
                    or not _same_inode(held_info, target[1])
                    or tombstone != b""
                    or not _same_inode(tombstone_info, placeholder_info)
                ):
                    raise PromptError(f"prune exchange identity mismatch: {name}")
            except Exception:
                _rename_exchange(dir_fd, plan.stage, name)
                _quarantine_leaf(
                    root,
                    plan.stage,
                    plan.evidence_root,
                    plan.placeholder_evidence,
                    b"",
                    0o600,
                    max_bytes=0,
                    fault_prefix=plan.fault_prefix,
                )
                raise
        elif target is not None:
            raise PromptError(f"prune target has unknown content: {name}")
        elif target_placeholder is not None:
            if target_placeholder[0] != b"" or hold_old is None or hold_old[0] != expected:
                raise PromptError(f"prune crash state has unknown content: {name}")
        elif hold_old is None:
            _quarantine_leaf(
                root,
                name,
                plan.evidence_root,
                plan.placeholder_evidence,
                b"",
                0o600,
                max_bytes=0,
                fault_prefix=plan.fault_prefix,
            )
            _quarantine_leaf(
                root,
                plan.stage,
                plan.evidence_root,
                plan.old_evidence,
                expected,
                0o644,
                max_bytes=MAX_WRAPPER_BYTES,
                fault_prefix=plan.fault_prefix,
            )
            return

        _quarantine_leaf(
            root,
            name,
            plan.evidence_root,
            plan.placeholder_evidence,
            b"",
            0o600,
            max_bytes=0,
            fault_prefix=plan.fault_prefix,
        )
        _fault(f"{plan.fault_prefix}-after-tombstone")
        _quarantine_leaf(
            root,
            plan.stage,
            plan.evidence_root,
            plan.old_evidence,
            expected,
            0o644,
            max_bytes=MAX_WRAPPER_BYTES,
            fault_prefix=plan.fault_prefix,
        )
        os.fsync(dir_fd)
    finally:
        for pinned_fd in set(pinned_fds):
            os.close(pinned_fd)
        os.close(dir_fd)


def _repo(path: str) -> Path:
    candidate = _expand_user_path(path, "repository root")
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        real = candidate.resolve(strict=True)
    except OSError as exc:
        raise PromptError(f"invalid repository root: {exc}") from exc
    _root_identity(real, "repository root")
    if not (real / ".codex").is_dir() or not (real / "content/commands").is_dir():
        raise PromptError(f"not a DinoStack repository root: {real}")
    return real


def _expand_user_path(path: str, label: str) -> Path:
    try:
        return Path(path).expanduser()
    except (OSError, RuntimeError) as exc:
        raise PromptError(f"cannot expand {label}") from exc


def _resolve_option(path: str, repo: Path, label: str) -> Path:
    candidate = _expand_user_path(path, label)
    if not candidate.is_absolute():
        candidate = repo / candidate
    return Path(os.path.abspath(candidate))


def _private_container(output: Path, state: Path) -> Path:
    if output.parent != state.parent or output == state:
        raise PromptError("arbitrary output and state must be distinct direct children of one private container")
    container = output.parent
    root = _root_identity(
        container,
        "arbitrary private container",
        exact_mode=0o700,
    )
    dir_fd = _open_root(root, "arbitrary private container")
    try:
        marker, _ = _read_child(
            dir_fd,
            PRIVATE_MARKER,
            "arbitrary private-container nonce",
            exact_mode=0o600,
        )
    finally:
        os.close(dir_fd)
    value = _closed(_load_json(marker, "arbitrary private-container nonce"), {"magic", "nonce", "schema_version"}, "arbitrary private-container nonce")
    if value["magic"] != PRIVATE_MAGIC or not _current_schema(value["schema_version"]) or not isinstance(value["nonce"], str) or not HEX_RE.fullmatch(value["nonce"]):
        raise PromptError("arbitrary private-container nonce has invalid values")
    return container


def resolve_paths(repo: Path, output_arg: str | None, state_arg: str | None) -> Paths:
    canonical = output_arg is None and state_arg is None
    if (output_arg is None) != (state_arg is None):
        raise PromptError("--output and --state-dir must be supplied together")
    if canonical:
        output = repo / PROMPTS_REL
        state = repo / STATE_REL
        binding = digest(f"{os.lstat(repo).st_dev}:{os.lstat(repo).st_ino}".encode())
        runtime = repo / RUNTIME_REL / binding
        for label, target in (
            ("prompt output root", output),
            ("prompt state root", state),
            ("prompt runtime root", runtime),
        ):
            _reject_symlink_ancestors(repo, target, label)
    else:
        output = _resolve_option(output_arg or "", repo, "prompt output root")
        state = _resolve_option(state_arg or "", repo, "prompt state root")
        container = _private_container(output, state)
        runtime = container / "runtime"
    return Paths(repo, output, state, runtime, canonical)


def _inventory(repo: Path) -> list[str]:
    commands = repo / COMMANDS_REL
    _reject_symlink_ancestors(repo, commands, "Codex command mirror")
    root = _root_identity(commands, "Codex command mirror")
    names: list[str] = []
    try:
        with os.scandir(commands) as entries:
            for entry in entries:
                if len(names) >= MAX_INVENTORY:
                    raise PromptError(
                        "Codex command inventory exceeds its entry ceiling"
                    )
                name = entry.name
                if (
                    name.startswith(".")
                    or not name.endswith(".md")
                    or len(name) > MAX_BASENAME + 3
                    or any(ord(char) < 0x20 or ord(char) > 0x7E for char in name)
                ):
                    raise PromptError(f"invalid direct command entry: {name!r}")
                basename = name[:-3]
                if not NAME_RE.fullmatch(basename):
                    raise PromptError(f"invalid command basename: {basename!r}")
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise PromptError(
                        f"cannot inspect command mirror {name}: {exc}"
                    ) from exc
                if not stat.S_ISLNK(info.st_mode):
                    raise PromptError(
                        f"command mirror must be an exact relative symlink: {name}"
                    )
                expected = f"../../content/commands/{name}"
                try:
                    target = os.readlink(entry.path)
                except OSError as exc:
                    raise PromptError(
                        f"cannot read command mirror symlink {name}: {exc}"
                    ) from exc
                if target != expected:
                    raise PromptError(f"command mirror target mismatch for {name}")
                source = repo / "content/commands" / name
                try:
                    source_info = os.lstat(source)
                except OSError as exc:
                    raise PromptError(
                        f"canonical command target missing for {name}: {exc}"
                    ) from exc
                if not stat.S_ISREG(source_info.st_mode):
                    raise PromptError(
                        f"canonical command target is not a regular file: {name}"
                    )
                names.append(basename)
    except OSError as exc:
        raise PromptError(f"cannot enumerate Codex command mirror: {exc}") from exc
    _revalidate(root, "Codex command mirror")
    if len(names) != len(set(names)):
        raise PromptError("duplicate command basenames")
    names.sort()
    return [name for name in names if name != DEFERRED_COMMAND]


def _wrapper(name: str) -> bytes:
    text = (
        "---\n"
        f"description: Run DinoStack workflow {name}\n"
        'argument-hint: "[arguments]"\n'
        "---\n"
        "Use the `$dinostack` skill. From that loaded skill's physical root, "
        f"read and execute the canonical `commands/{name}.md` workflow with these arguments:\n\n"
        "$ARGUMENTS\n"
    )
    return text.encode()


def _validate_wrapper(name: str, data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptError(f"wrapper {name} is not UTF-8: {exc}") from exc
    if text != _wrapper(name).decode():
        raise PromptError(f"wrapper {name} does not use exact generated bytes")
    token = f"commands/{name}.md"
    if text.count(token) != 1 or text.count("$ARGUMENTS") != 1:
        raise PromptError(f"wrapper {name} does not have exact resource and argument cardinality")
    neutral = text.replace(token, "commands/NEUTRAL_RESOURCE.md", 1)
    aliases = {name.removeprefix("ds-"), "brief", "wrap"}
    forbidden = (
        re.search(r"/ds-[a-z0-9-]+", neutral)
        or re.search(r"/prompts?:[^\s`]*", neutral)
        or re.search(r"```(?:bash|sh|shell)", neutral)
        or re.search(r"(?:^|\s)/(?:Users|home|tmp|var)/", neutral)
        or any(f"/{alias}" in neutral for alias in aliases)
        or any(
            f"commands/{other}.md" in neutral
            for other in re.findall(r"ds-[a-z0-9-]+", neutral)
        )
    )
    if forbidden:
        raise PromptError(f"wrapper {name} contains a forbidden legacy alias or body copy")


def _binding() -> dict[str, str]:
    return {
        "commands_root": COMMANDS_REL,
        "kind": "canonical",
        "prompts_root": PROMPTS_REL,
        "state_root": STATE_REL,
    }


def desired(repo: Path) -> Desired:
    names = _inventory(repo)
    wrappers = {f"{name}.md": _wrapper(name) for name in names}
    for name, data in wrappers.items():
        _validate_wrapper(name[:-3], data)
    entries = [
        {
            "basename": name[:-3],
            "output": name,
            "sha256": digest(data),
            "source": name,
        }
        for name, data in sorted(wrappers.items())
    ]
    manifest = canonical_json(
        {
            "binding": _binding(),
            "entries": entries,
            "magic": MANIFEST_MAGIC,
            "schema_version": SCHEMA,
        }
    )
    prompt_marker = canonical_json(
        {"binding": _binding(), "magic": PROMPT_MAGIC, "schema_version": SCHEMA}
    )
    state_marker = canonical_json(
        {"binding": _binding(), "magic": STATE_MAGIC, "schema_version": SCHEMA}
    )
    inventory_hash = digest(
        canonical_json([str(entry["basename"]) for entry in entries])
    )
    return Desired(wrappers, prompt_marker, state_marker, manifest, inventory_hash)


def _validate_marker(data: bytes, expected: bytes, label: str) -> None:
    value = _closed(
        _load_json(data, label),
        {"binding", "magic", "schema_version"},
        label,
    )
    if not _current_schema(value["schema_version"]):
        raise PromptError(f"{label} schema version mismatch")
    if data != expected:
        raise PromptError(f"{label} binding or schema mismatch")


def _parse_manifest(data: bytes) -> dict[str, object]:
    value = _closed(
        _load_json(data, "prompt manifest"),
        {"binding", "entries", "magic", "schema_version"},
        "prompt manifest",
    )
    if value["magic"] != MANIFEST_MAGIC or not _current_schema(value["schema_version"]):
        raise PromptError("prompt manifest magic or schema mismatch")
    if value["binding"] != _binding():
        raise PromptError("prompt manifest binding mismatch")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_INVENTORY:
        raise PromptError("prompt manifest entries must be a list")
    previous = ""
    for raw in entries:
        entry = _closed(raw, {"basename", "output", "sha256", "source"}, "prompt manifest entry")
        basename, output, source, sha = (
            entry["basename"],
            entry["output"],
            entry["source"],
            entry["sha256"],
        )
        if (
            not isinstance(basename, str)
            or not NAME_RE.fullmatch(basename)
            or len(basename) > MAX_BASENAME
            or basename == DEFERRED_COMMAND
            or output != f"{basename}.md"
            or source != f"{basename}.md"
            or not isinstance(sha, str)
            or not HEX_RE.fullmatch(sha)
            or output <= previous
            or "/" in output
        ):
            raise PromptError("prompt manifest entry correlation, order, or digest is invalid")
        previous = output
    return value


def _owned_manifest(paths: Paths, *, required: bool) -> tuple[bytes | None, dict[str, object] | None]:
    root = _root_identity(paths.state, "prompt state root")
    dir_fd = _open_root(root, "prompt state root")
    try:
        result = _read_optional_child(
            dir_fd,
            MANIFEST_NAME,
            "prompt manifest",
            exact_mode=0o644,
        )
    finally:
        os.close(dir_fd)
    if result is None:
        if required:
            raise PromptError("prompt manifest is missing")
        return None, None
    data, _ = result
    return data, _parse_manifest(data)


def _entry_map(manifest: dict[str, object] | None) -> dict[str, str]:
    if manifest is None:
        return {}
    entries = cast(list[dict[str, object]], manifest["entries"])
    return {
        str(entry["output"]): str(entry["sha256"])
        for entry in entries
    }


def _validate_owned_tree(paths: Paths, manifest: dict[str, object] | None) -> None:
    if not paths.output.exists() and manifest is None:
        return
    output_root = _root_identity(paths.output, "prompt output root")
    state_root = _root_identity(paths.state, "prompt state root")
    output_fd = _open_root(output_root, "prompt output root")
    state_fd = _open_root(state_root, "prompt state root")
    try:
        prompt_marker, _ = _read_child(
            output_fd,
            PROMPT_MARKER,
            "prompt root marker",
            exact_mode=0o644,
        )
        state_marker, _ = _read_child(
            state_fd,
            STATE_MARKER,
            "prompt state marker",
            exact_mode=0o644,
        )
        expected_markers = desired(paths.repo)
        _validate_marker(
            prompt_marker,
            expected_markers.prompt_marker,
            "prompt root marker",
        )
        _validate_marker(
            state_marker,
            expected_markers.state_marker,
            "prompt state marker",
        )
        expected_outputs = {PROMPT_MARKER, *_entry_map(manifest)}
        expected_state = (
            {STATE_MARKER, MANIFEST_NAME}
            if manifest is not None
            else {STATE_MARKER}
        )
        output_entries = set(
            _direct_entries(
                output_fd,
                "prompt output root",
                limit=MAX_OUTPUT_ENTRIES,
            )
        )
        state_entries = set(
            _direct_entries(
                state_fd,
                "prompt state root",
                limit=MAX_STATE_ENTRIES,
            )
        )
        if output_entries != expected_outputs:
            raise PromptError(
                "prompt output root has unmanifested, missing, or unexpected entries"
            )
        if state_entries != expected_state:
            raise PromptError("prompt state root has unexpected or missing entries")
        for name, expected_hash in _entry_map(manifest).items():
            data, _ = _read_child(
                output_fd,
                name,
                f"manifested wrapper {name}",
                exact_mode=0o644,
                max_bytes=MAX_WRAPPER_BYTES,
            )
            if digest(data) != expected_hash:
                raise PromptError(f"manifested wrapper digest mismatch: {name}")
    finally:
        os.close(state_fd)
        os.close(output_fd)


def _validate_output_against_manifest(
    paths: Paths,
    manifest: dict[str, object],
) -> None:
    root = _root_identity(paths.output, "prompt output root")
    expected = {PROMPT_MARKER, *_entry_map(manifest)}
    dir_fd = _open_root(root, "prompt output root")
    try:
        actual = set(
            _direct_entries(
                dir_fd,
                "prompt output root",
                limit=MAX_OUTPUT_ENTRIES,
            )
        )
        if actual != expected:
            raise PromptError(
                "prompt output root does not match the transaction manifest"
            )
        for name, expected_hash in _entry_map(manifest).items():
            data, _ = _read_child(
                dir_fd,
                name,
                f"transaction output {name}",
                exact_mode=0o644,
                max_bytes=MAX_WRAPPER_BYTES,
            )
            if digest(data) != expected_hash:
                raise PromptError(
                    f"transaction output digest mismatch before manifest publication: {name}"
                )
    finally:
        os.close(dir_fd)


def _validate_exact_wrappers(paths: Paths, want: Desired) -> None:
    root = _root_identity(paths.output, "prompt output root")
    dir_fd = _open_root(root, "prompt output root")
    try:
        for name, expected in want.wrappers.items():
            actual, _ = _read_child(
                dir_fd,
                name,
                f"generated wrapper {name}",
                exact_mode=0o644,
                max_bytes=MAX_WRAPPER_BYTES,
            )
            if actual != expected:
                raise PromptError(f"generated prompt wrapper drift: {name}")
    finally:
        os.close(dir_fd)


def _runtime_owner(paths: Paths) -> dict[str, object]:
    repo_info = os.lstat(paths.repo)
    return {
        "binding": digest(f"{repo_info.st_dev}:{repo_info.st_ino}".encode()),
        "magic": RUNTIME_MAGIC,
        "prompts_root": str(paths.output),
        "repo_dev": repo_info.st_dev,
        "repo_ino": repo_info.st_ino,
        "repo_realpath": str(paths.repo),
        "schema_version": SCHEMA,
        "state_root": str(paths.state),
    }


def _validate_owner_record(
    value: dict[str, object],
    label: str,
    *,
    require_canonical_children: bool = True,
) -> None:
    repo_dev = value["repo_dev"]
    repo_ino = value["repo_ino"]
    repo_realpath = value["repo_realpath"]
    prompts_root = value["prompts_root"]
    state_root = value["state_root"]
    paths_are_safe = all(
        isinstance(path, str)
        and "\x00" not in path
        and Path(path).is_absolute()
        and os.path.normpath(path) == path
        for path in (repo_realpath, prompts_root, state_root)
    )
    if (
        value["magic"] != RUNTIME_MAGIC
        or not _current_schema(value["schema_version"])
        or type(repo_dev) is not int
        or repo_dev < 0
        or type(repo_ino) is not int
        or repo_ino < 0
        or not paths_are_safe
        or (
            require_canonical_children
            and prompts_root != str(Path(repo_realpath) / PROMPTS_REL)
        )
        or (
            require_canonical_children
            and state_root != str(Path(repo_realpath) / STATE_REL)
        )
        or value["binding"]
        != digest(f"{repo_dev}:{repo_ino}".encode())
    ):
        raise PromptError(f"{label} has invalid semantic values")


def _validate_owner_evidence_paths(
    value: dict[str, object],
    evidence_root: RootIdentity,
    required_mode: str,
) -> None:
    repo = Path(cast(str, value["repo_realpath"]))
    prompts = Path(cast(str, value["prompts_root"]))
    state = Path(cast(str, value["state_root"]))
    canonical = (
        prompts == repo / PROMPTS_REL
        and state == repo / STATE_REL
    )
    runtime = evidence_root.path.parent
    container = runtime.parent
    private = (
        evidence_root.path.name == "evidence"
        and runtime.name == "runtime"
        and prompts.parent == container
        and state.parent == container
        and prompts != state
        and prompts.name not in {"runtime", PRIVATE_MARKER}
        and state.name not in {"runtime", PRIVATE_MARKER}
    )
    if (
        (required_mode == "canonical" and not canonical)
        or (required_mode == "private" and not private)
        or required_mode not in {"canonical", "private"}
    ):
        raise PromptError(
            "prompt runtime owner evidence paths do not match active runtime mode"
        )


def _owner_retryable(exc: PromptError) -> bool:
    return (
        str(exc)
        in {
            "prompt runtime owner changed while opening",
            "prompt runtime owner changed while reading",
            "prompt runtime owner changed while being pinned",
        }
        or isinstance(exc.__cause__, FileNotFoundError)
    )


def _read_owner_during_publication(
    runtime_fd: int,
    expected: bytes,
) -> tuple[bytes, os.stat_result] | None:
    for attempt in range(256):
        try:
            result = _read_optional_child(
                runtime_fd,
                "owner.json",
                "prompt runtime owner",
                exact_mode=0o600,
            )
        except PromptError as exc:
            if not _owner_retryable(exc) or attempt == 255:
                raise
        else:
            if result is None or result[0] == expected:
                return result
            if not expected.startswith(result[0]) or len(result[0]) >= len(expected):
                return result
            if attempt == 255:
                return result
        time.sleep(0.002)
    raise AssertionError("bounded owner publication loop exhausted")


def _publish_initial_owner(
    runtime: RootIdentity,
    expected: bytes,
) -> None:
    """Resume and atomically publish the exact initial owner under build.lock."""
    dir_fd = _open_root(runtime, "prompt runtime root")
    stage_fd = -1
    try:
        owner = _read_optional_child(
            dir_fd,
            "owner.json",
            "prompt runtime owner",
            exact_mode=0o600,
        )
        if owner is not None:
            if owner[0] != expected:
                raise PromptError("concurrent prompt runtime owner has unknown content")
            if _read_optional_child(
                dir_fd,
                INITIAL_OWNER_STAGE,
                "initial prompt runtime owner stage",
                exact_mode=0o600,
            ) is not None:
                raise PromptError("completed initial owner retains an unexpected stage")
            return
        try:
            stage_fd = os.open(
                INITIAL_OWNER_STAGE,
                os.O_RDWR | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=dir_fd,
            )
            os.fchmod(stage_fd, 0o600)
        except FileExistsError:
            stage_fd = os.open(
                INITIAL_OWNER_STAGE,
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dir_fd,
            )
        opened = os.fstat(stage_fd)
        _safe_regular_info(opened, "initial prompt runtime owner stage", mode=0o600)
        current = os.stat(INITIAL_OWNER_STAGE, dir_fd=dir_fd, follow_symlinks=False)
        if not _same_inode(opened, current):
            raise PromptError("initial prompt runtime owner stage changed while pinning")
        if opened.st_size > len(expected):
            raise PromptError("initial prompt runtime owner stage has unknown content")
        prefix = os.pread(stage_fd, opened.st_size, 0)
        if prefix != expected[:len(prefix)]:
            raise PromptError("initial prompt runtime owner stage has unknown content")
        offset = len(prefix)
        while offset < len(expected):
            chunk = expected[offset:offset + OWNER_WRITE_CHUNK]
            written = os.pwrite(stage_fd, chunk, offset)
            if written <= 0:
                raise PromptError("initial prompt runtime owner stage write made no progress")
            offset += written
            _fault("initial-owner-after-write")
        os.fsync(stage_fd)
        complete = os.fstat(stage_fd)
        current = os.stat(INITIAL_OWNER_STAGE, dir_fd=dir_fd, follow_symlinks=False)
        if not _same_inode(complete, current) or complete.st_size != len(expected):
            raise PromptError("initial prompt runtime owner stage changed before publication")
        if os.pread(stage_fd, len(expected), 0) != expected:
            raise PromptError("initial prompt runtime owner stage has unknown content")
        _rename_noreplace(dir_fd, INITIAL_OWNER_STAGE, "owner.json")
        published, published_info = _read_child(
            dir_fd,
            "owner.json",
            "prompt runtime owner",
            exact_mode=0o600,
        )
        if published != expected or not _same_inode(complete, published_info):
            raise PromptError("initial prompt runtime owner publication identity mismatch")
        os.fsync(dir_fd)
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        os.close(dir_fd)


def _resume_legacy_partial_owner(runtime: RootIdentity, expected: bytes) -> None:
    """Complete only an exact expected prefix left by the former direct writer."""
    dir_fd = _open_root(runtime, "prompt runtime root")
    owner_fd = -1
    try:
        try:
            owner_fd = os.open(
                "owner.json",
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dir_fd,
            )
        except FileNotFoundError:
            return
        opened = os.fstat(owner_fd)
        _safe_regular_info(opened, "prompt runtime owner", mode=0o600)
        current = os.stat("owner.json", dir_fd=dir_fd, follow_symlinks=False)
        if not _same_inode(opened, current):
            raise PromptError("prompt runtime owner changed while pinning legacy prefix")
        if opened.st_size >= len(expected):
            return
        prefix = os.pread(owner_fd, opened.st_size, 0)
        if prefix != expected[:len(prefix)]:
            return
        offset = len(prefix)
        while offset < len(expected):
            chunk = expected[offset:offset + OWNER_WRITE_CHUNK]
            written = os.pwrite(owner_fd, chunk, offset)
            if written <= 0:
                raise PromptError("legacy prompt runtime owner recovery made no progress")
            offset += written
        os.fsync(owner_fd)
        completed = os.fstat(owner_fd)
        current = os.stat("owner.json", dir_fd=dir_fd, follow_symlinks=False)
        if (
            not _same_inode(completed, current)
            or completed.st_size != len(expected)
            or os.pread(owner_fd, len(expected), 0) != expected
        ):
            raise PromptError("legacy prompt runtime owner changed during recovery")
        os.fsync(dir_fd)
    finally:
        if owner_fd >= 0:
            os.close(owner_fd)
        os.close(dir_fd)


def _validate_runtime_owner(data: bytes, paths: Paths) -> dict[str, object]:
    value = _closed(
        _load_json(data, "prompt runtime owner"),
        {
            "binding", "magic", "prompts_root", "repo_dev", "repo_ino",
            "repo_realpath", "schema_version", "state_root",
        },
        "prompt runtime owner",
    )
    _validate_owner_record(
        value,
        "prompt runtime owner",
        require_canonical_children=paths.canonical,
    )
    identity = os.lstat(paths.repo)
    recorded_repo = value["repo_realpath"]
    recorded_prompts = value["prompts_root"]
    recorded_state = value["state_root"]
    recorded_paths_match = (
        isinstance(recorded_repo, str)
        and isinstance(recorded_prompts, str)
        and isinstance(recorded_state, str)
        and recorded_prompts == str(Path(recorded_repo) / PROMPTS_REL)
        and recorded_state == str(Path(recorded_repo) / STATE_REL)
    )
    if (
        value["magic"] != RUNTIME_MAGIC
        or not _current_schema(value["schema_version"])
        or value["binding"] != digest(f"{identity.st_dev}:{identity.st_ino}".encode())
        or value["repo_dev"] != identity.st_dev
        or value["repo_ino"] != identity.st_ino
        or not (
            (
                value["prompts_root"] == str(paths.output)
                and value["state_root"] == str(paths.state)
            )
            or (paths.canonical and recorded_paths_match)
        )
    ):
        raise PromptError("prompt runtime owner binding mismatch")
    return value


def _recover_completed_owner_stage(
    paths: Paths,
    runtime: RootIdentity,
    expected: bytes,
) -> None:
    stage_name = f".owner-{digest(expected)}.stage"
    staged = _read_optional_pinned(
        runtime,
        stage_name,
        f"completed owner stage {stage_name}",
        mode=0o600,
        max_bytes=MAX_CONTROL_BYTES,
    )
    if staged is None:
        return
    staged_data, _, staged_fd = staged
    os.close(staged_fd)
    if staged_data == expected:
        raise PromptError("completed owner stage duplicates current owner unexpectedly")
    _validate_runtime_owner(staged_data, paths)
    evidence_root = _root_identity(
        paths.runtime / "evidence",
        "prompt runtime evidence root",
        exact_mode=0o700,
    )
    _quarantine_leaf(
        runtime,
        stage_name,
        evidence_root,
        f"owner-{digest(staged_data)}",
        staged_data,
        0o600,
        max_bytes=MAX_CONTROL_BYTES,
        fault_prefix="owner",
    )


def _foreign_pending(paths: Paths, base: Path) -> None:
    if not _lexists(base):
        return
    _root_identity(base, "prompt runtime binding root", exact_mode=0o700)
    seen = 0
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                if seen >= MAX_RUNTIME_BINDINGS:
                    raise PromptError(
                        "prompt runtime binding root exceeds its entry ceiling"
                    )
                seen += 1
                if entry.name == paths.runtime.name:
                    continue
                if (
                    not entry.is_dir(follow_symlinks=False)
                    or not HEX_RE.fullmatch(entry.name)
                ):
                    raise PromptError(
                        "prompt runtime binding root contains foreign state"
                    )
                candidate = Path(entry.path)
                transactions = candidate / "transactions"
                if _lexists(transactions):
                    _root_identity(
                        candidate,
                        "foreign prompt runtime root",
                        exact_mode=0o700,
                    )
                    _root_identity(
                        transactions,
                        "foreign prompt transaction root",
                        exact_mode=0o700,
                    )
                    with os.scandir(transactions) as pending:
                        if next(pending, None) is not None:
                            raise PromptError(
                                "cross-filesystem or foreign pending prompt "
                                "transaction conflict"
                            )
    except OSError as exc:
        raise PromptError(
            f"cannot enumerate prompt runtime binding root: {exc}"
        ) from exc


def _prepare_runtime(paths: Paths) -> tuple[RootIdentity, bytes | None]:
    if paths.canonical:
        agentic = paths.repo / ".agentic"
        _ensure_private_parent(agentic)
        base = paths.repo / RUNTIME_REL
        _mkdir_private(base)
        _foreign_pending(paths, base)
    else:
        base = paths.runtime.parent
    _mkdir_private(paths.runtime)
    runtime = _root_identity(paths.runtime, "prompt runtime root", exact_mode=0o700)
    expected = canonical_json(_runtime_owner(paths))
    stale_owner: bytes | None = None
    runtime_fd = _open_root(runtime, "prompt runtime root")
    lock_fd = -1
    try:
        lock_result = _read_optional_child(
            runtime_fd,
            "build.lock",
            "prompt build lock",
            exact_mode=0o600,
            max_bytes=0,
        )
        if lock_result is None:
            try:
                created_lock, _ = _create_leaf(
                    runtime,
                    "build.lock",
                    b"",
                    0o600,
                    "prompt build lock",
                )
            except FileExistsError:
                pass
            else:
                os.close(created_lock)
        lock_fd = os.open(
            "build.lock",
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=runtime_fd,
        )
        _safe_regular_info(os.fstat(lock_fd), "prompt build lock", mode=0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        locked_info = os.fstat(lock_fd)
        current_lock = os.stat("build.lock", dir_fd=runtime_fd, follow_symlinks=False)
        if not _same_inode(locked_info, current_lock):
            raise PromptError("prompt build lock was rotated while acquiring it")
        _resume_legacy_partial_owner(runtime, expected)
        owner_result = _read_owner_during_publication(runtime_fd, expected)
        if owner_result is None:
            _publish_initial_owner(runtime, expected)
            owner_result = (expected, os.stat(
                "owner.json", dir_fd=runtime_fd, follow_symlinks=False
            ))
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        os.close(runtime_fd)
    current, _ = owner_result
    _validate_runtime_owner(current, paths)
    if current != expected:
        stale_owner = current
    runtime_fd = _open_root(runtime, "prompt runtime root")
    try:
        lock_result = _read_optional_child(
            runtime_fd,
            "build.lock",
            "prompt build lock",
            exact_mode=0o600,
            max_bytes=0,
        )
    finally:
        os.close(runtime_fd)
    if lock_result is None:
        raise PromptError("prompt build lock disappeared after owner publication")
    transactions = paths.runtime / "transactions"
    runtime_fd = _open_root(runtime, "prompt runtime root")
    try:
        child_infos: dict[str, os.stat_result] = {}
        for child in ("transactions", "completed", "evidence"):
            try:
                os.mkdir(child, 0o700, dir_fd=runtime_fd)
                os.fsync(runtime_fd)
            except FileExistsError:
                pass
            child_infos[child] = os.stat(
                child,
                dir_fd=runtime_fd,
                follow_symlinks=False,
            )
            info = child_infos[child]
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != UID
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise PromptError(
                    f"prompt {child} root must be a current-user mode-0700 directory"
                )
    finally:
        os.close(runtime_fd)
    transaction_root = _root_identity(
        transactions,
        "prompt transaction root",
        exact_mode=0o700,
    )
    if (transaction_root.dev, transaction_root.ino) != (
        child_infos["transactions"].st_dev,
        child_infos["transactions"].st_ino,
    ):
        raise PromptError("prompt transaction root changed during preparation")
    completed_root = _root_identity(
        paths.runtime / "completed",
        "completed prompt evidence root",
        exact_mode=0o700,
    )
    completed_fd = _open_root(completed_root, "completed prompt evidence root")
    try:
        completed_entries = _direct_entries(
            completed_fd,
            "completed prompt evidence root",
            limit=MAX_EVIDENCE_TRANSACTIONS,
            overflow_error="completed prompt evidence exceeds its bounded cap",
        )
        for completed_name, info in completed_entries.items():
            if (
                not HEX_RE.fullmatch(completed_name)
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != UID
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise PromptError("completed prompt evidence contains an invalid entry")
    finally:
        os.close(completed_fd)
    evidence_root = _root_identity(
        paths.runtime / "evidence",
        "prompt runtime evidence root",
        exact_mode=0o700,
    )
    _validate_owner_evidence(evidence_root)
    return runtime, stale_owner


def _pending(paths: Paths) -> list[Path]:
    transactions = paths.runtime / "transactions"
    if _lexists(paths.runtime):
        runtime_root = _root_identity(
            paths.runtime,
            "prompt runtime root",
            exact_mode=0o700,
        )
    else:
        return []
    if not _lexists(transactions):
        return []
    transaction_root = _root_identity(
        transactions,
        "prompt transaction root",
        exact_mode=0o700,
    )
    runtime_fd = _open_root(runtime_root, "prompt runtime root")
    transaction_fd = -1
    pending: list[Path] = []
    try:
        transaction_fd = os.open(
            "transactions",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=runtime_fd,
        )
        opened = os.fstat(transaction_fd)
        if (opened.st_dev, opened.st_ino) != (
            transaction_root.dev,
            transaction_root.ino,
        ):
            raise PromptError("prompt transaction root changed while pinning")
        for name, info in _direct_entries(
            transaction_fd,
            "prompt transaction root",
            limit=1,
            overflow_error="multiple pending prompt transactions conflict",
        ).items():
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != UID
                or stat.S_IMODE(info.st_mode) != 0o700
                or not HEX_RE.fullmatch(name)
            ):
                raise PromptError(
                    "prompt transaction root contains foreign or malformed state"
                )
            candidate = transactions / name
            identity = _root_identity(
                candidate,
                "prompt transaction",
                exact_mode=0o700,
            )
            if (identity.dev, identity.ino) != (info.st_dev, info.st_ino):
                raise PromptError("prompt transaction was substituted during scan")
            pending.append(candidate)
    except OSError as exc:
        raise PromptError(f"cannot pin prompt transaction root: {exc}") from exc
    finally:
        if transaction_fd >= 0:
            os.close(transaction_fd)
        os.close(runtime_fd)
    if len(pending) > 1:
        raise PromptError("multiple pending prompt transactions conflict")
    return pending


def _validate_runtime_readonly(paths: Paths) -> list[Path]:
    """Validate the complete runtime topology without acquiring or creating state."""
    runtime = _root_identity(
        paths.runtime,
        "prompt runtime root",
        exact_mode=0o700,
    )
    runtime_fd = _open_root(runtime, "prompt runtime root")
    try:
        entries = _direct_entries(
            runtime_fd,
            "prompt runtime root",
            limit=6,
            overflow_error="prompt runtime root has unexpected direct children",
        )
        expected_entries = {
            "owner.json", "build.lock", "transactions", "completed", "evidence",
        }
        if set(entries) != expected_entries:
            raise PromptError("prompt runtime root has unexpected direct children")
        owner, _ = _read_child(
            runtime_fd,
            "owner.json",
            "prompt runtime owner",
            exact_mode=0o600,
        )
        _validate_runtime_owner(owner, paths)
        _read_child(
            runtime_fd,
            "build.lock",
            "prompt build lock",
            exact_mode=0o600,
            max_bytes=0,
        )
    finally:
        os.close(runtime_fd)

    pending = _pending(paths)
    for transaction in pending:
        transaction_root = _root_identity(
            transaction,
            "prompt transaction",
            exact_mode=0o700,
        )
        transaction_fd = _open_root(transaction_root, "prompt transaction")
        try:
            transaction_entries = set(
                _direct_entries(
                    transaction_fd,
                    "prompt transaction",
                    limit=MAX_TRANSACTION_ENTRIES,
                )
            )
        finally:
            os.close(transaction_fd)
        if transaction_entries != {"evidence", "journal.json", "new", "old"}:
            raise PromptError("pending prompt transaction has invalid topology")
        journal = _journal(transaction)
        if journal["binding"] != _binding():
            raise PromptError("pending transaction binding mismatch")
        _validate_transaction_semantics(transaction, journal)

    completed_root = _root_identity(
        paths.runtime / "completed",
        "completed prompt evidence root",
        exact_mode=0o700,
    )
    completed_fd = _open_root(completed_root, "completed prompt evidence root")
    try:
        completed_entries = _direct_entries(
            completed_fd,
            "completed prompt evidence root",
            limit=MAX_EVIDENCE_TRANSACTIONS,
            overflow_error="completed prompt evidence exceeds its bounded cap",
        )
    finally:
        os.close(completed_fd)
    for name, info in completed_entries.items():
        if (
            HEX_RE.fullmatch(name) is None
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != UID
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise PromptError("completed prompt evidence contains an invalid entry")
        transaction = paths.runtime / "completed" / name
        journal = _journal(transaction)
        if journal["binding"] != _binding():
            raise PromptError("completed transaction binding mismatch")
        _validate_transaction_semantics(transaction, journal)

    evidence_root = _root_identity(
        paths.runtime / "evidence",
        "prompt runtime evidence root",
        exact_mode=0o700,
    )
    _validate_owner_evidence(evidence_root)
    return pending


def _journal(path: Path) -> dict[str, object]:
    root = _root_identity(path, "prompt transaction", exact_mode=0o700)
    dir_fd = _open_root(root, "prompt transaction")
    try:
        entries = set(
            _direct_entries(
                dir_fd,
                "prompt transaction",
                limit=MAX_TRANSACTION_ENTRIES,
            )
        )
        if entries != {"evidence", "journal.json", "new", "old"}:
            raise PromptError(
                "prompt transaction root has an invalid closed schema"
            )
        data, _ = _read_child(
            dir_fd,
            "journal.json",
            "prompt transaction journal",
            exact_mode=0o600,
            max_bytes=MAX_CONTROL_BYTES,
        )
    finally:
        os.close(dir_fd)
    value = _closed(
        _load_json(data, "prompt transaction journal"),
        {
            "binding", "magic", "manifest_artifacts", "new_manifest_sha256",
            "old_manifest_sha256", "operations", "schema_version",
            "source_inventory_sha256", "transaction_id",
        },
        "prompt transaction journal",
    )
    if (
        value["magic"] != TRANSACTION_MAGIC
        or not _current_schema(value["schema_version"])
        or not isinstance(value["transaction_id"], str)
        or value["transaction_id"] != path.name
        or not HEX_RE.fullmatch(value["transaction_id"])
        or not isinstance(value["new_manifest_sha256"], str)
        or not HEX_RE.fullmatch(value["new_manifest_sha256"])
        or (
            value["old_manifest_sha256"] is not None
            and (
                not isinstance(value["old_manifest_sha256"], str)
                or not HEX_RE.fullmatch(value["old_manifest_sha256"])
            )
        )
        or not isinstance(value["source_inventory_sha256"], str)
        or not HEX_RE.fullmatch(value["source_inventory_sha256"])
    ):
        raise PromptError("prompt transaction journal values are invalid")
    operations = value["operations"]
    if not isinstance(operations, list) or len(operations) > MAX_INVENTORY:
        raise PromptError("prompt transaction operations are invalid")
    previous = ""
    for index, raw in enumerate(operations):
        operation = _closed(
            raw,
            {"action", "artifacts", "new_sha256", "old_sha256", "path"},
            "prompt transaction operation",
        )
        name = operation["path"]
        action = operation["action"]
        if (
            not isinstance(name, str)
            or "/" in name
            or not name.endswith(".md")
            or not NAME_RE.fullmatch(name[:-3])
            or name <= previous
            or action not in {"create", "replace", "prune"}
        ):
            raise PromptError("prompt transaction operation path, action, or order is invalid")
        if action == "create" and operation["old_sha256"] is not None:
            raise PromptError("create operation unexpectedly has an old digest")
        if action == "prune" and operation["new_sha256"] is not None:
            raise PromptError("prune operation unexpectedly has a new digest")
        if (
            (action == "create" and operation["new_sha256"] is None)
            or (action == "replace" and (
                operation["old_sha256"] is None or operation["new_sha256"] is None
            ))
            or (action == "prune" and operation["old_sha256"] is None)
        ):
            raise PromptError("prompt transaction operation digest/action correlation is invalid")
        for key in ("old_sha256", "new_sha256"):
            value_hash = operation[key]
            if value_hash is not None and (
                not isinstance(value_hash, str) or not HEX_RE.fullmatch(value_hash)
            ):
                raise PromptError("prompt transaction operation digest is invalid")
        if operation["artifacts"] != _artifact_values(
            str(value["transaction_id"]),
            index,
            str(action),
        ):
            raise PromptError("prompt transaction operation artifacts are invalid")
        previous = name
    manifest_action = (
        "create" if value["old_manifest_sha256"] is None else "replace"
    )
    if value["manifest_artifacts"] != _artifact_values(
        str(value["transaction_id"]),
        len(operations),
        manifest_action,
        label="manifest",
    ):
        raise PromptError("prompt transaction manifest artifacts are invalid")
    return value


def _artifact_values(
    transaction_id: str,
    index: int,
    action: str,
    *,
    label: str = "wrapper",
) -> dict[str, object]:
    prefix = f".dinostack-{transaction_id}-{index:04d}-{label}"
    return {
        "old_evidence": (
            f"{index:04d}-{label}-old"
            if action in {"replace", "prune"}
            else None
        ),
        "placeholder_evidence": (
            f"{index:04d}-{label}-placeholder"
            if action == "prune"
            else None
        ),
        "stage": f"{prefix}.{'hold' if action == 'prune' else 'stage'}",
    }


def _manifest_operations(
    old_manifest: dict[str, object] | None,
    new_manifest: dict[str, object],
    transaction_id: str,
) -> list[dict[str, object]]:
    old_entries = _entry_map(old_manifest)
    new_entries = _entry_map(new_manifest)
    operations: list[dict[str, object]] = []
    for name in sorted(set(old_entries) | set(new_entries)):
        old_hash = old_entries.get(name)
        new_hash = new_entries.get(name)
        if old_hash == new_hash:
            continue
        index = len(operations)
        action = (
            "create"
            if old_hash is None
            else "prune"
            if new_hash is None
            else "replace"
        )
        operations.append(
            {
                "action": action,
                "artifacts": _artifact_values(transaction_id, index, action),
                "new_sha256": new_hash,
                "old_sha256": old_hash,
                "path": name,
            }
        )
    return operations


def _validate_transaction_blobs(path: Path, journal: dict[str, object]) -> None:
    operations = journal["operations"]
    assert isinstance(operations, list)
    expected_old = {
        str(operation["path"])
        for operation in operations
        if isinstance(operation, dict) and operation["old_sha256"] is not None
    }
    expected_new = {
        str(operation["path"])
        for operation in operations
        if isinstance(operation, dict) and operation["new_sha256"] is not None
    }
    if journal["old_manifest_sha256"] is not None:
        expected_old.add(MANIFEST_NAME)
    expected_new.add(MANIFEST_NAME)
    for label, expected in (("old", expected_old), ("new", expected_new)):
        root = path / label
        identity = _root_identity(
            root,
            f"prompt transaction {label}",
            exact_mode=0o700,
        )
        dir_fd = _open_root(identity, f"prompt transaction {label}")
        try:
            entries = _direct_entries(
                dir_fd,
                f"prompt transaction {label}",
                limit=min(MAX_TRANSACTION_BLOBS, len(expected)),
            )
            actual = set(entries)
            for info in entries.values():
                _safe_regular_info(
                    info,
                    f"prompt transaction {label} blob",
                    mode=0o600,
                )
        finally:
            os.close(dir_fd)
        if actual != expected:
            raise PromptError(f"prompt transaction {label} blob closure mismatch")
    evidence = path / "evidence"
    evidence_root = _root_identity(
        evidence,
        "prompt transaction evidence",
        exact_mode=0o700,
    )
    evidence_fd = _open_root(evidence_root, "prompt transaction evidence")
    try:
        allowed: set[str] = set()
        for operation in operations:
            assert isinstance(operation, dict)
            artifacts = cast(dict[str, object], operation["artifacts"])
            allowed.update(
                str(value)
                for key in ("old_evidence", "placeholder_evidence")
                if (value := artifacts[key]) is not None
            )
        manifest_artifacts = cast(dict[str, object], journal["manifest_artifacts"])
        if manifest_artifacts["old_evidence"] is not None:
            allowed.add(str(manifest_artifacts["old_evidence"]))
        entries = _direct_entries(
            evidence_fd,
            "prompt transaction evidence",
            limit=min(MAX_TRANSACTION_EVIDENCE, len(allowed)),
        )
        if not set(entries).issubset(allowed):
            raise PromptError("prompt transaction evidence closure mismatch")
        for info in entries.values():
            _safe_regular_info(info, "prompt transaction evidence")
    finally:
        os.close(evidence_fd)


def _validate_transaction_semantics(
    path: Path,
    journal: dict[str, object],
) -> tuple[dict[str, object] | None, dict[str, object]]:
    _validate_transaction_blobs(path, journal)
    new_manifest_bytes = _blob(
        path / "new",
        MANIFEST_NAME,
        str(journal["new_manifest_sha256"]),
    )
    new_manifest = _parse_manifest(new_manifest_bytes)
    old_hash = journal["old_manifest_sha256"]
    old_manifest: dict[str, object] | None = None
    if isinstance(old_hash, str):
        old_manifest = _parse_manifest(
            _blob(path / "old", MANIFEST_NAME, old_hash)
        )
    if journal["operations"] != _manifest_operations(
        old_manifest,
        new_manifest,
        str(journal["transaction_id"]),
    ):
        raise PromptError(
            "prompt transaction operations do not exactly match manifest transition"
        )
    new_entries = cast(list[dict[str, object]], new_manifest["entries"])
    names = [str(entry["basename"]) for entry in new_entries]
    inventory_digests = {
        digest(canonical_json(names)),
        digest(canonical_json(sorted(names))),
    }
    if journal["source_inventory_sha256"] not in inventory_digests:
        raise PromptError("prompt transaction inventory digest does not match new manifest")
    journal_operations = cast(list[dict[str, object]], journal["operations"])
    for operation in journal_operations:
        assert isinstance(operation, dict)
        name = str(operation["path"])
        if operation["old_sha256"] is not None:
            _blob(path / "old", name, str(operation["old_sha256"]))
        if operation["new_sha256"] is not None:
            data = _blob(path / "new", name, str(operation["new_sha256"]))
            _validate_wrapper(name[:-3], data)
    return old_manifest, new_manifest


def _blob(root: Path, name: str, expected_hash: str) -> bytes:
    identity = _root_identity(
        root,
        f"prompt transaction {root.name}",
        exact_mode=0o700,
    )
    dir_fd = _open_root(identity, f"prompt transaction {root.name}")
    try:
        data, _ = _read_child(
            dir_fd,
            name,
            f"transaction blob {root.name}/{name}",
            exact_mode=0o600,
            max_bytes=(
                MAX_CONTROL_BYTES if name == MANIFEST_NAME else MAX_WRAPPER_BYTES
            ),
        )
    finally:
        os.close(dir_fd)
    if digest(data) != expected_hash:
        raise PromptError(f"transaction blob digest mismatch: {root.name}/{name}")
    return data


def _mutation_plan(
    transaction: Path,
    artifacts_value: object,
    fault_prefix: str,
) -> MutationPlan:
    artifacts = _closed(
        artifacts_value,
        {"old_evidence", "placeholder_evidence", "stage"},
        "prompt mutation artifacts",
    )
    for key in ("stage", "old_evidence", "placeholder_evidence"):
        value = artifacts[key]
        if value is not None and (
            not isinstance(value, str)
            or "/" in value
            or value in {"", ".", ".."}
            or len(value) > 160
        ):
            raise PromptError("prompt mutation artifact name is invalid")
    stage = artifacts["stage"]
    if not isinstance(stage, str):
        raise PromptError("prompt mutation stage name is invalid")
    evidence_root = _root_identity(
        transaction / "evidence",
        "prompt transaction evidence",
        exact_mode=0o700,
    )
    return MutationPlan(
        stage=stage,
        old_evidence=cast(str | None, artifacts["old_evidence"]),
        placeholder_evidence=cast(str | None, artifacts["placeholder_evidence"]),
        evidence_root=evidence_root,
        fault_prefix=fault_prefix,
    )


def _remove_transaction(transaction: Path) -> None:
    root = _root_identity(transaction, "prompt transaction", exact_mode=0o700)
    parent = _root_identity(
        transaction.parent,
        "prompt transaction root",
        exact_mode=0o700,
    )
    completed = _root_identity(
        transaction.parent.parent / "completed",
        "completed prompt evidence root",
        exact_mode=0o700,
    )
    parent_fd = _open_root(parent, "prompt transaction root")
    completed_fd = _open_root(completed, "completed prompt evidence root")
    try:
        if len(
            _direct_entries(
                completed_fd,
                "completed prompt evidence root",
                limit=MAX_EVIDENCE_TRANSACTIONS,
                overflow_error="completed prompt evidence cap reached",
            )
        ) >= MAX_EVIDENCE_TRANSACTIONS:
            raise PromptError("completed prompt evidence cap reached")
        _rename_noreplace_between(
            parent_fd,
            transaction.name,
            completed_fd,
            transaction.name,
        )
        archived = os.stat(
            transaction.name,
            dir_fd=completed_fd,
            follow_symlinks=False,
        )
        if (archived.st_dev, archived.st_ino) != (root.dev, root.ino):
            _rename_noreplace_between(
                completed_fd,
                transaction.name,
                parent_fd,
                transaction.name,
            )
            raise PromptError("prompt transaction was substituted during archival")
        _fault("transaction-after-archive")
        os.fsync(parent_fd)
        os.fsync(completed_fd)
    except OSError as exc:
        raise PromptError(f"cannot archive prompt transaction root: {exc}") from exc
    finally:
        os.close(completed_fd)
        os.close(parent_fd)


def _recover(paths: Paths) -> None:
    pending = _pending(paths)
    if not pending:
        return
    transaction = pending[0]
    transaction_root = _root_identity(
        transaction,
        "prompt transaction",
        exact_mode=0o700,
    )
    transaction_fd = _open_root(transaction_root, "prompt transaction")
    try:
        transaction_entries = set(
            _direct_entries(
                transaction_fd,
                "prompt transaction",
                limit=MAX_TRANSACTION_ENTRIES,
            )
        )
    finally:
        os.close(transaction_fd)
    if "journal.json" not in transaction_entries:
        if not transaction_entries:
            _remove_transaction(transaction)
            return
        raise PromptError("pending prompt transaction is missing its journal")
    journal = _journal(transaction)
    if journal["binding"] != _binding():
        raise PromptError("pending transaction binding mismatch")
    _, new_manifest_value = _validate_transaction_semantics(transaction, journal)
    old_hash = journal["old_manifest_sha256"]
    output_root = _root_identity(paths.output, "prompt output root")
    state_root = _root_identity(paths.state, "prompt state root")
    state_fd = _open_root(state_root, "prompt state root")
    try:
        current_manifest_result = _read_optional_child(
            state_fd,
            MANIFEST_NAME,
            "prompt manifest",
            exact_mode=0o644,
        )
    finally:
        os.close(state_fd)
    current_manifest = (
        current_manifest_result[0]
        if current_manifest_result is not None
        else None
    )
    current_hash = digest(current_manifest) if current_manifest is not None else None
    new_hash = str(journal["new_manifest_sha256"])
    valid_manifest_states = {new_hash}
    valid_manifest_states.add(old_hash if isinstance(old_hash, str) else None)
    if current_hash not in valid_manifest_states:
        raise PromptError("pending transaction found unknown manifest state")
    operations = journal["operations"]
    assert isinstance(operations, list)
    if current_hash not in {
        new_hash,
        old_hash if isinstance(old_hash, str) else None,
    }:
        raise PromptError("pending transaction cannot deterministically roll forward")
    new_manifest = _blob(
        transaction / "new", MANIFEST_NAME, str(journal["new_manifest_sha256"])
    )
    for operation in operations:
        assert isinstance(operation, dict)
        name = str(operation["path"])
        plan = _mutation_plan(
            transaction,
            operation["artifacts"],
            str(operation["action"]),
        )
        old_data = (
            _blob(transaction / "old", name, str(operation["old_sha256"]))
            if operation["old_sha256"] is not None
            else None
        )
        if operation["action"] == "prune":
            assert old_data is not None
            _unlink_owned(output_root, name, old_data, plan=plan)
        else:
            new_data = _blob(
                transaction / "new",
                name,
                str(operation["new_sha256"]),
            )
            _atomic_bytes(
                output_root,
                name,
                new_data,
                0o644,
                expected=old_data,
                plan=plan,
            )
    _validate_output_against_manifest(paths, new_manifest_value)
    manifest_plan = _mutation_plan(
        transaction,
        journal["manifest_artifacts"],
        "manifest",
    )
    old_manifest = (
        _blob(transaction / "old", MANIFEST_NAME, str(old_hash))
        if isinstance(old_hash, str)
        else None
    )
    _atomic_bytes(
        state_root,
        MANIFEST_NAME,
        new_manifest,
        0o644,
        expected=old_manifest,
        plan=manifest_plan,
    )
    _remove_transaction(transaction)


def _initialize_roots(paths: Paths, want: Desired) -> tuple[RootIdentity, RootIdentity]:
    if not paths.output.exists():
        _mkdir_generated(paths.output)
    if not paths.state.exists():
        _mkdir_generated(paths.state)
    output_root = _root_identity(paths.output, "prompt output root")
    state_root = _root_identity(paths.state, "prompt state root")
    output_fd = _open_root(output_root, "prompt output root")
    state_fd = _open_root(state_root, "prompt state root")
    try:
        prompt_marker = _read_optional_child(
            output_fd,
            PROMPT_MARKER,
            "prompt root marker",
            exact_mode=0o644,
        )
        output_entries = set(
            _direct_entries(
                output_fd,
                "prompt output root",
                limit=MAX_OUTPUT_ENTRIES,
            )
        )
        if prompt_marker is not None:
            _validate_marker(
                prompt_marker[0],
                want.prompt_marker,
                "prompt root marker",
            )
        elif not output_entries:
            _atomic_bytes(
                output_root,
                PROMPT_MARKER,
                want.prompt_marker,
                0o644,
                expected=None,
            )
        else:
            raise PromptError("unowned populated prompt output root")
        state_marker = _read_optional_child(
            state_fd,
            STATE_MARKER,
            "prompt state marker",
            exact_mode=0o644,
        )
        state_entries = set(
            _direct_entries(
                state_fd,
                "prompt state root",
                limit=MAX_STATE_ENTRIES,
            )
        )
        if state_marker is not None:
            _validate_marker(
                state_marker[0],
                want.state_marker,
                "prompt state marker",
            )
        elif not state_entries:
            _atomic_bytes(
                state_root,
                STATE_MARKER,
                want.state_marker,
                0o644,
                expected=None,
            )
        else:
            raise PromptError("unowned populated prompt state root")
    finally:
        os.close(state_fd)
        os.close(output_fd)
    return output_root, state_root


def _fault(label: str) -> None:
    if os.environ.get("DINOSTACK_PROMPT_FAULT") == label:
        raise PromptError(f"injected prompt transaction fault: {label}")


def _write_blob(root: RootIdentity, name: str, data: bytes) -> None:
    _atomic_bytes(root, name, data, 0o600, expected=None)


def _start_transaction(
    paths: Paths,
    want: Desired,
    old_manifest_bytes: bytes | None,
    old_manifest: dict[str, object] | None,
) -> tuple[Path, dict[str, object]]:
    old_entries = _entry_map(old_manifest)
    transaction_id = secrets.token_hex(32)
    operations = _manifest_operations(
        old_manifest,
        _parse_manifest(want.manifest),
        transaction_id,
    )
    transactions = paths.runtime / "transactions"
    transaction_parent = _root_identity(
        transactions,
        "prompt transaction root",
        exact_mode=0o700,
    )
    parent_fd = _open_root(transaction_parent, "prompt transaction root")
    try:
        try:
            os.mkdir(transaction_id, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except OSError as exc:
            raise PromptError(f"cannot create prompt transaction: {exc}") from exc
    finally:
        os.close(parent_fd)
    transaction = transactions / transaction_id
    try:
        transaction_root = _root_identity(
            transaction,
            "prompt transaction",
            exact_mode=0o700,
        )
        transaction_fd = _open_root(transaction_root, "prompt transaction")
        try:
            try:
                os.mkdir("old", 0o700, dir_fd=transaction_fd)
                os.mkdir("new", 0o700, dir_fd=transaction_fd)
                os.mkdir("evidence", 0o700, dir_fd=transaction_fd)
                os.fsync(transaction_fd)
            except OSError as exc:
                raise PromptError(
                    f"cannot initialize prompt transaction: {exc}"
                ) from exc
        finally:
            os.close(transaction_fd)
    except Exception:
        if _lexists(transaction):
            try:
                _remove_transaction(transaction)
            except PromptError:
                pass
        raise
    journal_written = False
    try:
        old_root = _root_identity(transaction / "old", "old transaction blobs", exact_mode=0o700)
        new_root = _root_identity(transaction / "new", "new transaction blobs", exact_mode=0o700)
        if old_manifest_bytes is not None:
            _write_blob(old_root, MANIFEST_NAME, old_manifest_bytes)
        _write_blob(new_root, MANIFEST_NAME, want.manifest)
        old_hashes = old_entries
        output_root = _root_identity(paths.output, "prompt output root")
        output_fd = _open_root(output_root, "prompt output root")
        try:
            for operation in operations:
                name = str(operation["path"])
                if operation["old_sha256"] is not None:
                    old_data, _ = _read_child(
                        output_fd,
                        name,
                        f"owned wrapper {name}",
                        exact_mode=0o644,
                        max_bytes=MAX_WRAPPER_BYTES,
                    )
                    if digest(old_data) != old_hashes[name]:
                        raise PromptError(
                            f"owned wrapper changed before journaling: {name}"
                        )
                    _write_blob(old_root, name, old_data)
                if operation["new_sha256"] is not None:
                    _write_blob(new_root, name, want.wrappers[name])
        finally:
            os.close(output_fd)
        _fsync_root(old_root, "old transaction blobs")
        _fsync_root(new_root, "new transaction blobs")
        _fault("after-blobs")
        journal: dict[str, object] = {
            "binding": _binding(),
            "magic": TRANSACTION_MAGIC,
            "manifest_artifacts": _artifact_values(
                transaction_id,
                len(operations),
                "create" if old_manifest_bytes is None else "replace",
                label="manifest",
            ),
            "new_manifest_sha256": digest(want.manifest),
            "old_manifest_sha256": digest(old_manifest_bytes) if old_manifest_bytes is not None else None,
            "operations": operations,
            "schema_version": SCHEMA,
            "source_inventory_sha256": want.inventory_hash,
            "transaction_id": transaction_id,
        }
        _write_blob(transaction_root, "journal.json", canonical_json(journal))
        journal_written = True
        _fsync_root(transaction_root, "prompt transaction")
        _fsync_root(transaction_parent, "prompt transaction root")
        _fault("after-journal")
        return transaction, journal
    except Exception:
        if not journal_written:
            _remove_transaction(transaction)
        raise


def build(paths: Paths) -> None:
    # Validate canonical input before the first write. Recovery itself deliberately
    # precedes the second inventory read once a durable transaction exists.
    first_want = desired(paths.repo)
    runtime_root, stale_owner = _prepare_runtime(paths)
    runtime_fd = _open_root(runtime_root, "prompt runtime root")
    lock_fd = -1
    try:
        try:
            lock_fd = os.open(
                "build.lock",
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=runtime_fd,
            )
        except OSError as exc:
            raise PromptError(f"cannot pin prompt build lock: {exc}") from exc
        _safe_regular_info(os.fstat(lock_fd), "prompt build lock", mode=0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        locked_info = os.fstat(lock_fd)
        current_lock = os.stat(
            "build.lock",
            dir_fd=runtime_fd,
            follow_symlinks=False,
        )
        if not _same_inode(locked_info, current_lock):
            raise PromptError("prompt build lock was rotated while acquiring it")
        _revalidate(runtime_root, "prompt runtime root")
        if stale_owner is None:
            _recover_completed_owner_stage(
                paths,
                runtime_root,
                canonical_json(_runtime_owner(paths)),
            )
        if _pending(paths):
            if not paths.output.exists() or not paths.state.exists():
                raise PromptError("pending transaction is missing generated roots")
            _recover(paths)
        if stale_owner is not None:
            new_owner = canonical_json(_runtime_owner(paths))
            owner_evidence_root = _root_identity(
                paths.runtime / "evidence",
                "prompt runtime evidence root",
                exact_mode=0o700,
            )
            owner_plan = MutationPlan(
                stage=f".owner-{digest(new_owner)}.stage",
                old_evidence=f"owner-{digest(stale_owner)}",
                placeholder_evidence=None,
                evidence_root=owner_evidence_root,
                fault_prefix="owner",
            )
            _atomic_bytes(
                runtime_root,
                "owner.json",
                new_owner,
                0o600,
                expected=stale_owner,
                plan=owner_plan,
            )
        want = desired(paths.repo)
        if want != first_want:
            raise PromptError("canonical command inventory changed during build")
        output_root, state_root = _initialize_roots(paths, want)
        old_bytes, old_manifest = _owned_manifest(paths, required=False)
        _validate_owned_tree(paths, old_manifest)
        if old_bytes == want.manifest:
            _validate_exact_wrappers(paths, want)
            return
        transaction, journal = _start_transaction(paths, want, old_bytes, old_manifest)
        operations = journal["operations"]
        assert isinstance(operations, list)
        for index, operation in enumerate(operations):
            assert isinstance(operation, dict)
            name = str(operation["path"])
            old_data = (
                _blob(transaction / "old", name, str(operation["old_sha256"]))
                if operation["old_sha256"] is not None
                else None
            )
            if operation["action"] == "prune":
                assert old_data is not None
                _unlink_owned(
                    output_root,
                    name,
                    old_data,
                    plan=_mutation_plan(
                        transaction,
                        operation["artifacts"],
                        "prune",
                    ),
                )
            else:
                new_data = _blob(transaction / "new", name, str(operation["new_sha256"]))
                _atomic_bytes(
                    output_root,
                    name,
                    new_data,
                    0o644,
                    expected=old_data,
                    plan=_mutation_plan(
                        transaction,
                        operation["artifacts"],
                        str(operation["action"]),
                    ),
                )
            _fault(f"after-operation-{index}")
        _fault("before-manifest")
        _validate_output_against_manifest(paths, _parse_manifest(want.manifest))
        _atomic_bytes(
            state_root,
            MANIFEST_NAME,
            want.manifest,
            0o644,
            expected=old_bytes,
            plan=_mutation_plan(
                transaction,
                journal["manifest_artifacts"],
                "manifest",
            ),
        )
        _fault("after-manifest")
        _validate_owned_tree(paths, _parse_manifest(want.manifest))
        _fault("before-cleanup")
        _remove_transaction(transaction)
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        os.close(runtime_fd)


def check(paths: Paths) -> None:
    want = desired(paths.repo)
    if _validate_runtime_readonly(paths):
        raise PromptError("pending prompt transaction requires build recovery")
    if not paths.output.exists() or not paths.state.exists():
        raise PromptError("generated prompt roots are missing")
    old_bytes, manifest = _owned_manifest(paths, required=True)
    _validate_owned_tree(paths, manifest)
    if old_bytes != want.manifest:
        raise PromptError("generated prompt manifest drift")
    _validate_exact_wrappers(paths, want)


def config_paths(config_arg: str | None) -> dict[str, str]:
    selected = config_arg
    if selected is None:
        selected = os.environ.get("AGENTIC_CONFIG_DIR") or os.environ.get("CODEX_HOME")
    if selected is None:
        home = os.environ.get("HOME")
        if not home or not os.path.isabs(home):
            raise PromptError("paths requires an absolute validated HOME when no config override is set")
        selected = str(Path(home) / ".codex")
    candidate = _expand_user_path(selected, "Codex config directory")
    if not candidate.is_absolute():
        raise PromptError("Codex config directory must be absolute")
    try:
        real = candidate.resolve(strict=True)
    except OSError as exc:
        raise PromptError(
            f"cannot resolve Codex config directory: {candidate}"
        ) from exc
    _root_identity(real, "Codex config directory")
    return {
        "config_dir": str(real),
        "prompts_root": str(real / "prompts"),
        "state_root": str(real / "prompt-generation-state"),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("build", "check"):
        command = sub.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--output")
        command.add_argument("--state-dir")
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--repo", required=True)
    paths = sub.add_parser("paths")
    paths.add_argument("--config-dir")
    return result


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "paths":
            sys.stdout.buffer.write(canonical_json(config_paths(args.config_dir)))
            return 0
        repo = _repo(args.repo)
        if args.command == "inventory":
            sys.stdout.buffer.write(canonical_json(_inventory(repo)))
            return 0
        paths = resolve_paths(repo, args.output, args.state_dir)
        if args.command == "build":
            build(paths)
            print(f"Codex prompt wrapper build: OK ({len(_inventory(repo))} wrappers)")
        else:
            check(paths)
            print(f"Codex prompt wrapper check: OK ({len(_inventory(repo))} wrappers)")
        return 0
    except PromptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
