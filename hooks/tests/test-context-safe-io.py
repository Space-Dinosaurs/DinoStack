#!/usr/bin/env python3
"""Adversarial and process-barrier tests for hooks/lib/context-safe-io.py."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import multiprocessing as mp
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import time
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "hooks" / "lib" / "context-safe-io.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("context_safe_io", HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safeio = load_helper()


def holder_process(project: str, conn) -> None:
    command = [
        str(HELPER_PATH),
        "--project-root",
        project,
        "lock",
        "acquire",
        "--owner-pid",
        str(os.getpid()),
        "--owner-kind",
        "barrier-holder",
    ]
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    conn.send((result.returncode, result.stdout))
    conn.recv()


def crash_holder(project: str, conn) -> None:
    result = safeio.acquire_lock(project, "crash-holder")
    conn.send(result)
    conn.close()
    os._exit(23)


def contention_worker(project: str, conn) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = safeio.acquire_lock(project, "contention-worker")
        if result.get("status") == "acquired":
            token = result["token"]
            time.sleep(0.03)
            released = safeio.release_lock(project, token)
            conn.send(released.get("released") is True)
            conn.close()
            return
        time.sleep(0.01)
    conn.send(False)
    conn.close()


class ContextSafeIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="context-safe-io-"))
        self.project = self.base / "project"
        self.project.mkdir(mode=0o700)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    @property
    def lock_dir(self) -> pathlib.Path:
        return self.project / ".agentic" / "wrap" / "lock"

    def acquire(self, kind: str = "test"):
        result = safeio.acquire_lock(str(self.project), kind)
        self.assertEqual(result["status"], "acquired", result)
        return result

    def test_owner_is_sorted_schema_and_tokenized(self) -> None:
        acquired = self.acquire("schema-test")
        raw = (self.lock_dir / "owner").read_bytes()
        owner = json.loads(raw)
        self.assertEqual(raw, safeio._json_bytes(owner))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(owner["magic"], safeio.LOCK_MAGIC)
        self.assertEqual(owner["schema_version"], 1)
        self.assertEqual(owner["owner_pid"], os.getpid())
        self.assertEqual(owner["owner_kind"], "schema-test")
        self.assertEqual(len(acquired["token"]), 64)
        st = self.lock_dir.stat()
        self.assertEqual((owner["lock_dev"], owner["lock_ino"]), (st.st_dev, st.st_ino))
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_cli_rejects_non_parent_owner_pid(self) -> None:
        result = subprocess.run(
            [
                str(HELPER_PATH), "--project-root", str(self.project), "lock", "acquire",
                "--owner-pid", "1", "--owner-kind", "invalid-parent",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "owner-pid-mismatch")
        self.assertFalse(self.lock_dir.exists())

    def test_public_api_and_cli_surface_are_frozen(self) -> None:
        public_functions = {
            name
            for name, value in vars(safeio).items()
            if inspect.isfunction(value) and not name.startswith("_") and name != "main"
        }
        self.assertEqual(
            public_functions,
            {
                "acquire_lock",
                "inspect_lock",
                "release_lock",
                "read_context",
                "commit_context",
                "transact_context",
            },
        )
        result = subprocess.run(
            [str(HELPER_PATH), "--project-root", str(self.project), "lock", "reclaim"],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertFalse(self.lock_dir.exists())

    def test_cli_rejects_malformed_and_noncanonical_json_without_mutation(self) -> None:
        acquired = self.acquire("malformed-input")
        for payload in ("not-json", "[]", "{}"):
            result = subprocess.run(
                [
                    str(HELPER_PATH),
                    "--project-root",
                    str(self.project),
                    "context",
                    "commit",
                    "--token",
                    acquired["token"],
                ],
                input=payload,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1, (payload, result.stdout, result.stderr))
            self.assertIn(json.loads(result.stdout)["error"], {"invalid-input", "invalid-body"})
        self.assertFalse((self.project / ".agentic" / "context.md").exists())

        with self.assertRaisesRegex(safeio.SafeIOError, "canonical JSON"):
            safeio.transact_context(
                str(self.project),
                {
                    "body": "replacement",
                    "spillover_record": {"schema_version": 1, "value": float("nan")},
                },
            )
        self.assertFalse((self.project / ".agentic" / "wrap" / safeio.SPILL_NAME).exists())
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_context_commit_fsyncs_temp_before_publish_and_parent_after(self) -> None:
        acquired = self.acquire("durability-order")
        agentic = self.project / ".agentic"
        guessed_temp = agentic / ".context.md.tmp.attacker-guessed"
        guessed_temp.write_text("external", encoding="utf-8")
        agentic_identity = (agentic.stat().st_dev, agentic.stat().st_ino)
        events = []
        real_fsync = safeio.os.fsync
        real_rename = safeio.os.rename

        def recording_fsync(fd):
            st = os.fstat(fd)
            events.append(("fsync", stat.S_IFMT(st.st_mode), (st.st_dev, st.st_ino)))
            return real_fsync(fd)

        def recording_rename(*args, **kwargs):
            events.append(("rename", args[0], args[1]))
            return real_rename(*args, **kwargs)

        safeio.os.fsync = recording_fsync
        safeio.os.rename = recording_rename
        try:
            result = safeio.commit_context(str(self.project), acquired["token"], "durable\n")
        finally:
            safeio.os.fsync = real_fsync
            safeio.os.rename = real_rename

        self.assertEqual(result["status"], "written")
        rename_index = next(index for index, event in enumerate(events) if event[0] == "rename")
        self.assertTrue(
            any(event[0] == "fsync" and event[1] == stat.S_IFREG for event in events[:rename_index]),
            events,
        )
        self.assertTrue(
            any(event[0] == "fsync" and event[2] == agentic_identity for event in events[rename_index + 1 :]),
            events,
        )
        self.assertEqual(guessed_temp.read_text(encoding="utf-8"), "external")
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_live_parent_survives_helper_exit_then_dead_owner_reclaims(self) -> None:
        parent_conn, child_conn = mp.Pipe()
        holder = mp.Process(target=holder_process, args=(str(self.project), child_conn))
        holder.start()
        rc, stdout = parent_conn.recv()
        self.assertEqual(rc, 0, stdout)
        first = json.loads(stdout)
        self.assertEqual(first["status"], "acquired")
        inspected = safeio.inspect_lock(str(self.project))
        self.assertEqual(inspected["owner_pid"], holder.pid)
        self.assertEqual(inspected["owner_state"], "alive")
        self.assertEqual(safeio.acquire_lock(str(self.project), "contender")["status"], "held")
        holder.terminate()
        holder.join(timeout=5)
        self.assertFalse(holder.is_alive())
        replacement = self.acquire("reclaimer")
        self.assertNotEqual(first["token"], replacement["token"])
        self.assertTrue(safeio.release_lock(str(self.project), replacement["token"])["released"])

    def test_crashed_owner_is_reclaimed(self) -> None:
        parent_conn, child_conn = mp.Pipe()
        holder = mp.Process(target=crash_holder, args=(str(self.project), child_conn))
        holder.start()
        first = parent_conn.recv()
        holder.join(timeout=5)
        self.assertEqual(holder.exitcode, 23)
        replacement = self.acquire("after-crash")
        self.assertNotEqual(first["token"], replacement["token"])
        self.assertTrue(safeio.release_lock(str(self.project), replacement["token"])["released"])

    def test_wrong_token_never_releases(self) -> None:
        acquired = self.acquire()
        with self.assertRaisesRegex(safeio.SafeIOError, "token"):
            safeio.release_lock(str(self.project), "0" * 64)
        self.assertTrue(self.lock_dir.is_dir())
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_replacement_inode_is_refused(self) -> None:
        acquired = self.acquire()
        saved = self.lock_dir.with_name("saved-lock")
        self.lock_dir.rename(saved)
        self.lock_dir.mkdir(mode=0o700)
        shutil.copyfile(saved / "owner", self.lock_dir / "owner")
        before = (saved / "owner").read_bytes()
        with self.assertRaisesRegex(safeio.SafeIOError, "inode"):
            safeio.release_lock(str(self.project), acquired["token"])
        self.assertEqual((saved / "owner").read_bytes(), before)
        self.assertTrue(self.lock_dir.is_dir())

    def test_symlink_agentic_parent_is_rejected_without_touching_target(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_text("unchanged", encoding="utf-8")
        (self.project / ".agentic").symlink_to(outside, target_is_directory=True)
        self.assertEqual(safeio.inspect_lock(str(self.project))["status"], "invalid")
        with self.assertRaises(safeio.SafeIOError):
            safeio.acquire_lock(str(self.project), "symlink-parent")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((outside / "wrap").exists())

    def test_symlink_project_and_wrap_parents_are_rejected(self) -> None:
        outside_project = self.base / "outside-project"
        outside_project.mkdir()
        linked_project = self.base / "linked-project"
        linked_project.symlink_to(outside_project, target_is_directory=True)
        with self.assertRaises(safeio.SafeIOError):
            safeio.acquire_lock(str(linked_project), "symlink-project")
        self.assertFalse((outside_project / ".agentic").exists())

        outside_wrap = self.base / "outside-wrap"
        outside_wrap.mkdir()
        agentic = self.project / ".agentic"
        agentic.mkdir()
        (agentic / "wrap").symlink_to(outside_wrap, target_is_directory=True)
        with self.assertRaises(safeio.SafeIOError):
            safeio.acquire_lock(str(self.project), "symlink-wrap")
        self.assertEqual(list(outside_wrap.iterdir()), [])

    def test_symlink_lock_and_owner_are_retained(self) -> None:
        wrap = self.project / ".agentic" / "wrap"
        wrap.mkdir(parents=True)
        outside = self.base / "outside-lock"
        outside.mkdir()
        (wrap / "lock").symlink_to(outside, target_is_directory=True)
        result = safeio.acquire_lock(str(self.project), "symlink-lock")
        self.assertEqual(result["status"], "invalid")
        self.assertTrue((wrap / "lock").is_symlink())

        (wrap / "lock").unlink()
        (wrap / "lock").mkdir()
        target = self.base / "owner-target"
        target.write_text("external", encoding="utf-8")
        (wrap / "lock" / "owner").symlink_to(target)
        result = safeio.acquire_lock(str(self.project), "symlink-owner")
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(target.read_text(encoding="utf-8"), "external")

        (wrap / "lock" / "owner").unlink()
        os.mkfifo(wrap / "lock" / "owner")
        result = safeio.acquire_lock(str(self.project), "fifo-owner")
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(stat.S_ISFIFO(os.lstat(wrap / "lock" / "owner").st_mode))

    def test_special_lock_and_context_targets_are_refused(self) -> None:
        wrap = self.project / ".agentic" / "wrap"
        wrap.mkdir(parents=True)
        os.mkfifo(wrap / "lock")
        self.assertEqual(safeio.acquire_lock(str(self.project), "fifo-lock")["status"], "invalid")
        self.assertTrue(stat.S_ISFIFO(os.lstat(wrap / "lock").st_mode))
        (wrap / "lock").unlink()

        acquired = self.acquire()
        context = self.project / ".agentic" / "context.md"
        os.mkfifo(context)
        with self.assertRaises(safeio.SafeIOError):
            safeio.commit_context(str(self.project), acquired["token"], "body")
        self.assertTrue(stat.S_ISFIFO(os.lstat(context).st_mode))
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_context_symlink_and_hardlink_are_refused(self) -> None:
        acquired = self.acquire()
        context = self.project / ".agentic" / "context.md"
        outside = self.base / "outside-context"
        outside.write_text("external", encoding="utf-8")
        context.symlink_to(outside)
        with self.assertRaises(safeio.SafeIOError):
            safeio.commit_context(str(self.project), acquired["token"], "new")
        self.assertEqual(outside.read_text(encoding="utf-8"), "external")
        context.unlink()
        context.write_text("old", encoding="utf-8")
        os.link(context, self.base / "context-hardlink")
        with self.assertRaises(safeio.SafeIOError):
            safeio.commit_context(str(self.project), acquired["token"], "new")
        self.assertEqual(context.read_text(encoding="utf-8"), "old")
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_coexistence_preserves_wrap_base_and_one_activity_block(self) -> None:
        context = self.project / ".agentic" / "context.md"
        context.parent.mkdir()
        base = "# Session Context\n*Written by /wrap on 2026-07-14.*\n\n## Recent Focus\n- preserved"
        context.write_text(base + safeio.ACTIVITY_SENTINEL + "old activity\n", encoding="utf-8")
        result = safeio.transact_context(
            str(self.project),
            {
                "mode": "coexist",
                "body": "fallback\n",
                "activity_block": "fresh activity\n",
                "spillover_record": {"schema_version": 1},
            },
        )
        self.assertEqual(result["status"], "written")
        expected = base + safeio.ACTIVITY_SENTINEL + "fresh activity\n"
        self.assertEqual(context.read_text(encoding="utf-8"), expected)
        self.assertEqual(context.read_text(encoding="utf-8").count(safeio.ACTIVITY_SENTINEL), 1)

    def test_contention_spills_one_exact_sorted_record_without_reading_context(self) -> None:
        acquired = self.acquire("live-wrap")
        context = self.project / ".agentic" / "context.md"
        context.write_text("do-not-read-or-change", encoding="utf-8")
        record = {"z": 1, "schema_version": 1, "session_id": "s", "a": ["x"]}
        result = safeio.transact_context(
            str(self.project),
            {"mode": "replace", "body": "replacement", "spillover_record": record},
        )
        self.assertEqual(result["status"], "spilled")
        self.assertEqual(context.read_text(encoding="utf-8"), "do-not-read-or-change")
        spill = self.project / ".agentic" / "wrap" / safeio.SPILL_NAME
        self.assertEqual(spill.read_bytes(), safeio._json_bytes(record))
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_spill_symlink_and_fifo_do_not_touch_external_target(self) -> None:
        acquired = self.acquire("live-wrap")
        spill = self.project / ".agentic" / "wrap" / safeio.SPILL_NAME
        outside = self.base / "outside-spill"
        outside.write_text("external", encoding="utf-8")
        spill.symlink_to(outside)
        with self.assertRaises(safeio.SafeIOError):
            safeio.transact_context(
                str(self.project),
                {"body": "x", "spillover_record": {"schema_version": 1}},
            )
        self.assertEqual(outside.read_text(encoding="utf-8"), "external")
        spill.unlink()
        os.mkfifo(spill)
        with self.assertRaises(safeio.SafeIOError):
            safeio.transact_context(
                str(self.project),
                {"body": "x", "spillover_record": {"schema_version": 1}},
            )
        self.assertTrue(stat.S_ISFIFO(os.lstat(spill).st_mode))
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

    def test_age_never_reclaims_live_or_malformed_owner(self) -> None:
        acquired = self.acquire("long-running")
        owner_path = self.lock_dir / "owner"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["acquired_at"] = "2000-01-01T00:00:00Z"
        owner_path.write_bytes(safeio._json_bytes(owner))
        self.assertEqual(safeio.acquire_lock(str(self.project), "contender")["status"], "held")
        self.assertTrue(safeio.release_lock(str(self.project), acquired["token"])["released"])

        self.lock_dir.mkdir()
        (self.lock_dir / "owner").write_text("123\nold\n", encoding="utf-8")
        self.assertEqual(safeio.acquire_lock(str(self.project), "contender")["status"], "invalid")
        self.assertTrue(self.lock_dir.exists())

    def test_contention_workers_serialize_and_release(self) -> None:
        processes = []
        parents = []
        for _ in range(6):
            parent, child = mp.Pipe()
            process = mp.Process(target=contention_worker, args=(str(self.project), child))
            process.start()
            processes.append(process)
            parents.append(parent)
        results = [parent.recv() for parent in parents]
        for process in processes:
            process.join(timeout=10)
        self.assertEqual(results, [True] * 6)
        self.assertEqual(safeio.inspect_lock(str(self.project))["status"], "absent")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--barriers", action="store_true")
    parser.add_argument("--adversarial", action="store_true")
    _, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__, *remaining], verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
