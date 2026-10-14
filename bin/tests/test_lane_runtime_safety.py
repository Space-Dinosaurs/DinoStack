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
