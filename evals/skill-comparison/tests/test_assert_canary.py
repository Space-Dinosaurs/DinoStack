"""
Purpose: Unit tests for evals/skill-comparison/canary/assert_canary.py.
         Covers: assert_canary() parse logic using synthetic JSONL fixtures,
         _find_task_spawn() (including nested-spawn rejection - M4 fix),
         _find_task_result_with_agent_type(), _check_agent_registered(),
         parse_frontmatter_tools(), and end-to-end tests against the real
         canary/skeptic.jsonl fixture (M2 fix: positive + negative).

Public API: pytest test module; no public symbols.

Upstream deps: canary.assert_canary (via conftest sys.path insertion),
               stdlib json, tempfile, pathlib.

Downstream consumers: pytest runner.

Failure modes: all tests use temp files or the committed fixture; no network
               I/O; no side effects on the real transcript.

Performance: standard; synthetic fixtures are tiny; real transcript is ~15 KB.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# conftest.py inserts evals/skill-comparison/ into sys.path so we can import
# from the canary/ subdirectory directly. Do NOT re-insert here (m4 fix).
from assert_canary import (
    assert_canary,
    parse_frontmatter_tools,
    _find_task_spawn,
    _find_task_result_with_agent_type,
    _check_agent_registered,
)

# Path to the real transcript fixture for M2 tests.
_FIXTURE_DIR = Path(__file__).parent.parent / "canary"
_REAL_TRANSCRIPT = _FIXTURE_DIR / "skeptic.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(tmp: Path, events: list[dict]) -> Path:
    """Write events as JSONL to a temp file and return the path."""
    p = tmp / "transcript.jsonl"
    lines = [json.dumps(e) for e in events]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _make_agent_tool_use(
    agent_name: str,
    tool_id: str = "toolu_abc",
    parent_tool_use_id: str | None = None,
) -> dict:
    """Make an assistant event with an Agent tool_use block."""
    event: dict = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": tool_id,
                    "input": {
                        "subagent_type": agent_name,
                        "prompt": "Test prompt.",
                    },
                }
            ],
        },
    }
    if parent_tool_use_id is not None:
        event["parent_tool_use_id"] = parent_tool_use_id
    return event


def _make_task_tool_use(
    agent_name: str,
    tool_id: str = "toolu_abc",
    parent_tool_use_id: str | None = None,
) -> dict:
    """Make an assistant event with a Task tool_use block (older CLI name)."""
    event: dict = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Task",
                    "id": tool_id,
                    "input": {
                        "subagent_type": agent_name,
                        "prompt": "Test prompt.",
                    },
                }
            ],
        },
    }
    if parent_tool_use_id is not None:
        event["parent_tool_use_id"] = parent_tool_use_id
    return event


def _make_task_result(agent_name: str, tool_use_id: str = "toolu_abc") -> dict:
    """Make the outer Task tool_result user event."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": [{"type": "text", "text": "Agent response here."}],
                }
            ],
        },
        "parent_tool_use_id": None,
        "tool_use_result": {"agentType": agent_name},
    }


def _make_inner_task_result(tool_use_id: str = "toolu_abc") -> dict:
    """Make a nested tool_result (from the inner agent's Read call etc.)."""
    return {
        "type": "user",
        "parent_tool_use_id": tool_use_id,  # nested, not the outer Task result
        "message": {"role": "user", "content": []},
    }


def _make_system_init(agents: list[str], tools: list[str] | None = None) -> dict:
    """Make a system/init event listing registered agents and tools."""
    event: dict = {
        "type": "system",
        "subtype": "init",
        "agents": agents,
        "session_id": "test-session",
        "model": "claude-test",
    }
    if tools is not None:
        event["tools"] = tools
    return event


def _make_result_event() -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "num_turns": 1,
        "result": "done",
        "total_cost_usd": 0.001,
    }


# ---------------------------------------------------------------------------
# Tests: parse_frontmatter_tools
# ---------------------------------------------------------------------------

