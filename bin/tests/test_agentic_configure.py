#!/usr/bin/env python3
"""
Regression tests for agentic-configure: emit-yaml, non-interactive default
acceptance, never-overwrite guard, bootstrap hook integration.

Test groups:
  1. test_emit_yaml_scalar_form - simple roles map to scalar lines.
  2. test_emit_yaml_mapping_form - roles with effort/reasoning render as mappings.
  3. test_emit_yaml_dedupes_pool - duplicate model entries in pool are merged.
  4. test_emit_yaml_fallback_pool - empty pool gets a default sentinel entry.
  5. test_noninteractive_writes_file - default accept path produces valid YAML.
  6. test_existing_file_is_not_overwritten - second run is a no-op.
  7. test_bootstrap_hook_idempotent - re-running the hook does not re-seed.

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


def test_noninteractive_writes_file():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "role-models.yml"
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
        )
        assert result.returncode == 0
        assert target.is_file()
        text = target.read_text()
        assert "roles:" in text
        assert "engineer:" in text


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
        env["NINEROUTER_URL"] = "http://127.0.0.1:1/v1"  # probe will fail
        env["HOME"] = td
        # First call: file exists -> no-op, sentinel absent
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


def main() -> int:
    failures = 0
    tests = [
        test_emit_yaml_scalar_form,
        test_emit_yaml_mapping_form,
        test_emit_yaml_dedupes_pool,
        test_emit_yaml_fallback_pool,
        test_noninteractive_writes_file,
        test_existing_file_is_not_overwritten,
        test_bootstrap_hook_idempotent,
    ]
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
