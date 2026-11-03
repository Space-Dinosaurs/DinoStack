#!/usr/bin/env python3
"""
Spec tests for /ds-implement-ticket Phase 5 §Low route.

- Step 3's cleanup before the quality gate must never delete or restore a
  file the change itself created, moved or edited. Step 4 stages those
  files, so a step 3 that removes untracked entries without that scope
  deletes the change's own new files before they are gated.
- Step 4's line count must measure only this change. The test runs step 4's
  own commands, taken from the command text, against a scratch repo whose
  base gained an unrelated commit after the branch was cut and fetched.

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
# The generated Codex skill rewrites project paths, so its step 4 is run too.
CODEX_SKILL_PATH = REPO_ROOT / ".codex" / "skills" / "dinostack-codex-implement-ticket" / "SKILL.md"

KEEP_SENTENCE = "Keep every file the change created, moved or edited."
SCOPE_SENTENCE = "Each other entry"


def _low_route_step(number: int, path: Path = COMMAND_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("### Low route (conductor implements)")
    end = text.index("\n### ", start + 1)
    section = text[start:end]
    match = re.search(rf"(?m)^{number}\. .*$", section)
    assert match, f"Low route step {number} not found"
    return match.group(0)


def test_step3_keeps_the_change_before_any_cleanup():
    step = _low_route_step(3)
    assert step.startswith(f"3. {KEEP_SENTENCE}"), (
        "step 3 must open by keeping every file the change created, moved or "
        "edited, so no reading of its cleanup applies to them"
    )


def test_step3_cleanup_applies_only_to_other_entries():
    step = _low_route_step(3)
    scope_idx = step.index(SCOPE_SENTENCE)
    for verb in ("delete", "restore", "clean -fd"):
        for match in re.finditer(re.escape(verb), step):
            assert match.start() > scope_idx, (
                f"step 3 says {verb!r} before scoping the cleanup to entries "
                "that are not part of the change"
            )


def test_low_steps_write_no_loop_state():
    # A loop-state write in steps 1-5 would resume a Low ticket at that write
    # after later steps ran (skipping steps 4-5, or into a retired worktree),
    # and inside a Phase 6b or 10a fix pass would overwrite that loop's state.
    text = COMMAND_PATH.read_text(encoding="utf-8")
    start = text.index("### Low route (conductor implements)")
    section = text[start:text.index("\n### ", start + 1)]
    assert "Steps 1-5 write no loop state" in section
    assert "inside a Phase 6b or 10a fix pass that loop's own state and counters stand" in section
    for token in ("last_phase=", "last_phase_action=", "loop-state-$LOOP_KEY.json"):
        assert token not in section, f"the Low route writes loop state: {token!r}"


def test_step4_phase10a_break_stops_instead_of_escalating():
    step = _low_route_step(4)
    escalate_idx = step.index("A broken bound or a risk-surface touch:")
    stop = (
        "In a Phase 10a fix the PR already exists, so do not escalate: stop as at "
        "Phase 10a's cap (`cap_exceeded`, W6b, STOP)"
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
def test_step4_count_ignores_base_commits_after_the_cut(path: Path):
    step = _low_route_step(4, path)
    base_set = re.search(r"`(LOW_BASE=\"\$\(git [^`]*\)\")`", step)
    assert base_set, "step 4 must set LOW_BASE before counting"
    numstat = re.search(r"`(git -C \"\$WORKTREE_PATH\" diff --cached -M --numstat [^`]*)`", step)
    assert numstat, "step 4's numstat command not found"
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
        "step 4 counted a base commit merged after the branch was cut: " + out
    )
    assert ".agentic/session-log" not in out, (
        "step 4 counted Phase 8's telemetry commit as part of the change: " + out
    )
