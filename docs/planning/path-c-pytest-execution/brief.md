# Brief: Path C - Real pytest execution for ICL-vs-orchestration eval

**Problem:** The eval harness scores correctness by parsing keyword signals from the agent's prose output. The latest Path A smoke run showed AVG delta +0.0011 between AE and ICL conditions (statistical noise) and the prior "AE wins Plan-tier" signal collapsed to a tie once `verification-realism` was dropped. The prose scorer is too soft to surface real correctness differences; we cannot trust further smoke runs to discriminate the two conditions.

**Success criteria:**
- Tickets that ship a test file in `workspace_files/` produce real pytest pass/fail outcomes that drive the `correctness` dimension instead of keyword approximation.
- Forward-compat: tickets without `test_command` continue to score via the keyword fallback unchanged.
- Misconfigured `test_command` (typo, missing path) produces a loud preflight failure at corpus load, not silent 0.0 scores.
- Symmetric-dimset invariant holds: AE and ICL score on identical dim shapes per ticket.

**Non-goals:**
- Sandboxing or dependency isolation per ticket (single venv shared with the harness).
- Extending the corpus to add more viable tickets in this iteration.
- Adding a new top-level `test-execution` dimension (kept inside `correctness`).

**Constraints:**
- No new runtime dependencies (subprocess, shlex, re are stdlib; pytest is already a project dep).
- Existing result JSON files (pre-Path-C) must remain readable: `_load_completed_scores` must still work.
- Preflight regex MUST search combined stdout+stderr (Skeptic r3 hard constraint - pytest emits ImportError to stdout).

**Verification:** New unit tests at `evals/icl_vs_orchestration/tests/test_test_executor.py`, `tests/test_corpus_preflight.py`, plus extensions to `tests/test_schema.py`, `tests/test_correctness.py`, `tests/test_runner.py` (specs in architect plan section 9). End-to-end smoke run against `r-brief-tier-whole-file` must produce a `test_execution` block in `result.json` and a `correctness_method: "mixed"` label in the report. Existing 167-test scorer suite must remain green.

**QA criteria:**
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: Eval harness is a python library invoked via CLI; no UI surface, no running service. All correctness verified via the harness's own pytest suite.
```

**Linked artifacts:**
- architect-plan: `./architect-plan.md`
- orchestration: `./orchestration.jsonl`
- risk register: `./risk-register.md`
- rollback: `./rollback.md`
- verification gate: `./verification-gate.md`
