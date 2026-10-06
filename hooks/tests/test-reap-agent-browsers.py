# Run with: python3 hooks/tests/test-reap-agent-browsers.py
"""
Tests for hooks/reap-agent-browsers.py.

Nothing here touches the machine it runs on: HOME is a scratch directory
for the whole run, the process table is a fixture, the signal sender and
the close runner are fakes, and the module-level ps/signal functions are
replaced with ones that fail the test if a code path reaches them
uninjected. The subprocess cases either stop before the process table is
read (empty or garbage stdin, the kill switch) or run the hook through a
wrapper that injects the same fakes and uses a stub agent-browser.

AE_REAPER_HOOK_UNDER_TEST, when set, points the suite at a mutated copy
of the hook; that is how each named mutation is run.

main() runs every test_* function and exits 1 if any raises AssertionError.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HOOK_PATH = os.environ.get("AE_REAPER_HOOK_UNDER_TEST") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reap-agent-browsers.py",
)

SCRATCH = tempfile.mkdtemp(prefix="reaper-test-")
os.environ["HOME"] = os.path.join(SCRATCH, "home")
os.makedirs(os.environ["HOME"])
os.environ.pop("AE_BROWSER_REAPER_DISABLE", None)

_spec = importlib.util.spec_from_file_location("reap_agent_browsers", HOOK_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _forbidden(*_a, **_k):
    raise AssertionError("a code path reached the real process table or signal sender")


mod.ps_rows = _forbidden
mod.send_signal = _forbidden

HOME = os.environ["HOME"]
AB_DIR = os.path.join(HOME, ".agent-browser")
LOG = os.path.join(HOME, ".agentic", "browser-reaper.log")
NOW = 1_800_000_000.0
# Real subagent transcript lines carry their agentId, so the ending agent's
# own id always appears in its own transcript.
AGENT_ID = "a670c93d0ae6ec5dc"


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"


# ---------------------------------------------------------------------------
# (a) extraction
# ---------------------------------------------------------------------------

POSITIVE = [
    ("agent-browser open about:blank --session a1", "a1"),
    ("agent-browser --session a2 open about:blank", "a2"),
    ("agent-browser --session=a3 --headed open about:blank", "a3"),
    ("FOO=1 /Users/x/.local/bin/agent-browser --profile p --session a4 open about:blank", "a4"),
    ("AGENT_BROWSER_SESSION=a5 agent-browser open about:blank", "a5"),
    ("env AGENT_BROWSER_SESSION=a6 agent-browser open about:blank | tee /tmp/o", "a6"),
    ("cd /tmp;\nagent-browser open about:blank --session a7", "a7"),
    ("agent-browser \\\n--session c1 open u", "c1"),
    ('bash -c "agent-browser open u --session c2"', "c2"),
    ("sh -lc 'agent-browser open u --session c6'", "c6"),
    ("npx -y agent-browser@0.27.0 --session c3 open u", "c3"),
    ("agent-browser -p ios --session c4 open u", "c4"),
    ("export AGENT_BROWSER_SESSION=c5; agent-browser open u", "c5"),
    ("agent-browser --json false open u --session j1", "j1"),
    ("agent-browser --headed false open u --session h1", "h1"),
]

NEGATIVE = [
    'grep -rn "agent-browser --session X" .',
    "agent-browser --session theirs get url",
    "agent-browser get url --session probe-x",
    "echo agent-browser open x --session nope",
    'agent-browser eval "open" --session nope2',
    'bash -c "echo agent-browser open --session n"',
    "agent-browser --headed false open u",
    "unknownwrap agent-browser --session n open u",
]


def test_extraction_positives():
    misses = [(c, want, mod.opened_sessions(c)) for c, want in POSITIVE
              if mod.opened_sessions(c) != {want}]
    assert not misses, misses


def test_extraction_negatives():
    hits = [(c, mod.opened_sessions(c)) for c in NEGATIVE if mod.opened_sessions(c)]
    assert not hits, hits


# ---------------------------------------------------------------------------
# (b) ownership window
# ---------------------------------------------------------------------------

def test_owned_inside_window():
    assert mod.owned({"s": [(100.0, 110.0)]}, {"s": 105.0}, NOW) == {"s"}


def test_owned_rejects_name_reuse_after_window():
    assert mod.owned({"s": [(100.0, 110.0)]}, {"s": 700.0}, NOW) == set()


def test_owned_rejects_daemon_that_predates_open():
    assert mod.owned({"s": [(100.0, 110.0)]}, {"s": 50.0}, NOW) == set()


def test_owned_without_result_is_capped_at_the_bash_timeout():
    # An open with no tool_result (agent killed mid-command) may still own a
    # daemon that came up while the command could have been running...
    assert mod.owned({"s": [(100.0, None)]}, {"s": 650.0}, 10_000.0) == {"s"}
    # ...but never one started after the Bash tool's 600 s maximum.
    assert mod.owned({"s": [(100.0, None)]}, {"s": 900.0}, 10_000.0) == set()


def test_owned_never_default_or_dead():
    assert mod.owned({"default": [(100.0, 110.0)], "x": [(100.0, 110.0)]},
                     {"default": 105.0}, NOW) == set()


# ---------------------------------------------------------------------------
# (c) transcript windows
# ---------------------------------------------------------------------------

def write_transcript(path, items):
    """items: [(timestamp, role, content-list)]"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for ts, role, content in items:
            f.write(json.dumps({"type": role, "timestamp": iso(ts),
                                "agentId": AGENT_ID,
                                "message": {"role": role, "content": content}}) + "\n")


