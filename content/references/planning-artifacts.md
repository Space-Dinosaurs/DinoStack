<!--
Purpose: Full reference for planning-artifact templates, directory layouts, and
         promotion mechanics extracted from METHODOLOGY.md §Planning Artifacts.
         Contains ordering, trigger table, gate-semantics authoring sequences,
         the Brief template (including outcome_rubric field), Plan-tier
         directory layout, verification-gate template (including rubric-resolved
         subsection), promotion mechanics, product-intent layer rules, and the
         canonical qa_default_skip definition.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/03-planning-artifacts.md (pointer),
            content/sections/12-protocol-details.md (Protocol Details entry).

Upstream deps: content/sections/03-planning-artifacts.md (parent section;
               read that section first for the promotion-threshold summary
               and blocking/non-blocking rules);
               content/rules/module-manifest.md (manifest header contract);
               content/rules/conventions.md §Project Overview Layer.

Downstream consumers: Conductor flows: Brief authoring (Gate semantics step 6),
                      Plan authoring (Plan tier authoring sequence), cross-session
                      resume (promotion_tier field); /ds-brief command (rubric synthesis
                      in Section 3 and PRD extraction in Section 5); /ds-implement-ticket
                      Phase 3b cross-artifact alignment check; /ds-implement-ticket
                      Phase 4 "Commit and push the planning artifact" subsection (Gate
                      semantics steps 10/Plan-tier bullet); skeptic agent (rubric
                      check step 3.5); product-discovery agent (rubric drafting step 5b).

Failure modes: Prose; does not execute. Drift between this file and the parent
               section (03-planning-artifacts.md) is a Major Skeptic finding.
               Stale step numbering in Gate semantics causes misrouted
               cross-references across phases; update inline step references
               whenever steps are renumbered. Stale field guidance misleads
               Brief authors; keep in sync with any changes to the Brief
               template fields.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Planning Artifacts.

# Planning Artifacts - Full Reference

## Ordering

The promotion check is downstream of architect+planner, upstream of engineer:

```
Risk classified Elevated
  -> architect (existing behavior; investigator-before-architect rules apply)
  -> Skeptic on architect plan (METHODOLOGY.md §Delegation)
  -> Open Questions on architect plan resolved (METHODOLOGY.md §Delegation)
  -> orchestration-planner (METHODOLOGY.md §Task Decomposition)
  -> [PROMOTION CHECK] count Elevated-or-above units, check track span, check session span
       -> 0-1 Elevated units: no Brief required (current behavior)
       -> 2-5 Elevated units: author Brief, Skeptic the Brief, then engineer
       -> 6+ Elevated units OR cross-track OR multi-session OR auto-promote-at-3rd-resume: assemble Plan, Skeptic the Plan, then engineer
  -> engineer(s) spawned with brief_path / plan_path in execution contract
```

The Brief is authored after the planner has returned a unit count, so "do we need a Brief?" is a mechanical check, not a guess. The architect plan and planner output are inputs the conductor uses to draft the Brief - the Brief is not asking the conductor to predict what will exist; it is asking the conductor to commit to the framing now that the shape is known. This mechanical restatement is a comprehension-artifact step: the act of restating the architect and planner output forces the conductor to demonstrate it understood both. The Skeptic reviewing the Brief asks a different question than the Skeptic that reviewed the architect plan - not "is the design sound?" but "did the conductor actually understand what was produced upstream, and is the verification real?" This catches implicit architect assumptions that do not survive being stated plainly, planner units that do not compose coherently when described together, and verification criteria that seemed obvious until someone had to write them down.

## Trigger table

All triggers are mechanical. Operator judgment is not a field. Triggers are evaluated after orchestration-planner returns.

