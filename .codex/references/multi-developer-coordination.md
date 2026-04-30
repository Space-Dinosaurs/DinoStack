<!--
Purpose: Coordination rules for repos with multiple developers each running their
         own Claude (or other harness) sessions against a shared remote.

Public API: prose reference; consumed by readers (humans and agents) when the
            single-developer git workflow in conventions.md is insufficient.

Upstream deps: content/rules/conventions.md (Git Workflow section), the
               project Memory Protocol's single-writer rule for decisions.md.

Downstream consumers: content/rules/conventions.md (links here via a one-line
                      pointer); any agent or human reasoning about cross-developer
                      branch, PR, or decisions.md coordination.

Failure modes: pure documentation; no runtime behavior. Stale guidance is the
               primary risk - update when branch-naming, PR, or decisions.md
               protocols change in conventions.md or the Memory Protocol.

Performance: standard.
-->

# Multi-developer coordination

The rules in `content/rules/conventions.md` (Git Workflow) address one developer running multiple Claude sessions on the same machine. When two or more developers each have their own Claude session and share a repository, additional coordination is required.

**Branch naming collisions:** When multiple developers work in parallel, generic branch names like `feature/auth-fix` can collide. For repos with multiple active developers, use a developer-prefix convention: `feature/<initials>/<name>` (e.g. `feature/th/auth-fix`). This makes in-flight branches unambiguous at a glance and prevents accidental pushes to a branch owned by someone else. This convention may be overridden per-project in the root `AGENTS.md`.

**Shared `decisions.md` ownership:** `decisions.md` is a single-writer file by convention (per the Memory Protocol). When two developers' Claude sessions both want to write to it, the second write can clobber the first. Before adding a decision: pull latest, append the new entry, then push immediately. Never batch multiple decisions into one uncommitted edit session. If a conflict occurs, merge it manually - do not let an agent auto-resolve a `decisions.md` conflict.

**Simultaneous PRs and rebase strategy:** When multiple developers have open PRs against `develop`/`development` at the same time, use a rebase-on-pull workflow rather than merge commits. Before pushing updates to a long-lived feature branch, rebase onto the latest `develop`. For short-lived PRs that land within a day, plain merges are acceptable. For any branch open more than a day, always rebase before requesting review.

**Worktree ownership:** Each developer maintains their own worktrees on their own machine. Worktrees are not shared. If two developers need to collaborate on the same feature branch, they coordinate via the remote - each pulls from and pushes to `origin`. They do not share or mount each other's local worktrees.

**Visibility via draft PRs:** PRs are the coordination mechanism. When a developer starts work, they open a draft PR early so other developers can see what is in flight. This replaces ad-hoc coordination channels and lets contributors spot conflicts before merge time.

**Project overrides:** Any of these rules may be overridden by the root `AGENTS.md` file of a project.
