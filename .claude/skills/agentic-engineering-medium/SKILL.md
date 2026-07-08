---
name: "agentic-engineering-medium"
description: >
  Medium-tier agentic engineering. Apply when the user mentions any software development work
  involving multi-file changes, refactors, team coordination, shared utilities, or any task
  that involves reading, writing, or reasoning about code and systems, and the user has opted
  into medium tier (via tier=medium in ~/.claude/agentic-engineering.json or --tier=medium on
  /implement-ticket). Skips QA gate, wrap-ticket, learning-extractor; uses inline Brief in
  engineer prompt instead of separate artifact.
---
# Agentic Engineering (medium)

Team-aware methodology without the full kernel. Multi-unit work, shared utilities, cross-session resume.

## How to act

### Risk classification (inline)

| Signal | Class |
|---|---|
| 1 file, no behavior change | Trivial - direct edit |
| 1 file local behavioral change, no cross-component data flow, no security surface | Low - direct edit + self-check |
| Anything else (multi-file, security/auth, architecture, new file with public symbol, shared utility) | Elevated - Worker + Skeptic |

### Elevated path

1. **Conductor classifies** risk and decides tier override.
2. **Spawn `engineer` in worktree** (`isolation: worktree`) for single-unit Elevated.
3. **Spawn `architect` first** for multi-unit Elevated (2+ files, shared utilities touched, cross-component data flow). Architect returns plan + unit list.
4. **Conductor authors Brief inline** in the engineer spawn prompt (5 lines: scope, acceptance, non-goals, verification, blast radius). No separate `docs/planning/<slug>.md` file.
5. **Skeptic reviews** diff in full. Findings: Critical/Major/Minor. Critical/Major block merge; engineer fixes; re-spawn Skeptic. Cap at 3 fix passes; convergence failure escalates.
6. **Loop-state resume** at `.agentic/loop-state.json` survives session exits; re-invoking `/implement-ticket` resumes from last phase.

### Multi-unit Elevated (2-5 units)

- Architect returns unit list (parallel vs sequential).
- Parallel units: spawn engineer per unit in own worktree, branch from `origin/main` (NOT local checkout, which may include sibling units).
- Sequential units: one branch, one PR per ticket.
- Skeptic reviews combined diff for sequential; per-unit for parallel.

### What medium tier does NOT do

- No QA gate (no `qa-engineer` spawn). User validates runtime manually or via CI.
- No `wrap-ticket` end-of-session sync. Use `/wrap` for plain-text summary.
- No learning-extractor, no meta-Skeptic, no ADR generator.
- No capability preflight block (warn-only, not blocking).
- No `qa-engineer` for Elevated UI changes (run yourself with `agent-browser` or skip).

For those: `/implement-ticket --tier=full`.

## Commands

- `/implement-ticket <id>` - run with current tier (or `--tier=medium|full|minimal` override)
- `/brief <topic>` - interactive planning dialogue (medium/full only); produces Brief artifact for full, inline prompt summary for medium
- `/agentic-status` - resolver dump
- `/agentic-config` - change tier/mode
- `/wrap` - session summary

## When to upgrade to full

- Cross-track change touching `AGENTS.md` at multiple depth-1 dirs.
- Security/auth/crypto/payments surface.
- Novel architecture decision needing ADR.
- QA gate required for UI-visible changes (>= 2 Elevated units touching user-facing behavior).
- Need `wrap-ticket` for automated end-of-session sync.

Set per-project: `agentic_tier: full` in `.agentic/config.json`. Or per-invocation: `/implement-ticket --tier=full`.