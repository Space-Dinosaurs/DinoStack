#!/usr/bin/env python3
"""
Drift gate: the config-dir env-var precedence list is hand-maintained in
THREE separate places (bin/_lib.py's CONFIG_DIR_ENV, hooks/lib/config-dir.js's
CONFIG_DIR_ENV, and bin/ds-identity's PROFILE_CONFIG_DIR_ENV) with only a
"kept in sync" comment holding them together - no code shares the literal.
Major B (round 2 of PR #723) was a live instance of this class: the two
resolvers agreed on the ENV VAR LIST but diverged on what to DO with a `~`
in a value, which a comment-only sync promise cannot catch either. This test
mechanically pins all three lists to the identical tuple, in the identical
order, so any future edit to one without the other two fails CI instead of
silently drifting.

Public API: none (pytest test module / standalone runner).

Run with: python3 bin/tests/test_config_dir_env_sync.py
       or: python3 -m pytest bin/tests/test_config_dir_env_sync.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent

_LIB_PATH = _REPO_ROOT / "bin" / "_lib.py"
_CONFIG_DIR_JS_PATH = _REPO_ROOT / "hooks" / "lib" / "config-dir.js"
_DS_IDENTITY_PATH = _REPO_ROOT / "bin" / "ds-identity"


def _load_lib_config_dir_env() -> tuple[str, ...]:
    loader = importlib.machinery.SourceFileLoader("_lib", str(_LIB_PATH))
    spec = importlib.util.spec_from_loader("_lib", loader)
    if spec is None:
        raise RuntimeError(f"Cannot build spec for _lib from {_LIB_PATH}")
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return tuple(mod.CONFIG_DIR_ENV)


def _extract_quoted_list(source: str, var_name: str, path: Path) -> tuple[str, ...]:
    """Extract an ordered tuple of quoted string literals from a
    `<var_name> = ( ... )` / `<var_name> = [ ... ]` / `<var_name>: ... = ( ... )`
    declaration, up to its closing paren/bracket. Language-agnostic (works
    for both the Python tuple and the JS array literal shapes used here).
    """
    # Find the declaration's opening bracket/paren after the variable name.
    decl_match = re.search(rf"\b{re.escape(var_name)}\b[^=]*=\s*[\(\[]", source)
    if not decl_match:
        raise AssertionError(f"Could not find declaration of {var_name} in {path}")
    start = decl_match.end()
    close_char = ")" if source[decl_match.end() - 1] == "(" else "]"
    end = source.index(close_char, start)
    body = source[start:end]
    return tuple(re.findall(r'["\']([A-Z_]+)["\']', body))


def test_all_three_config_dir_env_lists_match():
    """CONFIG_DIR_ENV (Python) == CONFIG_DIR_ENV (JS) == PROFILE_CONFIG_DIR_ENV (ds-identity)."""
    py_lib_list = _load_lib_config_dir_env()

    js_source = _CONFIG_DIR_JS_PATH.read_text(encoding="utf-8")
    js_list = _extract_quoted_list(js_source, "CONFIG_DIR_ENV", _CONFIG_DIR_JS_PATH)

    identity_source = _DS_IDENTITY_PATH.read_text(encoding="utf-8")
    identity_list = _extract_quoted_list(
        identity_source, "PROFILE_CONFIG_DIR_ENV", _DS_IDENTITY_PATH
    )

    assert py_lib_list == js_list, (
        f"bin/_lib.py CONFIG_DIR_ENV {py_lib_list} != "
        f"hooks/lib/config-dir.js CONFIG_DIR_ENV {js_list}"
    )
    assert py_lib_list == identity_list, (
        f"bin/_lib.py CONFIG_DIR_ENV {py_lib_list} != "
        f"bin/ds-identity PROFILE_CONFIG_DIR_ENV {identity_list}"
    )
    assert len(py_lib_list) > 0, "extracted list must be non-empty (extraction sanity check)"
    print("PASS test_all_three_config_dir_env_lists_match")


if __name__ == "__main__":
    test_all_three_config_dir_env_lists_match()
    print("All config-dir-env-sync tests passed.")
