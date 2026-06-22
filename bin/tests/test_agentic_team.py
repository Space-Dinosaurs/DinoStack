#!/usr/bin/env python3
"""
Tests for bin/agentic-team Unit 1 + Unit 2.

Unit 1 - team.yml loader + schema validation (AC1):
  test_invalid_harness_rejected          - unknown harness in roles -> non-zero exit
  test_invalid_default_harness_rejected  - unknown default_harness -> non-zero exit
  test_role_maps_to_harness_model        - valid role entry round-trips through loader
  test_project_team_yml_overrides_global - project file wins on per-key merge

Unit 2 - harness discovery (AC2):
  test_discover_marks_absent_harness     - absent binary -> installed=false
  test_discover_json_shape               - --json payload has required keys
  test_discover_uses_mapped_binary_name  - kimi probes kimi-cli not kimi

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
import json
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


def test_yaml_parser_handles_4space_indent_and_special_chars(tmp_path):
    """MAJOR regression: pyyaml loader must accept 4-space-indented team.yml
    and must NOT corrupt model values containing ':' or ' #'."""
    # 4-space indented (valid YAML, rejected by old hand-rolled parser)
    team_yml = _write(tmp_path, "team.yml", """\
enabled: true
default_harness: codex
roles:
    engineer:
        harness: codex
        model: gpt-5.3-codex
    skeptic:
        harness: claude
        model: claude-sonnet-4-6
""")
    config = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml)
    errors = _validate_config(config, source=str(team_yml))
    assert not errors, f"4-space indent must be accepted, got errors: {errors}"
    assert config["roles"]["engineer"]["model"] == "gpt-5.3-codex"

    # Model value containing ':' must not be truncated
    team_yml2 = _write(tmp_path, "team_colon.yml", """\
roles:
  engineer:
    harness: codex
    model: "namespace:gpt-5"
""")
    config2 = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml2)
    # model value must survive intact (old parser truncated at ':')
    assert config2["roles"]["engineer"]["model"] == "namespace:gpt-5", (
        f"colon in model value was corrupted: {config2['roles']['engineer'].get('model')!r}"
    )

    # Model value containing ' #' must not be truncated
    team_yml3 = _write(tmp_path, "team_hash.yml", """\
roles:
  engineer:
    harness: codex
    model: "gpt-5 #fast"
""")
    config3 = _load_team_config(global_path=Path("/dev/null"), project_path=team_yml3)
    assert config3["roles"]["engineer"]["model"] == "gpt-5 #fast", (
        f"hash in model value was corrupted: {config3['roles']['engineer'].get('model')!r}"
    )


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


# ---------------------------------------------------------------------------
# Unit 2 - AC2: harness discovery
# ---------------------------------------------------------------------------

# Import discover internals
_discover_harnesses = _mod._discover_harnesses
_probe_binary_installed = _mod._probe_binary_installed
HARNESS_BINARY = _mod.HARNESS_BINARY
KNOWN_HARNESSES = _mod.KNOWN_HARNESSES


def test_discover_marks_absent_harness(monkeypatch):
    """Monkeypatching shutil.which to None marks harness as installed=false.

    AC2 regression: absent binary -> installed=false, exit 0 overall.
    Hermetic: env vars cleared + probe_models stubbed so no network call fires
    even if OPENAI_BASE_URL/KIMI_BASE_URL happen to be set in the CI runner.
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])
    # Make every binary appear absent
    monkeypatch.setattr(_shutil, "which", lambda _b: None)
    payload = _discover_harnesses()

    for harness in KNOWN_HARNESSES:
        assert harness in payload, f"harness {harness!r} missing from discover output"
        assert payload[harness]["installed"] is False, (
            f"harness {harness!r} should be absent but got installed=True"
        )
        assert payload[harness]["models"] == [], (
            f"absent harness {harness!r} should have models=[]"
        )


