## QA Gate

**QA fires for every Elevated unit unless `qa_skip` is one of the 5 valid enum values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`.** The rationale is logged in the Brief / architect plan. A project having no `qa.md` is NOT a reason to skip QA. The `qa_default_skip` key in `.agentic/config.json` is reserved and inert (canonical definition in `content/references/planning-artifacts.md`).

**Concurrent QA + Skeptic for UI-visible changes.** When a unit's `qa_criteria` indicates QA fires (`qa_skip == null`, scenarios non-empty), spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. For non-UI or deferred-QA paths, the post-Skeptic QA flow applies. See `content/references/qa-gate.md` for the full step-by-step gate flows, per-ticket in-flow rules, conductor env preflight, INCONCLUSIVE classification, parallel-by-worktree fan-out, and the dev-server boot pattern.

### Diff-read rule and review ordering

**For Elevated correctness, security, auth, crypto, or payments units, the Skeptic MUST read the diff in full before sign-off. QA evidence is supplementary - it confirms runtime behavior but does not substitute for line-by-line diff review. On these units the review order is fixed: diff first, QA evidence second.**

For behavior-visible Elevated units that are not in the exclusion set above (UI changes, behavioral feature additions), the Skeptic SHOULD read the diff AND the QA evidence. When both are present, the Skeptic may use QA evidence as the primary signal for UI correctness claims, but diff review remains required for logic, side effects, and security surface.

For Low or Trivial units, the Skeptic applies its inline self-check. QA is not spawned for Trivial units (direct action path); QA for Low units follows the standard flow above.

**Reading 'diff is secondary' as 'diff is optional' on any Elevated unit is a protocol violation.** The diff obligation is unconditional for Elevated units; only the ordering and primary-signal weight differ by risk class.

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
