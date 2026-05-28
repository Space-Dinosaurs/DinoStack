# P0 Brief: Front-end QA methods + dependency preflight

## Problem

The AE methodology treats UI as "a thing you click through" rather than as a discipline. The new `visual_conformance` scenario type (commit d6d369b) proved the schema can carry FE-specific verification, but four gaps remain that block agents from delivering production-quality front-end work without operator hand-holding:

1. **No accessibility gate.** Zero mentions of axe/aria/WCAG/contrast across `content/`. UI ships with a11y regressions invisible to source review.
2. **No responsive/viewport coverage.** Single implicit viewport. Mobile bugs surface in production.
3. **No perceptual regression catch.** `visual_conformance` covers asserted claims only; unspecified layout shift, color drift, and spacing regressions go undetected.
4. **No dependency preflight.** qa-engineer discovers Playwright / axe / agent-browser / chrome-devtools MCP availability mid-run and returns BLOCKED, wasting a worker turn. There is no mechanism for agents to declare their required tooling up front or for the conductor to surface missing capabilities before spawning.

## Success criteria

A future qa-engineer run on an Elevated UI-visible unit:

- Auto-fails Skeptic-on-Brief when an `accessibility` scenario is missing (mirrors `visual_conformance` auto-Critical).
- Iterates every applicable scenario across each declared viewport and reports per-(scenario × viewport) pass/fail.
- When `perceptual_diff_enabled: true` in `.agentic/config.json`, runs Playwright `toHaveScreenshot` against committed baselines and fails on >tolerance drift.
- Before spawning, the conductor reads each agent's capability manifest, checks every declared tool, and either auto-installs (where safe) or surfaces a verbatim "missing dependencies: X, Y, Z" message with install commands. At P0 the default behavior is **advisory** (warn and proceed) so adoption is non-breaking; flipping to **blocking** (refuse the spawn) is a one-line `.agentic/config.json` change once every agent's manifest is populated.

## Constraints

- All four additions land as edits under `content/**` only. No source-code changes outside the methodology package.
- Schema-level changes are mirrored across the 10 adapter build targets (`.claude`, `.codex`, `.cursor`, `.gemini`, `.opencode`, `.kimi`, `.omp`, `.hermes`, `.pi`, `scripts/build-methodology.sh`). CI `check-adapter-sync` must pass.
- `perceptual_diff` is opt-in via `.agentic/config.json` `perceptual_diff_enabled: false` default. Baseline maintenance overhead justifies opt-in.
- axe WCAG level defaults to AA. AAA is aspirational; do not default-enforce.
- Viewport canonical sizes: mobile 375x667, tablet 768x1024, desktop 1440x900. Override via project `qa.md`.
- `accessibility` auto-Critical fires only on UI-visible Elevated units with `qa_skip == null`.
- **Landing order is fixed.** U3 (capability preflight) ships AFTER U2 (qa-engineer manifest authoring). U3 cannot enable its `block-on-missing-required` mode until every agent under `content/agents/` has a `capabilities:` block. Until then, preflight runs in **advisory mode**: missing required deps emit a warning naming the agent + tool + install command, but do NOT block the spawn. Advisory mode is the default in U3's initial landing; switch to blocking mode is a separate one-line config flip after U2 + the per-agent capability table (see below) are merged.
- **`capabilities:` block absent on an agent ⇒ preflight is a no-op for that agent** (treated as zero declared requirements, advisory or blocking mode irrelevant). This makes adoption incremental; agents are upgraded one at a time without breaking existing flows.
- Dependency preflight is non-destructive. **`auto_install: true` is restricted to commands whose ONLY side effect is `node_modules/` or `~/.local/`/`pip --user` mutation.** Specifically permitted: `npm install --no-save <pkg>`, `pip install --user <pkg>`. Specifically forbidden in `auto_install: true`: anything that downloads browser binaries to system caches (e.g. `playwright install chromium`), anything that mutates global state (`npm install -g`), anything requiring sudo, anything touching `package.json`/`package-lock.json`/`requirements.txt`. The forbidden set is surfaced as install hints only and waits for operator action.
- A missing dependency that the agent declared as `required: true` blocks the spawn (once blocking mode is active). `required: false` (optional capability) emits a warning and proceeds.

## Non-goals

- Storybook integration, theme/dark-mode conformance, motion verification, cross-browser matrix, Lighthouse perf budgets, design-spec drift detection. These are P1/P2 (see investigator brief).
- Reframing engineer.md with FE-discipline guidance and matching Skeptic finding categories. Separate P1 Brief.
- Baseline image diff visualization in PR comments. Diff PNGs land in qa report only at P0.
- Cross-agent capability negotiation (agent A requires what agent B installs). Each agent declares its own.

## Approach

Four mechanical schema extensions, each mirroring an existing precedent.

