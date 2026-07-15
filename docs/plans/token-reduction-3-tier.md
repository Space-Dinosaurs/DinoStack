# Token Reduction: 3-Tier Agentic Engineering

**Status:** proposed
**Scope:** `content/`, `.claude/build.sh`, `.claude/install.sh`, `bootstrap.sh`, `scripts/build-methodology.sh`
**Goal:** drop per-session methodology context ~85% by default, keep full-power on opt-in.

---

## Problem

A single `/implement-ticket` invocation on a typical Elevated ticket burns 80-250K tokens of methodology context (agent specs, references, sections), most of it read once at session start and never re-used. 4 tickets in a 5h Claude window routinely consume the entire budget before work completes.

Where the tokens go (audit 2026-07-07):

| Source | Bytes | Tokens (~) | When loaded |
|---|---|---|---|
| `~/.claude/CLAUDE.md` (OMC + AE markers) | 17 KB | ~5K | every Claude session, always |
| `@skills/agentic-engineering/METHODOLOGY.md` (concatenation of all `content/sections/*.md`) | 96 KB | ~25K | every session in AE project, via `@`-import in managed `~/.claude/CLAUDE.md` block |
| `@rules/code-standards.md` + `conventions.md` | 25 KB | ~6K | same |
| `MEMORY.md` | 5 KB | ~1.5K | auto-injected by Claude Code |
| project `AGENTS.md` | 9 KB | ~3K | loaded when working in repo |
| `/implement-ticket` command body | 180 KB | ~45K | per invocation |
| spawned subagent prompt (qa-engineer/architect/engineer/skeptic) | 14-54 KB each | ~5-15K each | per spawn |
| reachable references on-demand | 400 KB | ~100K max | trigger-only |
| **Subtotal session-start tax (AE project)** | | **~37K tokens** | every session |
| **Subtotal per-ticket (Elevated, full flow)** | | **~80-250K tokens** | per ticket |

`@skills/agentic-engineering/METHODOLOGY.md` is the dominant fixed cost: a single `@` import in the installed `~/.claude/CLAUDE.md` block injects 25K tokens into every session regardless of what the user does next. That is the line that converts a Claude Code subscription into a per-token treadmill.

## Design: 3 tiers

One new knob: `tier`. Default = `minimal`. Opt-in for more power.

| Tier | When | Session-start cost | Per-ticket cost | What you get |
|---|---|---|---|---|
| **minimal** (default) | solo work, small PRs, learning the framework | ~5K tokens (no METHODOLOGY auto-inject; no `@`-import of sections/rules) | ~10-20K | conductor + flat agent delegation. Inline risk classification. Direct exec + light adversarial review. No Brief/Plan artifact. No QA. No loop-state. No cross-session resume. |
| **medium** | team work, multi-unit PRs, scope > 1 file | ~92K tokens (sections-medium METHODOLOGY only, no rules auto-import) | ~30-50K | Full conductor + Skeptic + worktree workflow. Single-unit Elevated → engineer + Skeptic only. Multi-unit Elevated → architect + planner + conductor authors a 5-line inline Brief in the engineer spawn prompt (NO separate `docs/planning/<slug>.md` artifact). `.agentic/loop-state.json` resume works. No `qa-engineer`, no `wrap-ticket`, no `learning-extractor`. |
| **full** | legacy behavior, current install | ~37K tokens (full sections + rules auto-injected) | ~80-250K | Everything: architect, planner, Skeptic, QA gate, full references on-demand, `wrap-ticket`, planning artifacts, cross-session resume, ADR generation, learning extractor, meta-Skeptic, capability preflight. |

Selection knobs, in priority order:

1. CLI flag: `/implement-ticket DINO-123 --tier=medium` (highest)
2. Project config: `agentic_tier: medium` in `.agentic/config.json`
3. Global config: `tier` field in `~/.claude/agentic-engineering.json` (set by installer)
4. Default: `minimal`

`profile` field retained as legacy alias (resolves to `tier`); `relaxed | default | strict` maps to `minimal | medium | full` for back-compat. New installs ignore `profile`, see only `tier`.

## What changes per tier

### minimal

- `~/.claude/CLAUDE.md` block no longer `@`-imports METHODOLOGY.md or rules; only carries the agentic-engineering Skill Loading trigger table.
- Session-startup auto-load: `content/SKILL-minimal.md` (~1.5 KB).
- Conductor spawns only `engineer`, `skeptic`, `investigator` agents (compact variants). No architect, no planner, no qa-engineer, no wrap-ticket.
- `/implement-ticket` skips: activation preflight, Batch state contracts (N=1 only), Brief/Plan authoring, capabilities preflight, loop-state cross-session resume, events log, debug-on-failure, capability preflight. Keeps: risk classification, worktree isolation, Branch+commit+PR, basic Skeptic loop, quality gate (`$QUALITY_CMD`).
- Onboarding copy in `content/SKILL-minimal.md` directs users to `/agentic-config` for upgrade.

### medium

- `~/.claude/CLAUDE.md` block `@`-imports `sections-medium/METHODOLOGY.md` (~12 KB) but NOT the rules files. Trigger table stays.
- Session-startup auto-load: `content/SKILL-medium.md` (~5 KB).
- Conductor spawns `engineer`, `skeptic`, `architect`, `planner`, `investigator`, `debugger` (medium variants). No qa-engineer, no wrap-ticket, no security-auditor, no perf-analyst, no learning-extractor.
- `/implement-ticket` keeps: risk classification, Batch state contracts, Brief authoring (inline 5-line format, no separate `docs/planning/<slug>.md` artifact), capabilities preflight (compact), loop-state resume (Compact).
- Skips: QA gate, planning-artifacts separate Plan tier, wrap-ticket, learning-extractor, meta-Skeptic, ADR generator.

