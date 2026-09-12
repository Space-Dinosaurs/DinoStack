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
HOOKS_AGENTS = REPO_ROOT / "hooks" / "AGENTS.md"

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
# agent-team.md's floor was raised 4 -> 6 in round 5 (Skeptic Major 1,
# 7a855583 review): round 4 widened its two field-7-referencing bullets
# ("the ban is not limited to field 7 or the brief") from 4 to 6
# occurrences, and the floor must track the live count exactly - it was
# at zero slack (matching the live count precisely) before round 4, which
# is what made it load-bearing as an anti-regression floor rather than
# a loose minimum. Re-verify this floor against a live re-count on any
# future edit to that file, not by trusting this comment's arithmetic.
# ds-skeptic.md's floor was raised 1 -> 2 in round 6 (this round's own
# re-derivation, `39bee732` review): round 3 added a "not only field 7"
# scope-widening sentence to the spawn template's Global-context inputs
# block, which is itself a field-7 marker match, moving the live count
# from 1 to 2 while the floor stayed at 1 (zero slack at origin/main,
# nonzero at HEAD) - the exact "floor with zero slack silently gains
# slack" shape this guard exists to catch. Re-verify against a live
# re-count on any future edit to that file.
FIELD_7_MIN_OCCURRENCES = {
    COMMANDS_DIR / "ds-skeptic.md": 2,
    COMMANDS_DIR / "ds-implement-ticket.md": 5,
    COMMANDS_DIR / "ds-init-project.md": 2,
    COMMANDS_DIR / "ds-ticket-triage.md": 2,
    COMMANDS_DIR / "ds-wrap.md": 4,
    COMMANDS_DIR / "ds-brief.md": 2,
    REFERENCES_DIR / "agent-team.md": 6,
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


def test_neutrality_scope_disclosure_prose_pinned() -> None:
    """Round-2 (977d1450) resolved its Skeptic Major by widening the
    neutrality-scope-disclosure prose in content/commands/ds-skeptic.md
    (the brief '[Neutrality: ...]' note at the Adversarial-brief line, and
    the new '## Global-context inputs' header paragraph) plus
    content/references/skeptic-protocol.md's '### Scope of the ban'
    subsection - deliberately choosing prose over a mechanical rule
    because those sites are otherwise unpinned by any test. Round-3
    Major 1 closes that gap with distinctive multi-word phrase pins
    (never a bare identifier, which substring containment could defeat).
    Reddening mutation for each assertion: delete or narrow the pinned
    phrase back toward its pre-round-2 wording."""
    ds_skeptic = _read(COMMANDS_DIR / "ds-skeptic.md")
    protocol = _read(SKEPTIC_PROTOCOL)

    # ds-skeptic.md brief "[Neutrality: ...]" note (Adversarial-brief line).
    # Mutation: replace with the round-1 field-7-only wording, e.g.
    # "[Neutrality: no conductor hypothesis in field 7]".
    assert (
        "no conductor hypothesis, suspicion, or attention-steer, in any "
        "field or form; see skeptic-protocol.md Section 7 \"Scope of the "
        "ban: every field, every form, tagged or untagged\"" in ds_skeptic
    ), (
        f"{COMMANDS_DIR / 'ds-skeptic.md'} brief '[Neutrality: ...]' note "
        "no longer carries the every-field scope disclosure, including "
        "its trailing 'tagged or untagged' qualifier"
    )

    # ds-skeptic.md "## Global-context inputs" header paragraph. Mutation:
    # delete this paragraph outright (it did not exist pre-round-2).
    assert (
        "no sentence in fields 1-7, the brief above, or the resolved-issues "
        "preflight below may carry a conductor hypothesis, suspicion, or "
        "attention-steer in any form, tagged or untagged" in ds_skeptic
    ), (
        f"{COMMANDS_DIR / 'ds-skeptic.md'} is missing the Global-context "
        "header paragraph's every-field neutrality-scope disclosure, "
        "including its 'tagged or untagged' qualifier"
    )

    # skeptic-protocol.md "### Scope of the ban" subsection. Mutation:
    # delete the subsection heading or the "steering by exclusion" clause
    # (part of the observed-forms enumeration that names the exclusion
    # shape distinct from a bare assertion or disjunctive question).
    assert (
        "### Scope of the ban: every field, every form, tagged or untagged"
        in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} is missing the '### Scope of the ban' "
        "subsection heading"
    )
    assert "steering by exclusion rather than by naming a target" in protocol, (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "steering-by-exclusion observed-forms clause"
    )

    # Round-4's Skeptic (7a855583) found round-3's sweep applied a wording
    # test ("pin 3 already contains 'tagged or untagged'") rather than the
    # instructed load-bearing test, leaving three clauses this section
    # depends on unpinned. Round-5 closes those three specifically.

    # "partial disclosure" observed-forms clause (line ~557) - names the
    # shape this branch is titled for: a doubt disclosed with its target
    # but not its content. Load-bearing for: the enumeration actually
    # covering the branch's own namesake failure mode, not just the five
    # forms named in earlier rounds. Mutation: delete this clause from the
    # enumeration (leaving the other six forms intact).
    assert (
        "a partial disclosure that withholds a doubt's content while "
        "still naming its target" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' observed-forms enumeration "
        "is missing the partial-disclosure clause"
    )

    # "does not neutralize" sentence (line ~559) - load-bearing for: a
    # provenance tag being insufficient, by itself, to clear a conductor's
    # own conclusion for reviewer consumption. Without this sentence the
    # section states the ban is wide (every field, every form) but never
    # actually forecloses the "I tagged it, so it's fine" reading it
    # exists to close. Mutation: delete the sentence.
    assert (
        "it does not neutralize a conductor's own conclusion into "
        "something the reviewer may inherit" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "provenance-tag-does-not-neutralize sentence"
    )

    # Supersession sentence (line ~561) - load-bearing for: THIS wide
    # scope statement winning over any narrower field- or category-scoped
    # restatement elsewhere in the document (or the hook's docstring),
    # which is what makes the widening binding rather than merely
    # additional prose competing with older, narrower text. Mutation:
    # delete the supersession clause, leaving only the carve-out sentence.
    assert (
        "supersedes any narrower field- or category-specific restatement "
        "elsewhere in this document or in the hook's docstring" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "supersession sentence over narrower restatements"
    )


