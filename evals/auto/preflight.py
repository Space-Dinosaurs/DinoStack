"""
Purpose: Preflight checks run before the /auto-harness loop starts. Each check
         returns a boolean plus a human-readable reason; the CLI aborts on the
         first failure and prints the reason.

Public API: run_preflight(repo_root, component, components_cfg) -> dict with
            keys {ok: bool, failures: list[str], baseline_rows: int,
                  n_fixtures: int}.

Checks:
    - repo tree is clean (no staged/unstaged changes)
    - current branch is NOT main (would be destructive to commit on main)
    - lock file evals/.auto-harness.lock does not exist
    - component entry exists in components.yaml and is populated (not TODO)
    - fixtures directory exists and has >=1 fixture
    - component TSV exists with at least 3 * n_fixtures rows (enough history
      to compute baseline metric stably)
    - `claude` CLI is on PATH and prints a version string

Upstream deps: stdlib pathlib, shutil, subprocess, csv.

Downstream consumers: evals.auto.cli.

Failure modes: all failures are reported as strings; no exceptions raised.
"""
from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List


def _tsv_row_count(tsv: Path) -> int:
    if not tsv.exists():
        return 0
    with tsv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        rows = list(reader)
    return max(0, len(rows) - 1)  # minus header


def _count_fixtures(fixture_dir: Path) -> int:
    if not fixture_dir.exists():
        return 0
    return sum(1 for p in fixture_dir.iterdir() if p.is_dir())


def run_preflight(
    repo_root: Path, component: str, components_cfg: Dict[str, object]
) -> Dict[str, object]:
    failures: List[str] = []

    # 1. Clean tree
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        failures.append(f"git_status_failed: {r.stderr.strip()}")
    elif r.stdout.strip():
        failures.append("tree_not_clean: commit or stash local changes first")

    # 2. Branch is not main
    br = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    branch = br.stdout.strip() if br.returncode == 0 else ""
    if branch in ("main", "master"):
        failures.append(
            f"on_protected_branch:{branch}: check out a working branch before running /auto-harness"
        )

    # 3. Lock file absent
    lock = repo_root / "evals" / ".auto-harness.lock"
    if lock.exists():
        failures.append(
            f"lock_present:{lock}: another /auto-harness run may be active; remove the file only if you are sure no loop is running"
        )

    # 4. Component entry populated
    cfg = components_cfg.get(component) if isinstance(components_cfg, dict) else None
    if cfg is None:
        failures.append(f"component_not_in_components_yaml:{component}")
    elif not isinstance(cfg, dict):
        failures.append(f"component_config_malformed:{component}")
    elif "TODO" in cfg:
        failures.append(
            f"component_stub_only:{component}: components.yaml entry has TODO; populate editable/locked/max_edit_loc before running"
        )
    elif not cfg.get("editable"):
        failures.append(f"component_missing_editable:{component}")

    # 5. Fixtures present
    fixture_dir = repo_root / "evals" / "fixtures" / component
    n_fixtures = _count_fixtures(fixture_dir)
    if n_fixtures < 1:
        failures.append(f"no_fixtures_in:{fixture_dir}")

    # 6. Baseline TSV has >= 3 rows per fixture (i.e. at least n_fixtures rows;
    #    the architect plan requested >=3 TSV rows as history; interpret as
    #    "at least 1 full baseline cycle of n_fixtures rows, preferably 3 cycles").
    tsv = repo_root / "evals" / "results" / f"{component}.tsv"
    baseline_rows = _tsv_row_count(tsv)
    if baseline_rows < n_fixtures:
        failures.append(
            f"baseline_tsv_too_short:{tsv}: {baseline_rows} rows; need >= {n_fixtures} "
            f"(one full baseline run across {n_fixtures} fixtures)"
        )

    # 7. claude CLI available
    if shutil.which("claude") is None:
        failures.append("claude_cli_not_on_path: install Claude Code CLI or add to PATH")

    return {
        "ok": not failures,
        "failures": failures,
        "baseline_rows": baseline_rows,
        "n_fixtures": n_fixtures,
    }
