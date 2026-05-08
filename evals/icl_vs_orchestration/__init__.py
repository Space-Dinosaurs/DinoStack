"""
Purpose: ICL-vs-orchestration head-to-head evaluation harness.
         Runs historical tickets under two conditions (AE-orchestrated and
         ICL-baseline), scores on 6 dimensions, tracks cost, and emits a
         JSON report consumable by Stage 3 (pre-restructure baseline) and
         Stage 6 (post-restructure comparison) of the ICL-restructure plan.

Public API: exposed via cli.py entry point and run.ts bun wrapper.

Upstream deps: evals.runner.invoker, evals.runner.normalizer,
               evals.runner.loader (SHA idiom); pyyaml; stdlib.

Downstream consumers: Stage-3 baseline run, Stage-6 comparison run,
                      eval-routing-rules (reads results-v1.json).

Failure modes: BudgetExceeded raised by cost_gate on global or per-cell
               ceiling breach. Corpus load errors raise ValueError.
               All per-ticket run errors are captured in ConditionResult.status
               rather than propagating; the runner continues.

Performance: dominated by LLM invocation cost (minutes per ticket).
             Harness overhead is negligible.
"""
