"""
Purpose: Drive the /auto-harness iteration state machine for one component:
         spawn editor -> extract/validate diff -> apply -> run eval ->
         decide keep-or-revert -> commit or reset -> append ledger row.
         Stops on max_iterations, time budget, cost budget, plateau (3
         consecutive no-op or below-threshold), or editor auth/fatal errors.

Public API:
    run(cfg: LoopConfig) -> dict with keys {ok, reason, iterations, keeps,
                                            reverts, final_metric}

Ledger:
    14-column TSV appended at evals/results/auto-harness.tsv.

Upstream deps: stdlib time, pathlib, dataclasses, csv, json; sibling modules
               editor, apply, git_ops, runner_shim, overfitting, state.

Downstream consumers: evals.auto.cli.

Failure modes: a failing subprocess or validation error is recorded as an
               iteration with decision=reject and the loop continues. Auth
               errors ("401", "invalid_api_key") halt the loop with reason
               "auth_fatal". Other fatal exceptions propagate.

Performance: dominated by the per-iteration runner cost (3 runs per fixture
             x N fixtures); the loop infrastructure itself is negligible.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import apply as apply_mod
from . import editor as editor_mod
from . import git_ops
from . import overfitting as overfit
from . import runner_shim
from . import state as state_mod

_LEDGER_PATH_PARTS = ("evals", "results", "auto-harness.tsv")

# Output format instructions injected into program.md via {{OUTPUT_FORMAT_INSTRUCTIONS}}.
_DIFF_MODE_INSTRUCTIONS = """\
Respond with EXACTLY these two elements, in order, nothing else:

1. A single fenced diff block in unified-diff format that `git apply`
   can consume. File headers must use `a/` and `b/` prefixes (standard
   `git diff` output). Example:

```diff
--- a/content/agents/skeptic.md
+++ b/content/agents/skeptic.md
@@ -10,3 +10,4 @@
 existing line
 existing line
+new line added
 existing line
```

2. On its own line, immediately after the diff block:

```
Overfitting Rule verdict: yes|no because <one-sentence rationale>
```

If you cannot propose a plausible improvement this iteration, output:

```diff
```

(an empty diff block) and

```
Overfitting Rule verdict: no because no-op proposed
```

The loop will record a no-op and advance. A no-op is better than an
overfitting edit."""

_WHOLE_FILE_MODE_INSTRUCTIONS = """\
When editing large command files, output the COMPLETE new file content.
Do NOT use unified-diff format. Do NOT omit unchanged sections.

Respond with EXACTLY these two elements, in order, nothing else:

1. A single fenced markdown block containing the full rewritten file.
   The first non-empty line inside the block must be the file path,
   e.g. `content/commands/implement-ticket.md`. The rest is the full
   file content.

   Example:

   ```markdown
   content/commands/implement-ticket.md
   # File header...
   ...full content...
   ```

2. On its own line, immediately after the markdown block:

```
Overfitting Rule verdict: yes|no because <one-sentence rationale>
```

If you cannot propose a plausible improvement, output an empty markdown
block (` ```markdown\n``` `) and

```
Overfitting Rule verdict: no because no-op proposed
```

