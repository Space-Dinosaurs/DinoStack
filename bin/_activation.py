#!/usr/bin/env python3
"""
Internal activation-state primitives for the /ds command and agentic-config.
NOT a public CLI - do not invoke directly.

Purpose: manage the agentic-engineering activation layers that hooks/lib/
activation.{sh,py,js} read. Those guards do pure stat checks on the hot path;
this module owns the *writes* (and the structured ~/.agentic/activation.json
that the flat activation.list mirrors) plus the read used by `/ds status`.

Activation layers (must match hooks/lib/activation.* - first hit wins):
  1. <cwd>/.agentic/active          (explicit, persistent)
  2. <cwd>/.agentic/active.session  (explicit, this session only)
  3. <cwd>/.agentic/dormant         (tombstone; overrides auto-detect)
  4. <cwd>/.agentic/ dir exists     (zero-migration auto-detect)
  5. cwd in ~/.agentic/activation.list (installer/config allowlist)
  6. none -> dormant

Public API:
  resolve_state(cwd) -> dict
    {"active": bool, "reason": <layer>, "tier": <str|None>}. reason is one of
    "active-file", "session-file", "tombstone", "auto-detect", "allowlist",
    "dormant". Mirrors the guard precedence exactly so `/ds status` never
    disagrees with what the hooks do.

  activate(cwd, tier="minimal", by="ds", session=False) -> Path
    Writes <cwd>/.agentic/active (or active.session) as JSON
    {tier, activated_at, by[, session_id]} and removes any dormant tombstone.
    Returns the marker path. Also adds cwd to the ~/.agentic allowlist.

  deactivate(cwd, remove_from_allowlist=False) -> Path
    Writes <cwd>/.agentic/dormant tombstone and removes active/active.session.
    Leaves all other .agentic/ data intact. Optionally drops cwd from the
    allowlist. Returns the tombstone path.

  add_to_allowlist(cwd) / remove_from_allowlist(cwd) -> None
    Maintain ~/.agentic/activation.json (structured, source of truth) and the
    flat ~/.agentic/activation.list (realpath-per-line, the shell fast path).

  resident_bytes(cwd) -> int
    Total size of <cwd>/.agentic/ (for `/ds status`). 0 if absent.

Upstream deps: bin/_lib.atomic_write (loaded via the .resolve() sibling shim so a
symlinked bare invocation still finds _lib.py - see MEMORY.md), Python 3 stdlib.

Downstream consumers: content/commands/ds.md implementation, bin/agentic-config,
bin/agentic-status.

Failure modes: writes are atomic (atomic_write). resolve_state never raises -
any stat error degrades to fail-ACTIVE ({"active": True, "reason": "error"})
to match the guards. Allowlist edits are best-effort and idempotent.
Performance: stat-bounded; allowlist scans are line-oriented on a small file.
"""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import json
import os
import sys as _sys
from datetime import datetime, timezone
from pathlib import Path

# Load bin/_lib.atomic_write via the resolved sibling path so a symlinked bare
# invocation (install.sh symlinks bins but not _lib.py) still resolves it.
_LIB_PATH = Path(__file__).resolve().parent / "_lib.py"
if "_lib" in _sys.modules:
    _lib = _sys.modules["_lib"]
else:
    _loader = _ilm.SourceFileLoader("_lib", str(_LIB_PATH))
    _spec = _ilu.spec_from_loader("_lib", _loader)
    _lib = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _loader.exec_module(_lib)
    _sys.modules["_lib"] = _lib

atomic_write = _lib.atomic_write

_HOME_AGENTIC = Path(os.path.expanduser("~")) / ".agentic"
_ALLOWLIST_JSON = _HOME_AGENTIC / "activation.json"
_ALLOWLIST_FLAT = _HOME_AGENTIC / "activation.list"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _agentic_dir(cwd: str) -> Path:
    return Path(cwd) / ".agentic"


def _realpath(p: str) -> str:
    try:
        return os.path.realpath(p)
    except Exception:
        return p


