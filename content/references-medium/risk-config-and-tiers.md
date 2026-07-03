<!--
Purpose: Detailed risk-classification reference blocks extracted from
         content/sections/04-risk-classification.md. Contains: the
         medium-relevant project config catalog (behavioral toggles only),
         the Graph-derived risk signal mechanism + freshness + autonomous
         refresh; and the Tier declaration detail including role-default
         tier table (medium agents), model-param mapping, mandatory Tier-3
         escalation (with enforce-tier.py hook note), frontmatter defaults,
         enforcement, and adapter-specific routing (Codex/Gemini,
         Pi/oh-my-pi, cross-harness teams).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/04-risk-classification.md (inline pointers
            replacing each verbose block).

Upstream deps: content/sections/04-risk-classification.md (parent section;
               read that section first for risk levels, profiles, and
               signal table); content/references/planning-artifacts.md
               (canonical qa_default_skip definition).

Downstream consumers: conductor (reads config toggles before classifying
                      and spawning; reads tier table at every Elevated
                      spawn); content/sections/12-protocol-details.md
                      (Risk Classification Protocol Details entry).

Failure modes: Prose reference; does not auto-execute. The project-config
               toggle descriptions here shadow the conventions.md version
               (which covers the same toggles from the conventions angle);
               both must stay in sync with .agentic/config.json defaults.

Performance: Standard.
-->

> Parent section: `content/sections/04-risk-classification.md`. Read that section first for the risk levels, profiles, and the full signal table.

## Config Toggle Catalog (behavioral)

### Project config (`.agentic/config.json`)

The conductor reads `.agentic/config.json` to resolve project-level orchestration toggles before classifying and spawning (one, `qa_default_skip`, is reserved/inert - documented for schema completeness but does not currently alter behavior, and is full-tier-only since it gates the QA path). The file is **committed, not gitignored** (like `qa.md` / `deploy.md`), is seeded with defaults by `/init-project`, and is optional - if absent, every toggle takes its default and behavior is unchanged.

**Medium-active toggles:**

- `debugger_on_failure` - boolean, default `false`. When `true` AND the path is Elevated, `/implement-ticket` Phase 7 interposes a `debugger` diagnosis step before each engineer fix pass on a quality-gate failure. A Trivial-path ticket never invokes the Debugger regardless of this toggle (the gate is `debugger_on_failure == true` AND Elevated; both must hold).
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior - canonical definition in `content/references/planning-artifacts.md` §`qa_default_skip (canonical definition)`. This entry is a cross-reference only; conventions.md likewise cross-references and neither redefines it. **Full-tier-only** in any behavioral sense (medium has no QA gate).
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. When `budget`, the conductor routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to the `skeptic` or any agent whose spec mandates Tier 3 - the conductor still declares explicit `Tier: 3` for those regardless of the project `model_profile`. The same exemption covers any Skeptic the Mandatory Tier-3 review escalation rule has elevated for this unit: `budget` must not pass a downgrading `model` param to it. `budget` acts only through the spawn-call param; it never rewrites an agent's frontmatter `model:`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory | blocking`); default `advisory` in medium (full tier defaults to `blocking`). Controls what happens when the conductor finds a missing required dependency during capability preflight. `advisory` emits a warning with the install command and proceeds with the spawn. `blocking` refuses the spawn when any required dependency remains missing after auto-install. See `content/references/capability-preflight.md` for the full preflight protocol.
- `commit_telemetry` - boolean, default `true`. When `true`, `/implement-ticket` Phase 8 commits the per-developer session-log file (`.agentic/session-log/<developer_id>.jsonl`) as a separate commit on the PR branch, enabling cross-developer team visibility via `agentic-cost team` after pull. Set to `false` to opt out of telemetry commits on this project.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in for the daemon-driven deferred-wrap workflow; medium does not ship `wrap-ticket` so this toggle is dormant. Documented for schema parity with full tier.
- `abdication_guard_enabled` - boolean, default `false`. When `true`, a Stop hook detects conductor abdication - ending a turn by asking permission for a non-destructive next step - and blocks the stop, injecting a "proceed" directive. Mechanizes the Proactive autonomy / default-and-proceed rule in §Delegation. Default `false`; individual projects opt in.
- `skill_candidate_detection` - boolean, default `true`. Master toggle for the skill-candidate detector. When `true`, recurring friction patterns are detected at wrap time and candidates are written to `.agentic/skill-candidates.md`; the conductor emits a session-start notice when new candidates are found. When `false`, the detector exits immediately.
- `skill_candidate_nudge` - boolean, default `false`. Layer-2 opt-in for an in-session nudge the first time a domain crosses the candidate threshold during the current session. Requires `skill_candidate_detection: true`; alone has no effect.
- `ticket_driven` - enum (`off` | `offer` | `require`). Controls whether the conductor creates a tracker ticket before spawning the first implementer on net-new work. **Absent-key resolution:** when absent, effective value is `offer` when `TRACKER != none` and `off` when `TRACKER == none` - explicit value always wins. Cross-ref: `content/commands/implement-ticket-full.md` §Tracker Create Helper.