def test_round7_unpinned_scope_sentences_pinned() -> None:
    """Round-7: round-6's Task-2 enumeration claimed every sentence in
    "### Scope of the ban" not newly pinned that round was already covered
    by test_neutrality_scope_disclosure_prose_pinned,
    test_round4_widened_clauses_pinned, or test_docstring_states_bounded_scope.
    That claim was false for three sentences - a repo-wide literal-string
    search on each confirmed no test referenced any of them. Each was
    verified unpinned by execution before this test was added (apply the
    mutation, observe the full suite still passes, then restore).

    Sentence 1 - the section's own scope statement (the breadth clause
    naming all seven Global-context inputs, the brief, and the
    resolved-issues preflight, "in every syntactic form"). Load-bearing
    for: this is the pre-branch scope the whole branch exists to widen -
    the single most load-bearing sentence in the section. Mutation
    (executed, left `77 passed`): narrow "It applies to every field of a
    Skeptic spawn prompt - each of the seven Global-context inputs
    (Section 4.5), the adversarial brief ... and the resolved-issues
    preflight - in every syntactic form." down to "It applies to
    Global-context field 7 and the adversarial brief." The pinned heading
    survives that mutation unchanged, so a heading/body contradiction was
    otherwise invisible to every existing test.

    Sentence 2 - "A scope permission, instruction, or acceptance criterion
    given to a different agent is not a claim and is not disclosed as
    one." Load-bearing for: distinguishing an instruction given to a
    DIFFERENT agent (e.g. an engineer's acceptance criteria) from a claim
    about the artifact under review - without this sentence, the
    surrounding "does not neutralize" text reads as though any brief
    content addressed to another role must itself be disclosed as a
    claim. Mutation (executed, left `2362 passed, 126 subtests passed`):
    delete the sentence outright.

    Sentence 3 - "The reviewing Skeptic's Step 3.9 Neutrality check is the
    control for the remainder, scanning every Global-context field and the
    adversarial brief." Load-bearing for: the section explicitly names
    which control covers the part the hook's own bounded mechanical
    enforcement does not - without it, "Mechanical enforcement below
    covers a bounded subset only and is not a substitute" names a gap but
    never names what fills it. Mutation (executed, left `77 passed`):
    delete the sentence.
    """
    protocol = _read(SKEPTIC_PROTOCOL)

    assert (
        "each of the seven Global-context inputs (Section 4.5), the "
        "adversarial brief and any attack-surface probe or "
        "domain-extension sentence within it, and the resolved-issues "
        "preflight - in every syntactic form" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection's own scope "
        "statement has been narrowed - missing the every-field, "
        "every-syntactic-form breadth clause"
    )

    assert (
        "A scope permission, instruction, or acceptance criterion given "
        "to a different agent is not a claim and is not disclosed as "
        "one." in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "scope-permission-is-not-a-claim sentence"
    )

    assert (
        "The reviewing Skeptic's Step 3.9 Neutrality check is the "
        "control for the remainder, scanning every Global-context field "
        "and the adversarial brief." in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "Step-3.9-is-the-control-for-the-remainder sentence"
    )


