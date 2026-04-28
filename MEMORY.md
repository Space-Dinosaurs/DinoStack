# Memory

## User Preferences

- **2026-04-26:** Auto-harness workflow commits are pre-authorized. Do not ask for confirmation before committing routine auto-harness bookkeeping: baseline result TSVs (`evals/results/*.tsv`) and the auto-harness ledger (`evals/results/auto-harness.tsv`). These are non-destructive, workflow-generated artifacts. Proceed autonomously.

## Project Conventions

- **2026-04-28:** This project uses `main` as the sole integration branch. Do not use `develop`/`development` branching model for this repository - all feature/fix/chore work branches from `main` and merges back to `main`.

## Session Learnings (2026-04-26/27)

- **Auto-harness success pattern:** Works reliably for agent-mode components with clear scoring headroom and consistent fixture variance. security-auditor (0.750→0.866) and debugger (0.830→1.000) both shipped improvements via the harness.
- **Auto-harness failure pattern (command-mode):** Command-mode components (implement-ticket, update-agentic-engineering, memory-update) consistently fail auto-harness due to editor diff generation issues — either timeouts (>600s) or malformed hunks that `git apply --recount --3way` cannot resolve. The editor does not handle command-file briefs well.
- **Auto-harness failure pattern (variance inflation):** A single high-variance fixture can inflate `pooled_stdev` so much that the threshold becomes unreachable. architect (threshold ~0.20) and security-auditor retry (threshold ~0.35) both found real improvements that were reverted due to variance.
- **Skeptic structural cap:** The skeptic scorer's `fp_cap = max(max_credit, 1.0) * 0.5` creates a hard 0.500 ceiling when `raw_fp ≥ 0.5`. Prompt edits cannot break through this mathematical cap. Scorer recalibration is required before skeptic can be improved via harness.
- **Wrap component failure:** wrap auto-harness hit plateau after one iteration degraded the score (-0.352) and two others had editor failures. The 0.742 baseline may be near the prompt's local optimum.
- **Ledger preservation bug fixed:** `evals/auto/loop.py` now backs up and restores `evals/results/*.tsv` and `*.runlog.jsonl` across `git reset --hard` so revert iterations don't destroy rows from prior reject iterations in the same run.
- **Baseline generation status:** All 20 components now have at least partial baselines. 7 components are at ceiling (conductor, init-project, qa-engineer, adr-generator, perf-analyst, investigator, cleanup-worktrees). 3 have structural blockers (skeptic cap, release-orchestrator invalid_format fixtures).
- **Kimi CLI agent mapping:** `evals/runner/invoker.py` maps custom agent names to Kimi builtins (`coder`/`explore`/`plan`) and inlines instructions to avoid "Builtin subagent type not found" errors.

## Next Session Checklist

1. **Merge PRs #6 and #7** (security-auditor + debugger improvements)
2. **Fix command-mode auto-harness editor** — either increase editor timeout beyond 1200s, switch to whole-file replacement for command files, or fix the diff generation pipeline so malformed hunks stop appearing
3. **Recalibrate skeptic scorer** — remove or raise the 0.5 FP cap so skeptic can be improved via harness
4. **Fix release-orchestrator fixtures** ro-002 and ro-005 — they consistently produce `invalid_format`; need to understand why and adjust fixture or agent config
5. **Add harder fixtures to at-ceiling components** — conductor, init-project, qa-engineer, perf-analyst, cleanup-worktrees all have medians ≥0.90 and need more challenging fixtures to create headroom
6. **Run auto-harness on remaining command-mode components** after editor fix — update-agentic-engineering (0.43), prune-harness (0.45), memory-update (0.60), implement-ticket (0.20) all have baselines but couldn't enter the harness due to editor issues
7. **Push chore/karpathy-session** to origin — 22 commits ahead of remote
