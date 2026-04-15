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

# Quality Assurance

Runtime verification that gets smarter every run

---

## The qa-engineer in one slide

- Spawned **after Skeptic sign-off**, before merge, for any change with visible UI or behavioral output
- Verifies the change in a **real browser** - navigates, clicks, screenshots, captures console errors
- Falls back to source-reading only when browser access is blocked (labels those criteria `[source-verified]`)
- Returns a structured **PASS / FAIL / PARTIAL / BLOCKED** report with evidence
- Does **not** fix anything - reporting is the whole job

<div class="callout">
Static review (Skeptic) plus runtime review (qa-engineer) is the protocol's two-pass safety net. Compiles and looks right is not the same as actually works.
</div>

---

## `.claude/qa.md` is the project's QA memory

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
  pre { font-size: 0.72em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; line-height: 1.3; }
  p { margin: 0.3em 0; font-size: 0.9em; }
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

## Phase 6b QA loop - a bounded parallel to Phase 6

<style scoped>
  pre { font-size: 0.68em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.3em 0 0.5em 0; }
  ul { font-size: 0.8em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
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

github.com/Solara6/agentic-engineering