class TestParseFrontmatterTools:
    def test_parses_tools_from_real_skeptic_md(self):
        """The real skeptic.md frontmatter must list Read, Grep, Glob, Bash."""
        skeptic_md = Path(__file__).parent.parent.parent.parent / ".claude" / "agents" / "skeptic.md"
        if not skeptic_md.exists():
            pytest.skip("skeptic.md not found in repo (running outside repo)")
        tools = parse_frontmatter_tools(skeptic_md)
        assert "Read" in tools
        assert "Grep" in tools
        assert "Glob" in tools
        assert "Bash" in tools
        # Must NOT contain 'Task' (that was the brief typo; actual is Bash).
        assert "Task" not in tools

    def test_parses_tools_from_synthetic_frontmatter(self, tmp_path: Path):
        """Parses comma-separated tools from a synthetic .md file."""
        md = tmp_path / "agent.md"
        md.write_text(
            "---\nname: testagent\ntools: Read, Grep, Write\n---\n\nBody.",
            encoding="utf-8",
        )
        tools = parse_frontmatter_tools(md)
        assert tools == ["Read", "Grep", "Write"]

    def test_raises_on_missing_file(self, tmp_path: Path):
        """FileNotFoundError when file does not exist."""
        with pytest.raises(FileNotFoundError):
            parse_frontmatter_tools(tmp_path / "nonexistent.md")

    def test_raises_on_missing_tools_key(self, tmp_path: Path):
        """ValueError when frontmatter has no tools: key."""
        md = tmp_path / "agent.md"
        md.write_text("---\nname: testagent\n---\n\nBody.", encoding="utf-8")
        with pytest.raises(ValueError, match="No 'tools:' key"):
            parse_frontmatter_tools(md)

    def test_raises_on_missing_frontmatter(self, tmp_path: Path):
        """ValueError when file has no --- frontmatter block."""
        md = tmp_path / "agent.md"
        md.write_text("No frontmatter here.", encoding="utf-8")
        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_frontmatter_tools(md)

    def test_parses_bracket_list_form(self, tmp_path: Path):
        """Inline YAML bracket form tools: [Read, Grep, Glob, Bash] is handled."""
        md = tmp_path / "agent.md"
        md.write_text(
            "---\nname: testagent\ntools: [Read, Grep, Glob, Bash]\n---\n\nBody.",
            encoding="utf-8",
        )
        tools = parse_frontmatter_tools(md)
        assert tools == ["Read", "Grep", "Glob", "Bash"]


# ---------------------------------------------------------------------------
# Tests: _find_task_spawn (including M4 nested-spawn rejection)
# ---------------------------------------------------------------------------

