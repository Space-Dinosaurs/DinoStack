"""
Purpose: Provide component-tier isolation for eval runs. Phase 1 implements
         Tier 1 (git worktree under evals/.worktrees/); Tier 2 and Tier 3 are
         stubs that raise NotImplementedError per docs/planning/p2-self-improving-harness.md.

Public API: make_isolator(tier: int) -> Isolator,
            Tier1Worktree (context manager yielding a worktree Path),
            IsolatorBase abstract contract.

Upstream deps: stdlib subprocess, pathlib, tempfile, shutil, uuid.

Downstream consumers: evals.runner.cli, evals.runner.invoker.

Failure modes: raises RuntimeError if git worktree creation fails. Cleanup best-effort:
               on exit, runs `git worktree remove --force`; if that fails the caller
               may be left with stale directories under evals/.worktrees/ that the
               user can clean manually.

Performance: worktree add/remove is O(repo size) for the initial checkout; subsequent
             iterations are fast due to shared object store.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from .logging import get_logger

_log = get_logger("evals.isolator")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKTREE_BASE = _REPO_ROOT / "evals" / ".worktrees"


class IsolatorBase(ABC):
    tier: int

    @abstractmethod
    def __enter__(self) -> Path: ...

    @abstractmethod
    def __exit__(self, exc_type, exc, tb) -> None: ...


class Tier1Worktree(IsolatorBase):
    """Tier 1: git worktree of HEAD for read-only prompt components.

    Tier 1 is read-only: no Bash, no Write, no Edit, no network-bound tools.
    Allowed tools at the runner level are Read, Grep, Glob (plus Task for the
    two-level subagent spawn). If a component needs shell or network for its
    correctness, it does not belong at Tier 1 - declare Tier 2 or Tier 3.
    """

    tier = 1

    def __init__(self) -> None:
        self.worktree_path: Path | None = None

    def __enter__(self) -> Path:
        _WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
        name = f"wt-{uuid.uuid4().hex[:12]}"
        path = _WORKTREE_BASE / name
        # Detach at HEAD to avoid branch conflicts.
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        self.worktree_path = path
        return path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.worktree_path is None:
            return
        p = self.worktree_path
        # Best-effort cleanup - never raise, but surface failures via logging so
        # a silently-failing cleanup does not pile up stale worktrees.
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(p)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _log.warning(
                "git worktree remove --force failed for %s: %s",
                p,
                (result.stderr or result.stdout or "").strip(),
            )
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            if p.exists():
                _log.warning(
                    "worktree directory still present after cleanup: %s "
                    "(manual removal may be required)",
                    p,
                )
        self.worktree_path = None


class Tier2Stub(IsolatorBase):
    tier = 2

    def __enter__(self) -> Path:
        # TODO: Tier 2 - worktree + HOME redirect for commands that write to
        # the fixture (/init-project, /wrap). See
        # docs/planning/p2-self-improving-harness.md section "Isolation model".
        raise NotImplementedError("Tier 2 isolation not implemented in Phase 1")

    def __exit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError("Tier 2 isolation not implemented in Phase 1")


class Tier3Stub(IsolatorBase):
    tier = 3

    def __enter__(self) -> Path:
        # TODO: Tier 3 - Docker-mandatory sandbox for code-executing components
        # (Worker, Debugger, QA-engineer). See
        # docs/planning/p2-self-improving-harness.md section "Isolation model".
        raise NotImplementedError("Tier 3 isolation not implemented in Phase 1")

    def __exit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError("Tier 3 isolation not implemented in Phase 1")


def make_isolator(tier: int) -> IsolatorBase:
    if tier == 1:
        return Tier1Worktree()
    if tier == 2:
        return Tier2Stub()
    if tier == 3:
        return Tier3Stub()
    raise ValueError(f"Unknown isolation tier: {tier}")
