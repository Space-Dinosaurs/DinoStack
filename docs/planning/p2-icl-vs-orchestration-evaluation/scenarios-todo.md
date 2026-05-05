# Descoped Eval Scenarios - Skeptic Step-0 Enforcement

**Inbound dependency for `eval-harness-v1`.**
**Authored by:** `skeptic-global-context` engineer (Stage 1).
**Status:** HANDOFF - these scenarios are binding inputs for `eval-harness-v1`'s architect and engineer.

---

## Purpose

These scenarios verify that the Global-context input set enforcement (Section 4.5 of
`content/references/skeptic-protocol.md`) behaves correctly at runtime. They were
descoped from the `skeptic-global-context` unit (which is docs-only) and handed to
`eval-harness-v1` as concrete implementation targets.

The `eval-harness-v1` architect plan MUST either implement these scenarios as test
cases OR explicitly defer with rationale in its plan.

Companion artifact: `cost-normalization-contract.md` (covers report-format contract;
independent of these scenarios and may land on a different timeline).

---

## Scenario 1 - Skeptic Step-0 BLOCKED on incomplete prompt structure

**Target behavior:** When a Skeptic spawn prompt is missing required fields from the
Global-context input set, the Skeptic returns BLOCKED before producing any review
content.

**Setup:** Spawn a Skeptic with a deliberately incomplete Global-context block. Example:
include fields 1-3 and 5-6 but omit field 4 (`qa_criteria` block).

**Assert:**
- Return status is exactly `BLOCKED - Global-context input set incomplete: qa_criteria block missing`.
- No review content (no "Reviewed:", no "Findings:", no findings list) follows the BLOCKED line.
- `loop-state.json` `last_phase_action` is set to `skeptic_blocked_input`.
- `loop-state.json` iteration counter is unchanged (not advanced, not reset).

**Multi-dim coverage:** Run the same scenario against the correctness-Skeptic in a
multi-dimensional fan-out. Assert BLOCKED with same semantics. Confirm that
`security-auditor` and `perf-analyst` spawned in the same fan-out do NOT block on
missing `qa_criteria` (they receive Supplemental-context, not Global-context; Step-0
does not apply to them).

---

## Scenario 2 - Skeptic Step-0 BLOCKED on non-enum `n/a` value

**Target behavior:** When a Global-context field carries a bare `n/a` or a
non-enumerated `n/a - <string>` value, the Skeptic returns BLOCKED.

**Setup:** Spawn a Skeptic with all 6 fields present but with:
```
Architect plan: n/a - I forgot
```

**Assert:**
- Return status is exactly `BLOCKED - Global-context input set incomplete: architect plan n/a value not in enumerated set`.
- No review content follows.
- `loop-state.json` iteration counter unchanged.

**Enum boundary test:** Also run with each valid `n/a` value from the enumerated set in
Section 4.5. Each valid value must NOT trigger BLOCKED.

**Multi-dim coverage:** Run the same scenario against the correctness-Skeptic in the
multi-dimensional fan-out. Confirm `security-auditor` and `perf-analyst` are not blocked
by any `n/a` value (no enum requirement for Supplemental-context).

---

## Scenario 3 - Conductor counter-and-escalate after 3 consecutive BLOCKED returns

**Target behavior:** After 3 consecutive `skeptic_blocked_input` returns on the same
spawn target (same `unit_slug`), the conductor escalates to the human operator and does
NOT silently retry.

**Setup:** Drive 3 sequential BLOCKED returns on the same unit. Each return should
increment `.agentic/.spawn-block-counter-<unit_slug>`.

**Assert after 3rd BLOCKED:**
- `.agentic/.spawn-block-counter-<unit_slug>` contains count `3`.
- Conductor emits an escalation message (does not spawn a 4th Skeptic attempt).
- Escalation message includes the open fields that caused BLOCKED and the unit_slug.
- `loop-state.json` iteration counter unchanged across all 3 attempts.

**Assert counter cleanup:** After Phase 6 loop terminates with sign-off (Skeptic grants
"No unresolved Critical or Major findings. Sign-off granted."), the glob
`rm -f .agentic/.spawn-block-counter-*` runs and the counter file is absent.

**Multi-dim coverage:** Run the same 3-BLOCKED escalation scenario against the
correctness-Skeptic in a multi-dim fan-out. Confirm that security-auditor and
perf-analyst BLOCKED returns (if any - they can block for non-Step-0 reasons) use a
separate counter or no counter (their BLOCKED returns are engineer-fault or domain-fault,
not conductor-fault; they do NOT increment the Step-0 block counter).

---

## Scenario 4 - Plan-tier overflow fallback fires above 60K tokens

**Target behavior:** When the combined Global-context input set for a Plan-tier
second-pass Skeptic exceeds 60K tokens, the conductor switches to per-unit second-pass
mode plus a lightweight integration Skeptic on findings only.

**Setup:** Construct a synthetic Plan-tier Skeptic spawn where the sum of architect plan
+ Brief + qa_criteria + per-consumer table + related files > 60K tokens. The threshold
is measured in input tokens before the Skeptic spawns.

**Assert:**
- Conductor does NOT spawn a single Skeptic with the full combined context.
- Conductor spawns per-unit Skeptics (one per unit, each with that unit's subset of
  the Global-context) plus one integration Skeptic on the combined findings list only.
- The integration Skeptic receives the findings list, NOT the full Global-context block.
- Each per-unit Skeptic receives a valid Global-context block for its own unit.

**Edge case:** Test at exactly 60K tokens (inclusive threshold). Confirm the fallback
fires at >= 60K, not at > 60K.

---

## Supplemental-context shape verification (companion to Scenarios 1-3)

**Target behavior:** `security-auditor` and `perf-analyst` receive a `## Supplemental
context` block (not `## Global-context inputs`) when spawned in the multi-dim fan-out.
Fields may be omitted without triggering any block.

**Setup:** Spawn a multi-dim fan-out (correctness-Skeptic + security-auditor +
perf-analyst). Inspect each spawn prompt.

**Assert:**
- correctness-Skeptic prompt contains `## Global-context inputs` (exact heading).
- security-auditor prompt contains `## Supplemental context` (exact heading).
- perf-analyst prompt contains `## Supplemental context` (exact heading).
- Neither security-auditor nor perf-analyst prompt contains `## Global-context inputs`.
- Omitting `qa_criteria` from the Supplemental-context block does NOT cause BLOCKED
  on security-auditor or perf-analyst.

---

## Notes for `eval-harness-v1` architect

- These scenarios test conductor-level behavior (spawn brief construction, counter files,
  escalation) AND Skeptic-level behavior (Step-0 return format). Both layers must be
  exercised.
- The counter file path is `.agentic/.spawn-block-counter-<unit_slug>`. For single-unit
  spawns, `unit_slug` is `single`.
- `loop-state.json` `last_phase_action: skeptic_blocked_input` is the state value that
  the resume hook uses to re-spawn the Skeptic (not re-spawn the engineer) after a
  session interruption during a BLOCKED state.
- All scenarios assume the harness can inject synthetic spawn prompts and inspect both
  the Skeptic's return AND the resulting `loop-state.json` mutation.
