# P2 Brief: Front-end QA - motion method, Storybook 6 support, capability blocking mode

## Problem

P0 + P1 shipped accessibility, perceptual_diff, viewport, theme, story_id, FE-discipline, and capability preflight (advisory mode). Three follow-ups remain:

1. **No motion-accessibility verification.** The FE-discipline `motion-not-reduced-motion-aware` finding catches static-code violations, but there is no runtime verification that animations respect `prefers-reduced-motion: reduce`. Users with vestibular disorders get hit by motion regressions invisibly.
2. **Storybook 6 projects are blocked from `story_id` scenarios.** P1 explicitly deferred SB6 support; init-project warns and disables `storybook_enabled` for SB6 projects. Many design-system projects still on SB6 cannot use the isolation verification we shipped.
3. **Capability preflight stays advisory** until every agent's `capabilities:` block is populated. P0 shipped with 9 agents holding empty `required: [] optional: []` placeholders. P1 added qa-engineer. The remaining 9 need real manifests so the methodology can flip the default to `blocking`.

## Success criteria

- A qa-engineer run on a UI-visible unit with a `motion` scenario triggers CDP `Emulation.setEmulatedMedia` with `prefers-reduced-motion: reduce`, scans the configured elements, and reports per-(scenario × viewport × theme) PASS/FAIL/INCONCLUSIVE rows naming offending elements.
- When `motion_aware: true` is set in `.agentic/config.json` AND a UI-visible Elevated unit lacks any `motion` scenario, Skeptic-on-Brief raises Major.
- A qa-engineer run on a unit with `story_id` on a project whose `.agentic/config.json` `storybook_version: 6` navigates to the converted `?selectedKind=&selectedStory=` URL instead of `?id=`.
- New `init-project` runs default `capability_preflight_mode: blocking`. Existing projects keep their config unchanged. Every agent has a real `capabilities:` block so no spawn fails silently on missing manifest.

## Constraints

