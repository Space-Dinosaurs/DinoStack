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
 10. test_bootstrap_sentinel_on_no_probe - no-probe exit-0 writes sentinel.
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

def test_bootstrap_sentinel_on_no_probe():
    """No-probe no-op (exit 0) writes the sentinel so we do not retry."""
    hook = Path(__file__).parent.parent.parent / "hooks" / "role-models-bootstrap.py"
    with tempfile.TemporaryDirectory() as td:
        sentinel = Path(td) / ".agentic" / ".role-models-bootstrap"
        env = dict(os.environ)
        env["PI_HARNESS"] = "pi"
        # No NINEROUTER_URL set -> configure exits 0 with no file
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
        assert sentinel.exists(), "sentinel must be written on exit-0 no-op (suppress retry)"
        target = Path(td) / ".agentic" / "role-models.yml"
        assert not target.exists(), "no file written on no-probe no-op"


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
        test_bootstrap_sentinel_on_no_probe,
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
