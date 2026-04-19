"""
Purpose: Read/write the per-run state file at evals/auto/state/<branch>.json
         atomically. State carries iteration index, baseline metric, last-kept
         metric, branch name, start timestamp, and cumulative cost so a loop
         can resume or be inspected mid-flight.

Public API: load(path) -> dict, save(path, state) -> None,
            new_state(branch, baseline, component, max_iterations, time_budget_sec,
                      cost_budget_usd) -> dict.

Upstream deps: stdlib json, os, pathlib, tempfile, time.

Downstream consumers: evals.auto.loop, evals.auto.cli.

Failure modes: load() raises FileNotFoundError if state file is missing. save()
               writes via os.replace() for atomicity; does not fsync parent dir.
               Not multi-process safe; the loop's lock file (evals/.auto-harness.lock)
               is the concurrency guard.

Performance: single small JSON per call.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict


def new_state(
    branch: str,
    baseline: float,
    component: str,
    max_iterations: int,
    time_budget_sec: int,
    cost_budget_usd: float,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "branch": branch,
        "component": component,
        "started_at": time.time(),
        "baseline_metric": baseline,
        "last_kept_metric": baseline,
        "iteration": 0,
        "max_iterations": max_iterations,
        "time_budget_sec": time_budget_sec,
        "cost_budget_usd": cost_budget_usd,
        "cost_spent_usd": 0.0,
        "keeps": 0,
        "reverts": 0,
        "plateau_streak": 0,
        "history": [],  # list of {iteration, decision, delta, metric_after}
    }


def load(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile in same dir, then os.replace.
    fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, str(path))
    except Exception:
        # Best-effort cleanup of the temp file if replace failed.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
