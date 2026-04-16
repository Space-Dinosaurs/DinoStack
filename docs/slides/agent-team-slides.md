---
marp: true
title: Agent Team
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

# Agent Team

Purpose-built roles. Structured handoffs. Clean context.

---

## Why named agents

- Each agent has a **narrow job** and a clean context
- Specialization produces sharper output than one generalist doing everything
- Isolated worktrees mean their noise never touches your main session
- The protocol picks the right agent for the task so you usually don't have to

<div class="callout">
Think of named agents as a small team of specialists you can dispatch. The main thread is the manager, not the do-er.
</div>

---

<!-- _class: highlight -->

## The team (1/2)

<style scoped>
  .columns-3 { gap: 0.6em; }
  .columns-3 .card { padding: 0.55em 0.75em; font-size: 0.68em; border-radius: 8px; line-height: 1.3; }
  .columns-3 .card strong { font-size: 1.1em; }
  .columns-3 .card:nth-child(1) { border-left-color: #1e88e5; }
  .columns-3 .card:nth-child(2) { border-left-color: #e53935; }
  .columns-3 .card:nth-child(3) { border-left-color: #8e24aa; }
  .columns-3 .card:nth-child(4) { border-left-color: #00897b; }
  .columns-3 .card:nth-child(5) { border-left-color: #43a047; }
  .columns-3 .card:nth-child(6) { border-left-color: #fb8c00; }
  .columns-3 .card:nth-child(7) { border-left-color: #00acc1; }
  h2 { margin-bottom: 0.4em; }
  .tier { font-size: 0.85em; color: #888; margin-top: 0.3em; }
</style>

<div class="columns-3">
<div class="card"><strong>investigator</strong><br/>Maps unfamiliar code. Traces data flow and blast radius before you change anything.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>debugger</strong><br/>Root cause analysis. Given a failure, returns a diagnosis and fix brief.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>orchestration-planner</strong><br/>Picks the team. Given a goal, produces a structured execution plan.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>architect</strong><br/>Pre-implementation design. Reads the codebase, reads <code>.claude/findings.md</code> at plan time, returns a structured technical plan.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>engineer</strong><br/>Implements the change. Reads conventions, writes code, writes module manifests, adds regression tests for Critical/Major fixes, runs quality gates.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>skeptic</strong><br/>Adversarial reviewer. Classifies findings Critical / Major / Minor. Checks module manifests and regression tests.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>qa-engineer</strong><br/>Browser verification. Fires on UI-visible diffs after Skeptic sign-off.<div class="tier">Default Tier: 1</div></div>
</div>

---

<!-- _class: highlight -->

## The team (2/2)

<style scoped>
  .columns-3 { gap: 0.6em; }
  .columns-3 .card { padding: 0.55em 0.75em; font-size: 0.68em; border-radius: 8px; line-height: 1.3; }
  .columns-3 .card strong { font-size: 1.1em; }
  .columns-3 .card:nth-child(1) { border-left-color: #c62828; }
  .columns-3 .card:nth-child(2) { border-left-color: #3949ab; }
  .columns-3 .card:nth-child(3) { border-left-color: #558b2f; }
  .columns-3 .card:nth-child(4) { border-left-color: #6d4c41; }
  .columns-3 .card:nth-child(5) { border-left-color: #37474f; }
  .columns-3 .card:nth-child(6) { border-left-color: #f4511e; }
  h2 { margin-bottom: 0.4em; }
  .tier { font-size: 0.85em; color: #888; margin-top: 0.3em; }
</style>

<div class="columns-3">
<div class="card"><strong>security-auditor</strong><br/>OWASP-structured review. Auth, secrets, injection, privilege escalation.<div class="tier">Default Tier: 3</div></div>
<div class="card"><strong>adr-generator</strong><br/>Writes decision records. Captures the why behind architectural choices.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>adr-drift-detector</strong><br/>Audits codebase compliance against Architecture Decision Records.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>perf-analyst</strong><br/>Profiles CPU, memory, and latency hotspots. Returns a measured findings brief; does not implement fixes.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>release-orchestrator</strong><br/>End-to-end release sequencing. Pre-flight gates, version bump, tag, deploy, post-deploy verification.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>dependency-auditor</strong><br/>Supply-chain review. CVE scanning, license compliance, lockfile analysis across all ecosystems.<div class="tier">Default Tier: 1</div></div>
</div>

---

## How they work alone

- Spawned into their own **isolated worktree** - their own files, their own context
- Given a **structured brief** - goal, constraints, acceptance criteria, non-goals
- Do their narrow job and return a **structured result** - not raw transcript
- Only `engineer` writes files; every other specialist returns findings or plans

<div class="callout">
The main thread never sees their raw work - only their conclusion. That's the whole point: heavy work without heavy context.
</div>

---

## How they work together - standard feature

```
architect (plan)
    v
skeptic (plan review)       <- sign-off required
    v
engineer (implement)
    v
skeptic (code review)       <- sign-off required
    v
qa-engineer (verify)        <- conditional: UI-visible diff
    v
done
```

Plans get reviewed before code. Code gets reviewed before QA. Each stage hands off a structured artifact.

---

## The Skeptic agent is special

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- **Always a fresh spawn.** Never resumed, never continued from a prior round.
- A resumed Skeptic has seen its own previous criticism - it gets polite and misses things.
- Fresh context = adversarial teeth.
- Classifies findings Critical / Major / Minor. Critical blocks sign-off. Major requires action or a justified waiver.
- **Two new obligations:** (1) flags missing/stale module manifests on non-trivial files as Major; (2) verifies regression tests exist for any Critical/Major fix before granting sign-off.
- **Domain fit comes from the adversarial brief**, not the agent. The conductor writes a brief tailored to the change - auth flow, migration, perf regression - and the Skeptic reviews through that lens.

<div class="callout">
The Skeptic brings the teeth. The adversarial brief aims them - at auth, at a migration, at a perf regression - so a generic reviewer produces domain-sharp findings.
</div>

---

## The planner's planner

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- `orchestration-planner` is a **meta-agent** - it plans which other agents to spawn and in what order
- Given a goal, it returns: agent roster, phased execution plan, Skeptic checkpoints, parallelization map, open questions
- It does not implement anything - planning only
- Output is a structured plan the conductor follows directly

<div class="callout">
Default step: after an architect plan clears Skeptic review, run the orchestration-planner before spawning any workers on a multi-unit plan. See the Orchestration Planner deck for the full protocol.
</div>

---

## Conditional gates and composed flows

<style scoped>
  .columns { font-size: 0.85em; }
  .columns pre { font-size: 0.85em; padding: 0.5em 0.8em; }
  .columns p { margin: 0.3em 0; }
  .columns strong { font-size: 1em; }
</style>

<div class="columns">
<div>

**Bug or broken test**

```
debugger (diagnose)
    v
engineer (fix)
    v
skeptic (review)
    v
done
```

If debugger confidence is Low, escalate to the human - don't fix blind.

</div>
<div>

**Security-sensitive change**

```
architect -> skeptic
    v
engineer -> skeptic
    v
security-auditor
    v
qa-engineer (if UI)
    v
done
```

Auth, payments, secrets, user data all route through the auditor.

</div>
</div>

---

## When to invoke manually vs let the protocol choose

<style scoped>
  .columns { font-size: 0.88em; }
  .columns ul { margin: 0.3em 0; }
  .columns li { margin: 0.2em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="columns">
<div>

**Let the protocol choose (default)**
- You describe the goal in plain English
- Risk classification + orchestration-planner picks the right team
- This is the 90% case

</div>
<div>

**Invoke manually**
- You need a specific second opinion ("have the security-auditor look at this")
- You want to force a Skeptic pass on recent changes: `/skeptic`
- You want architecture first: ask for the architect explicitly

</div>
</div>

<div class="callout">
Manual invocation is an override, not the default interface. Trust the protocol first.
</div>

---

<!-- _class: lead -->

# A team of specialists. One manager.

Named agents do the work. You review the output and decide.

github.com/Solara6/agentic-engineering
