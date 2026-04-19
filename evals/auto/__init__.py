"""evals.auto: P3 /auto-harness autonomous self-improvement loop.

See evals/auto/README.md for operator usage. See
docs/planning/p2-self-improving-harness.md for the architect plan
motivating this package. The loop is a standalone Python CLI
(`python -m evals.auto.cli run <component>`) that iterates proposed
edits against a single component's eval, keeps improvements, reverts
regressions, and writes a ledger row per iteration.
"""
