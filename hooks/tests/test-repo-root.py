#!/usr/bin/env python3
"""
Unit tests: hooks/lib/repo_root.py (resolve_agentic_cwd_with_diagnostics /
resolve_agentic_cwd).

Consumes the SHARED cross-language fixture
hooks/tests/fixtures/repo-root-cases.json - the SAME cases drive
hooks/tests/test-repo-root.js, so a JS/Python resolver divergence
surfaces as one suite going red against a fixture neither owns.

Run with: python3 hooks/tests/test-repo-root.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(HERE, "..", "lib", "repo_root.py")
FIXTURE_PATH = os.path.join(HERE, "fixtures", "repo-root-cases.json")

_spec = importlib.util.spec_from_file_location("repo_root", LIB_PATH)
repo_root = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repo_root)

passed = 0
failed = 0


def assert_(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        print(f"  PASS: {message}")
        passed += 1
    else:
        print(f"  FAIL: {message}")
        failed += 1


def build_layout(tmp_dir: str, layout: dict) -> bool:
    dirs = (layout or {}).get("dirs", [""])
    for d in dirs:
        os.makedirs(os.path.join(tmp_dir, d), exist_ok=True)
    if layout and "git_at" in layout:
        git_path = os.path.join(tmp_dir, layout["git_at"], ".git")
        if layout.get("git_kind") == "file":
            with open(git_path, "w") as f:
                f.write("gitdir: ../.git/worktrees/x\n")
        else:
            os.makedirs(git_path, exist_ok=True)
        if layout.get("chmod_git"):
            try:
                os.chmod(git_path, int(layout["chmod_git"], 8))
            except OSError:
                pass  # best-effort; some platforms restrict this to root
    if layout and layout.get("symlink"):
        sym = layout["symlink"]
        src = os.path.join(tmp_dir, sym["from"])
        dst = os.path.join(tmp_dir, sym["to"])
        try:
            os.symlink(dst, src, target_is_directory=True)
        except OSError:
            return False
    return True


def cleanup(tmp_dir: str) -> None:
    # Restore any chmod-000 .git so recursive removal can traverse it.
    for root, dirs, files in os.walk(tmp_dir):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IRWXU)
            except OSError:
                pass
    try:
        os.chmod(tmp_dir, stat.S_IRWXU)
    except OSError:
        pass
    shutil.rmtree(tmp_dir, ignore_errors=True)


def run_case(tc: dict) -> None:
    raw_tmp = tempfile.mkdtemp(prefix="repo-root-py-")
    tmp_dir = os.path.realpath(raw_tmp)
    try:
        built = build_layout(tmp_dir, tc.get("layout"))
        if not built:
            print(f"  SKIP: {tc['id']} (platform cannot create symlinks)")
            return
        start = os.path.join(tmp_dir, tc.get("start", ""))
        result = repo_root.resolve_agentic_cwd_with_diagnostics(start)

        expected_root = os.path.join(tmp_dir, tc["expect"]["root"] or "")
        assert_(
            os.path.realpath(result["root"]) == os.path.realpath(expected_root),
            f"{tc['id']}: root resolves to expected path",
        )
        assert_(
            result["drift_levels"] == tc["expect"]["drift_levels"],
            f"{tc['id']}: drift_levels == {tc['expect']['drift_levels']} (got {result['drift_levels']})",
        )
        assert_(
            result["found_git_ancestor"] == tc["expect"]["found_git_ancestor"],
            f"{tc['id']}: found_git_ancestor == {tc['expect']['found_git_ancestor']} (got {result['found_git_ancestor']})",
        )

        wrapper_root = repo_root.resolve_agentic_cwd(start)
        assert_(
            wrapper_root == result["root"],
            f"{tc['id']}: resolve_agentic_cwd() agrees with resolve_agentic_cwd_with_diagnostics()['root']",
        )
    finally:
        cleanup(tmp_dir)


def main() -> int:
    with open(FIXTURE_PATH, "r") as f:
        fixtures = json.load(f)

    print("hooks/lib/repo_root.py tests\n")
    for tc in fixtures["cases"]:
        run_case(tc)

    # Never-raises smoke check not expressible via the shared fixture shape.
    try:
        repo_root.resolve_agentic_cwd("/definitely/does/not/exist/anywhere")
        never_raised = True
    except Exception:
        never_raised = False
    assert_(never_raised, "resolve_agentic_cwd never raises on a wholly nonexistent path")

    print(f"\n{passed} passed, {failed} failed.")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
