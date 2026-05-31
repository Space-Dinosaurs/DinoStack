# Model-Capability Abstraction Audit

**Date:** 2026-05-29
**Trigger:** Assess how Opus 4.8's new capabilities (1M context window, fast-mode Opus, improved long-horizon coherence) should impact the agentic-engineering methodology - reconciled against AE's harness- and model-agnostic design goal.
**Status:** Draft for Skeptic review.

## Thesis

AE is harness-agnostic and model-agnostic by design. It runs identically across Claude Code (Opus/Sonnet/Haiku), Codex (GPT), Gemini, and OpenCode. Model-specific facts must therefore be expressed as **deployment configuration**, never as **protocol prose**.

The seam already exists:
- **tier -> model** resolves via `~/.agentic/tier-map.yml` (opt-in, user-authored; no hardcoded fallback model list in repo or adapters).
- **risk boundary** is parameterized via `relaxed | default | strict` profiles.
- **cost/capability** routes via `.agentic/config.json` `model_profile`.

**Principle:** the methodology encodes orchestration *logic*; the deployment encodes capability *facts*.

The right question is not "how should AE change for Opus 4.8." It is: "does AE's abstraction layer already absorb any model's capability profile as configuration?" Where it does, 4.8 needs zero methodology edits - only new default values. Where a capability assumption has leaked into protocol prose, *that leak* is the defect; the fix is to reword or to remove the model name, never to add a new knob for 4.8.

## Headline result

A four-way parallel read-only sweep of all ~67 files in `content/` (sections, rules, references, agents, commands) found **~20 actionable findings. Every finding is `reword` or `keep-as-is`. Zero findings require `parameterize`.**

This is the load-bearing conclusion: the abstraction seam holds. There is no place in the methodology where a model-capability difference is structurally baked in such that it needs a new config key. Opus 4.8 (or any future model) is absorbed entirely at the deployment layer. The protocol-level work is purely removing capability assumptions from *justification phrasing* and removing two *hardcoded model names*.

## Locked remediation scope (decided in discussion)

1. **Reword** cost/latency-phrased tier guidance into capability/reasoning-depth terms.
2. **Restate** delegation's rationale as its three pillars (parallelism, independent adversarial review, context hygiene), noting context-hygiene weight is deployment-dependent. Keep every rule.
3. **Add** one sentence to the decomposition prose: unit size is bounded by *reviewability*, not writer capability. No threshold change, no new knob. (Decomposition thresholds stay fixed - they are calibrated to operator oversight and coordination risk, both model-independent; the blast-radius triggers - cross-track, multi-session, architecture - already catch the "few fat units, large blast radius" case independent of unit count.)
4. **Capture** 4.8 as default values in the deployment layer (tier-map, MEMORY, config defaults). The inverse half of this item, surfaced by the audit: **remove the two hardcoded model names from `content/` prose** so the protocol layer names tiers only, never models.

## Findings (actionable - `reword`, plus two `restructure` in Theme E)

Grouped by theme. Line numbers are a snapshot; re-verify before editing. No finding is `parameterize` - no new config knob is required anywhere.

### Theme A - Hardcoded model names outside a harness-scoped block (highest acuity)

| File:line | Quote | Fix |
|---|---|---|
| `content/sections/04-risk-classification.md:119` | `Tier: 3 (max capability - security audit needs Opus)` | Remove model name from the declaration example: `(max reasoning depth - security audit; Tier 3)`. Conductors copy this example verbatim; on Codex/Gemini the literal "Opus" breaks tier-map resolution. |
| `content/sections/04-risk-classification.md:123` | "When no tier is declared, the agent uses Sonnet." | "...uses the Tier 2 model for the active harness." Stated as universal fact outside the Claude-Code table; wrong on other harnesses. |
| `content/references/subagent-protocol.md:391` | "the conductor also passes a `model` param (`haiku` for Tier 1, `opus` for Tier 3)" | Prefix with explicit harness scope: `(Claude Code: \`haiku\` for Tier 1, \`opus\` for Tier 3; other harnesses resolve from tier-map or omit)`. **Correction (Skeptic):** the examples are stated as a universal rule, NOT inside a Claude-Code-scoped block; the Codex/Gemini branch is a follow-on sentence. A conductor on Gemini/Codex with no tier-map would pass `--model opus` literally and fail. Reclassified from the initial sweep's `keep-as-is`. |

### Theme B - Cost/latency-phrased tier guidance (scope item 1)

