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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire

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

# 11. fire-log integration: the advisory (allow_advisory) action must append
#     a well-formed line to <cwd>/.agentic/.enforcement-fires.jsonl; the
#     quiet-allow path (case 9, recent sentinel) must write nothing.
_fire_log_path = os.path.join(AGENTIC_DIR, ".enforcement-fires.jsonl")
try:
    os.remove(_fire_log_path)
except OSError:
    pass

total += 1
remove_sentinel()
run_hook(make_payload("Edit", PLANNING_FILE, TMPDIR), env={})
ok = os.path.exists(_fire_log_path)
if ok:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-planning-artifact-spawn"
        and _fire_lines[0].get("decision") == "allow_advisory"
    )

write_fresh_sentinel()
run_hook(make_payload("Edit", PLANNING_FILE, TMPDIR), env={})
with open(_fire_log_path, "r", encoding="utf-8") as f:
    _fire_lines_after = [json.loads(ln) for ln in f if ln.strip()]
ok = ok and len(_fire_lines_after) == 1  # unchanged - quiet allow logged nothing

status = "PASS" if ok else "FAIL"
if not ok:
    failed += 1
print(f"  [{status}] fire-log integration - advisory writes a line, quiet allow writes nothing")

# 12. Skeptic Critical regression: a raising log_fire() must NOT suppress
# the advisory allow decision. Confirmed failing pre-fix: against a8ded298
# (the commit under review), the copied-hook subprocess exits 0 with EMPTY
# stdout - the advisory is silently lost - because the pre-fix code called
# log_fire() BEFORE print(). See hooks/tests/_fire_log_test_helper.py.
total += 1
remove_sentinel()
_rc_rf, _stdout_rf, _stderr_rf = run_hook_with_raising_log_fire(
    "enforce-planning-artifact-spawn.py",
    make_payload("Edit", PLANNING_FILE, TMPDIR),
)
ok = is_allow_with_advisory(_rc_rf, _stdout_rf)
status = "PASS" if ok else "FAIL"
if not ok:
    failed += 1
print(f"  [{status}] raising log_fire cannot suppress the advisory decision")
if not ok:
    print(f"         stdout: {_stdout_rf!r}")
    print(f"         stderr: {_stderr_rf[-500:]!r}")

# ---------------------------------------------------------------------------
# 13. DS-171 paired writer/reader regression: the sentinel is WRITTEN by
# hooks/pre-tool-use-spawn-emit.js and READ by this hook. Both must resolve
# the SAME repo root from an identically-drifted cwd, or the reader looks
# for the sentinel at a path the writer never wrote to - silently breaking
# the 4h architect-spawn guard (false ALLOW+WARN even though an architect
# spawn genuinely just happened). Uses a REAL git repo (not TMPDIR, which
# has no .git ancestor) with cwd drifted three levels below the root, and
# invokes the actual writer subprocess before the reader.
# ---------------------------------------------------------------------------
total += 1
_git_tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="ds171-paired-"))
os.makedirs(os.path.join(_git_tmpdir, ".git"))
_drifted_cwd = os.path.join(_git_tmpdir, "x", "y", "z")
os.makedirs(_drifted_cwd)
# docs/planning/ lives under the DRIFTED cwd, not the repo root - this
# hook's own planning-dir check is deliberately cwd-relative (payload.cwd
# is normally the repo root itself; the DRIFT under test here is in WHERE
# THE SENTINEL RESOLVES, not in where docs/planning/ lives relative to
# cwd). Placing docs/planning/ at the repo root instead would make the
# hook exit at its early planning-dir check for an unrelated reason,
# never reaching the sentinel-resolution code path this test targets.
_git_planning_dir = os.path.join(_drifted_cwd, "docs", "planning")
os.makedirs(_git_planning_dir)
_git_planning_file = os.path.join(_git_planning_dir, "paired-brief.md")

_writer_path = os.path.join(os.path.dirname(__file__), "..", "pre-tool-use-spawn-emit.js")
_writer_payload = json.dumps(
    {
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "cwd": _drifted_cwd,
        "tool_input": {"subagent_type": "architect"},
    }
)
_writer_proc = subprocess.run(
    ["node", _writer_path], input=_writer_payload, capture_output=True, text=True
)

_reader_rc, _reader_stdout, _reader_stderr = run_hook(
    make_payload("Write", _git_planning_file, _drifted_cwd)
)
paired_ok = (
    _writer_proc.returncode == 0
    and os.path.isfile(os.path.join(_git_tmpdir, ".agentic", ".last-architect-spawn"))
    and not os.path.isdir(os.path.join(_drifted_cwd, ".agentic"))
    and is_allow_quiet(_reader_rc, _reader_stdout)
)
status = "PASS" if paired_ok else "FAIL"
if not paired_ok:
    failed += 1
print(f"  [{status}] paired writer/reader: reader finds the sentinel the writer wrote at the resolved repo root, from an identically-drifted cwd")
if not paired_ok:
    print(f"         writer rc={_writer_proc.returncode} stdout={_writer_proc.stdout!r} stderr={_writer_proc.stderr[-500:]!r}")
    print(f"         reader rc={_reader_rc} stdout={_reader_stdout!r}")

# ---------------------------------------------------------------------------
print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
