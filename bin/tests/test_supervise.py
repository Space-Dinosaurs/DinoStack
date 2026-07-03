#!/usr/bin/env python3
"""
Tests for bin/_supervise.py worker-supervision primitives.

Test groups:
  status.json I/O
    1. test_write_status_creates_file             - first write lands the file.
    2. test_write_status_merges_fields            - later writes merge, not clobber.
    3. test_write_status_appends_transition       - state change appends a record.
    4. test_write_status_no_transition_same_state - unchanged state -> no record.
    5. test_write_status_atomic_no_tmp            - no .tmp left after write.
    6. test_read_status_missing                   - missing file -> None.
    7. test_read_status_corrupt                   - bad JSON -> None (no raise).

  progress detection
    8. test_check_progress_ok                     - fresh output -> "ok".
    9. test_check_progress_stalled                - stale heartbeat -> "stalled".
   10. test_check_progress_timeout_wins           - over budget -> "timed_out".

  process control (real subprocess fakes)
   11. test_supervise_normal_exit_passthrough     - clean exit -> returncode.
   12. test_supervise_stall_kill                  - sleep-forever -> exit 125.
   13. test_supervise_timeout                     - long run -> exit 124.
   14. test_kill_process_group_reaches_grandchild - killpg kills sh->sh tree.
   15. test_kill_process_group_already_dead       - dead pid -> silent no-op.

Run with: python3 -m pytest bin/tests/test_supervise.py -q
       or: python3 bin/tests/test_supervise.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load bin/_supervise by path (matches how the CLIs load their siblings).
# ---------------------------------------------------------------------------
_MOD_PATH = Path(__file__).parent.parent / "_supervise.py"
_loader = importlib.machinery.SourceFileLoader("_supervise", str(_MOD_PATH))
_spec = importlib.util.spec_from_loader("_supervise", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for _supervise from {_MOD_PATH}")
sup = importlib.util.module_from_spec(_spec)
_loader.exec_module(sup)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ---------------------------------------------------------------------------
# status.json I/O
# ---------------------------------------------------------------------------

class TestStatusIO(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_status_creates_file(self):
        sup.write_status(self.run_dir, run_id="r1", state="running", pid=123)
        data = sup.read_status(self.run_dir)
        self.assertIsNotNone(data)
        self.assertEqual(data["run_id"], "r1")
        self.assertEqual(data["state"], "running")
        self.assertEqual(data["pid"], 123)

    def test_write_status_merges_fields(self):
        sup.write_status(self.run_dir, run_id="r1", state="running")
        sup.write_status(self.run_dir, output_bytes=42)
        data = sup.read_status(self.run_dir)
        # first-write fields survive the second (merge, not overwrite)
        self.assertEqual(data["run_id"], "r1")
        self.assertEqual(data["output_bytes"], 42)

    def test_write_status_appends_transition(self):
        sup.write_status(self.run_dir, state="running")
        sup.write_status(self.run_dir, state="killed", reason="stalled")
        data = sup.read_status(self.run_dir)
        transitions = data["transitions"]
        # one initial (None->running) + one (running->killed)
        self.assertEqual(len(transitions), 2)
        last = transitions[-1]
        self.assertEqual(last["from"], "running")
        self.assertEqual(last["to"], "killed")
        self.assertEqual(last["reason"], "stalled")
        # reason must NOT leak into the top-level status dict
        self.assertNotIn("reason", data)

    def test_write_status_no_transition_same_state(self):
        sup.write_status(self.run_dir, state="running")
        sup.write_status(self.run_dir, state="running", output_bytes=10)
        data = sup.read_status(self.run_dir)
        self.assertEqual(len(data["transitions"]), 1)

    def test_write_status_atomic_no_tmp(self):
        sup.write_status(self.run_dir, state="running")
        tmp = self.run_dir / "status.json.tmp"
        self.assertFalse(tmp.exists())

    def test_read_status_missing(self):
        self.assertIsNone(sup.read_status(self.run_dir))

    def test_read_status_corrupt(self):
        (self.run_dir / "status.json").write_text("{not valid json", encoding="utf-8")
        self.assertIsNone(sup.read_status(self.run_dir))

    def test_read_status_empty(self):
        (self.run_dir / "status.json").write_text("", encoding="utf-8")
        self.assertIsNone(sup.read_status(self.run_dir))


# ---------------------------------------------------------------------------
# progress detection
# ---------------------------------------------------------------------------

class TestCheckProgress(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = Path(self.tmp) / "stdout"
        self.err = Path(self.tmp) / "stderr"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_progress_ok(self):
        self.out.write_text("fresh\n", encoding="utf-8")
        started = time.time()
        self.assertEqual(
            sup.check_progress([self.out, self.err], 120, 600, started), "ok"
        )

    def test_check_progress_stalled(self):
        # Output file exists but its mtime is old; started_at also old.
        self.out.write_text("stale\n", encoding="utf-8")
        old = time.time() - 100
        os.utime(self.out, (old, old))
        started = time.time() - 100
        self.assertEqual(
            sup.check_progress([self.out, self.err], stall_seconds=5,
                               timeout_seconds=600, started_at=started),
            "stalled",
        )

    def test_check_progress_timeout_wins(self):
        # Fresh output but total budget exceeded -> timed_out beats stall.
        self.out.write_text("fresh\n", encoding="utf-8")
        started = time.time() - 100
        self.assertEqual(
            sup.check_progress([self.out, self.err], stall_seconds=5,
                               timeout_seconds=10, started_at=started),
            "timed_out",
        )


# ---------------------------------------------------------------------------
# process control - real subprocesses, tiny poll intervals
# ---------------------------------------------------------------------------

class TestSupervise(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = Path(self.tmp)
        self.out = self.run_dir / "stdout"
        self.err = self.run_dir / "stderr"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spawn(self, script: str) -> subprocess.Popen:
        fout = self.out.open("wb")
        ferr = self.err.open("wb")
        self._fout, self._ferr = fout, ferr
        return subprocess.Popen(
            ["sh", "-c", script],
            stdout=fout,
            stderr=ferr,
            start_new_session=True,
        )

    def test_supervise_normal_exit_passthrough(self):
        proc = self._spawn("echo hi; exit 7")
        code = sup.supervise(
            proc, self.run_dir, self.out, self.err,
            stall_seconds=60, timeout_seconds=60, poll_interval=0.1,
        )
        self.assertEqual(code, 7)
        data = sup.read_status(self.run_dir)
        self.assertEqual(data["state"], "done")
        self.assertEqual(data["exit_code"], 7)

    def test_supervise_stall_kill(self):
        # Emits nothing, sleeps forever -> stall window elapses -> 125.
        proc = self._spawn("sleep 30")
        code = sup.supervise(
            proc, self.run_dir, self.out, self.err,
            stall_seconds=0.3, timeout_seconds=60, poll_interval=0.1,
        )
        self.assertEqual(code, sup.EXIT_STALL)
        self.assertFalse(_alive(proc.pid))
        data = sup.read_status(self.run_dir)
        self.assertEqual(data["exit_code"], sup.EXIT_STALL)

    def test_supervise_timeout(self):
        # Keeps emitting (never stalls) but exceeds the hard timeout -> 124.
        proc = self._spawn("while true; do echo tick; sleep 0.1; done")
        code = sup.supervise(
            proc, self.run_dir, self.out, self.err,
            stall_seconds=60, timeout_seconds=0.4, poll_interval=0.1,
        )
        self.assertEqual(code, sup.EXIT_TIMEOUT)
        self.assertFalse(_alive(proc.pid))
        data = sup.read_status(self.run_dir)
        self.assertEqual(data["exit_code"], sup.EXIT_TIMEOUT)


# ---------------------------------------------------------------------------
# kill_process_group
# ---------------------------------------------------------------------------

class TestKillProcessGroup(unittest.TestCase):

    def test_kill_process_group_reaches_grandchild(self):
        # Parent sh spawns child sh that sleeps; killpg must reap the whole tree.
        tmp = tempfile.mkdtemp()
        marker = Path(tmp) / "child.pid"
        try:
            # Outer sh execs a child sh (sleep) in the same new session/group,
            # records the child's pid, then waits on it.
            script = f"sh -c 'echo $$ > {marker}; sleep 30' & echo started; wait"
            proc = subprocess.Popen(
                ["sh", "-c", script],
                start_new_session=True,
            )
            # Wait for the grandchild pid to be recorded.
            deadline = time.time() + 5
            while not marker.exists() and time.time() < deadline:
                time.sleep(0.05)
            child_pid = int(marker.read_text().strip())
            self.assertTrue(_alive(child_pid))

            sup.kill_process_group(proc.pid, grace_seconds=2)

            # Grandchild must be gone after the group kill.
            deadline = time.time() + 3
            while _alive(child_pid) and time.time() < deadline:
                time.sleep(0.05)
            self.assertFalse(_alive(child_pid))
            proc.wait(timeout=5)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_kill_process_group_already_dead(self):
        # Spawn, kill, reap, then call kill_process_group -> must not raise.
        proc = subprocess.Popen(["sh", "-c", "exit 0"], start_new_session=True)
        proc.wait(timeout=5)
        try:
            sup.kill_process_group(proc.pid)  # already dead -> silent
        except Exception as exc:  # noqa: BLE001
            self.fail(f"kill_process_group raised on dead pid: {exc!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# unkillable state
# ---------------------------------------------------------------------------

class TestSuperviseUnkillable(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = Path(self.tmp)
        self.out = self.run_dir / "stdout"
        self.err = self.run_dir / "stderr"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_supervise_reports_unkillable_when_wait_times_out(self):
        """If proc.wait() times out after kill, status records unkillable."""
        class _UnkillableProc:
            pid = 123456
            _poll = None

            def poll(self):
                return self._poll

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(cmd=["sh"], timeout=timeout)

        proc = _UnkillableProc()
        # kill_process_group on a non-existent pid is a silent no-op, so the
        # wait timeout path is exercised.
        code = sup.supervise(
            proc, self.run_dir, self.out, self.err,
            stall_seconds=0.1, timeout_seconds=60, poll_interval=0.05,
        )
        self.assertEqual(code, sup.EXIT_STALL)
        data = sup.read_status(self.run_dir)
        self.assertEqual(data["state"], "unkillable")
        transitions = data.get("transitions") or []
        self.assertTrue(transitions, "expected at least one transition")
        self.assertIn("process did not exit", transitions[-1]["reason"])
