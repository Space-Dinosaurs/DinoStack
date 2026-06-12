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
    17-column TSV appended at evals/results/auto-harness.tsv.
    Columns 15-17 (signed_rank_p, effect_mean_delta, nonzero_pairs) carry
    the stats.keep_decision output. Empty string on pre-runner rows.

Keep rule:
    An edit is kept only if stats.keep_decision(pair_deltas(...)) returns
    keep=True: one-sided sign-flip permutation test (alpha=0.05) AND mean
    per-fixture improvement >= EPSILON (0.02) AND >= 5 nonzero pairs.
    pooled_stdev is retained in the ledger as an observability metric only.

Upstream deps: stdlib time, pathlib, dataclasses, csv, json; sibling modules
               editor, apply, git_ops, runner_shim, overfitting, state, stats;
               evals.runner.tsv_writer (_ondisk_header).

Downstream consumers: evals.auto.cli.

Failure modes: a failing subprocess or validation error is recorded as an
               iteration with decision=reject and the loop continues. Auth
               errors ("401", "invalid_api_key") halt the loop with reason
               "auth_fatal". Other fatal exceptions propagate.
               _write_editor_log writes apply-failure debug logs to
               evals/auto/editor-logs/ (best-effort; IO errors silently
               swallowed so the loop never crashes on a log write).

Performance: dominated by the per-iteration runner cost (9 runs per fixture
             x N fixtures); the loop infrastructure itself is negligible.
"""
from __future__ import annotations

import csv
import json
import math
import re
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
from . import stats
from evals.runner.tsv_writer import _ondisk_header

_LEDGER_PATH_PARTS = ("evals", "results", "auto-harness.tsv")

# Output format instructions injected into program.md via {{OUTPUT_FORMAT_INSTRUCTIONS}}.
_DIFF_MODE_INSTRUCTIONS = """\
Respond with EXACTLY these two elements, in order, nothing else:

1. A single fenced diff block in unified-diff format that `git apply`
   can consume. File headers must use `a/` and `b/` prefixes (standard
   `git diff` output).

   CRITICAL - context lines must be verbatim:
   Every line WITHOUT a leading `+` or `-` (i.e. every context line,
   including the space prefix) MUST be copied BYTE-FOR-BYTE from the
   file exactly as Read. Do NOT paraphrase, reword, reformat, trim
   trailing whitespace, or alter a single character of any context
   line. Any deviation causes `git apply` to reject the patch.

   Example:

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


_FENCE_RE = re.compile(r'^```')


def _normalise_headings(text: str) -> str:
    """Normalise markdown heading lines in prose sections of editor output.

    Only touches lines outside fenced code blocks so diff and file content
    are preserved verbatim. Converts ``## Foo`` and ``**Foo**`` lines to
    plain lowercase text so downstream extractors match regardless of LLM
    formatting choice.
    """
    out: list = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n\r")
        if _FENCE_RE.match(bare.strip()):
            in_fence = not in_fence
            out.append(line)
        elif not in_fence and re.match(r'^(?:#{1,6}\s|\*{1,2}\S)', bare.strip()):
            out.append(apply_mod.normalise_heading(bare) + "\n")
        else:
            out.append(line)
    return "".join(out)


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
    "signed_rank_p",
    "effect_mean_delta",
    "nonzero_pairs",
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
    baseline_rows: list = field(default_factory=list)


def _ledger_path(repo_root: Path) -> Path:
    return repo_root.joinpath(*_LEDGER_PATH_PARTS)


