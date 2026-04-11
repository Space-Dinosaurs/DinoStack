---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: white;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
    color: white;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #f8f9fa;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5em;
  }
  .columns-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1em;
  }
  .card {
    background: white;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #0f3460;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #0f3460;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #e8f4f8;
    border-left: 4px solid #0f3460;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.5em 0;
  }
  blockquote {
    border-left: 4px solid #0f3460;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# Agentic Engineering

A protocol for shipping software with AI agents

---

## What it is

- A **portable methodology** for AI-assisted software development
- Loaded as a skill - it shapes how your agent plans, implements, and reviews code
- Mostly **passive**: you don't drive it with commands
- Risk-aware delegation, adversarial review, focused sessions
- Tool-agnostic: Claude Code, Cursor, and more

<div class="callout">
Not a framework you call into. A living protocol that shapes every response, every task, every review - in the background.
</div>

---

## What a typical session feels like

1. You state a goal in plain English - "fix the bug in X", "add feature Y"
2. The agent **classifies risk automatically** - small edit vs. real change
3. Small stuff is handled directly, in the conversation
4. Bigger stuff spawns a Worker in an isolated worktree, then a Skeptic review
5. You read the summary and decide: ship, revise, or drop

<div class="callout">
No commands required. The protocol runs itself - you just describe what you want.
</div>

---

<!-- _class: highlight -->

## What you actually get

<div class="columns">
<div class="card">
<strong>Fewer regressions</strong><br/>
Nothing meaningful merges without an adversarial Skeptic pass. Critical findings block.
</div>
<div class="card">
<strong>Focused sessions</strong><br/>
One goal per session. Explicit handoffs. Context stays narrow, output stays sharp.
</div>
<div class="card">
<strong>Better reviews</strong><br/>
Every non-trivial change ships with a pre-mortem, a review brief, and a classified findings list.
</div>
<div class="card">
<strong>Institutional memory</strong><br/>
Learnings, conventions, and decisions persist across sessions instead of dying with the chat.
</div>
</div>

---

## A small command surface

| Command | When you'd reach for it |
|---|---|
| `/init-project` | One-time setup when bringing the protocol into a repo |
| `/implement` | Explicitly hand a task to a Worker |
| `/skeptic` | Force a review pass on recent changes |
| `/wrap` | Close out a session: commit, PR, memory, cleanup |
| `/memory-update` | Persist a learning you want to keep |

<div class="callout">
Most sessions don't invoke any of these. Commands are accents, not the interface.
</div>

---

## Under the hood - risk classification

<div class="columns">
<div>

**Direct action**
- Reads, answering from memory
- Screenshots, diagnostic logging
- Small, reversible edits
- Handled in the main thread

</div>
<div>

**Elevated**
- Writing or changing code
- Multi-file changes, migrations
- Spawns Worker + Skeptic in the background
- Review loop runs automatically

</div>
</div>

<div class="callout">
When in doubt, the agent classifies <strong>Elevated</strong>. The cost of a review is cheap; the cost of a bad change is not.
</div>

---

## Under the hood - the agent team

<style scoped>
  .columns-3 { gap: 0.6em; }
  .columns-3 .card { padding: 0.6em 0.8em; font-size: 0.75em; border-radius: 8px; }
  .columns-3 .card strong { font-size: 1.05em; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.6em; }
</style>

<div class="columns-3">
<div class="card"><strong>investigator</strong><br/>Maps unfamiliar code</div>
<div class="card"><strong>debugger</strong><br/>Root-cause analysis</div>
<div class="card"><strong>orchestration-planner</strong><br/>Picks the team and sequencing</div>
<div class="card"><strong>architect</strong><br/>Designs before coding</div>
<div class="card"><strong>engineer</strong><br/>Implements changes</div>
<div class="card"><strong>skeptic</strong><br/>Adversarial review</div>
<div class="card"><strong>qa-engineer</strong><br/>Runtime verification</div>
<div class="card"><strong>security-auditor</strong><br/>Threat modeling</div>
<div class="card"><strong>adr-generator</strong><br/>Decision records</div>
</div>

<div class="callout">
Each role has a narrow job. The protocol picks the right one for the task - you don't have to.
</div>

---

<!-- _class: lead -->

# Ship with confidence

Risk-aware delegation. Adversarial review. Focused sessions.
Mostly passive - just describe the work.

github.com/Solara6/agentic-engineering
