# Run with: python3 hooks/tests/test-enforce-tier.py
"""
Unit tests for hooks/enforce-tier.py.

Each case pipes a JSON payload (or malformed string) into the hook via stdin
and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in stdout).
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
    os.path.dirname(__file__), "..", "enforce-tier.py"
)

# None of this file's payloads set a "cwd" field, so the hook's fire-logging
# helper (hooks/lib/enforcement_log.py) falls back to os.getcwd() - which,
# without an explicit subprocess cwd=, would be wherever this test file is
# invoked from (typically the live checkout). Pin the child process's cwd to
# an ephemeral temp dir so DENY-path fire-log writes never touch the repo.
_TEST_CWD = tempfile.mkdtemp(prefix="test-enforce-tier-")


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
        cwd=_TEST_CWD,
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
    # 35 (DS-226): security-auditor model="fable" -> ALLOW. Fable is the tier
    # ABOVE Opus, so it must satisfy the Tier-3-or-above accept check.
    # security-auditor's deny is UNCONDITIONAL on any sub-Tier-3 model
    # (independent of the brief - see case 7/9), which makes this a true test
    # of the model-tier accept path rather than of the brief-marker path (a
    # skeptic case with no brief would ALLOW regardless of model, since the
    # marker check never fires - that shape was tried and rejected during
    # development because it could not actually redden). Reddening mutation:
    # reverting TIER3_OR_ABOVE_MARKERS = ("opus", "fable") to ("opus",) alone
    # turns this case into a DENY (the pre-DS-226 "opus" in model.lower()
    # check also fails it, since "opus" is not a substring of "fable").
    (
        "35: Agent security-auditor model=fable -> ALLOW (DS-226 Fable tier)",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "security-auditor", "model": "fable"}}),
        "ALLOW",
        None,
    ),
    # 36 (DS-226): security-auditor model=full Fable id -> ALLOW. Mirrors
    # case 3's full-id coverage for opus. Same reddening mutation as case 35.
    (
        "36: Agent security-auditor model=claude-fable-5-1 -> ALLOW (DS-226 Fable tier, full id)",
        json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "security-auditor", "model": "claude-fable-5-1"}}),
        "ALLOW",
        None,
    ),
    # 37 (DS-226): security-auditor model="sonnet" on the SAME spawn shape as
    # 35/36 must still be DENIED (mirrors case 7) - proves widening the
    # accept set to include "fable" did not also loosen the sonnet/haiku/
    # other deny paths. Reddening mutation: any change that makes
    # TIER3_OR_ABOVE_MARKERS match "sonnet" (e.g. an overbroad substring or a
    # bug making the check unconditional) turns this ALLOW-when-it-should-DENY.
    (
        "37: Agent security-auditor model=sonnet -> DENY (still denied post-DS-226)",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
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

# 38 (Skeptic-required Fix 1): lock the AUTHOR branch's deny-message wording.
# The behavioral ALLOW/DENY cases above can't catch a pure message-wording
# revert, so this asserts on permissionDecisionReason content directly.
# POSITIVE: the reason must instruct "pass model: opus". NEGATIVE: the reason
# must NOT contain "omit the model param to use" - that is the correct
# remediation phrase on the skeptic/security-auditor branches (those roles
# default to Opus, so omitting is right), but on the AUTHOR branch it would
# be WRONG (architect/adr-generator/product-discovery default to Sonnet, so
# telling the operator to omit would silently defeat the escalation).
label_38 = "38: Agent architect model=sonnet + ADR brief -> author deny message wording locked"
reason_38 = deny_reason(json.dumps({
    "tool_name": "Agent",
    "tool_input": {
        "subagent_type": "architect",
        "model": "sonnet",
        "prompt": "author the ADR",
    },
}))
ok_38 = (
    reason_38 is not None
    and "pass model: opus" in reason_38
    and "omit the model param to use" not in reason_38
)
status_38 = "PASS" if ok_38 else "FAIL"
if not ok_38:
    failed += 1
print(f"  [{status_38}] {label_38}")
if not ok_38:
    print(f"         reason:   {reason_38!r}")

# 39 (fire-log integration): a DENY action must append a well-formed line to
# <cwd>/.agentic/.enforcement-fires.jsonl (hooks/lib/enforcement_log.py);
# a passthrough ALLOW (case 1, model omitted) must write nothing at all -
# no .agentic/ dir is even created. Uses an explicit "cwd" in the payload
# (rather than relying on the subprocess cwd= isolation _TEST_CWD provides)
# so this test exercises the same data["cwd"] read path a real Claude Code
# payload uses.
import tempfile as _tempfile_39

label_39 = "39: fire-log integration - deny writes a line, passthrough writes nothing"
_fire_cwd = _tempfile_39.mkdtemp(prefix="test-enforce-tier-firelog-")
_fire_log_path = os.path.join(_fire_cwd, ".agentic", ".enforcement-fires.jsonl")

# (a) DENY case: security-auditor downgraded below Opus.
run_hook(json.dumps({
    "tool_name": "Agent",
    "cwd": _fire_cwd,
    "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
}))
ok_39a = os.path.exists(_fire_log_path)
if ok_39a:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok_39a = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-tier"
        and _fire_lines[0].get("decision") == "deny"
    )

# (b) Passthrough case: model omitted on the same agent -> ALLOW, no write.
run_hook(json.dumps({
    "tool_name": "Agent",
    "cwd": _fire_cwd,
    "tool_input": {"subagent_type": "security-auditor"},
}))
with open(_fire_log_path, "r", encoding="utf-8") as f:
    _fire_lines_after = [json.loads(ln) for ln in f if ln.strip()]
ok_39b = len(_fire_lines_after) == 1  # unchanged - passthrough logged nothing

ok_39 = ok_39a and ok_39b
status_39 = "PASS" if ok_39 else "FAIL"
if not ok_39:
    failed += 1
print(f"  [{status_39}] {label_39}")

# 40 (Skeptic Critical regression): a raising log_fire() must NOT suppress
# the deny decision. Confirmed failing pre-fix: against a8ded298 (the
# commit under review), the copied-hook subprocess exits 0 with EMPTY
# stdout - the deny is silently lost - because the pre-fix _deny() called
# log_fire() BEFORE print(). See hooks/tests/_fire_log_test_helper.py.
label_40 = "40: raising log_fire cannot suppress the deny decision"
_rc_40, _stdout_40, _stderr_40 = run_hook_with_raising_log_fire(
    "enforce-tier.py",
    json.dumps({
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "security-auditor", "model": "sonnet"},
    }),
)
ok_40 = _rc_40 == 0 and not is_allow(_rc_40, _stdout_40)
status_40 = "PASS" if ok_40 else "FAIL"
if not ok_40:
    failed += 1
print(f"  [{status_40}] {label_40}")
if not ok_40:
    print(f"         stdout: {_stdout_40!r}")
    print(f"         stderr: {_stderr_40[-500:]!r}")

total_tests = len(cases) + 3

print()
if failed == 0:
    print(f"All {total_tests} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total_tests} tests FAILED.")
    sys.exit(1)
