"""
Purpose: Spec gate enforcing the MECHANICAL/ADVISORY return-contract tagging
         convention (content/references/subagent-return-contract.md) on every
         content/agents/*.md Output format section: every field must be
         tagged [MECHANICAL] or folded under a Notes [ADVISORY] block, and
         every non-enum MECHANICAL field must declare a numeric cap in its
         own header/body text.

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
            file as of Unit 0 (the contract doc + this gate ship before any
            content/agents/*.md file adopts the tagging convention - see
            content/references/subagent-return-contract.md "Migration
            status"). Unit 1 must remove a file from NOT_YET_MIGRATED only
            once that file's Output format section is actually migrated;
            leaving a migrated file in the allowlist silently disables
            enforcement for it (test_allowlist_has_no_stale_entries only
            catches files that no longer exist, not files that were
            migrated but never removed from the set).

Performance: negligible - reads <20 small text files.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "content" / "agents"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "agent_return_contract"

SECTION_START_RE = re.compile(r"^##\s+Output format\s*$", re.MULTILINE)
SECTION_END_RE = re.compile(r"^##\s+\S", re.MULTILINE)
HEADER_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)
TAG_RE = re.compile(r"\[(MECHANICAL|ADVISORY)([^\]]*)\]")
CAP_RE = re.compile(
    r"\b(?:cap(?:ped)?\s*(?:at)?\s*[:\-]?\s*|<=\s*|max(?:imum)?\s*(?:of)?\s*)(\d+)\s*"
    r"(chars?|characters?|items?|steps?|entries|words)\b",
    re.IGNORECASE,
)

# Unit 0 ships this gate + content/references/subagent-return-contract.md
# only - it does not touch any content/agents/*.md file, so every existing
# agent file predates the tagging convention and is allowlisted here.
# Unit 1 removes each file from this set as it migrates that file's Output
# format section to the tagging convention.
NOT_YET_MIGRATED = {
    "adr-drift-detector.md",
    "adr-generator.md",
    "architect.md",
    "debugger.md",
    "dependency-auditor.md",
    "engineer.md",
    "goal-condition-evaluator.md",
    "investigator.md",
    "learning-extractor.md",
    "learnings-agent.md",
    "orchestration-planner.md",
    "perf-analyst.md",
    "product-discovery.md",
    "qa-engineer.md",
    "release-orchestrator.md",
    "security-auditor.md",
    "skeptic.md",
    "wrap-ticket.md",
}


def extract_output_format_section(text):
    """Return the text of the '## Output format' section, or None if absent."""
    start_m = SECTION_START_RE.search(text)
    if not start_m:
        return None
    rest = text[start_m.end():]
    end_m = SECTION_END_RE.search(rest)
    return rest[: end_m.start()] if end_m else rest


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
        return [f"{filename}: no '## Output format' section found"]
    fields = extract_fields(section)
    if not fields:
        return [f"{filename}: no '###' fields found in the Output format section"]

    violations = []
    for header_text, body_text in fields:
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

        if not CAP_RE.search(header_text) and not CAP_RE.search(body_text):
            violations.append(
                f"{filename}: MECHANICAL field '{header_text}' declares no "
                "numeric cap (expected e.g. 'cap: 500 chars' or '<=15 steps') "
                "and is not tagged 'enum'"
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


# --- Real content/agents/*.md enforcement ---


def test_not_yet_migrated_files_are_accounted_for():
    """
    Every discovered content/agents/*.md file is either contract-compliant
    or present in NOT_YET_MIGRATED. A file that is neither (e.g. a new agent
    file added without following the tagging convention, or the allowlist)
    fails here rather than silently passing unnoticed.
    """
    for path in _real_agent_files():
        if path.name in NOT_YET_MIGRATED:
            continue
        violations = check_contract(path.read_text(), path.name)
        assert violations == [], (
            f"{path.name} is not in NOT_YET_MIGRATED and is not "
            f"contract-compliant: {violations}"
        )


def test_allowlist_has_no_stale_entries():
    """NOT_YET_MIGRATED must only name files that currently exist."""
    discovered = {p.name for p in _real_agent_files()}
    stale = NOT_YET_MIGRATED - discovered
    assert stale == set(), (
        f"NOT_YET_MIGRATED names files that no longer exist: {sorted(stale)}"
    )


def test_allowlist_covers_all_discovered_agent_files_today():
    """
    As of Unit 0, no content/agents/*.md file has migrated yet, so the
    allowlist should equal the full discovered set. This test documents that
    starting state and will need updating (shrinking NOT_YET_MIGRATED) as
    Unit 1 migrates files - it deliberately does not use a >= / subset
    check, so a Unit-1 migration that forgets to shrink NOT_YET_MIGRATED is
    caught here rather than passing silently forever.
    """
    discovered = {p.name for p in _real_agent_files()}
    assert discovered == NOT_YET_MIGRATED, (
        "content/agents/*.md file set has diverged from NOT_YET_MIGRATED - "
        "if this is because a file was migrated, remove it from "
        "NOT_YET_MIGRATED (test_not_yet_migrated_files_are_accounted_for "
        "will then enforce compliance for it); if a new agent file was "
        "added, add it to NOT_YET_MIGRATED or migrate it immediately."
    )
