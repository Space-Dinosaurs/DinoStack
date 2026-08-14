# Not matched by the `hooks/tests/test-*.py` CI glob (bin-tests.yml
# hooks-python-tests job) by design - this is a shared helper imported by
# the six enforce-*.py fire-log regression tests below, not a standalone
# test file with its own assertions.
"""
Purpose: shared regression-test helper that proves a raising log_fire()
         cannot suppress an enforce-*.py hook's own permission decision
         (Skeptic Critical finding on PR feat/deterministic-hook-telemetry:
         "fail-open is import-time only; a raising log_fire silently
         converts a deny into an allow").

Public API:
    run_hook_with_raising_log_fire(hook_basename, payload, cwd=None,
                                    extra_env=None,
                                    snapshot_source_repo_dir=None)
        -> (returncode, stdout, stderr)
        hook_basename: e.g. "enforce-tier.py" - resolved against the real
              hooks/ directory (one level up from hooks/tests/).
        payload: the raw stdin string to feed the hook subprocess.
        cwd: working directory for the subprocess; a fresh temp dir is
              created and used when omitted.
        extra_env: dict merged into the subprocess environment (e.g. to
              clear a guard's kill-switch var).
        snapshot_source_repo_dir: when set, the copy is nested one level
              deeper (<workdir>/hooks/<hook>.py, <workdir>/hooks/lib/) and
              a <workdir>/.snapshot-meta.json is written pointing
              source_repo_dir at this path - the DS-54 snapshot-metadata
              mechanism enforce-shippable-edit.py's _resolve_repo_root()
              already understands. Needed only for that hook: its deny
              path depends on resolving the REAL repo root to compute a
              relative path, which a bare copy-to-tempdir cannot satisfy.

    Mechanics: copies the target hook script into an isolated temp dir
        alongside a lib/enforcement_log.py stub whose log_fire()
        unconditionally raises TypeError (simulating the DS-54
        half-applied-snapshot scenario the Critical finding describes: an
        old-signature caller invoking a newly-signed lib function). Because
        every enforce-*.py hook resolves its lib path via
        `os.path.dirname(os.path.abspath(__file__))` /
        `Path(__file__).resolve().parent`, running the COPY (not the
        original) makes the hook's own `_load_log_fire()` pick up the
        raising stub instead of the real, never-raising implementation -
        without touching the real hooks/lib/enforcement_log.py at all.

Upstream deps: Python 3 stdlib only (os, shutil, subprocess, sys, tempfile).
Downstream consumers: test-enforce-tier.py, test-enforce-background-spawn.py,
    test-enforce-orchestrator-singularity.py,
    test-enforce-askuserquestion-default.py, test-enforce-shippable-edit.py,
    test-enforce-planning-artifact-spawn.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RAISING_STUB = (
    '"""Test stub: log_fire always raises. Exists only to prove the calling '
    'hook\'s decision print is unaffected by a raising fire-log call - see '
    'hooks/tests/_fire_log_test_helper.py."""\n\n'
    "def log_fire(data, hook_name, decision, reason):\n"
    '    raise TypeError("simulated half-applied lib snapshot signature mismatch")\n'
)


def run_hook_with_raising_log_fire(
    hook_basename: str,
    payload: str,
    cwd: str | None = None,
    extra_env: dict | None = None,
    snapshot_source_repo_dir: str | None = None,
) -> tuple[int, str, str]:
    workdir = tempfile.mkdtemp(prefix="test-raising-log-fire-")
    real_hook_path = os.path.join(_HOOKS_DIR, hook_basename)

    if snapshot_source_repo_dir:
        hooks_dir = os.path.join(workdir, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)
        copied_hook_path = os.path.join(hooks_dir, hook_basename)
        lib_dir = os.path.join(hooks_dir, "lib")
        with open(
            os.path.join(workdir, ".snapshot-meta.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {"source_repo_dir": os.path.realpath(snapshot_source_repo_dir)}, f
            )
    else:
        copied_hook_path = os.path.join(workdir, hook_basename)
        lib_dir = os.path.join(workdir, "lib")

    shutil.copyfile(real_hook_path, copied_hook_path)
    os.makedirs(lib_dir, exist_ok=True)
    with open(
        os.path.join(lib_dir, "enforcement_log.py"), "w", encoding="utf-8"
    ) as f:
        f.write(_RAISING_STUB)
    # Also copy the real git_worktree.py alongside the raising stub, for
    # hooks (currently only enforce-worktree-read.py) that dynamically
    # import it at the same lib/ path - without this, the copied hook's
    # own is_git_worktree() import fails-open to "not a worktree", which
    # would falsely turn an expected DENY into an ALLOW in this helper's
    # test cases and has nothing to do with the raising-log_fire behavior
    # under test here.
    real_git_worktree_path = os.path.join(_HOOKS_DIR, "lib", "git_worktree.py")
    if os.path.isfile(real_git_worktree_path):
        shutil.copyfile(
            real_git_worktree_path, os.path.join(lib_dir, "git_worktree.py")
        )

    run_cwd = cwd or tempfile.mkdtemp(prefix="test-raising-log-fire-cwd-")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, copied_hook_path],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        cwd=run_cwd,
    )
    return result.returncode, result.stdout, result.stderr
