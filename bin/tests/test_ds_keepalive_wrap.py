"""bin/ds-keepalive-wrap: the in-session wrap's lock/write/prune/release
sequence. Runs the executable directly and through the form the Claude Code
Bash tool uses (`<shell> -c "eval '<cmd>' && pwd -P"`), where a failure that
only sets errexit inside the command would go unnoticed."""

import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "bin" / "ds-keepalive-wrap"
CMD_DOC = REPO / "content" / "commands" / "ds-wrap-deferred.md"
SID = "11111111-2222-3333-4444-555555555555"
HEADINGS = ["Goal", "Next step", "Pending operator decisions", "Work state", "Artifacts", "Agents", "Watch out"]
WRITTEN = "wrap files written"


def _ck():
    spec = importlib.util.spec_from_file_location("cache_keepalive", REPO / "hooks" / "lib" / "cache_keepalive.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resume(sid=SID, headings=HEADINGS, pad=0):
    body = "# Resume: %s\n*Wrapped now. Kickoff: claude 'x'*\n" % sid
    return body + "".join("## %s\n- item\n" % h for h in headings) + "x" * pad


def _payload(**over):
    data = {"wrap_md": "# Session Context\nline with $HOME, `ticks` and 'quotes'\n", "memory_append": "- learned a thing",
            "resume": _resume()}
    data.update(over)
    return data


def _run(root, payload=None, sid=SID, tool=TOOL, raw=None):
    text = raw if raw is not None else json.dumps(_payload() if payload is None else payload)
    return subprocess.run([str(tool), "--root", str(root), "--session-id", sid], input=text, capture_output=True,
                          text=True, timeout=60)


def _lock(root):
    return Path(root) / ".agentic" / "wrap" / "lock"


def _one_line(r):
    lines = r.stdout.splitlines()
    assert len(lines) == 1, r.stdout + r.stderr
    return lines[0]


def _assert_failed(r, root, needle=""):
    line = _one_line(r)
    assert r.returncode == 1 and line.startswith("WRAP FAILED: ") and needle in line, r.stdout + r.stderr
    assert WRITTEN not in r.stdout
    assert not _lock(root).exists(), "the lock must be released on failure"


def test_fresh_project_writes_everything(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    r = _run(root)
    assert r.returncode == 0 and _one_line(r) == WRITTEN, r.stdout + r.stderr
    agentic = root / ".agentic"
    assert (agentic / "_wrap.md").read_text() == _payload()["wrap_md"]
    assert (agentic / "resume" / (SID + ".md")).read_text() == _resume()
    assert (agentic / "wrap" / "last-wrap").read_text().strip() == SID
    assert (agentic / "memory.md").read_text() == "- learned a thing\n"
    assert not _lock(root).exists()
    assert not [p for p in agentic.rglob(".*.tmp")]


def test_memory_is_appended_and_empty_append_leaves_it(tmp_path):
    root = tmp_path / "proj"
    (root / ".agentic").mkdir(parents=True)
    (root / ".agentic" / "memory.md").write_text("- old entry")
    assert _run(root).returncode == 0
    assert (root / ".agentic" / "memory.md").read_text() == "- old entry\n- learned a thing\n"
    assert _run(root, _payload(memory_append="")).returncode == 0
    assert (root / ".agentic" / "memory.md").read_text() == "- old entry\n- learned a thing\n"


# (path that is made a directory so its write fails, files that must not exist afterwards)
WRITE_FAILURES = [
    ("resume/%s.md" % SID, ["_wrap.md", "wrap/last-wrap", "memory.md"]),
    ("_wrap.md", ["wrap/last-wrap", "memory.md"]),
    ("wrap/last-wrap", ["memory.md"]),
    ("memory.md", []),
]


@pytest.mark.parametrize("blocked,absent", WRITE_FAILURES, ids=[w[0] for w in WRITE_FAILURES])
def test_each_failed_write_fails_loudly_and_stops(tmp_path, blocked, absent):
    root = tmp_path / "proj"
    target = root / ".agentic" / blocked
    (target / "in-the-way").mkdir(parents=True)
    r = _run(root)
    _assert_failed(r, root, "could not ")
    for rel in absent:
        assert not (root / ".agentic" / rel).exists(), rel + " was written after the failing step"


def test_lock_busy_is_reported_and_nothing_written(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    held = subprocess.run([str(REPO / "bin" / "ds-wrap-acquire-lock"), str(root), "--no-wait", "--role=agent"],
                          capture_output=True, text=True, timeout=30)
    assert held.returncode == 0, held.stdout + held.stderr
    r = _run(root)
    assert r.returncode == 5 and _one_line(r) == "wrap skipped: wrap lock busy", r.stdout + r.stderr
    assert not (root / ".agentic" / "_wrap.md").exists()
    assert _lock(root).exists(), "a busy lock stays with its owner"


@pytest.mark.parametrize("stub", ["echo 'WARNING: lock release failed, lock may persist'\n", "exit 3\n"])
def test_lock_release_failure_is_a_failure(tmp_path, stub):
    tree = tmp_path / "ds"
    (tree / "bin").mkdir(parents=True)
    shutil.copy(TOOL, tree / "bin" / "ds-keepalive-wrap")
    os.symlink(REPO / "bin" / "ds-wrap-acquire-lock", tree / "bin" / "ds-wrap-acquire-lock")
    os.symlink(REPO / "hooks", tree / "hooks")
    rel = tree / "bin" / "ds-wrap-release-lock"
    rel.write_text("#!/bin/sh\n" + stub)
    rel.chmod(0o755)
    root = tmp_path / "proj"
    root.mkdir()
    r = _run(root, tool=tree / "bin" / "ds-keepalive-wrap")
    line = _one_line(r)
    assert r.returncode == 1 and line.startswith("WRAP FAILED: ") and "wrap lock not released" in line, r.stdout
    assert WRITTEN not in r.stdout


def test_oversized_resume_rejected_before_any_write(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    ck = _ck()
    over = ck.RESUME_MAX_BYTES - len(_resume().encode()) + 1
    _assert_failed(_run(root, _payload(resume=_resume(pad=over))), root, "over the %d-byte limit" % ck.RESUME_MAX_BYTES)
    assert not (root / ".agentic" / "_wrap.md").exists()
    assert _run(root, _payload(resume=_resume(pad=over - 1))).returncode == 0


@pytest.mark.parametrize("payload,needle", [
    (_payload(resume=_resume(headings=HEADINGS[:-1])), "headings"),
    (_payload(resume=_resume(headings=HEADINGS[1:] + HEADINGS[:1])), "headings"),
    (_payload(resume=_resume(headings=HEADINGS + ["Extra"])), "headings"),
    (_payload(resume=_resume(sid="other")), "# Resume: " + SID),
    (_payload(wrap_md="  \n"), "wrap_md is empty"),
    ({"wrap_md": "x", "resume": _resume()}, "memory_append"),
    ([1, 2], "not a JSON object"),
], ids=["missing-heading", "reordered", "extra-heading", "wrong-sid", "empty-wrap", "missing-key", "not-object"])
def test_invalid_payload_rejected(tmp_path, payload, needle):
    root = tmp_path / "proj"
    root.mkdir()
    _assert_failed(_run(root, payload), root, needle)
    assert not (root / ".agentic" / "_wrap.md").exists()


def test_invalid_json_rejected(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _assert_failed(_run(root, raw='{"wrap_md": "unterminated'), root, "not valid JSON")


def test_path_escape_refused(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    r = _run(root, _payload(resume=_resume(sid="../../outside/x")), sid="../../outside/x")
    assert r.returncode == 1 and "session id" in r.stdout and not list(outside.iterdir()), r.stdout
    (root / ".agentic").mkdir()
    os.symlink(outside, root / ".agentic" / "resume")
    r = _run(root)
    assert r.returncode == 1 and "resolves outside" in r.stdout and not list(outside.iterdir()), r.stdout
    assert not _lock(root).exists() and not (root / ".agentic" / "_wrap.md").exists()
    other = tmp_path / "proj2"
    other.mkdir()
    os.symlink(outside, other / ".agentic")
    r = _run(other)
    assert r.returncode == 1 and "resolves outside" in r.stdout and not list(outside.iterdir()), r.stdout
    third = tmp_path / "proj3"
    (third / ".agentic").mkdir(parents=True)
    victim = outside / "victim"
    os.symlink(victim, third / ".agentic" / "_wrap.md")
    r = _run(third)
    assert r.returncode == 1 and "is a symlink" in r.stdout and not victim.exists(), r.stdout


def test_sigterm_releases_the_lock(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    p = subprocess.Popen([str(TOOL), "--root", str(root), "--session-id", SID], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if _lock(root).exists():
            break
        time.sleep(0.1)
    assert _lock(root).exists(), "the lock is taken before stdin is read"
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    assert p.returncode == 1 and out.startswith("WRAP FAILED: interrupted"), out + err
    assert not _lock(root).exists() and not (root / ".agentic" / "_wrap.md").exists()


def test_prune_removes_only_old_resume_files(tmp_path):
    root = tmp_path / "proj"
    consumed = root / ".agentic" / "resume" / "consumed"
    consumed.mkdir(parents=True)
    ck = _ck()
    old, fresh = consumed / "old.md", consumed / "fresh.md"
    for path, age_days in ((old, ck.RESUME_RETENTION_DAYS + 1), (fresh, ck.RESUME_RETENTION_DAYS - 1)):
        path.write_text("x")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    assert _run(root).returncode == 0
    assert not old.exists() and fresh.exists() and (root / ".agentic" / "resume" / (SID + ".md")).exists()


def _shell(name):
    path = shutil.which(name)
    if path is None:
        if os.environ.get("CI"):
            pytest.fail("%s is required in CI" % name)
        pytest.skip("%s not installed" % name)
    return path


def _harness(shell, root, payload):
    """The Bash tool's form: the command is eval'd on the left of `&&`."""
    cmd = _ck().wrap_command(str(REPO), SID, str(root)) + " <<'DSW_3fa9c07e12bd_1'\n" + json.dumps(payload) + "\nDSW_3fa9c07e12bd_1"
    return subprocess.run([_shell(shell), "-c", "eval " + shlex.quote(cmd) + " && pwd -P"], capture_output=True, text=True,
                          timeout=60, cwd=str(REPO))


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_harness_form_root_with_quote_and_spaces(tmp_path, shell):
    root = tmp_path / "it's a proj"
    root.mkdir()
    r = _harness(shell, root, _payload())
    assert r.returncode == 0 and r.stdout.splitlines()[0] == WRITTEN, r.stdout + r.stderr
    assert (root / ".agentic" / "resume" / (SID + ".md")).read_text() == _resume()
    assert not _lock(root).exists()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_harness_form_failed_resume_write_is_loud(tmp_path, shell):
    root = tmp_path / "proj"
    (root / ".agentic" / "resume" / (SID + ".md") / "in-the-way").mkdir(parents=True)
    r = _harness(shell, root, _payload())
    assert r.returncode != 0 and WRITTEN not in r.stdout, r.stdout + r.stderr
    assert r.stdout.startswith("WRAP FAILED: ") and len(r.stdout.splitlines()) == 1, r.stdout
    assert not (root / ".agentic" / "_wrap.md").exists() and not _lock(root).exists()


def test_doc_and_note_are_wired_to_the_tool():
    text = CMD_DOC.read_text()
    sec = re.search(r"^## In-session mode\n(.*?)(?=^## )", text, re.S | re.M).group(1)
    assert "`bin/ds-keepalive-wrap`" in sec and "WRAP_COMMAND" in sec
    for line in (WRITTEN, "wrap skipped: wrap lock busy", "WRAP FAILED: <reason>"):
        assert "`" + line + "`" in sec, line
    for key in ("wrap_md", "memory_append", "resume"):
        assert "`" + key + "`" in sec
    ck = _ck()
    note = ck.wrap_note(str(REPO), SID, "/proj")
    assert "WRAP_COMMAND: " + ck.wrap_command(str(REPO), SID, "/proj") in note
    assert shlex.split(ck.wrap_command(str(REPO), SID, "/proj"))[0] == str(TOOL)
    spec = importlib.util.spec_from_loader("ds_keepalive_wrap", importlib.machinery.SourceFileLoader("ds_keepalive_wrap", str(TOOL)))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    block = re.search(r"```\n[ \t]*(# Resume: <sid>\n.*?)```", sec, re.S).group(1)
    assert [l.strip()[3:] for l in block.splitlines() if l.strip().startswith("## ")] == list(tool.RESUME_HEADINGS)
