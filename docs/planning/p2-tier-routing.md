# P2 Cost-Aware Tier Routing - Design Plan

> Note: References to "agent-methodology.md" in this historical doc refer to what is now METHODOLOGY.md (assembled from content/sections/). See content/sections/README.md.

## Problem statement

12 out of 13 agents in this repo hardcode `model: claude-sonnet-4-6` in frontmatter; one (`adr-drift-detector`) hardcodes `model: claude-sonnet-4-5`. The mixed state demonstrates that model staleness is already a live problem. The Codex adapter intentionally omits the model field so agents inherit the session model. This means every subagent - from a trivial investigator read to a high-stakes security audit - runs at identical cost. Smart routing picks Haiku for cheap steps and Opus for hard ones, cutting spend 30-50%. We lack any equivalent.

The naive fix is to hardcode `model: claude-opus-4-6` into the architect and skeptic frontmatter. That approach fails on three counts:

1. **Model names go stale.** Claude model IDs change with each release (the agent files already have two Sonnet variants in circulation: `claude-sonnet-4-6` and `claude-sonnet-4-5`, demonstrating staleness is already happening). Baking model IDs into 13 agent files means 13 update points per provider, per release cycle.
2. **Same agent, different needs.** An investigator running a shallow "does this file exist?" check needs Tier 1. An investigator doing full blast-radius analysis on a security-critical change needs Tier 3. The right tier depends on the task, not just the agent type.
3. **Provider-agnostic design.** The repo already ships Claude, Cursor, and Codex adapters, with a Gemini adapter in P0. Hardcoding `claude-opus-4-6` in agent files works only for the Claude adapter - every other adapter ignores the `model` field anyway.

The design goal: conductors declare tier (1/2/3) at spawn time based on task context. For Claude Code, the `Agent` tool accepts a `model` parameter at spawn time that overrides any agent definition frontmatter. The conductor passes the model param directly. No build-time injection required.

---

## Design principles

**Tier abstraction, not model names.** Agent definitions and conductor declarations use abstract tier numbers (1, 2, 3). Model IDs are a deployment concern, not a methodology concern.

**Conductor picks tier at spawn time.** The conductor's tier declaration (e.g., `Tier: 3`) overrides any default. This is the primary tier mechanism. An agent spawned for two different tasks may legitimately run at different tiers.

**No tier in agent frontmatter.** The `model:` field in agent frontmatter is removed. For Claude Code, the conductor passes `model:` as a spawn-time parameter to the `Agent` tool. For Codex/Gemini, the conductor passes the resolved model name as a `--model` CLI flag. Provider tier maps (Codex/Gemini only) translate tier numbers to model names at spawn time.

**Tier 2 is the default.** When the conductor does not declare a tier, no model override is passed and the agent inherits the session model (Sonnet-equivalent for Claude Code). This matches current behavior exactly - no regression.

**Provider selection is install-time.** The user picks their provider (Claude, Codex, Gemini) at install time. The tier routing system operates within the selected provider.

---

## Scope

**In scope:**
- Conductor tier declaration protocol
- Spawn-time model resolution for Claude Code (built-in enum: `haiku`/`sonnet`/`opus`)
- Provider tier map format for Codex and Gemini (tier number to model name)
- Tier guidance per agent role and task context (advisory, not enforced)
- Migration path from current `model:` frontmatter (13-file frontmatter-only change)
- Changes to methodology files

**Out of scope:**
- Multi-provider pool routing (P1 - parallel fan-out with per-worker provider assignment)
- Rate limit handling across tiers
- Cost tracking or spend reporting
- Benchmark harness to measure tier-quality tradeoffs (P1 separate track)
- Automatic tier inference (conductor always declares explicitly; no auto-detection)

---

## Core mechanism

### Claude Code

The Claude Code `Agent` tool accepts a `model` parameter at spawn time with a fixed enum: `haiku`, `sonnet`, `opus`. This overrides any frontmatter `model:` field in the agent definition. The conductor maps tiers to this enum:

| Tier | Claude Code `model` param |
|---|---|
| 1 | `haiku` |
| 2 | omit (inherits session model - Sonnet) |
| 3 | `opus` |

For Tier 2, the conductor omits the `model` param entirely. The agent runs at the session model, which is Sonnet-equivalent. No tier-map lookup needed. No build step needed.

This is a spawn-time decision, not a compile-time default. The same agent definition can run at Tier 1, 2, or 3 in different spawns within the same session.

### Codex and Gemini