| File:line | Quote | Fix |
|---|---|---|
| `content/sections/04-risk-classification.md:114` | "route lightweight tasks to faster models and critical reviews to max-capability models" | "lower-depth models" / "maximum-reasoning-depth models" - reframe speed -> depth. |
| `content/sections/04-risk-classification.md:137` | "Tier 3 costs significantly more; include a justification parenthetical." | "Tier 3 demands maximum reasoning depth; include a justification parenthetical." |
| `content/agents/architect.md:240` | "deep-question runs benefit from max capability and spawn frequency is low" | "grill mode demands the widest design-question aperture; spawn frequency is low." Keeps the Tier 3 assignment; drops the cost-amortization framing. |
| `content/agents/orchestration-planner.md:56` | "each one adds latency and cost" | Drop the cost/latency clause; the following sentence already states the principle (only include agents whose capability is genuinely needed). |
| `content/agents/orchestration-planner.md:134` | "adds latency without proportional value" | "adds orchestration overhead without proportional review signal." |

### Theme C - Context-budget / context-hygiene framing (scope item 2)

These rules are sound on model-independent grounds (conductor availability, role separation, session-state reliability). Only the *justification* leaks a small-window assumption. Reword the rationale; keep the rule.

| File:line | Quote | Fix |
|---|---|---|
| `content/sections/04-risk-classification.md:7` | "mandatory context hygiene. A conductor that fills its own context...cannot orchestrate." | Restate as delegation pillars: a conductor doing investigation is unavailable for parallel coordination and conflates two reasoning tasks (terrain-mapping vs orchestration). Note context-hygiene weight is deployment-dependent. |
| `content/sections/02-delegation.md:3` | "it stays lightweight, available, and responsive" | "stays available and focused on orchestration." Only "lightweight" leaks; "available/responsive" carry the model-independent reason. |
| `content/references/subagent-protocol.md:434` | "context window is a finite resource. Long-running sessions degrade reasoning quality..." | Reframe on session-state reliability + operator oversight: stale state, cross-phase drift, harder crash recovery. |
| `content/references/subagent-protocol.md:458-462` | "Hitting the underlying model's context-window ceiling" (one bullet of four) | Replace the ceiling bullet with a session-state framing (stale crash-recovery artifacts). Keep the other three bullets - already model-independent. |
| `content/references/skeptic-protocol.md:195` | "prevents context degradation from accumulating full implementation text" | Reframe on brief readability/auditability and copy-paste error risk. |
| `content/commands/implement-ticket.md:38` | "synthesis-context savings did not justify a spawn" | Reframe on the actual reason: synthesis is consumed inline by the next phase, not a context-budget trade. |

### Theme D - Drift/hallucination as a *load-bearing* justification (highest value - behavioral)

This is the only place a capability claim sits inside a behavioral rule rather than framing. A reader on a model they believe "does not hallucinate" could conclude the rule does not apply to them and skip the verbatim-prior-output requirement. The real reason - scope discipline for a stateless subagent - is model-independent and stronger.

| File:line | Quote | Fix |
|---|---|---|
| `content/commands/implement-ticket.md:1191` | "hallucinating the parts it cannot see" | "producing output that diverges from the scoped change because it has no access to prior-iteration state." |
| `content/commands/implement-ticket.md:1356` | "regenerates from scratch and hallucinates" | "regenerates from scratch and diverges from the scoped change." |

### Theme E - Capability-coupled numeric constants (token/turn thresholds)

The numbers implicitly encode a window size. Verdict is `reword` or `restructure` - **not** `parameterize`. Consistent with the no-new-knob decision. **Label note (Skeptic):** the `~500 token` items are `restructure`, not pure `reword` - swapping a token count for a structural trigger changes the trigger *semantics*. The implementer must treat these as a behavioral-trigger change, not a copy-edit. The turn-count items are true `reword` (cite the canonical home; the numbers express operator-oversight horizon, which is model-independent).

| File:line | Bucket | Fix |
|---|---|---|
| `content/references/subagent-protocol.md:222` | **restructure** | Swap the token count for a structural trigger (fits one screenful / preflight list still fits a single spawn prompt). Trigger semantics change. |
| `content/commands/implement-ticket.md:1244` | **restructure** | Same structural-trigger swap; do not leave a hardcoded token count. Trigger semantics change. |
| `content/commands/implement-ticket.md:1242` | "soft limit (15-20 turns)...hard limit (25-30 turns)" | Reference `subagent-protocol.md` Section 13 as the single source; drop the inline duplicate numbers. (borderline - duplicate, not a new assumption.) |
| `content/commands/brief.md:38` | "push the conductor toward its context limit...soft limit (15-20 turns)" | Same - cite Section 13 rather than embedding numbers. |
| `content/commands/implement-ticket.md:1765` | "tail -300 truncation...to keep engineer context bounded" | Keep `tail -300`; reword rationale: CI failure output is almost always in the last 300 lines (head is setup/install noise). |

## Deliberate non-actions (`keep-as-is`)

Documented so a future pass does not "fix" them:

