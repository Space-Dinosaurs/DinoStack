# Skill Auto-Trigger Enforcement Gap

## Problem Statement

The agentic-engineering skill defines an auto-trigger condition: "The skill loads automatically when you describe software development work." However, in practice, the conductor agent frequently bypasses this trigger and proceeds directly to implementation — reading files, editing code, running shell commands — without first engaging the skill's protocol (subagent delegation, Skeptic review, worktree isolation).

This was observed in a live session where:
1. The user requested a multi-file feature implementation (wire GCS storage into a Next.js app)
2. The conductor had the `agentic-engineering` skill visible in its User skills list
3. The conductor nevertheless performed direct implementation for several turns before the user explicitly reminded them to use subagents
4. The conductor acknowledged: "I should have invoked the methodology from the start"

## Root Cause Analysis

### 1. Soft trigger vs. hard gate
The skill is listed in context as metadata (name, path, description) but there is **no hard enforcement mechanism** that prevents the agent from using file-editing or shell tools before the skill is explicitly engaged. The agent sees the skill, recognizes the task domain, but the cost of immediate action is lower than the cost of pausing to read and follow a multi-step protocol.

### 2. No intermediate "skill loaded" state
There is no observable state change when a skill "loads." The skill description is passively present in context; the agent must actively choose to read `SKILL.md`, then read the rules files, then change its behavior. This is cognitively expensive compared to just acting.

### 3. Competency illusion
The agent can perform the implementation task directly (it has the tools and knowledge), which creates a false sense that delegation is unnecessary. The value of the skill — adversarial review, risk classification, worktree isolation — is not immediately visible until a mistake is made.

### 4. Adapter-specific behavior variance
Different CLI adapters (Claude Code vs. Kimi Code CLI) handle skills differently:
- **Claude Code**: Custom slash commands (`/init-project`, `/wrap`) are first-class UI primitives. The user invokes them explicitly, creating a hard gate.
- **Kimi Code CLI**: Skills are passive context. The user can invoke via `/skill:agentic-engineering <command>`, but there is no enforcement that this happens before implementation.

## Impact

- **Elevated-risk tasks bypass review**: Security, auth, multi-file, and infrastructure changes go unreviewed.
- **Main agent becomes implementer**: Violates the core "conductor never implements" principle.
- **No worktree isolation**: Parallel subagents risk git working tree corruption.
- **User trust erosion**: Users expect consistent protocol adherence; manual reminders should not be required.

## Proposed Fix: Universal Skill Trigger Enforcement

### Option A: Pre-action skill check (recommended)

Before any tool call that writes files, runs shell commands with side effects, or edits code, the adapter/system layer should:

1. Check if any loaded skill has a trigger condition that matches the current task
2. If a match exists and the skill has not been explicitly engaged, **block the action**
3. Prompt the user: "This task appears to involve [domain]. The [skill-name] skill is available. Engage it? [Y/n/always]"
4. If user selects "always," write a preference flag and auto-engage for future sessions

**Pros**: Hard gate, user-controlled, prevents accidental bypass
**Cons**: Adds friction to every first action; requires accurate trigger classification

### Option B: Skill engagement hook in agent preamble

Modify the system prompt / agent preamble to include a mandatory pre-flight checklist:

```
Before using WriteFile, Shell (with writes), or StrReplaceFile:
1. Check loaded skills for domain match
2. If agentic-engineering skill is present and task involves code/files/infrastructure:
   - Read SKILL.md
   - Follow delegation rules in rules/agent-methodology.md
   - Do NOT implement directly
```

**Pros**: No system-layer changes needed; prompt-level fix
**Cons**: Prompt compliance is probabilistic; agents can still ignore it under pressure

### Option C: Tool-level skill gate

Wrap file-writing and shell-execution tools with a pre-check:

```python
def write_file(path, content):
    if skill_trigger_pending("agentic-engineering"):
        raise SkillNotEngagedError(
            "File writes blocked: agentic-engineering skill available but not engaged. "
            "Run /skill:agentic-engineering <command> first."
        )
    # proceed with write
```

**Pros**: Hard technical enforcement; impossible to bypass
**Cons**: Requires adapter-level tool wrapping; may block legitimate direct actions (Rule 7)

### Option D: Session-start skill preference

Add a user-scoped preference file (`~/.agentic/skill-defaults.json`) that maps skill names to auto-engage policies:

```json
{
  "agentic-engineering": {
    "autoEngage": true,
    "triggerDomains": ["software-development", "infrastructure", "database-migration"]
  }
}
```

When the session starts, if any skill has `autoEngage: true`, the system automatically loads and activates it before the first user message is processed.

**Pros**: Set-once, applies to all future sessions; no per-action friction
**Cons**: May over-engage for minor tasks (e.g., one-line typo fixes)

## Recommendation

Implement **Option D** (session-start auto-engage) as the primary fix, with **Option A** (pre-action check) as a safety net for skills that are not auto-engaged.

This creates a two-layer defense:
1. **Layer 1**: High-confidence skills auto-engage at session start (no friction for recurring work)
2. **Layer 2**: If a skill is not auto-engaged but the task matches its trigger domain, block the first implementation action and prompt the user

## Adapter Implementation Notes

### Kimi Code CLI

The Kimi Code CLI adapter should:
1. Read `~/.agentic/skill-defaults.json` at session initialization
2. For each skill with `autoEngage: true`, prepend its `SKILL.md` content to the system prompt context
3. Before executing any `WriteFile`, `StrReplaceFile`, or `Shell` with side effects, check if a non-auto-engaged skill matches the task domain
4. If matched, emit a tool-use block that prompts the user rather than executing the tool

### Claude Code

Claude Code already has first-class slash commands. The fix is lighter:
1. Add an `auto-engage` setting to `.claude/settings.json`
2. When `auto-engage: true` for a skill, intercept the first user message and auto-invoke the skill if the message matches trigger patterns

### Universal

Both adapters should write a `~/.agentic/skill-defaults.json` scaffold on first run:

```json
{
  "agentic-engineering": {
    "autoEngage": false,
    "promptOnMatch": true,
    "triggerDomains": ["software-development"]
  }
}
```

The user opts in to `autoEngage` after positive experiences, or leaves `promptOnMatch` as the safety net.

## Open Questions

1. How do we classify task domain accurately from a single user message? (Keyword heuristics? LLM classifier?)
2. Should Rule 7 direct actions (1-2 line edits) bypass the skill gate even when a skill matches?
3. How do we prevent skill auto-engagement from consuming excessive context window?
4. Should skills declare their own trigger conditions in machine-readable format (JSON schema) rather than natural language?
