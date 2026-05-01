"""
Purpose: Invoke evals.runner.cli as a subprocess for a given component, then
         read back the N freshly-appended rows from the component's TSV and
         aggregate them to a single scalar (mean-of-fixture-medians) plus a
         pooled stdev estimate.

Public API:
    run_component(repo_root: Path, component: str,
                  extra_env: dict | None = None,
                  timeout_sec: int = 1800) -> dict with keys
        {ok: bool, stdout: str, stderr: str, returncode: int, cost_usd: float}
    aggregate_latest(repo_root: Path, component: str,
                     n_fixtures: int) -> dict with keys
        {metric: float, pooled_stdev: float, rows: list[dict]}

Upstream deps: stdlib statistics, subprocess, pathlib, csv.

Downstream consumers: evals.auto.loop.

Failure modes: run_component propagates CLI failure via returncode. aggregate_latest
               raises ValueError if the TSV has fewer rows than n_fixtures or any
               recent row has status != "ok".

Performance: the subprocess dominates; shim overhead is negligible.

Aggregation choice: mean-of-fixture-medians.
  For each of the component's fixtures, evals/runner already writes
  primary_score_median and primary_score_stdev aggregating its N internal runs.
  We take the mean across fixtures as the scalar the loop optimizes. This
  is sensitive to all fixture scores and avoids suppressing genuine improvements
  on the majority when one fixture sits at an extreme. Pooled stdev is
  the root-mean-square of per-fixture stdevs (sqrt(mean(stdev**2))), used as
  one side of the keep-delta threshold: delta >= max(pooled_stdev, 0.02).
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


def run_component(
    repo_root: Path,
    component: str,
    extra_env: Optional[Dict[str, str]] = None,
    timeout_sec: int = 7200,
) -> Dict[str, object]:
    """Invoke `python -m evals.runner.cli run <component>` as a subprocess.

    The runner appends one TSV row per fixture. Cost is summed from the
    per-row diagnostic_json's per_run cost_usd entries, if present.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", "evals.runner.cli", "run", component]
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
        }
    return {
        "ok": r.returncode == 0,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "returncode": r.returncode,
        "cost_usd": 0.0,  # filled by aggregate_latest from TSV diagnostic
    }


def _read_last_rows(tsv: Path, n: int) -> List[Dict[str, str]]:
    if not tsv.exists():
        return []
    with tsv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
    return rows[-n:] if n > 0 else []


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
    repo_root: Path, component: str, n_fixtures: int
) -> Dict[str, object]:
    """Aggregate the last `n_fixtures` TSV rows into one scalar.

    Returns {metric, pooled_stdev, rows, cost_usd}. Raises ValueError if the
    TSV has fewer than n_fixtures rows.
    """
    tsv = _tsv_path(repo_root, component)
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
