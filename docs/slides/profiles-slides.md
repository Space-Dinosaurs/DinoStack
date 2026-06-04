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
  .numbered {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5em 0.9em;
    align-items: baseline;
    margin: 0.3em 0 0.6em 0;
  }
  .numbered .n {
    font-weight: bold;
    color: #b5451f;
    font-size: 1.1em;
  }
---

<!-- _class: lead -->

# Risk Profiles

Tune how aggressively the system reviews your work

---

## Three profiles, one dial

<style scoped>
  p { font-size: 0.92em; margin: 0.3em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
</style>

The system has a single tunable: how much Skeptic overhead to apply.

- **relaxed** - move fast, less review. Low-risk overrides are broadened so routine UI work skips Skeptic entirely.
- **default** - balanced. Single-file locally-scoped behavioral edits are Low. Everything else stays at standard Elevated thresholds.
- **strict** - maximum correctness gates. Changes that would normally be Low become Elevated and trigger a full Skeptic round.

<div class="callout">
Profiles are not a security dial - they tune review cadence. The underlying risk classification rules still apply; profiles adjust which edge cases get promoted or demoted relative to the baseline.
</div>

---

## relaxed

<style scoped>
  .card { font-size: 0.85em; line-height: 1.45; }
  ul li { margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="card" style="border-left-color: #2d5a3d;">

**For rapid iteration on well-understood UI or local bug fixes**

- Single-file locally-scoped behavioral edits: **Low** (no Skeptic)
- Multi-file pure-UI-only changes: **Low** (no Skeptic)
- Everything else: unchanged from default

</div>

<div class="callout">
Use relaxed on feature branches where you're moving fast and the surface area is contained. Switch back to default before merging anything that touches shared infrastructure or behavioral contracts.
</div>

---

## default

<style scoped>
  .card { font-size: 0.85em; line-height: 1.45; }
  ul li { margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="card" style="border-left-color: #1a5a7a;">

**The starting point for all projects**

- Single-file locally-scoped behavioral edits: **Low** (no Skeptic)
- All other legacy Elevated signals remain **Elevated**
- Multi-file UI-only changes: **Elevated** (Skeptic runs)
- The right choice for most day-to-day work

</div>

<div class="callout">
If you're not sure which profile to use, stay on default. It gives you one meaningful Low override (single-file local edits) without opening the floodgates on review.
</div>

---

## strict

<style scoped>
  .card { font-size: 0.85em; line-height: 1.45; }
  ul li { margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="card" style="border-left-color: #a83a2a;">

**For when correctness is paramount - payments, auth, shared infrastructure**

- UI-only copy changes: **Elevated** (Skeptic runs)
- File renaming: **Elevated** (Skeptic runs)
- Targeted wording fixes to already-reviewed content: **Elevated** (Skeptic runs)
- Diagnostic-only logging changes: **Low with self-check** (not unconditionally direct)
- Documentation-only file creation (new .md files that are pure lists/notes): **Low with self-check** (not unconditionally direct)

</div>

<div class="callout">
strict removes the Low-override carve-outs that other profiles rely on. More Skeptic rounds, more latency, higher confidence. Worth it when a mistake costs time or data.
</div>

---

## How to set your profile

<style scoped>
  pre { font-size: 0.82em; background: #f0ede6; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.4em 0; }
  p { font-size: 0.85em; margin: 0.3em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

**1. At install time**
```bash
bash .claude/install.sh --profile=strict
```

**2. Edit `~/.claude/agentic-engineering.json` directly**
```json
{ "mode": "opt-out", "profile": "strict" }
```

**3. Per-project override in root `AGENTS.md`**
```
agentic-engineering-profile: strict
```

<div class="callout">
Per-project override takes precedence over the global config. Set a global default that fits most of your work, then override in the projects that need tighter or looser gates.
</div>

---

<!-- _class: lead -->

# Start with default. Switch when it fits.

relaxed for fast-moving UI work. strict when a mistake costs time or data.

github.com/Solara6/agentic-engineering
