<!--
Purpose: ICL-vs-orchestration head-to-head eval harness. Runs historical
         tickets under two conditions (AE-orchestrated and ICL-baseline),
         scores on 6 dimensions, tracks cost, and emits a JSON report
         for Stage 3 (pre-restructure baseline) and Stage 6 (post-restructure
         comparison) of the p2-icl-vs-orchestration-evaluation plan.

Public API: CLI entry at cli.py; bun wrapper at run.ts.
  python -m evals.icl_vs_orchestration.cli run --corpus <name> \
    --ae-spec <path> --icl-spec <path> [--smoke] [--smoke-gate] \
    [--max-usd <n>] [--max-tokens <n>]
  bun evals/icl_vs_orchestration/run.ts [same args]

Upstream deps: evals.runner.invoker, evals.runner.normalizer,
               evals.runner.loader (SHA idiom); pyyaml; stdlib.

Downstream consumers: Stage-3 baseline run, Stage-6 comparison run,
                      eval-routing-rules (reads results-v1.json).

Failure modes: BudgetExceeded (exit 3) on global ceiling breach. Corpus
               load errors exit 2. Missing binary exits 4.

Performance: dominated by LLM invocation cost (minutes per ticket, $37/cell
             at the default budget allocation).
-->

# evals/icl_vs_orchestration

Two-condition eval harness: AE-orchestrated vs ICL-baseline, scored on 6 dimensions.

## Required binaries on PATH

- `python3` (3.11+) - harness implementation
- `bun` - TypeScript wrapper; required for `bun run.ts` invocations

Missing either binary causes exit 4 with a descriptive message naming the missing binary.

## Required input artifacts

The following files are consumed by this harness and must exist before a full run:

- `evals/baselines/2026-05-pre-icl-restructure.json` - Stage-0 baseline;
  provides `git.agentic_engineering_sha` as the AE `content_sha` pin.
  Pass via `--baseline <path>` to the CLI.

- `docs/planning/p2-icl-vs-orchestration-evaluation/scenarios-todo.md` -
  Skeptic Step-0 enforcement scenarios (authored by `skeptic-global-context`).
  Required for full smoke fixture construction. NOT required for smoke runs
  against the current stub fixtures; see COVERAGE.md for the current binding.

- `docs/planning/p2-icl-vs-orchestration-evaluation/cost-normalization-contract.md` -
  Cost-confounder normalization contract (authored by `skeptic-global-context`).
  Required before finalizing the report schema. Stubbed in `cost_gate.py` and
  `report.py` with `cost_normalization_pending: true` markers.

## Quick start (smoke run)

```bash
python -m evals.icl_vs_orchestration.cli run \
  --corpus smoke \
  --ae-spec evals/icl_vs_orchestration/specs/ae-orchestrated.yaml \
  --icl-spec evals/icl_vs_orchestration/specs/icl-baseline.yaml \
  --smoke
```

Or via bun:
```bash
bun evals/icl_vs_orchestration/run.ts \
  --corpus smoke \
  --ae-spec evals/icl_vs_orchestration/specs/ae-orchestrated.yaml \
  --icl-spec evals/icl_vs_orchestration/specs/icl-baseline.yaml \
  --smoke
```

## Module map

```
evals/icl_vs_orchestration/
  cli.py          - argparse entry point (run + resume subcommands)
  runner.py       - orchestration loop
  corpus.py       - corpus loader + baseline SHA reader
  schema.py       - YAML schema validators
  cost_gate.py    - global + per-cell budget enforcement
  metering.py     - token extraction + cost estimation
  smoke_gate.py   - >2x dominance check after smoke run
  report.py       - report assembler + validator
  run.ts          - bun wrapper (delegates to cli.py)
  conditions/
    base.py       - Protocol + TypedDicts + rationale extraction rule
    ae_orchestrated/
      single_shot.py - Q1=(a) single-shot AE adapter
    icl_baseline.py  - ICL-baseline adapter
    icl_spec.py      - ICL spec loader + prompt assembler
  scoring/
    registry.py         - scorer registry + aggregation
    weights.yaml        - dimension weights (must sum to 1.0)
    correctness.py      - Q2=(b) test-pass + (a) AC-keyword fallback
    scope_discipline.py - file-set inclusion check
    quality_gate_pass.py
    regression_test_presence.py
    verification_realism.py - floors ICL at 0.0 by design
    output_coherence.py     - binarized-per-type formula (v1)
  corpora/
    smoke/
      manifest.yaml
      COVERAGE.md   - per-condition dimension binding matrix
      tickets/<id>/
        ticket.yaml
        architect_plan.md (optional)
        relevant_files/
  specs/
    ae-orchestrated.yaml  - stub; update content_sha at Stage-3 run
    icl-baseline.yaml     - stub; update template_path when icl-baseline-spec lands
  results/
    <run_id>/
      results-v1.json   - committed after each Stage run
  tests/
    test_*.py
```

## Overfitting notice

See `evals/OVERFITTING-RULE.md`. Do not tune scorer weights or content/
based on individual fixture scores from this harness.

## Known limitations

- `cost_normalization_pending: true` in report output: cost-confounder
  normalization fields are stubbed pending `cost-normalization-contract.md`
  delivery. Do not compare absolute cost figures across Stage 3 and Stage 6
  until this is implemented.
- AE single-shot mode (Q1=(a)) measures "can the full AE context produce
  a good result in one shot"; it does not measure orchestration value.
  See `ae_execution_mode` field in the report.
- rationale_extraction_method="fallback-full-text" in smoke runs indicates
  the v1 stub ICL spec lacks a structured prompt template. Expected behavior
  until `icl-baseline-spec` lands.
