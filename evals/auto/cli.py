"""
Purpose: Command-line entry point for /auto-harness. Parses args, loads
         components.yaml, runs preflight, acquires a lock file, computes the
         baseline scalar from the component's existing TSV, creates a working
         branch, and drives evals.auto.loop.run(). On exit, releases the lock
         and prints a summary.

Public API: main(argv: list[str] | None = None) -> int;
            invoked via `python -m evals.auto.cli run <component> [...]`.

Upstream deps: stdlib argparse, os, pathlib, sys, time, json, yaml (via
               evals.runner dependency; we prefer pyyaml but fall back to a
               minimal parser if unavailable).

Downstream consumers: humans; CI (future).

Failure modes: preflight failures exit 2 with a printed reason. Lock contention
               exits 3. Other unhandled exceptions propagate.

Performance: CLI overhead negligible; the loop dominates wall time.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import git_ops
from . import loop as loop_mod
from . import preflight as preflight_mod
from . import runner_shim

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK_PATH = _REPO_ROOT / "evals" / ".auto-harness.lock"
_STATE_DIR = _REPO_ROOT / "evals" / "auto" / "state"
_COMPONENTS_YAML = _REPO_ROOT / "evals" / "auto" / "components.yaml"


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as e:  # pragma: no cover - pyyaml is in evals/requirements.txt
        raise RuntimeError(
            f"pyyaml not available: {e}. Install via `pip install -r evals/requirements.txt`."
        ) from e
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _acquire_lock(lock_path: Path) -> bool:
    """Create lock file atomically. Returns True on success, False if present."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} started={int(time.time())}\n")
        return True
    except Exception:
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass
        raise


def _release_lock(lock_path: Path) -> None:
    try:
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass


def _branch_name(component: str) -> str:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"auto-harness/{component}-{ts}"


def cmd_run(args: argparse.Namespace) -> int:
    components = _load_yaml(_COMPONENTS_YAML)
    pre = preflight_mod.run_preflight(_REPO_ROOT, args.component, components)
    if not pre["ok"]:
        print("preflight FAILED:", file=sys.stderr)
        for f in pre["failures"]:
            print(f"  - {f}", file=sys.stderr)
        return 2

    cfg = components.get(args.component) or {}
    max_iter = int(args.max_iterations or cfg.get("max_iterations") or 10)

    # Compute baseline from existing TSV.
    try:
        agg = runner_shim.baseline_from_tsv(_REPO_ROOT, args.component, pre["n_fixtures"])
    except ValueError as e:
        print(f"baseline computation failed: {e}", file=sys.stderr)
        return 2

    baseline = float(agg["metric"])
    pooled = float(agg["pooled_stdev"])
    baseline_rows = list(agg.get("rows") or [])
    print(f"baseline scalar = {baseline:.4f}  pooled_stdev = {pooled:.4f}")

    # Acquire lock.
    if not _acquire_lock(_LOCK_PATH):
        print(f"lock present at {_LOCK_PATH}; another loop may be running. "
              f"Remove the file only if you are sure no loop is active.",
              file=sys.stderr)
        return 3

    exit_code = 0
    try:
        # Create the working branch (unless --dry-run, in which case stay on
        # current branch and do NOT commit).
        if not args.dry_run:
            branch = _branch_name(args.component)
            git_ops.create_branch(_REPO_ROOT, branch)
            print(f"created branch: {branch}")
        else:
            branch = git_ops.current_branch(_REPO_ROOT)
            print(f"dry-run: staying on branch {branch}")

        state_file = _STATE_DIR / f"{branch.replace('/', '__')}.json"

        lcfg = loop_mod.LoopConfig(
            repo_root=_REPO_ROOT,
            component=args.component,
            component_cfg=cfg,
            max_iterations=1 if args.dry_run else max_iter,
            time_budget_sec=int(args.time_budget_sec),
            cost_budget_usd=float(args.cost_budget_usd),
            n_fixtures=int(pre["n_fixtures"]),
            baseline_metric=baseline,
            baseline_pooled_stdev=pooled,
            dry_run=args.dry_run,
            editor_model=args.editor_model,
            editor_timeout_sec=int(args.editor_timeout_sec),
            state_file=state_file,
            baseline_rows=baseline_rows,
        )

        result = loop_mod.run(lcfg)
        print("---- loop summary ----")
        print(f"  iterations: {result['iterations']}")
        print(f"  keeps:      {result['keeps']}")
        print(f"  reverts:    {result['reverts']}")
        print(f"  final:      {result['final_metric']:.4f}")
        print(f"  exit:       {result['reason']}")
        if not args.dry_run and result["keeps"] > 0:
            print(f"  branch:     {branch} (review + open PR manually; no auto-merge)")
    finally:
        _release_lock(_LOCK_PATH)

    return exit_code


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.auto.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Run the /auto-harness loop on a single component.")
    pr.add_argument("component", help="Component name as in evals/auto/components.yaml")
    pr.add_argument("--max-iterations", type=int, default=None,
                    help="Override the component's default max iterations.")
    pr.add_argument("--time-budget-sec", type=int, default=1800,
                    help="Wall-clock ceiling for the whole run. Default 1800s (30 min).")
    pr.add_argument("--cost-budget-usd", type=float, default=3.0,
                    help="Soft cost ceiling across editor + runner calls. Default 3.0.")
    pr.add_argument("--dry-run", action="store_true",
                    help="Run preflight, compute baseline, spawn editor ONCE, print the proposed diff, and exit without applying or committing.")
    pr.add_argument("--editor-model", default=None, help="Optional model override for the editor-agent.")
    pr.add_argument("--editor-timeout-sec", type=int, default=600,
                    help="Per-iteration editor-agent timeout. Default 600s.")
    pr.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
