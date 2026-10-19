"""Purpose: Regress lane signal ownership, legacy recovery, and exit persistence.
Public API: pytest bin/tests/test_lane_runtime_safety.py.
Upstream dependencies: pytest, Git, Bash, jq, ps, POSIX processes; _lane_runtime.
Downstream consumers: bin-tests.yml pytest bin/tests/ discovery.
Failure modes: mismatched process records, nested/missing legacy provenance,
and an exit between list observations fail assertions; subprocesses are reaped.
"""

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lane_runtime", ROOT / "bin/_lane_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def write_meta(path, **fields):
    path.write_text("".join(f"{key}={value}\n" for key, value in fields.items()))


@pytest.fixture
def processes():
    children = []

    def start(*args):
        child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children.append(child)
        return child

    yield start
    for child in children:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


def test_stop_rejects_inconsistent_pid_records(tmp_path, processes):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run = tmp_path / "run"
    run.mkdir()
    owned = processes("/bin/sh", "-p", "-c", "while :; do sleep 1; done")
    decoy = processes("sleep", "60")
    birth = subprocess.check_output(["ps", "-p", str(owned.pid), "-o", "lstart="], text=True)
    write_meta(
        run / "owned.meta", claude_bin="/bin/sh", pid=decoy.pid, pid_start=runtime.re.sub(" +", " ", birth).rstrip("\n")
    )
    (run / "owned.pid").write_text(str(owned.pid) + "\n")
    result = subprocess.run(
        [str(ROOT / "bin/ds-lane"), "stop", "owned"],
        cwd=tmp_path,
        env={**os.environ, "DS_LANE_RUN_DIR": str(run)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    try:
        decoy.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    assert decoy.poll() is None, "stop signaled the unvalidated metadata PID"
    assert owned.poll() is None


@pytest.mark.parametrize("nested_first", [False, True])
def test_legacy_recovers_one_top_level_init(tmp_path, monkeypatch, nested_first):
    monkeypatch.setenv("DS_LANE_LEGACY_CLAUDE_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "legacy.meta"
    write_meta(path, claude_bin=shutil.which("sh"), session_id="original")
    top = dict(
        type="system",
        subtype="init",
        parent_tool_use_id=None,
        session_id="original",
        permissionMode="default",
        cwd=str(tmp_path),
    )
    nested = {
        **top,
        "parent_tool_use_id": "nested-tool",
        "session_id": "subagent",
        "permissionMode": "bypassPermissions",
        "cwd": "/",
    }
    previous = {**top, "session_id": "previous", "permissionMode": "acceptEdits", "cwd": "/"}
    records = [previous, nested, top] if nested_first else [previous, top, nested]
    path.with_suffix(".jsonl").write_text("".join(json.dumps(e) + "\n" for e in records))
    saved = runtime.saved(str(path))
    assert saved["permission_mode"] == "default"
    assert saved["runtime_cwd"] == str(tmp_path)
    assert saved["config_dir"] == str(tmp_path)


@pytest.mark.parametrize("missing", ["session_id", "permissionMode", "cwd", "top-level", "matching-session"])
def test_legacy_refuses_missing_or_conflicting_provenance(tmp_path, monkeypatch, missing):
    monkeypatch.setenv("DS_LANE_LEGACY_CLAUDE_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "legacy.meta"
    write_meta(path, claude_bin=shutil.which("sh"), session_id="original")
    top = dict(
        type="system",
        subtype="init",
        parent_tool_use_id=None,
        session_id="original",
        permissionMode="default",
        cwd=str(tmp_path),
    )
    if missing == "top-level":
        top["parent_tool_use_id"] = "nested-tool"
    elif missing == "matching-session":
        top["session_id"] = "different"
    else:
        del top[missing]
    path.with_suffix(".jsonl").write_text(json.dumps(top) + "\n")
    with pytest.raises(ValueError):
        runtime.saved(str(path))


@pytest.mark.parametrize(
    "fields, valid",
    [
        ({"config_env_set": "0"}, True),
        ({"config_env_set": "1", "config_env": "/explicit"}, True),
        ({"config_env_set": "1"}, False),
        ({"config_env_set": "0", "config_env": "/explicit"}, False),
        ({"config_env_set": "yes", "config_env": "/explicit"}, False),
        ({"config_env_set": "true"}, False),
    ],
)
def test_saved_config_environment_is_validated(tmp_path, fields, valid):
    path = tmp_path / "lane.meta"
    sh = str(Path(shutil.which("sh")).resolve())
    write_meta(
        path,
        harness="claude",
        executable=sh,
        claude_bin=sh,
        config_dir=tmp_path,
        runtime_cwd=tmp_path,
        permission_mode="default",
        bg_ceiling="0",
        **fields,
    )
    if valid:
        assert runtime.saved(str(path))["config_env_set"] == fields["config_env_set"]
    else:
        with pytest.raises(ValueError, match="saved config environment"):
            runtime.saved(str(path))


def test_feeder_signals_the_pid_it_validated(tmp_path, processes):
    decoy = processes("sleep", "60")
    infile = tmp_path / "owned.in"
    infile.touch()
    feeder = processes("tail", "-n", "+1", "-f", str(infile))
    (tmp_path / "owned.tailpid").write_text(str(feeder.pid))
    source = (ROOT / "bin/ds-lane").read_text()
    functions = "is_live_feeder()" + source.split("is_live_feeder()", 1)[1].split("is_live_lane()", 1)[0]
    script = (
        """RUN_DIR="$1"
ps() { printf '%s\\n' "tail -n +1 -f $RUN_DIR/owned.in"; printf '%s' "$2" > "$RUN_DIR/owned.tailpid"; }
""".replace('"$2" >', str(decoy.pid) + " >")
        + functions
        + "\nkill_feeder owned\n"
    )
    subprocess.run(["bash", "-c", script, "_", str(tmp_path)], check=True)
    try:
        decoy.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    assert decoy.poll() is None, "feeder cleanup signaled a PID read after validation"


def test_list_persists_failure_when_process_exits_between_observations(tmp_path, processes):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run = tmp_path / "run"
    run.mkdir()
    owned = processes("/bin/sh", "-p", "-c", "while :; do sleep 1; done")
    birth = subprocess.check_output(["ps", "-p", str(owned.pid), "-o", "lstart="], text=True)
    write_meta(
        run / "owned.meta",
        claude_bin="/bin/sh",
        pid=owned.pid,
        status="running",
        pid_start=runtime.re.sub(" +", " ", birth).rstrip("\n"),
    )
    (run / "owned.pid").write_text(str(owned.pid))
    (run / "owned.jsonl").write_text(json.dumps(dict(type="result", is_error=True)) + "\n")
    stub = tmp_path / "stub"
    stub.mkdir()
    ps = stub / "ps"
    ps.write_text(
        '''#!/bin/sh
if [ "$4" = lstart= ]; then
  if [ -e "$DS_TEST_PS_COUNT" ]; then exit 1; fi
  touch "$DS_TEST_PS_COUNT"
fi
exec "'''
        + shutil.which("ps")
        + """" "$@"
"""
    )
    ps.chmod(0o755)
    result = subprocess.run(
        [str(ROOT / "bin/ds-lane"), "list", "owned"],
        cwd=tmp_path,
        env={
            **os.environ,
            "DS_LANE_RUN_DIR": str(run),
            "PATH": str(stub) + os.pathsep + os.environ["PATH"],
            "DS_TEST_PS_COUNT": str(tmp_path / "ps-count"),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "dead" in result.stdout and "down" in result.stdout
    assert runtime.metadata(run / "owned.meta")["status"] == "dead"


def assistant(text):
    return dict(type="assistant", parent_tool_use_id=None, message=dict(content=[dict(type="text", text=text)]))


RESULT = dict(type="result", parent_tool_use_id=None, subtype="success", is_error=False)
FATAL = dict(type="result", parent_tool_use_id=None, subtype="error_during_execution", is_error=True)


def guarded(tmp_path, capsys, log, mode="marker", **meta):
    path = tmp_path / "lane.meta"
    write_meta(path, harness="claude", claude_bin="/bin/sh", **meta)
    path.with_suffix(".jsonl").write_text("".join(json.dumps(e) + "\n" for e in log))
    capsys.readouterr()
    runtime.events(str(path), mode)
    return capsys.readouterr().out.strip()


def test_marker_needs_a_trailing_result(tmp_path, capsys):
    assert guarded(tmp_path, capsys, [RESULT, assistant("LANE-DONE early")]) == ""
    assert guarded(tmp_path, capsys, [RESULT, assistant("LANE-DONE ok"), RESULT]) == "done"
    assert guarded(tmp_path, capsys, [assistant("LANE-BLOCKED why?"), RESULT]) == "blocked"


def test_fatal_result_after_the_marker_suppresses_it(tmp_path, capsys):
    assert guarded(tmp_path, capsys, [assistant("LANE-DONE ok"), FATAL]) == ""
    assert guarded(tmp_path, capsys, [assistant("LANE-DONE ok"), RESULT, FATAL]) == ""


def test_marker_before_the_last_needed_turn_is_ignored(tmp_path, capsys):
    first_turn = [assistant("LANE-DONE first"), RESULT]
    assert guarded(tmp_path, capsys, first_turn, results_needed=2) == ""
    assert guarded(tmp_path, capsys, first_turn + [assistant("ack"), RESULT], results_needed=2) == ""
    later = first_turn + [assistant("LANE-DONE second"), RESULT]
    assert guarded(tmp_path, capsys, later, results_needed=2) == "done"


def test_merged_input_marker_counts_after_the_grace_period(tmp_path, capsys, monkeypatch):
    merged = [assistant("LANE-DONE merged"), RESULT]
    monkeypatch.setenv("DS_LANE_MIDTURN_GRACE_S", "1")
    assert guarded(tmp_path, capsys, merged, results_needed=2) == ""
    log = tmp_path / "lane.jsonl"
    os.utime(log, (log.stat().st_atime - 5, log.stat().st_mtime - 5))
    runtime.events(str(tmp_path / "lane.meta"), "marker")
    assert capsys.readouterr().out.strip() == "done"
    with log.open("a") as stream:
        stream.write(json.dumps(assistant("still going")) + "\n")
    os.utime(log, (log.stat().st_atime - 5, log.stat().st_mtime - 5))
    runtime.events(str(tmp_path / "lane.meta"), "marker")
    assert capsys.readouterr().out.strip() == ""


NOTIFIED = dict(RESULT, origin=dict(kind="task-notification", producer="session-task"))
PEER = dict(RESULT, origin=dict(kind="peer", name="conductor"))


def backdate(tmp_path):
    log = tmp_path / "lane.jsonl"
    os.utime(log, (log.stat().st_atime - 5, log.stat().st_mtime - 5))


def test_pending_counts_only_stdin_answers_since_the_offset(tmp_path, capsys):
    log = [RESULT, assistant("x"), dict(RESULT, parent_tool_use_id="nested"), NOTIFIED, PEER, RESULT]
    assert guarded(tmp_path, capsys, log, mode="pending", marker_offset=1, results_needed=2) == "1 6"
    assert guarded(tmp_path, capsys, log, mode="pending", marker_offset=1, results_needed=1) == "0 6"


def test_notification_results_do_not_answer_a_queued_send(tmp_path, capsys, monkeypatch):
    # The queued send's own turn has not run: an unmarked stdin answer, then a notification
    # turn that prints the marker.
    log = [assistant("ack"), RESULT, assistant("LANE-DONE from a notification turn"), NOTIFIED]
    monkeypatch.setenv("DS_LANE_MIDTURN_GRACE_S", "1")
    assert guarded(tmp_path, capsys, log, results_needed=2) == ""
    assert guarded(tmp_path, capsys, log, mode="pending", results_needed=2) == "1 4"


def test_notification_results_cannot_strand_a_marked_lane(tmp_path, capsys, monkeypatch):
    # The send merged into the marked running turn, then a notification turn ran: a notification
    # result answers no stdin input, so only the grace period settles the lane.
    log = [assistant("LANE-DONE merged"), RESULT, assistant("noted"), NOTIFIED]
    monkeypatch.setenv("DS_LANE_MIDTURN_GRACE_S", "1")
    assert guarded(tmp_path, capsys, log, results_needed=2) == ""
    backdate(tmp_path)
    runtime.events(str(tmp_path / "lane.meta"), "marker")
    assert capsys.readouterr().out.strip() == "done"
    runtime.events(str(tmp_path / "lane.meta"), "pending")
    assert capsys.readouterr().out.strip() == "0 4"


def test_marker_from_a_notification_turn_counts_once_inputs_are_answered(tmp_path, capsys):
    finished_by_notification = [RESULT, assistant("LANE-DONE task finished"), NOTIFIED]
    assert guarded(tmp_path, capsys, finished_by_notification) == "done"
    stale = [RESULT, assistant("LANE-DONE before the follow-up"), NOTIFIED, assistant("ack"), RESULT]
    assert guarded(tmp_path, capsys, stale, results_needed=2) == ""
    answered = stale + [assistant("LANE-DONE follow-up done"), PEER]
    assert guarded(tmp_path, capsys, answered, results_needed=2) == "done"


# Events Claude writes between turns (shapes from real 2.1.287 lane logs); none starts a turn.
BETWEEN_TURNS = [
    dict(type="command_lifecycle", command_uuid="c1", state="completed", uuid="u1", session_id="s"),
    dict(type="system", subtype="commands_changed", commands=[dict(name="dinostack")], uuid="u2", session_id="s"),
    dict(type="system", subtype="task_progress", task_id="t1", description="Running", uuid="u3", session_id="s"),
    dict(type="system", subtype="background_tasks_changed", tasks=[], uuid="u4", session_id="s"),
]
INIT = dict(type="system", subtype="init", parent_tool_use_id=None, session_id="s")


@pytest.mark.parametrize("trailing", BETWEEN_TURNS, ids=lambda e: e.get("subtype") or e["type"])
def test_events_between_turns_do_not_defeat_the_grace_period(tmp_path, capsys, monkeypatch, trailing):
    monkeypatch.setenv("DS_LANE_MIDTURN_GRACE_S", "1")
    log = [assistant("LANE-DONE merged"), RESULT, trailing]
    assert guarded(tmp_path, capsys, log, results_needed=2) == ""
    backdate(tmp_path)
    runtime.events(str(tmp_path / "lane.meta"), "marker")
    assert capsys.readouterr().out.strip() == "done"
    runtime.events(str(tmp_path / "lane.meta"), "pending")
    assert capsys.readouterr().out.strip() == "0 3"


def test_grace_clock_runs_from_the_turn_not_later_log_writes(tmp_path, capsys):
    # Background tasks keep writing progress events, so the log's mtime is always fresh.
    ended = dict(assistant("LANE-DONE merged"), timestamp="2026-01-01T00:00:00.000Z")
    log = [ended, RESULT] + BETWEEN_TURNS * 3
    assert guarded(tmp_path, capsys, log, results_needed=2) == "done"
    recent = dict(ended, timestamp=datetime.now(timezone.utc).isoformat())
    assert guarded(tmp_path, capsys, [recent, RESULT] + BETWEEN_TURNS, results_needed=2) == ""


@pytest.mark.parametrize(
    "started", [[INIT], [dict(type="system", subtype="task_notification"), INIT], [assistant("working")]]
)
def test_a_started_turn_defeats_the_grace_period(tmp_path, capsys, started):
    ended = dict(assistant("LANE-DONE merged"), timestamp="2026-01-01T00:00:00.000Z")
    log = [ended, RESULT] + BETWEEN_TURNS + started
    assert guarded(tmp_path, capsys, log, results_needed=2) == ""
    assert guarded(tmp_path, capsys, log, mode="pending", results_needed=2).split()[0] == "1"
