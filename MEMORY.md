# Memory

## How this file is managed

This is the always-loaded tier (imported via `@MEMORY.md`) - keep it under ~120 lines / ~2,000 words. When an entry stops being load-bearing for day-to-day sessions, move it verbatim to `MEMORY-archive.md` rather than deleting it. Never delete outright.

## Project Conventions

- **2026-04-28:** This project uses `main` as the sole integration branch. Do not use `develop`/`development` branching model for this repository - all feature/fix/chore work branches from `main` and merges back to `main`.

- **2026-07-02: `bin/*` CLIs loading `_lib.py` break via their PATH symlink.** Use `Path(__file__).resolve().parent / "_lib.py"`, never `.parent` - the bare form resolves to a missing `~/.local/bin/_lib.py` and soft-fails silently. `bin/agentic-feedback` has the fix; other `_lib`-dependent bins still have the bug (DS-66, open).

- **2026-06-24: DinoStack does not commit its own `.agentic/` runtime files** (only `!/.agentic/team.yml` is tracked) - it's the methodology's source, not a consumer. For a local per-project AE toggle, create a gitignored `.agentic/config.json`.

- **2026-06-21: An authenticated tracker CLI is not proof it points at this project's workspace.** Verify the CLI's workspace/org matches this repo's declared tracker before creating/updating tickets - stop and ask if identity can't be confirmed.

- **2026-07-09:** DinoStack's `AGENTS.md` has no `## Tracker` section, so `/implement-ticket` falls through to `TRACKER=none` - infer Jira (solara6.atlassian.net, prefix DS) from `~/.claude/settings.local.json` `ATLASSIAN_*` creds each session. Can't fix via public AGENTS.md (universality); needs a local gitignored mechanism, not yet built. (DS-74)

- **2026-07-09:** The DS Jira project's workflow is 3-state only (To Do / In Progress / Done) - status writebacks to `In Review`/`QA`/`Blocked` silently no-op via the tracker's forward-only guard. Cached in `.agentic/tracker-states.json` (gitignored, machine-local). (ticket: DS-74)

## Decisions

- **2026-05-18: Adapter-drift CI gate (`adapter-sync.yml`) is advisory-only** - drift is CI-visible (red X) on every PR but not a required status check, not hard-blocked at merge. Upgrade path: add `check-adapter-sync` as a required status check on `main`.

- **2026-07-01: "Works for everyone" (universality) is a North Star pillar.** Shared DinoStack behavior must never bake in one operator's identity, workspace, tracker, or local setup - resolve per-operator context at runtime and degrade gracefully when a capability isn't configured. Test: would this behave correctly for a teammate with different credentials/tracker/harness?

- **2026-07-02: Model-capability gains move the risk-profile dial, never remove an enforcement floor.** Hooks (abdication guard, tier/singularity enforcement) are written for the weakest supported model and stay universal - only harness-driven (not model-driven) mechanisms are retirement candidates.

- **2026-06-24: Decided NOT to build a nested "unit-lead" sub-conductor tier** - the existing background-spawn + digest-return pattern already keeps conductor context clean; an Opus Skeptic withheld sign-off (2 Critical, 4 Major) on the full design. Do not re-propose unless conductor context becomes a *measured* bottleneck. (Full rationale archived.)

- **2026-07-08: Live in-session HUD / real-time agent-dashboard UI belongs in Helios, not in agentic-engineering.** agentic-engineering's job is to produce structured telemetry (`.agentic/hud/*.json`); Helios (the sibling desktop product) is the intended home for rendering it. Static CLI rollups (`agentic-cost session/team/retro`) stay here.

- **2026-06-25: The public installer (`curl | bash`) pulls unpinned `main` HEAD - no checksum, signature, or release tag.** Live hardening gap now that the repo is public (deferred while private). Options: pin install to a release tag with version-bump, and/or publish a checksum/SRI.

- **2026-06-27: A deterministic hook cannot reliably detect an LLM-semantic event.** `events.jsonl` sat empty in ad-hoc sessions because signals like `conductor_direct`/`tool_failure_workaround` depended on the LLM choosing to self-report inline, which it reliably didn't. Fix pattern: derive that signal class at a natural LLM-reflection point (e.g. `/wrap`'s own reflection), not hook instrumentation.

