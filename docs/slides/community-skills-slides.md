---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
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
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: white;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #f8f9fa;
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
    border-radius: 10px;
    padding: 0.8em 1em;
    font-size: 0.9em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #0f3460;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #0f3460;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #e8f4f8;
    border-left: 4px solid #0f3460;
    padding: 0.5em 1em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
    font-size: 0.9em;
  }
  pre {
    font-size: 0.8em;
    padding: 0.5em 0.8em;
    margin: 0.3em 0 0.8em 0;
  }
  code {
    font-size: 0.9em;
  }
  blockquote {
    border-left: 4px solid #0f3460;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# Community Skills

Task-specific skills anyone can build, share, and install

---

## What are community skills?

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; }
</style>

- Optional, task-specific skills contributed by the community
- Each skill is **self-contained** - works on its own without the core methodology installed
- When agentic-engineering *is* installed, skills automatically benefit from risk classification, adversarial review, and the full agent team
- Installed and managed via the `/community-skills` command
- Browse the catalog at **github.com/Solara6/community-skills**

<div class="callout">
The key design rule: every community skill must work standalone. If someone installs just the skill without agentic-engineering, it still functions - they just don't get the methodology layer on top.
</div>

---

<!-- _class: highlight -->

## Anatomy of a skill

<style scoped>
  .columns .card { padding: 0.7em 0.9em; font-size: 0.85em; line-height: 1.35; }
  pre { font-size: 0.72em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

<div class="columns">
<div class="card">
<strong>SKILL.md</strong><br/>
YAML frontmatter with <code>name</code> and <code>description</code>, plus full instructions. The description triggers auto-activation - Claude matches it against the user's request.
</div>
<div class="card">
<strong>README.md</strong><br/>
User-facing docs: what it does, prerequisites, installation command, usage examples, and author. Follows a standard template.
</div>
</div>

```
community-skills/
  my-skill/
    SKILL.md       ← instructions + auto-trigger metadata
    README.md      ← user docs and install instructions
    references/    ← optional supporting files
```

<div class="callout">
The <code>description</code> field is critical - it determines when Claude auto-activates the skill. "Use when the user asks to generate slides" is good. "A helpful skill" is useless.
</div>

---

## Install and manage

<style scoped>
  pre { font-size: 0.78em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  p { font-size: 0.9em; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

The `/community-skills` command handles everything:

```
/community-skills list              Show all available skills
/community-skills install <name>    Symlink skill into ~/.claude/skills/
/community-skills uninstall <name>  Remove the symlink
/community-skills installed         List what you have installed
```

Installation creates a symlink from `~/.claude/skills/<name>` to the skill directory. No files are copied - updates to the skill repo flow through automatically.

<div class="callout">
Safety check: uninstall only removes symlinks that point into the community-skills directory. It will not touch core skills or anything installed from elsewhere.
</div>

---

## With and without the methodology

<style scoped>
  .columns .card { padding: 0.7em 0.9em; font-size: 0.85em; line-height: 1.35; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

<div class="columns">
<div class="card" style="border-left-color: #2e7d32;">
<strong>With agentic-engineering</strong><br/>
Risk classification applies to skill operations. Elevated work gets adversarial review. Named agents coordinate. The skill's output goes through the same quality gates as everything else.
</div>
<div class="card" style="border-left-color: #e65100;">
<strong>Without agentic-engineering</strong><br/>
The skill functions independently using its own instructions. No risk classification, no Skeptic review, no agent delegation. Still useful - just less structured.
</div>
</div>

<div class="callout">
This is why community skills must never add an <code>/agentic-engineering</code> prerequisite. The methodology is a bonus, not a dependency.
</div>

---

## Contributing a skill

<style scoped>
  ol { font-size: 0.88em; }
  ol li { margin: 0.25em 0; }
  .callout { font-size: 0.85em; padding: 0.4em 1em; }
</style>

1. Copy `community-skills/_template/` to `community-skills/your-skill-name/`
2. Fill in **SKILL.md** - write a specific `description` that tells Claude when to activate
3. Fill in **README.md** - what it does, prerequisites, usage examples
4. Add an entry to the `community-skills/README.md` catalog table
5. **Test standalone** - temporarily remove `~/.claude/skills/agentic-engineering` and verify the skill still works
6. Open a PR to the community-skills repo

<div class="callout">
Step 5 is the most important. If your skill breaks without the core methodology, it's not a community skill - it's a feature request for the core system.
</div>

---

<!-- _class: lead -->

# Build it. Share it. Install it.

Self-contained skills that get better with the methodology - but never require it.

github.com/Solara6/community-skills
