# Risk Register

- **R1: Preflight false-positive (collapsed by Skeptic r2 → r3 fix).** Open: regex must search combined stdout+stderr per Skeptic r3 hard constraint. Mitigation: encoded as engineer execution-contract requirement on `corpus-preflight` unit.
- **R2: Single-ticket signal underpowering.** Only `r-brief-tier-whole-file` carries real test execution in v1; AE-vs-ICL delta on Path C may not be statistically meaningful. Mitigation: documented v1 limitation; corpus diversification is a known follow-up.
- **R3: Workspace rootedness via `PYTHONPATH=workspace`.** Tickets whose test files import package-rooted symbols from outside the workspace will fail collection. Mitigation: tolerant preflight emits `log.warning` and defers to runtime.
- **R4: Stale `test_execution` on resume.** Resume re-uses stored test_execution without re-running preflight. Mitigation: documented in AGENTS.md known limitations.
- **R5: Symmetric-dimset invariant breakage.** New `test_execution` injection runs for both AE and ICL on the same workspace pre/post agent. Verified by integration Skeptic on combined corpus+runner+correctness diff.
- **R6: `_load_completed_scores` resume on old result JSON.** Old files lack `test_execution`; first-path check in `correctness.py` falls through to keyword fallback. Forward-compat preserved by `result.get("test_execution")` returning None.
