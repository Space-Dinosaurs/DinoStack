"""
Purpose: Executes the `chrome-devtools-mcp` capability entry's `check:`
         command from content/agents/qa-engineer.md against controlled
         fixtures, pinning the DS-254 repair of a check that could never
         report the MCP as present.

         The pre-fix command grepped `.claude/settings.json` for
         `chrome-devtools`. That file is `{}` in this repo and carries no
         `mcpServers` key in any consumer, so the predicate was dead: it
         returned non-zero on every machine regardless of whether the server
         was registered. DS-254 replaced it with an inline Python check over
         `~/.claude.json` and a cwd-relative `.mcp.json`.

         The command is EXTRACTED from the spec at run time, never hardcoded
         here, so this file cannot drift from the spec it claims to test.

Public API: pytest test functions only. `extract_check_command()` and
         `run_check()` are module-level helpers, exposed separately so a
         mutation run can drive a mutated spec or command through the same
         fixtures.

Upstream dependencies: content/agents/qa-engineer.md (its fenced ```yaml
         `capabilities:` block); PyYAML; `sh` and `python3` on PATH, since
         the extracted command invokes python3.

Downstream consumers: .github/workflows/bin-tests.yml `python-bin-tests`
         job, which runs `pytest bin/tests/ -q` - full-directory glob
         discovery, so no per-file wiring is needed for a new test_*.py.

Failure modes: `extract_check_command()` is fail-closed - a missing
         `capabilities` block, zero or multiple `chrome-devtools-mcp`
         entries, or an empty/multi-line `check` value raises AssertionError
         rather than returning a string that would make every fixture
         assertion vacuous.

         Each fixture runs the check via `sh -c '<check>'` with `HOME`
         redirected to a scratch directory and `cwd` set to a scratch
         directory, matching the preflight runner
         (content/references/capability-preflight.md, "POSIX shell
         precondition"). Home isolation is load-bearing and self-testing: a
         machine whose real `~/.claude.json` registers chrome-devtools would
         return 0 from the no-registration fixture, failing it, so the
         fixture cannot pass with a leaked HOME.

Performance: negligible - one YAML parse plus four short-lived `sh`
         subprocesses.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_SPEC = REPO_ROOT / "content" / "agents" / "qa-engineer.md"

TOOL_NAME = "chrome-devtools-mcp"

# The name the check looks for inside `mcpServers`. It is NOT the capability
# entry's own `tool:` name above, and the difference is load-bearing: the
# command evaluates `'chrome-devtools' in s(f)` where `s(f)` is the
# `mcpServers` DICT, so `in` is exact key membership rather than the substring
# test it reads as. Registering the server under `chrome-devtools-mcp` returns
# non-zero. This matches the real `~/.claude.json`, whose key is
# `chrome-devtools`.
REGISTRATION_KEY = "chrome-devtools"

# Non-greedy body capture between a ```yaml opening fence and the next bare
# closing fence.
_FENCED_YAML = re.compile(r"^```yaml[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)

_CHECK_TIMEOUT_SECONDS = 30


def extract_check_command(spec_path: Path = AGENT_SPEC) -> str:
    """Extract the `check` command for TOOL_NAME out of the agent spec.

    Raises AssertionError on any step that cannot yield a usable command, so
    a broken extraction can never degrade into a silent empty string that
    makes the fixture assertions below pass without exercising anything.
    """
    text = spec_path.read_text(encoding="utf-8")

    checks: list[str] = []
    for block in _FENCED_YAML.finditer(text):
        try:
            parsed = yaml.safe_load(block.group(1))
        except yaml.YAMLError:
            # qa-engineer.md carries a second ```yaml fence (a non-YAML
            # example) that does not parse. Skipping it is correct; a
            # malformed `capabilities:` block still surfaces below as a
            # zero-entry failure rather than being silently accepted.
            continue
        if not isinstance(parsed, dict):
            continue
        capabilities = parsed.get("capabilities")
        if not isinstance(capabilities, dict):
            continue
        for group in ("required", "optional"):
            entries = capabilities.get(group)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("tool") == TOOL_NAME:
                    checks.append(entry.get("check"))

    if len(checks) != 1:
        raise AssertionError(
            f"{spec_path}: expected exactly one {TOOL_NAME!r} capability entry, "
            f"found {len(checks)}"
        )

    command = checks[0]
    if not isinstance(command, str) or not command.strip():
        raise AssertionError(
            f"{spec_path}: {TOOL_NAME!r} entry has an empty or non-string `check`"
        )
    if command != command.strip() or "\n" in command:
        raise AssertionError(
            f"{spec_path}: {TOOL_NAME!r} `check` is not a single trimmed line: {command!r}"
        )
    return command


def run_check(command: str, *, home: Path, cwd: Path) -> subprocess.CompletedProcess:
    """Run `command` as the capability preflight does (`sh -c`), with HOME
    redirected and cwd pinned to the fixture's own directories."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        ["sh", "-c", command],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_CHECK_TIMEOUT_SECONDS,
    )


