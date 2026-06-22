#!/usr/bin/env python3
"""
Tests for bin/agentic-team Unit 1: team.yml loader + schema validation.

AC1 regression tests:
  test_invalid_harness_rejected          - unknown harness in roles -> non-zero exit
  test_invalid_default_harness_rejected  - unknown default_harness -> non-zero exit
  test_role_maps_to_harness_model        - valid role entry round-trips through loader
  test_project_team_yml_overrides_global - project file wins on per-key merge

Additional coverage:
  test_valid_config_loads_cleanly        - well-formed team.yml parses without error
  test_unknown_role_rejected             - unknown role key -> non-zero exit
  test_missing_files_treated_as_empty   - absent team.yml files -> empty config (ok)
  test_scalar_role_treated_as_harness   - scalar string role value sets harness
  test_dispatch_block_parsed             - dispatch sub-block round-trips
  test_normalize_role_spec_imported      - _role_spec.normalize_role_spec is wired

Run with: python3 -m pytest bin/tests/test_agentic_team.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load agentic-team as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN = Path(__file__).parent.parent
_TEAM_PATH = _BIN / "agentic-team"

_loader = importlib.machinery.SourceFileLoader("agentic_team", str(_TEAM_PATH))
_spec = importlib.util.spec_from_loader("agentic_team", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-team from {_TEAM_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_load_team_config = _mod._load_team_config
_validate_config = _mod._validate_config
_role_entry = _mod._role_entry
_parse_team_yml = _mod._parse_team_yml
main = _mod.main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# AC1 required tests
# ---------------------------------------------------------------------------

def test_invalid_harness_rejected(tmp_path):
    """Unknown harness in roles -> non-zero exit."""
    team_yml = _write(tmp_path, "team.yml", """
        enabled: true
        roles:
          engineer:
            harness: notaharness
            model: gpt-5
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert errors, "expected at least one error for unknown harness"
    assert any("notaharness" in e for e in errors)


def test_invalid_default_harness_rejected(tmp_path):
    """Unknown default_harness -> non-zero exit, named error."""
    team_yml = _write(tmp_path, "team.yml", """
        enabled: true
        default_harness: badharness
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert errors, "expected error for unknown default_harness"
    assert any("badharness" in e for e in errors)
    assert any("default_harness" in e for e in errors)


def test_role_maps_to_harness_model(tmp_path):
    """Valid role with harness + model round-trips through loader and _role_entry."""
    team_yml = _write(tmp_path, "team.yml", """
        enabled: true
        roles:
          engineer:
            harness: codex
            model: gpt-5.3-codex
            effort: medium
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert not errors, f"unexpected errors: {errors}"
    entry = _role_entry(config["roles"]["engineer"])
    assert entry["harness"] == "codex"
    assert entry["model"] == "gpt-5.3-codex"
    assert entry["effort"] == "medium"


def test_project_team_yml_overrides_global(tmp_path):
    """Project team.yml wins on per-top-level-key merge."""
    global_dir = tmp_path / "global_agentic"
    project_dir = tmp_path / "project_agentic"
    global_dir.mkdir()
    project_dir.mkdir()

    global_yml = global_dir / "team.yml"
    global_yml.write_text(textwrap.dedent("""
        enabled: true
        default_harness: codex
        roles:
          engineer:
            harness: codex
            model: gpt-5.3-codex
    """), encoding="utf-8")

    project_yml = project_dir / "team.yml"
    project_yml.write_text(textwrap.dedent("""
        default_harness: gemini
        roles:
          engineer:
            harness: gemini
            model: gemini-2.5-flash
    """), encoding="utf-8")

    config = _load_team_config(global_path=global_yml, project_path=project_yml)
    # project wins on default_harness
    assert config["default_harness"] == "gemini"
    # project wins on roles block entirely (shallow merge)
    assert config["roles"]["engineer"]["harness"] == "gemini"
    assert config["roles"]["engineer"]["model"] == "gemini-2.5-flash"
    # enabled from global survives (project didn't set it)
    assert config.get("enabled") is True


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------

def test_valid_config_loads_cleanly(tmp_path):
    """Well-formed team.yml with multiple roles parses without error."""
    team_yml = _write(tmp_path, "team.yml", """
        enabled: true
        default_harness: codex
        roles:
          engineer:
            harness: codex
            model: gpt-5.3-codex
          qa-engineer:
            harness: gemini
            model: gemini-2.5-flash
          skeptic:
            harness: claude
            model: claude-sonnet-4-6
        dispatch:
          timeout_seconds: 1800
          output_format: json
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert not errors, f"unexpected errors: {errors}"
    assert config["enabled"] is True
    assert config["default_harness"] == "codex"
    assert config["dispatch"]["timeout_seconds"] == 1800


def test_unknown_role_rejected(tmp_path):
    """Unknown role key -> error returned."""
    team_yml = _write(tmp_path, "team.yml", """
        roles:
          notarole:
            harness: codex
            model: gpt-5
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert errors, "expected error for unknown role"
    assert any("notarole" in e for e in errors)


def test_missing_files_treated_as_empty(tmp_path):
    """Absent team.yml files produce empty config (no error)."""
    config = _load_team_config(
        global_path=tmp_path / "nonexistent_global.yml",
        project_path=tmp_path / "nonexistent_project.yml",
    )
    assert config == {}
    errors = _validate_config(config)
    assert not errors


def test_scalar_role_treated_as_harness(tmp_path):
    """Scalar string role value is treated as harness name."""
    team_yml = _write(tmp_path, "team.yml", """
        roles:
          engineer: codex
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert not errors, f"unexpected errors: {errors}"
    entry = _role_entry(config["roles"]["engineer"])
    assert entry["harness"] == "codex"


def test_dispatch_block_parsed(tmp_path):
    """dispatch sub-block round-trips correctly."""
    team_yml = _write(tmp_path, "team.yml", """
        dispatch:
          timeout_seconds: 900
          output_format: json
    """)
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    assert config["dispatch"]["timeout_seconds"] == 900
    assert config["dispatch"]["output_format"] == "json"


def test_normalize_role_spec_imported():
    """normalize_role_spec is available and wired from _role_spec."""
    nrs = _mod.normalize_role_spec
    assert nrs("opus") == {"model": "opus"}
    assert nrs({"model": "sonnet", "effort": "high"}) == {"model": "sonnet", "effort": "high"}
    assert nrs(None) == {}
    assert nrs("") == {}


def test_main_exits_nonzero_on_bad_harness(tmp_path):
    """main() returns non-zero when config has invalid harness."""
    project_yml = _write(tmp_path, "team.yml", """
        roles:
          engineer:
            harness: BADHARNESS
            model: x
    """)
    rc = main([
        "--project-config", str(project_yml),
        "--global-config", str(tmp_path / "absent.yml"),
        "discover",
    ])
    assert rc != 0


def test_main_exits_nonzero_on_bad_default_harness(tmp_path):
    """main() returns non-zero when default_harness is invalid."""
    project_yml = _write(tmp_path, "team.yml", """
        default_harness: BADONE
    """)
    rc = main([
        "--project-config", str(project_yml),
        "--global-config", str(tmp_path / "absent.yml"),
        "discover",
    ])
    assert rc != 0
