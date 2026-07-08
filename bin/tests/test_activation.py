#!/usr/bin/env python3
"""
Tests for bin/_activation.py activation-state primitives.

Test groups:
  resolve_state (mirrors hooks/lib/activation.* precedence)
    - dormant when no marker; auto-detect when .agentic/ exists; tombstone
      overrides auto-detect; active/active.session override tombstone;
      indeterminate cwd -> fail-ACTIVE.
  activate / deactivate round-trip
    - activate writes marker + tier, clears tombstone, allowlists;
      deactivate writes tombstone, removes active markers, keeps data.
  allowlist
    - add/remove idempotent; flat .list mirrors the JSON.
  resident_bytes / clear_session_marker

Hermetic: every test uses a tempfile project and a fake HOME so the real
~/.agentic is never touched.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).parent.parent / "_activation.py"
_loader = importlib.machinery.SourceFileLoader("_activation", str(_MOD_PATH))
_spec = importlib.util.spec_from_loader("_activation", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for _activation from {_MOD_PATH}")
act = importlib.util.module_from_spec(_spec)
_loader.exec_module(act)


class _FakeHome(unittest.TestCase):
    """Base: redirect HOME and the module's cached ~/.agentic paths to a sandbox."""

    def setUp(self):
        self.project = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        # The module resolved ~/.agentic paths at import time; repoint them.
        self._old_paths = (act._HOME_AGENTIC, act._ALLOWLIST_JSON, act._ALLOWLIST_FLAT)
        act._HOME_AGENTIC = Path(self.home) / ".agentic"
        act._ALLOWLIST_JSON = act._HOME_AGENTIC / "activation.json"
        act._ALLOWLIST_FLAT = act._HOME_AGENTIC / "activation.list"

    def tearDown(self):
        act._HOME_AGENTIC, act._ALLOWLIST_JSON, act._ALLOWLIST_FLAT = self._old_paths
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        else:
            os.environ.pop("HOME", None)


class TestResolveState(_FakeHome):
    def test_dormant_no_marker(self):
        self.assertEqual(act.resolve_state(self.project)["reason"], "dormant")
        self.assertFalse(act.resolve_state(self.project)["active"])

    def test_auto_detect(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        s = act.resolve_state(self.project)
        self.assertTrue(s["active"])
        self.assertEqual(s["reason"], "auto-detect")

    def test_tombstone_overrides_auto_detect(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()
        s = act.resolve_state(self.project)
        self.assertFalse(s["active"])
        self.assertEqual(s["reason"], "tombstone")

    def test_active_overrides_tombstone(self):
        act.activate(self.project, tier="full")  # writes active + clears tombstone
        s = act.resolve_state(self.project)
        self.assertTrue(s["active"])
        self.assertEqual(s["reason"], "active-file")
        self.assertEqual(s["tier"], "full")

    def test_indeterminate_fails_active(self):
        self.assertTrue(act.resolve_state(None)["active"])
        self.assertEqual(act.resolve_state(None)["reason"], "error")


class TestActivateDeactivate(_FakeHome):
    def test_activate_writes_marker_and_allowlist(self):
        marker = act.activate(self.project, tier="medium")
        self.assertTrue(os.path.exists(marker))
        data = json.load(open(marker))
        self.assertEqual(data["tier"], "medium")
        self.assertEqual(data["by"], "ds")
        # Allowlist updated (JSON + flat mirror).
        self.assertTrue(act._in_allowlist(self.project))
        self.assertTrue(act._ALLOWLIST_FLAT.exists())

    def test_activate_clears_tombstone(self):
        act.deactivate(self.project)
        self.assertTrue(os.path.exists(os.path.join(self.project, ".agentic", "dormant")))
        act.activate(self.project)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".agentic", "dormant")))

    def test_session_marker(self):
        marker = act.activate(self.project, session=True, session_id="sess-1")
        self.assertTrue(str(marker).endswith("active.session"))
        self.assertEqual(json.load(open(marker))["session_id"], "sess-1")
        self.assertEqual(act.resolve_state(self.project)["reason"], "session-file")
        act.clear_session_marker(self.project)
        self.assertFalse(os.path.exists(marker))

    def test_deactivate_keeps_data(self):
        act.activate(self.project)
        # drop a data file that must survive deactivation
        data_file = os.path.join(self.project, ".agentic", "events.jsonl")
        with open(data_file, "w") as fh:
            fh.write("{}\n")
        act.deactivate(self.project)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".agentic", "active")))
        self.assertTrue(os.path.exists(data_file))  # data preserved

    def test_deactivate_forget_removes_allowlist(self):
        act.activate(self.project)
        self.assertTrue(act._in_allowlist(self.project))
        act.deactivate(self.project, remove_from_allowlist_flag=True)
        self.assertFalse(act._in_allowlist(self.project))


class TestAllowlist(_FakeHome):
    def test_add_idempotent(self):
        act.add_to_allowlist(self.project)
        act.add_to_allowlist(self.project)
        entries = act._read_allowlist()
        self.assertEqual(len([e for e in entries if os.path.realpath(e) == os.path.realpath(self.project)]), 1)

    def test_flat_mirror_matches_json(self):
        act.add_to_allowlist(self.project)
        flat = act._ALLOWLIST_FLAT.read_text().split()
        js = act._read_allowlist()
        self.assertEqual([os.path.realpath(x) for x in flat], [os.path.realpath(x) for x in js])

    def test_remove(self):
        act.add_to_allowlist(self.project)
        act.remove_from_allowlist(self.project)
        self.assertFalse(act._in_allowlist(self.project))


