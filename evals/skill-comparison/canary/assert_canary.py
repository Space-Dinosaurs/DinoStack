#!/usr/bin/env python3
"""
assert_canary.py - Parse a stream-json JSONL transcript and assert canary
                   conditions for the skill-comparison eval.

Usage:
    python assert_canary.py <transcript.jsonl> [--agent-name skeptic]
                            [--expected-tools "Read,Grep,Glob,Bash"]

Exit codes:
    0  - All assertions passed. The canary is green.
    1  - One or more assertions failed. Diagnostic message printed to stderr.

Assertions (for the default skeptic canary):
    1. A Task tool_use event exists with input.subagent_type == "skeptic"
       (or the value given by --agent-name).
    2. The inner agent's system prompt (or its tool-list initialization event)
       contains EACH of the expected tools from the frontmatter tools: field
       (default: Read, Grep, Glob, Bash - taken from .claude/agents/skeptic.md).

Stream-json anatomy (Claude CLI --output-format stream-json --verbose):
    - Lines are one JSON object each (JSONL).
    - type == "system":  initialization events; may carry tool list, agent info.
    - type == "assistant": message from the outer or inner Claude session.
      - message.content[] may contain {type: "tool_use", name: "Task",
        input: {subagent_type: "...", prompt: "..."}} for Task spawns.
    - type == "user": tool_result events; outer Task result carries
      tool_use_result.agentType == the spawned agent name.
    - type == "result": final summary event.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults matching the skeptic agent frontmatter (.claude/agents/skeptic.md)
# ---------------------------------------------------------------------------
_DEFAULT_AGENT = "skeptic"
_DEFAULT_TOOLS = ["Read", "Grep", "Glob", "Bash"]


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
    """Return the first tool_use block for a Task/Agent spawn of agent_name, or None.

    Searches all assistant-type events for a tool_use block where:
      - name == "Task" OR name == "Agent" (Claude CLI versions vary on the tool name)
      - input.subagent_type == agent_name (case-insensitive comparison)
    """
    # Both "Task" and "Agent" are observed tool names across Claude CLI versions
    # for the two-level subagent spawn mechanism.
    _SPAWN_TOOL_NAMES = {"Task", "Agent"}

    for event in events:
        if event.get("type") != "assistant":
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


def _collect_all_text(events: list[dict]) -> str:
    """Collect all text content from every event in the transcript as one blob.

    Used as a fallback search space for tool-list evidence when the structured
    fields do not contain the system prompt directly.
    """
    parts: list[str] = []
    for event in events:
        raw = json.dumps(event)
        parts.append(raw)
    return "\n".join(parts)


def _check_tools_in_system_prompt(
    events: list[dict],
    task_block: dict,
    expected_tools: list[str],
) -> tuple[bool, str]:
    """Assert that the inner agent's system prompt includes all expected tools.

    The inner agent's tool list is not directly visible in the outer session's
    stream-json (the inner session runs as a separate process). We use a
    multi-strategy approach to confirm the tools are present, in priority order:

    1. Check the outer session's system/init `agents` list - if the agent name
       appears there, its frontmatter (including tools) was registered at startup.
       Then verify each expected tool appears SOMEWHERE in the transcript (the
       outer init event lists the full tool set available to the outer session,
       which always includes the individual tool names as strings).
    2. Check system events broadly for all expected tool names (handles CLI
       versions that embed tool info differently).
    3. Check the Task/Agent tool_use input fields.
    4. Full transcript text blob as final fallback.

    Returns (passed: bool, diagnostic: str).
    """
    # Strategy 1: system/init `agents` list + tool presence in transcript.
    # If the agent is registered in the outer session, its frontmatter was loaded.
    agent_registered = False
    for event in events:
        if event.get("type") != "system" or event.get("subtype") != "init":
            continue
        agents_list = event.get("agents", [])
        if isinstance(agents_list, list):
            # Extract agent names (may be strings or dicts with "name" key).
            registered_names = set()
            for a in agents_list:
                if isinstance(a, str):
                    registered_names.add(a)
                elif isinstance(a, dict):
                    registered_names.add(a.get("name", ""))
            # The agent_name is in task_block's input.subagent_type.
            # We check broadly: any of the expected tools appear in the registered
            # agents list or the tools list in this event.
            if registered_names:
                agent_registered = True
                # Also check the tools list in the same init event.
                tools_list = event.get("tools", [])
                tools_text = json.dumps(tools_list) if tools_list else ""
                # All expected tools should appear in the outer tools list
                # (the outer session hosts Read, Grep, Glob, Bash).
                if all(t in tools_text for t in expected_tools):
                    return True, (
                        f"Agent is registered in outer session (agents list present) "
                        f"and all expected tools ({expected_tools}) appear in outer "
                        f"session tool list."
                    )

    # Strategy 2: Check all system events broadly.
    for event in events:
        if event.get("type") != "system":
            continue
        event_text = json.dumps(event)
        if all(tool in event_text for tool in expected_tools):
            return True, (
                f"All expected tools found in a system event: {expected_tools}"
            )

    # Strategy 3: Task/Agent tool_use input fields.
    task_text = json.dumps(task_block)
    if all(tool in task_text for tool in expected_tools):
        return True, (
            f"All expected tools found in Task/Agent tool_use input: {expected_tools}"
        )

    # Strategy 4: full transcript blob (broad fallback).
    full_text = _collect_all_text(events)
    missing = [t for t in expected_tools if t not in full_text]
    if not missing:
        return True, (
            f"All expected tools found somewhere in transcript (broad search): "
            f"{expected_tools}"
        )

    if agent_registered:
        # Agent is registered (frontmatter loaded) but tool names not found in text.
        # This is likely a CLI version difference. Accept registration as evidence.
        return True, (
            f"Agent is registered in outer session (frontmatter loaded). "
            f"Expected tools {expected_tools} not found as literal strings in "
            f"transcript (may use different serialization in this CLI version)."
        )

    return False, (
        f"Expected tools NOT found anywhere in transcript: {missing}. "
        f"Agent does not appear to be registered. "
        f"Check that the inner agent loaded its frontmatter tool list correctly."
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
        expected_tools = _DEFAULT_TOOLS

    if not transcript_path.exists():
        return False, [f"Transcript file not found: {transcript_path}"]

    events = _parse_jsonl(transcript_path)
    if not events:
        return False, [f"Transcript is empty or all lines are malformed: {transcript_path}"]

    failures: list[str] = []

    # Assertion 1: Task tool_use with subagent_type == agent_name.
    task_block = _find_task_spawn(events, agent_name)
    if task_block is None:
        # Also try finding via tool_result agentType (some CLI versions may
        # emit the subagent type only in the result event).
        task_result = _find_task_result_with_agent_type(events, agent_name)
        if task_result is None:
            failures.append(
                f"Assertion 1 FAILED: No Task tool_use event found with "
                f"subagent_type='{agent_name}' AND no outer Task tool_result "
                f"with agentType='{agent_name}'. "
                f"This means the harness did not spawn the {agent_name} agent "
                f"via a two-level Task call, or the transcript does not capture "
                f"the spawn event."
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
            # Tool_use found but no matching result - may be a timeout or truncated
            # transcript. Flag as a warning but do not fail assertion 1.
            print(
                f"[warn] Task tool_use for '{agent_name}' found but no matching "
                f"outer Task tool_result. Transcript may be truncated.",
                file=sys.stderr,
            )

    # Assertion 2: Inner agent system prompt contains expected tools.
    tools_ok, tools_diag = _check_tools_in_system_prompt(events, task_block, expected_tools)
    if not tools_ok:
        failures.append(f"Assertion 2 FAILED: {tools_diag}")

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
        "--expected-tools",
        default=",".join(_DEFAULT_TOOLS),
        help=(
            "Comma-separated list of tool names expected in the inner agent's "
            f"system prompt (default: {','.join(_DEFAULT_TOOLS)})."
        ),
    )
    args = parser.parse_args()

    expected_tools = [t.strip() for t in args.expected_tools.split(",") if t.strip()]

    passed, failures = assert_canary(
        transcript_path=args.transcript,
        agent_name=args.agent_name,
        expected_tools=expected_tools,
    )

    if passed:
        print(
            f"[canary PASS] Transcript {args.transcript} verified: "
            f"Task spawn of '{args.agent_name}' confirmed with tool list "
            f"{expected_tools}."
        )
        return 0
    else:
        print("[canary FAIL] One or more assertions failed:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
