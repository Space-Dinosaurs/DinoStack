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
  .numbered {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5em 0.9em;
    align-items: baseline;
    margin: 0.3em 0 0.6em 0;
  }
  .numbered .n {
    font-weight: bold;
    color: #b5451f;
    font-size: 1.1em;
  }
---

<!-- _class: lead -->

# Autonomy

Act, don't ask. Pick the best default, note the choice, proceed.

---

## The default is to proceed

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- The conductor's default is **to act, not to ask**
- If a next step is non-destructive and within the conductor's authority, it gets done - no "want me to draft X next?" pause
- Design-taste calls (naming, style, choice among libraries already in use, "which of several reasonable approaches") are resolved by the conductor, not surfaced to the operator
- The operator is invoked to complete the goal, not to approve every step

<div class="callout">
Asking permission to fix a broken test, create a missing import, or look something up is the conductor abdicating. If the work is in scope and within reason, do it and report what was done.
</div>

---

## The 5-source default hierarchy

<style scoped>
  .numbered { font-size: 0.85em; }
  .numbered .n { font-size: 1.0em; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Every time the conductor is tempted to ask, it first tries to derive a default by consulting, in order:

<div class="numbered">
<div class="n">1</div><div>Existing codebase patterns in files adjacent to the change</div>
<div class="n">2</div><div>Prior decisions in <code>MEMORY.md</code> and the project's decision log</div>
<div class="n">3</div><div>The architect's plan and any orchestration-planner output</div>
<div class="n">4</div><div>Established conventions in <code>AGENTS.md</code> and any track-level <code>AGENTS.md</code></div>
<div class="n">5</div><div>The most conservative interpretation of the ticket text (minimize blast radius, commit to the fewest future decisions)</div>
</div>

**First-match-wins.** Stop at the first source that yields a default. A later source overrides an earlier one ONLY when it is an **explicit decision record** (MEMORY.md entry, AGENTS.md convention, prior ADR) that supersedes the pattern.

<div class="callout">
If any source yields a reasonable default, the conductor proceeds and notes the choice: "Picked X because of Y; flag if wrong." It does NOT pause.
</div>

---

## Hard-stop vs surface-and-proceed

<style scoped>
  .columns { gap: 1.2em; }
  .columns .card { font-size: 0.82em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
  blockquote { font-size: 0.82em; margin: 0.4em 0; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #c62828;">
<strong>Hard-stop branch</strong><br/>
MUST stop and wait for an explicit user response.<br/><br/>
Fires when the decision would produce <strong>irreversible state</strong>: data loss, force push, schema migration, production deploy, sending external messages, spending money.<br/><br/>
Never overridden by default-and-proceed. A recommended default may be offered, but the conductor does not proceed until the user replies.
</div>
<div class="card" style="border-left-color: #43a047;">
<strong>Surface-and-proceed branch</strong><br/>
Non-irreversible. Used when ALL hold:<br/>
- No default can be derived from the five sources<br/>
- Guessing wrong would waste more than 30 minutes<br/>
- The question is specific and bounded<br/><br/>
Surface the question with a recommended default AND proceed with that default in the same turn.
</div>
</div>

<div class="callout">
Mandatory phrasing for surface-and-proceed: <em>"Proceeding with approach A (matches existing pattern in src/foo.ts) unless you say otherwise."</em>
</div>

---

## Carve-outs

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.78em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

<div class="columns-3">
<div class="card">
<strong>Open Questions</strong><br/>
An architect-declared "Open Questions" section is a <strong>protocol-level blocker</strong>. Conductor-derived defaults do NOT close an Open Question. Resolve by re-spawning the architect, asking the user the specific question, or descoping.
</div>
<div class="card">
<strong>Explicit command directives</strong><br/>
Command files under <code>content/commands/</code> that contain their own "stop and ask" directives are controlling for that decision. Example: <code>implement-ticket.md</code>'s BASE_BRANCH stop-and-ask when neither <code>develop</code> nor <code>development</code> exists.
</div>
<div class="card">
<strong>Agent-spec-mandated human decisions</strong><br/>
When an agent's spec mandates surfacing a decision to the human (e.g. <code>release-orchestrator</code>'s rollback-vs-fix-forward decision), that spec overrides the autonomy contract. The Worker follows its spec and surfaces the decision.
</div>
</div>

<div class="callout">
These three carve-outs sit above default-and-proceed. When one fires, the conductor does not try to derive a default - it follows the carve-out.
</div>

---

## Worker autonomy contract

<style scoped>
  blockquote { font-size: 0.82em; line-height: 1.45; margin: 0.5em 0; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

Every Worker brief (engineer or other implementer) must include this clause:

> "Resolve design-taste ambiguity by choosing the option most consistent with surrounding code. Return BLOCKED only for hard blockers: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict. Do not return BLOCKED for style, naming, choice among libraries already in use in this project, or 'which of several reasonable approaches' questions - pick one, proceed, and note the choice in the return summary. Introducing a new runtime dependency or performing a major-version upgrade of an existing dependency is NOT within this contract - if the task requires either, return BLOCKED so the conductor can route through architect + dependency-auditor per the risk table."

<div class="callout">
Design-taste BLOCKED returns are a contract violation. New-dep / major-upgrade BLOCKED returns are the correct behavior - those route to architect + dependency-auditor, not conductor-direct.
</div>

---

## Three paths for any decision

<style scoped>
  .columns-3 { gap: 0.9em; }
  .columns-3 .card { font-size: 0.74em; line-height: 1.38; padding: 0.7em 0.9em; }
  .columns-3 .card strong { font-size: 1.0em; }
  .columns-3 .card ul { margin: 0.3em 0 0 0; padding-left: 1.1em; }
  .columns-3 .card ul li { margin: 0.18em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #43a047;">
<strong>Proceed autonomously</strong>
<ul>
<li>Fixing a broken test discovered during work</li>
<li>Creating an obvious dependency (missing import, type def, upstream endpoint)</li>
<li>Looking something up</li>
<li>Design preference, stylistic choice</li>
<li>Which of several reasonable approaches</li>
<li>Choice among libraries already in use at a specific call site</li>
<li>Next unit of a multi-unit plan</li>
</ul>
</div>
<div class="card" style="border-left-color: #f9a825;">
<strong>Route to specialist</strong>
<ul>
<li>Introducing a new runtime dependency</li>
<li>Major-version upgrade of an existing dependency</li>
</ul>
<br/>
Not conductor-direct and not default-and-proceed. Worker returns BLOCKED; conductor routes to architect + dependency-auditor per the risk table.
</div>
<div class="card" style="border-left-color: #c62828;">
<strong>Stop and ask the user</strong>
<ul>
<li>Destructive or irreversible action not pre-authorized</li>
<li>Credential, external API key, product judgment only the user can make</li>
<li>A name only the user knows</li>
<li>Architect-declared Open Question</li>
<li>Declared scope is complete and expansion needs approval</li>
</ul>
</div>
</div>

<div class="callout">
The middle column is not a stop for the user - it's a stop for the conductor, which then spawns the right specialists.
</div>

---

## Stop-frequency is a planning signal

<style scoped>
  table { font-size: 0.82em; margin: 0.4em 0; }
  th, td { padding: 0.4em 0.7em; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Repeated genuine blockers within a task indicate the **plan is under-specified**, not that the conductor is being appropriately cautious.

| Task shape | Max genuine stops before flagging the plan |
|---|---|
| Trivial or single-unit | 0 - one blocker means it was not well-scoped |
| Single-unit Elevated | 1 |
| Multi-unit plan (2-5 units) | 2 across the whole plan |
| Large multi-unit plan (6+ units) | 3 across the whole plan |

When the threshold is exceeded, the conductor stops spawning Workers and surfaces a **planning concern** to the operator - options are re-spawn architect, answer open questions upfront and resume, or descope.

<div class="callout">
Piecemeal questions past the threshold paper over a structural gap and burn operator attention. Flag the plan; don't keep asking.
</div>

---

<!-- _class: lead -->

# Pick the best default. Note the choice. Proceed.

Act within authority. Stop only for irreversible state or genuine unknowns.

github.com/Space-Dinosaurs/agentic-engineering
