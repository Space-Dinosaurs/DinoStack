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
Upstream deps: every GIT-TRACKED *.md / *.html file under content/, docs/,
         and the repo-root README.md - read fresh on each run via `git
         ls-files` (never a cached list, never an unfiltered directory
         walk). Filtering through `git ls-files` matters beyond accuracy:
         `docs/planning/`, `docs/research/`, `docs/technical/`, and
         `docs/_archive/` are gitignored, and the rubric this test's PR
         was reviewed under explicitly exempts gitignored planning docs -
         an unfiltered `rglob()` walk would scan them anyway and could go
         red in a local checkout (which has those files present) over
         content this test has no authority to require a fix for, while
         staying silently green in a fresh worktree (which does not).
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
         ticket-offer gate / "before a ticket exists" / "before spawning" /
         "ticket ... spawn" within 80 chars, which also catches phrasings
         like "ticket before the first implementer spawns" that name
         neither "before spawning" nor "before a ticket exists" verbatim),
         then (2) within that already-narrow candidate set, forbid the
         phrases "first implementer" / "any implementer" / "no implementer"
         (singular or plural) that restate the narrow pre-widening trigger
         - a plain mention of "implementer" inside a gate-context line that
         does NOT narrow the trigger (e.g. "before spawning any subagent")
         still passes. Known residual blind spots (measured, not
         hypothetical - see test_no_gate_context_line_restates_narrow_trigger
         docstring): a restatement using the bare word "implementer" with
         no first/any/no qualifier (e.g. "do not spawn an implementer
         before a ticket exists"), or one that names no "implementer"
         token at all (e.g. "no engineer or architect spawns before a
         ticket exists", "before the first implementing agent spawns")
         will not be caught by this test.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

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
# never a hardcoded file list. The `ticket[^.]{0,80}spawn` alternative
# catches phrasings that name neither "before spawning" nor "before a
# ticket exists" verbatim, e.g. "creates a tracker ticket before the first
# implementer spawns" (docs/index.html - a real historical carrier that
# the first three alternatives alone do not see).
GATE_CONTEXT_PATTERN = re.compile(
    r"ticket_driven|ticket-offer gate|before a ticket exists|before spawning"
    r"|ticket[^.]{0,80}spawn",
    re.IGNORECASE,
)

# Stage 2: the specific narrow-trigger restatement this test guards against.
# Matches "first implementer", "any implementer", and "no implementer"
# (singular or plural) - the forms the stale text took pre-widening -
# without banning the bare word "implementer" on its own.
NARROW_TRIGGER_PATTERN = re.compile(
    r"\b(?:first|any|no)\s+implementers?\b", re.IGNORECASE
)


def _tracked_relative_paths() -> set[pathlib.Path]:
    """Git-tracked *.md / *.html paths under content/, docs/, and
    README.md, resolved to absolute paths. Scoping discovery to tracked
    files (rather than an unfiltered directory walk) matters because
    docs/planning/, docs/research/, docs/technical/, and docs/_archive/
    are gitignored - present in a local checkout, absent in a fresh
    worktree - and the review rubric this test exists under exempts
    gitignored planning docs from this test's authority."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "content", "docs", "README.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked: set[pathlib.Path] = set()
    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        path = REPO_ROOT / rel
        if path.suffix in SEARCH_SUFFIXES:
            tracked.add(path)
    return tracked


def _candidate_files() -> list[pathlib.Path]:
    tracked = _tracked_relative_paths()
    files: list[pathlib.Path] = [f for f in SEARCH_FILES if f in tracked]
    for root in SEARCH_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in SEARCH_SUFFIXES and path in tracked:
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
    sites, verified by direct discovery against origin/main (README.md,
    content/commands/ds-init-project.md, content/references/conventions-
    detail.md, content/references/risk-config-and-tiers.md, content/
    sections/02-delegation.md, docs/components.md, docs/configuration-
    reference.md, docs/index.html) - discovery is expected to find
    candidate lines in at least that many distinct files; the exact
    total line count is not pinned here since it is expected to grow
    as the docs evolve, and pinning it would recreate the same
    hand-maintained-list defect this PR removes.

    Known residual blind spots (measured, not hypothetical): this
    assertion will NOT catch a restatement using the bare word
    "implementer" with no first/any/no qualifier (e.g. "do not spawn an
    implementer before a ticket exists"), or one that names no
    "implementer" token at all (e.g. "no engineer or architect spawns
    before a ticket exists", "before the first implementing agent
    spawns"). Widening NARROW_TRIGGER_PATTERN further to catch the bare
    word would misfire on the legitimate "implementer"-as-role-framing
    prose documented in the False-positive reasoning section of this
    file's module docstring."""
    hits = _gate_context_lines()
    offenders = [
        (path, lineno, line)
        for path, lineno, line in hits
        if NARROW_TRIGGER_PATTERN.search(line)
    ]
    assert not offenders, (
        "found "
        f"{len(offenders)} gate-context line(s) restating the narrow "
        "pre-widening trigger ('first implementer' / 'any implementer' / "
        "'no implementer', singular or plural):\n"
        + "\n".join(f"  {p}:{n}: {l.strip()}" for p, n, l in offenders)
    )


def test_discovery_covers_known_historical_files():
    """Sanity check (not a hardcoded pin on line content): the 8 files
    known to have carried the stale restatement must each still surface
    at least one gate-context candidate line, so a future narrowing of
    GATE_CONTEXT_PATTERN can't silently stop scanning them. This list was
    derived by discovering every origin/main file whose narrow-trigger
    restatement matches GATE_CONTEXT_PATTERN + NARROW_TRIGGER_PATTERN
    together - not copied from an earlier draft of this test, which had
    named content/references/delegation-detail.md and content/commands/
    ds-implement-ticket.md (neither ever carried the restatement: the
    former's "implementer" mentions are generic Worker-Autonomy-Contract
    prose with no gate-context keyword nearby; the latter has no
    "implementer" mention at origin/main at all) while omitting README.md
    and content/commands/ds-init-project.md (which both did carry it)."""
    known_files = {
        REPO_ROOT / "README.md",
        REPO_ROOT / "content" / "commands" / "ds-init-project.md",
        REPO_ROOT / "content" / "references" / "conventions-detail.md",
        REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md",
        REPO_ROOT / "content" / "sections" / "02-delegation.md",
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