def test_round4_widened_clauses_pinned() -> None:
    """Round-4 (7a855583) widened three pre-existing clauses from a
    narrower ('Neutrality requirement (independent of completeness)')
    scope to the wider every-field scope ('Scope of the ban: every
    field, every form, tagged or untagged'): two bullets in
    content/references/agent-team.md (:200, :206) and one bullet in
    content/references/subagent-protocol.md (:425). Round-5 (Skeptic
    Minor) pins the widening itself, since reverting all three to their
    pre-round-4 wording left the suite green. Pins use the distinctive
    widening language and its pointer text, deliberately NOT a count of
    'field 7' tokens - a count-based pin here would double-count against
    FIELD_7_MIN_OCCURRENCES and reintroduce the same slack-tracking
    problem that caused round-4's Major 1 (the floor and this pin must
    stay independent checks). Mutation for each assertion: revert the
    matching clause to its pre-round-4 wording (see the f540fb74 diff).

    Round-6 (this round's own re-derivation): the agent-team.md
    assertion was previously an exact `== 2` count, which is NOT
    independent of the floor it claims to avoid coupling with - it
    fails the moment a legitimate third spawn-site bullet adopts the
    same widening clause (verified: adding a third occurrence pushed
    agent_team.count() to 3 and reddened this assertion, while
    FIELD_7_MIN_OCCURRENCES' floor of 6 tolerated the extra field-7
    marker it also introduces without complaint - the two checks were
    never symmetric under growth). Changed to a floor (`>=2`), matching
    the `>=` semantics MIN_OCCURRENCES and FIELD_7_MIN_OCCURRENCES
    already use elsewhere in this file, so a legitimate third site
    passes both checks instead of failing this one alone.
    Mutation for the floor: reduce the real count to 1 (remove one of
    the two existing widening-clause bullets) and confirm this
    assertion reddens."""
    agent_team = _read(REFERENCES_DIR / "agent-team.md")
    subagent_protocol = _read(REFERENCES_DIR / "subagent-protocol.md")

    # agent-team.md - both the plan-review and engineer-output-review
    # bullets gained the identical trailing widening clause. Load-bearing
    # for: the ban applying to every Global-context field at both spawn
    # sites, not just the field the sentence happens to be discussing.
    widening_clause = (
        ", in this or any other field; the ban is not limited to field 7 "
        "or the brief (see `content/references/skeptic-protocol.md` "
        "Section 7 \"Scope of the ban: every field, every form, tagged "
        "or untagged\")."
    )
    occurrences = agent_team.count(widening_clause)
    assert occurrences >= 2, (
        f"{REFERENCES_DIR / 'agent-team.md'}: expected the round-4 widening "
        f"clause at both the plan-review and engineer-output-review "
        f"bullets (at least 2 occurrences), found {occurrences}"
    )

    # subagent-protocol.md :425 - the "Priming adversarial briefs" Rules
    # bullet gained an explicit extension beyond field 7 into every other
    # Global-context field and the resolved-issues preflight, plus the
    # same pointer retarget. Load-bearing for: the Rules-list restatement
    # of the ban not silently narrower than the canonical section it
    # points to.
    assert (
        "or, per the wider rule, into any other Global-context field or "
        "the resolved-issues preflight, tagged or untagged" in subagent_protocol
    ), (
        f"{REFERENCES_DIR / 'subagent-protocol.md'} 'Priming adversarial "
        "briefs' bullet is missing the round-4 every-field widening clause"
    )
    # Round-2 (spawn-brief-neutrality-recipient-scope) update: the trailing
    # "for the full rule" was scoped to "for the full Skeptic-specific
    # elaboration" once Section 11 of this same file became the general,
    # recipient-wide canonical site - the pinned substring still requires
    # the citation to point at "Scope of the ban", not the pre-round-4
    # narrower "Neutrality requirement" section, which is the actual
    # load-bearing property this assertion protects.
    assert (
        'Section 7 "Scope of the ban: every field, every form, tagged or '
        'untagged" for the full Skeptic-specific elaboration' in subagent_protocol
    ), (
        f"{REFERENCES_DIR / 'subagent-protocol.md'} 'Priming adversarial "
        "briefs' bullet still points at the pre-round-4 narrower "
        "'Neutrality requirement' section instead of 'Scope of the ban'"
    )


