#!/usr/bin/env python3
"""
Purpose: Pin the memory main-only MARKER and POINTER lines that
         /ds-init-project (item 12) and /ds-wrap (pre-flight CLAUDE.md
         migration) write into a consumer's root CLAUDE.md against the
         MARKER the session-start-memory hook looks for.

Failure caught: a marker mismatch silently disables delivery for every
                newly migrated repo.

Retirement condition: the hook is retired, or marker writing moves into one
                      shared tool.

Public API: pytest entry points only.

Upstream deps: hooks/session-start-memory.py (MARKER, loaded via
               importlib, never executed as a hook),
               content/commands/ds-init-project.md,
               content/commands/ds-wrap.md.

Downstream consumers: the python-bin-tests CI job
                      (`python3 -m pytest bin/tests/`).

Failure modes: a missing hook file fails the test loudly; it never skips.

Performance: standard.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "session-start-memory.py"
PROSE = [
    REPO / "content" / "commands" / "ds-init-project.md",
    REPO / "content" / "commands" / "ds-wrap.md",
]


def _hook_marker():
    spec = importlib.util.spec_from_file_location("session_start_memory", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MARKER


def _marker_and_next(path, marker):
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    assert marker in lines, f"{path.relative_to(REPO)} has no line equal to MARKER {marker!r}"
    i = lines.index(marker)
    assert i + 1 < len(lines), f"{path.relative_to(REPO)}: MARKER is the last line"
    return lines[i + 1]


def test_marker_present_in_both_prose_files():
    marker = _hook_marker()
    for path in PROSE:
        _marker_and_next(path, marker)


def test_pointer_identical_in_both_prose_files():
    marker = _hook_marker()
    pointers = [_marker_and_next(path, marker) for path in PROSE]
    assert pointers[0] == pointers[1], (
        "POINTER after MARKER differs:\n"
        f"  ds-init-project.md: {pointers[0]!r}\n"
        f"  ds-wrap.md:         {pointers[1]!r}"
    )
