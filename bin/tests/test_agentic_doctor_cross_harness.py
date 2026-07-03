"""Unit tests for agentic-doctor's cross-harness health section (D-5).

Covers check_cross_harness() and its helpers by importing bin/agentic-doctor
as a module and mocking the external calls (team.yml loader, discover, omp
models ls) so the tests are hermetic -- no real harness or network needed.

Run with: python3 -m pytest bin/tests/test_agentic_doctor_cross_harness.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

_BIN = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("_agentic_doctor", str(_BIN / "agentic-doctor"))
_spec = importlib.util.spec_from_loader("_agentic_doctor", _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

Doctor = _mod.Doctor
check_cross_harness = _mod.check_cross_harness


def _doc():
    return Doctor(repo_dir=Path("/tmp/repo"), fix=False, json_mode=True)


def _statuses(doc, kind_substr):
    return [s for s, m in doc.findings if kind_substr in m]


class _FakeAT:
    """Minimal stand-in for the imported agentic-team module."""

    def __init__(self, config):
        self._config = config

    def _load_team_config(self):
        return self._config

    def _validate_config(self, config, source="team.yml"):
        return []  # valid by default

    def _role_entry(self, spec):
        if isinstance(spec, str):
            return {"harness": spec}
        if isinstance(spec, dict):
            return {"harness": spec.get("harness"), "model": spec.get("model")}
        return {}


def _patch(monkeypatch, config, installed=None, handles=None, resolver=True):
    at = _FakeAT(config)
    if resolver:
        at._resolve_role_model = lambda *a, **k: "x"
    monkeypatch.setattr(_mod, "_load_agentic_team_module", lambda: at)
    monkeypatch.setattr(_mod, "_installed_harnesses", lambda: installed)
    monkeypatch.setattr(_mod, "_omp_model_handles", lambda: handles)
    return at


def test_all_green(monkeypatch):
    cfg = {"default_harness": "omp",
           "roles": {"engineer": {"harness": "omp", "model": "kimi/kimi-k2.7"}}}
    _patch(monkeypatch, cfg, installed={"omp"}, handles={"kimi/kimi-k2.7"})
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "OK" and "schema valid" in m for s, m in doc.findings)
    assert any(s == "OK" and "omp installed" in m for s, m in doc.findings)
    assert any(s == "OK" and "kimi/kimi-k2.7" in m for s, m in doc.findings)
    assert not doc.has_unresolved_findings()  # no FAIL


def test_missing_harness_fails(monkeypatch):
    cfg = {"default_harness": "omp",
           "roles": {"engineer": {"harness": "codex", "model": "gpt"}}}
    _patch(monkeypatch, cfg, installed={"omp"}, handles=set())
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "FAIL" and "codex" in m for s, m in doc.findings)
    assert doc.has_unresolved_findings()


def test_unknown_model_warns_not_fails(monkeypatch):
    cfg = {"default_harness": "omp",
           "roles": {"engineer": {"harness": "omp", "model": "kimi/not-real"}}}
    _patch(monkeypatch, cfg, installed={"omp"}, handles={"kimi/kimi-k2.7"})
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "WARN" and "not in `omp models ls`" in m for s, m in doc.findings)
    assert not doc.has_unresolved_findings()  # WARN must not fail


def test_bad_schema_fails(monkeypatch):
    cfg = {"roles": {"engineer": {"harness": "omp", "model": "kimi/kimi-k2.7"}}}
    at = _patch(monkeypatch, cfg, installed={"omp"}, handles={"kimi/kimi-k2.7"})
    at._validate_config = lambda c, source="team.yml": ["bad thing"]
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "FAIL" and "bad thing" in m for s, m in doc.findings)


def test_no_team_yml_warns(monkeypatch):
    _patch(monkeypatch, {}, installed={"omp"}, handles=set())
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "WARN" and "no team.yml" in m for s, m in doc.findings)
    assert not doc.has_unresolved_findings()


def test_omp_unavailable_warns(monkeypatch):
    cfg = {"default_harness": "omp",
           "roles": {"engineer": {"harness": "omp", "model": "kimi/kimi-k2.7"}}}
    _patch(monkeypatch, cfg, installed={"omp"}, handles=None)  # omp ls failed
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "WARN" and "not verified" in m for s, m in doc.findings)
    assert not doc.has_unresolved_findings()


def test_dispatch_resolver_absent_warns(monkeypatch):
    cfg = {"default_harness": "omp",
           "roles": {"engineer": {"harness": "omp", "model": "kimi/kimi-k2.7"}}}
    at = _patch(monkeypatch, cfg, installed={"omp"}, handles={"kimi/kimi-k2.7"},
                resolver=False)
    # ensure no resolver attr
    if hasattr(at, "_resolve_role_model"):
        delattr(at, "_resolve_role_model")
    doc = _doc()
    check_cross_harness(doc)
    assert any(s == "WARN" and "model resolution not present" in m for s, m in doc.findings)


def test_omp_handle_parser_box_drawing():
    # The real omp table uses U+2502 separators; the parser must handle them.
    import subprocess

    class _R:
        returncode = 0
        stdout = (
            "│ cc/claude-fable-5   │ 200K │\n"
            "│ kimi/kimi-k2.7      │ 256K │\n"
            "| ascii/pipe-model | 1M |\n"
        )

    orig = subprocess.run
    subprocess.run = lambda *a, **k: _R()  # type: ignore[assignment]
    try:
        import shutil
        _which = shutil.which
        shutil.which = lambda name: "/usr/bin/omp"  # type: ignore[assignment]
        try:
            handles = _mod._omp_model_handles()
        finally:
            shutil.which = _which
    finally:
        subprocess.run = orig  # type: ignore[assignment]
    assert handles == {"cc/claude-fable-5", "kimi/kimi-k2.7", "ascii/pipe-model"}
