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


def deny_reason(payload: str, extra_env: dict | None = None) -> str | None:
    """Run the hook and return the parsed permissionDecisionReason string,
    or None if the call was not a deny / output was unparseable."""
    rc, stdout, _stderr = run_hook(payload, extra_env)
    if not is_deny(rc, stdout):
        return None
    try:
        obj = json.loads(stdout)
        return obj.get("hookSpecificOutput", {}).get("permissionDecisionReason")
    except Exception:
        return None


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

    # --- DS-77: authoring-role Tier-3 escalation (architect / adr-generator /
    # product-discovery) on Plan+ADR-tier units ---

    # 21: architect + ADR/cross-track brief -> DENY (done-criterion case)
    (
        "21: Agent architect model=sonnet + ADR cross-track brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "author the ADR for this cross-track change",
            },
        }),
        "DENY",
        None,
    ),
    # 22: architect + "architecture decision constraining future choices" -> DENY
    (
        "22: Agent architect model=sonnet + architecture-decision-constraining brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "architecture decision constraining future choices",
            },
        }),
        "DENY",
        None,
    ),
    # 23: architect + routine brief -> ALLOW (routine work must not break)
    (
        "23: Agent architect model=sonnet + routine brief -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "add a null check to the date formatter",
            },
        }),
        "ALLOW",
        None,
    ),
    # 24: architect + model omitted -> ALLOW (omit = Sonnet default; hook must not force Opus)
    (
        "24: Agent architect model omitted + ADR brief -> ALLOW (omit=Sonnet default)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "prompt": "author the ADR",
            },
        }),
        "ALLOW",
        None,
    ),
    # 25: architect + model=opus -> ALLOW (correct escalation)
    (
        "25: Agent architect model=opus + ADR brief -> ALLOW (correct escalation)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "opus",
                "prompt": "author the ADR",
            },
        }),
        "ALLOW",
        None,
    ),
    # 26: adr-generator + cross-track ADR brief -> DENY
    (
        "26: Agent adr-generator model=sonnet + cross-track ADR brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "adr-generator",
                "model": "sonnet",
                "prompt": "generate the ADR for the cross-track decision",
            },
        }),
        "DENY",
        None,
    ),
    # 27: adr-generator + model omitted -> ALLOW
    (
        "27: Agent adr-generator model omitted + ADR brief -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "adr-generator",
                "prompt": "generate the ADR",
            },
        }),
        "ALLOW",
        None,
    ),
    # 28: product-discovery + haiku downgrade + cross-track architecture brief -> DENY
    (
        "28: Agent product-discovery model=haiku + cross-track architecture brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "product-discovery",
                "model": "haiku",
                "prompt": "cross-track architecture decision synthesis",
            },
        }),
        "DENY",
        None,
    ),
    # 29: product-discovery + benign brief -> ALLOW
    (
        "29: Agent product-discovery model=sonnet + benign brief -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "product-discovery",
                "model": "sonnet",
                "prompt": "summarize user interview themes",
            },
        }),
        "ALLOW",
        None,
    ),
    # 30: architect + "author" substring-trap guard (\badr\b must not match "author")
    (
        "30: Agent architect model=sonnet + 'the author updated the page' -> ALLOW (substring-trap)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "the author updated the page",
            },
        }),
        "ALLOW",
        None,
    ),
    # 31: legacy "Task" tool name parity for the authoring-role path
    (
        "31: Task architect model=sonnet + ADR brief -> DENY (legacy tool name parity)",
        json.dumps({
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "author the ADR",
            },
        }),
        "DENY",
        None,
    ),
    # 32: kill-switch applies to the authoring-role path too
    (
        "32: Agent architect model=sonnet + ADR brief + AE_TIER_GUARD_DISABLE=1 -> ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "author the ADR",
            },
        }),
        "ALLOW",
        {"AE_TIER_GUARD_DISABLE": "1"},
    ),
    # 33: architect + "novel architecture" -> DENY (author marker; contrast with
    # test 20 where the SAME phrase on a skeptic spawn is ALLOW - independent
    # marker lists, review-role coverage gap does not apply to authoring roles)
    (
        "33: Agent architect model=sonnet + novel architecture brief -> DENY (author marker)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "novel architecture with novel tradeoffs",
            },
        }),
        "DENY",
        None,
    ),
    # 34: hyphenated "architectural-decision" variant must also match
    # (Skeptic-required Fix 2: \barchitectur\w*[- ]decision\b)
    (
        "34: Agent architect model=sonnet + hyphenated architectural-decision brief -> DENY",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "architect",
                "model": "sonnet",
                "prompt": "architectural-decision constraining future choices",
            },
        }),
        "DENY",
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

# 35 (Skeptic-required Fix 1): lock the AUTHOR branch's deny-message wording.
# The behavioral ALLOW/DENY cases above can't catch a pure message-wording
# revert, so this asserts on permissionDecisionReason content directly.
# POSITIVE: the reason must instruct "pass model: opus". NEGATIVE: the reason
# must NOT contain "omit the model param to use" - that is the correct
# remediation phrase on the skeptic/security-auditor branches (those roles
# default to Opus, so omitting is right), but on the AUTHOR branch it would
# be WRONG (architect/adr-generator/product-discovery default to Sonnet, so
# telling the operator to omit would silently defeat the escalation).
label_35 = "35: Agent architect model=sonnet + ADR brief -> author deny message wording locked"
reason_35 = deny_reason(json.dumps({
    "tool_name": "Agent",
    "tool_input": {
        "subagent_type": "architect",
        "model": "sonnet",
        "prompt": "author the ADR",
    },
}))
ok_35 = (
    reason_35 is not None
    and "pass model: opus" in reason_35
    and "omit the model param to use" not in reason_35
)
status_35 = "PASS" if ok_35 else "FAIL"
if not ok_35:
    failed += 1
print(f"  [{status_35}] {label_35}")
if not ok_35:
    print(f"         reason:   {reason_35!r}")

total_tests = len(cases) + 1

print()
if failed == 0:
    print(f"All {total_tests} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total_tests} tests FAILED.")
    sys.exit(1)
