# Run with: python3 hooks/tests/test-enforcement-log.py
"""
Unit tests for hooks/lib/enforcement_log.py (the shared fire-logging helper
introduced for the enforce-*.py fire-log project - see hooks/AGENTS.md).

Covers:
  1. A realistic payload produces a well-formed JSONL line with the
     expected fields (ts, hook, decision, reason).
  2. Multiple fires append multiple lines (no overwrite).
  3. Reason strings longer than the cap are truncated, never raise.
  4. Fail-open: an unwritable .agentic/ path (a file where a directory is
     expected) never raises and never touches stdout/stderr.
  5. cwd resolution: an explicit data["cwd"] is honored; a missing/blank
     cwd falls back to os.getcwd().
  6. Non-dict data is tolerated (treated as {} for cwd purposes).
  7-8. Repo-root anchoring and worktree aggregation.
  9. session_id/agent_id/tool_use_id join keys: present, absent,
     non-string, byte-identity, length cap, and fail-open.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import contextlib

LIB_PATH = os.path.join(os.path.dirname(__file__), "..", "lib", "enforcement_log.py")

_spec = importlib.util.spec_from_file_location("enforcement_log", LIB_PATH)
enforcement_log = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(enforcement_log)

failed = 0
total = 0


def check(label: str, condition: bool) -> None:
    global failed, total
    total += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    print(f"  [{status}] {label}")


def read_lines(cwd: str) -> list:
    path = os.path.join(cwd, ".agentic", ".enforcement-fires.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# 1. Well-formed line for a realistic payload
# ---------------------------------------------------------------------------
print("Test 1: well-formed line for a realistic payload")
tmp1 = tempfile.mkdtemp(prefix="test-enforcement-log-1-")
payload = {
    "tool_name": "Agent",
    "cwd": tmp1,
    "tool_input": {"subagent_type": "engineer", "model": "claude-haiku-4"},
}
enforcement_log.log_fire(payload, "enforce-tier", "deny", "explicit sub-Opus downgrade")
lines = read_lines(tmp1)
check("exactly one line written", len(lines) == 1)
if lines:
    entry = lines[0]
    check("has ts field (string)", isinstance(entry.get("ts"), str) and len(entry["ts"]) > 0)
    check("ts looks ISO8601 UTC (ends with Z)", entry.get("ts", "").endswith("Z"))
    check("hook field correct", entry.get("hook") == "enforce-tier")
    check("decision field correct", entry.get("decision") == "deny")
    check("reason field correct", entry.get("reason") == "explicit sub-Opus downgrade")

# ---------------------------------------------------------------------------
# 2. Multiple fires append multiple lines (no overwrite)
# ---------------------------------------------------------------------------
print("\nTest 2: multiple fires append, do not overwrite")
tmp2 = tempfile.mkdtemp(prefix="test-enforcement-log-2-")
for i in range(3):
    enforcement_log.log_fire({"cwd": tmp2}, "enforce-shippable-edit", "deny", f"reason-{i}")
lines2 = read_lines(tmp2)
check("three lines written", len(lines2) == 3)
check(
    "lines in append order",
    [e["reason"] for e in lines2] == ["reason-0", "reason-1", "reason-2"],
)

# ---------------------------------------------------------------------------
# 3. Reason truncation
# ---------------------------------------------------------------------------
print("\nTest 3: reason string truncation")
tmp3 = tempfile.mkdtemp(prefix="test-enforcement-log-3-")
long_reason = "x" * 5000
enforcement_log.log_fire({"cwd": tmp3}, "enforce-background-spawn", "deny", long_reason)
lines3 = read_lines(tmp3)
check("one line written despite huge reason", len(lines3) == 1)
if lines3:
    check("reason truncated to <= 800 chars", len(lines3[0]["reason"]) <= 800)
    check("reason truncated to exactly 800 chars", len(lines3[0]["reason"]) == 800)

# ---------------------------------------------------------------------------
# 4. Fail-open: unwritable .agentic/ path (a file, not a directory)
# ---------------------------------------------------------------------------
print("\nTest 4: fail-open on unwritable .agentic/ path")
tmp4 = tempfile.mkdtemp(prefix="test-enforcement-log-4-")
agentic_as_file = os.path.join(tmp4, ".agentic")
with open(agentic_as_file, "w", encoding="utf-8") as f:
    f.write("not a directory")

stdout_capture = io.StringIO()
stderr_capture = io.StringIO()
raised = False
try:
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        enforcement_log.log_fire({"cwd": tmp4}, "enforce-tier", "deny", "should not crash")
except Exception:
    raised = True

check("log_fire never raises on unwritable path", raised is False)
check("nothing written to stdout", stdout_capture.getvalue() == "")
check("nothing written to stderr", stderr_capture.getvalue() == "")

# ---------------------------------------------------------------------------
# 5. cwd resolution: explicit cwd honored; missing/blank falls back
# ---------------------------------------------------------------------------
print("\nTest 5: cwd resolution")
tmp5 = tempfile.mkdtemp(prefix="test-enforcement-log-5-")
enforcement_log.log_fire({"cwd": tmp5}, "enforce-tier", "deny", "explicit cwd")
check("explicit cwd honored", len(read_lines(tmp5)) == 1)

# Blank cwd falls back to os.getcwd() - verify by chdir'ing into a fresh temp
# dir and confirming the write lands there, not at the pre-chdir location.
tmp5b = tempfile.mkdtemp(prefix="test-enforcement-log-5b-")
_orig_cwd = os.getcwd()
try:
    os.chdir(tmp5b)
    enforcement_log.log_fire({"cwd": "   "}, "enforce-tier", "deny", "blank cwd falls back")
    check("blank cwd falls back to os.getcwd()", len(read_lines(tmp5b)) == 1)
finally:
    os.chdir(_orig_cwd)

# Missing cwd key entirely.
tmp5c = tempfile.mkdtemp(prefix="test-enforcement-log-5c-")
try:
    os.chdir(tmp5c)
    enforcement_log.log_fire({}, "enforce-tier", "deny", "absent cwd falls back")
    check("absent cwd key falls back to os.getcwd()", len(read_lines(tmp5c)) == 1)
finally:
    os.chdir(_orig_cwd)

# ---------------------------------------------------------------------------
# 6. Non-dict data tolerated
# ---------------------------------------------------------------------------
print("\nTest 6: non-dict data tolerated (treated as {})")
tmp6 = tempfile.mkdtemp(prefix="test-enforcement-log-6-")
raised6 = False
try:
    os.chdir(tmp6)
    enforcement_log.log_fire(None, "enforce-tier", "deny", "non-dict data")
    enforcement_log.log_fire("not a dict", "enforce-tier", "deny", "non-dict data 2")
    enforcement_log.log_fire(42, "enforce-tier", "deny", "non-dict data 3")
except Exception:
    raised6 = True
finally:
    os.chdir(_orig_cwd)
check("non-dict data never raises", raised6 is False)
check("non-dict data falls back to os.getcwd() and writes", len(read_lines(tmp6)) == 3)

# ---------------------------------------------------------------------------
# 7. DS-171 repo-root anchoring: a payload cwd DRIFTED to a subdirectory of
#    a real git repo must write at the repo ROOT, never at the drifted
#    subdirectory - this is the actual bug this test guards against a
#    regression of. Reverting enforcement_log.py's `os.path.join(cwd,
#    ".agentic")` back to a raw cwd join (undoing the resolve_agentic_cwd
#    wrap) is the mutation that must turn this test red.
# ---------------------------------------------------------------------------
print("\nTest 7: DS-171 repo-root anchoring (drifted cwd inside a real git repo)")
tmp7 = tempfile.mkdtemp(prefix="test-enforcement-log-7-")
tmp7 = os.path.realpath(tmp7)
os.makedirs(os.path.join(tmp7, ".git"))  # fake repo root marker
drifted = os.path.join(tmp7, "a", "b", "c")
os.makedirs(drifted)

enforcement_log.log_fire({"cwd": drifted}, "enforce-tier", "deny", "drift anchoring probe")

root_lines = read_lines(tmp7)
drifted_lines = read_lines(drifted)
check("write landed at the repo ROOT, not the drifted cwd", len(root_lines) == 1)
check("NO phantom .agentic/ tree at the drifted subdirectory", len(drifted_lines) == 0)
check(
    "no phantom .agentic dir exists at the drifted path at all",
    not os.path.isdir(os.path.join(drifted, ".agentic")),
)

# ---------------------------------------------------------------------------
# 8. Worktree fire-log aggregation: a fire from a cwd inside a LINKED git
#    worktree (its own .git is a FILE pointing into a
#    <primary>/.git/worktrees/<name> admin dir) must land in the PRIMARY
#    checkout's .agentic/.enforcement-fires.jsonl, not the worktree's own
#    throwaway copy. This is the actual defect this test guards against a
#    regression of: reverting the log_fire() root resolution back to a bare
#    resolve_agentic_cwd(cwd) call (dropping the _resolve_primary_root
#    follow-through) must turn this test red.
# ---------------------------------------------------------------------------
print("\nTest 8: worktree fire-log aggregation lands at the primary checkout")
tmp8 = tempfile.mkdtemp(prefix="test-enforcement-log-8-")
tmp8 = os.path.realpath(tmp8)
primary8 = os.path.join(tmp8, "primary")
os.makedirs(os.path.join(primary8, ".git"))  # fake primary checkout root marker

worktree8 = os.path.join(tmp8, "primary", ".claude", "worktrees", "agent-abc123")
os.makedirs(worktree8)
git_admin_dir = os.path.join(primary8, ".git", "worktrees", "agent-abc123")
os.makedirs(git_admin_dir)
with open(os.path.join(worktree8, ".git"), "w", encoding="utf-8") as f:
    f.write(f"gitdir: {git_admin_dir}\n")

enforcement_log.log_fire(
    {"cwd": worktree8}, "enforce-worktree-read", "deny", "worktree aggregation probe"
)

primary8_lines = read_lines(primary8)
worktree8_lines = read_lines(worktree8)
check(
    "fire row landed at the PRIMARY checkout, not the worktree",
    len(primary8_lines) == 1,
)
check(
    "NO stranded fire row written inside the worktree itself",
    len(worktree8_lines) == 0,
)
if primary8_lines:
    check(
        "primary-checkout row carries the expected hook/decision",
        primary8_lines[0].get("hook") == "enforce-worktree-read"
        and primary8_lines[0].get("decision") == "deny",
    )

# 8b. A submodule's .git is also a FILE, but its gitdir pointer has no
# `.git/worktrees/` admin-dir segment - must NOT be treated as a worktree
# and must write at its own root, exactly as before this fix.
print("\nTest 8b: a submodule-shaped .git file is not treated as a worktree")
tmp8b = tempfile.mkdtemp(prefix="test-enforcement-log-8b-")
tmp8b = os.path.realpath(tmp8b)
host8b = os.path.join(tmp8b, "host")
sub8b = os.path.join(tmp8b, "host", "sub")
os.makedirs(os.path.join(host8b, ".git", "modules", "sub"), exist_ok=True)
os.makedirs(sub8b, exist_ok=True)
with open(os.path.join(sub8b, ".git"), "w", encoding="utf-8") as f:
    f.write(f"gitdir: {os.path.join(host8b, '.git', 'modules', 'sub')}\n")
enforcement_log.log_fire({"cwd": sub8b}, "enforce-tier", "deny", "submodule probe")
check("submodule root keeps its own fire row (not redirected)", len(read_lines(sub8b)) == 1)

# ---------------------------------------------------------------------------
# 9. Session join keys: session_id/agent_id/tool_use_id copied from the
#    payload only when each is a non-empty string; absent keys leave the
#    line byte-identical to the canonical 4-field (or 4-field + detail) form.
# ---------------------------------------------------------------------------
print("\nTest 9: session join keys")


def raw_lines(cwd: str) -> list:
    path = os.path.join(cwd, ".agentic", ".enforcement-fires.jsonl")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines(keepends=True)


def canonical(ts: str, reason: str, **extra) -> str:
    entry = {"ts": ts, "hook": "enforce-tier", "decision": "deny", "reason": reason}
    entry.update(extra)
    return json.dumps(entry) + "\n"


tmp9 = os.path.realpath(tempfile.mkdtemp(prefix="test-enforcement-log-9-"))
ids = {"session_id": "sess-1", "agent_id": "agent-2", "tool_use_id": "toolu_3"}
enforcement_log.log_fire(dict(ids, cwd=tmp9), "enforce-tier", "deny", "present")
enforcement_log.log_fire({"cwd": tmp9}, "enforce-tier", "deny", "absent")
enforcement_log.log_fire(
    {"cwd": tmp9}, "enforce-tier", "deny", "absent+detail", detail={"k": 1}
)
enforcement_log.log_fire(
    {"cwd": tmp9, "session_id": None, "agent_id": 7, "tool_use_id": ""},
    "enforce-tier", "deny", "non-string",
)
enforcement_log.log_fire(
    {"cwd": tmp9, "session_id": ["x"], "agent_id": {"a": 1}, "tool_use_id": True},
    "enforce-tier", "deny", "non-string-2",
)
enforcement_log.log_fire(
    {"cwd": tmp9, "session_id": "sess-only"}, "enforce-tier", "deny", "partial"
)
raw9 = raw_lines(tmp9)
rows9 = [json.loads(line) for line in raw9]
check("six lines written", len(raw9) == 6)
if len(raw9) == 6:
    check(
        "present: all three keys written with their values",
        all(rows9[0].get(k) == v for k, v in ids.items()),
    )
    check(
        "present: keys follow the canonical 4 fields",
        raw9[0] == canonical(rows9[0]["ts"], "present", **ids),
    )
    check(
        "absent: line byte-identical to the canonical 4-field form",
        raw9[1] == canonical(rows9[1]["ts"], "absent"),
    )
    check(
        "absent + detail: line byte-identical to the 4-field + detail form",
        raw9[2] == canonical(rows9[2]["ts"], "absent+detail", detail={"k": 1}),
    )
    check(
        "None/int/empty-string values omitted, never written",
        raw9[3] == canonical(rows9[3]["ts"], "non-string"),
    )
    check(
        "list/dict/bool values omitted, never written",
        raw9[4] == canonical(rows9[4]["ts"], "non-string-2"),
    )
    check(
        "partial: only the present key is written",
        raw9[5] == canonical(rows9[5]["ts"], "partial", session_id="sess-only"),
    )
    check("no row anywhere carries a null value", "null" not in "".join(raw9))


class _RaisingGet(dict):
    def get(self, key, default=None):
        if key in ids:
            raise RuntimeError("boom")
        return super().get(key, default)


out9, err9 = io.StringIO(), io.StringIO()
raised9 = False
try:
    with contextlib.redirect_stdout(out9), contextlib.redirect_stderr(err9):
        enforcement_log.log_fire(_RaisingGet(cwd=tmp9), "enforce-tier", "deny", "raise")
except Exception:
    raised9 = True
check("a raising payload lookup never propagates", raised9 is False)
check("a raising payload lookup prints nothing", out9.getvalue() == "" and err9.getvalue() == "")

tmp9b = tempfile.mkdtemp(prefix="test-enforcement-log-9b-")
enforcement_log.log_fire(
    {"cwd": tmp9b, "session_id": "s" * 5000, "agent_id": "a" * 200, "tool_use_id": "t" * 201},
    "enforce-tier", "deny", "long ids",
)
rows9b = read_lines(tmp9b)
check("long-ids: one line written", len(rows9b) == 1)
if rows9b:
    check("session_id truncated to 200 chars", rows9b[0].get("session_id") == "s" * 200)
    check("agent_id at exactly 200 chars kept whole", rows9b[0].get("agent_id") == "a" * 200)
    check("tool_use_id at 201 chars truncated to 200", rows9b[0].get("tool_use_id") == "t" * 200)

print(f"\n{total - failed}/{total} tests passed.")
if failed:
    print(f"FAILED: {failed} test(s) failed.")
    sys.exit(1)
else:
    print("All tests passed.")
    sys.exit(0)
