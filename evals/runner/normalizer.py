"""
Purpose: Parse Claude CLI stream-json stdout into a normalized per-run trace
         capturing final text, tool calls, turn count, and latency.

Public API: parse_stream_json(raw_stdout: str) -> dict,
            build_trace(runs: list[dict]) -> dict.

Upstream deps: stdlib json.

Downstream consumers: evals.runner.invoker, evals.scoring.skeptic_lite.

Failure modes: malformed JSON lines are skipped with a note in the trace's
               _parse_warnings list rather than raising. An empty stream
               produces a trace with empty final_text and turns_used=0.

Performance: standard; O(lines).
"""
from __future__ import annotations

import json


def parse_stream_json(raw_stdout: str) -> dict:
    """Parse a single Claude CLI run's stream-json stdout into a normalized run record.

    The stream-json format emits one JSON object per line with a "type" discriminator.
    We care about assistant messages (final text concatenation), tool use blocks
    (count), and the final result event (total turns, cost).
    """
    final_text_parts: list[str] = []
    tool_calls: list[dict] = []
    turns_used: int = 0
    cost_usd: float | None = None
    warnings: list[str] = []
    last_assistant_text: str = ""

    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            warnings.append(f"json_decode_error: {e}")
            continue
        t = obj.get("type")
        if t == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                txt_chunks = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type")
                    if bt == "text":
                        txt_chunks.append(block.get("text", ""))
                    elif bt == "tool_use":
                        tool_calls.append({
                            "name": block.get("name"),
                            "id": block.get("id"),
                        })
                if txt_chunks:
                    last_assistant_text = "".join(txt_chunks)
                    final_text_parts.append(last_assistant_text)
        elif t == "result":
            # Final event; carries num_turns and total_cost_usd in current CLI.
            turns_used = int(obj.get("num_turns", obj.get("turns", 0)) or 0)
            if "total_cost_usd" in obj:
                cost_usd = float(obj["total_cost_usd"])
            # Prefer the "result" text field if present.
            if obj.get("result"):
                last_assistant_text = obj["result"]

    return {
        "final_text": last_assistant_text or ("\n\n".join(final_text_parts)),
        "tool_calls": tool_calls,
        "turns_used": turns_used,
        "cost_usd": cost_usd,
        "_parse_warnings": warnings,
    }


def build_trace(runs: list[dict]) -> dict:
    """Wrap per-run records in the trace shape consumed by scoring modules."""
    return {"runs": runs}