def test_discover_json_shape(monkeypatch):
    """--json payload contains required top-level keys for every harness.

    AC2 regression: json shape must include installed, models,
    invocation_family, native_subagent_disable_flag.
    Hermetic: env vars cleared + probe_models stubbed.
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])
    monkeypatch.setattr(_shutil, "which", lambda _b: None)
    payload = _discover_harnesses()

    required_keys = {
        "installed",
        "models",
        "invocation_family",
        "native_subagent_disable_flag",
    }
    for harness, info in payload.items():
        missing = required_keys - info.keys()
        assert not missing, (
            f"harness {harness!r} payload missing keys: {missing}"
        )
        assert isinstance(info["installed"], bool)
        assert isinstance(info["models"], list)
        assert isinstance(info["invocation_family"], str)
        # native_subagent_disable_flag may be None or str
        assert info["native_subagent_disable_flag"] is None or isinstance(
            info["native_subagent_disable_flag"], str
        )


def test_discover_uses_mapped_binary_name(monkeypatch):
    """discover probes kimi-cli (not kimi) for the kimi harness.

    AC2 regression: the binary-name map is the only hardcoded per-harness
    fact; kimi -> kimi-cli must be honoured.
    Hermetic: env vars cleared + probe_models stubbed.
    """
    probed: list[str] = []

    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])

    def fake_which(binary: str) -> str | None:
        probed.append(binary)
        return None  # report all absent; we only care what was probed

    monkeypatch.setattr(_shutil, "which", fake_which)
    _discover_harnesses()

    assert "kimi-cli" in probed, (
        f"expected kimi-cli to be probed but got: {probed}"
    )
    assert "kimi" not in probed, (
        f"kimi (bare name) should NOT be probed directly; got: {probed}"
    )


def test_discover_installed_harness_has_version_field(monkeypatch):
    """When a harness is installed, the version key is present (may be None).

    Installed but --version failing -> version=None is acceptable.
    Hermetic: env vars cleared + probe_models stubbed so codex's OPENAI_BASE_URL
    path never fires even if the var happens to be set in the runner.
    """
    import shutil as _shutil
    import subprocess as _subprocess

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])

    # Make 'codex' appear installed, all others absent
    def fake_which(binary: str) -> str | None:
        return "/usr/local/bin/codex" if binary == "codex" else None

    # Make --version call fail (simulate no --version support)
    def fake_run(*args, **kwargs):  # type: ignore[override]
        class _Result:
            stdout = ""
            returncode = 1
        return _Result()

    monkeypatch.setattr(_shutil, "which", fake_which)
    monkeypatch.setattr(_subprocess, "run", fake_run)

    payload = _discover_harnesses()
    assert payload["codex"]["installed"] is True
    assert "version" in payload["codex"]  # key must be present even if None


def test_discover_exit_zero_when_all_absent(monkeypatch, tmp_path):
    """main() returns 0 from discover even when every harness is absent.
    Hermetic: env vars cleared + probe_models stubbed.
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])
    monkeypatch.setattr(_shutil, "which", lambda _b: None)

    rc = main([
        "--global-config", str(tmp_path / "absent.yml"),
        "--project-config", str(tmp_path / "absent2.yml"),
        "discover",
    ])
    assert rc == 0, f"discover should exit 0 when all harnesses absent, got {rc}"


def test_discover_json_flag_produces_valid_json(monkeypatch, tmp_path, capsys):
    """discover --json produces valid JSON parseable output.
    Hermetic: env vars cleared + probe_models stubbed.
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_mod, "probe_models", lambda *_a, **_kw: [])
    monkeypatch.setattr(_shutil, "which", lambda _b: None)

    rc = main([
        "--global-config", str(tmp_path / "absent.yml"),
        "--project-config", str(tmp_path / "absent2.yml"),
        "discover",
        "--json",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, dict)
    # Every known harness must appear
    for h in KNOWN_HARNESSES:
        assert h in parsed, f"harness {h!r} missing from JSON output"


def test_discover_binary_map_coverage():
    """HARNESS_BINARY covers every KNOWN_HARNESS entry."""
    missing = KNOWN_HARNESSES - HARNESS_BINARY.keys()
    assert not missing, (
        f"HARNESS_BINARY is missing entries for: {missing}. "
        "Add a binary-name mapping for each new harness."
    )


def test_discover_env_var_flows_into_probe(monkeypatch):
    """When OPENAI_BASE_URL is set and codex is installed, probe_models is called
    with that URL and the returned models appear in the payload.

    Proves the HARNESS_MODELS_ENV -> probe_models wiring without real network.
    """
    import shutil as _shutil
    import subprocess as _subprocess

    fake_url = "http://localhost:19999"
    stub_models = ["gpt-5.3-codex", "gpt-5.3-mini"]

    monkeypatch.setenv("OPENAI_BASE_URL", fake_url)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)

    probed_urls: list[str] = []

    def stub_probe(url: str, *_a, **_kw) -> list[str]:
        probed_urls.append(url)
        return stub_models

    monkeypatch.setattr(_mod, "probe_models", stub_probe)

    # codex appears installed; all others absent
    monkeypatch.setattr(_shutil, "which",
                        lambda b: "/usr/local/bin/codex" if b == "codex" else None)

    # --version call returns something harmless
    def fake_run(*args, **kwargs):  # type: ignore[override]
        class _R:
            stdout = "codex 1.0.0"
            returncode = 0
        return _R()

    monkeypatch.setattr(_subprocess, "run", fake_run)

    payload = _discover_harnesses()

    assert payload["codex"]["installed"] is True
    assert payload["codex"]["models"] == stub_models, (
        f"models from probe_models must flow into payload, got {payload['codex']['models']!r}"
    )
    assert fake_url in probed_urls, (
        f"probe_models must be called with OPENAI_BASE_URL={fake_url!r}, called with {probed_urls}"
    )
