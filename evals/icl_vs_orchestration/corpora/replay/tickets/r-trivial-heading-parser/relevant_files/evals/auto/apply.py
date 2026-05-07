"""
Purpose: Extract the first fenced ```diff block from editor-agent output,
         validate its file paths against the component's editable/locked
         globs, enforce max_edit_loc, and apply via `git apply`. Rejection
         is loud; application is atomic (apply or don't).

         Also supports whole-file replacement mode for large command files
         where unified-diff generation is unreliable. In this mode the editor
         outputs the complete new file content in a fenced markdown block.

Public API:
    extract_diff(text: str) -> str | None
    extract_whole_file(text: str) -> tuple[str, str] | None
    validate_paths(diff: str, editable: list[str], locked: list[str])
        -> dict with keys {ok: bool, reason: str, paths: list[str]}
    validate_single_path(path: str, editable: list[str], locked: list[str])
        -> dict with keys {ok: bool, reason: str, paths: list[str]}
    count_changed_loc(diff: str) -> int
    count_changed_loc_for_whole_file(repo_root: Path, path: str,
                                     new_content: str) -> int
    apply_diff(repo_root: Path, diff: str) -> dict with keys
        {ok: bool, reason: str, stdout: str, stderr: str}
    apply_whole_file(repo_root: Path, path: str, content: str) -> dict with keys
        {ok: bool, reason: str, stdout: str, stderr: str}

Upstream deps: stdlib difflib, fnmatch, pathlib, re, subprocess.

Downstream consumers: evals.auto.loop.

Failure modes: validate_paths rejects on empty diff, on paths not matching any
               editable pattern, on paths matching any locked pattern, and on
               paths that traverse outside the repo ("../"). apply_diff reports
               `git apply` nonzero exit with stderr; it does not raise.

Performance: negligible; diffs are small (<=20 LOC).
"""
from __future__ import annotations

import difflib
import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ```diff ... ``` fenced block. The diff may span many lines; use DOTALL.
_DIFF_FENCE_RE = re.compile(r"```diff\s*\n(.*?)\n```", re.DOTALL)

# ```markdown ... ``` or ```md ... ``` fenced block for whole-file mode.
_WHOLE_FILE_FENCE_RE = re.compile(r"```(?:markdown|md)\s*\n(.*?)\n```", re.DOTALL)

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


def extract_whole_file(text: str) -> Optional[Tuple[str, str]]:
    """Extract a whole-file replacement from editor output.

    Looks for a fenced block with language tag ``markdown`` or ``md``.
    The first non-empty line inside the block may optionally be a file path
    comment like ``<!-- file: path -->`` or ``# path`` or just the bare
    path on its own line. If found, it is used as the path; otherwise the
    path is returned as an empty string.

    Returns ``(path, content)`` where content is everything inside the
    fenced block after the optional path line. Returns ``None`` if no
    markdown fenced block is present.
    """
    if not text:
        return None
    m = _WHOLE_FILE_FENCE_RE.search(text)
    if not m:
        return None
    body = m.group(1)
    lines = body.splitlines()
    if not lines:
        return ("", "")

    # Skip leading empty lines to find the first non-empty line.
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx >= len(lines):
        return ("", "")

    path = ""
    first = lines[idx].strip()
    if first.startswith("<!-- file:") and "-->" in first:
        path = first[first.find("file:") + 5 : first.find("-->")].strip()
        idx += 1
    elif first.startswith("#"):
        path = first.lstrip("#").strip()
        idx += 1
    elif first and not first.startswith("```"):
        path = first
        idx += 1

    content = "\n".join(lines[idx:])
    return (path, content)


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


def validate_single_path(
    path: str, editable: List[str], locked: List[str]
) -> Dict[str, object]:
    """Validate a single explicit path (whole-file replacement mode)."""
    if not path or not path.strip():
        return {"ok": False, "reason": "empty_path", "paths": []}
    if ".." in Path(path).parts:
        return {
            "ok": False,
            "reason": f"path_traversal_rejected:{path}",
            "paths": [path],
        }
    if _matches_any(path, locked):
        return {
            "ok": False,
            "reason": f"locked_path:{path}",
            "paths": [path],
        }
    if not _matches_any(path, editable):
        return {
            "ok": False,
            "reason": f"not_in_editable_allowlist:{path}",
            "paths": [path],
        }
    return {"ok": True, "reason": "", "paths": [path]}


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


def count_changed_loc_for_whole_file(
    repo_root: Path, path: str, new_content: str
) -> int:
    """Count changed lines between the existing file and new_content.

    Generates a unified diff and reuses count_changed_loc so the budget is
    consistent between diff mode and whole-file mode.
    """
    target = repo_root / path
    old_lines: List[str] = []
    if target.exists():
        old_lines = target.read_text(encoding="utf-8").splitlines()
    new_lines = new_content.splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    return count_changed_loc(diff)


def apply_diff(repo_root: Path, diff: str) -> Dict[str, object]:
    """Apply the diff via `git apply --index`. Returns status + git output.

    Editor-agent diffs frequently have off-by-one hunk counts and whitespace
    drift. We try three increasingly lenient modes:
    1. strict  (--index --whitespace=nowarn)
    2. recount (adds --recount so git recomputes @@ line counts)
    3. 3way    (adds --3way to fall back to 3-way merge on context mismatch)
    """
    if not diff.endswith("\n"):
        diff = diff + "\n"
    attempts = [
        ["git", "apply", "--index", "--whitespace=nowarn", "-"],
        ["git", "apply", "--index", "--whitespace=nowarn", "--recount", "-"],
        ["git", "apply", "--index", "--whitespace=nowarn", "--recount", "--3way", "-"],
    ]
    last = None
    for cmd in attempts:
        r = subprocess.run(
            cmd,
            cwd=str(repo_root),
            input=diff,
            capture_output=True,
            text=True,
        )
        last = r
        if r.returncode == 0:
            mode = "strict" if "--recount" not in cmd else ("3way" if "--3way" in cmd else "recount")
            return {
                "ok": True,
                "reason": f"applied_mode_{mode}",
                "stdout": r.stdout,
                "stderr": r.stderr,
            }
    return {
        "ok": False,
        "reason": f"git_apply_exit_{last.returncode}_all_modes_failed",
        "stdout": last.stdout,
        "stderr": last.stderr,
    }


def apply_whole_file(
    repo_root: Path, path: str, content: str
) -> Dict[str, object]:
    """Write content directly to path and stage it with git add.

    Returns status + any stderr from git add.
    """
    if not path or not path.strip():
        return {
            "ok": False,
            "reason": "empty_path",
            "stdout": "",
            "stderr": "",
        }
    if ".." in Path(path).parts:
        return {
            "ok": False,
            "reason": f"path_traversal_rejected:{path}",
            "stdout": "",
            "stderr": "",
        }
    target = repo_root / path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return {
            "ok": False,
            "reason": f"write_error:{e}",
            "stdout": "",
            "stderr": str(e),
        }
    r = subprocess.run(
        ["git", "add", "--", path],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return {
            "ok": False,
            "reason": f"git_add_exit_{r.returncode}",
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    return {
        "ok": True,
        "reason": "whole_file_written",
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
