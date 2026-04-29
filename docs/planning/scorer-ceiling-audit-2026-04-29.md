# Scorer Ceiling Audit - 2026-04-29

## Summary

Total components audited: 20
TSV baselines available: 16
TSV baselines missing: 4 (adr_drift_detector, adr_generator, dependency_auditor, investigator)

Tier breakdown (by fixture):

| Tier | Label | Count | Components |
|---|---|---|---|
| A | Prompt-improvable | 11 fixtures across 7 components | architect (5), conductor (partial), debugger (1), memory_update (1), prune_harness (1), representation_audit (5), update_agentic_engineering (1), wrap (2) |
| B | Scorer-bound | 10 fixtures across 3 components | init_project (8), release_orchestrator (1), security_auditor (1) |
| C | At-ceiling | 21 fixtures across 5 components | cleanup_worktrees (5), implement_ticket (5), perf_analyst (1), qa_engineer (1), plus partial fixtures in wrap/prune_harness/memory_update/skeptic |
| D | Parser-bound | Multiple fixtures, 1 component | conductor (several 0.0 fixtures) |
| E | Unknown | 0 | - |
| Missing | No TSV | - | adr_drift_detector, adr_generator, dependency_auditor, investigator |

**Key headline findings:**

1. `skeptic` has a structural fp_cap that creates a hard floor of ~0.5 for any TP-complete run with FP noise (`skeptic_lite.py` line 262). This is NOT a prompt problem on those fixtures - the scorer caps FP penalty at 50% of max_credit.

2. `representation_audit` plateaus at 0.85 across all 5 fixtures because `_count_candidate_credit()` consistently returns 0.0 when the agent produces out-of-range candidate counts. The 0.15 weight on that dimension is permanently lost. This IS prompt-improvable if the agent learns the correct range.

3. `init_project` is scorer-bound at 0.95 across all 8 fixtures. The scorer penalizes an unexpected `.claude/` file with `_EXTRAS_UNEXPECTED = 0.05`, and every fixture triggers this. Fixing requires either a scorer change or fixture change, not prompt improvement.

4. `conductor` has multiple 0.0 fixtures caused by parser failure (agent not emitting the required `## Routing decision (machine-readable)` JSON block). These are Tier D - format/prompt fixable but distinct from scorer ceiling.

---

## Recommended Action Ordering

1. **Fix conductor format (Tier D, high leverage):** Multiple fixtures scoring 0.0 due to parser failure. A prompt fix to enforce the required JSON block header would lift those fixtures substantially. No scorer change needed.

2. **Fix representation_audit prompt (Tier A, low risk):** Agent consistently produces out-of-range candidate counts. Add explicit count-range guidance to the prompt. Theoretical max is 1.0 - full 0.15 weight recoverable.

3. **Fix architect prompt (Tier A):** `open_questions` dimension commonly scores 0.0 (non-None when should be None, or absent). Explicit prompt instruction to leave open_questions empty when resolved would improve ar-001 and likely others.

4. **Fix debugger prompt (Tier A):** `root_cause_locality` at file+symbol tier (0.6) rather than file:line (1.0). Prompt improvement to always include line numbers in root cause citations would recover 0.4 weight on that dimension.

5. **Review init_project scorer (Tier B):** The unexpected `.claude/` file penalty is universal across all 8 fixtures - this is a fixture or scorer design issue, not a prompt issue. Scorer team should decide if `.claude/` creation is acceptable behavior and update `_EXTRAS_UNEXPECTED` mapping or fixture expected outputs accordingly.

6. **Review release_orchestrator scorer (Tier B):** `_BYPASS_CAP = 0.5` is hit because the agent emits `--force`. This may be intentional design (flag unsafe CLI usage) but the cap makes the fixture permanently scorer-limited. Decide if this is a valid ceiling or a scorer design choice to revisit.

7. **Review skeptic fp_cap (Tier B):** The bounded FP formula at line 262 ensures any TP-complete run with FP noise scores no higher than 0.5. This prevents the score from exceeding 0.5 on noisy fixtures. Whether this is intentional (punish false positives hard) or an inadvertent structural cap is a scorer design question, not prompt.

8. **Collect missing TSVs (Tier E - blocked):** adr_drift_detector, adr_generator, dependency_auditor, investigator have no baselines. Run evals on these components before any optimization targeting.

---

## Per-Fixture Table