def test_round6_sweep_closes_remaining_unpinned_widening_sites() -> None:
    """Round-6 full-cumulative-diff sweep (origin/main..HEAD) found four
    load-bearing sentences this branch's own prose added that no test
    anywhere in the suite covered, verified by reverting each to its
    pre-branch wording and confirming a targeted pytest run stayed green
    before adding the assertion below (and, for the Step 3.9 site
    specifically, that the FULL `pytest bin/tests -q` suite - 2361 tests -
    also stayed green, matching the round-5 reviewer's own measurement
    of that exact defect). Reddening mutation for each assertion: revert
    the matching sentence to the quoted pre-branch wording named in its
    comment.

    Deliberately excluded from this pin (rationale, not oversight): the
    generated .hermes/SKILL.md mirror, and four docs/ prose restatements
    in two different buckets. (1) docs/slides/skeptic-protocol-slides.md
    and its rendered .html are internally cross-checked by
    check-slides-sync's build-vs-source byte comparison - a stale .md
    still passes that gate (it only proves the .md and .html agree with
    each other, not with content/), so this exclusion accepts a real,
    known coverage gap on that pair's CONTENT rather than claiming
    mechanical coverage that does not exist. (2) docs/configuration-reference.md
    and docs/index.html DO carry mechanical verification against content/,
    but only for a narrow, unrelated slice: test_docs_currency_sync.py (run
    by bin-tests) checks their kill-switch enumerations against hooks/
    source and their agent-count claims against content/agents/*.md - it
    asserts nothing about this branch's neutrality-scope prose, so that
    coverage does not reach the sentences this pin would otherwise need to
    track. All four are hand-maintained, human-facing restatements rather than
    text any agent session loads and acts on (unlike every content/ and
    hooks/ site pinned above, which IS load-bearing for agent behavior);
    their staleness is the general AGENTS.md docs-currency-pass
    obligation's concern, not this spec's. Pinning them here would add
    four more sites this suite must keep in lockstep with content/
    prose it does not itself enforce staying in sync - reproducing the
    exact "prose copy drifts silently, unpinned, three rounds running"
    failure mode this test exists to close, one level up. The honest
    disposition is a real gap, named here, not a manufactured
    equivalence to the build-checked sites."""
    skeptic_agent = _read(SKEPTIC_AGENT)
    protocol = _read(SKEPTIC_PROTOCOL)
    hooks_agents = _read(HOOKS_AGENTS)

    # content/agents/skeptic.md "Reading your spawn prompt" item 4 - the
    # every-field, every-form, tagged-or-untagged restatement of the ban
    # from the Skeptic's own operating instructions (distinct from the
    # Step 3.9 mechanical-check restatement below - this is what the
    # agent believes about its inputs, not what it is instructed to scan
    # for). Load-bearing for: the agent's own understanding of field
    # scope not silently narrowing back to "neither field" (field 7 and
    # the brief only). Mutation: revert to "Neither field ever carries a
    # conductor hypothesis or suspicion about the artifact under review."
    assert (
        "No field of this input set, and no part of the adversarial "
        "brief, ever carries a conductor hypothesis, suspicion, or "
        "conclusion about the artifact under review, in any form and "
        "whether tagged or untagged" in skeptic_agent
    ), (
        f"{SKEPTIC_AGENT} 'Reading your spawn prompt' item 4 is missing "
        "the every-field, every-form, tagged-or-untagged restatement of "
        "the neutrality ban"
    )

    # content/agents/skeptic.md Step 3.9 - the branch's central
    # deliverable: widening the mechanical Neutrality check's own scan
    # scope from field 7 + the brief to every Global-context field (1-7)
    # plus the brief. Verified (round-6): reverting this exact sentence
    # to "Scan Global-context field 7 and the adversarial brief for a
    # conductor-composed hypothesis, suspicion, or attention-steer, per
    # the test defined in "Reading your spawn prompt" item 4 above." left
    # the full `pytest bin/tests -q` suite (2361 tests) green - this was
    # entirely unpinned before this assertion.
    assert (
        "Scan every field of the Global-context input set (1-7) and the "
        "adversarial brief for a conductor-composed hypothesis, "
        "suspicion, or conclusion about the artifact under review, in "
        "any form and whether tagged or untagged" in skeptic_agent
    ), (
        f"{SKEPTIC_AGENT} Step 3.9 is missing the every-field scan-scope "
        "widening - the Neutrality check's own instruction has narrowed "
        "back toward field-7-and-brief-only"
    )

    # content/references/skeptic-protocol.md - the "Mechanical
    # enforcement" paragraph's scope-disclosure clause, distinct from the
    # "### Scope of the ban" subsection heading and its enumerated
    # observed-forms already pinned above. Load-bearing for: readers of
    # the enforcement paragraph itself (not just the preceding
    # subsection) being told the hook covers a bounded subset and where
    # the remainder is actually checked. Mutation: revert to
    # "**Mechanical enforcement (implemented, DS-187): ...**" with no
    # bounded-subset qualifier, and delete the preceding sentence
    # "Mechanical enforcement below covers a bounded subset only and is
    # not a substitute."
    assert (
        "Mechanical enforcement below covers a bounded subset only and "
        "is not a substitute" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Scope of the ban' subsection is missing the "
        "bounded-subset-only disclosure ahead of the Mechanical "
        "enforcement paragraph"
    )
    assert (
        "a bounded subset only - see \"Scope of the ban\" above for the "
        "full rule" in protocol
    ), (
        f"{SKEPTIC_PROTOCOL} 'Mechanical enforcement' paragraph header is "
        "missing its own bounded-subset-only qualifier"
    )

    # hooks/AGENTS.md - the enforce-skeptic-neutrality.py module-map row's
    # scope-disclosure sentence. Load-bearing for: a reader of the module
    # map alone (without opening skeptic-protocol.md or the hook source)
    # not concluding this hook screens the brief body beyond its two
    # bounded surfaces. Mutation: revert the row's opening clause to
    # "Mechanically enforces Skeptic-brief neutrality at spawn time" and
    # delete the trailing "do not cite this row..." sentence.
    assert (
        "Mechanically enforces exactly two bounded surfaces of "
        "Skeptic-brief neutrality at spawn time" in hooks_agents
    ), (
        f"{HOOKS_AGENTS} enforce-skeptic-neutrality.py row is missing the "
        "exactly-two-bounded-surfaces scope disclosure"
    )
    assert (
        "do not cite this row as evidence the brief body is mechanically "
        "screened beyond them" in hooks_agents
    ), (
        f"{HOOKS_AGENTS} enforce-skeptic-neutrality.py row is missing the "
        "do-not-cite-as-evidence disclaimer"
    )