class TestFindTaskSpawn:
    def test_finds_agent_tool_use(self):
        events = [_make_agent_tool_use("skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None
        assert block["input"]["subagent_type"] == "skeptic"

    def test_finds_task_tool_use(self):
        """Older CLI used 'Task' as tool name; must still be recognized."""
        events = [_make_task_tool_use("skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None

    def test_case_insensitive_match(self):
        events = [_make_agent_tool_use("Skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None

    def test_wrong_agent_not_found(self):
        events = [_make_agent_tool_use("engineer")]
        block = _find_task_spawn(events, "skeptic")
        assert block is None

    def test_no_tool_use_events(self):
        events = [{"type": "assistant", "message": {"content": []}}]
        block = _find_task_spawn(events, "skeptic")
        assert block is None

    def test_non_spawn_tool_use_ignored(self):
        events = [{
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "name": "Read",
                    "id": "toolu_xyz",
                    "input": {"file_path": "/foo"},
                }]
            },
        }]
        block = _find_task_spawn(events, "skeptic")
        assert block is None

    def test_nested_spawn_rejected(self):
        """[M4 regression] Nested spawns (parent_tool_use_id set) must be rejected.

        The Brief requires 'direct two-level Task spawn'. A spawn event with
        parent_tool_use_id set originates from an inner agent, not the outer
        conductor. _find_task_spawn must return None for such events.
        """
        # Simulate an inner agent spawning another agent (nested).
        nested_event = _make_agent_tool_use(
            "skeptic",
            tool_id="toolu_inner",
            parent_tool_use_id="toolu_outer",  # nested - has parent
        )
        block = _find_task_spawn([nested_event], "skeptic")
        assert block is None, (
            "Nested spawn (parent_tool_use_id set) must NOT match; "
            "only direct outer-conductor spawns are valid."
        )

    def test_nested_spawn_rejected_but_outer_accepted(self):
        """[M4 regression] A nested spawn does not shadow a valid outer spawn."""
        nested = _make_agent_tool_use(
            "skeptic",
            tool_id="toolu_nested",
            parent_tool_use_id="toolu_outer",
        )
        outer = _make_agent_tool_use("skeptic", tool_id="toolu_direct")
        # Nested appears first; outer should still be found.
        block = _find_task_spawn([nested, outer], "skeptic")
        assert block is not None
        assert block.get("id") == "toolu_direct"


# ---------------------------------------------------------------------------
# Tests: _find_task_result_with_agent_type
# ---------------------------------------------------------------------------

class TestFindTaskResult:
    def test_finds_outer_task_result(self):
        events = [_make_task_result("skeptic")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is not None

    def test_nested_result_excluded(self):
        """Nested tool_results (parent_tool_use_id set) must NOT match."""
        events = [_make_inner_task_result()]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is None

    def test_wrong_agent_type_not_found(self):
        events = [_make_task_result("engineer")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is None

    def test_case_insensitive(self):
        events = [_make_task_result("Skeptic")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: _check_agent_registered (Critical fix - load-bearing check)
# ---------------------------------------------------------------------------

class TestCheckAgentRegistered:
    def test_passes_when_agent_in_init_agents(self):
        """[Critical regression] Agent in init.agents = registration confirmed."""
        events = [_make_system_init(agents=["skeptic", "engineer"])]
        ok, diag = _check_agent_registered(events, "skeptic", ["Read", "Grep"])
        assert ok, f"Expected pass, got: {diag}"
        assert "registered" in diag.lower()

    def test_fails_when_agent_not_in_init_agents(self):
        """[Critical regression] Agent absent from init.agents = fail (not vacuously pass)."""
        events = [
            _make_system_init(
                agents=["engineer"],  # skeptic NOT registered
                tools=["Read", "Grep", "Glob", "Bash"],  # conductor tools present
            )
        ]
        ok, diag = _check_agent_registered(events, "skeptic", ["Read", "Grep", "Glob", "Bash"])
        assert not ok, (
            "Must fail when agent is not in init.agents, even when tool names "
            "appear in the outer session's tools list. Blob-search must NOT be "
            "a passing condition."
        )
        assert "NOT in" in diag or "not in" in diag.lower()

    def test_fails_when_no_init_event(self):
        """No system/init event in transcript = fail."""
        events = [_make_result_event()]
        ok, diag = _check_agent_registered(events, "skeptic", ["Read"])
        assert not ok
        assert "No system/init" in diag

    def test_case_insensitive_agent_match(self):
        events = [_make_system_init(agents=["Skeptic"])]
        ok, _ = _check_agent_registered(events, "skeptic", ["Read"])
        assert ok

    def test_tool_mismatch_when_agents_surfaces_tools(self):
        """If init.agents surfaces per-agent tools and they don't match, fail."""
        events = [{
            "type": "system",
            "subtype": "init",
            "agents": [{"name": "skeptic", "tools": ["Read"]}],  # missing Grep, Glob, Bash
        }]
        ok, diag = _check_agent_registered(
            events, "skeptic", ["Read", "Grep", "Glob", "Bash"]
        )
        assert not ok
        assert "missing" in diag.lower()


# ---------------------------------------------------------------------------
# Tests: assert_canary (end-to-end with synthetic transcripts)
# ---------------------------------------------------------------------------

class TestAssertCanary:
    def test_passes_on_complete_transcript(self):
        """Full synthetic transcript with Agent spawn + agent in init.agents."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["skeptic", "engineer"],
                    tools=["Read", "Grep", "Glob", "Bash", "Task"],
                ),
                _make_agent_tool_use("skeptic"),
                _make_task_result("skeptic"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass, got failures: {failures}"

    def test_fails_when_no_spawn_event(self):
        """No Task/Agent tool_use in transcript."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [_make_result_event()]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read"])
            assert not passed
            assert any("Assertion 1 FAILED" in f for f in failures)

    def test_fails_when_wrong_agent_spawned(self):
        """Agent tool_use present but for a different agent."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_agent_tool_use("engineer"),  # wrong agent
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read"])
            assert not passed

    def test_fails_on_missing_transcript(self):
        """Non-existent transcript file returns failure."""
        p = Path("/tmp/no_such_file_canary_test.jsonl")
        passed, failures = assert_canary(p, agent_name="skeptic",
                                          expected_tools=["Read"])
        assert not passed
        assert any("not found" in f for f in failures)

    def test_fails_on_empty_transcript(self):
        """Empty JSONL produces failure."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            p = tmp / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read"])
            assert not passed

    def test_older_task_tool_name_accepted(self):
        """'Task' tool name (older CLI) also triggers assertion 1 pass."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["skeptic"],
                    tools=["Read", "Grep", "Glob", "Bash"],
                ),
                _make_task_tool_use("skeptic"),
                _make_task_result("skeptic"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass with Task tool name, got: {failures}"

    def test_malformed_json_lines_skipped(self):
        """Malformed lines in JSONL are skipped without crash."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            p = tmp / "malformed.jsonl"
            lines = [
                json.dumps(_make_system_init(["skeptic"], ["Read", "Grep", "Glob", "Bash"])),
                "{not valid json",
                json.dumps(_make_agent_tool_use("skeptic")),
                json.dumps(_make_task_result("skeptic")),
                json.dumps(_make_result_event()),
            ]
            p.write_text("\n".join(lines), encoding="utf-8")
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass despite malformed line, got: {failures}"

    def test_custom_agent_and_tools(self):
        """assert_canary works for agent_name != 'skeptic'."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["engineer"],
                    tools=["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
                ),
                _make_agent_tool_use("engineer"),
                _make_task_result("engineer"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="engineer",
                                              expected_tools=["Read", "Write", "Edit"])
            assert passed, f"Expected pass for engineer, got: {failures}"

    def test_fails_when_agent_not_registered_even_if_tools_in_blob(self):
        """[Critical regression] Tool names in outer tools list must NOT cause pass.

        This is the core regression test for the Critical Skeptic finding:
        the old blob-search would pass because the outer conductor's init event
        always lists Read, Grep, Glob, Bash as conductor tools. The new
        implementation must fail when the agent is not in init.agents,
        regardless of whether those tool names appear in the transcript.
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                # init event has conductor tools but skeptic NOT in agents list.
                _make_system_init(
                    agents=["engineer"],  # skeptic absent
                    tools=["Read", "Grep", "Glob", "Bash"],  # conductor tools present
                ),
                _make_agent_tool_use("skeptic"),  # spawn still present
                _make_task_result("skeptic"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(
                p,
                agent_name="skeptic",
                expected_tools=["Read", "Grep", "Glob", "Bash"],
            )
            assert not passed, (
                "Must FAIL when skeptic is not in init.agents, even though "
                "Read/Grep/Glob/Bash appear in the outer conductor's tools list. "
                "The blob-search must NOT be a passing condition."
            )
            assert any("Assertion 2 FAILED" in f for f in failures)

    def test_nested_spawn_not_counted_for_assertion1(self):
        """[M4 regression] A nested spawn alone does not satisfy Assertion 1."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(agents=["skeptic"]),
                # Only a nested spawn - not a direct outer-conductor spawn.
                _make_agent_tool_use(
                    "skeptic",
                    tool_id="toolu_nested",
                    parent_tool_use_id="toolu_some_parent",
                ),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(
                p,
                agent_name="skeptic",
                expected_tools=["Read"],
            )
            assert not passed, (
                "A nested spawn (parent_tool_use_id set) must NOT satisfy "
                "Assertion 1. Only direct outer-conductor spawns count."
            )
            assert any("Assertion 1 FAILED" in f for f in failures)


# ---------------------------------------------------------------------------
# Tests: Real fixture - positive and negative (M2 fix)
# ---------------------------------------------------------------------------

class TestRealTranscriptFixture:
    """Tests against the committed canary/skeptic.jsonl transcript."""

    @pytest.mark.skipif(
        not _REAL_TRANSCRIPT.exists(),
        reason="Real transcript fixture not found (expected at canary/skeptic.jsonl)",
    )
    def test_real_transcript_passes(self):
        """[M2 positive] The committed skeptic.jsonl transcript must pass the canary.

        This test uses the real transcript captured from a genuine Claude CLI
        run. It proves the asserter passes on a well-formed production-like
        transcript. If this test fails, the asserter may be too strict.
        """
        passed, failures = assert_canary(
            _REAL_TRANSCRIPT,
            agent_name="skeptic",
            expected_tools=["Read", "Grep", "Glob", "Bash"],
        )
        assert passed, (
            f"Real transcript canary/skeptic.jsonl should PASS but got failures:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )

    @pytest.mark.skipif(
        not _REAL_TRANSCRIPT.exists(),
        reason="Real transcript fixture not found (expected at canary/skeptic.jsonl)",
    )
    def test_mutated_transcript_fails_on_missing_registration(self):
        """[M2 negative] Mutated transcript missing agent registration must fail.

        This is the load-bearing regression test for the Critical finding.
        We parse the real transcript, strip all init.agents entries for
        'skeptic', write the mutated version to a temp file, and assert that
        the canary fails with an Assertion 2 failure (not a vacuous pass).
        """
        import copy

        events = []
        with open(_REAL_TRANSCRIPT, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # Deep-copy and mutate: remove skeptic from every init.agents list.
        mutated = []
        for event in events:
            e = copy.deepcopy(event)
            if e.get("type") == "system" and e.get("subtype") == "init":
                agents = e.get("agents", [])
                if isinstance(agents, list):
                    # Filter out "skeptic" (str or dict form).
                    filtered = []
                    for a in agents:
                        if isinstance(a, str) and a.lower() == "skeptic":
                            continue
                        if isinstance(a, dict) and a.get("name", "").lower() == "skeptic":
                            continue
                        filtered.append(a)
                    e["agents"] = filtered
            mutated.append(e)

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            p = tmp / "mutated.jsonl"
            p.write_text(
                "\n".join(json.dumps(e) for e in mutated),
                encoding="utf-8",
            )
            passed, failures = assert_canary(
                p,
                agent_name="skeptic",
                expected_tools=["Read", "Grep", "Glob", "Bash"],
            )
            assert not passed, (
                "Mutated transcript (skeptic removed from init.agents) must FAIL. "
                "If it passes, the registration check is not load-bearing."
            )
            assert any("Assertion 2 FAILED" in f for f in failures), (
                f"Expected Assertion 2 failure, got: {failures}"
            )
