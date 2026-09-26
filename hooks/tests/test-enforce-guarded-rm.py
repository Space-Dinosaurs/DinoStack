# Run with: python3 hooks/tests/test-enforce-guarded-rm.py
"""
Tests for hooks/enforce-guarded-rm.py (DS-261).

Classifier cases call find_unguarded_rm() directly; plumbing cases pipe a
PreToolUse payload into the hook as a subprocess. main() runs every test_*
function and exits 1 if any raises AssertionError.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire

HOOK_BASENAME = "enforce-guarded-rm.py"
HOOK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), HOOK_BASENAME
)
FIRE_LOG = ".enforcement-fires.jsonl"

_spec = importlib.util.spec_from_file_location("enforce_guarded_rm", HOOK_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
find_unguarded_rm = _mod.find_unguarded_rm

DENY_CASES = [
    ("rm $B/$s/$t.raw.json", "$B/$s/$t.raw.json", ["B", "s", "t"]),
    ('rm -rf "$D"/x', '"$D"/x', ["D"]),
    ('rm "$f"', '"$f"', ["f"]),
    ('cd /t && rm "$f"', '"$f"', ["f"]),
    ("for f in *; do rm $d/$f; done", "$d/$f", ["d", "f"]),
    ("(rm $X/y)", "$X/y", ["X"]),
    ("echo $(rm $X/y)", "$X/y", ["X"]),
    ("cat <(rm $X/y)", "$X/y", ["X"]),
    ("/bin/rm ${X}/y", "${X}/y", ["X"]),
    ("rm ${X?}/y", "${X?}/y", ["X"]),
    ("rm -- -$X", "-$X", ["X"]),
    ("X=1 rm $Y/x", "$Y/x", ["Y"]),
    ("AE_RM_GUARD_DISABLE=1 rm $Y/x", "$Y/x", ["Y"]),
    ("echo start\nrm $A/$B/x", "$A/$B/x", ["A", "B"]),
]

ALLOW_CASES = [
    'rm "${B:?}"/"${s:?}"/f',
    "rm /tmp/lit.json",
    "rm '$X/y'",
    "rm \\$X",
    'git rm "$f"',
    'nice git rm "$f"',
    "echo rm $X",
    "rm f > $LOG",
    "rm f < $IN",
    "rm ${X:-/tmp/d}/y",
    "rm ${#X}",
    "cat <<EOF\nrm $X\nEOF",
    "# rm $X",
    "case x in a) rm $y;; esac",
    'rm "$X',
    "ls",
    "cat <(true) rm $X",
]


def _run_hook(payload, cwd, env_extra=None, drop_kill_switch=True):
    env = os.environ.copy()
    if drop_kill_switch:
        env.pop("AE_RM_GUARD_DISABLE", None)
    if env_extra:
        env.update(env_extra)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, HOOK_PATH],
        input=raw,
        env=env,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _repo_dir():
    d = tempfile.mkdtemp(prefix="test-guarded-rm-")
    os.makedirs(os.path.join(d, ".git"))
    return d


def _bash_payload(command, cwd):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": "test-session",
    }


def _fire_rows(repo):
    path = os.path.join(repo, ".agentic", FIRE_LOG)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _decision(stdout):
    assert stdout.strip(), "hook printed no decision"
    out = json.loads(stdout)["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


def test_deny_cases():
    for command, operand, names in DENY_CASES:
        got = find_unguarded_rm(command)
        assert got == (operand, names), (command, got)


def test_allow_cases():
    for command in ALLOW_CASES:
        got = find_unguarded_rm(command)
        assert got is None, (command, got)


def test_classifier_never_raises_on_non_str_or_oversize():
    assert find_unguarded_rm(None) is None
    assert find_unguarded_rm("rm $X " + "a" * 100001) is None


def test_deny_output_and_fire_row():
    repo = _repo_dir()
    r = _run_hook(_bash_payload("rm $B/$s/x", repo), repo)
    assert r.returncode == 0, r
    decision, reason = _decision(r.stdout)
    assert decision == "deny", r.stdout
    assert "rm operand $B/$s/x expands unguarded variable(s) $B, $s." in reason
    rows = _fire_rows(repo)
    assert len(rows) == 1, rows
    assert rows[0]["hook"] == "enforce-guarded-rm", rows
    assert rows[0]["decision"] == "deny", rows
    assert rows[0].get("detail", {}).get("agent_self_corrects") is True, rows


def test_allow_writes_no_row_and_no_output():
    repo = _repo_dir()
    r = _run_hook(_bash_payload('rm "${B:?}"/x', repo), repo)
    assert r.returncode == 0 and r.stdout == "", r
    assert _fire_rows(repo) == []


def test_reason_text():
    reason = _mod.build_reason("$B/x", ["B"])
    assert "${VAR:?}" in reason, reason
    assert "scratchpad" in reason, reason
    assert "AE_RM_GUARD_DISABLE" not in reason, reason
    long_reason = _mod.build_reason("$B/" + "x" * 500, ["B"])
    assert "$B/" + "x" * 197 + " expands" in long_reason, long_reason


def test_kill_switch_in_process_env_allows():
    repo = _repo_dir()
    r = _run_hook(
        _bash_payload("rm $B/$s/x", repo), repo,
        env_extra={"AE_RM_GUARD_DISABLE": "1"},
    )
    assert r.returncode == 0 and r.stdout == "", r
    assert _fire_rows(repo) == []


def test_non_bash_and_malformed_inputs_allow():
    repo = _repo_dir()
    payloads = [
        {"tool_name": "Write", "tool_input": {"command": "rm $X"}, "cwd": repo},
        {"tool_name": "Bash", "tool_input": {}, "cwd": repo},
        {"tool_name": "Bash", "tool_input": {"command": 5}, "cwd": repo},
        {"tool_name": "Bash", "tool_input": "rm $X", "cwd": repo},
        "not json {",
        "[1, 2]",
        "",
    ]
    for p in payloads:
        r = _run_hook(p, repo)
        assert r.returncode == 0 and r.stdout == "", (p, r)


def test_raising_log_fire_still_denies():
    repo = _repo_dir()
    payload = json.dumps(_bash_payload("rm $B/$s/x", repo))
    rc, stdout, _stderr = run_hook_with_raising_log_fire(
        HOOK_BASENAME, payload, cwd=repo,
        extra_env={"AE_RM_GUARD_DISABLE": ""},
    )
    assert rc == 0, (rc, stdout, _stderr)
    decision, _reason = _decision(stdout)
    assert decision == "deny", stdout


def main():
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  [FAIL] {name}: {exc!r}")
    if failed:
        print(f"{failed} of {len(tests)} test(s) FAILED.")
        sys.exit(1)
    print(f"All {len(tests)} tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