def _append_ledger_row(repo_root: Path, row: Dict[str, Any]) -> Path:
    path = _ledger_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    missing = [c for c in LEDGER_HEADER if c not in row]
    if missing:
        raise ValueError(f"ledger row missing columns: {missing}")
    ondisk = _ondisk_header(path)
    if ondisk is None:
        # New or empty file - write header then the row.
        with path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t", lineterminator="\n")
            w.writerow(LEDGER_HEADER)
            w.writerow([str(row[c]) for c in LEDGER_HEADER])
    else:
        if ondisk != LEDGER_HEADER:
            raise ValueError(
                f"Ledger schema mismatch: on-disk header has {len(ondisk)} columns, "
                f"expected {len(LEDGER_HEADER)}. "
                f"Run `python -m evals.auto.migrate_tsv` to migrate the file."
            )
        with path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t", lineterminator="\n")
            w.writerow([str(row[c]) for c in LEDGER_HEADER])
    return path


def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fmt(x: float) -> str:
    return f"{x:.6f}"


def _is_auth_fatal(stderr: str) -> bool:
    s = (stderr or "").lower()
    return ("401" in s) or ("invalid_api_key" in s) or ("unauthorized" in s)


def _write_editor_log(
    repo_root: Path,
    component: str,
    iteration: int,
    ts: str,
    raw_editor_text: str,
    extracted_diff: str,
    label: str = "apply_failed",
) -> None:
    """Best-effort: write editor output to editor-logs/ for debugging.

    Writes <component>-iter<N>-<ts>-<label>.txt under evals/auto/editor-logs/.
    Silently swallows any IO error so the loop is never crashed by logging.
    """
    try:
        log_dir = repo_root / "evals" / "auto" / "editor-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = ts.replace(":", "-")
        filename = f"{component}-iter{iteration}-{safe_ts}-{label}.txt"
        path = log_dir / filename
        separator = "=" * 72
        content = (
            f"component: {component}\n"
            f"iteration: {iteration}\n"
            f"timestamp: {ts}\n"
            f"label: {label}\n"
            f"\n{separator}\n"
            f"EXTRACTED DIFF\n"
            f"{separator}\n"
            f"{extracted_diff or '(empty)'}\n"
            f"\n{separator}\n"
            f"RAW EDITOR TEXT\n"
            f"{separator}\n"
            f"{raw_editor_text or '(empty)'}\n"
        )
        path.write_text(content, encoding="utf-8")
    except Exception:  # best-effort; never crash the loop on a log write
        pass


def _time_left(start: float, budget: int) -> float:
    return budget - (time.time() - start)


def _budget_exhausted(cost_spent: float, budget: float) -> bool:
    return budget > 0 and cost_spent >= budget


def _preserve_results_across_reset(repo_root: Path) -> Dict[Path, str]:
    """Read current content of result TSVs and runlogs so they survive
    git reset --hard. Returns a dict of {path: content}."""
    preserved: Dict[Path, str] = {}
    results_dir = repo_root / "evals" / "results"
    if results_dir.exists():
        for path in results_dir.glob("*.tsv"):
            preserved[path] = path.read_text(encoding="utf-8")
        for path in results_dir.glob("*.runlog.jsonl"):
            preserved[path] = path.read_text(encoding="utf-8")
    return preserved


def _restore_results(repo_root: Path, preserved: Dict[Path, str]) -> None:
    """Write preserved content back after git reset --hard."""
    for path, content in preserved.items():
        path.write_text(content, encoding="utf-8")


_NO_SIGNAL_LINE = "  (no dimension signal available for this component)"
_BOTTOM_K = 3
# Minimum number of fixture rows to scan when computing dimension averages.
# `n_scan = max(n_fixtures, _DIMENSION_SCAN_ROWS)` floors the read at this many
# rows so very small corpora still get a useful sample.
_DIMENSION_SCAN_ROWS = 20
# Dimensions whose mean score is at or above this threshold are considered
# saturated (no addressable headroom) and excluded from the surfaced signal.
_SATURATION_THRESHOLD = 0.95
# Dimensions backed by fewer than this many non-vacuous runs are statistical
# noise (one fixture's quirk, not a corpus pattern) and excluded.
_MIN_RUN_COUNT = 2