## Methodology Enforcement

- **2026-07-01: The Elevated-signal table and the "when in doubt, classify Elevated" tie-break are duplicated across more files than a grep suggests** (`02-delegation.md`, `subagent-protocol.md`, `skeptic-protocol.md`, plus restatements in `orchestration-planner.md`/`agentic-status.md`). Match copies by semantics, not by grepping one phrase.

- **2026-07-07: A PreToolUse hook can't see the conductor's own structural decisions (only `tool_input`).** Tier-3 escalation for authoring roles (architect/adr-generator/product-discovery) on Plan+ADR units must be conductor-declared (explicit `model: opus`) - the hook can only backstop a sub-Opus downgrade, never detect the trigger itself.

- **2026-07-01: A bare `git pull` here can silently rewire hooks in every other open session** - hooks wire into `~/.claude/settings.json` by absolute path and reload on every tool call, no restart needed. Fix: a session-stable per-checkout hook snapshot dir that a bare pull doesn't mutate; restart other open sessions after any `hooks/` change lands.

- **2026-07-08: Vision-alignment enforcement shipped; `vision-alignment-check` CI is advisory-only by design** (mirrors adapter-drift). Canonical trigger-path list is owned by `content/agents/skeptic.md` step 3.6 (grep `keep.*sync` to find the two derived copies). Do NOT add to required branch-protection checks without an explicit operator decision.

- **2026-07-09: When drafting an "execution required" obligation clause, avoid phrasing a reviewer could read as permitting the check without re-executing.** DS-78's first draft of `qa-regression-obligation.md` had exactly this wording and was flagged Major by the plan Skeptic. Precise, unambiguous execution-obligation language is worth a second read before spawning the Worker.

- **2026-07-14: A handoff/plan authored in a different repo or session can encode environment assumptions that don't hold locally.** A cross-repo handoff asserted `/cleanup-worktrees` was deleting live worktrees; the live harness actually auto-locks isolation worktrees, contradicting the stated root cause. Verify a handoff's environmental premises against the live repo state before implementing its fix.

## Knowledge Capture

- **2026-07-07: Claude Code does NOT auto-inject the committed repo-root `MEMORY.md`** - it only injects whatever `CLAUDE.md` `@`-imports, plus the separate per-machine private memory store. `CLAUDE.md` must be `@AGENTS.md` + `@MEMORY.md` import lines - a bare `@AGENTS.md`-only file will NOT surface a committed `MEMORY.md`.

- **2026-06-19: Committed root `MEMORY.md` is public and teammate-facing - keep maintainer-internal content out of it.** Route eval/auto-harness internals and one-off session TODOs to the private memory store instead. Session-scoped knowledge files (session-learnings, `decisions.md`, ad-hoc `context.md`) stay local and are never opened as a PR, except a deliberate curated `docs(memory)` PR when explicitly authorized.

## Worktree & Git Hygiene

- **2026-06-12: An `isolation:"worktree"` engineer spawn with a named branch can leak into the conductor's own checkout and switch its HEAD** - observed corrupting `main` once. After every worktree-isolated spawn, verify the conductor's checkout is still on its expected branch (`git branch --show-current` + `git status` + `git diff --stat`) before committing.

- **2026-07-08: Isolation worktrees always branch from `main` HEAD, never from a named feature branch.** A continuation fix meant to land on an existing feature branch can't be briefed as "branch from `origin/<feature>`" - it silently starts from main. Cherry-pick or push the commit directly onto the existing branch's remote tip instead.

- **2026-06-12: `git checkout <sha> -- <path>` inside a worktree resurrects files a later commit deleted** - it doesn't replay deletions. When basing a step on a non-`main` commit this way, explicitly `git rm` anything that commit deleted, and gate on an exact `git ls-files` set.

- **2026-06-29: After an isolation-worktree engineer commits, the main checkout's view of that branch ref can lag behind the worktree's own HEAD.** Pushing by branch name can ship the stale base commit and `gh pr create` will reject it. Push the explicit commit SHA (`git push origin <sha>:refs/heads/<branch>`), not the branch name.

