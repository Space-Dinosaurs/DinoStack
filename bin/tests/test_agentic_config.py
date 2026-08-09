#!/usr/bin/env python3
"""
Tests for bin/agentic-config.

Covers:
  - _upsert_global_json: create-when-parent-absent, update-preserving-others,
    idempotent, mode 0o644, set_at written, bool/int JSON types
  - _upsert_project_config: create-when-parent-absent, update-preserving-others,
    idempotent, mode 0o644, bool/int JSON types, ticket_driven not injected
  - _upsert_agents_md_marker: replace-in-place, append-when-absent,
    other-marker-untouched, idempotent, mode 0o644,
    non-repo-cwd exit 2, git-root seeds AGENTS.md
  - main() validation: unknown setting exit 2, bad value exit 2,
    qa_default_skip exit 0, preset exit 2, not-writable exit 2,
    bad scope exit 2, missing args exit 2
  - Write round-trips re-read via _load_config or direct parse for
    each setting group (activation, profile, config.json bools/ints/enums)
  - opt-in footgun warning printed

Run with: pytest bin/tests/test_agentic_config.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load bin/agentic-config via SourceFileLoader (hyphen-named binary)
# (same pattern as test_agentic_status.py:23-42)
# ---------------------------------------------------------------------------

_BIN_PATH = Path(__file__).parent.parent / "agentic-config"
_loader = importlib.machinery.SourceFileLoader("agentic_config", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_config", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-config from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# Public surface under test
main = _mod.main
_upsert_global_json = _mod._upsert_global_json
_upsert_project_config = _mod._upsert_project_config
_upsert_agents_md_marker = _mod._upsert_agents_md_marker
_is_git_root = _mod._is_git_root
_parse_bool = _mod._parse_bool
_parse_int = _mod._parse_int

# Also import _load_config from agentic-status (for round-trip tests).
_STATUS_PATH = Path(__file__).parent.parent / "agentic-status"
_s_loader = importlib.machinery.SourceFileLoader("agentic_status_rt", str(_STATUS_PATH))
_s_spec = importlib.util.spec_from_loader("agentic_status_rt", _s_loader)
_s_mod = importlib.util.module_from_spec(_s_spec)
_s_loader.exec_module(_s_mod)
_load_config = _s_mod._load_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_mode(path: Path) -> int:
    """Return the permission bits of path."""
    return stat.S_IMODE(os.stat(path).st_mode)


# ---------------------------------------------------------------------------
# _upsert_global_json
# ---------------------------------------------------------------------------

class TestUpsertGlobalJson:
    def test_creates_file_and_parent_when_absent(self, tmp_path, monkeypatch):
        """Creates ~/.claude/ dir and the JSON file when neither exists."""
        fake_home = tmp_path / "home"
        fake_config = fake_home / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = _upsert_global_json("mode", "opt-out")
        assert result == fake_config
        assert fake_config.is_file()
        data = json.loads(fake_config.read_text())
        assert data["mode"] == "opt-out"
        assert "set_at" in data

    def test_mode_0o644(self, tmp_path, monkeypatch):
        """Written file has mode 0o644."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        _upsert_global_json("mode", "opt-out")
        assert _file_mode(fake_config) == 0o644

    def test_preserves_other_keys(self, tmp_path, monkeypatch):
        """Only updates the target key + set_at; leaves other keys untouched."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        fake_config.parent.mkdir(parents=True)
        fake_config.write_text(json.dumps({"mode": "opt-out", "profile": "strict", "extra": "keep"}))
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        _upsert_global_json("profile", "relaxed")
        data = json.loads(fake_config.read_text())
        assert data["profile"] == "relaxed"
        assert data["mode"] == "opt-out"
        assert data["extra"] == "keep"
        assert "set_at" in data

    def test_idempotent(self, tmp_path, monkeypatch):
        """Writing the same value twice produces the same result."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        _upsert_global_json("mode", "opt-out")
        first = json.loads(fake_config.read_text())
        _upsert_global_json("mode", "opt-out")
        second = json.loads(fake_config.read_text())
        assert first["mode"] == second["mode"]

    def test_set_at_written(self, tmp_path, monkeypatch):
        """set_at is always updated on write."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        _upsert_global_json("mode", "opt-in")
        data = json.loads(fake_config.read_text())
        assert "set_at" in data
        # ISO8601 format check (basic)
        assert "T" in data["set_at"]
        assert "Z" in data["set_at"]

    def test_bool_written_as_json_bool(self, tmp_path, monkeypatch):
        """Boolean values are stored as JSON true/false, not strings."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        _upsert_global_json("some_flag", True)
        raw = fake_config.read_text()
        data = json.loads(raw)
        assert data["some_flag"] is True
        assert "true" in raw  # JSON true, not "true" string

    def test_malformed_json_raises_validation_error(self, tmp_path, monkeypatch):
        """Malformed existing JSON raises _ValidationError; file is NOT overwritten."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        fake_config.parent.mkdir(parents=True)
        original = "not valid json {{{{"
        fake_config.write_text(original)
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        with pytest.raises(_mod._ValidationError, match="malformed"):
            _upsert_global_json("mode", "opt-out")
        # File must NOT have been overwritten.
        assert fake_config.read_text() == original


# ---------------------------------------------------------------------------
# _upsert_project_config
# ---------------------------------------------------------------------------

class TestUpsertProjectConfig:
    def test_creates_agentic_dir_when_absent(self, tmp_path, monkeypatch):
        """Creates .agentic/ directory when it does not exist."""
        monkeypatch.chdir(tmp_path)
        path = _upsert_project_config("abdication_guard_enabled", True)
        assert path.resolve() == (tmp_path / ".agentic" / "config.json").resolve()
        assert path.is_file()

    def test_mode_0o644(self, tmp_path, monkeypatch):
        """Written file has mode 0o644."""
        monkeypatch.chdir(tmp_path)
        path = _upsert_project_config("commit_telemetry", False)
        assert _file_mode(path) == 0o644

    def test_preserves_other_keys(self, tmp_path, monkeypatch):
        """Only the target key is updated; other keys remain unchanged."""
        monkeypatch.chdir(tmp_path)
        agentic = tmp_path / ".agentic"
        agentic.mkdir()
        cfg = agentic / "config.json"
        cfg.write_text(json.dumps({"debugger_on_failure": True, "theme_aware": False}))

        _upsert_project_config("commit_telemetry", True)
        data = json.loads(cfg.read_text())
        assert data["commit_telemetry"] is True
        assert data["debugger_on_failure"] is True
        assert data["theme_aware"] is False

    def test_idempotent(self, tmp_path, monkeypatch):
        """Writing the same value twice produces the same JSON output."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("storybook_version", 6)
        first = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        _upsert_project_config("storybook_version", 6)
        second = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert first["storybook_version"] == second["storybook_version"]

    def test_bool_stored_as_json_bool(self, tmp_path, monkeypatch):
        """Booleans are written as JSON true/false, not strings."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("skill_candidate_detection", False)
        raw = (tmp_path / ".agentic" / "config.json").read_text()
        assert "false" in raw
        data = json.loads(raw)
        assert data["skill_candidate_detection"] is False

    def test_int_stored_as_json_int(self, tmp_path, monkeypatch):
        """Integers are written as JSON numbers, not strings."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("deferred_wrap_idle_minutes", 30)
        raw = (tmp_path / ".agentic" / "config.json").read_text()
        data = json.loads(raw)
        assert data["deferred_wrap_idle_minutes"] == 30
        assert isinstance(data["deferred_wrap_idle_minutes"], int)

    def test_ticket_driven_not_present_by_default(self, tmp_path, monkeypatch):
        """ticket_driven is not injected unless the user explicitly sets it."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("commit_telemetry", True)
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert "ticket_driven" not in data

    def test_ticket_driven_written_when_set(self, tmp_path, monkeypatch):
        """ticket_driven is written when explicitly passed."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("ticket_driven", "offer")
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["ticket_driven"] == "offer"

    def test_storybook_version_stored_as_int(self, tmp_path, monkeypatch):
        """storybook_version is stored as an integer, not a string."""
        monkeypatch.chdir(tmp_path)
        _upsert_project_config("storybook_version", 7)
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["storybook_version"] == 7
        assert isinstance(data["storybook_version"], int)

    def test_malformed_json_raises_validation_error(self, tmp_path, monkeypatch):
        """Malformed existing config.json raises _ValidationError; file is NOT overwritten."""
        monkeypatch.chdir(tmp_path)
        agentic = tmp_path / ".agentic"
        agentic.mkdir()
        original = "{ broken"
        (agentic / "config.json").write_text(original)

        with pytest.raises(_mod._ValidationError, match="malformed"):
            _upsert_project_config("debugger_on_failure", True)
        # File must NOT have been overwritten.
        assert (agentic / "config.json").read_text() == original


