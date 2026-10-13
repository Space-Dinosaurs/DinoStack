#!/usr/bin/env python3
"""
Tests for bin/ds-evaluate: the /ds-evaluate signal collector CLI.

Covers: the telemetry-repo default (cwd's git toplevel, else --repo outside a
git work tree) and its repeatable flag, the window (default 30d, explicit
--since/--until, usage errors), signals coming from bin/_eval.py's
evaluate(), the methodology signals of the --repo checkout (ABSENT, never a
crash, outside a DinoStack checkout), a consumer repo exiting 0, the report
ending with "Refinement proposals" in evaluate()'s order (rank and route on
every line, D2 label samples) and then "Telemetry gaps" (no route, no rank),
no read of the session-log (its legacy cumulative rows were summed), and the
/ds-evaluate command file's Step 2 block reaching bin/ds-evaluate under both
bash and zsh.

Run with: python3 -m pytest bin/tests/test_ds_evaluate.py -q
"""
from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN = REPO_ROOT / "bin" / "ds-evaluate"
PY = sys.executable
CONFIG_DIR_ENV = ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR")
SINCE, UNTIL = "2026-10-01", "2026-10-08"

_loader = importlib.machinery.SourceFileLoader("ds_evaluate_under_test", str(BIN))
dse = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(dse)

