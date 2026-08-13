# Run with: python3 hooks/tests/test-enforce-worktree-write.py
"""
Unit tests for hooks/enforce-worktree-write.py.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin, with CLAUDE_PROJECT_DIR set as an env var (never a payload field),
and asserts ALLOW (exit 0, no deny in stdout) or DENY (exit 0,
permissionDecision "deny" in stdout, reason mentions the guard + path).

Mirrors hooks/tests/test-enforce-worktree-read.py field-for-field, adapted
for the Write/Edit/MultiEdit matcher set instead of Read.

The fail-open matrix is the primary invariant under test: this hook must
NEVER crash-to-block. Every case in the fail-open sections asserts
is_allow() - none of them may deny, and none may exit non-zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-worktree-write.py"
)


def make_primary_and_worktree():
    """Build a fake primary checkout with a nested isolation worktree,
    mirroring the real .claude/worktrees/agent-<id> layout (worktrees live
    INSIDE the primary root)."""
    primary = os.path.realpath(tempfile.mkdtemp(prefix="test-wtwrite-primary-"))
    os.makedirs(os.path.join(primary, "content"), exist_ok=True)
    with open(os.path.join(primary, "content", "foo.md"), "w", encoding="utf-8") as f:
        f.write("primary content\n")

    worktree = os.path.join(primary, ".claude", "worktrees", "agent-1")
    os.makedirs(os.path.join(worktree, "content"), exist_ok=True)
    with open(os.path.join(worktree, "content", "own.md"), "w", encoding="utf-8") as f:
        f.write("worktree content\n")

    return primary, worktree


def run_hook(
    payload: str,
    primary_root: str | None = None,
    extra_env: dict | None = None,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("AE_WORKTREE_WRITE_GUARD_DISABLE", None)  # clean slate per test
    if primary_root is not None:
        env["CLAUDE_PROJECT_DIR"] = primary_root
    else:
        env.pop("CLAUDE_PROJECT_DIR", None)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        cwd=cwd or tempfile.mkdtemp(prefix="test-enforce-worktree-write-cwd-"),
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
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


def make_payload(
    tool_name: str,
    file_path: str,
    agent_id: str | None = None,
    agent_type: str | None = None,
    cwd: str = "",
) -> str:
    tool_input: dict = {"file_path": file_path}
    if tool_name == "Write":
        tool_input["content"] = "x"
    elif tool_name == "Edit":
        tool_input["old_string"] = "a"
        tool_input["new_string"] = "b"
    elif tool_name == "MultiEdit":
        tool_input["edits"] = [{"old_string": "a", "new_string": "b"}]
    obj: dict = {"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}
    if agent_id is not None:
        obj["agent_id"] = agent_id
    if agent_type is not None:
        obj["agent_type"] = agent_type
    return json.dumps(obj)


failed = 0
total = 0


def check_allow(label: str, payload: str, primary_root=None, extra_env=None, cwd=None) -> None:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, primary_root=primary_root, extra_env=extra_env, cwd=cwd)
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


def check_deny(
    label: str,
    payload: str,
    primary_root=None,
    extra_env=None,
    cwd=None,
    must_contain: tuple[str, ...] = (),
) -> None:
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, primary_root=primary_root, extra_env=extra_env, cwd=cwd)
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


PRIMARY, WORKTREE = make_primary_and_worktree()
PRIMARY_TARGET = os.path.join(PRIMARY, "content", "foo.md")
WORKTREE_OWN_TARGET = os.path.join(WORKTREE, "content", "own.md")

# ---------------------------------------------------------------------------
# 1. Main-session call (no agent_id/agent_type) writing anywhere -> ALLOW.
# ---------------------------------------------------------------------------
print("-- main-session (no agent_id/agent_type) --")
check_allow(
    "main session writing primary content -> ALLOW",
    make_payload("Write", PRIMARY_TARGET, cwd=PRIMARY),
    primary_root=PRIMARY,
)
check_allow(
    "main session writing arbitrary temp path -> ALLOW",
    make_payload("Write", os.path.join(tempfile.mkdtemp(), "x.md"), cwd=PRIMARY),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 2. Subagent whose cwd == primary root (non-isolated) -> ALLOW.
# ---------------------------------------------------------------------------
print("-- subagent not worktree-isolated (cwd == primary_root) --")
check_allow(
    "subagent cwd==primary_root writing primary content -> ALLOW",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=PRIMARY),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 3. Worktree-isolated subagent writing inside its OWN worktree -> ALLOW.
# ---------------------------------------------------------------------------
print("-- worktree-isolated subagent, own worktree -> ALLOW --")
check_allow(
    "subagent writing its own worktree file -> ALLOW",
    make_payload("Write", WORKTREE_OWN_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 4. Worktree-isolated subagent writing the PRIMARY checkout -> DENY
#    (the violation case). Exercised across all three matcher tool names.
# ---------------------------------------------------------------------------
print("-- worktree-isolated subagent, primary checkout -> DENY --")
for _tool_name in ("Write", "Edit", "MultiEdit"):
    check_deny(
        f"subagent {_tool_name} on primary content while worktree-isolated -> DENY",
        make_payload(_tool_name, PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
        primary_root=PRIMARY,
        must_contain=("Worktree-write guard", PRIMARY_TARGET, "wk-1", "agent_type='engineer'", _tool_name),
    )

# agent_type must NOT appear in the deny reason when absent from the
# payload (the field is optional context, never a gate on its own).
check_deny(
    "subagent with no agent_type in payload -> DENY, reason omits agent_type=",
    json.dumps(
        {
            "tool_name": "Write",
            "agent_id": "wk-1",
            "cwd": WORKTREE,
            "tool_input": {"file_path": PRIMARY_TARGET, "content": "x"},
        }
    ),
    primary_root=PRIMARY,
    must_contain=("Worktree-write guard", "wk-1"),
)
_rc_noat, _stdout_noat, _stderr_noat = run_hook(
    json.dumps(
        {
            "tool_name": "Write",
            "agent_id": "wk-1",
            "cwd": WORKTREE,
            "tool_input": {"file_path": PRIMARY_TARGET, "content": "x"},
        }
    ),
    primary_root=PRIMARY,
)
total += 1
_, _reason_noat = is_deny(_rc_noat, _stdout_noat)
_ok_noat = "agent_type=" not in _reason_noat
status = "PASS" if _ok_noat else "FAIL"
if not _ok_noat:
    failed += 1
print(f"  [{status}] absent agent_type produces no agent_type= substring in deny reason")
if not _ok_noat:
    print(f"         reason: {_reason_noat!r}")

# ---------------------------------------------------------------------------
# 5. Path outside the primary root entirely -> ALLOW.
# ---------------------------------------------------------------------------
print("-- outside primary root entirely -> ALLOW --")
_outside_dir = os.path.realpath(tempfile.mkdtemp())
check_allow(
    "subagent writing a path outside primary_root entirely -> ALLOW",
    make_payload(
        "Write",
        os.path.join(_outside_dir, "y.md"),
        agent_id="wk-1",
        agent_type="engineer",
        cwd=WORKTREE,
    ),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 6. Symlink / non-normalized path that resolves into the primary checkout
#    -> still caught (realpath normalization on all three operands).
# ---------------------------------------------------------------------------
print("-- symlink normalization -> still caught --")
_symlink_dir = os.path.realpath(tempfile.mkdtemp(prefix="test-wtwrite-symlink-"))
_symlink_path = os.path.join(_symlink_dir, "sneaky.md")
os.symlink(PRIMARY_TARGET, _symlink_path)
check_deny(
    "symlink pointing at primary content, written from worktree -> DENY",
    make_payload("Write", _symlink_path, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
    must_contain=("Worktree-write guard", PRIMARY_TARGET),
)

# A non-normalized path (../ segments) that resolves inside primary_root
# via the worktree itself must still be recognized as "own worktree" ->
# ALLOW.
_dotdot_path = os.path.join(WORKTREE, "content", "..", "content", "own.md")
check_allow(
    "dotdot-relative path resolving to own worktree file -> ALLOW",
    make_payload("Write", _dotdot_path, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 6b. Non-canonical (symlinked) primary_root and caller_root operands must
#     still be realpath-normalized before the containment test.
# ---------------------------------------------------------------------------
print("-- non-canonical symlink primary_root/caller_root still normalized --")
_symop_primary, _symop_worktree = make_primary_and_worktree()
_symop_target = os.path.join(_symop_primary, "content", "foo.md")

# primary_root operand is a symlink alias; caller_root operand is canonical.
_primary_alias_parent = tempfile.mkdtemp(prefix="test-wtwrite-primary-alias-")
_primary_alias = os.path.join(_primary_alias_parent, "primary-link")
os.symlink(_symop_primary, _primary_alias)
check_deny(
    "CLAUDE_PROJECT_DIR is a non-canonical symlink alias -> still DENY",
    make_payload("Write", _symop_target, agent_id="wk-1", agent_type="engineer", cwd=_symop_worktree),
    primary_root=_primary_alias,
    must_contain=("Worktree-write guard",),
)

# caller_root operand (payload cwd) is a symlink alias; primary_root operand
# is canonical.
_worktree_alias_parent = tempfile.mkdtemp(prefix="test-wtwrite-worktree-alias-")
_worktree_alias = os.path.join(_worktree_alias_parent, "worktree-link")
os.symlink(_symop_worktree, _worktree_alias)
check_deny(
    "payload cwd is a non-canonical symlink alias -> still DENY",
    make_payload("Write", _symop_target, agent_id="wk-1", agent_type="engineer", cwd=_worktree_alias),
    primary_root=_symop_primary,
    must_contain=("Worktree-write guard",),
)

# ---------------------------------------------------------------------------
# 7. Kill-switch set -> ALLOW unconditionally.
# ---------------------------------------------------------------------------
print("-- kill-switch --")
check_allow(
    "AE_WORKTREE_WRITE_GUARD_DISABLE=1 on an otherwise-violating write -> ALLOW",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
    extra_env={"AE_WORKTREE_WRITE_GUARD_DISABLE": "1"},
)

# ---------------------------------------------------------------------------
# 8. Fail-open matrix: absent/malformed tool_input, absent cwd, absent
#    CLAUDE_PROJECT_DIR, unparseable stdin.
# ---------------------------------------------------------------------------
print("-- fail-open matrix --")
check_allow("empty stdin", "", primary_root=PRIMARY)
check_allow("malformed JSON", "not-json-at-all{{{{", primary_root=PRIMARY)
check_allow("JSON but not an object", json.dumps([1, 2, 3]), primary_root=PRIMARY)
check_allow(
    "non-guarded tool (Read)",
    make_payload("Read", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
)
check_allow(
    "missing tool_input",
    json.dumps({"tool_name": "Write", "agent_id": "wk-1", "agent_type": "engineer", "cwd": WORKTREE}),
    primary_root=PRIMARY,
)
check_allow(
    "missing file_path",
    json.dumps(
        {
            "tool_name": "Write",
            "agent_id": "wk-1",
            "agent_type": "engineer",
            "cwd": WORKTREE,
            "tool_input": {},
        }
    ),
    primary_root=PRIMARY,
)
check_allow(
    "blank file_path",
    json.dumps(
        {
            "tool_name": "Write",
            "agent_id": "wk-1",
            "agent_type": "engineer",
            "cwd": WORKTREE,
            "tool_input": {"file_path": "   "},
        }
    ),
    primary_root=PRIMARY,
)
check_allow(
    "absent cwd (blank string default from make_payload)",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=""),
    primary_root=PRIMARY,
)
check_allow(
    "cwd set but not a real directory",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd="/no/such/dir/at/all"),
    primary_root=PRIMARY,
)
check_allow(
    "CLAUDE_PROJECT_DIR absent from env entirely",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=None,
)
check_allow(
    "CLAUDE_PROJECT_DIR set but not a real directory",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root="/no/such/primary/dir",
)
check_allow(
    "agent_id present but blank string -> treated as absent (main session)",
    make_payload("Write", PRIMARY_TARGET, agent_id="", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
)
check_allow(
    "agent_id null -> treated as absent (main session)",
    json.dumps(
        {
            "tool_name": "Write",
            "agent_id": None,
            "agent_type": "engineer",
            "cwd": WORKTREE,
            "tool_input": {"file_path": PRIMARY_TARGET, "content": "x"},
        }
    ),
    primary_root=PRIMARY,
)
check_allow(
    "file_path with embedded null byte -> realpath raises -> fail-open",
    make_payload(
        "Write",
        os.path.join(PRIMARY, "content", "\x00bad"),
        agent_id="wk-1",
        agent_type="engineer",
        cwd=WORKTREE,
    ),
    primary_root=PRIMARY,
)
check_allow(
    "caller_root not a subdirectory of primary_root (sibling temp dirs)",
    make_payload(
        "Write",
        PRIMARY_TARGET,
        agent_id="wk-1",
        agent_type="engineer",
        cwd=os.path.realpath(tempfile.mkdtemp(prefix="test-wtwrite-sibling-")),
    ),
    primary_root=PRIMARY,
)

# ---------------------------------------------------------------------------
# 9. Config file absent -> guard still functions with an empty exemption
#    list (the primary DENY case above already ran with no config.json
#    present at all, proving this - re-assert explicitly here).
# ---------------------------------------------------------------------------
print("-- config absent -> empty exemption list, guard still functions --")
assert not os.path.exists(os.path.join(PRIMARY, ".agentic", "config.json"))
check_deny(
    "no config.json present at all -> guard still denies the violation",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    primary_root=PRIMARY,
    must_contain=("Worktree-write guard",),
)

# ---------------------------------------------------------------------------
# 10. A configured exemption suppresses an otherwise-violating write. Uses
#     the SEPARATE key worktree_write_guard_exemptions (not the read
#     guard's worktree_read_guard_exemptions).
# ---------------------------------------------------------------------------
print("-- configured exemption suppresses an otherwise-violating write --")
_EXEMPT_PRIMARY, _EXEMPT_WORKTREE = make_primary_and_worktree()
os.makedirs(os.path.join(_EXEMPT_PRIMARY, ".agentic"), exist_ok=True)
with open(
    os.path.join(_EXEMPT_PRIMARY, ".agentic", "config.json"), "w", encoding="utf-8"
) as f:
    json.dump({"worktree_write_guard_exemptions": ["content"]}, f)
_exempt_target = os.path.join(_EXEMPT_PRIMARY, "content", "foo.md")
check_allow(
    "target under a configured exemption prefix -> ALLOW",
    make_payload("Write", _exempt_target, agent_id="wk-1", agent_type="engineer", cwd=_EXEMPT_WORKTREE),
    primary_root=_EXEMPT_PRIMARY,
)
# A sibling path that merely starts with the same characters as the exempt
# prefix but is not path-segment-aligned must NOT be exempted.
os.makedirs(os.path.join(_EXEMPT_PRIMARY, "content-internal"), exist_ok=True)
with open(
    os.path.join(_EXEMPT_PRIMARY, "content-internal", "bar.md"), "w", encoding="utf-8"
) as f:
    f.write("x")
check_deny(
    "sibling path sharing a string prefix with the exemption (not segment-aligned) -> DENY",
    make_payload(
        "Write",
        os.path.join(_EXEMPT_PRIMARY, "content-internal", "bar.md"),
        agent_id="wk-1",
        agent_type="engineer",
        cwd=_EXEMPT_WORKTREE,
    ),
    primary_root=_EXEMPT_PRIMARY,
    must_contain=("Worktree-write guard",),
)
# The READ guard's exemption key must NOT suppress a write violation - the
# two keys are deliberately separate (different risk profile per axis).
_READONLY_EXEMPT_PRIMARY, _READONLY_EXEMPT_WORKTREE = make_primary_and_worktree()
os.makedirs(os.path.join(_READONLY_EXEMPT_PRIMARY, ".agentic"), exist_ok=True)
with open(
    os.path.join(_READONLY_EXEMPT_PRIMARY, ".agentic", "config.json"), "w", encoding="utf-8"
) as f:
    json.dump({"worktree_read_guard_exemptions": ["content"]}, f)
check_deny(
    "read-guard exemption key does not suppress a write violation -> DENY",
    make_payload(
        "Write",
        os.path.join(_READONLY_EXEMPT_PRIMARY, "content", "foo.md"),
        agent_id="wk-1",
        agent_type="engineer",
        cwd=_READONLY_EXEMPT_WORKTREE,
    ),
    primary_root=_READONLY_EXEMPT_PRIMARY,
    must_contain=("Worktree-write guard",),
)
# Malformed config.json (not JSON) -> fail-open toward empty exemptions,
# guard still functions.
_MALFORMED_PRIMARY, _MALFORMED_WORKTREE = make_primary_and_worktree()
os.makedirs(os.path.join(_MALFORMED_PRIMARY, ".agentic"), exist_ok=True)
with open(
    os.path.join(_MALFORMED_PRIMARY, ".agentic", "config.json"), "w", encoding="utf-8"
) as f:
    f.write("not-json-at-all{{{{")
check_deny(
    "malformed config.json -> empty exemption list, guard still denies",
    make_payload(
        "Write",
        os.path.join(_MALFORMED_PRIMARY, "content", "foo.md"),
        agent_id="wk-1",
        agent_type="engineer",
        cwd=_MALFORMED_WORKTREE,
    ),
    primary_root=_MALFORMED_PRIMARY,
    must_contain=("Worktree-write guard",),
)

# ---------------------------------------------------------------------------
# fire-log integration: a DENY action must append a well-formed line to
# <cwd>/.agentic/.enforcement-fires.jsonl; a main-session ALLOW (agent_id
# absent) must write nothing.
# ---------------------------------------------------------------------------
print("-- fire-log integration --")
total += 1
_fire_primary, _fire_worktree = make_primary_and_worktree()
_fire_target = os.path.join(_fire_primary, "content", "foo.md")
_fire_log_path = os.path.join(_fire_worktree, ".agentic", ".enforcement-fires.jsonl")

_fire_payload = json.dumps(
    {
        "tool_name": "Write",
        "agent_id": "wk-1",
        "agent_type": "engineer",
        "cwd": _fire_worktree,
        "tool_input": {"file_path": _fire_target, "content": "x"},
    }
)
rc, stdout, stderr = run_hook(_fire_payload, primary_root=_fire_primary, cwd=_fire_worktree)
ok = os.path.exists(_fire_log_path)
if ok:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-worktree-write"
        and _fire_lines[0].get("decision") == "deny"
    )
status = "PASS" if ok else "FAIL"
if not ok:
    failed += 1
print(f"  [{status}] deny writes a fire-log line")
if not ok:
    print(f"         rc={rc} stdout={stdout!r} stderr={stderr!r}")

# Main-session ALLOW (agent_id absent) -> no fire-log line written.
total += 1
_main_payload = json.dumps(
    {"tool_name": "Write", "cwd": _fire_worktree, "tool_input": {"file_path": _fire_target, "content": "x"}}
)
run_hook(_main_payload, primary_root=_fire_primary, cwd=_fire_worktree)
try:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines_after = [json.loads(ln) for ln in f if ln.strip()]
    ok = len(_fire_lines_after) == 1  # unchanged
except Exception:
    ok = False
status = "PASS" if ok else "FAIL"
if not ok:
    failed += 1
print(f"  [{status}] main-session allow writes nothing additional")

# ---------------------------------------------------------------------------
# Raising log_fire() must NOT suppress the deny decision (same regression
# pattern as test-enforce-shippable-edit.py's Critical fix).
# ---------------------------------------------------------------------------
print("-- raising log_fire cannot suppress the deny decision --")
total += 1
_rc_rf, _stdout_rf, _stderr_rf = run_hook_with_raising_log_fire(
    "enforce-worktree-write.py",
    make_payload("Write", PRIMARY_TARGET, agent_id="wk-1", agent_type="engineer", cwd=WORKTREE),
    extra_env={"CLAUDE_PROJECT_DIR": PRIMARY},
)
ok = _rc_rf == 0 and not is_allow(_rc_rf, _stdout_rf)
status = "PASS" if ok else "FAIL"
if not ok:
    failed += 1
print(f"  [{status}] raising log_fire cannot suppress the deny decision")
if not ok:
    print(f"         stdout: {_stdout_rf!r}")
    print(f"         stderr: {_stderr_rf[-500:]!r}")

print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
