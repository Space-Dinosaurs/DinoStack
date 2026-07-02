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
  test_dispatch_path_guardrail_shims_opencode_and_copilot - opencode/copilot shims present

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
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
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
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
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
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    probed: list[str] = []

    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)

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
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    import shutil as _shutil
    import subprocess as _subprocess

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)

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
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.setattr(_shutil, "which", lambda _b: None)

    rc = main([
        "--global-config", str(tmp_path / "absent.yml"),
        "--project-config", str(tmp_path / "absent2.yml"),
        "discover",
    ])
    assert rc == 0, f"discover should exit 0 when all harnesses absent, got {rc}"


def test_discover_json_flag_produces_valid_json(monkeypatch, tmp_path, capsys):
    """discover --json produces valid JSON parseable output.
    Hermetic: env vars cleared; models=[] always (static, no probe).
    """
    import shutil as _shutil

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
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


# ===========================================================================
# Unit 3 - dispatch / status / collect (AC3 + AC5 worker-side + AC8)
# ===========================================================================
#
# All dispatch tests use a FAKE-EXEC shim: a tiny shell script placed on a
# temp PATH entry that records argv and writes a known payload to stdout
# without calling any real CLI or network.
# ===========================================================================

import os as _os
import stat as _stat
import subprocess as _subprocess_mod
import textwrap as _textwrap
import threading as _threading

# Pull Unit 3 symbols from the already-loaded module.
_build_worker_argv = _mod._build_worker_argv
_build_shim_dir = _mod._build_shim_dir
_collect_output = _mod._collect_output
_run_status = _mod._run_status
_make_run_id = _mod._make_run_id
_LEAF_WORKER_CLAUSE = _mod._LEAF_WORKER_CLAUSE
HARNESS_BINARY = _mod.HARNESS_BINARY


def _make_fake_exec(tmp_path: Path, binary_name: str, stdout_payload: str) -> Path:
    """Write a tiny fake binary that echoes *stdout_payload* and exits 0.

    Returns the directory containing the fake binary (suitable for PATH prepend).
    """
    bin_dir = tmp_path / f"fake_bin_{binary_name}"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / binary_name
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s" {_subprocess_mod.list2cmdline([stdout_payload])}\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
    return bin_dir


def _make_brief_file(tmp_path: Path, content: str = "Do something.") -> Path:
    f = tmp_path / "brief.md"
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# AC3 + AC8: argv construction (no live CLIs)
# ---------------------------------------------------------------------------

def test_dispatch_builds_codex_argv():
    """codex argv includes 'exec', '--json', '--sandbox', 'read-only'."""
    argv = _build_worker_argv("codex", "test brief")
    assert argv[0] == HARNESS_BINARY["codex"]
    assert "exec" in argv
    assert "--json" in argv
    assert "--sandbox" in argv
    assert "read-only" in argv
    assert "--skip-git-repo-check" in argv


def test_dispatch_builds_gemini_argv():
    """gemini argv includes '-p' and '--output-format', 'json'."""
    argv = _build_worker_argv("gemini", "test brief")
    assert argv[0] == HARNESS_BINARY["gemini"]
    assert "-p" in argv
    assert "--output-format" in argv
    assert "json" in argv


def test_dispatch_builds_cursor_argv():
    """cursor-agent argv includes '-p', '--force', '--output-format', 'json'.

    The < /dev/null redirection is handled by Popen stdin=DEVNULL in dispatch,
    not in the argv list; we verify the flag set is correct here.
    """
    argv = _build_worker_argv("cursor-agent", "test brief")
    assert argv[0] == HARNESS_BINARY["cursor-agent"]
    assert "-p" in argv
    assert "--force" in argv
    assert "--output-format" in argv
    assert "json" in argv


def test_dispatch_builds_claude_argv():
    """claude worker argv includes '-p' and '--output-format', 'json'."""
    argv = _build_worker_argv("claude", "test brief")
    assert argv[0] == HARNESS_BINARY["claude"]
    assert "-p" in argv
    assert "--output-format" in argv
    assert "json" in argv


def test_dispatch_builds_opencode_argv():
    """opencode argv is ['opencode', 'run', '<brief>'] with no model flag."""
    argv = _build_worker_argv("opencode", "test brief")
    assert argv[0] == HARNESS_BINARY["opencode"]
    assert argv[1] == "run"
    assert "test brief" in argv
    assert "--model" not in argv