- **2026-06-04: An adapter-rebuild/baseline-regen engineer commit can silently revert unrelated source files, and green CI will not catch it.** A stale isolation worktree once reverted 51 files from three already-merged PRs while sync gates all passed. Verify any "regenerate generated artifacts" commit's diff touches *only* the intended generated paths before merging.

- **2026-07-09: The same "silent revert" failure mode also occurs from a hand-authored feature commit, not just a regen commit** - authored from a stale local snapshot, it silently reverted unrelated content in files it legitimately touched and green CI missed it. Diff the PR's base..tip for hunks unrelated to its stated intent before merging or rebasing (PR #390/#432, DS-47).

- **2026-07-08: When `origin/main` advances mid-session, a diff against it can make an unrelated, already-merged PR's files look reverted** - a diff-base artifact, not a real revert; your branch predates the merge. Diagnose against your commit's parent; rebase and re-run any generator the newly-merged commits may have changed.

- **2026-07-02: Checking for duplicate in-flight work only at spawn time misses collisions that start (or merge) while a Worker is running.** Check open PRs and `git status` before spawning, and re-check for a superseding merge right before opening a PR (a dirty `mergeStateStatus` on a fresh PR is the after-the-fact symptom); stand down and cite the superseding PR when superseded.

- **2026-06-13: Two reusable git lessons.** (1) To flip a gitignored file to tracked, append a negation line (`!.agentic/<file>`) rather than removing the ignore rule - additive negation is monotonic/safe, removal is the leak direction. (2) A per-PR green CI does not guarantee `main`'s end state is correct when multiple sessions touch it concurrently - assert the end state directly (`git ls-files`, `git check-ignore`).

- **2026-06-16: Merging to `main` requires `gh pr merge --squash --delete-branch --admin`.** Branch-protection requires 3 approving reviews plus last-push-approval, which a solo pusher can't satisfy; Repository Admin is the bypass actor. If `--admin` fails with an approval-required error, the bypass actor was removed from the ruleset and needs re-adding in GitHub's UI.