**Full-tier-only toggles (documented for schema completeness; inert in medium):**

- `perceptual_diff_enabled` - boolean, default `false`. Opt-in for the `perceptual_diff` QA scenario method; consumed by `qa-engineer`. Inert in medium.
- `theme_aware` - boolean, default `false`. Opt-in for per-theme QA tuples; consumed by `qa-engineer`. Inert in medium.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` on visual scenarios; consumed by `qa-engineer`. Inert in medium.
- `motion_aware` - boolean, default `false`. Opt-in for the `motion` scenario method auto-Major Skeptic rule. Inert in medium.
- `storybook_version` - enum (`6 | 7`), default `7`. Storybook URL format selector; consumed by `qa-engineer`. Inert in medium.

These full-tier-only keys are accepted by the medium conductor schema to keep project configs portable across tiers; they are simply never read.

#### Graph-derived risk signal

When a fresh `GRAPH_REPORT.md` exists at the repo root, the conductor uses a Graphify knowledge graph during risk classification to detect high-blast-radius or non-obvious-coupling changes. It is presence-gated and escalate-only: it can raise a classification toward Elevated, never lower one.

**Rationale.** Graphify writes `GRAPH_REPORT.md` at the repo root. Two of its computed sections name the symbols that carry the most architectural weight: God Nodes (highest-degree core abstractions) and Surprising Connections (cross-file couplings the author probably did not know about). A change touching one of those symbols is, by construction, the "Changes to shared utilities (single-file but high blast radius)" or "Logic with emergent/non-obvious cross-component interactions" Elevated signal - this mechanizes that judgment from an artifact the project already maintains.

**Mechanism (when a fresh `GRAPH_REPORT.md` exists at the repo root).** Before classifying, the conductor checks freshness (below). If fresh, it reads `GRAPH_REPORT.md` and tests the change's target symbol(s) for membership, against the graphify v8 report format:

- God Nodes: under the exact heading `## God Nodes (most connected - your core abstractions)`, each entry is `N. ` followed by a backtick-wrapped bare symbol label followed by ` - <degree> edges`. The match set is those bare labels.
- Surprising Connections: under the exact heading `## Surprising Connections (you probably didn't know these)`, each entry's first line is `- ` followed by backtick-wrapped `<source>`, `--<relation>-->`, backtick-wrapped `<target>`, then `  [<tag>]`. The match set is the bare `<source>` and `<target>` labels. The literal line `- None detected - all connections are within the same source files.` means no surprises.

On a match, the conductor treats it as an additional Elevated signal and classifies the change Elevated (or higher if other signals apply). On no match, no effect - classify as today. When the target symbol is not yet known at classification time (for example a vague task before investigation), the signal does not fire; classify as today. The signal never downgrades a classification.

Symbol matching is best-effort and bare-name-based (the report uses bare labels with no path qualification). Ambiguity (overloaded names, the same name in multiple files) is acceptable because the signal is escalate-only: over-firing toward Elevated only spawns a cheap extra Skeptic, while under-firing leaves today's behavior, so over-fire is the correct failure mode.

