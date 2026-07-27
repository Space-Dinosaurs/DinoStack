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

# The Learnings Pipeline

How DinoStack gets smarter every session

---

## Why a learnings pipeline

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- Every Skeptic finding, error-fix cycle, and tool-failure workaround is a signal
- Without capture, the next agent starting cold re-derives the same lessons from scratch
- The learnings pipeline converts ephemeral session knowledge into durable entries in `.agentic/learnings.md`
- That file is **committed** - teammates and future sessions inherit the knowledge automatically
- Two distinct feeders exist: `learning-extractor` (mechanical, per-ticket) and `learnings-agent` (mandatory triggers, per-session)

<div class="callout">
The pipeline is not a logging system. It is a self-improving loop: each closed ticket leaves the project measurably smarter than it found it.
</div>

---

<!-- _class: highlight -->

## The two feeders

<style scoped>
  .columns .card { font-size: 0.82em; line-height: 1.45; padding: 1em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
</style>

<div class="columns">
<div class="card">
<strong>learning-extractor</strong><br/>
Mechanically wired to <code>/ds-implement-ticket</code> Phase 6 clean exit. Fires automatically on every ticketed Skeptic loop completion. The conductor does NOT spawn this manually - it is part of the Phase 6 sequence.<br/><br/>
Emits <strong>LRN</strong> entries only (bug-fix residuals). Trigger: phase gate, not conductor judgment.
</div>
<div class="card">
<strong>learnings-agent</strong><br/>
Background capture on the mandatory triggers. Spawned by the conductor the FIRST time a trigger fires in a session; see the mandatory trigger list in `content/references/conductor-operating-rules.md` §learnings-agent background capture.<br/><br/>
Emits both <strong>LRN</strong> and <strong>KNW</strong> entries. Trigger: mandatory evaluation, conductor-initiated spawn.
</div>
</div>

<div class="callout">
Distinct triggers on purpose: <code>learning-extractor</code> guarantees coverage across every ticketed loop; <code>learnings-agent</code> captures the mandatory-trigger events no phase gate would catch.
</div>

---

## Entry types: LRN vs KNW

<style scoped>
  .columns .card { font-size: 0.82em; line-height: 1.45; padding: 1em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  ul { font-size: 0.82em; }
  ul li { margin: 0.1em 0; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #ff9d4d;">
<strong>LRN-YYYYMMDD-XXX</strong><br/>
Bug-fix learning. Fields:<br/>
<ul>
<li>Discovered, Severity, Domain</li>
<li>Pattern (what went wrong)</li>
<li>Fix (how it was resolved)</li>
<li>Source (phase/agent/ticket)</li>
</ul>
Used for bug-shaped findings from Skeptic loops and error-fix cycles. Emitted by both feeders.
</div>
<div class="card" style="border-left-color: #b06bff;">
<strong>KNW-YYYYMMDD-XXX</strong><br/>
Knowledge learning. Fields:<br/>
<ul>
<li>Discovered, Domain, Fact</li>
<li>Why-it-matters</li>
<li>Source</li>
</ul>
No Severity field. Used for env facts, dead-ends, architectural rationale, tool-failure workarounds, and cross-component gotchas. Emitted by <code>learnings-agent</code> only.
</div>
</div>

LRN and KNW maintain **independent per-day counters**. KNW entries are promoted to `MEMORY.md` at `/ds-wrap`.

---

## Capture classification: guardrail first

<style scoped>
  ol { font-size: 0.86em; }
  ol li { margin: 0.2em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
  table { font-size: 0.78em; width: 100%; }
</style>

Before writing any entry, the guardrail-first precedence chain runs:

1. **Can this be a guardrail?** If the knowledge encodes as a regression test, lint rule, type annotation, schema constraint, or CI check - write the guardrail instead. The guardrail IS the capture.
2. **Already covered?** If an existing guardrail, `AGENTS.md`, `MEMORY.md` entry, or the diff encodes it - SKIP. No duplicates.
3. **Apply the table** only when (a) and (b) both fail.

| Tier | Signal | Action |
|---|---|---|
| **MUST** | Expensive to re-derive AND no better home as a guardrail | Write `LRN` or `KNW` entry |
| **SHOULD** | One gate strong, the other marginal | Capture if cheap; prefer promoting to `MEMORY.md` |
| **SKIP** | Guardrail enforces it, visible in diff/code, already documented, one-off | Do not write |

<div class="callout">
A learning entry is the lowest tier of capture. The question is not "should I capture this?" - it is "what is the cheapest durable form this knowledge can take?"
</div>

---

## The MUST two-gate bar

<style scoped>
  .columns .card { font-size: 0.84em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
  blockquote { font-size: 0.82em; }
</style>

MUST tier requires **both** conditions to hold simultaneously:

<div class="columns">
<div class="card">
<strong>Gate 1: Expensive to re-derive</strong><br/>
A future agent starting cold would need non-trivial tool calls, failed attempts, external lookups, or multi-step diagnosis to rediscover it. If the next agent can find it in one Read or one search, SKIP.
</div>
<div class="card">
<strong>Gate 2: No better home</strong><br/>
A guardrail (test, type, lint, assertion, CI check) cannot encode it, AND it is not already in <code>AGENTS.md</code>, <code>MEMORY.md</code>, or the diff. If a better home exists, use it.
</div>
</div>

> "If I had to figure it out, the next agent shouldn't have to - but if a guardrail can stop them needing to figure it out at all, write the guardrail."

<div class="callout">
If either gate fails, drop to SHOULD or SKIP. MUST is genuinely rare.
</div>

---

## Where learnings land

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
  pre { font-size: 0.72em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
</style>

Three distinct knowledge stores - each with a different writer and lifecycle:

- **`.agentic/learnings.md`** - primary destination. Committed to git. Written by `learning-extractor` (LRN) and `learnings-agent` (LRN + KNW). Teammates inherit it on pull after merge.
- **`MEMORY.md`** (root `<cwd>/MEMORY.md`) - canonical durable facts. Committed. Loaded at session start via the `@MEMORY.md` import in the project root `CLAUDE.md`. KNW entries are promoted here at `/ds-wrap` when they stabilize.
- **`.agentic/memory.md`** - `/ds-wrap`-internal rolling scratch only. Gitignored. NOT auto-injected. NOT the same as root `MEMORY.md`.

```
learning-extractor ──> LRN entry ──> .agentic/learnings.md (committed)
learnings-agent    ──> LRN entry ──> .agentic/learnings.md (committed)
learnings-agent    ──> KNW entry ──> .agentic/learnings.md ──> MEMORY.md (at /ds-wrap)
```

<div class="callout">
Three stores, three writers, three audiences. Mixing them corrupts the `@MEMORY.md` import contract that keeps MEMORY.md clean for every session start.
</div>

---

## Skill-candidate detection

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
</style>

When friction recurs across sessions faster than learnings can absorb it, the pipeline escalates to **skill-candidate detection**:

- Repeated tool-failure workarounds with the same `domain_tag` in `events.jsonl` cluster into a signal
- `/ds-wrap` Part D and wrap-ticket session reflection scan for recurring patterns via `skill-candidate-deep-cluster.js`
- When a domain crosses the threshold, an entry appears in `.agentic/skill-candidates.md` with status `open`
- The conductor surfaces it at the next session start: `SKILL-CANDIDATE: domain '<domain>' has accumulated <count> occurrences - consider creating a skill`

A skill encodes what a sequence of LRN/KNW entries cannot: a reusable, activatable procedure the agent applies on demand rather than re-learning each time.

<div class="callout">
Learnings reduce re-derivation cost. Skills eliminate it. The pipeline routes from ad-hoc friction to structured knowledge to activatable skill - each tier cheaper than the one before.
</div>

---

<!-- _class: lead -->

# Capture once. Inherit forever.

Two feeders. One file. Every session smarter.

github.com/Space-Dinosaurs/DinoStack
