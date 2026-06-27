# Run with: python3 hooks/tests/test-enforce-tier.py
"""
Unit tests for hooks/enforce-tier.py.

Each case pipes a JSON payload (or malformed string) into the hook via stdin
and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in stdout).
"""

import json
import os
import subprocess
import sys

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-tier.py"
)


def run_hook(payload: str, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("AE_TIER_GUARD_DISABLE", None)  # clean slate per test
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
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
        decision = (
            obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        )
        return decision != "deny"
    except Exception:
        return True  # unparseable output -> not a deny


def is_deny(returncode: int, stdout: str) -> bool:
    """DENY: exit 0 and permissionDecision == deny in stdout."""
    if returncode != 0:
        return False
    try:
        obj = json.loads(stdout)
        decision = (
            obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        )
        return decision == "deny"
    except Exception:
        return False


cases = [
    # (label, payload_str, expected, extra_env)

    # 1: model omitted -> frontmatter default (Opus) -> ALLOW
    (
        "1: Agent skeptic model omitted -> ALLOW",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "skeptic"}}),
        "ALLOW",
        None,
    ),
    # 2: model="opus" -> ALLOW
    (
        "2: Agent skeptic model=opus -> ALLOW",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "skeptic", "model": "opus"}}),
        "ALLOW",
        None,
    ),
    # 3: model=full Opus id -> ALLOW
    (
        "3: Agent skeptic model=claude-opus-4-8 -> ALLOW",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "skeptic", "model": "claude-opus-4-8"}}),
        "ALLOW",
        None,
    ),
    # 4: sonnet downgrade + security brief -> DENY
    (
        "4: Agent skeptic model=sonnet + security brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "security adversarial brief for the auth flow",
            },
        }),
        "DENY",
        None,
    ),
    # 5: sonnet downgrade + benign brief -> ALLOW
    (
        "5: Agent skeptic model=sonnet + benign brief -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "review the button label copy change",
            },
        }),
        "ALLOW",
        None,
    ),
    # 6: haiku downgrade + migration in description -> DENY
    (
        "6: Agent skeptic model=haiku + schema migration description -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "haiku",
                "description": "verify the schema migration",
            },
        }),
        "DENY",
        None,
    ),
    # 7: security-auditor always blocked on non-opus
    (
        "7: Agent security-auditor model=sonnet -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
        }),
        "DENY",
        None,
    ),
    # 8: security-auditor model omitted -> ALLOW
    (
        "8: Agent security-auditor model omitted -> ALLOW",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "security-auditor"}}),
        "ALLOW",
        None,
    ),
    # 9: security-auditor model=opus -> ALLOW
    (
        "9: Agent security-auditor model=opus -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "security-auditor", "model": "opus"},
        }),
        "ALLOW",
        None,
    ),
    # 10: non-review agent -> ALLOW even with alarming prompt
    (
        "10: Agent engineer model=sonnet + alarming prompt -> ALLOW (non-review agent)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "engineer",
                "model": "sonnet",
                "prompt": "delete the production database",
            },
        }),
        "ALLOW",
        None,
    ),
    # 11: non-spawn tool -> passthrough ALLOW
    (
        "11: Read tool -> ALLOW (non-spawn passthrough)",
        json.dumps({"tool_name": "Read", "tool_input": {}}),
        "ALLOW",
        None,
    ),
    # 12: malformed stdin -> fail-open ALLOW
    (
        "12: malformed stdin -> ALLOW (fail-open)",
        "not-json",
        "ALLOW",
        None,
    ),
    # 13: tool_input null -> fail-open ALLOW
    (
        "13: Agent tool_input null -> ALLOW (fail-open)",
        json.dumps({"tool_name": "Agent", "tool_input": None}),
        "ALLOW",
        None,
    ),
    # 14: legacy "Task" tool name parity
    (
        "14: Task security-auditor model=sonnet -> DENY (legacy tool name parity)",
        json.dumps({
            "tool_name": "Task",
            "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
        }),
        "DENY",
        None,
    ),
    # 15: legacy "Task" + skeptic + JWT secrets in brief -> DENY
    (
        "15: Task skeptic model=sonnet + JWT secrets brief -> DENY",
        json.dumps({
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "rotate the JWT signing secrets",
            },
        }),
        "DENY",
        None,
    ),
    # 16: kill-switch -> ALLOW
    (
        "16: Agent security-auditor model=sonnet + AE_TIER_GUARD_DISABLE=1 -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
        }),
        "ALLOW",
        {"AE_TIER_GUARD_DISABLE": "1"},
    ),
    # 17: substring-trap guard - author/secretary/product must NOT fire
    (
        "17: Agent skeptic model=sonnet + author/secretary/product -> ALLOW (substring-trap)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "the author updated the secretary's product page",
            },
        }),
        "ALLOW",
        None,
    ),
    # 18: OAuth marker (Skeptic-required fix)
    (
        "18: Agent skeptic model=sonnet + OAuth callback -> DENY (oauth marker)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "review the OAuth callback handler",
            },
        }),
        "DENY",
        None,
    ),
    # 19: bare 'prod' deliberately NOT a marker
    (
        "19: Agent skeptic model=sonnet + 'prod the user' -> ALLOW (bare prod not a marker)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "prod the user for input",
            },
        }),
        "ALLOW",
        None,
    ),
    # 20: novel-architecture coverage gap (intentionally not keyworded)
    (
        "20: Agent skeptic model=sonnet + novel architecture -> ALLOW (documented coverage gap)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "skeptic",
                "model": "sonnet",
                "prompt": "evaluate this novel architecture decision",
            },
        }),
        "ALLOW",
        None,
    ),
]

failed = 0
for label, payload, expected, extra_env in cases:
    rc, stdout, stderr = run_hook(payload, extra_env)
    if expected == "ALLOW":
        ok = is_allow(rc, stdout)
    else:
        ok = is_deny(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
        print(f"         expected: {expected}")

print()
if failed == 0:
    print(f"All {len(cases)} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{len(cases)} tests FAILED.")
    sys.exit(1)
