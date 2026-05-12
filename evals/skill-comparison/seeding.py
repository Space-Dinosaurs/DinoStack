"""
Purpose: Seed a per-cell fix-phase working directory by cloning the upstream
         repo at the task's base_commit and applying the task's test_patch.
         Provides a writable working tree for the engineer agent and the
         held-out tests already baked in (applied by test_patch) so the
         score phase can run them without the engineer ever seeing them.

Public API:
    seed_fix_phase(
        task_slug: str,
        task_meta: dict,
        fix_dir: Path,
        tasks_root: Path,
        cache_dir: Path | None = None,
    ) -> dict
        Clones repo at base_commit into fix_dir and applies test_patch.diff.
        Returns {"seed_commit": "<sha>"} where seed_commit is the git SHA of
        the post-seeding commit (after test_patch is applied and committed).
        Callers use seed_commit as the base for computing engineer diffs.
        Raises SeedError on any failure (clone, checkout, or patch failure).

    SeedError(RuntimeError):
        Raised when seeding fails. The message includes which step failed
        and the subprocess stderr so the caller can log it and mark the cell
        as seed_error.

    DEFAULT_CACHE_DIR: Path
        ~/.cache/skill-comparison/seeds/ - cached clones keyed by
        <slug>-<base_commit[:8]>.

Upstream deps: stdlib subprocess, shutil, pathlib, logging, os.

Downstream consumers: runner.py run_matrix (production path, before engineer
                      spawn); tests/test_seeding.py.

Failure modes:
    - SeedError("clone_failed"): git clone returned non-zero.
    - SeedError("checkout_failed"): git fetch + checkout returned non-zero.
    - SeedError("patch_failed"): git apply returned non-zero (patch rejected).
    All three cases should be caught by runner.py and recorded as
    status="seed_error" in the TSV.

Performance: First call for a repo/commit pair does a shallow clone (slow,
    ~10-60 s depending on repo size and network). Subsequent calls hit the
    cache: a local git clone --local is fast (~0.5-2 s). Cache path:
    ~/.cache/skill-comparison/seeds/<slug>-<base_commit[:8]>/

    Cache GC note: the cache directory accumulates one entry per
    (task_slug, base_commit[:8]) pair and never auto-expires. For a
    12-task corpus this is ~12 entries totalling ~500 MB (shallow clones).
    No automatic garbage-collection is implemented; this is acceptable for
    the current small corpus. If the cache grows stale (base_commit changes
    or a new corpus generation is created) remove entries manually:
        rm -rf ~/.cache/skill-comparison/seeds/
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

_LOG = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "skill-comparison" / "seeds"


class SeedError(RuntimeError):
    """Raised when fix-phase seeding fails.

    Attributes:
        step: which step failed - "clone_failed", "checkout_failed", "patch_failed".
        stderr: captured stderr from the failing subprocess.
    """

    def __init__(self, step: str, stderr: str = "") -> None:
        self.step = step
        self.stderr = stderr
        super().__init__(f"seed_fix_phase failed at step={step!r}: {stderr[:500]}")


def _run(
    cmd: list[str],
    cwd: Path,
    label: str,
    step: str,
    timeout: int = 300,
) -> None:
    """Run a subprocess command; raise SeedError(step) on non-zero return code."""
    _LOG.debug("seeding [%s]: %s", label, " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        _LOG.error(
            "seeding [%s] step=%s returned %d:\n  stdout: %s\n  stderr: %s",
            label,
            step,
            result.returncode,
            result.stdout[:300],
            result.stderr[:300],
        )
        raise SeedError(step=step, stderr=result.stderr)


def _cache_key(task_slug: str, base_commit: str) -> str:
    """Return a filesystem-safe cache key for this (slug, commit) pair."""
    return f"{task_slug}-{base_commit[:8]}"


def _is_cache_valid(cache_path: Path) -> bool:
    """Return True if cache_path is a valid, non-corrupt cloned git repo.

    An interrupted git clone may leave a .git directory behind while the
    repo is unusable (HEAD not pointing to a commit, refs incomplete, etc.).
    We probe with `git rev-parse --verify HEAD`: if that fails, the cache
    entry is corrupt. We remove the corrupt directory so the next call does
    a fresh clone.
    """
    if not (cache_path / ".git").is_dir():
        return False
    # Probe: verify HEAD is resolvable. An interrupted clone creates .git
    # but leaves HEAD unresolvable, causing all subsequent git operations to fail.
    result = subprocess.run(
        ["git", "-C", str(cache_path), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        _LOG.warning(
            "Cache at %s has .git but HEAD is unresolvable (returncode=%d). "
            "Treating as corrupt and removing.",
            cache_path,
            result.returncode,
        )
        shutil.rmtree(cache_path, ignore_errors=True)
        return False
    return True


def seed_fix_phase(
    task_slug: str,
    task_meta: dict,
    fix_dir: Path,
    tasks_root: Path,
    cache_dir: Path | None = None,
) -> dict:
    """Clone repo at base_commit into fix_dir and apply test_patch.

    Steps:
      1. Determine cache path (~/.cache/skill-comparison/seeds/<key>/).
      2. If cache miss: shallow-clone the repo and fetch/checkout base_commit.
         If cache hit: use git clone --local from the cache copy.
      3. Copy/clone into fix_dir (always a fresh copy so each cell is isolated).
      4. Apply tasks_root/<slug>/test_patch.diff with git apply.
      5. Stage and commit the patched state as "seed: test_patch applied".
         Record the resulting commit SHA for use as the engineer-diff base.

    Args:
        task_slug: slug key (e.g. "requests-3362").
        task_meta: dict from corpus.yaml for this task; must contain
                   "repo_url" and "base_commit".
        fix_dir: destination directory (must not exist; will be created).
        tasks_root: directory containing per-task subdirectories (for locating
                    test_patch.diff).
        cache_dir: override for the cache root; defaults to DEFAULT_CACHE_DIR.

    Returns:
        dict with key "seed_commit": the git SHA of the post-seeding commit.
        Callers pass this SHA to scoring so that engineer diffs are computed
        relative to the post-seeding state, not the upstream base_commit.

    Raises:
        SeedError: on clone, checkout, or patch failure.
        FileNotFoundError: if tasks_root/<slug>/test_patch.diff is missing.
        ValueError: if task_meta is missing required fields.
    """
    repo_url = task_meta.get("repo_url", "")
    base_commit = task_meta.get("base_commit", "")
    if not repo_url:
        raise ValueError(f"task_meta for {task_slug!r} missing 'repo_url'")
    if not base_commit:
        raise ValueError(f"task_meta for {task_slug!r} missing 'base_commit'")

    patch_file = tasks_root / task_slug / "test_patch.diff"
    if not patch_file.is_file():
        raise FileNotFoundError(
            f"test_patch.diff not found at {patch_file}. "
            "Run seed_corpus.py to stage the patches first."
        )

    _effective_cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
    key = _cache_key(task_slug, base_commit)
    cache_path = _effective_cache_dir / key

    # -----------------------------------------------------------------------
    # Step 1: populate cache if needed.
    # -----------------------------------------------------------------------
    if not _is_cache_valid(cache_path):
        _LOG.info("Cache miss for %s - cloning %s at %s", task_slug, repo_url, base_commit[:8])
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove a partial/corrupt cache entry if present.
        if cache_path.exists():
            shutil.rmtree(cache_path)

        # Shallow clone with no specific branch - we fetch the commit next.
        try:
            _run(
                ["git", "clone", "--depth", "1", repo_url, str(cache_path)],
                cwd=_effective_cache_dir,
                label=task_slug,
                step="clone_failed",
                timeout=600,  # large repos can take a while
            )
        except SeedError:
            shutil.rmtree(cache_path, ignore_errors=True)
            raise

        # Fetch the exact base_commit (shallow clone may not include it).
        try:
            _run(
                ["git", "fetch", "--depth", "1", "origin", base_commit],
                cwd=cache_path,
                label=task_slug,
                step="checkout_failed",
                timeout=300,
            )
            _run(
                ["git", "checkout", base_commit],
                cwd=cache_path,
                label=task_slug,
                step="checkout_failed",
                timeout=60,
            )
        except SeedError:
            shutil.rmtree(cache_path, ignore_errors=True)
            raise
    else:
        _LOG.info("Cache hit for %s (%s)", task_slug, key)

    # -----------------------------------------------------------------------
    # Step 2: copy cache into fix_dir (fresh, isolated per cell).
    # -----------------------------------------------------------------------
    fix_dir.parent.mkdir(parents=True, exist_ok=True)
    if fix_dir.exists():
        shutil.rmtree(fix_dir)

    # Use git clone --local for speed (hardlinks where possible).
    _LOG.info("Cloning local cache -> %s", fix_dir)
    try:
        _run(
            ["git", "clone", "--local", str(cache_path), str(fix_dir)],
            cwd=_effective_cache_dir,
            label=task_slug,
            step="clone_failed",
            timeout=120,
        )
    except SeedError:
        shutil.rmtree(fix_dir, ignore_errors=True)
        raise

    # Ensure HEAD is at base_commit (local clone may have moved HEAD).
    try:
        _run(
            ["git", "checkout", base_commit],
            cwd=fix_dir,
            label=task_slug,
            step="checkout_failed",
            timeout=60,
        )
    except SeedError:
        shutil.rmtree(fix_dir, ignore_errors=True)
        raise

    # -----------------------------------------------------------------------
    # Step 3: apply test_patch (introduces failing tests; NOT the fix).
    # -----------------------------------------------------------------------
    _LOG.info("Applying test_patch for %s", task_slug)
    try:
        _run(
            ["git", "apply", str(patch_file)],
            cwd=fix_dir,
            label=task_slug,
            step="patch_failed",
            timeout=60,
        )
    except SeedError:
        shutil.rmtree(fix_dir, ignore_errors=True)
        raise

    # -----------------------------------------------------------------------
    # Step 4: commit the patched state so scoring can diff against it.
    # The engineer's changes are then visible via `git diff <seed_commit>`.
    # Using a dedicated seed identity keeps "git log" clean regardless of the
    # host's git user config.
    # -----------------------------------------------------------------------
    _LOG.info("Committing seed state for %s", task_slug)
    try:
        _run(
            ["git", "add", "-A"],
            cwd=fix_dir,
            label=task_slug,
            step="patch_failed",
            timeout=30,
        )
        _run(
            [
                "git",
                "-c", "user.email=seed@local",
                "-c", "user.name=seed",
                "commit",
                "-m", "seed: test_patch applied",
            ],
            cwd=fix_dir,
            label=task_slug,
            step="patch_failed",
            timeout=30,
        )
    except SeedError:
        shutil.rmtree(fix_dir, ignore_errors=True)
        raise

    # Capture the SHA of the seed commit.
    rev_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(fix_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    seed_commit = rev_result.stdout.strip()
    if not seed_commit:
        _LOG.warning("seed_fix_phase: could not resolve HEAD SHA for %s", task_slug)
        seed_commit = ""

    _LOG.info("seed_fix_phase complete: %s -> %s (seed_commit=%s)", task_slug, fix_dir, seed_commit[:8])
    return {"seed_commit": seed_commit}
