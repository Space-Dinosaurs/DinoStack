# Verification Gate

**Tests that must pass:**
- Unit: `pytest evals/icl_vs_orchestration/tests/ -x -q` (target: 0 failures; existing 167 tests + new test cases per unit-G acceptance criteria)
- Integration: end-to-end smoke run via `python -m evals.icl_vs_orchestration.cli --smoke --corpus replay --ae-spec specs/ae-orchestrated.yaml --icl-spec specs/icl-baseline.yaml`; verify `result.json` for `r-brief-tier-whole-file` contains `test_execution` block with `outcome ∈ {pass, fail}` and `returncode` set
- E2E: report-level assertion that `correctness_method == "mixed"` (one ticket has test_command, four have null) in the smoke results

**qa-engineer triggered?** No. `qa_criteria.qa_skip: pure-backend-library` per the Brief - no UI, no running service, no API surface beyond the CLI itself.

**Manual smoke check:** Operator runs `pytest evals/icl_vs_orchestration/tests/ -x -q` from the submodule root and confirms 0 failures. Operator runs the smoke CLI invocation above against the replay corpus and inspects `results/<run_id>/result.json` for at least one ticket showing the new `test_execution` field with the expected shape.

**Rollback signal:** Any unit-G test failure post-merge, OR a smoke run that aborts with an unexpected `RuntimeError` from `corpus.preflight_test_commands`, OR `correctness_method` field absent from the report. Hand-off to `rollback.md`.

**New regression tests required by findings flywheel?** No new entries in `.agentic/findings.md` mandate Path C regression tests; the unit-G test suite already covers each acceptance criterion. Verified by inspection of `.agentic/findings.md` (deleted in current parent state).