- All edits land under `content/**`. CI `check-adapter-sync` must pass.
- **`story_id` validity remains restricted to `method ∈ {visual_conformance, accessibility}`** as P1 mandated. `motion` does NOT compose with `story_id` at P2. Motion scenarios use the `route` field directly (URL or page path). Rationale: P1's restriction was Skeptic-approved and enforced as Critical in `content/references/skeptic-protocol.md`; expanding the allowlist without explicit operator confirmation violates the methodology hard gate on superseding prior binding constraints. Operators who want motion-on-isolated-story can wait for a future Brief that explicitly asks for that expansion.
- **`motion` is a new method enum value**, not a field modifier on `visual_conformance`. Rationale: motion verification is a behavioral check (CDP emulation + computed-style diff), not a rendering pass variation.
- **`motion_aware: false` default** in `.agentic/config.json` (mirrors `theme_aware` / `perceptual_diff_enabled` opt-in precedent). When `true`, auto-Major fires for missing motion scenarios on UI-visible Elevated units.
- **Motion method REQUIRES Playwright.** CDP `Emulation.setEmulatedMedia` cannot run via agent-browser CLI. qa-engineer's capabilities block adds `playwright-python` as `required` with `required_when: "scenario.method == 'motion'"`. INCONCLUSIVE with operator install message when Playwright missing AND `storybook_enabled` mode doesn't auto-install (Playwright browser binary install is not on the safe auto-install list per P0).
- **Motion `elements` field:** required on every motion scenario. Two valid values: (a) a CSS selector list (e.g. `["#hero-banner", ".nav-fade-in"]`) - scan only those elements; (b) the literal string `auto` - full-page scan.
- **Motion detection property set (binding for `auto` scan):** scan reports an element as "motion present" when any of these computed-style values is non-default AND not wrapped in a `prefers-reduced-motion: reduce` media query in source CSS: `animation-name` (not `none`), `animation-duration` (>0), `transition-property` (not `none`), `transition-duration` (>0). Explicitly excluded from `auto` detection: SVG `<animate>`, `<animateTransform>`, `<animateMotion>` elements (SMIL); `@keyframes` blocks with opacity-only changes; vendor-prefixed `-webkit-`/`-moz-` properties without an unprefixed equivalent. Excluded surfaces yield no finding; only the unprefixed/standard-property set drives PASS/FAIL.
- **SB6 URL conversion algorithm (binding):** split SB7 story ID on `--`; left = kind segment, right = story segment. Kind: replace `-` with `/`, then Title Case each path part. Story: replace `-` with ` `, then Title Case each word. URL: `<storybook_url>/iframe.html?selectedKind=<encoded_kind>&selectedStory=<encoded_story>`. Edge case: **a story ID with no `--` separator is malformed input and qa-engineer returns FAIL (not INCONCLUSIVE)** with operator message "Invalid story_id format: missing '--' separator. Correct the story_id field in your qa_criteria." Edge case fallback: after URL construction, if `curl` to the converted URL returns non-200, return INCONCLUSIVE with "SB6 story-name convention mismatch; set explicit URL via qa.md `story-url` tag override."
- **New `storybook_version` config key (binding):** enum `6 | 7`. Default `7`. init-project sets explicitly based on detection. When `6`, qa-engineer applies the SB6 conversion above; when `7` or absent, keeps current `?id=` format.
- **SB6 detection writes `storybook_url`:** when init-project detects an SB6 framework adapter, writes BOTH `storybook_version: 6` AND `storybook_url: "http://localhost:6006"` to the config (matches SB7 detection behavior; saves operator a manual step). `storybook_enabled` stays `false` - operator must opt in to enable storybook scenarios.
- **Capability blocking-mode flip:** `.agentic/config.json` `capability_preflight_mode` default flips from `advisory` to `blocking` in the init-project seed AND conventions.md AND 04-risk-classification.md. Existing projects keep their current config (init-project only seeds when the key is absent). The flip is safe before agent blocks are populated because absent or empty `capabilities:` blocks are documented no-ops in `content/references/capability-preflight.md`.
- **Agent capability block contents (binding):** see "Agent capability table" below. None use `auto_install: true` (all are system tools or developer-managed installs).
- **`context7` capability check measures MCP server config, not CLI presence:** the check command is `test -f .claude/settings.json && grep -q 'context7' .claude/settings.json` - mirrors the existing `chrome-devtools-mcp` pattern in qa-engineer.md. The `npx context7 --version` form was rejected because npx auto-downloads on miss and exits 0 unconditionally - zero signal about actual MCP availability.
- **Story ID enforcement allowlist stays `{visual_conformance, accessibility}`** in `content/references/skeptic-protocol.md`. The existing Critical rule is NOT modified - motion does not need to be added to the allowlist because constraint above blocks story_id on motion entirely.

## Non-goals