def bash_use(tid, cmd):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}


def result(tid):
    return {"type": "tool_result", "tool_use_id": tid, "content": "ok"}


def test_transcript_slow_command_window():
    path = os.path.join(SCRATCH, "c", "t.jsonl")
    write_transcript(path, [
        (1000, "assistant", [bash_use("t1", "agent-browser open u --session slow")]),
        (1000, "assistant", [{"type": "text", "text": "agent-browser --session other open x"}]),
        (1030, "user", [result("t1")]),
    ])
    cands = mod.candidates_from_transcript(path, time.monotonic() + 5)
    assert cands == {"slow": [(1000.0, 1030.0)]}, cands
    # The daemon came up 20 s into a 30 s open: owned only if the window's
    # upper bound is the tool_result time.
    assert mod.owned(cands, {"slow": 1020.0}, NOW) == {"slow"}


def test_transcript_overrun_drops_open_without_result():
    path = os.path.join(SCRATCH, "c2", "t.jsonl")
    write_transcript(path, [
        (1000, "assistant", [bash_use("t1", "agent-browser open u --session late")]),
        (1001, "user", [result("t1")]),
    ])
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    saved = mod.time.monotonic
    mod.time.monotonic = lambda: next(ticks)
    try:
        # The open line is read before the deadline, the result line after it.
        cands = mod.candidates_from_transcript(path, 50.0)
    finally:
        mod.time.monotonic = saved
    assert cands == {}, cands


# ---------------------------------------------------------------------------
# (d) orphan selection
# ---------------------------------------------------------------------------

