"""
Purpose: Provide component-tier isolation for eval runs. Tier 1 = git worktree
         of HEAD for read-only prompt components. Tier 2 = worktree + $HOME
         redirect for commands that write to the fixture (/init-project, /wrap).
         Tier 3 = Docker container with isolated mounts and network disabled
         for code-executing components (Worker, Debugger, QA-engineer,
         SWE-bench-style fix tasks).

         NOTE on Tier 2 auth preservation: Tier 2 redirects $HOME to a fresh
         tmpdir to keep the developer's real ~/.claude/ uncontaminated. The
         Claude CLI, however, resolves auth relative to $HOME (macOS keychain
         at ~/Library/Keychains/login.keychain-db, Linux at
         ~/.claude/.credentials.json). A bare HOME redirect produces "Not
         logged in" failures. To resolve this without giving the eval write
         access to the real ~/.claude/, Tier 2 creates narrow read-through
         symlinks for ONLY the auth artifacts:
           - macOS: fake_home/Library/Keychains -> real ~/Library/Keychains
           - all:   fake_home/.claude/.credentials.json -> real one (if any)
                    fake_home/.claude/.credentials.json.bak -> real one (if any)
         home_config seeded files take precedence over the symlinks (existence
         check before symlinking). __exit__ uses shutil.rmtree which removes
         symlinks without following them, so the real keychain and real
         credentials file are never touched on cleanup.

         NOTE on Tier 3 two-phase layout:
           Fix phase:  rw mount at /workspace/repo  (seeded fix-phase repo)
                       held-out tests NOT mounted
           Score phase: separate docker run invocation; mounts
                         /workspace/repo ro  (fix-phase output, read-only)
                         /scoring/tests  ro  (held-out tests)
                       pytest CWD is /scoring (NOT /workspace/repo) with
                       --noconftest --rootdir=/scoring/tests
                       --confcutdir=/scoring to prevent conftest.py or
                       pytest.ini planted by the agent from executing.
                       NO pip install during score phase - agent cannot
                       add dependencies that take effect during scoring.
         Both docker run invocations use --network none, --memory 1g,
         --cpus 1.0, --cap-drop=ALL, --security-opt=no-new-privileges,
         --pids-limit=256, --read-only, and --tmpfs /tmp:size=64m,noexec,nosuid.
         The docker build step requires network (for pip install) but the
         eval containers themselves are always network-isolated at run time.

         NOTE on Tier 3 macOS Docker Desktop divergence:
           On Linux, --network none disables all network namespaces. On
           macOS Docker Desktop, the container runs inside a Linux VM so
           --network none is equally effective for the container; the
           difference is that the host-level DNS resolver for Docker Desktop
           manages the VM's connectivity, not the container's. In practice,
           --network none reliably prevents in-container DNS resolution and
           outbound TCP on both platforms. No workaround is required.

         NOTE on Tier 3 container timeout handling:
           `timeout_seconds` is the REAL in-container wall-clock limit.
           The entrypoint wraps commands with `timeout <N>` so the process
           is killed inside the container. The outer subprocess.run timeout
           is set to timeout_seconds + 30 s as a host-side safety guard.
           On host-side subprocess.TimeoutExpired (fallback), the container
           is force-removed via `docker rm -f <cidfile-id>` in a try/finally
           so no container leaks on the Docker daemon.

         NOTE on image digest pinning:
           After each `docker build`, the local image digest is resolved via
           `docker inspect --format={{.Id}}` and stored. run_fix_phase and
           run_score_phase reference the digest (not the mutable tag) so
           parallel-branch tag overwrites cannot silently swap the image.

Public API: make_isolator(tier: int, **kwargs) -> Isolator,
            Tier1Worktree (context manager yielding a worktree Path),
            Tier2HomeRedirect (context manager yielding (worktree, fake_home)),
            Tier3Docker (context manager yielding a Tier3Context namedtuple),
            IsolatorBase abstract contract.

Upstream deps: stdlib subprocess, pathlib, tempfile, shutil, uuid, os, sys,
               json, typing. Tier 3 requires `docker` CLI on PATH; absence
               raises FileNotFoundError (OSError subclass) when any docker
               subprocess.run call is made - callers should guard with a
               _docker_available() check before constructing Tier3Docker.

Downstream consumers: evals.runner.cli, evals.runner.invoker.

Failure modes: raises RuntimeError if git worktree creation fails (Tier 1/2).
               raises RuntimeError if docker build/run fails (Tier 3).
               raises FileNotFoundError if `docker` CLI is not found on PATH
               (Tier 3 only); no network needed if image is pre-built.
               Cleanup best-effort; stale dirs under evals/.worktrees/ and the
               per-run fake-HOME temp dir are logged with a warning if
               removal fails. Auth-symlink creation failures are logged but
               do not raise - the eval still runs, may fall back to
               ANTHROPIC_API_KEY env if propagated. Tier 3 containers always
               run with --rm; on host-side TimeoutExpired the cidfile-tracked
               container is force-removed via docker rm -f in a try/finally.

Performance: worktree add/remove is O(repo size); fake-HOME creation is
             O(1) plus a handful of small file writes plus 1-3 symlinks.
             Tier 3 fix-phase container build is O(image size) on first run,
             then cached. Container cold-start is ~1-3 s on Docker Desktop.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, NamedTuple

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

        # Auth preservation: narrow symlinks so Claude CLI can resolve auth
        # via $HOME without exposing the rest of the developer's real config.
        # See module docstring for rationale.
        real_home = Path(os.path.expanduser("~"))

        # macOS keychain: symlink the entire Keychains directory so sub-keychain
        # files remain accessible to the Security framework.
        if sys.platform == "darwin":
            real_keychains = real_home / "Library" / "Keychains"
            if real_keychains.exists():
                fake_library = fake_home / "Library"
                fake_library.mkdir(parents=True, exist_ok=True)
                fake_keychains = fake_library / "Keychains"
                if not fake_keychains.exists():
                    try:
                        fake_keychains.symlink_to(real_keychains, target_is_directory=True)
                    except OSError as e:
                        _log.warning(
                            "Tier 2: failed to symlink keychain dir %s -> %s: %s",
                            fake_keychains, real_keychains, e,
                        )

        # Linux/cross-platform credentials.json (and .bak). home_config wins.
        for cred_name in (".credentials.json", ".credentials.json.bak"):
            real_cred = real_home / ".claude" / cred_name
            fake_cred = claude_dir / cred_name
            if real_cred.exists() and not fake_cred.exists():
                try:
                    fake_cred.symlink_to(real_cred)
                except OSError as e:
                    _log.warning(
                        "Tier 2: failed to symlink credential %s -> %s: %s",
                        fake_cred, real_cred, e,
                    )

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


# ---------------------------------------------------------------------------
# Tier 3: Docker container isolation
# ---------------------------------------------------------------------------


def _force_remove_cidfile_container(cidfile: Path) -> None:
    """Read the container ID from `cidfile` and force-remove the container.

    Called in the except/finally path when a host-side subprocess.TimeoutExpired
    fires. The cidfile is written by `docker run --cidfile` before the container
    starts executing, so it should be present. Best-effort: logs on failure,
    never raises.
    """
    try:
        cid = cidfile.read_text().strip()
    except OSError:
        _log.warning("Tier 3: cidfile %s unreadable; cannot force-remove container", cidfile)
        return
    if not cid:
        return
    try:
        subprocess.run(
            ["docker", "rm", "-f", cid],
            capture_output=True,
            check=False,
            timeout=15,
        )
        _log.info("Tier 3: force-removed container %s after timeout", cid)
    except (OSError, subprocess.TimeoutExpired) as e:
        _log.warning("Tier 3: docker rm -f %s failed: %s", cid, e)

# Pinned base image digest (python:3.11-slim, verified 2026-05-11).
# Pin by digest so a silent upstream tag move cannot change the base image
# between runs and break reproducibility. Update when intentionally upgrading.
_DOCKER_BASE_IMAGE = (
    "python@sha256:a5b427ace4900267d93db34138e512325c6fa6a"
    "f84ad5e4ed5f3b36258cc4142"
)

# Dockerfile location relative to this file.
_DOCKERFILE_PATH = Path(__file__).resolve().parent / "Dockerfile.swebench"

# Image tag used locally (not pushed).
_DOCKER_IMAGE_TAG = "ae-eval-swebench:latest"


class Tier3Context(NamedTuple):
    """Return value of Tier3Docker.__enter__."""

    # Host-side tmpdir seeded with the fix-phase repo. Mounted rw at
    # /workspace/repo inside the container.
    fix_phase_dir: Path

    # Host-side directory that holds the held-out test files. NOT mounted
    # during the fix phase; mounted ro at /scoring/tests during score phase.
    held_out_dir: Path

    # Image tag that was built (or already existed); retained for display /
    # compatibility only. run_fix_phase and run_score_phase use image_digest
    # for all docker run calls to avoid mutable-tag races.
    image_tag: str

    # Content-addressed digest resolved after build (or inspect of pre-built
    # image). Format: "sha256:<hex>". Used in all docker run calls so a
    # parallel-branch tag overwrite cannot silently swap the image.
    image_digest: str


class Tier3Docker(IsolatorBase):
    """Tier 3: Docker container with isolated mounts and --network none.

    Two-phase design:
      Fix phase   - rw mount at /workspace/repo; held-out tests NOT mounted.
      Score phase - separate `docker run`; /workspace/repo ro + /scoring/tests ro.

    Both phases run with --network none, --memory 1g, --cpus 1.0, and --rm.

    Inputs:
      fixture_repo_dir: optional host path to seed into fix_phase_dir before
                        yielding. If None, fix_phase_dir is an empty tmpdir.
      held_out_dir:     optional host path for the held-out test tree. If None,
                        a separate empty tmpdir is created (the dir still exists
                        but nothing is in it - the mount still does not appear
                        inside the fix-phase container).
      build_image:      if True (default), build the Docker image from
                        Dockerfile.swebench before entering. Set to False when
                        the image is known to be pre-built (e.g. in test
                        environments that pre-pull the image).
      timeout_seconds:  wall-clock timeout passed to the fix-phase `docker run`
                        via --stop-timeout (default 300 s).

    Yields: Tier3Context(fix_phase_dir, held_out_dir, image_tag)
    """

    tier = 3

    def __init__(
        self,
        fixture_repo_dir: Path | None = None,
        held_out_dir: Path | None = None,
        build_image: bool = True,
        timeout_seconds: int = 300,
    ) -> None:
        self.fixture_repo_dir = fixture_repo_dir
        self._held_out_dir = held_out_dir
        self.build_image = build_image
        self.timeout_seconds = timeout_seconds

        self._fix_phase_dir: Path | None = None
        self._owned_held_out_dir: Path | None = None  # only set if we created it
        self._container_id: str | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Tier3Context:
        # 1. Optionally build the image, then resolve the content digest.
        if self.build_image:
            self._build_image()
        image_digest = self._resolve_image_digest()

        # 2. Prepare fix-phase dir (rw copy of the fixture repo).
        fix_phase_dir = Path(tempfile.mkdtemp(prefix="t3-fix-"))
        if self.fixture_repo_dir is not None and self.fixture_repo_dir.exists():
            for child in self.fixture_repo_dir.iterdir():
                dest = fix_phase_dir / child.name
                if child.is_dir():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)
        self._fix_phase_dir = fix_phase_dir

        # 3. Prepare held-out dir.
        if self._held_out_dir is not None:
            held_out_dir = self._held_out_dir
        else:
            held_out_dir = Path(tempfile.mkdtemp(prefix="t3-held-"))
            self._owned_held_out_dir = held_out_dir

        return Tier3Context(
            fix_phase_dir=fix_phase_dir,
            held_out_dir=held_out_dir,
            image_tag=_DOCKER_IMAGE_TAG,
            image_digest=image_digest,
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        # Best-effort: nuke any lingering container (--rm already handles
        # clean exits; this catches crash/timeout paths).
        if self._container_id is not None:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_id],
                    capture_output=True,
                    check=False,
                )
            except OSError as e:
                _log.warning("Tier 3: failed to rm container %s: %s", self._container_id, e)
            self._container_id = None

        # Clean up host-side tmpdirs.
        for attr, label in (
            ("_fix_phase_dir", "fix-phase dir"),
            ("_owned_held_out_dir", "held-out dir"),
        ):
            p: Path | None = getattr(self, attr)
            if p is None:
                continue
            try:
                shutil.rmtree(p, ignore_errors=False)
            except OSError as e:
                _log.warning(
                    "Tier 3 cleanup: failed to remove %s %s: %s "
                    "(manual removal may be required)",
                    label, p, e,
                )
            setattr(self, attr, None)

    # ------------------------------------------------------------------
    # Image management
    # ------------------------------------------------------------------

    @staticmethod
    def _build_image() -> None:
        """Build the swebench Docker image from Dockerfile.swebench.

        Note: `docker build` requires network to pull the base image and run
        `pip install` in RUN steps. `--network none` is intentionally omitted
        here. Network isolation (`--network none`) is enforced at `docker run`
        time (fix and score phases) so that the eval container itself has no
        outbound network during the actual eval execution. The build step is a
        one-time setup; run-time isolation is the security boundary that matters.
        """
        if not _DOCKERFILE_PATH.exists():
            raise RuntimeError(
                f"Dockerfile.swebench not found at {_DOCKERFILE_PATH}. "
                "Cannot build Tier 3 image."
            )
        result = subprocess.run(
            [
                "docker", "build",
                "-t", _DOCKER_IMAGE_TAG,
                "-f", str(_DOCKERFILE_PATH),
                str(_DOCKERFILE_PATH.parent),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker build failed (exit {result.returncode}):\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        _log.info("Tier 3: image built as %s", _DOCKER_IMAGE_TAG)

    @staticmethod
    def _resolve_image_digest() -> str:
        """Resolve the local image to its content digest (sha256:<hex>).

        Uses `docker inspect` so the returned reference is content-addressed
        and immune to mutable-tag races where a parallel branch overwrites
        the local ae-eval-swebench:latest tag between build and run.

        Raises RuntimeError if the image is not found locally.
        """
        result = subprocess.run(
            ["docker", "inspect", "--format={{.Id}}", _DOCKER_IMAGE_TAG],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(
                f"docker inspect failed for {_DOCKER_IMAGE_TAG}: "
                f"{result.stderr.strip() or 'image not found locally'}"
            )
        digest = result.stdout.strip()
        _log.info("Tier 3: image digest resolved: %s", digest)
        return digest

    # ------------------------------------------------------------------
    # Run helpers (called by the eval driver, not by __enter__)
    # ------------------------------------------------------------------

    @staticmethod
    def run_fix_phase(
        ctx: Tier3Context,
        command: list[str] | None = None,
        timeout_seconds: int = 300,
        env: dict[str, str] | None = None,
        prompt: str | None = None,
        agent_name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the engineer fix phase, either via Claude CLI (prompt mode) or
        an arbitrary command (command mode).

        When `prompt` is provided the method invokes the Claude CLI on the
        HOST (not inside the container) with cwd=ctx.fix_phase_dir so that
        the agent's file writes land in the host-side directory that is
        later mounted at /workspace/repo:rw inside the score-phase container.
        The container is NOT started for the claude CLI invocation because the
        CLI requires outbound network to reach the Anthropic API; an
        in-container invocation under --network none would break auth.

        When `command` is provided (and `prompt` is None) the command is
        executed INSIDE the container with the standard fix-phase isolation:
          - /workspace/repo mounted rw; /scoring/tests NOT mounted.
          - --network none: no outbound network.
          - --cap-drop=ALL --security-opt=no-new-privileges.
          - --read-only rootfs; /tmp writable via tmpfs (64m, noexec, nosuid).
          - --pids-limit=256: fork-bomb mitigation.
          - Container referenced by content digest, not mutable tag.

        Exactly one of `prompt` or `command` must be supplied.

        Args:
            ctx: Tier3Context from __enter__.
            command: command to run INSIDE the container (command path).
            timeout_seconds: wall-clock limit.
            env: additional env vars for the claude CLI subprocess (prompt path)
                 or injected into the docker run command (command path).
            prompt: engineer prompt for the Claude CLI. When set, the CLI is
                    invoked on the HOST at cwd=ctx.fix_phase_dir.
            agent_name: optional named-agent spawned via two-level Task wrapper
                        (prompt path only). None = conductor runs directly.
            system_prompt: optional system prompt appended via
                           --append-system-prompt (prompt path only; used for
                           ae-rules-injected condition).
            model: optional --model flag for the Claude CLI (prompt path only).

        Returns a CompletedProcess. For the prompt path, returncode is 0 when
        the invoker returns status='ok' and 1 otherwise; stdout contains the
        invoker result dict as JSON. For the command path, returncode is the
        docker run exit code.

        Raises ValueError if neither or both of prompt/command are provided.
        """
        if prompt is None and command is None:
            raise ValueError(
                "Tier3Docker.run_fix_phase: exactly one of 'prompt' or 'command' must be provided"
            )
        if prompt is not None and command is not None:
            raise ValueError(
                "Tier3Docker.run_fix_phase: 'prompt' and 'command' are mutually exclusive"
            )

        if prompt is not None:
            # Prompt path: run the Claude CLI on the HOST so it can reach the
            # Anthropic API.  The agent's file writes go into ctx.fix_phase_dir,
            # which is the host-side copy of the repo mounted at /workspace/repo:rw
            # for the score phase.
            import json as _json
            from evals.runner.invoker import invoke_run as _invoke_run  # local to avoid circular
            result = _invoke_run(
                prompt=prompt,
                worktree=ctx.fix_phase_dir,
                timeout_seconds=timeout_seconds,
                agent_name=agent_name,
                mode="agent",
                system_prompt=system_prompt,
                model=model,
            )
            returncode = 0 if result.get("status") == "ok" else 1
            stdout_json = _json.dumps(result, default=str)
            return subprocess.CompletedProcess(
                args=[],
                returncode=returncode,
                stdout=stdout_json,
                stderr=result.get("stderr_tail", ""),
            )

        # Command path: run an arbitrary command INSIDE the container.
        assert command is not None  # guaranteed by the checks above
        cidfile = Path(tempfile.mktemp(prefix="t3-cid-", suffix=".cid"))
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--cidfile", str(cidfile),
            "--network", "none",
            "--memory", "1g",
            "--cpus", "1.0",
            "--pids-limit", "256",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:size=64m,noexec,nosuid",
            "--tmpfs", "/home/evaluser:size=32m,noexec,nosuid",
            "-e", f"EVAL_TIMEOUT_SECONDS={timeout_seconds}",
            "-v", f"{ctx.fix_phase_dir}:/workspace/repo:rw",
            "-w", "/workspace/repo",
        ]
        if env:
            for k, v in env.items():
                docker_cmd += ["-e", f"{k}={v}"]
        docker_cmd += [ctx.image_digest] + command
        try:
            return subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 30,  # host-side guard; in-container timeout is authoritative
            )
        except subprocess.TimeoutExpired:
            _force_remove_cidfile_container(cidfile)
            raise
        finally:
            try:
                cidfile.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def run_score_phase(
        ctx: Tier3Context,
        command: list[str],
        timeout_seconds: int = 300,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a scoring command inside the container (score phase).

        Security contract:
          - /workspace/repo mounted ro: agent-controlled fix output is read-only.
          - /scoring/tests mounted ro: held-out test tree.
          - Working directory is /scoring (NOT /workspace/repo) so pytest
            cannot discover conftest.py / pytest.ini / pyproject.toml planted
            by the agent in /workspace/repo.
          - pytest is invoked via the entrypoint with --noconftest
            --rootdir=/scoring/tests --confcutdir=/scoring so no conftest
            outside /scoring is loaded.
          - No pip install: the agent cannot add dependencies that affect scoring.
          - --network none, --cap-drop=ALL, --security-opt=no-new-privileges,
            --read-only, --tmpfs /tmp:size=64m,noexec,nosuid, --pids-limit=256.
          - Container referenced by content digest, not mutable tag.

        Timeout: see run_fix_phase docstring (same contract).

        Returns the CompletedProcess; callers check returncode.
        """
        cidfile = Path(tempfile.mktemp(prefix="t3-cid-", suffix=".cid"))
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--cidfile", str(cidfile),
            "--network", "none",
            "--memory", "1g",
            "--cpus", "1.0",
            "--pids-limit", "256",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:size=64m,noexec,nosuid",
            "--tmpfs", "/home/evaluser:size=32m,noexec,nosuid",
            "-e", f"EVAL_TIMEOUT_SECONDS={timeout_seconds}",
            "-v", f"{ctx.fix_phase_dir}:/workspace/repo:ro",
            "-v", f"{ctx.held_out_dir}:/scoring/tests:ro",
            "-w", "/scoring",
        ]
        if env:
            for k, v in env.items():
                docker_cmd += ["-e", f"{k}={v}"]
        docker_cmd += [ctx.image_digest] + command
        try:
            return subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 30,  # host-side guard; in-container timeout is authoritative
            )
        except subprocess.TimeoutExpired:
            _force_remove_cidfile_container(cidfile)
            raise
        finally:
            try:
                cidfile.unlink(missing_ok=True)
            except OSError:
                pass


def make_isolator(tier: int, **kwargs: Any) -> IsolatorBase:
    """Construct an isolator for the given tier.

    Tier 2 accepts `fixture_repo_dir: Path` and `home_config: dict[str,str]`
    keyword arguments.

    Tier 3 accepts:
      fixture_repo_dir: Path | None  - seed for the fix-phase dir
      held_out_dir: Path | None      - host path to the held-out test tree
      build_image: bool              - whether to build the Docker image (default True)
      timeout_seconds: int           - wall-clock timeout for docker run (default 300)
    """
    if tier == 1:
        return Tier1Worktree()
    if tier == 2:
        return Tier2HomeRedirect(
            fixture_repo_dir=kwargs.get("fixture_repo_dir"),
            home_config=kwargs.get("home_config") or {},
        )
    if tier == 3:
        return Tier3Docker(
            fixture_repo_dir=kwargs.get("fixture_repo_dir"),
            held_out_dir=kwargs.get("held_out_dir"),
            build_image=kwargs.get("build_image", True),
            timeout_seconds=kwargs.get("timeout_seconds", 300),
        )
    raise ValueError(f"Unknown isolation tier: {tier}")
