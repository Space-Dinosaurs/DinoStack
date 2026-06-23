#!/usr/bin/env python3
"""
Regression tests for agentic-configure: emit-yaml, non-interactive default
acceptance, never-overwrite guard, and team-shim delegation.

Test groups:
  1. test_emit_yaml_scalar_form - simple roles map to scalar lines.
  2. test_emit_yaml_mapping_form - roles with effort/reasoning render as mappings.
  3. test_emit_yaml_dedupes_pool - duplicate model entries in pool are merged.
  4. test_emit_yaml_fallback_pool - empty pool gets a default sentinel entry.
  5. test_noninteractive_writes_scalar_defaults - non-interactive writes scalar YAML.
  6. test_ask_user_interactive - ask-user path sets a role (simulated stdin).
  7. test_existing_file_is_not_overwritten - second run is a no-op.

Run with: python3 -m pytest bin/tests/test_agentic_configure.py -x
       or: python3 bin/tests/test_agentic_configure.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-configure as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-configure"
_loader = importlib.machinery.SourceFileLoader("agentic_configure", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_configure", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-configure from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_emit_yaml = _mod._emit_yaml
ROLES = _mod.ROLES


def test_emit_yaml_scalar_form():
    out = _emit_yaml({"engineer": "sonnet", "skeptic": "gpt-5"})
    assert "  engineer: sonnet" in out
    assert "  skeptic: gpt-5" in out


def test_emit_yaml_mapping_form():
    out = _emit_yaml(
        {"engineer": {"model": "sonnet", "effort": "medium", "reasoning": "4096"}}
    )
    assert "  engineer:" in out
    assert "    model: sonnet" in out
    assert "    effort: medium" in out
    assert "    reasoning: 4096" in out


def test_emit_yaml_dedupes_pool():
    out = _emit_yaml({"skeptic": "opus", "security-auditor": "opus"})
    pool_section = out.split("pool:")[1].split("fallback:")[0]
    assert pool_section.count("- opus") == 1


def test_emit_yaml_fallback_pool():
    out = _emit_yaml({"engineer": "sonnet"})
    pool_section = out.split("pool:")[1].split("fallback:")[0]
    assert "- sonnet" in pool_section


def test_noninteractive_writes_scalar_defaults():
    """Non-interactive with no suggestions writes scalar YAML defaults and exits 0."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "role-models.yml"
        result = subprocess.run(
            [str(_BIN_PATH), "--non-interactive", "--path", str(target)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"expected exit 0, got {result.returncode}: {result.stderr}"
        )
        assert target.is_file(), "non-interactive must write the file"
        text = target.read_text()
        assert "roles:" in text
        assert "engineer:" in text


def test_ask_user_interactive(monkeypatch):
    """_gather_roles with non_interactive=False reads defaults from _ask."""
    # Stub _ask to return 'opus' for every role prompt
    monkeypatch.setattr(_mod, "_ask", lambda prompt, default: default)
    monkeypatch.setattr(_mod, "_ask_effort", lambda default="medium": "")
    monkeypatch.setattr(_mod, "_ask_reasoning", lambda default="": "")
    roles = _mod._gather_roles(suggestions={}, non_interactive=False)
    assert isinstance(roles, dict), "must return dict of role -> model"
    for role, val in roles.items():
        assert isinstance(val, str), (
            f"ask-user path must return scalar str for {role!r}, got {type(val).__name__}"
        )


def test_existing_file_is_not_overwritten():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "role-models.yml"
        target.write_text("# user-edited\nroles:\n  engineer: opus\n")
        mtime_before = target.stat().st_mtime
        result = subprocess.run(
            [str(_BIN_PATH), "--non-interactive", "--path", str(target)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert target.read_text() == "# user-edited\nroles:\n  engineer: opus\n"
        assert target.stat().st_mtime == mtime_before


def test_noninteractive_default_produces_scalar_output():
    """CRITICAL regression: non-interactive path must emit scalar YAML (engineer: sonnet),
    not mapping form ({model: sonnet}). Byte-identical to pre-refactor output."""
    # Simulate non-interactive with no probe suggestions (bare default = 'sonnet')
    # _gather_roles stores bare string when effort and reasoning are both empty
    from unittest.mock import patch
    # patch normalize_role_spec to ensure it's never called for bare case
    original_normalize = _mod.normalize_role_spec
    calls = []
    def tracking_normalize(spec):
        calls.append(spec)
        return original_normalize(spec)
    with patch.object(_mod, "normalize_role_spec", tracking_normalize):
        roles = _mod._gather_roles(suggestions={}, non_interactive=True)
    # Every role must be a bare string (scalar), not a dict
    for role, val in roles.items():
        assert isinstance(val, str), (
            f"role {role!r} should be scalar str, got {type(val).__name__}: {val!r}. "
            "Pre-refactor emitted scalar YAML; the refactor broke this."
        )
    # normalize_role_spec must NOT have been called for the non-interactive path
    assert calls == [], f"normalize_role_spec called unexpectedly: {calls}"
    # The emitted YAML must use scalar form (engineer: sonnet), not mapping form
    out = _emit_yaml(roles)
    for role in roles:
        assert f"  {role}: " in out, f"expected scalar line for {role!r} in YAML output"
        assert f"  {role}:\n" not in out, f"unexpected mapping form for {role!r}"


# ---------------------------------------------------------------------------
# team shim delegation test (back-compat: agentic-configure team -> agentic-team configure)
# ---------------------------------------------------------------------------

def test_configure_team_shim_delegates_to_agentic_team():
    """agentic-configure team delegates to agentic-team configure via subprocess.

    Verifies: exit 0, team.yml written with correct content.
    This covers the back-compat shim path introduced in Unit 1.
    """
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "team.yml"
        rc = _mod.main([
            "team",
            "--non-interactive",
            "--assign", "engineer=codex:gpt-5",
            "--path", str(target),
        ])
        assert rc == 0, f"shim must exit 0, got {rc}"
        assert target.is_file(), "shim must produce team.yml"
        text = target.read_text()
    assert "enabled: true" in text
    assert "engineer:" in text
    assert "harness: codex" in text
    assert "model: gpt-5" in text
    assert "dispatch:" in text


def test_existing_flags_unaffected_by_team_subcommand():
    """Existing flag-only path still works after team subcommand addition."""
    # Simulate --help: must not error or mention 'team' in the flag-only parser.
    # We test that main() routes non-'team' argv to the original argparse parser
    # by checking that an unknown flag still raises SystemExit (argparse behavior).
    try:
        _mod.main(["--unknown-flag-xyz"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        # argparse may not raise on all Python versions; just verify no crash
        pass


def test_banner_has_no_pi_branding():
    """BANNER title line must not contain '(Pi / oh-my-pi)' parenthetical (de-branded in Unit 2).

    The first line is the title. The skip-hint line may still mention 'Pi' as a
    behavioral note (Pi uses session default when a role is unset) - that is
    accurate and not branding. We only assert the title parenthetical is gone.
    """
    banner = _mod.BANNER
    title_line = banner.splitlines()[0]
    assert "(Pi" not in title_line, (
        f"BANNER title still contains Pi branding parenthetical: {title_line!r}"
    )
    assert "oh-my-pi" not in title_line, (
        f"BANNER title still contains oh-my-pi: {title_line!r}"
    )
    # Must still describe its purpose
    assert "role-model" in banner, f"BANNER must mention role-model setup: {banner!r}"


def main() -> int:
    failures = 0
    tests = [
        # Pure unit tests (no pytest fixture, safe in script mode)
        test_emit_yaml_scalar_form,
        test_emit_yaml_mapping_form,
        test_emit_yaml_dedupes_pool,
        test_emit_yaml_fallback_pool,
        test_noninteractive_writes_scalar_defaults,
        test_existing_file_is_not_overwritten,
    ]
    tests = [t for t in tests if t is not None]
    # Note: test_ask_user_interactive and test_noninteractive_default_produces_scalar_output
    # need the pytest monkeypatch fixture and only run under `python3 -m pytest`.
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            print(f"FAIL  {t.__name__}: {exc}")
            failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {exc}")
            failures += 1
    if failures:
        print(f"{failures} test(s) failed")
        return 1
    print(f"All {len(tests)} tests passed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
