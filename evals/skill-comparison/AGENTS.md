# evals/skill-comparison

Outcome-driven eval tree for measuring AE methodology + named-agent impact
on real software-engineering tasks. Distinct from `evals/components/` (which
measures per-agent prompt correctness on synthetic fixtures); this tree
measures "does using this agent yield a better solution to a real bug than not
using it?" - a different eval class.

## Scope

- 8 conditions: `baseline`, `ae-rules-injected`, and one `<agent>-direct` per
  named agent (engineer, architect, investigator, debugger, skeptic, qa-engineer).
- Primary metric: binary pass/fail on held-out test suite.
- Task corpus frozen to git before any run; no post-hoc edits once a baseline
  cell has run against the list.

## Key docs

- Design: `docs/planning/p2-skill-comparison-evals/brief.md`
- Architect plan: `docs/planning/p2-skill-comparison-evals/architect-plan.md`
- Shared runner utilities: `evals/runner/`

## Overfitting Rule

Every `content/` edit motivated by a score from this harness MUST cite the
task fixture in the commit message and pass the counterfactual test defined in
`evals/OVERFITTING-RULE.md`. No exceptions.
