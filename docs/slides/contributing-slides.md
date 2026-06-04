---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 26px;
    padding: 50px 60px;
    background: #faf8f3;
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
    border-radius: 10px;
    padding: 0.8em 1em;
    font-size: 0.9em;
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
    border-left: 4px solid #b5451f;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# Contributing to Agentic Engineering

How the repo is structured and how to make changes safely

---

## What you can contribute

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.82em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; }
</style>

<div class="columns-3">
<div class="card" style="border-left-color: #2e7d32;">
<strong>Rules & references</strong><br/>
Bug fixes, clarifications, or new protocols. Make existing rules more precise or add new reference docs.
</div>
<div class="card" style="border-left-color: #1565c0;">
<strong>Agents & commands</strong><br/>
New named agents, new slash commands, or improvements to existing ones.
</div>
<div class="card" style="border-left-color: #7b1fa2;">
<strong>Adapters</strong><br/>
New tool support (Windsurf, Continue.dev, etc.) or improvements to existing Claude Code and Cursor adapters.
</div>
</div>

---

<!-- _class: highlight -->

## The golden rule: edit in `content/`

<style scoped>
  p { font-size: 0.88em; margin: 0.25em 0; }
  pre { font-size: 0.72em; padding: 0.5em 0.8em; margin: 0.3em 0 0.8em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; }
</style>

The `content/` directory is the single source of truth. Adapter files (`.claude/`, `.cursor/`) are generated outputs - never edit them directly.

```
content/
  rules/        3 rule files (agent-methodology, code-standards, conventions)
  references/   7 reference docs (agent-team, design-goals, doc-sync-obligation, multi-developer-coordination, regression-test-obligation, skeptic-protocol, subagent-protocol)
  commands/     6 command files (implement, init-project, memory-update, ...)
  agents/       10 agent definitions (architect, debugger, engineer, ...)
```

Build scripts regenerate adapter files from `content/`. The pre-commit hook runs both builds automatically when `content/` files are staged.

<div class="callout">
If you edit a file in <code>.claude/commands/</code> directly, the pre-commit hook will overwrite your changes. Always edit the source in <code>content/</code>.
</div>

---

## How the build pipeline works

<style scoped>
  .columns .card { padding: 0.7em 0.9em; font-size: 0.82em; line-height: 1.35; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; }
</style>

<div class="columns">
<div class="card">
<strong>.claude/build.sh</strong><br/>
Commands: prepends the <code>/agentic-engineering</code> prerequisite to each command from <code>content/commands/</code>. Rules, references, and agents are symlinked directly - no copy needed.
</div>
<div class="card">
<strong>.cursor/build.sh</strong><br/>
Rules: combines YAML frontmatter sidecars from <code>.cursor/rules/frontmatter/</code> with rule content to produce <code>.mdc</code> files. References and commands are copied.
</div>
</div>

- **Symlinks vs copies**: Claude Code uses symlinks into `content/` for rules, references, and agents. Cursor needs transformed formats, so it copies.
- **Frontmatter sidecars**: Cursor rules need YAML frontmatter (`alwaysApply`, `globs`). This metadata lives in `.cursor/rules/frontmatter/*.yaml`, separate from the content.

<div class="callout">
The build is idempotent. Running <code>install.sh</code> re-runs the build automatically. You can also run <code>.claude/build.sh</code> or <code>.cursor/build.sh</code> directly.
</div>

---

## PR workflow

<style scoped>
  ol { font-size: 0.88em; }
  ol li { margin: 0.2em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; }
</style>

1. **Pull before you change anything** - `git fetch origin && git pull --rebase origin main`
2. Create a feature branch from `main`
3. Edit in `content/` - the pre-commit hook rebuilds adapter files on commit
4. Test locally: re-run `install.sh`, open a session, verify the change works
5. Open a PR - one concern per PR, describe the *why* in the body
6. PR is merged after the required number of approvals

<div class="callout">
Pull-before-edit is especially important here. This repo sees active refactors - file renames, symlink restructures, directory reshapes. A stale local branch turns clean edits into hand-merges.
</div>

---

## Creating a new adapter

<style scoped>
  ol { font-size: 0.85em; }
  ol li { margin: 0.15em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; }
</style>

1. Create `.<toolname>/` matching the tool's config directory convention
2. Convert the 3 rules into the tool's native rule format (from `content/rules/`)
3. Copy or symlink the 7 reference docs (from `content/references/`)
4. Convert the 7 commands into the tool's command format (from `content/commands/`)
5. Wire up lifecycle hooks - risk reminder (before prompt) and context save (on stop)
6. Write `.<toolname>/README.md` with setup instructions
7. Update root `README.md` with the new adapter

<div class="callout">
Adapters translate format, not substance. If a rule doesn't apply to your tool, keep the rule but note the limitation in the adapter's README.
</div>

---

<!-- _class: lead -->

# Edit content. Build adapters. Test locally.

One source of truth, many delivery formats.

github.com/Space-Dinosaurs/agentic-engineering
