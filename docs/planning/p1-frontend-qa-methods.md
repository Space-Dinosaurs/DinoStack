# P1 Brief: Front-end QA - theme, storybook, FE-discipline, knowledge tags

## Problem

P0 shipped the FE/QA foundation: `accessibility`, `perceptual_diff`, `viewport`, and capability preflight. Four gaps remain that block agents from delivering production-quality FE work without re-litigating each surface in every Brief:

1. **No dark/light theme verification.** UI ships dark-mode regressions invisibly. Operators must re-author `visual_conformance` claims per theme manually.
2. **No component-isolation verification.** Design-system work in shared components is verified at route level, requiring auth and full app boot for what should be an isolated render check.
3. **FE is still not a discipline in the methodology.** `content/agents/engineer.md` has zero mentions of semantic HTML, ARIA, keyboard support, focus management, design tokens, or reduced motion. `content/references/skeptic-protocol.md` has no FE-specific finding categories. UI work passes Skeptic review on correctness criteria designed for backend logic.
4. **qa.md knowledge tags don't cover the new surfaces.** Tags are `viewport`, `a11y-baseline`, `perceptual-baseline`, `axe-rule` after P0. Adding `theme`, `story-url`, `motion` needed for the above.

## Success criteria

A future qa-engineer run on an Elevated UI-visible unit:

- When `.agentic/config.json` has `theme_aware: true`, `visual_conformance` and `accessibility` scenarios with `theme: both` run twice (light + dark) and report per-(scenario × viewport × theme) tuples. Auto-Major when `theme_aware: true` and the scenario omits `theme` on these two methods.
- When `.agentic/config.json` has `storybook_enabled: true` AND a unit's scenario has `story_id`, qa-engineer navigates to the storybook iframe (`/iframe.html?id=<story_id>`) and runs the scenario's method against the isolated component. Default `false`; opt-in to keep CI hermetic.
- When the diff touches FE files (FE-glob below), Skeptic applies the new FE-discipline finding categories from `content/references/frontend-discipline.md`. Major findings for a11y violations, hardcoded tokens in tokenized codebases, missing focus management, missing keyboard support, missing reduced-motion. Minor for missing responsive classes.

## Constraints

