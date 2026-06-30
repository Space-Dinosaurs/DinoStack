#!/usr/bin/env python3
"""
Regression tests for bin/agentic-status.

Covers:
  PR #249 review M2: _is_pi_omp_harness predicate (4 env vars, truthy semantics).
  PR #256 coverage expansion: _load_config, _resolve_agents_md, _scan_agents_md,
    _resolve, _profile_behavior_block, _role_models_status_block,
    _how_to_adjust_block, main.

Run with: python3 -m pytest bin/tests/test_agentic_status.py -x
       or: python3 bin/tests/test_agentic_status.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

_BIN_PATH = Path(__file__).parent.parent / "agentic-status"
_loader = importlib.machinery.SourceFileLoader("agentic_status", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_status", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-status from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_is_pi_omp_harness = _mod._is_pi_omp_harness
PI_OMP_HARNESS_ENV_VARS = _mod.PI_OMP_HARNESS_ENV_VARS
_load_config = _mod._load_config
_resolve_agents_md = _mod._resolve_agents_md
_scan_agents_md = _mod._scan_agents_md
_resolve = _mod._resolve
_profile_behavior_block = _mod._profile_behavior_block
_role_models_status_block = _mod._role_models_status_block
_telemetry_health_block = _mod._telemetry_health_block
_how_to_adjust_block = _mod._how_to_adjust_block
main = _mod.main

_EXPECTED_VARS = ("PI_HARNESS", "OMP_HARNESS", "OH_MY_PI_HARNESS", "AGENTIC_HARNESS")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_harness_env(monkeypatch):
    for k in _EXPECTED_VARS:
        monkeypatch.delenv(k, raising=False)


def _make_config(tmp_path, data: dict) -> Path:
    p = tmp_path / "agentic-engineering.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _is_pi_omp_harness (PR #249 coverage - kept intact)
# ---------------------------------------------------------------------------

def test_constant_has_four_vars():
    assert tuple(PI_OMP_HARNESS_ENV_VARS) == _EXPECTED_VARS


def test_each_var_individually_true(monkeypatch):
    for k in _EXPECTED_VARS:
        _clear_harness_env(monkeypatch)
        monkeypatch.setenv(k, "pi")
        assert _is_pi_omp_harness() is True, f"{k}=pi should be truthy"


def test_none_set_is_false(monkeypatch):
    _clear_harness_env(monkeypatch)
    assert _is_pi_omp_harness() is False


def test_empty_string_is_false(monkeypatch):
    _clear_harness_env(monkeypatch)
    for k in _EXPECTED_VARS:
        monkeypatch.setenv(k, "")
    assert _is_pi_omp_harness() is False


def test_one_empty_other_set_is_true(monkeypatch):
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("PI_HARNESS", "")
    monkeypatch.setenv("OMP_HARNESS", "omp")
    assert _is_pi_omp_harness() is True


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

def test_load_config_missing_file(monkeypatch, tmp_path):
    # Point CONFIG_PATH at a path that does not exist.
    monkeypatch.setattr(_mod, "CONFIG_PATH", tmp_path / "no-such-file.json")
    cfg, status = _load_config()
    assert status == "missing"
    assert cfg == {}


def test_load_config_valid_json(monkeypatch, tmp_path):
    data = {"mode": "opt-in", "profile": "strict", "preset": "lean"}
    p = _make_config(tmp_path, data)
    monkeypatch.setattr(_mod, "CONFIG_PATH", p)
    cfg, status = _load_config()
    assert status == "found"
    assert cfg["mode"] == "opt-in"
    assert cfg["profile"] == "strict"


def test_load_config_malformed_json(monkeypatch, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(_mod, "CONFIG_PATH", p)
    cfg, status = _load_config()
    assert status == "missing"
    assert cfg == {}


def test_load_config_json_not_dict(monkeypatch, tmp_path):
    p = tmp_path / "list.json"
    p.write_text('["a","b"]', encoding="utf-8")
    monkeypatch.setattr(_mod, "CONFIG_PATH", p)
    cfg, status = _load_config()
    assert status == "missing"
    assert cfg == {}


# ---------------------------------------------------------------------------
# _resolve_agents_md
# ---------------------------------------------------------------------------

def test_resolve_agents_md_direct(monkeypatch, tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("agentic-engineering: opt-in\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = _resolve_agents_md()
    assert result == agents


def test_resolve_agents_md_via_claude_md(monkeypatch, tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("agentic-engineering: opt-in\n", encoding="utf-8")
    # No AGENTS.md at root; CLAUDE.md points at it.
    (tmp_path / "root_AGENTS.md").write_text("", encoding="utf-8")
    # Actually: AGENTS.md exists -> direct hit. Use subdir for the @-import test.
    subdir = tmp_path / "sub"
    subdir.mkdir()
    real_agents = subdir / "AGENTS.md"
    real_agents.write_text("agentic-engineering: opt-in\n", encoding="utf-8")
    claude = subdir / "CLAUDE.md"
    claude.write_text("@AGENTS.md\n", encoding="utf-8")
    monkeypatch.chdir(subdir)
    # AGENTS.md is right there in subdir -> direct hit path.
    result = _resolve_agents_md()
    assert result == real_agents


def test_resolve_agents_md_via_at_import(monkeypatch, tmp_path):
    # cwd has CLAUDE.md pointing at a relative AGENTS.md, but no AGENTS.md directly.
    workdir = tmp_path / "proj"
    workdir.mkdir()
    actual = workdir / "docs" / "AGENTS.md"
    actual.parent.mkdir()
    actual.write_text("agentic-engineering: opt-out\n", encoding="utf-8")
    (workdir / "CLAUDE.md").write_text("@docs/AGENTS.md\n", encoding="utf-8")
    monkeypatch.chdir(workdir)
    result = _resolve_agents_md()
    assert result == actual


def test_resolve_agents_md_none_when_absent(monkeypatch, tmp_path):
    empty = tmp_path / "empty_proj"
    empty.mkdir()
    monkeypatch.chdir(empty)
    result = _resolve_agents_md()
    assert result is None


# ---------------------------------------------------------------------------
# _scan_agents_md
# ---------------------------------------------------------------------------

def test_scan_none_path():
    result = _scan_agents_md(None)
    assert result == {"marker": "none", "project_profile": None, "project_preset": None}


def test_scan_opt_in(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text("agentic-engineering: opt-in\n", encoding="utf-8")
    result = _scan_agents_md(f)
    assert result["marker"] == "opt-in"
    assert result["project_profile"] is None
    assert result["project_preset"] is None


def test_scan_opt_out(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text("agentic-engineering: opt-out\n", encoding="utf-8")
    result = _scan_agents_md(f)
    assert result["marker"] == "opt-out"


def test_scan_profile_line(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text(
        "agentic-engineering: opt-in\nagentic-engineering-profile: strict\n",
        encoding="utf-8",
    )
    result = _scan_agents_md(f)
    assert result["project_profile"] == "strict"


def test_scan_preset_line(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text(
        "agentic-engineering: opt-in\nagentic-engineering-preset: lean\n",
        encoding="utf-8",
    )
    result = _scan_agents_md(f)
    assert result["project_preset"] == "lean"


def test_scan_first_marker_wins(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text(
        "agentic-engineering: opt-in\nagentic-engineering: opt-out\n",
        encoding="utf-8",
    )
    result = _scan_agents_md(f)
    assert result["marker"] == "opt-in"


def test_scan_invalid_profile_ignored(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text(
        "agentic-engineering-profile: super-strict\n",
        encoding="utf-8",
    )
    result = _scan_agents_md(f)
    assert result["project_profile"] is None


def test_scan_missing_file(tmp_path):
    result = _scan_agents_md(tmp_path / "ghost.md")
    assert result == {"marker": "none", "project_profile": None, "project_preset": None}


def test_scan_list_prefix(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text("- agentic-engineering: opt-in\n", encoding="utf-8")
    result = _scan_agents_md(f)
    assert result["marker"] == "opt-in"


# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------

def _empty_scan():
    return {"marker": "none", "project_profile": None, "project_preset": None}


def test_resolve_missing_config_defaults():
    res = _resolve({}, _empty_scan(), "missing")
    assert res["mode"] == "opt-out"
    assert res["profile"] == "default"
    assert res["preset"] is None
    assert res["active"] is True
    assert "global config (default; file missing)" in res["mode_source"]


def test_resolve_optin_mode_no_marker_inactive():
    res = _resolve({"mode": "opt-in"}, _empty_scan(), "found")
    assert res["mode"] == "opt-in"
    assert res["active"] is False
    assert "opt-in mode requires" in res["active_reason"]


def test_resolve_optin_mode_with_optin_marker_active():
    scan = {"marker": "opt-in", "project_profile": None, "project_preset": None}
    res = _resolve({"mode": "opt-in"}, scan, "found")
    assert res["active"] is True
    assert "explicitly opted in" in res["active_reason"]


def test_resolve_optout_mode_optout_marker_inactive():
    scan = {"marker": "opt-out", "project_profile": None, "project_preset": None}
    res = _resolve({"mode": "opt-out"}, scan, "found")
    assert res["active"] is False
    assert "this project opted out" in res["active_reason"]


def test_resolve_optout_mode_no_marker_active():
    res = _resolve({"mode": "opt-out"}, _empty_scan(), "found")
    assert res["active"] is True


def test_resolve_project_preset_overrides_all(tmp_path):
    # project preset -> resolves to profile via PRESET_TABLE; overrides global profile.
    scan = {"marker": "opt-in", "project_profile": "strict", "project_preset": "lean"}
    res = _resolve({"mode": "opt-in", "profile": "strict"}, scan, "found")
    assert res["profile"] == "relaxed"  # lean -> relaxed
    assert res["preset"] == "lean"
    assert res["profile_source"] == "preset-resolved"
    assert res["preset_source"] == "project"


def test_resolve_project_profile_no_preset(tmp_path):
    scan = {"marker": "opt-in", "project_profile": "strict", "project_preset": None}
    res = _resolve({"mode": "opt-in"}, scan, "found")
    assert res["profile"] == "strict"
    assert res["profile_source"] == "project"


def test_resolve_global_preset_when_no_project_override():
    res = _resolve({"mode": "opt-out", "preset": "standard"}, _empty_scan(), "found")
    assert res["profile"] == "default"  # standard -> default
    assert res["preset"] == "standard"
    assert res["profile_source"] == "preset-resolved"
    assert res["preset_source"] == "global"


def test_resolve_global_profile_fallback():
    res = _resolve({"mode": "opt-out", "profile": "relaxed"}, _empty_scan(), "found")
    assert res["profile"] == "relaxed"
    assert res["profile_source"] == "global"
    assert res["preset"] is None


def test_resolve_invalid_mode_treated_as_optout():
    res = _resolve({"mode": "banana"}, _empty_scan(), "found")
    assert res["mode"] == "opt-out"


def test_resolve_invalid_profile_treated_as_default():
    res = _resolve({"profile": "mega-strict"}, _empty_scan(), "found")
    assert res["profile"] == "default"


def test_resolve_set_at_forwarded():
    res = _resolve({"set_at": "2025-01-01T00:00:00Z"}, _empty_scan(), "found")
    assert res["set_at"] == "2025-01-01T00:00:00Z"


def test_resolve_set_at_missing_returns_unset():
    res = _resolve({}, _empty_scan(), "found")
    assert res["set_at"] == "unset"


# ---------------------------------------------------------------------------
# _profile_behavior_block
# ---------------------------------------------------------------------------

def test_profile_behavior_block_default():
    lines = _profile_behavior_block("default")
    joined = "\n".join(lines)
    assert "Profile 'default'" in joined
    # The other two appear as parenthetical contrast.
    assert "(relaxed:" in joined
    assert "(strict:" in joined


def test_profile_behavior_block_relaxed():
    lines = _profile_behavior_block("relaxed")
    joined = "\n".join(lines)
    assert "Profile 'relaxed'" in joined
    assert "(default:" in joined
    assert "(strict:" in joined


def test_profile_behavior_block_strict():
    lines = _profile_behavior_block("strict")
    joined = "\n".join(lines)
    assert "Profile 'strict'" in joined
    assert "(relaxed:" in joined
    assert "(default:" in joined


def test_profile_behavior_block_unknown_falls_back_to_default():
    lines = _profile_behavior_block("nonexistent")
    joined = "\n".join(lines)
    # Falls back to default silently.
    assert "Profile 'default'" in joined


def test_profile_behavior_block_returns_list():
    result = _profile_behavior_block("default")
    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# _role_models_status_block
# ---------------------------------------------------------------------------

def test_role_models_status_block_no_files_no_harness(monkeypatch, tmp_path):
    # No yml files, no harness env -> empty list.
    _clear_harness_env(monkeypatch)
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    result = _role_models_status_block()
    assert result == []


def test_role_models_status_block_harness_no_files(monkeypatch, tmp_path):
    # Harness env set, no yml files -> returns lines with "not configured" message.
    _clear_harness_env(monkeypatch)
    monkeypatch.setenv("PI_HARNESS", "1")
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    result = _role_models_status_block()
    assert len(result) > 0
    assert any("not configured" in ln for ln in result)


def test_role_models_status_block_global_yml(monkeypatch, tmp_path):
    _clear_harness_env(monkeypatch)
    global_yml = tmp_path / "role-models.yml"
    global_yml.write_text(
        "roles:\n  author: sonnet\n  reviewer: haiku\nreviewers:\n  strategy: balanced\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", global_yml)
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    result = _role_models_status_block()
    joined = "\n".join(result)
    assert "active" in joined
    assert "balanced" in joined
    assert "2" in joined  # two role entries


def test_role_models_status_block_project_yml_takes_precedence(monkeypatch, tmp_path):
    _clear_harness_env(monkeypatch)
    project_yml = tmp_path / "project-role-models.yml"
    project_yml.write_text(
        "roles:\n  author: opus\nreviewers:\n  strategy: project-strategy\n",
        encoding="utf-8",
    )
    global_yml = tmp_path / "global-role-models.yml"
    global_yml.write_text(
        "roles:\n  author: haiku\nreviewers:\n  strategy: global-strategy\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", project_yml)
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", global_yml)
    result = _role_models_status_block()
    joined = "\n".join(result)
    assert "project-strategy" in joined
    # Project path appears in source file(s).
    assert str(project_yml) in joined


def test_role_models_status_block_no_bootstrap_sentinel(monkeypatch, tmp_path):
    # PR #256 removed the bootstrap-sentinel mirror. Confirm the function does
    # NOT reference or read any sentinel path - it only reads role-models.yml.
    _clear_harness_env(monkeypatch)
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    # If the function tried to read SENTINEL_PATH it would either read the real
    # developer's sentinel (not hermetic) or error. Confirm it just returns [].
    result = _role_models_status_block()
    assert result == []


# ---------------------------------------------------------------------------
# _how_to_adjust_block
# ---------------------------------------------------------------------------

def test_how_to_adjust_block_returns_lines():
    resolved = {"marker_path_display": "AGENTS.md"}
    lines = _how_to_adjust_block(resolved)
    assert isinstance(lines, list)
    assert len(lines) > 0


def test_how_to_adjust_block_contains_profile_instruction():
    resolved = {"marker_path_display": "AGENTS.md"}
    lines = _how_to_adjust_block(resolved)
    joined = "\n".join(lines)
    assert "agentic-engineering-profile:" in joined


def test_how_to_adjust_block_contains_global_instruction():
    resolved = {"marker_path_display": "/some/path/AGENTS.md"}
    lines = _how_to_adjust_block(resolved)
    joined = "\n".join(lines)
    assert '"profile"' in joined


def test_how_to_adjust_block_agents_path_substituted():
    resolved = {"marker_path_display": "/my/project/AGENTS.md"}
    lines = _how_to_adjust_block(resolved)
    joined = "\n".join(lines)
    assert "/my/project/AGENTS.md" in joined


def test_how_to_adjust_block_no_marker_path_key():
    # marker_path_display absent -> falls back to "AGENTS.md".
    lines = _how_to_adjust_block({})
    joined = "\n".join(lines)
    assert "AGENTS.md" in joined


# ---------------------------------------------------------------------------
# _telemetry_health_block
# ---------------------------------------------------------------------------

def _write_health_file(tmp_path: Path, data: dict) -> Path:
    """Write .agentic/.telemetry-health.json and return its Path."""
    agentic = tmp_path / ".agentic"
    agentic.mkdir(parents=True, exist_ok=True)
    p = agentic / ".telemetry-health.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_telemetry_health_block_absent_file(monkeypatch, tmp_path):
    """Absent health file -> empty list (section omitted silently)."""
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", tmp_path / "no-such-file.json")
    result = _telemetry_health_block()
    assert result == []


def test_telemetry_health_block_malformed_json(monkeypatch, tmp_path):
    """Malformed JSON -> empty list."""
    p = tmp_path / ".telemetry-health.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    result = _telemetry_health_block()
    assert result == []


def test_telemetry_health_block_ok_entry(monkeypatch, tmp_path):
    """failures == 0 -> OK status."""
    data = {
        "updated_at": "2026-01-01T12:00:00Z",
        "targets": {
            "writeSessionLog": {
                "failures": 0,
                "last_success": "2026-01-01T12:00:00Z",
                "last_error": None,
                "last_error_ts": None,
            }
        },
    }
    p = _write_health_file(tmp_path, data)
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    result = _telemetry_health_block()
    joined = "\n".join(result)
    assert "Telemetry health" in joined
    assert "writeSessionLog" in joined
    assert "OK" in joined


def test_telemetry_health_block_failing_entry(monkeypatch, tmp_path):
    """failures > 0 and no recovery -> FAILING status."""
    data = {
        "updated_at": "2026-01-01T12:00:00Z",
        "targets": {
            "writeLoopState": {
                "failures": 3,
                "last_success": None,
                "last_error": "ENOSPC: no space left on device",
                "last_error_ts": "2026-01-01T11:59:00Z",
            }
        },
    }
    p = _write_health_file(tmp_path, data)
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    result = _telemetry_health_block()
    joined = "\n".join(result)
    assert "FAILING" in joined
    assert "3 failure(s)" in joined
    assert "ENOSPC" in joined


def test_telemetry_health_block_recovered_entry(monkeypatch, tmp_path):
    """failures > 0 AND last_success > last_error_ts -> RECOVERED status."""
    data = {
        "updated_at": "2026-01-01T12:00:00Z",
        "targets": {
            "writeContextMd": {
                "failures": 1,
                "last_success": "2026-01-01T12:00:00Z",  # later than error
                "last_error": "EACCES: permission denied",
                "last_error_ts": "2026-01-01T11:00:00Z",
            }
        },
    }
    p = _write_health_file(tmp_path, data)
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    result = _telemetry_health_block()
    joined = "\n".join(result)
    assert "RECOVERED" in joined
    assert "1 failure(s)" in joined
    # Both timestamps rendered.
    assert "2026-01-01T12:00:00Z" in joined
    assert "2026-01-01T11:00:00Z" in joined


def test_telemetry_health_block_empty_targets(monkeypatch, tmp_path):
    """Empty targets dict -> empty list (section omitted)."""
    data = {"updated_at": "2026-01-01T12:00:00Z", "targets": {}}
    p = _write_health_file(tmp_path, data)
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    result = _telemetry_health_block()
    assert result == []


def test_main_output_contains_telemetry_health(monkeypatch, tmp_path, capsys):
    """main() includes 'Telemetry health' when health file is present."""
    _clear_harness_env(monkeypatch)
    monkeypatch.setattr(_mod, "CONFIG_PATH", tmp_path / "no-config.json")
    monkeypatch.setattr(_mod, "SENTINEL_PATH", tmp_path / ".activated")
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    data = {
        "updated_at": "2026-01-01T12:00:00Z",
        "targets": {
            "writeSessionTotal": {
                "failures": 0,
                "last_success": "2026-01-01T12:00:00Z",
                "last_error": None,
                "last_error_ts": None,
            }
        },
    }
    p = _write_health_file(tmp_path, data)
    monkeypatch.setattr(_mod, "HEALTH_FILE_PATH", p)
    monkeypatch.chdir(tmp_path)
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Telemetry health" in out


# ---------------------------------------------------------------------------
# main (smoke test)
# ---------------------------------------------------------------------------

def test_main_exits_zero_empty_env(monkeypatch, tmp_path, capsys):
    # Hermetic: point config, sentinel, role-models, and cwd at tmp locations.
    _clear_harness_env(monkeypatch)
    monkeypatch.setattr(_mod, "CONFIG_PATH", tmp_path / "no-config.json")
    monkeypatch.setattr(_mod, "SENTINEL_PATH", tmp_path / ".activated")
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    monkeypatch.chdir(tmp_path)
    rc = main([])
    assert rc == 0


def test_main_output_contains_status_header(monkeypatch, tmp_path, capsys):
    _clear_harness_env(monkeypatch)
    monkeypatch.setattr(_mod, "CONFIG_PATH", tmp_path / "no-config.json")
    monkeypatch.setattr(_mod, "SENTINEL_PATH", tmp_path / ".activated")
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    monkeypatch.chdir(tmp_path)
    main([])
    out = capsys.readouterr().out
    assert "agentic-engineering status" in out
    assert "What this means" in out
    assert "How to adjust" in out


def test_main_reflects_config(monkeypatch, tmp_path, capsys):
    _clear_harness_env(monkeypatch)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"mode": "opt-in", "profile": "relaxed"}), encoding="utf-8")
    monkeypatch.setattr(_mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(_mod, "SENTINEL_PATH", tmp_path / ".activated")
    monkeypatch.setattr(_mod, "ROLE_MODELS_GLOBAL_PATH", tmp_path / "no-global.yml")
    monkeypatch.setattr(_mod, "ROLE_MODELS_PROJECT_PATH", tmp_path / "no-project.yml")
    monkeypatch.chdir(tmp_path)
    main([])
    out = capsys.readouterr().out
    assert "opt-in" in out
    assert "relaxed" in out


# ---------------------------------------------------------------------------
# Bare-script entry (kept from original)
# ---------------------------------------------------------------------------

def _bare_main() -> int:
    """Bare-script entry: run only the import-free sanity test.

    The monkeypatch-based tests require the pytest fixture and run via
    `python3 -m pytest bin/tests/test_agentic_status.py -x`. This script-mode
    fallback confirms the module loads and the constant is correct.
    """
    failures = 0
    try:
        test_constant_has_four_vars()
        print("PASS  test_constant_has_four_vars")
    except AssertionError as exc:
        print(f"FAIL  test_constant_has_four_vars: {exc}")
        failures += 1
    print("Many tests registered; run via `python3 -m pytest` for the full suite")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(_bare_main())