# ---------------------------------------------------------------------------
# _upsert_agents_md_marker
# ---------------------------------------------------------------------------

class TestUpsertAgentsMdMarker:
    def _make_agents_md(self, tmp_path, content: str) -> Path:
        p = tmp_path / "AGENTS.md"
        p.write_text(content)
        return p

    def test_replace_activation_marker_in_place(self, tmp_path, monkeypatch):
        """Replaces existing dinostack: line without touching others."""
        md = self._make_agents_md(
            tmp_path,
            "# Project\nagentic-engineering: opt-out\nsome other line\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("activation", "opt-in")
        content = md.read_text()
        assert "agentic-engineering: opt-in" in content
        assert "agentic-engineering: opt-out" not in content
        assert "some other line" in content

    def test_append_activation_marker_when_absent(self, tmp_path, monkeypatch):
        """Appends activation marker when none exists."""
        md = self._make_agents_md(tmp_path, "# No markers here\n")
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("activation", "opt-out")
        content = md.read_text()
        assert "agentic-engineering: opt-out" in content
        assert "# No markers here" in content

    def test_replace_profile_marker_in_place(self, tmp_path, monkeypatch):
        """Replaces existing agentic-engineering-profile: line."""
        md = self._make_agents_md(
            tmp_path,
            "agentic-engineering: opt-in\nagentic-engineering-profile: relaxed\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("profile", "strict")
        content = md.read_text()
        assert "agentic-engineering-profile: strict" in content
        assert "agentic-engineering-profile: relaxed" not in content
        # Other marker untouched.
        assert "agentic-engineering: opt-in" in content

    def test_append_profile_marker_when_absent(self, tmp_path, monkeypatch):
        """Appends profile marker when none exists; leaves activation untouched."""
        md = self._make_agents_md(
            tmp_path,
            "agentic-engineering: opt-in\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("profile", "default")
        content = md.read_text()
        assert "agentic-engineering-profile: default" in content
        assert "agentic-engineering: opt-in" in content

    def test_other_marker_untouched_on_activation_write(self, tmp_path, monkeypatch):
        """Writing activation does not modify the profile marker line."""
        md = self._make_agents_md(
            tmp_path,
            "agentic-engineering: opt-out\nagentic-engineering-profile: strict\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("activation", "opt-in")
        content = md.read_text()
        assert "agentic-engineering-profile: strict" in content

    def test_other_marker_untouched_on_profile_write(self, tmp_path, monkeypatch):
        """Writing profile does not modify the activation marker line."""
        md = self._make_agents_md(
            tmp_path,
            "agentic-engineering: opt-out\nagentic-engineering-profile: relaxed\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("profile", "default")
        content = md.read_text()
        assert "agentic-engineering: opt-out" in content

    def test_idempotent(self, tmp_path, monkeypatch):
        """Writing the same marker twice yields identical file content."""
        md = self._make_agents_md(
            tmp_path,
            "agentic-engineering: opt-in\n",
        )
        monkeypatch.chdir(tmp_path)
        _upsert_agents_md_marker("activation", "opt-in")
        first = md.read_text()
        _upsert_agents_md_marker("activation", "opt-in")
        second = md.read_text()
        assert first == second

    def test_mode_0o644(self, tmp_path, monkeypatch):
        """Written AGENTS.md has mode 0o644."""
        self._make_agents_md(tmp_path, "# Project\n")
        monkeypatch.chdir(tmp_path)
        path = _upsert_agents_md_marker("activation", "opt-out")
        assert _file_mode(path) == 0o644

    def test_non_repo_cwd_no_agents_md_exits_2(self, tmp_path, monkeypatch):
        """Exit 2 when no AGENTS.md and cwd is not a git root."""
        # tmp_path has no .git entry -> not a git root.
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            _upsert_agents_md_marker("activation", "opt-in")
        assert exc_info.value.code == 2

    def test_git_root_without_agents_md_creates_it(self, tmp_path, monkeypatch):
        """Creates AGENTS.md when cwd is a git root and no AGENTS.md exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)
        path = _upsert_agents_md_marker("activation", "opt-in")
        assert path == tmp_path / "AGENTS.md"
        assert "agentic-engineering: opt-in" in path.read_text()

    def test_preserves_trailing_newline(self, tmp_path, monkeypatch):
        """File ends with exactly one newline after write."""
        self._make_agents_md(tmp_path, "# Header\n")
        monkeypatch.chdir(tmp_path)
        path = _upsert_agents_md_marker("profile", "relaxed")
        content = path.read_text()
        assert content.endswith("\n")
        assert not content.endswith("\n\n")


# ---------------------------------------------------------------------------
# main() validation
# ---------------------------------------------------------------------------

class TestMainValidation:
    def test_unknown_setting_exits_2(self, tmp_path, monkeypatch, capsys):
        """Unknown setting name -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "nonexistent_setting", "true"])
        assert result == 2

    def test_bad_bool_value_exits_2(self, tmp_path, monkeypatch, capsys):
        """Invalid value for a bool setting -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "abdication_guard_enabled", "maybe"])
        assert result == 2

    def test_bad_enum_value_exits_2(self, tmp_path, monkeypatch, capsys):
        """Invalid enum value -> exit 2."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(_mod, "CONFIG_PATH", tmp_path / ".claude" / "agentic-engineering.json")
        result = main(["agentic-config", "mode", "partially-on"])
        assert result == 2

    def test_qa_default_skip_exits_0(self, tmp_path, monkeypatch, capsys):
        """qa_default_skip is reserved/inert -> exit 0 with notice."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "qa_default_skip", "docs-only"])
        assert result == 0
        out = capsys.readouterr().out
        assert "reserved" in out or "inert" in out

    def test_preset_exits_2(self, tmp_path, monkeypatch, capsys):
        """preset is removed -> exit 2 with DS-48 message."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "preset", "lean"])
        assert result == 2
        err = capsys.readouterr().err
        assert "DS-48" in err or "profile" in err

    def test_not_writable_setting_exits_2(self, tmp_path, monkeypatch, capsys):
        """scaffolding_version is not writable -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "scaffolding_version", "2"])
        assert result == 2

    def test_bad_scope_exits_2(self, tmp_path, monkeypatch, capsys):
        """Invalid --scope value -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "mode", "opt-out", "--scope", "universe"])
        assert result == 2

    def test_missing_args_exits_2(self, tmp_path, monkeypatch, capsys):
        """Too few positional args -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "mode"])
        assert result == 2

    def test_no_args_exits_2(self, tmp_path, monkeypatch, capsys):
        """No args at all -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config"])
        assert result == 2

    def test_storybook_url_not_writable_exits_2(self, tmp_path, monkeypatch, capsys):
        """storybook_url is not writable -> exit 2."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "storybook_url", "http://localhost:6006"])
        assert result == 2


# ---------------------------------------------------------------------------
# Write round-trips
# ---------------------------------------------------------------------------

class TestWriteRoundTrips:
    """One round-trip per setting group, re-read via _load_config or direct parse."""

    def test_mode_round_trip(self, tmp_path, monkeypatch):
        """Write mode=opt-out then read back via _load_config."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        monkeypatch.setattr(_s_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "mode", "opt-out"])
        assert result == 0
        config, status = _load_config()
        assert status == "found"
        assert config["mode"] == "opt-out"

    def test_profile_global_round_trip(self, tmp_path, monkeypatch):
        """Write profile=strict --scope global then read via _load_config."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        monkeypatch.setattr(_s_mod, "CONFIG_PATH", fake_config)
        # Provide a git root so auto-detection picks "project" unless overridden.
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# repo\n")

        result = main(["agentic-config", "profile", "strict", "--scope", "global"])
        assert result == 0
        config, status = _load_config()
        assert config.get("profile") == "strict"

    def test_profile_project_round_trip(self, tmp_path, monkeypatch):
        """Write profile=relaxed --scope project then read back from AGENTS.md."""
        monkeypatch.chdir(tmp_path)
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# repo\nagentic-engineering: opt-in\n")
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "profile", "relaxed", "--scope", "project"])
        assert result == 0
        content = agents_md.read_text()
        assert "agentic-engineering-profile: relaxed" in content

    def test_bool_config_round_trip(self, tmp_path, monkeypatch):
        """Write abdication_guard_enabled=true then read back as JSON bool."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "abdication_guard_enabled", "true"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["abdication_guard_enabled"] is True

    def test_int_config_round_trip(self, tmp_path, monkeypatch):
        """Write deferred_wrap_idle_minutes=45 then read back as JSON int."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "deferred_wrap_idle_minutes", "45"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["deferred_wrap_idle_minutes"] == 45
        assert isinstance(data["deferred_wrap_idle_minutes"], int)

    def test_enum_config_round_trip(self, tmp_path, monkeypatch):
        """Write model_profile=budget then read back as string."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "model_profile", "budget"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["model_profile"] == "budget"

    def test_ticket_driven_round_trip(self, tmp_path, monkeypatch):
        """Write ticket_driven=require then read back; not injected without set."""
        monkeypatch.chdir(tmp_path)
        # First write another key - ticket_driven must NOT appear.
        main(["agentic-config", "commit_telemetry", "true"])
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert "ticket_driven" not in data
        # Now explicitly set it.
        result = main(["agentic-config", "ticket_driven", "require"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["ticket_driven"] == "require"

    def test_storybook_version_round_trip(self, tmp_path, monkeypatch):
        """Write storybook_version=7 then read back as int."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "storybook_version", "7"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["storybook_version"] == 7
        assert isinstance(data["storybook_version"], int)

    def test_rework_detection_round_trip(self, tmp_path, monkeypatch):
        """Write rework_detection=false via the CLI then read back as JSON bool.

        Regression test for a Skeptic Major finding on PR #484: rework_detection
        was documented in four places as disable-able via "a single toggle" but
        was never added to the _SETTINGS whitelist, so the CLI rejected it with
        "unknown setting 'rework_detection'". Confirmed failing pre-fix: this
        test raised SystemExit(2) from _cmd_set's unknown-setting branch before
        the _SETTINGS entry was added.
        """
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "rework_detection", "false"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["rework_detection"] is False

    def test_capability_preflight_mode_round_trip(self, tmp_path, monkeypatch):
        """Write capability_preflight_mode=blocking then read back."""
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "capability_preflight_mode", "blocking"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["capability_preflight_mode"] == "blocking"

    def test_tracker_state_diagnostic_round_trip(self, tmp_path, monkeypatch):
        """Write tracker_state_diagnostic=false via the CLI then read back as JSON bool.

        Functional counterpart to test_agentic_config_settings_registers_tracker_state_diagnostic
        in bin/tests/test_tracker_writeback_ranking_spec.py, which only checks the static
        _SETTINGS-dict presence. Mirrors test_rework_detection_round_trip's shape: PR #484's
        Skeptic Major finding on rework_detection was closed by pairing a static registration
        check with a functional round-trip check, and pending_merge_sweep later shipped without
        the CLI round trip covered at all (registration omitted entirely). This test exercises
        the CLI path itself so tracker_state_diagnostic cannot silently regress to
        pending_merge_sweep's gap.
        """
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "tracker_state_diagnostic", "false"])
        assert result == 0
        data = json.loads((tmp_path / ".agentic" / "config.json").read_text())
        assert data["tracker_state_diagnostic"] is False


# ---------------------------------------------------------------------------
# Success output and warnings
# ---------------------------------------------------------------------------

class TestSuccessOutput:
    def test_success_message_format(self, tmp_path, monkeypatch, capsys):
        """Success prints 'Changed: <setting> = <value> in <file>...' line."""
        monkeypatch.chdir(tmp_path)
        main(["agentic-config", "commit_telemetry", "false"])
        out = capsys.readouterr().out
        assert "Changed:" in out
        assert "commit_telemetry" in out
        assert "false" in out
        assert "Takes effect at next session start." in out

    def test_opt_in_footgun_warning(self, tmp_path, monkeypatch, capsys):
        """Writing mode=opt-in globally prints the KNW-20260701-001 warning."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        result = main(["agentic-config", "mode", "opt-in"])
        assert result == 0
        out = capsys.readouterr().out
        assert "KNW-20260701-001" in out or "opt-in" in out.lower()

    def test_opt_out_no_footgun_warning(self, tmp_path, monkeypatch, capsys):
        """Writing mode=opt-out does NOT print the opt-in warning."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        main(["agentic-config", "mode", "opt-out"])
        out = capsys.readouterr().out
        assert "KNW-20260701-001" not in out


# ---------------------------------------------------------------------------
# Activation marker via main()
# ---------------------------------------------------------------------------

class TestActivationMarkerViaMain:
    """The 'mode' setting writes global JSON; 'profile' --scope project writes AGENTS.md."""

    def test_mode_opt_out_via_main(self, tmp_path, monkeypatch):
        """main() with mode=opt-out writes to global JSON (not AGENTS.md)."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "mode", "opt-out"])
        assert result == 0
        assert fake_config.is_file()
        data = json.loads(fake_config.read_text())
        assert data["mode"] == "opt-out"

    def test_profile_project_marker_via_main(self, tmp_path, monkeypatch):
        """main() with profile=default --scope project writes AGENTS.md marker."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# test\n")
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "profile", "default", "--scope", "project"])
        assert result == 0
        content = (tmp_path / "AGENTS.md").read_text()
        assert "agentic-engineering-profile: default" in content
        # Global config should NOT have been written.
        assert not fake_config.exists()

    def test_profile_global_via_main_updates_json(self, tmp_path, monkeypatch):
        """main() with profile=relaxed --scope global writes global JSON."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        monkeypatch.chdir(tmp_path)
        result = main(["agentic-config", "profile", "relaxed", "--scope", "global"])
        assert result == 0
        data = json.loads(fake_config.read_text())
        assert data["profile"] == "relaxed"


# ---------------------------------------------------------------------------
# _parse_bool / _parse_int
# ---------------------------------------------------------------------------

class TestParsers:
    def test_parse_bool_true_variants(self):
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("1") is True
        assert _parse_bool("yes") is True

    def test_parse_bool_false_variants(self):
        assert _parse_bool("false") is False
        assert _parse_bool("False") is False
        assert _parse_bool("0") is False
        assert _parse_bool("no") is False

    def test_parse_bool_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_bool("maybe")
        with pytest.raises(ValueError):
            _parse_bool("enabled")

    def test_parse_int_valid(self):
        assert _parse_int("1") == 1
        assert _parse_int("100") == 100
        assert _parse_int("30", int_min=1) == 30

    def test_parse_int_below_min_raises(self):
        with pytest.raises(ValueError, match=">="):
            _parse_int("0", int_min=1)

    def test_parse_int_non_integer_raises(self):
        with pytest.raises(ValueError, match="expected integer"):
            _parse_int("abc")

    def test_parse_int_float_raises(self):
        with pytest.raises(ValueError, match="expected integer"):
            _parse_int("1.5")


# ---------------------------------------------------------------------------
# Regression: Fix 1 - activation setting writes AGENTS.md marker
# (was unreachable before; agents_activation target was dead code)
# ---------------------------------------------------------------------------

class TestActivationSettingRegression:
    """activation setting writes dinostack: <value> to AGENTS.md."""

    def test_activation_opt_in_writes_agents_md(self, tmp_path, monkeypatch):
        """[Fix1] main(['activation','opt-in']) writes agentic-engineering: opt-in to AGENTS.md."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# Project\nagentic-engineering-profile: strict\n")
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "activation", "opt-in"])
        assert result == 0
        content = (tmp_path / "AGENTS.md").read_text()
        assert "agentic-engineering: opt-in" in content
        # Profile marker must be untouched.
        assert "agentic-engineering-profile: strict" in content
        # Global JSON must NOT have been written.
        assert not fake_config.exists()

    def test_activation_opt_out_writes_agents_md(self, tmp_path, monkeypatch):
        """[Fix1] main(['activation','opt-out']) writes agentic-engineering: opt-out to AGENTS.md."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# Project\n")
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "activation", "opt-out"])
        assert result == 0
        content = (tmp_path / "AGENTS.md").read_text()
        assert "agentic-engineering: opt-out" in content

    def test_activation_replaces_existing_marker(self, tmp_path, monkeypatch):
        """[Fix1] activation replaces an existing dinostack: line in place."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text(
            "# Project\nagentic-engineering: opt-out\nagentic-engineering-profile: relaxed\n"
        )
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "activation", "opt-in"])
        assert result == 0
        content = (tmp_path / "AGENTS.md").read_text()
        assert "agentic-engineering: opt-in" in content
        assert "agentic-engineering: opt-out" not in content
        # Profile marker untouched.
        assert "agentic-engineering-profile: relaxed" in content

    def test_activation_non_repo_cwd_exits_2(self, tmp_path, monkeypatch):
        """[Fix1] activation from non-git-root cwd with no AGENTS.md -> exit 2."""
        # tmp_path has no .git entry and no AGENTS.md.
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["agentic-config", "activation", "opt-in"])
        assert exc_info.value.code == 2

    def test_activation_scope_flag_emits_note(self, tmp_path, monkeypatch, capsys):
        """[Fix1+Fix3] --scope passed to activation emits a note to stderr (not an error)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# Project\n")
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "activation", "opt-in", "--scope", "project"])
        assert result == 0
        err = capsys.readouterr().err
        assert "note:" in err
        assert "ignored" in err