| Component | Fixture ID | Current Median | Stdev | Theoretical Max | Ceiling Cause | Improvability Tier |
|---|---|---|---|---|---|---|
| architect | ar-001 | 0.95000 | 0.0 | 1.0 | none | A |
| architect | ar-002 | 0.87125 | 0.0 | 1.0 | none | A |
| architect | ar-003 | 0.92778 | 0.0 | 1.0 | none | A |
| architect | ar-004 | 0.84500 | 0.0 | 1.0 | none | A |
| architect | ar-005 | 0.82857 | 0.0 | 1.0 | none | A |
| cleanup_worktrees | cw-001..005 | 1.00000 | 0.0 | 1.0 | none | C |
| conductor | cn-001..003 | 1.00000 | 0.0 | 1.0 | none | C |
| conductor | cn-004 | 0.00000 | 0.0 | 1.0 | none | D |
| conductor | cn-005 | 0.28571 | 0.0 | 1.0 | none | A/D |
| conductor | cn-006 | 0.00000 | 0.0 | 1.0 | none | D |
| conductor | cn-007 | 0.00000 | 0.0 | 1.0 | none | D |
| debugger | db-001 | 0.78000 | 0.0 | 1.0 | none | A |
| implement_ticket | it-001..005 | 1.00000 | 0.0 | 1.0 | none | C |
| init_project | ip-001..008 | 0.95000 | 0.0 | 0.95* | extras_cap | B |
| memory_update | mu-001 | 0.85000 | 0.0 | 1.0 | none | A |
| memory_update | mu-002..005 | 1.00000 | 0.0 | 1.0 | none | C |
| perf_analyst | pa-001 | 1.00000 | 0.0 | 1.0 | none | C |
| prune_harness | ph-001..003,005 | 1.00000 | 0.0 | 1.0 | none | C |
| prune_harness | ph-004 | 0.60000 | 0.0 | 1.0 | none | A |
| qa_engineer | qe-001 | 1.00000 | 0.0 | 1.0 | none | C |
| release_orchestrator | ro-001 | 0.50000 | 0.0 | 0.50* | branch_cap | B |
| representation_audit | ra-001..005 | 0.85000 | 0.0 | 0.85* | dimension_cap | A |
| security_auditor | sa-001 | 0.75000 | 0.0 | 1.0** | fp_cap | B |
| skeptic | sk-001 | 0.50000 | 0.0 | 1.0** | fp_cap | B |
| skeptic | sk-002 | 0.87500 | 0.0 | 1.0 | none | A |
| skeptic | sk-003 | 1.00000 | 0.0 | 1.0 | none | C |
| skeptic | sk-004 | 0.83333 | 0.0 | 1.0 | none | A |
| skeptic | sk-005 | 0.72917 | 0.0 | 1.0 | none | A |
| skeptic | sk-006 | 0.50000 | 0.0 | 1.0** | fp_cap | B |
| skeptic | sk-007 | 0.66667 | 0.0 | 1.0 | none | A |
| skeptic | sk-008..012,015 | 0.50000 | 0.0 | 1.0** | fp_cap | B |
| skeptic | sk-013 | 0.00000 | 0.0 | 1.0 | none | A |
| skeptic | sk-014 | 1.00000 | 0.0 | 1.0 | none | C |
| update_agentic_engineering | uae-001..003,005 | 1.00000 | 0.0 | 1.0 | none | C |
| update_agentic_engineering | uae-004 | 0.80000 | 0.0 | 1.0 | none | A |
| wrap | wr-001,003..006,008 | 1.00000 | 0.0 | 1.0 | none | C |
| wrap | wr-002 | 0.92500 | 0.0 | 1.0 | extras_cap | A/B |
| wrap | wr-007 | 0.92500 | 0.0 | 1.0 | extras_cap | A/B |
| adr_drift_detector | - | - | - | - | unknown | Missing |
| adr_generator | - | - | - | - | unknown | Missing |
| dependency_auditor | - | - | - | - | unknown | Missing |
| investigator | - | - | - | - | unknown | Missing |

*Practical ceiling under current scorer logic - theoretical max is 1.0 but requires scorer change.
**Scorer ceiling under current FP-cap formula; agent can recover by reducing FP rate.

---

## Per-Component Findings

### architect (Confidence: HIGH)
5 fixtures, all Tier A. Dimensions: proposal_structure (0.15), constraints_captured (0.20), open_questions (0.15), risk_items (0.15), implementation_units (0.20), component_map (0.15). ar-001 (0.95): `open_questions` dimension scores 0.0 - diagnostic shows `{expected: 'none', is_none: false}`. ar-002..005 (0.828-0.927): various dimension misses; no structural cap. **Recommended: prompt improvement to clear `open_questions` when resolved.**

### cleanup_worktrees (Confidence: HIGH)
5 fixtures all at 1.0. Saturated; no productive harness headroom.

### conductor (Confidence: HIGH)
7 fixtures. cn-001/002/003 at 1.0. cn-004/006/007 at 0.0 (Tier D - parser failure: missing `## Routing decision (machine-readable)` JSON block). cn-005 at 0.285714 (~2/7): partial match. **Critical fix: enforce the JSON block format in the conductor prompt.**

### debugger (Confidence: MEDIUM, n=1)
db-001 at 0.78. `root_cause_locality` at file+symbol tier (0.6 / 1.0); `diagnosis_keywords` at 0.5. Prompt improvement to include line numbers and match keyword vocabulary recovers gap.

### implement_ticket (Confidence: HIGH)
5 fixtures at 1.0. Saturated.

### init_project (Confidence: HIGH)
8 fixtures all at 0.95 (Tier B). Diagnostic confirms across all: `extras_penalty: 0.05, unexpected_claude_md: 1`. Every fixture expects no `.claude/` directory but agent creates one. **Decision required:** is `.claude/` creation expected behavior? If yes, remove `unexpected_claude_md` from extras mapping; if no, the prompt needs to suppress it.

### memory_update (Confidence: HIGH)
mu-001 at 0.85 (Tier A) - likely `supersedes_old` dimension scoring 0.0 on new-entry path. mu-002..005 at 1.0.

### perf_analyst (Confidence: LOW, n=1)
pa-001 at 1.0. Insufficient data.

### prune_harness (Confidence: HIGH)
ph-001/002/003/005 at 1.0. ph-004 at 0.6 - `signal_discipline` dimension (weight=0.40) scores 0.0. Tier A.

### qa_engineer (Confidence: LOW, n=1)
qe-001 at 1.0. Insufficient data.

### release_orchestrator (Confidence: HIGH)
ro-001 at 0.5 (Tier B). `_BYPASS_CAP = 0.5` triggered by agent emitting `--force`. Diagnostic: `bypass_capped: true, bypass_hits: ["--force"]`. **Decision required:** is the cap firing the desired behavior (test of unsafe-CLI rejection) or a defect (prompt should avoid `--force`)?

### representation_audit (Confidence: HIGH)
5 fixtures all at 0.85 (Tier A, dimension_cap). `candidate_count` (weight=0.15) scores 0.0 on every fixture. `_count_candidate_credit()` returns 0.0 when count is outside `[proposal_min_candidates, proposal_max_candidates]` (e.g., ra-001 expects 3-10). **Fix: prompt the agent to read the fixture's candidate range and enforce it in output.** Range varies per fixture - editor needs visibility into fixture YAMLs (currently locked).

### security_auditor (Confidence: MEDIUM, n=1)
sa-001 at 0.75. Same fp_cap formula as skeptic. Correctness dim at 0.5 (cap hit); other 5 dimensions at 1.0. Math: `0.50 * 0.5 + 0.15 + 0.10 + 0.10 + 0.10 + 0.05 = 0.75`. Recoverable to 1.0 if agent eliminates FPs.

### skeptic (Confidence: HIGH)
15 fixtures. 8 at 0.5 (fp_cap, Tier B). 4 at 0.66-0.875 (Tier A). 2 at 1.0. 1 at 0.0 (Tier A - all TPs missed). The fp_cap floor: `primary = (max_credit - fp_cap) / max_credit = 0.5` whenever cap fires. **Reducing fp_cap firing requires either prompt-side FP reduction or scorer redesign.**

### update_agentic_engineering (Confidence: HIGH)
uae-001/002/003/005 at 1.0. uae-004 at 0.8 - the `both_ahead/divergent` `stop_divergent` case. `commit_credit=0.0` on stop path where HEAD advanced. Tier A.

### wrap (Confidence: MEDIUM)
6 fixtures at 1.0. wr-002 and wr-007 at 0.925 - extras_cap firing on 1 unexpected file. Diagnostic JSON not parsed; classification A/B pending.

### adr_drift_detector / adr_generator / dependency_auditor / investigator (Confidence: LOW, no TSV)
Scorer code analyzed; no baseline data. Run baselines before targeting.

---

## Methodology Notes

1. Data sources: 16 TSV baselines at `/evals/results/`, all 20 scorer modules at `/evals/scoring/`, fixture YAMLs for skeptic and representation_audit.

2. Stdev=0.0 across all TSVs likely means n=1 per fixture, not deterministic confidence.

3. Theoretical max "1.0" = no structural cap in scorer. "0.95*" / "0.50*" = cap reached at that value; reaching 1.0 requires a scorer change, not a prompt change.

4. fp_cap math: `fp_cap = max(N, 1.0) * 0.5` where N = max_credit. Maximum achievable score when cap fires = `(N - N*0.5) / N = 0.5`. Mathematical floor; not a configurable parameter.

5. Tier D = parser-bound (format failure forcing 0.0). Distinct from Tier A (substantive quality improvement) because the gap is parsing, not content.

---

## Open Questions

1. Missing TSV baselines for 4 components - run baselines before targeting.
2. release_orchestrator ro-001 fixture intent - deliberate `--force` test or agent defect?
3. wrap wr-002/007 specific unexpected file unconfirmed (diagnostic JSON not parsed).
4. memory_update mu-001 dimension miss inferred from math, not diagnostic JSON.
5. conductor cn-001/002/003 (passing) vs cn-004/006/007 (failing) format difference - fixture YAMLs not read.
6. skeptic sk-013 (score 0.0) - all TPs missed; fixture or prompt issue?
7. skeptic fp_cap design intent - intentional FP punishment or inadvertent structural cap?

---

## Confidence

**Medium overall.** Scorer code fully read for all 20 components; TSV data read for 16. Tier B ceiling causes traced to exact code lines (skeptic fp_cap line 262, init_project _EXTRAS_UNEXPECTED, release_orchestrator _BYPASS_CAP line 84). Tier A classifications inferred from score math; specific agent behaviors not verified by reading fixture YAML + agent output pairs for most components. 4 missing TSVs reduce overall confidence from High to Medium.
