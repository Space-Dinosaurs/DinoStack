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

Then append `original_task_id` to the tracker file. The sweep is a standalone scan - not parallel with other startup tool calls. Tracker file format is one `original_task_id` per line, append-only, gitignored under the `.agentic/` umbrella. File-absent equals empty set. This catches divergences whose meta-Skeptic completed asynchronously after the originating session ended.

**Pagination (vicious loop defense):** The sweep MUST NOT read the full `.agentic/events.jsonl` on every boot. It reads only events with `ts` strictly greater than the timestamp stored in `.agentic/.meta-divergence-last-sweep` (ISO8601 UTC, single line, file-absent = first run). On first run (no tracker file), the scan is capped to the most recent 100 lines of the events file. After the sweep completes, the conductor writes the current ISO8601 UTC timestamp to the tracker file (atomic: tmp + `mv`). This prevents the vicious loop where growing telemetry consumes ever more context on every session start. See `content/references/skeptic-protocol.md` Section 14 "Session-start sweep pagination" for the full procedure.

**Session context** is auto-written by the Stop hook to `.agentic/context.md` after every agent turn. (Legacy fallback: `~/.claude/projects/[hash]/context.md` - used only when `.agentic/context.md` does not exist.) `/wrap` is available for richer on-demand summarization. Update `MEMORY.md` at the end of any session where stable facts were learned. Close the session cleanly so the Stop hook can finish writing `context.md`: in the terminal CLI, use `/exit` rather than ctrl+c; in the desktop or web app, just close the window or tab normally rather than force-quitting.

**Per-developer session log:** `.agentic/session-log/<developer_id>.jsonl` - committed per-developer session rollup for team telemetry (Stop hook writer; see `content/references/events-log.md` "Per-developer session log"). Requires `agentic-identity init <handle>` to activate. Aggregated via `agentic-cost team`.

**MEMORY.md** is auto-injected at startup by Claude Code. It stores stable facts learned about the project - architecture, key file paths, user preferences, recurring solutions. Include rationale with each entry ("chose X because Y"). Rules:
- Before adding an entry, check if it supersedes an existing one and update it in place (adjust the date)
- Remove entries that are no longer true
- Do not duplicate what is already in `AGENTS.md`
- Session-specific state (current task, next steps) belongs in `context.md`, not here
- Entry format: `- **YYYY-MM-DD:** [what and why, in one sentence]`

## The Intent Layer

A project's intent is encoded across a small set of artifacts. Treat them as a coherent layer, not as unrelated files:

- `docs/overview/vision.md` - product vision and purpose; operator-owned, agents read but never write
- `docs/overview/requirements.md` - scoped functional and non-functional requirements; operator-owned, agents read but never write
- `AGENTS.md` - project-level decisions and conventions (tool-agnostic).
- `MEMORY.md` - stable facts learned about the project, with rationale.
- `decisions.md` - the project's decision log, where used.
- `qa.md` - QA triggers and project-specific quirks the QA engineer needs to know.
- Module manifests - file-level intent embedded in the source itself (see `module-manifest.md`).
- `glossary.md` - the project's Ubiquitous Language (see below).

Together these form the project's **intent layer**. Drift in any of them is **intent debt** - the system stops reflecting what we meant to build, and downstream agents and humans drift along with the artifacts. Keep them current. A stale entry is worse than a missing one because readers trust it.

### Project Overview Layer

`docs/overview/vision.md` and `docs/overview/requirements.md` are operator-authored documents that capture durable product intent above the task level. When present, Architect and Investigator read them before producing output; the design or investigation must not contradict them.

**What each file contains:**
- `vision.md` - why the product exists, who it serves, what outcome it delivers (one screen, narrative form)
- `requirements.md` - scoped functional and non-functional requirements, as bulleted statements

**Rules:**
- Operator-owned: agents read, never write or propose edits to these files
- Optional and graceful: if `docs/overview/` does not exist or these files are absent, nothing breaks
- Not a replacement for per-task Briefs: the Brief's "Problem" and "Constraints" fields should be consistent with these docs when present, but overview docs do not replace task-scoped planning artifacts

### Project Config (`.agentic/config.json`)

