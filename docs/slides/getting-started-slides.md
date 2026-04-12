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
    margin: 0.4em 0 0.8em 0;
  }
  blockquote {
    border-left: 4px solid #0f3460;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# Getting Started

Install agentic-engineering and ship your first focused session

---

## Install in two steps

**1.** Open a terminal where you keep your repos and start Claude Code:

```bash
cd ~        # or ~/code, ~/projects, etc.
claude
```

**2.** Paste this into Claude Code:

```
Clone git@github.com:Solara6/agentic-engineering.git and run .claude/install.sh
```

The agent clones the repo, runs the installer, and walks you through optional tool setup. Idempotent - safe to re-run anytime.

---

## Always run `claude` from the project directory

The **current working directory is the project identity**. Claude Code keys every bit of persistence - memory, CLAUDE.md, session history - to the cwd it was started from.

```bash
cd ~/code/myproject
claude
```

That's the whole mechanism. Same project dir = same memory, automatically.

<div class="callout">
Optional ergonomic tip: add <code>-n myproject</code> to label the session. It shows up in the <code>/resume</code> picker and your terminal title - handy for finding sessions later, but it doesn't affect memory.
</div>

---

## First move in a real repo - `/init-project`

<style scoped>
  pre { font-size: 0.8em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { margin: 0.4em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

From inside the repo, start Claude Code and run `/init-project`:

```bash
cd ~/code/myproject
claude
```
```
/init-project
```

A **one-time, per-repo** setup. Bootstraps project memory, captures conventions, and seeds the risk defaults so the protocol knows what "normal" looks like here.

<div class="callout">
Do this once per repo, before you start delegating real work. Skip it and the agent runs blind.
</div>

---

<!-- _class: highlight -->

## The single most important habit - focused sessions

<div class="columns">
<div>

**One session = one goal**

- State the goal clearly at the start
- Resist scope creep
- If new work appears, note it, save it for next session
- Short, explicit, reviewable

</div>
<div>

**Why it matters**

- Context stays narrow, output stays sharp
- Reviews stay scoped
- Memory captures one clean learning per session
- You can actually ship

</div>
</div>

<div class="callout">
Focused sessions are the single biggest force multiplier. The protocol assumes you'll keep context narrow - fight the urge to pile on.
</div>

---

## Close every session with `/wrap`

<style scoped>
  pre { font-size: 0.8em; padding: 0.4em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { margin: 0.4em 0; }
  ul { margin: 0.3em 0; }
  li { margin: 0.15em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

When the goal is done - or clearly won't be done today - run `/wrap`. It does the closing ritual so you don't have to:

- Commits the work and opens a PR
- Cleans up the worktree
- Captures learnings into memory
- Marks the session done so next time starts fresh

<div class="callout">
<code>/wrap</code> is not optional ceremony. Skipping it is how memory drifts, context bloats, and sessions become unshippable.
</div>

---

## Your first practice loop

1. Pick a **small, real** task in a repo where you've run `/init-project`
2. Start a fresh `claude` session in that repo
3. State the goal in one sentence - resist adding "and also..."
4. Let the agent classify risk and run the loop (no commands needed)
5. Read the Skeptic review, decide: ship, revise, or drop
6. Run `/wrap` - even if the answer was "drop it"
7. Repeat tomorrow with a new small task

<div class="callout">
First few sessions feel slower than "just doing it." That's the trade - raw speed for reviewable, shippable, memorable work.
</div>

---

<!-- _class: lead -->

# Small sessions. Clear goals. `/wrap` every time.

That's the whole practice.

github.com/Solara6/agentic-engineering
