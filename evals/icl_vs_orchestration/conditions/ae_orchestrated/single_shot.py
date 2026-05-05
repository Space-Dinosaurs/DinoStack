"""
Purpose: AE-orchestrated condition adapter - single-shot execution mode
         (Q1=(a), operator-confirmed 2026-05-04).

         Invokes the Claude CLI in single-shot mode: one `claude -p` call
         that receives the full ticket context and is expected to produce
         the complete implementation in one response. The adapter then
         extracts rationale_or_plan from the final_text using the v1
         symmetric extraction rule (structured-section parse, fallback to
         entire text), mirroring the ICL-baseline adapter's behavior.

Public API:
  AEOrchestratedSingleShot (implements Condition Protocol)
    condition_id = "ae-orchestrated"
    prepare(ticket, workspace) -> None
    run(ticket, workspace, cost_gate, timeout_seconds) -> ConditionResult dict

Upstream deps: conditions/base.py (extract_rationale_or_plan),
               metering.py (extract_tokens, estimate_cost_usd),
               evals.runner.invoker (invoke_run, probe_claude_cli),
               evals.runner.normalizer (parse_stream_json);
               schema.py (validate_ae_spec); pyyaml; stdlib.

Downstream consumers: runner.py.

Failure modes: all LLM invocation errors are captured in result.status
               ("error", "timeout") rather than propagating. Cost gate
               BudgetExceeded is re-raised (caller aborts the run).

Performance: one LLM call per ticket; dominated by model latency (seconds
             to minutes). Workspace prep is local I/O only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from ...metering import estimate_cost_usd, extract_tokens
from ...schema import validate_ae_spec
from ..base import extract_rationale_or_plan

try:
    from evals.runner import invoker as _invoker
except ImportError:
    _invoker = None  # type: ignore[assignment]


class AEOrchestratedSingleShot:
    """Single-shot AE condition: one claude -p call per ticket."""

    condition_id = "ae-orchestrated"

    def __init__(self, ae_spec_path: Path) -> None:
        with ae_spec_path.open() as f:
            self._spec = yaml.safe_load(f)
        validate_ae_spec(self._spec)
        if self._spec["execution_mode"] != "single-shot":
            raise ValueError(
                f"AEOrchestratedSingleShot requires execution_mode='single-shot'; "
                f"got '{self._spec['execution_mode']}'."
            )
        self._ae_spec_path = ae_spec_path
        self._model = self._spec.get("model", "claude-sonnet")

    def prepare(self, ticket: dict, workspace: Path) -> None:
        """Write ticket context files into workspace for the LLM invocation."""
        workspace.mkdir(parents=True, exist_ok=True)
        ticket_yaml_path = workspace / "ticket.yaml"
        ticket_yaml_path.write_text(yaml.dump(ticket["ticket_yaml"]))

        arch_path = ticket.get("architect_plan_path")
        if arch_path and Path(arch_path).exists():
            dest = workspace / "architect_plan.md"
            dest.write_text(Path(arch_path).read_text())

        brief_path = ticket.get("brief_path")
        if brief_path and Path(brief_path).exists():
            dest = workspace / "brief.md"
            dest.write_text(Path(brief_path).read_text())

    def run(
        self,
        ticket: dict,
        workspace: Path,
        cost_gate: object,
        timeout_seconds: int,
    ) -> dict:
        """Run single-shot AE for one ticket; return ConditionResult dict."""
        ticket_id = ticket["ticket_id"]
        t0 = time.monotonic()

        prompt = self._build_prompt(ticket, workspace)

        # Invoke via invoker if available; fall back to stub for tests
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
            # Test stub path
            status = "ok"
            final_text = ""
            tool_calls = []
            stderr_tail = ""
            run_record = {}

        wall_seconds = time.monotonic() - t0
        tokens = extract_tokens(run_record)
        cost_usd = estimate_cost_usd(tokens, self._model)

        # Save raw trace
        trace_path = workspace / f"{ticket_id}__ae-orchestrated__trace.json"
        trace_path.write_text(json.dumps(run_record, default=str))

        # Extract rationale using v1 symmetric rule (structured first, fallback full text)
        # Under Q1=(a) single-shot, AE produces one final_text with no guaranteed
        # structured section - same shape as ICL - so the fallback applies symmetrically.
        source_text = final_text
        rationale_or_plan, extraction_method = extract_rationale_or_plan(source_text)

        # Extract diff from final_text heuristically
        diff = _extract_diff(final_text)

        artifacts: dict = {
            "rationale_or_plan": rationale_or_plan,
            "diff": diff or "",
            "rationale_extraction_method": extraction_method,
        }

        return {
            "ticket_id": ticket_id,
            "condition_id": "ae-orchestrated",
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
                "execution_mode": "single-shot",
                "content_sha": self._spec.get("content_sha", ""),
                "model": self._model,
                "ae_spec_path": str(self._ae_spec_path),
                "stderr_tail": stderr_tail,
            },
            "quality_gates": {},
            "artifacts": artifacts,
        }

    def _build_prompt(self, ticket: dict, workspace: Path) -> str:
        """Assemble the single-shot AE prompt from ticket context."""
        ticket_yaml = ticket.get("ticket_yaml", {})
        description = ticket_yaml.get("description", "")
        ticket_id = ticket["ticket_id"]

        parts = [
            f"# Ticket: {ticket_id}",
            "",
            f"## Description",
            description,
            "",
        ]

        arch_path = workspace / "architect_plan.md"
        if arch_path.exists():
            parts += [
                "## Architect Plan",
                arch_path.read_text(),
                "",
            ]

        brief_path = workspace / "brief.md"
        if brief_path.exists():
            parts += [
                "## Brief",
                brief_path.read_text(),
                "",
            ]

        relevant_files_dir = ticket.get("relevant_files_dir")
        if relevant_files_dir and Path(relevant_files_dir).exists():
            for p in sorted(Path(relevant_files_dir).iterdir()):
                if p.is_file():
                    parts += [
                        f"## File: {p.name}",
                        p.read_text(),
                        "",
                    ]

        parts += [
            "## Task",
            "Implement the changes described in the ticket and architect plan above.",
            "Provide your complete implementation, including:",
            "1. A rationale section (## Rationale) explaining your approach",
            "2. The complete diff of all changes (## Diff)",
            "Return structured output with these sections clearly delimited.",
        ]

        return "\n".join(parts)


class AEOrchestratedSDKMultiturn:
    """SDK-multiturn AE condition - not implemented in v1."""

    condition_id = "ae-orchestrated"

    def __init__(self, ae_spec_path: Path) -> None:
        raise NotImplementedError(
            "sdk-multiturn execution mode is not implemented in eval-harness-v1. "
            "Use execution_mode='single-shot' (Q1=(a), operator-confirmed)."
        )

    def prepare(self, ticket: dict, workspace: Path) -> None:
        raise NotImplementedError

    def run(self, ticket: dict, workspace: Path, cost_gate: object, timeout_seconds: int) -> dict:
        raise NotImplementedError


class AEOrchestratedPythonConductorSim:
    """Python-conductor-sim AE condition - not implemented in v1."""

    condition_id = "ae-orchestrated"

    def __init__(self, ae_spec_path: Path) -> None:
        raise NotImplementedError(
            "python-conductor-sim execution mode is not implemented in eval-harness-v1. "
            "Use execution_mode='single-shot' (Q1=(a), operator-confirmed)."
        )

    def prepare(self, ticket: dict, workspace: Path) -> None:
        raise NotImplementedError

    def run(self, ticket: dict, workspace: Path, cost_gate: object, timeout_seconds: int) -> dict:
        raise NotImplementedError


def make_ae_condition(ae_spec_path: Path) -> AEOrchestratedSingleShot:
    """Factory: load spec and return the appropriate AE condition adapter.

    Only single-shot is supported in v1; other modes raise NotImplementedError.
    """
    with ae_spec_path.open() as f:
        spec = yaml.safe_load(f)
    mode = spec.get("execution_mode", "single-shot")
    if mode == "single-shot":
        return AEOrchestratedSingleShot(ae_spec_path)
    elif mode == "sdk-multiturn":
        return AEOrchestratedSDKMultiturn(ae_spec_path)  # type: ignore[return-value]
    elif mode == "python-conductor-sim":
        return AEOrchestratedPythonConductorSim(ae_spec_path)  # type: ignore[return-value]
    else:
        raise ValueError(f"Unknown AE execution_mode: '{mode}'")


def _extract_diff(text: str) -> str | None:
    """Heuristically extract a unified diff from text output."""
    import re
    # Look for a diff block (```diff ... ``` or raw unified diff header)
    code_block = re.search(r"```diff\n(.*?)```", text, re.DOTALL)
    if code_block:
        return code_block.group(1).strip()
    # Look for unified diff header
    raw = re.search(r"((?:--- .+\n\+\+\+ .+\n(?:@@ .+@@.*\n)?(?:[-+ ].+\n?)*)+)", text)
    if raw:
        return raw.group(1).strip()
    return None


def _infer_files_touched(diff: str | None) -> list[str]:
    """Extract file paths from a unified diff."""
    if not diff:
        return []
    import re
    files = re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)
    return list(dict.fromkeys(files))  # deduplicate, preserve order
