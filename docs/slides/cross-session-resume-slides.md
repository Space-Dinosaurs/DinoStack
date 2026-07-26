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

# Cross-Session Loop Resume

Long-running workflows that survive rate limits and session exits

---

## The problem

<style scoped>
  p { font-size: 0.88em; margin: 0.3em 0; }
  ul { font-size: 0.86em; }
  li { margin: 0.18em 0; }
  .callout { font-size: 0.84em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

A `/ds-implement-ticket` loop that runs multiple engineers and Skeptics across many phases can take longer than a single session allows. Rate limits hit. Sessions exit. Work is interrupted.

Without a resume mechanism, every interruption means:
- Losing track of which phase the loop was in
- Not knowing which units are complete versus in-progress
- Risking a re-run that overwrites already-committed work
- Losing the Brief or Plan path that governs remaining units

The solution is `.agentic/loop-state.json` - a file the conductor writes at every phase transition so any session can pick up exactly where the last one stopped.

<div class="callout">
Loop state is written atomically (tmp + rename) at every phase boundary. The file is gitignored - it is local ephemeral state, never committed.
</div>

---

<!-- _class: highlight -->

## loop-state.json - the phase cursor

<style scoped>
  pre { font-size: 0.7em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.6em 0; }
  p { font-size: 0.82em; margin: 0.2em 0; }
  ul { font-size: 0.82em; }
  li { margin: 0.1em 0; }
</style>

The conductor writes `.agentic/loop-state.json` at initialization and at every phase transition:

```
Skeptic spawn  ->  write loop-state.json (last_phase=skeptic, action=spawned)
Skeptic return ->  write loop-state.json (last_phase=skeptic, action=returned)
Engineer spawn ->  write loop-state.json (last_phase=engineer, action=spawned)
Engineer return -> write loop-state.json (last_phase=engineer, action=returned)
QA spawn       ->  write loop-state.json (last_phase=qa, action=spawned)
QA return      ->  write loop-state.json (last_phase=qa, action=returned)
```

`last_phase` and `last_phase_action` are the authoritative resume keys. The Stop hook fires once per **turn** and only refreshes a `last_updated` liveness timestamp; on a genuine terminal session end, the **SessionEnd hook** writes `status: "interrupted"` if the file exists and `status == "active"`.

- Silent Stop hook / SessionEnd hook failure is acceptable - the **10-minute implicit-interrupt heuristic** handles missed writes: any `status == "active"` file with `last_updated` more than 10 minutes old is treated as interrupted

---

## Resume check on session start

<style scoped>
  p { font-size: 0.84em; margin: 0.2em 0; }
  ul { font-size: 0.82em; }
  li { margin: 0.12em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When `/ds-implement-ticket` is invoked, it checks for `.agentic/loop-state.json` **before reading AGENTS.md**. If the file exists with `status == "interrupted"` (or `status == "active"` with `last_updated` more than 10 minutes old), the conductor offers resume or fresh start.

**Resumable phases (automatic):**
- Phase 6/6b Skeptic/QA loop at iteration boundaries - committed engineer output, clean branch
- Phase 7 quality gate when engineer committed (`engineer_returned` or `rerun_pending` action)

**Resumable with human confirmation:**
- Mid-engineer (dirty branch) - conductor asks human to discard or commit the partial work

**Restart required:**
- Phases 1-4 are cheap to re-run and have no branch side effects. State file is not written until Phase 6 loop initialization.

<div class="callout">
If a Skeptic is interrupted mid-output, resume re-runs the Skeptic from scratch (<code>last_phase=skeptic</code>, <code>last_phase_action=spawned</code>). Skeptic is read-only and idempotent - re-running it costs one agent turn, not correctness.
</div>

---

## Brief and Plan path recording

<style scoped>
  p { font-size: 0.84em; margin: 0.22em 0; }
  ul { font-size: 0.82em; }
  li { margin: 0.14em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When a Brief or Plan governs the task, three fields are written to `.agentic/loop-state.json` at authoring time:

- `brief_path` - absolute path to the Brief file
- `plan_path` - absolute path to the Plan directory (when applicable)
- `promotion_tier` - enum: `none`, `brief`, or `plan`

On resume, the conductor re-reads the Brief or Plan **before spawning the next worker**. This ensures the governing artifact is always in context, even if the session that authored it is long gone.

**Mid-flight escalation:** if a task promotes from Trivial or single-unit Elevated to Brief or Plan tier during execution, a retroactive Brief is authored before the next engineer spawn. The in-flight engineer is allowed to return; already-completed units are not retroactively re-reviewed.

<div class="callout">
<strong>Auto-promotion at the third resume:</strong> a Brief-tier task that has been resumed twice already promotes to Plan tier on the third resume - signaling that multi-session scope warrants fuller documentation.
</div>

---

## Batch-state coexistence

<style scoped>
  p { font-size: 0.84em; margin: 0.2em 0; }
  ul { font-size: 0.82em; }
  li { margin: 0.12em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When `/ds-implement-ticket` runs with 2 or more ticket IDs, a sibling file `.agentic/batch-state.json` tracks batch-level cursor alongside `loop-state.json`'s per-ticket phase cursor.

**Session ownership gate:** both files carry a `session_id` field. Every write applies a per-write gate that aborts (with an operator-visible warning) if:
- The existing `session_id` belongs to a different session whose liveness timestamp (`last_updated` for `loop-state.json`, `updated_at` for `batch-state.json`) is within 10 minutes
- The existing `session_id` is null or absent (legacy state - force-takeover eligible)

This prevents orphan-session corruption uniformly across both files.

**Concurrency limits:**
- Only one batch per project root is supported
- A second concurrent N>=2 invocation is refused at Phase 0a-pre
- N=1 invocations against an active foreign batch warn but do not refuse
- Single-ticket Trivial invocations never create `batch-state.json`

<div class="callout">
The SessionEnd hook mirrors its <code>loop-state.json</code> terminal interrupted-mark write to <code>batch-state.json</code> via the same best-effort silent-fail discipline. The Stop hook's separate per-turn liveness refresh mirrors similarly.
</div>

---

## File hygiene

<style scoped>
  .columns { gap: 1.2em; }
  .columns .card { font-size: 0.82em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; display: block; margin-bottom: 0.3em; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

<div class="columns">
<div class="card">
<strong>loop-state.json</strong>
Written atomically (tmp + rename) at every phase transition. Gitignored - never committed. Set to <code>status: "complete"</code> or deleted after the PR is opened.
</div>
<div class="card">
<strong>batch-state.json</strong>
Sibling to loop-state.json for multi-ticket runs. Same atomic write discipline. Same gitignore. Never created for single-ticket invocations.
</div>
</div>

**Phase breadcrumbs** accompany every phase transition - the conductor emits `[phase: label]` inline at each boundary. Phase breadcrumbs are emitted separately at each phase boundary and appear in the session context.

<div class="callout">
loop-state.json must not be committed to git. Its presence in the repo would mislead the next developer about what phase the loop is in. Gitignore is the contract; the file is ephemeral state, not project history.
</div>

---

<!-- _class: lead -->

# Phase written. Session exits. Resume.

The loop picks up where it stopped.

github.com/Space-Dinosaurs/DinoStack
