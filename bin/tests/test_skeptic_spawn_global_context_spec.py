#!/usr/bin/env python3
"""
Spec test for DS-112: every Skeptic-spawn-constructing template in
content/commands/ must carry the 6-field "Global-context inputs" block (or a
live, non-dangling pointer to content/references/skeptic-protocol.md Section
4.5, which defines the canonical block) so a conductor copying the template
verbatim does not produce a prompt that fails Skeptic Step 0.

Live-validated defect: content/commands/ds-skeptic.md's spawn template
listed only 3 of the 4 required Skeptic-spawn inputs (what-to-review, the
adversarial brief, the resolved-issues preflight) and omitted the
Global-context input set entirely - fired as an unconditional Step-0
BLOCKED in a live session before this fix.

This is a defect class that recurs when closed one site at a time (DS-98
precedent). Enumeration of every site checked, with include/exclude
reasoning:

INCLUDED (constructs an actual spawn prompt a conductor would copy,
verified to lack the block prior to this fix):
  - content/commands/ds-skeptic.md               (Step 2 Skeptic template)
  - content/commands/ds-implement-ticket.md       (Phase 3b architect-plan
    review, Phase 5 per-unit spawning, Phase 5 integration Skeptic, Phase 6
    main spawn template)
  - content/commands/ds-init-project.md           (CLAUDE.md split Skeptic)
  - content/commands/ds-ticket-triage.md          (Phase 4b artifact Skeptic)
  - content/commands/ds-wrap.md                   (Step 2 context-file
    Skeptic, Part E memory-compression Skeptic)

EXCLUDED (mentions Skeptic review generically, or delegates to another
command's own spawn template, or is a Tier-1 leaf agent that never spawns a
Skeptic at all - none of these construct a fill-in prompt of their own):
  - content/commands/ds-configure-team.md   (routing/suppression prose only)
  - content/commands/ds-status.md           (risk-table summary prose only)
  - content/commands/ds-wrap-deferred.md     (explicitly spawns nothing)
  - content/commands/ds-prune-harness.md     (delegates to
    /ds-update-agentic-engineering's own review, no template)
  - content/commands/ds-representation-audit.md (delegates to
    /ds-update-agentic-engineering's own review, no template)
  - content/commands/ds-memory-update.md     (queries past spawns, does not
    spawn one)
  - content/commands/ds-brief.md             (delegates to the standard
    architect-plan-review flow, no template of its own)
  - content/agents/architect.md, content/agents/learning-extractor.md,
    content/agents/goal-condition-evaluator.md, content/agents/learnings-agent.md
    (mention "Skeptic" only in constraint/description prose; none spawn one)

content/agents/skeptic.md already delegates to Section 4.5 by reference
(confirmed live below) and is excluded from the per-site block check for
that reason - it is the agent definition, not a spawn-prompt template.

Run with: python3 -m pytest bin/tests/test_skeptic_spawn_global_context_spec.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMMANDS_DIR = REPO_ROOT / "content" / "commands"
SKEPTIC_PROTOCOL = REPO_ROOT / "content" / "references" / "skeptic-protocol.md"
SKEPTIC_AGENT = REPO_ROOT / "content" / "agents" / "skeptic.md"

# Anchor heading Section 4.5 uses in skeptic-protocol.md - the live pointer
# check below fails if this heading is ever renamed without updating the
# pointer text these sites use to reference it.
SECTION_4_5_HEADING = "## 4.5. Global-Context Input Set"

# Sites that construct an actual Skeptic spawn prompt and therefore MUST
# carry the "Global-context inputs" heading (a caller filling in placeholders
# must end up with that literal heading in the assembled prompt).
SPAWN_TEMPLATE_SITES = [
    COMMANDS_DIR / "ds-skeptic.md",
    COMMANDS_DIR / "ds-implement-ticket.md",
    COMMANDS_DIR / "ds-init-project.md",
    COMMANDS_DIR / "ds-ticket-triage.md",
    COMMANDS_DIR / "ds-wrap.md",
]

# Minimum number of "Global-context inputs" occurrences expected per file -
# a file with multiple distinct Skeptic spawn sites needs the block (or a
# pointer naming it) at each site, not just once anywhere in the file.
MIN_OCCURRENCES = {
    COMMANDS_DIR / "ds-skeptic.md": 1,
    COMMANDS_DIR / "ds-implement-ticket.md": 4,  # Phase 3b, per-unit, integration, Phase 6
    COMMANDS_DIR / "ds-init-project.md": 1,
    COMMANDS_DIR / "ds-ticket-triage.md": 1,
    COMMANDS_DIR / "ds-wrap.md": 2,  # Step 2 context-file review, Part E compression
}


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def test_section_4_5_anchor_exists() -> None:
    """The canonical block definition must exist at the heading every site
    points to - otherwise every 'see Section 4.5' pointer below is dangling."""
    text = _read(SKEPTIC_PROTOCOL)
    assert SECTION_4_5_HEADING in text, (
        f"{SKEPTIC_PROTOCOL} is missing the '{SECTION_4_5_HEADING}' heading - "
        "every command-file pointer to Section 4.5 is now dangling"
    )


def test_skeptic_agent_delegates_by_reference() -> None:
    """content/agents/skeptic.md must carry a live, non-dangling pointer to
    Section 4.5 rather than a duplicated inline copy of the block."""
    text = _read(SKEPTIC_AGENT)
    assert "Global-context" in text, (
        f"{SKEPTIC_AGENT} no longer mentions the Global-context input set"
    )
    assert "Section 4.5" in text, (
        f"{SKEPTIC_AGENT} no longer points at skeptic-protocol.md Section 4.5"
    )


def test_every_spawn_template_site_carries_the_block() -> None:
    """Every enumerated Skeptic-spawn-constructing command file must contain
    the '## Global-context inputs' heading (the literal text a filled-in
    prompt would carry) at least as many times as it has distinct spawn
    sites. This is the direct regression guard for the live-validated
    defect: ds-skeptic.md's template previously had zero occurrences."""
    failures = []
    for path in SPAWN_TEMPLATE_SITES:
        text = _read(path)
        count = text.count("Global-context inputs")
        expected_min = MIN_OCCURRENCES[path]
        if count < expected_min:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: found {count} occurrence(s) of "
                f"'Global-context inputs', expected at least {expected_min}"
            )
    assert not failures, (
        "Skeptic spawn template(s) missing the Global-context inputs block "
        "(DS-112 regression - a conductor copying the template verbatim "
        "would produce a prompt that fails Skeptic Step 0):\n"
        + "\n".join(failures)
    )


def test_every_spawn_template_site_points_at_section_4_5() -> None:
    """Every enumerated site must also cite Section 4.5 as the canonical
    format definition, not just the bare heading text (guards against a
    future edit that adds the heading text without the explanatory pointer,
    which would leave the n/a-rationale rules and Step-0 semantics
    undiscoverable from the template site)."""
    failures = []
    for path in SPAWN_TEMPLATE_SITES:
        text = _read(path)
        if "Section 4.5" not in text:
            failures.append(str(path.relative_to(REPO_ROOT)))
    assert not failures, (
        "Skeptic spawn template(s) missing a 'Section 4.5' pointer to the "
        "canonical Global-context block format:\n" + "\n".join(failures)
    )
