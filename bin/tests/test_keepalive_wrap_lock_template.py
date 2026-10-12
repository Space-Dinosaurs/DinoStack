"""Executes the call-B template from content/commands/ds-wrap-deferred.md
(In-session mode) against the real wrap-lock binaries, under bash and zsh,
and asserts the lock is released on every path the shell can observe: a
clean run, a failed write, an exit inside the braces, and SIGTERM. A busy
lock is reported and left with its owner."""

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CMD = REPO / "content" / "commands" / "ds-wrap-deferred.md"
SID = "11111111-2222-3333-4444-555555555555"
SHELLS = ["bash", "zsh"]


def _template():
    text = CMD.read_text()
    sec = re.search(r"^## In-session mode\n(.*?)(?=^## )", text, re.S | re.M).group(1)
    block = re.search(r"```bash\n(.*?)```", sec, re.S).group(1)
    return "\n".join(line[3:] if line.startswith("   ") else line for line in block.splitlines())


def _script(root, body):
    t = _template()
    assert "<steps 3-6: one heredoc per file, see below>" in t
    return (t.replace("<root>", str(root)).replace("<repo_dir>", str(REPO)).replace("<sid>", SID)
             .replace("<steps 3-6: one heredoc per file, see below>", body))


def _shell(name):
    path = shutil.which(name)
    if path is None:
        if os.environ.get("CI"):
            pytest.fail("%s is required in CI" % name)
        pytest.skip("%s not installed" % name)
    return path


def _project(tmp_path):
    root = tmp_path / "proj"
    (root / ".agentic").mkdir(parents=True)
    return root


def _lock(root):
    return root / ".agentic" / "wrap" / "lock"


def _released_msg(root, out):
    """zsh runs the EXIT trap while the brace group's redirect is still in
    force, so the trap's line lands in the log rather than on stdout."""
    log = root / ".agentic" / "wrap" / ".wrap-b.log"
    return "wrap lock released" in out or (log.exists() and "wrap lock released" in log.read_text())


@pytest.mark.parametrize("shell", SHELLS)
def test_clean_run_writes_and_releases(tmp_path, shell):
    root = _project(tmp_path)
    body = ("cat > .agentic/.wrap.tmp <<'DSW_3fa9c07e12bd_1'\n# Session Context\nline with DSW_ and $HOME and `x`\n"
            "DSW_3fa9c07e12bd_1\nmv .agentic/.wrap.tmp .agentic/_wrap.md")
    r = subprocess.run([_shell(shell), "-c", _script(root, body)], capture_output=True, text=True, timeout=60)
    assert "wrap files written: 0" in r.stdout and "wrap lock released" in r.stdout, r.stdout + r.stderr
    assert (root / ".agentic" / "_wrap.md").read_text() == "# Session Context\nline with DSW_ and $HOME and `x`\n"
    assert not _lock(root).exists()
    assert len([l for l in r.stdout.splitlines() if l.strip()]) <= 5


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("body", ["cat > .agentic/no/such/dir/file <<'DSW_a_1'\nx\nDSW_a_1", "exit 3"])
def test_failure_inside_braces_releases(tmp_path, shell, body):
    root = _project(tmp_path)
    r = subprocess.run([_shell(shell), "-c", _script(root, body)], capture_output=True, text=True, timeout=60)
    assert _released_msg(root, r.stdout), r.stdout + r.stderr
    assert not _lock(root).exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_sigterm_releases(tmp_path, shell):
    root = _project(tmp_path)
    p = subprocess.Popen([_shell(shell), "-c", _script(root, "sleep 30")], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    for _ in range(100):
        if _lock(root).exists():
            break
        time.sleep(0.1)
    assert _lock(root).exists(), "lock was never acquired"
    os.killpg(p.pid, signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    assert _released_msg(root, out), out + err
    assert not _lock(root).exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_busy_lock_reported_and_left_alone(tmp_path, shell):
    root = _project(tmp_path)
    held = subprocess.run(["node", str(REPO / "bin" / "ds-wrap-acquire-lock"), str(root), "--no-wait", "--role=agent",
                           "--print-token"], capture_output=True, text=True, timeout=30)
    assert held.returncode == 0, held.stdout + held.stderr
    r = subprocess.run([_shell(shell), "-c", _script(root, "touch .agentic/should-not-exist")], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0 and "wrap lock not acquired" in r.stdout, r.stdout + r.stderr
    assert not (root / ".agentic" / "should-not-exist").exists()
    assert _lock(root).exists(), "a busy lock must stay with its owner"