**Freshness.** The conductor reads freshness from the same file as the signal (`GRAPH_REPORT.md`):

- Primary (graph built in a git repo): under the exact heading `## Graph Freshness`, parse the line `- Built from commit: ` followed by a backtick-wrapped 8-character SHA. The graph is fresh only if that SHA equals the first 8 characters of `git rev-parse HEAD` AND the change's target file(s) have no uncommitted modifications (`git status --porcelain -- <target-paths>` is empty for those paths - a commit match alone misses uncommitted edits).
- Fallback (no `## Graph Freshness` section, i.e. the graph was built outside a git repo): compare `GRAPH_REPORT.md`'s mtime against the newest target-source-file mtime; if any target source is newer, treat as stale. Fail safe to stale on any ambiguity.
- On stale or undetermined: ignore the signal entirely - neither escalate nor downgrade - and classify exactly as today by human judgment.

**Autonomous refresh.** The conductor keeps the graph fresh itself. At the point it is about to use the graph - before its own risk classification and before spawning the investigator - the conductor checks for an existing graph (`graphify-out/graph.json` or `GRAPH_REPORT.md`). If one exists and the staleness check above fails (built-commit not equal to HEAD, or uncommitted changes to the relevant files), the conductor runs `graphify update .` once from the repo root on its own checkout (honoring `GRAPHIFY_OUT` if set), then reads the refreshed report. This runs at most ONCE per session: after the first refresh the conductor treats the graph as fresh for the remainder of the session regardless of how many times staleness is later detected - it does not re-ru…

**Format coupling.** The pinned strings above are the graphify v8 report format. A future graphify heading change fails safe (no heading match means an empty match set and no escalation); if graphify changes the format, these strings need a follow-up sync.

**GRAPHIFY_OUT.** The conductor reads the repo-root `GRAPH_REPORT.md` and, when refreshing, honors `GRAPHIFY_OUT` to locate the graph directory. A report relocated via `GRAPHIFY_OUT` is treated as "no report present" at the repo root - the signal does not fire and behavior is unchanged. Projects wanting the signal keep the report at the repo root.

## Tier Declaration Detail

### Tier declaration

Conductors declare the model tier at spawn time to route lightweight tasks to lower-depth models and critical reviews to maximum-reasoning-depth models. Tier is declared in the same block as Risk, immediately below the Risk line.

**Declaration format:**

```
Risk: Elevated - [specific signal]
Tier: <n> (role default | justification)
Spawning <agent>.
```

**Tier is a required field of the spawn declaration.** Every Elevated spawn carries a `Tier:` line directly below `Risk:`. The conductor either (a) names a tier explicitly with a justification, or (b) writes `Tier: <n> (role default)` to consciously accept the spawned agent's role-default tier from the Role-default tier table below. "Forgetting" to think about tier is no longer available: an Elevated declaration with no `Tier:` line is malformed. In medium, all implementation spawns resolve to Tier 2 by role default; the Skeptic review resolves to Tier 3 by role default.

**Model param mapping (Claude Code):**

| Tier | Claude Code `model` param | Use when                                                                                                                                                |
| ---- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | `model: "haiku"`          | Shallow/mechanical tasks: existence checks, simple reads, format-only operations. In medium, the `investigator` haiku default is the only Tier-1 spawn. |
| 2    | `"sonnet"`                | Standard work - engineer, investigator (when not haiku), debugger, orchestration-planner, architect at normal depth                                     |
| 3    | `model: "opus"`           | Adversarial review and complex blast-radius analysis; the Skeptic defaults to Opus                                                                      |

**Mandatory Tier-3 review escalation.** When a unit is Elevated AND matches any of the following signals, the Skeptic reviewing that unit MUST be Tier 3 (Opus), regardless of the agent's role default or the project `model_profile`:

- security, auth, crypto, payments, or secrets
- irreversible operation: delete, migration, schema change, force push
- novel architecture constraining future choices
- high blast radius / shared-utility change
- release, deploy, or production-state change