# --------------------------------------------------------------------------- #
# Allowlist (structured JSON is source of truth; flat .list is the shell path). #
# --------------------------------------------------------------------------- #
def _read_allowlist() -> list:
    try:
        with open(_ALLOWLIST_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data.get("projects", [])
        return [e for e in entries if isinstance(e, str)]
    except Exception:
        return []


def _write_allowlist(entries: list) -> None:
    """Write both the JSON (source of truth) and the flat .list mirror atomically."""
    _HOME_AGENTIC.mkdir(parents=True, exist_ok=True)
    # De-dupe on realpath while preserving order.
    seen = set()
    ordered = []
    for e in entries:
        rp = _realpath(e)
        if rp not in seen:
            seen.add(rp)
            ordered.append(rp)
    atomic_write(
        _ALLOWLIST_JSON,
        json.dumps({"projects": ordered, "updated_at": _now_iso()}, indent=2) + "\n",
        mode=0o644,
    )
    atomic_write(_ALLOWLIST_FLAT, "".join(f"{p}\n" for p in ordered), mode=0o644)


def add_to_allowlist(cwd: str) -> None:
    entries = _read_allowlist()
    target = _realpath(cwd)
    if target not in {_realpath(e) for e in entries}:
        entries.append(target)
        _write_allowlist(entries)


def remove_from_allowlist(cwd: str) -> None:
    entries = _read_allowlist()
    target = _realpath(cwd)
    kept = [e for e in entries if _realpath(e) != target]
    if len(kept) != len(entries):
        _write_allowlist(kept)


def _in_allowlist(cwd: str) -> bool:
    target = _realpath(cwd)
    return target in {_realpath(e) for e in _read_allowlist()}


# --------------------------------------------------------------------------- #
# State resolution (mirrors hooks/lib/activation.* precedence exactly).        #
# --------------------------------------------------------------------------- #
def resolve_state(cwd) -> dict:
    """Resolve activation for *cwd*; see module docstring for precedence."""
    try:
        if not isinstance(cwd, str) or not cwd.strip():
            return {"active": True, "reason": "error", "tier": None}
        agentic = _agentic_dir(cwd.strip())
        active_file = agentic / "active"
        session_file = agentic / "active.session"
        tombstone = agentic / "dormant"
        if active_file.exists():
            return {"active": True, "reason": "active-file", "tier": _read_tier(active_file)}
        if session_file.exists():
            return {"active": True, "reason": "session-file", "tier": _read_tier(session_file)}
        if tombstone.exists():
            return {"active": False, "reason": "tombstone", "tier": None}
        if agentic.is_dir():
            return {"active": True, "reason": "auto-detect", "tier": None}
        if _in_allowlist(cwd.strip()):
            return {"active": True, "reason": "allowlist", "tier": None}
        return {"active": False, "reason": "dormant", "tier": None}
    except Exception:
        return {"active": True, "reason": "error", "tier": None}


def _read_tier(marker: Path):
    try:
        with open(marker, encoding="utf-8") as fh:
            return json.load(fh).get("tier")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Activate / deactivate.                                                        #
# --------------------------------------------------------------------------- #
def activate(cwd: str, tier: str = "minimal", by: str = "ds", session: bool = False,
             session_id=None) -> Path:
    """Write the active marker, clear any tombstone, and allowlist the project."""
    agentic = _agentic_dir(cwd)
    agentic.mkdir(parents=True, exist_ok=True)
    marker = agentic / ("active.session" if session else "active")
    payload = {"tier": tier, "activated_at": _now_iso(), "by": by}
    if session and session_id:
        payload["session_id"] = session_id
    atomic_write(marker, json.dumps(payload, indent=2) + "\n", mode=0o644)
    # Clear tombstone so auto-detect/explicit no longer read dormant.
    tombstone = agentic / "dormant"
    try:
        tombstone.unlink()
    except FileNotFoundError:
        pass
    add_to_allowlist(cwd)
    return marker


def deactivate(cwd: str, remove_from_allowlist_flag: bool = False) -> Path:
    """Write the dormant tombstone and remove active/active.session. Data kept."""
    agentic = _agentic_dir(cwd)
    agentic.mkdir(parents=True, exist_ok=True)
    for name in ("active", "active.session"):
        try:
            (agentic / name).unlink()
        except FileNotFoundError:
            pass
    tombstone = agentic / "dormant"
    atomic_write(
        tombstone,
        json.dumps({"deactivated_at": _now_iso(), "by": "ds"}, indent=2) + "\n",
        mode=0o644,
    )
    if remove_from_allowlist_flag:
        remove_from_allowlist(cwd)
    return tombstone


def resident_bytes(cwd: str) -> int:
    """Total byte size of <cwd>/.agentic/ (for `/ds status`). 0 if absent."""
    agentic = _agentic_dir(cwd)
    total = 0
    try:
        for root, _dirs, files in os.walk(agentic):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except Exception:
        pass
    return total


def clear_session_marker(cwd: str) -> None:
    """Remove <cwd>/.agentic/active.session (SessionEnd cleanup for /ds --session)."""
    try:
        (_agentic_dir(cwd) / "active.session").unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass
