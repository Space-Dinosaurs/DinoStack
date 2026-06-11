---
marp: true
title: Parallel Fan-out
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
  section {
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
  pre {
    font-size: 0.8em;
    padding: 0.5em 0.8em;
    margin: 0.3em 0 0.8em 0;
  }
  code {
    font-size: 0.9em;
  }
---

<!-- _class: lead -->

# Parallel Fan-out

N engineers. One message. Skeptic-gated join.

---

## When fan-out applies

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

Fan-out is triggered when `orchestration-planner` returns **2 or more independent units**.

**Conditions for fan-out:**
- Planner classified units as independent (no shared state, no interface dependency)
- Each unit's brief is fully self-contained (files, acceptance criteria, quality gate)
- A bug in unit A would not be detectable only by examining unit B's code

**What does NOT trigger fan-out:**
- N=1: falls through to standard single-engineer Phase 5 path
- Interdependent units: still run in parallel, but use integration Skeptic strategy
- Units with shared file writes: planner misclassification - will surface as a merge conflict

<div class="callout">
The conductor must not derive parallelization itself. The orchestration-planner's classification is the authoritative source.
</div>

---

## The fan-out execution model

<style scoped>
  pre { font-size: 0.68em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.82em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

```
orchestration-planner returns N units
         │
         ▼
1. Conductor writes N pending entries to .agentic/tasks.jsonl
2. Conductor creates N worktrees from BASE_BRANCH
   git worktree add .worktrees/feature-unit1 -b feature-unit1 origin/main
   git worktree add .worktrees/feature-unit2 -b feature-unit2 origin/main

3. Conductor updates entries to in_progress, then spawns N engineers
   in a SINGLE MESSAGE (parallel)
         │
         ▼
   [engineer A]  [engineer B]  [engineer C]
   worktree A    worktree B    worktree C
   P0 loop A     P0 loop B     P0 loop C
         │
         ▼
4. All N return → conductor evaluates join condition
5. Join: merge in merge_order, then post-merge quality check
```

<div class="callout">
Workers return their summaries in the normal return path. Conductor handles all task-state file writes.
</div>

---

## The SKEPTIC_STRATEGY decision

<style scoped>
  .columns { gap: 1.2em; margin-bottom: 0.6em; }
  .columns .card { font-size: 0.82em; line-height: 1.5; padding: 1em 1.2em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

The planner classifies each parallel group and sets `skeptic_strategy`:

<div class="columns">
<div class="card">
<strong>per-unit</strong><br/>
Units are fully independent. Each gets its own Skeptic reviewing only its unit's diff. Per-unit Skeptics can themselves be spawned in parallel - non-overlapping diffs, no interference. Runs as part of each unit's P0 persistence loop inside its worktree.
</div>
<div class="card">
<strong>integration</strong><br/>
Units have shared interface contracts, shared data models, or cross-cutting concerns. Still implemented in parallel. But Skeptic review is deferred until all units are merged onto a scratch integration branch. One integration Skeptic reviews the combined diff. This IS the Phase 6 gate - no second Skeptic.
</div>
</div>

**Independence heuristic** (from `subagent-protocol.md` Section 6):
> "If a bug in unit A would only be detectable by examining unit B's implementation, or if unit A's correctness depends on assumptions about unit B's interface" - classify as interdependent.

<div class="callout">
Stacked Skeptics on interdependent units produce false signal. One integration Skeptic sees the combined diff. The planner's classification is the source of truth.
</div>

---

## P0 persistence loop per unit

<style scoped>
  pre { font-size: 0.68em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.82em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Each unit runs its own P0 Engineer → Skeptic loop inside its worktree:

```
Unit A worktree                     Unit B worktree
─────────────────────────           ─────────────────────────
Engineer A implements               Engineer B implements
    │                                   │
Skeptic A reviews ──> sign-off?    Skeptic B reviews ──> sign-off?
    │ findings?                         │ findings?
    └── Engineer A fix ──> loop        └── Engineer B fix ──> loop
    │ cap / convergence? ──> FAIL      │ cap / convergence? ──> FAIL
    ▼ sign-off                         ▼ sign-off
status: done                       status: done
```

- **"Done" means Skeptic signed off**, not first engineer commit
- Conductor updates the task entry to `status: done` only after sign-off
- Loops are fully self-contained per worktree - no cross-unit context sharing
- If a unit's loop exhausts its cap: `status: failed` with `"persistence loop exhausted"`

<div class="callout">
The join fires only after ALL units have reached a terminal state (done/failed/blocked). There is no per-unit notification event - the conductor waits for all N return values.
</div>

---

## Join conditions

<style scoped>
  .columns { gap: 1em; margin-bottom: 0.5em; }
  .columns .card { font-size: 0.78em; line-height: 1.45; padding: 0.9em 1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
  p { font-size: 0.85em; margin: 0.2em 0; }
</style>

After all N engineers return, conductor reads `.agentic/tasks.jsonl` and evaluates:

<div class="columns">
<div class="card">
<strong>All-done</strong><br/>
All N units at <code>status: done</code>.<br/>Proceed: sequential <code>--no-ff</code> merge in <code>merge_order</code>, then post-merge quality check.
</div>
<div class="card">
<strong>Partial success</strong><br/>
Some <code>done</code>, some <code>failed</code>.<br/>Merge green units. Retry failed unit once with preserved worktree (depth=1). Second failure escalates.
</div>
<div class="card">
<strong>Total failure</strong><br/>
All units <code>failed</code>.<br/>Clean up all worktrees. Escalate with failure outputs. Recommend sequential re-implementation.
</div>
<div class="card">
<strong>Blocked</strong><br/>
Any unit returned <code>Status: BLOCKED</code>.<br/>Treat as failed for that unit. Cannot be resolved by conductor - escalate immediately.
</div>
</div>

**Join timeout:** 30-minute deadline (configurable). Units still `in_progress` at deadline treated as failed.

<div class="callout">
<code>.agentic/tasks.jsonl</code> is the coordination surface. Conductor-only writes. Workers return summaries in their normal return path.
</div>

---

## Partial-success handling

<style scoped>
  pre { font-size: 0.72em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.84em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When some units fail and some succeed:

```
1. Record which units are green (status: done) and which failed

2. Are green units independently mergeable?
   (True if they are truly independent of the failed unit)
   → YES: merge green units into FEATURE_BRANCH
   → NO: hold all merges until failed unit resolves

3. Re-spawn engineer for failed unit (retry, depth=1):
   - Brief: original task brief from task entry inputs field
   - Context: failure detail from outputs.worker_summary
   - Worktree: preserved in-place (do NOT clean up)
   - Note: "This is a re-run, not a fresh start"

4. If re-run succeeds → merge, proceed to Skeptic phase
   If re-run fails (second time) → ESCALATE with full failure history
```

**Maximum retry depth: 1 automatic retry per unit.** No infinite loops.

<div class="callout">
The failed unit's worktree is preserved until resolution or escalation. Do not clean it up early.
</div>

---

## Merge strategy

<style scoped>
  pre { font-size: 0.72em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.84em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

After all-done join, conductor merges sequentially in `merge_order`:

```bash
# For each unit in merge_order:
git -C $REPO merge --no-ff ${FEATURE_BRANCH}-unit1

# After each merge, check for conflicts:
git -C $REPO diff --name-only --diff-filter=U
# Any output = conflicts present → git merge --abort → conflict recovery
```

**Rules:**
- Sequential `--no-ff` always (no octopus merge). Preserves conflict attributability.
- Conflict at any step: abort, stop remaining merges, spawn single engineer for sequential re-implementation
- After all N merges: run `QUALITY_CMD` on `FEATURE_BRANCH` (integration quality check)
- Integration check failure: spawn engineer on `FEATURE_BRANCH` for fix, then single Skeptic on incremental diff
- Cleanup after success: `git worktree remove --force` + `git branch -d` + `git worktree prune`

<div class="callout">
The integration quality check catches failures invisible to individual worktrees - behavioral interactions between units that per-unit tests could not detect.
</div>

---

## Task-state coordination

<style scoped>
  h2 { font-size: 1.6em; margin-bottom: 0.3em; }
  p { font-size: 0.85em; margin: 0.25em 0; }
  pre { font-size: 0.6em; padding: 0.35em 0.7em; line-height: 1.25; margin: 0.25em 0 0.35em 0; }
  table { font-size: 0.78em; margin: 0.3em 0; }
  th, td { padding: 0.3em 0.6em; }
  .callout { font-size: 0.76em; padding: 0.35em 0.9em; margin-top: 0.35em; }
</style>

`.agentic/tasks.jsonl` is the durable fan-out coordination surface:

```jsonl
{"task_id":"sess1-auth-middleware","unit_slug":"auth-middleware","status":"pending","branch_name":"feature-auth-unit1","worktree_path":".worktrees/feature-auth-unit1","inputs":{...}}
{"task_id":"sess1-user-profile-api","unit_slug":"user-profile-api","status":"in_progress","branch_name":"feature-auth-unit2","worktree_path":".worktrees/feature-auth-unit2","inputs":{...}}
```

**Entry lifecycle (conductor writes all):**

| Event | Status written |
|---|---|
| Fan-out initiated | `pending` - unit_slug, branch_name, worktree_path, inputs |
| Before engineer spawn | `in_progress` |
| Skeptic signed off | `done` |
| Unit failed or blocked | `failed` / `blocked` |
| Branch merged | `done` + `outputs.commit_sha` updated |

**Crash recovery:** On resume, `in_progress` entries = dead agents = treat as failed, re-spawn with original brief from `inputs` field.

<div class="callout">
If <code>.agentic/tasks.jsonl</code> does not exist, conductor creates it at fan-out initiation. Fallback: derive status from each engineer's structured return line (<code>Status: DONE</code> / <code>Status: BLOCKED</code>).
</div>

---

## Edge cases

<style scoped>
  .columns { gap: 1.2em; }
  .columns .card { font-size: 0.76em; line-height: 1.4; padding: 0.9em 1em; }
  .columns .card strong { font-size: 1.0em; }
</style>

<div class="columns">
<div class="card">
<strong>Wrong branch in worktree</strong><br/>
Before merging, verify <code>git rev-parse --abbrev-ref HEAD</code> in worktree matches <code>branch_name</code> from task entry. Mismatch = abort that unit's merge and escalate.
</div>
<div class="card">
<strong>Stale worktrees (crash recovery)</strong><br/>
Run <code>git worktree prune</code> and check for stale <code>feature-*-unit*</code> branches before creating new worktrees. Delete stale branches before re-creating.
</div>
<div class="card">
<strong>Shared file writes (planner error)</strong><br/>
Two "independent" units writing the same file. Surfaces as merge conflict. Recovery: sequential re-implementation. Promote as planner misclassification finding.
</div>
<div class="card">
<strong>Very large N (&gt;4 units)</strong><br/>
Conflict risk grows with N even for independent units (shared test fixtures, generated files). Consider chunking: fan out in batches of 2-4, merge each batch, run integration check, then next batch.
</div>
<div class="card">
<strong>Integration check fails after all-green per-unit Skeptics</strong><br/>
Units not as independent as classified - behavioral interaction. Spawn engineer on FEATURE_BRANCH for fix. Fix goes through single Skeptic. Does NOT replace Phase 6.
</div>
<div class="card">
<strong>Phase 6 interaction</strong><br/>
<code>per-unit</code>: Phase 6 fires normally (combined diff). <code>integration</code>: integration Skeptic IS Phase 6 - do not spawn a second Skeptic.
</div>
</div>

---

<!-- _class: lead -->

# N engineers. One message. Skeptic-gated join.

Fan-out extends the P0 persistence loop to parallel units - without sacrificing adversarial review.

github.com/Space-Dinosaurs/agentic-engineering
