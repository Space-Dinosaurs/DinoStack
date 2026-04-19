"""
Purpose: Probe for the Claude CLI, shell out to it with the eval-standard
         non-interactive flags, and return a normalized per-run record.

Public API: probe_claude_cli() -> str,
            invoke_run(prompt, worktree, timeout_seconds,
                       agent_name=None, mode="agent", home=None) -> dict,
            build_two_level_prompt(agent_name: str, brief: str) -> str.

            mode="command" skips the two-level Task wrapper, uses a
            permissive tool list + acceptEdits permission mode, and returns
            a filesystem snapshot under the "filesystem" key of the run
            record (keyed by repo-relative path, valued by sha256 hex).

Upstream deps: stdlib subprocess, time, tempfile, shutil; evals.runner.normalizer.

Downstream consumers: evals.runner.cli.

Failure modes: probe_claude_cli raises RuntimeError with remediation text if the
               `claude` binary is not on PATH. invoke_run captures timeouts and
               non-zero exits into the returned record's status field rather than
               raising; the scoring module decides how to score invalid runs.

               Two-level spawn: when agent_name is provided, the outer Claude
               session is instructed to spawn the named subagent via the Task
               tool and return its response verbatim. The normalizer extracts
               the subagent's text from the tool_result event. If no
               tool_result is present (e.g. the outer session refused to
               spawn), invocation_mode is reported as "raw-prompt" as a
               diagnostic fallback, and the outer assistant text is used.

Performance: dominated by the Claude CLI call itself (seconds). Runner overhead
             is a single subprocess.run per run.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from .normalizer import parse_stream_json

CLAUDE_BIN = "claude"

# Tier 1 is read-only. The Skeptic (and any future Tier 1 component) reads
# diffs and worker output - it does not execute shell commands and does not
# modify files. We therefore drop Bash/Write/Edit and restrict to read-only
# plus Task (for the two-level subagent spawn in invoke_run_two_level).
_ALLOWED_TOOLS = "Read,Grep,Glob,Task"
# Command-mode allows a top-level scaffolding command (e.g. /init-project) to
# read, write, and run shell tooling inside the isolated worktree. Tier 2's
# HOME redirect is what contains the blast radius; the tool list is
# permissive on purpose.
_COMMAND_ALLOWED_TOOLS = "Read,Grep,Glob,Task,Write,Edit,Bash"
_MAX_TURNS = "6"
# Command-mode runs can take many turns (scaffolding /init-project writes
# ~15 files, runs subprocess calls, and curates content). Give it more
# headroom than the Tier 1 subagent cap.
_COMMAND_MAX_TURNS = "60"


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


def build_two_level_prompt(agent_name: str, brief: str) -> str:
    """Wrap a subagent brief in the outer-session spawner instruction.

    The outer claude -p session's job is to spawn the named subagent via the
    Task tool, pass the brief through unchanged, and return the subagent's
    response verbatim. The outer session must not add commentary, and must
    not re-interpret or re-format the brief.
    """
    return (
        f"Invoke the Task tool exactly once with subagent_type='{agent_name}' "
        "and the prompt below. Return the subagent's response verbatim, with "
        "no added commentary or formatting.\n\n"
        "---\n\n"
        f"{brief.rstrip()}\n"
    )


def _snapshot_filesystem(root: Path) -> dict[str, str]:
    """Walk `root` and return {rel_path: sha256} for every regular file.

    Used by Tier 2 command-mode runs to capture the resulting worktree state
    so the scorer can check file existence, sizes, and content. Skips
    symlinks (shouldn't occur in a scaffolding run) and anything under
    `.git/` (none in Tier 2 worktrees today, but belt-and-braces).
    """
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        # Exclude .git defensively.
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            try:
                data = full.read_bytes()
            except OSError:
                continue
            rel = str(full.relative_to(root))
            out[rel] = hashlib.sha256(data).hexdigest()
    return out


def invoke_run(
    prompt: str,
    worktree: Path,
    timeout_seconds: int,
    agent_name: str | None = None,
    mode: str = "agent",
    home: Path | None = None,
) -> dict:
    """Run the Claude CLI once with `prompt` at `worktree` cwd; return a run record.

    Modes:
      "agent"   (default): wrap prompt in a two-level Task spawn of the named
                subagent; use the Tier 1 read-only tool list.
      "command": pass the prompt through verbatim (no Task wrapper), use the
                command tool list with acceptEdits, and capture a filesystem
                snapshot of the worktree on exit under the key "filesystem".

    If `home` is provided, the subprocess inherits the current environment
    except HOME is overridden to `home` (Tier 2 HOME redirect).
    """
    if mode == "command":
        outer_prompt = prompt
        allowed_tools = _COMMAND_ALLOWED_TOOLS
        permission_mode = "acceptEdits"
        max_turns = _COMMAND_MAX_TURNS
        expect_subagent = False
    else:
        if agent_name:
            outer_prompt = build_two_level_prompt(agent_name, prompt)
        else:
            outer_prompt = prompt
        allowed_tools = _ALLOWED_TOOLS
        permission_mode = "default"
        max_turns = _MAX_TURNS
        expect_subagent = bool(agent_name)

    # The Claude CLI accepts the prompt as the argument to -p; subprocess.run
    # passes it through argv without shell parsing, so no escaping is needed.
    cmd = [
        CLAUDE_BIN,
        "-p",
        outer_prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--allowed-tools", allowed_tools,
        "--permission-mode", permission_mode,
        "--max-turns", max_turns,
    ]

    env = None
    if home is not None:
        env = os.environ.copy()
        env["HOME"] = str(home)

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
            env=env,
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

    parsed = parse_stream_json(stdout, expect_subagent=expect_subagent)
    parsed["latency_ms"] = latency_ms
    parsed["status"] = status
    parsed["stderr_tail"] = stderr[-500:] if stderr else ""

    if mode == "command":
        parsed["filesystem"] = _snapshot_filesystem(worktree)

    return parsed
