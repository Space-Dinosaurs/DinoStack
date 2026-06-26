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

# Quality Assurance

Runtime verification that gets smarter every run

---

## The qa-engineer: what it does

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- Verifies the change in a **real browser** - navigates, clicks, screenshots, captures console errors
- Falls back to source-reading when browser access is blocked (labels those criteria `[source-verified]`)
- Returns a structured **PASS / FAIL / PARTIAL / BLOCKED / INCONCLUSIVE** report with evidence
- Does **not** fix anything - reporting is the whole job

<div class="callout">
Static review (Skeptic) + runtime review (qa-engineer) = the protocol's two-pass safety net.
</div>

---

## The qa-engineer: when it runs

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- For UI-visible changes with `qa_criteria` defined: spawned **in parallel with the Skeptic** (both background, single message) - sign-off requires both to pass
- For non-UI or unknown-diff cases: spawned **after Skeptic sign-off** as a sequential fallback

<div class="callout">
For UI-visible changes, Skeptic and qa-engineer run concurrently - no sequential delay. Both must pass before the unit is complete.
</div>

---

## `qa.md` is the project's QA memory

<style scoped>
  pre { font-size: 0.8em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { margin: 0.4em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

Per-project file, seeded by `/init-project` when a web UI is detected. Two jobs:

**1. Config** - how to run the app for QA

```markdown
## Dev server
command: npm run dev
port: 3000
## URLs
local: http://localhost:3000
staging: https://staging.example.com
## Preferences
prefer: local
```

**2. Knowledge** - project-specific quirks learned from past runs

<div class="callout">
qa.md is the only file the qa-engineer is allowed to write to. It is QA infrastructure, not application code.
</div>

---

## How qa.md shapes a run - pre-flight

<style scoped>
  ol { font-size: 0.9em; }
  ol li { margin: 0.25em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

Before touching the browser, the qa-engineer:

1. **Resolves the URL** - prompt URL wins, otherwise reads `qa.md` config
2. **Starts the dev server** automatically using the config'd `command` and `port`
3. **Waits up to 30s** for the port to respond, then curls the URL to confirm
4. **Reads every `## Knowledge` entry** and applies them as pre-flight adjustments
5. Only then does it begin testing the acceptance criteria

<div class="callout">
No URL-hunting, no manual dev server instructions, no re-discovering quirks. The project already told the qa-engineer how to run itself.
</div>

---

<!-- _class: highlight -->

## Knowledge tags - how quirks get applied

<style scoped>
  table { font-size: 0.82em; }
  th, td { padding: 0.35em 0.6em; }
  h2 { margin-bottom: 0.5em; }
</style>

Every knowledge entry is tagged. The tag tells the qa-engineer exactly how to use it.

| Tag | Effect on the next run |
|---|---|
| `server` | Adjust the dev server startup (extra flag, different command) |
| `timing` | Insert the specified delay at the relevant workflow step |
| `port` | Override the config'd port with the noted alternative |
| `auth` | Follow the documented login flow instead of discovering it fresh |
| `noise` | Exclude those console errors from blocking-issue classification |
| `retry` | Retry that endpoint or action once before marking FAIL |
| `tool` | Apply specific flags when invoking Playwright or agent-browser |

---

## The write-back loop - qa runs get smarter

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.9em; padding: 0.5em 1em; margin-top: 0.4em; }
</style>

After each run the qa-engineer reviews what it discovered and appends up to 3 knowledge entries, only if **all** of these hold:

- Project-specific quirk, not generic browser behavior
- Likely to recur on every future QA run
- Required non-obvious handling (a flag, delay, retry, workaround)
- Not already captured

Bugs in the app do **not** go here - those belong in the QA report. qa.md is for workarounds the QA process itself needs to remember.

<div class="callout">
First run in a new project is slow - qa-engineer is discovering quirks. Every run after pays that cost back: the pre-flight already knows.
</div>

---

## Example - one week in the life of qa.md

<style scoped>
  pre { font-size: 0.57em; padding: 0.25em 0.5em; margin: 0.12em 0 0.3em 0; line-height: 1.15; }
  p { margin: 0.1em 0; font-size: 0.78em; }
</style>

```markdown
# QA Config
## Dev server
command: npm run dev
port: 3000
## URLs
local: http://localhost:3000

## Knowledge
- [2026-04-02] timing: Wait 2s after nav to /dashboard - React Query refetch is async
- [2026-04-04] noise: Ignore "Hydration mismatch" warning in dev build - SSR/CSR known gap
- [2026-04-07] auth: Dev login uses demo@example.com / password. Submit, wait for /app redirect.
- [2026-04-09] retry: /api/search 500s once on cold start - retry once before FAIL
```

Each entry was a surprise the first time. After the entry, the qa-engineer handles it automatically on every run that follows.

---

## When QA is skipped - `qa_skip` enum

<style scoped>
  table { font-size: 0.78em; }
  th, td { padding: 0.28em 0.6em; }
  p { font-size: 0.8em; margin: 0.2em 0; }
  .callout { font-size: 0.76em; padding: 0.35em 0.9em; margin-top: 0.3em; }
</style>

QA fires by default for every Elevated unit. It is skipped only when the architect explicitly sets one of these five `qa_skip` values:

| Value | When it applies |
|---|---|
| `pure-backend-library` | No UI or behavioral surface visible to users |
| `config-only` | Change is purely configuration with no runtime code path |
| `type-only-refactor` | Only types/interfaces changed - no runtime effect |
| `dep-bump-no-runtime-change` | Dependency version bump with no API change |
| `docs-only` | Documentation files only, no code |

No `qa.md` is NOT a reason to skip QA - its absence only removes supplemental context; the gate still fires.

<div class="callout">
If none of these five values fit, QA fires. The <code>qa_skip</code> rationale must be logged in the Brief or architect plan.
</div>

---

## INCONCLUSIVE - when runtime is unreachable

<style scoped>
  ul { font-size: 0.85em; }
  ul li { margin: 0.2em 0; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

When the qa-engineer cannot reach a runtime path (preview deploy blocked AND local-env unavailable), the result is **INCONCLUSIVE** (`qa_unverified=true`) - not a pass.

- The conductor **MUST NOT auto-promote** INCONCLUSIVE to PASS
- Static source review of an Elevated UI-visible criterion is approximately zero signal - state hooks, conditional rendering, and prop-sync bugs are invisible to source review
- The conductor surfaces the state to the operator with three options:
  1. **Provide the missing env/URL** and re-run QA
  2. **Accept INCONCLUSIVE** - the PR can merge but carries `qa_unverified=true`
  3. **Abandon the ticket**

<div class="callout">
INCONCLUSIVE is not a pass. The operator must explicitly accept the unverified state before merge. The conductor does not proceed silently.
</div>

---

## Phase 6b QA loop - a bounded parallel to Phase 6

<style scoped>
  pre { font-size: 0.63em; padding: 0.35em 0.6em; line-height: 1.25; margin: 0.2em 0 0.35em 0; }
  ul { font-size: 0.75em; }
  ul li { margin: 0.1em 0; }
  .callout { font-size: 0.75em; padding: 0.35em 0.9em; margin-top: 0.3em; }
</style>

```
Phase 6b QA loop (independent 3-pass cap)
─────────────────────────────────────────────────────────
Only runs when Phase 6 exits cleanly (Skeptic sign-off)
    │
qa-engineer verifies acceptance criteria
    │
PASS? ──> Phase 7 (quality gate)
    │
failures? ──> update qa_failures_log ──> Engineer fix pass ──> loop back
    │
cap_reached (iteration == 3) or convergence_failure ──> ESCALATE to human
```

- **3-pass cap is independent**: exhausting Phase 6 Skeptic cap does not consume Phase 6b QA budget
- **Phase 6b only runs after Phase 6 clean exit** - if Phase 6 escalates (`cap_reached`, `convergence_failure`, `blocked`), Phase 6b is skipped entirely
- **`qa_failures_log` schema**: each failure tracked with `id`, `description`, `first_raised`, `status`, `claimed_fix`, `re_raised` - mirrors `findings_log` structure
- **QA convergence trigger**: same failure re-raised unchanged after a claimed fix - no severity qualifier (QA failures are not Critical/Major/Minor; any re-raised failure triggers `convergence_failure`)
- **Same BLOCKED/NEEDS_CONTEXT handling**: Engineer BLOCKED = immediate escalation; NEEDS_CONTEXT = context re-supply without incrementing iteration

<div class="callout">
Skeptic and QA test orthogonal properties - correctness vs. functional acceptance. The loop budgets reflect this: independent caps, independent state, independent escalation.
</div>

---

<!-- _class: lead -->

# QA that compounds

Browser-real verification. Per-project memory. Every run starts smarter.

github.com/Space-Dinosaurs/DinoStack
