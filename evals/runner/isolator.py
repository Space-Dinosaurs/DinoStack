"""
Purpose: Provide component-tier isolation for eval runs. Tier 1 = git worktree
         of HEAD for read-only prompt components. Tier 2 = worktree + $HOME
         redirect for commands that write to the fixture (/init-project, /wrap).
         Tier 3 is a stub for Docker-sandboxed code execution.

Public API: make_isolator(tier: int, **kwargs) -> Isolator,
            Tier1Worktree (context manager yielding a worktree Path),
            Tier2HomeRedirect (context manager yielding (worktree, fake_home)),
            IsolatorBase abstract contract.

Upstream deps: stdlib subprocess, pathlib, tempfile, shutil, uuid, os, json.

Downstream consumers: evals.runner.cli, evals.runner.invoker.

Failure modes: raises RuntimeError if git worktree creation fails. Cleanup
               best-effort; stale dirs under evals/.worktrees/ and the
               per-run fake-HOME temp dir are logged with a warning if
               removal fails.

Performance: worktree add/remove is O(repo size); fake-HOME creation is
             O(1) plus a handful of small file writes.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

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


class Tier2HomeRedirect(IsolatorBase):
    """Tier 2: worktree PLUS redirected $HOME for fixture-writing commands.

    Tier 2 is for commands like /init-project and /wrap that must write files
    into a project directory. Isolation layers:

    - Worktree: seeded by copying the fixture's `repo/` subtree into a tmpdir
      (NOT a git worktree of HEAD - the fixture defines the starting repo
      state, not the repo we are developing).
    - $HOME redirect: a fresh tmpdir is created and passed to the subprocess
      as HOME so the command sees only the config we seed into
      $FAKE_HOME/.claude/. This prevents the runner from contaminating the
      developer's real `~/.claude/` or reading their real
      `agentic-engineering.json`.

    Inputs:
      fixture_repo_dir: path on disk containing the seeded fixture repo
                        (from fixture.dir / fixture.inputs.get("repo_dir"))
      home_config:      dict of filename -> str content to seed into
                        $FAKE_HOME/.claude/. e.g.
                        {"agentic-engineering.json": '{"mode":"opt-out",...}'}

    Yields: (worktree_path, fake_home_path). Both are temp directories owned
    by this isolator; the caller must not treat them as persistent.
    """

    tier = 2

    def __init__(
        self,
        fixture_repo_dir: Path | None = None,
        home_config: dict[str, str] | None = None,
    ) -> None:
        self.fixture_repo_dir = fixture_repo_dir
        self.home_config = home_config or {}
        self._worktree: Path | None = None
        self._fake_home: Path | None = None

    def __enter__(self) -> tuple[Path, Path]:
        # Fake HOME: fresh tmpdir so the command sees a clean ~/.claude/
        fake_home = Path(tempfile.mkdtemp(prefix="eval-home-"))
        claude_dir = fake_home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self.home_config.items():
            (claude_dir / name).write_text(content, encoding="utf-8")
        self._fake_home = fake_home

        # Worktree: copy the fixture's seeded repo into a fresh tmpdir. If no
        # seeded repo is provided, yield an empty tmpdir.
        worktree = Path(tempfile.mkdtemp(prefix="eval-wt-"))
        if self.fixture_repo_dir is not None and self.fixture_repo_dir.exists():
            # Copy contents of fixture_repo_dir into worktree (not the dir
            # itself). We iterate the top-level children so the worktree IS
            # the repo root.
            for child in self.fixture_repo_dir.iterdir():
                dest = worktree / child.name
                if child.is_dir():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)
        self._worktree = worktree

        return worktree, fake_home

    def __exit__(self, exc_type, exc, tb) -> None:
        for attr, label in (("_worktree", "worktree"), ("_fake_home", "fake HOME")):
            p: Path | None = getattr(self, attr)
            if p is None:
                continue
            try:
                shutil.rmtree(p, ignore_errors=False)
            except OSError as e:
                _log.warning(
                    "Tier 2 cleanup: failed to remove %s %s: %s "
                    "(manual removal may be required)",
                    label, p, e,
                )
            setattr(self, attr, None)


class Tier3Stub(IsolatorBase):
    tier = 3

    def __enter__(self) -> Path:
        # TODO: Tier 3 - Docker-mandatory sandbox for code-executing components
        # (Worker, Debugger, QA-engineer). See
        # docs/planning/p2-self-improving-harness.md section "Isolation model".
        raise NotImplementedError("Tier 3 isolation not implemented in Phase 1")

    def __exit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError("Tier 3 isolation not implemented in Phase 1")


def make_isolator(tier: int, **kwargs: Any) -> IsolatorBase:
    """Construct an isolator for the given tier.

    Tier 2 accepts `fixture_repo_dir: Path` and `home_config: dict[str,str]`
    keyword arguments; they are ignored by other tiers. Tier 1 and Tier 3 take
    no arguments.
    """
    if tier == 1:
        return Tier1Worktree()
    if tier == 2:
        return Tier2HomeRedirect(
            fixture_repo_dir=kwargs.get("fixture_repo_dir"),
            home_config=kwargs.get("home_config") or {},
        )
    if tier == 3:
        return Tier3Stub()
    raise ValueError(f"Unknown isolation tier: {tier}")
