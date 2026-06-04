---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    background: #faf8f3;
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
    border-radius: 12px;
    padding: 1.2em;
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
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
  }
  blockquote {
    border-left: 4px solid #b5451f;
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
One-time per repo. Seeds AGENTS.md, captures conventions, bootstraps memory.
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

The **cwd is the project directory**. Every bit of persistence - AGENTS.md, MEMORY.md, session history, `/wrap` outputs - is keyed to the directory `claude` was started in. Nothing else matters for memory continuity.

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
5. **Same cwd** next time - Claude Code reads the same memory and AGENTS.md automatically
6. Next session starts with richer AGENTS.md, fuller MEMORY.md, sharper defaults
7. Repeat - each loop is a step up, not a reset

<div class="callout">
The whole system is designed around one bet: <strong>context hygiene beats raw model smarts</strong>. Respect the loop and it pays back every session after the first.
</div>

---

<!-- _class: highlight -->

## Two layers of session capture

<style scoped>
  .columns { font-size: 0.85em; margin-bottom: 0.8em; }
  .columns .card { padding: 0.7em 1em; font-size: 0.92em; }
  p { font-size: 0.85em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

<div class="columns">
<div class="card">
<strong>Stop hook (automatic)</strong><br/>
Fires after every turn. Writes <code>context.md</code> with recent user messages, files touched, uncommitted changes, and tools used. Zero ceremony - it just runs.
</div>
<div class="card">
<strong>/wrap (on demand)</strong><br/>
Replaces the stop hook's raw snapshot with a structured, enriched version. Captures decisions, conventions, and gotchas into AGENTS.md and memory. Merges across sessions.
</div>
</div>

<p style="margin-top: 0.8em;">If <code>/wrap</code> has already written <code>context.md</code>, the stop hook <strong>appends</strong> a Session Activity block instead of overwriting - so <code>/wrap</code> content is never lost.</p>

<div class="callout">
The stop hook is the safety net - you always get <em>something</em>. <code>/wrap</code> is the upgrade - you get structured, compounding context.
</div>

<div class="callout">
Close the session cleanly so the Stop hook can finish writing <code>context.md</code>. In the terminal CLI, use <code>/exit</code> rather than ctrl+c (ctrl+c can interrupt the hook and lose session state). In the desktop or web app, <code>/exit</code> is not available - just close the window or tab normally rather than force-quitting.
</div>

---

## Multiple sessions and the rolling window

<style scoped>
  p { font-size: 0.88em; margin: 0.3em 0; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

You can run **multiple sessions in parallel** - open separate terminals, each with `claude` in the same project directory. They share the same persistent memory and AGENTS.md.

When you `/wrap` each session, they merge into a shared `context.md` using a **rolling window of five slots** (Session A through E):

- First wrap writes Session A. Second wrap labels the existing as A, adds B.
- At five sessions, the oldest (A) drops off and everything shifts down.
- Non-focus sections (next steps, file paths, gotchas) merge across all sessions - duplicates removed.

This means you can work on five parallel streams in a project and `/wrap` each one. The next session that starts sees a merged view of all recent work.

<div class="callout">
The rolling window keeps context.md bounded. Five slots is enough to capture active workstreams without drowning the next session in stale history.
</div>

---

<!-- _class: lead -->

# Keep context clean. Let it compound.

Focused sessions. Same project dir. `/wrap` every time.

github.com/Solara6/agentic-engineering
