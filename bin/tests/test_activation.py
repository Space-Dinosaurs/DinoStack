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

    def test_dormant_notice_does_not_spam_on_repeated_marker_failure(self):
        """If marker creation fails, the warning is emitted only once per process."""
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()
        # Make ~/.agentic a regular file so every dormant-notice marker write
        # fails inside the real _emit_dormant_notice; the process-level
        # _DORMANT_NOTICE_ATTEMPTED cache must still suppress repeat warnings.
        open(os.path.join(self.home, ".agentic"), "w").close()

        try:
            active1, err1 = self._capture_stderr(hook_act.is_active, self.project)
            active2, err2 = self._capture_stderr(hook_act.is_active, self.project)
        finally:
            # Clear the process-level attempt cache so other tests are unaffected.
            hook_act._DORMANT_NOTICE_ATTEMPTED.discard(os.path.realpath(self.project))

        self.assertFalse(active1)
        self.assertFalse(active2)
        self.assertIn("AGENTIC-ENGINEERING DORMANT", err1)
        self.assertEqual(err2, "")

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


class TestHookActivationAncestorWalk(_FakeHome):
    """is_active() must walk from cwd up to the outermost git root so subagents
    inside <repo>/.agentic/worktrees/<branch>/ inherit the project root's
    activation instead of silently going dormant (closes the five-hook bypass)."""

    def _capture_stderr(self, func, *args, **kwargs):
        old = sys.stderr
        buf = _io.StringIO()
        sys.stderr = buf
        try:
            result = func(*args, **kwargs)
        finally:
            sys.stderr = old
        return result, buf.getvalue()

    def _make_repo(self):
        # Main-checkout .git directory (outermost .git-bearing ancestor).
        os.makedirs(os.path.join(self.project, ".git"))

    def _make_worktree(self, name="feat-x"):
        wt = os.path.join(self.project, ".agentic", "worktrees", name)
        os.makedirs(wt)
        # A worktree carries a .git *file* (gitdir pointer), not a directory.
        with open(os.path.join(wt, ".git"), "w") as fh:
            fh.write("gitdir: /placeholder\n")
        sub = os.path.join(wt, "src", "pkg")
        os.makedirs(sub)
        return sub

    def test_worktree_inherits_active_marker(self):
        self._make_repo()
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "active"), "w").close()
        cwd = self._make_worktree()
        self.assertTrue(hook_act.is_active(cwd))

    def test_worktree_inherits_dormant_tombstone_with_notice(self):
        self._make_repo()
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "dormant"), "w").close()
        cwd = self._make_worktree()
        active, err = self._capture_stderr(hook_act.is_active, cwd)
        self.assertFalse(active)
        self.assertIn("AGENTIC-ENGINEERING DORMANT", err)
        # Notice keyed on the project root, not the worktree subdir.
        self.assertIn(self.project, err)

    def test_deep_subdir_walks_to_repo_root(self):
        self._make_repo()
        os.makedirs(os.path.join(self.project, ".agentic"))
        open(os.path.join(self.project, ".agentic", "active"), "w").close()
        deep = os.path.join(self.project, "src", "a", "b", "c")
        os.makedirs(deep)
        self.assertTrue(hook_act.is_active(deep))

    def test_walk_bounded_at_git_root_ignores_home_agentic(self):
        # A user-level ~/.agentic dir exists (allowlist home). A naive fs-root
        # walk would auto-detect ACTIVE from isdir(~/.agentic); the git-root
        # bound must prevent escaping above the project.
        os.makedirs(os.path.join(self.home, ".agentic"))
        self._make_repo()  # project has .git but NO .agentic marker
        cwd = os.path.join(self.project, "src")
        os.makedirs(cwd)
        self.assertFalse(hook_act.is_active(cwd))

    def test_worktree_inherits_allowlist(self):
        self._make_repo()
        # No marker at the project; activation comes solely from the allowlist,
        # which records the project ROOT (not the worktree subdir).
        os.makedirs(os.path.join(self.home, ".agentic"))
        with open(os.path.join(self.home, ".agentic", "activation.list"), "w") as fh:
            fh.write(self.project + "\n")
        cwd = self._make_worktree()
        self.assertTrue(hook_act.is_active(cwd))

    def test_no_git_preserves_exact_cwd_behavior(self):
        # No git checkout anywhere -> legacy exact-cwd: dormant with no marker,
        # and we must not auto-detect from a ~/.agentic dir above cwd.
        os.makedirs(os.path.join(self.home, ".agentic"))
        self.assertFalse(hook_act.is_active(self.project))



