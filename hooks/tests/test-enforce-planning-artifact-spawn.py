# Run with: python3 hooks/tests/test-enforce-planning-artifact-spawn.py
"""
Unit tests for hooks/enforce-planning-artifact-spawn.py.

Each case calls run_case() which sets up filesystem state, pipes a JSON
payload into the hook via stdin, and asserts:
  ALLOW+WARN  - exit 0, permissionDecision "allow", advisory text in reason
  ALLOW+QUIET - exit 0 and no ADVISORY in hookSpecificOutput (silently allowed)

The hook MUST NEVER emit permissionDecision "deny" or "ask" under any input.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-planning-artifact-spawn.py"
)


def run_hook(payload: str, env: dict = None) -> tuple:
    """Returns (returncode, stdout, stderr)."""
    run_env = os.environ.copy()
    # Remove any inherited kill-switch so tests run with a clean env.
    run_env.pop("AE_PLANNING_GUARD_DISABLE", None)
    if env:
        run_env.update(env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=run_env,
    )
    return result.returncode, result.stdout, result.stderr


def parse_output(stdout: str):
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except Exception:
        return {}


def is_never_deny(returncode: int, stdout: str) -> bool:
    """Invariant: hook must exit 0 and never emit deny or ask."""
    if returncode != 0:
        return False
    obj = parse_output(stdout)
    decision = obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
    return decision not in ("deny", "ask")


def is_allow_with_advisory(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    obj = parse_output(stdout)
    hso = obj.get("hookSpecificOutput", {})
    return (
        hso.get("permissionDecision") == "allow"
        and "ADVISORY" in hso.get("permissionDecisionReason", "")
    )


def is_allow_quiet(returncode: int, stdout: str) -> bool:
    """Silently allowed: exit 0, no deny, no ADVISORY output."""
    if returncode != 0:
        return False
    obj = parse_output(stdout)
    if not obj:
        return True
    hso = obj.get("hookSpecificOutput", {})
    decision = hso.get("permissionDecision", "")
    reason = hso.get("permissionDecisionReason", "")
    return decision not in ("deny", "ask") and "ADVISORY" not in reason


def make_payload(tool_name: str, file_path: str, cwd: str) -> str:
    return json.dumps(
        {
            "tool_name": tool_name,
            "cwd": cwd,
            "tool_input": {"file_path": file_path},
        }
    )


# ---------------------------------------------------------------------------
# Temp directory setup.
# Use os.path.realpath to resolve /var -> /private/var on macOS so test
# paths match what the hook resolves when it canonicalizes cwd from payload.
# ---------------------------------------------------------------------------
_raw_tmpdir = tempfile.mkdtemp()
TMPDIR = os.path.realpath(_raw_tmpdir)
PLANNING_DIR = os.path.join(TMPDIR, "docs", "planning")
os.makedirs(PLANNING_DIR, exist_ok=True)
AGENTIC_DIR = os.path.join(TMPDIR, ".agentic")
os.makedirs(AGENTIC_DIR, exist_ok=True)
SRC_DIR = os.path.join(TMPDIR, "src")
os.makedirs(SRC_DIR, exist_ok=True)

SENTINEL_PATH = os.path.join(AGENTIC_DIR, ".last-architect-spawn")
PLANNING_FILE = os.path.join(PLANNING_DIR, "my-brief.md")
NON_PLANNING_FILE = os.path.join(SRC_DIR, "index.ts")


def write_fresh_sentinel():
    with open(SENTINEL_PATH, "w") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def write_stale_sentinel():
    with open(SENTINEL_PATH, "w") as f:
        f.write("2000-01-01T00:00:00Z")
    stale_ts = time.time() - (5 * 3600)
    os.utime(SENTINEL_PATH, (stale_ts, stale_ts))


def remove_sentinel():
    try:
        os.remove(SENTINEL_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Tests defined as imperative functions that set up state before invoking.
# ---------------------------------------------------------------------------
failed = 0
total = 0


def run_case(label: str, setup_fn, payload: str, env: dict, expected: str) -> None:
    global failed, total
    total += 1
    setup_fn()  # set up filesystem state for this case
    rc, stdout, stderr = run_hook(payload, env=env)

    # Invariant: hook must NEVER deny.
    if not is_never_deny(rc, stdout):
        print(f"  [FAIL] {label}")
        print(f"         INVARIANT VIOLATED: deny or non-zero exit")
        print(f"         rc={rc} stdout={stdout!r}")
        failed += 1
        return

    if expected == "ALLOW+WARN":
        ok = is_allow_with_advisory(rc, stdout)
    else:
        ok = is_allow_quiet(rc, stdout)

    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
        print(f"         expected: {expected}")


# 1. Kill-switch: AE_PLANNING_GUARD_DISABLE=1 -> ALLOW+QUIET regardless.
run_case(
    "Kill-switch active (Write to planning/) -> ALLOW+QUIET",
    setup_fn=remove_sentinel,
    payload=make_payload("Write", PLANNING_FILE, TMPDIR),
    env={"AE_PLANNING_GUARD_DISABLE": "1"},
    expected="ALLOW+QUIET",
)

# 2. Recent sentinel (<4h) -> ALLOW+QUIET (no advisory).
run_case(
    "Recent sentinel (<4h), Write to planning/ -> ALLOW+QUIET",
    setup_fn=write_fresh_sentinel,
    payload=make_payload("Write", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+QUIET",
)

# 3. Absent sentinel -> ALLOW+WARN (advisory emitted).
run_case(
    "Absent sentinel, Write to planning/ -> ALLOW+WARN",
    setup_fn=remove_sentinel,
    payload=make_payload("Write", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+WARN",
)

# 4. Stale sentinel (>4h) -> ALLOW+WARN (advisory emitted).
run_case(
    "Stale sentinel (>4h), Write to planning/ -> ALLOW+WARN",
    setup_fn=write_stale_sentinel,
    payload=make_payload("Write", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+WARN",
)

# 5. Target NOT under docs/planning/ -> ALLOW+QUIET.
run_case(
    "Target not under docs/planning/ (absent sentinel) -> ALLOW+QUIET",
    setup_fn=remove_sentinel,
    payload=make_payload("Write", NON_PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+QUIET",
)

# 6. Malformed stdin -> fail-open, ALLOW+QUIET.
run_case(
    "Malformed stdin -> fail-open ALLOW+QUIET",
    setup_fn=lambda: None,
    payload="not-json-at-all{{{{",
    env={},
    expected="ALLOW+QUIET",
)

# 7. Missing cwd -> fail-open, ALLOW+QUIET.
run_case(
    "Missing cwd -> fail-open ALLOW+QUIET",
    setup_fn=remove_sentinel,
    payload=json.dumps({"tool_name": "Write", "tool_input": {"file_path": PLANNING_FILE}}),
    env={},
    expected="ALLOW+QUIET",
)

# 8. Edit tool, absent sentinel -> ALLOW+WARN.
run_case(
    "Edit tool, absent sentinel, planning/ target -> ALLOW+WARN",
    setup_fn=remove_sentinel,
    payload=make_payload("Edit", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+WARN",
)

# 9. Edit tool, recent sentinel -> ALLOW+QUIET.
run_case(
    "Edit tool, recent sentinel (<4h), planning/ target -> ALLOW+QUIET",
    setup_fn=write_fresh_sentinel,
    payload=make_payload("Edit", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+QUIET",
)

# 10. Non-Write/Edit tool (Read) -> ALLOW+QUIET.
run_case(
    "Non-Write/Edit tool (Read) -> ALLOW+QUIET",
    setup_fn=remove_sentinel,
    payload=make_payload("Read", PLANNING_FILE, TMPDIR),
    env={},
    expected="ALLOW+QUIET",
)

# ---------------------------------------------------------------------------
print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
