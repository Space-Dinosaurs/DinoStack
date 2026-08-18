# Obsolescence Signal - Floor vs. Dial

## The test

Model-capability changes move the risk-profile dial, they never remove an enforcement floor. Prose rules and enforcement hooks (abdication guard, tier enforcement, singularity guard) are written for the weakest supported model and stay universal; a stronger model makes a hook cheaper to satisfy, never optional. When evaluating an "obsolescence" claim (a newer model makes gate X unnecessary), ask two questions first: is it harness-driven or model-driven, and is it a floor or a dial? Only harness-driven vestiges are retirement candidates.

This is the mandatory pre-filter for `/ds-prune-harness`: apply it to every candidate before it enters the proposal. A rule or hook that enforces a floor is never a deletion candidate regardless of which signal fired.

## Applying the test

Two questions, asked in order:

1. **Harness-driven or model-driven?** A harness-driven vestige exists because of a limitation in the tooling around the model (a stale API shape, a workaround for a harness bug that has since been fixed, a fallback path for a capability the harness no longer lacks). A model-driven claim rests on "the model is smarter now" - that claim never justifies removing a floor, because the rule was never written for today's model; it was written for the weakest model the methodology supports.
2. **Floor or dial?** A floor is a rule whose violation is catastrophic or silently unrecoverable if skipped (an enforcement hook, a hard behavioral rule with no graceful degradation). A dial is a rule whose strictness can vary with capability (how much detail a prompt needs to spell out, how many worked examples a rule needs to land correctly). Only dials move with model capability. Floors do not move.

A candidate that is model-driven, or that enforces a floor (even if harness-driven), fails the pre-filter and must not be proposed for deletion. Only a candidate that is BOTH harness-driven AND a dial (or a pure harness workaround with no floor role at all) is eligible to proceed to the signal checklist.

## Worked examples (this repo)

**Harness-driven vestige (retirement-eligible):** a fallback path written to compensate for a harness bug or missing capability that has since shipped - for example, a prose instruction telling agents to manually re-derive a value because the harness payload did not expose it, once the harness starts exposing that value directly. The rule exists only because of a tooling gap; once the gap closes, the workaround has no remaining job. This is the shape Signal 5 ("orphaned fallback text") is built to catch, and it is the class the floor-vs-dial test clears for further review, not the class it protects.

**Model-driven floor (never a candidate):** the abdication guard (`hooks/enforce-no-abdication.py`) and the tier-enforcement / singularity-guard hooks. These exist because even a highly capable model will, under specific conditions, abdicate a decision back to the operator instead of proceeding, or attempt to shortcut required review. A stronger model may satisfy these guards more easily and trigger them less often - that is the dial moving - but the guard itself does not become unnecessary. Zero fires in a measurement window is evidence the guard is cheap to satisfy, not evidence it can be removed; per this document's own test, this is exactly the model-driven-floor case the pre-filter is designed to exclude.
