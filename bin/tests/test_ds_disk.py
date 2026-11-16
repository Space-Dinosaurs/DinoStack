"""Behavioral tests for bin/ds-disk: target globs and near misses, the
seven-check predicate (symlink, foreign uid, age, cwd holder, open file,
git metadata), scratchpad session rules, leftovers, scan-failure fail-safe,
report-mode read-only, and the info sizing budget.

Isolation: HOME, --tmpdir and --scratch-root all sit under pytest's
tmp_path; `_guard` asserts that before any `--sweep`, so no case can reach
the real TMPDIR, /tmp/claude-<uid> or a real repo.
"""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BIN = Path(__file__).resolve().parent.parent
_DISK = _BIN / "ds-disk"

_loader = _ilm.SourceFileLoader("_ds_disk_under_test", str(_DISK))
disk = _ilu.module_from_spec(_ilu.spec_from_loader("_ds_disk_under_test", _loader))
_loader.exec_module(disk)

OLD = 30 * 24 * 3600
UUID_A = "11111111-2222-3333-4444-555555555555"
UUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
UUID_C = "0123abcd-0123-4567-89ab-0123456789ab"


def _age(path: Path, seconds: int = OLD) -> None:
    t = time.time() - seconds
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames + dirnames:
            os.utime(os.path.join(dirpath, name), (t, t), follow_symlinks=False)
    os.utime(path, (t, t), follow_symlinks=False)


def _mkdir(path: Path, files=("data",), seconds: int = OLD) -> Path:
    path.mkdir(parents=True)
    for f in files:
        (path / f).write_text("x")
    _age(path, seconds)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    tmpdir = tmp_path / "tmp"
    scratch = tmp_path / "scratch"
    for d in (home, tmpdir, scratch):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return {"root": tmp_path, "home": home, "tmpdir": tmpdir, "scratch": scratch}


def _guard(env) -> None:
    root = os.path.realpath(env["root"])
    for key in ("home", "tmpdir", "scratch"):
        assert os.path.realpath(env[key]).startswith(root + os.sep), key
    assert os.path.realpath(os.path.expanduser("~")) == os.path.realpath(env["home"])
    real_tmp = os.path.realpath(os.environ.get("TMPDIR") or "/tmp")
    assert os.path.realpath(env["tmpdir"]) != real_tmp
    assert os.path.realpath(env["scratch"]) != os.path.realpath(f"/tmp/claude-{os.getuid()}")


def _run(env, capsys, *extra, sweep=False):
    if sweep:
        _guard(env)
    argv = ["--json", "--tmpdir", str(env["tmpdir"]), "--scratch-root", str(env["scratch"]), *extra]
    if sweep:
        argv.insert(0, "--sweep")
    rc = disk.main(argv)
    out = json.loads(capsys.readouterr().out)
    by_name = {Path(c["path"]).name: c for c in out["candidates"]}
    return rc, out, by_name