def _build_dimension_signal(
    repo_root: Path,
    component: str,
    n_fixtures: int,
    editable_paths: List[str],
) -> str:
    """Compute corpus-level per-dimension mean scores from the component's TSV.

    Walks diagnostic_json.per_run[*].diagnostic for each row:
      - Nested dict dimensions: any key whose value is a dict containing a
        numeric 'score' key is treated as a dimension. If the dict also has
        vacuous=True the run is excluded from that dimension's average.
      - Flat float dimensions: any key whose value is a finite float in
        [0.0, 1.0] is treated as a flat dimension (e.g. conductor's
        decision_hit). These have no vacuous flag; all runs are counted.

    Only dimensions whose name appears as a literal substring in at least one
    editable file are included (prevents hallucinated section names reaching the
    editor). Substring match is case-insensitive against the raw snake_case name.

    Returns the bottom-K=3 worst-scoring qualifying dimensions formatted as
    lines like:
      - <dim_name>: avg <score> across <count> non-vacuous runs

    Falls back to _NO_SIGNAL_LINE when no qualifying dimensions exist.
    """
    tsv_path = repo_root / "evals" / "results" / f"{component}.tsv"
    n_scan = max(n_fixtures, _DIMENSION_SCAN_ROWS)
    rows = runner_shim._read_last_rows(tsv_path, n_scan)
    if not rows:
        return _NO_SIGNAL_LINE

    # Read editable file contents once (lowercase).
    editable_texts: List[str] = []
    for rel_path in editable_paths:
        abs_path = repo_root / rel_path
        if abs_path.exists():
            try:
                editable_texts.append(abs_path.read_text(encoding="utf-8").lower())
            except OSError:
                pass

    def _in_editable(dim_name: str) -> bool:
        # Try multiple casing/separator variants to handle the gap between
        # scorer-internal snake_case names and human-facing prompt sections.
        # E.g. dim "open_questions" should match "Open questions" / "open
        # questions" / "open-questions" / "openQuestions" / "open_questions".
        snake = dim_name.lower()
        variants = {
            snake,
            snake.replace("_", " "),
            snake.replace("_", "-"),
            snake.replace("_", ""),
        }
        return any(any(v in text for v in variants) for text in editable_texts)

    # Accumulate: dim_name -> list of (score, count) per qualifying run.
    # Using parallel lists: dim_scores[dim] = list of float scores from non-vacuous runs.
    dim_scores: Dict[str, List[float]] = {}

    for row in rows:
        raw = row.get("diagnostic_json") or ""
        if not raw:
            continue
        try:
            top = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for pr in top.get("per_run") or []:
            diag = pr.get("diagnostic")
            if not isinstance(diag, dict):
                continue
            for dim_name, val in diag.items():
                if isinstance(val, dict):
                    # Nested dict dimension - must have numeric 'score'.
                    score = val.get("score")
                    if not isinstance(score, (int, float)):
                        continue
                    if not math.isfinite(float(score)):
                        continue
                    # Skip vacuous runs for this dimension.
                    if val.get("vacuous") is True:
                        continue
                    if dim_name not in dim_scores:
                        dim_scores[dim_name] = []
                    dim_scores[dim_name].append(float(score))
                elif isinstance(val, float) and math.isfinite(val) and 0.0 <= val <= 1.0:
                    # Flat float dimension (e.g. conductor's decision_hit).
                    if dim_name not in dim_scores:
                        dim_scores[dim_name] = []
                    dim_scores[dim_name].append(val)

    if not dim_scores:
        return _NO_SIGNAL_LINE

    # Filter to dimensions that appear in editable files.
    qualifying: Dict[str, List[float]] = {
        dim: scores
        for dim, scores in dim_scores.items()
        if scores and _in_editable(dim)
    }

    if not qualifying:
        return _NO_SIGNAL_LINE

    # Compute mean per dimension. Filter out saturated dims (no addressable
    # headroom) and statistical-noise dims (single-run signals).
    averages = [(dim, sum(sc) / len(sc), len(sc)) for dim, sc in qualifying.items()]
    averages = [
        (dim, avg, count)
        for dim, avg, count in averages
        if avg < _SATURATION_THRESHOLD and count >= _MIN_RUN_COUNT
    ]
    if not averages:
        return _NO_SIGNAL_LINE

    averages.sort(key=lambda t: t[1])
    bottom = averages[:_BOTTOM_K]

    lines = [
        f"  - {dim}: avg {avg:.3f} across {count} non-vacuous runs"
        for dim, avg, count in bottom
    ]
    return "\n".join(lines)


