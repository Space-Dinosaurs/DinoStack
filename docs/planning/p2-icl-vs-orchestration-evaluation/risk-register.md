# Risk Register

Operational risks specific to this Plan-tier task. Implementation risks live in the per-unit architect plans.

- **Eval cost overrun on v1 run.** Brief caps the v1 run at $300 / 30M tokens HARD. Harness must enforce the cap inline; a single uncapped run wastes spend and yields no usable signal.
- **False confidence on under-powered corpus.** Brief caps cells at 50 tickets. Smoke-gate dominance check is a heuristic, not a significance test - downstream readers must not treat smoke-gate "wins" as conclusive.
- **In-flight session breakage during phase rename.** `loop-state.json` compatibility shim is required when the phase-rename lands; out of scope for this Plan, flagged here.
- **Cross-track surface.** Touches `content/`, `evals/`, multiple adapters. ADR carve-out applied via Brief; cross-track ADR is not re-litigated here.
- **Drift between Brief amendments / branch-stack misorder.** Amendments #1 and #2 stack on the Brief. Merging `feature/plan-tier-assembly` (or its derivative `feature/plan-tier-assembly-fixes-r2`) before `feature/brief-amendment-q-routing-q-noise` and `feature/brief-amendment-2-inbound-deps` produces a Brief without its amendments. Mitigation: merge in stack order (#1 -> #2 -> Plan-assembly -> fixes-r2), or fold all four into a single PR before merge to main.
- **Q1=(a) single-shot AE under-measures multi-spawn orchestration value** (see eval-harness-v1 Known Limitations). Threatens P3 routing-decision validity. Mitigation: declare via `ae_execution_mode` report field; consider v2 sdk-multiturn or python-conductor-sim if directional signal is ambiguous.
- **60K-token Plan-tier overflow fallback heuristic in skeptic-global-context is unmeasured.** Threshold may not fire reliably; mitigation deferred to prompt-assembly-canonical unit.
- **ICL `rationale_extraction_method = fallback-full-text` produces noisier output-coherence than the production spec.** Surfaced via `rationale_extraction_method_count` in eval-harness-v1 report. P-prod-ICL gate validates upgrade when icl-baseline-spec lands.
