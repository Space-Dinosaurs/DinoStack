# Brief: /implement-ticket delegation maximization

**Problem:** The conductor inside `/implement-ticket` performs work that floods its own context window — investigating unfamiliar code, running quality gates, creating worktrees and branches, opening PRs, posting tracker updates, authoring findings entries inline. This degrades its ability to orchestrate longer tasks and multi-ticket batches. Subagents exist for each of these jobs but the command does not consistently route through them.

**Success criteria:**
- Conductor does not run `cd $REPO && $QUALITY_CMD` directly anywhere in the command (engineer reports `quality_gate_results` instead).
- Conductor does not create branches or worktrees on the Elevated path (engineer's execution contract owns it).
- Conductor does not call Linear/Jira MCP tools for tracker write-back in Phase 11 (a tracker-writeback spawn does it).
- Conductor does not author `.agentic/findings.md` entries inline (a findings-curator spawn owns it).
- Trivial single-ticket invocations behave identically to today (no investigator, no batch state, no extended engineer contract).

**Non-goals:**
- Cross-session batch handoff (paused/interrupted/replan/session_id machinery). Deferred to a follow-up Brief.
- Universal investigator on Trivial-classified tickets. Trivial keeps direct-action conductor flow.
- PR-opener spawn. `gh pr create` stays in the conductor (synthesis context savings did not justify the spawn).

**Constraints:**
- Backward compat: single-ticket Trivial invocations are bit-for-bit identical to today.
- All `.agentic/*` writes remain conductor-sole-writer (existing rule).
- Edits stay additive within `content/commands/implement-ticket.md`; section structure preserved.
- Cross-file ripple: one line in `content/agents/engineer.md` for the binding `quality_gate_results` return-shape contract on the Elevated path.
- METHODOLOGY.md and `hooks/stop-context.js` are NOT edited in this Brief.

**Verification:** Inspect the edited `content/commands/implement-ticket.md` against grep checks: zero `cd $REPO && $QUALITY_CMD` in conductor blocks; zero `git checkout -b` in conductor blocks on the Elevated path (Trivial path and fan-out path retain conductor-side worktree creation); zero `mcp__linear__` and `mcp__mcp-atlassian__` outside the tracker-writeback spawn brief; new "Conductor responsibilities (irreducible)" section enumerates at minimum the items the conductor never delegates; new Phase 0a (Batch triage, N≥2) section exists and is gated correctly; Phase 2 investigator trigger reads "Low or above AND unfamiliar"; Findings curator subsection at end of Phase 6 reads from Skeptic's final return with `(pattern_hash, ticket_id)` de-dup. Walk a representative single-ticket Trivial invocation through Phases 1→12 and confirm equivalent end state on these axes: branch created with same naming, commit exists, PR opened with same body shape, tracker updated, loop-state cleared, exit phase reached, no `.agentic/batch-state.json` created, no investigator spawn fired, no findings-curator spawn fired, engineer ran with lightweight contract. Run `bash .claude/build.sh` after the source edit and confirm artifact diffs are clean.

**Open Questions:** none.

**Linked artifacts:** architect-plan: this Brief's scope is the v2 architect plan (revised after Skeptic iteration 1) minus the deferred point 9. Skeptic v2 left 1 Critical + 3 Major findings — all four are concentrated in point 9 and resolved by deferring it. The two remaining Minors (engineer.md conditionality wording; three-paths-for-branch-creation advisory comment) are addressed in implementation. Orchestration: 2 atomic units — (a) `content/commands/implement-ticket.md` additive edits per the architect plan steps 2-12 minus step 9's session_id propagation; (b) `content/agents/engineer.md` one-line conditional return-shape addition (step 1). Sequential, single engineer.
