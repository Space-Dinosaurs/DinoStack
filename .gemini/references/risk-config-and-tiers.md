<!--
Purpose: Detailed risk-classification reference blocks extracted from
         content/sections/04-risk-classification.md. Contains: the
         fifteen-toggle project config catalog (behavioral toggles only);
         the Graph-derived risk signal mechanism + freshness + autonomous
         refresh; and the full Tier declaration detail including role-default
         tier table, model-param mapping, mandatory Tier-3 escalation (with
         enforce-tier.py hook note), frontmatter defaults, enforcement, and
         adapter-specific routing (Codex/Gemini, Pi/oh-my-pi, cross-harness
         teams).

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

The conductor reads `.agentic/config.json` to resolve fifteen project-level orchestration toggles before classifying and spawning (one, `qa_default_skip`, is reserved/inert - documented for schema completeness but does not currently alter behavior). The file is **committed, not gitignored** (like `qa.md` / `deploy.md`), is seeded with defaults by `/init-project`, and is optional - if absent, every toggle takes its default and behavior is unchanged.

- `debugger_on_failure` - boolean, default `false`. When `true` AND the path is Elevated, `/implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass on a quality-gate failure. A Trivial-path ticket never invokes the Debugger regardless of this toggle (the gate is `debugger_on_failure == true` AND Elevated; both must hold).
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior - canonical definition in `content/references/planning-artifacts.md` §`qa_default_skip (canonical definition)`. This entry is a cross-reference only; conventions.md likewise cross-references and neither redefines it.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. When `budget`, the conductor routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - the conductor still declares explicit `Tier: 3` for those regardless of the project `model_profile`. The same exemption covers any Skeptic the Mandatory Tier-3 review escalation rule has elevated for this unit: `budget` must not pass a downgrading `model` param to it. `budget` acts only through the spawn-call param; it never rewrites an agent's frontmatter `model:`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory | blocking`); default `blocking` as of P2 (all agent manifests are populated). The conductor reads this before every Agent spawn to decide whether missing required capabilities warn-and-proceed (`advisory`) or halt the spawn (`blocking`). Canonical reference: `content/references/capability-preflight.md`.
- `perceptual_diff_enabled` - boolean, default `false`. Opt-in for the `perceptual_diff` QA scenario method; when `true`, qa-engineer runs Playwright `page.screenshot()` + pixelmatch comparison against committed baselines.
- `theme_aware` - boolean, default `false`. Opt-in for per-theme QA tuples; when `true`, qa-engineer runs `visual_conformance` and `accessibility` scenarios in both light and dark themes and reports per-(scenario x viewport x theme) results. The conductor reads this toggle when inspecting `qa_criteria` to determine whether theme enforcement auto-Major rules apply.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer targets the Storybook iframe for isolated component verification. Requires Storybook 7+; init-project sets the related `storybook_url` config key when SB7+ is detected.
- `motion_aware` - boolean, default `false`. Opt-in for the `motion` scenario method auto-Major Skeptic rule; when `true`, qa-engineer runs CDP-emulated reduced-motion checks per scenario.
- `storybook_version` - enum (`6 | 7`), default `7`. Selects Storybook URL format for `story_id` scenarios; `6` uses `?selectedKind=&selectedStory=` format. Set automatically by init-project.
- `commit_telemetry` - boolean, default `true`. When `true`, `/implement-ticket` Phase 8 commits the per-developer session-log file (`.agentic/session-log/<developer_id>.jsonl`) as a separate commit on the PR branch, enabling cross-developer team visibility via `agentic-cost team` after pull. Set to `false` to opt out of telemetry commits on this project.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in for the daemon-driven deferred-wrap workflow; when `true`, an out-of-session daemon picks up deferred `/wrap` jobs, tuned by the `deferred_wrap_*` related keys (`deferred_wrap_idle_minutes`, `deferred_wrap_heartbeat_seconds`, `deferred_wrap_timeout_minutes`, `deferred_wrap_inprogress_reclaim_minutes`, `deferred_wrap_pending_ttl_days` - see `content/rules/conventions.md` §Project Config). The default `false` preserves the in-session synchronous `/wrap` behavior.
- `abdication_guard_enabled` - boolean, default `false`. When `true`, a Stop hook detects conductor abdication - ending a turn by asking permission for a non-destructive next step - and blocks the stop, injecting a "proceed" directive. Mechanizes the Proactive autonomy / default-and-proceed rule in §Delegation. Default `false`; individual projects opt in. See `content/rules/conventions.md` §Project Config for full semantics.
- `skill_candidate_detection` - boolean, default `true`. Master toggle for the skill-candidate detector. When `true`, the Stop hook scans `.agentic/events.jsonl` and `.agentic/learnings.md` for recurring friction patterns and writes candidates to `.agentic/skill-candidates.md`; the conductor emits a session-start notice when new candidates are found (Layer 1). When `false`, the detector exits immediately and all layers are dark. Set to `false` to opt out of skill-candidate tracking entirely.
- `skill_candidate_nudge` - boolean, default `false`. Layer-2 opt-in. When `true` AND `skill_candidate_detection` is `true`, a `PostToolUse(Task)` hook emits an in-session nudge the first time a domain crosses the candidate threshold during the current session. Requires the master toggle to be enabled; `skill_candidate_nudge` alone has no effect. Default `false` (matches the `deferred_wrap_daemon` opt-in precedent).

