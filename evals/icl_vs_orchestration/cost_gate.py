"""
Purpose: Track per-ticket LLM spend against global (USD + token) and
         per-cell budgets, raising BudgetExceeded on ceiling breach.
         Writes an atomic tally file so resume can re-derive state from
         per-ticket results on crash recovery.

Public API:
  CostGate(run_dir, max_usd_global, max_tokens_global,
           max_usd_per_cell, max_tokens_per_cell)
  CostGate.record(cell_id, ticket_id, tokens, cost_usd) -> None
  CostGate.check(cell_id) -> None
  CostGate.remaining(cell_id=None) -> tuple[float, int]
  CostGate.finalize(cells_pending: bool, tickets_in_flight: bool) -> dict
  BudgetExceeded(scope, cell_id, totals)
  reconcile_tally(run_dir: Path) -> dict
    Re-derives cost tally from ticket_results/ on resume; call before
    constructing CostGate when resuming an interrupted run.

Upstream deps: stdlib json, pathlib, threading.

Downstream consumers: runner.py, cli.py.

Failure modes: BudgetExceeded raised when a ceiling is hit; callers catch
               and set abort.flag. Atomic write (tmp+rename) for tally;
               partial-write crash leaves the prior valid tally intact.

Performance: per-record cost is O(1); tally write is O(cells).

NOTE: cost-confounder normalization fields (per cost-normalization-contract.md)
      are stubbed here as TODO placeholders. They will be filled in once
      the sibling engineer (skeptic-global-context) delivers
      cost-normalization-contract.md. See architect-plan note: "engineer reads
      cost-normalization-contract.md before finalizing cost_gate.py and report.py."
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class BudgetExceeded(Exception):
    """Raised when a cost or token ceiling is breached."""

    def __init__(self, scope: str, cell_id: str | None, totals: dict) -> None:
        self.scope = scope  # "global" | "cell"
        self.cell_id = cell_id
        self.totals = totals
        msg = (
            f"Budget exceeded (scope={scope}"
            + (f", cell={cell_id}" if cell_id else "")
            + f"): {totals}"
        )
        super().__init__(msg)


class CostGate:
    """Thread-safe cost tracker with global + per-cell budget enforcement."""

    def __init__(
        self,
        run_dir: Path,
        max_usd_global: float = 300.0,
        max_tokens_global: int = 30_000_000,
        max_usd_per_cell: float | None = None,
        max_tokens_per_cell: int | None = None,
    ) -> None:
        self._run_dir = run_dir
        self._max_usd_global = max_usd_global
        self._max_tokens_global = max_tokens_global
        self._max_usd_per_cell = max_usd_per_cell
        self._max_tokens_per_cell = max_tokens_per_cell
        self._lock = threading.Lock()
        # Global accumulators
        self._global_usd = 0.0
        self._global_tokens = 0
        # Per-cell accumulators: {cell_id: {usd: float, tokens: int}}
        self._cells: dict[str, dict] = {}
        # Per-ticket entries for reconcile: {cell_id: {ticket_id: {usd, tokens}}}
        self._ticket_entries: dict[str, dict] = {}
        # Ensure run_dir exists
        run_dir.mkdir(parents=True, exist_ok=True)

    def _tally_path(self) -> Path:
        return self._run_dir / "cost_tally.json"

    def record(
        self,
        cell_id: str,
        ticket_id: str,
        tokens: dict,
        cost_usd: float,
    ) -> None:
        """Record cost for one ticket result; check ceilings; write tally.

        tokens dict expected keys: input, output (int each).
        Raises BudgetExceeded if a ceiling is hit after recording.
        """
        token_total = int(tokens.get("input", 0)) + int(
            tokens.get("output", 0)
        )
        with self._lock:
            self._global_usd += cost_usd
            self._global_tokens += token_total
            cell = self._cells.setdefault(
                cell_id, {"usd": 0.0, "tokens": 0}
            )
            cell["usd"] += cost_usd
            cell["tokens"] += token_total
            tcell = self._ticket_entries.setdefault(cell_id, {})
            tcell[ticket_id] = {
                "usd": tcell.get(ticket_id, {}).get("usd", 0.0) + cost_usd,
                "tokens": tcell.get(ticket_id, {}).get("tokens", 0) + token_total,
            }
            self._write_tally_locked()
        # Check ceilings AFTER recording (write-order: tally first)
        self.check(cell_id)

    def check(self, cell_id: str) -> None:
        """Raise BudgetExceeded if any ceiling is exceeded for cell_id.

        Checks global ceiling first, then per-cell ceiling.
        """
        with self._lock:
            g_usd = self._global_usd
            g_tok = self._global_tokens
            cell = self._cells.get(cell_id, {"usd": 0.0, "tokens": 0})
            c_usd = cell["usd"]
            c_tok = cell["tokens"]

        if g_usd > self._max_usd_global or g_tok > self._max_tokens_global:
            raise BudgetExceeded(
                scope="global",
                cell_id=None,
                totals={
                    "global_usd": g_usd,
                    "global_tokens": g_tok,
                    "limit_usd": self._max_usd_global,
                    "limit_tokens": self._max_tokens_global,
                },
            )
        if self._max_usd_per_cell is not None and c_usd > self._max_usd_per_cell:
            raise BudgetExceeded(
                scope="cell",
                cell_id=cell_id,
                totals={
                    "cell_usd": c_usd,
                    "limit_usd_per_cell": self._max_usd_per_cell,
                },
            )
        if (
            self._max_tokens_per_cell is not None
            and c_tok > self._max_tokens_per_cell
        ):
            raise BudgetExceeded(
                scope="cell",
                cell_id=cell_id,
                totals={
                    "cell_tokens": c_tok,
                    "limit_tokens_per_cell": self._max_tokens_per_cell,
                },
            )

    def remaining(
        self, cell_id: str | None = None
    ) -> tuple[float, int]:
        """Return (remaining_usd, remaining_tokens) against the relevant ceiling.

        If cell_id is None, returns global remaining.
        """
        with self._lock:
            if cell_id is None:
                return (
                    max(0.0, self._max_usd_global - self._global_usd),
                    max(0, self._max_tokens_global - self._global_tokens),
                )
            cell = self._cells.get(cell_id, {"usd": 0.0, "tokens": 0})
            rem_usd = (
                max(0.0, self._max_usd_per_cell - cell["usd"])
                if self._max_usd_per_cell is not None
                else float("inf")
            )
            rem_tok = (
                max(0, self._max_tokens_per_cell - cell["tokens"])
                if self._max_tokens_per_cell is not None
                else 2**62
            )
            return rem_usd, rem_tok

    def finalize(
        self, cells_pending: bool, tickets_in_flight: bool
    ) -> dict:
        """Return tally dict for the final report.

        If cells_pending or tickets_in_flight AND global ceiling is exceeded,
        the caller should write abort.flag. If the ceiling is hit at
        finalization only (no pending/in-flight), set
        budget_breached_at_finalization=True, aborted=False, no abort.flag.

        NOTE: cost-confounder normalization fields are stubbed pending
        cost-normalization-contract.md delivery from the sibling engineer.
        TODO: implement normalization fields per cost-normalization-contract.md
        """
        with self._lock:
            g_usd = self._global_usd
            g_tok = self._global_tokens
            cells_copy = {k: dict(v) for k, v in self._cells.items()}

        breached = (
            g_usd > self._max_usd_global or g_tok > self._max_tokens_global
        )
        aborted = breached and (cells_pending or tickets_in_flight)

        return {
            "global_usd": g_usd,
            "global_tokens": g_tok,
            "limit_usd_global": self._max_usd_global,
            "limit_tokens_global": self._max_tokens_global,
            "per_cell": cells_copy,
            "budget_breached_at_finalization": breached and not aborted,
            "aborted": aborted,
            # TODO: cost-confounder normalization fields per
            # cost-normalization-contract.md (pending sibling delivery).
            # These will appear in the final report schema under the
            # normalization contract's field names.
            "cost_normalization_pending": True,
        }

    def _write_tally_locked(self) -> None:
        """Write tally atomically (tmp+rename). Caller holds _lock."""
        tally = {
            "global_usd": self._global_usd,
            "global_tokens": self._global_tokens,
            "cells": {k: dict(v) for k, v in self._cells.items()},
        }
        tmp = self._tally_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(tally, indent=2))
        os.replace(tmp, self._tally_path())


def reconcile_tally(run_dir: Path) -> dict:
    """Re-derive cost tally from ticket_results/ directory.

    Called on resume when the tally file may be stale or absent.
    Returns dict with keys: global_usd, global_tokens,
    cells: {cell_id: {usd, tokens}}.
    """
    import re

    results_dir = run_dir / "ticket_results"
    tally: dict = {"global_usd": 0.0, "global_tokens": 0, "cells": {}}
    if not results_dir.exists():
        return tally

    for result_file in results_dir.glob("*__*.json"):
        # filename: {ticket_id}__{condition_id}.json
        name = result_file.stem
        match = re.match(r"^(.+)__(ae-orchestrated|icl-baseline)$", name)
        if not match:
            continue
        ticket_id, condition_id = match.group(1), match.group(2)
        # cell_id is condition_id for now; may be expanded to
        # condition__model__corpus in future
        cell_id = condition_id
        try:
            data = json.loads(result_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        cost = float(data.get("cost_usd", 0.0))
        tokens = data.get("tokens", {})
        tok_total = int(tokens.get("input", 0)) + int(tokens.get("output", 0))
        tally["global_usd"] += cost
        tally["global_tokens"] += tok_total
        cell = tally["cells"].setdefault(cell_id, {"usd": 0.0, "tokens": 0})
        cell["usd"] += cost
        cell["tokens"] += tok_total

    return tally
