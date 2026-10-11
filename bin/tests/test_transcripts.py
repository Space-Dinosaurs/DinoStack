#!/usr/bin/env python3
"""
Tests for bin/_transcripts.py: multi-store discovery, project-dir matching,
per-message usage dedupe, cost-state absence and subagent PR parsing.

Run with: python3 -m pytest bin/tests/test_transcripts.py
"""
import importlib.machinery
import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parent.parent / "_transcripts.py"
_loader = importlib.machinery.SourceFileLoader("_transcripts_under_test", str(_MOD_PATH))
tr = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(tr)

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _write(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records), encoding="utf-8")
    return path


def _asst(mid, out, ts, cwd, model="claude-opus-5-5", entrypoint="cli", version="2.1.287", sidechain=False, content=None):
    return {
        "type": "assistant", "isSidechain": sidechain, "timestamp": ts, "cwd": cwd,
        "entrypoint": entrypoint, "version": version,
        "message": {
            "id": mid, "model": model, "role": "assistant", "content": content or [],
            "usage": {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": 100,
                      "cache_creation_input_tokens": 50,
                      "cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 30}},
        },
    }


def _user(ts, cwd, content=None, tool_use_result=None):
    rec = {"type": "user", "timestamp": ts, "cwd": cwd,
           "message": {"role": "user", "content": content if content is not None else "hi"}}
    if tool_use_result is not None:
        rec["toolUseResult"] = tool_use_result
    return rec


def _cost(total, model_usage):
    return {"type": "cost-state", "totalCostUSD": total, "modelUsage": model_usage}


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in tr._lib.CONFIG_DIR_ENV:
        monkeypatch.delenv(var, raising=False)
    return home


def test_project_dir_prefix_replaces_separators_without_double_dash():
    assert tr.project_dir_prefix("/Users/x/r") == "-Users-x-r"
    assert tr.project_dir_prefix("/Users/x/r/.claude/worktrees/a") == "-Users-x-r--claude-worktrees-a"


def test_stores_is_realpath_deduped_union_of_all_sources(isolated_env, tmp_path, monkeypatch):
    a = isolated_env / ".claude" / "projects"
    b = isolated_env / ".claude-moment8" / "projects"
    env_cfg = tmp_path / "envcfg"
    extra_proj = tmp_path / "extra" / "projects"
    for d in (a, b, env_cfg / "projects", extra_proj):
        d.mkdir(parents=True)
    (tmp_path / "alias").symlink_to(b)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(env_cfg))
    got = tr.stores(extra=[tmp_path / "extra", tmp_path / "alias", tmp_path / "missing"])
    want = {os.path.realpath(p) for p in (a, b, env_cfg / "projects", extra_proj)}
    assert sorted(map(str, got)) == sorted(want)
    assert len(got) == 4


def test_stores_absent_is_empty(isolated_env):
    assert tr.stores() == []


def _session_dir(store: Path, repo: Path, suffix: str = "") -> Path:
    return store / (tr.project_dir_prefix(repo) + suffix)