#### Graph-derived risk signal

When a fresh `GRAPH_REPORT.md` exists at the repo root, the conductor uses a Graphify knowledge graph during risk classification to detect high-blast-radius or non-obvious-coupling changes. It is presence-gated and escalate-only: it can raise a classification toward Elevated, never lower one.

**Rationale.** Graphify writes `GRAPH_REPORT.md` at the repo root. Two of its computed sections name the symbols that carry the most architectural weight: God Nodes (highest-degree core abstractions) and Surprising Connections (cross-file couplings the author probably did not know about). A change touching one of those symbols is, by construction, the "Changes to shared utilities (single-file but high blast radius)" or "Logic with emergent/non-obvious cross-component interactions" Elevated signal - this mechanizes that judgment from an artifact the project already maintains.

**Mechanism (when a fresh `GRAPH_REPORT.md` exists at the repo root).** Before classifying, the conductor checks freshness (below). If fresh, it reads `GRAPH_REPORT.md` and tests the change's target symbol(s) for membership, against the graphify v8 report format:
- God Nodes: under the exact heading `## God Nodes (most connected - your core abstractions)`, each entry is `N. ` followed by a backtick-wrapped bare symbol label followed by ` - <degree> edges`. The match set is those bare labels.
- Surprising Connections: under the exact heading `## Surprising Connections (you probably didn't know these)`, each entry's first line is `- ` followed by backtick-wrapped `<source>`, ` --<relation>--> `, backtick-wrapped `<target>`, then `  [<tag>]`. The match set is the bare `<source>` and `<target>` labels. The literal line `- None detected - all connections are within the same source files.` means no surprises.

On a match, the conductor treats it as an additional Elevated signal and classifies the change Elevated (or higher if other signals apply). On no match, no effect - classify as today. When the target symbol is not yet known at classification time (for example a vague task before investigation), the signal does not fire; classify as today. The signal never downgrades a classification.

Symbol matching is best-effort and bare-name-based (the report uses bare labels with no path qualification). Ambiguity (overloaded names, the same name in multiple files) is acceptable because the signal is escalate-only: over-firing toward Elevated only spawns a cheap extra Skeptic, while under-firing leaves today's behavior, so over-fire is the correct failure mode.

