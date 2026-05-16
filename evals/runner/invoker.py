"""
Purpose: Probe for the Claude CLI, shell out to it with the eval-standard
         non-interactive flags, and return a normalized per-run record.

Public API: probe_cli(backend) -> str,
            invoke_run(prompt, worktree, timeout_seconds,
                       agent_name=None, mode="agent", home=None,
                       model=None, system_prompt=None, backend="claude") -> dict,
            build_two_level_prompt(agent_name: str, brief: str, backend="claude") -> str.

            mode="command" skips the two-level Task wrapper, uses a
            permissive tool list + acceptEdits permission mode, and returns
            a filesystem snapshot under the "filesystem" key of the run
            record (keyed by repo-relative path, valued by sha256 hex).

Upstream deps: stdlib subprocess, time, tempfile, shutil; evals.runner.normalizer.

Downstream consumers: evals.runner.cli.

Failure modes: probe_cli raises RuntimeError with remediation text if the
               requested binary is not on PATH. invoke_run captures timeouts and
               non-zero exits into the returned record's status field rather than
               raising; the scoring module decides how to score invalid runs.

               Two-level spawn: when agent_name is provided, the outer CLI
               session is instructed to spawn the named subagent via the Task
               tool (Claude) or Agent tool (Kimi) and return its response verbatim.
               The normalizer extracts the subagent's text from the tool_result
               event. If no tool_result is present (e.g. the outer session refused
               to spawn), invocation_mode is reported as "raw-prompt" as a
               diagnostic fallback, and the outer assistant text is used.

Performance: dominated by the CLI call itself (seconds). Runner overhead
             is a single subprocess.run per run.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from .normalizer import parse_stream_json

CLAUDE_BIN = "claude"
KIMI_BIN = "kimi"

_LOG = logging.getLogger(__name__)


class Backend:
    """Backend identifiers for the eval runner."""

    CLAUDE = "claude"
    KIMI = "kimi"


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
# SWE-bench fix tasks need many turns: read files, edit, run tests, iterate.
# Raised from 6 to 40 (smoke v5 regression: engineer hit max_turns at 6 and
# exited despite $0.75 spend with no fix applied).
# The _MAX_TURNS_DEFAULT is the process-level default; invoke_run accepts an
# optional max_turns kwarg so the runner CLI can override via --max-turns.
_MAX_TURNS_DEFAULT = 40
_MAX_TURNS = str(_MAX_TURNS_DEFAULT)
# Command-mode runs can take many turns (scaffolding /init-project writes
# ~15 files, runs subprocess calls, and curates content). Give it more
# headroom than the Tier 1 subagent cap.
_COMMAND_MAX_TURNS = "60"


def probe_claude_cli() -> str:
    """Legacy alias for probe_cli(Backend.CLAUDE). Kept for backward compat."""
    return probe_cli(Backend.CLAUDE)


def probe_cli(backend: str = Backend.CLAUDE) -> str:
    """Check that the requested CLI binary is on PATH and returns its version."""
    if backend == Backend.KIMI:
        bin_name = KIMI_BIN
        install_hint = (
            "Install Kimi CLI (https://docs.moonshot.cn/kimi-cli) and ensure "
            "`kimi --version` runs before using the evals runner."
        )
    else:
        bin_name = CLAUDE_BIN
        install_hint = (
            "Install Claude Code (https://docs.claude.com/claude-code) and ensure "
            "`claude --version` runs before using the evals runner."
        )

    if shutil.which(bin_name) is None:
        raise RuntimeError(
            f"The `{bin_name}` CLI was not found on PATH. {install_hint}"
        )
    result = subprocess.run(
        [bin_name, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`{bin_name} --version` exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def build_two_level_prompt(agent_name: str, brief: str, backend: str = Backend.CLAUDE) -> str:
    """Wrap a subagent brief in the outer-session spawner instruction.

    The outer CLI session's job is to spawn the named subagent via the
    Task tool (Claude) or Agent tool (Kimi), pass the brief through unchanged,
    and return the subagent's response verbatim. The outer session must not add
    commentary, and must not re-interpret or re-format the brief.
    """
    if backend == Backend.KIMI:
        tool_name = "Agent"
        instruction = (
            f"Use the {tool_name} tool exactly once with subagent_type='{agent_name}' "
            "and the prompt below. Return the subagent's response verbatim, with "
            "no added commentary or formatting.\n\n"
        )
    else:
        tool_name = "Task"
        instruction = (
            f"Invoke the {tool_name} tool exactly once with subagent_type='{agent_name}' "
            "and the prompt below. Return the subagent's response verbatim, with "
            "no added commentary or formatting.\n\n"
        )
    return (
        instruction
        + "---\n\n"
        + f"{brief.rstrip()}\n"
    )


def _snapshot_filesystem(root: Path) -> dict[str, str]:
    """Walk `root` and return {rel_path: sha256} for every regular file.

    Used by Tier 2 command-mode runs to capture the resulting worktree state
    so the scorer can check file existence, sizes, and content. Skips
    symlinks (shouldn't occur in a scaffolding run) and anything under
    `.git/` (none in Tier 2 worktrees today, but belt-and-suspenders).
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
    model: str | None = None,
    system_prompt: str | None = None,
    max_turns: int | None = None,
    backend: str = Backend.CLAUDE,
) -> dict:
    """Run the CLI once with `prompt` at `worktree` cwd; return a run record.

    Modes:
      "agent"   (default): wrap prompt in a two-level Task/Agent spawn of the named
                subagent; use the Tier 1 read-only tool list.
      "command": pass the prompt through verbatim (no Task/Agent wrapper), use the
                command tool list with acceptEdits, and capture a filesystem
                snapshot of the worktree on exit under the key "filesystem".

    If `home` is provided, the subprocess inherits the current environment
    except HOME is overridden to `home` (Tier 2 HOME redirect).

    If `model` is provided, --model is passed through to the CLI.

    If `system_prompt` is provided, it is appended to the default system
    prompt via --append-system-prompt (Claude only). For Kimi, this parameter
    is ignored with a warning because Kimi has no equivalent flag.

    If `max_turns` is provided, it overrides the module-level default for
    agent mode (_MAX_TURNS_DEFAULT=40) or command mode (_COMMAND_MAX_TURNS=60).
    Useful for SWE-bench fix tasks that need more tool iterations.

    `backend` selects the CLI to invoke: "claude" (default) or "kimi".
    """
    if mode == "command":
        outer_prompt = prompt
        allowed_tools = _COMMAND_ALLOWED_TOOLS
        permission_mode = "acceptEdits"
        effective_max_turns = str(max_turns) if max_turns is not None else _COMMAND_MAX_TURNS
        expect_subagent = False
    else:
        if agent_name:
            outer_prompt = build_two_level_prompt(agent_name, prompt, backend=backend)
        else:
            outer_prompt = prompt
        allowed_tools = _ALLOWED_TOOLS
        permission_mode = "default"
        effective_max_turns = str(max_turns) if max_turns is not None else _MAX_TURNS
        expect_subagent = bool(agent_name)

    if backend == Backend.KIMI:
        cmd = [
            KIMI_BIN,
            "-p",
            outer_prompt,
            "--print",
            "--yolo",
            "--output-format", "stream-json",
            "--work-dir", str(worktree),
            "--max-steps-per-turn", effective_max_turns,
        ]
        if model is not None:
            cmd.extend(["--model", model])
        if system_prompt is not None:
            _LOG.warning(
                "Kimi backend does not support --append-system-prompt; "
                "system_prompt parameter is ignored."
            )
        # Disable MCP servers for eval runs to avoid connection errors from
        # misconfigured or unavailable MCP servers interfering with the harness.
        cmd.extend(["--mcp-config-file", "/tmp/empty-mcp.json"])
        # Kimi uses --work-dir instead of subprocess cwd.
        subprocess_cwd = None
    else:
        # Claude CLI accepts the prompt as the argument to -p; subprocess.run
        # passes it through argv without shell parsing, so no escaping is needed.
        cmd = [
            CLAUDE_BIN,
            "-p",
            outer_prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--allowed-tools", allowed_tools,
            "--permission-mode", permission_mode,
            "--max-turns", effective_max_turns,
        ]
        if model is not None:
            cmd.extend(["--model", model])
        if system_prompt is not None:
            # Inject AE rules (or any system context) via --append-system-prompt.
            # This appends to (not replaces) the default Claude Code system prompt,
            # preserving the baseline context while adding the AE methodology rules.
            # Flag verified in `claude --help` (2026-05-12).
            cmd.extend(["--append-system-prompt", system_prompt])
        subprocess_cwd = str(worktree)

    # Route through litellm when model id uses a non-Anthropic prefix.
    _litellm_prefixes = ("claude-kimi-", "claude-qwen-", "claude-owl-", "claude-deepseek")
    _use_litellm = model is not None and any(model.startswith(p) for p in _litellm_prefixes)

    env = None
    if home is not None or _use_litellm:
        env = os.environ.copy()
        if home is not None:
            env["HOME"] = str(home)
            # Prepend $HOME/bin so per-fixture stubs (e.g. a `gh` stub placed
            # by a seed hook) shadow any matching binary on the developer's
            # real PATH. This is the Tier 2 proxy boundary for CLI tools the
            # command body shells out to.
            env["PATH"] = f"{home}/bin:" + env.get("PATH", "")
        if _use_litellm:
            env["ANTHROPIC_BASE_URL"] = "http://localhost:4000"
            # Preflight: verify the litellm proxy is reachable before invoking.
            import urllib.request as _ur
            try:
                _ur.urlopen("http://localhost:4000/v1/models", timeout=5)
            except Exception as _e:
                parsed = {
                    "status": "proxy-unreachable",
                    "stderr_tail": f"litellm proxy preflight failed: {_e}",
                    "final_text": "",
                    "tool_calls": [],
                    "tokens": {},
                    "latency_ms": 0,
                }
                if mode == "command":
                    parsed["filesystem"] = _snapshot_filesystem(worktree)
                return parsed

    t0 = time.monotonic()
    status = "ok"
    stdout = ""
    stderr = ""
    try:
        result = subprocess.run(
            cmd,
            cwd=subprocess_cwd,
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
    # Expose the raw CLI stdout so callers can write a verbatim transcript.
    # final_text is derived from parsed stream-json events and may be empty
    # if the stream had no assistant text (e.g. all tool-use); cli_stdout is
    # the unprocessed pipe capture and is always the ground-truth transcript.
    parsed["cli_stdout"] = stdout

    if mode == "command":
        parsed["filesystem"] = _snapshot_filesystem(worktree)

    return parsed
