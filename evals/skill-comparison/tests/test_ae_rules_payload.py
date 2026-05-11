"""
Purpose: Unit tests for evals.skill-comparison.ae_rules_payload.build_payload and
         content_glob to verify glob order, byte-equivalence, and separator
         correctness.

Public API: pytest test module; no public symbols.

Upstream deps: evals.skill_comparison.ae_rules_payload, stdlib pathlib, tempfile.

Downstream consumers: pytest runner.

Failure modes: tests use temp directories; no network I/O; no side effects on
               the real content/ tree.

Performance: standard; all tests run on small synthetic content trees.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ae_rules_payload import build_payload, content_glob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(root: Path, rel: str, text: str) -> Path:
    """Write a file at root/rel, creating parent dirs as needed."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _make_content_tree(tmp: Path) -> dict[str, str]:
    """Create a minimal synthetic content/ tree and return {rel_path: content}."""
    files = {
        "SKILL.md": "# SKILL entry point\nThis is the skill manifest.\n",
        "sections/01-activation.md": "# Activation\nSection one content.\n",
        "sections/02-delegation.md": "# Delegation\nSection two content.\n",
        "rules/code-standards.md": "# Code standards\nRule content.\n",
        "rules/conventions.md": "# Conventions\nAnother rule.\n",
        "references/skeptic-protocol.md": "# Skeptic protocol\nReference content.\n",
        "references/subagent-protocol.md": "# Subagent protocol\nMore reference.\n",
        "commands/implement-ticket.md": "# Implement ticket\nCommand content.\n",
        "commands/wrap.md": "# Wrap\nAnother command.\n",
    }
    for rel, content in files.items():
        _write(tmp, rel, content)
    return files


# ---------------------------------------------------------------------------
# Test 1: build_payload is byte-equivalent given the same content tree
# ---------------------------------------------------------------------------

def test_build_payload_byte_equivalent():
    """build_payload returns identical bytes on two calls against the same tree."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _make_content_tree(tmp)

        payload1 = build_payload(tmp)
        payload2 = build_payload(tmp)

        assert payload1 == payload2, (
            "build_payload must be deterministic: two calls on the same tree must return "
            "identical output"
        )


# ---------------------------------------------------------------------------
# Test 2: glob order is enforced (SKILL.md -> sections -> rules -> references -> commands)
# ---------------------------------------------------------------------------

def test_content_glob_order():
    """content_glob returns files in the canonical load-bearing order."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _make_content_tree(tmp)

        paths = content_glob(tmp)
        names = [p.relative_to(tmp).as_posix() for p in paths]

        # SKILL.md must come first.
        assert names[0] == "SKILL.md", f"First entry must be SKILL.md, got {names[0]}"

        # sections must come before rules.
        section_indices = [i for i, n in enumerate(names) if n.startswith("sections/")]
        rule_indices = [i for i, n in enumerate(names) if n.startswith("rules/")]
        reference_indices = [i for i, n in enumerate(names) if n.startswith("references/")]
        command_indices = [i for i, n in enumerate(names) if n.startswith("commands/")]

        assert section_indices, "Expected at least one sections/ file"
        assert rule_indices, "Expected at least one rules/ file"
        assert reference_indices, "Expected at least one references/ file"
        assert command_indices, "Expected at least one commands/ file"

        assert max(section_indices) < min(rule_indices), (
            "All sections/ files must appear before any rules/ file"
        )
        assert max(rule_indices) < min(reference_indices), (
            "All rules/ files must appear before any references/ file"
        )
        assert max(reference_indices) < min(command_indices), (
            "All references/ files must appear before any commands/ file"
        )


# ---------------------------------------------------------------------------
# Test 3: sections within each group are sorted lexicographically by filename
# ---------------------------------------------------------------------------

def test_content_glob_lexicographic_sort_within_groups():
    """Files within each glob group are sorted lexicographically by filename."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _make_content_tree(tmp)

        paths = content_glob(tmp)

        def _group(prefix: str) -> list[str]:
            return [p.name for p in paths if p.relative_to(tmp).as_posix().startswith(prefix)]

        for group_prefix in ("sections/", "rules/", "references/", "commands/"):
            group_names = _group(group_prefix)
            assert group_names == sorted(group_names), (
                f"Files in {group_prefix} must be sorted lexicographically; "
                f"got {group_names}"
            )


# ---------------------------------------------------------------------------
# Test 4: ordering test compares first 200 chars under each section header
# ---------------------------------------------------------------------------

def test_build_payload_section_content_ordering():
    """The first 200 chars under each separator header match the expected file content."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        file_contents = _make_content_tree(tmp)

        payload = build_payload(tmp)

        for rel_path, expected_content in file_contents.items():
            header = f"# === {rel_path} ==="
            assert header in payload, f"Expected separator header {header!r} in payload"

            # Find position just after the separator header.
            start = payload.index(header) + len(header)
            # Skip leading newlines from the separator template.
            while start < len(payload) and payload[start] == "\n":
                start += 1

            # The next 200 chars (or less if file is shorter) must start with
            # the expected file content.
            snippet = payload[start : start + 200]
            expected_snippet = expected_content[:200]

            assert snippet.startswith(expected_snippet), (
                f"Content under header {header!r} does not start with expected text.\n"
                f"Expected: {expected_snippet!r}\n"
                f"Got:      {snippet!r}"
            )


# ---------------------------------------------------------------------------
# Test 5: FileNotFoundError on missing content_root
# ---------------------------------------------------------------------------

def test_build_payload_missing_root_raises():
    """build_payload raises FileNotFoundError when content_root does not exist."""
    with pytest.raises(FileNotFoundError):
        build_payload(Path("/nonexistent/content_root_for_test"))


# ---------------------------------------------------------------------------
# Test 6: SKILL.md missing from tree - no crash, SKILL.md absent from glob
# ---------------------------------------------------------------------------

def test_content_glob_skill_md_absent():
    """content_glob handles missing SKILL.md gracefully (omits it, no crash)."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        # Create sections but no SKILL.md.
        _write(tmp, "sections/01-sec.md", "section content")

        paths = content_glob(tmp)
        names = [p.name for p in paths]

        assert "SKILL.md" not in names
        assert "01-sec.md" in names


# ---------------------------------------------------------------------------
# Test 7: separator format is stable and contains relative path
# ---------------------------------------------------------------------------

def test_build_payload_separator_contains_rel_path():
    """Each file's content is preceded by a separator containing its relative path."""
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        _make_content_tree(tmp)

        payload = build_payload(tmp)

        # Every separator must follow the template: # === <rel_path> ===
        for rel_path in ["SKILL.md", "sections/01-activation.md", "rules/code-standards.md",
                          "references/skeptic-protocol.md", "commands/implement-ticket.md"]:
            expected = f"# === {rel_path} ==="
            assert expected in payload, (
                f"Separator for {rel_path!r} not found in payload"
            )
