"""
Purpose: Integration tests for evals.runner.isolator.Tier3Docker. Verifies
         the Docker-based sandbox properties required by the skill-comparison
         eval: container boots, network is denied, held-out tests are
         unreachable during the fix phase, rw and ro mounts are at distinct
         paths, and containers clean up without leaks.

         All tests are skipped if `docker` is unavailable on the test host
         (e.g. CI without Docker) or if Dockerfile.swebench is not present.
         Tests that require a built image are also individually guarded.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.isolator (Tier3Docker, make_isolator,
               Tier3Context, _DOCKERFILE_PATH, _DOCKER_IMAGE_TAG),
               subprocess, pathlib, tempfile, shutil, pytest.

Downstream consumers: pytest runner (evals/ test suite). Referenced by
                      docs/planning/p2-skill-comparison-evals/verification-gate.md
                      as QA scenario 3 evidence.

Failure modes: test isolation only. Each test uses its own Tier3Docker context
               manager; no shared mutable state. Containers are always cleaned
               up via try/finally inside the isolator __exit__.

Performance: each docker run call adds ~2-5 s cold-start overhead. Full suite
             takes ~30-60 s when the image is pre-built; longer on first build.
             Mark slow tests with @pytest.mark.slow if needed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from evals.runner.isolator import (
    Tier3Docker,
    Tier3Context,
    _DOCKERFILE_PATH,
    _DOCKER_IMAGE_TAG,
    make_isolator,
)

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    """Return True if the `docker` CLI is present and responsive."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _dockerfile_present() -> bool:
    return _DOCKERFILE_PATH.exists()


def _image_exists() -> bool:
    """Return True if the ae-eval-swebench image is already built locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", _DOCKER_IMAGE_TAG],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# Module-level skip: no Docker = skip all tests in this file.
docker_unavailable = not _docker_available()
pytestmark = pytest.mark.skipif(
    docker_unavailable,
    reason="docker CLI not available on this host",
)

# Dockerfile-level skip (separate from docker availability).
requires_dockerfile = pytest.mark.skipif(
    not _dockerfile_present(),
    reason=f"Dockerfile.swebench not found at {_DOCKERFILE_PATH}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built_image():
    """Build the Docker image once per test module, then yield the tag.

    Skips if the Dockerfile is missing. If the image already exists, reuses
    it without rebuilding (idempotent for local dev iterations).
    """
    if not _dockerfile_present():
        pytest.skip(f"Dockerfile.swebench not found at {_DOCKERFILE_PATH}")

    if not _image_exists():
        result = subprocess.run(
            [
                "docker", "build",
                "-t", _DOCKER_IMAGE_TAG,
                "-f", str(_DOCKERFILE_PATH),
                str(_DOCKERFILE_PATH.parent),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            pytest.fail(
                f"docker build failed (exit {result.returncode}):\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

    return _DOCKER_IMAGE_TAG


# ---------------------------------------------------------------------------
# Helper: run a command in a throw-away container (fix-phase layout)
# ---------------------------------------------------------------------------

def _run_in_fix_phase(
    ctx: Tier3Context,
    command: list[str],
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a command inside the container in fix-phase mount layout."""
    return Tier3Docker.run_fix_phase(ctx, command, timeout_seconds=timeout)


