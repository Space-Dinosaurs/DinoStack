---
name: agentic-engineering
description: Apply when working on any software development task - implementing features, fixing bugs, reviewing code, debugging, testing, deploying, working with agents or subagents, making architecture decisions, setting up projects, managing dependencies, or any task that involves reading, writing, or reasoning about code and systems. Provides risk classification, Worker+Skeptic adversarial review, task decomposition, and named agent definitions.
---

# Agentic Engineering

This skill provides the full agentic engineering methodology: structured delegation, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

## Core Protocol (always apply)

The project `AGENTS.md` (or `.codex/AGENTS.md` at repo root) contains the full methodology rules. Those are loaded automatically. This skill provides additional protocol specs and command templates loaded on demand.

## Reference Docs (read when needed)

These live in `references/` alongside this skill:

- **skeptic-protocol.md** - Skeptic loop orchestration, findings classification (Critical/Major/Minor), sign-off format, adversarial briefs, and the Elevated + Cleanup path. Read when: declaring Elevated risk, running a Skeptic, or interpreting findings.

- **subagent-protocol.md** - Parallel spawning rules, worktree isolation, check-in behavior, phase breadcrumbs, and task decomposition rules for multi-Worker plans. Read when: spawning multiple parallel agents, setting up worktrees, or decomposing complex tasks.

- **agent-team.md** - Named agent roles (engineer, architect, investigator, debugger, security-auditor, qa-engineer, perf-analyst, release-orchestrator, dependency-auditor, orchestration-planner), composed flows, decision rules, and spawn requirements. Read when: deciding which agent to spawn or composing a multi-agent flow.

- **design-goals.md** - Design principles and goals of the Agentic Engineering system. Read when: evaluating whether a proposed change aligns with the system's intent.

## Command Templates

These are prompt templates for common workflows. Two invocation paths are available:

**Slash commands (preferred):** If the installer has been run, invoke as `/prompts:<name>`:
- `/prompts:skeptic` - Full Skeptic Protocol orchestration (Worker -> Skeptic -> re-route loop)
- `/prompts:implement` - Ticket-to-PR flow (Architect -> Orchestration Planner -> Engineer -> Skeptic)
- `/prompts:wrap` - Session context enrichment and AGENTS.md updates
- `/prompts:memory-update` - Capture a project decision to memory
- `/prompts:init-project` - Scaffold a new project with AGENTS.md hierarchy
- `/prompts:update-protocol` - Governs edits to methodology documents

**Manual paste (fallback):** Read `.codex/commands/<name>.md` and paste into your session.

**Important:** The `/agentic-engineering` prerequisite line present in Claude Code command files does not apply here. Codex does not use a skill-loading prerequisite system. When using these templates, simply invoke or paste the content directly.

## Named Agents

Codex supports named agents loaded from `~/.codex/agents/*.toml` (personal) or `.codex/agents/*.toml` (project-scoped). The agentic-engineering installer symlinks `~/.codex/agents/` to `.codex/agents/`, which contains TOML agent files generated from `content/agents/*.md`.

The following named agents are available after install:

| Agent | Role |
|---|---|
| `engineer` | Implementation: features, bug fixes, refactors, scripts |
| `architect` | Pre-implementation technical design |
| `debugger` | Root cause analysis |
| `investigator` | Codebase exploration and blast radius mapping |
| `qa-engineer` | Runtime browser verification after Skeptic sign-off |
| `security-auditor` | OWASP-structured security audit |
| `perf-analyst` | Performance profiling: measures latency, memory, and throughput; produces a fix brief |
| `release-orchestrator` | End-to-end release sequencing: pre-flight gates, version bump, changelog, tag, deploy, verification |
| `dependency-auditor` | Supply-chain review: CVE scanning, license compliance, lockfile analysis across all ecosystems |
| `orchestration-planner` | Decompose a complex goal into a sequenced agent execution plan |
| `skeptic` | Adversarial review of Worker output |
| `adr-drift-detector` | Audit codebase compliance against ADRs |
| `adr-generator` | Create new Architecture Decision Records |

