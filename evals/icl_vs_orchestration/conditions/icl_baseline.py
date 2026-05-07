"""
Purpose: ICL-baseline condition adapter. Invokes the Claude CLI with a single
         assembled prompt (full ticket context in one shot) and extracts
         rationale_or_plan using the v1 symmetric extraction rule, mirroring
         the AE-orchestrated single-shot adapter.

Public API:
  ICLBaseline (implements Condition Protocol)
    condition_id = "icl-baseline"
    prepare(ticket, workspace) -> None
    run(ticket, workspace, cost_gate, timeout_seconds) -> ConditionResult dict

Upstream deps: conditions/base.py (extract_rationale_or_plan),
               conditions/icl_spec.py (load_spec, assemble_icl_prompt),
               metering.py (extract_tokens, estimate_cost_usd),
               evals.runner.invoker (invoke_run); pyyaml; stdlib.

Downstream consumers: runner.py.

Failure modes: all LLM invocation errors captured in result.status
               ("error", "timeout"). BudgetExceeded from cost_gate is re-raised.

Performance: one LLM call per ticket; dominated by model latency.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import yaml

from ..metering import estimate_cost_usd, extract_tokens
from .base import extract_rationale_or_plan
from .icl_spec import assemble_icl_prompt, load_spec

try:
    from evals.runner import invoker as _invoker
except ImportError:
    _invoker = None  # type: ignore[assignment]


def _extract_diff(text: str) -> str | None:
    """Heuristically extract a unified diff from ICL output text."""
    import re
    code_block = re.search(r"```diff\n(.*?)```", text, re.DOTALL)
    if code_block:
        return code_block.group(1).strip()
    raw = re.search(
        r"((?:--- .+\n\+\+\+ .+\n(?:@@ .+@@.*\n)?(?:[-+ ].+\n?)*)+)", text
    )
    if raw:
        return raw.group(1).strip()
    return None


def _infer_files_touched(diff: str | None) -> list[str]:
    if not diff:
        return []
    import re
    files = re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)
    return list(dict.fromkeys(files))


class ICLBaseline:
    """ICL-baseline condition: one assembled prompt, one LLM call."""

    condition_id = "icl-baseline"

    def __init__(self, icl_spec_path: Path) -> None:
        self._spec = load_spec(icl_spec_path)
        self._icl_spec_path = icl_spec_path
        self._model = self._spec.get("model", "claude-sonnet")

    def prepare(self, ticket: dict, workspace: Path) -> None:
        """Write ticket context into workspace (mirrors AE adapter)."""
        workspace.mkdir(parents=True, exist_ok=True)
        ticket_yaml_path = workspace / "ticket.yaml"
        ticket_yaml_path.write_text(yaml.dump(ticket["ticket_yaml"]))

        ticket_dir = ticket.get("ticket_dir")
        if ticket_dir:
            workspace_files_dir = Path(ticket_dir) / "workspace_files"
            if workspace_files_dir.exists():
                for src in workspace_files_dir.rglob("*"):
                    if src.is_file() and src.name != ".gitkeep":
                        rel = src.relative_to(workspace_files_dir)
                        dest = workspace / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)

    def run(
        self,
        ticket: dict,
        workspace: Path,
        cost_gate: object,
        timeout_seconds: int,
    ) -> dict:
        """Run ICL baseline for one ticket; return ConditionResult dict."""
        ticket_id = ticket["ticket_id"]
        t0 = time.monotonic()

        prompt = assemble_icl_prompt(self._spec, ticket)

        if _invoker is not None:
            try:
                run_record = _invoker.invoke_run(
                    prompt=prompt,
                    worktree=workspace,
                    timeout_seconds=timeout_seconds,
                    agent_name=None,
                    mode="command",
                )
                status = run_record.get("status", "ok")
                final_text = run_record.get("final_text", "")
                tool_calls = run_record.get("tool_calls", [])
                stderr_tail = run_record.get("stderr_tail", "")
            except Exception as e:
                status = "error"
                final_text = ""
                tool_calls = []
                stderr_tail = str(e)
                run_record = {}
        else:
            status = "ok"
            final_text = ""
            tool_calls = []
            stderr_tail = ""
            run_record = {}

        wall_seconds = time.monotonic() - t0
        tokens = extract_tokens(run_record)
        cost_usd = estimate_cost_usd(tokens, self._model)

        trace_path = workspace / f"{ticket_id}__icl-baseline__trace.json"
        trace_path.write_text(json.dumps(run_record, default=str))

        # v1 symmetric extraction rule: same as AE adapter
        # ICL source = final_text; try structured parse, fallback to full text
        rationale_or_plan, extraction_method = extract_rationale_or_plan(final_text)

        diff = _extract_diff(final_text)

        artifacts: dict = {
            "rationale_or_plan": rationale_or_plan,
            "diff": diff or "",
            "rationale_extraction_method": extraction_method,
        }

        return {
            "ticket_id": ticket_id,
            "condition_id": "icl-baseline",
            "status": status,
            "final_text": final_text,
            "diff": diff,
            "files_touched": _infer_files_touched(diff),
            "tool_calls": tool_calls,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "wall_seconds": wall_seconds,
            "raw_trace_path": trace_path,
            "invocation_meta": {
                "model": self._model,
                "icl_spec_path": str(self._icl_spec_path),
                "context_budget_tokens": self._spec.get("context_budget_tokens"),
                "file_selection_rule": self._spec.get("file_selection_rule"),
                "stderr_tail": stderr_tail,
            },
            "quality_gates": {},
            "artifacts": artifacts,
        }
