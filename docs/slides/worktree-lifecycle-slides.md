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
Path <code>.claude/worktrees/*</code>. Created automatically by the Agent tool when <code>isolation: "worktree"</code> is set on the spawn call. Each parallel subagent gets its own copy of the tree.<br/><br/>
<strong>Cleanup trigger:</strong> once the agent returns and the conductor opens a PR (or confirms no PR is needed), the isolation worktree is redundant. The branch holds the commits. Remove immediately.
</div>
<div class="card">
<strong>Feature worktrees</strong><br/>
Path <code>.agentic/worktrees/&lt;branch-name&gt;</code>.<br/><br/>
<strong>Cleanup trigger:</strong> removed after the PR is merged. The merge (not the PR open) is the trigger.
</div>
</div>

<div class="callout">
Classified by <strong>path, never branch name</strong> (<code>bin/tests/worktree_model.py</code>'s <code>classify_entry</code> is normative - DS-118: a renamed branch can live inside either admin directory, so a name-based scheme collides). Two classes, two distinct cleanup triggers. Getting the trigger wrong leaves stale worktrees that accumulate between runs and confuse subsequent sessions.
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
- Isolation worktrees with changes persist until the conductor explicitly removes them

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
# Local branch prune - bin/ds-branch-prune (DS-153), covering
# worktree-agent-* branches and every other stale local branch:
command -v ds-branch-prune >/dev/null 2>&1 && ds-branch-prune
```

The **branch prune** (`bin/ds-branch-prune`) runs alongside it - a four-layer, first-match-wins subsumption predicate, never force-deletes unproven work:

1. Ancestry - every commit is literally on `origin/main`
2. Squash-patch equivalence - the branch's cumulative delta matches a merged PR's squash commit
3. Tip-subsumption - the tip carries no commit beyond the head that was squashed
4. Content-on-main - every file the branch touched is byte-identical to `origin/main`

- Re-run the preflight only if the user explicitly switches branches or after 30+ minutes of idle time
- Absence of proof is always a skip (`SKIP_UNPROVEN`) - a bare "a PR merged" signal is never sufficient on its own

<div class="callout">
The aggressive per-session prune is a complement to Claude Code's own 30-day orphan sweep, not a replacement. Stale worktrees accumulate between sweeps.
</div>

---

## Ad-hoc cleanup obligation + the automatic reaper

<style scoped>
  ul { font-size: 0.86em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

`/ds-implement-ticket` Phase 8's own cleanup only fires on that command's own success path. Any ad-hoc `isolation: "worktree"` spawn outside it is on the conductor: clean it up at the natural completion point, not "eventually."

`bin/ds-reap-worktrees` is the executable form of `/ds-cleanup-worktrees`'s predicate - it delegates the locked/dirty/branch-evidence decision to `worktree_model.disposition_for` (the same normative function the command file cites), never a second copy of that logic:

- Removable only when clean, unlocked, not-self, past an age floor (default 24h), free of PROTECTED gitignored content (`docs/planning/**`, `.env*`, `*.local` block by default; everything else ignored, including generated adapter output, is disposable - `--strict-ignored` for the old fail-safe-allowlist polarity), AND the branch is MERGED/an ancestor of base, or unpushed with zero unique commits - a CLOSED PR or an unpushed branch WITH unique commits is always reported, never removed
- `.agentic/**` INVERTS the polarity: protected by default, disposable only for a small named set (`events.jsonl`/telemetry, `wrap/`, `codex-prompt-generation/`, `hud/`, cache dirs) - round 3's blanket protection measured `removed=0` here since this repo dogfoods itself and every worktree accumulates telemetry; `.agentic/events.jsonl` is salvaged into the primary repo before removal, and a failed salvage blocks removal rather than risking a silent loss
- `--count-only` is the mode both passive triggers use automatically - `ds-base-sync`'s post-merge advisory note and a SessionStart nudge past a small worktree-count threshold - a single `git worktree list` call, no network, no per-entry evaluation
- Neither passive trigger ever removes anything - actual removal stays an explicit `/ds-cleanup-worktrees` or bare `ds-reap-worktrees --dry-run`/no-flags invocation
- `bin/ds-reap-all` sweeps SEVERAL repos in one invocation - discovers repos via explicit `--repo`, a root-directory scan, or a `~/.agentic/reap-all.json` fallback, then runs `ds-reap-worktrees` once per repo sequentially, forwarding every flag verbatim; it owns no safety logic of its own

<div class="callout">
Report is automatic; removal is not. The backstop closes the "I forgot" gap without silently deleting anything on your behalf.
</div>

---

## The unproven class: archive, don't accumulate

<style scoped>
  ul { font-size: 0.86em; }
  ul li { margin: 0.2em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

Even a worktree that passes every gate can still be stuck `SKIP_UNPROVEN`: a real, unmerged, never-pushed branch with no matching PR - `disposition_for` correctly refuses to guess. Left alone, these never resolve.

`bin/ds-branch-prune` already solved this for BRANCHES: archive into a verified `git bundle`, prove the restore path, then delete (`.agentic/branch-archive/`, DS-153). `ds-reap-worktrees --archive-unproven` - OPT-IN, never the default - extends that exact pattern to WORKTREES:

- Only two dispositions qualify - `SKIP_NOT_PUSHED` and `SKIP_AMBIGUOUS_NO_PR` - an explicit whitelist, never the whole `SKIP_UNPROVEN` bucket: `SKIP_PR_OPEN` (a hard safety override) and `SKIP_LS_REMOTE_ERROR` (a transient failure) are NEVER archived, even with the flag set
- Refuses to run at all in degraded gh mode (`--no-gh`, or `gh` unavailable/unauthenticated) - without PR evidence it can't tell a genuinely-unprovable branch from one behind an open PR
- `git bundle create` captures the FULL branch, then `git bundle verify` runs BEFORE any removal - a failed create or verify blocks removal entirely, same discipline as the telemetry-salvage guard
- Removes the WORKTREE only, never the branch - `bin/ds-branch-prune` still owns branch deletion
- Prints the exact (braced) restore command: `git fetch <bundle> "refs/heads/${BRANCH}:refs/heads/${BRANCH}"`
- `.agentic/worktree-archive/` is gitignored and grows unbounded - pruning it is the operator's job, same as `.agentic/branch-archive/`

<div class="callout">
Without --archive-unproven, SKIP_UNPROVEN worktrees are reported and never touched - unchanged default behavior.
</div>

---

<!-- _class: lead -->

# Isolated. Pruned. Clean.

Every spawn contained. Every merge leaves no trace.

github.com/Space-Dinosaurs/DinoStack
