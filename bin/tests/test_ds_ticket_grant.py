#!/usr/bin/env python3
"""
Tests for ds-ticket-grant: writes the one-shot, operator-attributable
exception to hooks/enforce-ticket-batching.py's same-session ticket-
batching cap.

Test groups:
  1. test_grant_writes_reason_and_timestamp - a valid grant call writes
     {"reason": <str>, "granted_at": <str>} at the exact path the hook's
     own `_grant_path` resolves to for the same (repo, session_id).
  2. test_grant_path_matches_hook_naming - the CLI's own `_grant_path`
     sanitizes session_id byte-for-byte identically to the hook's
     `_safe_session_id`/`_grant_path` (cross-checked against the loaded
     hook module directly, not a re-typed copy of the regex).
  3. test_empty_reason_is_hard_error - a blank/whitespace-only --reason is
     rejected (exit 1, nothing written).
  4. test_empty_session_id_is_hard_error - a blank/whitespace-only
     --session-id is rejected (exit 1, nothing written).
  5. test_nonexistent_repo_is_hard_error - a --repo path that does not
     exist on disk is rejected (exit 1, nothing written, no directory
     created).
  6. test_bootstraps_bare_repo_agentic_dir - a --repo with no .agentic/
     yet gets it created at mode 0o700 (mirrors bin/ds-defer append's
     identical documented side effect).
  7. test_second_grant_overwrites_first - a second `grant` call for the
     same (repo, session_id) overwrites the first rather than erroring or
     appending.
  8. test_cli_runs_through_path_symlink_resolving_lib - regression guard
     for the install.sh PATH-symlink invocation path, mirroring ds-defer's
     identical test.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_ds_ticket_grant.py -x
       or: python3 bin/tests/test_ds_ticket_grant.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# ---------------------------------------------------------------------------
# Load ds-ticket-grant as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "ds-ticket-grant"
_loader = importlib.machinery.SourceFileLoader("ds_ticket_grant", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("ds_ticket_grant", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for ds-ticket-grant from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

main = _mod.main

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-ticket-batching.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("enforce_ticket_batching", str(_HOOK_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main() capturing stdout/stderr. Returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _ensure_git_marker(cwd: str) -> None:
    """Matches the hook's own test suite's helper - a `.git` existence
    marker so `resolve_agentic_cwd_with_diagnostics` resolves `cwd` as a
    repo root instead of failing open."""
    try:
        Path(cwd, ".git").mkdir(exist_ok=True)
    except OSError:
        pass


def test_grant_writes_reason_and_timestamp():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "operator asked for it"]
        )
        assert rc == 0, err
        hook_mod = _load_hook_module()
        expected_path = hook_mod._grant_path(tmp, "sess-1")
        assert expected_path is not None
        record = json.loads(expected_path.read_text())
        assert record["reason"] == "operator asked for it"
        assert "granted_at" in record and isinstance(record["granted_at"], str)


def test_grant_path_matches_hook_naming():
    """The CLI's own `_grant_path` must resolve to the exact same file the
    hook's `_grant_path` reads from, for several session_id shapes
    (including ones needing sanitization)."""
    hook_mod = _load_hook_module()
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        for session_id in ("sess-1", "weird/id with spaces!", "a.b_c-d"):
            cli_path = _mod._grant_path(tmp, session_id)
            hook_path = hook_mod._grant_path(tmp, session_id)
            # Compare resolved absolute paths - the hook's repo-root
            # resolution passes cwd through `Path.resolve()` internally
            # (following e.g. macOS's /var -> /private/var symlink), while
            # the CLI's `_grant_path` builds directly off the caller-
            # supplied --repo string. Both must still name the SAME real
            # file once resolved.
            assert cli_path.resolve() == hook_path.resolve(), (session_id, cli_path, hook_path)


def test_empty_reason_is_hard_error():
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "   "]
        )
        assert rc == 1
        assert not (Path(tmp) / ".agentic").exists()


def test_empty_session_id_is_hard_error():
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "   ", "--reason", "operator asked"]
        )
        assert rc == 1
        assert not (Path(tmp) / ".agentic").exists()


def test_nonexistent_repo_is_hard_error():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = str(Path(tmp) / "does-not-exist")
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", fake_repo, "--session-id", "sess-1", "--reason", "operator asked"]
        )
        assert rc == 1
        assert not Path(fake_repo).exists()


def test_bootstraps_bare_repo_agentic_dir():
    with tempfile.TemporaryDirectory() as tmp:
        assert not (Path(tmp) / ".agentic").exists()
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "operator asked"]
        )
        assert rc == 0, err
        agentic_dir = Path(tmp) / ".agentic"
        assert agentic_dir.is_dir()
        assert (agentic_dir.stat().st_mode & 0o777) == 0o700


def test_second_grant_overwrites_first():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run(["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "first ask"])
        rc, out, err = _run(
            ["ds-ticket-grant", "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "second ask"]
        )
        assert rc == 0, err
        hook_mod = _load_hook_module()
        path = hook_mod._grant_path(tmp, "sess-1")
        record = json.loads(path.read_text())
        assert record["reason"] == "second ask"
        # Exactly one grant file for this session - no accumulation.
        matches = list(Path(tmp, ".agentic").glob(".ticket-batch-grant-sess-1.json"))
        assert len(matches) == 1


def test_cli_runs_through_path_symlink_resolving_lib():
    """Regression guard for the install.sh PATH-symlink invocation path -
    mirrors bin/ds-defer's identical test. Invokes the CLI as a subprocess
    through a symlink and asserts it can still locate and load
    bin/_lib.py rather than raising FileNotFoundError (the DS-66 bug
    class)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        fake_bin = Path(tmp) / "fake-local-bin"
        fake_bin.mkdir()
        symlink = fake_bin / "ds-ticket-grant"
        symlink.symlink_to(_BIN_PATH.resolve())
        result = subprocess.run(
            [sys.executable, str(symlink), "grant", "--repo", tmp, "--session-id", "sess-1", "--reason", "operator asked"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        hook_mod = _load_hook_module()
        path = hook_mod._grant_path(tmp, "sess-1")
        assert path.is_file()


if __name__ == "__main__":
    import inspect

    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures.append(name)
                print(f"FAIL {name}: {e}")
    if failures:
        print(f"\n{len(failures)} failed: {failures}")
        sys.exit(1)
    print("\nAll tests passed.")