- **2026-07-14: The live Claude Code harness auto-locks every `isolation:"worktree"` worktree at creation.** Directory is `.claude/worktrees/agent-<agentId>` (NOT `worktree-agent-<id>` - that's the branch name); a non-force `git worktree remove` already refuses it (`remove -f -f` needed). Worktree-cleanup detection must match the branch-name pattern, not assume the dir path contains the same substring.

## Adapters & Build

- **2026-07-09:** The 88,323 B resident-budget ratchet and `scripts/check-resident-budget.sh` referenced in `RUNBOOK-extraction-audit.md` do not exist on `main` - they assume unmerged PR #420 (DS-68). Until #420 lands, resident-set tickets have to report a re-derivable delta by hand instead of running the missing check. (ticket: DS-74)

- **2026-07-09: A compression/extraction change that moves inline prose into `content/references/*-detail.md` creates a staleness class that merges silently, with no conflict marker** - later commits keep patching the original inline location while the extracted copy diverges unnoticed. Catching all instances required a file-by-file audit of every post-branch-point commit (PR #420, DS-68).

- **2026-06-21: Adapter/methodology build discipline.** `content/` is single-sourced into all adapter dirs; any `content/` change requires `bash scripts/build-all.sh` (all 11 dirs) then `git diff --exit-code -- <adapter dirs>`. `content/sections/**` changes also need `scripts/.methodology-baseline.sha256` regenerated. `check-adapter-sync` CI tests the PR **merge result**, not your branch alone - rebase onto current `origin/main` and rebuild before merging.

- **2026-06-24: `gemini-cli` 0.47 tightened agent-schema validation** - `tools:` must be a YAML array, `disallowedTools:` no longer accepted, `description:` must be quoted, and gemini validates each tool name against its own registry (`Read->read_file`, `Bash->run_shell_command`, etc). Mapping lives only in `.gemini/build.sh`.

- **2026-06-26: A harness without isolated-subagent context windows (or with always-injected rules) will reproduce the "Cursor cost ~30x Claude Code" problem** - content flagged `alwaysApply: true` re-injects every tool call, and with no real Agent/Task tool the conductor->Worker->Skeptic loop simulates inline in one ever-growing window. Fix: on-demand loading + an override preamble telling the model to act as conductor-and-implementer.

- **2026-06-16: Repo checkout convention is `DinoStack`, but `agentic-engineering` stays the stable name for install-targets/identifiers.** Do not rename `~/.claude/skills/agentic-engineering/`, config files, `/agentic-*` commands, the `opt-in`/`opt-out` marker, or the skill name. Checkout dir name is DinoStack; `agentic-engineering` as a tool identifier/config filename/command prefix stays as-is.

- **2026-06-17: The `dinostack-docs` Vercel project has its Root Directory set to `docs/`, so Vercel reads `docs/vercel.json` - the repo-root `vercel.json` is ignored for redirects/rewrites/headers.** This caused a live install-URL redirect to 404 silently. Put any Vercel redirect/rewrite/header change in `docs/vercel.json`, not the repo-root file.

- **2026-07-09: Some `content/` source files are hardlinked (not copied) into their adapter destinations, inconsistently - check before assuming a build script alone keeps things in sync.** E.g. `content/agents/skeptic.md`/`.claude/agents/skeptic.md` share an inode; `.hermes/SKILL.md` is a verbatim embed, not a hardlink. `bash scripts/build-all.sh` is still required regardless. (DS-78)

- **2026-07-15: `.github/workflows/adapter-sync.yml` is the source of truth for the 11-script adapter build set (including `.copilot/build.sh`).** At least two other enumerations had drifted to only 10 scripts (missing `.copilot`): the `/update-agentic-engineering` Step 3 build block (fixed) and the installed `.git/hooks/pre-commit` hook (fix in progress). Cross-check any future change to the adapter build set against the CI workflow, not against a duplicated list.

## Hooks & Subagent Mechanics

- **2026-07-08: PreToolUse hook mechanics for Agent/Task spawns.** `tool_input` exposes `subagent_type`, `prompt`, `description`, `model` (absent when omitted); model precedence is env var > spawn-call `model` > frontmatter `model:` > session default. Deny: print `permissionDecision:"deny"` JSON, exit 0. Warn without blocking: `"allow"` + a `permissionDecisionReason`.

- **2026-06-30: An LLM cannot reliably run a long foreground poll loop (foreground `sleep` is blocked).** Fix: move the poll loop into a small binary invoked as a **background** spawn (`run_in_background: true`) - the conductor stays available and gets a synchronous exit code on completion.

- **On a GLM session (or any non-Claude model backing the session), spawning a methodology subagent fails immediately.** Agent frontmatter `model:` is a Claude alias the non-Claude key doesn't carry, and the Agent tool's `model` param enum is Claude-only. Go conductor-direct with mechanical verification, or switch the session to a Claude model first.

- **2026-06-22: The Graphify PyPI package is genuinely named `graphifyy` (double-y)** - the CLI/skill command stays `graphify`. This looks like a typo and has been "corrected" incorrectly before; it isn't one - verified against the upstream README/landing page.

- **2026-06-25: AE agents carry an explicit `model:` in frontmatter (opus for `skeptic`/`security-auditor`, sonnet for the rest).** Omit the spawn-call `model` param to accept the role default; pass it explicitly only to override a specific spawn. Passing it unconditionally on every spawn silently overrides Opus on review agents.

## Slides (Marp decks, docs/slides/)

- **2026-07-01:** Never include `"mode": "opt-in"` in doc/adapter example JSON unless demonstrating opt-in activation - it silently disables the entire methodology on repos without an `agentic-engineering: opt-in` marker; show only the field being demonstrated (e.g. `{ "profile": "relaxed" }`) or use `"mode": "opt-out"`. (session)

- **2026-06-11: Dark-theme reskin gotcha - Marp `theme: default` leaks high-specificity light styles.** (1) Table rows render white (`section table tr` out-specifies bare `tr`) - fix: `table tr { background: transparent }` + `:nth-child(2n)` zebra. (2) Syntax-highlighted code is dark-on-dark (`section` keeps `color-scheme: light`) - fix: add `color-scheme: dark` to `section`; QA a highlighted slide, not a plain fence. Edit `.md`, regenerate via `bash scripts/build-slides.sh`.
