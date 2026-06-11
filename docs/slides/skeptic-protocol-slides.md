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

# The Skeptic Protocol

Adversarial review that stays independent by design

---

## Why adversarial review matters

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- A reviewer who has seen the implementer's reasoning is **anchored** to that framing
- Self-review catches typos. It does not catch flawed assumptions.
- The value of review is **independence** - seeing the output without the justification
- The Skeptic sees only the output and the adversarial brief, never the Worker's reasoning process
- This is not optional polish. It is the protocol's primary quality gate.

<div class="callout">
A resumed Skeptic has heard its own prior criticism - it gets polite and misses things. Fresh context is what gives the review teeth.
</div>

---

<!-- _class: highlight -->

## The core loop

<style scoped>
  pre { font-size: 0.72em; padding: 0.5em 0.8em; line-height: 1.35; margin: 0.3em 0 0.8em 0; }
  ol { font-size: 0.82em; }
  ol li { margin: 0.15em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

```
Primary agent spawns Worker (with adversarial brief + task)
    |
Worker implements, returns output
    |
Primary agent spawns fresh Skeptic (with brief + output)
    |
Skeptic classifies findings: Critical / Major / Minor
    |
No Critical/Major? ──> Sign-off granted ──> Done
    |
Critical/Major found? ──> Route to new Worker ──> Loop back
```

1. The **primary agent** orchestrates - it never implements Elevated work itself
2. Each **Worker** is a fresh spawn with accumulated context from prior rounds
3. Each **Skeptic** is a fresh spawn - never continued, never resumed
4. The loop repeats until the Skeptic grants sign-off or the re-route limit is hit

---

## The adversarial brief

<style scoped>
  p { font-size: 0.88em; margin: 0.3em 0; }
  blockquote { font-size: 0.82em; }
  ul { font-size: 0.85em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

The brief defines the **threat model** the Skeptic must adopt. It is domain-specific - not generic.

> "An attacker controls one compromised account and one compromised device. What can they access, modify, or forge? Look for: session fixation, token replay, privilege escalation paths, and any state the server trusts without re-verifying."

- The primary agent writes it (or extends a template) and passes it to both Worker and Skeptic **verbatim**
- The agent must not soften, summarize, or editorialize the brief
- Templates exist for: auth, API endpoints, crypto, DB migrations, data pipelines, smart contracts, architecture docs, general code review

<div class="callout">
Generic briefs produce generic findings. The brief is where you aim the Skeptic at what actually matters for this change.
</div>

---

## Findings classification

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.82em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.1em; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #ff5d73;">
<strong>Critical</strong><br/>
Blocks sign-off. Must be resolved. Security vulnerabilities, correctness failures, data loss paths.
</div>
<div class="card" style="border-left-color: #ff9d4d;">
<strong>Major</strong><br/>
Blocks sign-off unless the Worker provides a compelling documented reason to defer. Missing error handling, silent failure edge cases, DRY violations and missed abstractions (duplication, copy-paste programming, reinventing existing helpers).
</div>
<div class="card" style="border-left-color: #3ad99a;">
<strong>Minor</strong><br/>
Never blocks sign-off. Applied automatically by a background agent after sign-off. Style, logging gaps, low-impact optimizations.
</div>
</div>

<div class="callout">
Every finding must be classified. Unclassified findings default to Major. The Skeptic cannot wave something through without saying what it is.
</div>

---

## Escalation and round limits

<style scoped>
  ul { font-size: 0.8em; }
  ul li { margin: 0.15em 0; }
  p { font-size: 0.83em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; }
</style>

- **2 re-route limit (default)**: same finding contested across 2+ rounds without resolution - escalate to the human with both positions
- **Simple changes**: capped at **1 round** - Critical/Major findings escalate directly
- **Standard Elevated changes**: the 2-re-route rule applies
- The primary agent tracks each finding by its text across all rounds

**Loop-context override (inside `/implement-ticket` Phase 6):** the 2-re-route rule is replaced by a stricter contract - **1 re-raise of a Critical finding after a claimed fix** is enough to trigger convergence failure escalation. The loop already consumes iteration budget on each fix pass; waiting for a second re-raise wastes a pass on a finding the Engineer already failed to address. Outside a named loop, the 2-re-route rule is unchanged.

<div class="callout">
The protocol does not force resolution. Inside a persistence loop, it escalates faster. Outside, the standard 2-re-route buffer applies.
</div>

---

## The resolved issues preflight + findings_log

<style scoped>
  p { font-size: 0.84em; margin: 0.3em 0; }
  pre { font-size: 0.71em; padding: 0.4em 0.8em; line-height: 1.3; margin: 0.3em 0 0.6em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

On round 2+, the primary agent prepends a preflight list to the brief so the fresh Skeptic doesn't re-raise already-fixed issues:

```
The following issues were identified and resolved in prior rounds.
Do not re-raise them unless you believe the resolution is genuinely
insufficient:

[C1: Missing auth check on /admin endpoint → Added middleware guard]
[M1: No error handling on payment callback → Added try/catch with rollback]
```

**Inside the persistence loop:** the preflight list is backed by `findings_log` - a structured in-context accumulator that tracks every finding across all iterations (`id`, `severity`, `first_raised`, `status`, `claimed_fix`, `re_raised`). When the Skeptic re-raises a previously-addressed finding, it uses `[PREV: <id>]` so the conductor can mechanically detect it and update `re_raised: true`.

**Auto-close rule:** when the Skeptic grants sign-off (zero new findings), ALL `findings_log` entries with `status: open` or `status: addressed` are automatically closed. The absence of re-raise is an implicit confirmation that all fixes were accepted.

<div class="callout">
Fresh context for independence. Preflight list for efficiency. findings_log for accountability across iterations.
</div>

---

## Three new Skeptic obligations

<style scoped>
  .columns-3 { gap: 1.2em; }
  .columns-3 .card { font-size: 0.82em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns-3 .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
  ul { font-size: 0.85em; }
  ul li { margin: 0.15em 0; }
</style>

<div class="columns-3">
<div class="card">
<strong>Module manifest check</strong><br/>
On any non-trivial file touched by the Worker (exports a public symbol, ~50+ LOC, or side-effecting): verify a module manifest header exists and reflects the current file.<br/><br/>
Tiered: missing = <strong>Minor</strong> (non-blocking, hygiene); stale = <strong>Major</strong> (blocks sign-off); stale-on-correctness/security path = <strong>Critical</strong>.
</div>
<div class="card">
<strong>Regression test verification</strong><br/>
Before granting sign-off on any round where a Critical or Major finding was fixed: verify a regression test was added - a test that would have failed without the fix.<br/><br/>
Missing test without a documented exception = <strong>Major</strong> finding.
</div>
<div class="card">
<strong>Telemetry emit check</strong><br/>
At every instrumented boundary (engineer/skeptic/qa spawn or Trivial-path direct edit): verify <code>.agentic/events.jsonl</code> received the matching <code>spawn_start</code>/<code>spawn_complete</code> or <code>conductor_direct</code> events.<br/><br/>
Missing emit = <strong>Minor</strong> (non-blocking; keeps <code>/agentic-cost</code> dashboards accurate).
</div>
</div>

<div class="callout">
These checks are additions to the standard Skeptic pass - they run alongside the existing findings classification, not instead of it. Comprehension, regression, and observability gates layered on top of Critical/Major/Minor.
</div>

---

## Cognitive surrender check

<style scoped>
  .columns { gap: 1.2em; }
  .columns .card { font-size: 0.82em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #3ad99a;">
<strong>Cognitive offloading (good)</strong><br/>
Delegating mechanics to the agent - boilerplate, search, transformation. Judgment stays with the human and the Skeptic.
</div>
<div class="card" style="border-left-color: #ff5d73;">
<strong>Cognitive surrender (bad)</strong><br/>
Treating the LLM as System 3. A Skeptic that agrees with the Worker on every point with zero findings across two iterations is a rubber-stamp signal.
</div>
</div>

<div class="callout">
Cure: an <strong>audit-note Minor</strong> attesting the Skeptic re-read the diff end-to-end with independent attention. Documents what was checked, not what was wrong. Exempt from <code>/implement-ticket</code> Phase 6 re-raise and convergence-failure detection - bookkeeping, not contested findings.
</div>

---

## Calibration layer

<style scoped>
  ul { font-size: 0.82em; }
  ul li { margin: 0.15em 0; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  pre { font-size: 0.7em; padding: 0.4em 0.8em; line-height: 1.3; margin: 0.3em 0 0.6em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

The audit-note Minor is the per-spawn defense against rubber-stamping. The **calibration layer** is the long-horizon backstop - it detects drift in aggregate over time without enlarging the per-spawn review surface.

- **Findings counters in `events.jsonl`** - every Skeptic `spawn_complete` carries `findings_count`, `diff_lines`, `signed_off`, and `iteration` inside `data`. Conductor builds the merged JSON inline; subagents do not write to `.agentic/`.
- **5% sampled meta-Skeptic** - deterministic bucket from `hash(task_id+iteration) % 100 < 5`. Background fire-and-forget; conductor declares the unit complete without waiting. Meta-Skeptic returns text only; conductor parses and emits `meta_review_complete`.
- **Surfacing** - Critical/Major divergence on a sampled spawn surfaces as one inline `META-DIVERGENCE:` line. Original sign-off remains binding; the notice is advisory. Surfacing fires both in-session (Phase 6 turn boundaries) and at session start (catches async returns from prior sessions). The sweep paginates via `.meta-divergence-last-sweep` timestamp tracker to avoid reading the full events file on every boot.
- **Inspection CLI** - `agentic-calibrate density` (findings per 100 diff-lines, excludes zero-diff rows) and `agentic-calibrate divergence` (meta-Skeptic rubber-stamp rate). Warming-up line shown until 10 qualifying spawns observed.

<div class="callout">
Threat model: drift detection in a non-adversarial conductor relationship. Not a cheating-prevention mechanism - a compromised conductor can mis-emit. The target is operator self-deception over time, not adversarial spoofing.
</div>

---

<!-- _class: lead -->

# Fresh. Independent. Classified.

Every finding named. Every round tracked. Every escalation clean.

github.com/Space-Dinosaurs/agentic-engineering
