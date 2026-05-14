"""
Purpose: Pre-flight smoke check for the skill-comparison eval harness.

Validates the scoring infrastructure for each task BEFORE running expensive
LLM-based evaluations. Seeds each task's repo, runs the held-out tests against
the unmodified base commit, and classifies the result.

CLI:
    python evals/skill-comparison/preflight.py \
        --tasks-yaml evals/skill-comparison/tasks/corpus.yaml \
        [--tasks astropy-12907 sphinx-7686] \
        [--tier3 auto|off] \
        [--rebuild-image] \
        [--timeout 120] \
        [--json]

Returns non-zero exit code if any task is not ``ok``.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyyaml is required; install with: pip install pyyaml") from exc

from scoring import _run_pytest_local, _run_pytest_tier3
from seeding import SeedError, seed_fix_phase

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PreflightResult:
    """Result of preflighting one task."""

    task_slug: str
    status: str  # "ok", "seed_error", "infra_fail", "unexpected_pass"
    returncode: int = -1
    pytest_output: str = ""
    seed_error: str = ""
    diagnostics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Infrastructure error detection
# ---------------------------------------------------------------------------

_INFRA_PATTERNS = [
    "ImportError",
    "ModuleNotFoundError",
    "pytest.UsageError",
    "unrecognized arguments",
    "error:",
]


def _is_infra_failure(returncode: int, output: str) -> bool:
    """Return True if pytest output signals an infrastructure failure.

    When returncode == 1 and the output contains ``FAILED`` lines, pytest
    successfully collected and executed tests — this is an expected test
    failure, not an infrastructure error. Collection-only errors (no FAILED
    lines) are flagged as infrastructure failures.
    """
    if returncode not in (0, 1):
        return True
    output_lower = output.lower()
    # If pytest collected and ran tests (FAILED lines), it's an expected
    # test failure even if the traceback contains ImportError etc.
    if returncode == 1 and (
        output_lower.startswith("failed ") or " failed " in output_lower
    ):
        return False
    for pattern in _INFRA_PATTERNS:
        if pattern.lower() in output_lower:
            return True
    return False


def classify_status(returncode: int, output: str) -> str:
    """Classify a pytest run result into a preflight status.

    - ``infra_fail`` — pytest failed with infrastructure error.
    - ``unexpected_pass`` — pytest exited 0 (all tests passed on base commit).
    - ``ok`` — pytest exited with test failures (expected).
    """
    if _is_infra_failure(returncode, output):
        return "infra_fail"
    if returncode == 0:
        return "unexpected_pass"
    return "ok"


# ---------------------------------------------------------------------------
# Docker probe
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Return True if the Docker CLI is functional."""
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Per-task check
# ---------------------------------------------------------------------------


