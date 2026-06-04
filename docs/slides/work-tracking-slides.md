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
<code>.claude/tracking.md</code> is the protocol's pressure release: project-level, free-form instructions the orchestration-planner reads and follows verbatim.
</div>

---

## Where it lives and who reads it

<style scoped>
  pre { font-size: 0.82em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { margin: 0.4em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

File: `.claude/tracking.md` at the project root.

Reader: the **orchestration-planner** agent, during step 7 of its planning process:

```
Check if .claude/tracking.md exists in the project root.
If it does, read it and follow its instructions.
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
  pre { font-size: 0.68em; padding: 0.6em 0.8em; line-height: 1.35; margin: 0.3em 0 0.8em 0; }
  h2 { margin-bottom: 0.4em; }
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
  pre { font-size: 0.78em; padding: 0.55em 0.8em; line-height: 1.35; margin: 0.3em 0 0.8em 0; }
  h2 { margin-bottom: 0.4em; }
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
- **Version control it** - same as `AGENTS.md`, `decisions.md`, and the rest of `.claude/`
- **Scales down cleanly** - no file means no tracker actions, and the planner plans the same way otherwise

<div class="callout">
One file, one reader, one job: give the planner project-specific tracker instructions it can execute during any orchestration. That is the whole surface area.
</div>

---

<!-- _class: lead -->

# One file. Project-specific. Planner-executed.

Tracker flexibility without protocol bloat.

github.com/Space-Dinosaurs/agentic-engineering
