# Rollback

Each unit reverts independently. Reverse merge order on cross-unit revert.

- **`evals-baseline-capture`**: revert the baseline JSON commit. The file lives under `evals/baselines/` with no other consumers.
- **`eval-harness-v1`**: revert the entire `evals/icl-vs-orchestration/` directory. No existing importers; safe to delete wholesale.
- **`skeptic-global-context`**: revert the `content/` edits AND the new artifacts (`scenarios-todo.md`, `cost-normalization-contract.md`). Skeptic protocol returns to the current 3-input baseline; Skeptic Step-0 BLOCKED behavior disappears; iteration counter unchanged.
- **Cross-unit dependency.** `skeptic-global-context`'s artifacts are consumed by `eval-harness-v1`. Reverting `skeptic-global-context` first leaves the harness consuming missing files. Revert in reverse merge order: `eval-harness-v1` first, then `skeptic-global-context`, then `evals-baseline-capture`.
