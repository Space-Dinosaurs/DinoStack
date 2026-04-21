# adr-generator fixtures

Tier 1 eval fixtures for the `adr-generator` named subagent
(`content/agents/adr-generator.md`). Each fixture is a `fixture.yaml`
with `inputs.decision_brief` + `inputs.constraints` + `inputs.existing_adrs`
and an `expected` block read by `evals/scoring/adr_generator_lite.py`.

## What this measures vs. what it does NOT measure

**Measures:** the adr-generator's ability to produce a well-structured
ADR document following its role doc's template - YAML front matter with
the 7 required keys and shape checks on title/status/date, the 8 required
sections (Status, Context, Decision, Consequences with Positive and
Negative sub-sections, Alternatives Considered, Implementation Notes,
References), per-section substring fidelity to the decision brief,
minimum alternatives count plus explicit rejection reasons, coded-bullet
floors (POS/NEG/ALT/IMP/REF), and filename-convention correctness
(including next-sequential NNNN when prior ADRs are declared).

**Does NOT measure** the adr-generator's actual filesystem-discovery
behavior. Fixtures do not seed a live `docs/adr/` that the agent can
read with Glob at eval time. Under Tier 1 isolation the worktree is a
checkout of HEAD, Write/Edit/Bash are dropped from the agent's tool
list (`evals/runner/invoker.py` `_ALLOWED_TOOLS = "Read,Grep,Glob,Task"`),
and existing-ADR context is supplied to the agent via the prompt's
`existing_adrs` block. This is a **synthetic-brief proxy** for real
decision-capture from a conversation plus a real directory walk,
analogous to the architect fixtures using inline prose for
`codebase_context` (see `evals/fixtures/architect/README.md` and
`evals/LEARNINGS.md` Phase 5 proxy caveats).

A maintainer edit to `adr-generator.md` that changes how the agent
*discovers* the next NNNN from disk (e.g. "run `ls docs/adr/ | tail -n
1`" vs "Glob for adr-*.md") cannot move fixture scores because the
agent has no disk to discover. Edits to frontmatter shape, section
naming, substring expectations, alternatives discipline, coded-bullet
conventions, and filename-pattern requirements ARE measurable.

**File output caveat.** The agent's role doc instructs it to save the
ADR to `docs/adr/<filename>.md`. Under Tier 1 isolation Write/Edit are
not granted to the subagent, so the agent emits the ADR inline as its
final response. The scorer prefers an on-disk file under `docs/adr/` if
one exists (for forward-compatibility with a future Tier 2 variant) and
falls back to parsing `final_text`. Some fixtures under `repo/docs/adr/`
contain documentation-only stubs of prior ADRs that would be seeded
under a future Tier 2 run; under Tier 1 they are ignored.

## Fixture corpus

| id     | scenario                            | expected_nnnn | headroom                                           |
|--------|-------------------------------------|---------------|----------------------------------------------------|
| ag-001 | datastore choice (clean baseline)   | 0001          | ceiling-capable baseline                           |
| ag-002 | auth strategy w/ 2 prior ADRs       | 0003          | numbering-aware; next-NNNN discovery from prompt   |
| ag-003 | caching layer                       | 0001          | below-ceiling: high coded_bullet floors            |
| ag-004 | semver policy                       | 0001          | below-ceiling: paraphrase risk on "semver"         |
| ag-005 | service mesh adoption               | 0001          | below-ceiling: alternatives-discipline trap        |

## Scorer axes

See `evals/scoring/adr_generator_lite.py` for the full formula. Six
dimensions sum to 1.0:

- `w_frontmatter = 0.15` - 7 required YAML keys; title/status/date shape
- `w_sections = 0.25` - 8 required sections (macro hit fraction)
- `w_substrings = 0.25` - per-section substring fidelity (macro-avg)
- `w_alternatives = 0.15` - `alternatives_min` blocks + rejection reasons
- `w_coded_bullets = 0.10` - POS/NEG/ALT/IMP/REF floors
- `w_filename = 0.10` - TIERED: pattern + correct NNNN = 1.0,
                        pattern + wrong NNNN = 0.5,
                        malformed/missing = 0.0

Every axis is vacuous-safe: a fixture that does not exercise an axis
(e.g. declares no `coded_bullet_floors`) credits 1.0 rather than 0/0
(precedent: `init_project_lite` v3 vacuous-axis handling, LEARNINGS
lines 149-165).

## Cold-reader check

Each fixture was drafted so the decision brief contains situational
facts (volumes, constraints, existing state) rather than the template
rules themselves. A reader who has never seen `content/agents/adr-generator.md`
cannot mechanically infer the 7-key YAML shape or the ALT-NNN coding
convention from the brief alone - those belong to the role doc. Reword
the fixture if a cold reader can telegraph the structural scoring
targets (LEARNINGS lines 28-36).
