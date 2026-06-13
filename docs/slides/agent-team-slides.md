---
marp: true
title: Agent Team
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
  .columns-3 .card:nth-child(1) { border-left-color: #4ea3ff; }
  .columns-3 .card:nth-child(2) { border-left-color: #ff5d73; }
  .columns-3 .card:nth-child(3) { border-left-color: #b06bff; }
  .columns-3 .card:nth-child(4) { border-left-color: #2fd4c4; }
  .columns-3 .card:nth-child(5) { border-left-color: #3ad99a; }
  .columns-3 .card:nth-child(6) { border-left-color: #ff9d4d; }
  .columns-3 .card:nth-child(7) { border-left-color: #2fd4c4; }
  h2 { margin-bottom: 0.4em; }
  .tier { font-size: 0.85em; color: #6a7c97; margin-top: 0.3em; }
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
  .columns-3 .card:nth-child(1) { border-left-color: #ff5d73; }
  .columns-3 .card:nth-child(2) { border-left-color: #7c8cff; }
  .columns-3 .card:nth-child(3) { border-left-color: #3ad99a; }
  .columns-3 .card:nth-child(4) { border-left-color: #c79a86; }
  .columns-3 .card:nth-child(5) { border-left-color: #8aa0b5; }
  .columns-3 .card:nth-child(6) { border-left-color: #ff9d4d; }
  .columns-3 .card:nth-child(7) { border-left-color: #b06bff; }
  .columns-3 .card:nth-child(8) { border-left-color: #2fd4c4; }
  .columns-3 .card:nth-child(9) { border-left-color: #ff7a5d; }
  h2 { margin-bottom: 0.4em; }
  .tier { font-size: 0.85em; color: #6a7c97; margin-top: 0.3em; }
</style>

<div class="columns-3">
<div class="card"><strong>security-auditor</strong><br/>OWASP-structured review. Auth, secrets, injection, privilege escalation.<div class="tier">Default Tier: 3</div></div>
<div class="card"><strong>adr-generator</strong><br/>Writes decision records. Captures the why behind architectural choices.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>adr-drift-detector</strong><br/>Audits codebase compliance against Architecture Decision Records.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>perf-analyst</strong><br/>Profiles CPU, memory, and latency hotspots. Returns a measured findings brief; does not implement fixes.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>release-orchestrator</strong><br/>End-to-end release sequencing. Pre-flight gates, version bump, tag, deploy, post-deploy verification.<div class="tier">Default Tier: 2</div></div>
<div class="card"><strong>dependency-auditor</strong><br/>Supply-chain review. CVE scanning, license compliance, lockfile analysis across all ecosystems.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>learning-extractor</strong><br/>Per-ticket learning extraction at Phase 6 clean exit. Reads resolved findings_log and writes fix-pattern entries to .agentic/learnings.md.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>wrap-ticket</strong><br/>Per-ticket learnings capture at Phase 11b (PR open). Appends durable learnings to MEMORY.md, decisions.md, and .agentic/context.md.<div class="tier">Default Tier: 1</div></div>
<div class="card"><strong>learnings-agent</strong><br/>Session-scoped background learnings capture. Receives learning events in real-time and writes structured entries to .agentic/learnings.md immediately.<div class="tier">Default Tier: 1</div></div>
</div>

---

## How they work alone

- Spawned into their own **isolated worktree** - their own files, their own context
- Given a **structured brief** - goal, constraints, acceptance criteria, non-goals
- Do their narrow job and return a **structured result** - not raw transcript
- Most agents are read-only analysis/planning. `engineer`, `adr-generator`, `release-orchestrator`, `learnings-agent`, and `wrap-ticket` write files.

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
- **Two new obligations:** (1) tiered manifest enforcement on non-trivial files (missing = Minor, stale = Major, stale-on-correctness/security path = Critical); (2) verifies regression tests exist for any Critical/Major fix before granting sign-off.
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
- Each unit in the JSONL output carries a `skeptic_strategy`: `"per-unit"` (independent units, parallel Skeptics), `"integration"` (shared interface, one combined-diff Skeptic), or `"multi-dimensional"` (high-stakes: correctness-Skeptic + security-auditor + perf-analyst in parallel on the same diff)
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

github.com/Space-Dinosaurs/DinoStack
