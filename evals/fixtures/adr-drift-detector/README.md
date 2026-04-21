# adr-drift-detector fixtures

Tier 1 component eval for the `adr-drift-detector` named agent
(`content/agents/adr-drift-detector.md`). Each fixture ships a
`fixture.yaml` plus a `repo/` subdirectory that is copied verbatim
into the worktree root before the agent is spawned, so the agent sees
`docs/adr/*.md` and a seeded source tree at its CWD.

## Fixtures

| id     | archetype                          | primary axis                 | ceiling-capable |
|--------|------------------------------------|------------------------------|-----------------|
| ad-001 | clean compliance                   | format + classification      | yes             |
| ad-002 | single clear violation             | classification + evidence    | yes             |
| ad-003 | partial compliance                 | classification (PARTIAL)     | no (PARTIAL by design) |
| ad-004 | FP trap (test-only sqlite3)        | classification (no over-flag)| no (easy to overflag) |
| ad-005 | superseded + proposed + unverifiable | superseded + sections      | yes             |

ad-003 is deliberately below-ceiling. The tsconfig sets `"strict": true`
but then overrides `"noImplicitAny": false`. A naive reading of `strict`
alone would call this FOLLOWED; the correct classification given ADR
wording is PARTIAL. A report that labels it VIOLATED is also a scoring
loss (misclassification FP).

ad-004 is the false-positive trap. The ADR requires PostgreSQL in
production paths and explicitly allows sqlite3 inside `tests/`. A naive
`grep -r "import sqlite3"` fires on the test file and tempts the agent
to flag the ADR as VIOLATED. The correct call is FOLLOWED. The scorer
assigns a 0.3 FP penalty if the ADR is placed under `## Violations`
and a 0.15 FP penalty for `## Partial Compliance`.

ad-005 exercises the status-routing axes: one Superseded ADR whose
`superseded_by` target does not exist in the ADR directory (requires
the warning flag per the role doc), one Proposed ADR (not audited, must
be listed under `## Proposed`), one process-only ADR (must be
UNVERIFIABLE), and one Accepted ADR that is followed.

## Tool-grant proxy caveat

Production `adr-drift-detector` has `tools: Read, Bash, Grep, Glob`
declared in its frontmatter. The Tier 1 eval isolator grants
`Read,Grep,Glob,Task` at the CLI level and relies on the git worktree +
fixture-copy staging for blast-radius containment. The agent in the
eval does not have Bash.

This is a deliberate proxy choice:

- Tier 1 isolation is read-only via the worktree + allowed-tools list.
  Adding Bash to Tier 1 would break that invariant (see
  `evals/LEARNINGS.md` - "isolation claims must match isolation
  mechanisms").
- All five fixtures are solvable with Read/Glob/Grep against a seeded
  source tree. None depends on Bash-only capabilities (e.g. running
  `date` for the report header is a nice-to-have, not load-bearing -
  the scorer does not require the date to match today).
- The role prompt tells the agent to use Glob/Read/Grep instead of
  `grep -r` at Tier 1; vocabulary for both is accepted.

If a future archetype requires Bash to solve (e.g. running a test suite
to verify a "tests must cover X" ADR), promote the component to Tier 2
rather than granting Bash at Tier 1.

## Fixture layout

```
evals/fixtures/adr-drift-detector/
  ad-NNN/
    fixture.yaml     # id, component, protocol_sha, inputs, expected_report
    repo/            # source tree copied into the worktree root
      docs/adr/*.md  # ADR markdown
      src/...        # seeded source tree
      package.json | pyproject.toml | ...
```

`inputs.repo_dir` must equal `"repo"` in the current runner (the
prompt builder smoke-checks that at least one ADR directory exists
under this path before the agent is spawned).

## Adding a fixture

1. Pick an archetype. The scorer rewards per-ADR classification
   correctness (45%) and evidence (20%); fixtures should exercise a
   distinct failure mode the corpus does not already cover.
2. Author the ADR markdown so a human reader can answer "does the code
   follow this?" from the seeded tree alone. Do not telegraph the
   expected classification in the ADR body - the agent must read the
   source to decide. See `evals/LEARNINGS.md` - "Telegraphing is the
   most insidious fixture defect".
3. Keep the seeded source tree small (under ~30 files). The point is
   to exercise the scorer's dimensions, not to build a realistic
   service.
4. Fill in `expected_report` with:
   - `expected_classifications`: list of `{adr_id, classification}`
     for every ADR in the fixture. Classifications are VIOLATED,
     PARTIAL, UNVERIFIABLE, FOLLOWED, SKIPPED, or PROPOSED.
   - `expected_violation_evidence`: list of `{adr_id, paths}` for
     VIOLATED ADRs - the scorer checks that each listed path appears
     as a substring in the run's `## Violations` body.
   - `expected_superseded_missing`: list of ADR ids whose
     `superseded_by` target does not exist in the ADR dir and must be
     flagged per role-doc rule.
   - `vacuous_axes`: any of `["classification", "evidence",
     "sections", "superseded"]` to mark vacuous (score 1.0, no
     renormalization per the init_project_lite v3 precedent).
5. Cold-read test: have an independent reader run the fixture without
   reading `adr-drift-detector.md` and check whether the ADR
   classifications are inferable from the ADR + source alone. If they
   can score top marks without reading the role doc, the fixture is
   probably telegraphing - revise until they cannot.