**1. `accessibility` scenario method.** New enum value on `method`. Per-scenario `wcag_level` (default `AA`) is the canonical operator-facing field; `axe_tags` is computed from it (`A` ⇒ `[wcag2a]`, `AA` ⇒ `[wcag2a, wcag2aa]`, `AAA` ⇒ `[wcag2a, wcag2aa, wcag2aaa]`). Operators MAY override the computed value by setting `axe_tags` explicitly; when both are set, **explicit `axe_tags` wins at runtime** and Skeptic raises Minor advising the operator to remove either `wcag_level` or `axe_tags` to eliminate the redundancy. qa-engineer runs `@axe-core/playwright` per viewport and reports violations by impact. Auto-Critical Skeptic rule mirrors `visual_conformance` at `content/references/skeptic-protocol.md:326-328`.

**2. `viewport` field.** Root-level default on `qa_criteria` (default `[desktop]`); per-scenario override. **Per-scenario `viewport` REPLACES the root list, not extends it** (matches the principle that scenario-level fields are full overrides everywhere else in the schema). qa-engineer iterates `page.setViewportSize()` over each applicable viewport. The auto-Major "responsive ticket without viewport matrix" rule is a **Skeptic judgment call, not a regex**: the Skeptic-on-Brief reviewer reads the ticket text and architect plan and raises Major when the work is clearly responsive (mobile breakpoint changes, new Tailwind responsive prefixes touching layout, explicit "works on mobile" success criterion) and viewport is unset or `[desktop]`-only. Trying to mechanize this with keyword regex produces false positives on prose ("automobile", "Markdown" containing `md:`, log file mentions of `lg:`) and misses synonyms ("phone layout", "small screens", "narrow viewport").

**3. `perceptual_diff` scenario method.** New enum value. Per-scenario `tolerance` (default `0.001`) and `baseline_path` (default `tests/visual-baselines/<scenario-id>/<viewport>.png`). First-run absent baseline → save baseline + return INCONCLUSIVE with "baseline pending review" note. Subsequent runs → Playwright `toHaveScreenshot({ maxDiffPixelRatio: tolerance })`. Auto-Major when `perceptual_diff_enabled: true` AND UI-visible AND no `perceptual_diff` scenario present.

**4. Capability manifest + preflight.** New YAML block on agent specs under `content/agents/`. Schema:

```yaml
capabilities:
  required:
    - tool: "@axe-core/playwright"
      check: "npm ls @axe-core/playwright"   # exit 0 = present, non-zero = missing
      install: "npm install --no-save @axe-core/playwright"
      auto_install: true                     # node_modules-only side effect, allowed
      required_when: "scenario.method == 'accessibility'"   # per-spawn conditional gate
  optional:
    - tool: "playwright-python"
      check: "python -c 'import playwright'"
      install_hint: "pip install playwright && playwright install chromium"  # NOT auto: downloads ~150MB browser binary
    - tool: "agent-browser"
      check: "command -v agent-browser"
      install_hint: "npm install -g agent-browser"
    - tool: "chrome-devtools-mcp"
      check: "test -f .claude/settings.json && grep -q chrome-devtools .claude/settings.json"
      install_hint: "add chrome-devtools MCP server to .claude/settings.json"
```

**Check command portability.** Check commands MUST be POSIX-shell compatible (the methodology already assumes POSIX shell elsewhere; this is restated here). Semantics: exit code 0 = present, non-zero = missing. Stderr is suppressed by the preflight runner; agents do not redirect it themselves. Windows operators run via WSL or Git Bash; native PowerShell is not supported (already a methodology-wide assumption).

**Per-agent capability table (binding for U2 + U3 landing):**

| Agent | Required | Optional |
|---|---|---|
| qa-engineer | `@axe-core/playwright` (when `accessibility` method used) | `playwright-python`, `agent-browser`, `chrome-devtools-mcp` |
| engineer | (none) | (none) |
| architect | (none) | (none) |
| investigator | (none) | (none) |
| debugger | (none) | (none) |
| skeptic | (none) | (none) |
| security-auditor | (none) | (none) |
| dependency-auditor | (none; uses host package manager already required for the project) | (none) |
| release-orchestrator | (none; uses `gh` CLI per existing project assumption) | (none) |
| perf-analyst | (none) | `playwright-python` (perceptual perf scenarios) |
| orchestration-planner | (none) | (none) |

P0 only populates qa-engineer's manifest in U2; other agents land with empty `capabilities:` blocks as placeholders (no-op per the absent-block rule above). Filling them is a P1 follow-up.

**Conductor preflight flow.**
1. Before Agent spawn, read the target agent's `capabilities:` block. If absent, skip preflight entirely for this spawn.
2. **Resolve `required_when` per spawn.** For each entry under `required:`, evaluate its `required_when` predicate (if present) against the current spawn context: the spawn's `qa_criteria` block (when spawning qa-engineer), the Brief's success criteria, and the unit's task fields. The predicate language is a small fixed grammar: `scenario.method == '<value>'`, `scenario.method in ['<v1>', '<v2>']`, `brief.has_field('<name>')`, joined by `&&` / `||`. An entry with no `required_when` is unconditionally required. An entry whose `required_when` evaluates false is downgraded to optional (warn-on-miss) for this spawn. This makes `@axe-core/playwright` mandatory only when an `accessibility` scenario is in the spawn payload, and optional otherwise - solving the per-spawn vs per-agent resolution problem cleanly.
3. For each required + optional entry surviving step 2, run `check`. Cache the result under `.agentic/.capability-cache.json` keyed by `(agent, tool)` with TTL 30 min.
4. **Cache miss policy: cache HITS only. Misses are never cached** so an operator who installs a dep mid-session sees it picked up on the next spawn without manual cache-bust.
5. `auto_install: true` entries that fail their check: run `install`; re-run `check`; if still failing, treat as a regular miss.
6. Remaining required misses ⇒ block (in blocking mode) or warn (in advisory mode) with:
   ```
   <agent> preflight: <mode>
     required missing: <tool> — install: <install_hint or install>
     optional missing: <tool> — install: <install_hint>
   ```
