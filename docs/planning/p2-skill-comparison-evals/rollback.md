# Rollback

**Blast radius:** evals/ tree only; no production runtime, no consumers outside operator-invoked eval runs.

**Undo procedure:**
1. Revert or close the PR before merge; if already merged, open a revert PR.
2. After revert, delete `evals/skill-comparison/` (entire subtree) and the Tier 3 additions in `evals/runner/isolator.py` (the `tier_3_docker` function + Dockerfile.swebench + entrypoint).
3. Remove any `skill-comparison.tsv` rows under `evals/results/`.
4. No data migration, no schema change, no deployed artifact - this is an offline eval harness, not a service.

**When to trigger:** sensitivity check (QA scenario 2) repeatedly fails across two corpus iterations AND no plausible prompt edit moves >=60% of tasks outside the envelope. At that point the eval is not discriminating and shipping it would mislead future content/ edits via the Overfitting Rule.

**Non-triggers:** single bad run, single failed task, transient Docker flake - retry per the existing harness retry policy, do not roll back.
