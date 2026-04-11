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

# Context Management

Why it's the bottleneck - and how the protocol keeps you out of it

---

## Context is the bottleneck - not the model

- The model is usually fine. Your **context** is the problem.
- Long sessions accumulate irrelevant noise - old plans, dead branches, raw tool output
- More tokens is not more smart. It is more confused.
- Fresh sessions with zero context forget everything useful you already learned
- **Two separate failure modes, one root cause:** bad context hygiene

<div class="callout">
Context rot mid-session and amnesia across sessions are the same problem at two timescales.
</div>

---

<!-- _class: highlight -->

## The two failure modes

<div class="columns">
<div class="card">
<strong>In-session: context rot</strong><br/><br/>
Session starts sharp. Hours in, the agent is slower, repeats itself, loses the plot, re-reads files it already knows. The context window is full of stale noise crowding out what matters.
</div>
<div class="card">
<strong>Across sessions: amnesia</strong><br/><br/>
Every new chat starts from zero. Hard-won conventions, past decisions, and project quirks die with the last session. You re-explain the same things, forever.
</div>
</div>

---

## Fighting in-session rot

<div class="columns">
<div>

**Subagent delegation**
Heavy work (research, reviews, investigations) runs in a sub-thread. Only a structured summary returns to the main context.

**Worktree isolation**
Workers get their own clean slate. Their reads, failed attempts, and raw tool output never touch your main session.

</div>
<div>

**Focused sessions**
One goal = narrow context. The protocol actively resists scope creep because scope creep is context creep.

**Risk classification**
Small stuff stays direct and cheap. Big stuff is delegated out. Neither bloats the main thread.

</div>
</div>

---

## Fighting cross-session amnesia

<style scoped>
  .columns-3 .card { padding: 0.8em 1em; font-size: 0.85em; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="columns-3">
<div class="card">
<strong>/init-project</strong><br/>
One-time per repo. Seeds CLAUDE.md, captures conventions, bootstraps memory.
</div>
<div class="card">
<strong>Same project dir</strong><br/>
<code>cwd</code> is the project identity. Running <code>claude</code> from the same directory always reads the same persistent memory.
</div>
<div class="card">
<strong>/wrap</strong><br/>
End-of-session ritual. Commits learnings into memory so the next session reads richer context than this one.
</div>
</div>

<div class="callout">
<code>/init-project</code> -> work -> <code>/wrap</code> -> next session from the same dir is a <strong>feedback loop</strong>. Each run starts smarter than the last.
</div>

---

## The load-bearing habit: run from the project directory

The **cwd is the project directory**. Every bit of persistence - CLAUDE.md, MEMORY.md, session history, `/wrap` outputs - is keyed to the directory `claude` was started in. Nothing else matters for memory continuity.

```bash
cd ~/code/myproject
claude
```

Same directory every time = same persistent memory every time. That's the whole mechanism.

<div class="callout">
Session naming (<code>-n myproject</code>) and resumption (<code>-r</code>) are optional ergonomics - labels and recovery tools, not memory mechanisms. The real load-bearing habit is the <code>cd</code>.
</div>

---

## The compounding loop

<style scoped>
  ol { font-size: 0.9em; }
  ol li { margin: 0.2em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

1. **`/init-project`** seeds baseline context for a repo
2. You work a focused session - one clear goal
3. Heavy lifting is delegated so the main thread stays clean
4. **`/wrap`** commits learnings into memory
5. **Same cwd** next time - Claude Code reads the same memory and CLAUDE.md automatically
6. Next session starts with richer CLAUDE.md, fuller MEMORY.md, sharper defaults
7. Repeat - each loop is a step up, not a reset

<div class="callout">
The whole system is designed around one bet: <strong>context hygiene beats raw model smarts</strong>. Respect the loop and it pays back every session after the first.
</div>

---

<!-- _class: lead -->

# Keep context clean. Let it compound.

Focused sessions. Same project dir. `/wrap` every time.

github.com/Solara6/agentic-engineering
