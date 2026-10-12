#!/usr/bin/env python3
"""
Purpose: Pin the memory main-only MARKER and POINTER lines that
         /ds-init-project (item 12) and /ds-wrap (pre-flight CLAUDE.md
         migration) write into a consumer's root CLAUDE.md against the
         MARKER the session-start-memory hook looks for, and pin the
         bounded-read instruction at each site that reads MEMORY.md.

Failure caught: a marker mismatch silently disables delivery for every
                newly migrated repo; a read site regressing to "Read
                MEMORY.md in full" hits the Read tool's per-call cap on a
                large file.

Retirement condition: the hook is retired, or marker writing moves into one
                      shared tool (marker pins); Claude Code's Read cap is
                      lifted or MEMORY.md delivery moves off file reads
                      (bounded-read pins).

Public API: pytest entry points only.

Upstream deps: hooks/session-start-memory.py (MARKER, loaded via
               importlib, never executed as a hook),
               content/commands/ds-init-project.md,
               content/commands/ds-wrap.md, and the BOUNDED_READ_SITES
               files below.

Downstream consumers: the python-bin-tests CI job
                      (`python3 -m pytest bin/tests/`).

Failure modes: a missing hook file fails the test loudly; it never skips.

Performance: standard.
"""
import importlib.util
import re
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


def test_stale_pointer_prefix_matches_current_pointer():
    marker = _hook_marker()
    for path in PROSE:
        text = path.read_text(encoding="utf-8")
        prefixes = re.findall(r"starts with `(MEMORY\.md \(durable facts[^`]*)`", text)
        assert len(prefixes) == 1, f"{path.relative_to(REPO)}: {len(prefixes)} stale-pointer rules"
        pointer = _marker_and_next(path, marker)
        assert pointer.startswith(prefixes[0]), (
            f"{path.relative_to(REPO)}: stale-pointer prefix {prefixes[0]!r} "
            "does not match the current pointer, so the refresh rule would rewrite it every run"
        )


# Catches a MEMORY.md read site regressing to "Read MEMORY.md in full"; retires
# when Claude Code's Read cap is lifted or MEMORY.md delivery moves off file reads.
BOUNDED_READ_SITES = [
    ("CLAUDE.md", "never the whole file at once"),
    ("content/commands/ds-init-project.md", "never the whole file at once"),
    ("content/commands/ds-wrap.md", "never the whole file at once"),
    ("content/commands/ds-wrap.md", "Do not Read it whole; step 3 works from grep hits"),
    ("content/commands/ds-wrap.md", "This brief carries the path, not the content"),
    ("content/commands/ds-wrap.md", "Read the original from the target path you were given in chunks"),
    ("content/commands/ds-wrap.md", "path and counts, never the content"),
    ("content/commands/ds-wrap-deferred.md", "grep it for the entry's distinctive terms and Read only a window"),
    ("content/commands/ds-implement-ticket.md", "else grep it on demand and Read bounded windows around hits"),
    ("content/commands/ds-brief.md", "grep the intent keywords, Read bounded windows around hits"),
    ("content/commands/ds-memory-update.md", "never Read it whole"),
    ("content/agents/learnings-agent.md", "never Read the file whole. Grep it"),
    ("content/agents/wrap-ticket.md", "never Read the file whole. Grep it"),
]


def test_bounded_read_instruction_at_each_site():
    missing = [
        f"{rel}: {phrase!r}"
        for rel, phrase in BOUNDED_READ_SITES
        if phrase not in (REPO / rel).read_text(encoding="utf-8")
    ]
    assert not missing, "bounded-read instruction missing:\n  " + "\n  ".join(missing)
