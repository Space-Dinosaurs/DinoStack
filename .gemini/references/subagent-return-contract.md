<!--
Manifest
Purpose: Canonical, single-sourced definition of the attention test that
         classifies every subagent return field as MECHANICAL or ADVISORY,
         replacing per-agent-file restatement of "never omit any section."
Public API: the attention test text below (quoted from docs/overview/vision.md
            Goal 1), the MECHANICAL/ADVISORY tagging convention, and the
            KEEP-as-MECHANICAL justification rule. content/agents/*.md Output
            format sections reference this file with a one-line pointer
            rather than restating the test.
Upstream dependencies: docs/overview/vision.md (Goal 1 - quoted verbatim,
            never paraphrased independently, so the two copies cannot drift).
Downstream consumers: content/agents/*.md Output format preambles (Unit 1,
            not yet migrated - see bin/tests/test_agent_return_contract_spec.py
            NOT_YET_MIGRATED); bin/tests/test_agent_return_contract_spec.py
            (the spec gate enforcing the tagging convention).
Failure modes: prose-only file, no runtime failure mode. Staleness risk: if
            docs/overview/vision.md Goal 1's wording changes, the quoted
            block below must be updated in the same change or the citation
            becomes inaccurate - grep this file's quoted block against
            vision.md when editing either.
Performance: n/a (reference doc, read on trigger).
-->

# Subagent Return Contract

## Why this file exists

DinoStack has a documented, repeated failure mode of duplicating a binding
rule across many files until the copies quietly drift apart (see this
repo's `AGENTS.md` entries on the Elevated-signal table and on plan/brief
duplication). The rule below - which field in a subagent's return is
always present versus optional - is exactly that kind of rule, and it
previously existed only as an unbounded, per-agent "never omit any section"
instruction repeated across 17 agent files. This file single-sources it.

Every one of `content/agents/*.md`'s Output format sections should carry a
**one-line pointer** to this file, never a restated copy of the test itself.

## The governing source: North Star Goal 1

This file does not invent a new rule - it operationalizes one that already
exists in the ratified product-intent layer. Quoted verbatim from
`docs/overview/vision.md`, North Star Goal 1:

> **Guard operator attention.** Surface decisions and work-stoppages, not
> status. A change that adds capability but increases what the operator
> must read, watch, or babysit is a regression, not a feature. (The
> "attention test" is the tie-breaker when trade-offs are unclear.)

This is the single citation of Goal 1 for return-contract purposes. If
Goal 1's wording in `docs/overview/vision.md` changes, update the quoted
block above in the same change - do not let this copy drift from its
source.

## The attention test, applied per field

Every subagent return field is exactly one of two kinds, decided by the
attention test:

> **Every subagent return field is exactly one of two kinds, decided by the
> attention test (DinoStack North Star Goal 1, `docs/overview/vision.md`):
> does this field surface a decision the conductor/operator must make, or a
> work-stoppage that blocks progress - including serving as a
> machine-parsed input to a specific downstream gate, hook, or command-file
> step?**
> - **MECHANICAL** (passes the attention test) - ALWAYS present, using the
>   field's declared null form when empty (e.g. `blocking_count: 0`,
>   `findings: []`). A field that merely HAS a downstream consumer but
>   conveys no decision or blocker (pure status/audit-trail narration) is
>   NOT automatically MECHANICAL by that fact alone.
> - **ADVISORY** (fails the attention test - pure status, narration, or
>   context with no decision/blocker payload) - folded into a single
>   `Notes` block, PRESENT ONLY WHEN NON-EMPTY. An empty Notes block is
>   entirely omitted - no "None" line, no boilerplate.
>
> A KEEP-as-MECHANICAL verdict on a field with no grep-matchable downstream
> consumer requires a stated autonomy or verifiability gain (e.g. "omitting
> this forces the next agent to re-investigate, a measurable autonomy
> loss") - "a human might find it useful" is not sufficient justification
> on its own.

## Tagging convention

Every per-agent Output format section must tag each field. In an agent
file's Output format section, a field is a `###` sub-header; tag it inline
on the header line:

- `### <Field name> [MECHANICAL, cap: <N> chars]` (or `items` / `steps` /
  `entries` / `words`) for a MECHANICAL prose or list field. The numeric
  cap must be declared in the field's own bullet/header text - not left
  implicit.
- `### <Field name> [MECHANICAL, enum]` for a MECHANICAL field whose value
  is a closed enum (no character cap needed - the enum's own value set is
  the bound).
- `### Notes [ADVISORY]` - the single fold-target for every field that
  fails the attention test. Present only when non-empty.

No untagged field is permitted. `bin/tests/test_agent_return_contract_spec.py`
is the spec gate that checks for this tagging, mechanically - it verifies
tag presence and cap declaration, not classification correctness. Whether a
given field was tagged MECHANICAL or ADVISORY *correctly* is a human
judgment call the gate cannot make; that judgment is what the KEEP-as-
MECHANICAL rule above governs.

## Migration status

This file and its spec gate ship independently of any agent-file edits.
`content/agents/*.md` files do not yet use this tagging convention - see
`NOT_YET_MIGRATED` in `bin/tests/test_agent_return_contract_spec.py` for
the current list of files pending migration.