def _build_editor_context(cfg: LoopConfig) -> Dict[str, Any]:
    editable = cfg.component_cfg.get("editable") or []
    locked = cfg.component_cfg.get("locked") or []
    is_whole_file = cfg.component_cfg.get("whole_file_replacement", False)
    dimension_signal = _build_dimension_signal(
        cfg.repo_root,
        cfg.component,
        cfg.n_fixtures,
        list(editable),
    )
    return {
        "COMPONENT": cfg.component,
        "EDITABLE_FILES": "\n".join(f"  - {p}" for p in editable),
        "LOCKED_FILES": "\n".join(f"  - {p}" for p in locked),
        "BASELINE_METRIC": _fmt(cfg.baseline_metric),
        "POOLED_STDEV": _fmt(cfg.baseline_pooled_stdev),
        "EPSILON": _fmt(stats.EPSILON),
        "MAX_EDIT_LOC": str(cfg.component_cfg.get("max_edit_loc", 20)),
        "WHOLE_FILE_MODE": "true" if is_whole_file else "false",
        "EDITOR_TIMEOUT_SEC": str(cfg.editor_timeout_sec),
        "OUTPUT_FORMAT_INSTRUCTIONS": _format_instructions(cfg.component, is_whole_file),
        "DIMENSION_SIGNAL": dimension_signal,
    }


