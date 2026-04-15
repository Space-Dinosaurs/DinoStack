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
<div class="card" style="border-left-color: #c62828;">
<strong>Critical</strong><br/>
Blocks sign-off. Must be resolved. Security vulnerabilities, correctness failures, data loss paths.
</div>
<div class="card" style="border-left-color: #fb8c00;">
<strong>Major</strong><br/>
Blocks sign-off unless the Worker provides a compelling documented reason to defer. Missing error handling, silent failure edge cases.
</div>
<div class="card" style="border-left-color: #43a047;">
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

## Two new Skeptic obligations

<style scoped>
  .columns { gap: 1.2em; }
  .columns .card { font-size: 0.82em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.4em; }
  ul { font-size: 0.85em; }
  ul li { margin: 0.15em 0; }
</style>

<div class="columns">
<div class="card">
<strong>Module manifest check</strong><br/>
On any non-trivial file touched by the Worker (exports a public symbol, ~50+ LOC, or side-effecting): verify a module manifest header exists and reflects the current file.<br/><br/>
Missing or stale manifest = <strong>Major</strong> finding. Blocks sign-off.
</div>
<div class="card">
<strong>Regression test verification</strong><br/>
Before granting sign-off on any round where a Critical or Major finding was fixed: verify a regression test was added - a test that would have failed without the fix.<br/><br/>
Missing test without a documented exception = <strong>Major</strong> finding.
</div>
</div>

<div class="callout">
Both checks are additions to the standard Skeptic pass - they run alongside the existing findings classification, not instead of it. Module manifests are a comprehension gate; regression tests are a regression gate.
</div>

---

<!-- _class: lead -->

# Fresh. Independent. Classified.

Every finding named. Every round tracked. Every escalation clean.

github.com/Solara6/agentic-engineering
