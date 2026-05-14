# Memory

## User Preferences

- **2026-04-26:** Auto-harness workflow commits are pre-authorized. Do not ask for confirmation before committing routine auto-harness bookkeeping: baseline result TSVs (`evals/results/*.tsv`) and the auto-harness ledger (`evals/results/auto-harness.tsv`). These are non-destructive, workflow-generated artifacts. Proceed autonomously.

## Project Conventions

- **2026-04-28:** This project uses `main` as the sole integration branch. Do not use `develop`/`development` branching model for this repository - all feature/fix/chore work branches from `main` and merges back to `main`.

## Active migrations

- **Path 1 restructure (Wave 1 shipped 2026-04-30, Wave 1.5 + Wave 2 pending):** see docs/planning/p1-path1-restructure-handoff.md

## Session Learnings (2026-04-26/28)

- **2026-04-28: Tier 2 isolator HOME redirect broke Claude CLI auth.** Every command-mode component (implement-ticket, wrap, init-project, prune-harness, memory-update, cleanup-worktrees, update-agentic-engineering, representation-audit) was scoring the 0.2 floor (forbidden_credit only) because the CLI couldn't find auth in the redirected HOME (macOS keychain / Linux .credentials.json). All "command-mode baselines" predating PR #12 are invalid - they measured the floor, not the agents. Re-baseline required before any auto-harness run on command-mode components. Fixed in PR #12 via narrow auth-preservation symlinks in `evals/runner/isolator.py`.
- **Auto-harness success pattern:** Works reliably for agent-mode components with clear scoring headroom and consistent fixture variance. security-auditor (0.750→0.866) and debugger (0.830→1.000) both shipped improvements via the harness.
- **Auto-harness failure pattern (command-mode editor) - HISTORICAL, may need re-validation:** Command-mode components were observed to fail auto-harness via editor timeouts or malformed hunks. Re-validation needed now that auth works - prior diagnoses may have conflated editor failure with the auth bug above.
- **Auto-harness failure pattern (variance inflation):** A single high-variance fixture can inflate `pooled_stdev` so much that the threshold becomes unreachable. architect (threshold ~0.20) and security-auditor retry (threshold ~0.35) both found real improvements that were reverted due to variance.
- **Skeptic structural cap:** The skeptic scorer's `fp_cap = max(max_credit, 1.0) * 0.5` creates a hard 0.500 ceiling when `raw_fp ≥ 0.5`. Prompt edits cannot break through this mathematical cap. Scorer recalibration is required before skeptic can be improved via harness.
- **Wrap component failure:** wrap auto-harness hit plateau after one iteration degraded the score (-0.352) and two others had editor failures. The 0.742 baseline may be near the prompt's local optimum.
- **Ledger preservation bug fixed:** `evals/auto/loop.py` now backs up and restores `evals/results/*.tsv` and `*.runlog.jsonl` across `git reset --hard` so revert iterations don't destroy rows from prior reject iterations in the same run.
- **Baseline generation status:** All 20 components now have at least partial baselines. 7 components are at ceiling (conductor, init-project, qa-engineer, adr-generator, perf-analyst, investigator, cleanup-worktrees). 3 have structural blockers (skeptic cap, release-orchestrator invalid_format fixtures).
- **Kimi CLI agent mapping:** `evals/runner/invoker.py` maps custom agent names to Kimi builtins (`coder`/`explore`/`plan`) and inlines instructions to avoid "Builtin subagent type not found" errors.

## Runtime Context Management (2026-05-14)

Implemented all 5 gaps from `docs/planning/gap-runtime-context-management.md` via 5 PRs:

1. **Gap 1 — Conductor Context Budget** (#88): Added Section 13 to `subagent-protocol.md` with soft limit (15–20 turns) and hard limit (25–30 turns). Referenced in `/brief`, `/implement-ticket`, and `design-goals.md` Goal 4.
2. **Gap 2 — Exchange Log Compression** (#89): Added compression rules to `skeptic-protocol.md` Section 3, compressed 4-round example in Section 11, and Phase 6 step in `implement-ticket.md`.
3. **Gap 3 — Memory Retrieval Tool** (#90): Built `bin/agentic-memory` (Python, stdlib only) with `query` and `turns` subcommands. Documented in `memory-update.md`, `subagent-protocol.md` direct actions, and `AGENTS.md`.
4. **Gap 4 — Long-Session Eval** (#91): Created `evals/long-session/` with 3 YAML fixtures (database, API, test strategy), pass/fail `scorer.py`, and `LEARNINGS.md` section.
5. **Gap 5 — Vicious Loop Defense** (#87): Added meta-divergence sweep pagination to `skeptic-protocol.md` Section 14 and `conventions.md`. Uses `.meta-divergence-last-sweep` timestamp tracker with 100-line cold-start cap.

**Process note:** Architect spawns timed out repeatedly for plan generation. Switched to direct plan file creation from the existing planning doc, then spawned per-gap engineers + skeptics in parallel. This proved more reliable than large architect spawns.

## Next Session Checklist

1. ~~**Fix command-mode auto-harness editor**~~ ✅ DONE (whole-file replacement)
2. ~~**Fix Tier 2 HOME redirect breaking CLI auth**~~ ✅ DONE 2026-04-28 (PR #12)
3. **Re-baseline 8 command-mode components** under fixed isolator: implement-ticket, wrap, init-project, prune-harness, memory-update, cleanup-worktrees, update-agentic-engineering, representation-audit. Old baselines were the 0.2 floor and are invalid.
4. **Recalibrate skeptic scorer** — remove or raise the 0.5 FP cap so skeptic can be improved via harness
5. **Fix release-orchestrator fixtures** ro-002 and ro-005 — they consistently produce `invalid_format`
6. **Add harder fixtures to at-ceiling components** — conductor, init-project, qa-engineer, perf-analyst, cleanup-worktrees, adr-generator, investigator (medians ≥0.90, no headroom)
7. **Run auto-harness on command-mode components** after re-baselining (step 3) and after re-validating the editor pattern
