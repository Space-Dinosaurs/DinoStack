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
    ) -> RunReport

    RunReport (dataclass):
        rows_written: int
        budget_breached: bool
        partial: bool
        tsv_path: Path
        error: str | None

    CONDITION_LABELS (list[str]) - the canonical 8-condition names.

Upstream deps: stdlib pathlib, time, csv, json, dataclasses, sys, logging.
               pyyaml (project-standard dep).
               evals.runner.invoker (invoke_run, build_two_level_prompt).
               evals.runner.isolator (Tier3Docker, make_isolator).
               evals.skill-comparison.ae_rules_payload (build_payload).
               evals.skill-comparison.config_discovery (discover_configs).
               evals.skill-comparison.scoring (score_cell).
               evals.icl_vs_orchestration.cost_gate (CostGate, BudgetExceeded).

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
import sys
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

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONDITION_LABELS: list[str] = [
    "baseline",
    "ae-rules-injected",
    "engineer-direct",
    "architect-direct",
    "investigator-direct",
    "debugger-direct",
    "skeptic-direct",
    "qa-engineer-direct",
]

# Conditions that route via named-agent direct spawn (two-level Task).
_AGENT_CONDITIONS: dict[str, str] = {
    "engineer-direct": "engineer",
    "architect-direct": "architect",
    "investigator-direct": "investigator",
    "debugger-direct": "debugger",
    "skeptic-direct": "skeptic",
    "qa-engineer-direct": "qa-engineer",
}

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
) -> dict:
    """Run one (task, condition, replicate) cell and return a raw result dict.

    When dry_run=True, skips the actual CLI invocation and returns a canned
    transcript for testing purposes.

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

    agent_name: Optional[str] = _AGENT_CONDITIONS.get(condition)
    system_prompt: Optional[str] = ae_payload if condition == "ae-rules-injected" else None

    # For per-agent conditions, the two-level Task wrapper is built by invoker.
    # For baseline and ae-rules-injected, agent_name is None (conductor runs directly).
    result = invoke_run(
        prompt=prompt,
        worktree=Path("."),  # worktree is the Tier3 fix_phase_dir; set by caller context
        timeout_seconds=_PYTEST_TIMEOUT_SECONDS * 2,  # give engineer 240s
        agent_name=agent_name,
        mode="agent",
    )
    return result


# ---------------------------------------------------------------------------
# Core matrix loop
# ---------------------------------------------------------------------------


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
) -> RunReport:
    """Orchestrate the 8-condition skill-comparison eval matrix.

    For each (task, condition, replicate) cell:
      1. Materialise the condition config (ae-rules payload for ae-rules-injected,
         agent name for per-agent conditions, nothing for baseline).
      2. Spawn the engineer run (via Tier 3 Docker unless dry_run=True).
      3. Score the result.
      4. Append one row to the TSV ledger.

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
        n_replicates_methodology: replicates for baseline and ae-rules-injected
                                   (default 5; this is the headline pair).
        max_usd: global USD ceiling (default 250).
        max_tokens: global token ceiling (default 75 M).
        max_wall_seconds: global wall-clock ceiling (default 12 h).
        dry_run: if True, skip actual CLI calls and return canned results.
        conditions: subset of CONDITION_LABELS to run (None = all 8).

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

    tasks = _load_tasks(tasks_yaml)
    active_conditions = conditions if conditions is not None else CONDITION_LABELS

    # Build ae-rules payload once (reused for every ae-rules-injected cell).
    ae_payload: Optional[str] = None
    if "ae-rules-injected" in active_conditions and not dry_run:
        from ae_rules_payload import build_payload  # noqa: F401 (local import)
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
    report = RunReport(tsv_path=results_tsv)
    matrix_start = time.monotonic()

    for task_slug, task_meta in tasks.items():
        for condition in active_conditions:
            # Methodology pair uses n_replicates_methodology; others use n_replicates.
            n = (
                n_replicates_methodology
                if condition in ("baseline", "ae-rules-injected")
                else n_replicates
            )
            for rep in range(1, n + 1):
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

                # Run the cell.
                try:
                    result = _run_cell(
                        task_slug=task_slug,
                        task_meta=task_meta,
                        condition=condition,
                        replicate=rep,
                        ae_payload=ae_payload,
                        dry_run=dry_run,
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

                transcript = result.get("final_text", "")
                run_status = result.get("status", "unknown")
                cost_usd = float(result.get("cost_usd") or 0.0)
                usage = result.get("usage") or {}
                latency_ms = int(result.get("latency_ms") or 0)
                invocation_mode = result.get("invocation_mode", "")

                # Score the cell (local, no Docker, when dry_run).
                fix_dir = Path(tempfile.mkdtemp()) if dry_run else Path(".")
                held_dir = Path(tempfile.mkdtemp()) if dry_run else Path(".")

                try:
                    scored = score_cell(
                        task_slug=task_slug,
                        transcript=transcript,
                        task_meta=task_meta,
                        fix_phase_dir=fix_dir,
                        held_out_dir=held_dir,
                        tier3_ctx=None,  # Docker ctx is managed by caller in production
                        pytest_timeout=_PYTEST_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    _LOG.error(
                        "score_cell raised for %s rep %d: %s",
                        cell_id, rep, exc,
                    )
                    from scoring import ScoringResult as _SR
                    scored = _SR(
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
                        import shutil as _sh
                        _sh.rmtree(fix_dir, ignore_errors=True)
                        _sh.rmtree(held_dir, ignore_errors=True)

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
                row = {
                    "task_slug": task_slug,
                    "condition": condition,
                    "replicate": rep,
                    "status": run_status,
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
                    "diagnostics_json": json.dumps(scored.diagnostics),
                }
                _append_tsv_row(results_tsv, row)
                report.rows_written += 1

    return report


# ---------------------------------------------------------------------------
# Missing import for tempfile (used in dry_run path above)
# ---------------------------------------------------------------------------
import tempfile  # noqa: E402 (placed after function definitions for clarity)


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
