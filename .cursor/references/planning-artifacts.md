<!--
Purpose: Full reference for planning-artifact templates, directory layouts, and
         promotion mechanics extracted from METHODOLOGY.md §Planning Artifacts.
         Contains the Brief template (including outcome_rubric field), Plan-tier
         directory layout, verification-gate template (including rubric-resolved
         subsection), promotion mechanics, product-intent layer rules, and the
         canonical qa_default_skip definition.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/03-planning-artifacts.md (Gate semantics pointer),
            content/sections/12-protocol-details.md (Protocol Details entry).

Upstream deps: content/sections/03-planning-artifacts.md (parent section;
               read that section first for triggers and ordering);
               content/rules/module-manifest.md (manifest header contract);
               content/rules/conventions.md §Project Overview Layer.

Downstream consumers: Conductor flows: Brief authoring (Gate semantics step 6),
                      Plan authoring (Plan tier authoring sequence), cross-session
                      resume (promotion_tier field); /brief command (rubric synthesis
                      in Section 3 and PRD extraction in Section 5); /implement-ticket
                      Phase 3b cross-artifact alignment check; skeptic agent (rubric
                      check step 3.5); product-discovery agent (rubric drafting step 5b).

Failure modes: Prose; does not execute. Drift between this file and the parent
               section (03-planning-artifacts.md) is a Major Skeptic finding.
               Stale field guidance misleads Brief authors; keep in sync with
               any changes to the Brief template fields.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Planning Artifacts. Read that section first for triggers and ordering.

# Planning Artifacts - Full Reference

## Brief template

**Canonical path:** `docs/planning/<slug>.md` (slug = kebab-case feature name, prefixed with priority tag if the project uses one, e.g. `p2-foo.md`).

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