| Condition | Artifact required |
|---|---|
| Risk = Trivial or Low | None |
| Risk = Elevated AND orchestration-planner returns 0-1 Elevated-or-above units (or planner skipped per the existing single-unit exception) | None (architect plan only - current behavior) |
| Risk = Elevated AND orchestration-planner returns 2-5 Elevated-or-above units | Brief + architect plan |
| Risk = Elevated AND orchestration-planner returns 6+ Elevated-or-above units | Plan (Brief + architect + orchestration JSONL + risk register + rollback + verification gate) |
| Any unit's `output_paths` spans 2+ tracks (see "Track" definition below) | Plan |
| Work spans 2+ sessions (declared at planning time, OR auto-promoted when the ticket's `.agentic/loop-state-<LOOP_KEY>.json` - legacy: `.agentic/loop-state.json` - resumes a Brief-tier task into a third session) | Plan |
| Cross-track OR triggers an "Architecture decision constraining future choices" risk signal | Plan + ADR |

**Unit counting rule.** Only units whose own risk classification is Elevated or above count toward the 2-5 / 6+ thresholds. Trivial units in a mixed-risk plan do not count - they are routed per the standard Trivial conductor rule and contribute zero to promotion.

**"Track" definition (mechanical).** A track is a depth-1 directory under the repo root that contains its own `AGENTS.md` file (per the conventions in `content/rules/conventions.md`). Nested `AGENTS.md` files (e.g. `app/factory/AGENTS.md`) do not create new tracks - they are sub-context within their parent track.

- Worked example A: a repo with `api/AGENTS.md`, `app/AGENTS.md`, `worker/AGENTS.md`, `infra/AGENTS.md` at depth 1. A unit touching `app/factory/foo.ts` is in the `app` track. A change touching both `app/...` and `api/...` is cross-track and triggers Plan + ADR.
- Worked example B: a change touching `app/factory/foo.ts` and `app/ui/bar.tsx` is single-track (`app`); the nested `factory/AGENTS.md` does not split the track.

**Other notes:**
- Unit count comes from the orchestration-planner's JSONL output, counted by `unit_slug` entries with risk >= Elevated.
- Track span is computed by mapping each `output_paths` entry to its depth-1 ancestor and checking for `AGENTS.md` at that depth.
- Session span is initially declared, then auto-promoted by the resume hook when the threshold is hit (see Promotion mechanics below).
- A task can be promoted upward mid-work. It cannot be demoted.

## Gate semantics

**Authoring sequence (Brief tier):**
1. Architect runs (existing behavior).
2. Skeptic on architect plan.
3. Open Questions on architect plan resolved.
4. Orchestration-planner runs.
5. Promotion check against the trigger table.
6. If 2-5 Elevated-or-above units: check whether `.agentic/brief-session.json` exists with `status: complete` and `brief_source: operator` AND `brief_path` points to an existing file. If both conditions hold, the Brief is pre-existing and operator-confirmed - skip conductor authoring and go directly to step 8. If not, conductor authors Brief at `docs/planning/<slug>.md` using architect output, planner output, and the original ticket as inputs.
7. **Cross-artifact alignment check (conductor-direct).** When a Brief exists and the orchestration-planner returned at least one unit with a non-empty `acceptance_criteria` array, the conductor mechanically maps every Brief success criterion to at least one unit's `acceptance_criteria`. Any UNCOVERED criterion is resolved (re-spawn planner with the gap called out, or surface a descope/expand decision to the operator) before the Skeptic-on-Brief runs. When no unit has non-empty `acceptance_criteria`, emit `[phase: cross-artifact-check-skipped | no criteria to map]` and proceed. Full procedure in `/ds-implement-ticket` Phase 3b "Cross-artifact alignment check". This mechanical check complements - does not replace - the adversarial Skeptic-on-Brief.
8. Spawn Skeptic on the Brief. When the Brief is pre-existing and operator-confirmed (`brief_source: operator`), use the operator-confirmed Skeptic variant (completeness-only review - see `content/commands/ds-brief.md` Section 6 for the exact brief text). When the Brief was conductor-authored, use the standard "Document synthesis, architecture, and planning" adversarial brief; the verification field is part of the Skeptic's review surface in both cases. The `QA criteria` field is also part of the Skeptic's review surface: for Elevated tickets, the Skeptic must validate that the field is present, that `qa_skip` is one of the 5 valid enum values or null, that `qa_skip_rationale` is populated when `qa_skip != null`, and that `scenarios[]` is non-empty when `qa_skip == null`. Absence on Elevated is a Critical finding; an invalid `qa_skip` enum is a Major finding. This spawn also requires the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5): field 2 (Brief/Plan artifact) is `n/a - Skeptic-on-Brief (Brief is the artifact under review)`; field 4 (per-consumer impact table) is `n/a - Brief tier (per-consumer lives in architect plan path above)`; field 6 (diff under review) leads with the unit's stable key (§4.5's Stable unit key contract) followed by " | " and the paths the Brief proposes to touch, since this is a pre-implementation review and no diff exists yet; field 7 (conductor spawn brief) is `n/a - internal scaffolding artifact (no conductor claim-bearing brief text distinct from the artifact itself)`.
9. On Brief sign-off (and after any Open Questions in the Brief are resolved per the Open Questions hard gate in METHODOLOGY.md §Delegation), engineer(s) spawn with `brief_path` populated in their execution contract.
10. **Commit and push (mandatory, per-repo eligibility-gated, gaps 1/2 only - DS-124 covers gap 3).** Runs at the unconditional start of Phase 4 (`content/commands/ds-implement-ticket.md`, anchor `` Commit and push the planning artifact `` - see step 3), whenever `brief_path` or `plan_path` is populated. Checks `git check-ignore -q -- docs/planning/<slug>` first; if ignored, no-op. Otherwise commits (no checkout, DCO-trailered) and pushes by explicit SHA immediately, with the conductor-side retry-on-rejection from API item 1.