class TestResidentBytes(_FakeHome):
    def test_zero_when_absent(self):
        self.assertEqual(act.resident_bytes(self.project), 0)

    def test_counts_bytes(self):
        act.activate(self.project, tier="minimal")
        self.assertGreater(act.resident_bytes(self.project), 0)


# ---------------------------------------------------------------------------
# hooks/lib/activation.py guard tests (dormant tombstone + unsuppressable notice)
# ---------------------------------------------------------------------------
import importlib.machinery as _hl_machinery
import importlib.util as _hl_util
import io as _io

_HOOK_MOD_PATH = Path(__file__).parent.parent.parent / "hooks" / "lib" / "activation.py"
_hl_loader = _hl_machinery.SourceFileLoader("hook_activation", str(_HOOK_MOD_PATH))
_hl_spec = _hl_util.spec_from_loader("hook_activation", _hl_loader)
if _hl_spec is None:
    raise RuntimeError(f"Cannot build spec for hooks/lib/activation.py from {_HOOK_MOD_PATH}")
hook_act = _hl_util.module_from_spec(_hl_spec)
_hl_loader.exec_module(hook_act)


class TestHookActivationDormantNotice(_FakeHome):
    """is_active() emits an unsuppressable notice the first time it observes
    a dormant tombstone; the marker lives outside the project directory."""

    def _capture_stderr(self, func, *args, **kwargs):
        old = sys.stderr
        buf = _io.StringIO()
        sys.stderr = buf
        try:
            result = func(*args, **kwargs)
        finally:
            sys.stderr = old
        return result, buf.getvalue()

    def test_dormant_tombstone_emits_notice_once(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()

        active1, err1 = self._capture_stderr(hook_act.is_active, self.project)
        self.assertFalse(active1)
        self.assertIn("AGENTIC-ENGINEERING DORMANT", err1)
        self.assertIn(self.project, err1)
        self.assertIn("tombstone", err1)

        marker = hook_act._dormant_notice_path(self.project)
        self.assertTrue(os.path.exists(marker))

        active2, err2 = self._capture_stderr(hook_act.is_active, self.project)
        self.assertFalse(active2)
        self.assertEqual(err2, "")

    def test_dormant_notice_marker_outside_project(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()

        marker = hook_act._dormant_notice_path(self.project)
        home_prefix = os.path.realpath(self.home) + os.sep
        self.assertTrue(
            os.path.realpath(marker).startswith(home_prefix),
            f"marker {marker!r} must live under fake HOME, not project",
        )
        # Key is derived from realpath(cwd), so two paths resolving to the same
        # project share the same marker.
        self.assertEqual(
            hook_act._dormant_notice_path(self.project),
            hook_act._dormant_notice_path(os.path.realpath(self.project)),
        )

    def test_dormant_notice_still_prints_if_marker_creation_fails(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()

        real_emit = hook_act._emit_dormant_notice
        calls = []

        def broken_emit(cwd):
            # Print the warning but fail to create the marker.
            calls.append(cwd)
            print("AGENTIC-ENGINEERING DORMANT: warning", file=sys.stderr)
            raise OSError("marker creation simulated failure")

        hook_act._emit_dormant_notice = broken_emit
        try:
            active, err = self._capture_stderr(hook_act.is_active, self.project)
        finally:
            hook_act._emit_dormant_notice = real_emit

        self.assertFalse(active)
        self.assertIn("AGENTIC-ENGINEERING DORMANT", err)

    def test_active_overrides_tombstone_no_notice(self):
        act.activate(self.project, tier="full")
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()
        active, err = self._capture_stderr(hook_act.is_active, self.project)
        self.assertTrue(active)
        self.assertEqual(err, "")

    def test_auto_detect_active_no_notice(self):
        os.makedirs(os.path.join(self.project, ".agentic"))
        active, err = self._capture_stderr(hook_act.is_active, self.project)
        self.assertTrue(active)
        self.assertEqual(err, "")

    def test_indeterminate_cwd_fails_active_no_notice(self):
        active, err = self._capture_stderr(hook_act.is_active, None)
        self.assertTrue(active)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()


    def test_dormant_notice_does_not_spam_on_repeated_marker_failure(self):
        """If marker creation fails, the warning is emitted only once per process."""
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()

        real_emit = hook_act._emit_dormant_notice
        calls = []

        def broken_emit(cwd):
            calls.append(cwd)
            print("AGENTIC-ENGINEERING DORMANT: warning", file=sys.stderr)
            raise OSError("marker creation simulated failure")

        hook_act._emit_dormant_notice = broken_emit
        try:
            _, err1 = self._capture_stderr(hook_act.is_active, self.project)
            _, err2 = self._capture_stderr(hook_act.is_active, self.project)
        finally:
            hook_act._emit_dormant_notice = real_emit
            # Clear the process-level attempt cache so other tests are unaffected.
            hook_act._DORMANT_NOTICE_ATTEMPTED.discard(os.path.realpath(self.project))

        self.assertEqual(calls, [self.project])
        self.assertIn("AGENTIC-ENGINEERING DORMANT", err1)
        self.assertEqual(err2, "")