- ~~`content/references/subagent-protocol.md:391`~~ - **moved to Theme A `reword`** (Skeptic correction): the `haiku`/`opus` examples are stated as a universal rule, not inside a Claude-Code-scoped block.
- `content/references/skeptic-protocol.md:305` - the `60K token` threshold is a review-*scope* switch (when to split into per-unit Skeptics), not a context-window budget. Applies even on a 1M-context model. Add this clarifying note verbatim: *"The 60K limit is a prompt-assembly threshold for review focus, not a model context constraint; it applies regardless of the underlying model's window size, because adversarial review signal degrades as the assembled prompt grows."*
- `content/references/skeptic-protocol.md:432` - "long-horizon drift" = meta-Skeptic calibration drift over sessions, a measurement term, not model long-context coherence.
- `content/commands/implement-ticket.md:1463` - "Co-Authored-By: Claude Sonnet 4.6" inside a literal commit-template example. Illustrative; version suffix is a maintenance concern, not a capability leak.
- `content/commands/agentic-cost.md:65,70` - model keys inside the user-maintained `~/.agentic/pricing.yml` example. Sample data for a user-edited file.
- `content/agents/skeptic.md:106`, `content/agents/security-auditor.md:115` - "costs more than a false positive" is a production-defect-cost argument, not model economics.
- `content/agents/architect.md:234` - "subagents are single-shot" is a harness-protocol fact.
- Tier declarations by *number* throughout - correct; tier->model resolution is deployment-local.

## Decomposition thresholds: explicitly unchanged

The Brief/Plan promotion gates (2-5 Elevated units = Brief, 6+ = Plan) and "one agent, one task, one prompt" stay as-is. Rationale (decided in discussion): they are calibrated to operator oversight and coordination risk (model-independent); unit *count* auto-adjusts through the orchestration-planner as capability changes; and the blast-radius triggers (cross-track, multi-session, architecture-decision) catch the dangerous low-count/high-blast-radius case independent of unit count. The binding constraint on unit *size* is reviewer effectiveness and human PR comprehension - both model-independent. A capable model that *can* write fatter units should not, because review quality binds first. Scope item 3 adds one sentence making that explicit, hardening the prose against future over-tuning.

**Known limitation (Skeptic, accepted):** a single-track, large-in-track-blast-radius change that a more capable planner keeps as one fat Elevated unit gets no Brief (single Elevated unit = architect plan is the artifact), and the Plan-tier blast-radius triggers (cross-track, multi-session, architecture) do not fire on it. This gap is not new with 4.8 - it predates it - but 4.8 makes it more common by collapsing more work into single units. The accepted mitigant is the reviewability bound (item 3): unit size is capped by what a Skeptic and a human can review well, which limits how fat a single unit should get regardless of model. Recalibrating the thresholds themselves is explicitly out of scope for an abstraction-hygiene audit; flag for a future threshold-tuning pass if in-track blast radius proves to slip through in practice.

## Deployment-layer changes (scope item 4)

These capture 4.8 facts where they belong - outside `content/`:

- **`~/.agentic/tier-map.yml`** (and the Claude Code defaults): record current Tier 1/2/3 -> model mappings for the active stack. Fast-mode Opus availability may justify revisiting the Tier 2 default, but that is a deployment tuning decision, not a methodology edit.
- **MEMORY.md** "Subagents use Sonnet" pin (`pass model="sonnet" explicitly on every Agent spawn unless Tier 1/3 override applies`): this is an active behavioral override injected every session, not a passive note. **Concrete disposition: RETAIN as-is, with an explicit revisit trigger.** Rationale: Tier 2 is defined as standard work, and Sonnet is sufficient for it; the pin is a deliberate cost lever, and flipping the default to Opus-everywhere is a cost increase that is the operator's economic call, not an audit recommendation. **Revisit trigger:** when fast-mode Opus pricing at sustained Tier 2 spawn volume is confirmed at or below Sonnet's, re-evaluate whether to drop the pin and let Tier 2 resolve to Opus via tier-map. Until that condition is confirmed with real pricing, the pin stands. This entry is deployment-local and correctly located in MEMORY.md; no edit is made now.
- **`.agentic/config.json`** `model_profile`: unchanged default; `budget` remains the deliberate cost-down exception.

These are out of scope for the `content/` reword PR and are not gated by the Skeptic review of this audit.

## Recommended execution

A single Elevated reword pass over `content/`, routed through `/update-agentic-engineering` (these are methodology files). All ~18 reword edits are justification-phrasing or model-name removals with no behavioral change to orchestration logic. Re-verify line numbers at edit time (they drift). Run all 8 adapter build scripts before commit (adapter-sync discipline) and confirm `check-adapter-sync` passes. The two highest-value edits to prioritize: Theme A (model-name removal in the copied example) and Theme D (drift-justification on a behavioral rule).
