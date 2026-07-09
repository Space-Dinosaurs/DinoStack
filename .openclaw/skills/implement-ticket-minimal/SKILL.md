---
name: implement-ticket-minimal
description: "Take a ticket (Linear, Jira, or none) from description to a merged PR with the smallest viable agent flow (engineer + Skeptic, no architect, no planner, no Brief artifact, no QA gate, no wrap-ticket, "
user-invocable: true
---
# Implement Ticket (minimal tier)

> Tier resolved by the router (`implement-ticket.md`); this body executes only when the active tier is `minimal`. Do not invoke this file directly. The router reads its own tier resolution (CLI flag > project config > global config > legacy `profile` alias > default `minimal`) and dispatches here for `tier=minimal`.

Take a ticket (Linear, Jira, or none) from description to a merged PR with the smallest viable agent flow (engineer + Skeptic, no architect, no planner, no Brief artifact, no QA gate, no wrap-ticket, no loop-state, no events log, no batch contracts beyond N=1). The `$ARGUMENTS` value passed to `/implement-ticket` is propagated here as-is; bare ticket IDs, single-issue URLs, and freeform text are accepted (Phase 0 input normalization is bypassed on this tier — conductor passes input straight to the engineer prompt).

---

## Tier=minimal execution (replaces full tier flow)

This body replaces the full tier flow entirely. The full tier body (`implement-ticket-full.md`) does not apply. Follow this section end-to-end.

**Skips (do not run):**

- Brief/Plan artifact authoring (`docs/planning/<slug>.md`).
- Architect spawn, orchestration-planner spawn.
- Capability preflight block.
- `loop-state.json` writes (no resume anchor; if interrupted, the next invocation starts fresh).
- `events.jsonl` writes.
- `wrap-ticket` end-of-session tracker sync.
- Phase 6b QA gate.
- Batch contracts beyond N=1 (no `batch-state.json`).

### Phase M-0: Risk classify

Classify risk inline:

- **Trivial:** 1 file, no behavior/API/shared-token change, no auth/surface, reversible one-liner. Direct edit.
- **Low:** 1 file local behavioral edit, no cross-component data flow, no security surface. Direct edit + self-check.
- **Elevated:** anything else. Worker + Skeptic.

### Phase M-1: Engineer spawn (Trivial / Low / Elevated)

1. `isolation: worktree`. Branch from `origin/main`.
2. Engineer prompt: target files, acceptance criteria, `$QUALITY_CMD`, base branch.
3. No Brief artifact. No architect. No planner.
4. Engineer returns `diff_summary`, `commit_sha`, `pr_url`, `quality_gate_results`.

### Phase M-2: Self-check (Low only)

Low: re-read diff in full before merge. Verify intent, edge cases, side effects. On concern: reclassify as Elevated and re-run from Phase M-1.

### Phase M-3: Skeptic review (Elevated only)

1. Read diff in full (`git diff origin/$BASE_BRANCH..HEAD`).
2. Findings: Critical/Major/Minor.
3. Cap 3 fix passes. Convergence failure escalates.
4. Sign-off: granted | blocked.

### Phase M-4: Quality gate + PR

1. Run `$QUALITY_CMD` (engineer already ran it; conductor spot-checks via CI).
2. Conductor opens PR via `gh pr create` if engineer did not.
3. PR body: result-led, bullets over prose, evidence. No AI attribution.

### Phase M-5: Cleanup

1. Remove isolation worktree: `git worktree remove .agentic/worktrees/<branch>`.
2. No `wrap-ticket` (use `/wrap` for plain-text session summary if needed).

### Trivial path (Phase M-T)

For Trivial risk: skip Skeptic, skip worktree-isolation prompt ceremony. Direct edit in main checkout only if zero behavior change AND no other file references it. Otherwise delegate to worktree-isolated engineer with no brief and no Skeptic.
