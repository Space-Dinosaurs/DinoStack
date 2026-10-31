"""DS_ALL_HARNESSES switch for tests that read non-Claude adapter output.

Claude Code is the primary harness: a methodology PR regenerates only
`.claude/`, and the other adapters catch up in an on-demand chore PR (root
AGENTS.md, "Claude Code first"). Assertions over non-Claude generated copies
run only when DS_ALL_HARNESSES=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ALL_HARNESSES = os.environ.get("DS_ALL_HARNESSES") == "1"

non_claude = pytest.mark.skipif(
    not ALL_HARNESSES,
    reason="reads non-Claude generated adapter output; set DS_ALL_HARNESSES=1",
)


def in_current_harness_rel(rel: str) -> bool:
    """True for a repo-relative path under a canonical source or `.claude`."""
    top = rel.split("/", 1)[0]
    return not top.startswith(".") or top == ".claude"


def in_current_harness(repo_root: Path, path: Path) -> bool:
    """True for canonical sources and Claude Code adapter output."""
    return in_current_harness_rel(path.relative_to(repo_root).as_posix())


def scoped(repo_root: Path, paths: list[Path]) -> list[Path]:
    """All paths under DS_ALL_HARNESSES=1, otherwise only the current harness's."""
    if ALL_HARNESSES:
        return list(paths)
    return [p for p in paths if in_current_harness(repo_root, p)]
