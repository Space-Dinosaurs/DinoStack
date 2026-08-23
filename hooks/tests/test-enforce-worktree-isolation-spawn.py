# Run with: python3 hooks/tests/test-enforce-worktree-isolation-spawn.py
"""
Unit tests for hooks/enforce-worktree-isolation-spawn.py.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin and asserts ALLOW (exit 0, no deny in stdout) or DENY (exit 0, deny
in stdout, reason names the isolation fix).

Fixture note: FIXTURE_WITH_ISOLATION and FIXTURE_WITHOUT_ISOLATION below
are built from a REAL PreToolUse stdin capture obtained this session
(project-scoped capture hook, 2026-08-23; raw log gitignored, not shipped
with this repo, and still growing as concurrent sessions append to it - the
SHAPES below are the load-bearing evidence, not a record count, which would
go stale the next time anyone reads the live log). Both `tool_name: "Agent"`
shapes were captured: a with-isolation spawn, `tool_input` keys
`['description', 'isolation', 'prompt', 'subagent_type']` with
`isolation == "worktree"`; and a without-isolation spawn, `tool_input` keys
`['description', 'prompt', 'subagent_type']` - no `isolation` key at all.
This corroborates `hooks/AGENTS.md` §"Spawn payload mechanics"'s
schema-derived `isolation` key listing with an actual payload capture.
There is no capture for `tool_name: "Task"` - see
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
#    Mutation that would redden: removing the hook's actual guard
#    (`if tool_name != "Agent": sys.exit(0)`) would fall through into the
#    role check with tool_name="Write" and DENY it (the deny message
#    interpolates `f"{tool_name} spawn of subagent_type '{role}' blocked"`
#    with no tool_name check of its own) - measured: neutralizing this
#    guard fails 2/29 tests, both this case AND case 6 ("Task"), since
#    both tool_name != "Agent" and end up reaching the role/isolation
#    checks unguarded.
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
#    Mutation that would redden ("empty stdin" / "malformed JSON"
#    specifically): removing the hook's SOLE
#    `except Exception: sys.exit(0)` handler (the outer one wrapping
#    json.load through the deny call) turns the json.load crash into a
#    nonzero exit rather than an ALLOW - measured: 2/29 tests FAIL when
#    that handler alone is removed. The hook previously had a SECOND,
#    fully redundant try/except wrapped tightly around just the
#    json.load call; it was deleted (rather than individually pinned)
#    because it caught the exact same Exception class the outer handler
#    already catches for every JSON-derived payload - no input via stdin
#    could make removing ONLY that inner handler observably differ from
#    removing neither, so no test could pin it individually without being
#    vacuous. See the hook's own `main()` comment at the json.load call.
#    "tool_input is null" / "tool_input missing entirely" document behavior,
#    they do NOT pin the `not isinstance(raw_tinput, dict)` guard - measured:
#    replacing the guard with `raw_tinput = data.get("tool_input") or {}`
#    leaves all 29 tests passing, since a null or missing `tool_input`
#    collapses to `{}` either way and the two forms are unfalsifiable-by-
#    construction for these two inputs. See case 8b below for the same
#    guard's isinstance-specific tests (truthy non-dict values), which ARE
#    the ones that document the guard without pinning it either.
#    "subagent_type is not a string" (int 5) exercises the plain
#    `role not in MANDATED_ROLES` membership test with a non-string,
#    hashable value - it does NOT test an isinstance guard on `role`. An
#    earlier version of this hook had one (`not isinstance(role, str) or
#    role not in MANDATED_ROLES`); round-3 mutation testing found it
#    unfalsifiable-by-construction (a non-hashable role like a list raises
#    inside the membership test and is caught by the outer exception
#    handler, landing on the identical ALLOW a short-circuit would produce
#    - verified: both mutated and unmutated forms print the same (0, '')
#    for both an int and a list role), so it was deleted per this repo's
#    standing preference for deletion over a narrowed, unfalsifiable
#    rewrite. See case 8b below for the SEPARATE isinstance guard on
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
# 8b. tool_input isinstance guard: documents behavior, does NOT pin the
#     guard - these are NOT regression tests for the guard's presence.
#     Measured: removing `if not isinstance(raw_tinput, dict): sys.exit(0)`
#     entirely (replacing it with `raw_tinput = data.get("tool_input") or
#     {}`, dropping the isinstance check) leaves both cases below printing
#     the identical ALLOW - a truthy string/list `tool_input` falls through
#     to `raw_tinput.get(...)`, raises AttributeError, and the lone
#     fail-open handler catches it, landing on the same externally
#     observable outcome as the explicit guard. No test can distinguish
#     the two forms for any input reachable from JSON, the same
#     unfalsifiable-by-construction shape as the deleted
#     `isinstance(role, str)` check documented at case 8 above.
#
#     Kept anyway, unlike that deleted check: the role check was a
#     redundant re-statement of logic `role not in MANDATED_ROLES`
#     already fully handles on its own (the isinstance clause added no
#     new code path, only an earlier exit to the same outcome). This
#     `isinstance(raw_tinput, dict)` guard is different in kind, not
#     degree - it is the SOLE type gate on the top-level `tool_input`
#     value before ANY `.get()` call is made on it anywhere in this
#     function; every subsequent line's use of `raw_tinput`/`tinput`
#     relies on the dict-shape invariant this line states explicitly.
#     Removing it would not shorten the logic, it would just delete the
#     one place that invariant is documented, leaving it implicit and
#     resting entirely on the outer exception handler. That is a
#     documentation/architecture argument, not a test-observable one -
#     per the SCOPE CONSTRAINT on this fix pass (no hook execution-logic
#     changes), the guard is kept as-is and these tests are relabeled to
#     stop claiming they pin it.
# ---------------------------------------------------------------------------
print("-- tool_input isinstance guard: truthy non-dict values -> ALLOW (documents behavior, does not pin the guard) --")
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

# ---------------------------------------------------------------------------
# 9. Kill-switch: AE_WORKTREE_ISOLATION_GUARD_DISABLE=1 fails open even on a
#    payload that would otherwise deny (round-3 reinstatement).
#    Mutation that would redden: removing the
#    `os.environ.get("AE_WORKTREE_ISOLATION_GUARD_DISABLE") == "1"` check (or
#    its early sys.exit(0)) in main() would flip this to DENY.
# ---------------------------------------------------------------------------
print("-- kill-switch AE_WORKTREE_ISOLATION_GUARD_DISABLE=1 -> ALLOW --")
check(
    "engineer spawn, no isolation key, kill-switch set -> allow",
    _payload("engineer"),
    "ALLOW",
    extra_env={"AE_WORKTREE_ISOLATION_GUARD_DISABLE": "1"},
)

print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} tests FAILED.")
    sys.exit(1)