def test_dispatch_builds_copilot_argv():
    """copilot argv includes '-p', '--allow-all-tools', '--allow-all-paths'."""
    argv = _build_worker_argv("copilot", "test brief")
    assert argv[0] == HARNESS_BINARY["copilot"]
    assert "-p" in argv
    assert "test brief" in argv
    assert "--allow-all-tools" in argv
    assert "--allow-all-paths" in argv


# ---------------------------------------------------------------------------
# AC5: PATH guardrail shims
# ---------------------------------------------------------------------------

def test_dispatch_path_guardrail_shims_git(tmp_path):
    """Shim dir contains a 'git' shim that is executable."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shim_dir = _build_shim_dir(run_dir, exempt_binary="codex")
    git_shim = shim_dir / "git"
    assert git_shim.exists(), "git shim must be present"
    assert git_shim.stat().st_mode & _stat.S_IEXEC, "git shim must be executable"


def test_dispatch_path_guardrail_shims_opencode_and_copilot(tmp_path):
    """Shim dir contains executable 'opencode' and 'copilot' shims."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shim_dir = _build_shim_dir(run_dir, exempt_binary="codex")
    for binary_name in ("opencode", "copilot"):
        shim = shim_dir / binary_name
        assert shim.exists(), f"{binary_name} shim must be present"
        assert shim.stat().st_mode & _stat.S_IEXEC, f"{binary_name} shim must be executable"