def _listing(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_globs_and_near_misses(env, capsys):
    t = env["tmpdir"]
    _mkdir(t / "skc-oauth-abc", files=("connector.db",))
    _mkdir(t / "agent-browser-chrome-abc")
    _mkdir(t / "puppeteer_dev_chrome_profile-abc")
    for near in ("skc-oauth", "agent-browser-chrome", "Puppeteer_dev_chrome_profile-x", "xskc-oauth-1"):
        _mkdir(t / near)
    rc, out, c = _run(env, capsys, sweep=True)
    assert rc == 0, out
    for name in ("skc-oauth-abc", "agent-browser-chrome-abc", "puppeteer_dev_chrome_profile-abc"):
        assert c[name]["action"] == "swept", c[name]
        assert not (t / name).exists()
    for near in ("skc-oauth", "agent-browser-chrome", "Puppeteer_dev_chrome_profile-x", "xskc-oauth-1"):
        assert near not in c
        assert (t / near).is_dir()
    assert not [p for p in t.iterdir() if p.name.startswith(".ds-disk-reaping-")]


def test_age_floors(env, capsys):
    t = env["tmpdir"]
    _mkdir(t / "skc-oauth-young", files=("connector.db",), seconds=5 * 3600)
    _mkdir(t / "skc-oauth-aged", files=("connector.db",), seconds=7 * 3600)
    _mkdir(t / "agent-browser-chrome-young", seconds=23 * 3600)
    old = _mkdir(t / "agent-browser-chrome-fresh-inside")
    (old / "new").write_text("x")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c["skc-oauth-young"]["reason"] == "too_young"
    assert c["skc-oauth-aged"]["action"] == "swept"
    assert c["agent-browser-chrome-young"]["reason"] == "too_young"
    assert c["agent-browser-chrome-fresh-inside"]["reason"] == "too_young"


def test_static_keeps(env, capsys, monkeypatch):
    t = env["tmpdir"]
    _mkdir(t / "skc-oauth-extra", files=("connector.db", "other"))
    real = _mkdir(env["root"] / "elsewhere")
    os.symlink(real, t / "agent-browser-chrome-link")
    (t / "puppeteer_dev_chrome_profile-file").write_text("x")
    _age(t / "puppeteer_dev_chrome_profile-file")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c["skc-oauth-extra"]["reason"] == "unexpected_contents"
    assert c["agent-browser-chrome-link"]["reason"] == "symlink"
    assert c["puppeteer_dev_chrome_profile-file"]["reason"] == "not_directory"
    assert (t / "skc-oauth-extra" / "other").exists()
    assert (real / "data").exists()


def test_foreign_uid_kept(env, capsys, monkeypatch):
    _mkdir(env["tmpdir"] / "agent-browser-chrome-x")
    monkeypatch.setattr(disk, "_current_uid", lambda: os.getuid() + 1)
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c["agent-browser-chrome-x"]["reason"] == "foreign_owner"
    assert (env["tmpdir"] / "agent-browser-chrome-x").is_dir()


def test_scratchpads(env, capsys, monkeypatch):
    proj = env["scratch"] / "-Users-someone-proj"
    proj.mkdir()
    _mkdir(proj / UUID_A)
    _mkdir(proj / UUID_B)
    _mkdir(proj / UUID_C)
    _mkdir(proj / "not-a-uuid")
    upper = _mkdir(proj / UUID_A.upper().replace("-", "_"))
    young = _mkdir(proj / "99999999-2222-3333-4444-555555555555", seconds=6 * 24 * 3600)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", UUID_B)
    transcript = env["home"] / ".claude-alt" / "projects" / "x" / f"{UUID_C}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c[UUID_A]["action"] == "swept"
    assert c[UUID_B]["reason"] == "current_session"
    assert c[UUID_C]["reason"] == "active_transcript"
    assert c[young.name]["reason"] == "too_young"
    assert "not-a-uuid" not in c
    assert (proj / "not-a-uuid").is_dir()
    assert upper.name not in c
    assert upper.is_dir()
    assert (proj / UUID_B).is_dir() and (proj / UUID_C).is_dir()


def test_scratch_project_symlink_skipped(env, capsys):
    real = env["root"] / "realproj"
    real.mkdir()
    _mkdir(real / UUID_A)
    os.symlink(real, env["scratch"] / "linkproj")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert UUID_A not in c
    assert (real / UUID_A).is_dir()


def test_git_metadata_kept(env, capsys):
    proj = env["scratch"] / "p"
    proj.mkdir()
    nested = proj / UUID_A
    nested.mkdir()
    (nested / "work" / "repo" / ".git" / "objects").mkdir(parents=True)
    (nested / "work" / "repo" / "f").write_text("x")
    _age(nested)
    gitfile = proj / UUID_B
    (gitfile / "wt").mkdir(parents=True)
    (gitfile / "wt" / ".git").write_text("gitdir: /somewhere\n")
    _age(gitfile)
    bare = proj / UUID_C
    (bare / "x.git" / "objects").mkdir(parents=True)
    (bare / "x.git" / "refs").mkdir()
    (bare / "x.git" / "HEAD").write_text("ref: refs/heads/main\n")
    _age(bare)
    plain = _mkdir(proj / "99999999-2222-3333-4444-555555555555")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    for name in (UUID_A, UUID_B, UUID_C):
        assert c[name]["reason"] == "contains_git", c[name]
        assert (proj / name).is_dir()
    assert c[plain.name]["action"] == "swept"


def test_leftovers(env, capsys):
    t = env["tmpdir"]
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead = proc.pid
    _mkdir(t / f".ds-disk-reaping-{dead}-agent-browser-chrome-x")
    live = _mkdir(t / f".ds-disk-reaping-{os.getpid()}-agent-browser-chrome-y")
    proj = env["scratch"] / "p"
    proj.mkdir()
    _mkdir(proj / f".ds-disk-reaping-{dead}-{UUID_A}")
    young = _mkdir(t / f".ds-disk-reaping-{dead}-young", seconds=60)
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c[f".ds-disk-reaping-{dead}-agent-browser-chrome-x"]["action"] == "swept"
    assert c[f".ds-disk-reaping-{dead}-{UUID_A}"]["action"] == "swept"
    assert c[live.name]["reason"] == "live_pid"
    assert c[young.name]["reason"] == "too_young"
    assert live.is_dir() and young.is_dir()
    assert sorted(p.name for p in proj.iterdir()) == []


def test_overflowing_leftover_pid_kept(env, capsys):
    huge = _mkdir(env["tmpdir"] / ".ds-disk-reaping-99999999999999999999-x")
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 0
    assert c[huge.name]["reason"] == "live_pid"
    assert huge.is_dir()


def test_cwd_holder_kept(env, capsys):
    held = _mkdir(env["tmpdir"] / "agent-browser-chrome-cwd")
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(held))
    try:
        rc, _, c = _run(env, capsys, sweep=True)
    finally:
        holder.kill()
        holder.wait()
    assert rc == 0
    assert c["agent-browser-chrome-cwd"]["reason"] == "cwd_held"
    assert held.is_dir()


