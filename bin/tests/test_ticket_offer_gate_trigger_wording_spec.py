#!/usr/bin/env python3
"""
Purpose: Regression guard for the stale ticket-offer-gate trigger wording
         defect (PR #755 round 1): a restatement of the OLD narrow trigger
         ("do not spawn any implementer" / "spawning the first implementer")
         survived at content/sections/02-delegation.md:23 after the gate was
         widened to "first subagent spawn of any kind (exemptions apply)",
         and escaped four separate tree-wide searches before a manual rubric
         grade caught it. This test discovers gate-trigger CONTEXT lines by
         content (never a hardcoded file list - a pinned list is the same
         hand-maintained-closed-list defect this PR removes) and asserts
         none of them restate the narrow "first/any implementer" trigger.
Public API: pytest test functions only.
Upstream deps: every tracked *.md / *.html file under content/, docs/, and
         the repo-root README.md - read fresh on each run, no cached list.
Downstream consumers: bin-tests.yml python-bin-tests job
         (`pytest bin/tests/ -q`), full-directory glob discovery under
         `bin/tests/`, no per-file wiring required.
Failure modes: (a) a stale narrow-trigger restatement in any discovered
         gate-context line - the exact historical defect shape; (b)
         discovery finding zero candidate lines, which would make the
         property assertion vacuously true - this is treated as a hard
         failure ("discovery is broken, not clean"), same discipline as
         the `command -v` guard pattern in
         .github/workflows/bin-tests.yml.
False-positive reasoning: "implementer" alone is legitimate role-framing
         used throughout the tree ("not an implementer", "Worker (engineer
         or other implementer)", "You are an Engineer - the implementer")
         and appears in unrelated worktree-isolation / threat-model prose.
         A blanket ban on the bare word would misfire immediately. This
         test narrows in two stages: (1) discover only lines whose content
         is about the ticket-offer-gate TRIGGER itself (ticket_driven /
         ticket-offer gate / "before a ticket exists" / "before spawning"),
         then (2) within that already-narrow candidate set, forbid only the
         specific phrases "first implementer" / "any implementer" that
         restate the narrow pre-widening trigger - a plain mention of
         "implementer" inside a gate-context line that does NOT narrow the
         trigger (e.g. "before spawning any subagent") still passes.
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SEARCH_ROOTS = [
    REPO_ROOT / "content",
    REPO_ROOT / "docs",
]
SEARCH_FILES = [
    REPO_ROOT / "README.md",
]
SEARCH_SUFFIXES = {".md", ".html"}

# Stage 1: lines that are ABOUT the ticket-offer-gate trigger, by content -
# never a hardcoded file list.
GATE_CONTEXT_PATTERN = re.compile(
    r"ticket_driven|ticket-offer gate|before a ticket exists|before spawning",
    re.IGNORECASE,
)

# Stage 2: the specific narrow-trigger restatement this test guards against.
# Matches "first implementer" and "any implementer" (the two forms the
# stale text took pre-widening) without banning the bare word.
NARROW_TRIGGER_PATTERN = re.compile(
    r"\b(?:first|any)\s+implementer\b", re.IGNORECASE
)


def _candidate_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = list(SEARCH_FILES)
    for root in SEARCH_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SEARCH_SUFFIXES:
                files.append(path)
    return files


def _gate_context_lines() -> list[tuple[pathlib.Path, int, str]]:
    """Every (file, 1-based line number, line text) where the line mentions
    the ticket-offer-gate trigger. The SOLE discovery predicate - every test
    below calls this, never re-implements the scan inline."""
    hits: list[tuple[pathlib.Path, int, str]] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if GATE_CONTEXT_PATTERN.search(line):
                hits.append((path, lineno, line))
    return hits


def test_discovery_finds_gate_context_lines():
    """Vacuous-pass guard: if discovery finds nothing, the property test
    below would pass trivially. Fail loudly instead - discovery is broken,
    not clean. (Same discipline as the `command -v` hard-fail-under-CI
    pattern in .github/workflows/bin-tests.yml.)"""
    hits = _gate_context_lines()
    assert hits, (
        "gate-context discovery found ZERO candidate lines across "
        f"{REPO_ROOT / 'content'}, {REPO_ROOT / 'docs'}, "
        f"{REPO_ROOT / 'README.md'} - this means discovery is BROKEN, "
        "not that the tree is clean. Fix GATE_CONTEXT_PATTERN or the "
        "search roots before trusting the property test."
    )


def test_no_gate_context_line_restates_narrow_trigger():
    """The regression assertion. There are 8 known historical restatement
    sites (content/sections/02-delegation.md, content/references/
    conventions-detail.md, content/references/delegation-detail.md,
    content/references/risk-config-and-tiers.md, content/commands/
    ds-implement-ticket.md, docs/components.md, docs/configuration-
    reference.md, docs/index.html) - discovery is expected to find
    candidate lines in at least that many distinct files; the exact
    total line count is not pinned here since it is expected to grow
    as the docs evolve, and pinning it would recreate the same
    hand-maintained-list defect this PR removes."""
    hits = _gate_context_lines()
    offenders = [
        (path, lineno, line)
        for path, lineno, line in hits
        if NARROW_TRIGGER_PATTERN.search(line)
    ]
    assert not offenders, (
        "found "
        f"{len(offenders)} gate-context line(s) restating the narrow "
        "pre-widening trigger ('first implementer' / 'any implementer'):\n"
        + "\n".join(f"  {p}:{n}: {l.strip()}" for p, n, l in offenders)
    )


def test_discovery_covers_known_historical_files():
    """Sanity check (not a hardcoded pin on line content): the 8 files
    known to have carried the stale restatement must each still surface
    at least one gate-context candidate line, so a future narrowing of
    GATE_CONTEXT_PATTERN can't silently stop scanning them."""
    known_files = {
        REPO_ROOT / "content" / "sections" / "02-delegation.md",
        REPO_ROOT / "content" / "references" / "conventions-detail.md",
        REPO_ROOT / "content" / "references" / "delegation-detail.md",
        REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
        REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md",
        REPO_ROOT / "docs" / "components.md",
        REPO_ROOT / "docs" / "configuration-reference.md",
        REPO_ROOT / "docs" / "index.html",
    }
    hit_files = {path for path, _lineno, _line in _gate_context_lines()}
    missing = known_files - hit_files
    assert not missing, (
        f"discovery found no gate-context line in {len(missing)} of the "
        f"8 known historical restatement sites: {sorted(str(m) for m in missing)} "
        "- GATE_CONTEXT_PATTERN may have narrowed too far."
    )