def _one_iteration(
    cfg: LoopConfig,
    iteration: int,
    base_metric: float,
    base_pooled_stdev: float,
    base_commit: str,
    cumulative_cost: float,
    base_rows: list,
) -> Dict[str, Any]:
    """Run one editor -> apply -> eval -> decide cycle.

    Returns a dict with the ledger row plus control fields:
        {row, decision, new_metric, new_pooled_stdev, new_rows, cost_usd, fatal}
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
                "signed_rank_p": "",
                "effect_mean_delta": "",
                "nonzero_pairs": "",
            },
            "decision": "halt",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "new_rows": base_rows,
            "cost_usd": cost_this,
            "fatal": True,
        }

    raw_text = er.get("text") or ""
    is_whole_file = cfg.component_cfg.get("whole_file_replacement", False)

    # Fix 4: extract the diff BEFORE _normalise_headings so that diff-content
    # lines (e.g. `+```bash`) never pass through the heading normalizer and
    # cannot flip its fence toggle, corrupting hunk content.
    if is_whole_file:
        extracted = apply_mod.extract_whole_file(raw_text)
        # Normalise headings only after extraction - whole-file mode doesn't
        # have diff lines to worry about, but be consistent.
        text = _normalise_headings(raw_text)
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
        # Extract diff from raw text before normalisation touches it.
        diff = apply_mod.extract_diff(raw_text) or ""
        # Now normalise headings in the full text (used for overfitting verdict
        # parsing); the diff is already captured so normalisation cannot corrupt it.
        text = _normalise_headings(raw_text)
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
        # Fix 3: log raw editor output for all pre-apply rejections so
        # extraction failures (empty_or_noop_diff, etc.) are observable.
        _ts_now = _now_utc_iso()
        _extracted_for_log = new_content if is_whole_file else diff
        _write_editor_log(
            cfg.repo_root,
            cfg.component,
            iteration,
            _ts_now,
            raw_text,
            _extracted_for_log,
            label=f"pre_apply_reject_{reject_reason[:40]}",
        )
        return {
            "row": {
                "timestamp_utc": _ts_now,
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
                "signed_rank_p": "",
                "effect_mean_delta": "",
                "nonzero_pairs": "",
            },
            "decision": "reject",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "new_rows": base_rows,
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
                "signed_rank_p": "",
                "effect_mean_delta": "",
                "nonzero_pairs": "",
            },
            "decision": "dry_run_skip_apply",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "new_rows": base_rows,
            "cost_usd": cost_this,
            "fatal": False,
        }

    if is_whole_file:
        ar = apply_mod.apply_whole_file(cfg.repo_root, path, new_content)
    else:
        ar = apply_mod.apply_diff(cfg.repo_root, diff)
    if not ar["ok"]:
        # Fix 3: write the extracted diff + raw editor text so corruption is visible.
        _ts_apply = _now_utc_iso()
        _extracted_for_log = new_content if is_whole_file else diff
        _write_editor_log(
            cfg.repo_root,
            cfg.component,
            iteration,
            _ts_apply,
            raw_text,
            _extracted_for_log,
            label="apply_failed",
        )
        return {
            "row": {
                "timestamp_utc": _ts_apply,
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
                "signed_rank_p": "",
                "effect_mean_delta": "",
                "nonzero_pairs": "",
            },
            "decision": "reject",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "new_rows": base_rows,
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
        preserved = _preserve_results_across_reset(cfg.repo_root)
        git_ops.reset_hard(cfg.repo_root, base_commit)
        _restore_results(cfg.repo_root, preserved)
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
                "signed_rank_p": "",
                "effect_mean_delta": "",
                "nonzero_pairs": "",
            },
            "decision": "revert",
            "new_metric": base_metric,
            "new_pooled_stdev": base_pooled_stdev,
            "new_rows": base_rows,
            "cost_usd": cost_this,
            "fatal": False,
        }

    head_commit = str(rr.get("head_commit") or "")
    agg = runner_shim.aggregate_latest(
        cfg.repo_root,
        cfg.component,
        cfg.n_fixtures,
        expected_commit=head_commit if head_commit else None,
    )
    new_metric = float(agg["metric"])
    new_pooled_stdev = float(agg["pooled_stdev"])
    new_rows: list = list(agg.get("rows") or [])
    runner_cost = float(agg.get("cost_usd") or 0.0)
    cost_this += runner_cost

    delta = new_metric - base_metric
    deltas = stats.pair_deltas(base_rows, new_rows, key="fixture_id")
    decision_result = stats.keep_decision(deltas)
    keep = decision_result["keep"]

    p_value = decision_result["p_value"]
    signed_rank_p_str = _fmt(p_value) if p_value is not None else ""
    effect_mean_delta_str = _fmt(decision_result["effect_mean_delta"])
    nonzero_pairs_str = str(decision_result["n_nonzero"])

    if keep:
        decision = "keep"
        reason = decision_result["reason"]
        # The proposal is already committed on the branch; nothing else to do.
    else:
        decision = "revert"
        reason = decision_result["reason"]
        preserved = _preserve_results_across_reset(cfg.repo_root)
        git_ops.reset_hard(cfg.repo_root, base_commit)
        _restore_results(cfg.repo_root, preserved)

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
            "signed_rank_p": signed_rank_p_str,
            "effect_mean_delta": effect_mean_delta_str,
            "nonzero_pairs": nonzero_pairs_str,
        },
        "decision": decision,
        "new_metric": new_metric if keep else base_metric,
        "new_pooled_stdev": new_pooled_stdev if keep else base_pooled_stdev,
        "new_rows": new_rows if keep else base_rows,
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

    cur_rows: list = list(cfg.baseline_rows)

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
            base_rows=cur_rows,
        )
        _append_ledger_row(cfg.repo_root, out["row"])
        cumulative_cost += float(out.get("cost_usd") or 0.0)

        decision = out["decision"]
        if decision == "keep":
            keeps += 1
            cur_metric = float(out["new_metric"])
            cur_pooled = float(out["new_pooled_stdev"])
            cur_rows = list(out.get("new_rows") or cur_rows)
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
