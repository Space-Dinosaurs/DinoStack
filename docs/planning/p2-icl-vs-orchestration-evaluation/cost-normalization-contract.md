# Descoped Report-Format Contract - Token-Cost Confounder Normalization

**Inbound dependency for `eval-harness-v1`.**
**Authored by:** `skeptic-global-context` engineer (Stage 1).
**Status:** HANDOFF - this contract is a binding input for `eval-harness-v1`'s architect and engineer.

---

## Purpose

The `skeptic-global-context` unit adds a Global-context input set (Section 4.5 of
`content/references/skeptic-protocol.md`) to every Skeptic spawn. This adds 3,000 -
10,000 additional input tokens per Skeptic spawn. The effect is a 3-5x increase in
Skeptic input cost across the post-restructure protocol relative to the pre-restructure
baseline.

This is a **measurement confounder** for the Stage 3 vs Stage 6 eval comparison:
- Stage 3 runs against the pre-restructure protocol (Skeptic does NOT pay Global-context input cost).
- Stage 6 runs against the post-restructure protocol (Skeptic DOES pay Global-context input cost).
- A naive cost-ratio comparison will show the post-restructure protocol as more expensive
  even when the restructure itself is a protocol improvement.

This contract specifies the required normalization (or flagging) so the Stage 3 vs
Stage 6 comparison is interpretable.

Companion artifact: `scenarios-todo.md` (covers Step-0 enforcement scenarios; independent
of this contract and may land on a different timeline).

---

## Contract

`eval-harness-v1`'s Stage 3 vs Stage 6 cost-comparison report MUST either:

**(a) Apply normalization** - subtract the measured Global-context overhead from
post-restructure Skeptic costs before computing the cost ratio between conditions, OR

**(b) Flag the confounder explicitly** - if normalization is not applied, the report's
`limitations` section must flag this confounder verbatim.

---

## Required report shape

`evals/icl-vs-orchestration/results-v1.json` MUST carry the following block at the
top-level or under a `methodology` key:

```json
{
  "skeptic_input_cost_normalization": {
    "applied": true,
    "method": "<string describing the normalization method, e.g. 'subtract_median_global_context_tokens_per_spawn'>",
    "baseline_tokens": 0,
    "post_restructure_tokens": 7500
  }
}
```

**Field semantics:**

- `applied` (bool, required): `true` if the report's cost-ratio figure is normalized;
  `false` if raw (un-normalized) cost ratios are reported.
- `method` (string, required when `applied: true`): human-readable description of the
  normalization method. At minimum: which token counts were subtracted, whether median
  or mean was used, and how per-spawn overhead was measured.
- `baseline_tokens` (int, required): median Global-context input tokens per Skeptic spawn
  in Stage 3 (pre-restructure). Expected value: 0 (pre-restructure Skeptics do not
  receive Global-context).
- `post_restructure_tokens` (int, required): median Global-context input tokens per
  Skeptic spawn in Stage 6 (post-restructure). Expected range: 3,000 - 10,000.

---

## Acceptance criteria

**If `applied: true`:**
- The cost-ratio column in the report represents protocol cost excluding the
  Global-context overhead.
- The report prose explains what "normalized cost" means in one sentence.
- Raw (un-normalized) cost figures are retained alongside normalized figures so a
  reader can compute the overhead themselves.

**If `applied: false`:**
- The `limitations` section of the report MUST contain the following verbatim text
  (or a text that is substantively equivalent - no paraphrase that omits the core claim):

  > "Cost comparison is biased against the post-restructure condition because
  > post-restructure Skeptic spawns carry a Global-context input overhead of
  > approximately {post_restructure_tokens} tokens per spawn that pre-restructure
  > Skeptics did not pay. This overhead does not represent routing complexity
  > or protocol quality; it represents verification-surface investment.
  > The cost-ratio figure without normalization overstates the post-restructure
  > condition's per-ticket cost by an amount proportional to the number of
  > Skeptic spawns per ticket."

---

## Measurement guidance

The harness can measure `post_restructure_tokens` empirically:

1. On the first Stage 6 run (or the smoke run), collect the input token counts for all
   Skeptic spawns.
2. For each spawn, compute the token count of the `## Global-context inputs` section
   (fields 1-6 as defined in Section 4.5).
3. Take the median across all spawns. This is `post_restructure_tokens`.

Alternative (acceptable): use a fixed estimate of 5,000 tokens per spawn (conservative
midpoint of the 3,000-10,000 range), documented in `method` as `fixed_estimate_5000`.

---

## Rationale

The Global-context overhead is a deliberate verification-surface investment, not
a routing complexity tax. The eval's purpose is to measure whether the protocol
produces better outcomes per dollar. If the cost comparison conflates "better verification
coverage" with "more expensive routing", the measurement does not answer the question
it was designed to answer.

Normalizing (or explicitly flagging) this confounder is necessary for the Stage 3 vs
Stage 6 comparison to be the eval the operator expects.
