# Run with: python3 hooks/tests/test-enforce-nested-worktree-spawn.py
"""
Unit tests for hooks/enforce-nested-worktree-spawn.py.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin and asserts either:
  - SILENT: exit 0, empty stdout (no advisory emitted).
  - ADVISORY: exit 0, permissionDecision "allow" in stdout, reason
    references the DS-190 incident.

This hook is ADVISORY-ONLY (see hooks/AGENTS.md and the hook's own module
docstring) - there is no deny path anywhere, so every case here asserts
either silence or an advisory allow, never a deny.

Uses a REAL `git worktree add` fixture (not a hand-authored `.git` file
gitdir pointer, unlike the read/write worktree-guard sibling tests) since
the ticket calls for exercising the genuine git-worktree shape end to end.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-nested-worktree-spawn.py"
)

_CLEANUP_ROOTS: list = []


def _cleanup_fixtures() -> None:
    for root in _CLEANUP_ROOTS:
        try:
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass


atexit.register(_cleanup_fixtures)


def _run_git(args: list, cwd: str) -> None:
    subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


def make_primary_and_real_worktree():
    """Build a REAL primary git checkout with one commit, then a REAL
    linked worktree via `git worktree add` (mirrors the actual
    .claude/worktrees/agent-<id> layout the live harness produces)."""
    primary = os.path.realpath(tempfile.mkdtemp(prefix="test-nwt-primary-"))
    _run_git(["init", "-q"], cwd=primary)
    with open(os.path.join(primary, "README.md"), "w", encoding="utf-8") as f:
        f.write("primary\n")
    _run_git(["add", "README.md"], cwd=primary)
    _run_git(["commit", "-q", "-m", "init"], cwd=primary)

    worktree = os.path.join(primary, ".claude", "worktrees", "agent-1")
    os.makedirs(os.path.dirname(worktree), exist_ok=True)
    _run_git(
        ["worktree", "add", "-q", "-b", "worktree-agent-1", worktree],
        cwd=primary,
    )

    _CLEANUP_ROOTS.append(primary)
    return primary, worktree


def add_worktree(primary: str, name: str) -> str:
    """Add a further REAL linked worktree off the same primary checkout
    (nested under primary, so it is cleaned up transitively when the
    primary root is removed - no separate cleanup entry needed)."""
    worktree = os.path.join(primary, ".claude", "worktrees", name)
    os.makedirs(os.path.dirname(worktree), exist_ok=True)
    _run_git(
        ["worktree", "add", "-q", "-b", f"worktree-{name}", worktree],
        cwd=primary,
    )
    return worktree


def run_hook(
    payload: str,
    cwd: str,
    extra_env: dict | None = None,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("AE_NESTED_WORKTREE_GUARD_DISABLE", None)  # clean slate per test
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


def is_silent(returncode: int, stdout: str) -> bool:
    return returncode == 0 and stdout.strip() == ""


def is_advisory(returncode: int, stdout: str) -> tuple[bool, str]:
    if returncode != 0:
        return False, ""
    try:
        obj = json.loads(stdout)
        hso = obj.get("hookSpecificOutput", {})
        decision = hso.get("permissionDecision", "")
        reason = hso.get("permissionDecisionReason", "")
        return decision == "allow" and bool(reason), reason
    except Exception:
        return False, ""


def make_payload(
    tool_name: str,
    cwd: str,
    session_id: str | None = "sess-1",
    agent_id: str | None = None,
) -> str:
    obj: dict = {"tool_name": tool_name, "cwd": cwd, "tool_input": {}}
    if session_id is not None:
        obj["session_id"] = session_id
    if agent_id is not None:
        obj["agent_id"] = agent_id
    return json.dumps(obj)


failed = 0
total = 0


def check_silent(label: str, payload: str, cwd: str, extra_env=None) -> None:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, cwd=cwd, extra_env=extra_env)
    ok = is_silent(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload!r}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")


def check_advisory(label: str, payload: str, cwd: str, extra_env=None) -> str:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, cwd=cwd, extra_env=extra_env)
    ok, reason = is_advisory(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload!r}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
    return reason


PRIMARY, WORKTREE = make_primary_and_real_worktree()

# ---------------------------------------------------------------------------
# 1. Main-session spawn from a worktree cwd, no pre-existing .agentic/ ->
#    first call emits an advisory referencing DS-190 AND creates the dir +
#    state file. The precondition (no .agentic/ yet) is asserted, not just
#    commented.
# ---------------------------------------------------------------------------
print("-- main-session, worktree cwd, first call this session -> ADVISORY --")
_agentic_dir = os.path.join(WORKTREE, ".agentic")
assert not os.path.exists(_agentic_dir), (
    "fixture precondition violated: .agentic/ must not exist before the "
    "first hook invocation"
)
_reason1 = check_advisory(
    "first Task spawn from worktree cwd this session -> advisory allow",
    make_payload("Task", WORKTREE, session_id="sess-1"),
    cwd=WORKTREE,
)
assert "DS-190" in _reason1, f"advisory reason missing DS-190 reference: {_reason1!r}"

_state_path = os.path.join(_agentic_dir, ".nested-worktree-spawn-sess-1.json")
total += 1
_ok_state = os.path.isdir(_agentic_dir) and os.path.isfile(_state_path)
status = "PASS" if _ok_state else "FAIL"
if not _ok_state:
    failed += 1
print(f"  [{status}] first call creates .agentic/ dir and state file")
if not _ok_state:
    print(f"         .agentic/ exists: {os.path.isdir(_agentic_dir)}")
    print(f"         state file exists: {os.path.isfile(_state_path)}")

# ---------------------------------------------------------------------------
# 2. Second call, same session_id/cwd -> silent (already warned).
# ---------------------------------------------------------------------------
print("-- second call, same session_id/cwd -> SILENT --")
check_silent(
    "second Task spawn from worktree cwd, same session -> silent",
    make_payload("Task", WORKTREE, session_id="sess-1"),
    cwd=WORKTREE,
)

# ---------------------------------------------------------------------------
# 3. Main-session spawn from the PRIMARY checkout (not a worktree) -> silent.
# ---------------------------------------------------------------------------
print("-- main-session, primary-checkout cwd -> SILENT --")
check_silent(
    "Task spawn from primary checkout cwd -> silent",
    make_payload("Agent", PRIMARY, session_id="sess-2"),
    cwd=PRIMARY,
)

# ---------------------------------------------------------------------------
# 4. Subagent (agent_id present) spawning from a worktree cwd -> silent.
#    This hook only concerns the conductor's own spawn axis.
# ---------------------------------------------------------------------------
print("-- agent_id present, worktree cwd -> SILENT --")
check_silent(
    "subagent (agent_id present) spawn from worktree cwd -> silent",
    make_payload("Agent", WORKTREE, session_id="sess-3", agent_id="wk-1"),
    cwd=WORKTREE,
)

# ---------------------------------------------------------------------------
# 5. Non-Task/Agent tool_name -> silent (passthrough).
# ---------------------------------------------------------------------------
print("-- other tool_name -> SILENT --")
check_silent(
    "Write tool_name from worktree cwd -> silent (not Task/Agent)",
    make_payload("Write", WORKTREE, session_id="sess-4"),
    cwd=WORKTREE,
)

# ---------------------------------------------------------------------------
# 6. Malformed stdin -> exit 0, silent.
# ---------------------------------------------------------------------------
print("-- malformed stdin -> SILENT (fail-open) --")
check_silent("empty stdin", "", cwd=WORKTREE)
check_silent("malformed JSON", "not-json-at-all{{{{", cwd=WORKTREE)
check_silent("JSON but not an object", json.dumps([1, 2, 3]), cwd=WORKTREE)

# ---------------------------------------------------------------------------
# 7. Kill-switch set -> silent unconditionally, even on an otherwise-
#    advisory-worthy spawn.
# ---------------------------------------------------------------------------
print("-- kill-switch -> SILENT unconditionally --")
check_silent(
    "AE_NESTED_WORKTREE_GUARD_DISABLE=1 on an otherwise-advisory spawn -> silent",
    make_payload("Task", WORKTREE, session_id="sess-5"),
    cwd=WORKTREE,
    extra_env={"AE_NESTED_WORKTREE_GUARD_DISABLE": "1"},
)

# ---------------------------------------------------------------------------
# 8. Missing/empty cwd -> silent.
# ---------------------------------------------------------------------------
print("-- missing/empty cwd -> SILENT --")
check_silent(
    "cwd absent from payload -> silent",
    json.dumps({"tool_name": "Task", "session_id": "sess-6", "tool_input": {}}),
    cwd=WORKTREE,
)
check_silent(
    "cwd blank string -> silent",
    make_payload("Task", "", session_id="sess-7"),
    cwd=WORKTREE,
)

# ---------------------------------------------------------------------------
# 9. Missing/empty session_id -> silent (no dedup key -> skip enforcement).
# ---------------------------------------------------------------------------
print("-- missing/empty session_id -> SILENT --")
check_silent(
    "session_id absent from payload -> silent",
    json.dumps({"tool_name": "Task", "cwd": WORKTREE, "tool_input": {}}),
    cwd=WORKTREE,
)
check_silent(
    "session_id blank string -> silent",
    make_payload("Task", WORKTREE, session_id=""),
    cwd=WORKTREE,
)

# ---------------------------------------------------------------------------
# 10. mkdir/stat I/O failure path fails open TOWARD emitting. `.agentic` is
#     created as a FILE (not a directory) so
#     `Path(cwd, ".agentic").mkdir(parents=True, exist_ok=True)` raises
#     (a file already occupies that path) - the exception must be swallowed
#     and the hook must still proceed to emit the advisory.
# ---------------------------------------------------------------------------
print("-- .agentic path occupied by a file (mkdir fails) -> ADVISORY still fires --")
_wt_io_fail = add_worktree(PRIMARY, "agent-io-fail")
_agentic_blocker = os.path.join(_wt_io_fail, ".agentic")
with open(_agentic_blocker, "w", encoding="utf-8") as f:
    f.write("not a directory\n")
assert os.path.isfile(_agentic_blocker), (
    "fixture precondition violated: .agentic must be a file, not a dir"
)
_reason_io = check_advisory(
    "Task spawn where .agentic mkdir fails (blocked by a file) -> advisory still fires",
    make_payload("Task", _wt_io_fail, session_id="sess-io-fail"),
    cwd=_wt_io_fail,
)
assert "DS-190" in _reason_io, (
    f"advisory reason missing DS-190 reference: {_reason_io!r}"
)
total += 1
_ok_no_state = os.path.isfile(_agentic_blocker) and not os.path.isdir(
    _agentic_blocker
)
status = "PASS" if _ok_no_state else "FAIL"
if not _ok_no_state:
    failed += 1
print(f"  [{status}] mkdir failure leaves .agentic as the pre-existing file (no persistence)")

# ---------------------------------------------------------------------------
# 11. Same session_id, DIFFERENT worktree cwd -> re-fires (dedup key is
#     per-worktree, keyed on cwd, not solely on session_id).
# ---------------------------------------------------------------------------
print("-- same session_id, different worktree cwd -> ADVISORY re-fires --")
_wt_second = add_worktree(PRIMARY, "agent-2")
_reason_dedup = check_advisory(
    "Task spawn from a SECOND worktree, same session_id already used on the first -> advisory",
    make_payload("Task", _wt_second, session_id="sess-1"),
    cwd=_wt_second,
)
assert "DS-190" in _reason_dedup, (
    f"advisory reason missing DS-190 reference: {_reason_dedup!r}"
)

print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