**Freshness.** The conductor reads freshness from the same file as the signal (`GRAPH_REPORT.md`):
- Primary (graph built in a git repo): under the exact heading `## Graph Freshness`, parse the line `- Built from commit: ` followed by a backtick-wrapped 8-character SHA. The graph is fresh only if that SHA equals the first 8 characters of `git rev-parse HEAD` AND the change's target file(s) have no uncommitted modifications (`git status --porcelain -- <target-paths>` is empty for those paths - a commit match alone misses uncommitted edits).
- Fallback (no `## Graph Freshness` section, i.e. the graph was built outside a git repo): compare `GRAPH_REPORT.md`'s mtime against the newest target-source-file mtime; if any target source is newer, treat as stale. Fail safe to stale on any ambiguity.
- On stale or undetermined: ignore the signal entirely - neither escalate nor downgrade - and classify exactly as today by human judgment.

**Autonomous refresh.** The conductor keeps the graph fresh itself. At the point it is about to use the graph - before its own risk classification and before spawning the investigator - the conductor checks for an existing graph (`graphify-out/graph.json` or `GRAPH_REPORT.md`). If one exists and the staleness check above fails (built-commit not equal to HEAD, or uncommitted changes to the relevant files), the conductor runs `graphify update .` once from the repo root on its own checkout (honoring `GRAPHIFY_OUT` if set), then reads the refreshed report. This runs at most ONCE per session: after the first refresh the conductor treats the graph as fresh for the remainder of the session regardless of how many times staleness is later detected - it does not re-run `graphify update .` on every classification (in-session memory, the same once-per-session discipline as the cached base branch; no new state file). The conductor refreshes ONLY an existing graph this way: it NEVER autonomously runs a from-scratch `graphify .`, `graphify --watch`, or any rebuild or destructive path. If no graph exists at all, the conductor does NOT build one - it falls back to today's non-graph behavior. The conductor alone refreshes; the investigator and every other subagent keep their read-only lock and never run a mutating graphify subcommand. `graphify update .` is incremental and free for code-only deltas (tree-sitter AST, no LLM), but re-extracting changed docs, papers, or images costs LLM tokens, so on a mixed corpus an autonomous refresh may spend tokens; this is intrinsic to keeping an adopted graph fresh and has no opt-out toggle. If `graphify update .` fails (non-zero exit, binary error, or timeout), the conductor proceeds with the existing stale graph and notes the staleness; an update failure never blocks risk classification, and because the signal is escalate-only, using a stale graph is safe (it can only under-fire, never create a false downgrade).

**Format coupling.** The pinned strings above are the graphify v8 report format. A future graphify heading change fails safe (no heading match means an empty match set and no escalation); if graphify changes the format, these strings need a follow-up sync.

**GRAPHIFY_OUT.** The conductor reads the repo-root `GRAPH_REPORT.md` and, when refreshing, honors `GRAPHIFY_OUT` to locate the graph directory. A report relocated via `GRAPHIFY_OUT` is treated as "no report present" at the repo root - the signal does not fire and behavior is unchanged. Projects wanting the signal keep the report at the repo root.

## Tier Declaration Detail

### Tier declaration

Conductors declare the model tier at spawn time to route lightweight tasks to lower-depth models and critical reviews to maximum-reasoning-depth models. Tier is declared in the same block as Risk, immediately below the Risk line.

**Declaration format:**
```
Risk: Elevated - security adversarial brief
Tier: 3  (max reasoning depth - security audit; Tier 3)
Spawning security-auditor.
```

**Tier is a required field of the spawn declaration.** Every Elevated spawn carries a `Tier:` line directly below `Risk:`. The conductor either (a) names a tier explicitly with a justification, or (b) writes `Tier: <n> (role default)` to consciously accept the spawned agent's role-default tier from the Role-default tier table below. "Forgetting" to think about tier is no longer available: an Elevated declaration with no `Tier:` line is malformed. Most implementation spawns resolve to Tier 2 by role default; review spawns (skeptic, security-auditor) resolve to Tier 3 by role default.

**Model param mapping (Claude Code):**

| Tier | Claude Code `model` param | Use when |
|---|---|---|
| 1 | `model: "haiku"` | Shallow/mechanical tasks: existence checks, simple reads, format-only operations |
| 2 | `"sonnet"` | Standard work - engineer, investigator, qa-engineer at normal depth |
| 3 | `model: "opus"` | Security audits, novel architecture, complex blast-radius analysis; skeptic and security-auditor review by default |

