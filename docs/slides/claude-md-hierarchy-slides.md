---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 26px;
    padding: 50px 60px;
    background: #faf8f3;
  }
  section h2 {
    font-size: 1.6em;
    margin: 0 0 0.5em 0;
  }
  section p, section li {
    line-height: 1.4;
    margin: 0.3em 0;
  }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: #faf8f3;
    color: #1a1a1f;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
    color: #224466;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #faf8f3;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5em;
    margin-bottom: 0.8em;
  }
  .columns-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1em;
    margin-bottom: 0.8em;
  }
  .card {
    background: white;
    border-radius: 10px;
    padding: 0.8em 1em;
    font-size: 0.9em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #b5451f;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #b5451f;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #faf0e8;
    border-left: 4px solid #b5451f;
    padding: 0.5em 1em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
    font-size: 0.9em;
  }
  pre {
    font-size: 0.8em;
    padding: 0.5em 0.8em;
    margin: 0.3em 0 0.8em 0;
  }
  code {
    font-size: 0.9em;
  }
  blockquote {
    border-left: 4px solid #b5451f;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# The CLAUDE.md Hierarchy

How agents inherit context at the right level of detail

---

## The problem: context is expensive

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; }
</style>

- Every token in an agent's context window has a cost - latency, accuracy, money
- A backend agent doesn't need frontend conventions. A frontend agent doesn't need database schemas.
- Loading everything everywhere wastes the window on irrelevant detail
- Loading nothing means every session starts from scratch - rediscovering the same decisions
- The solution: a **layered hierarchy** where each level adds detail only when relevant

<div class="callout">
The hierarchy gives agents the right context at the right time - broad rules globally, project decisions at the root, deep detail only in the directories that need it.
</div>

---

<!-- _class: highlight -->

## Three tiers of CLAUDE.md

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.82em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.05em; }
  .columns-3 .card code { display: inline-block; margin-bottom: 0.4em; }
  .callout { font-size: 0.78em; padding: 0.4em 1em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #7b1fa2;">
<strong>Global</strong><br/>
<code>~/.claude/CLAUDE.md</code><br/>
Always loaded in every session. Behavioral rules, skill-loading triggers, universal preferences. Under ~30 lines.
</div>
<div class="card" style="border-left-color: #1565c0;">
<strong>Project root</strong><br/>
<code>[repo]/CLAUDE.md</code><br/>
One-paragraph summary, resolved architecture decisions, repo structure, tools, conventions. Under ~40 lines.
</div>
<div class="card" style="border-left-color: #2e7d32;">
<strong>Subdirectory</strong><br/>
<code>[repo]/[track]/CLAUDE.md</code><br/>
Stack details, track-specific patterns, gotchas, schemas. Loaded only when working in that directory. Under ~60 lines.
</div>
</div>

<div class="callout">
Each tier inherits from the one above. An agent working in <code>api/</code> sees: global rules + project root + api/CLAUDE.md. Line limits prevent context bloat - every line in CLAUDE.md is loaded into every agent's context window, so keeping files lean directly improves accuracy and speed.
</div>

---

## What goes where

<style scoped>
  table { font-size: 0.78em; margin: 0.3em 0 0.8em 0; }
  th { background: #f0f0f0; }
  td, th { padding: 0.4em 0.6em; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

| Level | Contains | Example |
|---|---|---|
| **Global** | Behavioral rules, skill triggers, em-dash ban, commit style | "Never use em dashes" |
| **Project root** | Project name, decisions (brief), repo map, tools, tracker config | "Base branch: develop" |
| **Subdirectory** | Stack, key conventions, commands, schemas, gotchas | "All API routes use Zod validation" |

And what does **not** go in CLAUDE.md:

| File | Purpose |
|---|---|
| `decisions.md` | Architecture decisions with full rationale (auto-loaded from rules) |
| `context.md` | Ephemeral session state - auto-written by the Stop hook |
| `MEMORY.md` | Stable facts learned across sessions |

<div class="callout">
CLAUDE.md holds resolved decisions as brief bullets. The <em>rationale</em> (alternatives, tradeoffs) belongs in decisions.md so root stays under 40 lines.
</div>

---

## How /init-project scaffolds it

<style scoped>
  ol { font-size: 0.88em; }
  ol li { margin: 0.2em 0; }
  pre { font-size: 0.75em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

1. **Discovery phase** - auto-detects project name, description, tracks, database, web UI, tracker
2. **Creates root CLAUDE.md** - one-paragraph summary, decisions section, repo structure map, tools
3. **Creates track CLAUDE.md files** - one per detected subdirectory (e.g. `api/CLAUDE.md`, `web/CLAUDE.md`)
4. **Creates supporting files** - `.claude/settings.json`, docs structure, MEMORY.md stub

```
myproject/
  CLAUDE.md              ← root (under 40 lines)
  api/CLAUDE.md          ← backend track detail
  web/CLAUDE.md          ← frontend track detail
  .claude/settings.json  ← MCP servers, shared config
```

<div class="callout">
Running /init-project is idempotent - it updates existing files and adds new tracks without overwriting what's already there.
</div>

---

## How /wrap keeps it current

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  .columns .card { padding: 0.7em 0.9em; font-size: 0.85em; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

<div class="columns">
<div class="card">
<strong>What /wrap reads</strong>

- Files touched this session
- Git diff and commit history
- Existing CLAUDE.md content
- Current context.md
</div>
<div class="card">
<strong>What /wrap writes</strong>

- Updates root CLAUDE.md with new decisions
- Creates/updates track CLAUDE.md files
- Enriches context.md with session summary
- Adds stable facts to MEMORY.md
</div>
</div>

- If you touched a new subdirectory, /wrap creates its track CLAUDE.md automatically
- Stable facts (architecture, gotchas, setup commands) get extracted and persisted
- Ephemeral details (current task, next steps) stay in context.md where they belong

<div class="callout">
The hierarchy grows organically. You don't plan it upfront - /wrap builds it from what actually happened in each session.
</div>

---

<!-- _class: lead -->

# Right context. Right level. Right time.

Lean roots, detailed tracks, nothing wasted.

github.com/Solara6/agentic-engineering
