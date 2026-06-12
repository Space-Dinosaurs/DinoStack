"""
Purpose: Invoke evals.runner.cli as a subprocess for a given component, then
         read back the N freshly-appended rows from the component's TSV and
         aggregate them to a single scalar (mean-of-fixture-medians) plus a
         pooled stdev estimate.

Public API:
    run_component(repo_root: Path, component: str,
                  extra_env: dict | None = None,
                  timeout_sec: int = 7200) -> dict with keys
        {ok: bool, stdout: str, stderr: str, returncode: int, cost_usd: float,
         head_commit: str}
    aggregate_latest(repo_root: Path, component: str,
                     n_fixtures: int,
                     expected_commit: str | None = None) -> dict with keys
        {metric: float, pooled_stdev: float, rows: list[dict], cost_usd: float}

Upstream deps: stdlib statistics, subprocess, pathlib, csv.

Downstream consumers: evals.auto.loop.

Failure modes: run_component propagates CLI failure via returncode.
               aggregate_latest (expected_commit=None path) raises ValueError
               if the TSV has fewer rows than n_fixtures.
               aggregate_latest (expected_commit=<sha> path) raises ValueError
               if the filtered rows for that commit do not number exactly
               n_fixtures, or if the fixture_id values among those rows are not
               all-distinct.

Performance: the subprocess dominates; shim overhead is negligible.

Aggregation choice: mean-of-fixture-medians.
  For each of the component's fixtures, evals/runner already writes
  primary_score_median and primary_score_stdev aggregating its N internal runs.
  We take the mean across fixtures as the scalar the loop optimizes. This
  is sensitive to all fixture scores and avoids suppressing genuine improvements
  on the majority when one fixture sits at an extreme. Pooled stdev is
  the root-mean-square of per-fixture stdevs (sqrt(mean(stdev**2))), used as
  observability only (not a keep threshold - keep decisions are made by
  evals.auto.stats.keep_decision via the sign-flip permutation gate).

  expected_commit param (run-delimiter):
    When expected_commit is not None, aggregate_latest filters TSV rows to
    those whose `commit` column equals expected_commit, then asserts exactly
    n_fixtures rows with all-distinct fixture_id values. This prevents the
    trailing-window read from mixing rows across runs when n_runs or fixture
    count changes between runs.
    When expected_commit is None, behavior is bit-for-bit identical to the
    original trailing-window read (existing tests are the back-compat gate).

  run_component HEAD-equals-per-row-commit invariant:
    run_component reads `git rev-parse HEAD` immediately before launching
    the runner subprocess and returns it as `head_commit`. The runner
    stamps each TSV row with the same HEAD at the moment it runs. Callers
    should pass `result["head_commit"]` as `expected_commit` to
    aggregate_latest to take advantage of the run-delimiter assertions.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _tsv_path(repo_root: Path, component: str) -> Path:
    return repo_root / "evals" / "results" / f"{component}.tsv"


def _read_git_head(repo_root: Path) -> str:
    """Return the current HEAD commit SHA for repo_root."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def run_component(
    repo_root: Path,
    component: str,
    extra_env: Optional[Dict[str, str]] = None,
    timeout_sec: int = 7200,
    model: str = "sonnet",
) -> Dict[str, object]:
    """Invoke `python -m evals.runner.cli run <component>` as a subprocess.

    The runner appends one TSV row per fixture. Cost is summed from the
    per-row diagnostic_json's per_run cost_usd entries, if present.

    Reads git HEAD immediately before launching the subprocess and returns
    it as `head_commit`. The runner stamps each TSV row with the same HEAD,
    so callers can pass `result["head_commit"]` as `expected_commit` to
    aggregate_latest for run-delimiter assertions.
    """
    head_commit = _read_git_head(repo_root)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", "evals.runner.cli", "run", component, "--model", model]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "stdout": e.stdout or "",
            "stderr": f"timeout after {timeout_sec}s",
            "returncode": -1,
            "cost_usd": 0.0,
            "head_commit": head_commit,
        }
    return {
        "ok": r.returncode == 0,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "returncode": r.returncode,
        "cost_usd": 0.0,  # filled by aggregate_latest from TSV diagnostic
        "head_commit": head_commit,
    }