CHROME = "/x/Google Chrome for Testing"
ORPHAN_ROWS = {
    10: (1, 60, CHROME + " --user-data-dir=/var/T/agent-browser-chrome-aaa --remote-debugging-port=0"),
    20: (30, 60, CHROME + " --user-data-dir=/var/T/agent-browser-chrome-bbb"),
    30: (1, 60, "/Users/x/.local/bin/agent-browser daemon"),
    40: (999, 60, "chromium --user-data-dir=/var/T/playwright_chromiumdev_profile-ccc"),
    50: (1, 60, CHROME + " --type=renderer --user-data-dir=/var/T/agent-browser-chrome-aaa"),
    60: (1, 60, "/x/chrome_crashpad_handler --database=/y"),
    70: (1, 60, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--user-data-dir=/Users/x/Library/Application Support/Google/Chrome"),
}


def test_select_orphans():
    assert mod.select_orphans(ORPHAN_ROWS) == [10, 40], mod.select_orphans(ORPHAN_ROWS)


# ---------------------------------------------------------------------------
# (e) dispatch, through main() with every machine-facing call injected
# ---------------------------------------------------------------------------

class Run:
    def __init__(self):
        self.closes = []
        self.signals = []
        self.ps_calls = 0


def reset_home():
    shutil.rmtree(HOME, ignore_errors=True)
    os.makedirs(AB_DIR)


def run_main(payload, rows=None, pids=None, binary="/fake/agent-browser", raw=None):
    """pids: name -> pid written to ~/.agent-browser/<name>.pid."""
    rec = Run()
    for name, pid in (pids or {}).items():
        with open(os.path.join(AB_DIR, name + ".pid"), "w") as f:
            f.write(str(pid))

    def fake_ps(timeout):
        rec.ps_calls += 1
        return dict(rows or {})

    def fake_run(argvs, budget):
        rec.closes.extend(argvs)
        return [(a, 0) for a in argvs]

    saved = (mod.ps_rows, mod.send_signal, mod.run_bounded, mod.find_binary,
             mod.time.time, sys.stdin)
    mod.ps_rows = fake_ps
    mod.send_signal = lambda pid, sig: rec.signals.append(pid)
    mod.run_bounded = fake_run
    mod.find_binary = lambda: binary
    mod.time.time = lambda: NOW
    sys.stdin = io.StringIO(raw if raw is not None else json.dumps(payload))
    mod._state["event"] = None
    try:
        mod.main()
    finally:
        (mod.ps_rows, mod.send_signal, mod.run_bounded, mod.find_binary,
         mod.time.time, sys.stdin) = saved
    return rec


def log_text():
    try:
        with open(LOG) as f:
            return f.read()
    except OSError:
        return ""


def owned_fixture(name="mine", now=NOW, launched_task=None):
    """A transcript that opened `name` at now-100..now-95 and a live daemon
    for it that started at now-97. launched_task, when given, is the id of a
    background task this agent started, named in its own tool_result."""
    path = os.path.join(HOME, "proj", "sess.jsonl")
    items = [
        (now - 100, "assistant", [bash_use("t1", "agent-browser open u --session " + name)]),
        (now - 95, "user", [result("t1")]),
    ]
    if launched_task:
        items.append((now - 90, "assistant", [bash_use("t2", "sleep 60")]))
        items.append((now - 90, "user", [{"type": "tool_result", "tool_use_id": "t2",
                                           "content": "running in background with ID: " + launched_task}]))
    write_transcript(path, items)
    rows = {4242: (1, 97, "agent-browser daemon")}
    return path, rows, {name: 4242}


def test_stop_event_is_ignored():
    reset_home()
    path, rows, pids = owned_fixture()
    rec = run_main({"hook_event_name": "Stop", "transcript_path": path}, rows, pids)
    assert rec.closes == [] and rec.ps_calls == 0 and rec.signals == [], vars(rec)
    assert log_text() == ""


def test_subagent_stop_ignores_parent_transcript_path():
    reset_home()
    path, rows, pids = owned_fixture()
    rec = run_main({"hook_event_name": "SubagentStop", "transcript_path": path}, rows, pids)
    assert rec.closes == [], rec.closes


def test_subagent_stop_closes_owned_session():
    reset_home()
    path, rows, pids = owned_fixture()
    rec = run_main({"hook_event_name": "SubagentStop", "agent_id": "a1",
                    "agent_transcript_path": path}, rows, pids)
    assert rec.closes == [["/fake/agent-browser", "close", "--session", "mine"]], rec.closes
    assert "closed=[mine]" in log_text(), log_text()


SELF_TASK ={"id": AGENT_ID, "type": "subagent", "status": "running",
             "description": "x", "agent_type": "general-purpose"}


def bg_payload(path, tasks=(), crons=()):
    return {"hook_event_name": "SubagentStop", "agent_id": AGENT_ID,
            "agent_transcript_path": path, "background_tasks": list(tasks),
            "session_crons": list(crons)}


def test_own_background_task_defers_close():
    reset_home()
    path, rows, pids = owned_fixture(launched_task="bshell123abc")
    rows[77] = ORPHAN_ROWS[10]
    task = {"id": "bshell123abc", "type": "shell", "status": "running", "description": "x"}
    rec = run_main(bg_payload(path, [SELF_TASK, task]), rows, pids)
    assert rec.closes == [], rec.closes
    assert rec.signals == [77], rec.signals
    assert "verdict=deferred own_pending=[bshell123abc]" in log_text(), log_text()


def test_own_session_cron_defers_close():
    reset_home()
    path, rows, pids = owned_fixture(launched_task="cron98765xyz")
    rec = run_main(bg_payload(path, crons=[{"id": "cron98765xyz", "schedule": "* * * * *",
                                            "recurring": False, "prompt": "p"}]), rows, pids)
    assert rec.closes == [], rec.closes


def test_background_subagent_listing_only_itself_still_closes():
    # Measured on Claude Code 2.1.287: a background subagent's own SubagentStop
    # lists that subagent in background_tasks.
    reset_home()
    path, rows, pids = owned_fixture()
    rec = run_main(bg_payload(path, [SELF_TASK]), rows, pids)
    assert [a[3] for a in rec.closes] == ["mine"], rec.closes


def test_sibling_background_work_does_not_block_close():
    reset_home()
    path, rows, pids = owned_fixture()
    sibling = {"id": "asibling00000001", "type": "subagent", "status": "running", "description": "y"}
    rec = run_main(bg_payload(path, [SELF_TASK, sibling]), rows, pids)
    assert [a[3] for a in rec.closes] == ["mine"], rec.closes
    assert "others_in_flight=1" in log_text(), log_text()


def test_unidentified_background_entry_defers_close():
    reset_home()
    path, rows, pids = owned_fixture()
    rec = run_main(bg_payload(path, [{"type": "shell"}]), rows, pids)
    assert rec.closes == [], rec.closes


def test_own_pending_read_past_deadline_defers():
    reset_home()
    path, _rows, _pids = owned_fixture()
    sibling = {"id": "asibling00000001", "type": "subagent", "status": "running", "description": "y"}
    own, _others = mod.own_pending_work(bg_payload(path, [SELF_TASK, sibling]), [path],
                                        time.monotonic() - 1)
    assert "scan-deadline" in own, own


def test_slow_own_pending_read_defers_close_in_main():
    reset_home()
    path, rows, pids = owned_fixture()
    sibling = {"id": "asibling00000001", "type": "subagent", "status": "running", "description": "y"}
    saved = mod.SCAN_BUDGET_S
    mod.SCAN_BUDGET_S = -1.0
    try:
        rec = run_main(bg_payload(path, [SELF_TASK, sibling]), rows, pids)
    finally:
        mod.SCAN_BUDGET_S = saved
    assert rec.closes == [], rec.closes
    assert "own_pending=[scan-deadline]" in log_text(), log_text()


def test_session_end_closes_main_and_unstopped_subagent_sessions():
    reset_home()
    path, rows, pids = owned_fixture("mainsess")
    sub = os.path.join(path[:-6], "subagents", "agent-x.jsonl")
    write_transcript(sub, [
        (NOW - 50, "assistant", [bash_use("s1", "agent-browser --session subsess open u")]),
        (NOW - 49, "user", [result("s1")]),
    ])
    rows[5151] = (1, 50, "agent-browser daemon")
    pids["subsess"] = 5151
    rec = run_main({"hook_event_name": "SessionEnd", "reason": "resume",
                    "transcript_path": path}, rows, pids)
    closed = sorted(a[3] for a in rec.closes)
    assert closed == ["mainsess", "subsess"], rec.closes
    assert "reason=resume" in log_text(), log_text()


def test_name_reuse_is_skipped_and_logged():
    reset_home()
    path, _rows, pids = owned_fixture("reuse")
    rows = {4242: (1, 5, "agent-browser daemon")}
    rec = run_main({"hook_event_name": "SubagentStop", "agent_transcript_path": path},
                   rows, pids)
    assert rec.closes == [], rec.closes
    assert "reuse:daemon-start-outside-window" in log_text(), log_text()


def test_kill_switch_logs_and_does_nothing():
    reset_home()
    path, rows, pids = owned_fixture()
    os.environ["AE_BROWSER_REAPER_DISABLE"] = "1"
    try:
        rec = run_main({"hook_event_name": "SubagentStop", "agent_transcript_path": path},
                       rows, pids)
    finally:
        del os.environ["AE_BROWSER_REAPER_DISABLE"]
    assert rec.closes == [] and rec.ps_calls == 0, vars(rec)
    assert "verdict=disabled" in log_text(), log_text()


def test_no_binary_closes_nothing_and_skips_prune():
    reset_home()
    path, rows, pids = owned_fixture()
    pids["stale"] = 31337
    rec = run_main({"hook_event_name": "SubagentStop", "agent_transcript_path": path},
                   rows, pids, binary=None)
    assert rec.closes == [], rec.closes
    assert "mine:no-binary" in log_text() and "pruned=False" in log_text(), log_text()


def test_empty_stdin_is_a_silent_noop():
    reset_home()
    rec = run_main(None, raw="")
    assert rec.ps_calls == 0 and log_text() == "", vars(rec)


def test_dead_pid_file_triggers_prune():
    reset_home()
    rec = run_main({"hook_event_name": "SubagentStop", "agent_transcript_path": "/nope"},
                   {}, {"stale": 31337})
    assert rec.closes == [["/fake/agent-browser", "session", "list"]], rec.closes


# ---------------------------------------------------------------------------
# (f) the real script as a subprocess
# ---------------------------------------------------------------------------

WRAPPER = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("r", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rows = {int(k): tuple(v) for k, v in json.loads(sys.argv[2]).items()}
m.ps_rows = lambda timeout: rows
def no_signal(pid, sig):
    raise SystemExit("signal attempted")
m.send_signal = no_signal
m._entry()
"""


def run_script(stdin, env_extra=None, rows=None, wrapped=False, timeout=20):
    env = {"PATH": "/usr/bin:/bin", "HOME": HOME}
    env.update(env_extra or {})
    if wrapped:
        argv = [sys.executable, "-c", WRAPPER, HOOK_PATH, json.dumps(rows or {})]
    else:
        argv = [sys.executable, HOOK_PATH]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - t0, "timed out after %ds" % timeout
    return proc.returncode, time.monotonic() - t0, proc.stderr


def test_script_garbage_and_empty_stdin_exit_zero_silently():
    reset_home()
    for stdin in ("not json{", "", "[1, 2]"):
        rc, _, err = run_script(stdin)
        assert rc == 0, (stdin, rc, err)
    assert log_text() == "", log_text()


def test_script_kill_switch_exits_zero():
    reset_home()
    rc, _, err = run_script(json.dumps({"hook_event_name": "SubagentStop"}),
                            {"AE_BROWSER_REAPER_DISABLE": "1"})
    assert rc == 0 and "verdict=disabled" in log_text(), (rc, err, log_text())


def test_script_minimal_path_without_binary():
    reset_home()
    path, rows, pids = owned_fixture(now=time.time())
    with open(os.path.join(AB_DIR, "mine.pid"), "w") as f:
        f.write("4242")
    payload = json.dumps({"hook_event_name": "SubagentStop", "agent_transcript_path": path})
    rc, elapsed, err = run_script(payload, rows=rows, wrapped=True)
    assert rc == 0 and elapsed < 6, (rc, elapsed, err)
    assert "mine:no-binary" in log_text(), log_text()


def test_script_hung_close_is_killed_inside_deadline():
    reset_home()
    path, rows, pids = owned_fixture(now=time.time())
    with open(os.path.join(AB_DIR, "mine.pid"), "w") as f:
        f.write("4242")
    bindir = os.path.join(HOME, ".local", "bin")
    os.makedirs(bindir)
    pidfile = os.path.join(SCRATCH, "stub.pid")
    stub = os.path.join(bindir, "agent-browser")
    with open(stub, "w") as f:
        f.write("#!/bin/sh\necho $$ > '%s'\nexec sleep 30\n" % pidfile)
    os.chmod(stub, 0o755)
    payload = json.dumps({"hook_event_name": "SubagentStop", "agent_transcript_path": path})
    rc, elapsed, err = run_script(payload, rows=rows, wrapped=True)
    assert rc == 0 and elapsed < 6, (rc, elapsed, err)
    assert "mine:close-timeout" in log_text(), log_text()
    with open(pidfile) as f:
        stub_pid = int(f.read())
    try:
        os.kill(stub_pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, "stub agent-browser %d survived the hook" % stub_pid


# ---------------------------------------------------------------------------
# (g) log rotation, (h) manifest
# ---------------------------------------------------------------------------

def test_log_rotates_above_one_mib():
    reset_home()
    os.makedirs(os.path.dirname(LOG))
    with open(LOG, "w") as f:
        f.write("x" * (1024 * 1024 + 1))
    mod.write_log("event=SubagentStop verdict=ran")
    assert os.path.exists(LOG + ".1"), "no rotated log"
    assert os.path.getsize(LOG + ".1") == 1024 * 1024 + 1
    assert os.path.getsize(LOG) < 200, os.path.getsize(LOG)


def _manifest_field(name):
    doc = mod.__doc__ or ""
    for i, line in enumerate(doc.splitlines()):
        if line.startswith(name + ":"):
            rest = [line[len(name) + 1:].strip()]
            for nxt in doc.splitlines()[i + 1:]:
                if not nxt.strip() or (nxt[:1] != " " and ":" in nxt):
                    break
                rest.append(nxt.strip())
            return " ".join(r for r in rest if r)
    return ""


def test_manifest_names_catch_and_retirement():
    assert "memory exhaustion" in _manifest_field("Catch"), _manifest_field("Catch")
    assert "browser-reaper.log" in _manifest_field("Retirement"), _manifest_field("Retirement")


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print("  [PASS] %s" % name)
            except AssertionError as exc:
                failed += 1
                print("  [FAIL] %s: %r" % (name, exc))
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    if failed:
        print("%d of %d test(s) FAILED." % (failed, len(tests)))
        sys.exit(1)
    print("All %d tests passed." % len(tests))
    sys.exit(0)


if __name__ == "__main__":
    main()