- `story_id` on `motion` scenarios (deferred to a future Brief that explicitly asks the operator to supersede P1's allowlist).
- Auto-detection of `motion_aware: true` from CSS files (operator-declared, mirrors `theme_aware` precedent).
- Auto-detection of `motion_aware` (operator-declared).
- SB6 selectedKind/selectedStory name convention overrides via qa.md (covered by the existing `story-url` knowledge tag override; no new tag needed).
- Cross-browser CDP support (CDP is Chromium-only by definition; this is an inherited limitation, not a new one).
- Auto-installing Playwright browser binary (not on the safe auto-install allowlist per P0; operator runs `playwright install chromium`).

## Approach

Five units, sequenced with file-level pre-deconfliction.

**Unit 1 - schema foundation** (`content/references/planning-artifacts.md`, `content/agents/architect.md`):
- Add `motion` to the `method` enum prose
- Add `motion` scenario YAML example with `route`, `elements`, `evidence` fields
- Extend per-method compatibility table: motion row with `route` and `elements` required, `theme` and per-scenario `viewport` optional, `story_id` NOT valid
- **UPDATE the enumeration prose sentence in planning-artifacts.md** that currently reads "`visual_conformance` and `accessibility` scenarios accept two additional optional fields: `theme` and `story_id`. Setting either field on any other method ... is invalid and Skeptic raises Critical." Split this into TWO sentences: (a) "`theme` is valid on `visual_conformance`, `accessibility`, and `motion` scenarios. Setting `theme` on any other method is invalid and Skeptic raises Critical." (b) "`story_id` is valid on `visual_conformance` and `accessibility` scenarios only (P1 binding). Setting `story_id` on any other method - including `motion` - is invalid and Skeptic raises Critical." Without this prose update, the file will contain an active contradiction between the per-method table (allows `theme` on motion) and the enumeration sentence (forbids it). U3's skeptic-protocol.md update mirrors decision (a) for `theme`; the planning-artifacts.md prose must match.
- Mirror the same split in `content/agents/architect.md` if its prose mirrors the planning-artifacts.md enumeration sentence (verify by reading the file; if mirrored, update identically).
- Document `motion_aware`, `storybook_version` config keys
- architect.md auto-rule: `motion_aware: true` AND UI-visible Elevated AND `qa_skip == null` AND no motion scenario → Major
- Story_id allowlist stays unchanged; explicitly note "motion does not compose with story_id at P2"

**Unit 2 - qa-engineer procedures** (`content/agents/qa-engineer.md` ONLY):
- New `## Motion scenarios` section AFTER `## Storybook scenarios`. Procedure: read `route` and `elements`; launch Playwright; set viewport per existing viewport-iteration loop; for each (scenario × viewport × theme) tuple: navigate to `route`, call CDP `Emulation.setEmulatedMedia` with `features: [{name: 'prefers-reduced-motion', value: 'reduce'}]`, for each target element (per-selector list OR auto-scan per binding property set), capture computed styles, classify per binding rules; PASS when all motion is disabled/guarded; FAIL with element list and offending styles; INCONCLUSIVE when only SVG/SMIL or vendor-prefixed properties detected.
- Add `motion` knowledge tag: format `motion: /route [selector,selector,...]` or `motion: /route auto`. Operator-declared route + element list overrides scenario `route`/`elements` when present.
- Add motion to evidence JSON shape with `route`, `elements_scanned`, `motion_present_elements` fields plus existing per-tuple `theme`, `viewport`.
- Update `capabilities:` block: add `playwright-python` to `required` array with `required_when: "scenario.method == 'motion'"`, install_hint per P0 spec (NOT auto_install).
- Add SB6 URL branching within the existing `## Storybook scenarios` section: read `.agentic/config.json` `storybook_version`; if `6`, apply SB6 conversion algorithm with explicit FAIL on missing `--`, INCONCLUSIVE on non-200; if absent or `7`, keep current `?id=` format.

**Unit 3 - Skeptic enforcement** (`content/references/skeptic-protocol.md`):
- Add `### motion enforcement (auto-Major)` subsection AFTER the existing `### FE-discipline findings` subsection (matches P1 pattern of new enforcement at end of P0/P1 chain).
- Trigger: `motion_aware: true` AND UI-visible Elevated AND `qa_skip == null` AND no motion scenario present → Major.
- Citation requirement: finding must cite the relevant `content/references/frontend-discipline.md` §5 (Reduced motion) section.
- DO NOT modify the existing `### story_id enforcement` block - allowlist stays `{visual_conformance, accessibility}`. Add a one-line note: "P2 motion scenarios do not support story_id; see planning-artifacts.md per-method table."
- **UPDATE the existing `### theme enforcement` block to add `motion` to the allowlist.** The current rule reads "When `theme` is present on any scenario whose method is NOT `visual_conformance` or `accessibility` ... Skeptic raises Critical." Update the allowlist to `{visual_conformance, accessibility, motion}`. Rationale: the Brief Success criteria explicitly promises per-(scenario × viewport × theme) rows for motion scenarios; without this allowlist update, every theme-bearing motion scenario auto-fires Critical and the success criterion is unreachable. **Authorization for this expansion lives in the architect plan API/interface design section** (`docs/planning/p2-architect-plan.md` lines 56-68), which explicitly states `theme` is valid on `motion`. The Brief incorporates that upstream decision; it is not the originating authorization.

**Unit 4 - config + init + conventions** (`content/commands/init-project.md`, `content/rules/conventions.md`, `content/sections/04-risk-classification.md`, `content/references/capability-preflight.md`):
- init-project: seed `motion_aware: false`, `storybook_version: 7` (default), `capability_preflight_mode: "blocking"`. Update SB version detection: SB6 branch writes `storybook_version: 6` + `storybook_url: "http://localhost:6006"`; SB7+ branch writes `storybook_version: 7` (explicit) + `storybook_url`.
- conventions.md: count "Eight toggles" → "Ten toggles"; add `motion_aware`, `storybook_version`; update `capability_preflight_mode` default note to `blocking`.
- 04-risk-classification.md: same count update; mirror toggle entries.
- capability-preflight.md: update mode-resolution note - default is now `blocking` as of P2 because all agent manifests are populated; remove "advisory until manifests populated" rationale.

**Unit 5 - agent capability blocks** (all 9 agent files with empty stubs):
- Populate per the binding table below. Each agent file edits its own frontmatter `capabilities:` block only. No prose edits.

### Agent capability table (binding)

This table reconciles the architect plan's API/interface table with two operator decisions documented inline below. Deviations from the plan are flagged explicitly.

| Agent | `required:` | `optional:` |
|---|---|---|
| `architect` | (none - read-only) | `context7` (check: `test -f .claude/settings.json && grep -q 'context7' .claude/settings.json`, install_hint: "configure Context7 MCP server in .claude/settings.json") |
| `engineer` | `node` (check: `command -v node`, unconditional), `git` (check: `command -v git`, unconditional) | `context7` (same as architect) |
| `investigator` | (none) | `context7` |
| `debugger` | `node` (check: `command -v node`, `required_when: "brief.has_field('stack_trace')"`), `git` (unconditional) | `context7` |
| `skeptic` | (none) | (none) |
| `security-auditor` | `git` (unconditional) | `semgrep` (check: `command -v semgrep`, install_hint: "pip install semgrep") |
| `dependency-auditor` | `git` (unconditional), `node` (check: `command -v node`, `required_when: "brief.has_field('package_json')"`), `npm` (check: `command -v npm`, `required_when: "brief.has_field('package_json')"`) | `pip` (check: `command -v pip`), `cargo` (check: `command -v cargo`) |
| `release-orchestrator` | `git` (unconditional), `gh` (check: `command -v gh`, install_hint: "brew install gh") | (none) |
| `perf-analyst` | (none) | `lighthouse` (check: `command -v lighthouse`, install_hint: "npm install -g lighthouse"), `k6` (check: `command -v k6`, install_hint: "see k6 install docs at https://k6.io/docs/get-started/installation/") |
| `orchestration-planner` | (none) | (none) |

**Decision notes (reconciled with architect plan):**
- `debugger.required.node` uses the architect plan's `required_when: brief.has_field('stack_trace')` form. A Debugger task without a stack trace does not need Node; with one, it does.
- `dependency-auditor.required.node` and `.npm` use the architect plan's `required_when: brief.has_field('package_json')` form. Cross-ecosystem tasks (Python/Rust) don't need Node/npm; Node-ecosystem tasks do.
- `dependency-auditor.required.git` is added as unconditional (NOT in architect plan). Rationale: dependency-auditor uses git for lockfile history analysis on every task regardless of ecosystem; making it unconditional matches the operator decision pattern for release-orchestrator and engineer.
- `pip` and `cargo` stay `optional` (not required-when) because a `package_json` brief field does not imply a multi-ecosystem audit; explicit Python/Rust audits would carry their own `brief.has_field` predicates if they existed, which they don't at this Brief tier.

**File ownership (no overlap):**
- U1 owns: planning-artifacts.md, architect.md
- U2 owns: qa-engineer.md ONLY
- U3 owns: skeptic-protocol.md ONLY
- U4 owns: init-project.md, conventions.md, 04-risk-classification.md, capability-preflight.md
- U5 owns: 9 agent files (architect.md, engineer.md, investigator.md, debugger.md, skeptic.md, security-auditor.md, dependency-auditor.md, release-orchestrator.md, perf-analyst.md, orchestration-planner.md)

**U1/U5 file conflict on architect.md:** U1 owns the schema/auto-rule edits in architect.md (prose + YAML examples). U5 owns the `capabilities:` block in architect.md (frontmatter only). Different file regions, no textual overlap. U5 must branch AFTER U1 PR merges to avoid any race.

## QA criteria

```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: All P2 changes are documentation-only edits to content/ schema specs and agent specs in the methodology repo. Verification surface lives in downstream consumer projects.
  scenarios: []
  manual_smoke: none
```

## Verification gate

1. **Motion smoke (post-merge follow-up; tracked separately, NOT a P2 deliverable):** synthetic Brief at `docs/planning/p2-motion-smoke.md` targets a Helios UI ticket exercising `method: motion` with both explicit selector list and `auto` modes. Expected: per-(scenario × viewport × theme) rows, FAIL output naming an element with `animation-name: pulse` not wrapped in reduced-motion media query. **This item validates the implementation in a downstream project; P2 itself ships the methodology pieces only. Gate items #2-#7 are the actual pre-merge verification.**
2. **Motion missing trigger:** Brief authored with `motion_aware: true` AND UI-visible Elevated AND no motion scenario; Skeptic-on-Brief raises Major citing the new enforcement rule.
3. **SB6 conversion:** unit test the conversion algorithm with three inputs: `components-button--primary` (single-word), `forms-text-input--with-icon` (multi-word kind), `button` (missing `--` → expected FAIL).
4. **SB6 detection:** init-project against a fixture with `@storybook/react@6.5.0`; confirm `storybook_version: 6` + `storybook_url` written, `storybook_enabled: false` preserved.
5. **Blocking mode flip:** new init-project run produces `capability_preflight_mode: blocking`; existing fixture with `advisory` confirmed unchanged.
6. **Capability gate:** spawn engineer with `node` deliberately uninstalled; conductor surfaces missing-required-dep block message.
7. **Adapter sync:** all 10 build scripts succeed; CI `check-adapter-sync` green.

## Open questions

None. All Skeptic-flagged decisions are committed in Constraints:

- `story_id` does NOT compose with `motion` at P2 (P1 allowlist preserved; expansion deferred to a future explicit Brief).
- `motion` IS a new method enum value, not a field modifier.
- Playwright is `required_when: motion` for qa-engineer.
- SB6 invalid story_id is hard FAIL, not INCONCLUSIVE.
- `motion_aware` is operator-declared (not auto-detected).
- SB6 detection writes `storybook_url`.
- `context7` capability check is MCP-config grep, not CLI presence.
- `auto` motion scan property set is explicit: `animation-name`, `animation-duration`, `transition-property`, `transition-duration`. SVG SMIL and vendor-prefixed properties explicitly excluded.

## Decomposition hint

Five units total. Critical path: U1 → U2/U3/U4/U5 (all parallel after U1 merge) → CI gate.

- **U1: schema foundation** - sequential foundation.
- **U2: qa-engineer procedures** - depends on U1.
- **U3: Skeptic enforcement** - depends on U1; parallel with U2.
- **U4: config + init + conventions + capability-preflight doc** - depends on U1; parallel with U2/U3.
- **U5: 9 agent capability blocks** - depends on U1 (because U5 also touches architect.md frontmatter and U1 owns architect.md prose; must branch from post-U1-merge main). Parallel with U2/U3/U4.
- **Adapter rebuild** - pre-commit hook handles per commit; final CI gate.
