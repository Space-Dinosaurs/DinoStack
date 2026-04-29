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

**Session context** is auto-written by the Stop hook to `.agentic/context.md` after every agent turn. (Legacy fallback: `~/.claude/projects/[hash]/context.md` - used only when `.agentic/context.md` does not exist.) `/wrap` is available for richer on-demand summarization. Update `MEMORY.md` at the end of any session where stable facts were learned. Close the session cleanly so the Stop hook can finish writing `context.md`: in the terminal CLI, use `/exit` rather than ctrl+c; in the desktop or web app, just close the window or tab normally rather than force-quitting.

**MEMORY.md** is auto-injected at startup by Claude Code. It stores stable facts learned about the project - architecture, key file paths, user preferences, recurring solutions. Include rationale with each entry ("chose X because Y"). Rules:
- Before adding an entry, check if it supersedes an existing one and update it in place (adjust the date)
- Remove entries that are no longer true
- Do not duplicate what is already in `AGENTS.md`
- Session-specific state (current task, next steps) belongs in `context.md`, not here
- Entry format: `- **YYYY-MM-DD:** [what and why, in one sentence]`

## Git Workflow

The main working tree stays on `development` (or `develop`) at all times. All feature work happens in worktrees.

**Base branch resolution** - resolve in this order before any work begins:
1. Use `develop` if it exists.
2. Fall back to `development` if it exists.
3. Otherwise create `develop` from `main` (fall back to `master` if `main` does not exist).

**Conductor preflight** - run this checklist before any work begins. Do not skip it when the user issues a direct command; commands are goals, not overrides for workflow hygiene.
1. What branch is the working tree on? (`git branch --show-current`)
2. Does this branch already contain unrelated commits? If yes, create a new worktree/branch instead of piling on.
3. Are there uncommitted changes? If so, do they belong to the current task? Stash or commit unrelated work before proceeding.
4. When was `origin` last fetched? Run `git fetch origin` if it has been more than a few minutes.
5. Does this task need a new worktree? Any new feature, fix, or chore gets its own worktree branched from the resolved base branch.

**Feature worktrees:** Each task or feature gets one worktree branched from `origin/development` (or `origin/develop`). Run `git fetch origin` before creating any worktree. Edit directly in the worktree - do not create sub-worktrees for individual changes.

**Parallel agent work:** When multiple agents need to work simultaneously on the same task, each parallel agent gets its own sub-worktree branching from the feature branch. Sub-worktrees are the parallelism tool, not the default for every edit.

**Branch naming:** `feature/<name>`, `fix/<name>`, `chore/<name>`.

**Merging:** Always open a PR from the feature branch into `develop`/`development` after Skeptic sign-off. PRs are required regardless of whether other sessions are active - they make in-flight work visible and force explicit conflict resolution.

**Cleanup:** Remove worktrees after the branch is merged (PR merged) or the task is explicitly closed or cancelled without a merge. Do not leave stale worktrees. Between tasks, the main tree should be on `development` with no active worktrees.

**Commit each fix immediately during testing.** Never accumulate uncommitted changes on the main working tree (`development`/`develop`) during live testing sessions. After each validated fix: create fix branch, commit, PR, merge, pull - then start the next fix. Do not batch multiple unrelated fixes. The cost of a quick PR per fix is low; the cost of untangling a divergent working tree is high.

**Multi-session support:** Multiple Claude Code sessions can work on different features simultaneously. Each session creates its own worktree from `development`. The main tree stays on `development` as neutral ground - never move it to a feature branch.

## Multi-developer coordination

The rules above address one developer running multiple Claude sessions on the same machine. When two or more developers each have their own Claude session and share a repository, additional coordination is required.

**Branch naming collisions:** When multiple developers work in parallel, generic branch names like `feature/auth-fix` can collide. For repos with multiple active developers, use a developer-prefix convention: `feature/<initials>/<name>` (e.g. `feature/th/auth-fix`). This makes in-flight branches unambiguous at a glance and prevents accidental pushes to a branch owned by someone else. This convention may be overridden per-project in the root `AGENTS.md`.

**Shared `decisions.md` ownership:** `decisions.md` is a single-writer file by convention (per the Memory Protocol). When two developers' Claude sessions both want to write to it, the second write can clobber the first. Before adding a decision: pull latest, append the new entry, then push immediately. Never batch multiple decisions into one uncommitted edit session. If a conflict occurs, merge it manually - do not let an agent auto-resolve a `decisions.md` conflict.

**Simultaneous PRs and rebase strategy:** When multiple developers have open PRs against `develop`/`development` at the same time, use a rebase-on-pull workflow rather than merge commits. Before pushing updates to a long-lived feature branch, rebase onto the latest `develop`. For short-lived PRs that land within a day, plain merges are acceptable. For any branch open more than a day, always rebase before requesting review.

**Worktree ownership:** Each developer maintains their own worktrees on their own machine. Worktrees are not shared. If two developers need to collaborate on the same feature branch, they coordinate via the remote - each pulls from and pushes to `origin`. They do not share or mount each other's local worktrees.

**Visibility via draft PRs:** PRs are the coordination mechanism. When a developer starts work, they open a draft PR early so other developers can see what is in flight. This replaces ad-hoc coordination channels and lets contributors spot conflicts before merge time.

**Project overrides:** Any of these rules may be overridden by the root `AGENTS.md` file of a project.
