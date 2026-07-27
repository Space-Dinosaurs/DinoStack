#!/usr/bin/env python3
"""
Spec tests for the "learnings-agent capture model" documentation axis
(DS-97, 5th attempt): learnings-agent capture is MANDATORY-TRIGGER (gated by
the MANDATORY PROTOCOL GATE at content/references/conductor-operating-rules.md:91),
not discretionary / ad-hoc conductor judgment.

Prior attempts each declared this axis closed and each verification method
was narrower than the claim it certified:
  - a file-scoped check missed 5 of 6 sites
  - a token-scoped check missed semantic variants (e.g. "conductor judgment")
  - a case-sensitive check missed a capitalized "Discretionary capture"

This suite closes the gap with a case-insensitive literal search PLUS a
semantic-variant search, over content/, docs/slides/*.md, docs/index.html,
README.md, and CONTRIBUTING.md (discretionary-literal scope also covers
README.md/CONTRIBUTING.md; semantic-variant scope is content/, docs/slides/*.md,
and docs/index.html per the spec).

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

MANDATORY_GATE_CITATION = "content/references/conductor-operating-rules.md:91"

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
    """content/ (recursive) + docs/slides/*.md (non-recursive) + docs/index.html.
    README.md/CONTRIBUTING.md are intentionally excluded from this scope per
    the spec (the semantic-variant check targets the methodology/doc surface
    the discretionary phrasing was actually found on)."""
    files = [p for p in sorted(CONTENT_DIR.rglob("*")) if p.is_file()]
    files += sorted(SLIDES_DIR.glob("*.md"))
    if DOCS_INDEX.exists():
        files.append(DOCS_INDEX)
    return files


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
        for pattern in SEMANTIC_VARIANT_PATTERNS:
            if not pattern.search(line):
                continue
            if any(p == ap and sub in line for ap, sub in ALLOWED_SEMANTIC_VARIANT_HITS):
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
