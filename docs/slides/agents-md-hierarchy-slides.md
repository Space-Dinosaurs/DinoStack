---
marp: true
theme: default
paginate: true
style: |
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700;800;900&family=Nunito+Sans:wght@400;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
  section {
    font-family: 'Nunito Sans', system-ui, sans-serif;
    background-color: #02050C;
    background-image:
      radial-gradient(800px 480px at 14% -10%, rgba(24,224,255,0.12), transparent 60%),
      radial-gradient(680px 420px at 100% 0%, rgba(176,107,255,0.10), transparent 58%),
      radial-gradient(720px 560px at 70% 115%, rgba(24,224,255,0.05), transparent 60%);
    color: #eaf1fb;
    color-scheme: dark;
  }
  h1, h2, h3, h4, h5, h6 {
    font-family: 'Orbitron', system-ui, sans-serif;
    color: #ffffff;
    letter-spacing: 0.01em;
  }
  h1 { text-shadow: 0 0 30px rgba(24,224,255,0.35); }
  h2 {
    color: #eaf1fb;
    text-shadow: 0 0 18px rgba(24,224,255,0.20);
    border-bottom: 1px solid rgba(255,255,255,0.12);
    padding-bottom: 0.18em;
  }
  strong { color: #ffffff; }
  a { color: #18E0FF; text-decoration: none; }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    color: #eaf1fb;
  }
  section.lead h1 {
    font-size: 2.6em;
    margin-bottom: 0.2em;
    color: #ffffff;
    text-shadow: 0 0 38px rgba(24,224,255,0.45);
  }
  section.lead p {
    font-size: 1.2em;
    color: rgba(234,241,251,0.78);
  }
  section.highlight {
    background-color: #02050C;
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
    background: #0A1020;
    border: 1px solid rgba(255,255,255,0.10);
    border-left: 4px solid #18E0FF;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 14px rgba(0,0,0,0.45), 0 0 22px rgba(24,224,255,0.06);
    color: #eaf1fb;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #18E0FF;
    font-family: 'Orbitron', system-ui, sans-serif;
  }
  .label {
    font-size: 0.9em;
    color: #9bb0cc;
    margin-top: 0.2em;
  }
  .callout {
    background: rgba(24,224,255,0.06);
    border-left: 4px solid #18E0FF;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
    color: #eaf1fb;
  }
  blockquote {
    border-left: 4px solid #18E0FF;
    padding-left: 1em;
    color: rgba(234,241,251,0.78);
    font-style: italic;
  }
  code {
    font-family: 'JetBrains Mono', monospace;
    background: rgba(255,255,255,0.06);
    color: #9be9ff;
    padding: 0.1em 0.35em;
    border-radius: 4px;
  }
  pre {
    background: #04070F;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    color: #eaf1fb;
  }
  pre code {
    background: transparent;
    color: #eaf1fb;
    padding: 0;
  }
  table {
    border-collapse: collapse;
    background: transparent;
  }
  table tr {
    background: transparent;
  }
  table tr:nth-child(2n) {
    background: rgba(255,255,255,0.03);
  }
  th, td {
    border: 1px solid rgba(255,255,255,0.12);
    padding: 0.4em 0.8em;
  }
  th {
    background: rgba(255,255,255,0.05);
    color: #ffffff;
    font-family: 'Nunito Sans', system-ui, sans-serif;
  }
  td {
    color: #eaf1fb;
  }
  section::after {
    color: #6a7c97;
  }
  mark {
    background: rgba(233,181,33,0.22);
    color: #ffffff;
  }
  kbd {
    background: rgba(255,255,255,0.08);
    color: #eaf1fb;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 4px;
  }
  hr {
    background-color: rgba(255,255,255,0.12);
  }
  section {
    font-size: 26px;
    padding: 50px 60px;
  }
  .card {
    border-radius: 10px;
    padding: 0.8em 1em;
    font-size: 0.9em;
  }
  .callout {
    padding: 0.5em 1em;
    font-size: 0.9em;
  }
  section h2 {
    font-size: 1.6em;
    margin: 0 0 0.5em 0;
  }
  section p, section li {
    line-height: 1.4;
    margin: 0.3em 0;
  }
  pre {
    font-size: 0.8em;
    padding: 0.5em 0.8em;
    margin: 0.3em 0 0.8em 0;
  }
  code {
    font-size: 0.9em;
  }
---

<!-- _class: lead -->

# The AGENTS.md Hierarchy

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

## AGENTS.md: the cross-tool standard

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.84em; padding: 0.5em 1em; }
  .columns .card { padding: 0.7em 0.9em; font-size: 0.85em; }
</style>

**`AGENTS.md` is the single source of project instructions** - the cross-tool standard supported natively by OpenAI Codex CLI and readable by Claude Code via a one-line import.

<div class="columns">
<div class="card" style="border-left-color: #4ea3ff;">
<strong>Claude Code users</strong><br/><br/>
Create <code>CLAUDE.md</code> at the repo root containing exactly one line:<br/>
<code>@AGENTS.md</code><br/><br/>
Claude Code imports <code>AGENTS.md</code> transparently. No duplication needed.
</div>
<div class="card" style="border-left-color: #3ad99a;">
<strong>Codex CLI users</strong><br/><br/>
Codex reads <code>AGENTS.md</code> natively. No extra setup required - just create <code>AGENTS.md</code> and it loads automatically.
</div>
</div>

