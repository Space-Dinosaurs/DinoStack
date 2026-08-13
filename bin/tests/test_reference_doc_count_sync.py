#!/usr/bin/env python3
"""
Regression guard for the reference-doc count drift (DS-141 Skeptic Major).

The number of files in content/references/ is a reality-asserting quantity:
the DS-141 evidence-on-disk.md addition bumped it 33 -> 34 and the count had
to be manually synced across six doc sites. That drift was caught by a Skeptic,
not by CI. This spec pins every count site to the LIVE count
(len(content/references/*.md)) - derived, never a hardcoded literal - so a
future reference doc added without updating every site now fails here instead
of silently drifting against a stale number.

Count sites covered:
  - ADAPTERS.md                        : "The <N> reference docs"
  - README.md                          : "**Reference docs** (<N> files)"
  - CONTRIBUTING.md                    : "the <N> reference docs" plus the
                                         parenthesized name enumeration, which
                                         must name exactly <N> real docs
  - docs/slides/contributing-slides.md : "<N> reference docs" at both sites
  - content/SKILL.md                   : every `**references/<name>.md**`
                                         bullet resolves to a real file, and
                                         evidence-on-disk.md (the doc that
                                         triggered this drift) is listed
  - docs/index.html                    : the evidence-on-disk.md node is in the
                                         Referenced Protocol Documents grid
  - docs/components.md                 : "**Reference docs** (<N> .md docs
                                         plus <M> example .yml files" against
                                         the live content/references/ counts
                                         for both extensions (PR #719 fixed a
                                         33 -> 39 drift here; the site was
                                         previously unpinned)

docs/index.html's grid is a curated subset, not a full enumeration - it lists
a fraction of the files and carries pre-existing stale names (e.g. graphify.md,
wrap-deferred.md) that are not content/references files, so a full "every doc
has a node" assertion is not mechanically derivable from repo state. The guard
pins the specific node that triggered this drift instead.

Run with: python3 -m pytest bin/tests/test_reference_doc_count_sync.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REFERENCES_DIR = REPO_ROOT / "content" / "references"

ADAPTERS_PATH = REPO_ROOT / "ADAPTERS.md"
README_PATH = REPO_ROOT / "README.md"
CONTRIBUTING_PATH = REPO_ROOT / "CONTRIBUTING.md"
SLIDES_PATH = REPO_ROOT / "docs" / "slides" / "contributing-slides.md"
SKILL_PATH = REPO_ROOT / "content" / "SKILL.md"
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
COMPONENTS_PATH = REPO_ROOT / "docs" / "components.md"

# The doc whose addition bumped the count 33 -> 34 and triggered this finding.
DRIFT_TRIGGER_DOC = "evidence-on-disk"


@pytest.fixture(scope="module")
def reference_stems() -> list[str]:
    """Live set of reference-doc basenames (without .md), derived from repo
    state. 'Derived, not pinned' - the expected set is never a hardcoded list."""
    return sorted(p.stem for p in REFERENCES_DIR.glob("*.md"))


@pytest.fixture(scope="module")
def reference_count(reference_stems) -> int:
    return len(reference_stems)


def _stated_counts(text: str, pattern: str) -> list[int]:
    return [int(m) for m in re.findall(pattern, text, re.IGNORECASE)]


def test_derived_count_is_plausible(reference_count):
    # Sanity floor: the derived count is the ground truth this spec enforces.
    # A collapse below this floor means content/references/ itself lost files.
    assert reference_count >= 30, (
        f"reference-doc count {reference_count} is implausibly small"
    )


def test_adapters_md_count_matches(reference_count):
    text = ADAPTERS_PATH.read_text(encoding="utf-8")
    counts = _stated_counts(text, r"the (\d+) reference docs")
    assert counts, "ADAPTERS.md must state a reference-doc count"
    assert all(c == reference_count for c in counts), (
        f"ADAPTERS.md states {counts} reference docs, expected {reference_count}"
    )


def test_readme_count_matches(reference_count):
    text = README_PATH.read_text(encoding="utf-8")
    match = re.search(r"\*\*Reference docs\*\* \((\d+) files\)", text)
    assert match, (
        "README.md reference-docs line must state the count as "
        "'**Reference docs** (<N> files)'"
    )
    stated = int(match.group(1))
    assert stated == reference_count, (
        f"README.md states {stated} reference-doc files, expected {reference_count}"
    )


def test_contributing_count_and_enumeration_match(reference_count, reference_stems):
    text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
    match = re.search(r"the (\d+) reference docs \(([^)]*)\)", text, re.IGNORECASE)
    assert match, (
        "CONTRIBUTING.md must state 'the <N> reference docs' with a "
        "parenthesized name enumeration"
    )
    stated = int(match.group(1))
    names = [n.strip() for n in match.group(2).split(",")]
    assert stated == reference_count, (
        f"CONTRIBUTING.md states {stated} reference docs, expected {reference_count}"
    )
    assert len(names) == stated, (
        f"CONTRIBUTING.md enumeration lists {len(names)} names but states {stated}"
    )
    assert len(set(names)) == len(names), (
        "CONTRIBUTING.md enumeration contains duplicate reference-doc names"
    )
    missing = [stem for stem in reference_stems if stem not in names]
    assert not missing, (
        f"CONTRIBUTING.md enumeration is missing reference docs: {missing}"
    )
    extra = [name for name in names if name not in reference_stems]
    assert not extra, (
        f"CONTRIBUTING.md enumeration names non-reference-docs: {extra}"
    )


def test_slides_count_matches_at_all_sites(reference_count):
    text = SLIDES_PATH.read_text(encoding="utf-8")
    counts = _stated_counts(text, r"(\d+) reference docs")
    assert len(counts) >= 2, (
        f"contributing-slides.md must state the count at both sites, "
        f"found {len(counts)}"
    )
    assert all(c == reference_count for c in counts), (
        f"contributing-slides.md states {counts} reference docs, "
        f"expected {reference_count} at every site"
    )


def test_components_md_counts_match(reference_count, reference_stems):
    text = COMPONENTS_PATH.read_text(encoding="utf-8")
    md_match = re.search(r"\*\*Reference docs\*\* \((\d+) \.md docs", text)
    assert md_match, (
        "docs/components.md must state the count as "
        "'**Reference docs** (<N> .md docs ...'"
    )
    stated_md = int(md_match.group(1))
    assert stated_md == reference_count, (
        f"docs/components.md states {stated_md} reference-doc .md files, "
        f"expected {reference_count}"
    )

    yml_match = re.search(r"plus (\d+) example \.yml files", text)
    assert yml_match, (
        "docs/components.md must state the example .yml count as "
        "'plus <M> example .yml files'"
    )
    live_yml = len(list(REFERENCES_DIR.glob("*.yml")))
    stated_yml = int(yml_match.group(1))
    assert stated_yml == live_yml, (
        f"docs/components.md states {stated_yml} example .yml files, "
        f"expected {live_yml}"
    )


def test_skill_md_lists_only_real_reference_docs(reference_stems):
    text = SKILL_PATH.read_text(encoding="utf-8")
    listed = re.findall(r"\*\*references/([a-z0-9-]+)\.md\*\*", text)
    assert listed, (
        "content/SKILL.md must list reference docs in its Reference Docs section"
    )
    phantom = [name for name in listed if name not in reference_stems]
    assert not phantom, (
        f"content/SKILL.md references non-existent docs: {phantom}"
    )


def test_skill_md_lists_drift_trigger_doc(reference_stems):
    assert DRIFT_TRIGGER_DOC in reference_stems, (
        f"content/references/{DRIFT_TRIGGER_DOC}.md must exist"
    )
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert f"**references/{DRIFT_TRIGGER_DOC}.md**" in text, (
        f"content/SKILL.md must list references/{DRIFT_TRIGGER_DOC}.md - the "
        "doc whose addition triggered this guard"
    )


def test_index_html_has_drift_trigger_node():
    text = INDEX_PATH.read_text(encoding="utf-8")
    marker = "Referenced Protocol Documents"
    assert marker in text, (
        "docs/index.html must contain the Referenced Protocol Documents grid"
    )
    grid_text = text[text.index(marker):]
    node_forms = (
        f'node-protocol">{DRIFT_TRIGGER_DOC}.md',
        f'node-protocol"><a href="{DRIFT_TRIGGER_DOC}.md"',
    )
    assert any(form in grid_text for form in node_forms), (
        f"docs/index.html Referenced Protocol Documents grid must contain a "
        f"node for {DRIFT_TRIGGER_DOC}.md - the doc whose addition triggered "
        "this guard"
    )
