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

# Risk Classification

Signal-based decisions that drive every delegation choice

---

## The three tiers

<style scoped>
  .columns-3 .card { padding: 0.8em 1em; font-size: 0.82em; line-height: 1.4; }
  .columns-3 .card strong { font-size: 1.1em; display: block; margin-bottom: 0.4em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #3ad99a;">
<strong>Trivial</strong>
Delegate to a worktree-isolated engineer. No Skeptic. No brief file. The conductor never edits the shippable tree directly.
</div>
<div class="card" style="border-left-color: #18E0FF;">
<strong>Low</strong>
Direct action. Brief inline self-check only. No Worker spawn. No Skeptic.
</div>
<div class="card" style="border-left-color: #ff5d73;">
<strong>Elevated</strong>
Worker + fresh independent Skeptic. State the classification before starting. Any single Elevated signal triggers this path.
</div>
</div>

<div class="callout">
A fourth path exists: <strong>Elevated + Cleanup</strong> - Worker, then Skeptic, then <code>/simplify</code>, then a narrow second Skeptic pass. Used when the diff accumulates cruft that warrants a dedicated cleanup round.
</div>

---

<!-- _class: highlight -->

## The tier table

<style scoped>
  table { font-size: 0.78em; width: 100%; }
  th, td { padding: 0.3em 0.65em; }
  .callout { font-size: 0.79em; padding: 0.35em 1em; margin-top: 0.35em; }
</style>

| Level | Delegation | Review | Declaration |
|---|---|---|---|
| Trivial | Worktree-isolated engineer (no Skeptic, no brief) | None | Silent |
| Low | Direct action | Brief inline self-check | Silent |
| Elevated | Worker | Fresh independent Skeptic | Stated before starting |
| Elevated + Cleanup | Worker | Skeptic -> `/simplify` -> Skeptic (narrow) | Stated before starting |

<div class="callout">
<strong>When in doubt, classify as Elevated.</strong> Risk is assessed by signal, not by the conductor's subjective estimate of difficulty. A conductor that re-evaluates the spawn decision because an edit "feels straightforward" is violating the protocol - regardless of whether the output turns out to be correct.
</div>

---

## Elevated signals - what pushes a task up

<style scoped>
  .columns { gap: 1.2em; margin-bottom: 0.5em; }
  .columns .card { font-size: 0.76em; line-height: 1.4; padding: 0.8em 1em; }
  ul { font-size: 0.79em; margin: 0; padding-left: 1.1em; }
  li { margin: 0.1em 0; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #ff5d73;">

**Scope and effect**
- Any code edit with behavioral effect (write/modify/delete)
- Multi-file change (any size)
- New file creation (any file)
- Changes to shared utilities (single-file but high blast radius)
- Logic with emergent/non-obvious cross-component interactions

</div>
<div class="card" style="border-left-color: #b06bff;">

**Domain and reversibility**
- Security / auth / crypto / payments / secrets
- Irreversible operation (delete, migration, schema change, force push)
- Architecture decision constraining future choices
- Modifies protocol or infrastructure files
- Production or shared state
- Configuration changes

</div>
</div>

Any one of these signals is sufficient. There is no majority vote - a single match escalates.

---

## Elevated signals - continued

<style scoped>
  .columns { gap: 1.2em; margin-bottom: 0.4em; }
  .columns .card { font-size: 0.8em; line-height: 1.4; padding: 0.8em 1em; }
  .callout { font-size: 0.79em; padding: 0.35em 1em; margin-top: 0.3em; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #E9B521;">

**Externals and unknowns**
- Touches external APIs or services
- Unfamiliar codebase area
- Bash with side effects (writes, deletes, network, DB)
- Anything where a mistake costs time or data
- User signals high stakes

</div>
<div class="card" style="border-left-color: #18E0FF;">

**Planning and investigation**
- Document synthesis / architecture / planning
- Research that produces an artifact (doc, plan, recommendation)
- Context preservation: a sequence of exploratory tool calls collectively constitutes investigation - classify by the task, not the individual call

</div>
</div>

<div class="callout">
<strong>No re-deliberation.</strong> Once a task matches an Elevated signal, classify it and spawn. Generalized: a decision stands until NEW evidence arrives, and a reversal must name the new information - re-reading the same source is not new information.
</div>

---

## Trivial signals - all must hold

<style scoped>
  ul { font-size: 0.84em; }
  li { margin: 0.18em 0; }
  p { font-size: 0.84em; margin: 0.2em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

ALL of the following must hold - any single disqualifier pushes to Elevated:

- Touches exactly one file (or one file plus its colocated test/snapshot)
- No change to control flow, data flow, state shape, API surface, or types
- No change to shared design tokens, theme files, config, env, or CI
- No change to anything a downstream consumer imports (exported symbols, public CSS classes, route paths)
- Reversible with a one-line revert
- No security, auth, permissions, billing, or PII surface involved

**Canonical Trivial examples:** a hardcoded color, padding, or font-size in one component; a button label or alt text; a typo fix; Tailwind class tweaks on one element.

<div class="callout">
<strong>NOT Trivial even if it feels small:</strong> edits to <code>tailwind.config.*</code>, theme files, CSS variables, or any shared token file; any change touching 2+ files; anything in auth, payments, or data-handling paths; renames, even local ones.
</div>

<div class="callout">
<strong>Implicit Trivial batching.</strong> A series of related Trivial tweaks can share one draft PR: the first push opens it, later related tweaks continue the same branch via detached-HEAD seeding, and an explicit or implicit ship trigger merges it. Full mechanism in the worktree-lifecycle reference doc.
</div>

---

## The Low path and context preservation

<style scoped>
  p { font-size: 0.86em; margin: 0.25em 0; }
  ul { font-size: 0.84em; }
  li { margin: 0.15em 0; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.5em; }
</style>

Low-risk actions include: clearly reversible reads (no writes); diagnostic-only logging across any number of files where every change has zero behavioral effect; file renaming with no content changes; UI-only copy changes; targeted wording fixes to already-reviewed content.

In `relaxed`, ephemeral chat advice may also be Low only when it is chat-only, write-free,
non-binding, and not acceptance criteria or governing downstream input. Then scan every remaining
Elevated signal; any match still wins. After activation and skill loading, answer from context
already held or classify Elevated before the first project-content read. `default` and `strict` are unchanged.

**Context preservation rule:** apply risk to the task, not the individual tool call.

- A read is **Low** when you know what you are looking for and are confirming a specific fact
- A read is **Elevated** when the goal is to understand something - tracing behavior, finding a root cause, or mapping blast radius
- A sequence of reads, greps, and bashes that collectively constitute investigation is an Elevated task - regardless of whether each individual step looks Low in isolation

<div class="callout">
Do not start project exploration as Low. Explicit unfamiliar or multi-read requests are Elevated before any project-content read. Spawn the appropriate named agent: investigator for codebase exploration, debugger for root cause analysis, architect for design questions.
</div>

---

## Letter equals spirit

<style scoped>
  blockquote { font-size: 0.9em; margin: 0.4em 0; }
  p { font-size: 0.86em; margin: 0.25em 0; }
  ul { font-size: 0.84em; }
  li { margin: 0.18em 0; }
  .callout { font-size: 0.82em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

> "Violating the letter of these rules is violating the spirit. 'I followed the intent' after skipping a required step is not a defense."

**Downward tie-break counterweight:** the default "when in doubt, classify Elevated" is overridden only when a named Low or Trivial override's full definition - including every exclusion clause - is affirmatively satisfied and zero other Elevated signals are present.

- "Provably small" means the override can be named and each exclusion individually confirmed against the diff
- A general impression that the change looks safe does not qualify

The declaration format makes classification explicit:

```
Risk: Elevated - [specific signal]
Tier: 2 (role default)
Applying adversarial review.
```

<div class="callout">
Classify once, act once. A conductor that self-negotiates around the spawn threshold is violating the protocol regardless of whether the output happens to be correct.
</div>

---

<!-- _class: lead -->

# Signal in. Decision out.

One Elevated signal is enough. When in doubt, go Elevated.

github.com/Space-Dinosaurs/DinoStack
