# Brief: Path B - replay corpus expansion v2

**Problem:** Current corpus (5 tickets) yielded AVG AE +0.1451 vs ICL on first Path C smoke (run `415824f0a793`). Only 1 ticket carries real test execution; the other 4 use prose keyword fallback. Sample size is too small to interpret the +0.1451 signal with confidence; plan-tier has 1 ticket only.

**Success criteria:**
- 4 new replay tickets land in `corpora/replay/tickets/`: `r-single-elev-mean-of-medians`, `r-trivial-preserve-results`, `r-single-elev-parse-subagent`, `r-brief-tier-calibrate-density`.
- Each new ticket's synthetic test passes against the merge-commit diff and FAILS against pre-merge state (real signal, not pattern-match).
- Corpus manifest includes the new ticket slugs; `build_replay_corpus.py` `TICKETS` dict captures pre-merge SHAs.
- `evals/icl_vs_orchestration/AGENTS.md` documents synthetic-test visibility as a known limitation per the Skeptic-flagged Major.

**Non-goals:**
- Plan-tier does not reach 3-ticket target in v2 (stays at 1; v3 mining from `agentic-factory/`/`helios/`).
- Trivial does not reach 3-ticket target in v2 (stays at 2; least-differentiating class).
- OpenCode TypeScript plugin and 2 bash-script tickets are descoped (no Python pytest path).

**Constraints:**
- Synthetic tests use `importlib.machinery.SourceFileLoader` (NOT `spec_from_file_location` - fails for hyphenated paths).
- Path C HARD CONSTRAINT applies: preflight regex on combined stdout+stderr.
- Each synthetic test runs <5s, stdlib-only deps, AC-grounded in original PR commit message.

**Verification:** Each ticket Worker must run viability gate before marking DONE: (1) `pytest --collect-only <test_path>` exits 0 or import-deferred from repo root; (2) test FAILS on pre-merge `workspace_files/` state; (3) test PASSES after merge diff is applied. After all 4 tickets land, run `python3 -m pytest evals/icl_vs_orchestration/tests/ -q` (existing 196 tests must remain green) and a fresh smoke run (`python3 -m evals.icl_vs_orchestration.cli run --corpus replay --smoke ...`) to confirm `correctness_method: "mixed"` with at least 2 `test-pass-real` per-ticket diagnostics (existing whole-file + new mean-of-medians).

**QA criteria:**
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: Replay corpus is data + scripts, no UI, no running service. Verification via pytest viability gate per ticket.
```

**Linked artifacts:**
- architect-plan: `./architect-plan.md` (compiled from r1 + r2 revisions; r2 closes 2 Critical + 1 Major from Skeptic)
- orchestration: 4 ticket-authoring units in parallel + 1 manifest update + 1 build_replay_corpus.py update; manifest+build depend on tickets landing
