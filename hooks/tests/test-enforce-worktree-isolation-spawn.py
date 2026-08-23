# Run with: python3 hooks/tests/test-enforce-worktree-isolation-spawn.py
"""
Unit tests for hooks/enforce-worktree-isolation-spawn.py.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin and asserts ALLOW (exit 0, no deny in stdout) or DENY (exit 0, deny
in stdout, reason names the isolation fix).

Fixture note: FIXTURE_WITH_ISOLATION and FIXTURE_WITHOUT_ISOLATION below
are built from a REAL PreToolUse stdin capture obtained this session
(project-scoped capture hook, 2026-08-23; raw log gitignored, not shipped
with this repo). Three `tool_name: "Agent"` records were captured: two
with-isolation spawns, `tool_input` keys `['description', 'isolation',
'prompt', 'subagent_type']` with `isolation == "worktree"`; and one
without-isolation spawn, `tool_input` keys `['description', 'prompt',
'subagent_type']` - no `isolation` key at all. This corroborates
`hooks/AGENTS.md` §"Spawn payload mechanics"'s schema-derived `isolation` key listing with an
actual payload capture. There is no capture for `tool_name: "Task"` - see
hooks/enforce-worktree-isolation-spawn.py's Trigger docstring note for why
enforcement is scoped to "Agent" only and case 6 below asserts ALLOW for
"Task".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-worktree-isolation-spawn.py"
)

# No payload below sets "cwd", so the hook's best-effort fire-logging helper
# falls back to os.getcwd(). Pin the child process's cwd to an ephemeral temp
# dir so a DENY-path fire-log write never touches this repo's own .agentic/.
_TEST_CWD = tempfile.mkdtemp(prefix="test-enforce-worktree-isolation-spawn-")


def run_hook(payload: str, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=_TEST_CWD,
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


# ---------------------------------------------------------------------------
# Transcript-derived fixture shapes (see module docstring for provenance).
# ---------------------------------------------------------------------------
FIXTURE_WITH_ISOLATION = {
    "tool_name": "Agent",
    "tool_input": {
        "description": "Implement the fix",
        "isolation": "worktree",
        "prompt": "...",
        "subagent_type": "engineer",
    },
}
FIXTURE_WITHOUT_ISOLATION = {
    "tool_name": "Agent",
    "tool_input": {
        "description": "Implement the fix",
        "prompt": "...",
        "subagent_type": "engineer",
    },
}


def _payload(subagent_type: str, isolation=..., tool_name: str = "Agent") -> str:
    tool_input = {"description": "d", "prompt": "p", "subagent_type": subagent_type}
    if isolation is not ...:
        tool_input["isolation"] = isolation
    return json.dumps({"tool_name": tool_name, "tool_input": tool_input})


failed = 0
total = 0


def check(label: str, payload: str, expected: str, extra_env=None) -> None:
    """expected: 'ALLOW' or 'DENY'."""
    global failed, total
    total += 1
    rc, stdout, stderr = run_hook(payload, extra_env=extra_env)
    if expected == "ALLOW":
        ok = is_allow(rc, stdout)
        detail_ok, reason = True, ""
    else:
        ok, reason = is_deny(rc, stdout)
        if ok:
            detail_ok = "isolation" in reason.lower() and "worktree" in reason.lower()
            ok = ok and detail_ok
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload!r}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")


# ---------------------------------------------------------------------------
# 1. Mandated roles, isolation key ABSENT -> DENY.
#    Mutation that would redden: deleting the `isolation is None` /
#    `raw_tinput.get("isolation")` absence-handling path (e.g. defaulting
#    the missing key to "worktree") would flip this to ALLOW.
# ---------------------------------------------------------------------------
print("-- mandated role, isolation key absent -> DENY --")
for role in ("engineer", "qa-engineer", "release-orchestrator"):
    check(
        f"{role} spawn, no isolation key -> deny",
        _payload(role),
        "DENY",
    )

# ---------------------------------------------------------------------------
# 2. Mandated roles, isolation set to a wrong value -> DENY.
#    Mutation that would redden: changing the equality check to a truthy
#    check (`if isolation:`) would flip "none"/True to ALLOW.
# ---------------------------------------------------------------------------
print("-- mandated role, isolation wrong value -> DENY --")
for role in ("engineer", "qa-engineer", "release-orchestrator"):
    check(
        f"{role} spawn, isolation='none' -> deny",
        _payload(role, isolation="none"),
        "DENY",
    )
check(
    "engineer spawn, isolation=true (bool, not the string) -> deny",
    _payload("engineer", isolation=True),
    "DENY",
)

# ---------------------------------------------------------------------------
# 3. Mandated roles, isolation == "worktree" exactly -> ALLOW.
#    Mutation that would redden: inverting the equality check
#    (`if isolation != _REQUIRED_ISOLATION: sys.exit(0)`) would flip this
#    to DENY.
# ---------------------------------------------------------------------------
print("-- mandated role, isolation='worktree' -> ALLOW --")
for role in ("engineer", "qa-engineer", "release-orchestrator"):
    check(
        f"{role} spawn, isolation='worktree' -> allow",
        _payload(role, isolation="worktree"),
        "ALLOW",
    )

# ---------------------------------------------------------------------------
# 4. Non-mandated role -> ALLOW regardless of isolation.
#    Mutation that would redden: removing the `role not in MANDATED_ROLES`
#    check (or emptying MANDATED_ROLES) would flip this to DENY.
# ---------------------------------------------------------------------------
print("-- non-mandated role -> ALLOW regardless of isolation --")
for role in ("investigator", "skeptic", "architect"):
    check(
        f"{role} spawn, no isolation key -> allow (not a mandated role)",
        _payload(role),
        "ALLOW",
    )
    check(
        f"{role} spawn, isolation='none' -> allow (not a mandated role)",
        _payload(role, isolation="none"),
        "ALLOW",
    )

# ---------------------------------------------------------------------------
# 5. Transcript-derived fixture shapes (see module docstring).
#    Mutation that would redden: same as case 1/3 above - these are the
#    same predicate exercised against the closest-to-real payload shape.
# ---------------------------------------------------------------------------
print("-- transcript-derived fixture shapes --")
check(
    "fixture: real with-isolation Agent spawn shape -> allow",
    json.dumps(FIXTURE_WITH_ISOLATION),
    "ALLOW",
)
check(
    "fixture: real without-isolation Agent spawn shape -> deny",
    json.dumps(FIXTURE_WITHOUT_ISOLATION),
    "DENY",
)

# ---------------------------------------------------------------------------
# 6. Legacy tool_name="Task" is deliberately fail-open (unproven predicate -
#    no real Task-spawn payload capture exists to confirm the same
#    omitted-when-unset shape as "Agent").
#    Mutation that would redden: widening the tool_name check to enforce on
#    "Task" (e.g. `tool_name not in ("Task", "Agent")`) would flip this to
#    DENY.
# ---------------------------------------------------------------------------
print("-- tool_name='Task' is fail-open (unproven predicate) -> ALLOW --")
check(
    "Task: engineer spawn, no isolation key -> allow (Task not enforced)",
    _payload("engineer", tool_name="Task"),
    "ALLOW",
)

# ---------------------------------------------------------------------------
# 7. Non-spawn tool_name -> ALLOW (passthrough).
#    Mutation that would redden: removing the `tool_name not in ("Task",
#    "Agent")` guard would make this fall through into the role check with
#    tool_name="Write" - still allowed here, but the guard also protects
#    against a future change to the deny message's `f"{tool_name} spawn"`
#    interpolation reaching a non-spawn tool.
# ---------------------------------------------------------------------------
print("-- non-spawn tool_name -> ALLOW (passthrough) --")
check(
    "Write tool_name, engineer subagent_type, no isolation -> allow (not a spawn)",
    json.dumps({
        "tool_name": "Write",
        "tool_input": {"subagent_type": "engineer"},
    }),
    "ALLOW",
)

# ---------------------------------------------------------------------------
# 8. Fail-open: malformed/missing input never denies.
#    Mutation that would redden ("empty stdin" / "malformed JSON" / "JSON
#    but not an object" specifically): removing the hook's SOLE
#    `except Exception: sys.exit(0)` handler (the outer one wrapping
#    json.load through the deny call) turns the json.load crash into a
#    nonzero exit rather than an ALLOW - measured: 2/27 tests FAIL when
#    that handler alone is removed. The hook previously had a SECOND,
#    fully redundant try/except wrapped tightly around just the
#    json.load call; it was deleted (rather than individually pinned)
#    because it caught the exact same Exception class the outer handler
#    already catches for every JSON-derived payload - no input via stdin
#    could make removing ONLY that inner handler observably differ from
#    removing neither, so no test could pin it individually without being
#    vacuous. See the hook's own `main()` comment at the json.load call.
#    "tool_input is null" / "tool_input missing entirely" test the
#    `not isinstance(raw_tinput, dict)` guard, not the exception handler.
#    "subagent_type is not a string" tests the `not isinstance(role, str)`
#    guard specifically - see case 8b below for the isinstance guard on
#    tool_input itself with a TRUTHY non-dict value (a value that could
#    survive an `or {}`-style mutation and still reach the role check).
# ---------------------------------------------------------------------------
print("-- fail-open on malformed input --")
check("empty stdin", "", "ALLOW")
check("malformed JSON", "not-json-at-all{{{{", "ALLOW")
check("JSON but not an object", json.dumps([1, 2, 3]), "ALLOW")
check(
    "tool_input is null",
    json.dumps({"tool_name": "Agent", "tool_input": None}),
    "ALLOW",
)
check(
    "tool_input missing entirely",
    json.dumps({"tool_name": "Agent"}),
    "ALLOW",
)
check(
    "subagent_type is not a string",
    json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": 5}}),
    "ALLOW",
)

# ---------------------------------------------------------------------------
# 8b. tool_input isinstance guard: a TRUTHY non-dict value must still be
#     rejected, not just a null/missing one. Pins the `isinstance` check
#     itself rather than the `not raw_tinput` shortcut a weaker guard
#     (e.g. `data.get("tool_input") or {}`) would also pass.
#     Mutation that would redden: replacing
#     `if not isinstance(raw_tinput, dict): sys.exit(0)` with
#     `raw_tinput = data.get("tool_input") or {}` (dropping the isinstance
#     check entirely) would let a truthy string/list `tool_input` fall
#     through to `raw_tinput.get(...)`, raising AttributeError and (with
#     the single exception handler intact) still exiting 0 - so this
#     mutation is only reddened by asserting these are non-crashing ALLOWs
#     under the CURRENT guard, i.e. confirms the isinstance check is what
#     makes this an explicit, understood ALLOW rather than an
#     exception-swallowed accidental one. Verified by manual mutation (see
#     fix summary): both mutated forms still print ALLOW here, since the
#     lone fail-open handler catches the resulting AttributeError either
#     way - this test's value is documenting the guard's presence and
#     intended behavior, not distinguishing it from the fail-open path.
# ---------------------------------------------------------------------------
print("-- tool_input isinstance guard: truthy non-dict values -> ALLOW --")
check(
    "tool_input is a truthy string, not a dict",
    json.dumps({"tool_name": "Agent", "tool_input": "engineer"}),
    "ALLOW",
)
check(
    "tool_input is a truthy list, not a dict",
    json.dumps({"tool_name": "Agent", "tool_input": ["engineer"]}),
    "ALLOW",
)

print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
