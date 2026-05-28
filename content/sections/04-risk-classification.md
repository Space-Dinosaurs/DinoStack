## Risk Classification

Perform a brief risk assessment before starting any task. Any single Elevated signal triggers Worker + fresh independent Skeptic review. Low risk permits direct action with a brief inline self-check. When in doubt, classify as Elevated.

**Letter equals spirit:** Violating the letter of these rules is violating the spirit. "I followed the intent" after skipping a required step is not a defense.

**Context preservation - apply risk to the task, not the tool call.** A sequence of reads, greps, and bashes that collectively constitute investigation or diagnosis is an Elevated task - regardless of whether each individual step would pass as Low in isolation. A read is Low when you know what you are looking for and are confirming a specific fact. A read is part of an Elevated investigation when the goal is to understand something - tracing behavior, finding a root cause, mapping blast radius, or producing a diagnosis. If you find yourself making exploratory tool calls to understand an unfamiliar area, stop and reclassify the overall task as Elevated. Delegation is not just a safety mechanism - it is mandatory context hygiene. A conductor that fills its own context with investigation work cannot orchestrate. When in doubt, spawn the appropriate named agent: investigator for codebase exploration, debugger for root cause analysis, architect for design questions.

| Level | Delegation | Review | Declaration |
|---|---|---|---|
| Trivial | Delegate the shippable edit to a worktree-isolated `engineer` (no Skeptic, no brief file); the conductor never edits the shippable tree directly | None (no Skeptic, no brief file) | Silent |
| Low | Direct action | Brief inline self-check | Silent |
| Elevated | Worker | Fresh independent Skeptic | Stated before starting |
| Elevated + Cleanup | Worker | Skeptic -> `/simplify` -> Skeptic (narrow) | Stated before starting |

### Risk profiles

The methodology supports three risk profiles that shift the boundary between Low and Elevated. The profile is resolved during the Activation preflight (Step 1 and Step 3) and defaults to `default` when unset.

- **`relaxed`** — minimal Skeptic overhead. Use for rapid iteration on well-understood UI or local bug fixes.
- **`default`** — slightly relaxed from legacy behavior. Single-file locally-scoped behavioral edits are Low rather than Elevated.
- **`strict`** — broad Skeptic coverage. Use when correctness is paramount and review bandwidth is acceptable.

#### Profile deltas

The existing signal lists below represent the `default` profile. These deltas apply:

**`relaxed` (additional Low overrides):**
- **Single-file, locally-scoped code edits with behavioral effect** are treated as **Low** instead of Elevated.
  - Definition: touches exactly one file; modifies local behavior (e.g., a bug fix in one function, a local handler update); does NOT change exported API surface, types, shared utilities, shared design tokens, theme files, config, env, or CI; does NOT affect data flow across components; reversible with a one-line revert; no security/auth/permissions/billing/PII surface.
- **Multi-file pure-UI-only changes** are treated as **Low** instead of Elevated.
  - Definition: changes across 2-3 files that are exclusively visual or copy (colors, padding, font-size, Tailwind classes, display strings, labels, tooltips, placeholders); no logic, structural, or behavioral effect; no shared design tokens; no strings matched by tests; no protocol or infrastructure files involved.

**`default` (compared to legacy):**
- **Single-file, locally-scoped code edits with behavioral effect** are treated as **Low** instead of Elevated (same definition as `relaxed` above). All other signals remain at their legacy levels.

**`strict` (removed Low overrides):**
- **UI-only copy changes** are treated as **Elevated**; the Low override is removed.
- **File renaming** is treated as **Elevated**; the Low override is removed.
- **Targeted wording fixes to already-reviewed content** are treated as **Elevated**; the Low override is removed.
- **Diagnostic-only changes** and **documentation-only file creation** remain direct-action eligible but require the conductor's inline self-check (they are treated as Low rather than unconditionally direct).

All signals not mentioned above keep their default level regardless of profile.

### Elevated signals

See §Delegation signal table above for the full Elevated signals list.

### Trivial signals

ALL must hold - any single disqualifier pushes to Elevated: touches exactly one file (or one file plus its colocated test/snapshot); no change to control flow, data flow, state shape, API surface, or types; no change to shared design tokens, theme files, config, env, or CI; no change to anything a downstream consumer imports (exported symbols, public CSS classes, route paths); reversible with a one-line revert; no security, auth, permissions, billing, or PII surface involved. Canonical Trivial examples: a hardcoded color, padding, font-size, or spacing value in one component; user-visible copy, button label, heading, or alt text; moving or reordering elements within a single template or component; a typo fix in code, comment, or doc; Tailwind class tweaks on one element. NOT Trivial even if it feels small: edits to `tailwind.config.*`, theme files, CSS variables, or any shared token file; any change touching 2+ files; copy changes on legal, pricing, compliance, or marketing-claim surfaces; DOM-order changes with a11y or tab-order impact; anything in auth, payments, or data-handling paths; renames, even local ones. When in doubt between Trivial and Elevated, choose Elevated.

