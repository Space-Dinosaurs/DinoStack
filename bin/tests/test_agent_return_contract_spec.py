"""
Purpose: Spec gate enforcing the MECHANICAL/ADVISORY return-contract tagging
         convention (content/references/subagent-return-contract.md) on every
         content/agents/*.md Output format section: every field must be
         tagged [MECHANICAL] or folded under a Notes [ADVISORY] block, and
         every non-enum MECHANICAL field must declare a numeric cap in its
         own header text.

Public API: check_contract(text, filename) -> list[str] (violations; empty
            list means compliant). Also collected as pytest test functions.

Upstream dependencies: content/agents/*.md (real agent files, allowlisted
            below); bin/tests/fixtures/agent_return_contract/*.md (fixtures
            used to verify the checker logic itself, independent of the
            allowlist).

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests job,
            which runs `pytest bin/tests/ -q` - full-directory glob
            discovery, no per-file wiring required for a new test_*.py file.

Failure modes: pure static analysis, no I/O beyond reading .md files under
            this repo. NOT_YET_MIGRATED below allowlists every real agent
            file that HAS a recognized return-contract heading as of Unit 0
            (the contract doc + this gate ship before any content/agents/*.md
            file adopts the tagging convention - see
            content/references/subagent-return-contract.md "Migration
            status"). Unit 1 must remove a file from NOT_YET_MIGRATED only
            once that file's return-contract section is actually migrated;
            leaving a migrated file in the allowlist silently disables
            enforcement for it (test_allowlist_has_no_stale_entries only
            catches files that no longer exist, not files that were
            migrated but never removed from the set).
            NO_STRUCTURED_RETURN_SECTION separately tracks files with no
            recognized return-contract heading at all (verified against the
            live tree - see the heading-synonym decision below); these are
            not silently folded into NOT_YET_MIGRATED because they are not
            expected to gain a `## Output format`-shaped section under the
            current design.
            The real content/agents/*.md corpus embeds its field templates
            inside fenced ``` code blocks that themselves contain example
            `##`-level lines (e.g. debugger.md's `## Diagnosis: [...]`
            inside its Output format template) - a naive "first `^## `
            after the start heading" section-end scan truncates the section
            at that in-fence line. The extractor below tracks fenced-code
            spans and skips any candidate section-end match that falls
            inside one.

Performance: negligible - reads <20 small text files.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "content" / "agents"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "agent_return_contract"

# Heading synonyms verified against the live content/agents/*.md corpus
# (not trusted from any prior description). Each of these headings was
# individually confirmed to introduce the agent's OWN return-contract
# section, not an unrelated section that merely shares vocabulary:
#   - "Output format"    - the majority case (debugger, architect, ...)
#   - "Sign-off format"  - skeptic.md:118, explicitly the agent's own
#                            structured return ("The conductor validates
#                            this format exactly.")
#   - "Report structure" - dependency-auditor.md, perf-analyst.md,
#                            release-orchestrator.md, each an explicit
#                            "output this exact report" instruction
#   - "Output templates" - product-discovery.md:157, the agent's own
#                            proposal-file templates
# "Message format" (learnings-agent.md:71) was considered and REJECTED:
# on that file it documents the *conductor's inbound* message fields, not
# the agent's own return - learnings-agent's actual return lives under
# "### 6. Return" (learnings-agent.md:197), a Workflow sub-step, not a
# top-level section at all. Treating "Message format" as a synonym would
# have made the gate parse the wrong section's fields. learnings-agent.md
# is therefore in NO_STRUCTURED_RETURN_SECTION below, not NOT_YET_MIGRATED.
HEADING_SYNONYMS = (
    "Output format",
    "Sign-off format",
    "Report structure",
    "Output templates",
)
SECTION_START_RE = re.compile(
    r"^##\s+(?:" + "|".join(re.escape(h) for h in HEADING_SYNONYMS) + r")\s*$",
    re.MULTILINE,
)
SECTION_END_RE = re.compile(r"^##\s+\S", re.MULTILINE)
FENCE_RE = re.compile(r"^```.*$", re.MULTILINE)
HEADER_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)
TAG_RE = re.compile(r"\[(MECHANICAL|ADVISORY)([^\]]*)\]")
CAP_RE = re.compile(
    r"\b(?:cap(?:ped)?\s*(?:at)?\s*[:\-]?\s*|<=\s*|max(?:imum)?\s*(?:of)?\s*)(\d+)\s*"
    r"(chars?|characters?|items?|steps?|entries|words)\b",
    re.IGNORECASE,
)

# Unit 0 ships this gate + content/references/subagent-return-contract.md
# only - it does not touch any content/agents/*.md file, so every existing
# agent file with a recognized return-contract heading predates the
# tagging convention and is allowlisted here. Unit 1 removes each file
# from this set as it migrates that file's section to the tagging
# convention.
NOT_YET_MIGRATED = {
    "architect.md",
    "debugger.md",
    "dependency-auditor.md",
    "engineer.md",
    "goal-condition-evaluator.md",
    "investigator.md",
    "orchestration-planner.md",
    "perf-analyst.md",
    "product-discovery.md",
    "qa-engineer.md",
    "release-orchestrator.md",
    "security-auditor.md",
    "skeptic.md",
}

# Files with NO recognized return-contract heading at all (verified via
# `grep -n "^## " content/agents/*.md` against the live tree, 2026-08-11):
# adr-drift-detector.md, adr-generator.md, and wrap-ticket.md have no such
# section under any name; learning-extractor.md likewise has none;
# learnings-agent.md has a "## Message format" heading but it documents
# inbound fields, not the agent's own return (see HEADING_SYNONYMS comment
# above) - its actual return is an unheaded Workflow sub-step. These are
# tracked separately from NOT_YET_MIGRATED because they are not expected
# to gain a `## Output format`-shaped section under the current design;
# folding them into NOT_YET_MIGRATED would silently claim "has a section,
# just not tagged yet," which is false for all five.
NO_STRUCTURED_RETURN_SECTION = {
    "adr-drift-detector.md",
    "adr-generator.md",
    "learning-extractor.md",
    "learnings-agent.md",
    "wrap-ticket.md",
}


def _fenced_spans(text):
    """Return a list of (start, end) character spans covered by fenced
    ``` code blocks, pairing consecutive fence markers as open/close.
    Assumes fences are balanced (verified against the live corpus)."""
    marks = list(FENCE_RE.finditer(text))
    return [
        (marks[i].start(), marks[i + 1].end())
        for i in range(0, len(marks) - 1, 2)
    ]


def extract_output_format_section(text):
    """Return the text of the agent's own return-contract section (matched
    via HEADING_SYNONYMS), or None if no recognized heading is present.

    The section end is the first top-level '## ' heading that is NOT
    itself inside a fenced code block - the real corpus embeds example
    '##'-level lines inside the very code fence that documents the field
    template (e.g. debugger.md's '## Diagnosis: [...]'), and those must
    not be mistaken for the section boundary.
    """
    start_m = SECTION_START_RE.search(text)
    if not start_m:
        return None
    rest = text[start_m.end():]
    fenced = _fenced_spans(rest)
    for end_m in SECTION_END_RE.finditer(rest):
        pos = end_m.start()
        if any(s <= pos < e for s, e in fenced):
            continue
        return rest[:pos]
    return rest


def extract_fields(section_text):
    """Return [(header_text, body_text), ...] for each '###' field in the section."""
    headers = list(HEADER_RE.finditer(section_text))
    fields = []
    for i, hm in enumerate(headers):
        header_text = hm.group(1).strip()
        body_start = hm.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(section_text)
        fields.append((header_text, section_text[body_start:body_end]))
    return fields


def check_contract(text, filename="<fixture>"):
    """Return a list of human-readable violation strings; [] means compliant."""
    section = extract_output_format_section(text)
    if section is None:
        return [
            f"{filename}: no recognized return-contract heading found "
            f"(tried: {', '.join(HEADING_SYNONYMS)})"
        ]
    fields = extract_fields(section)
    if not fields:
        return [f"{filename}: no '###' fields found in the Output format section"]

    violations = []
    for header_text, _body_text in fields:
        tag_m = TAG_RE.search(header_text)
        if not tag_m:
            violations.append(
                f"{filename}: field '{header_text}' has no [MECHANICAL] or "
                "[ADVISORY] tag"
            )
            continue

        tag, tag_extra = tag_m.group(1), tag_m.group(2)
        if tag == "ADVISORY":
            if "notes" not in header_text.lower():
                violations.append(
                    f"{filename}: field '{header_text}' is tagged [ADVISORY] but "
                    "is not folded under a 'Notes' header"
                )
            continue

        # MECHANICAL: enum fields are exempt from the numeric-cap requirement
        # (the enum's own closed value set is the bound).
        if "enum" in tag_extra.lower():
            continue

        # The cap must be anchored to the field's own header/tag text (per
        # the tagging convention: "declared in the field's own bullet/header
        # text - not left implicit"), NOT searched across the whole body.
        # A body-wide search lets unrelated prose elsewhere in the field
        # (e.g. "at max 3 items of supporting evidence" in an unrelated
        # sentence) satisfy the cap requirement for a field that never
        # actually declared one.
        if not CAP_RE.search(header_text):
            violations.append(
                f"{filename}: MECHANICAL field '{header_text}' declares no "
                "numeric cap in its own header (expected e.g. "
                "'[MECHANICAL, cap: 500 chars]') and is not tagged 'enum'"
            )
    return violations


def _read_fixture(name):
    return (FIXTURES_DIR / name).read_text()


def _real_agent_files():
    return sorted(AGENTS_DIR.glob("*.md"))


# --- Fixture-based checker correctness tests (independent of the allowlist) ---


def test_compliant_fixture_is_contract_compliant():
    text = _read_fixture("compliant_agent.md")
    assert check_contract(text, "compliant_agent.md") == []


def test_fixture_missing_tag_is_flagged():
    text = _read_fixture("missing_tag_agent.md")
    violations = check_contract(text, "missing_tag_agent.md")
    assert violations, "expected a violation for an untagged field"
    assert any("no [MECHANICAL] or [ADVISORY] tag" in v for v in violations)


def test_fixture_missing_cap_is_flagged():
    text = _read_fixture("missing_cap_agent.md")
    violations = check_contract(text, "missing_cap_agent.md")
    assert violations, "expected a violation for a MECHANICAL field with no cap"
    assert any("declares no numeric cap" in v for v in violations)


def test_fenced_template_fixture_is_contract_compliant():
    """
    Reproduces the REAL content/agents/*.md corpus shape (verified against
    debugger.md et al.): the field template lives inside a fenced code
    block that itself contains a '##'-level example line
    ('## Diagnosis: [...]'). Before the fence-aware fix, SECTION_END_RE
    matched that in-fence '##' line and truncated the section to ~30-140
    chars before it ever reached a '###' field - this fixture proves the
    extractor now correctly walks past it to the real end of section
    ('## Rules').
    """
    text = _read_fixture("compliant_fenced_template_agent.md")
    violations = check_contract(text, "compliant_fenced_template_agent.md")
    assert violations == [], violations


def test_cap_requirement_ignores_unrelated_body_prose():
    """
    A MECHANICAL field with no cap declared in its own header must still be
    flagged even when its body contains unrelated cap-shaped prose (e.g.
    'at max 3 items of supporting evidence') that has nothing to do with
    this field's own cap. Proves CAP_RE is anchored to header_text only,
    not searched across the whole field body.
    """
    text = _read_fixture("missing_cap_unrelated_body_prose_agent.md")
    violations = check_contract(text, "missing_cap_unrelated_body_prose_agent.md")
    assert violations, (
        "expected a cap violation even though unrelated body prose contains "
        "a cap-shaped phrase"
    )
    assert any("declares no numeric cap" in v for v in violations)


# --- Real content/agents/*.md enforcement ---


def test_not_yet_migrated_files_are_accounted_for():
    """
    Every discovered content/agents/*.md file is either contract-compliant
    or present in NOT_YET_MIGRATED or NO_STRUCTURED_RETURN_SECTION. A file
    that is in none of those (e.g. a new agent file added without following
    the tagging convention, or without being classified) fails here rather
    than silently passing unnoticed.
    """
    for path in _real_agent_files():
        if path.name in NOT_YET_MIGRATED or path.name in NO_STRUCTURED_RETURN_SECTION:
            continue
        violations = check_contract(path.read_text(), path.name)
        assert violations == [], (
            f"{path.name} is not in NOT_YET_MIGRATED or "
            f"NO_STRUCTURED_RETURN_SECTION and is not contract-compliant: "
            f"{violations}"
        )


def test_not_yet_migrated_entries_are_actually_unmigrated():
    """
    The other half of the Unit-1 migration contract: every file listed in
    NOT_YET_MIGRATED must still be genuinely non-compliant when checked
    directly (independent of the skip in
    test_not_yet_migrated_files_are_accounted_for above). Migrating a
    file's return-contract section makes it contract-compliant; if that
    file is left on NOT_YET_MIGRATED anyway, THIS assertion goes red - a
    Unit-1 migration that forgets to shrink NOT_YET_MIGRATED for a file it
    just migrated is caught here, not silently passed. Shrinking the
    allowlist (removing the now-migrated file) is the only way to make
    this suite green again for that file.
    """
    for name in sorted(NOT_YET_MIGRATED):
        path = AGENTS_DIR / name
        violations = check_contract(path.read_text(), name)
        assert violations != [], (
            f"{name} is listed in NOT_YET_MIGRATED but its return-contract "
            "section is already fully contract-compliant - remove it from "
            "NOT_YET_MIGRATED so test_not_yet_migrated_files_are_accounted_for "
            "starts enforcing it"
        )


def test_allowlist_has_no_stale_entries():
    """NOT_YET_MIGRATED and NO_STRUCTURED_RETURN_SECTION must only name
    files that currently exist."""
    discovered = {p.name for p in _real_agent_files()}
    stale = (NOT_YET_MIGRATED | NO_STRUCTURED_RETURN_SECTION) - discovered
    assert stale == set(), (
        "NOT_YET_MIGRATED/NO_STRUCTURED_RETURN_SECTION name files that no "
        f"longer exist: {sorted(stale)}"
    )


def test_allowlists_are_disjoint():
    """A file must not be classified as both 'has an unmigrated section'
    and 'has no section at all' - the two allowlists are mutually
    exclusive by construction."""
    overlap = NOT_YET_MIGRATED & NO_STRUCTURED_RETURN_SECTION
    assert overlap == set(), f"files present in both allowlists: {sorted(overlap)}"


# Note: there is deliberately no `discovered == NOT_YET_MIGRATED |
# NO_STRUCTURED_RETURN_SECTION` equality test here. That was the shape of
# the pre-fix bug (test_allowlist_covers_all_discovered_agent_files_today):
# it would go red on every successful Unit-1 migration, since a migrated
# file is correctly REMOVED from NOT_YET_MIGRATED without being added
# anywhere else, legitimately shrinking the union over time.
# test_not_yet_migrated_files_are_accounted_for already provides the
# subset-safe equivalent (any file outside both allowlists must be
# contract-compliant), which is what actually catches an unclassified new
# agent file without blocking legitimate migrations.
