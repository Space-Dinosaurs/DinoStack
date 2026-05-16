"""
Purpose: Orchestrate the 8-condition skill-comparison eval matrix. For each
         (task, condition, replicate) cell: materialise the condition config,
         build the agent payload, spawn the Tier 3 Docker isolator, capture
         the transcript, run scoring, and append one row to the TSV ledger.
         Enforces per-matrix USD / token / wall-clock budget ceilings
         (BudgetExceeded exit-3 pattern from evals/icl_vs_orchestration/).

Public API:
    run_matrix(
        tasks_yaml: Path,
        specs_dir: Path | None,
        results_tsv: Path,
        content_root: Path,
        n_replicates: int = 3,
        n_replicates_methodology: int = 5,
        max_usd: float = 250.0,
        max_tokens: int = 75_000_000,
        max_wall_seconds: float = 43200.0,
        dry_run: bool = False,
        conditions: list[str] | None = None,
        tier3_mode: str = "auto",
        tasks_filter: list[str] | None = None,
        max_cells: int | None = None,
        rebuild_image: bool = False,
    ) -> RunReport

    RunReport (dataclass):
        rows_written: int
        budget_breached: bool
        partial: bool
        tsv_path: Path
        error: str | None

    CONDITION_LABELS (list[str]) - the canonical 8-condition names.

Upstream deps: stdlib pathlib, time, csv, json, dataclasses, sys, logging,
               tempfile, shutil.
               pyyaml (project-standard dep).
               evals.runner.invoker (invoke_run, build_two_level_prompt).
               evals.runner.isolator (Tier3Docker, make_isolator).
               evals.skill-comparison.ae_rules_payload (build_payload).
               evals.skill-comparison.config_discovery (discover_configs).
               evals.skill-comparison.scoring (score_cell).
               evals.skill-comparison.seeding (seed_fix_phase, SeedError).
               evals.icl_vs_orchestration.cost_gate (CostGate, BudgetExceeded).

Build-once contract: when tier3_mode='auto' and not dry_run, run_matrix calls
Tier3Docker.ensure_image() ONCE before the cell loop. Per-cell Tier3Docker(...)
instantiations pass build_image=False. The module-level _IMAGE_DIGEST_CACHE in
isolator.py ensures the build subprocess is never invoked more than once per
process, even if build_image=True were passed accidentally.
When rebuild_image=True, ensure_image(force_rebuild=True) is called, which runs
`docker rmi -f` before `docker build` to discard Docker's layer cache and force
a fully clean rebuild. This is necessary when Dockerfile.swebench has changed
but the locally-tagged image is stale - evicting only the in-process digest
cache was insufficient because `docker build` would still reuse cached layers.

Transcript persistence: every cell persists the engineer CLI stdout+stderr to
<results_tsv_dir>/transcripts/<task_slug>__<condition>__rep<N>.log.  On
cli_exit_* status, the transcript path is logged in diagnostics_json and the
last 500 chars are printed to stderr for quick post-mortem without opening the
file.

Downstream consumers: CLI / scripts; evals/skill-comparison/tests/test_runner.py.

Failure modes: BudgetExceeded halts the matrix and writes a partial report
               (exit code 3 when run as __main__). Individual cell failures
               (CLI timeout, docker error) are captured in the TSV row's
               status field and do not abort the matrix. Wall-clock ceiling
               is checked between cells; a breach halts with partial=True.

Performance: dominated by the Claude CLI calls (~seconds per cell). TSV
             append is O(1). Total matrix: ~312 cells at ~30-300 s each.
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyyaml is required; install with: pip install pyyaml") from exc

# Module-level import so tests can patch `runner.score_cell` cleanly.
from scoring import ScoringResult, score_cell  # noqa: E402

# Module-level import so tests can patch `runner.seed_fix_phase` cleanly.
from seeding import SeedError, seed_fix_phase  # noqa: E402

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONDITION_LABELS_CLAUDE: list[str] = [
    "baseline",
    "ae-rules-injected",
    "engineer-direct",
    "architect-direct",
    "investigator-direct",
    "debugger-direct",
    "skeptic-direct",
    "qa-engineer-direct",
]

CONDITION_LABELS_KIMI: list[str] = [
    "baseline",
    "ae-skill",
    "coder-direct",
    "explore-direct",
    "plan-direct",
]

# Backward compat: default to Claude conditions.
CONDITION_LABELS: list[str] = CONDITION_LABELS_CLAUDE

# Conditions that route via named-agent direct spawn (two-level Task/Agent).
_AGENT_CONDITIONS_CLAUDE: dict[str, str] = {
    "engineer-direct": "engineer",
    "architect-direct": "architect",
    "investigator-direct": "investigator",
    "debugger-direct": "debugger",
    "skeptic-direct": "skeptic",
    "qa-engineer-direct": "qa-engineer",
}

_AGENT_CONDITIONS_KIMI: dict[str, str] = {
    "coder-direct": "coder",
    "explore-direct": "explore",
    "plan-direct": "plan",
}

# Backward compat: default to Claude agent mapping.
_AGENT_CONDITIONS: dict[str, str] = _AGENT_CONDITIONS_CLAUDE


def _agent_conditions_for_backend(backend: str) -> dict[str, str]:
    if backend == "kimi":
        return _AGENT_CONDITIONS_KIMI
    return _AGENT_CONDITIONS_CLAUDE


def _condition_labels_for_backend(backend: str) -> list[str]:
    if backend == "kimi":
        return CONDITION_LABELS_KIMI
    return CONDITION_LABELS_CLAUDE


def _methodology_pair_for_backend(backend: str) -> tuple[str, ...]:
    if backend == "kimi":
        return ("baseline", "ae-skill")
    return ("baseline", "ae-rules-injected")

# Per-task pytest timeout (Brief: <120 s held-out test budget).
_PYTEST_TIMEOUT_SECONDS = 120

# TSV schema for the skill-comparison ledger.
_TSV_HEADER: tuple[str, ...] = (
    "task_slug",
    "condition",
    "replicate",
    "status",
    "pass_fail",
    "score_primary",
    "lines_touched",
    "files_touched",
    "scope_creep_flag",
    "held_out_failures",
    "cost_usd",
    "tokens_input",
    "tokens_output",
    "latency_ms",
    "invocation_mode",
    "diagnostics_json",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RunReport:
    """Summary returned by run_matrix."""

    rows_written: int = 0
    budget_breached: bool = False
    partial: bool = False
    tsv_path: Optional[Path] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# TSV helpers
# ---------------------------------------------------------------------------


def _ensure_tsv_header(path: Path) -> None:
    """Write header to path if path does not exist or is empty."""
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(_TSV_HEADER)


def _append_tsv_row(path: Path, row: dict) -> None:
    """Append one row to the TSV ledger (append mode, no header write)."""
    out: list[str] = []
    for col in _TSV_HEADER:
        val = row.get(col, "")
        if col == "diagnostics_json" and not isinstance(val, str):
            val = json.dumps(val, sort_keys=True, separators=(",", ":"))
        out.append(str(val) if val is not None else "")
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(out)


# ---------------------------------------------------------------------------
# Task corpus loading
# ---------------------------------------------------------------------------


def _load_tasks(tasks_yaml: Path) -> dict:
    """Load corpus.yaml and return the tasks sub-dict."""
    with tasks_yaml.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError(f"corpus.yaml at {tasks_yaml} has no 'tasks' mapping")
    return tasks


# ---------------------------------------------------------------------------
# Condition materialisation helpers
# ---------------------------------------------------------------------------


def _build_fix_prompt(task_slug: str, task_meta: dict) -> str:
    """Build the engineer prompt for one task cell."""
    problem = task_meta.get("problem_summary", f"Fix the bug in task {task_slug}.")
    repo_url = task_meta.get("repo_url", "")
    base_commit = task_meta.get("base_commit", "")
    return (
        f"You are given a Python repository bug to fix.\n\n"
        f"Task: {task_slug}\n"
        f"Problem: {problem.strip()}\n"
        f"Repository: {repo_url}\n"
        f"Base commit: {base_commit}\n\n"
        "Reproduce the failing test(s), identify the root cause, and apply the "
        "minimal patch that makes the failing tests pass without breaking other "
        "tests. Output your patch as a unified git diff fenced in a ```diff block."
    )


def _run_cell(
    task_slug: str,
    task_meta: dict,
    condition: str,
    replicate: int,
    ae_payload: Optional[str],
    dry_run: bool,
    worktree: Optional[Path] = None,
    backend: str = "claude",
) -> dict:
    """Run one (task, condition, replicate) cell and return a raw result dict.

    When dry_run=True, skips the actual CLI invocation and returns a canned
    transcript for testing purposes.

    Args:
        worktree: the fix-phase directory to run the CLI in. Defaults to
                  Path(".") for backward compat; in production this is the
                  Tier3Context.fix_phase_dir seeded with the task's base repo.
        backend: "claude" (default) or "kimi".

    Returns a dict with keys matching the invoker's run record plus extra
    fields used for TSV row construction.
    """
    from evals.runner.invoker import invoke_run  # local import for testability

    prompt = _build_fix_prompt(task_slug, task_meta)

    if dry_run:
        # Return a canned transcript used in unit tests.
        return {
            "final_text": (
                "Analysed the bug. Here is the fix.\n\n"
                "```diff\n"
                "diff --git a/django/core/management/commands/sqlmigrate.py "
                "b/django/core/management/commands/sqlmigrate.py\n"
                "--- a/django/core/management/commands/sqlmigrate.py\n"
                "+++ b/django/core/management/commands/sqlmigrate.py\n"
                "@@ -1 +1 @@\n"
                "-old line\n"
                "+new line\n"
                "```"
            ),
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "latency_ms": 0,
            "invocation_mode": "dry-run",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
        }

    agent_conditions = _agent_conditions_for_backend(backend)
    agent_name: Optional[str] = agent_conditions.get(condition)
    # ae-rules-injected (Claude): inject the full AE methodology payload as the
    # system prompt so the model runs with the complete protocol context.
    # Kimi has no --append-system-prompt equivalent, so system_prompt is None.
    if backend == "kimi":
        system_prompt: Optional[str] = None
    else:
        system_prompt = ae_payload if condition == "ae-rules-injected" else None

    effective_worktree = worktree if worktree is not None else Path(".")

    # For per-agent conditions, the two-level Task/Agent wrapper is built by invoker.
    # For baseline and methodology conditions, agent_name is None (conductor runs directly).
    result = invoke_run(
        prompt=prompt,
        worktree=effective_worktree,
        timeout_seconds=_PYTEST_TIMEOUT_SECONDS * 2,  # give engineer 240s
        agent_name=agent_name,
        mode="agent",
        system_prompt=system_prompt,
        backend=backend,
    )
    return result


# ---------------------------------------------------------------------------
# Core matrix loop
# ---------------------------------------------------------------------------


def _load_completed_cells(results_tsv: Path) -> set[tuple[str, str, int]]:
    """Read the TSV and return the set of (task_slug, condition, replicate) already done.

    Used for resume semantics: cells already present are skipped unless --force.
    """
    if not results_tsv.exists() or results_tsv.stat().st_size == 0:
        return set()
    completed: set[tuple[str, str, int]] = set()
    with results_tsv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            try:
                completed.add((
                    row["task_slug"],
                    row["condition"],
                    int(row["replicate"]),
                ))
            except (KeyError, ValueError):
                continue  # malformed row; skip
    return completed


def run_matrix(
    tasks_yaml: Path,
    specs_dir: Optional[Path] = None,
    results_tsv: Optional[Path] = None,
    content_root: Optional[Path] = None,
    n_replicates: int = 3,
    n_replicates_methodology: int = 5,
    max_usd: float = 250.0,
    max_tokens: int = 75_000_000,
    max_wall_seconds: float = 43200.0,
    dry_run: bool = False,
    conditions: Optional[list[str]] = None,
    tier3_mode: str = "auto",
    force: bool = False,
    tasks_filter: Optional[list[str]] = None,
    max_cells: Optional[int] = None,
    rebuild_image: bool = False,
    backend: str = "claude",
) -> RunReport:
    """Orchestrate the skill-comparison eval matrix.

    For each (task, condition, replicate) cell:
      1. Skip if already present in TSV (resume semantics; override with force=True).
      2. Materialise the condition config (ae-rules payload for ae-rules-injected,
         agent name for per-agent conditions, nothing for baseline).
      3. In production (tier3_mode='auto', not dry_run): instantiate Tier3Docker
         per task to provide isolated fix and score phases.
      4. Spawn the engineer run (via Tier 3 Docker unless dry_run=True or
         tier3_mode='off').
      5. Score the result (in-container via Tier3Docker.run_score_phase when
         tier3_ctx is provided, else local subprocess).
      6. Append one row to the TSV ledger.

    Budget ceilings (USD, tokens, wall-clock) are checked between cells.
    BudgetExceeded halts with partial=True; the TSV contains results so far.

    Args:
        tasks_yaml: path to evals/skill-comparison/tasks/corpus.yaml.
        specs_dir: directory of condition YAML specs (optional; used for
                   content_glob cache validation).
        results_tsv: path for the output TSV. Defaults to
                     evals/skill-comparison/results/skill-comparison.tsv.
        content_root: path to content/ directory (for ae-rules-injected payload).
                      Defaults to <repo_root>/content/.
        n_replicates: replicates per cell (default 3).
        n_replicates_methodology: replicates for the methodology pair
                                   (default 5; this is the headline pair).
        max_usd: global USD ceiling (default 250).
        max_tokens: global token ceiling (default 75 M).
        max_wall_seconds: global wall-clock ceiling (default 12 h).
        dry_run: if True, skip actual CLI calls and return canned results.
                 Implies tier3_mode='off'.
        conditions: subset of condition labels to run (None = all for backend).
        tier3_mode: "auto" (default) - instantiate Tier3Docker in production
                    (i.e. when not dry_run); "off" - skip Tier3, run local
                    subprocess for both fix and score phases (for dry-run /
                    unit tests).
        force: if True, re-run cells already present in the TSV (no resume skip).
        tasks_filter: optional list of task slugs (keys from corpus.yaml) to
                      include. If None or empty, all tasks run. An unrecognised
                      slug raises ValueError before any cell is executed.
        max_cells: hard stop after writing this many rows to the TSV (excluding
                   the header). Only rows written in this invocation count
                   toward the ceiling - resume-skipped pre-existing rows do NOT
                   count. This means ``--max-cells 5`` will write up to 5 new
                   rows regardless of how many already exist in the TSV. If
                   None, no ceiling. When both tasks_filter and max_cells are
                   supplied, whichever limit is reached first wins. When
                   max_cells is reached, report.partial is set to True (mirrors
                   the wall-clock ceiling behavior).
        rebuild_image: if True, evict the cached image digest from
                       _IMAGE_DIGEST_CACHE before calling ensure_image(), forcing
                       a fresh docker build. Useful when Dockerfile.swebench has
                       changed and the locally-tagged image is stale. Has no
                       effect when tier3_mode='off' or dry_run=True.
        backend: "claude" (default) or "kimi". Selects the CLI backend and
                 condition matrix.

    Returns:
        RunReport with summary stats.
    """
    _REPO_ROOT = Path(__file__).resolve().parent.parent.parent

    if results_tsv is None:
        results_tsv = (
            Path(__file__).parent / "results" / "skill-comparison.tsv"
        )
    if content_root is None:
        content_root = _REPO_ROOT / "content"

    # Transcript directory: <results_tsv_dir>/transcripts/
    # Each cell writes its engineer CLI output here for post-mortem.
    _transcript_dir = results_tsv.parent / "transcripts"
    _transcript_dir.mkdir(parents=True, exist_ok=True)

    tasks = _load_tasks(tasks_yaml)

    # Apply tasks_filter: if provided and non-empty, restrict to named slugs.
    if tasks_filter:
        unknown = [s for s in tasks_filter if s not in tasks]
        if unknown:
            raise ValueError(
                f"Unknown task slug(s) in --tasks filter: {unknown}. "
                f"Valid slugs: {sorted(tasks.keys())}"
            )
        tasks = {slug: tasks[slug] for slug in tasks_filter}

    default_conditions = _condition_labels_for_backend(backend)
    active_conditions = conditions if conditions is not None else default_conditions

    # Resolve effective tier3 mode. dry_run forces Tier3 off.
    use_tier3 = (tier3_mode == "auto") and (not dry_run)

    # Build ae-rules payload once (reused for every ae-rules-injected cell).
    # Kimi backend has no --append-system-prompt equivalent, so skip payload build.
    ae_payload: Optional[str] = None
    methodology_pair = _methodology_pair_for_backend(backend)
    if backend != "kimi" and "ae-rules-injected" in active_conditions and not dry_run:
        from ae_rules_payload import build_payload
        ae_payload = build_payload(content_root)

    # Cost / budget gate.
    from evals.icl_vs_orchestration.cost_gate import BudgetExceeded, CostGate

    run_dir = results_tsv.parent / ".run_state"
    cost_gate = CostGate(
        run_dir=run_dir,
        max_usd_global=max_usd,
        max_tokens_global=max_tokens,
    )

    _ensure_tsv_header(results_tsv)

    # Resume: load already-completed cells so we can skip them.
    completed_cells: set[tuple[str, str, int]] = (
        set() if force else _load_completed_cells(results_tsv)
    )

    report = RunReport(tsv_path=results_tsv)
    matrix_start = time.monotonic()

    # max_cells: total rows written in this run (across resume + new).
    # We count rows written in this invocation only (report.rows_written is the
    # counter); completed_cells are already in the file and do not count toward
    # the ceiling for this run.
    _cells_this_run = 0

    # Conditionally import Tier3Docker for production runs.
    _Tier3Docker = None
    if use_tier3:
        from evals.runner.isolator import (  # type: ignore[assignment]
            Tier3Docker as _Tier3Docker,
        )

    # Per-task dockerfile routing.
    # Collect unique dockerfiles from active tasks and ensure each image is
    # built once before the cell loop.  Default dockerfile uses the standard
    # tag; custom dockerfiles derive their tag from the filename.
    _dockerfile_dir = Path(__file__).resolve().parent.parent.parent / "evals" / "runner"
    _default_image_tag = "ae-eval-swebench:latest"

    def _derive_image_tag(dockerfile_name: str) -> str:
        """Map Dockerfile.swebench-<suffix> -> ae-eval-swebench:<suffix>."""
        if dockerfile_name == "Dockerfile.swebench":
            return _default_image_tag
        prefix = "Dockerfile.swebench-"
        if dockerfile_name.startswith(prefix):
            suffix = dockerfile_name[len(prefix):]
            return f"ae-eval-swebench:{suffix}"
        # Fallback for unexpected filenames.
        return f"ae-eval-swebench:{dockerfile_name.replace('.', '-')}"

    _task_image_tags: dict[str, str] = {}  # task_slug -> image_tag
    if use_tier3:
        assert _Tier3Docker is not None
        unique_dockerfiles: dict[str, str] = {}  # dockerfile_name -> image_tag
        for task_slug, task_meta in tasks.items():
            dockerfile_name = task_meta.get("dockerfile", "Dockerfile.swebench")
            image_tag = _derive_image_tag(dockerfile_name)
            _task_image_tags[task_slug] = image_tag
            unique_dockerfiles[dockerfile_name] = image_tag

        for dockerfile_name, image_tag in unique_dockerfiles.items():
            dockerfile_path = _dockerfile_dir / dockerfile_name
            if rebuild_image:
                # Evict cached digest so ensure_image() rebuilds from scratch.
                from evals.runner.isolator import _IMAGE_DIGEST_CACHE
                _IMAGE_DIGEST_CACHE.pop(image_tag, None)
            _LOG.info(
                "Tier 3: ensuring image %s from %s (one-time build before cell loop)",
                image_tag,
                dockerfile_path,
            )
            _Tier3Docker.ensure_image(
                image_tag=image_tag,
                dockerfile=dockerfile_path,
                force_rebuild=rebuild_image,
            )

    for task_slug, task_meta in tasks.items():
        for condition in active_conditions:
            # Methodology pair uses n_replicates_methodology; others use n_replicates.
            n = (
                n_replicates_methodology
                if condition in ("baseline", "ae-rules-injected")
                else n_replicates
            )
            for rep in range(1, n + 1):
                # Resume: skip cells already present in TSV.
                if (task_slug, condition, rep) in completed_cells:
                    _LOG.debug(
                        "Skipping already-completed cell: task=%s condition=%s rep=%d",
                        task_slug, condition, rep,
                    )
                    continue

                # Wall-clock budget check.
                elapsed = time.monotonic() - matrix_start
                if elapsed > max_wall_seconds:
                    _LOG.warning(
                        "Wall-clock ceiling reached (%.0f s > %.0f s). "
                        "Halting matrix with partial results.",
                        elapsed,
                        max_wall_seconds,
                    )
                    report.partial = True
                    return report

                cell_id = f"{task_slug}__{condition}"
                _LOG.info(
                    "Running cell: task=%s condition=%s rep=%d/%d",
                    task_slug, condition, rep, n,
                )

                # Per-task Tier3 context (production path).
                # Instantiated fresh per (task, condition, rep) so each cell
                # gets an isolated fix-phase dir seeded from the task's base
                # commit. The held-out dir is populated from task_meta.
                tier3_ctx = None
                _tier3_instance = None
                _non_tier3_fix_dir: Optional[Path] = None

                if use_tier3:
                    assert _Tier3Docker is not None  # guarded above
                    # held_out_dir: path to the task's held-out test files.
                    # In production these are committed to the corpus at a
                    # well-known location; fall back to None (empty tmpdir).
                    held_out_path: Optional[Path] = None
                    task_held_out = task_meta.get("_held_out_dir_path")
                    if task_held_out and Path(task_held_out).exists():
                        held_out_path = Path(task_held_out)
                    # held_out_from_fix_dir=True: test_patch is applied to the
                    # fix-phase dir during seeding, so /scoring/tests must
                    # mount the same dir as /workspace/repo. When a task also
                    # provides a held_out_path (pre-seeded corpus files),
                    # held_out_from_fix_dir takes precedence so the
                    # post-seeding test files are used for scoring.
                    _cell_image_tag = _task_image_tags.get(
                        task_slug, _default_image_tag
                    )
                    _tier3_instance = _Tier3Docker(
                        fixture_repo_dir=None,  # base repo seeded externally
                        held_out_dir=held_out_path,
                        build_image=False,  # image already built once by ensure_image() above
                        timeout_seconds=_PYTEST_TIMEOUT_SECONDS * 2,
                        held_out_from_fix_dir=True,
                        image_tag=_cell_image_tag,
                    )
                    tier3_ctx = _tier3_instance.__enter__()

                try:
                    # Determine the fix-phase directory.
                    # Tier3 provides an isolated tmpdir; otherwise fall back
                    # to a per-cell tempdir in tier3_mode='off' (non-dry-run).
                    fix_worktree: Optional[Path] = (
                        tier3_ctx.fix_phase_dir if tier3_ctx is not None else None
                    )

                    # Seeding: clone repo at base_commit and apply test_patch.
                    # Skipped in dry_run mode (canned transcript path).
                    _seed_status: Optional[str] = None  # None = ok / "seed_error"
                    _seed_commit: str = ""  # SHA of post-seeding commit; used for engineer diff
                    if not dry_run:
                        # When not using Tier3, create a tempdir for the fix phase.
                        if fix_worktree is None:
                            _non_tier3_fix_dir = Path(tempfile.mkdtemp(
                                prefix=f"skill-cmp-{task_slug}-"
                            ))
                            fix_worktree = _non_tier3_fix_dir

                        _tasks_root = Path(__file__).parent / "tasks"
                        try:
                            _seed_result = seed_fix_phase(
                                task_slug=task_slug,
                                task_meta=task_meta,
                                fix_dir=fix_worktree,
                                tasks_root=_tasks_root,
                            )
                            _seed_commit = _seed_result.get("seed_commit", "")
                        except SeedError as seed_exc:
                            _LOG.error(
                                "Seed failed for %s rep %d (step=%s): %s",
                                cell_id, rep, seed_exc.step, seed_exc,
                            )
                            _seed_status = "seed_error"
                        except (FileNotFoundError, ValueError) as seed_exc:
                            _LOG.error(
                                "Seed pre-check failed for %s rep %d: %s",
                                cell_id, rep, seed_exc,
                            )
                            _seed_status = "seed_error"

                    # Post-seed commands: run after successful seeding and before
                    # the engineer spawn.  If any command fails, treat it as a
                    # seed_error so the cell is skipped.
                    #
                    # When Tier3 is active, commands run INSIDE the container
                    # (via run_fix_phase command path) so C-extension builds
                    # produce Linux-compatible binaries even when the host is
                    # macOS.  The container mounts fix_worktree rw, so in-place
                    # builds write .so files back to the host directory.
                    # When Tier3 is off, commands run directly on the host.
                    if _seed_status is None and not dry_run:
                        _post_seed_cmds = task_meta.get("post_seed_commands")
                        if _post_seed_cmds and fix_worktree is not None:
                            for _cmd in _post_seed_cmds:
                                _LOG.info(
                                    "Running post-seed command for %s: %s",
                                    cell_id, _cmd,
                                )
                                if tier3_ctx is not None and _Tier3Docker is not None:
                                    _ps_result = _Tier3Docker.run_fix_phase(
                                        ctx=tier3_ctx,
                                        command=["sh", "-c", _cmd],
                                        timeout_seconds=300,
                                    )
                                else:
                                    _ps_result = subprocess.run(
                                        _cmd,
                                        shell=True,
                                        cwd=fix_worktree,
                                        capture_output=True,
                                        text=True,
                                        timeout=300,
                                    )
                                if _ps_result.returncode != 0:
                                    _LOG.error(
                                        "Post-seed command failed for %s rep %d: %s\nstderr: %s",
                                        cell_id, rep, _cmd,
                                        _ps_result.stderr,
                                    )
                                    _seed_status = "seed_error"
                                    break

                    # If seeding failed, record seed_error row and skip engineer.
                    if _seed_status == "seed_error":
                        _append_tsv_row(
                            results_tsv,
                            {
                                "task_slug": task_slug,
                                "condition": condition,
                                "replicate": rep,
                                "status": "seed_error",
                                "pass_fail": "0",
                                # MAJOR-2: use empty string for score_primary on error
                                # rows so the aggregator excludes them from median
                                # computation. 0.0 would silently inflate failure rates.
                                "score_primary": "",
                                "lines_touched": 0,
                                "files_touched": 0,
                                "scope_creep_flag": "0",
                                "held_out_failures": "[]",
                                "cost_usd": 0.0,
                                "tokens_input": 0,
                                "tokens_output": 0,
                                "latency_ms": 0,
                                "invocation_mode": "seed_error",
                                "diagnostics_json": "{}",
                            },
                        )
                        report.rows_written += 1
                        _cells_this_run += 1
                        # Cleanup non-Tier3 tmpdir if we created one.
                        if _non_tier3_fix_dir is not None:
                            shutil.rmtree(_non_tier3_fix_dir, ignore_errors=True)
                            _non_tier3_fix_dir = None
                        if max_cells is not None and _cells_this_run >= max_cells:
                            _LOG.info(
                                "max_cells ceiling reached (%d). "
                                "Halting matrix with partial results.",
                                max_cells,
                            )
                            report.partial = True
                            return report
                        continue

                    # Run the fix phase.
                    # Production (tier3_ctx is not None): route through
                    # Tier3Docker.run_fix_phase so the isolator orchestrates
                    # the Claude CLI invocation. This ensures the isolator's
                    # fix-phase directory is the canonical cwd for the agent.
                    # MAJOR-3 regression: previously invoke_run was called
                    # directly here, bypassing run_fix_phase entirely.
                    try:
                        if tier3_ctx is not None:
                            # Fix-phase CLI runs on host (Anthropic API network requirement).
                            # Score-phase enforces container isolation - see run_score_phase.
                            # Build prompt and invoke via the isolator.
                            _fix_prompt = _build_fix_prompt(task_slug, task_meta)
                            _agent_conditions = _agent_conditions_for_backend(backend)
                            _agent_name: Optional[str] = _agent_conditions.get(condition)
                            if backend == "kimi":
                                _system_prompt: Optional[str] = None
                            else:
                                _system_prompt = (
                                    ae_payload if condition == "ae-rules-injected" else None
                                )
                            cp = _Tier3Docker.run_fix_phase(
                                ctx=tier3_ctx,
                                prompt=_fix_prompt,
                                timeout_seconds=_PYTEST_TIMEOUT_SECONDS * 2,
                                agent_name=_agent_name,
                                system_prompt=_system_prompt,
                                backend=backend,
                            )
                            # run_fix_phase (prompt path) encodes the invoker
                            # dict as JSON in cp.stdout.
                            try:
                                result = json.loads(cp.stdout)
                            except (json.JSONDecodeError, TypeError):
                                result = {
                                    "final_text": cp.stdout or "",
                                    "status": "ok" if cp.returncode == 0 else f"cli_exit_{cp.returncode}",
                                    "cost_usd": 0.0,
                                    "usage": {},
                                    "latency_ms": 0,
                                    "invocation_mode": "tier3",
                                    "tool_calls": [],
                                    "turns_used": 0,
                                    "_parse_warnings": ["run_fix_phase stdout was not valid JSON"],
                                }
                        else:
                            result = _run_cell(
                                task_slug=task_slug,
                                task_meta=task_meta,
                                condition=condition,
                                replicate=rep,
                                ae_payload=ae_payload,
                                dry_run=dry_run,
                                worktree=fix_worktree,
                                backend=backend,
                            )
                    except Exception as exc:
                        _LOG.error(
                            "Cell %s rep %d raised unexpectedly: %s",
                            cell_id, rep, exc,
                        )
                        result = {
                            "final_text": "",
                            "status": f"error:{type(exc).__name__}",
                            "cost_usd": 0.0,
                            "usage": {},
                            "latency_ms": 0,
                            "invocation_mode": "error",
                            "tool_calls": [],
                            "turns_used": 0,
                            "_parse_warnings": [str(exc)],
                        }

                    # Use cli_stdout for transcript: it is the verbatim CLI
                    # pipe capture and is always populated when the CLI ran.
                    # final_text is parsed from stream-json events and may be
                    # empty when the run produced only tool-use events with no
                    # assistant text blocks (the smoke v4 regression case).
                    transcript = result.get("cli_stdout") or result.get("final_text", "")
                    run_status = result.get("status", "unknown")
                    cost_usd = float(result.get("cost_usd") or 0.0)
                    usage = result.get("usage") or {}
                    latency_ms = int(result.get("latency_ms") or 0)
                    invocation_mode = result.get("invocation_mode", "")

                    # Persist engineer transcript for post-mortem.
                    _transcript_slug = f"{task_slug}__{condition}__rep{rep}"
                    _transcript_path = _transcript_dir / f"{_transcript_slug}.log"
                    try:
                        _stderr_tail = result.get("stderr_tail", "") or ""
                        # Guard: transcript and stderr_tail must be strings.
                        _transcript_content = transcript if isinstance(transcript, str) else str(transcript)
                        if _stderr_tail and isinstance(_stderr_tail, str):
                            _transcript_content = (
                                _transcript_content
                                + "\n\n--- stderr ---\n"
                                + _stderr_tail
                            )
                        _transcript_path.write_text(
                            _transcript_content, encoding="utf-8"
                        )
                    except OSError as _t_exc:
                        _LOG.warning(
                            "Failed to persist transcript for %s rep %d: %s",
                            cell_id, rep, _t_exc,
                        )
                        _transcript_path = None  # type: ignore[assignment]

                    # On CLI exit failures, print last 500 chars to stderr for
                    # quick post-mortem without opening the file.
                    if run_status.startswith("cli_exit_") and transcript:
                        _tail = transcript[-500:]
                        print(
                            f"[cli_exit] {cell_id} rep {rep}: last 500 chars of transcript:\n"
                            f"{_tail}",
                            file=sys.stderr,
                        )

                    # Score the cell.
                    # dry_run: use fresh tmpdirs; production: use Tier3 dirs
                    # or the seeded fix_worktree (tier3_mode='off' path).
                    if dry_run:
                        fix_dir = Path(tempfile.mkdtemp())
                        held_dir = Path(tempfile.mkdtemp())
                    elif tier3_ctx is not None:
                        fix_dir = tier3_ctx.fix_phase_dir
                        held_dir = tier3_ctx.held_out_dir
                    elif fix_worktree is not None:
                        # tier3_mode='off' production: use the seeded worktree.
                        # The test_patch was applied to fix_worktree, so the
                        # held-out tests live there alongside the source.
                        fix_dir = fix_worktree
                        held_dir = fix_worktree
                    else:
                        fix_dir = Path(".")
                        held_dir = Path(".")

                    _score_error: Optional[str] = None
                    _fail_to_pass = task_meta.get("fail_to_pass") or []
                    try:
                        scored = score_cell(
                            task_slug=task_slug,
                            transcript=transcript,
                            task_meta=task_meta,
                            fix_phase_dir=fix_dir,
                            held_out_dir=held_dir,
                            tier3_ctx=tier3_ctx,
                            pytest_timeout=_PYTEST_TIMEOUT_SECONDS,
                            fail_to_pass=_fail_to_pass,
                            seed_commit=_seed_commit,
                        )
                    except Exception as exc:
                        _LOG.error(
                            "score_cell raised for %s rep %d: %s",
                            cell_id, rep, exc,
                        )
                        _score_error = str(exc)
                        scored = ScoringResult(
                            pass_fail=False,
                            score_primary=0.0,
                            lines_touched=0,
                            files_touched=0,
                            scope_creep_flag=False,
                            held_out_failures=[],
                            pytest_returncode=-1,
                            diff_text="",
                            diagnostics={"error": str(exc)},
                        )
                    finally:
                        if dry_run:
                            shutil.rmtree(fix_dir, ignore_errors=True)
                            shutil.rmtree(held_dir, ignore_errors=True)

                finally:
                    # Always exit the Tier3 context manager so containers and
                    # tmpdirs are cleaned up even on exception.
                    if _tier3_instance is not None:
                        _tier3_instance.__exit__(None, None, None)
                        tier3_ctx = None
                    # Cleanup non-Tier3 seeded tmpdir (if we created one).
                    if _non_tier3_fix_dir is not None:
                        shutil.rmtree(_non_tier3_fix_dir, ignore_errors=True)
                        _non_tier3_fix_dir = None

                # Record cost.
                tokens_input = int(usage.get("input_tokens", usage.get("input", 0)))
                tokens_output = int(usage.get("output_tokens", usage.get("output", 0)))

                try:
                    cost_gate.record(
                        cell_id=cell_id,
                        ticket_id=f"{cell_id}__rep{rep}",
                        tokens={
                            "input": tokens_input,
                            "output": tokens_output,
                            "cache_creation": int(
                                usage.get("cache_creation_input_tokens",
                                          usage.get("cache_creation", 0))
                            ),
                            "cache_read": int(
                                usage.get("cache_read_input_tokens",
                                          usage.get("cache_read", 0))
                            ),
                        },
                        cost_usd=cost_usd,
                    )
                except BudgetExceeded as exc:
                    _LOG.warning("Budget exceeded: %s. Halting.", exc)
                    report.budget_breached = True
                    report.partial = True
                    report.error = str(exc)
                    return report

                # Append TSV row.
                # If score_cell itself raised, override run_status to "score_error"
                # so that callers can distinguish a clean run with a scoring failure
                # from a successful run ("ok") or an engineer-phase failure.
                effective_status = "score_error" if _score_error is not None else run_status

                # Merge transcript path into diagnostics so operators can locate
                # the log file from the TSV row alone.
                _diagnostics = dict(scored.diagnostics)
                if _transcript_path is not None:
                    _diagnostics["transcript_path"] = str(_transcript_path)
                if effective_status.startswith("cli_exit_") and _transcript_path is not None:
                    _diagnostics["cli_exit_transcript"] = str(_transcript_path)

                row = {
                    "task_slug": task_slug,
                    "condition": condition,
                    "replicate": rep,
                    "status": effective_status,
                    "pass_fail": "1" if scored.pass_fail else "0",
                    "score_primary": scored.score_primary,
                    "lines_touched": scored.lines_touched,
                    "files_touched": scored.files_touched,
                    "scope_creep_flag": "1" if scored.scope_creep_flag else "0",
                    "held_out_failures": json.dumps(scored.held_out_failures),
                    "cost_usd": cost_usd,
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                    "latency_ms": latency_ms,
                    "invocation_mode": invocation_mode,
                    "diagnostics_json": json.dumps(_diagnostics),
                }
                _append_tsv_row(results_tsv, row)
                report.rows_written += 1
                _cells_this_run += 1
                if max_cells is not None and _cells_this_run >= max_cells:
                    _LOG.info(
                        "max_cells ceiling reached (%d). "
                        "Halting matrix with partial results.",
                        max_cells,
                    )
                    report.partial = True
                    return report

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run skill-comparison eval matrix.")
    parser.add_argument("--tasks-yaml", type=Path, required=True)
    parser.add_argument("--results-tsv", type=Path, default=None)
    parser.add_argument("--content-root", type=Path, default=None)
    parser.add_argument("--n-replicates", type=int, default=3)
    parser.add_argument("--n-replicates-methodology", type=int, default=5)
    parser.add_argument("--max-usd", type=float, default=250.0)
    parser.add_argument("--max-tokens", type=int, default=75_000_000)
    parser.add_argument("--max-wall-seconds", type=float, default=43200.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--conditions", nargs="*", default=None)
    parser.add_argument(
        "--tier3",
        choices=["auto", "off"],
        default="auto",
        help=(
            "Tier 3 Docker isolation mode. 'auto' (default) instantiates "
            "Tier3Docker in production; 'off' skips Docker (for dry-run / "
            "unit tests)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run cells already present in the TSV (bypass resume skip).",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=None,
        dest="tasks_filter",
        metavar="SLUG",
        help=(
            "Space-separated list of task slugs to include (matches keys in "
            "corpus.yaml). If omitted or empty, all tasks run. Unknown slugs "
            "raise an error before any cell executes."
        ),
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Hard stop after writing N rows to the TSV (excluding the header). "
            "Useful for 'just one cell' smoke validation. When both --tasks and "
            "--max-cells are passed, whichever limit is reached first wins."
        ),
    )
    parser.add_argument(
        "--rebuild-image",
        action="store_true",
        default=False,
        help=(
            "Force a fresh Docker image build by evicting the cached digest "
            "before calling ensure_image(). Use when Dockerfile.swebench has "
            "changed and the locally-tagged ae-eval-swebench:latest image is "
            "stale. Has no effect when --tier3=off or --dry-run."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=["claude", "kimi"],
        default="claude",
        help=(
            "CLI backend to use for the eval runs. 'claude' (default) uses the "
            "Claude Code CLI; 'kimi' uses the Kimi CLI."
        ),
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    report = run_matrix(
        tasks_yaml=args.tasks_yaml,
        results_tsv=args.results_tsv,
        content_root=args.content_root,
        n_replicates=args.n_replicates,
        n_replicates_methodology=args.n_replicates_methodology,
        max_usd=args.max_usd,
        max_tokens=args.max_tokens,
        max_wall_seconds=args.max_wall_seconds,
        dry_run=args.dry_run,
        conditions=args.conditions,
        tier3_mode=args.tier3,
        force=args.force,
        tasks_filter=args.tasks_filter if args.tasks_filter else None,
        max_cells=args.max_cells,
        rebuild_image=args.rebuild_image,
        backend=args.backend,
    )

    print(json.dumps(
        {
            "rows_written": report.rows_written,
            "budget_breached": report.budget_breached,
            "partial": report.partial,
            "tsv_path": str(report.tsv_path) if report.tsv_path else None,
            "error": report.error,
        },
        indent=2,
    ))

    if report.budget_breached:
        sys.exit(3)
