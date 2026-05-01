## Writing Style

Never use em dashes (--). Use a regular hyphen (-) instead in all generated text, copy, comments, documentation, and commit messages.

## Project Structure Convention

`AGENTS.md` is the canonical project-instructions file across Claude Code, Codex, Cursor, and other tools. Claude Code reads it via a one-line `CLAUDE.md` containing `@AGENTS.md`. Always structure projects with a lean root `AGENTS.md` and deeper context in subdirectory `AGENTS.md` files co-located with the code they describe.

- **Root `AGENTS.md`** - one-paragraph summary, resolved architecture decisions, cross-cutting conventions, repo structure map. Keep it under ~40 lines. This limit applies to project root AGENTS.md files. The global `~/.claude/CLAUDE.md` is exempt.
- **Subdirectory `AGENTS.md`** (e.g. `backend/AGENTS.md`, `contracts/AGENTS.md`) - loaded only when working in that directory. Can be as detailed as needed without polluting other contexts.
- **`.claude/settings.json`** - project-scoped MCP servers and shared config (safe to commit).
- **`.claude/settings.local.json`** - secrets and local env values (always gitignored).

When starting a new project, run `/init-project` to scaffold this structure automatically.

## Session Context and Memory

**Session startup:** Read `.agentic/context.md` as the first action of every session - standalone, never in parallel with other tool calls.

**Meta-divergence sweep at session start.** After reading `.agentic/context.md`, the conductor sweeps `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For each such event with non-empty `data.divergence.critical_missed` or `data.divergence.major_missed`, emit at the next user-facing turn boundary:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Then append `original_task_id` to the tracker file. The sweep is a standalone scan - not parallel with other startup tool calls. Tracker file format is one `original_task_id` per line, append-only, gitignored under the `.agentic/` umbrella. File-absent equals empty set. This catches divergences whose meta-Skeptic completed asynchronously after the originating session ended. See `content/references/skeptic-protocol.md` Section 13 for the full specification.

**Session context** is auto-written by the Stop hook to `.agentic/context.md` after every agent turn. (Legacy fallback: `~/.claude/projects/[hash]/context.md` - used only when `.agentic/context.md` does not exist.) `/wrap` is available for richer on-demand summarization. Update `MEMORY.md` at the end of any session where stable facts were learned. Close the session cleanly so the Stop hook can finish writing `context.md`: in the terminal CLI, use `/exit` rather than ctrl+c; in the desktop or web app, just close the window or tab normally rather than force-quitting.

**MEMORY.md** is auto-injected at startup by Claude Code. It stores stable facts learned about the project - architecture, key file paths, user preferences, recurring solutions. Include rationale with each entry ("chose X because Y"). Rules:
- Before adding an entry, check if it supersedes an existing one and update it in place (adjust the date)
- Remove entries that are no longer true
- Do not duplicate what is already in `AGENTS.md`
- Session-specific state (current task, next steps) belongs in `context.md`, not here
- Entry format: `- **YYYY-MM-DD:** [what and why, in one sentence]`

## The Intent Layer

A project's intent is encoded across a small set of artifacts. Treat them as a coherent layer, not as unrelated files:

- `AGENTS.md` - project-level decisions and conventions (tool-agnostic).
- `MEMORY.md` - stable facts learned about the project, with rationale.
- `decisions.md` - the project's decision log, where used.
- `qa.md` - QA triggers and project-specific quirks the QA engineer needs to know.
- Module manifests - file-level intent embedded in the source itself (see `module-manifest.md`).
- `glossary.md` - the project's Ubiquitous Language (see below).

Together these form the project's **intent layer**. Drift in any of them is **intent debt** - the system stops reflecting what we meant to build, and downstream agents and humans drift along with the artifacts. Keep them current. A stale entry is worse than a missing one because readers trust it.

### Ubiquitous Language (`glossary.md`)

A `glossary.md` at the project root (or referenced from the root `AGENTS.md`) holds the project's domain terms - the **Ubiquitous Language** that humans, code, and LLM agents all use to describe the system. When a glossary is present:

- Agents prefer existing terms over inventing synonyms. If the glossary calls it "shipment", do not introduce "delivery", "consignment", or "package" in code, comments, prompts, or docs without first updating the glossary.
- The Skeptic flags a synonym-of-an-existing-term as a **Minor** finding (style + intent drift).
- The glossary is part of the intent layer above - keep it current as the domain vocabulary evolves.

A glossary is optional; not every project needs one. But once introduced, it is binding on the project.

## Git Workflow

**Conductor does not create worktrees for itself.** The conductor edits directly on its current branch. Worktrees are exclusively for subagents.

**Base branch resolution** - resolve in this order before any work begins:
1. Use `develop` if it exists.
2. Fall back to `development` if it exists.
3. Otherwise create `develop` from `main` (fall back to `master` if `main` does not exist).

**Conductor preflight** - run this checklist before any work begins. Do not skip it when the user issues a direct command; commands are goals, not overrides for workflow hygiene.
1. What branch is the working tree on? (`git branch --show-current`)
2. Does this branch already contain unrelated commits? If yes, start fresh from the base branch before proceeding.
3. Are there uncommitted changes? If so, do they belong to the current task? Stash or commit unrelated work before proceeding.
4. When was `origin` last fetched? Run `git fetch origin` if it has been more than a few minutes.

**Subagent worktrees:** Each parallel subagent gets its own worktree, branched from the conductor's current branch. Worktrees are created at `.agentic/worktrees/<branch-name>` under the project root (already gitignored via the `.agentic/` umbrella). The conductor merges each subagent branch back after sign-off and removes the worktree.

```bash
# Create a subagent worktree:
git worktree add .agentic/worktrees/<branch-name> -b <branch-name> HEAD

# Remove after merge:
git worktree remove .agentic/worktrees/<branch-name>
git branch -d <branch-name>
```

**Branch naming:** `feature/<name>`, `fix/<name>`, `chore/<name>`.

**Merging:** Always open a PR from the subagent branch into `develop`/`development` after Skeptic sign-off. PRs are required regardless of whether other sessions are active - they make in-flight work visible and force explicit conflict resolution.

**Cleanup:** Remove worktrees after the subagent branch is merged or the task is explicitly closed. Do not leave stale worktrees. Between tasks there should be no active subagent worktrees.

**Commit each fix immediately during testing.** Never accumulate uncommitted changes during live testing sessions. After each validated fix: commit, PR, merge, pull - then start the next fix. Do not batch multiple unrelated fixes.

**Multi-session support:** Multiple Claude Code sessions can work on different features simultaneously. Each session operates on its own branch. No worktree coordination is needed between sessions at the conductor level.

Multi-developer coordination guidance lives in `content/references/multi-developer-coordination.md`.