`.agentic/config.json` holds project-level methodology toggles the conductor reads to adjust orchestration behavior. It is **committed, not gitignored** - like `qa.md` and `deploy.md`, it is portable project intent that travels with the repo (the `.agentic/` umbrella ignore must carve it out; see `.gitignore`). It is seeded with defaults by `/init-project`. Six toggles:

- `debugger_on_failure` - boolean, default `false`. When `true`, the Elevated-path quality gate in `/implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass. Opt-in; the default preserves existing behavior. A Trivial-path ticket never invokes the Debugger regardless of this toggle.
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior. **Canonical definition lives in `content/references/planning-artifacts.md` §`qa_default_skip` (canonical definition)** - this entry is a cross-reference only and does not restate the semantics.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. `budget` routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - those require explicit `Tier: 3` regardless of the project `model_profile`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory` | `blocking`), default `advisory`. Controls what happens when the conductor finds a missing required dependency during capability preflight. `advisory` emits a warning with the install command and proceeds with the spawn. `blocking` refuses the spawn when any required dependency remains missing after auto-install. Default is `advisory` at P0; flip to `blocking` is a one-line change once every agent under `content/agents/` has a populated `capabilities:` manifest. See `content/references/capability-preflight.md` for the full preflight protocol.
- `perceptual_diff_enabled` - boolean, default `false`. When `true`, qa-engineer runs Playwright `toHaveScreenshot` against committed baselines in `tests/visual-baselines/` and raises auto-Major on drift exceeding per-scenario `tolerance`. Opt-in; baseline maintenance overhead justifies the default of `false`.

The file is operator-tunable but optional and graceful: if absent, every toggle takes its default and nothing breaks.

### Ubiquitous Language (`glossary.md`)

A `glossary.md` at the project root (or referenced from the root `AGENTS.md`) holds the project's domain terms - the **Ubiquitous Language** that humans, code, and LLM agents all use to describe the system. When a glossary is present:

- Agents prefer existing terms over inventing synonyms. If the glossary calls it "shipment", do not introduce "delivery", "consignment", or "package" in code, comments, prompts, or docs without first updating the glossary.
- The Skeptic flags a synonym-of-an-existing-term as a **Minor** finding (style + intent drift).
- The glossary is part of the intent layer above - keep it current as the domain vocabulary evolves.

A glossary is optional; not every project needs one. But once introduced, it is binding on the project.

## Git Workflow

**Conductor never edits shippable artifacts directly - including Trivial one-line changes.** Every shippable change is delegated to a worktree-isolated `engineer` branched from `origin/main`. The conductor edits only exempt artifacts in its own checkout. Worktrees are exclusively for subagents.

**Shippable/exempt classifier (4-rule precedence, first match wins):**
1. `.agentic/**` -> EXEMPT (conductor sole-writer).
2. begins `docs/planning/` -> EXEMPT (Briefs/Plans/ADRs/planning subdirs). ALL other docs SHIPPABLE, by name: `docs/research/`, `docs/_archive/`, `docs/overview/`, `docs/technical/`, `docs/images/`, `docs/slides/`, file `docs/agentic-engineering.html` (Vercel `outputDirectory: docs`).
3. conductor-direct PRINT/DECISION/RESOLVER-EXECUTION -> EXEMPT.
4. any other tracked-file write -> SHIPPABLE -> delegate to worktree-isolated engineer (Trivial: no Skeptic/no brief; Elevated: full Worker+Skeptic).

**Base branch resolution** - always use `main` (fall back to `master` if `main` does not exist). Never use `develop` or `development`.

**Conductor preflight** - run this checklist ONCE at session start. Do not skip it when the user issues a direct command; commands are goals, not overrides for workflow hygiene. Cache the resolved base branch in-context for the session; do not re-run the full preflight before every subagent spawn. Re-run only if the user explicitly switches branches or after 30+ minutes of idle time.
1. What branch is the working tree on? (`git branch --show-current`)
2. Does this branch already contain unrelated commits? If yes, start fresh from the base branch before proceeding.
3. Are there uncommitted changes? If so, do they belong to the current task? Stash or commit unrelated work before proceeding.
4. When was `origin` last fetched? Run `git fetch origin` if it has been more than a few minutes.
5. Resolve the base branch (see **Base branch resolution** below) and cache it as `BASE_BRANCH` for the session.
6. Run worktree prune (see `content/sections/10-worktree-lifecycle.md`) and delete stale `worktree-agent-*` branches.

