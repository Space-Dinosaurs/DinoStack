"""
Purpose: Extract the first fenced ```diff block from editor-agent output,
         validate its file paths against the component's editable/locked
         globs, enforce max_edit_loc, and apply via `git apply`. Rejection
         is loud; application is atomic (apply or don't).

Public API:
    extract_diff(text: str) -> str | None
    validate_paths(diff: str, editable: list[str], locked: list[str])
        -> dict with keys {ok: bool, reason: str, paths: list[str]}
    count_changed_loc(diff: str) -> int
    apply_diff(repo_root: Path, diff: str) -> dict with keys
        {ok: bool, reason: str, stdout: str, stderr: str}

Upstream deps: stdlib fnmatch, pathlib, re, subprocess.

Downstream consumers: evals.auto.loop.

Failure modes: validate_paths rejects on empty diff, on paths not matching any
               editable pattern, on paths matching any locked pattern, and on
               paths that traverse outside the repo ("../"). apply_diff reports
               `git apply` nonzero exit with stderr; it does not raise.

Performance: negligible; diffs are small (<=20 LOC).
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# ```diff ... ``` fenced block. The diff may span many lines; use DOTALL.
_DIFF_FENCE_RE = re.compile(r"```diff\s*\n(.*?)\n```", re.DOTALL)

# Matches the "+++ b/path" and "--- a/path" headers of a unified diff.
_DIFF_PATH_RE = re.compile(r"^(?:\+\+\+|---)\s+[ab]/(.+?)(?:\s|$)", re.MULTILINE)


def extract_diff(text: str) -> Optional[str]:
    """Return the first fenced ```diff block content, or None if absent."""
    if not text:
        return None
    m = _DIFF_FENCE_RE.search(text)
    if not m:
        return None
    body = m.group(1).strip()
    return body or None


def _paths_from_diff(diff: str) -> List[str]:
    paths = set()
    for m in _DIFF_PATH_RE.finditer(diff):
        p = m.group(1).strip()
        if p == "/dev/null":
            continue
        paths.add(p)
    return sorted(paths)


def _matches_any(path: str, patterns: List[str]) -> bool:
    for pat in patterns:
        # fnmatch handles simple globs; support "**" as "*" recursive by
        # splitting. For our editable/locked specs (plain files or dir/**)
        # fnmatch with translated pattern is sufficient.
        if fnmatch.fnmatch(path, pat):
            return True
        # Support "dir/**" style explicitly.
        if pat.endswith("/**"):
            prefix = pat[:-3]
            if path == prefix or path.startswith(prefix + "/"):
                return True
    return False


def validate_paths(
    diff: str, editable: List[str], locked: List[str]
) -> Dict[str, object]:
    if not diff or not diff.strip():
        return {"ok": False, "reason": "empty_diff", "paths": []}
    paths = _paths_from_diff(diff)
    if not paths:
        return {
            "ok": False,
            "reason": "no_file_headers_found",
            "paths": [],
        }
    for p in paths:
        if ".." in Path(p).parts:
            return {
                "ok": False,
                "reason": f"path_traversal_rejected:{p}",
                "paths": paths,
            }
        if _matches_any(p, locked):
            return {
                "ok": False,
                "reason": f"locked_path:{p}",
                "paths": paths,
            }
        if not _matches_any(p, editable):
            return {
                "ok": False,
                "reason": f"not_in_editable_allowlist:{p}",
                "paths": paths,
            }
    return {"ok": True, "reason": "", "paths": paths}


def count_changed_loc(diff: str) -> int:
    """Count added+removed content lines in a unified diff.

    File headers (+++, ---) and hunk headers (@@) are NOT counted.
    """
    if not diff:
        return 0
    n = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("+") or line.startswith("-"):
            n += 1
    return n


def apply_diff(repo_root: Path, diff: str) -> Dict[str, object]:
    """Apply the diff via `git apply --index`. Returns status + git output."""
    if not diff.endswith("\n"):
        diff = diff + "\n"
    # --index stages the changes so they are ready for commit.
    r = subprocess.run(
        ["git", "apply", "--index", "--whitespace=nowarn", "-"],
        cwd=str(repo_root),
        input=diff,
        capture_output=True,
        text=True,
    )
    return {
        "ok": r.returncode == 0,
        "reason": "" if r.returncode == 0 else f"git_apply_exit_{r.returncode}",
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
