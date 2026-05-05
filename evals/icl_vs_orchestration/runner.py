"""
Purpose: Orchestration loop for the ICL-vs-orchestration eval. Iterates over
         corpus tickets x conditions, invokes each condition adapter, scores
         results via the scorer registry, writes per-ticket results atomically,
         tracks cost with the cost gate, and handles abort/resume.

Public API:
  RunConfig (dataclass)
  run_eval(config: RunConfig) -> dict  # returns partial or complete report dict
  resume_run(run_id: str, run_dir: Path, config: RunConfig) -> dict

Upstream deps: corpus.py, cost_gate.py (CostGate, BudgetExceeded),
               smoke_gate.py, scoring/registry.py, report.py; stdlib.

Downstream consumers: cli.py.

Failure modes: BudgetExceeded triggers abort.flag write + partial report.
               Per-ticket errors are captured in ConditionResult.status; the
               runner continues unless abort.flag is present.
               Write-order: ticket_results -> tally (tally is always derivable
               from ticket_results on crash recovery via reconcile_tally).

Performance: dominated by LLM invocations. Harness overhead is O(tickets * dims).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .corpus import load_corpus
from .cost_gate import BudgetExceeded, CostGate, reconcile_tally
from .report import build_methodology
from .scoring.registry import ScorerRegistry, load_registry
from .smoke_gate import check_smoke_dominance

_LOG = logging.getLogger(__name__)

_RUNTIME_BASE = Path(".runtime")


@dataclass
class RunConfig:
    corpus_dir: Path
    ae_spec_path: Path
    icl_spec_path: Path
    run_dir: Path | None = None
    smoke: bool = False
    smoke_gate: bool = False
    max_tickets: int | None = None
    cells_whitelist: list[str] = field(default_factory=list)
    max_usd_global: float = 300.0
    max_tokens_global: int = 30_000_000
    max_usd_per_cell: float | None = None
    max_tokens_per_cell: int | None = None
    timeout_seconds: int = 300
    weights_path: Path | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    baseline_sha: str | None = None


def run_eval(config: RunConfig) -> dict:
    """Run the eval from scratch; return report dict."""
    run_dir = config.run_dir or (_RUNTIME_BASE / config.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    results_dir = run_dir / "ticket_results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Load corpus
    manifest, tickets = load_corpus(config.corpus_dir)
    if config.smoke:
        tickets = tickets[:5]
    if config.max_tickets:
        tickets = tickets[: config.max_tickets]

    # Load conditions
    from .conditions.ae_orchestrated.single_shot import make_ae_condition
    from .conditions.icl_baseline import ICLBaseline

    ae_condition = make_ae_condition(config.ae_spec_path)
    icl_condition = ICLBaseline(config.icl_spec_path)
    conditions = [ae_condition, icl_condition]

    # Load scorer registry
    registry = load_registry(config.weights_path)

    # Initialize cost gate
    cost_gate = CostGate(
        run_dir=run_dir,
        max_usd_global=config.max_usd_global,
        max_tokens_global=config.max_tokens_global,
        max_usd_per_cell=config.max_usd_per_cell,
        max_tokens_per_cell=config.max_tokens_per_cell,
    )

    # Run all tickets via shared helper (also used by resume_run)
    ticket_scores, cells_dropped, aborted, abort_reason = _run_tickets(
        tickets=tickets,
        conditions=conditions,
        registry=registry,
        cost_gate=cost_gate,
        run_dir=run_dir,
        config=config,
        results_dir=results_dir,
    )

    # Smoke-gate dominance check
    smoke_gate_result = None
    if config.smoke and config.smoke_gate and ticket_scores:
        smoke_agg = _aggregate_smoke_scores(ticket_scores)
        cells = [c.condition_id for c in conditions]
        smoke_gate_result = check_smoke_dominance(list(smoke_agg.values()), cells)

    # Finalize: pass actual pending/in-flight state so finalize() can compute
    # aborted correctly. If loop exited early (local aborted=True) but no cells
    # are actually pending or dropped, finalize() correctly returns aborted=False
    # with budget_breached_at_finalization=True per architect plan step 19.
    # Do NOT pass `or aborted` here - `aborted` is loop-control state only and
    # must not bleed into finalize()'s judgment about whether cells were pending.
    tally = cost_gate.finalize(
        cells_pending=len(cells_dropped) > 0,
        tickets_in_flight=False,
    )

    # Use finalize()'s authoritative aborted value, not the local loop-control
    # variable. This reconciles two semantics: local-loop-aborted (early exit
    # due to BudgetExceeded) vs report-aborted (whether pending work was lost).
    # When budget is hit during finalization with no in-flight/pending work,
    # finalize() returns aborted=False, budget_breached_at_finalization=True.
    report_aborted = tally["aborted"]
    report_abort_reason = abort_reason if report_aborted else None

    report = _build_report(
        config=config,
        manifest=manifest,
        ticket_scores=ticket_scores,
        tally=tally,
        cells_dropped=cells_dropped,
        aborted=report_aborted,
        abort_reason=report_abort_reason,
        smoke_gate_result=smoke_gate_result,
    )

    # Propagate budget_breached_at_finalization flag when not aborted.
    if tally.get("budget_breached_at_finalization"):
        report["budget_breached_at_finalization"] = True

    # Write report
    report_dir = Path("evals/icl_vs_orchestration/results") / config.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "results-v1.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    _LOG.info("Report written to %s", report_path)

    return report


def _build_report(
    config: RunConfig,
    manifest: dict,
    ticket_scores: dict,
    tally: dict,
    cells_dropped: list[str],
    aborted: bool,
    abort_reason: str | None,
    smoke_gate_result: Any,
) -> dict:
    """Assemble the results-v1.json report dict."""
    from .scoring.output_coherence import TAXONOMY_VERSION

    # Count rationale_extraction_method per condition
    rationale_method_count: dict[str, dict] = {}
    # Count floored dims per condition
    floored_dim_count: dict[str, dict] = {}
    weights_renormalized_count = 0

    by_ticket_class: dict[str, list] = {}
    for ticket_id, scores in ticket_scores.items():
        for cid, sc in scores.items():
            if isinstance(sc, dict) and sc.get("status") == "ok":
                if sc.get("weights_renormalized"):
                    weights_renormalized_count += 1
                for dim in sc.get("floored_dims", []):
                    fc = floored_dim_count.setdefault(cid, {})
                    fc[dim] = fc.get(dim, 0) + 1
            # Accumulate rationale_extraction_method counts per condition.
            # The runner injects "_rationale_extraction_method" into scorer
            # output dicts so _build_report can count them without needing
            # the raw results. Values: "structured" | "fallback-full-text".
            if isinstance(sc, dict):
                method = sc.get("_rationale_extraction_method")
                if method:
                    rc = rationale_method_count.setdefault(cid, {})
                    rc[method] = rc.get(method, 0) + 1

    summary = {
        "tickets_run": len(ticket_scores),
        "conditions": ["ae-orchestrated", "icl-baseline"],
        "by_ticket_class": by_ticket_class,
    }

    report = {
        "schema_version": "results-v1",
        "run_id": config.run_id,
        "corpus_dir": str(config.corpus_dir),
        "ae_spec": str(config.ae_spec_path),
        "icl_spec": str(config.icl_spec_path),
        "baseline_sha_pinned": config.baseline_sha,
        "ae_execution_mode": "single-shot",  # Q1=(a) resolved
        "correctness_method": "ac-keyword",  # Q2 primary is test-pass; fallback is ac-keyword; reported as ac-keyword for v1 smoke (no real tests)
        "output_coherence_method": "fixed-common-pair-binarized-v1",
        "output_coherence_taxonomy_version": TAXONOMY_VERSION,
        "smoke": config.smoke,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "cells_dropped_by_per_cell_budget": cells_dropped,
        "weights_renormalized_count": weights_renormalized_count,
        "floored_dim_count_per_condition": floored_dim_count,
        "rationale_extraction_method_count": rationale_method_count,
        "cost": tally,
        "methodology": build_methodology(
            tally.get("skeptic_input_cost_normalization")
        ),
        "summary": summary,
        "tickets": ticket_scores,
        "smoke_gate": (
            {
                "dominated": smoke_gate_result.dominated,
                "dominated_cells": smoke_gate_result.dominated_cells,
                "reason": smoke_gate_result.reason,
                "summary": smoke_gate_result.summary,
            }
            if smoke_gate_result
            else None
        ),
    }
    return report


def _aggregate_smoke_scores(ticket_scores: dict) -> dict:
    """Aggregate ticket scores by condition for smoke-gate check."""
    by_condition: dict[str, dict] = {}
    for ticket_id, scores in ticket_scores.items():
        for cid, sc in scores.items():
            agg = by_condition.setdefault(
                cid,
                {
                    "condition_id": cid,
                    "primaries": [],
                    "costs": [],
                },
            )
            if isinstance(sc, dict) and "primary" in sc:
                agg["primaries"].append(sc["primary"])

    result = {}
    for cid, agg in by_condition.items():
        primaries = agg["primaries"]
        result[cid] = {
            "condition_id": cid,
            "primary_mean": sum(primaries) / len(primaries) if primaries else 0.0,
            "cost_usd_mean": 0.0,  # cost gate tracks separately
            "ticket_count": len(primaries),
        }
    return result


def _write_abort_flag(run_dir: Path, cells_pending: bool) -> None:
    """Write abort.flag only when there are cells_pending or in-flight tickets."""
    if cells_pending:
        abort_path = run_dir / "abort.flag"
        abort_path.write_text("Budget exceeded; run aborted with pending work.\n")


def _error_result(ticket_id: str, condition_id: str, error: str) -> dict:
    """Return a ConditionResult-shaped dict for a failed run."""
    return {
        "ticket_id": ticket_id,
        "condition_id": condition_id,
        "status": "error",
        "final_text": "",
        "diff": None,
        "files_touched": [],
        "tool_calls": [],
        "tokens": {},
        "cost_usd": 0.0,
        "wall_seconds": 0.0,
        "raw_trace_path": "",
        "invocation_meta": {"error": error},
        "quality_gates": {},
        "artifacts": {
            "rationale_or_plan": "",
            "diff": "",
            "rationale_extraction_method": "fallback-full-text",
        },
    }


def _run_tickets(
    tickets: list[dict],
    conditions: list,
    registry,
    cost_gate: "CostGate",
    run_dir: Path,
    config: "RunConfig",
    results_dir: Path,
    cells_dropped_init: list[str] | None = None,
) -> tuple[dict, list[str], bool, str | None]:
    """Execute per-ticket condition loop; return (ticket_scores, cells_dropped, aborted, abort_reason).

    Extracted from run_eval() so resume_run() can reuse the same execution path
    for remaining tickets without duplicating logic.
    """
    ticket_scores: dict[str, dict] = {}
    cells_dropped: list[str] = list(cells_dropped_init or [])
    aborted = False
    abort_reason: str | None = None

    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        _LOG.info("Running ticket %s", ticket_id)

        condition_results: dict[str, dict] = {}
        condition_scores: dict[str, dict] = {}

        for condition in conditions:
            cid = condition.condition_id
            cell_id = cid  # v1: cell = condition

            if cell_id in cells_dropped:
                _LOG.info("Skipping dropped cell %s for ticket %s", cell_id, ticket_id)
                continue

            result_path = results_dir / f"{ticket_id}__{cid}.json"

            # Prepare workspace
            workspace = run_dir / "workspaces" / f"{ticket_id}__{cid}"
            workspace.mkdir(parents=True, exist_ok=True)

            try:
                condition.prepare(ticket, workspace)
            except Exception as e:
                _LOG.error("prepare() failed for %s/%s: %s", ticket_id, cid, e)
                continue

            # Run condition
            try:
                result = condition.run(
                    ticket=ticket,
                    workspace=workspace,
                    cost_gate=cost_gate,
                    timeout_seconds=config.timeout_seconds,
                )
            except BudgetExceeded as e:
                _LOG.warning("Budget exceeded during ticket %s/%s: %s", ticket_id, cid, e)
                aborted = True
                abort_reason = str(e)
                # Only write abort.flag when there is actually pending work
                # (dropped cells or remaining tickets). If this is the first
                # cell of the first ticket with no prior drops, no abort.flag.
                _write_abort_flag(
                    run_dir,
                    cells_pending=len(cells_dropped) > 0,
                )
                break
            except Exception as e:
                _LOG.error("condition.run() failed for %s/%s: %s", ticket_id, cid, e)
                result = _error_result(ticket_id, cid, str(e))

            # Write-order: ticket result first, then cost tally
            result["raw_trace_path"] = str(result.get("raw_trace_path", ""))
            result_path.write_text(json.dumps(result, default=str))

            try:
                cost_gate.record(
                    cell_id=cell_id,
                    ticket_id=ticket_id,
                    tokens=result.get("tokens", {}),
                    cost_usd=result.get("cost_usd", 0.0),
                )
            except BudgetExceeded as e:
                if e.scope == "cell":
                    _LOG.warning("Per-cell budget exceeded for cell %s: %s", cell_id, e)
                    cells_dropped.append(cell_id)
                else:
                    _LOG.warning("Global budget exceeded: %s", e)
                    aborted = True
                    abort_reason = str(e)
                    _write_abort_flag(run_dir, cells_pending=bool(cells_dropped))
                    break

            condition_results[cid] = result

            # Score; inject rationale_extraction_method into scorer output
            try:
                ticket_score = registry.score_result(result, ticket)
                # Inject rationale_extraction_method from raw result artifacts
                # so _build_report can accumulate per-condition counts without
                # needing access to the raw result dicts.
                method = result.get("artifacts", {}).get(
                    "rationale_extraction_method"
                )
                if method:
                    ticket_score["_rationale_extraction_method"] = method
                condition_scores[cid] = ticket_score
            except Exception as e:
                _LOG.error("Scoring failed for %s/%s: %s", ticket_id, cid, e)
                condition_scores[cid] = {"status": "scoring-error", "error": str(e)}

        if aborted:
            break

        # Symmetric-dimset invariant check
        if "ae-orchestrated" in condition_scores and "icl-baseline" in condition_scores:
            try:
                registry.assert_symmetric_dimset(
                    condition_scores["ae-orchestrated"],
                    condition_scores["icl-baseline"],
                )
            except AssertionError as e:
                _LOG.error("Invariant violation for ticket %s: %s", ticket_id, e)
                for cid in condition_scores:
                    condition_scores[cid]["status"] = "invariant-violation"
                    condition_scores[cid]["invariant_error"] = str(e)

        ticket_scores[ticket_id] = condition_scores

    return ticket_scores, cells_dropped, aborted, abort_reason


def resume_run(run_id: str, run_dir: Path, config: RunConfig) -> dict:
    """Resume an interrupted run by reconciling tally from ticket_results/."""
    _LOG.info("Resuming run %s from %s", run_id, run_dir)

    # Re-derive tally from completed ticket results
    tally = reconcile_tally(run_dir)
    _LOG.info("Reconciled tally: %s", tally)

    # Re-initialize cost gate with reconciled state
    cost_gate = CostGate(
        run_dir=run_dir,
        max_usd_global=config.max_usd_global,
        max_tokens_global=config.max_tokens_global,
        max_usd_per_cell=config.max_usd_per_cell,
        max_tokens_per_cell=config.max_tokens_per_cell,
    )
    # Populate cost gate from reconciled tally
    cost_gate._global_usd = tally["global_usd"]
    cost_gate._global_tokens = tally["global_tokens"]
    for cid, cell_data in tally.get("cells", {}).items():
        cost_gate._cells[cid] = dict(cell_data)

    # Find already-completed ticket+condition pairs
    results_dir = run_dir / "ticket_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    completed: set[str] = set()
    if results_dir.exists():
        for f in results_dir.glob("*__*.json"):
            completed.add(f.stem)

    # Load corpus and determine remaining tickets
    manifest, all_tickets = load_corpus(config.corpus_dir)
    if config.smoke:
        all_tickets = all_tickets[:5]
    if config.max_tickets:
        all_tickets = all_tickets[: config.max_tickets]

    remaining_tickets = [
        t
        for t in all_tickets
        if not all(
            f"{t['ticket_id']}__{cid}" in completed
            for cid in ["ae-orchestrated", "icl-baseline"]
        )
    ]
    _LOG.info(
        "Resume: %d tickets already complete, %d remaining.",
        len(all_tickets) - len(remaining_tickets),
        len(remaining_tickets),
    )

    config.run_id = run_id
    config.run_dir = run_dir

    new_ticket_scores: dict[str, dict] = {}
    cells_dropped: list[str] = []
    aborted = False
    abort_reason: str | None = None

    if remaining_tickets:
        from .conditions.ae_orchestrated.single_shot import make_ae_condition
        from .conditions.icl_baseline import ICLBaseline

        ae_condition = make_ae_condition(config.ae_spec_path)
        icl_condition = ICLBaseline(config.icl_spec_path)
        conditions = [ae_condition, icl_condition]
        registry = load_registry(config.weights_path)

        new_ticket_scores, cells_dropped, aborted, abort_reason = _run_tickets(
            tickets=remaining_tickets,
            conditions=conditions,
            registry=registry,
            cost_gate=cost_gate,
            run_dir=run_dir,
            config=config,
            results_dir=results_dir,
        )
        _LOG.info(
            "Resume: ran %d remaining tickets; aborted=%s",
            len(remaining_tickets),
            aborted,
        )

    # Rebuild report from ALL completed results (prior + newly run)
    registry_for_report = load_registry(config.weights_path)
    ticket_scores = _load_completed_scores(results_dir, registry_for_report)
    # Merge new scores into loaded scores (in case some are not on disk yet)
    for tid, scores in new_ticket_scores.items():
        ticket_scores.setdefault(tid, {}).update(scores)

    # Do NOT pass `or aborted` here - loop-control state must not bleed into
    # finalize()'s judgment. If no cells were dropped, cells_pending=False.
    tally_final = cost_gate.finalize(
        cells_pending=len(cells_dropped) > 0,
        tickets_in_flight=False,
    )
    report_aborted = tally_final["aborted"]
    report_abort_reason = abort_reason if report_aborted else None

    report = _build_report(
        config=config,
        manifest=manifest,
        ticket_scores=ticket_scores,
        tally=tally_final,
        cells_dropped=cells_dropped,
        aborted=report_aborted,
        abort_reason=report_abort_reason,
        smoke_gate_result=None,
    )
    if tally_final.get("budget_breached_at_finalization"):
        report["budget_breached_at_finalization"] = True

    report_dir = Path("evals/icl_vs_orchestration/results") / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "results-v1.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    return report


def _load_completed_scores(
    results_dir: Path, registry: ScorerRegistry
) -> dict:
    """Load all completed ticket results and re-score them."""
    import re

    ticket_results: dict[str, dict] = {}
    for result_file in sorted(results_dir.glob("*__*.json")):
        name = result_file.stem
        match = re.match(r"^(.+)__(ae-orchestrated|icl-baseline)$", name)
        if not match:
            continue
        ticket_id, cid = match.group(1), match.group(2)
        try:
            result = json.loads(result_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        ticket = {"ticket_id": ticket_id, "ticket_yaml": {}}
        score = registry.score_result(result, ticket)
        ticket_scores = ticket_results.setdefault(ticket_id, {})
        ticket_scores[cid] = score

    return ticket_results
