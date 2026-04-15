# oh-my-claudecode vs agentic-engineering

Comparison and roadmap notes from a 2026-04-15 review of [Yeachan-Heo/oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (OMC) against this repository.

## Scale & positioning

| | OMC | agentic-engineering |
|---|---|---|
| Stars / reach | ~29k | Personal / small-team |
| Language | TypeScript-heavy | Shell + Markdown |
| Distribution | npm package + Claude plugin marketplace | `install.sh` symlinks |
| Target user | Mass consumer adoption | Disciplined solo/pair workflow |
| Pitch | "Don't learn Claude Code, just use OMC" | Opinionated methodology you learn and apply |

## Philosophy

- **OMC**: Autonomy-first. `/autopilot`, persistent `/ralph` verify/fix loops, auto-resume on rate limits, smart Haiku/Opus routing for cost. Hides the loop from the user.
- **Ours**: Methodology over autonomy. Explicit Architect → Engineer → Skeptic → QA pipeline with risk classification (Elevated vs. direct), Skeptic Protocol as a first-class adversarial gate. Surfaces the loop so humans stay in it.

## Agents

- **OMC**: 19 agents — analyst, planner, executor, critic, verifier, tracer, scientist, designer, architect, debugger, code-reviewer, code-simplifier, document-specialist, explore, git-master, qa-tester, security-reviewer, test-engineer, writer.
- **Ours**: 10 agents — architect, engineer, skeptic, qa-engineer, investigator, debugger, security-auditor, adr-generator, adr-drift-detector, orchestration-planner. Tighter roster, each tied to a protocol phase.

## Commands

- **OMC**: `/autopilot`, `/team`, `/ralph`, `/deep-interview`, `/setup`.
- **Ours**: `/implement`, `/skeptic`, `/wrap`, `/init-project`, `/memory-update`, `/update-protocol`, `/community-skills`.

## Distinctive features

**OMC only**
- Benchmark harness (SWE-bench-style eval for its own agents)
- Telegram / Discord / Slack notification routing
- HUD statusline with real-time orchestration metrics
- OpenClaw event forwarding to external gateways
- npm distribution
- 12 translated READMEs

**Ours only**
- Skeptic Protocol (adversarial review with structured sign-off)
- ADR drift detection
- Multi-adapter build (Claude, Cursor, Codex from shared `content/`)
- Risk-classification UserPromptSubmit hook
- Slide decks for teaching the methodology

**Overlap**: multi-agent orchestration, architect/debugger/critic-style roles, Codex support.

---

## OMC's autonomy mechanics

1. **Self-looping execution** (`/ralph`, `/autopilot`). Verify/fix cycles that don't stop until acceptance criteria pass. No human gate between iterations.
2. **Staged pipeline with shared state** (`team-plan → team-prd → team-exec → team-verify → team-fix`). Agents read/write a shared task list; conductor doesn't hand-carry context.
3. **Rate-limit daemon** (`omc wait`). Detects limits, calculates reset, auto-resumes sessions via tmux. Long jobs survive quota windows unattended.
4. **Smart model routing**. Haiku for cheap steps, Opus for hard ones. Cost-aware without conductor involvement.
5. **Session replay logs** (`.omc/state/agent-replay-*.jsonl`). Post-mortem and resumability.

## OMC's scale mechanics

1. **Ultrawork mode**. Burst parallelism for mechanical fan-out (refactors, codemod-style fixes).
2. **tmux worker pool** (`omc team N:provider`). N workers spawn on demand, each in its own pane, die on completion. Scales horizontally across providers (Claude + Codex + Gemini).
3. **HUD statusline**. Live observability across workers so you can supervise many concurrently.
4. **Benchmark harness**. Measures whether scaling changes actually improve success rate.

---

## Where we already win

- **Rigor per step**: Skeptic Protocol catches defects OMC's verify loops won't, because adversarial review is orthogonal to "did it run." `/ralph` will happily loop a plausible-but-wrong implementation forever.
- **Provenance**: ADR drift detection + risk classification produce an audit trail OMC lacks.
- **Methodology transfer**: humans learn the loop. OMC hides it — users can't diagnose when autopilot misfires.

## Where we are materially behind

1. **No persistence loop.** `/implement` is one-shot. A ralph-equivalent (`/implement --until-green`) that re-runs Skeptic + QA until both pass would be a direct upgrade, compatible with our rigor.
2. **No parallel fan-out primitive.** Background subagents exist but no first-class "spawn N engineers against N independent subtasks, join when all green." orchestration-planner plans it; nothing executes it concurrently.
3. **No rate-limit resumer.** Long jobs die at quota boundaries.
4. **No shared task-state file.** Conductor carries everything in context. A `.agentic/tasks.jsonl` would let workers coordinate without conductor round-trips and let a loop resume after restart.
5. **No benchmark harness.** We cannot prove a change to the Skeptic prompt makes reviews better or worse.
6. **No cost-aware model routing.** Agents hardcode Sonnet/Opus. A router picking Haiku for `investigator` and Opus for `architect` would cut spend 30–50%.
7. **Gemini adapter missing.** We have Claude, Cursor, and Codex adapters — but no Gemini. OMC's multi-provider worker pool assumes Codex **and** Gemini are both available as workers.

---

## Recommended roadmap

Pursue these in order. They are compatible with the methodology — none require adopting OMC's "zero learning curve" framing.

### P0 — Persistence loop gated by Skeptic + QA

Turn `/implement` from one-shot into a real agent. Loop Engineer → Skeptic → QA until both sign off or the loop hits a max-iteration cap. Acceptance gate is Skeptic sign-off, **not** just "tests pass." Highest leverage change.

### P0 — Gemini adapter

Build a `.gemini/` adapter parallel to `.codex/` and `.claude/`. Same `content/` source of truth, same install script shape. Unblocks multi-provider worker pools and makes our repo genuinely provider-agnostic rather than Claude-plus-two.

### P1 — Shared task-state file + parallel fan-out primitive

`.agentic/tasks.jsonl` (or similar) as the shared coordination surface. orchestration-planner writes the DAG; a new primitive executes independent nodes in parallel, joins when all green. Scale for us looks like many small rigorous units, not one fast sloppy one.

### P1 — Benchmark harness for agents

Without it, every future prompt change is vibes. Start with Skeptic (adversarial review accuracy on planted-defect fixtures) and Architect (plan quality against known-good references). This compounds: every other improvement becomes measurable.

### P2 — Cost-aware model routing

Per-agent default model declaration in frontmatter, conductor respects it. Haiku for investigator/explore-style work, Sonnet for engineer, Opus for architect/skeptic.

### P2 — Rate-limit resumer + HUD

Lower priority — only matters once persistent parallel jobs are real. Rate-limit daemon first (unlocks long unattended runs), HUD statusline second (supervision ergonomics).

### Skip

- npm distribution
- Translated READMEs
- Telegram/Discord/Slack notification routing

These are product surface, not methodology.