The Codex and Gemini CLIs accept a `--model` flag at invocation time. If a tier map exists (`.agentic/tier-map.yml` project-local or `~/.agentic/tier-map.yml` user-global), the conductor resolves the tier number to a model name and passes `--model <name>` in the spawn invocation. If neither file exists, the conductor omits the `--model` flag entirely and the CLI uses its session default - there is no hardcoded fallback. See "Tier map missing at spawn time" below.

### Summary by adapter

| Adapter | Resolution point | How |
|---|---|---|
| Claude Code | Spawn time | `model` param on `Agent` tool call (`haiku`/`sonnet`/`opus` enum) |
| Codex | Spawn time | `--model` flag on `codex` CLI invocation with name from tier-map.yml if present; flag omitted (CLI session default) if no tier-map exists |
| Gemini | Spawn time | `--model` flag on `gemini` CLI invocation with name from tier-map.yml if present; flag omitted (CLI session default) if no tier-map exists |

---

## Provider tier map (Codex and Gemini only)

Claude Code uses a built-in enum for model selection - no tier-map lookup is needed. The tier-map file exists only for Codex and Gemini, where the conductor needs to resolve a tier number to a provider-specific model name string.

### Format

```yaml
# ~/.agentic/tier-map.yml
# Provider tier maps for cost-aware routing - Codex and Gemini only.
# Tier 1 = cheap/fast, Tier 2 = balanced, Tier 3 = max capability.
# Claude Code uses a built-in enum (haiku/sonnet/opus); this file is not consulted for Claude.

codex:
  tiers:
    1: gpt-4o-mini
    2: gpt-4o
    3: o3

gemini:
  tiers:
    1: gemini-2.0-flash
    2: gemini-2.0-pro
    3: gemini-ultra-2
```

### Location and lookup order

The harness resolves the tier map with the following precedence (first found wins):

1. `.agentic/tier-map.yml` in the project root (project-specific overrides)
2. `~/.agentic/tier-map.yml` (user-global config, authored by the user)

If neither file exists, the conductor MUST NOT pass `--model` to the Codex/Gemini CLI. The CLI uses its own session default (provider-controlled). There are no hardcoded model-name fallbacks anywhere in the repo or adapters.

The project-level file is not committed to this repo (add `.agentic/` to `.gitignore` to prevent accidental model-name commitment).

### Where it lives

`~/.agentic/tier-map.yml` is authored by the user when they want tier routing for Codex or Gemini. The adapter install scripts (`.codex/install.sh`, `.gemini/install.sh`) do NOT write this file and do NOT create `~/.agentic/` - tier routing is fully opt-in. The Claude adapter is unaffected regardless: Claude Code uses the built-in `haiku`/`sonnet`/`opus` enum, not a tier map.

The `content/references/tier-map-example.yml` file is an illustrative example users copy and edit themselves. It is not consulted at runtime and is not installed anywhere. Model names in the example are illustrative only and not kept current - users must edit them to match their provider's current catalog.

### Update process

To update a Codex model version:

```yaml
# Edit ~/.agentic/tier-map.yml
codex:
  tiers:
    2: gpt-5  # was gpt-4o
```

No agent files change. No rebuild required. The new model takes effect on the next spawn.

---

## Conductor tier declaration protocol

### Declaration format

The conductor declares tier in the same block as Risk, immediately below the risk line:

```
Risk: Elevated - security adversarial brief
Tier: 3  (max capability - security audit needs Opus)
Spawning security-auditor.
```

```
Risk: Elevated - codebase exploration
Tier: 1  (shallow file existence check - Haiku sufficient)
Spawning investigator.
```

When no tier is declared, no model override is passed and the agent inherits the session model (Tier 2 behavior). The conductor MUST NOT declare a tier for Trivial-risk direct actions (no subagent is spawned, the conductor acts directly using the session model).

### When to declare a tier

Tier declaration is optional but required for non-default selections. The mental model:

- **Tier 1** - declare explicitly when the task is clearly shallow: existence checks, simple reads, format-only operations, lightweight synthesis. Only go Tier 1 when confident the output quality floor is not a concern.
- **Tier 2** - the default. No declaration needed. Standard engineer, investigator, skeptic work at normal depth. Most spawns land here.
- **Tier 3** - declare explicitly when the task demands maximum capability: security adversarial review, complex architecture design with novel tradeoffs, full blast-radius analysis across a large unknown codebase, synthesis of contradictory evidence. Tier 3 costs significantly more; justify it in the parenthetical.