When Codex spawns a named agent by name, it loads that agent's `developer_instructions` and config from the corresponding TOML file automatically.

**Fallback - quick agent preambles (use when TOML agents are not installed):**

If the named agent TOML files are not installed (e.g., in a fresh environment before running `install.sh`), spawn subagents with an explicit role preamble in the prompt:

- **engineer**: "You are a Worker agent. Implement this specific change and return your complete output. The main agent will arrange Skeptic review."
- **architect**: "You are an Architect agent. Produce a concrete implementation plan for the task below. Identify parallel vs sequential units, risks, and the appropriate adversarial brief type for Skeptic review."
- **investigator**: "You are an Investigator agent. Map the codebase area described below: what exists, what would change, and the blast radius of the proposed change."
- **skeptic**: "You are a Skeptic agent. Review the output below adversarially. Apply the adversarial brief. Classify findings as Critical, Major, or Minor. Return findings and sign-off in the required format."
- **orchestration-planner**: "You are an Orchestration Planner. Given the architect's plan below, identify which units are independent (can run in parallel) vs dependent (must be sequential), and return a structured execution plan."
- **debugger**: "You are a Debugger agent. Identify the root cause of the issue described below. Do not fix it - return a diagnosis with evidence."
- **security-auditor**: "You are a Security Auditor. Review the code or design below for security vulnerabilities. Focus on the attack surfaces described in the adversarial brief."
- **perf-analyst**: "You are a Performance Analyst. Profile the target described below, establish baseline measurements, identify the hotspot, and return a findings brief with measured evidence. Do not implement fixes."
- **release-orchestrator**: "You are the Release Orchestrator. Run the full release sequence for the target environment described below: pre-flight gates, version decision, changelog, version bump, tag, deploy, and post-deploy verification. Report immediately if any gate fails."
- **dependency-auditor**: "You are a Dependency Auditor. Run vulnerability scanners for all detected ecosystems in the project below, audit license compliance, assess maintenance signals, and return a structured findings report. Do not modify any files."

## Lifecycle Hooks

Codex supports lifecycle hooks behind a feature flag (`codex_hooks = true` in `~/.codex/config.toml`). The installer enables this flag automatically. Two hooks are wired:

- **`UserPromptSubmit`** - Injects the risk classification reminder as developer context before every prompt. This mirrors the Claude Code `UserPromptSubmit` hook.
- **`Stop`** - Writes a minimal session context file to `~/.codex/projects/[hash]/context.md` on session end. This is a thin port of the Claude Code `stop-context.js` (captures last assistant message, session ID, model). For richer context, run `/prompts:wrap` manually.

If hooks are not firing, verify `codex_hooks = true` is present in `~/.codex/config.toml` under `[features]`.

## Slash Commands (Custom Prompts)

Custom prompts are installed to `~/.codex/prompts/` and invoked as `/prompts:<name>` in the Codex CLI or IDE extension. Available prompts: `skeptic`, `implement`, `wrap`, `memory-update`, `init-project`, `update-protocol`.

**Note:** Codex docs mark custom prompts as deprecated in favor of skills. They are installed for discoverability but may be removed in a future Codex version.

## Remaining Limitations vs Claude Code

- **Background subagent spawning** - Codex's subagent model differs from Claude Code. Adapt multi-agent flows to Codex's available spawning mechanism.
- **Stop hook richness** - The Codex `Stop` hook context is thinner than the Claude Code version (no tool-use transcript). Use `/prompts:wrap` for richer session handoff.

Named agents are fully supported via `~/.codex/agents/*.toml` - see the Named Agents section above.

Codex supports a global instructions file at `~/.codex/AGENTS.md` (equivalent to Claude Code's `~/.claude/CLAUDE.md`). The adapter's `install.sh` symlinks `~/.codex/AGENTS.md` to `.codex/AGENTS.md` so the methodology is injected globally in addition to this skill.
