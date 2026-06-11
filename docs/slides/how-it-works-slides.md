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

# DinoStack

A protocol for shipping software with AI agents

---

## How to tell it's working

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  code { font-size: 0.92em; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

The protocol is observational. The conductor narrates delegations as it runs - listen for phrases like:

- `Routing this through orchestration-planner - multiple phases involved.`
- `Spawning architect to produce a plan before any code lands.`
- `Spawning engineer to implement the cache layer.`
- `Handing off to skeptic for adversarial review.`
- `Spawning debugger on the failing test.`
- `QA engineer verifying acceptance criteria in the browser.`

<div class="callout">
No narration? The task was classified <strong>Direct action</strong> - handled in the main thread without a subagent. That is the protocol working, not off.
</div>

---

## What it is

- A **portable methodology** for AI-assisted software development
- Loaded as a skill - it shapes how your agent plans, implements, and reviews code
- Mostly **passive**: you don't drive it with commands
- Risk-aware delegation, adversarial review, focused sessions
- Tool-agnostic: Claude Code, Cursor, Codex, Gemini CLI

<div class="callout">
Not a framework you call into. A living protocol that shapes every response, every task, every review - in the background.
</div>

---

## What a typical session feels like

<style scoped>
  ol { font-size: 0.88em; }
  ol li { margin: 0.2em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

1. You state a goal in plain English - "fix the bug in X", "add feature Y"
2. The agent **classifies risk** - small edit vs. real change
3. Small stuff is handled directly, in the conversation
4. For bigger work, the agent proposes a **plan** - agents to spawn, sequencing, review gates
5. You **review the plan together** - push back, adjust scope, approve. This is the key decision point.
6. Approved plan executes: Worker in an isolated worktree, then Skeptic review
7. You read the summary and decide: ship, revise, or drop

<div class="callout">
The planning step is collaborative - the agent proposes, you refine. Implementation only starts after you approve.
</div>

---

<!-- _class: highlight -->

## What you actually get

<div class="columns">
<div class="card">
<strong>Fewer regressions</strong><br/>
Nothing meaningful merges without an adversarial Skeptic pass. Critical findings block.
</div>
<div class="card">
<strong>Focused sessions</strong><br/>
One goal per session. Explicit handoffs. Context stays narrow, output stays sharp.
</div>
<div class="card">
<strong>Better reviews</strong><br/>
Every non-trivial change ships with a pre-mortem, a review brief, and a classified findings list.
</div>
<div class="card">
<strong>Institutional memory</strong><br/>
Learnings, conventions, and decisions persist across sessions instead of dying with the chat.
</div>
</div>

---

## A small command surface

| Command | When you'd reach for it |
|---|---|
| `/init-project` | One-time setup when bringing the protocol into a repo |
| `/implement-ticket` | Explicitly hand a task to a Worker |
| `/skeptic` | Force a review pass on recent changes |
| `/wrap` | Close out a session: commit, PR, memory, cleanup |
| `/memory-update` | Persist a learning you want to keep |

<div class="callout">
Most sessions don't invoke any of these. Commands are accents, not the interface.
</div>

---

## Under the hood - risk classification

<style scoped>
  p { font-size: 0.9em; margin: 0.3em 0; }
  .columns { font-size: 0.88em; }
  .columns ul { margin: 0.2em 0; }
  .columns li { margin: 0.15em 0; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

The main session agent decides for each task: handle it directly, or delegate to a specialist in the background.

<div class="columns">
<div>

**Direct action**
- Reads, answering from memory
- Screenshots, diagnostic logging
- Small, reversible edits
- Handled in the main thread

</div>
<div>

**Elevated**
- Writing or changing code
- Multi-file changes, migrations
- Spawns Worker + Skeptic in the background
- Review loop runs automatically

</div>
</div>

<div class="callout">
When in doubt, the agent classifies <strong>Elevated</strong>. The cost of a review is cheap; the cost of a bad change is not.
</div>

<div class="callout">
<strong>Tier declaration:</strong> Conductors declare <code>Tier: 1/2/3</code> when spawning. Tier 2 is the default - no change to existing spawns. Tier 1 = cheap/fast (Haiku). Tier 3 = max capability (Opus). Declaration is documentation; the <code>model</code> param in the Agent tool call is enforcement.
</div>

---

## Under the hood - the agent team

<style scoped>
  .columns-3 { gap: 0.5em; margin-bottom: 0; }
  .columns-3 .card { padding: 0.45em 0.7em; font-size: 0.66em; border-radius: 8px; line-height: 1.25; }
  .columns-3 .card strong { font-size: 1.1em; }
  .columns-3 .card:nth-child(1) { border-left-color: #4ea3ff; }
  .columns-3 .card:nth-child(2) { border-left-color: #ff5d73; }
  .columns-3 .card:nth-child(3) { border-left-color: #b06bff; }
  .columns-3 .card:nth-child(4) { border-left-color: #2fd4c4; }
  .columns-3 .card:nth-child(5) { border-left-color: #3ad99a; }
  .columns-3 .card:nth-child(6) { border-left-color: #ff9d4d; }
  .columns-3 .card:nth-child(7) { border-left-color: #2fd4c4; }
  .columns-3 .card:nth-child(8) { border-left-color: #ff5d73; }
  .columns-3 .card:nth-child(9) { border-left-color: #7c8cff; }
  .columns-3 .card:nth-child(10) { border-left-color: #3ad99a; }
  .columns-3 .card:nth-child(11) { border-left-color: #c79a86; }
  .columns-3 .card:nth-child(12) { border-left-color: #8aa0b5; }
  .columns-3 .card:nth-child(13) { border-left-color: #ff9d4d; }
  h2 { margin-bottom: 0.35em; }
</style>

<div class="columns-3">
<div class="card"><strong>investigator</strong><br/>Maps unfamiliar code</div>
<div class="card"><strong>debugger</strong><br/>Root-cause analysis</div>
<div class="card"><strong>orchestration-planner</strong><br/>Picks the team and sequencing</div>
<div class="card"><strong>architect</strong><br/>Designs before coding</div>
<div class="card"><strong>engineer</strong><br/>Implements changes</div>
<div class="card"><strong>skeptic</strong><br/>Adversarial review</div>
<div class="card"><strong>qa-engineer</strong><br/>Runtime verification</div>
<div class="card"><strong>security-auditor</strong><br/>Threat modeling</div>
<div class="card"><strong>adr-generator</strong><br/>Decision records</div>
<div class="card"><strong>adr-drift-detector</strong><br/>ADR compliance audit</div>
<div class="card"><strong>perf-analyst</strong><br/>Performance profiling</div>
<div class="card"><strong>release-orchestrator</strong><br/>End-to-end release sequencing</div>
<div class="card"><strong>dependency-auditor</strong><br/>Supply-chain review</div>
</div>

---

## The persistence loop - Engineer -> Skeptic -> QA

<style scoped>
  pre { font-size: 0.68em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.82em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

```
Phase 6: Skeptic loop (max 3 fix passes)          Phase 6b: QA loop (max 3 fix passes)
─────────────────────────────────────────         ─────────────────────────────────────
Engineer implements                               (only runs if Phase 6 exits cleanly)
    │
Skeptic reviews ──> sign-off? ──> Phase 6b ──>  QA verifies ──> PASS? ──> Phase 7
    │ Critical/Major found?                           │ failures?
    └── Engineer fix pass ──> loop back              └── Engineer fix pass ──> loop back
    │ cap_reached / convergence? ──> ESCALATE        │ cap / convergence? ──> ESCALATE
```

- **3 fix passes per phase** - caps are independent (Skeptic cap and QA cap are separate budgets)
- **`findings_log` carries forward** - prior findings tracked by ID; closed findings are not re-litigated
- **Convergence failure** - one re-raise of a **Critical** finding after a claimed fix triggers immediate escalation (does not wait for a second attempt)
- **Escalation reasons**: `cap_reached`, `convergence_failure`, `blocked`

<div class="callout">
The loop is a named protocol primitive - not ad-hoc re-routing. Every iteration emits a breadcrumb: <code>[loop: skeptic | iteration 2/3 | open findings: 1 Critical]</code>
</div>

<div class="callout">
<strong>Loop durability:</strong> state is written to <code>.agentic/loop-state.json</code> at each phase transition (atomic write). Loops survive rate limits and session exits — the next session resumes from the last phase boundary via <code>/implement-ticket</code>'s built-in resume check.
</div>

---

## When the loop stalls

<style scoped>
  .columns { gap: 1em; margin-bottom: 0.5em; }
  .columns .card { font-size: 0.78em; line-height: 1.4; padding: 0.8em 1em; }
  .columns .card strong { font-size: 1.05em; }
  p { font-size: 0.85em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

<div class="columns">
<div class="card">
<strong>cap_reached</strong><br/>
3 fix passes ran, Critical/Major findings still open. Loop exits. QA is skipped. Human receives the open findings list and three options: clarify, defer, or scope as follow-on.
</div>
<div class="card">
<strong>convergence_failure</strong><br/>
Skeptic re-raised a <strong>Critical</strong> finding after the Engineer claimed to fix it. One re-raise is enough - the loop does not wait for a second attempt. Signals a design conflict, not an implementation mistake.
</div>
<div class="card">
<strong>blocked</strong><br/>
Engineer returned BLOCKED - hit a design conflict that fix passes cannot resolve. Treated as immediate escalation regardless of iteration count.
</div>
</div>

The conductor surfaces the raw finding history and waits for human direction. It does not synthesize fix suggestions.

<div class="callout">
The loop terminates cleanly or escalates. It never runs forever.
</div>

---

## Parallel fan-out - N engineers in one message

<style scoped>
  pre { font-size: 0.68em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.82em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When `orchestration-planner` returns 2+ independent units, `/implement-ticket` Phase 5 fans out:

```
orchestration-planner
  unit A (merge_order:1, skeptic_strategy:per-unit)
  unit B (merge_order:2, skeptic_strategy:per-unit)
         │
         ▼  single message (parallel)
  ┌──────────────┐    ┌──────────────┐
  │ worktree A   │    │ worktree B   │
  │ engineer A   │    │ engineer B   │
  │ → skeptic A  │    │ → skeptic B  │
  │ (P0 loop)    │    │ (P0 loop)    │
  └──────┬───────┘    └──────┬───────┘
         └────── join ───────┘
               │
         sequential --no-ff merge
         (merge_order: A then B)
               │
         post-merge quality check
```

<div class="callout">
Each unit runs its own P0 persistence loop. "Done" = Skeptic signed off, not first commit.
</div>

---

## Fan-out join conditions

<style scoped>
  .columns { gap: 1em; margin-bottom: 0.5em; }
  .columns .card { font-size: 0.78em; line-height: 1.4; padding: 0.8em 1em; }
  .columns .card strong { font-size: 1.05em; }
  p { font-size: 0.85em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

After all N engineers return, conductor evaluates the join:

<div class="columns">
<div class="card">
<strong>All-done</strong><br/>
All units reach <code>status: done</code> (Skeptic signed off). Proceed to sequential merge in <code>merge_order</code>.
</div>
<div class="card">
<strong>Partial success</strong><br/>
Some done, some failed. Merge green units. Retry failed unit once (depth=1) with preserved worktree. Second failure escalates.
</div>
<div class="card">
<strong>Total failure</strong><br/>
All units failed. Clean up worktrees. Escalate with full failure outputs - recommend sequential fallback.
</div>
<div class="card">
<strong>Blocked</strong><br/>
Any unit returned <code>Status: BLOCKED</code>. Treat as failed. Conductor cannot resolve - escalate immediately.
</div>
</div>

<div class="callout">
Task state tracked in <code>.agentic/tasks.jsonl</code>. Conductor writes all entries - workers return summaries only.
</div>

---

## Regression test obligation

<style scoped>
  .columns { gap: 1.2em; margin-bottom: 0.6em; }
  .columns .card { font-size: 0.8em; line-height: 1.4; padding: 0.9em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  p { font-size: 0.88em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Every Critical or Major finding that gets fixed without a test is a latent regression. The fix loop closes the gap:

<div class="columns">
<div class="card">
<strong>Per-finding regression test</strong><br/>
Worker adds a test that would have <em>failed</em> without the fix. Skeptic verifies it exists before sign-off. Lives in the project test suite.
</div>
</div>

<div class="callout">
The regression test is code-level: it catches the specific failure mode so the same bug cannot silently reappear in a future change.
</div>

---

<!-- _class: lead -->

# Ship with confidence

Risk-aware delegation. Adversarial review. Focused sessions.
Mostly passive - just describe the work.

github.com/Space-Dinosaurs/agentic-engineering
