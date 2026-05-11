# Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Direct two-level Task spawn does not preserve frontmatter at invocation | Low | Critical | Canary in unit 4 before seeding any non-baseline cell; halt and surface to operator on failure. |
| 2 | Tier 3 Docker isolator is more work than estimated | Medium | Major | Scope to Python-only + pytest-only + single base image; descope multi-language. If still over-budget, defer to follow-up and ship Tier-2 code-review corpus as v0.5 with documented caveat. |
| 3 | Task corpus too small to discriminate; all conditions converge to same score | High | Major | Mandatory sensitivity check in unit 7 before declaring done; baseline-vs-baseline n=5 replicates establish the envelope; expand corpus or pick harder tasks if <60% of tasks move outside the envelope on the methodology delta or on a plausible per-agent prompt edit. |
| 4 | `ae-rules-injected` payload diverges from real production activation (no preflight, no MEMORY.md, no sentinel, no Stop hook, no per-command preflight) | High | Major | Condition labeled `ae-rules-injected` (not `ae-skill`); production-layer disclosure table in Brief and README; QA scenario 4 asserts label + table are published; `ae_rules_payload.py` builds payload deterministically from globbed file set with content-glob cache invalidation. |
| 5 | Overfitting to corpus (humans tune agents to pass these specific tasks) | Medium | Major | Overfitting Rule binding; commit messages must cite task fixture; periodic corpus rotation (annual); corpus is frozen between rotations. |
| 6 | Held-out test leakage (agent reads test files during fix phase) | Medium | Critical | Tier 3 mounts held-out tests at a path separate from worktree, read-only; isolator unit-test in unit 2 asserts in-container read attempt fails with ENOENT or EACCES. |
| 7 | `baseline` condition is ambiguous (what counts as "no methodology"?) | Medium | Major | Define `baseline` precisely in README; document `~/.claude/CLAUDE.md` confound; do NOT silently treat baseline as methodology-free. |
| 8 | Cost or wall-clock ceiling exceeded mid-run | Medium | Major | `BudgetExceeded` exit-3 via existing `cost_gate.py` pattern; runner halts and emits a partial report. |
