"""
Purpose: Parse Claude or Kimi CLI stream-json stdout into a normalized per-run trace
         capturing final text, tool calls, turn count, and latency.

Public API: parse_stream_json(raw_stdout: str, expect_subagent: bool = False) -> dict,
            build_trace(runs: list[dict]) -> dict.

            parse_stream_json return dict includes:
              "usage": dict - token counts from the result event's usage sub-object,
                       with at minimum the keys input_tokens (int), output_tokens (int),
                       cache_creation_input_tokens (int), cache_read_input_tokens (int).
                       Empty dict ({}) when the result event is absent or carries no
                       usage sub-object (e.g. dry-run, error exit, or older CLI version).

Upstream deps: stdlib json.

Downstream consumers: evals.runner.invoker, evals.scoring.skeptic_lite.

Failure modes: malformed JSON lines are skipped with a note in the trace's
               _parse_warnings list rather than raising. An empty stream
               produces a trace with empty final_text and turns_used=0 and
               usage={}. If the result event carries no usage sub-object (older
               CLI versions, error exits), usage is {} and no exception is raised.

               Two-level spawn: when expect_subagent=True, the parser prefers
               the text returned inside the Task/Agent tool's tool_result event (the
               subagent's final output) over the outer session's assistant
               text. If no tool_result is found, invocation_mode is set to
               "raw-prompt" and final_text falls back to the outer session's
               last assistant text with a parse warning.

Performance: standard; O(lines).
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Claude format helpers
# ---------------------------------------------------------------------------

def _is_outer_task_result(obj: dict) -> bool:
    """True if this user event is the outer-level result of a Task subagent call.

    The stream-json shape emits nested tool_results from the subagent's own
    tool calls (Read, Grep, etc.) interleaved with the outer Task tool result.
    Nested tool_results have parent_tool_use_id set to the subagent's Task
    tool_use id, whereas the outer Task tool_result has parent_tool_use_id
    None and a tool_use_result.agentType field set to the spawned subagent.
    """
    if obj.get("parent_tool_use_id") is not None:
        return False
    tur = obj.get("tool_use_result")
    if isinstance(tur, dict) and tur.get("agentType"):
        return True
    return False


def _extract_tool_result_text(obj: dict) -> str | None:
    """Return the concatenated text blocks from the outer Task tool_result event."""
    tur = obj.get("tool_use_result")
    if isinstance(tur, dict):
        content = tur.get("content")
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            joined = "".join(texts).strip()
            if joined:
                return joined

    # Fallback: walk message.content for tool_result blocks (top-level only).
    msg = obj.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if isinstance(inner, list):
                    texts = [
                        b.get("text", "")
                        for b in inner
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = "".join(texts).strip()
                    if joined:
                        return joined
                elif isinstance(inner, str) and inner.strip():
                    return inner.strip()
    return None


# ---------------------------------------------------------------------------
# Kimi format helpers
# ---------------------------------------------------------------------------

def _extract_kimi_assistant_text(obj: dict) -> str:
    """Extract text from a Kimi assistant message's content array.

    Ignores think blocks; concatenates text blocks.
    """
    content = obj.get("content", [])
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
    return "".join(texts)


def _extract_kimi_subagent_text(tool_content: str) -> str | None:
    """Extract the subagent's meaningful output from a Kimi tool response.

    Kimi tool responses have a structured header (agent_id, status, etc.)
    followed by a [summary] section. We want the summary content.
    """
    if not tool_content:
        return None
    # Look for [summary] marker and take everything after it.
    marker = "[summary]\n"
    idx = tool_content.find(marker)
    if idx != -1:
        text = tool_content[idx + len(marker):].strip()
        if text:
            return text
    # Fallback: if no marker, return the whole thing if it looks like a diff or code.
    stripped = tool_content.strip()
    if stripped:
        return stripped
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_stream_json(raw_stdout: str, expect_subagent: bool = False) -> dict:
    """Parse a Claude or Kimi CLI run's stream-json stdout into a normalized run record.

    Auto-detects the backend format: Claude uses a "type" discriminator per line,
    Kimi uses a "role" field. Empty streams fall back to Claude defaults.
    """
    # Detect format from first non-empty parseable line.
    backend = "claude"
    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "role" in obj:
            backend = "kimi"
        break

    if backend == "kimi":
        return _parse_stream_json_kimi(raw_stdout, expect_subagent)
    return _parse_stream_json_claude(raw_stdout, expect_subagent)


def _parse_stream_json_claude(raw_stdout: str, expect_subagent: bool) -> dict:
    """Claude-specific parser (original logic, preserved exactly)."""
    final_text_parts: list[str] = []
    tool_calls: list[dict] = []
    turns_used: int = 0
    cost_usd: float | None = None
    warnings: list[str] = []
    last_assistant_text: str = ""
    subagent_text: str | None = None
    outer_result_text: str = ""
    result_usage: dict = {}

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
        elif t == "user":
            if expect_subagent and subagent_text is None and _is_outer_task_result(obj):
                extracted = _extract_tool_result_text(obj)
                if extracted:
                    subagent_text = extracted
        elif t == "result":
            turns_used = int(obj.get("num_turns", obj.get("turns", 0)) or 0)
            if "total_cost_usd" in obj:
                cost_usd = float(obj["total_cost_usd"])
            if obj.get("result"):
                outer_result_text = obj["result"]
            if isinstance(obj.get("usage"), dict):
                result_usage = obj["usage"]

    if expect_subagent:
        if subagent_text:
            final_text = subagent_text
            invocation_mode = "two-level"
        else:
            final_text = last_assistant_text or outer_result_text or "\n\n".join(final_text_parts)
            invocation_mode = "raw-prompt"
            warnings.append(
                "two-level spawn requested but no Task tool_result text found; "
                "falling back to outer session's assistant text"
            )
    else:
        final_text = outer_result_text or last_assistant_text or "\n\n".join(final_text_parts)
        invocation_mode = "raw-prompt"

    return {
        "final_text": final_text,
        "tool_calls": tool_calls,
        "turns_used": turns_used,
        "cost_usd": cost_usd,
        "invocation_mode": invocation_mode,
        "usage": result_usage,
        "_parse_warnings": warnings,
    }


def _parse_stream_json_kimi(raw_stdout: str, expect_subagent: bool) -> dict:
    """Kimi-specific parser for role-based stream-json format."""
    final_text_parts: list[str] = []
    tool_calls: list[dict] = []
    warnings: list[str] = []
    last_assistant_text: str = ""
    subagent_text: str | None = None
    outer_result_text: str = ""

    # Track the outer Agent tool call id for subagent extraction.
    outer_agent_call_id: str | None = None

    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            warnings.append(f"json_decode_error: {e}")
            continue

        role = obj.get("role")
        if role == "assistant":
            txt = _extract_kimi_assistant_text(obj)
            if txt:
                last_assistant_text = txt
                final_text_parts.append(txt)
            # Collect tool calls.
            for tc in obj.get("tool_calls", []):
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    tool_calls.append({
                        "name": func.get("name") if isinstance(func, dict) else None,
                        "id": tc.get("id"),
                    })
                    # Track the outer Agent call for subagent extraction.
                    if expect_subagent and outer_agent_call_id is None:
                        if isinstance(func, dict) and func.get("name") == "Agent":
                            outer_agent_call_id = tc.get("id")
        elif role == "tool":
            if expect_subagent and subagent_text is None:
                if outer_agent_call_id is not None and obj.get("tool_call_id") == outer_agent_call_id:
                    content = obj.get("content")
                    if isinstance(content, str):
                        extracted = _extract_kimi_subagent_text(content)
                        if extracted:
                            subagent_text = extracted

    # Kimi does not emit a result event; usage/cost are unavailable in stream-json.
    if expect_subagent:
        if subagent_text:
            final_text = subagent_text
            invocation_mode = "two-level"
        else:
            final_text = last_assistant_text or outer_result_text or "\n\n".join(final_text_parts)
            invocation_mode = "raw-prompt"
            warnings.append(
                "two-level spawn requested but no Agent tool response text found; "
                "falling back to outer session's assistant text"
            )
    else:
        final_text = outer_result_text or last_assistant_text or "\n\n".join(final_text_parts)
        invocation_mode = "raw-prompt"

    return {
        "final_text": final_text,
        "tool_calls": tool_calls,
        "turns_used": 0,
        "cost_usd": None,
        "invocation_mode": invocation_mode,
        "usage": {},
        "_parse_warnings": warnings,
    }


def build_trace(runs: list[dict]) -> dict:
    """Wrap per-run records in the trace shape consumed by scoring modules."""
    return {"runs": runs}