**Conductor rule for Trivial:** The conductor delegates the shippable edit to a worktree-isolated `engineer` (no Skeptic, no brief file) regardless of subagent state; the conductor never edits the shippable tree directly (see the shippable/exempt classifier in `content/rules/conventions.md` §Git Workflow). A commit message is still required. If a Worker discovers mid-task that the change is not actually Trivial (e.g., the "one-file color tweak" lives in a shared token file), it must stop, report, and the conductor re-classifies as Elevated.

**Post-debugger Low classification.** Post-debugger-brief bug fixes that are single-file and exercised by an existing test may be classified Low if they meet all Trivial signals; otherwise standard Elevated applies.

### Low signals

Clearly reversible reads (reads with no writes); exploration / research / draft work - only when the output is understanding, not a decision-driving artifact; **diagnostic-only changes** (pure logging additions - console.log, .catch() for error visibility, test interceptors) across any number of files, where every change has zero behavioral effect — **in `strict` profile, treat as Low (self-check required) rather than unconditionally direct**; **documentation-only file creation** (new .md or .txt files that are pure lists, glossaries, or running notes - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/agentic-engineering/; overrides the "new file creation" Elevated signal for this case only) — **in `strict` profile, treat as Low (self-check required) rather than unconditionally direct**; **targeted wording fixes to already-reviewed content** (phrasing adjustments where the substance was already Skeptic-approved in the current or a recent session - e.g., syncing parallel descriptions, adding a clarifying phrase to an existing enumeration; does not apply to new decisions, new recommendations, or new content not previously reviewed; does not override the "modifies protocol or infrastructure files" Elevated signal; overrides the single-file edit and new file Elevated signals for this case only) — **in `strict` profile, this override is removed; treat as Elevated**; **file renaming** (renaming or moving files via `git mv` or equivalent, with no content changes to any file - neither the renamed file nor any other file; overrides the "new file creation", "multi-file changes", and "Bash with side effects" Elevated signals for this case only; does not override the "modifies protocol or infrastructure files" Elevated signal - renaming protocol or infrastructure files remains Elevated regardless; if any other files reference the renamed path - imports, cross-references, config entries - the operation is Elevated because those reference updates constitute content changes in other files; if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the operation is Elevated because the rename changes behavior without changing file contents) — **in `strict` profile, this override is removed; treat as Elevated**; **UI-only copy changes** (rewording display strings, labels, tooltips, or placeholder text where the change has no logic, structural, or behavioral effect - e.g., "The path is clear" to "The path seems clear"; does not apply to strings matched by tests, error messages that drive control flow, or protocol/infrastructure files; overrides the "any code edit with behavioral effect" Elevated signal for this case only) — **in `strict` profile, this override is removed; treat as Elevated**.

### Mid-task reclassification

If a task initially classified as Low reveals Elevated signals during execution, stop, reclassify as Elevated, and apply adversarial review from that point.

### Low risk self-check

After completing a Low-risk change, re-read it in full. Verify intent, edge cases, and side effects. If any concern arises, reclassify as Elevated.

### Project config (`.agentic/config.json`)

The conductor reads `.agentic/config.json` to resolve eight project-level orchestration toggles before classifying and spawning. The file is **committed, not gitignored** (like `qa.md` / `deploy.md`), is seeded with defaults by `/init-project`, and is optional - if absent, every toggle takes its default and behavior is unchanged.

