# investigator fixtures

Tier 1 component eval for the `investigator` named agent
(`content/agents/investigator.md`). Each fixture ships a `fixture.yaml`
plus a `seed/` subdirectory that is copied verbatim into the worktree at
the same relative path (`./seed/`) before the agent is spawned.

## Fixtures

| id      | archetype                  | primary axis                  | ceiling-capable |
|---------|----------------------------|-------------------------------|-----------------|
| in-001  | single-function trace      | citation accuracy             | yes             |
| in-002  | blast-radius map           | blast_radius_paths coverage   | no (dynamic dispatch) |
| in-003  | multi-file data-flow       | structure + answer keywords   | yes             |
| in-004  | ambiguous / gaps required  | calibration (confidence, gaps)| no (Medium/Low) |
| in-005  | scoped summary (control)   | structure + answer; vacuous citation+blast | yes  |

in-002 is deliberately below-ceiling because `seed/plugins/loader.py` reaches
the bus method via `getattr(shared_bus, method_name)`, which many briefs will
flag under "Risks and gotchas" but not credit as a call site in Component map.
The fixture's `acceptable_confidence: [Medium, Low]` and
`gaps_nonempty: true` reward a brief that names the indirection without
claiming complete coverage.

in-004 is the calibration stressor. The seed tree gives you enough to form
hypotheses (the rollup's half-open window, the ingest trigger's server-side
timestamp, late-arriving mobile events) but not enough to confirm one - log
data from outside the seed tree is needed. A High-confidence brief on this
fixture is wrong by construction.

in-005 is the scoped-summary control. Citation and blast axes are marked
`vacuous` on the fixture; those axes score 1.0 and do not renormalize,
per the init_project_lite v3 precedent (`evals/LEARNINGS.md` - vacuous
dimension handling). This lets the fixture still exercise the structure +
answer + calibration axes without forcing spurious file:line citations
for a single-file summary task.

## Tool-grant proxy caveat

Production `investigator` has `tools: Read, Glob, Grep, Bash` declared in
its frontmatter. The Tier 1 eval isolator grants
`Read,Grep,Glob,Task` at the CLI level and relies on the git-worktree
worktree-of-HEAD layer for blast-radius containment. The effect is that
the production agent has Bash (read-only by policy) and the eval agent
does not.

This is a deliberate proxy choice:

- Tier 1 isolation is read-only-fs via the worktree + the allowed-tools
  list. Adding Bash to Tier 1 would break that invariant
  (`evals/LEARNINGS.md` - isolation claims must match isolation
  mechanisms). Upgrading investigator to Tier 2 or Tier 3 to get Bash
  back is not warranted for the archetypes covered here - all five
  fixtures are solvable with Read/Glob/Grep against a seeded source
  tree.
- The agent's prompt and role remain unchanged; only the runtime tool
  list differs. The scorer does not reward or penalize tool choice; it
  scores the output brief. A fixture that genuinely required Bash to
  solve (e.g. running `find -type l` to surface symlinks) is out of
  scope for this corpus.

If a future archetype requires Bash to solve, promote the component to
Tier 2 (HOME redirect + permissive tools under a contained worktree)
rather than papering over it by granting Bash at Tier 1.

## Fixture layout

```
evals/fixtures/investigator/
  in-NNN/
    fixture.yaml      # id, component, protocol_sha, inputs, expected_investigation
    seed/             # source tree the agent explores; any shape
      ...
```

`inputs.seed_dir` must equal `"seed"` in the current runner (the prompt
builder tells the agent the code lives at `./seed/`).

## Adding a fixture

1. Pick an archetype and write the question so it states WHAT the
   conductor wants to understand, not HOW to investigate it. Telegraphing
   the method is the most common fixture defect
   (`evals/LEARNINGS.md` - telegraphing).
2. Stage the seed tree under `seed/`. Keep it small (1-6 files); the
   point is to exercise the scorer's dimensions, not to build a realistic
   app.
3. Fill in `expected_investigation` with:
   - `answer_keywords`: concrete strings that a correct direct answer
     will contain
   - `expected_citations`: repo-relative paths the brief should cite
     (path+line earns 1.0; path-only earns 0.5)
   - `blast_radius_paths`: paths that must appear in the Component map
     body (substring match; leave empty to skip)
   - `acceptable_confidence`: list of allowed confidence levels for the
     fixture's evidence quality
   - `gaps_nonempty`: true if the fixture is ambiguous and a responsible
     brief must declare what it could not verify
   - `vacuous_axes`: any of `["answer", "citation", "blast", "calibration"]`
     to mark as vacuous (score 1.0 without renormalization)
4. Test-read: ask a cold reader to produce the brief from the fixture
   alone. If they can score top marks without reading the investigator
   role, the fixture is telegraphing - revise until they can't.
