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
Downstream consumers: content/agents/*.md return-contract section preambles
            (see bin/tests/test_agent_return_contract_spec.py
            SHAPE_ASSIGNMENTS, NOT_YET_MIGRATED, and EXEMPT_FILE_ARTIFACT
            for the current per-file shape and migration status);
            bin/tests/test_agent_return_contract_spec.py (the spec gate
            enforcing the per-shape compliance obligations).
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
always present versus optional - is exactly that kind of rule. It does not
yet exist as a widespread per-agent restatement: verified against the
live tree (2026-08-11), of the 18 files under `content/agents/*.md`, 5
carry some form of a "don't omit" instruction - `debugger.md:110` and
`investigator.md:126` carry a section-scoped "never omit any section"
instruction, `adr-drift-detector.md:259` carries the equivalent "do not
omit the section", `architect.md:238` carries the equivalent "Do not omit
the block" for its `qa_criteria` section, and `skeptic.md:167` carries a
narrower, LINE-scoped instance ("Never omit the 'Active search:' line").
This file single-sources that concern going forward, before it spreads
further as an ad hoc per-agent restatement.

Every one of `content/agents/*.md`'s return-contract sections should carry
a **one-line pointer** to this file, never a restated copy of the test
itself. Not every agent file uses the heading "## Output format" verbatim,
and not every return takes the same physical shape - see "Compliance
shapes" below, and `bin/tests/test_agent_return_contract_spec.py`'s
`HEADING_SYNONYMS` for the recognized alternate headings (`Sign-off
format`, `Report structure`, `Output templates`).

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

## Compliance shapes

Not every agent's return can take the same physical shape - four shapes are
recognized, each with its own affirmative compliance obligation. Recognizing
more than one shape is legitimate only because each shape below carries an
equal or stronger attention-test guarantee than tagged prose fields; no
shape is a blanket exemption, and a file must satisfy its own shape's
obligation to be compliant.

**Shape 1 - Tagged prose fields.** A `## Output format` (or heading-synonym)
section with `###`-level sub-header fields, each tagged inline:

- `### <Field name> [MECHANICAL, cap: <N> chars]` (or `items` / `steps` /
  `entries` / `words`) - cap declared in the field's own header text.
- `### <Field name> [MECHANICAL, enum]` - closed-enum value, no cap needed.
- `### Notes [ADVISORY]` - the single fold-target for fields that fail the
  attention test. Present only when non-empty.

Fields commonly live inside a fenced template block; tag them there exactly
as above - the fence is not a boundary that exempts fields from tagging.

**Shape 2 - Structured schema-object return.** The return is a single
literal fenced ` ```yaml ` or ` ```json ` block (optionally with a
JSON-Schema fragment) - no narrative `###` fields. Obligation: (a) every
classification/status-bearing field declares a closed enum; (b) every
field capable of open-ended or repeated content declares an explicit
bound. Both obligations are checked against a CLOSED whitelist of
recognized bound forms - this is the CANONICAL, full list; Shapes 3 and 4
below each consult only a NAMED SUBSET of it (see those shapes for exactly
which forms apply - round 6 fix: a prior revision of this file falsely
claimed all three shapes shared "the same closed whitelist", which the
code never actually implemented). See
`bin/tests/test_agent_return_contract_spec.py` for the code, which this
list must stay identical to:

1. **Closed enum list** - either the field's value stands ALONE as a bare
   `X | Y | Z` token list (never inside a `<...>` narrative placeholder
   bracket), or an explicit `enum:` label (inline or on a `#`-prefixed
   comment line) precedes a `|`-delimited list.
2. **True-adjacent numeric cap** - a `cap`/`capped`/`max`/`maximum`/
   `maxLength`/`truncated to` keyword IMMEDIATELY followed by a digit and
   a unit (`chars`, `items`, `steps`, `entries`, `words`) - not merely
   present anywhere in the same field's text.
3. **Fixed-length spec** - a digit directly modifying `char`/`chars`/
   `character(s)` (e.g. "full 40-char SHA") - a self-describing bound,
   distinct from form 2.
4. **One-line marker** - a `<one-line ...>` / `<single-line ...>`
   placeholder.
5. **Bounded-by-nature value literal** - a `<...>` placeholder whose
   ENTIRE body names one of a closed vocabulary of well-known,
   syntactically-constrained value types: `sha`/`from-sha`/`to-sha`/
   `commit sha`, `url`, `timestamp`, `tag`, `path`/`repo-relative path`/
   `file path`, `environment name`/`remote name`, `exact command run`/
   `exact rollback command`, `count`, `version`.
6. **Nullable-type placeholder** - `<TYPE or null>` (optionally `<TYPE,
   or null>`), where TYPE is 1-2 words drawn from a closed vocabulary of
   BOUNDED type names: `number`, `int`, `integer`, `boolean`, `bool`,
   `date`, `timestamp`, `sha`, `url`, `path`, `tag`, `id`, `name`.

Anything matching none of the six forms above is unbounded and flagged.
Extending this list is a deliberate edit: add the new form to the code
AND to this list in the same change - never widen an existing form's
matching to silence a specific false positive.

Round 6 removed two things from this list, deliberately, not by
narrowing an existing form's match: a former "schema/doc pointer" form
(`defined in`/`defined once` followed, within a short window, by a
concrete `.md` path or the word `schema`) was DELETED outright - it
remained a bypassable proximity heuristic even after a round-5
tightening, and a full-body-fullmatch rewrite (the pattern used for form
6 below) had no clean shape to anchor on for pointer phrasing, which is
always embedded in a longer sentence, not a standalone value. And form 6
(nullable-type placeholder) no longer accepts `string`, `str`, `object`,
or `array` as a TYPE word - a bare type declaration is not itself a
bound (`<string or null>` carries no length limit at all).

**Shape 3 - Fixed literal-line template.** A short (`<= 8` lines), fixed
sequence of `Label: <value>` lines, OR a bare closed-enum-shaped status
token (an all-caps identifier, no colon, e.g. `BLOCKED`) standing alone
as its own line - not JSON/YAML, not `###`-tagged. Obligation: every
`Label:` line's value is a closed enum, a bare count, or explicitly
bounded to one line by its own placeholder text; a bare status-token line
is bounded by construction (the token itself is the fixed value, drawn
from a small implied vocabulary). This shape does NOT use the Shape-2
whitelist above - it consults its own smaller, named form set: closed
enum (Shape-2 form 1, plus a bare `true`/`false` literal), a **bare
count** (a Shape-3-only form: a bare `<N>`/`N` integer placeholder, with
no keyword-led cap requirement), the **one-line marker** (Shape-2 form
4), and a **fully-realized literal** (a Shape-3-only form: a value
containing no `<...>` placeholder at all has no open narrative slot to
overflow, and is bounded by construction). It does NOT use Shape-2's
true-adjacent numeric cap, fixed-length spec, or bounded-by-nature value
literal forms - none of these apply to a single physical `Label: value`
line the way they do to a multi-line schema leaf or report placeholder.
`skeptic.md` is this shape under an additional constraint: its six lines
are validated verbatim by the conductor
(`content/references/skeptic-protocol.md` Section 11;
`content/commands/ds-skeptic.md:68`; `content/commands/ds-wrap.md:439,443`)
- a migration for this file may add a cap declaration in the surrounding
prose only, and must never alter, retag, or restructure any of those six
validated line prefixes.

**Shape 4 - Fixed markdown-sectioned flat report.** A literal fenced
report template of multiple `##`-level sections, fixed in count (not a
repeated per-item structure), not machine-parsed as JSON. Obligation: the
report's top status line declares a closed enum; every other section with
open-ended free text declares an explicit bound in its own placeholder
bracket text. This shape consults exactly FOUR of the six Shape-2 forms
above - closed enum (form 1), true-adjacent numeric cap and fixed-length
spec (forms 2/3), and bounded-by-nature value literal (form 5) - a
placeholder naming a bounded-by-nature value type, like a SHA, URL,
timestamp, tag, or exact command, needs no separate cap; only genuinely
open-ended narrative does. It does NOT consult the one-line marker (form
4) or nullable-type placeholder (form 6): a report-template placeholder
bracket has never been written in either of those two shapes in the real
corpus, so there is nothing for those forms to match here, and this is a
documented absence rather than a silent gap (round 6 - a prior revision
of this file falsely claimed Shape 4 used "the SAME closed whitelist as
Shape 2", which the code never actually implemented). Round 4 regressed
this to an unconditional numeric-cap requirement on every placeholder
after deleting a gameable narrative-hint-word heuristic - round 5
restored the doc's actual scope ("every OTHER section WITH open-ended
free text") via this narrower whitelist instead of a keyword heuristic.

**Exemption - file-artifact output.** A file is exempt from all four
shapes only when its deliverable is a file it writes to disk, not a
payload the conductor parses or gates on, AND no downstream command file
parses a conductor-facing return from it. Requires the affirmative reason
stated per-file below - never "has no section under any name."

No untagged Shape-1 field, no unbounded Shape-2/3/4 field, and no
undeclared enum is permitted. `bin/tests/test_agent_return_contract_spec.py`
is the spec gate that checks for these obligations per shape, mechanically
- it verifies structural presence, not classification correctness (whether
a field was assigned the right shape or the right MECHANICAL/ADVISORY
verdict is a human judgment the gate cannot make).

## Migration status

This file and its spec gate ship independently of any agent-file edits.

**Round 5 (2026-08-11) structural change:** the boolean `NOT_YET_MIGRATED`
allowlist referenced by earlier revisions of this section is RETIRED. A
boolean set can only say "still flagged" - it cannot detect a checker
becoming more permissive (a violation silently disappearing) or more
strict (a new violation silently appearing) for a file that remains
flagged either way, and four consecutive rounds of the spec gate shipped
exactly that failure mode. The authoritative, current per-file status is
now `bin/tests/fixtures/agent_return_contract/expected_violations_snapshot.json`
- an exact snapshot of every violation string the live checker emits for
every `SHAPE_ASSIGNMENTS` file, asserted verbatim by
`test_expected_violations_snapshot_matches_reality`. See
`bin/tests/generate_agent_return_contract_snapshot.py` for the deliberate,
reviewed update procedure (never a silent one-command refresh). Per-shape
summary as of 2026-08-11 (round 6):

- **Shape 1** (tag every `###` field): `architect.md`, `debugger.md`,
  `dependency-auditor.md`, `investigator.md`, `orchestration-planner.md`,
  `perf-analyst.md`, `product-discovery.md`, `qa-engineer.md`,
  `security-auditor.md` - not yet migrated.
- **Shape 2** (schema-object): `engineer.md`, `learning-extractor.md`,
  `learnings-agent.md`, `wrap-ticket.md`, `adr-drift-detector.md` have a
  real structured return (under a `### N. Return` workflow sub-step or a
  non-synonym `##` phase heading) but are not yet migrated to this
  shape's enum/cap obligation. `engineer.md` now carries FOUR genuine
  violations, not one - round 6's Major-1 fix (a bare type declaration is
  not itself a bound) correctly re-flags `task_id` (`<string or null>`)
  and `branch_name` (`<string, or null>`), and round 6's Major-2 fix
  (schema/doc-pointer form deleted outright) correctly re-flags
  `learnings_candidate`, alongside the pre-existing `pr_description_body`
  gap. Round 5's `files_modified.path` (`<repo-relative path>`) fix
  stands unchanged - it is a genuine bounded-by-nature value literal and
  is still not flagged.
- **Shape 3** (fixed literal-line template): `skeptic.md` needs one
  narrow, additive cap declaration on finding-description length, in the
  Calibration section - its six conductor-validated structural lines are
  never altered. `goal-condition-evaluator.md` was previously claimed
  COMPLIANT NOW; round 5's `check_shape3` fix (now inspects every fenced
  block in the section, not just the first) found it genuinely
  non-compliant - its second template's Evidence value
  (`"evaluator-error: <reason>"`) declares no bound. Its third template's
  `BLOCKED` line, initially also flagged as "not a `Label: value` line",
  is a round-5 over-strictness artifact corrected in round 6: a bare
  closed-enum-shaped status token standing alone is a legitimate Shape-3
  line (see "Shape 3" above) and is no longer flagged. There is still no
  "compliant now" file in the corpus - the Evidence-value gap remains
  genuine.
- **Shape 4** (markdown-sectioned flat report): `release-orchestrator.md`
  carries THREE genuine violations, not two as earlier claimed - an
  explicit cap on its "Failures and blockers" free-text section, a bound
  on its "QA report" placeholder (`<summary or "see spawned qa-engineer
  output">`), and (round 6 Minor fix) a bound on its `<message>`
  placeholder in the commit-listing lines under "What shipped" (appears
  twice) - a commit message is not bounded by nature the way a SHA/URL/
  timestamp/tag is, so `message`/`commit message` were removed from the
  bounded-by-nature-value-literal vocabulary.
- **Exempt** (file-artifact output, not a return payload): `adr-generator.md`
  - its deliverable is the generated ADR document itself, not a
  conductor-parsed return.