The loop will record a no-op and advance. A no-op is better than an
overfitting edit."""


def _format_instructions(component: str, whole_file_mode: bool) -> str:
    """Return the output-format instructions for the editor program template."""
    return _WHOLE_FILE_MODE_INSTRUCTIONS if whole_file_mode else _DIFF_MODE_INSTRUCTIONS


LEDGER_HEADER: tuple = (
    "timestamp_utc",
    "component",
    "branch",
    "iteration",
    "base_commit",
    "proposed_commit",
    "baseline_metric",
    "new_metric",
    "delta",
    "pooled_stdev",
    "decision",
    "reason",
    "overfitting_verdict",
    "cost_usd_cumulative",
)


@dataclass
class LoopConfig:
    repo_root: Path
    component: str
    component_cfg: Dict[str, Any]
    max_iterations: int
    time_budget_sec: int
    cost_budget_usd: float
    n_fixtures: int
    baseline_metric: float
    baseline_pooled_stdev: float
    dry_run: bool = False
    editor_model: Optional[str] = None
    editor_timeout_sec: int = 600
    state_file: Optional[Path] = None


def _ledger_path(repo_root: Path) -> Path:
    return repo_root.joinpath(*_LEDGER_PATH_PARTS)


def _append_ledger_row(repo_root: Path, row: Dict[str, Any]) -> Path:
    path = _ledger_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    missing = [c for c in LEDGER_HEADER if c not in row]
    if missing:
        raise ValueError(f"ledger row missing columns: {missing}")
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if is_new:
            w.writerow(LEDGER_HEADER)
        w.writerow([str(row[c]) for c in LEDGER_HEADER])
    return path


def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fmt(x: float) -> str:
    return f"{x:.6f}"


def _keep_delta_threshold(pooled_stdev: float) -> float:
    return max(pooled_stdev, 0.02)


def _is_auth_fatal(stderr: str) -> bool:
    s = (stderr or "").lower()
    return ("401" in s) or ("invalid_api_key" in s) or ("unauthorized" in s)


def _time_left(start: float, budget: int) -> float:
    return budget - (time.time() - start)


def _budget_exhausted(cost_spent: float, budget: float) -> bool:
    return budget > 0 and cost_spent >= budget


def _build_editor_context(cfg: LoopConfig) -> Dict[str, Any]:
    editable = cfg.component_cfg.get("editable") or []
    locked = cfg.component_cfg.get("locked") or []
    is_whole_file = cfg.component_cfg.get("whole_file_replacement", False)
    return {
        "COMPONENT": cfg.component,
        "EDITABLE_FILES": "\n".join(f"  - {p}" for p in editable),
        "LOCKED_FILES": "\n".join(f"  - {p}" for p in locked),
        "BASELINE_METRIC": _fmt(cfg.baseline_metric),
        "POOLED_STDEV": _fmt(cfg.baseline_pooled_stdev),
        "MAX_EDIT_LOC": str(cfg.component_cfg.get("max_edit_loc", 20)),
        "WHOLE_FILE_MODE": "true" if is_whole_file else "false",
        "EDITOR_TIMEOUT_SEC": str(cfg.editor_timeout_sec),
        "OUTPUT_FORMAT_INSTRUCTIONS": _format_instructions(cfg.component, is_whole_file),
    }


def _one_iteration(
    cfg: LoopConfig,
    iteration: int,
    base_metric: float,
    base_pooled_stdev: float,
    base_commit: str,
    cumulative_cost: float,
) -> Dict[str, Any]:
    """Run one editor -> apply -> eval -> decide cycle.

    Returns a dict with the ledger row plus control fields:
        {row, decision, new_metric, new_pooled_stdev, cost_usd, fatal}
    """
    # Build and dispatch editor brief.
    brief = editor_mod.build_brief(editor_mod.load_program_template(), _build_editor_context(cfg))
    er = editor_mod.spawn_editor(
        cfg.repo_root, brief, timeout_sec=cfg.editor_timeout_sec, model=cfg.editor_model
    )
    cost_this = float(er.get("cost_usd") or 0.0)

    # Fatal auth -> short-circuit the loop entirely.
    if not er["ok"] and _is_auth_fatal(str(er.get("stderr", ""))):
        return {
            "row": {
                "timestamp_utc": _now_utc_iso(),
                "component": cfg.component,
                "branch": git_ops.current_branch(cfg.repo_root),
                "iteration": iteration,
                "base_commit": base_commit,
                "proposed_commit": "",
                "baseline_metric": _fmt(base_metric),
                "new_metric": "",
                "delta": "",
                "pooled_stdev": _fmt(base_pooled_stdev),
                "decision": "halt",
                "reason": "editor_auth_fatal",
                "overfitting_verdict": "",
                "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
            },
            "decision": "halt",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "cost_usd": cost_this,
            "fatal": True,
        }

    text = er.get("text") or ""
    is_whole_file = cfg.component_cfg.get("whole_file_replacement", False)

    if is_whole_file:
        extracted = apply_mod.extract_whole_file(text)
        path = ""
        new_content = ""
        if extracted:
            path, new_content = extracted
        diff_for_overfit = new_content
        editable_paths = list(cfg.component_cfg.get("editable") or [])
        locked_paths = list(cfg.component_cfg.get("locked") or [])
        validation = {"ok": True, "reason": "", "paths": []}
        loc = 0
        if extracted is not None and path:
            validation = apply_mod.validate_single_path(
                path, editable=editable_paths, locked=locked_paths
            )
            loc = apply_mod.count_changed_loc_for_whole_file(
                cfg.repo_root, path, new_content
            )
    else:
        diff = apply_mod.extract_diff(text) or ""
        diff_for_overfit = diff
        validation = apply_mod.validate_paths(
            diff,
            editable=list(cfg.component_cfg.get("editable") or []),
            locked=list(cfg.component_cfg.get("locked") or []),
        )
        loc = apply_mod.count_changed_loc(diff)

    max_loc = int(cfg.component_cfg.get("max_edit_loc", 20))

    # Overfitting check: parse verdict line AND scan both rationale and diff.
    verdict = overfit.parse_verdict(text, diff=diff_for_overfit)

    # Pre-apply decision: if any of these fail, record reject and skip runner.
    reject_reason = ""
    if not er["ok"]:
        reject_reason = f"editor_failed_rc{er.get('returncode')}"
    elif is_whole_file:
        if extracted is None or not new_content.strip():
            reject_reason = "empty_or_noop_diff"
        elif not path:
            reject_reason = "whole_file_missing_path"
        elif verdict["verdict"] != "pass":
            reject_reason = f"overfitting:{verdict.get('reason','')}"
        elif not validation["ok"]:
            reject_reason = f"validation:{validation.get('reason','')}"
        elif loc > max_loc:
            reject_reason = f"loc_exceeds_budget:{loc}>{max_loc}"
    else:
        if not diff.strip():
            reject_reason = "empty_or_noop_diff"
        elif verdict["verdict"] != "pass":
            reject_reason = f"overfitting:{verdict.get('reason','')}"
        elif not validation["ok"]:
            reject_reason = f"validation:{validation.get('reason','')}"
        elif loc > max_loc:
            reject_reason = f"loc_exceeds_budget:{loc}>{max_loc}"

    if reject_reason:
        return {
            "row": {
                "timestamp_utc": _now_utc_iso(),
                "component": cfg.component,
                "branch": git_ops.current_branch(cfg.repo_root),
                "iteration": iteration,
                "base_commit": base_commit,
                "proposed_commit": "",
                "baseline_metric": _fmt(base_metric),
                "new_metric": "",
                "delta": "",
                "pooled_stdev": _fmt(base_pooled_stdev),
                "decision": "reject",
                "reason": reject_reason,
                "overfitting_verdict": verdict["verdict"],
                "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
            },
            "decision": "reject",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "cost_usd": cost_this,
            "fatal": False,
        }

    if cfg.dry_run:
        if is_whole_file:
            print("----- DRY RUN: PROPOSED WHOLE FILE -----")
            print(f"Path: {path}")
            print(new_content)
        else:
            print("----- DRY RUN: PROPOSED DIFF -----")
            print(diff)
        print("----- Overfitting verdict:", verdict["verdict"], "-----")
        return {
            "row": {
                "timestamp_utc": _now_utc_iso(),
                "component": cfg.component,
                "branch": git_ops.current_branch(cfg.repo_root),
                "iteration": iteration,
                "base_commit": base_commit,
                "proposed_commit": "",
                "baseline_metric": _fmt(base_metric),
                "new_metric": "",
                "delta": "",
                "pooled_stdev": _fmt(base_pooled_stdev),
                "decision": "dry_run_skip_apply",
                "reason": f"dry_run:loc={loc}:paths={','.join(validation['paths'])}",
                "overfitting_verdict": verdict["verdict"],
                "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
            },
            "decision": "dry_run_skip_apply",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "cost_usd": cost_this,
            "fatal": False,
        }

    if is_whole_file:
        ar = apply_mod.apply_whole_file(cfg.repo_root, path, new_content)
    else:
        ar = apply_mod.apply_diff(cfg.repo_root, diff)
    if not ar["ok"]:
        return {
            "row": {
                "timestamp_utc": _now_utc_iso(),
                "component": cfg.component,
                "branch": git_ops.current_branch(cfg.repo_root),
                "iteration": iteration,
                "base_commit": base_commit,
                "proposed_commit": "",
                "baseline_metric": _fmt(base_metric),
                "new_metric": "",
                "delta": "",
                "pooled_stdev": _fmt(base_pooled_stdev),
                "decision": "reject",
                "reason": f"apply_failed:{ar.get('reason','')}:{(ar.get('stderr') or '')[:200]}",
                "overfitting_verdict": verdict["verdict"],
                "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
            },
            "decision": "reject",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "cost_usd": cost_this,
            "fatal": False,
        }

    # Commit the staged change on the auto-harness branch so we have a SHA
    # to either keep or revert.
    commit_msg = (
        f"auto-harness({cfg.component}): iteration {iteration} proposal\n\n"
        f"Scores inform; they do not justify. Proposed by editor-agent under\n"
        f"the Overfitting Rule (evals/OVERFITTING-RULE.md).\n"
    )
    proposed_sha = git_ops.commit_all(cfg.repo_root, commit_msg)

    # Run the eval.
    rr = runner_shim.run_component(cfg.repo_root, cfg.component)
    if not rr["ok"]:
        # Revert the proposed commit; record reject.
        git_ops.reset_hard(cfg.repo_root, base_commit)
        return {
            "row": {
                "timestamp_utc": _now_utc_iso(),
                "component": cfg.component,
                "branch": git_ops.current_branch(cfg.repo_root),
                "iteration": iteration,
                "base_commit": base_commit,
                "proposed_commit": proposed_sha,
                "baseline_metric": _fmt(base_metric),
                "new_metric": "",
                "delta": "",
                "pooled_stdev": _fmt(base_pooled_stdev),
                "decision": "revert",
                "reason": f"runner_failed_rc{rr.get('returncode')}: {(rr.get('stderr') or '')[:200]}",
                "overfitting_verdict": verdict["verdict"],
                "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
            },
            "decision": "revert",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "cost_usd": cost_this,
            "fatal": False,
        }

    agg = runner_shim.aggregate_latest(cfg.repo_root, cfg.component, cfg.n_fixtures)
    new_metric = float(agg["metric"])
    new_pooled_stdev = float(agg["pooled_stdev"])
    runner_cost = float(agg.get("cost_usd") or 0.0)
    cost_this += runner_cost

    delta = new_metric - base_metric
    threshold = _keep_delta_threshold(max(new_pooled_stdev, base_pooled_stdev))
    keep = delta >= threshold

    if keep:
        decision = "keep"
        reason = f"delta={delta:.4f}>=threshold={threshold:.4f}"
        # The proposal is already committed on the branch; nothing else to do.
    else:
        decision = "revert"
        reason = f"delta={delta:.4f}<threshold={threshold:.4f}"
        git_ops.reset_hard(cfg.repo_root, base_commit)

    return {
        "row": {
            "timestamp_utc": _now_utc_iso(),
            "component": cfg.component,
            "branch": git_ops.current_branch(cfg.repo_root),
            "iteration": iteration,
            "base_commit": base_commit,
            "proposed_commit": proposed_sha,
            "baseline_metric": _fmt(base_metric),
            "new_metric": _fmt(new_metric),
            "delta": _fmt(delta),
            "pooled_stdev": _fmt(new_pooled_stdev),
            "decision": decision,
            "reason": reason,
            "overfitting_verdict": verdict["verdict"],
            "cost_usd_cumulative": _fmt(cumulative_cost + cost_this),
        },
        "decision": decision,
        "new_metric": new_metric if keep else base_metric,
        "new_pooled_stdev": new_pooled_stdev if keep else base_pooled_stdev,
        "cost_usd": cost_this,
        "fatal": False,
    }


def run(cfg: LoopConfig) -> Dict[str, Any]:
    start = time.time()
    iterations = 0
    keeps = 0
    reverts = 0
    plateau_streak = 0
    cumulative_cost = 0.0
    cur_metric = cfg.baseline_metric
    cur_pooled = cfg.baseline_pooled_stdev
    cur_base_commit = git_ops.head_sha(cfg.repo_root)

    # Persist initial state.
    if cfg.state_file is not None:
        st = state_mod.new_state(
            branch=git_ops.current_branch(cfg.repo_root),
            baseline=cfg.baseline_metric,
            component=cfg.component,
            max_iterations=cfg.max_iterations,
            time_budget_sec=cfg.time_budget_sec,
            cost_budget_usd=cfg.cost_budget_usd,
        )
        state_mod.save(cfg.state_file, st)

    halt_reason = ""
    while iterations < cfg.max_iterations:
        if _time_left(start, cfg.time_budget_sec) <= 0:
            halt_reason = "time_budget_exhausted"
            break
        if _budget_exhausted(cumulative_cost, cfg.cost_budget_usd):
            halt_reason = "cost_budget_exhausted"
            break

        iterations += 1
        out = _one_iteration(
            cfg,
            iteration=iterations,
            base_metric=cur_metric,
            base_pooled_stdev=cur_pooled,
            base_commit=cur_base_commit,
            cumulative_cost=cumulative_cost,
        )
        _append_ledger_row(cfg.repo_root, out["row"])
        cumulative_cost += float(out.get("cost_usd") or 0.0)

        decision = out["decision"]
        if decision == "keep":
            keeps += 1
            cur_metric = float(out["new_metric"])
            cur_pooled = float(out["new_pooled_stdev"])
            cur_base_commit = git_ops.head_sha(cfg.repo_root)
            plateau_streak = 0
        elif decision == "revert":
            reverts += 1
            plateau_streak += 1
        elif decision == "reject":
            plateau_streak += 1
        elif decision == "dry_run_skip_apply":
            # In dry-run we do exactly one iteration and exit.
            halt_reason = "dry_run_complete"
            break
        elif decision == "halt":
            halt_reason = out["row"].get("reason", "halt")
            break

        # Update state snapshot.
        if cfg.state_file is not None:
            try:
                st = state_mod.load(cfg.state_file)
            except FileNotFoundError:
                st = state_mod.new_state(
                    branch=git_ops.current_branch(cfg.repo_root),
                    baseline=cfg.baseline_metric,
                    component=cfg.component,
                    max_iterations=cfg.max_iterations,
                    time_budget_sec=cfg.time_budget_sec,
                    cost_budget_usd=cfg.cost_budget_usd,
                )
            st["iteration"] = iterations
            st["last_kept_metric"] = cur_metric
            st["cost_spent_usd"] = cumulative_cost
            st["keeps"] = keeps
            st["reverts"] = reverts
            st["plateau_streak"] = plateau_streak
            st["history"].append({
                "iteration": iterations,
                "decision": decision,
                "delta": out["row"].get("delta", ""),
                "metric_after": cur_metric,
            })
            state_mod.save(cfg.state_file, st)

        if plateau_streak >= 3:
            halt_reason = "plateau_3_consecutive"
            break

    return {
        "ok": True,
        "reason": halt_reason or "max_iterations_reached",
        "iterations": iterations,
        "keeps": keeps,
        "reverts": reverts,
        "final_metric": cur_metric,
        "cost_usd": cumulative_cost,
    }
