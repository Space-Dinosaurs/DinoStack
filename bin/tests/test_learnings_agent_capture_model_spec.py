#!/usr/bin/env python3
"""
Spec tests for the "learnings-agent capture model" documentation axis
(DS-97, 5th attempt): learnings-agent capture is MANDATORY-TRIGGER (gated by
content/references/conductor-operating-rules.md §MANDATORY PROTOCOL GATE),
not discretionary / ad-hoc conductor judgment.

Prior attempts each declared this axis closed and each verification method
was narrower than the claim it certified:
  - a file-scoped check missed 5 of 6 sites
  - a token-scoped check missed semantic variants (e.g. "conductor judgment")
  - a case-sensitive check missed a capitalized "Discretionary capture"

A Skeptic mutation-test pass on this suite itself then found three more
narrowness defects (a line-scoped allowlist that swallowed co-located
violations, a semantic-variant scope that excluded README.md/CONTRIBUTING.md,
and a stale line-number citation) - fixed here without losing any of the
five original catches; see the allowlist and scope-file docstrings below for
the details of each fix.

This suite closes the gap with a case-insensitive literal search PLUS a
semantic-variant search, over content/, docs/slides/*.md, docs/index.html,
README.md, and CONTRIBUTING.md (discretionary-literal scope and
semantic-variant scope now both cover README.md/CONTRIBUTING.md).

Covers:
  - (a) case-insensitive "discretionary" returns exactly the 2 sanctioned
    sites (content/references/conductor-operating-rules.md and
    content/references/capture-classification.md), both of which describe
    what the mandatory gate REPLACED - not a live discretionary-capture claim.
  - (b) semantic variants that assert the superseded model ("conductor
    judgment", "captures learnings ad-hoc", "no automatic phase trigger",
    "conductor-discretionary") return zero hits, excluding the two known
    semantically-unrelated/already-sanctioned uses of "conductor judgment"
    (the correct phase-gate contrast in learnings-pipeline-slides.md, and the
    unrelated re-route prose in docs/index.html).
  - Every failure message names the offending file:line and states why the
    phrasing contradicts the mandatory gate - not just that a count mismatched.

Run with: python3 -m pytest bin/tests/test_learnings_agent_capture_model_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CONTENT_DIR = REPO_ROOT / "content"
SLIDES_DIR = REPO_ROOT / "docs" / "slides"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
README = REPO_ROOT / "README.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"

MANDATORY_GATE_CITATION = (
    "content/references/conductor-operating-rules.md §MANDATORY PROTOCOL GATE"
)

DISCRETIONARY_RE = re.compile(r"discretionary", re.IGNORECASE)

SANCTIONED_DISCRETIONARY_SITES = {
    CONTENT_DIR / "references" / "conductor-operating-rules.md",
    CONTENT_DIR / "references" / "capture-classification.md",
}

SEMANTIC_VARIANT_PATTERNS = [
    re.compile(r"conductor judgment", re.IGNORECASE),
    re.compile(r"captures learnings ad-hoc", re.IGNORECASE),
    re.compile(r"no automatic phase trigger", re.IGNORECASE),
    re.compile(r"conductor-discretionary", re.IGNORECASE),
]

# (path, exact substring expected on the matching line) allowlist for the two
# known uses of "conductor judgment" that are NOT assertions about the
# learnings-agent capture model: the correct phase-gate contrast in
# learnings-pipeline-slides.md, and unrelated /ds-implement-ticket re-route
# prose in docs/index.html that predates this fix.
ALLOWED_SEMANTIC_VARIANT_HITS = {
    (SLIDES_DIR / "learnings-pipeline-slides.md", "phase gate, not conductor judgment"),
    (DOCS_INDEX, "ad-hoc conductor judgment"),
}


def _iter_lines(files):
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            yield path, lineno, line


def _discretionary_literal_scope_files():
    """content/ (recursive) + docs/slides/*.md (non-recursive) + docs/index.html
    + README.md + CONTRIBUTING.md - mirrors:
    grep -rni "discretionary" content/ docs/slides/*.md docs/index.html README.md CONTRIBUTING.md
    """
    files = [p for p in sorted(CONTENT_DIR.rglob("*")) if p.is_file()]
    files += sorted(SLIDES_DIR.glob("*.md"))
    for p in (DOCS_INDEX, README, CONTRIBUTING):
        if p.exists():
            files.append(p)
    return files


def _semantic_variant_scope_files():
    """Same scope as _discretionary_literal_scope_files() - content/ (recursive)
    + docs/slides/*.md (non-recursive) + docs/index.html + README.md +
    CONTRIBUTING.md. A prior revision excluded README.md/CONTRIBUTING.md from
    this scope on the theory that the literal-'discretionary' check already
    covered them - but that only catches the literal word, not the semantic
    variants this function's caller checks for, and README.md/CONTRIBUTING.md
    are the most public surfaces in the set. Reuses
    _discretionary_literal_scope_files() rather than duplicating the file list."""
    return _discretionary_literal_scope_files()


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


# ---------------------------------------------------------------------------
# (a) case-insensitive "discretionary" - exactly the 2 sanctioned sites
# ---------------------------------------------------------------------------

def test_discretionary_case_insensitive_exactly_two_sanctioned_sites():
    files = _discretionary_literal_scope_files()
    hits = [(p, ln, line) for p, ln, line in _iter_lines(files) if DISCRETIONARY_RE.search(line)]

    unexpected = [(p, ln, line) for p, ln, line in hits if p not in SANCTIONED_DISCRETIONARY_SITES]
    assert not unexpected, (
        "Found 'discretionary' (case-insensitive) outside the two sanctioned sites that describe "
        f"what the MANDATORY PROTOCOL GATE ({MANDATORY_GATE_CITATION}) replaced. learnings-agent "
        "capture is MANDATORY-TRIGGER, not discretionary - any other site asserting 'discretionary' "
        "contradicts the gate and must be reworded (this is exactly the failure mode of the prior "
        "4 attempts at closing this axis). Offending site(s): "
        + "; ".join(f"{_rel(p)}:{ln}: {line.strip()!r}" for p, ln, line in unexpected)
    )

    hit_paths = {p for p, _, _ in hits}
    missing = SANCTIONED_DISCRETIONARY_SITES - hit_paths
    assert not missing, (
        "expected sanctioned 'discretionary' site(s) not found (vacuity guard - if these disappear "
        "silently this test would degrade to trivially passing): "
        + ", ".join(sorted(_rel(m) for m in missing))
    )

    assert len(hits) == 2, (
        f"expected exactly 2 case-insensitive 'discretionary' hits (one per sanctioned site describing "
        f"what {MANDATORY_GATE_CITATION} replaced), found {len(hits)}: "
        + ", ".join(f"{_rel(p)}:{ln}" for p, ln, _ in hits)
    )


def test_discretionary_sanctioned_sites_describe_the_gate_replacement():
    # Guard against a coincidental future hit at a sanctioned path that isn't
    # actually the "replaces discretionary ..." framing (e.g. a new, live
    # discretionary-capture claim slipping into the same file).
    files = _discretionary_literal_scope_files()
    hits_by_path: dict[Path, list[tuple[int, str]]] = {}
    for p, ln, line in _iter_lines(files):
        if DISCRETIONARY_RE.search(line) and p in SANCTIONED_DISCRETIONARY_SITES:
            hits_by_path.setdefault(p, []).append((ln, line))

    for path in SANCTIONED_DISCRETIONARY_SITES:
        lines = hits_by_path.get(path, [])
        assert lines, f"{_rel(path)} has no 'discretionary' hit to validate"
        assert any("replaces discretionary" in line.lower() for _, line in lines), (
            f"{_rel(path)} mentions 'discretionary' but not in the sanctioned 'replaces discretionary "
            f"...' framing - verify it still describes what the mandatory gate at "
            f"{MANDATORY_GATE_CITATION} replaced, not a live discretionary-capture claim. "
            f"Lines found: {['%d: %s' % (ln, line.strip()) for ln, line in lines]}"
        )


# ---------------------------------------------------------------------------
# (b) semantic variants of the superseded model - zero hits (excluding the
# two known sanctioned/unrelated uses of "conductor judgment")
# ---------------------------------------------------------------------------

def test_semantic_variants_asserting_superseded_model_are_absent():
    files = _semantic_variant_scope_files()
    violations = []
    for p, ln, line in _iter_lines(files):
        # Pattern-scoped allowlist: strip only the allowlisted substring(s) for
        # this path from the line before matching, so a second, non-allowlisted
        # variant co-located on the same line is still caught. A prior
        # revision excluded the entire line once any allowlisted substring was
        # present anywhere on it, which masked any of the three other
        # semantic-variant patterns landing on the same line as an allowed hit.
        remainder = line
        for allowed_path, sub in ALLOWED_SEMANTIC_VARIANT_HITS:
            if p == allowed_path:
                remainder = remainder.replace(sub, "")
        for pattern in SEMANTIC_VARIANT_PATTERNS:
            if not pattern.search(remainder):
                continue
            violations.append((p, ln, line, pattern.pattern))

    assert not violations, (
        "Found phrasing that asserts learnings-agent capture is discretionary / driven by ad-hoc "
        f"conductor judgment, contradicting the MANDATORY PROTOCOL GATE at {MANDATORY_GATE_CITATION} "
        "(learnings-agent fires on mandatory triggers - see content/references/capture-classification.md "
        "- not conductor discretion). Offending site(s): "
        + "; ".join(
            f"{_rel(p)}:{ln} (matched /{pat}/): {line.strip()!r}"
            for p, ln, line, pat in violations
        )
    )


def test_semantic_variant_allowlist_entries_still_present_and_correctly_scoped():
    # Vacuity guard on the allowlist itself: if either sanctioned "conductor
    # judgment" use disappears or changes wording, the allowlist becomes dead
    # weight and the absence test above would stop meaningfully exercising the
    # exclusion path. Confirm both allowed hits are still found exactly where
    # expected.
    files = _semantic_variant_scope_files()
    found = {(p, sub): False for p, sub in ALLOWED_SEMANTIC_VARIANT_HITS}
    for p, _ln, line in _iter_lines(files):
        for ap, sub in ALLOWED_SEMANTIC_VARIANT_HITS:
            if p == ap and sub in line:
                found[(ap, sub)] = True
    missing = [f"{_rel(p)} containing {sub!r}" for (p, sub), ok in found.items() if not ok]
    assert not missing, (
        "expected sanctioned 'conductor judgment' allowlist site(s) not found - the exclusion in "
        "test_semantic_variants_asserting_superseded_model_are_absent is untested if these vanish: "
        + "; ".join(missing)
    )


# ---------------------------------------------------------------------------
# risk-config-and-tiers.md rationale cell (FIX 1) - regression guard
# ---------------------------------------------------------------------------

def test_learnings_agent_role_table_row_states_mandatory_trigger_capture():
    path = CONTENT_DIR / "references" / "risk-config-and-tiers.md"
    text = path.read_text(encoding="utf-8")
    assert "| learnings-agent | 2 | sonnet | Mandatory-trigger capture |" in text, (
        "learnings-agent role-default-tier table row must read 'Mandatory-trigger capture', not "
        f"'Discretionary capture' - see the MANDATORY PROTOCOL GATE at {MANDATORY_GATE_CITATION}"
    )
    assert "| learnings-agent | 2 | sonnet | Discretionary capture |" not in text


# ---------------------------------------------------------------------------
# learnings-pipeline-slides.md rhetorical-contrast clause (FIX 2) - regression guard
# ---------------------------------------------------------------------------

def test_learnings_pipeline_slides_trigger_contrast_uses_mandatory_language():
    path = SLIDES_DIR / "learnings-pipeline-slides.md"
    text = path.read_text(encoding="utf-8")
    assert (
        "<code>learnings-agent</code> captures the mandatory-trigger events no phase gate would catch."
        in text
    ), (
        "the learning-extractor/learnings-agent trigger-contrast clause must read 'captures the "
        "mandatory-trigger events', not the weaker 'captures ad-hoc session events' framing - the "
        f"literal contrast is true but conveyed a weaker obligation than the gate at "
        f"{MANDATORY_GATE_CITATION} actually establishes"
    )
    assert "captures ad-hoc session events no phase gate would catch" not in text


# ---------------------------------------------------------------------------
# Index-first dedup (DS: learnings.md INDEX section) - the INDEX section
# added to content/templates/.agentic/learnings.md replaces the prior
# read-the-whole-file dedup procedure: learnings-agent and learning-extractor
# now read only the compact `## Index` section (one line per entry) to
# determine ID counters and find dedup candidates, falling back to a
# targeted single-entry read only on a plausible match. The bidirectional
# completeness check below asserts every `## [ID]` entry heading (under
# `## Entries`) has exactly one matching index line (under `## Index`), and
# vice versa - an entry without its index line is a protocol violation the
# next writer must repair, and a phantom index line with no matching entry
# is equally a defect (over-declaration, not just under-declaration).
# ---------------------------------------------------------------------------

LEARNINGS_TEMPLATE = CONTENT_DIR / "templates" / ".agentic" / "learnings.md"

_ENTRY_HEADING_RE = re.compile(r"^## \[((?:LRN|KNW)-\d{8}-\d{3})\]", re.MULTILINE)
_INDEX_LINE_RE = re.compile(r"^- \[((?:LRN|KNW)-\d{8}-\d{3})\]", re.MULTILINE)


def _section_body(text: str, start_heading: str, end_heading: str | None = None) -> str:
    """Return the text strictly between `start_heading` (exclusive) and either
    `end_heading` (if given and found) or the next top-level SECTION heading
    ('## ' not followed by '[' - i.e. not an entry heading like
    '## [LRN-...]'). Returns '' if `start_heading` is absent. Used to scope
    entry/index scanning to the real Index/Entries sections only - the
    '## Format' block above them contains example
    `## [LRN-YYYYMMDD-XXX]`/`## [KNW-YYYYMMDD-XXX]` headings inside a fenced
    code block that must NOT be counted as entries, and (for the '## Entries'
    section with no end_heading) the fallback boundary must not itself match
    the FIRST real entry heading it is supposed to include."""
    start_match = re.search(r"^" + re.escape(start_heading) + r"\s*$", text, re.MULTILINE)
    if start_match is None:
        return ""
    start_idx = start_match.end()
    if end_heading is not None:
        end_match = re.search(
            r"^" + re.escape(end_heading) + r"\s*$", text[start_idx:], re.MULTILINE
        )
        if end_match is not None:
            return text[start_idx : start_idx + end_match.start()]
    match = re.search(r"^## (?!\[)", text[start_idx:], re.MULTILINE)
    return text[start_idx : start_idx + match.start()] if match else text[start_idx:]


def learnings_index_completeness(text: str) -> tuple[list[str], list[str]]:
    """Return (missing_from_index, phantom_in_index): sorted ID lists.

    missing_from_index - entry IDs under '## Entries' with no matching line
    under '## Index'. phantom_in_index - index IDs under '## Index' with no
    matching entry heading under '## Entries'. Bidirectional set equality,
    not one-directional containment (see MEMORY.md's derived-pin discipline -
    a one-directional check misses over-declaration entirely)."""
    index_section = _section_body(text, "## Index", "## Entries")
    entries_section = _section_body(text, "## Entries")
    index_ids = set(_INDEX_LINE_RE.findall(index_section))
    entry_ids = set(_ENTRY_HEADING_RE.findall(entries_section))
    missing_from_index = sorted(entry_ids - index_ids)
    phantom_in_index = sorted(index_ids - entry_ids)
    return missing_from_index, phantom_in_index


def test_learnings_template_has_index_section_before_entries():
    text = LEARNINGS_TEMPLATE.read_text(encoding="utf-8")
    assert "## Index" in text, "content/templates/.agentic/learnings.md is missing the '## Index' section"
    index_pos = text.index("## Index")
    entries_pos = text.index("## Entries")
    assert index_pos < entries_pos, (
        "'## Index' must appear before '## Entries' in "
        "content/templates/.agentic/learnings.md"
    )


def test_learnings_template_index_is_bidirectionally_complete():
    # The template ships with zero entries, so this is the trivial-complete
    # case: both lists must be empty. A real project's .agentic/learnings.md
    # (untracked scaffold output, not present in this repo) inherits the same
    # invariant from the moment it is created from this template.
    text = LEARNINGS_TEMPLATE.read_text(encoding="utf-8")
    missing, phantom = learnings_index_completeness(text)
    assert missing == [], f"template Entries section has entries with no index line: {missing}"
    assert phantom == [], f"template Index section has phantom lines with no matching entry: {phantom}"


_POSITIVE_FIXTURE = """# Learnings

## Format

```markdown
## [LRN-YYYYMMDD-XXX] <title>

**Pattern:** example
```

## Index

- [LRN-20260601-001] example LRN hook
- [KNW-20260601-001] example KNW hook

## Entries

## [LRN-20260601-001] Example LRN title

**Discovered:** 2026-06-01 (session)
**Severity:** Minor
**Domain:** test
**Pattern:** example pattern
**Fix:** example fix
**Source:** test

## [KNW-20260601-001] Example KNW title

**Discovered:** 2026-06-01 (session)
**Domain:** test
**Fact:** example fact
**Why-it-matters:** example
**Source:** test
"""


def test_index_completeness_checker_passes_on_well_formed_fixture():
    # Positive control: the fixture's two entries each have exactly one
    # matching index line, and the '## Format' block's example headings
    # inside the fenced code block are correctly excluded from the scan.
    missing, phantom = learnings_index_completeness(_POSITIVE_FIXTURE)
    assert missing == []
    assert phantom == []


def test_index_completeness_checker_catches_entry_missing_its_index_line():
    # [MUTATION] Remove the KNW entry's index line - simulates an append that
    # wrote the entry body but not its index hook in the same edit.
    mutated = _POSITIVE_FIXTURE.replace("- [KNW-20260601-001] example KNW hook\n", "")
    missing, phantom = learnings_index_completeness(mutated)
    assert missing == ["KNW-20260601-001"], (
        f"expected the checker to catch the entry with no index line, got missing={missing}"
    )
    assert phantom == []


def test_index_completeness_checker_catches_phantom_index_line():
    # [MUTATION] Add an index line with no matching entry - simulates a
    # dangling/over-declared index entry (e.g. the entry was later deleted
    # but its index line was not).
    mutated = _POSITIVE_FIXTURE.replace(
        "- [KNW-20260601-001] example KNW hook\n",
        "- [KNW-20260601-001] example KNW hook\n- [LRN-20260601-999] phantom entry, never written\n",
    )
    missing, phantom = learnings_index_completeness(mutated)
    assert missing == []
    assert phantom == ["LRN-20260601-999"], (
        f"expected the checker to catch the phantom index line, got phantom={phantom}"
    )


def test_index_completeness_checker_excludes_format_block_example_headings():
    # [MUTATION-adjacent regression guard] The '## Format' section's example
    # `## [LRN-YYYYMMDD-XXX] <title>` heading is not a real ID (it is a
    # literal YYYYMMDD/XXX placeholder, which the ID regex does not match
    # anyway) - but this also guards against a future fixture/template using
    # a real-shaped ID in a documentation example leaking into the count.
    fixture_with_realistic_example = _POSITIVE_FIXTURE.replace(
        "## [LRN-YYYYMMDD-XXX] <title>",
        "## [LRN-20260601-001] <title>",
    )
    missing, phantom = learnings_index_completeness(fixture_with_realistic_example)
    assert missing == [] and phantom == [], (
        "a '## [ID]'-shaped heading inside the fenced '## Format' example block must not be "
        f"counted as a real entry; got missing={missing}, phantom={phantom}"
    )


_INDEX_LESS_FIXTURE = """# Learnings

## Entries

## [LRN-20260601-001] Example LRN title

**Discovered:** 2026-06-01 (session)
**Severity:** Minor
**Domain:** test
**Pattern:** example pattern
**Fix:** example fix
**Source:** test

## [KNW-20260601-001] Example KNW title

**Discovered:** 2026-06-01 (session)
**Domain:** test
**Fact:** example fact
**Why-it-matters:** example
**Source:** test
"""


def test_index_completeness_checker_reports_migration_needed_as_all_entries_missing():
    # A legacy file with entries but no '## Index' section at all (predates
    # the Index section's introduction) is reported by this checker as every
    # one of its N entries missing from the index - but this checker is NOT
    # the migration-needed signal a writer actually uses: the writer's real
    # trigger (content/agents/learnings-agent.md Step 0 / the migration
    # paragraph in learning-extractor.md) is the direct, unconditional check
    # "does the file have a '## Index' heading at all", independent of entry
    # count. That distinction matters precisely because this checker's
    # missing-list is empty (not "N missing") for a zero-entry pre-Index
    # file, which would silently look like nothing-to-migrate if the writer
    # mistakenly used this checker's output as its trigger instead of the
    # direct heading-absence check. This test only confirms the checker's own
    # (secondary, diagnostic) behavior on a non-empty legacy file.
    missing, phantom = learnings_index_completeness(_INDEX_LESS_FIXTURE)
    assert missing == ["KNW-20260601-001", "LRN-20260601-001"], (
        f"expected both pre-Index entries reported missing (migration-needed detection), got {missing}"
    )
    assert phantom == []


def test_index_completeness_checker_passes_after_migration_backfill():
    # The same file, after a writer performs the one-time absent-index
    # migration (Step 0 in learnings-agent.md / the migration paragraph in
    # learning-extractor.md): backfilled Index lines make it bidirectionally
    # complete again.
    migrated = _INDEX_LESS_FIXTURE.replace(
        "## Entries",
        "## Index\n\n"
        "- [LRN-20260601-001] Example LRN title\n"
        "- [KNW-20260601-001] Example KNW title\n\n"
        "## Entries",
        1,
    )
    missing, phantom = learnings_index_completeness(migrated)
    assert missing == [], f"post-migration fixture should be bidirectionally complete, got missing={missing}"
    assert phantom == [], f"post-migration fixture should be bidirectionally complete, got phantom={phantom}"


_STRAY_LINE_OUTSIDE_INDEX_FIXTURE = """# Learnings

This file uses the `## Index` section below to speed up dedup.

- [LRN-20260601-666] stray line sitting in prose before the real Index section, must not count

## Index

- [LRN-20260601-001] example LRN hook

## Entries

## [LRN-20260601-001] Example LRN title

**Discovered:** 2026-06-01 (session)
**Severity:** Minor
**Domain:** test
**Pattern:** example pattern
**Fix:** example fix
**Source:** test
"""


def test_index_completeness_checker_ignores_stray_index_shaped_line_outside_real_section():
    # [MUTATION - section-scoping] The fixture's prose above the real '## Index'
    # heading contains both a literal (inline, not line-start) mention of
    # '## Index'/'## Entries' AND a stray '- [ID]'-shaped line. Under a
    # substring-based `text.find("## Index")` / `text.find("## Entries")`
    # section boundary (the pre-fix implementation), the inline mentions are
    # matched as if they were the real headings, pulling the stray line into
    # the computed Index section and reporting it as a phantom index entry -
    # this assertion goes RED under that implementation. Line-anchoring the
    # heading search (requiring the heading alone on its own line) excludes
    # the stray line correctly.
    missing, phantom = learnings_index_completeness(_STRAY_LINE_OUTSIDE_INDEX_FIXTURE)
    assert missing == [], f"expected no missing entries, got {missing}"
    assert phantom == [], (
        "a '- [ID]'-shaped line sitting outside the real '## Index' section (in prose before it) "
        f"must not be counted as an index line, got phantom={phantom}"
    )


# ---------------------------------------------------------------------------
# Agent specs document the index-first dedup procedure, including the
# same-edit index-line obligation (R2 in the ticket's rubric)
# ---------------------------------------------------------------------------

LEARNINGS_AGENT_MD = CONTENT_DIR / "agents" / "learnings-agent.md"
LEARNING_EXTRACTOR_MD = CONTENT_DIR / "agents" / "learning-extractor.md"


def test_learnings_agent_and_learning_extractor_document_index_first_dedup():
    for path in (LEARNINGS_AGENT_MD, LEARNING_EXTRACTOR_MD):
        text = path.read_text(encoding="utf-8")
        assert "index-first" in text.lower(), (
            f"{_rel(path)} no longer documents the index-first dedup procedure"
        )
        assert "## Index" in text, (
            f"{_rel(path)} no longer references the '## Index' section"
        )
        assert "same edit" in text.lower(), (
            f"{_rel(path)} no longer states the same-edit index-line obligation "
            "(an entry appended without its index line is a protocol violation)"
        )
        assert "protocol violation" in text.lower(), (
            f"{_rel(path)} no longer states that an entry without its index line "
            "is a protocol violation the next writer must repair"
        )


def test_learnings_agent_and_learning_extractor_document_absent_index_migration():
    for path in (LEARNINGS_AGENT_MD, LEARNING_EXTRACTOR_MD):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "migration" in lower, (
            f"{_rel(path)} no longer names the absent-index migration owner and procedure"
        )
        assert "one-time" in lower or "one time" in lower, (
            f"{_rel(path)} no longer states the migration is a one-time pass"
        )
        assert "full-file" in lower or "whole file" in lower, (
            f"{_rel(path)} no longer states migration dedup falls back to a full-file read/compare"
        )


def test_learnings_agent_and_learning_extractor_migration_trigger_is_unconditional_on_index_absence():
    # [ROUND-2 RELOCATION FIX] Round 1's Critical (migration trigger gated on
    # a live discretionary-capture-style qualifier) was hand-patched in
    # round 2 into a NEW, still-broken gate: "has one or more `## [ID]`
    # entries under `## Entries` ... and has no `## Index` section" - which
    # left the migration path unreachable for any pre-Index file with zero
    # entries. The round-2 prose-pin (see the "migration"/"one-time"/
    # "full-file" test above) passed anyway, because it pinned generic
    # migration vocabulary, never the trigger CONDITION itself. This test
    # pins the trigger condition directly: the migration mandate reads "no
    # `## Index`" (case-insensitive) with NO adjacent entry-count qualifier,
    # and the file states that a zero-entry pre-Index file also migrates.
    # [MUTATION] Re-adding "has one or more ... entries under `## Entries`,
    # and has no `## Index`" back into either file reddens this test - verify
    # this by temporarily restoring the pre-fix phrasing and re-running.
    for path in (LEARNINGS_AGENT_MD, LEARNING_EXTRACTOR_MD):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "no `## index`" in lower, (
            f"{_rel(path)} does not state the unconditional trigger 'no `## Index`' - the "
            "migration mandate must trigger on '## Index' absence alone, adjacent to the "
            "migration-owner declaration"
        )
        assert "has one or more" not in lower, (
            f"{_rel(path)} still gates the migration trigger on an entry-count qualifier "
            "('has one or more ... entries') - this is the round-1 Critical relocated, not "
            "fixed: it makes migration unreachable for a zero-entry pre-Index file. Delete "
            "the qualifier; the trigger must be unconditional on '## Index' absence alone."
        )
        assert "zero-entry" in lower, (
            f"{_rel(path)} does not state that a zero-entry pre-Index file also migrates "
            "(trivially, producing an empty '## Index' section)"
        )


def test_learnings_agent_and_learning_extractor_resolve_append_only_vs_index_repair():
    for path in (LEARNINGS_AGENT_MD, LEARNING_EXTRACTOR_MD):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "append-only governs" in lower, (
            f"{_rel(path)} still states a bare 'append-only' rule without scoping it to entry "
            "bodies - this reads as forbidding the required Index-repair/migration writes"
        )
        assert "required repair" in lower, (
            f"{_rel(path)} does not state that inserting a missing index line is required repair, "
            "not an append-only violation"
        )


def test_learnings_agent_and_learning_extractor_disclose_index_invariant_enforcement_scope():
    for path in (LEARNINGS_AGENT_MD, LEARNING_EXTRACTOR_MD):
        text = path.read_text(encoding="utf-8")
        assert "CI-enforced only for the shipped template" in text, (
            f"{_rel(path)} does not disclose that the bidirectional Index invariant is mechanically "
            "enforced only for the shipped (zero-entry) template, and is a writer obligation on a "
            "live consumer project's committed .agentic/learnings.md"
        )


def test_wrap_ticket_scopes_id_extraction_to_entries_section():
    path = CONTENT_DIR / "agents" / "wrap-ticket.md"
    text = path.read_text(encoding="utf-8")
    assert "## Entries" in text, (
        f"{_rel(path)} Phase 11b extraction no longer references the '## Entries' section"
    )
    assert "index" in text.lower() and "hook" in text.lower(), (
        f"{_rel(path)} does not explain why extraction must be scoped away from '## Index' "
        "hook lines, which match the same ID-shaped regex"
    )


# ---------------------------------------------------------------------------
# Round-3 regression pins (Skeptic round 4)
# ---------------------------------------------------------------------------

def test_wrap_ticket_states_pre_migration_fallback_never_zero_matching_entries():
    # [MUTATION] Delete the "Pre-migration fallback:" sentence (or its "Never
    # silently treat a pre-migration file as zero matching entries" clause)
    # from content/agents/wrap-ticket.md - this assertion goes RED.
    path = CONTENT_DIR / "agents" / "wrap-ticket.md"
    text = path.read_text(encoding="utf-8")
    assert "Pre-migration fallback:" in text, (
        f"{_rel(path)} no longer states the 'Pre-migration fallback:' clause for a "
        "'.agentic/learnings.md' with no '## Entries' heading yet (predates the Index "
        "section and no writer has migrated it)"
    )
    assert "Never silently treat a pre-migration file as zero matching entries" in text, (
        f"{_rel(path)} no longer states the explicit warning against silently treating a "
        "pre-migration file as zero matching entries - without it, Phase 11b extraction can "
        "silently drop every learning in an unmigrated file"
    )


def test_learning_extractor_has_single_learnings_header_and_scoped_append_only():
    # [MUTATION] Restore round-2's divergent second '# Learnings' header block
    # in content/agents/learning-extractor.md (or reintroduce a bare
    # 'Append-only.' line, i.e. the unscoped rule this round's fix replaced
    # with 'Append-only governs entry bodies, not the Index.') - either
    # mutation goes RED. The negative assertions are scoped so the legitimate
    # qualified wording ("Append-only governs entry bodies") still passes.
    path = CONTENT_DIR / "agents" / "learning-extractor.md"
    text = path.read_text(encoding="utf-8")

    header_matches = re.findall(r"^# Learnings\s*$", text, re.MULTILINE)
    assert len(header_matches) == 0, (
        f"{_rel(path)} contains a second, divergent '# Learnings' header block - this file "
        "must have a single shape for the template/procedure it documents, not two competing "
        f"copies. Found {len(header_matches)} bare '# Learnings' header line(s)."
    )

    bare_append_only = re.findall(r"^Append-only\.\s*$", text, re.MULTILINE)
    assert not bare_append_only, (
        f"{_rel(path)} contains a bare, unscoped 'Append-only.' line - this reads as forbidding "
        "the required Index-repair/migration writes. The rule must be scoped, e.g. "
        "'Append-only governs entry bodies, not the Index.'"
    )
    assert "append-only governs entry bodies" in text.lower(), (
        f"{_rel(path)} lost the scoped 'Append-only governs entry bodies, not the Index.' "
        "wording while checking for the unscoped form"
    )