def _read_last_rows(tsv: Path, n: int) -> List[Dict[str, str]]:
    if not tsv.exists():
        return []
    with tsv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
    return rows[-n:] if n > 0 else []


def _read_all_rows(tsv: Path) -> List[Dict[str, str]]:
    if not tsv.exists():
        return []
    with tsv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return list(reader)


def _row_cost(row: Dict[str, str]) -> float:
    raw = row.get("diagnostic_json") or ""
    if not raw:
        return 0.0
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return 0.0
    total = 0.0
    for pr in d.get("per_run", []) or []:
        diag = pr.get("diagnostic") or {}
        # invoker stashes cost_usd in the top-level run record; aggregator
        # preserves it via diagnostic when available. Be lenient about the
        # field's location.
        c = diag.get("cost_usd")
        if c is None:
            c = pr.get("cost_usd")
        if isinstance(c, (int, float)):
            total += float(c)
    return total


def aggregate_latest(
    repo_root: Path,
    component: str,
    n_fixtures: int,
    expected_commit: Optional[str] = None,
) -> Dict[str, object]:
    """Aggregate the last `n_fixtures` TSV rows into one scalar.

    Returns {metric, pooled_stdev, rows, cost_usd}. Raises ValueError if the
    TSV has fewer than n_fixtures rows (expected_commit=None path).

    When expected_commit is not None (run-delimiter path):
      - Filters all TSV rows to those whose `commit` column equals expected_commit.
      - Asserts exactly n_fixtures rows matched (raises ValueError on mismatch).
      - Asserts the matched rows' fixture_id values are all-distinct and number
        n_fixtures (raises ValueError on duplicate fixture_id).
      Both assertions are gated on expected_commit is not None; the None path
      is bit-for-bit identical to the original trailing-window behavior.
    """
    tsv = _tsv_path(repo_root, component)

    if expected_commit is not None:
        # Run-delimiter path: filter by commit, assert exact count + unique ids.
        all_rows = _read_all_rows(tsv)
        rows = [r for r in all_rows if r.get("commit") == expected_commit]
        if len(rows) != n_fixtures:
            raise ValueError(
                f"TSV {tsv}: expected exactly {n_fixtures} rows for commit "
                f"{expected_commit!r}, got {len(rows)}"
            )
        fixture_ids = [r.get("fixture_id", "") for r in rows]
        if len(set(fixture_ids)) != n_fixtures:
            seen: dict[str, int] = {}
            for fid in fixture_ids:
                seen[fid] = seen.get(fid, 0) + 1
            dupes = {k: v for k, v in seen.items() if v > 1}
            raise ValueError(
                f"TSV {tsv}: duplicate fixture_id values among rows for commit "
                f"{expected_commit!r}: {dupes}"
            )
    else:
        # Original trailing-window path: unchanged behavior.
        rows = _read_last_rows(tsv, n_fixtures)
        if len(rows) < n_fixtures:
            raise ValueError(
                f"TSV {tsv} has {len(rows)} rows; expected at least {n_fixtures}"
            )

    medians: List[float] = []
    stdevs: List[float] = []
    cost = 0.0
    for r in rows:
        try:
            medians.append(float(r["primary_score_median"]))
            stdevs.append(float(r["primary_score_stdev"]))
        except (KeyError, ValueError) as e:
            raise ValueError(f"malformed TSV row: {e}") from e
        cost += _row_cost(r)
    metric = statistics.mean(medians)
    pooled_stdev = math.sqrt(sum(s * s for s in stdevs) / len(stdevs)) if stdevs else 0.0
    return {
        "metric": float(metric),
        "pooled_stdev": float(pooled_stdev),
        "rows": rows,
        "cost_usd": float(cost),
    }


def baseline_from_tsv(
    repo_root: Path, component: str, n_fixtures: int
) -> Dict[str, object]:
    """Read the last n_fixtures rows of the TSV as a baseline snapshot.

    Used by preflight and dry-run: the most recent production-prompt rows in
    the ledger define the starting metric. Loop runs produce fresh rows in a
    dedicated auto-harness.tsv, not this one.
    """
    return aggregate_latest(repo_root, component, n_fixtures)
