---
marp: true
title: Orchestration Planner
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    background: #faf8f3;
    font-size: 26px;
    padding: 50px 60px;
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

# Orchestration Planner

The agent that plans other agents.

---

## The planning gap

- Complex goals have non-obvious team composition
- The conductor's attention is the scarce resource - don't spend it on decomposition
- **Antipattern:** conductor self-assesses parallelization mid-task, gets sequencing wrong, reclassifies halfway through
- Reclassification mid-execution is expensive: lost context, restarted agents, broken handoffs

<div class="callout">
The orchestration-planner exists so the conductor delegates composition reasoning, not just execution. Think before you spawn.
</div>

---

## When to invoke

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

Invoke the orchestration-planner when any of these are true:

- **Complex goal** - the task involves multiple distinct work units
- **Non-obvious team** - it is not clear which agents are needed or in what order
- **Multiple phases** - design, implement, review, verify each depend on prior output
- **Avoid mid-task reclassification** - you want sequencing locked before spawning workers

<div class="callout">
Default step: after an architect or investigator returns a plan and the Skeptic signs off, run the orchestration-planner before spawning any workers. Skip only when the architect already returned a single atomic unit.
</div>

---

<!-- _class: highlight -->

## What it returns

<style scoped>
  .columns { font-size: 0.82em; gap: 1em; }
  .columns ul { margin: 0.2em 0; }
  .columns li { margin: 0.15em 0; }
  h2 { margin-bottom: 0.4em; }
</style>

<div class="columns">
<div>

**Plan structure**
- **Task summary** - goal + why this team was chosen
- **Risk classification** - Low / Elevated / Elevated + Cleanup
- **Agent roster** - agents and their specific role
- **Execution plan** - phased: spawn, give, returns, proceed-when

</div>
<div>

**Review + coordination**
- **Skeptic checkpoints** - what each reviews, what constitutes a pass
- **Parallelization opportunities** - which phases run concurrently and why
- **Conductor actions** - decisions, memory updates, context synthesis between phases
- **Open questions** - ambiguities needing human input before execution

</div>
</div>

---

## Orchestration-planner vs architect

<style scoped>
  .columns { font-size: 0.88em; }
  .columns ul { margin: 0.2em 0; }
  .columns li { margin: 0.18em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="columns">
<div>

**Architect**
- Designs the code for one task
- Reads the codebase, maps the change
- Returns a technical plan: data model, API shape, file sequence
- Scope: a single implementation unit

</div>
<div>

**Orchestration-planner**
- Designs the execution flow for many agents
- Reads the goal and the architect's plan
- Returns an agent sequence: who, what order, what hand-offs
- Scope: the full multi-agent campaign

</div>
</div>

<div class="callout">
Standard sequence: architect → skeptic-of-architect → orchestration-planner → worker phases
</div>

---

<!-- _class: highlight -->

## A worked example

<style scoped>
  .columns { font-size: 0.78em; gap: 1.2em; }
  .columns ul { margin: 0.15em 0; }
  .columns li { margin: 0.12em 0; }
  h2 { margin-bottom: 0.35em; }
  p { font-size: 0.78em; margin: 0.2em 0; }
</style>

*Illustrative example* - goal: "Add a /skill-audit slash command with tests and docs"

<div class="columns">
<div>

**Plan output**
- Risk: Elevated (new files, multi-file)
- Phase 1 (sequential): architect - design command structure
- Phase 2 (sequential): skeptic - review architect plan
- Phase 3 (parallel): engineer A - implementation; engineer B - docs
- Phase 4 (sequential): integration skeptic - reviews combined diff

</div>
<div>

**Key planner decisions**
- Docs and implementation are independent - safe to parallelize
- One integration Skeptic covers both, not two stacked Skeptics
- Skeptic checkpoint: no Critical/Major before marking complete
- Open questions: none - architect plan fully specified inputs

</div>
</div>

---

## Parallelization in practice

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- **Independent workstreams with no shared state** can run concurrently
- **Shared state or sequential dependencies** (architect before engineer, debugger before fix) must stay sequential
- Identify dependencies first - parallelization is the residual, not the default

**Skeptic placement rules:**
- Independent elevated units - each gets its own Skeptic
- Interdependent elevated units - one integration Skeptic reviews the combined diff
- Stacked per-unit Skeptics on interdependent changes produce false signal

<div class="callout">
One integration Skeptic, not stacked Skeptics. The planner identifies unit boundaries so the conductor applies the right rule.
</div>

---

<!-- _class: lead -->

# Delegate composition, not just execution.

The orchestration-planner does the structural reasoning so the conductor doesn't have to.

github.com/Solara6/agentic-engineering