def check_task(
    task_slug: str,
    task_meta: dict,
    tasks_root: Path,
    tier3: bool,
    timeout: int,
    rebuild_image: bool,
) -> PreflightResult:
    """Run the preflight check for a single task.

    Args:
        task_slug: corpus key (e.g. "django-11039").
        task_meta: dict from corpus.yaml for this task.
        tasks_root: directory containing per-task subdirectories.
        tier3: whether to run pytest inside the Tier 3 Docker container.
        timeout: pytest wall-clock budget in seconds.
        rebuild_image: whether to force-rebuild the Tier 3 image.

    Returns:
        PreflightResult with status and diagnostics.
    """
    _LOG.info("Preflight: %s (tier3=%s)", task_slug, tier3)

    tier3_instance = None
    tier3_ctx = None
    non_tier3_fix_dir: Optional[Path] = None

    # Derive image tag from per-task dockerfile (same logic as runner.py).
    # Resolve tasks_root so the path computation works regardless of whether
    # tasks_root is relative (e.g. "tasks/" -> "." parent) or absolute.
    _dockerfile_dir = tasks_root.resolve().parent.parent / "runner"
    _default_image_tag = "ae-eval-swebench:latest"

    def _derive_image_tag(dockerfile_name: str) -> str:
        if dockerfile_name == "Dockerfile.swebench":
            return _default_image_tag
        prefix = "Dockerfile.swebench-"
        if dockerfile_name.startswith(prefix):
            suffix = dockerfile_name[len(prefix):]
            return f"ae-eval-swebench:{suffix}"
        return f"ae-eval-swebench:{dockerfile_name.replace('.', '-')}"

    dockerfile_name = task_meta.get("dockerfile", "Dockerfile.swebench")
    image_tag = _derive_image_tag(dockerfile_name)

    try:
        if tier3:
            from evals.runner.isolator import Tier3Docker

            dockerfile_path = _dockerfile_dir / dockerfile_name
            Tier3Docker.ensure_image(
                image_tag=image_tag,
                dockerfile=dockerfile_path,
                force_rebuild=rebuild_image,
            )
            tier3_instance = Tier3Docker(
                fixture_repo_dir=None,
                held_out_dir=None,
                build_image=False,
                timeout_seconds=timeout * 2,
                held_out_from_fix_dir=True,
                image_tag=image_tag,
            )
            tier3_ctx = tier3_instance.__enter__()
            fix_dir = tier3_ctx.fix_phase_dir
        else:
            fix_dir = Path(tempfile.mkdtemp(prefix=f"preflight-{task_slug}-"))
            non_tier3_fix_dir = fix_dir

        # Seed the repo at base_commit and apply test_patch.
        try:
            seed_result = seed_fix_phase(
                task_slug=task_slug,
                task_meta=task_meta,
                fix_dir=fix_dir,
                tasks_root=tasks_root,
            )
            seed_commit = seed_result.get("seed_commit", "")
        except SeedError as exc:
            _LOG.error("Preflight seed error for %s: %s", task_slug, exc)
            return PreflightResult(
                task_slug=task_slug,
                status="seed_error",
                seed_error=str(exc),
                diagnostics={"step": exc.step, "stderr": exc.stderr[:500]},
            )
        except (FileNotFoundError, ValueError) as exc:
            _LOG.error("Preflight seed pre-check failed for %s: %s", task_slug, exc)
            return PreflightResult(
                task_slug=task_slug,
                status="seed_error",
                seed_error=str(exc),
                diagnostics={"error_type": type(exc).__name__},
            )

        # Post-seed commands (e.g. C-extension builds).
        # In Tier3 mode, commands run inside the container so cross-platform
        # builds work; in non-Tier3 mode they run on the host.
        _post_seed_cmds = task_meta.get("post_seed_commands")
        if _post_seed_cmds:
            for _cmd in _post_seed_cmds:
                _LOG.info("Preflight post-seed command for %s: %s", task_slug, _cmd)
                if tier3_ctx is not None:
                    _ps_result = Tier3Docker.run_fix_phase(
                        ctx=tier3_ctx,
                        command=["sh", "-c", _cmd],
                        timeout_seconds=300,
                    )
                else:
                    _ps_result = subprocess.run(
                        _cmd,
                        shell=True,
                        cwd=fix_dir,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                if _ps_result.returncode != 0:
                    _LOG.error(
                        "Preflight post-seed command failed for %s: %s\nstderr: %s",
                        task_slug, _cmd, _ps_result.stderr,
                    )
                    return PreflightResult(
                        task_slug=task_slug,
                        status="seed_error",
                        seed_error=f"post_seed_command failed: {_cmd}",
                        diagnostics={
                            "cmd": _cmd,
                            "stderr": _ps_result.stderr[:500],
                            "returncode": _ps_result.returncode,
                        },
                    )

        # Run held-out pytest against the unmodified base commit.
        fail_to_pass = task_meta.get("fail_to_pass") or []
        if tier3_ctx is not None:
            try:
                returncode, pytest_out = _run_pytest_tier3(
                    tier3_ctx, timeout, fail_to_pass=fail_to_pass
                )
            except subprocess.TimeoutExpired:
                _LOG.warning("Preflight timeout for %s (tier3)", task_slug)
                return PreflightResult(
                    task_slug=task_slug,
                    status="infra_fail",
                    returncode=-1,
                    pytest_output="pytest timed out",
                    diagnostics={
                        "seed_commit": seed_commit,
                        "timeout": timeout,
                        "tier3": tier3,
                        "error": "TimeoutExpired",
                    },
                )
        else:
            # test_patch was applied to fix_dir, so held-out tests live there.
            returncode, pytest_out = _run_pytest_local(
                held_out_dir=fix_dir,
                fix_phase_dir=fix_dir,
                timeout=timeout,
                fail_to_pass=fail_to_pass,
            )

        status = classify_status(returncode, pytest_out)

        return PreflightResult(
            task_slug=task_slug,
            status=status,
            returncode=returncode,
            pytest_output=pytest_out,
            diagnostics={
                "seed_commit": seed_commit,
                "timeout": timeout,
                "tier3": tier3,
            },
        )

    finally:
        if tier3_instance is not None:
            tier3_instance.__exit__(None, None, None)
        if non_tier3_fix_dir is not None:
            shutil.rmtree(non_tier3_fix_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_table(results: list[PreflightResult]) -> str:
    """Return a human-readable table of preflight results."""
    lines: list[str] = []
    lines.append("-" * 70)
    lines.append(f"{'Task':<25} {'Status':<18} {'RC':>4}  {'Notes'}")
    lines.append("-" * 70)
    for r in results:
        note = ""
        if r.status == "seed_error":
            note = r.seed_error[:50]
        elif r.status == "infra_fail":
            note = "infrastructure error"
        elif r.status == "unexpected_pass":
            note = "tests pass on base commit"
        lines.append(f"{r.task_slug:<25} {r.status:<18} {r.returncode:>4}  {note}")
    lines.append("-" * 70)
    ok_count = sum(1 for r in results if r.status == "ok")
    lines.append(f"Summary: {ok_count}/{len(results)} tasks ok")
    return "\n".join(lines)


def _format_json(results: list[PreflightResult]) -> str:
    """Return a JSON-serializable report."""
    payload = [
        {
            "task_slug": r.task_slug,
            "status": r.status,
            "returncode": r.returncode,
            "seed_error": r.seed_error,
            "pytest_output": r.pytest_output,
            "diagnostics": r.diagnostics,
        }
        for r in results
    ]
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pre-flight smoke check for skill-comparison eval harness.",
    )
    parser.add_argument(
        "--tasks-yaml",
        required=True,
        type=Path,
        help="Path to corpus YAML file (e.g. tasks/corpus.yaml).",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=None,
        help="Specific task slugs to check (default: all tasks in YAML).",
    )
    parser.add_argument(
        "--tier3",
        choices=["auto", "off"],
        default="auto",
        help="Tier 3 Docker mode: 'auto' uses Docker if available, 'off' skips it.",
    )
    parser.add_argument(
        "--rebuild-image",
        action="store_true",
        help="Force rebuild the Tier 3 Docker image before running.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Pytest wall-clock timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of a human-readable table.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.tasks_yaml.exists():
        print(f"ERROR: tasks-yaml not found: {args.tasks_yaml}", file=sys.stderr)
        return 2

    corpus = yaml.safe_load(args.tasks_yaml.read_text(encoding="utf-8"))
    tasks = corpus.get("tasks", {})
    tasks_root = args.tasks_yaml.parent.resolve()

    task_slugs = args.tasks if args.tasks else list(tasks.keys())

    # Validate requested tasks exist.
    unknown = [s for s in task_slugs if s not in tasks]
    if unknown:
        print(f"ERROR: unknown task(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    use_tier3 = (args.tier3 == "auto") and _docker_available()
    if args.tier3 == "auto" and not use_tier3:
        _LOG.info("Docker unavailable; falling back to tier3=off")

    results: list[PreflightResult] = []
    for slug in task_slugs:
        result = check_task(
            task_slug=slug,
            task_meta=tasks[slug],
            tasks_root=tasks_root,
            tier3=use_tier3,
            timeout=args.timeout,
            rebuild_image=args.rebuild_image,
        )
        results.append(result)

    if args.json:
        print(_format_json(results))
    else:
        print(_format_table(results))

    all_ok = all(r.status == "ok" for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