def test_held_open_kept_sibling_swept(env, capsys):
    if shutil.which("lsof") is None:
        if os.environ.get("CI"):
            pytest.fail("lsof is required in CI for the held-open check")
        pytest.skip("lsof not installed")
    held = _mkdir(env["tmpdir"] / "agent-browser-chrome-held")
    _mkdir(env["tmpdir"] / "agent-browser-chrome-free")
    target = held / "data"
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys,time; f=open(sys.argv[1]); print('ok', flush=True); time.sleep(60)", str(target)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ok"
        _age(held)
        rc, _, c = _run(env, capsys, sweep=True)
    finally:
        holder.kill()
        holder.wait()
    assert rc == 0
    assert c["agent-browser-chrome-held"]["reason"] == "held_open"
    assert c["agent-browser-chrome-free"]["action"] == "swept"
    assert target.exists()


def test_scan_failure_skips_everything(env, capsys, monkeypatch):
    _mkdir(env["tmpdir"] / "agent-browser-chrome-a")
    _mkdir(env["tmpdir"] / "puppeteer_dev_chrome_profile-b")
    monkeypatch.setattr(disk, "_open_paths_scan", lambda: None)
    rc, _, c = _run(env, capsys, sweep=True)
    assert rc == 1
    for name in ("agent-browser-chrome-a", "puppeteer_dev_chrome_profile-b"):
        assert c[name]["action"] == "keep" and c[name]["reason"] == "scan_unavailable"
        assert (env["tmpdir"] / name).is_dir()


def test_report_mode_deletes_nothing(env, capsys):
    _mkdir(env["tmpdir"] / "agent-browser-chrome-a")
    proj = env["scratch"] / "p"
    proj.mkdir()
    _mkdir(proj / UUID_A)
    before = _listing(env["root"])
    rc, out, c = _run(env, capsys)
    assert rc == 0
    assert c["agent-browser-chrome-a"]["action"] == "would_sweep"
    assert c[UUID_A]["action"] == "would_sweep"
    assert _listing(env["root"]) == before
    assert set(out) == {"free_bytes", "volume_path", "candidates", "info", "errors"}


def test_info_budget_gives_null_bytes(env, capsys, monkeypatch):
    (env["home"] / ".cache").mkdir()
    monkeypatch.setattr(disk, "INFO_BUDGET_SECONDS", 0.0)
    rc, out, _ = _run(env, capsys)
    assert rc == 0
    caches = [i for i in out["info"] if i["label"] == "caches"]
    assert caches and all(i["bytes"] is None for i in caches)
    assert "budget" in caches[0]["note"]


def test_info_measures_within_budget(env, capsys):
    cache = env["home"] / ".cache"
    cache.mkdir()
    (cache / "blob").write_bytes(b"x" * 100_000)
    rc, out, _ = _run(env, capsys)
    assert rc == 0
    caches = [i for i in out["info"] if i["label"] == "caches"]
    assert caches[0]["bytes"] and caches[0]["bytes"] >= 100_000


def test_cli_usage_error_exits_2():
    r = subprocess.run([sys.executable, str(_DISK), "--bogus"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