_VISION_MD = """# DinoStack Product Vision (North Star)

## North Star (what every change should serve)

1. **Guard operator attention.** Surface decisions and work-stoppages, not status.
2. **Produce verifiable outcomes autonomously.** Agents should drive work to a checkable result.
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dinostack(tmp_path: Path) -> Path:
    repo = tmp_path / "dinostack"
    (repo / "content" / "sections").mkdir(parents=True)
    return repo


def _git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    return path


def _env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    for var in CONFIG_DIR_ENV:
        env.pop(var, None)
    return env


def _run(tmp_path: Path, *args: str, cwd: Path):
    return subprocess.run([PY, str(BIN), *args], capture_output=True, text=True, env=_env(tmp_path),
                          cwd=str(cwd), timeout=120)


def _json(tmp_path: Path, *args: str, cwd: Path) -> dict:
    proc = _run(tmp_path, *args, "--json", cwd=cwd)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def _real(path: Path) -> str:
    return os.path.realpath(path)


def _section(out: str, title: str, end: str | None = None) -> list[str]:
    body = out.split(f"\n{title}\n", 1)[1]
    if end is not None:
        body = body.split(f"\n{end}\n", 1)[0]
    return [line for line in body.splitlines() if line.strip()]


# Telemetry repo and window ---------------------------------------------------


def test_default_telemetry_repo_is_the_cwd_git_toplevel(tmp_path):
    project = _git_init(tmp_path / "project")
    (project / "sub").mkdir()
    data = _json(tmp_path, "--repo", str(_dinostack(tmp_path)), "--since", SINCE, "--until", UNTIL,
                 cwd=project / "sub")
    assert data["meta"]["repos"] == [_real(project)]


def test_default_telemetry_repo_falls_back_to_repo_outside_a_git_work_tree(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = _dinostack(tmp_path)
    data = _json(tmp_path, "--repo", str(repo), "--since", SINCE, "--until", UNTIL, cwd=outside)
    assert data["meta"]["repos"] == [_real(repo)]


def test_telemetry_repo_is_repeatable(tmp_path):
    a, b = _git_init(tmp_path / "a"), _git_init(tmp_path / "b")
    data = _json(tmp_path, "--repo", str(_dinostack(tmp_path)), "--telemetry-repo", str(a),
                 "--telemetry-repo", str(b), "--since", SINCE, "--until", UNTIL, cwd=tmp_path)
    assert data["meta"]["repos"] == [_real(a), _real(b)]


def test_window_defaults_to_30_days_and_passes_explicit_bounds(tmp_path):
    repo = _dinostack(tmp_path)
    meta = _json(tmp_path, "--repo", str(repo), cwd=repo)["meta"]
    start, end = datetime.fromisoformat(meta["start"]), datetime.fromisoformat(meta["end"])
    assert end - start == timedelta(days=30)
    assert abs(datetime.now(timezone.utc) - end) < timedelta(minutes=5)

    meta = _json(tmp_path, "--repo", str(repo), "--since", SINCE, "--until", UNTIL, cwd=repo)["meta"]
    assert (meta["start"], meta["end"]) == ("2026-10-01T00:00:00+00:00", "2026-10-08T00:00:00+00:00")
    meta = _json(tmp_path, "--repo", str(repo), "--since", "14d", "--until", UNTIL, cwd=repo)["meta"]
    assert meta["start"] == "2026-09-24T00:00:00+00:00"


@pytest.mark.parametrize("args", [["--since", "yesterday"], ["--since", UNTIL, "--until", SINCE],
                                  ["--telemetry-repo", ""], ["--telemetry-repo", "missing"],
                                  ["--repo", "missing"]])
def test_usage_errors_exit_2(tmp_path, args):
    proc = _run(tmp_path, *args, cwd=tmp_path)
    assert proc.returncode == 2, proc.stderr


# Methodology signals -----------------------------------------------------------


def test_methodology_signals_come_from_the_dinostack_checkout(tmp_path):
    repo = _dinostack(tmp_path)
    _write(repo / "AGENTS.md", "hello")
    _write(repo / ".agentic" / "memory" / "MEMORY.md", "abc")
    _write(repo / "docs" / "overview" / "vision.md", _VISION_MD)
    (repo / "scripts").mkdir()
    _write(repo / "scripts" / "unrelated.sh", "#!/bin/bash\n")
    _write(tmp_path / "home" / ".claude" / "CLAUDE.md", "0123456789")

    m = _json(tmp_path, "--repo", str(repo), "--since", SINCE, "--until", UNTIL, cwd=tmp_path)["methodology"]
    assert m["repo"] == _real(repo)
    assert m["vision_pillars"] == ["1. Guard operator attention", "2. Produce verifiable outcomes autonomously"]
    assert m["resident_floor"] == {
        "files": {"~/.claude/CLAUDE.md": 10, "AGENTS.md": 5, ".agentic/memory/MEMORY.md": 3}, "sum": 18}
    assert "budget_gates" not in m


def test_methodology_is_absent_outside_a_dinostack_checkout(tmp_path):
    repo = tmp_path / "plain"
    _write(repo / "docs" / "overview" / "vision.md", _VISION_MD)
    proc = _run(tmp_path, "--repo", str(repo), "--since", SINCE, "--until", UNTIL, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "[methodology]  " + _real(repo) + "\n  ABSENT: not a DinoStack checkout" in proc.stdout


# Consumer repo, end to end ---------------------------------------------------


def _denies(n: int, start: datetime, spacing_minutes: int = 5, hook: str = "enforce-x") -> str:
    rows = [{"ts": (start + timedelta(minutes=spacing_minutes * i)).isoformat().replace("+00:00", "Z"),
             "hook": hook, "decision": "deny", "reason": f"blocked {i}", "session_id": "s1",
             "tool_use_id": f"tu-{i}"} for i in range(n)]
    return "".join(json.dumps(r) + "\n" for r in rows)


def test_consumer_repo_exits_0_and_ends_with_proposals_then_gaps(tmp_path):
    consumer = _git_init(tmp_path / "consumer")
    _write(consumer / ".agentic" / ".enforcement-fires.jsonl",
           _denies(12, datetime(2026, 10, 3, 9, tzinfo=timezone.utc)))
    assert not (consumer / "hooks").exists() and not (consumer / "content").exists()

    proc = _run(tmp_path, "--since", SINCE, "--until", UNTIL, cwd=consumer)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    gaps = _section(out, "Telemetry gaps")
    assert out.splitlines()[0].startswith(f"ds-evaluate: 1 refinement proposals, {len(gaps)} telemetry gap lines ")
    assert out.index("\nRefinement proposals\n") < out.index("\nTelemetry gaps\n")
    proposals = _section(out, "Refinement proposals", "Telemetry gaps")
    assert proposals[0].startswith("  1. D2   enforce-x  [hooks[enforce-x].repeat_share = ")
    assert proposals[0].endswith("n=12]  unpriced  -> prune-harness")
    assert proposals[1] == f"       label samples for repo {_real(consumer)} (fire_key  ts  reason):"
    assert [line.split()[0] for line in proposals[2:]] == ["tu-11", "tu-10", "tu-9", "tu-8", "tu-7"]
    assert proposals[2].endswith('"blocked 11"')
    assert "  items: n/a (no keyed work items)" in out

    data = _json(tmp_path, "--since", SINCE, "--until", UNTIL, cwd=consumer)
    d2 = data["decisions"][0]
    assert (d2["rule"], d2["subject"], d2["repo"]) == ("D2", "enforce-x", _real(consumer))
    assert [s["fire_key"] for s in d2["label_sample"]] == ["tu-11", "tu-10", "tu-9", "tu-8", "tu-7"]
    assert list(data)[-3:] == ["methodology", "decisions", "gaps"]
    assert gaps and len(gaps) <= len(data["gaps"])


def test_several_proposals_print_in_eval_order_end_to_end(tmp_path):
    """Three decisions whose _eval order (count descending) differs from both
    rule order and the order the rules are evaluated in."""
    consumer = _git_init(tmp_path / "consumer")
    day = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
    cap = [{"ts": (day + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "hook": "enforce-skeptic-round-cap", "decision": "deny"} for i in range(20)]
    old = {"ts": "2026-09-20T00:00:00Z", "hook": "enforce-a", "decision": "allow"}
    _write(consumer / ".agentic" / ".enforcement-fires.jsonl",
           "".join(json.dumps(r) + "\n" for r in [old, *cap])
           + _denies(12, day, hook="enforce-a") + _denies(30, day, spacing_minutes=1, hook="enforce-b"))

    data = _json(tmp_path, "--since", SINCE, "--until", UNTIL, cwd=consumer)
    order = [(d["rule"], d["subject"]) for d in data["decisions"]]
    assert order == [("D2", "enforce-b"), ("D1b", "skeptic round-cap hits rising"), ("D2", "enforce-a")]
    assert order != sorted(order, key=lambda o: o[0])

    out = _run(tmp_path, "--since", SINCE, "--until", UNTIL, cwd=consumer).stdout
    numbered = [line for line in _section(out, "Refinement proposals", "Telemetry gaps")
                if re.match(r"^  \d+\. ", line)]
    assert len(numbered) == 3
    for i, (line, (rule, subject)) in enumerate(zip(numbered, order), 1):
        assert line.startswith(f"  {i}. {rule:<4} {subject}  "), line


# Report order and shape ----------------------------------------------------------


def _report(tmp_path: Path, monkeypatch, decisions: list[dict], gaps: list[dict]) -> str:
    monkeypatch.setattr(dse._EVAL, "_feedback_items", lambda repo: [])
    repo = tmp_path / "r"
    repo.mkdir()
    end = datetime(2026, 10, 8, tzinfo=timezone.utc)
    r = dse._EVAL.evaluate([repo], end - timedelta(days=7), end, use_gh=False, stores=[], rates={})
    r["methodology"] = {"repo": str(repo), "absent": "fixture"}
    r["decisions"], r["gaps"] = decisions, gaps
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dse.print_report(r)
    return buf.getvalue()


def _decision(rule, subject, rank_usd, count):
    return {"rule": rule, "subject": subject, "evidence": {"figure": f"fig.{subject}", "value": 0.75, "count": count},
            "rank_usd": rank_usd, "route": dse._EVAL.ROUTES[rule], "repo": "/r"}


def test_proposals_keep_eval_order_with_rank_and_route_on_every_line(tmp_path, monkeypatch):
    decisions = dse._EVAL.order_decisions([
        _decision("D1b", "cap", None, 5), _decision("D2", "hook", None, 20),
        _decision("D1a", "late", 10.0, 7), _decision("D3", "AUT-1", 50.0, 1)])
    assert [d["subject"] for d in decisions] == ["AUT-1", "late", "hook", "cap"]
    out = _report(tmp_path, monkeypatch, decisions, [])
    lines = _section(out, "Refinement proposals", "Telemetry gaps")
    assert len(lines) == 4
    expected_rank = ["$50.00", "$10.00", "unpriced", "unpriced"]
    for i, (line, d) in enumerate(zip(lines, decisions)):
        ev = d["evidence"]
        assert line.startswith(f"  {i + 1}. {d['rule']:<4} {d['subject']}  ")
        assert f"[{ev['figure']} = 0.75, n={ev['count']}]  {expected_rank[i]}  -> {d['route']}" in line
        assert line.endswith(f"-> {dse._EVAL.ROUTES[d['rule']]}")


def test_gaps_come_last_with_no_route_and_no_rank(tmp_path, monkeypatch):
    gaps = [{"input": "skeptic_rounds.late_withheld_share", "status": "ABSENT", "coverage": None,
             "blocks": ["D1a"], "repo": "/r"},
            {"input": "hooks[enforce-x].repeat_share", "status": "ABSENT", "coverage": 0.0,
             "blocks": ["D2"], "repo": "/r"}]
    out = _report(tmp_path, monkeypatch, [_decision("D1a", "late", 10.0, 7)], gaps)
    assert out.splitlines()[0].startswith("ds-evaluate: 1 refinement proposals, 2 telemetry gap lines ")
    lines = _section(out, "Telemetry gaps")
    assert lines == ["  skeptic_rounds.late_withheld_share: ABSENT  blocks D1a",
                     "  hooks[*].repeat_share: ABSENT (1 hooks: enforce-x)  blocks D2"]
    routes = set(dse._EVAL.ROUTES.values())
    for line in lines:
        assert "->" not in line and "$" not in line and "unpriced" not in line
        assert not any(route in line for route in routes)
    assert out.rstrip("\n").endswith(lines[-1])


def test_empty_proposals_and_gaps_print_none(tmp_path, monkeypatch):
    out = _report(tmp_path, monkeypatch, [], [])
    assert _section(out, "Refinement proposals", "Telemetry gaps") == ["  none"]
    assert _section(out, "Telemetry gaps") == ["  none"]


# Session log -------------------------------------------------------------------


def test_cumulative_legacy_session_rows_are_never_summed(tmp_path):
    repo = _dinostack(tmp_path)
    rows = [{"ts": f"2026-10-0{i}T10:00:00Z", "event": "session_total", "session_uuid": "u1",
             "data": {"wall_seconds": 1234567 * i, "spawn_count": i}} for i in (2, 3, 4)]
    _write(repo / ".agentic" / "session-log" / "dev.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    proc = _run(tmp_path, "--repo", str(repo), "--since", SINCE, "--until", UNTIL, "--json", cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "session_log" not in data and "session_log" not in data["methodology"]
    assert str(1234567 * 9) not in proc.stdout
    assert data["meta"]["sessions"] == 0


# /ds-evaluate Step 2 block ------------------------------------------------------

COMMAND_MD = REPO_ROOT / "content" / "commands" / "ds-evaluate.md"
STEP2_SHELLS = ("bash", "zsh")


def _step2_block() -> str:
    step2 = COMMAND_MD.read_text(encoding="utf-8").split("\n## Step 2 ", 1)[1].split("\n## Step 3 ", 1)[0]
    block = step2.split("```bash\n", 1)[1].split("\n```", 1)[0]
    assert block.count("<window>") == 1
    return block.replace("<window>", "14d")


def _shell(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        if os.environ.get("CI"):
            pytest.fail(f"{name} is not installed; under CI the Step 2 block must run in it")
        pytest.skip(f"{name} is not installed")
    return found


def _step2_fixture(tmp_path: Path, repo_dir_is_git: bool) -> tuple[Path, Path]:
    """A fake HOME whose config names a stand-in DinoStack checkout that carries
    the shipped repo-dir.sh and a bin/ds-evaluate stub echoing its arguments."""
    checkout = tmp_path / "checkout"
    _write(checkout / "scripts" / "lib" / "repo-dir.sh",
           (REPO_ROOT / "scripts" / "lib" / "repo-dir.sh").read_text(encoding="utf-8"))
    stub = checkout / "bin" / "ds-evaluate"
    _write(stub, '#!/bin/sh\necho "REACHED $*"\n')
    stub.chmod(0o755)
    if repo_dir_is_git:
        _git_init(checkout)
    _write(tmp_path / "home" / ".agentic" / "agentic-engineering-config.json",
           json.dumps({"repo_dir": str(checkout)}))
    return checkout, _git_init(tmp_path / "project")


@pytest.mark.parametrize("shell", STEP2_SHELLS)
def test_step2_block_reaches_ds_evaluate(tmp_path, shell):
    checkout, project = _step2_fixture(tmp_path, repo_dir_is_git=True)
    proc = subprocess.run([_shell(shell), "-c", _step2_block()], capture_output=True, text=True,
                          env=_env(tmp_path), cwd=str(project), timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"REACHED --repo {checkout} --telemetry-repo {_real(project)} --since 14d"


@pytest.mark.parametrize("shell", STEP2_SHELLS)
def test_step2_block_fails_loudly_when_repo_dir_cannot_be_resolved(tmp_path, shell):
    _checkout, project = _step2_fixture(tmp_path, repo_dir_is_git=False)
    proc = subprocess.run([_shell(shell), "-c", _step2_block()], capture_output=True, text=True,
                          env=_env(tmp_path), cwd=str(project), timeout=120)
    assert proc.returncode != 0
    assert "REACHED" not in proc.stdout
    assert "ds-evaluate: cannot resolve the DinoStack checkout" in proc.stderr
