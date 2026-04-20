# Debugger eval fixtures

Tier 1, agent-mode component eval for `content/agents/debugger.md`. Five
fixtures (db-001..db-005) covering two clean causal chains (db-001,
db-002), one below-ceiling ambiguous-repro fixture (db-003), one
below-ceiling no-docs Low-confidence fixture (db-004), and one
config-not-code location-discrimination fixture (db-005).

## What this measures vs. what it does NOT

Measures: the named debugger subagent's ability to

- produce the mandated 6-section output (Diagnosis / Root cause /
  Evidence / Hypotheses considered / Fix brief / Confidence)
- pin the defect location at file:line, file+symbol, or file-only
  precision where appropriate
- use the right confidence level against the evidence available
- discipline its hypothesis listing (each hypothesis gets an
  eliminated/confirmed verdict)
- route a Low-confidence diagnosis to the "Insufficient evidence to
  write a fix brief" phrasing rather than guess

Does NOT measure: the debugger's ability to interactively investigate a
live repo. `content/agents/debugger.md` grants Bash for `git log`,
`pytest`, and `grep` against a running system. The eval worktree has no
live repo and no shell-tooling access relevant to the scenario. Every
fixture ships a static evidence bundle (bug report + source file +
stack trace or test output + optional config) and the prompt tells the
agent to diagnose from that bundle. This is a deliberate Bash-withheld
proxy.

The most load-bearing consequence: a fixture that would, in production,
be resolvable by a single `git log -p` or `context7 query-docs` call
(db-004's library-upgrade scenario) is labeled Low confidence here, and
the scorer checks for the "Insufficient evidence" phrasing rather than
for a correct diagnosis. That captures the behavioral rule from
content/agents/debugger.md (the three-eliminated-hypotheses escalation)
rather than the investigation outcome that a live session would
produce.

## Fixture index

| ID     | Scenario                                    | Expected confidence | Location hint |
|--------|---------------------------------------------|---------------------|---------------|
| db-001 | off-by-one inclusive range in compute_window | High                | code          |
| db-002 | null deref on req.session for unauth routes  | High                | code          |
| db-003 | token-bucket race: decrement outside lock    | Medium              | code          |
| db-004 | library-upgrade ack API change, docs denied  | Low                 | code          |
| db-005 | config timeout_ms=30 meant 30s, not 30ms     | High                | config        |

## Cold-reader test

Each fixture was drafted against the rule in `evals/LEARNINGS.md` line
28-36: the bug_report and payload must tell the agent WHAT is wrong
(the operational symptom, the files in play, the constraints on
investigation) but must not restate the rule the scorer tests.

db-004 is the closest call: the bug report states the investigation
constraints ("you do NOT have Bash, internet, or Context7 access")
because those constraints ARE facts about this eval's environment, not
the rule. The rule the scorer is testing is content/agents/debugger.md's
three-eliminated-hypotheses -> "Confidence: Low" escalation. The
fixture does not telegraph that rule; a cold-reader must retrieve it
from the methodology files.

## Scoring

See `evals/scoring/debugger_lite.py` module docstring for the full
formula. Six weighted dimensions sum to 1.0. Structure (0.15) and
confidence calibration (0.10) are never vacuous; root cause locality
(0.30) is tiered; diagnosis keywords (0.20), hypothesis discipline
(0.10), and fix-brief specificity (0.15) may be vacuous when the
fixture declares no substrings / opts out of the hypothesis axis.