### Justification parentheticals

The conductor should include a brief justification when declaring a non-default tier:

```
Tier: 1  (known-file read, no synthesis needed)
Tier: 3  (security adversarial brief - planted-defect probing needs max capability)
Tier: 3  (novel architecture in unfamiliar domain - architect needs full context window)
```

The justification is advisory, not enforced. Its value is in making tier choices reviewable.

### Enforcement: declaration is not self-executing

**The tier declaration is not self-executing.** Writing `Tier: 3` in the conductor's status text does not automatically change the model. The conductor must also pass the corresponding `model` param in the `Agent` tool call (`model: "opus"` for Tier 3, `model: "haiku"` for Tier 1). A declaration without the tool call param produces Tier 2 behavior regardless of what is written in the text block. The declaration serves as self-documentation and review evidence; the param is the enforcement mechanism.

### Model param mapping (Claude Code)

When the conductor declares a tier, the corresponding `Agent` tool call includes:

- Tier 1: `model: "haiku"`
- Tier 2: omit `model` param
- Tier 3: `model: "opus"`

---

## Tier guidance by agent role and task context

This section is advisory for conductors. It documents which tier is appropriate for which agent type under which conditions. It is not enforced by the harness.

### Default tier assignments

| Agent | Default tier | Rationale |
|---|---|---|
| `engineer` | 2 | Standard implementation; Tier 1 misses edge cases, Tier 3 rarely needed |
| `architect` | 2 | Design work benefits from Sonnet's reasoning; Tier 3 reserved for novel domains |
| `skeptic` | 2 | Adversarial review requires quality; Tier 3 for security or high-stakes audits |
| `investigator` | 1 | Most investigation is file reading; Tier 2 when mapping complex blast radius |
| `debugger` | 2 | Root cause analysis requires reasoning; Tier 1 for obvious/isolated bugs |
| `qa-engineer` | 1 | UI verification is mechanical; rarely needs more |
| `security-auditor` | 3 | Security analysis is the canonical Tier 3 use case |
| `orchestration-planner` | 1 | DAG planning is structured; Sonnet-quality rarely needed |
| `adr-generator` | 2 | ADR quality matters; Tier 1 output tends to be shallow |
| `adr-drift-detector` | 1 | Pattern matching on known ADRs; no synthesis needed |
| `perf-analyst` | 2 | Profiling interpretation requires reasoning |
| `release-orchestrator` | 2 | Decision sequencing needs reliability; not a reasoning-heavy task |
| `dependency-auditor` | 1 | CVE matching and license lookup; mechanical work |

### Conductor upgrade cases (declare Tier 3)

- `architect` on a novel architecture with no existing patterns in the codebase
- `architect` on a decision with significant irreversible consequences
- `skeptic` on a security adversarial brief (planted-defect probing, auth surface review)
- `skeptic` on a Critical finding round-trip when initial review may have been incomplete
- `investigator` on full blast-radius analysis of a change touching 10+ unknown files
- `engineer` when the implementation involves novel algorithm design (rare)

### Conductor downgrade cases (declare Tier 1)

- `investigator` for existence checks, simple file reads, format validation
- `investigator` when the conductor already has partial context and only needs a specific fact
- `debugger` for a stack trace with an obvious call site (no reasoning chain needed)
- `orchestration-planner` for small, clearly-structured tasks where the plan is mechanical
- `engineer` for a purely mechanical transformation (rename, format, add boilerplate) when the conductor is confident scope is bounded

### What does NOT justify Tier 3

- "The task is important" (importance != reasoning difficulty)
- "I want the best output" (Tier 2 is already high quality; Tier 3 is for cases where Tier 2 genuinely falls short)
- Routine Skeptic review of standard engineer output
- Any task where Tier 2 has never failed before

---

## Interaction with P0 Gemini adapter and P1 multi-provider pools

### P0 - Gemini adapter

The Gemini adapter design in `docs/planning/p0-gemini-adapter.md` does not address model selection within Gemini. P2 does not change this: `.gemini/install.sh` does not write to `~/.agentic/tier-map.yml`. Users who want tier routing for Gemini spawns author the file themselves with a `gemini:` section. If no tier map exists at spawn time, the Gemini CLI uses its session default. The Gemini adapter's `install.sh` design is unaffected.

### P1 - multi-provider worker pools

P1 assigns workers to providers (e.g., "spawn 3 engineers: 1 Claude, 1 Codex, 1 Gemini"). P2's tier system is per-provider: each provider has its own tier 1/2/3 resolution. When P1 assigns a worker to a provider, the tier resolution for that provider is used.