**Outcome rubric:** <Operator-confirmed pass/fail lines (max 6). Each line is a terse, observable acceptance statement tagged with its verification_type: `deterministic` (a nameable gate - tests, lint, schema check, HTTP status) or `judgment` (qualitative, graded adversarially by the independent Skeptic - never self-certifying). Required for Elevated; absence is a Critical Skeptic finding. Distinct from Verification: Verification names gate commands; rubric lines are the operator's semantic definition of done. Draft via product-discovery step 5b or /brief Section 3, then confirm before Brief authoring.>
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
- QA criteria: required for Elevated. YAML schema fields: `qa_skip` (one of: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only` - or null); `qa_skip_rationale` (string, max 200 chars, required iff `qa_skip != null`); `viewport` (root-level list of named viewports applied to all scenarios; default `[desktop]`; valid values: `mobile`, `tablet`, `desktop`; canonical sizes: mobile 375x667, tablet 768x1024, desktop 1440x900; override canonical sizes via project `qa.md`); `scenarios[]` with `id` (monotonic int), `description` (one observable sentence), `method` (one of: `browser`, `api`, `runtime-required`, `visual_conformance`, `accessibility`, `perceptual_diff`, `motion`), `evidence` (string), optional per-scenario `viewport` list (REPLACES the root list for this scenario, not extends it) - required when `qa_skip == null` with at least 1 entry; `manual_smoke` (paragraph or "none"). Drives the Phase 6b QA gate trigger in `/implement-ticket`. The Skeptic-on-Brief reviewer validates this field: an absent QA criteria block on an Elevated Brief is a Critical finding; an invalid `qa_skip` enum is a Major finding. Operator-supplied Briefs (`brief_source: operator`) must include this field; absence is a Critical finding the operator must resolve before sign-off. When the unit is UI-visible AND the ticket text contains an Expected Result block (or equivalent visual-claim section), the unit's `scenarios[]` MUST contain at least one scenario with `method: visual_conformance`, with a verbatim `source_quote` and at least one `expected_visual_claims[]` entry. Absence is a Critical finding. The `advisory: true` marker on individual claims opts them out of auto-Critical / auto-fail but remains auditable in the Skeptic review surface. `visual_conformance` scenarios add two REQUIRED fields beyond the standard scenario shape: `source_quote` (string, verbatim copy of the ticket's Expected Result block or equivalent visual-spec section - paraphrase is not permitted) and `expected_visual_claims[]` (min 1 entry; each entry is `{claim: <verbatim atomic assertion>, advisory?: <bool, default false>}`). Each claim must be a single atomic check (one color, one position, one element presence, one typography attribute); compound claims must be split into separate entries. The `visual_conformance` method is not exclusive with `browser` - use `visual_conformance` when the criterion is the visual spec itself; use `browser` for behavioral UI flows (clicks, state transitions, form submissions). `accessibility` scenarios add two per-scenario fields: `wcag_level` (default `AA`; enum: `A`, `AA`, `AAA`) and optional `axe_tags` (array of axe-core rule tag strings). When `axe_tags` is absent, it is computed from `wcag_level` at runtime: `A` => `[wcag2a]`, `AA` => `[wcag2a, wcag2aa]`, `AAA` => `[wcag2a, wcag2aa, wcag2aaa]`. When both `wcag_level` and `axe_tags` are set explicitly, `axe_tags` wins at runtime; Skeptic raises Minor finding (redundant declaration - remove one). `accessibility` is required (auto-Critical) when the unit is UI-visible AND Elevated AND `qa_skip == null`. `perceptual_diff` scenarios add two per-scenario fields: `tolerance` (float, default `0.001`) and `baseline_path` (string, default `tests/visual-baselines/<scenario-id>/<viewport>.png`). Opt-in via `.agentic/config.json` `perceptual_diff_enabled: true` (default `false`). First run with absent baseline saves the baseline and returns INCONCLUSIVE with "baseline pending review" note; subsequent runs compare against the saved baseline using `page.screenshot()` + pixelmatch buffer comparison with `diff_ratio > tolerance` fail threshold. When `perceptual_diff_enabled: true` AND the unit is UI-visible AND the ticket has a visual spec AND no `perceptual_diff` scenario is present, Skeptic raises Major. `motion` scenarios add two REQUIRED fields: `route` (string, URL or page path to navigate to) and `elements` (string `"auto"` for full-page scan, or array of CSS selectors). `motion` scenarios run via Playwright CDP `Emulation.setEmulatedMedia` with `prefers-reduced-motion: reduce` and report per-(scenario x viewport x theme) PASS/FAIL/INCONCLUSIVE rows. Requires `playwright-python` (see qa-engineer.md); returns INCONCLUSIVE with install message when Playwright missing. When `motion_aware: true` (`.agentic/config.json`) AND the unit is UI-visible AND Elevated AND `qa_skip == null` AND no `motion` scenario is present, Skeptic raises Major. `theme` is valid on `visual_conformance`, `accessibility`, and `motion` scenarios. Setting `theme` on any other method (`perceptual_diff`, `browser`, `api`, `runtime-required`) is invalid and Skeptic raises Critical. `theme` (enum: `light | dark | both`; default `both` when `.agentic/config.json` `theme_aware: true`) causes qa-engineer to run the scenario once per theme value in a two-pass loop. When `theme_aware: false` AND `theme` is set on a scenario, qa-engineer logs an operator warning and ignores the field (no INCONCLUSIVE, no fail - the field is silently skipped). `theme` is subject to an auto-Major rule: when `theme_aware: true` AND the scenario method is `visual_conformance` or `accessibility` AND the `theme` field is absent, the Skeptic raises Major. `story_id` is valid on `visual_conformance` and `accessibility` scenarios only (P1 binding). Setting `story_id` on any other method - including `motion` - is invalid and Skeptic raises Critical. `story_id` (string; Storybook 7+ story ID format, e.g. `"components-button--primary"`) causes qa-engineer to navigate to `<storybook_url>/iframe.html?id=<story_id>` instead of the live-app URL. When `storybook_version: 6` in `.agentic/config.json`, qa-engineer applies the SB6 URL conversion algorithm (splits on `--`, Title Cases kind and story segments, uses `?selectedKind=&selectedStory=` format). A story ID with no `--` separator is malformed input; qa-engineer returns FAIL. Opt-in: only include `story_id` when `.agentic/config.json` has `storybook_enabled: true` (default `false`). When `story_id` is present but `storybook_enabled: false`, qa-engineer returns INCONCLUSIVE with operator message "story_id set but storybook_enabled is false in .agentic/config.json - set storybook_enabled: true to activate Storybook scenario routing." `storybook_url` defaults to `http://localhost:6006`; override via qa.md `story-url` tag (per-run) or `.agentic/config.json` `storybook_url` (per-project).

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
- `.agentic/loop-state.json` `promotion_tier` is updated to reflect the new tier (see METHODOLOGY.md §Cross-session loop resume).

**Auto-promotion at 3rd resume.** When `.agentic/loop-state.json` records a third resume of a Brief-tier task, the conductor authors the missing Plan-tier artifacts (risk register, rollback, verification gate) before the next worker spawn. The trigger is mechanical - resume-count tracked in the loop-state file - and fires regardless of whether the operator notices the session span.

**Promotion is upward only.** A task cannot be demoted. Once a Brief or Plan exists, subsequent workers continue to read it.

## Product-intent layer (operator-owned)

Above task-level Briefs and Plans sits an optional operator-owned product-intent layer: `docs/overview/vision.md` (why the product exists, who it serves, what outcome it delivers) and `docs/overview/requirements.md` (scoped functional and non-functional requirements). These files are operator-authored and committed; agents read them but never write or propose edits. When present, the Architect treats them as authoritative product intent and the Investigator reads them for framing context; a Brief's `Problem` and `Constraints` fields should be consistent with them. They are optional and graceful - if `docs/overview/` or these files are absent, nothing breaks and no planning artifact is blocked. Schema and authoring rules live in `content/rules/conventions.md` §Project Overview Layer.

## `motion_aware` (config key)

`motion_aware` is a boolean project-level config key in `.agentic/config.json`. Default `false`. When `true`, a UI-visible Elevated unit with `qa_skip == null` that has no `motion` scenario in its `qa_criteria` will trigger a Skeptic Major finding. Mirrors the `theme_aware` opt-in precedent. Operator-declared; there is no auto-detection from CSS files. Seeded to `false` by `/init-project`.

## `storybook_version` (config key)

`storybook_version` is an enum config key in `.agentic/config.json` with valid values `6` or `7`. Default `7`. When `6`, qa-engineer applies the SB6 URL conversion algorithm for `story_id` fields: splits the story ID on `--`, Title Cases each path segment for kind and each word for story, and constructs the URL as `<storybook_url>/iframe.html?selectedKind=<encoded_kind>&selectedStory=<encoded_story>`. A story ID with no `--` separator is malformed; qa-engineer returns FAIL. When the value is absent or `7`, qa-engineer uses the current `?id=` format unchanged. Seeded explicitly by `/init-project` based on `@storybook/*` framework adapter version detection.

## `qa_default_skip` (canonical definition)

`qa_default_skip` is a **reserved** project-level config key in `.agentic/config.json`, documented here for schema completeness. This is the canonical definition; `content/rules/conventions.md` and §Risk Classification cross-reference this section and must not redefine it.

- It is **distinct from** the per-Brief/per-unit `qa_skip` enum (the 5 values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`). The two are unrelated keys and must not be conflated: `qa_skip` is a per-unit QA decision; `qa_default_skip` is a reserved project-level toggle.
- It **does NOT currently alter QA-gate behavior.** The QA fire/skip decision remains governed entirely by the per-unit `qa_skip` enum and the invariant in §QA Gate (`content/sections/05-qa-gate.md`). `qa_default_skip` does not override, weaken, or bypass that invariant, and introduces no new skip category.

The key is reserved so projects and tooling can rely on a stable schema; any future behavioral wiring is out of scope until separately specified.