**Mandatory Tier-3 review escalation.** When a unit is Elevated AND matches any of the following signals, the Skeptic (or security-auditor) reviewing that unit MUST be Tier 3 (Opus), regardless of the agent's role default or the project `model_profile`:
- security, auth, crypto, payments, or secrets
- irreversible operation: delete, migration, schema change, force push
- novel architecture constraining future choices
- high blast radius / shared-utility change
- release, deploy, or production-state change

This reuses the Elevated risk-signal vocabulary above. The conductor passes `model: opus` explicitly on these Skeptic spawns even though the skeptic frontmatter already defaults to Opus: the explicit param documents the mandate, survives a session whose model was overridden, and guards against an accidental downgrade param. `model_profile: budget` NEVER downgrades a mandated-Tier-3 Skeptic. Note the one case neither frontmatter nor the explicit param can rescue: if the org `availableModels` allowlist excludes opus, the Opus request is silently dropped and the agent inherits the session model - on a mandated-Tier-3 unit the conductor must surface that Opus is unavailable rather than proceed on an inherited model. On Claude Code this rule is mechanically backstopped by `hooks/enforce-tier.py` (escalate-only, fail-open): it denies an explicit sub-Opus `model` param on a mandated-Tier-3 review spawn (security-auditor always; skeptic when the brief matches an escalation signal). It backstops four of the five signal categories - the novel-architecture signal is not keyword-detectable, and the hook guards the spawn-call param only, not the `CLAUDE_CODE_SUBAGENT_MODEL` env override.