# ---------------------------------------------------------------------------
# Cross-implementation parity: the ancestor walk + worktree-zone hardening must
# behave identically in hooks/lib/activation.py (in-process reference),
# bin/_activation.py resolve_state (in-process), hooks/lib/activation.sh
# (bash subprocess), and hooks/lib/activation.js (node subprocess).
# ---------------------------------------------------------------------------
import json as _json
import shutil as _shutil
import subprocess as _subprocess

_REPO_ROOT = Path(__file__).parent.parent.parent
_SH_GUARD = _REPO_ROOT / "hooks" / "lib" / "activation.sh"
_JS_GUARD = _REPO_ROOT / "hooks" / "lib" / "activation.js"
_HAVE_BASH = _shutil.which("bash") is not None
_HAVE_NODE = _shutil.which("node") is not None

def _sh_is_active(cwd: str, home: str) -> bool:
    """Invoke the shell guard as a subprocess; rc 0 -> active, rc 1 -> dormant."""
    script = 'source "%s"; ae_is_active "$1"' % _SH_GUARD
    result = _subprocess.run(
        ["bash", "-c", script, "_", cwd],
        capture_output=True, text=True,
        env={**os.environ, "HOME": home},
    )
    if result.returncode not in (0, 1):
        raise AssertionError(
            f"sh guard unexpected rc={result.returncode}: {result.stderr}")
    return result.returncode == 0

def _js_is_active(cwd: str, home: str) -> bool:
    """Invoke the Node guard as a subprocess; stdout 'true'/'false'."""
    script = (
        "const g = require(%s);"
        "process.stdout.write(String(g.isActive(process.argv[1])));"
    ) % _json.dumps(str(_JS_GUARD))
    result = _subprocess.run(
        ["node", "-e", script, cwd],
        capture_output=True, text=True,
        env={**os.environ, "HOME": home},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"js guard failed rc={result.returncode}: {result.stderr}")
    return result.stdout.strip() == "true"

class _WalkScenarios(_FakeHome):
    """Shared fixtures for the parity matrix: git repo + worktree builders."""

    def _fresh_sandboxes(self):
        """New project + HOME per scenario so markers never leak between cases."""
        self.project = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        os.environ["HOME"] = self.home
        act._HOME_AGENTIC = Path(self.home) / ".agentic"
        act._ALLOWLIST_JSON = act._HOME_AGENTIC / "activation.json"
        act._ALLOWLIST_FLAT = act._HOME_AGENTIC / "activation.list"
        hook_act._DORMANT_NOTICE_ATTEMPTED.clear()

    def _make_repo(self):
        # Main-checkout .git directory (outermost .git-bearing ancestor).
        os.makedirs(os.path.join(self.project, ".git"))

    def _make_worktree(self, name="feat-x"):
        wt = os.path.join(self.project, ".agentic", "worktrees", name)
        os.makedirs(wt)
        # A worktree carries a .git *file* (gitdir pointer), not a directory.
        with open(os.path.join(wt, ".git"), "w") as fh:
            fh.write("gitdir: /placeholder\n")
        sub = os.path.join(wt, "src", "pkg")
        os.makedirs(sub)
        return sub

    def _touch(self, *parts):
        path = os.path.join(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

# --- scenario builders: each takes the case, sets up, returns (cwd, expected) ---

def _sc_worktree_active(tc):
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "active")
    return tc._make_worktree(), True

def _sc_worktree_dormant(tc):
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "dormant")
    return tc._make_worktree(), False

def _sc_deep_subdir(tc):
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "active")
    deep = os.path.join(tc.project, "src", "a", "b", "c")
    os.makedirs(deep)
    return deep, True

def _sc_bounded_at_git_root(tc):
    # ~/.agentic exists but the git-root bound must stop the walk reaching it.
    os.makedirs(os.path.join(tc.home, ".agentic"))
    tc._make_repo()
    cwd = os.path.join(tc.project, "src")
    os.makedirs(cwd)
    return cwd, False

def _sc_worktree_allowlist(tc):
    tc._make_repo()
    os.makedirs(os.path.join(tc.home, ".agentic"))
    with open(os.path.join(tc.home, ".agentic", "activation.list"), "w") as fh:
        fh.write(tc.project + "\n")
    return tc._make_worktree(), True

def _sc_no_git_exact_cwd(tc):
    # No checkout anywhere: legacy exact-cwd; must not auto-detect ~/.agentic.
    os.makedirs(os.path.join(tc.home, ".agentic"))
    return tc.project, False

def _sc_nearest_marker_wins(tc):
    # Root dormant, nested (non-worktree) package active -> nearest wins.
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "dormant")
    tc._touch(tc.project, "src", "pkg", ".agentic", "active")
    deep = os.path.join(tc.project, "src", "pkg", "deep")
    os.makedirs(deep)
    return deep, True

