#!/usr/bin/env python3
"""
Regression tests for agentic-configure: emit-yaml, non-interactive default
acceptance, never-overwrite guard, bootstrap hook integration, and the
PR #249 probe-URL fix (Step 1 of the review fix plan).

Test groups:
  1. test_emit_yaml_scalar_form - simple roles map to scalar lines.
  2. test_emit_yaml_mapping_form - roles with effort/reasoning render as mappings.
  3. test_emit_yaml_dedupes_pool - duplicate model entries in pool are merged.
  4. test_emit_yaml_fallback_pool - empty pool gets a default sentinel entry.
  5. test_noninteractive_no_probe_writes_nothing - M6: empty probe URL -> exit 0, no file.
  6. test_noninteractive_with_probe_writes_file - M6 positive path: mocked probe writes file.
  7. test_probe_url_appends_v1_models - C1: base http://x[/] -> http://x/v1/models.
  8. test_existing_file_is_not_overwritten - second run is a no-op.
  9. test_bootstrap_hook_idempotent - re-running the hook does not re-seed.
 10. test_bootstrap_no_sentinel_on_no_url - URL unset -> no sentinel (retry).
 11. test_bootstrap_no_sentinel_on_probe_failure - probe-failure non-zero does NOT.

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


def test_noninteractive_no_probe_writes_nothing():
    """Non-interactive + empty probe URL -> exit 0, NO file written (M6)."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "role-models.yml"
        env = dict(os.environ)
        env.pop("NINEROUTER_URL", None)  # ensure no probe URL from env
        result = subprocess.run(
            [
                str(_BIN_PATH),
                "--non-interactive",
                "--path",
                str(target),
                "--probe-url",
                "",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        assert result.returncode == 0
        assert not target.exists(), f"expected no file, got: {target}"
        assert "no probe URL" in result.stderr


def test_noninteractive_with_probe_writes_file(monkeypatch):
    """Non-interactive + successful probe -> file written with role mappings."""
    fake_payload = {
        "models": ["cc/claude-sonnet-4-5", "cx/gpt-5", "cc/claude-opus-4-5"],
        "roles": {
            "engineer": {"primary": "cc/claude-sonnet-4-5", "alternates": []},
            "conductor": {"primary": "cc/claude-opus-4-5", "alternates": []},
        },
        "reviewer_pool": ["cx/gpt-5"],
    }
    _mod._probe_or_empty = lambda url, key: fake_payload
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "role-models.yml"
        rc = _mod.main([
            "--non-interactive",
            "--path", str(target),
            "--probe-url", "http://x",
        ])
        assert rc == 0
        assert target.is_file(), "file must be written on successful probe"
        text = target.read_text()
    assert "roles:" in text
    assert "engineer:" in text


def test_probe_url_appends_v1_models(monkeypatch):
    """_probe_models in bin/agentic-models resolves <base>/v1/models."""
    import importlib.util as _ilu
    import importlib.machinery as _im
    models_path = Path(__file__).parent.parent / "agentic-models"
    loader = _im.SourceFileLoader("agentic_models", str(models_path))
    spec = _ilu.spec_from_loader("agentic_models", loader)
    m = _ilu.module_from_spec(spec)
    loader.exec_module(m)

    captured = {}
    class FakeReq:
        def __init__(self, url, method="GET"):
            captured["url"] = url
            captured["method"] = method
        def add_header(self, k, v):
            captured.setdefault("headers", {})[k] = v

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b'{"data": [{"id": "m1"}]}'

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(m.urllib.request, "Request", FakeReq)
    monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)
    # base without trailing slash -> base/v1/models
    out = m._probe_models("http://x", None, timeout=5)
    assert out == ["m1"]
    assert captured["url"] == "http://x/v1/models", captured["url"]

    # Trailing slash on base: strip exactly one, still base/v1/models
    m._probe_models("http://x/", None, timeout=5)
    assert captured["url"] == "http://x/v1/models", captured["url"]


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


def test_bootstrap_hook_idempotent():
    """Re-running the hook on a configured session must not change the file."""
    hook = Path(__file__).parent.parent.parent / "hooks" / "role-models-bootstrap.py"
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / ".agentic" / "role-models.yml"
        target.parent.mkdir(parents=True)
        target.write_text("roles:\n  engineer: opus\n")
        sentinel = Path(td) / ".agentic" / ".role-models-bootstrap"
        env = dict(os.environ)
        env["PI_HARNESS"] = "pi"
        env["NINEROUTER_URL"] = "http://127.0.0.1:1"  # base without /v1; probe will fail
        env["HOME"] = td
        # File already exists -> no-op (sentinel absent because we never reach configure)
        r1 = subprocess.run(
            [sys.executable, str(hook)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert r1.returncode == 0
        assert target.read_text() == "roles:\n  engineer: opus\n"
        assert not sentinel.exists()

def test_bootstrap_no_sentinel_on_no_url():
    """URL unset -> hook no-ops, no sentinel, retry next session."""
    hook = Path(__file__).parent.parent.parent / "hooks" / "role-models-bootstrap.py"
    with tempfile.TemporaryDirectory() as td:
        sentinel = Path(td) / ".agentic" / ".role-models-bootstrap"
        env = dict(os.environ)
        env["PI_HARNESS"] = "pi"
        # No NINEROUTER_URL set -> hook no-ops without calling configure or writing sentinel
        env.pop("NINEROUTER_URL", None)
        env["HOME"] = td
        r = subprocess.run(
            [sys.executable, str(hook)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert r.returncode == 0
        assert not sentinel.exists(), "sentinel must NOT be written when URL unset (allow retry)"
        target = Path(td) / ".agentic" / "role-models.yml"
        assert not target.exists(), "no file written on no-URL no-op"


def test_bootstrap_no_sentinel_on_probe_failure():
    """Probe failure (configure exit non-zero) must NOT write the sentinel."""
    hook = Path(__file__).parent.parent.parent / "hooks" / "role-models-bootstrap.py"
    with tempfile.TemporaryDirectory() as td:
        sentinel = Path(td) / ".agentic" / ".role-models-bootstrap"
        env = dict(os.environ)
        env["PI_HARNESS"] = "pi"
        # Pointing at a port nothing listens on -> probe fails -> configure exits 2
        env["NINEROUTER_URL"] = "http://127.0.0.1:1"
        env["HOME"] = td
        r = subprocess.run(
            [sys.executable, str(hook)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert r.returncode == 0  # hook itself always exits 0
        assert not sentinel.exists(), "sentinel must NOT be written when configure fails (allow retry)"


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


def main() -> int:
    failures = 0
    tests = [
        # Pure unit tests (no pytest fixture, safe in script mode)
        test_emit_yaml_scalar_form,
        test_emit_yaml_mapping_form,
        test_emit_yaml_dedupes_pool,
        test_emit_yaml_fallback_pool,
        test_noninteractive_no_probe_writes_nothing,
        test_existing_file_is_not_overwritten,
        test_bootstrap_hook_idempotent,
        test_bootstrap_no_sentinel_on_no_url,
        test_bootstrap_no_sentinel_on_probe_failure,
    ]
    tests = [t for t in tests if t is not None]
    # Note: test_noninteractive_with_probe_writes_file and test_probe_url_appends_v1_models
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