- `debugger_on_failure` - boolean, default `false`. When `true` AND the path is Elevated, `/implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass on a quality-gate failure. A Trivial-path ticket never invokes the Debugger regardless of this toggle (the gate is `debugger_on_failure == true` AND Elevated; both must hold).
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior - canonical definition in `content/references/planning-artifacts.md` §`qa_default_skip (canonical definition)`. This entry is a cross-reference only; conventions.md likewise cross-references and neither redefines it.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. When `budget`, the conductor routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - the conductor still declares explicit `Tier: 3` for those regardless of the project `model_profile`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory | blocking`); default `advisory`. The conductor reads this before every Agent spawn to decide whether missing required capabilities warn-and-proceed (`advisory`) or halt the spawn (`blocking`). Canonical reference: `content/references/capability-preflight.md`.
- `perceptual_diff_enabled` - boolean, default `false`. Opt-in for the `perceptual_diff` QA scenario method; when `true`, qa-engineer runs Playwright `page.screenshot()` + pixelmatch comparison against committed baselines.
- `theme_aware` - boolean, default `false`. Opt-in for per-theme QA tuples; when `true`, qa-engineer runs `visual_conformance` and `accessibility` scenarios in both light and dark themes and reports per-(scenario x viewport x theme) results. The conductor reads this toggle when inspecting `qa_criteria` to determine whether theme enforcement auto-Major rules apply.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer targets the Storybook iframe for isolated component verification. Requires Storybook 7+; init-project sets the related `storybook_url` config key when SB7+ is detected.

Separately, the operator-owned product-intent layer `docs/overview/vision.md` + `docs/overview/requirements.md` sits above task-level Briefs. When present, the Architect treats them as authoritative product intent and the Investigator reads them for framing context; agents read but never write these files. Schema and authoring rules: `content/references/planning-artifacts.md` §Product-intent layer (operator-owned) and `content/rules/conventions.md` §Project Overview Layer.

### Declaration format

```
Risk: Elevated - [specific signal]
Applying adversarial review.
```
```
Risk: Elevated + Cleanup - [specific signal]
Applying adversarial review with /simplify cleanup pass.
```

When a Brief or Plan governs the task (see METHODOLOGY.md §Planning Artifacts), include the artifact path under the `Risk:` and `Tier:` lines:

```
Risk: Elevated - multi-unit feature
Tier: 2
Brief: docs/planning/<slug>.md
Applying adversarial review.
```
```
Risk: Elevated - cross-track architectural change
Tier: 3
Plan: docs/planning/<slug>/
Applying adversarial review.
```

### Tier declaration

Conductors declare the model tier at spawn time to route lightweight tasks to faster models and critical reviews to max-capability models. Tier is declared in the same block as Risk, immediately below the Risk line.

**Declaration format:**
```
Risk: Elevated - security adversarial brief
Tier: 3  (max capability - security audit needs Opus)
Spawning security-auditor.
```

**Default:** Tier 2. When no tier is declared, the agent uses Sonnet. Most spawns are Tier 2 - omit the declaration entirely.

**Model param mapping (Claude Code):**

| Tier | Claude Code `model` param | Use when |
|---|---|---|
| 1 | `model: "haiku"` | Shallow/mechanical tasks: existence checks, simple reads, format-only operations |
| 2 | `"sonnet"` | Standard work - engineer, investigator, skeptic at normal depth |
| 3 | `model: "opus"` | Security audits, novel architecture, complex blast-radius analysis |

**Enforcement:** The tier declaration is not self-executing. Writing `Tier: 3` does not change the model. The conductor must also pass the corresponding `model` param in the Agent tool call. A declaration without the tool call param produces Tier 2 behavior regardless of what is written in the text block. The declaration serves as self-documentation and review evidence; the param is the enforcement mechanism.

**When to declare Tier 1:** task is clearly shallow - existence checks, simple file reads, format validation, lightweight synthesis. Only go Tier 1 when confident the output quality floor is not a concern.

**When to declare Tier 3:** task demands maximum capability - security adversarial review, complex architecture design with novel tradeoffs, full blast-radius analysis across a large unknown codebase. Tier 3 costs significantly more; include a justification parenthetical.

**Codex/Gemini:** If `~/.agentic/tier-map.yml` (or a project-local `.agentic/tier-map.yml`) exists, the conductor resolves tier to a model name from that file and passes `--model <name>` on the CLI invocation. If neither file exists, the conductor omits `--model` entirely and the CLI uses its session default - there is no hardcoded fallback model list anywhere in the repo or adapters. Tier routing for Codex/Gemini is fully opt-in; users author the tier-map file themselves. See `content/references/tier-map-example.yml` for the format.

### Spawn presets (per-spawn capability bundles)

**Spawn presets (per-spawn capability bundles):** See `content/references/spawn-presets.md` for the full protocol - bundle format, library locations (`~/.agentic/presets.yml` global; `.agentic/presets.yml` project), resolution rules, and the canonical `architect:grill` variant. Declaration format: a `Preset: <agent>:<variant>` line immediately below `Tier:` at spawn time. Example library: `content/references/spawn-presets-example.yml`.

For the full tier guidance table (default tiers by agent role, upgrade cases, downgrade cases), see `docs/planning/p2-tier-routing.md`.