**Authoring sequence (Plan tier):** identical to Brief tier through step 6, plus:
- Conductor authors `risk-register.md`, `rollback.md`, and `verification-gate.md`, and assembles the Plan directory. Set `plan_path = docs/planning/<slug>/` (repo-relative, mirroring `brief_path`'s existing assignment convention) immediately upon assembling the Plan directory.
- **Commit and push (mandatory, per-repo eligibility-gated, gaps 1/2 only - DS-124 covers gap 3).** Runs at the unconditional start of Phase 4 (`content/commands/ds-implement-ticket.md`, anchor `` Commit and push the planning artifact `` - see step 3), whenever `brief_path` or `plan_path` is populated. Checks `git check-ignore -q -- docs/planning/<slug>` first; if ignored, no-op. Otherwise commits (no checkout, DCO-trailered) and pushes by explicit SHA immediately, with the conductor-side retry-on-rejection from API item 1.
- **Gap 3 is explicitly out of scope for this authoring sequence - see DS-124.** A later revision to an already-committed Plan (mid-flight escalation, 3rd-resume auto-promotion, a late Skeptic-round fix) has no automatic re-invocation of this step under this ticket.
- A second Skeptic pass reviews the assembled Plan as a whole (not the components individually - they were already reviewed). Scope: integration coherence, missing rollback for any high-blast-radius unit, risk register completeness, and verification gate completeness (no "cannot specify" entries). This spawn also requires the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5): field 1 (architect plan) is `n/a - assembled Plan review (per-unit plans listed inline)`; field 6 (diff under review) leads with the unit's stable key (§4.5) followed by " | " and the paths the assembled Plan proposes to touch; field 7 (conductor spawn brief) is `n/a - internal scaffolding artifact (no conductor claim-bearing brief text distinct from the artifact itself)`. When the combined Global-context input set exceeds 60K tokens, apply the "Plan-tier second-pass overflow fallback" in Section 4.5 instead of assembling one oversized prompt: one Skeptic per unit (each with that unit's Global-context subset) plus a lightweight integration Skeptic receiving only the combined findings list.
- Workers spawn only after assembled-Plan sign-off, with both `brief_path` and `plan_path` in their execution contract.

**ADR tier:** ADR is authored alongside the Brief, not after, because the architectural decision shapes the Brief's constraints. ADR review follows the project's existing ADR process; if none exists, the ADR goes through the same "Document synthesis, architecture, and planning" Skeptic review as the Brief.

## Brief template

**Canonical path:** `docs/planning/<slug>.md` (slug = kebab-case feature name, prefixed with priority tag if the project uses one, e.g. `p2-foo.md`). (this is the on-disk / git-operations path, always repo-relative; the execution-contract `brief_path`/`plan_path` handed to an isolated engineer is a separate, absolute-path value normalized at spawn construction.)

**Template (must fit on one screen; ~15-20 lines):**