**Role-default tier table (committed; each agent's frontmatter `model:` MUST agree with this table).**

| Agent | Default tier | Claude `model:` | Rationale |
|---|---|---|---|
| skeptic | 3 | opus | Adversarial review quality binds correctness |
| security-auditor | 3 | opus | Spec-mandated Tier 3; threat-model depth |
| architect | 2 | sonnet | Standard design; upgrade to Tier 3 per the escalation rule for novel-architecture units |
| engineer | 2 | sonnet | Implementation |
| investigator | 2 | sonnet | Terrain mapping |
| orchestration-planner | 2 | sonnet | Decomposition |
| qa-engineer | 2 | sonnet | Runtime verification |
| debugger | 2 | sonnet | Root-cause analysis |
| dependency-auditor | 2 | sonnet | Dependency review |
| perf-analyst | 2 | sonnet | Performance analysis |
| release-orchestrator | 2 | sonnet | Release execution; escalate the reviewing Skeptic per the rule above |
| product-discovery | 2 | sonnet | Requirements synthesis |
| adr-generator | 2 | sonnet | ADR authoring |
| adr-drift-detector | 2 | sonnet | Compliance audit |
| learning-extractor | 2 | sonnet | Pattern extraction |
| learnings-agent | 2 | sonnet | Discretionary capture |
| wrap-ticket | 2 | sonnet | Session wrap |

Tier 1 (haiku) has no default-role owner; it is opt-in per spawn for shallow mechanical tasks.

**Frontmatter defaults and the model param.** Each agent's frontmatter `model:` encodes its role-default tier. Resolution precedence (Claude Code): `CLAUDE_CODE_SUBAGENT_MODEL` env var > spawn-call `model` param > frontmatter `model:` > inherited session model. Therefore:
- To accept an agent's role default, the conductor OMITS the `model` param; the frontmatter supplies the model (a skeptic spawn with no param runs Opus).
- To OVERRIDE for a specific spawn (upgrade a Tier-2 agent to Tier 3 for a novel-architecture unit, or assert a mandated-Tier-3 Skeptic), the conductor passes an explicit `model` param, which wins.
- Every agent declares an explicit frontmatter `model:` so an omitted param is always correct and a Sonnet-intended agent never silently inherits Opus from an Opus session.
- Budget mode: `model_profile: budget` acts ONLY through the spawn-call param, never by rewriting frontmatter. To get a Tier-1 (haiku) review on a NON-mandated skeptic spawn under budget mode, the conductor passes an explicit downgrade param; omitting the param yields the Opus frontmatter default. Budget mode never downgrades a mandated-Tier-3 Skeptic (see the escalation rule above).
- Org allowlist caveat: if `availableModels` excludes opus, frontmatter `model: opus` is silently dropped and the agent inherits the session model. On a mandated-Tier-3 unit in such an org, the conductor must surface that Opus is unavailable rather than proceed on an inherited model.

**Enforcement:** The tier declaration is not self-executing. Writing `Tier: 3` does not change the model. The conductor must also pass the corresponding `model` param in the Agent tool call. A declaration without the tool call param produces Tier 2 behavior regardless of what is written in the text block. The declaration serves as self-documentation and review evidence; the param is the enforcement mechanism. On Pi/omp with `role-models.yml` present and a reviewer strategy that depends on author identity (`distinct-from-author`), the conductor records, in-context, the model string it used for each engineer/architect spawn, and passes that author-model into the subsequent skeptic/security-auditor spawn so the reviewer-diversity strategy can resolve. This is in-context state only - no new state file.

**When to declare Tier 1:** task is clearly shallow - existence checks, simple file reads, format validation, lightweight synthesis. Only go Tier 1 when confident the output quality floor is not a concern.

**When to declare Tier 3:** task demands maximum reasoning depth - security adversarial review, complex architecture design with novel tradeoffs, full blast-radius analysis across a large unknown codebase. Reserve Tier 3 for these cases and include a justification parenthetical.

**Codex/Gemini:** If `~/.agentic/tier-map.yml` (or a project-local `.agentic/tier-map.yml`) exists, the conductor resolves tier to a model name from that file and passes `--model <name>` on the CLI invocation. If neither file exists, the conductor omits `--model` entirely and the CLI uses its session default - there is no hardcoded fallback model list anywhere in the repo or adapters. Tier routing for Codex/Gemini is fully opt-in; users author the tier-map file themselves. See `content/references/tier-map-example.yml` for the format.

**Pi / oh-my-pi (role-models layer):** On the Pi and oh-my-pi harnesses an additional opt-in layer maps each role -- and the adversarial reviewer -- to a concrete model. If `~/.agentic/role-models.yml` (or project-local `.agentic/role-models.yml`) exists, the conductor resolves the spawn's `model`, `effort`, and `reasoning` fields from it: `roles[<role>]` for forward roles (scalar string or `{model, effort, reasoning}` mapping; the conductor forwards only the keys that are set), and a reviewer-diversity strategy (`distinct-from-author` / `round-robin` / `by-task`) for `skeptic` / `security-auditor` spawns so the reviewer runs on a different model than the author. The explicit `roles[<role>]` model wins over the Tier-implied model on collision (operator intent), and the conductor notes the override. If neither file exists, the conductor omits the fields and Pi uses its session defaults -- there are no hardcoded model IDs. To seed the file, run `bin/agentic-configure`: the wizard asks you per role and ranks the model names you supply using the hint dictionaries in `bin/agentic-models`. See `content/references/role-models.md` for the schema and resolution algorithm, and `content/references/model-discovery.md` for the per-role ranking heuristics and selection paths.

**Cross-harness teams (opt-in, independent of role-models; any harness):** This layer is independent of the Pi/omp role-models layer above; it works on any conductor harness (Claude, Codex, Gemini, Kimi, Pi, omp, or any other). When `team.yml` is present and `enabled: true`, the conductor may dispatch Workers to entirely different CLI harnesses (codex, gemini, cursor-agent, kimi, pi, omp, claude-as-worker) rather than spawning native subagents. The role resolution, Tier declaration, and spawn-preset mechanism above all apply before dispatch; collected worker output re-enters the existing Skeptic/QA gates unchanged. See `content/references/cross-harness-teams.md` for the decision rule, `team.yml` schema, self-containment guard, and per-harness dispatch table.
