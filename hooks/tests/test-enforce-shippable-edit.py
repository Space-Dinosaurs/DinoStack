# Run with: python3 hooks/tests/test-enforce-shippable-edit.py
"""
Unit tests for hooks/enforce-shippable-edit.py.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin and asserts ALLOW (exit 0, no deny in stdout) or DENY (exit 0,
permissionDecision "deny" in stdout, reason mentions the guard + path).

The fail-open matrix is the primary invariant under test: this hook must
NEVER crash-to-block (the failure mode the predecessor version had). Every
case in FAIL_OPEN_CASES asserts is_allow() - none of them may deny, and
none may exit non-zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-shippable-edit.py"
)

# Real repo root: hooks/tests/../.. from this test file's location.
REPO_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


def run_hook(payload: str, extra_env: dict | None = None, cwd: str | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("AE_SHIPPABLE_GUARD_DISABLE", None)  # clean slate per test
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
    """ALLOW: exit 0 and no deny decision in stdout."""
    if returncode != 0:
        return False
    if not stdout.strip():
        return True
    try:
        obj = json.loads(stdout)
        decision = obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        return decision != "deny"
    except Exception:
        return True  # unparseable output -> not a deny


def is_deny(returncode: int, stdout: str) -> tuple[bool, str]:
    """DENY: exit 0, permissionDecision == deny. Returns (ok, reason)."""
    if returncode != 0:
        return False, ""
    try:
        obj = json.loads(stdout)
        hso = obj.get("hookSpecificOutput", {})
        decision = hso.get("permissionDecision", "")
        reason = hso.get("permissionDecisionReason", "")
        return decision == "deny", reason
    except Exception:
        return False, ""


def make_payload(tool_name: str, file_path: str, agent_id: str | None = None, cwd: str = "") -> str:
    obj: dict = {"tool_name": tool_name, "tool_input": {"file_path": file_path}, "cwd": cwd}
    if agent_id is not None:
        obj["agent_id"] = agent_id
    return json.dumps(obj)


failed = 0
total = 0


def check_allow(label: str, payload: str, extra_env: dict | None = None) -> None:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, extra_env)
    ok = is_allow(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload!r}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")


def check_deny(label: str, payload: str, extra_env: dict | None = None, must_contain: tuple[str, ...] = ()) -> None:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, extra_env)
    ok, reason = is_deny(rc, stdout)
    if ok:
        for token in must_contain:
            if token not in reason:
                ok = False
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload!r}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
        print(f"         reason:   {reason!r}")
        print(f"         must_contain: {must_contain!r}")


# ---------------------------------------------------------------------------
# 1. FAIL-OPEN matrix - none of these may ever deny.
# ---------------------------------------------------------------------------
print("-- fail-open matrix --")

check_allow("empty stdin", "")
check_allow("malformed JSON", "not-json-at-all{{{{")
check_allow("JSON but not an object", json.dumps([1, 2, 3]))
check_allow(
    "missing tool_input",
    json.dumps({"tool_name": "Write"}),
)
check_allow(
    "missing file_path",
    json.dumps({"tool_name": "Write", "tool_input": {}}),
)
check_allow(
    "blank file_path",
    json.dumps({"tool_name": "Write", "tool_input": {"file_path": "   "}}),
)
check_allow(
    "non-matcher tool (Read)",
    make_payload("Read", os.path.join(REPO_ROOT, "content", "foo.md")),
)
check_allow(
    "file_path that makes realpath raise (embedded null byte)",
    make_payload("Write", os.path.join(REPO_ROOT, "content", "\x00bad")),
)
_relcwd_dir = os.path.realpath(tempfile.mkdtemp())
check_allow(
    "relative file_path + cwd (joins cleanly, resolves outside repo) -> ALLOW",
    make_payload("Edit", os.path.join("content", "foo.md"), cwd=_relcwd_dir),
)

# ---------------------------------------------------------------------------
# 2. Subagent (agent_id present) editing a shippable path -> ALLOW.
# ---------------------------------------------------------------------------
print("-- subagent allow --")
check_allow(
    "subagent (agent_id set) editing shippable content/foo.md -> ALLOW",
    make_payload(
        "Write",
        os.path.join(REPO_ROOT, "content", "foo.md"),
        agent_id="engineer-abc123",
    ),
)

# ---------------------------------------------------------------------------
# 3. Kill-switch -> ALLOW even on a shippable path with no agent_id.
# ---------------------------------------------------------------------------
print("-- kill-switch --")
check_allow(
    "AE_SHIPPABLE_GUARD_DISABLE=1 on shippable path -> ALLOW",
    make_payload("Write", os.path.join(REPO_ROOT, "content", "foo.md")),
    extra_env={"AE_SHIPPABLE_GUARD_DISABLE": "1"},
)

# ---------------------------------------------------------------------------
# 4. Exemptions -> ALLOW (conductor, no agent_id, matcher tool).
# ---------------------------------------------------------------------------
print("-- exemptions --")
check_allow(
    ".agentic/x.json -> ALLOW",
    make_payload("Write", os.path.join(REPO_ROOT, ".agentic", "x.json")),
)
check_allow(
    "docs/planning/x.md -> ALLOW",
    make_payload("Write", os.path.join(REPO_ROOT, "docs", "planning", "x.md")),
)
check_allow(
    "bin/AGENTS.md -> ALLOW",
    make_payload("Edit", os.path.join(REPO_ROOT, "bin", "AGENTS.md")),
)
check_allow(
    "hooks/AGENTS.md -> ALLOW",
    make_payload("Edit", os.path.join(REPO_ROOT, "hooks", "AGENTS.md")),
)
check_allow(
    "AGENTS.md (repo root) -> ALLOW",
    make_payload("Edit", os.path.join(REPO_ROOT, "AGENTS.md")),
)
check_allow(
    "MEMORY.md (repo root) -> ALLOW",
    make_payload("Edit", os.path.join(REPO_ROOT, "MEMORY.md")),
)
check_allow(
    "CLAUDE.md (repo root) -> ALLOW",
    make_payload("Edit", os.path.join(REPO_ROOT, "CLAUDE.md")),
)
_outside_dir = os.path.realpath(tempfile.mkdtemp())
check_allow(
    "path outside the repo -> ALLOW",
    make_payload("Write", os.path.join(_outside_dir, "x.md")),
)

# ---------------------------------------------------------------------------
# 5. Conductor BLOCKED positive: agent_id absent, Write/Edit/MultiEdit,
#    shippable path inside the repo -> DENY.
# ---------------------------------------------------------------------------
print("-- conductor blocked (positive) --")
_target = os.path.join(REPO_ROOT, "content", "foo.md")
check_deny(
    "Write, no agent_id, content/foo.md -> DENY",
    make_payload("Write", _target),
    must_contain=("Shippable-edit guard", _target),
)
check_deny(
    "Edit, no agent_id, content/foo.md -> DENY",
    make_payload("Edit", _target),
    must_contain=("Shippable-edit guard", _target),
)
check_deny(
    "MultiEdit, no agent_id, content/foo.md -> DENY",
    make_payload("MultiEdit", _target),
    must_contain=("Shippable-edit guard", _target),
)
check_deny(
    "Write, null agent_id, content/foo.md -> DENY",
    make_payload("Write", _target, agent_id=None),
    must_contain=("Shippable-edit guard", _target),
)
check_deny(
    "Write, empty-string agent_id, content/foo.md -> DENY",
    make_payload("Write", _target, agent_id=""),
    must_contain=("Shippable-edit guard", _target),
)

# ---------------------------------------------------------------------------
# 6. DS-54 snapshot-meta resolution: hook run from a fake "snapshot" copy
#    with .snapshot-meta.json pointing at a separate fake source_repo_dir
#    must resolve repo_root through the metadata, not through its own
#    on-disk location.
# ---------------------------------------------------------------------------
print("-- snapshot-meta resolution --")


def _run_snapshot_case() -> None:
    global failed, total
    fake_source = os.path.realpath(tempfile.mkdtemp())
    os.makedirs(os.path.join(fake_source, "content"), exist_ok=True)
    os.makedirs(os.path.join(fake_source, ".agentic"), exist_ok=True)

    snapshot_dir = os.path.realpath(tempfile.mkdtemp())
    snapshot_hooks_dir = os.path.join(snapshot_dir, "hooks")
    os.makedirs(snapshot_hooks_dir, exist_ok=True)
    with open(HOOK_PATH, "r", encoding="utf-8") as src:
        hook_source = src.read()
    snapshot_hook_path = os.path.join(snapshot_hooks_dir, "enforce-shippable-edit.py")
    with open(snapshot_hook_path, "w", encoding="utf-8") as dst:
        dst.write(hook_source)

    meta_path = os.path.join(snapshot_dir, ".snapshot-meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"source_repo_dir": fake_source, "source_hash": "x", "snapshotted_at": "x"}, f)

    def _run_from_snapshot(payload: str) -> tuple[int, str, str]:
        env = os.environ.copy()
        env.pop("AE_SHIPPABLE_GUARD_DISABLE", None)
        result = subprocess.run(
            [sys.executable, snapshot_hook_path],
            input=payload,
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    # (a) shippable path under fake_source/content/ -> DENY (repo root
    #     resolved via .snapshot-meta.json, not the snapshot dir itself).
    total += 1
    shippable_target = os.path.join(fake_source, "content", "bar.md")
    rc, stdout, stderr = _run_from_snapshot(
        make_payload("Write", shippable_target)
    )
    ok, reason = is_deny(rc, stdout)
    ok = ok and "Shippable-edit guard" in reason and shippable_target in reason
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] snapshot-meta redirect: shippable path under source_repo_dir -> DENY")
    if not ok:
        print(f"         rc={rc} stdout={stdout!r} stderr={stderr!r}")

    # (b) .agentic/ path under fake_source -> ALLOW (exemption still
    #     applies after the redirect).
    total += 1
    exempt_target = os.path.join(fake_source, ".agentic", "bar.json")
    rc, stdout, stderr = _run_from_snapshot(make_payload("Write", exempt_target))
    ok = is_allow(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] snapshot-meta redirect: .agentic/ path under source_repo_dir -> ALLOW")
    if not ok:
        print(f"         rc={rc} stdout={stdout!r} stderr={stderr!r}")


_run_snapshot_case()

# ---------------------------------------------------------------------------
print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
