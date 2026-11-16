"""Tests for ds-doctor's check_disk: OK with nothing sweepable, WARN with an
aged candidate (which it never deletes), SKIP under the kill switch and
under a live --fix, a disk line under --fix --dry-run, and an exit code the
WARN does not change.

ds-disk runs against fixture roots under tmp_path via check_disk's
extra_args; HOME is a scratch dir, so nothing real is scanned or touched.
"""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BIN = Path(__file__).resolve().parent.parent
_loader = _ilm.SourceFileLoader("_ds_doctor_disk", str(_BIN / "ds-doctor"))
doctor = _ilu.module_from_spec(_ilu.spec_from_loader("_ds_doctor_disk", _loader))
_loader.exec_module(doctor)

OLD = 30 * 24 * 3600
_CHECK_DISK = doctor.check_disk


@pytest.fixture
def fx(tmp_path, monkeypatch):
    home = tmp_path / "home"
    tmpdir = tmp_path / "tmp"
    scratch = tmp_path / "scratch"
    for d in (home, tmpdir, scratch):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR",
                "AE_DOCTOR_DISK_CHECK_DISABLE", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
    return {"home": home, "args": ("--tmpdir", str(tmpdir), "--scratch-root", str(scratch)), "tmpdir": tmpdir}


def _aged_candidate(tmpdir: Path) -> Path:
    d = tmpdir / "agent-browser-chrome-old"
    d.mkdir()
    (d / "data").write_text("x")
    t = time.time() - OLD
    os.utime(d / "data", (t, t))
    os.utime(d, (t, t))
    return d


def _disk_findings(doc):
    return [(s, m) for s, m in doc.findings if m.startswith("disk:")]


def test_ok_when_nothing_sweepable(fx):
    doc = doctor.Doctor(repo_dir=fx["home"], fix=False, json_mode=True)
    doctor.check_disk(doc, fx["args"])
    (status, message), = _disk_findings(doc)
    assert status == "OK", message
    assert "free on" in message


def test_warn_with_aged_candidate_and_nothing_deleted(fx):
    cand = _aged_candidate(fx["tmpdir"])
    doc = doctor.Doctor(repo_dir=fx["home"], fix=False, json_mode=True)
    before = doc.has_unresolved_findings()
    doctor.check_disk(doc, fx["args"])
    (status, message), = _disk_findings(doc)
    assert status == "WARN", message
    assert "ds-disk --sweep" in message
    assert cand.is_dir()
    assert doc.has_unresolved_findings() == before


def test_skip_under_kill_switch(fx, monkeypatch):
    monkeypatch.setenv("AE_DOCTOR_DISK_CHECK_DISABLE", "1")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ds-disk ran"))
    doc = doctor.Doctor(repo_dir=fx["home"], fix=False, json_mode=True)
    doctor.check_disk(doc, fx["args"])
    (status, _), = _disk_findings(doc)
    assert status == "SKIP"


def test_skip_under_live_fix(fx, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ds-disk ran"))
    doc = doctor.Doctor(repo_dir=fx["home"], fix=True, json_mode=True)
    doctor.check_disk(doc, fx["args"])
    (status, _), = _disk_findings(doc)
    assert status == "SKIP"


def test_report_failure_is_warn_not_fail(fx, monkeypatch):
    def broken(*a, **k):
        return subprocess.CompletedProcess(a, 1, stdout="not json", stderr="")
    monkeypatch.setattr(subprocess, "run", broken)
    doc = doctor.Doctor(repo_dir=fx["home"], fix=False, json_mode=True)
    doctor.check_disk(doc, fx["args"])
    (status, _), = _disk_findings(doc)
    assert status == "WARN"


def _main(monkeypatch, capsys, fx, *argv):
    monkeypatch.setattr(doctor, "check_disk", lambda doc: _CHECK_DISK(doc, fx["args"]))
    monkeypatch.setattr(sys, "argv", ["ds-doctor", *argv, "--json"])
    rc = doctor.main()
    payload = json.loads(capsys.readouterr().out)
    disk = [f for f in payload["findings"] if f["message"].startswith("disk:")]
    assert len(disk) == 1, payload["findings"]
    return rc, disk[0]["status"]


def test_fix_dry_run_reports_read_only_and_exit_unchanged(fx, monkeypatch, capsys):
    cand = _aged_candidate(fx["tmpdir"])
    rc_on, status_on = _main(monkeypatch, capsys, fx, "--fix", "--dry-run")
    assert status_on == "WARN"
    assert cand.is_dir()
    monkeypatch.setenv("AE_DOCTOR_DISK_CHECK_DISABLE", "1")
    rc_off, status_off = _main(monkeypatch, capsys, fx, "--fix", "--dry-run")
    assert status_off == "SKIP"
    assert rc_on == rc_off