_WALK_SCENARIOS = [
    ("worktree_inherits_active", _sc_worktree_active),
    ("worktree_inherits_dormant", _sc_worktree_dormant),
    ("deep_subdir_walks_to_repo_root", _sc_deep_subdir),
    ("bounded_at_git_root_ignores_home_agentic", _sc_bounded_at_git_root),
    ("worktree_inherits_allowlist", _sc_worktree_allowlist),
    ("no_git_preserves_exact_cwd", _sc_no_git_exact_cwd),
    ("nearest_marker_wins", _sc_nearest_marker_wins),
]

# --- hardening scenarios: markers inside .agentic/worktrees/** are ignored ---

def _hz_tombstone_in_worktree_root_active(tc):
    # Dormant tombstone written by a subagent in its own worktree must NOT
    # override the project root's active marker.
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "active")
    tc._touch(tc.project, ".agentic", "worktrees", "wt1", ".agentic", "dormant")
    cwd = os.path.join(tc.project, ".agentic", "worktrees", "wt1", "src")
    os.makedirs(cwd)
    return cwd, True

def _hz_active_in_worktree_root_dormant(tc):
    # An active marker inside a worktree is meaningless; the root's dormant
    # tombstone must win.
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "dormant")
    tc._touch(tc.project, ".agentic", "worktrees", "wt1", ".agentic", "active")
    cwd = os.path.join(tc.project, ".agentic", "worktrees", "wt1")
    os.makedirs(cwd, exist_ok=True)
    return cwd, False

def _hz_root_tombstone_propagates_into_worktree(tc):
    # Existing behavior preserved: a tombstone at the real root still
    # propagates down into worktrees (the zone rule only ignores markers
    # INSIDE the worktree zone, never the root's own markers).
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "dormant")
    return tc._make_worktree("wt9"), False

def _hz_zone_tombstone_only_root_autodetects(tc):
    # ONLY a tombstone inside the zone, no root marker: the walk must skip the
    # zone tombstone and auto-detect ACTIVE at the root (.agentic/ exists
    # because it holds worktrees/). Without the skip, every impl would decide
    # dormant at the worktree level.
    tc._make_repo()
    tc._touch(tc.project, ".agentic", "worktrees", "wt1", ".agentic", "dormant")
    cwd = os.path.join(tc.project, ".agentic", "worktrees", "wt1")
    os.makedirs(cwd, exist_ok=True)
    return cwd, True

_HARDENING_SCENARIOS = [
    ("tombstone_in_worktree_root_active", _hz_tombstone_in_worktree_root_active),
    ("active_in_worktree_root_dormant", _hz_active_in_worktree_root_dormant),
    ("root_tombstone_propagates_into_worktree", _hz_root_tombstone_propagates_into_worktree),
    ("zone_tombstone_only_root_autodetects", _hz_zone_tombstone_only_root_autodetects),
]

class TestCrossImplAncestorWalk(_WalkScenarios):
    """The 7 ancestor-walk cases mirrored against the sh and js guards (invoked
    as subprocesses) plus both in-process Python implementations."""

    def test_walk_parity_all_impls(self):
        for name, builder in _WALK_SCENARIOS:
            with self.subTest(scenario=name):
                self._fresh_sandboxes()
                cwd, expected = builder(self)
                self.assertEqual(hook_act.is_active(cwd), expected, f"hook-py: {name}")
                self.assertEqual(
                    act.resolve_state(cwd)["active"], expected, f"bin-py: {name}")
                if _HAVE_BASH:
                    self.assertEqual(
                        _sh_is_active(cwd, self.home), expected, f"sh: {name}")
                if _HAVE_NODE:
                    self.assertEqual(
                        _js_is_active(cwd, self.home), expected, f"js: {name}")

class TestWorktreeZoneHardening(_WalkScenarios):
    """Markers inside <root>/.agentic/worktrees/** must be ignored by all four
    implementations; the project root's own markers always decide."""

    def test_hardening_parity_all_impls(self):
        for name, builder in _HARDENING_SCENARIOS:
            with self.subTest(scenario=name):
                self._fresh_sandboxes()
                cwd, expected = builder(self)
                self.assertEqual(hook_act.is_active(cwd), expected, f"hook-py: {name}")
                self.assertEqual(
                    act.resolve_state(cwd)["active"], expected, f"bin-py: {name}")
                if _HAVE_BASH:
                    self.assertEqual(
                        _sh_is_active(cwd, self.home), expected, f"sh: {name}")
                if _HAVE_NODE:
                    self.assertEqual(
                        _js_is_active(cwd, self.home), expected, f"js: {name}")

if __name__ == "__main__":
    unittest.main()
