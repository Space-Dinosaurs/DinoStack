# P2 Architect Plan: FE/QA additions (motion method, SB6 support, capability blocking-mode flip)

## Approach

Three bounded additions to the P1 FE/QA foundation: (1) a new `motion` scenario method and its auto-rule; (2) SB6 URL format support gated by a new `storybook_version` config key; (3) populating the 9 empty agent capability blocks and flipping `capability_preflight_mode` default to `blocking`. All changes are documentation-only edits under `content/**` mirrored across 10 adapter build scripts.

## Codebase context

- 10 adapter build scripts at `.claude/`, `.cursor/`, `.gemini/`, `.codex/`, `.kimi/`, `.omp/`, `.hermes/`, `.pi/`, `.opencode/`, `.agentic/` each running `scripts/build-methodology.sh` - adapter sync enforced by CI `check-adapter-sync` gate.
- `content/agents/qa-engineer.md` already has populated `capabilities:` block with P1 fields; 9 other agent files have `required: []` / `optional: []` stubs.
- `content/references/planning-artifacts.md` line 67 contains the authoritative qa_criteria schema prose; `content/agents/architect.md` lines 98-204 mirror it as YAML comments.
- `content/references/skeptic-protocol.md` lines 350-370 hold the FE-discipline enforcement subsection.
- `content/rules/conventions.md` line 78 documents `capability_preflight_mode: advisory`; line 81 documents `storybook_enabled`.
- `content/sections/04-risk-classification.md` lines 77, 80 document the same keys.
- `content/commands/init-project.md` lines 693-700 contain the SB version-detection algorithm.
- `content/references/frontend-discipline.md` §5 (lines 130-165) covers reduced-motion.
- `content/references/capability-preflight.md` line 138 states the flip condition: "once every agent under `content/agents/` has a populated manifest."

## Per-consumer impact table

This plan modifies the `method` enum and the `capabilities:` blocks in shared agent specs, which ripple through all 10 adapter build outputs.

| `consumer_file` | `passes_relevant_arg?` | `uses_compensating_pattern?` | `current_behavior` | `new_behavior` |
|---|---|---|---|---|
| `.claude/build.sh` | copies `content/**` verbatim | no | method enum = 6 values, all agent capabilities empty | method enum = 7 values, 9 agents populated, default `blocking` |
| `.cursor/build.sh` | copies `content/**` verbatim | no | same as above | same delta |
| `.gemini/build.sh` | copies `content/**` verbatim | no | same | same |
| `.codex/build.sh` | copies `content/**` verbatim | no | same | same |
| `.kimi/build.sh` | copies `content/**` verbatim | no | same | same |
| `.omp/build.sh` | copies `content/**` verbatim | no | same | same |
| `.hermes/build.sh` | copies `content/**` verbatim | no | same | same |
| `.pi/build.sh` | copies `content/**` verbatim | no | same | same |
| `.opencode/build.sh` | copies `content/**` verbatim | no | same | same |
| `scripts/build-methodology.sh` | assembles canonical output | no | same | same |

## Data model

**New `storybook_version` config key:**
```yaml
storybook_version: 6 | 7  # default 7. Written by init-project when SB6 detected.
```
When `storybook_version: 6`, qa-engineer uses SB6 URL format; when absent or `7`, keeps current `?id=` format.

**New `motion_aware` config key:**
```yaml
motion_aware: false  # default false. When true, Skeptic auto-Major fires when UI-visible
                     # Elevated unit lacks a motion scenario.
```

**`capability_preflight_mode` default change:** `advisory` → `blocking` in init-project seed and all references.

**`method` enum extension:** add `motion` to `browser | api | runtime-required | visual_conformance | accessibility | perceptual_diff`.

## API / interface design

**`motion` scenario YAML shape:**
```yaml
- id: N
  description: "Animated elements disable or reduce motion when prefers-reduced-motion: reduce"
  method: motion
  route: <URL or "story:<story_id>">   # required; which page/story to test
  elements: <CSS selector list> | auto  # required; "auto" = full-page scan
  evidence: <what artifact proves pass>
  # story_id: "components-button--primary"   # valid on motion
  # theme: both                              # valid on motion; runs per-theme
```

`story_id` and `theme` are valid on `motion` (not restricted to `visual_conformance`/`accessibility` as P1 had it). `browser` and `api` remain excluded.

**SB6 URL conversion algorithm:**

Input: SB7 story ID string e.g. `"components-button--primary"`

1. Split on `--`. Left = kind segment; right = story segment.
2. Kind segment: replace `-` with `/`; capitalize each path part (`components-button` → `Components/Button`).
3. Story segment: replace `-` with ` `; capitalize first letter of each word (`with-icon` → `With Icon`).
4. Build URL: `<storybook_url>/iframe.html?selectedKind=<encoded_kind>&selectedStory=<encoded_story>`.

Example: `"components-button--with-icon"` → `selectedKind=Components%2FButton&selectedStory=With%20Icon`

Edge case: if story ID contains no `--`, emit INCONCLUSIVE with "SB6 story ID format requires `kind--story` separator."

**Agent capability blocks (binding):**

