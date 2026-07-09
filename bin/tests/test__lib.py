#!/usr/bin/env python3
"""
Tests for bin/_lib.py shared helpers: atomic_write and acquire_exclusive_lock.

Test groups:
  1. test_atomic_write_creates_file - basic write + replace.
  2. test_atomic_write_mode_bits    - chmod 0o600 applied to destination.
  3. test_atomic_write_mode_none    - mode=None -> new file gets 0o644 (no 0o600 force).
  4. test_atomic_write_no_tmp_on_success - no leftover temp files after success.
  5. test_atomic_write_cleans_tmp_on_failure - temp unlinked when replace impossible.
  6. test_atomic_write_mode_none_preserves_existing_perms - rewrites keep dest perms.
  7. test_atomic_write_temp_name_unpredictable - pre-planted <dest>.tmp symlink not followed.
  8. test_acquire_lock_acquires_and_releases - context manager acquires, code runs, releases.
  9. test_acquire_lock_blocks_second - second acquirer times out while first holds lock.
 10. test_acquire_lock_releases_after_with - after 'with' block, second acquirer succeeds.

Run with: python3 bin/tests/test__lib.py
       or: python3 -m pytest bin/tests/test__lib.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Load bin/_lib as a module (no .py extension needed for the CLIs, but _lib
# does have .py - load by path to match how the CLIs do it at runtime).
# ---------------------------------------------------------------------------
_LIB_PATH = Path(__file__).parent.parent / "_lib.py"
_loader = importlib.machinery.SourceFileLoader("_lib", str(_LIB_PATH))
_spec = importlib.util.spec_from_loader("_lib", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for _lib from {_LIB_PATH}")
_lib = importlib.util.module_from_spec(_spec)
_loader.exec_module(_lib)

atomic_write = _lib.atomic_write
acquire_exclusive_lock = _lib.acquire_exclusive_lock


# ---------------------------------------------------------------------------
# atomic_write tests
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.dest = Path(self.tmp_dir) / "output.txt"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_atomic_write_creates_file(self):
        atomic_write(self.dest, "hello world\n")
        self.assertTrue(self.dest.is_file())
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "hello world\n")

    def test_atomic_write_mode_bits(self):
        atomic_write(self.dest, "secret\n", mode=0o600)
        file_mode = stat.S_IMODE(os.stat(self.dest).st_mode)
        self.assertEqual(file_mode, 0o600)

    def test_atomic_write_mode_none_skips_chmod(self):
        # mode=None on a NEW file must not force 0o600 (mkstemp's default); it
        # falls back to 0o644 to match the prior write_text umask behavior so
        # callers like agentic-migrate don't regress to owner-only files.
        atomic_write(self.dest, "config\n", mode=None)
        self.assertTrue(self.dest.is_file())
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "config\n")
        file_mode = stat.S_IMODE(os.stat(self.dest).st_mode)
        self.assertEqual(file_mode, 0o644)
        self.assertNotEqual(file_mode, 0o600)

    def test_atomic_write_no_tmp_on_success(self):
        atomic_write(self.dest, "data\n")
        leftovers = list(Path(self.tmp_dir).glob(self.dest.name + "*.tmp"))
        self.assertEqual(leftovers, [], "no temp files should remain after success")
        self.assertFalse((self.dest.parent / (self.dest.name + ".tmp")).exists())

    def test_atomic_write_cleans_tmp_on_failure(self):
        # Make dest a directory so os.replace fails; the temp file is cleaned up.
        self.dest.mkdir()
        with self.assertRaises(Exception):
            atomic_write(self.dest, "data\n")
        leftovers = list(Path(self.tmp_dir).glob(self.dest.name + "*.tmp"))
        self.assertEqual(leftovers, [], "temp file should be removed on failure")

    def test_atomic_write_overwrites_existing(self):
        self.dest.write_text("old content\n", encoding="utf-8")
        atomic_write(self.dest, "new content\n")
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "new content\n")

    def test_atomic_write_mode_none_preserves_existing_perms(self):
        # mode=None must keep the destination's current mode across a rewrite
        # (agentic-migrate relies on this for shared config files).
        self.dest.write_text("old\n", encoding="utf-8")
        os.chmod(self.dest, 0o640)
        atomic_write(self.dest, "new\n", mode=None)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.dest).st_mode), 0o640)

    def test_atomic_write_temp_name_unpredictable(self):
        # A pre-planted "<dest>.tmp" symlink must NOT be followed (same-user
        # TOCTOU): the temp name is randomized, so the victim is never opened
        # and the destination is written via os.replace.
        victim = Path(self.tmp_dir) / "victim.txt"
        victim.write_text("do not touch\n", encoding="utf-8")
        planted = self.dest.parent / (self.dest.name + ".tmp")
        os.symlink(victim, planted)
        atomic_write(self.dest, "payload\n")
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "payload\n")
        self.assertEqual(
            victim.read_text(encoding="utf-8"), "do not touch\n",
            "predictable .tmp symlink must not be written through",
        )


# ---------------------------------------------------------------------------
# acquire_exclusive_lock tests
# ---------------------------------------------------------------------------

class TestAcquireExclusiveLock(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.lock_path = Path(self.tmp_dir) / ".test.lock"
        self.lock_path.touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_acquire_lock_acquires_and_releases(self):
        """Context manager acquires the lock, body runs, lock released on exit."""
        ran = []
        with acquire_exclusive_lock(self.lock_path, timeout=5.0):
            ran.append(True)
        self.assertEqual(ran, [True])

    def test_acquire_lock_blocks_second_acquirer(self):
        """Second acquirer times out while first holds the lock."""
        result = {}

        def hold_lock():
            with acquire_exclusive_lock(self.lock_path, timeout=10.0):
                # Signal holder is in; sleep long enough for second acquirer to time out.
                result["held"] = True
                time.sleep(1.5)

        holder = threading.Thread(target=hold_lock)
        holder.start()

        # Wait until holder has the lock.
        deadline = time.monotonic() + 2.0
        while not result.get("held") and time.monotonic() < deadline:
            time.sleep(0.05)

        # Second acquirer with very short timeout should raise RuntimeError.
        with self.assertRaises(RuntimeError) as ctx:
            with acquire_exclusive_lock(self.lock_path, timeout=0.2):
                pass

        self.assertIn("timeout", str(ctx.exception).lower())
        holder.join(timeout=5.0)

    def test_acquire_lock_releases_so_second_can_acquire(self):
        """After 'with' block exits, a second acquirer succeeds."""
        with acquire_exclusive_lock(self.lock_path, timeout=5.0):
            pass

        # Lock should now be free; second acquisition must succeed.
        second_ran = []
        with acquire_exclusive_lock(self.lock_path, timeout=5.0):
            second_ran.append(True)
        self.assertEqual(second_ran, [True])

    def test_acquire_lock_releases_on_exception_in_body(self):
        """Lock is released even when the body raises an exception."""
        try:
            with acquire_exclusive_lock(self.lock_path, timeout=5.0):
                raise ValueError("body error")
        except ValueError:
            pass

        # Lock must be free now.
        acquired = []
        with acquire_exclusive_lock(self.lock_path, timeout=1.0):
            acquired.append(True)
        self.assertEqual(acquired, [True])


# ---------------------------------------------------------------------------
# Standalone runner (matches existing test pattern in bin/tests/)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