### full

- Identical to current behavior.
- `~/.claude/CLAUDE.md` block `@`-imports full `METHODOLOGY.md` + rules. (Current behavior.)
- Session-startup auto-load: `content/SKILL-{full,medium,minimal}.md` (= current body, kept as full).
- All 18 agents available; all 32 references reachable; full Brief/Plan artifact flow; QA gate; wrap-ticket; learning-extractor.

## File changes

### New files

- `content/SKILL-minimal.md` (~1.5 KB)
- `content/SKILL-medium.md` (~5 KB)
- `content/sections-minimal/01-activation-preflight.md` (tiny)
- `content/sections-minimal/02-risk-classification.md` (inline)
- `content/sections-minimal/03-delegation.md` (engineer + skeptic only)
- `content/sections-minimal/METHODOLOGY.md` (assembled, ~6 KB)
- `content/sections-medium/` (~6 files, subset of full sections)
- `content/agents-minimal/{engineer,skeptic,investigator}.md` (compact)
- `content/agents-medium/{engineer,skeptic,architect,planner,investigator,debugger}.md` (slim)
- `content/references-minimal/{risk-classification,worktree-basics}.md` (essentials)
- `content/references-medium/` (~8 files, subset)

### Renamed

- `content/SKILL-{full,medium,minimal}.md` -> `content/SKILL-full.md` (no content change)

### Modified

- `scripts/build-methodology.sh` accepts `[tier]` positional arg; default `full` (matches current behavior); reads from `content/sections-<tier>/`.
- `.claude/build.sh` builds three skill directories: `.claude/skills/agentic-engineering`, `...-medium`, `...-minimal`.
- `.claude/install.sh`:
  - New flag `--tier=minimal|medium|full` (default `minimal`).
  - Writes `tier` field to `~/.claude/agentic-engineering.json`.
  - Symlinks only tier-appropriate commands, agents, and skill directory into `~/.claude/`.
  - Writes tier-specific `managed_content` block to `~/.claude/CLAUDE.md` (no `@`-import for minimal; sections-only `@`-import for medium; full `@`-import for full).
- `bootstrap.sh`: pass `--tier` flag through to `install.sh`.
- `content/commands/implement-ticket.md`: add `--tier=<minimal|medium|full>` flag parsing; gate Phase 0-12 branches on resolved tier; minimal skips Phase 1 (architect), Phase 2 (planner), Phase 3 (Brief artifact), Phase 6b (QA), Phase 12 (wrap-ticket).
- `content/sections/01-activation-preflight.md`: read `tier` from `~/.claude/agentic-engineering.json`; if absent, default `minimal`.
- `content/commands/agentic-config.md`: add `tier` setting; legacy `profile` continues to work.
- `AGENTS.md`: add `agentic-engineering-tier: <default>` note (operator can pin per-project).
- `MEMORY.md`: add decision entry.
- `CHANGELOG.md`: add entry under unreleased.

## Token savings (target)

| Phase | Before | After (default minimal) | Reduction |
|---|---|---|---|
| Session start (every Claude Code session in AE project) | ~37K | ~5K | 86% |
| Per ticket, Trivial | ~80K | ~12K | 85% |
| Per ticket, Elevated single-unit | ~150K | ~25K | 83% |
| Per ticket, Elevated multi-unit (Brief tier) | ~200K | ~50K | 75% |
| 4-ticket batch (typical 5h session) | ~600K-1M | ~80-150K | 80-85% |

Medium tier cuts another ~30-50% off full. Full tier preserves today's behavior bit-for-bit.

## Migration

Existing users re-running `.claude/install.sh` get the upgrade prompt (or accept `--tier=full` for legacy parity). One-line opt-in to upgrade per-project: `/agentic-config` -> tier -> medium. Default behavior change is opt-out safe: setting `tier: full` in `~/.claude/agentic-engineering.json` reproduces today's session exactly.

`.claude/install.sh` re-running overwrites the `managed_content` block in `~/.claude/CLAUDE.md`. Manual edits between markers (`<!-- BEGIN/END managed-by-agentic-engineering -->`) are preserved by the existing regex-sub path.

## Out of scope

- OMC's `~/.claude/CLAUDE.md` block (~5K tokens). Owned by oh-my-claudecode, separate project. Not in scope.
- Adapter builds for non-Claude harnesses (`.codex/`, `.gemini/`, `.kimi/`, `.cursor/`, `.omp/`, `.opencode/`). Tier system lands on Claude first; other adapters follow in separate PR per adapter.
- Telemetry changes. `commit_telemetry` and `.agentic/events.jsonl` unchanged.

## Rollout

1. Ship on Claude adapter first; verified by `bash .claude/install.sh --tier=minimal` on DinoStack itself.
2. Update `bootstrap.sh` doc comment to mention `--tier`.
3. Other adapters in follow-up PRs; tier system already wired at `scripts/build-methodology.sh` boundary.
4. CHANGELOG entry under unreleased; deprecate `profile` field after one minor release.