The conductor's tier declaration in P1 context means: "spawn this agent at Tier N, using whatever provider it lands on." The harness resolves provider from the pool assignment, then tier from the declaration, then model from the enum (Claude) or tier map (Codex/Gemini).

No design conflict. P2 tier resolution is a subordinate lookup that operates after P1's provider assignment.

**Coordination surface:** The `.agentic/tier-map.yml` file introduced by P2 (authored by the user, not created by install scripts) is the natural location for P1 to store provider pool configuration. The nested `tiers:` format accommodates this - P1 can add a `pool:` key alongside `tiers:` without breaking the P2 tier lookup:

```yaml
codex:
  tiers:
    1: gpt-4o-mini
    2: gpt-4o
    3: o3
  # pool:  # added by P1
  #   max_workers: 3
```

---

## Migration

### Current state

12 of 13 agent files in `content/agents/` have `model: claude-sonnet-4-6` in frontmatter; `adr-drift-detector.md` has `model: claude-sonnet-4-5`. Since the conductor now passes `model:` as a spawn-time `Agent` tool parameter, the frontmatter field is unused and should be removed. This is a 13-file change touching only frontmatter.

The `.claude/agents/` directory symlink remains as-is. `build.sh` does not change. The pre-commit hook does not change.

### Migration steps

**Step 1: Remove `model:` from `content/agents/*.md`**

Remove the `model:` line from all 13 source files in `content/agents/`. This is a frontmatter-only change. The Codex TOML generation already strips the model field; this step has no effect on Codex output. Claude Code will use the spawn-time `model` param going forward; the frontmatter field is no longer needed.

**Step 2: Update methodology to document tier declaration syntax**

Add a "Tier declaration" subsection to `content/rules/agent-methodology.md` under the "Delegation" section. Document the declaration format, the model param mapping (haiku/sonnet/opus), the default tier, upgrade and downgrade cases, and the justification parenthetical convention. This is the primary conductor-facing documentation.

**Step 3: Add tier-map example for Codex/Gemini**

Add `content/references/tier-map-example.yml` as a documentation-only example covering the Codex and Gemini sections. Do not include a `claude:` section - Claude Code uses the built-in enum.

**Step 4: Install scripts do not write tier-map**

`.codex/install.sh` and `.gemini/install.sh` do not write to `~/.agentic/tier-map.yml` and do not create `~/.agentic/`. Tier routing is opt-in: users who want it author the file themselves, using `content/references/tier-map-example.yml` as a starting template. This keeps zero hardcoded model IDs in the repo or the install output - the exact point of P2.

### What does NOT need to change

- `.claude/build.sh` - no model injection logic needed
- `.claude/install.sh` - no tier-map writes needed
- `.claude/agents/` directory symlink - stays as-is
- `hooks/pre-commit` - no changes needed

### Rollback path

If spawn-time model override produces unexpected behavior, the rollback is:

1. Restore `model: claude-sonnet-4-6` to all 13 `content/agents/*.md` files
2. Stop passing `model` param in conductor spawns

No build artifacts to revert. No symlink conversions to undo. The rollback is a pure frontmatter restore.

---

## Edge cases and failure modes

### Tier map missing at spawn time (Codex/Gemini)

If neither `.agentic/tier-map.yml` (project) nor `~/.agentic/tier-map.yml` (user) exists when a Codex/Gemini spawn occurs, the conductor omits the `--model` flag entirely. The CLI uses its own session default, which is Tier-2-equivalent for most provider defaults. Spawns are never blocked by a missing tier map; they degrade cleanly to the session model. There is no hardcoded fallback list - the repo intentionally contains zero model-name defaults so provider releases do not require repo edits.

### Unknown tier declared

If the conductor declares `Tier: 4` (or any tier not defined), the harness logs a warning and falls back to Tier 2. The warning should be visible in the spawn output.

### Provider mismatch

If the user is running the Codex adapter but the tier map only has a `claude:` section (which it should not, since Claude does not use the tier map), resolution falls back to session-model default. Codex inherits the session model when no `--model` flag is passed. No error; behavior matches current behavior.

### Tier map drift between machines (Codex/Gemini)

If a developer updates `~/.agentic/tier-map.yml` on one machine but not another, the same Codex/Gemini agent spawn may resolve to different models. This is expected - the tier map is machine-local to allow per-install customization. For team consistency, commit a project-level `.agentic/tier-map.yml` and remove `.agentic/` from `.gitignore` for that project.

