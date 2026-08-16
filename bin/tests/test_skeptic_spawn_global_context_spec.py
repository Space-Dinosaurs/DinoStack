#!/usr/bin/env python3
"""
Spec test for DS-112: every Skeptic-spawn-constructing template in
content/commands/ must carry the 7-field "Global-context inputs" block (or a
live, non-dangling pointer to content/references/skeptic-protocol.md Section
4.5, which defines the canonical block) so a conductor copying the template
verbatim does not produce a prompt that fails Skeptic Step 0.

Live-validated defect: content/commands/ds-skeptic.md's spawn template
listed only 3 of the 4 required Skeptic-spawn inputs (what-to-review, the
adversarial brief, the resolved-issues preflight) and omitted the
Global-context input set entirely - fired as an unconditional Step-0
BLOCKED in a live session before this fix.

This is a defect class that recurs when closed one site at a time (DS-98
precedent; two prior DS-112 passes already missed sites before this one).
The corrected standard, applied on this third pass: a site needs the block
if a conductor following it would assemble a Skeptic prompt. Prescriptive
input enumerations count - "include:", "includes:", "receives:", "spawn ...
with:", numbered or bulleted input lists near a Skeptic spawn - regardless
of directory. Generic prose about "the Skeptic reviews X" does not.
Enumeration of every site checked, with include/exclude reasoning:

INCLUDED (constructs an actual spawn prompt a conductor would copy,
verified to lack the block prior to this fix):
  - content/commands/ds-skeptic.md               (Step 2 Skeptic template)
  - content/commands/ds-implement-ticket.md       (Phase 3b architect-plan
    review, Phase 5 per-unit spawning, Phase 5 integration Skeptic, Phase 6
    main spawn template, Section 14 meta-Skeptic spawn brief)
  - content/commands/ds-init-project.md           (CLAUDE.md split Skeptic)
  - content/commands/ds-ticket-triage.md          (Phase 4b artifact Skeptic)
  - content/commands/ds-wrap.md                   (Step 2 context-file
    Skeptic, Part E memory-compression Skeptic)
  - content/references/agent-team.md              (":195" architect-plan
    review "include:" list, ":200" engineer-output review "include:" list -
    both are prescriptive spawn-input enumerations in the same shape as the
    command templates above; a conductor following either verbatim assembles
    a prompt missing all 6 Global-context fields. Originally excluded in the
    first pass of this fix as "mentions Skeptic review generically" - that
    reasoning did not survive scrutiny: these are "when spawning `skeptic`
    for X review, include:" lists, i.e. exactly the defect class this test
    guards against. DS-112 follow-up.)
  - content/references/planning-artifacts.md     (":98" Skeptic-on-Brief
    spawn in the Brief-tier authoring sequence step 8, ":103" Plan-tier
    second-pass Skeptic reviewing the assembled Plan - both are prescriptive
    "spawn Skeptic on X" steps in the canonical authoring sequence a
    conductor executes verbatim. Missed in both prior DS-112 passes because
    the file was excluded wholesale as "narrative/rule prose" without
    checking whether its authoring-sequence numbered steps are themselves
    spawn-input enumerations - they are. Third-pass fix.)
  - content/commands/ds-brief.md                  (":221" "After architect
    returns: spawn Skeptic using the operator-confirmed variant" - a
    prescriptive spawn step in the Brief hand-off flow, not the generic
    Section 6 variant-selection prose that was the basis for the prior
    exclusion. The prior exclusion reasoning conflated "selects which brief
    text to use" (Section 6, still correctly excluded on its own) with "the
    site that actually spawns the Skeptic" (this step) - they are different
    parts of the same file. Third-pass fix.)

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
  - content/commands/ds-brief.md Section 6   (selects which adversarial-brief
    variant text to use based on `brief_source`; does not itself enumerate
    spawn inputs - the actual spawn step at ":221" is now covered above)
  - content/commands/ds-cost.md, ds-feedback-triage.md, ds-help.md,
    ds-status.md, ds-test-suite-comprehension.md
    (mention Skeptic only in narrative/reporting prose; none construct a
    spawn-input list)
  - content/agents/architect.md, content/agents/engineer.md,
    content/agents/learning-extractor.md, content/agents/goal-condition-evaluator.md,
    content/agents/learnings-agent.md, content/agents/qa-engineer.md,
    content/agents/security-auditor.md, content/agents/orchestration-planner.md,
    content/agents/product-discovery.md, content/agents/wrap-ticket.md
    (mention "Skeptic" only in constraint/description prose; none spawn one)
  - content/references/conductor-operating-rules.md, conventions-detail.md,
    cross-session-loop-resume.md, delegation-detail.md, design-goals.md,
    digest-return-pattern.md, events-log.md,
    qa-gate.md, qa-regression-obligation.md, regression-test-obligation.md,
    risk-config-and-tiers.md, role-models.md, spawn-presets.md,
    subagent-protocol.md, task-state-file.md, trigger-catalog.md,
    frontend-discipline.md, ticket-rework.md
    (all mention Skeptic spawning in narrative/rule prose - tier resolution,
    loop mechanics, model selection, digest fields, prior-attempt callouts -
    none contain a prescriptive "include:"/"receives:"/"spawn ... with:" list
    of spawn-prompt inputs; re-swept for the DS-112 third-pass per the
    corrected standard above)
  - content/sections/**.md                  (kernel restatements of the
    rules above; same reasoning - narrative, not spawn-input enumerations)

The Section 4.5 "Global-Context Input Set" definition itself, and its
Section 14 "Supplemental-context block" carve-out for `security-auditor`/
`perf-analyst`, live in content/references/skeptic-protocol.md and are the
canonical block this test's other sites point at - they are not themselves
"spawn template sites" in the enumeration sense EXCEPT for the Section 14
"Meta-Skeptic spawn brief" subsection, which is its own prescriptive
"The meta-Skeptic receives:" list and is now included above alongside its
content/commands/ds-implement-ticket.md counterpart.

content/agents/skeptic.md already delegates to Section 4.5 by reference
(confirmed live below) and is excluded from the per-site block check for
that reason - it is the agent definition, not a spawn-prompt template.

Total sites carrying the block after this pass: 8 (6 from the first two
DS-112 passes, plus planning-artifacts.md and ds-brief.md from this pass) -
9 distinct spawn shapes counting skeptic-protocol.md's own meta-Skeptic
list, which the file `content/references/skeptic-protocol.md` earns
inclusion for as a spawn-template site alongside its role as the Section
4.5 canonical definition.

Run with: python3 -m pytest bin/tests/test_skeptic_spawn_global_context_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMMANDS_DIR = REPO_ROOT / "content" / "commands"
REFERENCES_DIR = REPO_ROOT / "content" / "references"
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
    COMMANDS_DIR / "ds-brief.md",
    REFERENCES_DIR / "agent-team.md",
    REFERENCES_DIR / "planning-artifacts.md",
    SKEPTIC_PROTOCOL,
]

# Minimum number of "Global-context inputs" occurrences expected per file -
# a file with multiple distinct Skeptic spawn sites needs the block (or a
# pointer naming it) at each site, not just once anywhere in the file.
MIN_OCCURRENCES = {
    COMMANDS_DIR / "ds-skeptic.md": 1,
    COMMANDS_DIR / "ds-implement-ticket.md": 5,  # Phase 3b, per-unit, integration, Phase 6, meta-Skeptic
    COMMANDS_DIR / "ds-init-project.md": 1,
    COMMANDS_DIR / "ds-ticket-triage.md": 1,
    COMMANDS_DIR / "ds-wrap.md": 2,  # Step 2 context-file review, Part E compression
    COMMANDS_DIR / "ds-brief.md": 1,  # Turn N+k step 7 Skeptic-on-Brief spawn
    REFERENCES_DIR / "agent-team.md": 2,  # architect-plan review, engineer-output review
    REFERENCES_DIR / "planning-artifacts.md": 2,  # Skeptic-on-Brief step 8, Plan-tier second-pass
    SKEPTIC_PROTOCOL: 3,  # Section 4.5 heading, heading-distinction cross-ref, Section 14 meta-Skeptic list
}


# Field-7 regression guard (Skeptic PR #729 round-1 Major 2 / Minor 1): a
# case-insensitive marker pattern for the "conductor spawn brief" field added
# to the Global-context block. A site can spell the marker as the literal
# "field 7" (e.g. "field 7 per §4.5"), as "7 fields" (a whole-block count
# restatement, e.g. the meta-Skeptic sites), or as "conductor spawn brief"
# (the field's own name, e.g. ds-skeptic.md's numbered "7. Conductor spawn
# brief" template line, which never spells out "field 7" literally). A single
# line commonly matches more than one alternative (e.g. "field 7 (conductor
# spawn brief) is ..."), which inflates the count above the floor rather than
# masking a drop - the assertion is a floor (>=), not an exact count, so this
# is safe.
FIELD_7_MARKER_RE = re.compile(r"field 7|7 fields|conductor spawn brief", re.IGNORECASE)

# Minimum number of field-7 marker occurrences expected per file - the floor
# is the actual measured count at the time this guard was added (DS-112
# follow-up, PR #729 rework). A future edit that silently drops the
# conductor-spawn-brief field from any of these 13 spawn-prompt-constructing
# sites (11 originally enumerated plus the 2 planning-artifacts.md sites
# discovered during PR #729) - or from the canonical Section 4.5 definition
# and its agent-team.md restatements - reduces the count below this floor.
FIELD_7_MIN_OCCURRENCES = {
    COMMANDS_DIR / "ds-skeptic.md": 1,
    COMMANDS_DIR / "ds-implement-ticket.md": 5,
    COMMANDS_DIR / "ds-init-project.md": 2,
    COMMANDS_DIR / "ds-ticket-triage.md": 2,
    COMMANDS_DIR / "ds-wrap.md": 4,
    COMMANDS_DIR / "ds-brief.md": 2,
    REFERENCES_DIR / "agent-team.md": 4,
    REFERENCES_DIR / "planning-artifacts.md": 4,
    SKEPTIC_PROTOCOL: 7,
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


def test_every_spawn_template_site_carries_field_7() -> None:
    """Every enumerated Skeptic-spawn-constructing site must also carry the
    field-7 (conductor spawn brief) marker at least as many times as it was
    measured to at the time this guard was added. This is the direct
    regression guard for the live-validated defect: a prior round of this PR
    added field 7 to the Global-context block everywhere but left
    bin/tests/test_skeptic_spawn_global_context_spec.py's own docstring
    asserting the stale 6-field count, with no mechanical check that field 7
    itself stays present at every site going forward."""
    failures = []
    for path, expected_min in FIELD_7_MIN_OCCURRENCES.items():
        text = _read(path)
        count = len(FIELD_7_MARKER_RE.findall(text))
        if count < expected_min:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: found {count} field-7 marker "
                f"occurrence(s) (pattern: 'field 7' / '7 fields' / 'conductor "
                f"spawn brief', case-insensitive), expected at least {expected_min}"
            )
    assert not failures, (
        "Skeptic spawn template(s) missing the field-7 (conductor spawn "
        "brief) marker (regression - a conductor copying the template "
        "verbatim would produce a Global-context block missing field 7):\n"
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


def test_set_shaped_claim_discipline_heading_is_non_dangling() -> None:
    """DS-176: content/agents/skeptic.md's new Rules bullet points at
    skeptic-protocol.md's '### Set-shaped claim discipline' heading - if
    that heading is ever renamed or removed, the pointer goes dangling
    silently (no build failure, no runtime error). Mirrors
    test_skeptic_agent_delegates_by_reference's non-dangling-pointer shape."""
    agent_text = _read(SKEPTIC_AGENT)
    assert "Set-shaped claim discipline" in agent_text, (
        f"{SKEPTIC_AGENT} no longer points at the Set-shaped claim discipline "
        "section (Rules bullet removed or reworded)"
    )
    protocol_text = _read(SKEPTIC_PROTOCOL)
    assert "### Set-shaped claim discipline" in protocol_text, (
        f"{SKEPTIC_PROTOCOL} no longer carries the '### Set-shaped claim "
        "discipline' heading the skeptic.md Rules bullet points at"
    )