- All four additions land as edits under `content/**` only. No source-code changes outside the methodology package.
- Schema changes mirrored across 10 adapter build targets (same list as P0). CI `check-adapter-sync` must pass.
- **`story_id` is restricted to `method ∈ {visual_conformance, accessibility}` only.** Setting `story_id` on `perceptual_diff`, `browser`, `api`, or `runtime-required` is invalid; Skeptic raises Critical. Rationale: `perceptual_diff` would have ambiguous baseline-path semantics (story vs live-app render); `api` and `runtime-required` have no browser surface; `browser` is for interaction flows where Storybook's isolated render does not apply.
- **`storybook_enabled: false` default** in `.agentic/config.json` (mirrors `perceptual_diff_enabled` precedent). Opt-in keeps CI hermetic and avoids surfacing storybook-dev-server requirements in pipelines that don't use Storybook.
- **Storybook 7+ only.** SB7+ URL format is `?args=&id=`; SB6's `?selectedKind=&selectedStory=` is NOT supported at P1. **Version detection algorithm (binding):** check `package.json` for a Storybook framework adapter in this exact precedence order: `@storybook/react`, `@storybook/vue`, `@storybook/vue3`, `@storybook/angular`, `@storybook/svelte`, `@storybook/web-components`, `@storybook/html`, `@storybook/core`. Take the FIRST one present; that package's semver determines the version. If none of those exist but other `@storybook/*` packages do (e.g., only `@storybook/addon-*`), emit warning "Storybook framework adapter not detected; storybook scenarios disabled" and leave `storybook_enabled: false`. If the detected framework package is `< 7.0.0`, emit warning "Storybook 6 detected; story scenarios disabled. Upgrade to SB7+ to use this feature." and leave `storybook_enabled: false`. Mixed-version installs (framework adapter on SB7+ with legacy `addon-*` on SB6) ARE supported - the framework adapter version is authoritative. SB6 framework adapter support is a P2 consideration.
- **`theme_aware: false` default** (mirrors P0 config precedent). When `true`, qa-engineer's default toggle mechanism **covers exactly two patterns**: CSS class (`document.documentElement.classList.toggle('dark')`) and data-attribute (`setAttribute('data-theme', 'dark')`). qa-engineer tries class first, then data-attribute, logs which mechanism worked in the scenario evidence, and emits INCONCLUSIVE (NOT pass) when neither produces a visible state change. **Other toggle patterns (`localStorage` + reload, React context/state, `prefers-color-scheme` simulation) are NOT covered by the default** and require operators to set the `qa.md` `theme` knowledge tag with a custom selector or action recipe. The Brief does not claim general-purpose theme coverage; the qa.md override is the escape hatch and qa-engineer surfaces "default theme toggle failed; set `theme:` tag in qa.md" in the INCONCLUSIVE message.
- **`storybook_url` default** `http://localhost:6006`. Operator overrides via qa.md `story-url` tag (per-run) or `.agentic/config.json` `storybook_url` (per-project).
- **Capability gate for storybook scenarios:** `curl -s -o /dev/null -w '%{http_code}' <storybook_url>/iframe.html` non-200 returns INCONCLUSIVE with operator message "Storybook dev server not reachable at <url>. Start it with `npm run storybook` or set storybook_url." NOT a clean skip - CI must surface the unmet precondition.
- **FE-glob is `**/*.{tsx,jsx,vue,svelte,astro,css,scss,html,mdx}` with multiple exclusions.** Tailwind config (`tailwind.config.{ts,js,mjs,cjs}`) and `.module.{css,scss}` are caught by extension match. Excluded paths: `content/**` (agentic-engineering methodology files); `docs/**/*.{mdx,html}` and `**/docs/**/*.{mdx,html}` (documentation `.mdx` and `.html` use markdown-as-HTML constructs that intentionally differ from production UI - NOTE this exclusion is scoped to `.mdx`/`.html` only; `.tsx`/`.jsx`/etc under `docs/` paths still receive FE-discipline review because they are real production components); `**/*.stories.{tsx,jsx,ts,js}` (story files document component states); `**/*.test.{tsx,jsx,ts,js}`, `**/*.spec.{tsx,jsx,ts,js}` (test files).
- **FE-discipline severities are calibrated by accessibility/operational impact, not visual nicety:**
  - Major: `semantic-html-misuse`, `aria-needs-no-aria`, `missing-focus-management` (modal/drawer context), `hardcoded-token-instead-of-design-token` (token-system detection rules below), `missing-keyboard-support`, `motion-not-reduced-motion-aware`, `outline-none-without-replacement`
  - Minor: `missing-responsive-class` (often intentional on desktop-only surfaces)
  - Each finding requires the Skeptic to cite both the file/line AND the matching `content/references/frontend-discipline.md` section. Findings without the cross-reference are invalid.
- **Token-system detection for `hardcoded-token-instead-of-design-token` (binding heuristics, any one triggers "token system present"):** (a) `tailwind.config.{ts,js,mjs,cjs}` exists at repo root AND contains a `theme.extend` block with `colors` or `spacing`; (b) any CSS file (per FE-glob) contains `:root` with at least two `--`-prefixed custom properties used elsewhere in the codebase; (c) a `tokens.{ts,js,json}` or `design-tokens.{ts,js,json}` file at the repo root; (d) a `theme.{ts,js}` or `themes/` directory exporting an object literal. None of (a)-(d) detected ⇒ the finding does NOT fire. The Skeptic must cite which heuristic triggered detection in the finding body; absent that citation, the finding is invalid.
- **`motion` knowledge tag is DEFERRED to P2** (will ship alongside its consumer scenario method). P1 does not introduce the tag to avoid dead-infrastructure drift.

## Non-goals

