"""
Purpose: Probe for the Claude CLI, shell out to it with the eval-standard
         non-interactive flags, and return a normalized per-run record.

Public API: probe_claude_cli() -> str,
            invoke_run(prompt: str, worktree: pathlib.Path, timeout_seconds: int) -> dict.

Upstream deps: stdlib subprocess, time, tempfile, shutil; evals.runner.normalizer.

Downstream consumers: evals.runner.cli.

Failure modes: probe_claude_cli raises RuntimeError with remediation text if the
               `claude` binary is not on PATH. invoke_run captures timeouts and
               non-zero exits into the returned record's status field rather than
               raising; the scoring module decides how to score invalid runs.

Performance: dominated by the Claude CLI call itself (seconds). Runner overhead
             is a single subprocess.run per run.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .normalizer import parse_stream_json

CLAUDE_BIN = "claude"

_ALLOWED_TOOLS = "Read,Grep,Glob,Bash"
_MAX_TURNS = "6"


def probe_claude_cli() -> str:
    if shutil.which(CLAUDE_BIN) is None:
        raise RuntimeError(
            "The `claude` CLI was not found on PATH. Install Claude Code "
            "(https://docs.claude.com/claude-code) and ensure `claude --version` "
            "runs before using the evals runner."
        )
    result = subprocess.run(
        [CLAUDE_BIN, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`claude --version` exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def invoke_run(prompt: str, worktree: Path, timeout_seconds: int) -> dict:
    """Run the Claude CLI once with `prompt` at `worktree` cwd; return a run record."""
    # The Claude CLI accepts the prompt as the argument to -p; subprocess.run
    # passes it through argv without shell parsing, so no escaping is needed.
    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--allowed-tools", _ALLOWED_TOOLS,
        "--permission-mode", "acceptEdits",
        "--max-turns", _MAX_TURNS,
    ]

    t0 = time.monotonic()
    status = "ok"
    stdout = ""
    stderr = ""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = result.stdout
        stderr = result.stderr
        if result.returncode != 0:
            status = f"cli_exit_{result.returncode}"
    except subprocess.TimeoutExpired as e:
        status = "timeout"
        stdout = (e.stdout.decode("utf-8", errors="replace") if e.stdout else "")
        stderr = (e.stderr.decode("utf-8", errors="replace") if e.stderr else "")
    latency_ms = int((time.monotonic() - t0) * 1000)

    parsed = parse_stream_json(stdout)
    parsed["latency_ms"] = latency_ms
    parsed["status"] = status
    parsed["stderr_tail"] = stderr[-500:] if stderr else ""
    return parsed
