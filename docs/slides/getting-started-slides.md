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
---

<!-- _class: lead -->

# Getting Started

Install DinoStack and ship your first focused session

---

## Install in two steps

<style scoped>
  pre { font-size: 0.82em; padding: 0.4em 0.8em; margin: 0.2em 0; }
  p { font-size: 0.9em; margin: 0.25em 0; }
</style>

**1.** Open a terminal where you keep your repos and start Claude Code:

```bash
cd ~        # or ~/code, ~/projects, etc.
claude
```

**2.** Paste this into Claude Code:

```
Clone git@github.com:Space-Dinosaurs/DinoStack.git and run .claude/install.sh
```

The agent clones, installs, and walks you through optional tool setup - idempotent, safe to re-run.

---

## Install in two steps (cont.)

<style scoped>
  p { font-size: 0.9em; margin: 0.3em 0; }
  blockquote { font-size: 0.88em; margin: 0.5em 0; padding: 0.4em 0.9em; }
  .callout { font-size: 0.88em; padding: 0.5em 1.1em; margin-top: 0.6em; }
</style>

<div class="callout">
Claude Code is the primary adapter. The installer at <code>.claude/install.sh</code> is idempotent and safe to re-run.
</div>

**Other adapters** use the same pattern - each tool's native format:

> Gemini CLI: `bash .gemini/install.sh`
> Cursor: `.cursor/install.sh`
> Codex CLI: `.codex/install.sh`
> Kimi: `.kimi/install.sh`
> OpenCode: `.opencode/install.sh`

---

## Pick an activation mode

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.2em 0; }
  p { font-size: 0.88em; margin: 0.3em 0; }
</style>

The installer asks one question: how should the methodology activate across your projects?

- **`opt-out` (default)** - active everywhere. Individual projects disable it by adding `agentic-engineering: opt-out` to their root `AGENTS.md`. Best for most users.
- **`opt-in`** - dormant until a project's `AGENTS.md` contains `agentic-engineering: opt-in`. Best for trying the protocol in one project before rolling out everywhere.

Press Enter to accept the default, or pass `--mode=opt-in` / `--mode=opt-out` to the installer. The choice is saved to `~/.claude/agentic-engineering.json` and shared across all adapters - re-run any installer with a `--mode` flag to change it later.

On first activation (TTY only) the preflight prints a one-line notice naming the resolved `mode`, `marker`, `profile`, and `preset`, and points you at `/agentic-status` (resolver dump) and `/agentic-disable` (explicit opt-out; refuses on an existing `opt-in` without `--force`). The notice is gated on a per-project sentinel at `.agentic/.activated`; deleting it re-arms the notice only. `AGENTIC_QUIET=1` suppresses both.

---

## Always run `claude` from the project directory

The **current working directory is the project identity**. Claude Code keys every bit of persistence - memory, AGENTS.md, session history - to the cwd it was started from.

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
  pre { font-size: 0.8em; padding: 0.4em 0.7em; margin: 0.2em 0 0.5em 0; }
  p { margin: 0.3em 0; }
  .callout { font-size: 0.88em; padding: 0.4em 1em; margin-top: 0.4em; }
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

When the goal is done - or clearly won't be done today - run `/wrap`. It does the session-close ritual for non-ticket sessions:

- Produces a structured `.agentic/context.md` with decisions, next steps, and gotchas
- Extracts stable facts and adds them to MEMORY.md
- Updates AGENTS.md with conventions learned this session
- Leaves the next session starting from richer context than this one

<div class="callout">
<code>/wrap</code> is not optional ceremony. Skipping it is how memory drifts, context bloats, and sessions become unshippable.
</div>

<div class="callout">
After <code>/wrap</code>, close the session cleanly. In the terminal CLI, use <code>/exit</code> rather than ctrl+c. In the desktop or web app, <code>/exit</code> is not available - just close the window or tab normally.
</div>

---

## Your first practice loop

<style scoped>
  p.preamble { font-size: 0.78em; font-style: italic; margin: 0.2em 0 0.5em 0; color: #9bb0cc; line-height: 1.4; }
  ol { margin: 0.3em 0; }
  ol li { margin: 0.18em 0; line-height: 1.35; }
  .callout { font-size: 0.82em; padding: 0.4em 0.9em; margin-top: 0.5em; }
</style>

<p class="preamble">One-time setup: in <code>~/.claude/settings.json</code> set <code>defaultMode: "bypassPermissions"</code> with a small denylist of destructive commands. See Hands-off Configuration in the docs.</p>

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

github.com/Space-Dinosaurs/DinoStack
