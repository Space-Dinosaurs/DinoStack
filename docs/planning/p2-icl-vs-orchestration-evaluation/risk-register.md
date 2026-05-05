# Risk Register

Operational risks specific to this Plan-tier task. Implementation risks live in the per-unit architect plans.

- **Eval cost overrun on v1 run.** Brief caps the v1 run at $300 / 30M tokens HARD. The harness must enforce the cap inline; a single run that blows past the cap wastes spend and produces no usable signal.
- **False confidence on under-powered corpus.** Brief caps cells at 50 tickets. The smoke-gate dominance check is a non-statistical heuristic, not a significance test - downstream readers must not treat smoke-gate "wins" as conclusive.
- **In-flight session breakage during Brief restructure.** A `loop-state.json` compatibility shim will be required when the phase-rename lands. Out of scope for this Plan; flagged so it is not forgotten.
- **Cross-track surface.** Touches `content/`, `evals/`, and multiple adapters. ADR carve-out applied via Brief; cross-track ADR is not re-litigated here.
- **Drift between Brief amendments.** Amendments #1 and #2 are stacked; any future amendment authored before the operator merges this Plan risks diverging from what the engineers consume.
