<!--
Purpose: Full reference for the spawn-preset protocol extracted from
         content/sections/04-risk-classification.md §Spawn presets.

Public API: Read-only reference. Load when authoring a `Preset:` declaration,
            setting up `~/.agentic/presets.yml`, or invoking the `architect:grill`
            variant.

Upstream deps: content/sections/04-risk-classification.md (parent section;
               Tier declaration format and Risk declaration live there).
               content/references/spawn-presets-example.yml (example library).

Downstream consumers: content/sections/04-risk-classification.md (inline pointer),
                      content/agents/architect.md (architect:grill variant reference),
                      content/commands/ds-init-project.md (presets.yml seeding).

Failure modes: Prose + YAML schema; not auto-executed. Resolution rule 4
               (effective tier = max(preset tier, role default) unless an
               explicit `Tier:` line or `model_profile: budget` downgrades)
               means a stale low preset `tier` is ignored, never honored.

Performance: Standard.
-->

> Parent section: `content/sections/04-risk-classification.md` §Spawn presets (per-spawn capability bundles). Read that section for the Tier and Risk declaration format first.

# Spawn presets - full reference

A **spawn preset** is a named bundle of `(agent, tier, brief_prefix)` declared on a single line at spawn time. Presets pre-package common spawn shapes so the conductor does not repeat boilerplate.

**Declaration format (optional line, immediately below `Tier:`):**
```
Risk: Elevated - new file creation
Tier: 3
Preset: engineer:default
Spawning engineer.
```

The `Preset:` line is OPTIONAL. When absent, the conductor selects agent and tier inline (current behavior). When present, the preset supplies the agent identity, the tier override, and a brief prefix prepended to the spawn brief. The conductor still writes the rest of the brief inline.

**Preset library location:**
- Global: `~/.agentic/presets.yml`
- Project override: `.agentic/presets.yml` (wins on key collision; merged shallowly per top-level key)

**Reference format:** `<agent>:<variant>` (e.g., `engineer:default`, `skeptic:plan-review`, `skeptic:security`).

**Schema (each preset entry):**
- `agent`: string - which named agent to spawn (engineer, skeptic, architect, etc.)
- `tier`: 1 | 2 | 3 - can only raise the spawn's tier above the agent's role default, never lower it
- `brief_prefix`: string - text prepended to the conductor's inline brief; may be empty

The preset schema deliberately excludes `tool_scope` - on Claude, tool scoping is advisory documentation only (not harness-enforced), so embedding it in presets adds no enforcement value. Keep the preset surface minimal.

**Resolution rules:**
1. Conductor reads `.agentic/presets.yml` if it exists; merges over `~/.agentic/presets.yml`. Project keys win on collision.
2. If the referenced `<agent>:<variant>` is undefined, the conductor warns inline (`Preset 'engineer:foo' not found in presets library; falling back to engineer:default.`) and uses `<agent>:default`.
3. If `<agent>:default` is also undefined, the conductor proceeds with no preset (full inline-spec behavior) and notes the absence in the spawn declaration.
4. The `Tier:` line equals max(preset tier, role default from the Role-default tier table in `content/references/risk-config-and-tiers.md`) unless the conductor deliberately downgrades via an explicit `Tier:` line or `model_profile: budget`, and notes that downgrade.

See `content/references/spawn-presets-example.yml` for an example library to copy as a starting point.

**Canonical variant for wide-design-gap work:** `architect:grill` is the opt-in deep-questioning Architect variant. Concrete trigger: the task description is under 200 words and asks an open "how should we..." question, OR the standard `architect:default` first-pass plan returns with 5+ Open Questions. Subjective trigger also valid: novel architecture, high blast-radius decisions, or vague problem framing where Open Questions feels insufficient. Grill mode is a two-phase orchestration (question-dump spawn, then plan-synthesis spawn with accumulated Q&A as input) - see `content/agents/architect.md` Variants for the full flow and the preset entry for the brief.
