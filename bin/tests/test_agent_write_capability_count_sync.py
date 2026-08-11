"""
Purpose: Cross-site consistency pin for the "N of 18 agents write files"
         fact and its full name enumeration, which live at 5 sites with no
         mechanical link between them: docs/index.html (two independent
         occurrences), docs/slides/agent-team-slides.md, the full 18-row
         table in content/references/agent-team.md, and the 10-row subset
         table in content/agents/orchestration-planner.md. Round 2 of
         DS-return-contract Unit 4 corrected docs/index.html:1594 to
         "10 of 18" but left :1696 at "7 of 18" in the same commit; round 3
         then hand-found a third stale site in orchestration-planner.md.
         This gate makes that class of disagreement unmergeable instead of
         relying on another manual sweep.

Public API: pytest test functions only; no importable helpers are consumed
         elsewhere.

Upstream dependencies: docs/index.html; docs/slides/agent-team-slides.md;
         content/references/agent-team.md; content/agents/orchestration-
         planner.md; content/agents/*.md (only for the derived master list
         of 18 real agent basenames - never a hand-typed literal).

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests job,
         which runs `pytest bin/tests/ -q` - full-directory glob discovery,
         no per-file wiring required for a new test_*.py file.

Failure modes: pure static analysis, no I/O beyond reading these 4 text
         files plus globbing content/agents/*.md for the master name list.
         This is deliberately a PURE CONSISTENCY pin, not a judgment call
         about whether a Bash-heredoc-only report write counts as "writes
         files" - content/references/agent-team.md's full 18-row table is
         treated as the derived source of truth (it is the only site that
         enumerates every agent with an explicit per-row Yes/No, so it is
         the one site a human edits when the underlying fact changes), and
         every other site is asserted to AGREE with it, both on the
         numeral ("N of 18") and on the full set of writer names. The
         orchestration-planner.md table is a 10-row SUBSET of the 18 (its
         own "Available agents" list, not a full enumeration), so it is
         checked differently: every agent it lists must have the same
         Yes/No writes-files verdict as the full table, not that its
         writer subset sums to the same N.
         Both axes are pinned independently, per the round-4 finding that
         a list can go stale without the number changing: the numeral
         check and the enumeration (name-set) check are separate
         assertions, and both were verified to redden on an isolated
         single-axis mutation (numeral-only, then membership-only) before
         being left in place.

Performance: negligible - reads 4 small text files plus one glob.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "content" / "agents"
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
SLIDES_PATH = REPO_ROOT / "docs" / "slides" / "agent-team-slides.md"
AGENT_TEAM_PATH = REPO_ROOT / "content" / "references" / "agent-team.md"
PLANNER_PATH = REPO_ROOT / "content" / "agents" / "orchestration-planner.md"

# Derived, never a hand-typed literal - the master set of real agent
# basenames under content/agents/*.md.
ALL_AGENT_NAMES = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))

_TABLE_ROW_RE = re.compile(r"^\|\s*`([a-z0-9\-]+)`\s*\|.*\|\s*(Yes|No)\b")
_NUMERAL_RE = re.compile(r"(\d+)\s+of\s+(\d+)")


def _parse_writes_table(text: str) -> dict[str, bool]:
    """Parse a `| \\`name\\` | ... | Yes/No ... |` markdown table into
    {agent_name: writes_files}."""
    result: dict[str, bool] = {}
    for line in text.split("\n"):
        m = _TABLE_ROW_RE.match(line.strip())
        if m:
            result[m.group(1)] = m.group(2) == "Yes"
    return result


def _prose_write_files_lines(text: str) -> list[str]:
    """Every line asserting the 'N of M write files' fact in prose form."""
    return [
        ln
        for ln in text.split("\n")
        if "write files" in ln.lower() and _NUMERAL_RE.search(ln)
    ]


_FULL_AGENT_LIST_RE = re.compile(r"\d+\s+named agents\s*\([^)]*\)", re.IGNORECASE)


def _enumeration_span(line: str) -> str:
    """The substring of a prose line that actually enumerates the writer
    agents. The writer enumeration sits either before or after the literal
    "write files" cue depending on the site's sentence structure (docs/
    index.html lists it after "write files:"; the slides deck lists it
    before "write files -"), so this strips only the one unrelated full-18
    listing that can appear earlier in the same line (docs/index.html's
    opening "18 named agents (...)" parenthetical, which is not the writer
    enumeration) and returns the rest of the line for name matching."""
    return _FULL_AGENT_LIST_RE.sub("", line)


def _names_in_span(span: str) -> set[str]:
    return {
        name
        for name in ALL_AGENT_NAMES
        if re.search(rf"\b{re.escape(name)}\b", span)
    }


def test_full_table_derives_a_plausible_writer_set():
    # Sanity floor: the derived source of truth itself hasn't collapsed.
    full_table = _parse_writes_table(AGENT_TEAM_PATH.read_text(encoding="utf-8"))
    assert len(full_table) == len(ALL_AGENT_NAMES), (
        f"content/references/agent-team.md table has {len(full_table)} rows, "
        f"expected {len(ALL_AGENT_NAMES)} (one per content/agents/*.md file)"
    )
    writer_count = sum(1 for w in full_table.values() if w)
    assert writer_count >= 5, (
        f"derived writer count {writer_count} is implausibly small"
    )


def test_prose_sites_agree_with_full_table_on_numeral_and_enumeration():
    full_table = _parse_writes_table(AGENT_TEAM_PATH.read_text(encoding="utf-8"))
    expected_total = len(full_table)
    expected_writers = {name for name, writes in full_table.items() if writes}
    expected_count = len(expected_writers)

    sites: list[tuple[str, str]] = []
    index_lines = _prose_write_files_lines(INDEX_PATH.read_text(encoding="utf-8"))
    assert len(index_lines) == 2, (
        f"expected exactly 2 'N of M write files' prose lines in docs/index.html, "
        f"found {len(index_lines)}: {index_lines}"
    )
    sites.append(("docs/index.html (The Team card)", index_lines[0]))
    sites.append(("docs/index.html (Key constraint note)", index_lines[1]))

    slides_lines = _prose_write_files_lines(SLIDES_PATH.read_text(encoding="utf-8"))
    assert len(slides_lines) == 1, (
        f"expected exactly 1 'N of M write files' prose line in "
        f"docs/slides/agent-team-slides.md, found {len(slides_lines)}"
    )
    sites.append(("docs/slides/agent-team-slides.md", slides_lines[0]))

    for label, line in sites:
        m = _NUMERAL_RE.search(line)
        assert m is not None, f"{label}: no 'N of M' numeral found in {line!r}"
        stated_n, stated_m = int(m.group(1)), int(m.group(2))
        assert (stated_n, stated_m) == (expected_count, expected_total), (
            f"{label} states '{stated_n} of {stated_m}' but "
            f"content/references/agent-team.md's full table derives "
            f"'{expected_count} of {expected_total}': {line!r}"
        )

        stated_names = _names_in_span(_enumeration_span(line))
        assert stated_names == expected_writers, (
            f"{label} writer enumeration disagrees with content/references/"
            f"agent-team.md's full table.\n"
            f"  missing from {label}: {sorted(expected_writers - stated_names)}\n"
            f"  extra in {label}: {sorted(stated_names - expected_writers)}"
        )


def test_orchestration_planner_subset_table_agrees_with_full_table():
    full_table = _parse_writes_table(AGENT_TEAM_PATH.read_text(encoding="utf-8"))
    planner_table = _parse_writes_table(PLANNER_PATH.read_text(encoding="utf-8"))

    assert len(planner_table) >= 5, (
        f"content/agents/orchestration-planner.md's 'Available agents' table "
        f"parsed only {len(planner_table)} rows - table-format regression?"
    )

    assert set(planner_table) - set(full_table) == {"general-purpose"}, (
        "orchestration-planner.md's subset table has row names with no "
        "matching content/agents/*.md file beyond the known `general-purpose` "
        f"exemption: {sorted((set(planner_table) - set(full_table)) - {'general-purpose'})}"
    )

    for name, writes in planner_table.items():
        if name not in full_table:
            # e.g. `general-purpose` - a real spawn target but not a file
            # under content/agents/*.md, so it has no row to agree with.
            continue
        assert full_table[name] == writes, (
            f"orchestration-planner.md's subset table says `{name}` "
            f"writes_files={writes}, but content/references/agent-team.md's "
            f"full table says writes_files={full_table[name]}"
        )
