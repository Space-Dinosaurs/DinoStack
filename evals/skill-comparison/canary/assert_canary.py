#!/usr/bin/env python3
"""
assert_canary.py - Parse a stream-json JSONL transcript and assert canary
                   conditions for the skill-comparison eval.

Purpose: Assert that a skill-comparison eval transcript proves the expected
         subagent was (a) registered in the outer session's init.agents list
         (load-bearing: CLI cannot register an agent without parsing its
         frontmatter), and (b) spawned via a direct two-level Task/Agent call
         from the outer conductor (not a nested spawn from an inner agent).
         Tool-list evidence is derived from the agent's frontmatter at assert
         time via _parse_frontmatter_tools(), not hardcoded.

         NOTE (Critical finding fix): Prior to this revision, Assertion 2 used
         a blob-search for tool name strings that trivially passed on any
         well-formed CLI transcript because the outer conductor's system/init
         event always lists Read, Grep, Glob, Bash as conductor tools. That
         blob-search is now REMOVED as a passing condition. The load-bearing
         check is agent registration in init.agents (CLI cannot register an
         agent without parsing its frontmatter). A separate
         frontmatter-tool-match check verifies the registered agent's tools
         match what the frontmatter declares, if init.agents surfaces tools.

Public API: assert_canary(transcript_path, agent_name, expected_tools) -> (bool, list[str])
            parse_frontmatter_tools(agent_md_path) -> list[str]

Upstream deps: stdlib (argparse, json, pathlib, sys, re).

Downstream consumers: evals/skill-comparison/canary/run_canary.sh,
                      evals/skill-comparison/tests/test_assert_canary.py.

Failure modes: returns (False, [message]) on assertion failure; returns
               (False, [message]) if transcript_path does not exist.
               parse_frontmatter_tools raises FileNotFoundError if the agent
               .md file is missing.

Performance: O(transcript lines); dominated by JSON parse. Standard for
             ~100-line transcripts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_AGENT = "skeptic"

# Path to the skeptic frontmatter relative to the repo root.
# Resolved at import time by walking up from this file's location.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_AGENT_MD = _REPO_ROOT / ".claude" / "agents" / "skeptic.md"


def parse_frontmatter_tools(agent_md_path: Path) -> list[str]:
    """Parse the YAML frontmatter of a .claude/agents/*.md file and return
    the tools list.

    The frontmatter block is delimited by ``---`` lines at the top of the
    file.  The ``tools:`` line is expected to be one of two supported forms:

    - Comma-separated bare list: ``tools: Read, Grep, Glob, Bash``
    - Inline YAML bracket list: ``tools: [Read, Grep, Glob, Bash]``

    Block-sequence form (multi-line ``- Read``) is NOT supported.

    Args:
        agent_md_path: Absolute path to the agent markdown file.

    Returns:
        List of tool name strings, e.g. ["Read", "Grep", "Glob", "Bash"].

    Raises:
        FileNotFoundError: if agent_md_path does not exist.
        ValueError: if no ``tools:`` key is found in the frontmatter.
    """
    if not agent_md_path.exists():
        raise FileNotFoundError(
            f"Agent frontmatter file not found: {agent_md_path}"
        )

    text = agent_md_path.read_text(encoding="utf-8")
    # Extract content between first pair of --- delimiters.
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        raise ValueError(
            f"No YAML frontmatter block found in {agent_md_path}"
        )

    frontmatter = match.group(1)
    tools_match = re.search(r"^tools:\s*(.+)$", frontmatter, re.MULTILINE)
    if not tools_match:
        raise ValueError(
            f"No 'tools:' key found in frontmatter of {agent_md_path}"
        )

    raw = tools_match.group(1).strip()
    # Strip surrounding brackets for inline YAML bracket-list form: [Read, Grep, ...]
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip() for t in raw.split(",") if t.strip()]


def _parse_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file and return a list of parsed JSON objects.

    Malformed lines are skipped with a warning to stderr.
    """
    lines: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for i, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                lines.append(obj)
            except json.JSONDecodeError as exc:
                print(f"[warn] line {i}: invalid JSON - {exc}", file=sys.stderr)
    return lines


def _find_task_spawn(events: list[dict], agent_name: str) -> dict | None:
    """Return the first OUTER-CONDUCTOR tool_use block for a direct Task/Agent
    spawn of agent_name, or None.

    Only events where ``parent_tool_use_id`` is absent or None are examined.
    This enforces the Brief's requirement of a "direct two-level Task spawn":
    spawns from inner agents (nested, with a non-None parent_tool_use_id) are
    rejected to prevent false positives from deeply nested sub-spawns.

    Searches outer-conductor assistant-type events for a tool_use block where:
      - name == "Task" OR name == "Agent" (Claude CLI versions vary on tool name)
      - input.subagent_type == agent_name (case-insensitive)
    """
    _SPAWN_TOOL_NAMES = {"Task", "Agent"}

    for event in events:
        if event.get("type") != "assistant":
            continue
        # Reject nested events (from inner agents) - only outer conductor events
        # have parent_tool_use_id absent or None.
        if event.get("parent_tool_use_id") is not None:
            continue
        msg = event.get("message", {})
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in _SPAWN_TOOL_NAMES:
                continue
            inp = block.get("input", {})
            subagent_type = inp.get("subagent_type", "")
            if subagent_type.lower() == agent_name.lower():
                return block
    return None


def _find_task_result_with_agent_type(events: list[dict], agent_name: str) -> dict | None:
    """Return the outer Task tool_result user event for agent_name, or None.

    The outer Task result arrives as a user event with:
      - parent_tool_use_id == None
      - tool_use_result.agentType == agent_name
    """
    for event in events:
        if event.get("type") != "user":
            continue
        if event.get("parent_tool_use_id") is not None:
            continue
        tur = event.get("tool_use_result", {})
        if isinstance(tur, dict):
            at = tur.get("agentType", "")
            if at.lower() == agent_name.lower():
                return event
    return None


def _check_agent_registered(
    events: list[dict],
    agent_name: str,
    expected_tools: list[str],
) -> tuple[bool, str]:
    """Assert that the inner agent is registered in the outer session's
    init.agents list.

    This is the LOAD-BEARING check for Assertion 2. The Claude CLI cannot
    register an agent in init.agents without parsing its frontmatter file.
    Agent registration therefore proves the frontmatter (including the tools
    list) was loaded by the CLI at startup.

    Blob-search for tool-name strings is NOT used as a passing condition
    because the outer session's system/init event always lists conductor tools
    (Read, Grep, Glob, Bash) regardless of whether the inner agent's
    frontmatter was loaded - that check is vacuous.

    If init.agents surfaces the agent's tool list, we also verify it matches
    the expected_tools derived from the frontmatter. If the CLI does not
    surface tools per registered agent (format varies by CLI version), we
    rely solely on the registration boolean.

    Returns (passed: bool, diagnostic: str).
    """
    for event in events:
        if event.get("type") != "system" or event.get("subtype") != "init":
            continue

        agents_list = event.get("agents", [])
        if not isinstance(agents_list, list):
            continue

        # Extract registered agent names (may be strings or dicts with "name").
        registered_names: set[str] = set()
        agent_tools_map: dict[str, list[str]] = {}
        for a in agents_list:
            if isinstance(a, str):
                registered_names.add(a.lower())
            elif isinstance(a, dict):
                name = a.get("name", "")
                if name:
                    registered_names.add(name.lower())
                    # Some CLI versions surface tools per agent.
                    tools = a.get("tools", [])
                    if isinstance(tools, list) and tools:
                        agent_tools_map[name.lower()] = [
                            str(t) for t in tools
                        ]

        if agent_name.lower() not in registered_names:
            return False, (
                f"Agent '{agent_name}' is NOT in the outer session's "
                f"init.agents list. Registered agents: {sorted(registered_names)}. "
                f"The CLI must register the agent by parsing its frontmatter at "
                f"startup. Check that .claude/agents/{agent_name}.md exists and "
                f"is well-formed."
            )

        # Agent is registered - frontmatter was loaded.
        # If the CLI surfaces per-agent tools, verify they match frontmatter.
        agent_lower = agent_name.lower()
        if agent_lower in agent_tools_map:
            registered_tools = [t.strip() for t in agent_tools_map[agent_lower]]
            expected_set = set(expected_tools)
            registered_set = set(registered_tools)
            if not expected_set.issubset(registered_set):
                missing = sorted(expected_set - registered_set)
                return False, (
                    f"Agent '{agent_name}' is registered but its tool list in "
                    f"init.agents is missing expected tools: {missing}. "
                    f"Expected (from frontmatter): {sorted(expected_set)}. "
                    f"Registered: {sorted(registered_set)}."
                )
            return True, (
                f"Agent '{agent_name}' is registered in init.agents with "
                f"matching tool list: {sorted(registered_set)}."
            )

        # CLI does not surface per-agent tools - rely on registration alone.
        return True, (
            f"Agent '{agent_name}' is registered in init.agents (frontmatter "
            f"loaded by CLI). Per-agent tool list not surfaced in this CLI "
            f"version; relying on registration as proof of frontmatter load."
        )

    # No system/init event found.
    return False, (
        f"No system/init event found in transcript. Cannot verify agent "
        f"'{agent_name}' registration. Transcript may be truncated or from "
        f"an unsupported CLI version."
    )


def assert_canary(
    transcript_path: Path,
    agent_name: str = _DEFAULT_AGENT,
    expected_tools: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Parse transcript and assert canary conditions.

    Returns:
        (passed: bool, diagnostics: list[str])
        passed is True when all assertions hold.
        diagnostics is empty on success; contains failure messages on failure.
    """
    if expected_tools is None:
        # Derive expected tools from the frontmatter - single source of truth.
        try:
            expected_tools = parse_frontmatter_tools(_DEFAULT_AGENT_MD)
        except (FileNotFoundError, ValueError) as exc:
            # Fall back to known-good defaults if frontmatter is unavailable
            # (e.g., running tests outside the repo). Log a warning.
            print(
                f"[warn] could not parse frontmatter from {_DEFAULT_AGENT_MD}: {exc}. "
                f"Falling back to hardcoded defaults.",
                file=sys.stderr,
            )
            expected_tools = ["Read", "Grep", "Glob", "Bash"]

    if not transcript_path.exists():
        return False, [f"Transcript file not found: {transcript_path}"]

    events = _parse_jsonl(transcript_path)
    if not events:
        return False, [f"Transcript is empty or all lines are malformed: {transcript_path}"]

    failures: list[str] = []

    # Assertion 1: Direct outer-conductor Task/Agent tool_use with
    # subagent_type == agent_name (parent_tool_use_id must be absent/None).
    task_block = _find_task_spawn(events, agent_name)
    if task_block is None:
        # Also try finding via tool_result agentType (some CLI versions may
        # emit the subagent type only in the result event).
        task_result = _find_task_result_with_agent_type(events, agent_name)
        if task_result is None:
            failures.append(
                f"Assertion 1 FAILED: No direct outer-conductor Task/Agent "
                f"tool_use event found with subagent_type='{agent_name}' AND "
                f"no outer Task tool_result with agentType='{agent_name}'. "
                f"This means the harness did not spawn the {agent_name} agent "
                f"via a direct two-level Task call (nested spawns are rejected), "
                f"or the transcript does not capture the spawn event."
            )
            # Cannot check assertion 2 without the task block.
            return False, failures
        else:
            # Synthesize a minimal task_block from the result for assertion 2.
            task_block = {"_from_result": True, "_result_event": task_result}
    else:
        # Verify the agentType in the tool_result also matches (belt-and-braces).
        task_result = _find_task_result_with_agent_type(events, agent_name)
        if task_result is None:
            # Tool_use found but no matching result - may be timeout or truncated.
            # Flag as a warning but do not fail assertion 1.
            print(
                f"[warn] Task/Agent tool_use for '{agent_name}' found but no "
                f"matching outer Task tool_result. Transcript may be truncated.",
                file=sys.stderr,
            )

    # Assertion 2: Agent is registered in outer session's init.agents list.
    # This is the load-bearing check: CLI cannot register an agent without
    # parsing its frontmatter. Blob-search for tool strings is NOT used as a
    # passing condition (vacuous: outer conductor tools always appear in init).
    registered_ok, registered_diag = _check_agent_registered(
        events, agent_name, expected_tools
    )
    if not registered_ok:
        failures.append(f"Assertion 2 FAILED: {registered_diag}")

    return len(failures) == 0, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert canary conditions on a skill-comparison stream-json transcript."
    )
    parser.add_argument(
        "transcript",
        type=Path,
        help="Path to the JSONL stream-json transcript file.",
    )
    parser.add_argument(
        "--agent-name",
        default=_DEFAULT_AGENT,
        help=f"Name of the subagent expected in the transcript (default: {_DEFAULT_AGENT}).",
    )
    parser.add_argument(
        "--agent-md",
        type=Path,
        default=None,
        help=(
            "Path to the agent .md file for frontmatter tool parsing. "
            "Defaults to .claude/agents/<agent-name>.md relative to repo root."
        ),
    )
    parser.add_argument(
        "--expected-tools",
        default=None,
        help=(
            "Comma-separated list of tool names expected in the agent's "
            "frontmatter (overrides frontmatter parsing; for testing only)."
        ),
    )
    args = parser.parse_args()

    # Resolve expected tools: CLI override > frontmatter parsing.
    if args.expected_tools is not None:
        expected_tools: list[str] | None = [
            t.strip() for t in args.expected_tools.split(",") if t.strip()
        ]
    elif args.agent_md is not None:
        try:
            expected_tools = parse_frontmatter_tools(args.agent_md)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
    else:
        expected_tools = None  # let assert_canary derive from default path

    passed, failures = assert_canary(
        transcript_path=args.transcript,
        agent_name=args.agent_name,
        expected_tools=expected_tools,
    )

    if passed:
        print(
            f"[canary PASS] Transcript {args.transcript} verified: "
            f"Task spawn of '{args.agent_name}' confirmed and agent is "
            f"registered in init.agents (frontmatter loaded)."
        )
        return 0
    else:
        print("[canary FAIL] One or more assertions failed:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