7. Mode is read from `.agentic/config.json` `capability_preflight_mode: advisory | blocking` (default `advisory` at P0; flip to `blocking` is a separate landing once U2 + adapter rebuilds complete).

Cache file is gitignored under the existing `.agentic/` umbrella.

For full schema diffs, per-file edit summary, auto-Critical trigger table, baseline storage convention, and per-method evidence JSON shape, see the architect plan at the end of this Brief.

## QA criteria

```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: All P0 changes are documentation-only edits to content/ schema specs and agent specs. Behavioral verification of the new methods themselves happens in a follow-up smoke Brief that uses them.
  scenarios: []
  manual_smoke: none
```

## Verification gate

After the four units land and adapters rebuild:

1. **Smoke Brief** at `docs/planning/p0-qa-methods-smoke.md` (follow-up) authors a synthetic Helios UI ticket exercising all three new methods + viewport matrix `[mobile, desktop]`. Expected: per-(scenario × viewport) rows in qa report, axe violations JSON, baseline-seed INCONCLUSIVE on first run.
2. **Capability preflight smoke (non-destructive)**: instead of uninstalling Playwright on the host harness, point qa-engineer at an isolated worktree whose `capabilities:` block declares a synthetic `required` tool with `check: "false"` (POSIX `/bin/false`, always exits non-zero, no host mutation) and `install_hint: "this is a smoke test"`. Spawn qa-engineer; in advisory mode the conductor emits the warning and proceeds; flip the worktree's `.agentic/config.json` `capability_preflight_mode: blocking` and re-spawn; conductor refuses the spawn with the verbatim message. All mutations are confined to the disposable smoke worktree (`.agentic/config.json` and `.agentic/.capability-cache.json` under that worktree); host state is untouched and the smoke is re-runnable by recreating the worktree.
3. **Skeptic auto-Critical**: author a deliberately incomplete Brief (UI-visible Elevated, missing `accessibility` scenario) and confirm Skeptic-on-Brief raises Critical citing the new rule.
4. **Adapter sync**: all 10 build scripts succeed; CI `check-adapter-sync` green.
5. **Schema drift check**: scoped enum validator — for each of `content/references/planning-artifacts.md`, `content/agents/architect.md`, `content/agents/qa-engineer.md`, `content/references/skeptic-protocol.md`, assert the file contains every new enum member (`accessibility`, `perceptual_diff`) and contains zero references to the old 4-member enum list as a closed set. Implemented as a small shell script in the follow-up smoke Brief, not a raw `grep -rn`.

## Open questions

None. All Skeptic-flagged decisions are committed in the Brief above:
- `wcag_level` is canonical, `axe_tags` overrides when explicit at runtime, both-set ⇒ Minor (redundant declaration)
- Per-scenario `viewport` REPLACES root `viewport`
- Capability preflight has two modes (advisory / blocking), default `advisory` at P0
- Blocking-mode flip is a separate follow-up Brief (committed decision, not open); P0 ships preflight infrastructure in advisory mode only because flipping to blocking before every agent has a manifest would create false-positive friction with no upside
- `auto_install: true` restricted to `node_modules/` and `pip --user` side effects only; Playwright browser install is hint-only
- `required_when` predicate language defined; conditional requirements resolved per-spawn against `qa_criteria`/Brief/unit context
- Capability cache caches hits only; misses are re-checked on every spawn
- Responsive-viewport enforcement is Skeptic judgment, not regex
- Per-agent capability table is included; P0 only populates qa-engineer

## Decomposition hint

Four orchestration units, mostly parallelizable:

- **U1: schema extensions** (`content/references/planning-artifacts.md`, `content/agents/architect.md`, `content/references/skeptic-protocol.md`) - sequential (canonical schema, then mirrors).
- **U2: qa-engineer procedures** (`content/agents/qa-engineer.md`) - depends on U1.
- **U3: capability manifest + conductor preflight** (`content/sections/02-delegation.md` or new `content/sections/02b-capability-preflight.md`, plus YAML blocks added to every `content/agents/*.md`) - independent of U1/U2.
- **U4: init-project seed + config.json key + conventions.md doc** (`content/commands/init-project.md`, `content/rules/conventions.md`) - depends on U1.
- **Adapter rebuild** (run all 10 build scripts) - final step after U1-U4.

---

## Architect plan reference

See conversation context for the full architect plan covering schema diffs, per-file line ranges, auto-Critical trigger table, baseline storage convention, evidence JSON additions, and per-consumer impact table.