- Storybook 6 support (P2 if there's demand).
- Standalone `motion` scenario method (P2).
- Lighthouse perf budgets, cross-browser matrix, design-spec drift (P2/P3).
- Reframing security-auditor or perf-analyst as FE-aware (separate Brief).
- Auto-detection of `theme_aware: true` from codebase (operator declares; opt-in).

## Approach

Five units total: four content-edit units (U1-U4) plus U5 (adapter rebuild verification). The pre-commit hook rebuilds adapters on every commit, so U5 in practice is a final CI gate confirmation, not engineer work - but it is counted as a unit to remove ambiguity about end-of-pipeline responsibility.

**1. Schema additions** (`content/references/planning-artifacts.md`, `content/agents/architect.md`, `content/references/skeptic-protocol.md`):
- `theme` field on `visual_conformance` and `accessibility` scenarios (enum `light | dark | both`; default `both` when `theme_aware: true`; ignored with warning when `theme_aware: false` and field set)
- `story_id` field on `visual_conformance` and `accessibility` scenarios only (string; Storybook 7+ story ID format); Critical on incompatible method combination
- Auto-Major rules: `theme` missing when `theme_aware: true` on `visual_conformance`/`accessibility`; `story_id` on incompatible method
- New `### theme enforcement` and `### story_id enforcement` Skeptic subsections after the P0 `### viewport enforcement` block

**2. qa-engineer procedures** (`content/agents/qa-engineer.md` ONLY):
- New `## Theme-aware scenarios` section: two-pass loop (light/dark), toggle-mechanism fallback chain with evidence logging, qa.md override resolution
- New `## Storybook scenarios` section: `storybook_enabled` preflight, URL resolution (qa.md tag → config key → default), `/iframe.html?id=` navigation, capability gate (curl precondition)
- Knowledge tags extended: `theme`, `story-url` (the `motion` tag is deferred to P2 alongside its consumer)
- Evidence JSON extended with `theme` and `story_id` fields per tuple
- `capabilities:` block: add `storybook_url` (optional, gated by config)

**3. FE-discipline reference + engineer.md addendum** (`content/references/frontend-discipline.md` NEW, `content/agents/engineer.md`, `content/references/skeptic-protocol.md`):
- New `content/references/frontend-discipline.md` (7 sections per architect outline; module manifest header required)
- `engineer.md` gains short `## Front-end discipline` section with cross-reference (single section, ≤12 lines)
- `skeptic-protocol.md` gains `### FE-discipline findings (auto-apply on FE diffs)` subsection: FE-glob trigger, finding table with severities, citation requirement

**4. Config + init seed + risk-classification toggle entry** (`content/commands/init-project.md`, `content/sections/04-risk-classification.md`, `content/rules/conventions.md`):
- `.agentic/config.json` seed gains `theme_aware: false`, `storybook_enabled: false`; `storybook_url` only when SB7+ detected
- init-project Storybook version detection (read `package.json` for `@storybook/*` semver; emit SB6 warning if `< 7.0.0`)
- conventions.md §Project Config gains the new keys (toggles count `6` → `8`)
- 04-risk-classification.md §Project Config gains the new keys (count `6` → `8`)

**File ownership (no overlap, safe parallel):**
- U1 owns: `planning-artifacts.md`, `architect.md`, `skeptic-protocol.md`
- U2 owns: `qa-engineer.md` ONLY
- U3 owns: `engineer.md`, `frontend-discipline.md` (new), `skeptic-protocol.md` SUBSECTION ADD (FE-discipline findings only; U1 owns the theme/story_id subsections)
- U4 owns: `init-project.md`, `conventions.md`, `04-risk-classification.md`

**U1 and U3 both touch `skeptic-protocol.md`.** To eliminate any race: U1 adds the schema-enforcement subsections (`theme`, `story_id`); U3 adds the FE-discipline subsection. **U3's engineer spawn brief MUST explicitly require that U3's worktree branches from main only AFTER U1's PR has merged.** The conductor enforces this by serializing the U1 → U3 transition: U1 PR opens, Skeptic passes, PR merges, main pulled, THEN U3 spawns with worktree branched from updated main. U2 and U4 may run in parallel with U3 because they touch disjoint files (U2 owns qa-engineer.md only; U4 owns init-project.md / conventions.md / 04-risk-classification.md only). This is the same pattern P0 used for U1 → U2 → U3 → U4 sequencing; the addition here is the explicit branch-from-post-U1-merge requirement in the U3 spawn brief.

## QA criteria

```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: All P1 changes are documentation-only edits to content/ schema specs and agent specs. No runtime code changes in the agentic-engineering repo itself.
  scenarios: []
  manual_smoke: none
```

## Verification gate

1. **Smoke Brief** at `docs/planning/p1-fe-qa-smoke.md` (follow-up) targets a synthetic Helios UI ticket exercising `theme: both` on a `visual_conformance` scenario, `story_id` on an `accessibility` scenario, and a `.tsx` diff that triggers FE-discipline findings. Expected: per-(scenario × viewport × theme) rows, axe run against the Storybook iframe, Skeptic finding output citing `frontend-discipline.md` sections.
2. **Capability gates:** spawn qa-engineer with `theme_aware: true` AND scenario missing `theme` field; confirm Skeptic-on-Brief raises Major. Spawn with `story_id` on `method: perceptual_diff`; confirm Critical.
3. **Storybook detection:** init-project against a fixture project with `@storybook/react@6.5.0` in package.json; confirm SB6 warning emitted, `storybook_enabled: false`, no `storybook_url` written.
4. **Theme toggle fallback:** qa-engineer run on a `data-theme`-based project (no `.dark` class); confirm fallback succeeds and evidence JSON logs `theme_toggle_mechanism: "data-attribute"`.
5. **FE-glob exclusions:** Skeptic on a `.stories.tsx` diff confirms FE-discipline findings do NOT fire. Skeptic on `tailwind.config.ts` confirms findings DO fire.
6. **Adapter sync:** all 10 build scripts succeed; CI `check-adapter-sync` green.
7. **Schema drift check:** `grep -rn "story_id\|theme_aware\|storybook_enabled" content/` returns consistent hits across `planning-artifacts.md`, `architect.md`, `qa-engineer.md`, `skeptic-protocol.md`, `init-project.md`, `conventions.md`, `04-risk-classification.md`.

## Open questions

None. Both prior open questions are resolved with committed decisions:

1. **Storybook 6 support: DEFERRED to P2.** Rationale: SB6 EOL is approaching, the `?selectedKind=` URL format requires a separate code path in qa-engineer, and SB6 projects can upgrade without semantic change. P1 detects SB6 explicitly and disables `storybook_enabled` with a clear operator message; this is a clean degradation, not a silent failure.

2. **`motion` knowledge tag DEFERRED with explicit P2 marker.** P1 does NOT ship the `motion` knowledge tag. Rationale: shipping infrastructure with no consumer creates semantic drift (the Skeptic finding from the prior round). When P2 introduces a `method: motion` scenario, it will ship the tag and the consumer together. This drops the tag from the U2 scope (one less line of work).

## Decomposition hint

Five units, with file ownership pre-deconflicted:

- **U1: schema additions** (`planning-artifacts.md`, `architect.md`, `skeptic-protocol.md` schema enforcement subsections) - sequential foundation.
- **U2: qa-engineer procedures** (`qa-engineer.md` ONLY) - depends on U1.
- **U3: FE-discipline reference + engineer.md addendum + Skeptic FE-discipline subsection** (`frontend-discipline.md` new, `engineer.md`, `skeptic-protocol.md` FE-discipline subsection only) - sequential after U1 to avoid skeptic-protocol.md conflict; can run parallel with U2.
- **U4: config + init seed + risk-classification entries** (`init-project.md`, `conventions.md`, `04-risk-classification.md`) - depends on U1; can run parallel with U2 and U3.
- **U5: adapter rebuild** - pre-commit hook handles per commit; final CI check on merge.

Critical path: U1 → U2 → merge / U3 → merge / U4 → merge → CI gate.

---

## Architect plan reference

Full architect plan returned in prior conversation turn. Skeptic on architect plan surfaced 7 Majors (story_id + perceptual_diff baseline semantics, method compatibility matrix, SB6 capability gate, story_id CI gate, U2/U3 file conflict, theme toggle default, false-empty Open Questions). All 7 are resolved in this Brief above via the explicit constraints and the file-ownership table.
