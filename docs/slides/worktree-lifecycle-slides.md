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

# Worktree Lifecycle

Isolation by default. Clean up by rule.

---

## Why worktree isolation matters

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- The conductor's main worktree holds untracked scaffolding: `.agentic/`, loop-state files - NOT in-flight planning artifacts, which are committed and pushed as soon as they are authored
- A subagent running in the same tree can stage and commit conductor files it was never meant to ship
- This does not surface as a test break - it surfaces as a reviewer asking "why is `.agentic/loop-state.json` in this PR?" days later
- Worktree isolation prevents both pollution and cross-engineer commit contamination when parallel spawns share a tree
- Every `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST use `isolation: "worktree"`

<div class="callout">
The conductor never edits the shippable tree directly - not even for Trivial one-line changes. Only the execution location moves off the primary checkout.
</div>

---

<!-- _class: highlight -->

## Two classes of worktree

<style scoped>
  .columns .card { font-size: 0.82em; line-height: 1.45; padding: 1em 1.1em; }
  .columns .card strong { font-size: 1.05em; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
</style>

<div class="columns">
<div class="card">
<strong>Isolation worktrees</strong><br/>
Named <code>worktree-agent-*</code>. Created automatically by the Agent tool when <code>isolation: "worktree"</code> is set on the spawn call. Each parallel subagent gets its own copy of the tree.<br/><br/>
<strong>Cleanup trigger:</strong> once the agent returns and the conductor opens a PR (or confirms no PR is needed), the isolation worktree is redundant. The branch holds the commits. Remove immediately.
</div>
<div class="card">
<strong>Feature worktrees</strong><br/>
Named <code>feature/*</code>, <code>fix/*</code>, or <code>chore/*</code>. Created at <code>.agentic/worktrees/&lt;branch-name&gt;</code>.<br/><br/>
<strong>Cleanup trigger:</strong> removed after the PR is merged. The merge (not the PR open) is the trigger.
</div>
</div>

<div class="callout">
Two classes, two distinct cleanup triggers. Getting the trigger wrong leaves stale worktrees that accumulate between runs and confuse subsequent sessions.
</div>

---

## The isolation mandate

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.5em; }
  pre { font-size: 0.72em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
</style>

**There is no in-place exception.** The mandate applies to every shippable-edit spawn:

- Elevated-risk engineer spawns require isolation (standard case)
- Trivial-path solo engineer spawns also require isolation - the lightweight posture (no Skeptic, no brief) is preserved; only the execution location changes
- qa-engineer spawns require isolation
- release-orchestrator spawns require isolation

The Agent tool creates isolation worktrees automatically when `isolation: "worktree"` is set on the spawn call. No manual `git worktree add` is needed or correct for isolation worktrees - that command is for manually-managed feature/subagent worktrees only.

The version floor matters: on Claude Code builds predating the isolated-worktree own-file fix, an isolated engineer self-denies on its own files and deadlocks. The fix is a hard floor for the delegation model.

<div class="callout">
"Conductor never edits the shippable tree directly" is not a convention. It is the mechanism that prevents scaffolding files from appearing in PRs.
</div>

---

## Cleanup: isolation worktrees

<style scoped>
  ul { font-size: 0.88em; }
  ul li { margin: 0.25em 0; }
  pre { font-size: 0.68em; padding: 0.35em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Trigger: agent returned output AND conductor has opened a PR (or confirmed no PR needed).

```bash
# Verify no uncommitted changes before removing:
git -C <worktree-path> status --porcelain
# If clean (no output), remove the worktree and local branch:
git worktree remove <worktree-path>
git branch -D <branch-name> 2>/dev/null || true
# Safe: the PR is backed by the branch on origin, not this local ref.
# Only the redundant local branch is removed; pushed commits and PR are unaffected.
# If modified tracked files exist, inspect first then force-remove:
# git worktree remove --force <worktree-path>
```

- The local branch lingers after `worktree remove` without an explicit `branch -D`
- Force-remove is only safe after confirming nothing important is uncommitted
- Isolation worktrees with changes persist until the conductor explicitly removes them - subagents do not have hooks

<div class="callout">
Isolation worktrees with no changes are auto-cleaned by the Agent tool. Those with changes are the conductor's responsibility.
</div>

---

## Cleanup: feature worktrees

<style scoped>
  pre { font-size: 0.72em; padding: 0.4em 0.7em; line-height: 1.3; margin: 0.2em 0 0.5em 0; }
  ul { font-size: 0.88em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Trigger: the PR is merged (not when the PR is opened).

```bash
gh pr merge <number> --squash --delete-branch
git worktree remove --force <worktree-path>
git branch -D <branch-name>   # if not auto-deleted by --delete-branch
git worktree prune             # clean up any stale metadata
```

- `--delete-branch` on `gh pr merge` may not auto-delete in all gh CLI versions; the explicit `git branch -D` is the fallback
- `git worktree prune` cleans up stale metadata left over from worktrees removed without the normal command

Do not leave stale worktrees between tasks. Between tasks there should be no active subagent worktrees.

<div class="callout">
Feature worktrees outlive the PR open state; isolation worktrees do not. That asymmetry is the main source of incorrect cleanup timing.
</div>

---

## Session-start prune

<style scoped>
  pre { font-size: 0.66em; padding: 0.35em 0.7em; line-height: 1.28; margin: 0.15em 0 0.5em 0; }
  ul { font-size: 0.86em; }
  ul li { margin: 0.15em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Run **once at session start** in the conductor preflight - not before every subagent spawn. Cache the resolved base branch for the session:

```bash
git fetch origin
git worktree prune
# Delete orphaned worktree-agent-* branches not checked out in a live worktree:
git branch | grep 'worktree-agent-' | sed 's/^[* ]*//' | while read b; do
  git worktree list | grep -qF "[$b]" || git branch -D "$b"
done
```

The **branch prune** runs alongside it. Three safe signals only - never force-deletes unproven work:

1. `[gone]`-upstream branches (merged + remote-deleted via squash + `--delete-branch`)
2. Branches fully merged into `origin/main`
3. Orphaned `worktree-agent-*` branches whose worktree no longer exists

- Re-run the preflight only if the user explicitly switches branches or after 30+ minutes of idle time
- `[gone]` is the reliable merged-and-cleaned signal after a history rewrite; ancestry alone misses squash-merged branches

<div class="callout">
The aggressive per-session prune is a complement to Claude Code's own 30-day orphan sweep, not a replacement. Stale worktrees accumulate between sweeps.
</div>

---

<!-- _class: lead -->

# Isolated. Pruned. Clean.

Every spawn contained. Every merge leaves no trace.

github.com/Space-Dinosaurs/DinoStack
