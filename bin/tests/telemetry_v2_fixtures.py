"""
Purpose: Builders for DS-246 telemetry_v 2 hook spawn rows, shared by
         test_telemetry.py and test_ds_change_delta.py. These rows are the
         read-side contract the U1 hooks (pre-tool-use-spawn-emit.js,
         subagent-stop-spawn-emit.js) must emit: a field renamed here is a
         field the U2 readers stop seeing.

Public API: tokens(...), v2_start(...), v2_complete(...), unpaired_complete(...),
            legacy_complete(...), internal_stop(...), write_jsonl(path, rows),
            make_linked_worktree(tmp) -> (main_root, worktree_root)

Upstream deps: git (make_linked_worktree only).

Downstream consumers: bin/tests/test_telemetry.py, bin/tests/test_ds_change_delta.py,
            bin/tests/test_agentic_cost_subcommands.py, bin/tests/test_agentic_calibrate.py.

Failure modes: make_linked_worktree raises CalledProcessError when git fails.

Performance: trivial; make_linked_worktree runs four git commands.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_linked_worktree(tmp: Path) -> tuple[Path, Path]:
    """A main checkout with one commit plus a linked worktree of it."""
    env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
    main = tmp / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main, check=True, env=env)
    (main / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=main, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=main, check=True, env=env)
    worktree = tmp / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(worktree)], cwd=main, check=True, env=env)
    return main.resolve(), worktree.resolve()


def tokens(input=0, output=0, cache_read=0, cc_5m=0, cc_1h=0) -> dict:
    return {
        "input": input,
        "output": output,
        "cache_creation": cc_5m + cc_1h,
        "cache_read": cache_read,
        "cache_creation_5m": cc_5m,
        "cache_creation_1h": cc_1h,
    }


def v2_start(ts, agent, spawn_id, task_id=None, session="sess-1", tool_use_id=None,
             task_id_source=None, task_id_note=None) -> dict:
    data = {
        "source": "hook",
        "session_uuid": session,
        "tokens_note": "unavailable (harness)",
        "spawn_id": spawn_id,
        "tool_use_id": tool_use_id or f"toolu_{spawn_id}",
        "parent_agent_id": None,
        "telemetry_v": 2,
        "task_id_source": task_id_source or ("invocation" if task_id else "none"),
    }
    if task_id is None:
        data["task_id_note"] = task_id_note or "no_invocation"
    return {"ts": ts, "phase": "hook", "event": "spawn_start", "agent": agent,
            "task_id": task_id, "data": data}


def v2_complete(ts, agent, spawn_id, task_id=None, *, run_index=1, run_start_ts=None,
                wall_seconds=10.0, cumulative=None, run_tokens=None,
                model="claude-opus-5-5", model_source="transcript",
                pair_method="tool_use_id", session="sess-1", **extra) -> dict:
    """spawn_complete for run `run_index` of the spawn whose spawn_start
    carried `spawn_id`. `cumulative`/`run_tokens` None mirrors an
    unresolved transcript (tokens_note instead of tokens); extra keys
    (qa_result, findings_count, iteration, signed_off, ...) go into data."""
    data = {
        "source": "hook",
        "session_uuid": session,
        "tool_use_id": f"toolu_{spawn_id}",
        "agent_id": f"agent-{spawn_id}",
        "agent_source": "sidecar",
        "paired_spawn_id": spawn_id,
        "telemetry_v": 2,
        "task_id_source": "paired_start" if task_id else "none",
        "pair_method": pair_method,
        "run_index": run_index,
        "run_start_ts": run_start_ts,
        "wall_seconds": wall_seconds,
        "suspect": False,
        "transcript_source": "agent_transcript_path",
    }
    if wall_seconds is None:
        data["wall_note"] = "no run boundary found"
    if cumulative is None:
        data["tokens_note"] = "unavailable (transcript not found)"
        data["model_note"] = "unavailable (transcript not found)"
    else:
        data["tokens"] = cumulative
        data["run_tokens"] = run_tokens if run_tokens is not None else cumulative
        data["model"] = model
        data["model_source"] = model_source
    data.update(extra)
    return {"ts": ts, "phase": "hook", "event": "spawn_complete", "agent": agent,
            "task_id": task_id, "data": data}


def unpaired_complete(ts, agent, agent_id, cumulative, task_id=None, tool_use_id=None) -> dict:
    """A U1 stop that matched no spawn_start: run_index, pair_method and
    wall are null, and run_tokens repeats the cumulative tokens."""
    row = v2_complete(ts, agent, None, task_id, run_index=None, pair_method=None, wall_seconds=None,
                      cumulative=cumulative, model="claude-fable-5-1")
    row["data"].update(tool_use_id=tool_use_id, agent_id=agent_id)
    return row


def legacy_complete(ts, agent, spawn_id, task_id=None, wall_seconds=31.0, cumulative=None,
                    model="claude-opus-5") -> dict:
    """A pre-DS-246 hook spawn_complete (no telemetry_v)."""
    data = {
        "source": "hook",
        "session_uuid": "sess-legacy",
        "tool_use_id": None,
        "agent_id": f"agent-{spawn_id}",
        "agent_source": "paired_start",
        "paired_spawn_id": spawn_id,
        "wall_seconds": wall_seconds,
        "suspect": False,
    }
    if cumulative is not None:
        data["tokens"] = cumulative
        data["model"] = model
    return {"ts": ts, "phase": "hook", "event": "spawn_complete", "agent": agent,
            "task_id": task_id, "data": data}


def internal_stop(ts, agent_id="agent-internal", session="sess-1") -> dict:
    return {"ts": ts, "phase": "hook", "event": "subagent_stop_internal", "agent": None,
            "task_id": None,
            "data": {"source": "hook", "session_uuid": session, "agent_id": agent_id,
                     "reason": "empty agent_type, no sidecar"}}
