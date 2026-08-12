#!/usr/bin/env python3
"""
Purpose: Guard against malformed `.claude/commands.frontmatter/<name>.yaml`
         sidecars silently regenerating a broken or truncated Claude Code
         command-picker `description:` into `.claude/commands/<name>.md`.
         `check-adapter-sync` compares regenerated output byte-for-byte, so
         a malformed sidecar that regenerates DETERMINISTICALLY goes green
         there - it never sees the semantic content, only that the build was
         reproduced. This test is the only gate that actually parses the
         generated frontmatter and checks its meaning.

Public API: pytest test functions. Run with
              python3 -m pytest bin/tests/test_command_picker_descriptions.py -q
            (.github/workflows/bin-tests.yml's `python-bin-tests` job runs
            `python3 -m pytest bin/tests/ -q`, auto-discovering; no additional
            CI wiring is required.)

Upstream deps: `.claude/commands/*.md` (must be freshly built by
               `bash .claude/build.sh` before this runs - CI's adapter-sync
               job builds before the drift check, and bin-tests runs on the
               same checked-out tree), `bin/agentic-help` (imported as the
               canonical description source), stdlib + pyyaml.

Downstream consumers: none (CI gate only).

Failure modes this test exists to catch, none of which raise anywhere else
in the build pipeline:
  - B1: an unquoted `description:` value containing `: ` - a bare `cat` never
    errors, but `yaml.safe_load` raises ScannerError. Caught by
    test_frontmatter_parses_without_error.
  - B2: an unquoted `#` mid-value - parses "successfully" but SILENTLY
    TRUNCATES everything after the `#` (YAML end-of-line comment). No error
    anywhere in the build. Caught by test_description_matches_agentic_help,
    since a truncated string no longer equals the canonical `bin/agentic-help`
    line.
  - B3: a sidecar missing its trailing newline - the closing `---` fence
    glues onto the description value and no valid frontmatter block exists
    at byte 0. Caught by test_frontmatter_block_at_byte_zero.

Performance: parses 27 small files; well under a second.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMMANDS_DST = _REPO_ROOT / ".claude" / "commands"
_CONTENT_COMMANDS = _REPO_ROOT / "content" / "commands"
_AGENTIC_HELP = _REPO_ROOT / "bin" / "agentic-help"

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def _load_agentic_help_descriptions() -> dict[str, str]:
    """Import bin/agentic-help and parse its per-command one-liners.

    Returns {command-name-without-leading-slash: description text}.
    """
    loader = importlib.machinery.SourceFileLoader("agentic_help", str(_AGENTIC_HELP))
    spec = importlib.util.spec_from_loader("agentic_help", loader)
    if spec is None:
        raise RuntimeError(f"Cannot build spec for agentic-help from {_AGENTIC_HELP}")
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)  # type: ignore[union-attr]
    text: str = mod.HELP_TEXT
    found: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(/ds-[a-z-]+)\s{2,}(.*)$", line)
        if m:
            found[m.group(1)[1:]] = m.group(2).strip()
    return found


def _all_command_names() -> list[str]:
    return sorted(p.stem for p in _CONTENT_COMMANDS.glob("ds-*.md"))


def _generated_body(name: str) -> str:
    dst = _COMMANDS_DST / f"{name}.md"
    assert dst.is_file(), (
        f"{dst} does not exist - run `bash .claude/build.sh` before this test"
    )
    return dst.read_text()


def test_all_27_commands_present():
    """Sanity check on the fixture set itself, not the gate's own subject."""
    names = _all_command_names()
    assert len(names) == 27, f"Expected 27 commands, found {len(names)}: {names}"


def test_frontmatter_block_at_byte_zero():
    """Catches B3 (missing trailing newline -> glued closing fence).

    A sidecar without a trailing newline produces `..."text"---` on one
    line, which does not match a `---\\n...\\n---\\n` frontmatter block at
    byte 0 at all.
    """
    for name in _all_command_names():
        body = _generated_body(name)
        m = _FRONTMATTER_RE.match(body)
        assert m is not None, (
            f"{name}.md: no well-formed frontmatter block at byte 0 - "
            f"check for a missing trailing newline in the sidecar. "
            f"First 120 chars: {body[:120]!r}"
        )


def test_frontmatter_parses_without_error():
    """Catches B1 (unquoted `: ` in the description value).

    An unquoted colon-space inside a YAML scalar breaks the parser
    (ScannerError) rather than silently misparsing.
    """
    for name in _all_command_names():
        body = _generated_body(name)
        m = _FRONTMATTER_RE.match(body)
        assert m is not None, f"{name}.md: frontmatter block missing (see test_frontmatter_block_at_byte_zero)"
        raw_yaml = m.group(1)
        try:
            yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            raise AssertionError(
                f"{name}.md: frontmatter failed to parse as YAML - "
                f"likely an unquoted ': ' in the description. Error: {exc}"
            ) from exc


def test_description_key_present_and_nonempty():
    for name in _all_command_names():
        body = _generated_body(name)
        m = _FRONTMATTER_RE.match(body)
        assert m is not None
        parsed = yaml.safe_load(m.group(1)) or {}
        desc = parsed.get("description")
        assert desc, f"{name}.md: frontmatter has no non-empty 'description' key"


def test_description_matches_agentic_help():
    """Catches B2 (unquoted `#` -> silent truncation) and future drift.

    `bin/agentic-help` is the canonical description source (plan Step 1).
    A truncated description simply stops equaling the canonical line -
    this is the assertion that makes B2 detectable at all, since a bare
    `cat`-based build (`.claude/build.sh`) never errors on it.
    """
    canonical = _load_agentic_help_descriptions()
    for name in _all_command_names():
        assert name in canonical, (
            f"{name}: no corresponding line in bin/agentic-help HELP_TEXT - "
            f"every command must have a canonical description there (plan Step 1)"
        )
        body = _generated_body(name)
        m = _FRONTMATTER_RE.match(body)
        assert m is not None
        parsed = yaml.safe_load(m.group(1)) or {}
        desc = parsed.get("description")
        assert desc == canonical[name], (
            f"{name}.md: generated description does not match bin/agentic-help "
            f"canonical text.\nGenerated: {desc!r}\nCanonical: {canonical[name]!r}"
        )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