def _write_registration(path: Path, server_name: str) -> None:
    path.write_text(
        json.dumps({"mcpServers": {server_name: {"command": "npx"}}}),
        encoding="utf-8",
    )


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    return home, cwd


def _describe(completed: subprocess.CompletedProcess) -> str:
    return (
        f"rc={completed.returncode} "
        f"stdout={completed.stdout.decode(errors='replace').strip()!r} "
        f"stderr={completed.stderr.decode(errors='replace').strip()!r}"
    )


def test_no_registration_reports_missing(tmp_path: Path) -> None:
    """No .claude.json in HOME and no .mcp.json in cwd -> non-zero."""
    command = extract_check_command()
    home, cwd = _scratch(tmp_path)

    completed = run_check(command, home=home, cwd=cwd)

    assert completed.returncode == 1, (
        "unregistered fixture must report the MCP as missing. "
        + _describe(completed)
    )


def test_home_claude_json_registration_reports_present(tmp_path: Path) -> None:
    """chrome-devtools in HOME/.claude.json -> zero."""
    command = extract_check_command()
    home, cwd = _scratch(tmp_path)
    _write_registration(home / ".claude.json", REGISTRATION_KEY)

    completed = run_check(command, home=home, cwd=cwd)

    assert completed.returncode == 0, (
        f"{TOOL_NAME!r} registered in $HOME/.claude.json must report present. "
        + _describe(completed)
    )


def test_cwd_mcp_json_registration_reports_present(tmp_path: Path) -> None:
    """chrome-devtools in a cwd-relative .mcp.json -> zero.

    The command consults this path as well as `~/.claude.json`; exercising
    only the HOME arm would leave half the command unpinned.
    """
    command = extract_check_command()
    home, cwd = _scratch(tmp_path)
    _write_registration(cwd / ".mcp.json", REGISTRATION_KEY)

    completed = run_check(command, home=home, cwd=cwd)

    assert completed.returncode == 0, (
        f"{TOOL_NAME!r} registered in ./.mcp.json must report present. "
        + _describe(completed)
    )


def test_unrelated_server_registration_reports_missing(tmp_path: Path) -> None:
    """A .mcp.json registering some other server -> non-zero.

    Guards the `in` predicate on the server NAME: a rewrite that returns 0
    on the mere existence of a registration file would satisfy the two
    presence fixtures above while reporting every unrelated MCP as the one
    under test.
    """
    command = extract_check_command()
    home, cwd = _scratch(tmp_path)
    _write_registration(cwd / ".mcp.json", "some-other-mcp")

    completed = run_check(command, home=home, cwd=cwd)

    assert completed.returncode == 1, (
        "an unrelated MCP registration must not satisfy the "
        f"{TOOL_NAME!r} check. " + _describe(completed)
    )
