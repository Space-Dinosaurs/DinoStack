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

- **agent-team.md** - Named agent roles (engineer, architect, investigator, debugger, security-auditor, orchestration-planner), composed flows, decision rules, and spawn requirements. Read when: deciding which agent to spawn or composing a multi-agent flow.

- **design-goals.md** - Design principles and goals of the Agentic Engineering system. Read when: evaluating whether a proposed change aligns with the system's intent.

## Command Templates (in .codex/commands/)

These are prompt templates for common workflows. Invoke them by pasting into your session:

- **skeptic.md** - Full Skeptic Protocol orchestration (Worker -> Skeptic -> re-route loop)
- **implement.md** - Ticket-to-PR flow (Architect -> Orchestration Planner -> Engineer -> Skeptic)
- **wrap.md** - Session context enrichment and AGENTS.md updates
- **memory-update.md** - Capture a project decision to memory
- **init-project.md** - Scaffold a new project with AGENTS.md hierarchy
- **update-protocol.md** - Governs edits to methodology documents

**Important:** The `/agentic-engineering` prerequisite line present in Claude Code command files does not apply here. Codex does not use a skill-loading prerequisite system. When using these templates, simply paste the content directly into your session.

## Named Agents

Codex does not have a built-in named agent system like Claude Code's `~/.claude/agents/`. To use named agents, spawn subagents with their role preamble explicitly in the prompt. The `agent-team.md` reference contains the full agent definitions.

**Quick agent preambles:**

- **engineer**: "You are a Worker agent. Implement this specific change and return your complete output. The main agent will arrange Skeptic review."
- **architect**: "You are an Architect agent. Produce a concrete implementation plan for the task below. Identify parallel vs sequential units, risks, and the appropriate adversarial brief type for Skeptic review."
- **investigator**: "You are an Investigator agent. Map the codebase area described below: what exists, what would change, and the blast radius of the proposed change."
- **skeptic**: "You are a Skeptic agent. Review the output below adversarially. Apply the adversarial brief. Classify findings as Critical, Major, or Minor. Return findings and sign-off in the required format."
- **orchestration-planner**: "You are an Orchestration Planner. Given the architect's plan below, identify which units are independent (can run in parallel) vs dependent (must be sequential), and return a structured execution plan."
- **debugger**: "You are a Debugger agent. Identify the root cause of the issue described below. Do not fix it - return a diagnosis with evidence."
- **security-auditor**: "You are a Security Auditor. Review the code or design below for security vulnerabilities. Focus on the attack surfaces described in the adversarial brief."

## Limitations vs Claude Code

Codex does not support:
- **Lifecycle hooks** - No beforeSubmitPrompt or stop hook. The risk reminder must be applied manually by following the protocol, not triggered automatically. Session context must be saved manually (run the `/wrap` command template when ending a session).
- **Slash command system** - Commands are prompt templates, not first-class slash commands. Paste them into the session manually.
- **Background subagent spawning** - Codex's subagent model differs from Claude Code. Adapt multi-agent flows to Codex's available spawning mechanism.

Codex does support a global instructions file at `~/.codex/AGENTS.md` (equivalent to Claude Code's `~/.claude/CLAUDE.md`). The adapter's `install.sh` symlinks `~/.codex/AGENTS.md` to `.codex/AGENTS.md` so the methodology is injected globally in addition to this skill.
