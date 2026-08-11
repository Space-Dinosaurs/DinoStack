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
live tree (2026-08-11), of the 18 files under `content/agents/*.md`, only
3 (`debugger.md`, `investigator.md`, `skeptic.md`) carry any "never omit
any section" instruction. This file single-sources that concern going
forward, before it spreads further as an ad hoc per-agent restatement.

Every one of `content/agents/*.md`'s return-contract sections should carry
a **one-line pointer** to this file, never a restated copy of the test
itself. Not every agent file uses the heading "## Output format" verbatim,
and not every return takes the same physical shape - see "Compliance
shapes" below, and `bin/tests/test_agent_return_contract_spec.py`'s
`HEADING_SYNONYMS` for the recognized alternate headings (`Sign-off
format`, `Report structure`, `Output templates`).

Correction (2026-08-11, round 5): the claim above ("of the 18 files, only
3 carry any 'never omit any section' instruction") undercounted. Verified
directly: `debugger.md:110` and `investigator.md:126` carry a
section-scoped "never omit any section" instruction; `adr-drift-detector.md:259`
carries the equivalent "do not omit the section"; `architect.md:238`
carries the equivalent "Do not omit the block" for its `qa_criteria`
section. `skeptic.md:167` carries a narrower, LINE-scoped instance
("Never omit the 'Active search:' line"), not a section-scoped one. The
accurate count is 5 files carrying some form of a "don't omit"
instruction (4 section/block-scoped, 1 line-scoped), not 3.

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
recognized bound forms (round 5 - previously several of these were
keyword/phrase-anywhere searches with no adjacency or specificity
requirement, despite claiming otherwise; see
`bin/tests/test_agent_return_contract_spec.py` for the code, which this
list must stay identical to):

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
5. **Schema/doc pointer** - `defined in`/`defined once` followed, within
   a short window, by a concrete `.md` path or the word `schema` - never
   the bare phrase alone.
6. **Bounded-by-nature value literal** - a `<...>` placeholder whose
   ENTIRE body names one of a closed vocabulary of well-known,
   syntactically-constrained value types: `sha`/`from-sha`/`to-sha`/
   `commit sha`, `url`, `timestamp`, `tag`, `path`/`repo-relative path`/
   `file path`, `environment name`/`remote name`, `exact command run`/
   `exact rollback command`, `message`/`commit message`, `count`,
   `version`.
7. **Nullable-type placeholder** - `<TYPE or null>` (optionally `<TYPE,
   or null>`), where TYPE is 1-2 words drawn from a closed vocabulary of
   type names (`string`, `number`, `boolean`, `date`, `sha`, `url`,
   `path`, `tag`, `id`, `name`, `object`, `array`, ...).

Anything matching none of the seven forms above is unbounded and flagged.
Extending this list is a deliberate edit: add the new form to the code
AND to this list in the same change - never widen an existing form's
matching to silence a specific false positive.

**Shape 3 - Fixed literal-line template.** A short (`<= 8` lines), fixed
`Label: <value>` sequence - not JSON/YAML, not `###`-tagged. Obligation:
every value is a closed enum, a bare count, or explicitly bounded to one
line by its own placeholder text. `skeptic.md` is this shape under an
additional constraint: its six lines are validated verbatim by the
conductor (`content/references/skeptic-protocol.md` Section 11;
`content/commands/ds-skeptic.md:68`; `content/commands/ds-wrap.md:439,443`)
- a migration for this file may add a cap declaration in the surrounding
prose only, and must never alter, retag, or restructure any of those six
validated line prefixes.

**Shape 4 - Fixed markdown-sectioned flat report.** A literal fenced
report template of multiple `##`-level sections, fixed in count (not a
repeated per-item structure), not machine-parsed as JSON. Obligation: the
report's top status line declares a closed enum; every other section with
open-ended free text declares an explicit bound in its own placeholder
bracket text - checked against the SAME closed whitelist as Shape 2 above
(a placeholder naming a bounded-by-nature value type, like a SHA, URL,
timestamp, tag, or exact command, needs no separate cap; only genuinely
open-ended narrative does). Round 4 regressed this to an unconditional
numeric-cap requirement on every placeholder after deleting a gameable
narrative-hint-word heuristic - round 5 restores the doc's actual scope
("every OTHER section WITH open-ended free text") via the whitelist
instead of a keyword heuristic.

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
summary as of 2026-08-11:

- **Shape 1** (tag every `###` field): `architect.md`, `debugger.md`,
  `dependency-auditor.md`, `investigator.md`, `orchestration-planner.md`,
  `perf-analyst.md`, `product-discovery.md`, `qa-engineer.md`,
  `security-auditor.md` - not yet migrated.
- **Shape 2** (schema-object): `engineer.md`, `learning-extractor.md`,
  `learnings-agent.md`, `wrap-ticket.md`, `adr-drift-detector.md` have a
  real structured return (under a `### N. Return` workflow sub-step or a
  non-synonym `##` phase heading) but are not yet migrated to this
  shape's enum/cap obligation. `engineer.md` carries exactly ONE genuine
  violation now (`pr_description_body` declares no cap, one-line marker,
  or schema pointer) - round 5 also fixed two over-strictness defects
  that had nothing to do with a real gap: `files_modified.path`
  (`<repo-relative path>`) is a bounded-by-nature value literal, and
  `task_id` (`<string or null>`) is a recognized nullable-type
  placeholder; neither should ever have been flagged.
- **Shape 3** (fixed literal-line template): `skeptic.md` needs one
  narrow, additive cap declaration on finding-description length, in the
  Calibration section - its six conductor-validated structural lines are
  never altered. `goal-condition-evaluator.md` was previously claimed
  COMPLIANT NOW; round 5's `check_shape3` fix (now inspects every fenced
  block in the section, not just the first) found it genuinely
  non-compliant - its second template's Evidence value
  (`"evaluator-error: <reason>"`) declares no bound, and its third
  template's `BLOCKED` line is not a `Label: value` line. It was never
  actually fully compliant, only under-checked; there is no longer a
  "compliant now" file in the corpus.
- **Shape 4** (markdown-sectioned flat report): `release-orchestrator.md`
  carries TWO genuine violations, not one as earlier claimed - an
  explicit cap on its "Failures and blockers" free-text section, AND a
  bound on its "QA report" placeholder (`<summary or "see spawned
  qa-engineer output">`), which is likewise open-ended narrative and was
  never actually covered by the "one narrow addition" claim; round 4's
  unconditional-cap regression masked the real scope of this file's
  gap by over-flagging every other placeholder alongside it (13 false
  positives - SHAs, a URL, a timestamp, a tag, exact commands, names,
  and a commit message - none of which need a cap under the round-5
  bounded-by-nature whitelist).
- **Exempt** (file-artifact output, not a return payload): `adr-generator.md`
  - its deliverable is the generated ADR document itself, not a
  conductor-parsed return.