def _run_in_score_phase(
    ctx: Tier3Context,
    command: list[str],
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a command inside the container in score-phase mount layout."""
    return Tier3Docker.run_score_phase(ctx, command, timeout_seconds=timeout)


# ---------------------------------------------------------------------------
# Test 1: container boots and executes a trivial command
# ---------------------------------------------------------------------------

def test_container_boots(built_image):
    """Container starts and a trivial command exits 0."""
    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        result = _run_in_fix_phase(ctx, ["python", "-c", "print('hello')"])
    assert result.returncode == 0, (
        f"Container did not boot cleanly. stderr: {result.stderr!r}"
    )
    assert "hello" in result.stdout


# ---------------------------------------------------------------------------
# Test 2: --network none enforced - DNS resolution must fail
# ---------------------------------------------------------------------------

def test_network_none_dns_fails(built_image):
    """In-container DNS resolution fails when --network none is set."""
    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        # Python's socket.getaddrinfo raises socket.gaierror on DNS failure.
        result = _run_in_fix_phase(
            ctx,
            [
                "python", "-c",
                (
                    "import socket\n"
                    "try:\n"
                    "    socket.getaddrinfo('example.com', 80)\n"
                    "    print('DNS_SUCCEEDED')\n"
                    "except socket.gaierror:\n"
                    "    print('DNS_FAILED')\n"
                ),
            ],
        )
    assert result.returncode == 0
    assert "DNS_FAILED" in result.stdout, (
        f"Expected DNS to fail under --network none, got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: held-out tests unreachable during fix phase
# ---------------------------------------------------------------------------

def test_held_out_unreachable_in_fix_phase(built_image, tmp_path):
    """In-container cat of /scoring/tests/<file> fails with ENOENT or EACCES
    during the fix phase (the path is not mounted at all).

    The leakage contract: /scoring/tests must NOT be mounted during the fix
    phase. The in-container process should see ENOENT when it tries to read
    that path.
    """
    # Create a real held-out test file on the host.
    held_out_host = tmp_path / "held-out"
    held_out_host.mkdir()
    (held_out_host / "test_secret.py").write_text(
        "def test_secret(): pass\n", encoding="utf-8"
    )

    # NOTE: we do NOT pass held_out_dir to the isolator during the fix phase.
    # The isolator's run_fix_phase helper intentionally omits /scoring/tests.
    isolator = Tier3Docker(build_image=False)  # held_out_dir=None by default
    with isolator as ctx:
        # Attempt to read the held-out file inside the container.
        result = _run_in_fix_phase(
            ctx,
            [
                "python", "-c",
                (
                    "import os, sys\n"
                    "try:\n"
                    "    open('/scoring/tests/test_secret.py').read()\n"
                    "    print('LEAKED')\n"
                    "    sys.exit(0)\n"
                    "except (FileNotFoundError, PermissionError, OSError) as e:\n"
                    "    print(f'BLOCKED:{type(e).__name__}')\n"
                    "    sys.exit(0)\n"
                ),
            ],
        )

    assert result.returncode == 0
    assert "LEAKED" not in result.stdout, (
        "CRITICAL: held-out test contents were readable during the fix phase! "
        f"stdout: {result.stdout!r}"
    )
    assert "BLOCKED" in result.stdout, (
        f"Expected BLOCKED (ENOENT/EACCES) but got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 3b: same test expressed via subprocess that SHOULD fail this test
#          if we accidentally mount held-out tests rw or at the same path
# ---------------------------------------------------------------------------

def test_held_out_leakage_detection_is_real(built_image, tmp_path):
    """Verify the leakage test is not a false negative by confirming that
    if we DO mount /scoring/tests, the file IS readable. This ensures that
    test_held_out_unreachable_in_fix_phase is actually exercising the right
    thing (it would fail if we switched to score-phase mounting).
    """
    held_out_host = tmp_path / "held-out"
    held_out_host.mkdir()
    (held_out_host / "test_canary.py").write_text(
        "def test_canary(): pass\n", encoding="utf-8"
    )

    isolator = Tier3Docker(held_out_dir=held_out_host, build_image=False)
    with isolator as ctx:
        # Score phase mounts /scoring/tests - file should be readable here.
        result = _run_in_score_phase(
            ctx,
            [
                "python", "-c",
                (
                    "try:\n"
                    "    content = open('/scoring/tests/test_canary.py').read()\n"
                    "    print('READABLE:' + content[:20])\n"
                    "except Exception as e:\n"
                    "    print(f'ERROR:{e}')\n"
                ),
            ],
        )

    assert result.returncode == 0
    assert "READABLE" in result.stdout, (
        f"Score phase should be able to read held-out tests, got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: rw and ro mounts at DISTINCT paths
# ---------------------------------------------------------------------------

def test_fix_and_held_out_at_distinct_paths(built_image, tmp_path):
    """Fix-phase mount (/workspace/repo) and held-out mount (/scoring/tests)
    are at distinct in-container paths; neither is a subtree of the other.
    """
    fix_host = tmp_path / "fix"
    fix_host.mkdir()
    (fix_host / "fix_file.txt").write_text("fix content\n", encoding="utf-8")

    held_host = tmp_path / "held"
    held_host.mkdir()
    (held_host / "held_file.txt").write_text("held content\n", encoding="utf-8")

    isolator = Tier3Docker(
        fixture_repo_dir=fix_host,
        held_out_dir=held_host,
        build_image=False,
    )
    with isolator as ctx:
        # Score phase: both paths are mounted ro.
        result = _run_in_score_phase(
            ctx,
            [
                "python", "-c",
                (
                    "import os\n"
                    # Confirm the two paths are distinct.
                    "fix = '/workspace/repo'\n"
                    "held = '/scoring/tests'\n"
                    "# Paths must not overlap.\n"
                    "assert not fix.startswith(held), 'fix inside held!'\n"
                    "assert not held.startswith(fix), 'held inside fix!'\n"
                    # Confirm fix-phase content is accessible at fix path.
                    "fix_content = open(os.path.join(fix, 'fix_file.txt')).read()\n"
                    "assert 'fix content' in fix_content, f'fix content missing: {fix_content}'\n"
                    # Confirm held-out content is accessible at held path.
                    "held_content = open(os.path.join(held, 'held_file.txt')).read()\n"
                    "assert 'held content' in held_content, f'held content missing: {held_content}'\n"
                    "print('DISTINCT_OK')\n"
                ),
            ],
        )

    assert result.returncode == 0, (
        f"Distinct-paths check failed. stderr: {result.stderr!r}"
    )
    assert "DISTINCT_OK" in result.stdout


# ---------------------------------------------------------------------------
# Test 5: fix phase write succeeds; held-out tree is not writable
# ---------------------------------------------------------------------------

def test_fix_phase_is_rw(built_image):
    """The fix-phase container can write to /workspace/repo."""
    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        result = _run_in_fix_phase(
            ctx,
            [
                "python", "-c",
                (
                    "open('/workspace/repo/agent_output.txt', 'w').write('done')\n"
                    "print('WROTE_OK')\n"
                ),
            ],
        )
    assert result.returncode == 0
    assert "WROTE_OK" in result.stdout


def test_score_phase_repo_is_ro(built_image):
    """The score-phase container cannot write to /workspace/repo (ro mount)."""
    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        result = _run_in_score_phase(
            ctx,
            [
                "python", "-c",
                (
                    "try:\n"
                    "    open('/workspace/repo/should_not_write.txt', 'w').write('x')\n"
                    "    print('WRITE_SUCCEEDED')\n"
                    "except (OSError, PermissionError) as e:\n"
                    "    print(f'WRITE_BLOCKED:{type(e).__name__}')\n"
                ),
            ],
        )
    assert result.returncode == 0
    assert "WRITE_SUCCEEDED" not in result.stdout, (
        "Score phase should not be able to write to the ro fix-phase mount"
    )
    assert "WRITE_BLOCKED" in result.stdout


# ---------------------------------------------------------------------------
# Test 6: clean shutdown - no leaked containers
# ---------------------------------------------------------------------------

def test_no_leaked_containers(built_image):
    """After __exit__, no containers from this test remain running or stopped."""
    # Capture running containers before.
    def _running_containers() -> set[str]:
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"ancestor={_DOCKER_IMAGE_TAG}",
             "--format", "{{.ID}}"],
            capture_output=True, text=True, timeout=10,
        )
        return set(r.stdout.strip().split()) if r.stdout.strip() else set()

    before = _running_containers()

    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        # Run a short command so a container actually starts.
        _run_in_fix_phase(ctx, ["python", "-c", "pass"])

    after = _running_containers()

    # Any new containers that appeared should be gone (--rm handles clean exits).
    leaked = after - before
    assert not leaked, (
        f"Leaked containers after isolator exit: {leaked}. "
        "All containers with --rm should have been removed."
    )


# ---------------------------------------------------------------------------
# Test 7: make_isolator(tier=3) returns Tier3Docker
# ---------------------------------------------------------------------------

def test_make_isolator_tier3_returns_correct_type():
    """make_isolator(3) returns a Tier3Docker instance."""
    isolator = make_isolator(3, build_image=False)
    assert isinstance(isolator, Tier3Docker)
    assert isolator.tier == 3


# ---------------------------------------------------------------------------
# Test 8: Tier3Context tuple structure
# ---------------------------------------------------------------------------

def test_tier3_context_fields(built_image, tmp_path):
    """Tier3Context exposes fix_phase_dir, held_out_dir, and image_tag."""
    held = tmp_path / "held"
    held.mkdir()

    isolator = Tier3Docker(held_out_dir=held, build_image=False)
    with isolator as ctx:
        assert isinstance(ctx, Tier3Context)
        assert ctx.fix_phase_dir.exists()
        assert ctx.held_out_dir == held
        assert ctx.image_tag == _DOCKER_IMAGE_TAG