```markdown
# Brief: <feature name>

**Problem:** <1-2 sentences. Behavior gap in user/system terms, not implementation terms.>

**Success criteria:** <Bulleted, observable from outside. Max 4 bullets.>
- <criterion 1>
- <criterion 2>

**Non-goals:** <What this explicitly does NOT do. Max 3 bullets. Write "none plausible" if none.>
- <non-goal 1>

**Constraints:** <Hard constraints only - existing contracts, perf budgets, compat targets, deadlines. Not preferences.>

**Verification:** <Single non-skippable line. The test(s), gate(s), qa.md trigger pattern(s), and any regression test mandated by `.agentic/findings.md` that prove this is done. "Cannot specify" is itself a planning gap and blocks Skeptic sign-off.>

**Outcome rubric:** <Operator-confirmed pass/fail lines (max 6). Each line is a terse, observable acceptance statement tagged with its verification_type: `deterministic` (a nameable gate - tests, lint, schema check, HTTP status) or `judgment` (qualitative, graded adversarially by the independent Skeptic - never self-certifying). Required for Elevated; absence is a Critical Skeptic finding. Distinct from Verification: Verification names gate commands; rubric lines are the operator's semantic definition of done. Draft via product-discovery step 5b or /ds-brief Section 3, then confirm before Brief authoring.>
- [ ] <criterion, e.g. all existing tests pass with zero regressions> [deterministic]
- [ ] <criterion, e.g. the new flow is coherent and self-consistent from an operator perspective> [judgment]

**QA criteria:** <Required for Elevated. YAML block with `qa_skip` (one of 5 valid enums or null), `qa_skip_rationale` (required iff qa_skip != null), `viewport` (root-level default list, default `[desktop]`), `scenarios[]` (required if qa_skip null; method ∈ {browser, api, runtime-required, visual_conformance, accessibility, perceptual_diff}), `manual_smoke`. Operator-supplied Briefs must include this field; absence on Elevated is a Critical Skeptic finding.>

**Linked artifacts:** architect-plan: <path>; orchestration: <path or inline JSONL block>
```

