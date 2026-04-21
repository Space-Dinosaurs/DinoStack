# perf-analyst component eval

Measures whether `content/agents/perf-analyst.md` produces a correctly
structured, measurement-grounded Perf Analysis report given a static
bundle of profiling artifacts.

## What this measures

- Does the report carry the exact 10-section shape (title + 9
  sub-headings: Summary, Methodology, Measurements, Perf budget
  verdict, Hotspot, Root cause, Evidence, Fix brief for engineer,
  Confidence)?
- Does the Hotspot section name the location (file / function
  keywords) the fixture's staged artifacts point to?
- Does the Hotspot section classify the bottleneck with the exact
  enum token the role doc lists (e.g. "N+1 queries", "Synchronous I/O
  in a hot path", "Unbounded growth")? Does it avoid a forbidden
  pattern for the fixture (e.g. pa-003 is CPU-repeated-computation
  and "N+1" is a miscategorization trap)?
- Does the Evidence + Measurements text quote the numeric citations
  the fixture tokenizes (percentages, ms values, query counts, byte
  totals)?
- Does the Perf budget verdict emit PASS / FAIL / N/A matching the
  fixture's declared budget state?
- Does the Fix brief name a concrete location AND a concrete action
  verb (replace, remove, cache, memoize, batch, async, ...)? A verb-
  only brief without location is half-credit.
- Is the Confidence enum calibrated against the fixture's
  acceptable level? Below-ceiling fixtures (pa-001 no second
  measurement, pa-003 no perf budget) cap an overclaimed "High" at
  0.5 via the overclaim guard even when the "adjacent" tier would
  normally allow it.

## What this does NOT measure

- Real profiling. The Tier 1 isolator grants only Read/Grep/Glob/Task -
  no Bash - so the agent cannot actually run `py-spy`, `pprof`,
  `EXPLAIN ANALYZE`, or a benchmark. Each fixture ships static
  profiling artifacts (profile.txt, explain.txt, query_log.txt,
  flamegraph.txt, heap_snapshot.txt, source_excerpt.py) that stand
  in for what the agent would otherwise capture live.
- Second-measurement verification. Fixtures mark whether a second
  measurement is plausible given the static bundle; calibration on
  pa-001 and pa-003 deliberately caps confidence below High because
  the bundle cannot be re-profiled.
- Measurement methodology quality. The scorer checks that the report
  cites numbers, not whether the agent chose the best profiling tool.

## Bash-denied proxy caveat

Production `perf-analyst` has `tools: Read, Glob, Grep, Bash`
declared in its frontmatter. The Tier 1 eval isolator grants
`Read,Grep,Glob,Task` at the CLI level and withholds Bash (per
`evals/LEARNINGS.md` - isolation claims must match isolation
mechanisms). The effect is that the production agent can spawn
`py-spy` / `pprof` / `hyperfine` against a live target, and the eval
agent cannot.

This is a deliberate proxy choice:

- Tier 1 isolation is read-only-fs via the worktree + the allowed-
  tools list. Adding Bash to Tier 1 would break that invariant.
- Every fixture's artifacts encode what a live profiling session
  would have captured. The prompt tells the agent "Target cannot be
  re-profiled; artifacts are canonical." so it does not try to
  execute a tool it cannot call.
- The scorer does not reward or penalize tool choice; it scores the
  output report's structure, hotspot locality, pattern
  classification, evidence quoting, budget verdict, fix brief
  specificity, and confidence calibration.

If a future archetype requires live profiling to solve (e.g. a
fixture that depends on observing allocations under load rather than
reading a pre-captured heap snapshot), promote the component to
Tier 2 (HOME redirect + Bash under a contained worktree) rather
than papering over it by granting Bash at Tier 1.

## Isolation

Tier 1: worktree-of-HEAD + allowed_tools=Read/Grep/Glob/Task,
`default` permission mode, no HOME redirect. Each fixture's artifact
files are staged into `./evals-fixture/` inside the worktree before
the agent is spawned.

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this
component:

- Adding a "synonym map" so a report that writes "database loop" is
  credited for "N+1 queries". Don't. Enforce the pattern enum in the
  prompt's Required output vocabulary block; keep scoring exact.
- Editing the role doc to pre-list the exact sentence the fixture
  expects. Fails the overfitting rule - the fixture's specificity
  would disappear if the fixture disappeared.

## Known limitations

- The Bash-denied proxy means fixtures that would require a live
  re-profile to distinguish the correct hotspot from a plausible
  decoy are out of scope. The current corpus is solvable purely
  from the staged artifacts.
- No cross-fixture check that two fixtures with the same pattern
  class produce differentiable scores under a prompt edit. If this
  bites in sensitivity-check, add a third same-pattern fixture
  with distinct hotspot keywords.