def test_git_shim_exits_nonzero_and_logs(tmp_path):
    """Running the git shim exits non-zero and writes to violations.log."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shim_dir = _build_shim_dir(run_dir, exempt_binary="codex")
    git_shim = shim_dir / "git"

    result = _subprocess_mod.run(
        [str(git_shim), "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "git shim must exit non-zero"

    violations_log = run_dir / "violations.log"
    assert violations_log.exists(), "violations.log must be created on shim invocation"
    log_text = violations_log.read_text(encoding="utf-8")
    assert "git" in log_text, "violations.log must mention the blocked binary"


def test_shim_exempt_binary_absent(tmp_path):
    """The exempt binary (the worker's own CLI) is NOT shimmed."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shim_dir = _build_shim_dir(run_dir, exempt_binary="codex")
    codex_shim = shim_dir / "codex"
    assert not codex_shim.exists(), (
        "exempt binary must not have a blocking shim"
    )


# ---------------------------------------------------------------------------
# AC5: workdir isolation
# ---------------------------------------------------------------------------

def _dispatch_via_subprocess(
    tmp_path: Path,
    workdir: Path,
    fake_bin_dir: Path,
    brief_file: Path,
    harness: str = "codex",
    role: str = "engineer",
) -> tuple[int, str]:
    """Run dispatch as a subprocess with fake_bin_dir prepended to PATH.

    Returns (returncode, run_id_or_stderr).
    """
    import sys as _sys
    env_patch = dict(_os.environ)
    env_patch["PATH"] = str(fake_bin_dir) + _os.pathsep + env_patch.get("PATH", "")
    agentic_team_path = str(_BIN / "agentic-team")
    result = _subprocess_mod.run(
        [_sys.executable, agentic_team_path,
         "dispatch",
         "--harness", harness,
         "--role", role,
         "--brief", str(brief_file),
         "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        env=env_patch,
    )
    return result.returncode, result.stdout.strip() or result.stderr.strip()


def _wait_for_stdout(run_dir: Path, timeout: float = 5.0) -> None:
    """Poll until run_dir/stdout exists and is non-empty (or timeout)."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while not (run_dir / "stdout").exists() or (run_dir / "stdout").stat().st_size == 0:
        if _time.monotonic() > deadline:
            break
        _time.sleep(0.05)


def _wait_for_exit_file(run_dir: Path, timeout: float = 5.0) -> None:
    """Poll until run_dir/exit exists (or timeout)."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while not (run_dir / "exit").exists():
        if _time.monotonic() > deadline:
            break
        _time.sleep(0.05)


def test_worker_workdir_isolated_from_repo(tmp_path):
    """dispatch runs worker with cwd = --workdir, not the repo root.

    Uses a fake-exec shim that writes its cwd to stdout, then verifies
    the collected output matches tmp_path, not the repo root.
    """
    workdir = tmp_path / "worker_wd"
    workdir.mkdir()

    # Fake 'codex' binary that writes its own cwd to stdout as plain text.
    fake_bin_dir = tmp_path / "fake_bin"
    fake_bin_dir.mkdir()
    fake_codex = fake_bin_dir / "codex"
    fake_codex.write_text(
        "#!/bin/sh\n"
        'printf "%s" "$(pwd)"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_codex.chmod(fake_codex.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

    brief_file = _make_brief_file(tmp_path)

    rc, run_id = _dispatch_via_subprocess(tmp_path, workdir, fake_bin_dir, brief_file)
    assert rc == 0, f"dispatch failed: {run_id}"
    assert run_id, "dispatch must print a run-id"

    run_dir = workdir / ".agentic" / "teamrun" / run_id
    _wait_for_stdout(run_dir)

    stdout_text = (run_dir / "stdout").read_text(encoding="utf-8", errors="replace")
    # The cwd recorded by the fake codex must match workdir, not the repo root.
    assert str(workdir) in stdout_text, (
        f"worker cwd must be workdir {workdir}, got: {stdout_text!r}"
    )


# ---------------------------------------------------------------------------
# AC5: leaf-worker clause in brief
# ---------------------------------------------------------------------------

def test_worker_brief_contains_leaf_clause(tmp_path):
    """The brief passed to the worker is prepended with the leaf-worker clause.

    We verify that _LEAF_WORKER_CLAUSE text appears in the augmented brief
    that dispatch writes (by inspecting what the fake worker receives).
    """
    workdir = tmp_path / "worker_wd"
    workdir.mkdir()

    # Fake codex: argv is: codex exec <brief_text> --json ...
    # $2 is the brief text (1-indexed shell positional).
    fake_bin_dir = tmp_path / "fake_bin"
    fake_bin_dir.mkdir()
    fake_codex = fake_bin_dir / "codex"
    fake_codex.write_text(
        "#!/bin/sh\n"
        'printf "%s" "$2"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_codex.chmod(fake_codex.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

    original_brief = "Do the task."
    brief_file = _make_brief_file(tmp_path, original_brief)

    rc, run_id = _dispatch_via_subprocess(tmp_path, workdir, fake_bin_dir, brief_file)
    assert rc == 0, f"dispatch failed: {run_id}"

    run_dir = workdir / ".agentic" / "teamrun" / run_id
    _wait_for_stdout(run_dir)

    stdout_text = (run_dir / "stdout").read_text(encoding="utf-8", errors="replace")
    # The leaf-worker clause keywords must appear in what the worker received.
    assert "leaf worker" in stdout_text, (
        f"leaf-worker clause must appear in brief sent to worker, got: {stdout_text!r}"
    )
    assert "do not spawn sub-agents" in stdout_text, (
        "leaf-worker clause must include 'do not spawn sub-agents'"
    )


# ---------------------------------------------------------------------------
# AC8: collect output parsing
# ---------------------------------------------------------------------------

def test_collect_parses_gemini_json(tmp_path):
    """collect demuxes gemini --output-format json -> .response field."""
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "harness").write_text("gemini\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    payload = {"response": "Hello from gemini", "other": "ignored"}
    (run_dir / "stdout").write_text(json.dumps(payload), encoding="utf-8")

    result = _collect_output(run_dir, "gemini")
    assert result == "Hello from gemini", f"unexpected: {result!r}"


def test_collect_parses_codex_jsonl(tmp_path):
    """collect demuxes codex --json JSONL -> last event's message field."""
    run_dir = tmp_path / "run2"
    run_dir.mkdir()
    (run_dir / "harness").write_text("codex\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    jsonl = "\n".join([
        json.dumps({"type": "start", "message": ""}),
        json.dumps({"type": "delta", "message": "partial"}),
        json.dumps({"type": "done", "message": "Final codex answer"}),
    ])
    (run_dir / "stdout").write_text(jsonl, encoding="utf-8")

    result = _collect_output(run_dir, "codex")
    assert result == "Final codex answer", f"unexpected: {result!r}"


def test_collect_parses_cursor_json(tmp_path):
    """collect demuxes cursor-agent json -> .response field."""
    run_dir = tmp_path / "run3"
    run_dir.mkdir()
    (run_dir / "harness").write_text("cursor-agent\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    payload = {"response": "Cursor result here", "status": "ok"}
    (run_dir / "stdout").write_text(json.dumps(payload), encoding="utf-8")

    result = _collect_output(run_dir, "cursor-agent")
    assert result == "Cursor result here", f"unexpected: {result!r}"


def test_collect_parses_claude_json(tmp_path):
    """collect demuxes claude -p json -> .result or .message field."""
    run_dir = tmp_path / "run4"
    run_dir.mkdir()
    (run_dir / "harness").write_text("claude\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    payload = {"result": "Claude leaf worker response", "cost_usd": 0.001}
    (run_dir / "stdout").write_text(json.dumps(payload), encoding="utf-8")

    result = _collect_output(run_dir, "claude")
    assert result == "Claude leaf worker response", f"unexpected: {result!r}"


def test_collect_falls_back_to_raw_for_unknown_harness(tmp_path):
    """When harness is kimi/pi/omp (no JSON schema), raw stdout is returned."""
    run_dir = tmp_path / "run5"
    run_dir.mkdir()
    (run_dir / "harness").write_text("kimi\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    (run_dir / "stdout").write_text("Raw kimi output line\n", encoding="utf-8")

    result = _collect_output(run_dir, "kimi")
    assert "Raw kimi output line" in result


def test_collect_falls_back_to_raw_for_opencode(tmp_path):
    """opencode has no known JSON schema -> raw stdout returned."""
    run_dir = tmp_path / "run6"
    run_dir.mkdir()
    (run_dir / "harness").write_text("opencode\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    (run_dir / "stdout").write_text("Raw opencode output line\n", encoding="utf-8")

    result = _collect_output(run_dir, "opencode")
    assert "Raw opencode output line" in result


def test_collect_falls_back_to_raw_for_copilot(tmp_path):
    """copilot has no known JSON schema -> raw stdout returned."""
    run_dir = tmp_path / "run7"
    run_dir.mkdir()
    (run_dir / "harness").write_text("copilot\n", encoding="utf-8")
    (run_dir / "exit").write_text("0\n", encoding="utf-8")
    (run_dir / "stdout").write_text("Raw copilot output line\n", encoding="utf-8")

    result = _collect_output(run_dir, "copilot")
    assert "Raw copilot output line" in result


# ---------------------------------------------------------------------------
# run-id determinism note (for reviewer)
# ---------------------------------------------------------------------------
# _make_run_id uses a process-wide monotonic counter + os.getpid().
# Within one test process the counter increments 0, 1, 2, ... so consecutive
# calls produce different IDs without any clock dependency.
# Concurrent processes are disambiguated by pid.

def test_make_run_id_unique_within_process():
    """Consecutive run-ids within the same process are distinct."""
    ids = [_make_run_id("engineer") for _ in range(5)]
    assert len(set(ids)) == 5, f"run-ids must be unique, got: {ids}"


def test_make_run_id_contains_role():
    """run-id contains the role name for human readability."""
    rid = _make_run_id("qa-engineer")
    assert "qa-engineer" in rid, f"role not in run-id: {rid!r}"


# ===========================================================================
# New tests: reaper, killpg watchdog, mkdir guard, run-id urandom suffix
# ===========================================================================

def test_reaper_writes_exit_zero_on_success(tmp_path):
    """AC3 regression: worker exiting 0 -> exit file = '0', status = done.

    A fake codex that exits 0 must result in:
      - exit file containing '0'
      - _run_status returning 'done'
      - collect returning exit code 0
    """
    workdir = tmp_path / "worker_wd"
    workdir.mkdir()

    # _make_fake_exec produces a binary that prints stdout_payload and exits 0.
    fake_bin_dir = _make_fake_exec(tmp_path, "codex", '{"result":"ok"}')
    brief_file = _make_brief_file(tmp_path)

    rc, run_id = _dispatch_via_subprocess(tmp_path, workdir, fake_bin_dir, brief_file)
    assert rc == 0, f"dispatch failed: {run_id}"

    run_dir = workdir / ".agentic" / "teamrun" / run_id
    _wait_for_exit_file(run_dir, timeout=5.0)

    assert (run_dir / "exit").exists(), "exit file must be written by reaper"
    exit_val = (run_dir / "exit").read_text(encoding="utf-8").strip()
    assert exit_val == "0", f"exit file must contain '0' for a successful worker, got {exit_val!r}"

    status = _run_status(run_dir)
    assert status == "done", f"_run_status must return 'done' for exit=0, got {status!r}"


def test_reaper_writes_exit_nonzero_on_failure(tmp_path):
    """AC3 regression: worker exiting 3 -> exit file = '3', status = failed."""
    workdir = tmp_path / "worker_wd"
    workdir.mkdir()

    # Fake codex that exits with code 3.
    fake_bin_dir = tmp_path / "fake_bin_fail"
    fake_bin_dir.mkdir()
    fake_binary = fake_bin_dir / "codex"
    fake_binary.write_text(
        "#!/bin/sh\n"
        'printf "%s" "error output"\n'
        "exit 3\n",
        encoding="utf-8",
    )
    fake_binary.chmod(fake_binary.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

    brief_file = _make_brief_file(tmp_path)

    rc, run_id = _dispatch_via_subprocess(tmp_path, workdir, fake_bin_dir, brief_file)
    assert rc == 0, f"dispatch failed: {run_id}"

    run_dir = workdir / ".agentic" / "teamrun" / run_id
    _wait_for_exit_file(run_dir, timeout=5.0)

    assert (run_dir / "exit").exists(), "exit file must be written by reaper"
    exit_val = (run_dir / "exit").read_text(encoding="utf-8").strip()
    assert exit_val == "3", f"exit file must contain '3' for worker exiting 3, got {exit_val!r}"

    status = _run_status(run_dir)
    assert status == "failed", f"_run_status must return 'failed' for exit=3, got {status!r}"


def test_collect_exit_code_reflects_worker_success(tmp_path, capsys):
    """collect returns exit 0 when worker succeeded (exit file = 0)."""
    import argparse as _argparse
    workdir = tmp_path / "worker_wd"
    workdir.mkdir()

    fake_bin_dir = _make_fake_exec(tmp_path, "codex", '{"result":"hello"}')
    brief_file = _make_brief_file(tmp_path)

    rc, run_id = _dispatch_via_subprocess(tmp_path, workdir, fake_bin_dir, brief_file)
    assert rc == 0, f"dispatch failed: {run_id}"

    run_dir = workdir / ".agentic" / "teamrun" / run_id
    _wait_for_exit_file(run_dir, timeout=5.0)

    # Build a minimal args namespace for _cmd_collect.
    args = _argparse.Namespace(run_id=run_id, workdir=str(workdir))
    collect_rc = _mod._cmd_collect(args)
    assert collect_rc == 0, f"collect must return 0 for a successful run, got {collect_rc}"


def test_watchdog_uses_killpg(tmp_path, monkeypatch):
    """MAJOR regression: _cursor_watchdog calls os.killpg, not proc.kill().

    We verify by monkeypatching os.killpg and confirming it is called when
    the watchdog fires a timeout, and that exit=124 is written.
    """
    import subprocess as _sp
    import time as _time

    run_dir = tmp_path / "run_watchdog"
    run_dir.mkdir()

    killpg_calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    monkeypatch.setattr(_mod._os if hasattr(_mod, "_os") else _os, "killpg", fake_killpg, raising=False)
    # Also patch on the os module that agentic-team imported at load time.
    import os as _real_os
    original_killpg = _real_os.killpg
    _real_os.killpg = fake_killpg  # type: ignore[assignment]

    try:
        # Spawn a real long-running process so proc.pid and pgid are valid.
        proc = _sp.Popen(
            ["sleep", "60"],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            start_new_session=True,
        )
        timed_out_flag: list[bool] = [False]
        # Use timeout=0 so the watchdog fires immediately.
        _mod._cursor_watchdog(proc, timeout=0, run_dir=run_dir, timed_out_flag=timed_out_flag)

        # Give the watchdog thread time to fire.
        deadline = _time.monotonic() + 3.0
        while not (run_dir / "exit").exists() and _time.monotonic() < deadline:
            _time.sleep(0.05)

        # Clean up the process in case killpg was bypassed.
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    finally:
        _real_os.killpg = original_killpg  # type: ignore[assignment]

    assert killpg_calls, "os.killpg must be called by the watchdog on timeout"
    assert timed_out_flag[0] is True, "timed_out_flag must be set by watchdog"
    assert (run_dir / "exit").exists(), "watchdog must write exit file"
    exit_val = (run_dir / "exit").read_text(encoding="utf-8").strip()
    assert exit_val == "124", f"watchdog must write exit=124, got {exit_val!r}"


def test_dispatch_mkdir_guard_unwritable_parent(tmp_path, monkeypatch):
    """mkdir guard: unwritable workdir exits non-zero with error message, no traceback."""
    import argparse as _argparse

    workdir = tmp_path / "worker_wd"
    workdir.mkdir()
    brief_file = _make_brief_file(tmp_path)

    # Make run_dir.mkdir raise OSError to simulate unwritable workdir.
    original_mkdir = Path.mkdir

    def patched_mkdir(self: Path, *args, **kwargs):  # type: ignore[override]
        if "teamrun" in str(self):
            raise OSError("Permission denied (simulated)")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", patched_mkdir)

    args = _argparse.Namespace(
        harness="codex",
        role="engineer",
        brief=str(brief_file),
        workdir=str(workdir),
    )
    rc = _mod._cmd_dispatch(args)
    assert rc != 0, "dispatch must return non-zero on unwritable workdir"


def test_run_id_contains_urandom_suffix():
    """run-id contains a 4-char hex urandom suffix (pid-reuse tiebreaker)."""
    rid = _make_run_id("engineer")
    # Format: <role>-<counter>-<pid>-<4hex>
    parts = rid.split("-")
    # Last part must be 4 hex chars.
    assert len(parts) >= 4, f"run-id must have at least 4 dash-separated parts, got: {rid!r}"
    suffix = parts[-1]
    assert len(suffix) == 4, f"urandom suffix must be 4 hex chars, got {suffix!r}"
    assert all(c in "0123456789abcdef" for c in suffix), (
        f"urandom suffix must be lowercase hex, got {suffix!r}"
    )


# ===========================================================================
# Unit 3+4 - M2b model routing + M2a sibling-gated .active unlink
# ===========================================================================

_is_live_readonly = _mod._is_live_readonly
_MODEL_FLAG_HARNESSES = _mod._MODEL_FLAG_HARNESSES


# --- M2b argv: model appended at END, brief positional NOT displaced ---------

def test_model_appended_codex_argv_end():
    """(a) codex argv ends with ['-m', 'X']; (d) brief stays at original index."""
    base = _build_worker_argv("codex", "BRIEF")
    argv = _build_worker_argv("codex", "BRIEF", model="X")
    assert argv[-2:] == ["-m", "X"], f"codex must end with -m X, got {argv!r}"
    # brief positional index unchanged vs the no-model build
    assert argv.index("BRIEF") == base.index("BRIEF")
    assert argv[:len(base)] == base, "no-model prefix must be byte-identical"


def test_model_appended_gemini_argv_end():
    """(b) gemini argv ends with ['-m', 'X']; (d) brief not displaced."""
    base = _build_worker_argv("gemini", "BRIEF")
    argv = _build_worker_argv("gemini", "BRIEF", model="X")
    assert argv[-2:] == ["-m", "X"], f"gemini must end with -m X, got {argv!r}"
    assert argv.index("BRIEF") == base.index("BRIEF")
    assert argv[:len(base)] == base


def test_model_appended_claude_argv_end():
    """(c) claude argv ends with ['--model', 'X']; (d) brief not displaced."""
    base = _build_worker_argv("claude", "BRIEF")
    argv = _build_worker_argv("claude", "BRIEF", model="X")
    assert argv[-2:] == ["--model", "X"], f"claude must end with --model X, got {argv!r}"
    assert argv.index("BRIEF") == base.index("BRIEF")
    assert argv[:len(base)] == base


def test_model_appended_opencode_argv_end():
    """opencode argv ends with ['--model', 'X']; brief not displaced."""
    base = _build_worker_argv("opencode", "BRIEF")
    argv = _build_worker_argv("opencode", "BRIEF", model="X")
    assert argv[-2:] == ["--model", "X"], f"opencode must end with --model X, got {argv!r}"
    assert argv.index("BRIEF") == base.index("BRIEF")
    assert argv[:len(base)] == base


def test_model_appended_copilot_argv_end():
    """copilot argv ends with ['--model', 'X']; brief not displaced."""
    base = _build_worker_argv("copilot", "BRIEF")
    argv = _build_worker_argv("copilot", "BRIEF", model="X")
    assert argv[-2:] == ["--model", "X"], f"copilot must end with --model X, got {argv!r}"
    assert argv.index("BRIEF") == base.index("BRIEF")
    assert argv[:len(base)] == base


def test_no_model_argv_unchanged():
    """(f) no model -> argv identical to pre-change behavior (no model flag)."""
    for harness in (
        "codex", "gemini", "claude", "cursor-agent", "kimi", "pi", "omp",
        "opencode", "copilot",
    ):
        argv = _build_worker_argv(harness, "BRIEF")
        assert "-m" not in argv, f"{harness}: no -m when model is None"
        assert "--model" not in argv, f"{harness}: no --model when model is None"
    # explicit model=None is the same as omitting it
    assert _build_worker_argv("codex", "BRIEF") == _build_worker_argv("codex", "BRIEF", model=None)
    # falsy empty string must not append either
    assert _build_worker_argv("codex", "BRIEF", model="") == _build_worker_argv("codex", "BRIEF")


# --- M2b fail-fast: reject --model for non-confirmed harness, no side effect --

def test_dispatch_model_rejected_for_kimi_no_side_effect(tmp_path, monkeypatch, capsys):
    """(e) dispatch --model X --harness kimi -> exit 2, reject message, no run
    dir created, no subprocess spawned."""
    import argparse as _argparse

    workdir = tmp_path / "wd"
    workdir.mkdir()
    brief_file = _make_brief_file(tmp_path)
    teamrun = workdir / ".agentic" / "teamrun"

    # Prove no subprocess is spawned: any Popen call is a hard failure.
    def _no_popen(*a, **k):
        raise AssertionError("subprocess.Popen must NOT be called on a rejected dispatch")

    monkeypatch.setattr(_mod.subprocess, "Popen", _no_popen)

    args = _argparse.Namespace(
        harness="kimi", role="engineer",
        brief=str(brief_file), workdir=str(workdir), model="some-model",
    )
    rc = _mod._cmd_dispatch(args)
    assert rc == 2, f"rejected dispatch must return 2, got {rc}"
    err = capsys.readouterr().err
    assert "--model is not supported for harness 'kimi'" in err
    assert "codex" in err and "gemini" in err and "claude" in err
    # No filesystem side effect: teamrun dir never created (fail-fast precedes mkdir).
    assert not teamrun.exists(), "no run dir / teamrun tree may be created on reject"
    assert _MODEL_FLAG_HARNESSES == frozenset(
        {"codex", "gemini", "claude", "opencode", "copilot"}
    )


# --- M2a: sibling-gated .active unlink ---------------------------------------

def _make_terminal_run(teamrun: Path, run_id: str, exit_code: str = "0") -> Path:
    """Create a terminal (exit-file present) sibling run dir."""
    rd = teamrun / run_id
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "exit").write_text(exit_code + "\n", encoding="utf-8")
    (rd / "harness").write_text("codex\n", encoding="utf-8")
    (rd / "stdout").write_text("done\n", encoding="utf-8")
    return rd


def _make_live_run(teamrun: Path, run_id: str) -> Path:
    """Create a 'live' sibling: pid file pointing at THIS process, no exit file."""
    rd = teamrun / run_id
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "pid").write_text(str(_os.getpid()) + "\n", encoding="utf-8")
    (rd / "harness").write_text("codex\n", encoding="utf-8")
    (rd / "stdout").write_text("running\n", encoding="utf-8")
    return rd


def test_collect_unlinks_active_when_all_siblings_terminal(tmp_path):
    """(g) two terminal sibling runs -> collect on one unlinks .active."""
    import argparse as _argparse
    workdir = tmp_path / "wd"
    teamrun = workdir / ".agentic" / "teamrun"
    teamrun.mkdir(parents=True)
    (teamrun / ".active").write_text(str(_os.getpid()) + "\n", encoding="utf-8")

    _make_terminal_run(teamrun, "engineer-0001-x")
    target = _make_terminal_run(teamrun, "engineer-0002-y")

    args = _argparse.Namespace(run_id="engineer-0002-y", workdir=str(workdir))
    rc = _mod._cmd_collect(args)
    assert rc == 0
    assert not (teamrun / ".active").exists(), ".active must be unlinked when no sibling is live"


def test_collect_leaves_active_when_sibling_live(tmp_path):
    """(h) one live sibling (pid alive, no exit) -> collect LEAVES .active."""
    import argparse as _argparse
    workdir = tmp_path / "wd"
    teamrun = workdir / ".agentic" / "teamrun"
    teamrun.mkdir(parents=True)
    (teamrun / ".active").write_text(str(_os.getpid()) + "\n", encoding="utf-8")

    _make_live_run(teamrun, "engineer-live-1")  # pid = us, alive, no exit file
    _make_terminal_run(teamrun, "engineer-0002-y")

    args = _argparse.Namespace(run_id="engineer-0002-y", workdir=str(workdir))
    rc = _mod._cmd_collect(args)
    assert rc == 0
    assert (teamrun / ".active").exists(), ".active must remain while a sibling is live"


def test_collect_sibling_scan_writes_no_exit_files(tmp_path):
    """(i) the sibling liveness scan creates no 'exit' files in sibling dirs."""
    import argparse as _argparse
    workdir = tmp_path / "wd"
    teamrun = workdir / ".agentic" / "teamrun"
    teamrun.mkdir(parents=True)
    (teamrun / ".active").write_text(str(_os.getpid()) + "\n", encoding="utf-8")

    # Sibling with a DEAD pid and NO exit file: _run_status would write exit=1,
    # but the read-only _is_live_readonly path must NOT.
    dead = teamrun / "engineer-dead-1"
    dead.mkdir(parents=True)
    (dead / "pid").write_text("999999\n", encoding="utf-8")  # almost-certainly-dead pid
    (dead / "harness").write_text("codex\n", encoding="utf-8")
    assert not (dead / "exit").exists()

    target = _make_terminal_run(teamrun, "engineer-0002-y")
    args = _argparse.Namespace(run_id="engineer-0002-y", workdir=str(workdir))
    rc = _mod._cmd_collect(args)
    assert rc == 0
    assert not (dead / "exit").exists(), "sibling scan must NOT write exit files (read-only)"
    # dead sibling not live -> .active unlinked
    assert not (teamrun / ".active").exists()


def test_is_live_readonly_pure():
    """_is_live_readonly: live pid -> True; exit file present -> False; never writes."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        rd = Path(d)
        (rd / "pid").write_text(str(_os.getpid()) + "\n", encoding="utf-8")
        assert _is_live_readonly(rd) is True
        # exit file present -> terminal -> not live, regardless of pid
        (rd / "exit").write_text("0\n", encoding="utf-8")
        assert _is_live_readonly(rd) is False


# ===========================================================================
# Unit 1 configure subcommand tests (migrated from test_agentic_configure.py)
# Monkeypatching seam: _discover_harnesses (replaces the old _run_discover).
# ===========================================================================

import tempfile as _tempfile

# Pull configure symbols from the already-loaded agentic-team module.
_cmd_configure = _mod._cmd_configure
_emit_team_yaml = _mod._emit_team_yaml
_rank_assignments = _mod._rank_assignments
_score_model_for_role = _mod._score_model_for_role
_TEAM_CAPABILITY_TABLE = _mod._TEAM_CAPABILITY_TABLE


def test_configure_team_noninteractive_writes_block(tmp_path):
    """--non-interactive --assign pairs produce a valid team.yml block."""
    target = tmp_path / ".agentic" / "team.yml"
    rc = main([
        "configure",
        "--non-interactive",
        "--assign", "engineer=codex:gpt-5.3-codex",
        "--assign", "skeptic=cursor-agent:gpt-5",
        "--default-harness", "codex",
        "--path", str(target),
    ])
    assert rc == 0, f"expected exit 0, got {rc}"
    assert target.is_file(), "team.yml must be written"
    text = target.read_text()
    assert "engineer:" in text
    assert "harness: codex" in text
    assert "model: gpt-5.3-codex" in text
    assert "skeptic:" in text
    assert "harness: cursor-agent" in text
    assert "default_harness: codex" in text
    assert "enabled: true" in text
    assert "dispatch:" in text


def test_configure_team_noninteractive_unknown_harness_fails(tmp_path):
    """--assign with unknown harness must exit 2 and write nothing."""
    target = tmp_path / "team.yml"
    rc = main([
        "configure",
        "--non-interactive",
        "--assign", "engineer=badharness:somemodel",
        "--path", str(target),
    ])
    assert rc == 2
    assert not target.exists(), "no file must be written on validation error"


def test_configure_team_noninteractive_requires_assign(tmp_path):
    """--non-interactive with no --assign must exit 2."""
    target = tmp_path / "team.yml"
    rc = main([
        "configure",
        "--non-interactive",
        "--path", str(target),
    ])
    assert rc == 2


def test_configure_team_emit_yaml_structure():
    """_emit_team_yaml produces correct YAML structure."""
    assignments = {
        "engineer": ("codex", "gpt-5.3-codex"),
        "skeptic": ("cursor-agent", ""),
    }
    out = _emit_team_yaml(assignments, "codex")
    assert "enabled: true" in out
    assert "default_harness: codex" in out
    assert "engineer:" in out
    assert "    harness: codex" in out
    assert "    model: gpt-5.3-codex" in out
    assert "  skeptic: cursor-agent" in out  # scalar form when no model
    assert "dispatch:" in out
    assert "timeout_seconds: 1800" in out
