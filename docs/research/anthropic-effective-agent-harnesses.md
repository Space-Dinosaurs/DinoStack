# Effective Harnesses for Long-Running Agents (Anthropic)

**Source:** https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
**YouTube commentary:** https://youtu.be/AURa5oPVvaE (Daniel, Crafter's Lab)
**Date Researched:** 2026-03-13
**Category:** agentic-frameworks

---

## Summary

Anthropic published an engineering post documenting the failures they encountered building a long-running coding agent with Opus 4.5 and how they fixed them. The three core failure modes - context loss between sessions, agents trying to do everything at once, and agents falsely declaring work "done" - turn out to be universal. Their solutions are structurally simple: files, progress tracking, and explicit constraints. The YouTube video by Daniel (Crafter's Lab) validates this pattern against what solo developers have already been building independently.

## Key Points

**The three failure modes Anthropic hit:**
1. **Context loss** - Every new session starts cold. Without external memory, the agent has no idea what happened before and wastes its entire context window rediscovering the project state.
2. **Scope explosion** - The agent sees the whole project and tries to build all of it in one pass. It runs out of context mid-implementation and leaves the codebase in a broken, undocumented limbo state.
3. **False completion** - The agent marks a feature "done" after passing unit tests or seeing a 200 curl response, without ever testing the actual user experience. The feature is broken but the agent doesn't know.

**The two-agent architecture they used:**

- **Initializer agent** (runs once at project start): Creates `init.sh` to spin up dev servers, writes `claude-progress.txt` as a running log, generates `features.json` with every feature defaulting to `"passes": false`, and makes an initial git commit.
- **Coding agent** (runs each subsequent session): Starts by running `pwd`, reading git history and progress files, running `init.sh`. Picks the single highest-priority unfinished feature. Implements it, tests end-to-end via Puppeteer MCP, commits, updates progress, marks feature `"passes": true` only after confirmed browser-level testing.

## Details

### Why JSON instead of Markdown for the feature list

Anthropic deliberately chose JSON over Markdown checklists because "the model is less likely to inappropriately change or overwrite JSON files." With a Markdown checklist, Claude tends to reorganize and rewrite the whole file. With JSON, it surgically updates the `passes` field and leaves the rest intact. This raises a broader question: file format as a control mechanism for agent behavior.

`features.json` entry format:
```json
{
  "category": "functional",
  "description": "New chat button creates a fresh conversation",
  "steps": ["Navigate to main interface", "Click the 'New Chat' button"],
  "passes": false
}
```

### Strongly-worded instructions

Anthropic used hard non-negotiable language rather than polite suggestions. Key examples:
- "It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality"
- Run `pwd` at session start to confirm working directory
- Read git logs and `claude-progress.txt` before doing anything
- "Read the features list file and choose the highest-priority feature"

The insight: soft language like "please try to avoid modifying tests if possible" gives the model room to find a justification. Hard language treats the rule as a wall, not a suggestion.

### End-to-end testing via Puppeteer MCP

Their most impactful fix for the false-completion problem: telling the agent to test like a real user by opening the browser, clicking buttons, filling forms, and visually verifying output - not just checking curl responses. Results were "dramatically better." Open question for mobile/SwiftUI: Puppeteer doesn't exist for iOS, and Xcode MCP handles previews and build logs but not full end-to-end user-level testing.

### Scale

The initializer generates 200+ feature test cases by default. The reference app was a claude.ai clone. The model stack was Opus 4.5 on the Claude Agent SDK with context compaction.

### Connection to CLAUDE.md / progress.md patterns

The pattern Anthropic described (initializer creating external memory files that every subsequent session reads first) maps directly to what solo developers have independently built with CLAUDE.md and progress.md. The model is not the fix - the harness around the model is the fix. Anthropic, the team that built Claude, could not solve multi-session continuity without external structure.

## Takeaways / Why It Matters

The real signal here is who is saying it: the people who built the model are admitting the model can't maintain continuity across sessions without help from the outside. If you're running cold sessions with no context files, you're fighting a problem Anthropic couldn't solve without structure either.

Three things to steal immediately:
1. A `features.json` (not `.md`) that forces incremental one-feature-at-a-time progress
2. A progress file every session reads before touching any code
3. Hard, non-negotiable instruction language in your system prompt - not polite requests

The open question worth watching: whether specialized sub-agents (QA, testing, cleanup) would outperform a single general-purpose coding agent for long-running projects.

## Sources

- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- https://youtu.be/AURa5oPVvaE (Daniel, Crafter's Lab - video commentary)