def test_project_dirs_keeps_repo_and_worktree_and_rejects_sibling(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    keep_root = _write(_session_dir(store, repo) / "s1.jsonl",
                       [{"type": "mode"}, _user("2026-10-01T10:00:00Z", str(repo))]).parent
    keep_wt = _write(_session_dir(store, repo, "--claude-worktrees-a") / "s2.jsonl",
                     [_user("2026-10-01T10:00:00Z", str(repo / ".claude" / "worktrees" / "a"))]).parent
    sibling = tmp_path / "r2"
    _write(_session_dir(store, sibling) / "s3.jsonl", [_user("2026-10-01T10:00:00Z", str(sibling))])
    _write(store / "-unrelated" / "s4.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
    got = tr.project_dirs(str(repo), [store])
    assert got == [keep_root, keep_wt]


def test_usage_dedupes_message_id_keeping_max_output_and_drops_synthetic(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    cwd = str(repo)
    _write(_session_dir(store, repo) / "sess.jsonl", [
        _asst("m1", 6, "2026-10-01T10:00:00Z", cwd),
        _asst("m1", 400, "2026-10-01T10:00:01Z", cwd),
        _asst("m1", 7, "2026-10-01T10:00:02Z", cwd),
        _asst("m2", 50, "2026-10-01T10:00:03Z", cwd, entrypoint="sdk-cli", version="2.1.288"),
        _asst("m3", 999, "2026-10-01T10:00:04Z", cwd, model="<synthetic>"),
        _asst("m4", 77, "2026-10-01T10:00:05Z", cwd, sidechain=True),
    ])
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert set(s.conductor) == {("claude-opus-5-5", "cli", "2.1.287"), ("claude-opus-5-5", "sdk-cli", "2.1.288")}
    cli = s.conductor[("claude-opus-5-5", "cli", "2.1.287")]
    assert cli["output"] == 400
    assert cli["messages"] == 1
    assert cli["cache_creation_1h"] == 30
    assert s.conductor[("claude-opus-5-5", "sdk-cli", "2.1.288")]["output"] == 50


def test_cost_uses_last_cost_state_record(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    _write(_session_dir(store, repo) / "sess.jsonl", [
        _user("2026-10-01T10:00:00Z", str(repo)),
        _cost(1.5, {"claude-opus-5-5": {"costUSD": 1.5}}),
        _cost(2.25, {"claude-opus-5-5": {"costUSD": 2.25}}),
    ])
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert s.cost_usd == 2.25
    assert s.model_usage == {"claude-opus-5-5": {"costUSD": 2.25}}


def test_absent_cost_state_is_none_never_zero(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    _write(_session_dir(store, repo) / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert s.cost_usd is None
    assert s.model_usage is None
    assert s.conductor == {}
    assert s.subagents == []


def test_sessions_window_overlap_and_multiple_stores(tmp_path):
    repo = tmp_path / "r"
    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    _write(_session_dir(s1, repo) / "in.jsonl", [_user("2026-09-30T23:00:00Z", str(repo)),
                                                 _user("2026-10-01T01:00:00Z", str(repo))])
    _write(_session_dir(s2, repo) / "in2.jsonl", [_user("2026-10-01T12:00:00Z", str(repo))])
    _write(_session_dir(s2, repo) / "after.jsonl", [_user("2026-10-05T12:00:00Z", str(repo))])
    _write(_session_dir(s2, repo) / "before.jsonl", [_user("2026-09-01T12:00:00Z", str(repo))])
    got = tr.sessions(str(repo), START, END, [s1, s2])
    assert sorted(s.session_id for s in got) == ["in", "in2"]
    assert {s.session_id: s.store for s in got} == {"in": s1, "in2": s2}


def test_subagent_meta_usage_wall_and_pr_created(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    pdir = _session_dir(store, repo)
    _write(pdir / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
    sub_dir = pdir / "sess" / "subagents"
    wt = str(repo / ".claude" / "worktrees" / "agent-a1")
    _write(sub_dir / "agent-a1.jsonl", [
        _user("2026-10-01T10:00:00Z", wt),
        _asst("x1", 5, "2026-10-01T10:00:10Z", wt, entrypoint="sdk-cli", sidechain=True, content=[
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "GH_TOKEN=abc gh pr create --base main --title x"}},
            {"type": "tool_use", "id": "t2", "name": "Bash",
             "input": {"command": "cd r && gh pr create --base main"}},
            {"type": "tool_use", "id": "t3", "name": "Bash",
             "input": {"command": "grep -E 'DCO|gh pr create|--base' AGENTS.md"}},
            {"type": "tool_use", "id": "t4", "name": "Bash", "input": {"command": "gh pr create --base main"}},
        ]),
        _user("2026-10-01T10:00:20Z", wt,
              content=[{"type": "tool_result", "tool_use_id": "t1", "content": "https://github.com/o/r/pull/11"}],
              tool_use_result={"gitOperation": {"pr": {"number": 11, "action": "created"}}}),
        _user("2026-10-01T10:00:30Z", wt,
              content=[{"type": "tool_result", "tool_use_id": "t2", "content": "https://github.com/o/r/pull/12\n"}]),
        _user("2026-10-01T10:00:40Z", wt,
              content=[{"type": "tool_result", "tool_use_id": "t3", "content": "see https://github.com/o/r/pull/99"}]),
        _user("2026-10-01T10:01:40Z", wt,
              content=[{"type": "tool_result", "tool_use_id": "t4", "is_error": True,
                        "content": "https://github.com/o/r/pull/13"}]),
    ])
    (sub_dir / "agent-a1.meta.json").write_text(json.dumps(
        {"agentType": "engineer", "description": "do x", "toolUseId": "toolu_9"}), encoding="utf-8")
    _write(sub_dir / "agent-b2.jsonl", [_user("2026-10-01T10:00:00Z", wt)])
    (s,) = tr.sessions(str(repo), START, END, [store])
    subs = {x.agent_id: x for x in s.subagents}
    a1, b2 = subs["a1"], subs["b2"]
    assert (a1.agent_type, a1.description, a1.tool_use_id) == ("engineer", "do x", "toolu_9")
    assert a1.pr_created == [("o/r", 11), ("o/r", 12)]
    assert a1.wall_seconds == 100.0
    assert a1.usage[("claude-opus-5-5", "sdk-cli", "2.1.287")]["output"] == 5
    assert (b2.agent_type, b2.description, b2.tool_use_id, b2.pr_created) == (None, None, None, [])
    assert b2.usage == {}


def _one_sub(tmp_path, records):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    pdir = _session_dir(store, repo)
    _write(pdir / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
    _write(pdir / "sess" / "subagents" / "agent-a1.jsonl", records)
    (s,) = tr.sessions(str(repo), START, END, [store])
    (sub,) = s.subagents
    return sub


def _tool_call(tid, command, ts="2026-10-01T10:00:10Z"):
    return _asst("u-" + tid, 5, ts, "/w", sidechain=True,
                 content=[{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}])


def _tool_result(tid, text, git_pr=None, is_error=False, ts="2026-10-01T10:00:20Z"):
    block = {"type": "tool_result", "tool_use_id": tid, "content": text}
    if is_error:
        block["is_error"] = True
    tur = {"gitOperation": {"pr": git_pr}} if git_pr else None
    return _user(ts, "/w", content=[block], tool_use_result=tur)


def test_pr_created_matches_command_substitution_env_prefix_in_a_chain(tmp_path):
    cmd = "cd /x/wt && GH_TOKEN=$(gh auth token --user someone) gh pr create --base develop --title 't'"
    sub = _one_sub(tmp_path, [_tool_call("t1", cmd), _tool_result("t1", "https://github.com/o/api/pull/7")])
    assert sub.pr_created == [("o/api", 7)]


def test_pr_created_trusts_git_operation_whatever_the_command(tmp_path):
    sub = _one_sub(tmp_path, [
        _tool_call("t1", "bash /tmp/open_pr.sh"),
        _tool_result("t1", "done", git_pr={"number": 31, "url": "https://github.com/o/web/pull/31",
                                           "action": "created"}),
    ])
    assert sub.pr_created == [("o/web", 31)]


def test_pr_created_keeps_repos_apart_for_colliding_numbers(tmp_path):
    sub = _one_sub(tmp_path, [
        _tool_call("t1", "gh pr create -R o/api"),
        _tool_result("t1", "https://github.com/o/api/pull/5"),
        _tool_call("t2", "gh pr create -R o/web", ts="2026-10-01T10:00:30Z"),
        _tool_result("t2", "https://github.com/o/web/pull/5", ts="2026-10-01T10:00:40Z"),
    ])
    assert sub.pr_created == [("o/api", 5), ("o/web", 5)]


def test_pr_created_ignores_an_errored_gh_pr_create(tmp_path):
    sub = _one_sub(tmp_path, [
        _tool_call("t1", "gh pr create --base main"),
        _tool_result("t1", "a pull request already exists: https://github.com/o/r/pull/4", is_error=True),
    ])
    assert sub.pr_created == []


def test_malformed_shapes_do_not_raise(tmp_path):
    sub = _one_sub(tmp_path, [
        {"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": "/w", "message": "gh pr create"},
        {"type": "assistant", "timestamp": "2026-10-01T10:00:01Z", "message": {
            "content": [{"type": "tool_use", "id": "t1", "input": "gh pr create"}, "gh pr create"]}},
        {"type": "user", "timestamp": "2026-10-01T10:00:02Z", "toolUseResult": "gitOperation",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
        {"type": "assistant", "timestamp": "2026-10-01T10:00:03Z", "message": {"usage": "assistant", "model": 5}},
        ["gh pr create"],
    ])
    assert sub.pr_created == []
    assert sub.usage == {}


def test_file_history_snapshot_nested_timestamp_is_not_a_record_time(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    _write(_session_dir(store, repo) / "sess.jsonl", [
        _user("2026-10-01T10:00:00Z", str(repo)),
        {"type": "file-history-snapshot", "messageId": "m",
         "snapshot": {"messageId": "m", "trackedFileBackups": {}, "timestamp": "2026-10-05T10:00:00Z"}},
        _user("2026-10-01T11:00:00Z", str(repo)),
    ])
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert s.last_ts == datetime(2026, 10, 1, 11, tzinfo=timezone.utc)


def test_cost_start_ts_comes_from_the_last_cost_state_start_time(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    late = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    rec = _cost(3.0, {})
    rec["startTime"] = int(late.timestamp() * 1000)
    _write(_session_dir(store, repo) / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo)), rec])
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert (s.cost_usd, s.cost_start_ts) == (3.0, late)


def test_naive_window_is_read_as_utc_not_local(tmp_path, monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset unavailable")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        repo = tmp_path / "r"
        store = tmp_path / "store"
        _write(_session_dir(store, repo) / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
        got = tr.sessions(str(repo), datetime(2026, 10, 1, 9, 30), datetime(2026, 10, 1, 10, 30), [store])
        assert [s.session_id for s in got] == ["sess"]
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_mtime_prefilter_keeps_a_session_whose_subagent_file_is_recent(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    pdir = _session_dir(store, repo)
    main = _write(pdir / "sess.jsonl", [_user("2026-10-01T10:00:00Z", str(repo))])
    sub = _write(pdir / "sess" / "subagents" / "agent-a1.jsonl", [_user("2026-10-01T10:00:00Z", "/w")])
    old = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
    recent = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).timestamp()
    os.utime(main, (old, old))
    os.utime(sub, (recent, recent))
    (s,) = tr.sessions(str(repo), START, END, [store])
    assert [x.agent_id for x in s.subagents] == ["a1"]


def test_cwd_is_checked_per_session_not_per_project_dir(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    shared = _session_dir(store, repo, "-foo")
    _write(shared / "a.jsonl", [_user("2026-10-01T10:00:00Z", str(repo / "foo"))])
    _write(shared / "b.jsonl", [_user("2026-10-01T10:00:00Z", str(tmp_path / "r-foo"))])
    got = tr.sessions(str(repo), START, END, [store])
    assert [s.session_id for s in got] == ["a"]


def test_missing_cache_creation_split_is_none_and_total_is_kept(tmp_path):
    repo = tmp_path / "r"
    store = tmp_path / "store"
    rec = _asst("m1", 9, "2026-10-01T10:00:00Z", str(repo))
    del rec["message"]["usage"]["cache_creation"]
    _write(_session_dir(store, repo) / "sess.jsonl", [rec, _asst("m2", 9, "2026-10-01T10:00:01Z", str(repo))])
    (s,) = tr.sessions(str(repo), START, END, [store])
    bucket = s.conductor[("claude-opus-5-5", "cli", "2.1.287")]
    assert bucket["cache_creation"] == 100
    assert bucket["cache_creation_5m"] is None
    assert bucket["cache_creation_1h"] is None
