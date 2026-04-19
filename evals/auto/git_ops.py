"""
Purpose: Thin wrappers around git commands used by the auto-harness loop:
         branch creation, current-branch query, clean-tree check, commit,
         hard-reset/revert to a ref, and diff LOC count between two refs.

Public API:
    current_branch(repo) -> str
    is_clean(repo) -> bool
    head_sha(repo) -> str
    create_branch(repo, name, base="HEAD") -> None
    commit_all(repo, message) -> str (new commit SHA)
    reset_hard(repo, ref) -> None
    diff_loc(repo, ref_a, ref_b) -> int

Upstream deps: stdlib subprocess, pathlib.

Downstream consumers: evals.auto.loop, evals.auto.cli.

Failure modes: any non-zero git exit raises RuntimeError with stderr.

Performance: git subprocess overhead; each call is O(10-100ms).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def _git(repo: Path, *args: str, check: bool = True, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        input=input_text,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {r.returncode}): {r.stderr.strip()}")
    return r


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def head_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def is_clean(repo: Path) -> bool:
    r = _git(repo, "status", "--porcelain")
    return r.stdout.strip() == ""


def create_branch(repo: Path, name: str, base: str = "HEAD") -> None:
    _git(repo, "checkout", "-b", name, base)


def commit_all(repo: Path, message: str) -> str:
    # Stage everything (the apply.py path uses --index, but Worker edits to
    # state files etc. should never land; callers are expected to have staged
    # only intentional changes before calling).
    _git(repo, "commit", "-m", message)
    return head_sha(repo)


def reset_hard(repo: Path, ref: str) -> None:
    _git(repo, "reset", "--hard", ref)


def diff_loc(repo: Path, ref_a: str, ref_b: str) -> int:
    r = _git(repo, "diff", "--numstat", f"{ref_a}..{ref_b}")
    n = 0
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                n += int(parts[0]) + int(parts[1])
            except ValueError:
                continue
    return n
