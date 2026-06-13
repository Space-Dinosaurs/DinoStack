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
  .numbered {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5em 0.9em;
    align-items: baseline;
    margin: 0.3em 0 0.6em 0;
  }
  .numbered .n {
    font-weight: bold;
    color: #18E0FF;
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

<div class="card" style="border-left-color: #3ad99a;">

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

<div class="card" style="border-left-color: #4ea3ff;">

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

<div class="card" style="border-left-color: #ff7a5d;">

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
  pre { font-size: 0.82em; background: #04070F; border-radius: 8px; padding: 0.8em 1.2em; margin: 0.4em 0; }
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
Or use the `preset` field (`lean` | `standard` | `strict`) - overrides `profile` when set:
```json
{ "mode": "opt-out", "preset": "strict" }
```

**3. Per-project override in root `AGENTS.md`**
```
agentic-engineering-profile: strict
```
Or use `preset` (wins over `agentic-engineering-profile:` on collision):
```
agentic-engineering-preset: strict
```

<div class="callout">
Per-project preset wins over per-project profile. Preset resolves: lean->relaxed, standard->default, strict->strict. Set a global default that fits most of your work, then override in the projects that need tighter or looser gates.
</div>

---

<!-- _class: lead -->

# Start with default. Switch when it fits.

relaxed for fast-moving UI work. strict when a mistake costs time or data.

github.com/Space-Dinosaurs/DinoStack
