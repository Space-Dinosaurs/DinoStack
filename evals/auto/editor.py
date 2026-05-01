"""
Purpose: Spawn the editor-agent as a headless `claude -p` subprocess with
         Read/Grep/Glob allowed and NO write tools. Build the brief by
         substituting component context into program.md and return the raw
         response text (stdout assistant text).

Public API: build_brief(template: str, context: dict) -> str,
            spawn_editor(repo_root: Path, brief: str, timeout_sec: int = 600,
                         model: str | None = None) -> dict with keys
            {ok: bool, text: str, stderr: str, returncode: int, cost_usd: float}.

Upstream deps: stdlib subprocess, pathlib, json.

Downstream consumers: evals.auto.loop.

Failure modes: spawn_editor returns ok=False on nonzero exit or timeout; does
               not raise. Cost is extracted from the stream-json `result` event
               if present, else 0.0.

Performance: single `claude -p` invocation, typically 30-120s wall time.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional


_PROGRAM_MD_PATH = Path(__file__).resolve().parent / "program.md"


def load_program_template() -> str:
    return _PROGRAM_MD_PATH.read_text(encoding="utf-8")


def build_brief(template: str, context: Dict[str, object]) -> str:
    """Simple {{KEY}} substitution. Missing keys raise KeyError so the caller
    notices (we'd rather fail loudly than ship a brief with unresolved
    placeholders to the model).
    """
    out = template
    required = ("COMPONENT", "EDITABLE_FILES", "LOCKED_FILES", "BASELINE_METRIC",
                "POOLED_STDEV", "MAX_EDIT_LOC", "DIMENSION_SIGNAL")
    for key in required:
        if key not in context:
            raise KeyError(f"build_brief: missing required context key {key!r}")
    for key, value in context.items():
        out = out.replace("{{" + str(key) + "}}", str(value))
    return out


def _extract_assistant_text(stream_json: str) -> tuple:
    """Walk the stream-json output and return (final_text, cost_usd).

    We concatenate assistant text blocks in order and read total_cost_usd
    from the final `result` event.
    """
    texts = []
    cost = 0.0
    for line in stream_json.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        texts.append(b.get("text", ""))
        elif t == "result":
            if "total_cost_usd" in obj:
                try:
                    cost = float(obj["total_cost_usd"])
                except (TypeError, ValueError):
                    cost = 0.0
            # `result` events also carry a consolidated `result` string.
            if not texts and obj.get("result"):
                texts.append(str(obj["result"]))
    return ("".join(texts), cost)


def spawn_editor(
    repo_root: Path,
    brief: str,
    timeout_sec: int = 600,
    model: Optional[str] = None,
) -> Dict[str, object]:
    """Invoke `claude -p` with Read/Grep/Glob only and return the response."""
    cmd = [
        "claude", "-p", brief,
        "--allowed-tools", "Read,Grep,Glob",
        "--permission-mode", "default",
        "--output-format", "stream-json",
        "--verbose",
    ]
    if model:
        cmd.extend(["--model", model])
    try:
        r = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "text": "",
            "stderr": f"timeout after {timeout_sec}s",
            "returncode": -1,
            "cost_usd": 0.0,
        }
    text, cost = _extract_assistant_text(r.stdout)
    return {
        "ok": r.returncode == 0,
        "text": text,
        "stderr": r.stderr,
        "returncode": r.returncode,
        "cost_usd": cost,
    }