# ---------------------------------------------------------------------------
# Regression: Fix 2 - malformed JSON causes exit 2 via main()
# (was silently discarding all other keys before)
# ---------------------------------------------------------------------------

class TestMalformedJsonViaMainRegression:
    def test_malformed_global_json_via_main_exits_2(self, tmp_path, monkeypatch, capsys):
        """[Fix2] main() with malformed global JSON -> exit 2, file not overwritten."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        fake_config.parent.mkdir(parents=True)
        original = "{ broken json"
        fake_config.write_text(original)
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)

        result = main(["agentic-config", "mode", "opt-out"])
        assert result == 2
        assert fake_config.read_text() == original
        err = capsys.readouterr().err
        assert "malformed" in err.lower() or "fix" in err.lower()

    def test_malformed_project_config_via_main_exits_2(self, tmp_path, monkeypatch, capsys):
        """[Fix2] main() with malformed .agentic/config.json -> exit 2, file not overwritten."""
        monkeypatch.chdir(tmp_path)
        agentic = tmp_path / ".agentic"
        agentic.mkdir()
        original = "not json at all"
        (agentic / "config.json").write_text(original)

        result = main(["agentic-config", "commit_telemetry", "true"])
        assert result == 2
        assert (agentic / "config.json").read_text() == original
        err = capsys.readouterr().err
        assert "malformed" in err.lower() or "fix" in err.lower()


# ---------------------------------------------------------------------------
# Regression: Fix 3 - --scope ignored emits a note to stderr
# ---------------------------------------------------------------------------

class TestScopeIgnoredNoteRegression:
    def test_mode_with_scope_emits_note(self, tmp_path, monkeypatch, capsys):
        """[Fix3] mode is global-only; passing --scope emits a note to stderr."""
        fake_config = tmp_path / ".claude" / "agentic-engineering.json"
        monkeypatch.setattr(_mod, "CONFIG_PATH", fake_config)
        monkeypatch.chdir(tmp_path)

        result = main(["agentic-config", "mode", "opt-out", "--scope", "project"])
        assert result == 0
        err = capsys.readouterr().err
        assert "note:" in err
        assert "ignored" in err

    def test_config_json_setting_with_scope_emits_note(self, tmp_path, monkeypatch, capsys):
        """[Fix3] config.json settings ignore --scope and emit a note to stderr."""
        monkeypatch.chdir(tmp_path)

        result = main(["agentic-config", "commit_telemetry", "true", "--scope", "global"])
        assert result == 0
        err = capsys.readouterr().err
        assert "note:" in err
        assert "ignored" in err

    def test_no_scope_flag_no_note(self, tmp_path, monkeypatch, capsys):
        """[Fix3] no --scope flag -> no note emitted."""
        monkeypatch.chdir(tmp_path)

        main(["agentic-config", "commit_telemetry", "false"])
        err = capsys.readouterr().err
        assert "note:" not in err
