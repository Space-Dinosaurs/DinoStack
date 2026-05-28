#!/usr/bin/env python3
"""
Smoke test for `agentic-cost team` subcommand.

Creates 3 fixture JSONL files (alice x2 sessions, bob x1 session) in a tmp
directory, patches SESSION_LOG_DIR, invokes cmd_team, and asserts correct
aggregation. Run with: python3 bin/tests/test_agentic_cost_team.py
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import types
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-cost as a module (it has no .py extension)
# ---------------------------------------------------------------------------
_COST_PATH = Path(__file__).parent.parent / "agentic-cost"
loader = importlib.machinery.SourceFileLoader("agentic_cost", str(_COST_PATH))
spec = importlib.util.spec_from_loader("agentic_cost", loader)
if spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-cost from {_COST_PATH}")
_mod = importlib.util.module_from_spec(spec)
loader.exec_module(_mod)


def _make_session_line(
    developer_id: str,
    session_uuid: str,
    wall: float,
    tokens: dict,
    spawn_count: int,
    by_agent: dict,
) -> str:
    return json.dumps({
        "ts": "2026-05-28T10:00:00Z",
        "phase": "session_end",
        "event": "session_total",
        "agent": None,
        "task_id": None,
        "developer_id": developer_id,
        "session_uuid": session_uuid,
        "project_slug": "test-project",
        "branch": "main",
        "data": {
            "wall_seconds": wall,
            "tokens": tokens,
            "spawn_count": spawn_count,
            "by_agent": by_agent,
        },
    })


def run_tests():
    with tempfile.TemporaryDirectory() as tmpdir:
        session_log_dir = Path(tmpdir) / "session-log"
        session_log_dir.mkdir()

        # Alice - session 1
        alice1 = _make_session_line(
            developer_id="alice",
            session_uuid="uuid-a1",
            wall=100.0,
            tokens={"input": 1000, "output": 500, "cache_creation": 200, "cache_read": 100},
            spawn_count=2,
            by_agent={
                "engineer": {"spawns": 1, "wall_seconds": 60.0, "tokens_total": 1200},
                "skeptic": {"spawns": 1, "wall_seconds": 40.0, "tokens_total": 600},
            },
        )
        # Alice - session 2
        alice2 = _make_session_line(
            developer_id="alice",
            session_uuid="uuid-a2",
            wall=200.0,
            tokens={"input": 2000, "output": 800, "cache_creation": 300, "cache_read": 150},
            spawn_count=3,
            by_agent={
                "engineer": {"spawns": 2, "wall_seconds": 120.0, "tokens_total": 2000},
                "skeptic": {"spawns": 1, "wall_seconds": 80.0, "tokens_total": 1000},
            },
        )
        # Bob - session 1
        bob1 = _make_session_line(
            developer_id="bob",
            session_uuid="uuid-b1",
            wall=50.0,
            tokens={"input": 500, "output": 200, "cache_creation": 50, "cache_read": 25},
            spawn_count=1,
            by_agent={
                "engineer": {"spawns": 1, "wall_seconds": 50.0, "tokens_total": 775},
            },
        )

        (session_log_dir / "alice.jsonl").write_text(alice1 + "\n" + alice2 + "\n")
        (session_log_dir / "bob.jsonl").write_text(bob1 + "\n")

        # Patch SESSION_LOG_DIR on the module
        original_dir = _mod.SESSION_LOG_DIR
        _mod.SESSION_LOG_DIR = session_log_dir

        try:
            records, skipped = _mod._load_session_logs()

            # --- Assertion 1: total records loaded ---
            assert len(records) == 3, f"Expected 3 records, got {len(records)}"
            assert skipped == 0, f"Expected 0 skipped, got {skipped}"

            # --- Assertion 2: aggregation ---
            agg = _mod._aggregate_team(records)
            assert "alice" in agg, "Expected alice in agg"
            assert "bob" in agg, "Expected bob in agg"

            # --- Assertion 3: alice session count ---
            assert agg["alice"]["sessions"] == 2, (
                f"Alice sessions: expected 2, got {agg['alice']['sessions']}"
            )

            # --- Assertion 4: bob session count ---
            assert agg["bob"]["sessions"] == 1, (
                f"Bob sessions: expected 1, got {agg['bob']['sessions']}"
            )

            # --- Assertion 5: alice total tokens ---
            alice_tok = agg["alice"]["tokens"]
            assert alice_tok["input"] == 3000, (
                f"Alice input tokens: expected 3000, got {alice_tok['input']}"
            )
            assert alice_tok["output"] == 1300, (
                f"Alice output tokens: expected 1300, got {alice_tok['output']}"
            )

            # --- Assertion 6: by_agent merge for alice engineer ---
            alice_eng = agg["alice"]["by_agent"].get("engineer")
            assert alice_eng is not None, "Expected alice.by_agent.engineer"
            assert alice_eng["spawns"] == 3, (
                f"Alice engineer spawns: expected 3, got {alice_eng['spawns']}"
            )
            assert alice_eng["tokens_total"] == 3200, (
                f"Alice engineer tokens_total: expected 3200, got {alice_eng['tokens_total']}"
            )

            # --- Assertion 7: by_agent merge for alice skeptic ---
            alice_sk = agg["alice"]["by_agent"].get("skeptic")
            assert alice_sk is not None, "Expected alice.by_agent.skeptic"
            assert alice_sk["spawns"] == 2, (
                f"Alice skeptic spawns: expected 2, got {alice_sk['spawns']}"
            )

            # --- Assertion 8: bob by_agent ---
            bob_eng = agg["bob"]["by_agent"].get("engineer")
            assert bob_eng is not None, "Expected bob.by_agent.engineer"
            assert bob_eng["spawns"] == 1, (
                f"Bob engineer spawns: expected 1, got {bob_eng['spawns']}"
            )

            # --- Assertion 9: cmd_team produces table output ---
            fake_args = types.SimpleNamespace(json=False)
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                result = _mod.cmd_team(fake_args)
            finally:
                sys.stdout = old_stdout
            table = captured.getvalue()
            assert result == 0, f"cmd_team returned {result}, expected 0"
            assert "alice" in table, "Expected 'alice' in table output"
            assert "bob" in table, "Expected 'bob' in table output"

            print("All assertions passed.")

        finally:
            _mod.SESSION_LOG_DIR = original_dir


if __name__ == "__main__":
    run_tests()