This reuses the Elevated risk-signal vocabulary above. The conductor passes `model: opus` explicitly on these Skeptic spawns even though the skeptic frontmatter already defaults to Opus: the explicit param documents the mandate, survives a session whose model was overridden, and guards against an accidental downgrade param. `model_profile: budget` NEVER downgrades a mandated-Tier-3 Skeptic. Note the one case neither frontmatter nor the explicit param can rescue: if the org `availableModels` allowlist excludes opus, the Opus request is silently dropped and the agent inherits the session model - on a mandated-Tier-3 unit the conductor must surface that Opus is unavailable rather than proceed on an inherited model.

**Role-default tier table — medium agents (6):**

| Agent                   | Default tier | Claude `model:` | Rationale                                                                                        |
| ----------------------- | ------------ | --------------- | ------------------------------------------------------------------------------------------------ |
| `skeptic`               | 3            | opus            | Adversarial review quality binds correctness                                                     |
| `architect`             | 2            | sonnet          | Standard design; upgrade to Tier 3 per the escalation rule for novel-architecture units          |
| `engineer`              | 2            | sonnet          | Implementation                                                                                   |
| `investigator`          | 1            | haiku           | Cheap file:line search; promote to sonnet when the user explicitly asks for deep terrain mapping |
| `orchestration-planner` | 2            | sonnet          | Decomposition                                                                                    |
| `debugger`              | 2            | sonnet          | Root-cause analysis                                                                              |

**Full-tier-only agents (12; do not spawn in medium):**

| Agent                      | Default tier | Claude `model:` | Rationale                                               |
| -------------------------- | ------------ | --------------- | ------------------------------------------------------- |
| `security-auditor`         | 3            | opus            | Spec-mandated Tier 3; threat-model depth                |
| `qa-engineer`              | 2            | sonnet          | Runtime verification                                    |
| `dependency-auditor`       | 2            | sonnet          | Dependency review                                       |
| `perf-analyst`             | 2            | sonnet          | Performance analysis                                    |
| `release-orchestrator`     | 2            | sonnet          | Release execution                                       |
| `product-discovery`        | 2            | sonnet          | Requirements synthesis                                  |
| `adr-generator`            | 2            | sonnet          | ADR authoring                                           |
| `adr-drift-detector`       | 2            | sonnet          | Compliance audit                                        |
| `learning-extractor`       | 2            | sonnet          | Pattern extraction                                      |
| `learnings-agent`          | 2            | sonnet          | Discretionary capture                                   |
| `wrap-ticket`              | 2            | sonnet          | Session wrap                                            |
| `goal-condition-evaluator` | 1            | haiku           | Cheap per-turn stop-condition check for open-goal loops |

**Small-unit Tier-2 Skeptic carve-out.** When a unit meets the simple/targeted-unit mechanical metric (`content/sections/04-risk-classification.md` §Simple/targeted unit (mechanical metric)) AND matches none of the 5 Mandatory Tier-3 signal categories above, the conductor MAY declare `Tier: 2 (small-unit nudge)` for the reviewing Skeptic instead of accepting the unconditional Opus role default. The declaration stays visible in the `Tier:` line at spawn time, same as any other tier declaration. This is a loop-cost lever only - it never widens what classifies as Low or Trivial, and the Skeptic still runs.

The 5 Mandatory Tier-3 signal categories are untouched by this carve-out and still force Opus unconditionally, including for the Skeptic reviewing that unit: security/auth/crypto/payments/secrets, irreversible operations, novel architecture constraining future choices, high blast radius / shared-utility change, and release/deploy/production-state change. Do NOT route this carve-out to Tier 1/Haiku - Tier 1 is defined above as existence-checks/format-only and routing a Skeptic review there would gut review depth. The floor for this carve-out is Tier 2, never Tier 1.

**Frontmatter defaults and the model param.** Each agent's frontmatter `model:` encodes its role-default tier. Resolution precedence (Claude Code): `CLAUDE_CODE_SUBAGENT_MODEL` env var > spawn-call `model` param > frontmatter `model:` > inherited session model. Therefore:

- To accept an agent's role default, the conductor OMITS the `model` param; the frontmatter supplies the model (a skeptic spawn with no param runs Opus).
- To OVERRIDE for a specific spawn (upgrade a Tier-2 agent to Tier 3 for a novel-architecture unit, or assert a mandated-Tier-3 Skeptic), the conductor passes an explicit `model` param, which wins.
- Every agent declares an explicit frontmatter `model:` so an omitted param is always correct and a Sonnet-intended agent never silently inherits Opus from an Opus session.
- Budget mode: `model_profile: budget` acts ONLY through the spawn-call param, never by rewriting frontmatter. To get a Tier-1 (haiku) review on a NON-mandated skeptic spawn under budget mode, the conductor passes an explicit downgrade param; omitting the param yields the Opus frontmatter default. Budget mode never downgrades a mandated-Tier-3 Skeptic (see the escalation rule above).
- Org allowlist caveat: if `availableModels` excludes opus, frontmatter `model: opus` is silently dropped and the agent inherits the session model. On a mandated-Tier-3 unit in such an org, the conductor must surface that Opus is unavailable rather than proceed on an inherited model.

**Enforcement:** The tier declaration is not self-executing. Writing `Tier: 3` does not change the model. The conductor must also pass the corresponding `model` param in the Agent tool call. A declaration without the tool call param produces Tier 2 behavior regardless of what is written in the text block. The declaration serves as self-documentation and review evidence; the param is the enforcement mechanism. On Pi/omp with `role-models.yml` present, the conductor records, in-context, the model string it used for each engineer/architect spawn, and passes that author-model into the subsequent Skeptic spawn so a reviewer-diversity strategy can resolve.

**When to declare Tier 1:** task is clearly shallow - existence checks, simple file reads, format validation, lightweight synthesis. Only go Tier 1 when confident the output quality floor is not a concern.

**When to declare Tier 3:** task demands maximum reasoning depth - adversarial review, complex architecture design with novel tradeoffs, full blast-radius analysis across a large unknown codebase. Reserve Tier 3 for these cases and include a justification parenthetical.

**Codex/Gemini:** If `~/.agentic/tier-map.yml` (or a project-local `.agentic/tier-map.yml`) exists, the conductor resolves tier to a model name from that file and passes `--model <name>` on the CLI invocation. If neither file exists, the conductor omits `--model` entirely and the CLI uses its session default - there is no hardcoded fallback model list anywhere in the repo or adapters. Tier routing for Codex/Gemini is fully opt-in; users author the tier-map file themselves. See `content/references/tier-map-example.yml` for the format.

**Pi / oh-my-pi (role-models layer):** On the Pi and oh-my-pi harnesses an additional opt-in layer maps each role - and the adversarial reviewer - to a concrete model. If `~/.agentic/role-models.yml` (or project-local `.agentic/role-models.yml`) exists, the conductor resolves the spawn's `model`, `effort`, and `reasoning` fields from it: `roles[<role>]` for forward roles (scalar string or `{model, effort, reasoning}` mapping; the conductor forwards only the keys that are set), and a reviewer-diversity strategy (`distinct-from-author` / `round-robin` / `by-task`) for `skeptic` spawns so the reviewer runs on a different model than the author. The explicit `roles[<role>]` model wins over the Tier-implied model on collision (operator inten…

**Cross-harness teams (opt-in, independent of role-models; any harness):** This layer is independent of the Pi/omp role-models layer above; it works on any conductor harness (Claude, Codex, Gemini, Kimi, Pi, omp, or any other). When `team.yml` is present and `enabled: true`, the conductor may dispatch Workers to entirely different CLI harnesses (codex, gemini, cursor-agent, kimi, pi, omp, opencode, copilot, claude-as-worker) rather than spawning native subagents. The role resolution, Tier declaration, and spawn-preset mechanism above all apply before dispatch; collected worker output re-enters the existing Skeptic gate unchanged. See `content/references/cross-harness-teams.md` for the decision rule, `team.yml` schema, self-containment guard, and per-harn…
