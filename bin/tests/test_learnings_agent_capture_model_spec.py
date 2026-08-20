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
    start_idx = text.find(start_heading)
    if start_idx == -1:
        return ""
    start_idx += len(start_heading)
    if end_heading is not None:
        end_idx = text.find(end_heading, start_idx)
        if end_idx != -1:
            return text[start_idx:end_idx]
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