<div class="callout">
Sources: <a href="https://code.claude.com/docs/en/memory.md#agents-md">Anthropic import-syntax docs</a> · <a href="https://developers.openai.com/codex/guides/agents-md">OpenAI AGENTS.md guide</a> · <a href="https://agents.md">agents.md</a>
</div>

---

<!-- _class: highlight -->

## Three tiers of AGENTS.md

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.82em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.05em; }
  .columns-3 .card code { display: inline-block; margin-bottom: 0.4em; }
  .callout { font-size: 0.78em; padding: 0.4em 1em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #b06bff;">
<strong>Global</strong><br/>
<code>~/.claude/CLAUDE.md</code><br/>
Always loaded in every Claude Code session. Behavioral rules, skill-loading triggers, universal preferences. Under ~30 lines.
</div>
<div class="card" style="border-left-color: #4ea3ff;">
<strong>Project root</strong><br/>
<code>[repo]/AGENTS.md</code><br/>
One-paragraph summary, resolved architecture decisions, repo structure, tools, conventions. Under ~40 lines.
</div>
<div class="card" style="border-left-color: #3ad99a;">
<strong>Subdirectory</strong><br/>
<code>[repo]/[track]/AGENTS.md</code><br/>
Stack details, track-specific patterns, gotchas, schemas. Loaded only when working in that directory. Can be as detailed as needed.
</div>
</div>

<div class="callout">
Each tier inherits from the one above. An agent working in <code>api/</code> sees: global rules + project root + api/AGENTS.md. The root ~40-line limit prevents context bloat; subdirectory files are loaded only in context and can be as detailed as the track requires.
</div>

---

## What goes where

<style scoped>
  table { font-size: 0.78em; margin: 0.3em 0 0.6em 0; }
  th { background: rgba(255,255,255,0.05); }
  td, th { padding: 0.35em 0.6em; }
  p { font-size: 0.85em; margin: 0.3em 0; }
</style>

| Level | Contains | Example |
|---|---|---|
| **Global** | Behavioral rules, skill triggers, em-dash ban, commit style | "Never use em dashes" |
| **Project root** | Project name, decisions (brief), repo map, tools, tracker config | "Base branch: main" |
| **Subdirectory** | Stack, key conventions, commands, schemas, gotchas | "All API routes use Zod validation" |

The intent layer extends beyond `AGENTS.md` - each file has a distinct role (see next slide).

---

## The intent layer

<style scoped>
  table { font-size: 0.76em; margin: 0.25em 0 0.5em 0; }
  th { background: rgba(255,255,255,0.05); }
  td, th { padding: 0.3em 0.55em; }
  .callout { font-size: 0.80em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

| File | Purpose |
|---|---|
| `docs/overview/vision.md` + `requirements.md` | Operator-owned product intent - agents read, never write |
| `decisions.md` | Architecture decisions with full rationale |
| `.agentic/context.md` | Ephemeral session state - auto-written by the Stop hook |
| `MEMORY.md` | Stable facts learned across sessions |
| `.agentic/learnings.md` | Fix-pattern learnings from resolved Skeptic cycles |
| `.agentic/findings.md` | Curated recurring Skeptic-finding patterns |
| `glossary.md` | Ubiquitous Language - agents prefer these terms |
| `qa.md` | QA triggers and accumulated runtime knowledge |

<div class="callout">
Drift between code and these files is <strong>intent debt</strong> - distinct from technical debt in the code (module manifests embed the same file-level intent in the source). A stale entry is worse than a missing one because readers trust it.
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
2. **Creates root AGENTS.md** - one-paragraph summary, decisions section, repo structure map, tools
3. **Creates track AGENTS.md files** - one per detected subdirectory (e.g. `api/AGENTS.md`, `web/AGENTS.md`)
4. **Creates supporting files** - `.claude/settings.json`, docs structure, MEMORY.md stub

```
myproject/
  AGENTS.md              ← root (under 40 lines)
  CLAUDE.md              ← one line: @AGENTS.md  (Claude Code loader)
  api/AGENTS.md          ← backend track detail
  web/AGENTS.md          ← frontend track detail
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
- Existing AGENTS.md content
- Current `.agentic/context.md`
</div>
<div class="card">
<strong>What /wrap writes</strong>

- Updates root AGENTS.md with new decisions
- Creates/updates track AGENTS.md files
- Enriches `.agentic/context.md` with session summary
- Adds stable facts to MEMORY.md
- Promotes recurring or high-blast-radius Skeptic findings to `.agentic/findings.md`
</div>
</div>

- If you touched a new subdirectory, /wrap creates its track AGENTS.md automatically
- Stable facts (architecture, gotchas, setup commands) get extracted and persisted
- Ephemeral details (current task, next steps) stay in `.agentic/context.md` where they belong

<div class="callout">
The hierarchy grows organically. You don't plan it upfront - /wrap builds it from what actually happened in each session.
</div>

---

<!-- _class: lead -->

# Right context. Right level. Right time.

Lean roots, detailed tracks, nothing wasted.

github.com/Space-Dinosaurs/DinoStack