| Agent | `required:` | `optional:` |
|---|---|---|
| `architect` | (none - read-only) | `context7` (check: `npx context7 --version 2>/dev/null`, install_hint: `npx context7`) |
| `engineer` | `node` (unconditional), `git` (unconditional) | `context7` |
| `investigator` | (none - read-only) | `context7` |
| `debugger` | `node` (required_when: `brief.has_field('stack_trace')`), `git` (unconditional) | `context7` |
| `skeptic` | (none) | (none) |
| `security-auditor` | `git` (unconditional) | `semgrep` (check: `command -v semgrep`, install_hint: `pip install semgrep`) |
| `dependency-auditor` | `node` (required_when: `brief.has_field('package_json')`), `npm` (same) | `pip`, `cargo` |
| `release-orchestrator` | `git` (unconditional), `gh` (check: `command -v gh`) | (none) |
| `perf-analyst` | (none) | `lighthouse` (check: `command -v lighthouse`, install_hint: `npm install -g lighthouse`), `k6` (check: `command -v k6`, install_hint: see k6 docs) |
| `orchestration-planner` | (none) | (none) |

None use `auto_install: true`.

## Implementation steps

1. `content/references/planning-artifacts.md` - add `motion` to method enum prose; add motion YAML example with `route`, `elements`; extend method compatibility table; document `motion_aware` config key.
2. `content/agents/architect.md` - add `motion` to method enum comment; add auto-rule for motion-required-when-motion_aware-true; add motion YAML block; add story_id+theme validity note for motion.
3. `content/agents/qa-engineer.md` - frontmatter update; motion capability entry; `## Motion scenarios` section (CDP Emulation.setEmulatedMedia, computed-style checks, pass/fail/inconclusive criteria); `motion` knowledge tag; SB6 URL branching.
4. `content/references/skeptic-protocol.md` - `### motion enforcement` subsection.
5. `content/commands/init-project.md` - SB6 detection extension; `motion_aware: false` seed; `capability_preflight_mode: "blocking"` seed.
6. `content/rules/conventions.md` - update mode default; add storybook_version + motion_aware; toggle count 8 → 10.
7. `content/sections/04-risk-classification.md` - mirror conventions changes.
8. `content/references/capability-preflight.md` - update mode-resolution note to blocking-default.
9. Populate all 9 empty-block agent files per the API table above.
10. `content/agents/qa-engineer.md` SB6 branch within Step 3.

**Ordering:**
- Steps 1-2 must land before Steps 3, 4, 5.
- Steps 6-8 parallel with Steps 3-5.
- Step 9 fully parallel with everything.
- Adapter rebuild via pre-commit hook; final CI gate.

## QA criteria

```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: All P2 changes are documentation-only edits to content/ schema specs and agent specs.
  scenarios: []
  manual_smoke: none
```

## Trade-offs and constraints

**Alternatives considered:**
- `motion` as field modifier on `visual_conformance`: rejected - motion is a distinct behavioral check (CDP emulation + computed-style diff), not a rendering pass variation.
- `story_id` remaining restricted to `{visual_conformance, accessibility}`: P1 Brief explicit. P2 expands to add `motion` because motion verification on an isolated Storybook component has no ambiguous baseline semantics.
- Flipping `capability_preflight_mode` without populating manifests first: rejected - P0 commitment is "once every agent has a populated manifest." Steps 1-9 populate; Steps 6-8 document the flip in the same PR batch.
- SB6 detection auto-setting `storybook_enabled: true`: rejected - P1 constraint is explicit opt-in for CI hermeticity.

**Known limitations:**
- `motion` CDP requires Playwright (not agent-browser). `auto` scan may produce false positives on SVG/vendor-prefixed properties - procedure notes INCONCLUSIVE is appropriate.
- SB6 story ID conversion capitalizes each dash-separated segment; may not match project conventions. INCONCLUSIVE fallback when URL returns non-200.
- `capability_preflight_mode: blocking` is breaking default for NEW projects only; existing projects keep their config.
- `perf-analyst` `k6` install_hint points to docs (multi-platform tool).

## Open questions

1. **Expand `story_id` validity globally to include `motion`?** P1 Brief stated story_id restricted to {visual_conformance, accessibility}. Recommended: document the expansion inline.
2. **`motion_aware` auto-detection vs operator-declared.** Should init-project grep CSS for `prefers-reduced-motion` and auto-set? Recommended: operator-declared (matches `theme_aware` precedent).
3. **SB6 detection writing `storybook_url`.** Current plan does NOT write `storybook_url` for SB6. Recommended: write it (same as SB7), saves operator a step.

## Decomposition hint

- **U1 (schema foundation):** planning-artifacts.md + architect.md. Sequential.
- **U2 (qa-engineer procedures):** qa-engineer.md only - motion procedure, SB6 branching, motion tag. Depends on U1.
- **U3 (skeptic enforcement):** skeptic-protocol.md motion subsection. Depends on U1; parallel with U2.
- **U4 (config + init + conventions):** init-project.md, conventions.md, 04-risk-classification.md, capability-preflight.md. Depends on U1; parallel with U2/U3.
- **U5 (agent capability blocks):** all 9 agent files with empty stubs. No content dependency. Fully parallel.
- **U6 (adapter rebuild):** pre-commit hook + final CI gate.

Critical path: U1 → U2, U3, U4 (parallel) → CI. U5 parallel with all.