**Subagent worktrees:** Each parallel subagent gets its own worktree, branched from the conductor's current branch. Worktrees are created at `.agentic/worktrees/<branch-name>` under the project root (already gitignored via the `.agentic/` umbrella). The conductor merges each subagent branch back after sign-off and removes the worktree.

```bash
# Create a subagent worktree:
git worktree add .agentic/worktrees/<branch-name> -b <branch-name> HEAD

# Remove after merge:
git worktree remove .agentic/worktrees/<branch-name>
git branch -d <branch-name>
```

**Branch naming:** `feature/<name>`, `fix/<name>`, `chore/<name>`.

**Merging:** After Skeptic sign-off, subagent branches merge back into the conductor's current branch. The conductor's branch (not the individual subagent branch) then opens a PR into `main`. PRs are required regardless of whether other sessions are active - they make in-flight work visible and force explicit conflict resolution.

**Cleanup:** Remove worktrees after the subagent branch is merged or the task is explicitly closed. Do not leave stale worktrees. Between tasks there should be no active subagent worktrees.

**Commit each fix immediately during testing.** Never accumulate uncommitted changes during live testing sessions. After each validated fix: commit, PR, merge, pull - then start the next fix. Do not batch multiple unrelated fixes.

**Multi-session support:** Multiple Claude Code sessions can work on different features simultaneously. Each session operates on its own branch. No worktree coordination is needed between sessions at the conductor level.

## Context Economy

Agents must be mindful of context-window consumption. Large outputs increase latency, burn tokens, and can push the session toward truncation. Follow these rules:

- **Do not duplicate file contents in prose.** Reference files by path. The reader can use ReadFile if they need the full text.
- **Keep diffs minimal.** Use standard unified diff format with 3 lines of context per hunk. Do not paste entire files when only a few lines changed.
- **Do not paste tool output verbatim** unless specifically asked or unless the output is short (<20 lines). Summarize command results: "`pytest` passes (42 tests, 0 failures)" rather than dumping the full test log.
- **Structured blocks over prose.** Prefer the JSON structured block for machine-readable data (file lists, gate results) and keep prose for human-readable narrative only.

Multi-developer coordination guidance lives in `content/references/multi-developer-coordination.md`.

## External Comment Discipline

Agents author artifacts that humans read outside the session - PR titles and bodies, PR review comments, Linear comments, Jira comments, commit messages that summarise work, deploy and release notes. These surfaces have a different cost profile from in-session output: humans read them under time pressure, often on a phone, often days after the work landed. Verbosity is not free here - it is a tax on every future reader.

Apply these rules to every external-facing comment:

- **Lead with the result and the link.** The first line should answer "what changed and where do I look?" - not restate the ticket, not narrate the journey.
- **Bullets over prose.** Each bullet earns its place by adding something the diff, screenshot, or linked artifact does not already show. If a bullet just describes what the diff shows, delete it.
- **Cut what the reader can see for themselves.** Do not restate the ticket. Do not narrate the agent's own process ("I reviewed", "we investigated", "after analysis"). Do not summarise a diff that is one click away.
- **Evidence beats description.** A screenshot, a test URL, a log excerpt, or a link to the failing line is worth more than a paragraph of explanation. Link, do not transcribe.
- **No marketing voice, no emojis, no agent attribution footers.** The writing-style rules elsewhere in this methodology (plain verbs, no rule-of-three triads, no AI vocabulary, no em dashes) apply with extra force on external surfaces because humans read them quickly and judgmentally.
- **Length is not the metric; signal-per-line is.** A long comment is fine when every line is load-bearing. A three-line comment that restates the ticket is too long.
- **Skeptic findings posted as PR review comments** are one finding per comment in the form `[Severity] path:line - issue. Fix: <one-line action>.` No preamble, no sign-off banner, no "Active search" line on per-finding comments - that line belongs to the conductor-internal sign-off, not the PR surface.
- **Self-check before posting.** Re-read this section. For each sentence ask: is this load-bearing for a human deciding "do I need to act on this?" If not, delete it.

This rule layers conciseness expectations on top of the structural templates in `content/commands/implement-ticket.md` (PR body, tracker comment). The templates still apply; this rule governs the substance that fills them.
