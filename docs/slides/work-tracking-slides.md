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

# Work Tracking

Project-specific tracker instructions the planner actually follows

---

## The problem tracking.md solves

<style scoped>
  ul { font-size: 0.95em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

Every project tracks work differently:

- Some use Linear. Some use Jira. Some use a plain markdown file. Some use nothing.
- Status transitions, comment conventions, QA handoffs, branch naming - all project-specific.
- Baking a single flow into the protocol would force every team to agree - they won't.
- Baking *nothing* in means every session re-explains "how do we track work here?"

<div class="callout">
<code>.agentic/tracking.md</code> is the protocol's pressure release: project-level, free-form instructions the orchestration-planner reads and follows verbatim.
</div>

---

## Where it lives and who reads it

<style scoped>
  pre { font-size: 0.82em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { margin: 0.4em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

File: `.agentic/tracking.md` at the project root (legacy path `.claude/tracking.md` also recognized as fallback).

Reader: the **orchestration-planner** agent, during step 7 of its planning process:

```
Check for .agentic/tracking.md first, then .claude/tracking.md (legacy fallback).
If it exists at either path, read it and follow its instructions.
```

The planner is otherwise strictly read-only. `tracking.md` is the **one file** that can instruct it to run commands (curl a ticket API, update a status, post a comment).

<div class="callout">
No file = no tracker actions. The protocol degrades cleanly for projects that don't care.
</div>

---

## What goes in it

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.22em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

The file is free-form, but a good one tells the planner things like:

- **Where the ticket lives** - Linear team, Jira project, Notion doc, markdown file
- **How to fetch it** - exact CLI command, MCP call, or file path to read
- **How to record planning decisions** - a comment on the ticket, a log file, nothing at all
- **Which status transitions to make and when** - "move to In Progress when architect starts", "move to In QA after Skeptic passes"
- **Who to assign for QA** - user ID, team, or "skip - no QA assignee"
- **What NOT to do** - e.g. "never close a ticket automatically, the PM does that"

<div class="callout">
Treat it as a runbook the planner will literally execute. Vague instructions produce vague behavior.
</div>

---

<!-- _class: highlight -->

## Example - a Linear project

<style scoped>
  pre { font-size: 0.62em; padding: 0.45em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
  h2 { margin-bottom: 0.3em; }
</style>

```markdown
# Work Tracking

This project uses Linear. Ticket IDs look like ENG-1234.

## At planning start
1. Fetch the ticket: mcp__linear__get_issue with the ticket ID
2. Read the Implementation, Files, and QA sections from the description
3. Note blockedBy tickets - confirm they are Done before continuing
4. Transition the ticket to "In Progress" (state ID: abc-123)

## At plan completion (before engineer spawn)
- Post a comment on the ticket with the final phase list and estimated phases

## At Skeptic pass
- Transition the ticket to "In QA"
- Assign QA to user 789-xyz

## Never
- Close the ticket. The PM decides when Done is Done.
```

---

## Example - a project with no external tracker

<style scoped>
  pre { font-size: 0.72em; padding: 0.45em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
  h2 { margin-bottom: 0.3em; }
  p { font-size: 0.88em; margin: 0.2em 0; }
</style>

Not every project has Linear or Jira. `tracking.md` can point at anything:

```markdown
# Work Tracking

No external tracker. Work is captured in docs/worklog.md.

## At planning start
- Append a new section to docs/worklog.md with today's date and the goal.

## At plan completion
- Under that section, write the phase list as a checklist.

## As phases complete
- The engineer will check items off as part of its DONE report.
  The planner does not need to touch the file again after planning.
```

---

## How it composes with the rest of the protocol

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

- **`/init-project`** can seed the file during project setup - you edit it to match your tracker
- **The orchestration-planner** reads it every time it plans a task - no caching, no staleness
- **Every other agent ignores it** - engineer, skeptic, qa-engineer, investigator never touch it
- **Version control it** - same as `AGENTS.md`, `decisions.md`, and other tool-agnostic config in `.agentic/`
- **Scales down cleanly** - no file means no tracker actions, and the planner plans the same way otherwise

<div class="callout">
One file, one reader, one job: give the planner project-specific tracker instructions it can execute during any orchestration. That is the whole surface area.
</div>

---

<!-- _class: lead -->

# One file. Project-specific. Planner-executed.

Tracker flexibility without protocol bloat.

github.com/Space-Dinosaurs/DinoStack
