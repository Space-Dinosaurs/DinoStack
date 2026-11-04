#!/usr/bin/env python3
"""
Spec tests for /ds-implement-ticket Phase 5 §Low route.

- The conductor spawns one engineer for a Low ticket and implements nothing
  itself; no conductor-implements exception remains in the command.
- Every Low fix spawn carries the bound check, and the first spawn renames a
  stale local branch instead of failing to create it.
- A broken bound in a Phase 10a fix stops instead of escalating, since the PR
  already exists.
- The bound check's line count must measure only this change. The test runs
  its own commands, taken from the command text, against a scratch repo
  whose base gained an unrelated commit after the branch was cut and fetched.

Run with: python3 -m pytest bin/tests/test_low_route_spec.py -q
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from harness_scope import non_claude

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMMAND_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
# The generated Codex skill rewrites project paths, so its bound check is run too.
CODEX_SKILL_PATH = REPO_ROOT / ".codex" / "skills" / "dinostack-codex-implement-ticket" / "SKILL.md"

HEADING = "### Low route (one engineer)"


def _low_route_section(path: Path = COMMAND_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(HEADING)
    return text[start:text.index("\n### ", start + 1)]


def _bound_check(path: Path = COMMAND_PATH) -> str:
    match = re.search(r"(?m)^\*\*Bound check\.\*\* .*$", _low_route_section(path))
    assert match, "Low route bound check not found"
    return match.group(0)


def test_low_route_spawns_an_engineer():
    section = _low_route_section()
    assert "The conductor implements nothing on a Low ticket" in section
    assert "It spawns one worktree-isolated `engineer`" in section


def test_no_conductor_implements_exception_remains():
    text = COMMAND_PATH.read_text(encoding="utf-8")
    for phrase in ("conductor implements)", "Low conductor", "makes the change itself"):
        assert phrase not in text, f"conductor-implements phrasing remains: {phrase!r}"


def test_every_low_fix_brief_carries_the_bound_check():
    section = _low_route_section()
    assert (
        "The first change, a restart and a CI fix (Phase 10a) are each a fresh spawn, and a QA fix "
        "(Phase 6b) and a Phase 7 fix are each a §Fix-pass delivery; every such brief carries "
        "the ticket and its acceptance text and the bound check below"
    ) in section, "a Low fix spawn must carry the bound check, not only the first spawn"


def test_low_first_spawn_renames_a_stale_local_branch():
    section = _low_route_section()
    assert (
        "Before the first spawn, when `$BRANCH_NAME` is not on origin but exists locally "
        "(`git -C \"$REPO\" rev-parse --verify --quiet \"refs/heads/$BRANCH_NAME\"`), "
        "rename it as the preflight does, to a name free locally and on origin"
    ) in section, "a stale local branch must not fail the Low first spawn's branch create"


def test_phase10a_break_stops_instead_of_escalating():
    step = _bound_check()
    escalate_idx = step.index("A broken bound or a risk-surface touch:")
    stop = (
        "In a Phase 10a fix the PR already exists, so the conductor does not escalate: "
        "it stops as at Phase 10a's cap (`cap_exceeded`, W6b, STOP)"
    )
    assert stop in step, (
        "a Low CI fix that breaks the bound after the PR exists must stop, not "
        "re-enter Phase 3 (which would create a second PR and ledger line)"
    )
    assert step.index(stop) > escalate_idx


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> str:
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, check=True, capture_output=True, text=True
    ).stdout


@pytest.mark.parametrize("path", [
    pytest.param(COMMAND_PATH, id="content"),
    pytest.param(CODEX_SKILL_PATH, id="codex", marks=non_claude),
])
def test_bound_count_ignores_base_commits_after_the_cut(path: Path):
    step = _bound_check(path)
    base_set = re.search(r"`(LOW_BASE=\"\$\(git [^`]*\)\")`", step)
    assert base_set, "the bound check must set LOW_BASE before counting"
    numstat = re.search(r"`(git -C \"\$WORKTREE_PATH\" diff --cached -M --numstat [^`]*)`", step)
    assert numstat, "the bound check's numstat command not found"
    script = f"{base_set.group(1)}\n{numstat.group(1)}\n"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        })
        _run(["git", "init", "-q", "--bare", "-b", "main", "origin.git"], root, env)
        _run(["git", "clone", "-q", "origin.git", "work"], root, env)
        work = root / "work"
        (work / "a.txt").write_text("".join(f"{i}\n" for i in range(10)))
        _run(["git", "add", "a.txt"], work, env)
        _run(["git", "commit", "-qm", "base"], work, env)
        _run(["git", "push", "-q", "origin", "HEAD:main"], work, env)
        _run(["git", "checkout", "-qb", "feat"], work, env)
        # Phase 8's telemetry commit, already on the branch when a Phase 10a fix runs.
        log_dir = work / ".agentic" / "session-log"
        log_dir.mkdir(parents=True)
        (log_dir / "dev.jsonl").write_text("".join(f'{{"n":{i}}}\n' for i in range(150)))
        _run(["git", "add", "-f", ".agentic/session-log/dev.jsonl"], work, env)
        _run(["git", "commit", "-qm", "chore(telemetry): session log"], work, env)

        _run(["git", "clone", "-q", "-b", "main", "origin.git", "other"], root, env)
        other = root / "other"
        (other / "unrelated.txt").write_text("".join(f"{i}\n" for i in range(200)))
        _run(["git", "add", "unrelated.txt"], other, env)
        _run(["git", "commit", "-qm", "unrelated"], other, env)
        _run(["git", "push", "-q", "origin", "HEAD:main"], other, env)

        _run(["git", "fetch", "-q", "origin"], work, env)
        with (work / "a.txt").open("a") as fh:
            fh.write("10\n")
        _run(["git", "add", "a.txt"], work, env)

        env.update({"WORKTREE_PATH": str(work), "BASE_BRANCH": "main"})
        out = _run(["bash", "-c", script], work, env)

    assert "a.txt" in out, out
    assert "unrelated.txt" not in out, (
        "the bound check counted a base commit merged after the branch was cut: " + out
    )
    assert ".agentic/session-log" not in out, (
        "the bound check counted Phase 8's telemetry commit as part of the change: " + out
    )
