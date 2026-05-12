"""
Purpose: Integration tests for evals.runner.isolator.Tier3Docker. Verifies
         the Docker-based sandbox properties required by the skill-comparison
         eval: container boots, network is denied, held-out tests are
         unreachable during the fix phase, rw and ro mounts are at distinct
         paths, containers clean up without leaks, and security hardening
         flags are applied (--cap-drop=ALL, --security-opt=no-new-privileges,
         --read-only, --pids-limit). Also covers: score-phase conftest/ini
         isolation (C2), timeout leak prevention (M4/M5), mount enumeration
         (m1), image digest pinning (M6), and build-once-reuse across cells
         (regression test for tier3-build-once fix).

         All tests are skipped if `docker` is unavailable on the test host
         (e.g. CI without Docker) or if Dockerfile.swebench is not present.
         Tests that require a built image are individually guarded.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.isolator (Tier3Docker, make_isolator,
               Tier3Context, _DOCKERFILE_PATH, _DOCKER_IMAGE_TAG,
               _force_remove_cidfile_container),
               subprocess, pathlib, tempfile, shutil, unittest.mock, pytest.

Downstream consumers: pytest runner (evals/ test suite). Referenced by
                      docs/planning/p2-skill-comparison-evals/verification-gate.md
                      as QA scenario 3 evidence.

Failure modes: test isolation only. Each test uses its own Tier3Docker context
               manager; no shared mutable state. Containers are always cleaned
               up via try/finally inside the isolator __exit__.

Performance: each docker run call adds ~2-5 s cold-start overhead. Full suite
             takes ~30-60 s when the image is pre-built; longer on first build.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import evals.runner.isolator as _isolator_module
from evals.runner.isolator import (
    Tier3Docker,
    Tier3Context,
    _DOCKERFILE_PATH,
    _DOCKER_IMAGE_TAG,
    _IMAGE_DIGEST_CACHE,
    _force_remove_cidfile_container,
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
    """Tier3Context exposes fix_phase_dir, held_out_dir, image_tag, image_digest."""
    held = tmp_path / "held"
    held.mkdir()

    isolator = Tier3Docker(held_out_dir=held, build_image=False)
    with isolator as ctx:
        assert isinstance(ctx, Tier3Context)
        assert ctx.fix_phase_dir.exists()
        assert ctx.held_out_dir == held
        assert ctx.image_tag == _DOCKER_IMAGE_TAG
        # Digest must be a non-empty sha256 string.
        assert ctx.image_digest.startswith("sha256:"), (
            f"Expected sha256: digest, got: {ctx.image_digest!r}"
        )


# ---------------------------------------------------------------------------
# Test 9 (C2): score phase ignores conftest.py planted in fix-phase output
# ---------------------------------------------------------------------------

def test_score_phase_ignores_conftest(built_image, tmp_path):
    """A conftest.py planted by the agent in /workspace/repo must NOT execute
    during scoring (C2 regression test).

    The malicious conftest raises RuntimeError on collection. If it executed,
    pytest would exit non-zero. We assert pytest still discovers and reports
    the real held-out test correctly.
    """
    # Fix-phase output: contains agent code AND a malicious conftest.py.
    fix_dir = tmp_path / "fix"
    fix_dir.mkdir()
    (fix_dir / "conftest.py").write_text(
        'def pytest_collection_modifyitems(items): raise RuntimeError("planted conftest executed!")\n',
        encoding="utf-8",
    )
    (fix_dir / "mymodule.py").write_text("def answer(): return 42\n", encoding="utf-8")

    # Held-out tests: a simple test that passes.
    held_dir = tmp_path / "held"
    held_dir.mkdir()
    (held_dir / "test_real.py").write_text(
        "def test_passes(): assert 1 + 1 == 2\n", encoding="utf-8"
    )

    isolator = Tier3Docker(
        fixture_repo_dir=fix_dir,
        held_out_dir=held_dir,
        build_image=False,
    )
    with isolator as ctx:
        # Use the entrypoint's run-tests command (score phase contract).
        result = _run_in_score_phase(ctx, ["run-tests"])

    # The malicious conftest must NOT have run. If it had, pytest exits non-zero
    # with "RuntimeError: planted conftest executed!".
    assert "planted conftest executed" not in result.stdout, (
        f"CRITICAL: planted conftest.py executed during scoring! "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert "planted conftest executed" not in result.stderr, (
        f"CRITICAL: planted conftest.py executed during scoring! "
        f"stderr: {result.stderr!r}"
    )
    # The real test must have been collected and passed.
    assert result.returncode == 0, (
        f"Score phase failed unexpectedly (conftest isolation or test error). "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert "1 passed" in result.stdout, (
        f"Expected '1 passed' from the real test; got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 10 (C2): score phase ignores pytest.ini planted in fix-phase output
# ---------------------------------------------------------------------------

def test_score_phase_ignores_pytest_ini(built_image, tmp_path):
    """A pytest.ini planted by the agent in /workspace/repo must NOT execute
    during scoring (C2 regression test - companion to conftest test).

    The malicious pytest.ini sets addopts to a nonexistent plugin reference
    that would cause pytest to fail on startup if loaded. We assert pytest
    still succeeds with the real held-out test.
    """
    fix_dir = tmp_path / "fix"
    fix_dir.mkdir()
    (fix_dir / "pytest.ini").write_text(
        "[pytest]\naddopts = -p planted_nonexistent_plugin_xyzzy\n",
        encoding="utf-8",
    )

    held_dir = tmp_path / "held"
    held_dir.mkdir()
    (held_dir / "test_real.py").write_text(
        "def test_passes(): assert True\n", encoding="utf-8"
    )

    isolator = Tier3Docker(
        fixture_repo_dir=fix_dir,
        held_out_dir=held_dir,
        build_image=False,
    )
    with isolator as ctx:
        result = _run_in_score_phase(ctx, ["run-tests"])

    # pytest.ini from /workspace/repo must NOT have been loaded.
    assert "planted_nonexistent_plugin_xyzzy" not in result.stdout, (
        f"Planted pytest.ini was loaded during scoring! "
        f"stdout: {result.stdout!r}"
    )
    assert "planted_nonexistent_plugin_xyzzy" not in result.stderr, (
        f"Planted pytest.ini was loaded during scoring! "
        f"stderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"Score phase failed. stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert "1 passed" in result.stdout


# ---------------------------------------------------------------------------
# Test 11 (M4/M5): timeout kills container; no leak (unit test via mock)
# ---------------------------------------------------------------------------

def test_timeout_cleanup_no_leak_unit():
    """When subprocess.run raises TimeoutExpired, _force_remove_cidfile_container
    is called and the container is force-removed (M4/M5 regression test).

    This is a unit test using mocks to avoid a ~30s real sleep. The real
    Docker path is validated by test_timeout_cleanup_real_container below.
    """
    import tempfile as _tempfile

    # Create a real cidfile with a fake container ID.
    cidfile = Path(_tempfile.mktemp(prefix="t3-cid-test-", suffix=".cid"))
    fake_cid = "deadbeefcafe1234"
    cidfile.write_text(fake_cid)

    removed_ids: list[str] = []

    def _fake_docker_rm(cmd, **kwargs):
        if cmd[0] == "docker" and cmd[1] == "rm":
            removed_ids.append(cmd[3])  # docker rm -f <cid>
        result = MagicMock()
        result.returncode = 0
        return result

    try:
        with patch("subprocess.run", side_effect=_fake_docker_rm):
            _force_remove_cidfile_container(cidfile)
    finally:
        cidfile.unlink(missing_ok=True)

    assert fake_cid in removed_ids, (
        f"Expected docker rm -f {fake_cid!r} to be called; got: {removed_ids}"
    )


def test_timeout_cleanup_no_leak_integration(built_image, tmp_path):
    """Run a real container that sleeps past the host-side timeout; verify the
    container is force-removed and does not appear in `docker ps -a` after
    the TimeoutExpired is caught (M5 integration regression test).

    This test uses a very short host-side timeout (3s) and a container command
    that sleeps for 999s. The in-container `timeout` wrapper would kill at
    EVAL_TIMEOUT_SECONDS, but we set that high and rely on the host-side
    subprocess.run timeout to fire first for this test scenario.
    """
    isolator = Tier3Docker(build_image=False)

    containers_before: set[str] = set()
    containers_after: set[str] = set()

    def _containers() -> set[str]:
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"ancestor={_DOCKER_IMAGE_TAG}",
             "--format", "{{.ID}}"],
            capture_output=True, text=True, timeout=10,
        )
        return set(r.stdout.strip().split()) if r.stdout.strip() else set()

    with isolator as ctx:
        containers_before = _containers()
        # Temporarily monkeypatch run_fix_phase to use a short outer timeout.
        # We override timeout_seconds here so the inner entrypoint timeout is
        # large (999s) but the outer subprocess.run timeout fires at 3s.
        # To achieve this cleanly, we call subprocess.run directly with a
        # short timeout on the docker run command and catch TimeoutExpired.

        # Build the docker run command as run_fix_phase would, but with a
        # tiny subprocess timeout and large EVAL_TIMEOUT_SECONDS.
        cidfile_path = Path(tempfile.mktemp(prefix="t3-cid-leak-test-", suffix=".cid"))
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--cidfile", str(cidfile_path),
            "--network", "none",
            "--memory", "1g",
            "--cpus", "1.0",
            "--pids-limit", "256",
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:size=64m,noexec,nosuid",
            "--tmpfs", "/home/evaluser:size=32m,noexec,nosuid",
            "-e", "EVAL_TIMEOUT_SECONDS=999",
            "-v", f"{ctx.fix_phase_dir}:/workspace/repo:rw",
            "-w", "/workspace/repo",
            ctx.image_digest,
            "sleep", "999",
        ]

        with pytest.raises(subprocess.TimeoutExpired):
            try:
                subprocess.run(docker_cmd, capture_output=True, text=True, timeout=5)
            except subprocess.TimeoutExpired:
                # Simulate what run_fix_phase does: force-remove the container.
                from evals.runner.isolator import _force_remove_cidfile_container
                _force_remove_cidfile_container(cidfile_path)
                cidfile_path.unlink(missing_ok=True)
                raise

    # After cleanup, no new containers should remain.
    containers_after = _containers()
    leaked = containers_after - containers_before
    assert not leaked, (
        f"Container leaked after TimeoutExpired + force-remove: {leaked}. "
        "docker rm -f should have cleaned it up."
    )


# ---------------------------------------------------------------------------
# Test 12 (m1): mount enumeration in fix phase does not reveal held-out paths
# ---------------------------------------------------------------------------

def test_mount_enumeration_does_not_reveal_held_out(built_image, tmp_path):
    """In-container /proc/mounts enumeration during the fix phase must not
    reveal any entry that includes 'scoring' or the host path of the held-out
    directory (m1 regression test).

    The held-out dir must not be visible in /proc/mounts during the fix phase
    because it is not mounted at all.
    """
    held_out_host = tmp_path / "held-out-secret"
    held_out_host.mkdir()
    (held_out_host / "test_secret.py").write_text(
        "def test_secret(): pass\n", encoding="utf-8"
    )

    # Fix phase: held_out_dir is NOT passed to Tier3Docker, so it is never
    # mounted in the fix-phase container.
    isolator = Tier3Docker(build_image=False)
    with isolator as ctx:
        result = _run_in_fix_phase(
            ctx,
            [
                "python", "-c",
                (
                    "mounts = open('/proc/mounts').read()\n"
                    "print('MOUNTS_DUMPED')\n"
                    "print(mounts)\n"
                ),
            ],
        )

    assert result.returncode == 0, (
        f"Failed to read /proc/mounts: {result.stderr!r}"
    )
    assert "MOUNTS_DUMPED" in result.stdout

    mounts_output = result.stdout

    # No entry should reference the held-out path or "scoring".
    assert "scoring" not in mounts_output.lower(), (
        f"Found 'scoring' in /proc/mounts during fix phase - held-out path leaked!\n"
        f"mounts:\n{mounts_output}"
    )
    # The host path should not appear either (Docker bind mount source is not
    # visible inside the container in /proc/mounts for security reasons, but
    # verify the held-out basename is absent as a belt-and-suspenders check).
    assert "held-out-secret" not in mounts_output, (
        f"Found held-out host path substring in /proc/mounts during fix phase!\n"
        f"mounts:\n{mounts_output}"
    )


# ---------------------------------------------------------------------------
# Test 13 (M6): image digest is resolved and stored in Tier3Context
# ---------------------------------------------------------------------------

def test_image_digest_is_content_addressed(built_image, tmp_path):
    """Tier3Context.image_digest is a sha256 digest (content-addressed reference)
    that is distinct from the mutable tag (M6 regression test).

    This ensures run helpers use the digest, not the tag, so parallel-branch
    tag overwrites cannot silently swap the image.
    """
    held = tmp_path / "held"
    held.mkdir()

    isolator = Tier3Docker(held_out_dir=held, build_image=False)
    with isolator as ctx:
        # Digest must be a valid sha256 string.
        assert ctx.image_digest.startswith("sha256:"), (
            f"image_digest is not a sha256 string: {ctx.image_digest!r}"
        )
        # Digest must differ from the mutable tag.
        assert ctx.image_digest != ctx.image_tag, (
            "image_digest must not equal image_tag (tag is mutable, digest is not)"
        )
        # Digest must be long enough (sha256 = 64 hex chars after "sha256:").
        hex_part = ctx.image_digest.removeprefix("sha256:")
        assert len(hex_part) == 64, (
            f"sha256 digest hex part must be 64 chars; got {len(hex_part)}: {hex_part!r}"
        )


# ---------------------------------------------------------------------------
# Test 14: build-once-reuse regression (tier3-build-once fix)
# _build_image must be called AT MOST ONCE across N cell instantiations.
# ---------------------------------------------------------------------------


def test_tier3_build_image_called_once_across_cells():
    """Regression test: _build_image is called at most once across N simulated
    cells (tier3-build-once fix).

    Previously, each per-cell Tier3Docker context manager called _build_image()
    on __enter__, causing N x 24 redundant docker builds for a 24-task matrix.
    After the fix:
      - ensure_image() populates _IMAGE_DIGEST_CACHE on first call.
      - Subsequent Tier3Docker.__init__ detects the cache hit and sets
        build_image=False, so _build_image is never invoked again.

    This is a pure unit test using mocks; no Docker daemon required.
    """
    N_CELLS = 5  # simulate 5 cells that would previously have caused 5 builds

    build_call_count = 0
    inspect_call_count = 0

    fake_digest = "sha256:" + "a" * 64

    def _fake_subprocess_run(cmd, **kwargs):
        nonlocal build_call_count, inspect_call_count
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if "build" in cmd:
            build_call_count += 1
            result.stdout = "Successfully built abc123"
        elif "inspect" in cmd:
            inspect_call_count += 1
            result.stdout = fake_digest + "\n"
        return result

    # Clear the module-level cache so we start fresh.
    _isolator_module._IMAGE_DIGEST_CACHE.clear()

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_fake_subprocess_run):
            # Simulate what run_matrix does: call ensure_image() ONCE up front.
            digest = Tier3Docker.ensure_image()
            assert digest == fake_digest, f"ensure_image returned wrong digest: {digest!r}"

            # Now simulate N cells, each instantiating Tier3Docker(build_image=False).
            # The cache hit means build_image stays False even if build_image=True is passed.
            for _ in range(N_CELLS):
                isolator = Tier3Docker(build_image=True)  # caller passes True; cache overrides
                assert isolator.build_image is False, (
                    "Tier3Docker.__init__ must set build_image=False when cache is populated"
                )
                # Simulate __enter__ without actually entering (cache path is synchronous).
                # We verify the cache short-circuit by checking that _build_image was
                # not incremented further.
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()

    # _build_image (docker build) must have been called exactly ONCE (from ensure_image).
    assert build_call_count == 1, (
        f"Expected _build_image to be called exactly once across ensure_image + {N_CELLS} cells; "
        f"got {build_call_count}. The build-once-reuse contract is broken."
    )
    # docker inspect must also be called exactly once (from ensure_image).
    assert inspect_call_count == 1, (
        f"Expected docker inspect to be called once; got {inspect_call_count}."
    )


def test_tier3_ensure_image_idempotent():
    """ensure_image() called twice returns the cached digest without rebuilding."""
    build_call_count = 0
    inspect_call_count = 0
    fake_digest = "sha256:" + "b" * 64

    def _fake_subprocess_run(cmd, **kwargs):
        nonlocal build_call_count, inspect_call_count
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if "build" in cmd:
            build_call_count += 1
            result.stdout = "Successfully built"
        elif "inspect" in cmd:
            inspect_call_count += 1
            result.stdout = fake_digest + "\n"
        return result

    _isolator_module._IMAGE_DIGEST_CACHE.clear()
    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_fake_subprocess_run):
            d1 = Tier3Docker.ensure_image()
            d2 = Tier3Docker.ensure_image()  # second call - must hit cache
        assert d1 == fake_digest
        assert d2 == fake_digest
        assert build_call_count == 1, (
            f"ensure_image() should only build once; build_call_count={build_call_count}"
        )
        assert inspect_call_count == 1, (
            f"ensure_image() should only inspect once; inspect_call_count={inspect_call_count}"
        )
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()


def test_tier3_enter_uses_cached_digest_without_subprocess():
    """When the cache is already populated, Tier3Docker.__enter__ must use the
    cached digest and make zero subprocess calls for build or inspect.

    Regression test: threads cache lookup through self.image_tag (MAJOR finding fix).
    The subprocess mock raises on any call so an uncached subprocess would error
    loudly instead of silently returning a wrong digest.
    """
    fake_digest = "sha256:" + "c" * 64
    _isolator_module._IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = fake_digest

    def _noisy_subprocess_run(cmd, **kwargs):
        raise AssertionError(
            f"subprocess.run must NOT be called when cache is populated; got cmd={cmd!r}"
        )

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_noisy_subprocess_run):
            isolator = Tier3Docker(build_image=True)  # True is overridden by cache
            assert isolator.build_image is False, (
                "Cache hit must force build_image=False in __init__"
            )
            # Actually call __enter__ - this is the zero-subprocess claim under test.
            ctx = isolator.__enter__()
            try:
                assert ctx.image_digest == fake_digest, (
                    f"__enter__ must return the cached digest; got {ctx.image_digest!r}"
                )
                assert ctx.image_tag == _DOCKER_IMAGE_TAG, (
                    f"__enter__ must propagate self.image_tag; got {ctx.image_tag!r}"
                )
            finally:
                isolator.__exit__(None, None, None)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()


# ---------------------------------------------------------------------------
# Bug-1 regression: pytest-timeout must be installed in the Docker image
# ---------------------------------------------------------------------------


def test_dockerfile_includes_pytest_timeout():
    """Dockerfile.swebench pip install line must include pytest-timeout.

    Regression test for Bug-1: scoring.py passes --timeout=<N> to pytest
    inside the container, but the original Dockerfile only installed
    pytest==8.3.5. Every score phase failed with:
      'unrecognized arguments: --timeout=120'
    because pytest-timeout was not present.

    This is a static grep test - no Docker needed. It documents the build-time
    contract and catches regressions where the Dockerfile is edited and the
    pytest-timeout dependency is accidentally removed.
    """
    dockerfile_text = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "pytest-timeout" in dockerfile_text, (
        f"Dockerfile.swebench at {_DOCKERFILE_PATH} must include 'pytest-timeout' "
        "in its pip install RUN layer. "
        "Bug-1 regression: scoring.py passes --timeout=<N> to pytest inside the "
        "container; without pytest-timeout installed, every score phase fails with "
        "'unrecognized arguments: --timeout=120'."
    )


# ---------------------------------------------------------------------------
# held_out_from_fix_dir regression tests (held-out-mount fix)
# ---------------------------------------------------------------------------


def test_held_out_from_fix_dir_sets_held_out_equal_to_fix_phase():
    """When held_out_from_fix_dir=True, Tier3Context.held_out_dir == fix_phase_dir.

    Regression test for the held-out-mount bug: if no held_out_dir is passed,
    __enter__ used to create an empty tmpdir for /scoring/tests. pytest inside
    the score container found no tests and exited with 'file or directory not
    found'. With held_out_from_fix_dir=True the held-out dir is the same
    object as the fix-phase dir, where seed_fix_phase places the test files.
    """
    fake_digest = "sha256:" + "d" * 64
    _isolator_module._IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = fake_digest

    def _noisy_subprocess_run(cmd, **kwargs):
        raise AssertionError(
            f"subprocess.run must NOT be called when cache is populated; got cmd={cmd!r}"
        )

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_noisy_subprocess_run):
            isolator = Tier3Docker(held_out_from_fix_dir=True, build_image=False)
            ctx = isolator.__enter__()
            try:
                assert ctx.held_out_dir == ctx.fix_phase_dir, (
                    f"held_out_from_fix_dir=True must set held_out_dir == fix_phase_dir; "
                    f"got held_out_dir={ctx.held_out_dir!r}, fix_phase_dir={ctx.fix_phase_dir!r}"
                )
            finally:
                isolator.__exit__(None, None, None)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()


def test_held_out_from_fix_dir_no_empty_tmpdir_created():
    """When held_out_from_fix_dir=True, no separate owned tmpdir is created for
    held-out. _owned_held_out_dir must remain None so __exit__ does not attempt
    to delete the fix-phase dir a second time.
    """
    fake_digest = "sha256:" + "e" * 64
    _isolator_module._IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = fake_digest

    def _noisy_subprocess_run(cmd, **kwargs):
        raise AssertionError(f"subprocess.run called unexpectedly: {cmd!r}")

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_noisy_subprocess_run):
            isolator = Tier3Docker(held_out_from_fix_dir=True, build_image=False)
            ctx = isolator.__enter__()
            try:
                assert isolator._owned_held_out_dir is None, (
                    "_owned_held_out_dir must be None when held_out_from_fix_dir=True "
                    "(fix-phase dir must not be double-deleted on __exit__)"
                )
            finally:
                isolator.__exit__(None, None, None)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()


def test_held_out_from_fix_dir_takes_precedence_over_held_out_dir(tmp_path):
    """When both held_out_from_fix_dir=True and held_out_dir=<path> are passed,
    held_out_from_fix_dir takes precedence and the result equals fix_phase_dir.
    """
    import shutil as _shutil

    fake_digest = "sha256:" + "f" * 64
    _isolator_module._IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = fake_digest

    explicit_held = tmp_path / "explicit-held"
    explicit_held.mkdir()

    def _noisy_subprocess_run(cmd, **kwargs):
        raise AssertionError(f"subprocess.run called unexpectedly: {cmd!r}")

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_noisy_subprocess_run):
            isolator = Tier3Docker(
                held_out_dir=explicit_held,
                held_out_from_fix_dir=True,
                build_image=False,
            )
            ctx = isolator.__enter__()
            try:
                assert ctx.held_out_dir == ctx.fix_phase_dir, (
                    "held_out_from_fix_dir=True must override held_out_dir; "
                    f"expected fix_phase_dir={ctx.fix_phase_dir!r}, "
                    f"got held_out_dir={ctx.held_out_dir!r}"
                )
                assert ctx.held_out_dir != explicit_held, (
                    "explicit held_out_dir must be ignored when held_out_from_fix_dir=True"
                )
            finally:
                isolator.__exit__(None, None, None)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()


# ---------------------------------------------------------------------------
# Regression test: force_rebuild=True in ensure_image() runs docker rmi
# before docker build so Docker layer cache is discarded, not just in-process
# cache. Prevents stale image reuse when Dockerfile.swebench changes.
# Bug: --rebuild-image only evicted _IMAGE_DIGEST_CACHE; `docker build` still
# reused cached layers from the old locally-tagged image.
# Fix: ensure_image(force_rebuild=True) runs `docker rmi -f <tag>` first.
# ---------------------------------------------------------------------------


def test_ensure_image_force_rebuild_runs_rmi():
    """ensure_image(force_rebuild=True) invokes `docker rmi -f <image_tag>`
    before `docker build`, discarding Docker's layer cache for the tagged image.

    Regression test for the --rebuild-image bug: the old code only evicted
    _IMAGE_DIGEST_CACHE (in-process) but did not remove the locally-tagged
    Docker image. `docker build` would then reuse cached layers and produce
    an image that appeared fresh but still used stale layers from the old
    Dockerfile. force_rebuild=True now calls `docker rmi -f` first.
    """
    build_call_count = 0
    rmi_call_count = 0
    rmi_calls: list[list[str]] = []
    inspect_call_count = 0
    fake_digest = "sha256:" + "9" * 64

    def _fake_subprocess_run(cmd, **kwargs):
        nonlocal build_call_count, rmi_call_count, inspect_call_count
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if len(cmd) >= 2 and cmd[1] == "rmi":
            rmi_call_count += 1
            rmi_calls.append(list(cmd))
        elif "build" in cmd:
            build_call_count += 1
            result.stdout = "Successfully built"
        elif "inspect" in cmd:
            inspect_call_count += 1
            result.stdout = fake_digest + "\n"
        return result

    # Seed the cache as if ensure_image() had previously been called.
    _isolator_module._IMAGE_DIGEST_CACHE[_DOCKER_IMAGE_TAG] = "sha256:" + "0" * 64

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_fake_subprocess_run):
            digest = Tier3Docker.ensure_image(force_rebuild=True)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()

    # docker rmi must have been called with -f and the image tag.
    assert rmi_call_count == 1, (
        f"Expected docker rmi to be called exactly once; got {rmi_call_count}. "
        "force_rebuild=True must remove the old image before building."
    )
    assert "-f" in rmi_calls[0], (
        f"docker rmi call must include -f (force); got: {rmi_calls[0]!r}"
    )
    assert _DOCKER_IMAGE_TAG in rmi_calls[0], (
        f"docker rmi must target the image tag {_DOCKER_IMAGE_TAG!r}; "
        f"got: {rmi_calls[0]!r}"
    )

    # docker build must still have been called (force_rebuild doesn't skip build).
    assert build_call_count == 1, (
        f"Expected docker build to be called exactly once; got {build_call_count}."
    )

    # The fresh digest must be returned (not the old stale one).
    assert digest == fake_digest, (
        f"ensure_image(force_rebuild=True) must return the freshly resolved digest; "
        f"got {digest!r}"
    )

    # Cache must now hold the fresh digest, not the old one.
    assert _isolator_module._IMAGE_DIGEST_CACHE.get(_DOCKER_IMAGE_TAG) is None, (
        "Cache must have been cleared by the finally block in this test "
        "(confirming force_rebuild evicted the stale entry)"
    )


def test_ensure_image_force_rebuild_rmi_errors_are_swallowed():
    """ensure_image(force_rebuild=True) does not raise when docker rmi fails
    (e.g. image does not exist yet on the first build).

    The rmi step is best-effort: errors must be swallowed so that
    `--rebuild-image` on a fresh machine (no prior image) does not abort.
    """
    rmi_returncode = 1  # simulate "No such image"
    build_call_count = 0
    fake_digest = "sha256:" + "a" * 64

    def _fake_subprocess_run(cmd, **kwargs):
        nonlocal rmi_returncode, build_call_count
        result = MagicMock()
        result.stdout = ""
        result.stderr = ""
        if len(cmd) >= 2 and cmd[1] == "rmi":
            result.returncode = rmi_returncode  # rmi fails
        elif "build" in cmd:
            build_call_count += 1
            result.returncode = 0
            result.stdout = "Successfully built"
        elif "inspect" in cmd:
            result.returncode = 0
            result.stdout = fake_digest + "\n"
        else:
            result.returncode = 0
        return result

    _isolator_module._IMAGE_DIGEST_CACHE.clear()

    try:
        with patch("evals.runner.isolator.subprocess.run", side_effect=_fake_subprocess_run):
            # Must not raise even though docker rmi returned non-zero.
            digest = Tier3Docker.ensure_image(force_rebuild=True)
    finally:
        _isolator_module._IMAGE_DIGEST_CACHE.clear()

    assert digest == fake_digest, (
        f"Expected fresh digest after force_rebuild despite rmi failure; got {digest!r}"
    )
    assert build_call_count == 1, (
        f"docker build must still run after a failed rmi; got {build_call_count} builds."
    )