**Field guidance (one line each):**
- Problem: behavior gap, not solution. If you wrote "add X", restate as "users cannot Y".
- Success criteria: pass/fail testable from outside. Drives Skeptic completion review.
- Non-goals: written to defeat the most likely scope-creep direction.
- Constraints: list only what would change the architect's design if violated.
- Verification: non-skippable. Name the concrete tests, gates, qa.md trigger patterns, and regression tests required by the findings flywheel. If verification cannot be specified at planning time, that is itself a planning gap and must be flagged before the promotion gate passes - the Brief is not Skeptic-eligible until verification is named.
- Outcome rubric: OPERATOR-AUTHORED ACCEPTANCE STATEMENTS - distinct from the Verification field's gate commands. Verification = mechanical commands and test paths; rubric = the operator's semantic definition of done, expressed as max 6 terse pass/fail lines each tagged `verification_type: deterministic | judgment`. Deterministic lines name the gate that proves the criterion; judgment lines are graded adversarially by the independent Skeptic and must never be self-certifying. Required for Elevated (absence is Critical); not required for Trivial or Low.
- QA criteria: required for Elevated. YAML schema fields: `qa_skip` (one of: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only` - or null); `qa_skip_rationale` (string, max 200 chars, required iff `qa_skip != null`); `viewport` (root-level list of named viewports applied to all scenarios; default `[desktop]`; valid values: `mobile`, `tablet`, `desktop`; canonical sizes: mobile 375x667, tablet 768x1024, desktop 1440x900; override canonical sizes via project `qa.md`); `scenarios[]` with `id` (monotonic int), `description` (one observable sentence), `method` (one of: `browser`, `api`, `runtime-required`, `visual_conformance`, `accessibility`, `perceptual_diff`, `motion`), `evidence` (string), optional per-scenario `viewport` list (REPLACES the root list for this scenario, not extends it) - required when `qa_skip == null` with at least 1 entry; `manual_smoke` (paragraph or "none"). Drives the Phase 6b QA gate trigger in `/ds-implement-ticket`. The Skeptic-on-Brief reviewer validates this field: an absent QA criteria block on an Elevated Brief is a Critical finding; an invalid `qa_skip` enum is a Major finding. Operator-supplied Briefs (`brief_source: operator`) must include this field; absence is a Critical finding the operator must resolve before sign-off. When the unit is UI-visible AND the ticket text contains an Expected Result block (or equivalent visual-claim section), the unit's `scenarios[]` MUST contain at least one scenario with `method: visual_conformance`, with a verbatim `source_quote` and at least one `expected_visual_claims[]` entry. Absence is a Critical finding. The `advisory: true` marker on individual claims opts them out of auto-Critical / auto-fail but remains auditable in the Skeptic review surface. `visual_conformance` scenarios add two REQUIRED fields beyond the standard scenario shape: `source_quote` (string, verbatim copy of the ticket's Expected Result block or equivalent visual-spec section - paraphrase is not permitted) and `expected_visual_claims[]` (min 1 entry; each entry is `{claim: <verbatim atomic assertion>, advisory?: <bool, default false>}`). Each claim must be a single atomic check (one color, one position, one element presence, one typography attribute); compound claims must be split into separate entries. The `visual_conformance` method is not exclusive with `browser` - use `visual_conformance` when the criterion is the visual spec itself; use `browser` for behavioral UI flows (clicks, state transitions, form submissions). `accessibility` scenarios add two per-scenario fields: `wcag_level` (default `AA`; enum: `A`, `AA`, `AAA`) and optional `axe_tags` (array of axe-core rule tag strings). When `axe_tags` is absent, it is computed from `wcag_level` at runtime: `A` => `[wcag2a]`, `AA` => `[wcag2a, wcag2aa]`, `AAA` => `[wcag2a, wcag2aa, wcag2aaa]`. When both `wcag_level` and `axe_tags` are set explicitly, `axe_tags` wins at runtime; Skeptic raises Minor finding (redundant declaration - remove one). `accessibility` is required (auto-Critical) when the unit is UI-visible AND Elevated AND `qa_skip == null`. `perceptual_diff` scenarios add two per-scenario fields: `tolerance` (float, default `0.001`) and `baseline_path` (string, default `tests/visual-baselines/<scenario-id>/<viewport>.png`). Opt-in via `.agentic/config.json` `perceptual_diff_enabled: true` (default `false`). First run with absent baseline saves the baseline and returns INCONCLUSIVE with "baseline pending review" note; subsequent runs compare against the saved baseline using `page.screenshot()` + pixelmatch buffer comparison with `diff_ratio > tolerance` fail threshold. When `perceptual_diff_enabled: true` AND the unit is UI-visible AND the ticket has a visual spec AND no `perceptual_diff` scenario is present, Skeptic raises Major. `motion` scenarios add two REQUIRED fields: `route` (string, URL or page path to navigate to) and `elements` (string `"auto"` for full-page scan, or array of CSS selectors). `motion` scenarios run via Playwright CDP `Emulation.setEmulatedMedia` with `prefers-reduced-motion: reduce` and report per-(scenario x viewport x theme) PASS/FAIL/INCONCLUSIVE rows. Requires `playwright-python` (see qa-engineer.md); returns INCONCLUSIVE with install message when Playwright missing. When `motion_aware: true` (`.agentic/config.json`) AND the unit is UI-visible AND Elevated AND `qa_skip == null` AND no `motion` scenario is present, Skeptic raises Major. `theme` is valid on `visual_conformance`, `accessibility`, and `motion` scenarios. Setting `theme` on any other method (`perceptual_diff`, `browser`, `api`, `runtime-required`) is invalid and Skeptic raises Critical. `theme` (enum: `light | dark | both`; default `both` when `.agentic/config.json` `theme_aware: true`) causes qa-engineer to run the scenario once per theme value in a two-pass loop. When `theme_aware: false` AND `theme` is set on a scenario, qa-engineer logs an operator warning and ignores the field (no INCONCLUSIVE, no fail - the field is silently skipped). `theme` is subject to an auto-Major rule: when `theme_aware: true` AND the scenario method is `visual_conformance` or `accessibility` AND the `theme` field is absent, the Skeptic raises Major. `story_id` is valid on `visual_conformance` and `accessibility` scenarios only (P1 binding). Setting `story_id` on any other method - including `motion` - is invalid and Skeptic raises Critical. `story_id` (string; Storybook 7+ story ID format, e.g. `"components-button--primary"`) causes qa-engineer to navigate to `<storybook_url>/iframe.html?id=<story_id>` instead of the live-app URL. When `storybook_version: 6` in `.agentic/config.json`, qa-engineer applies the SB6 URL conversion algorithm (splits on `--`, Title Cases kind and story segments, uses `?selectedKind=&selectedStory=` format). A story ID with no `--` separator is malformed input; qa-engineer returns FAIL. Opt-in: only include `story_id` when `.agentic/config.json` has `storybook_enabled: true` (default `false`). When `story_id` is present but `storybook_enabled: false`, qa-engineer returns INCONCLUSIVE with operator message "story_id set but storybook_enabled is false in .agentic/config.json - set storybook_enabled: true to activate Storybook scenario routing." `storybook_url` defaults to `http://localhost:6006`; override via qa.md `story-url` tag (per-run) or `.agentic/config.json` `storybook_url` (per-project).

**Per-method required fields:**

| Method | Required extra fields | Optional extra fields |
|---|---|---|
| `browser` | (none beyond base scenario) | per-scenario `viewport` |
| `api` | (none beyond base scenario) | (none) |
| `runtime-required` | (none beyond base scenario) | (none) |
| `visual_conformance` | `source_quote`, `expected_visual_claims[]` | per-scenario `viewport`, `theme`, `story_id` |
| `accessibility` | (none - `wcag_level` defaults to `AA`) | `wcag_level`, `axe_tags`, per-scenario `viewport`, `theme`, `story_id` |
| `perceptual_diff` | (none - `tolerance` and `baseline_path` have defaults; opt-in via config) | `tolerance`, `baseline_path`, per-scenario `viewport` |
| `motion` | `route`, `elements` | `theme`, per-scenario `viewport` |
- Linked artifacts: makes the Brief auditable against its own inputs.

## Plan-tier directory

The Plan is primarily assembled from existing artifacts (architect plan, planner JSONL, Brief), with three short conductor-authored coverage documents. The "assembly" framing prevents the Plan from becoming a long-form design rewrite.

A "Plan" is a directory:

```
docs/planning/<slug>/
  brief.md                  # Brief template above (assembled)
  architect-plan.md         # architect's existing output, as-is (assembled)
  orchestration.jsonl       # orchestration-planner output, verbatim (assembled)
  risk-register.md          # <=10 lines, conductor-authored (coverage)
  rollback.md               # <=10 lines, conductor-authored (coverage)
  verification-gate.md      # see template below, conductor-authored (coverage)
```

**`verification-gate.md` owns the trigger (the signal that says "verification failed, time to roll back"); `rollback.md` owns the procedure (the steps to actually undo). They are complementary, not overlapping.**

**ADR carve-out:** for ADR-required work (cross-track or "Architecture decision constraining future choices"), add `adr-NNN.md` using the project's existing ADR convention. The Plan does not redefine ADR format.

**Coverage exception to "assembly":** risk register, rollback, and verification gate are conductor-authored because they exist nowhere upstream - the architect plan covers implementation, the planner covers structure, neither covers operational risk or verification. These three files are short by design (<=10 lines each plus the verification template); if any one exceeds the budget, the Plan is too large and should be split into multiple Briefs.

## Verification gate template

`verification-gate.md`:

```markdown
# Verification Gate

**Tests that must pass:**
- Unit: <commands or "n/a">
- Integration: <commands or "n/a">
- E2E: <commands or "n/a">

**qa-engineer triggered?** <yes/no>. If yes, list the qa.md trigger patterns that fire and the units they apply to.

**Manual smoke check:** <single paragraph or "none">

**Rubric lines resolved:**
- Rubric line 1 [deterministic]: gate command: `<command>`; result: pass/fail
- Rubric line 2 [judgment]: grader: Skeptic; result: pass/fail

**Rollback signal:** <how we will know post-merge that this needs to be reverted - what alarm, what user signal, what metric. This is the trigger that hands off to `rollback.md`.>

**New regression tests required by findings flywheel?** <yes/no>. If yes, list the `.agentic/findings.md` entry IDs and the test files that will hold the regression.
```

The verification gate is non-skippable. **If verification cannot be specified at planning time, that is itself a planning gap and must be flagged before the promotion gate passes.** Any "cannot specify" entry blocks Skeptic sign-off; the operator resolves the gap by re-running architect, tightening the Brief, or descoping until verification is knowable.

## Promotion mechanics

**Mid-flight escalation.** A task can be promoted upward mid-work (e.g., a 3-unit Brief-tier task that the architect re-plans into 8 units gets re-classified as Plan-tier; an Elevated-single task whose planner re-decomposition produces 3+ Elevated units gets promoted to Brief-tier). When this fires:

- The in-flight engineer is allowed to return.
- Already-completed units are not retroactively re-reviewed.
- The retroactive Brief (or Plan) is authored before the next engineer spawn and governs all subsequent units.
- The Skeptic pass on the retroactive artifact runs to completion before the next worker spawns.
- the ticket's `.agentic/loop-state-<LOOP_KEY>.json` has its `promotion_tier` updated to reflect the new tier (see METHODOLOGY.md §Cross-session loop resume).

**Auto-promotion at 3rd resume.** When the ticket's `.agentic/loop-state-<LOOP_KEY>.json` (legacy: `.agentic/loop-state.json`) records a third resume of a Brief-tier task, the conductor authors the missing Plan-tier artifacts (risk register, rollback, verification gate) before the next worker spawn. The trigger is mechanical - the `resume_count` field, incremented once per accepted resume including a legacy adoption (see `/ds-implement-ticket` Phase 6 Field notes) - and fires regardless of whether the operator notices the session span. Because the file is keyed per ticket, the count is now per ticket rather than shared, which is what makes it meaningful across a batch. A file adopted from the legacy unkeyed path starts at `0`, so a Brief-tier task mid-flight when keying landed auto-promotes later than it otherwise would - bounded and one-time.

**Promotion is upward only.** A task cannot be demoted. Once a Brief or Plan exists, subsequent workers continue to read it.

## Product-intent layer (operator-owned)

Above task-level Briefs and Plans sits an optional operator-owned product-intent layer: `docs/overview/vision.md` (why the product exists, who it serves, what outcome it delivers) and `docs/overview/requirements.md` (scoped functional and non-functional requirements). These files are operator-authored and committed; agents read them but never write or propose edits. When present, the Architect treats them as authoritative product intent, the Investigator reads them for framing context, and the Engineer reads them before implementing (see `content/agents/engineer.md` §Reading your spawn prompt and required context) - so the intent layer is consulted before shippable work even on an architect-skipped path, not only when a ticket is routed through Architect/Investigator; a Brief's `Problem` and `Constraints` fields should be consistent with them. They are optional and graceful - if `docs/overview/` or these files are absent, nothing breaks and no planning artifact is blocked. Schema and authoring rules live in `content/rules/conventions.md` §Project Overview Layer.

## `motion_aware` (config key)

`motion_aware` is a boolean project-level config key in `.agentic/config.json`. Default `false`. When `true`, a UI-visible Elevated unit with `qa_skip == null` that has no `motion` scenario in its `qa_criteria` will trigger a Skeptic Major finding. Mirrors the `theme_aware` opt-in precedent. Operator-declared; there is no auto-detection from CSS files. Seeded to `false` by `/ds-init-project`.

## `storybook_version` (config key)

`storybook_version` is an enum config key in `.agentic/config.json` with valid values `6` or `7`. Default `7`. When `6`, qa-engineer applies the SB6 URL conversion algorithm for `story_id` fields: splits the story ID on `--`, Title Cases each path segment for kind and each word for story, and constructs the URL as `<storybook_url>/iframe.html?selectedKind=<encoded_kind>&selectedStory=<encoded_story>`. A story ID with no `--` separator is malformed; qa-engineer returns FAIL. When the value is absent or `7`, qa-engineer uses the current `?id=` format unchanged. Seeded explicitly by `/ds-init-project` based on `@storybook/*` framework adapter version detection.

## `qa_default_skip` (canonical definition)

`qa_default_skip` is a **reserved** project-level config key in `.agentic/config.json`, documented here for schema completeness. This is the canonical definition; `content/rules/conventions.md` and §Risk Classification cross-reference this section and must not redefine it.

- It is **distinct from** the per-Brief/per-unit `qa_skip` enum (the 5 values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`). The two are unrelated keys and must not be conflated: `qa_skip` is a per-unit QA decision; `qa_default_skip` is a reserved project-level toggle.
- It **does NOT currently alter QA-gate behavior.** The QA fire/skip decision remains governed entirely by the per-unit `qa_skip` enum and the invariant in §QA Gate (`content/sections/05-qa-gate.md`). `qa_default_skip` does not override, weaken, or bypass that invariant, and introduces no new skip category.

The key is reserved so projects and tooling can rely on a stable schema; any future behavioral wiring is out of scope until separately specified.