### Codex/Gemini model flag not supported

If a Codex or Gemini CLI version does not support `--model` flag for subagent spawns, tier routing silently falls back to the session model. The session model is Tier 2-equivalent in most cases.

---

## Changes required

### New files

- `content/references/tier-map-example.yml` - documentation-only example (Codex/Gemini sections only; no `claude:` section)
- `.agentic/` entry in `.gitignore` (prevents project-level tier-map from being committed)

### Modified files

**`content/agents/*.md` (all 13 files)**
- Remove `model:` line from frontmatter

**`content/rules/agent-methodology.md`**
- Add "Tier declaration" subsection under "Delegation" documenting declaration format, model param mapping (haiku/sonnet/opus for Claude Code), default tier, upgrade/downgrade cases, and justification parenthetical convention
- The "Tier declaration" subsection must include the enforcement note: the tier declaration is documentation; the model param in the Agent tool call is enforcement. Both are required for non-default tiers.

**`content/commands/implement-ticket.md`** - UPDATE REQUIRED (minor)
- Add a note in the spawn block for each agent-spawn phase (Phase 3 architect, Phase 5 engineer, Phase 6 skeptic) directing the conductor to the tier declaration protocol in `agent-methodology.md`. The note should say: "Declare a tier if this spawn warrants non-default model selection (see Tier declaration in agent-methodology.md). Default is Tier 2 (omit the model param)."

**`content/references/subagent-protocol.md`** - UPDATE REQUIRED
- Section 10 (Input Contract) and Rule 3 (Spawn threshold) describe spawn invocation contents. Add a note to Section 10: "For non-Tier-2 spawns, the conductor also passes a `model` param in the Agent tool call (`haiku` for Tier 1, `opus` for Tier 3). This param is omitted for Tier 2 (default). Codex/Gemini: if a tier-map file exists (`.agentic/tier-map.yml` project-local or `~/.agentic/tier-map.yml` user-global), pass `--model <resolved-name>` from it; if no tier-map exists, omit `--model` and the CLI uses its session default (there is no hardcoded fallback). The model param is an implementation detail of the spawn call, not part of the spawn prompt text."

**`.codex/install.sh`**
- Does NOT write `~/.agentic/tier-map.yml` and does NOT create `~/.agentic/`. Tier routing is opt-in: users author the file themselves when they want it. No tier-map logic in install.
- Optionally: add a comment to the TOML agent template documenting why model is omitted (spawn-time resolution via `--model` flag)

**`.gemini/install.sh`**
- Does NOT write `~/.agentic/tier-map.yml` and does NOT create `~/.agentic/`. Same rationale as `.codex/install.sh`: zero hardcoded model names anywhere in the repo or its install artifacts. Users who want tier routing author `~/.agentic/tier-map.yml` themselves, using `content/references/tier-map-example.yml` as an illustrative reference.

### Docs and slides

- **`docs/agentic-engineering.html`** - UPDATE REQUIRED. Add cost-aware tier routing as a capability. The hub page should note that conductors can declare tier (1/2/3) at spawn time to route lightweight tasks to faster models and critical reviews to max-capability models.
- **`docs/slides/how-it-works-slides.md`** - UPDATE REQUIRED. Add tier declaration as a conductor concept in the spawning flow. A brief callout on the relevant slide: conductors declare `Tier: 1/2/3` when spawning; Tier 2 is the default (no change to existing spawns).
- **`docs/slides/agent-team-slides.md`** - UPDATE REQUIRED. Add a default tier column to the agent table (showing each agent's default tier: security-auditor=3, engineer/architect/skeptic=2, investigator/qa-engineer=1, etc.).
- **New deck:** No standalone deck warranted. Tier routing is an incremental enhancement to the existing spawning model, not a new primitive. The how-it-works and agent-team updates are sufficient.

### Files that do NOT change

- `.claude/build.sh` - no model injection needed
- `.claude/install.sh` - no tier-map writes needed
- `.claude/agents/` - stays as directory symlink to `../content/agents/`
- `hooks/pre-commit` - no changes needed
- Any Cursor adapter files

---

## Open questions (resolved 2026-04-16)

**Q3: Investigator default Tier 1.** Decision: accept plan recommendation. Tier 1 default, with explicit documentation that complex blast-radius analysis warrants conductor upgrade to Tier 2 or Tier 3. Rationale: minimizes cost for the common case (shallow reads); conductor always has the option to declare a higher tier when depth is needed.
