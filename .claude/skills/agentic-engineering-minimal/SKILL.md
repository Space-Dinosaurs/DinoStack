---
name: "agentic-engineering-minimal"
description: >
  Minimal-tier agentic engineering (default). Apply when the user mentions any software
  development work for solo or single-file scope: implementing features, fixing bugs,
  refactoring local code, debugging, testing, or any task that involves reading, writing,
  or reasoning about code and systems. Defaults to direct edits with inline risk
  classification; spawns engineer + skeptic for elevated work in a worktree. No Brief/Plan
  artifacts, no QA gate, no architect/planner. For multi-unit or team work, escalate to
  medium or full tier via /agentic-config.
---
# Agentic Engineering (minimal)

Smallest viable methodology. Solo work, single-file changes, learning the framework.

## How to act

**Risk classification (inline, every spawn):**

| Signal | Class |
|---|---|
| Trivial: 1 file, no behavior change, no API surface, no shared tokens, no security/auth/payments, reversible with one-line revert | direct edit |
| Low: 1 file behavioral, local, no security surface, no cross-component data flow | direct edit + inline self-check |
| Elevated: anything else (multi-file, security, architecture, new file, behavioral change) | spawn `engineer` in worktree |

For Elevated: delegate to `engineer` subagent with `isolation: worktree`. Branch from `origin/main`. Engineer returns diff + commit hash + PR URL.

**Adversarial review.** Elevated diffs go through `skeptic` for sign-off before merge. Skeptic reads the diff in full, returns Critical/Major/Minor findings. Critical/Major block merge; Engineer fixes; re-spawn Skeptic. Cap at 3 fix passes; on convergence failure, escalate to operator.

**No Brief, no Plan, no QA gate, no architect, no planner, no wrap-ticket in minimal tier.** Use `/implement-ticket --tier=medium` or `--tier=full` if the work needs those.

**Stop-and-ask.** Hard stop only for: destructive/irreversible actions, missing info only the user has, ambiguous acceptance criteria. Otherwise act and report.

## Commands

- `/implement-ticket <id|list|URL|freeform>` - run a ticket end-to-end with current tier
- `/agentic-status` - read-only resolver dump (mode, tier, marker provenance)
- `/agentic-config` - change tier/mode interactively
- `/agentic-help` - full command inventory
- `/wrap` - end-of-session summary (lightweight in minimal)

## When to upgrade

Promote to `--tier=medium` when ANY of these apply:
- Multi-unit work (>= 2 files, >= 1 shared utility touched)
- You need Brief/Plan authoring
- You need cross-session loop resume
- You're shipping to a team and want invariants on the worker output

Promote to `--tier=full` when:
- Cross-track architectural change
- Security/auth/crypto/payments
- Novel architecture decision
- Need QA gate, meta-Skeptic, learning extractor

CLI override per invocation: `/implement-ticket DINO-123 --tier=medium`.

Set per-project: `agentic_tier: medium` in `.agentic/config.json`.