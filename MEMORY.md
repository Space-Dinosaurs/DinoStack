# Memory

## How this file is managed

This is the always-loaded tier (imported via `@MEMORY.md`) - keep it under ~120 lines / ~2,000 words. When an entry stops being load-bearing for day-to-day sessions, move it verbatim to `MEMORY-archive.md` rather than deleting it - never delete outright. Before archiving, check `MEMORY-archive.md` for an existing copy first: the archived version is usually longer and should win, so verify any "covered elsewhere" justification against that specific entry, not the batch.

## Project Conventions

- **2026-07-02: `bin/*` CLIs loading `_lib.py` break via their PATH symlink.** Use `Path(__file__).resolve().parent / "_lib.py"`, never `.parent` - the bare form resolves to a missing `~/.local/bin/_lib.py` and soft-fails silently. `bin/agentic-feedback` has the fix; other `_lib`-dependent bins still have the bug (DS-66, open).

- **2026-06-24: DinoStack does not commit its own `.agentic/` runtime files** (only `!/.agentic/team.yml` is tracked) - it's the methodology's source, not a consumer. For a per-project AE toggle, create a gitignored `.agentic/config.json`.

- **2026-06-21: An authenticated tracker CLI is not proof it points at this project's workspace.** Verify the workspace/org matches the repo's declared tracker before creating/updating tickets - stop and ask if identity can't be confirmed.

- **2026-07-09:** DinoStack's `AGENTS.md` has no `## Tracker` section, so `/implement-ticket` falls through to `TRACKER=none` - infer Jira (solara6.atlassian.net, prefix DS) from `~/.claude/settings.local.json` `ATLASSIAN_*` creds each session. Can't fix via public AGENTS.md (universality); needs a local gitignored mechanism. (DS-74)

- **2026-07-26: DS Jira writebacks to `In Review`/`QA`/`Blocked` don't land because those statuses don't exist in the DS project (workflow is `To Do` / `In Progress` / `Done`) - the forward-only guard is no longer the reason.** Cached in `.agentic/tracker-states.json` (gitignored); cache is a snapshot (`fetched_at: 2026-07-09`), and Phase 2c logs `configured state '...' not found; available: [...]`. What the post-#481 guard does for an absent target is undetermined - no post-#481 DS writeback has been observed. Precondition: this repo resolves `TRACKER=none` (see the DS-74 entry above), so the Helper skips at step 1 unless a session infers Jira manually. Remediation: add the missing statuses to the DS workflow. (ticket: DS-74)

- **2026-08-02: The local gitignored tracker overlay now exists (`bin/agentic-tracker`, PR #537) but is NOT initialized here** - `grep "Tracker" AGENTS.md` is still empty and this repo still resolves `TRACKER=none`, so the manual `ATLASSIAN_*` inference above remains the live workaround until `agentic-tracker init` is run. The overlay is applied after the four-step `AGENTS.md` chain: when `AGENTS.md` declares no tracker (this repo's case) or a different one, the overlay is **sole source and fully replaces** the base (`_source: "overlay"`); field-by-field merge (`_source: "merged"`) happens only when both declare the same tracker.

- **2026-08-02: `bin/agentic-base-sync` is the only mechanism that moves a local branch ref outside an explicit checkout+pull** - `/ds-implement-ticket` Phase 12 calls it unconditionally after merge. It deliberately has no blanket dirty-guard; do not re-add one (`content/references/base-branch-sync.md`, `KNW-20260801-006`).

## Decisions

- **2026-07-31: Knowledge-file committing moved from `/ds-implement-ticket` Phase 11c (deleted, #534) to `/ds-wrap` Part G.** Phase 11c had produced zero commits ever: it read only `wrap-ticket`'s return JSON so `learnings-agent` writes were invisible, it skipped when no PR existed, and a categorical `.agentic/*` floor refused `learnings.md` outright. Part G copies the three files **verbatim** onto a `chore/knowledge-*` branch and pushes - no merge algorithm, because the destination is a reviewed PR and a human reads the diff. An earlier design spent three review rounds building entry-hashing, section-anchoring, and a ledger before that was recognized. Review-rigor was promoted to Phase **11d**, deliberately not reusing `11c` (it fires on Trivial tickets, which would falsify `ticket-rework.md`'s "11c is skipped on Trivial").

- **2026-07-25 (supersedes 2026-05-18): Adapter-drift CI gate (`check-adapter-sync`) is now a required status check on `main` and hard-blocks merge on drift.** Verified against the live branch-protection ruleset (14 required checks total, `check-adapter-sync` among them). No longer advisory-only.

- **2026-07-01: "Works for everyone" (universality) is a North Star pillar.** Shared DinoStack behavior must never bake in one operator's identity, workspace, tracker, or local setup - resolve per-operator context at runtime and degrade gracefully when unconfigured. Test: would this work for a teammate with different credentials/tracker/harness?

- **2026-07-02: Model-capability gains move the risk-profile dial, never remove an enforcement floor.** Hooks (abdication guard, tier/singularity enforcement) are written for the weakest supported model and stay universal - only harness-driven (not model-driven) mechanisms are retirement candidates.

- **2026-06-24: Decided NOT to build a nested "unit-lead" sub-conductor tier** - the existing background-spawn + digest-return pattern already keeps conductor context clean; an Opus Skeptic withheld sign-off (2 Critical, 4 Major) on the full design. Do not re-propose unless context becomes a *measured* bottleneck. (Full rationale archived.)

- **2026-07-08: Live in-session HUD / real-time agent-dashboard UI belongs in Helios, not in agentic-engineering.** agentic-engineering produces structured telemetry (`.agentic/hud/*.json`); Helios (the sibling desktop product) is the intended home for rendering it. Static CLI rollups (`agentic-cost session/team/retro`) stay here.

- **2026-06-27: A deterministic hook cannot reliably detect an LLM-semantic event.** `events.jsonl` sat empty in ad-hoc sessions because signals like `conductor_direct`/`tool_failure_workaround` depended on the LLM self-reporting inline, which it reliably didn't. Fix pattern: derive that signal at a natural LLM-reflection point (e.g. `/wrap`'s own reflection), not hook instrumentation.

- **2026-07-27: The deferred G2 concurrent-wrap-queueing design's stated premise (`context.md` races) is stale post-#499** - `context.md` is now a lock-free derived rollup (session-keyed shards + compare-and-retry) with no remaining hazard. If G2 is resumed, re-scope it to the three files that actually still contend: `.agentic/_wrap.md`, root `MEMORY.md`, and `decisions.md`. See `.agentic/learnings.md` KNW-20260727-002 for full detail.

- **2026-07-29: `.agentic/tasks.jsonl` ownership and ordering are defined by the executable `bin/tests/fold_model.py` (DS-108, #521), not by prose.** An executable model was chosen because it is diffable, directly testable, and cannot drift from the gates that enforce it - the prose rules had already drifted, and five plan revisions passed before a non-prefix-monotonic ordering defect surfaced. Ordering is arrival order only; `updated_at` feeds staleness, never ordering. Gates: `bin/tests/test_fold_invariants.py`, `bin/tests/test_tasks_jsonl_fold.sh`.

- **2026-07-29: `strict_required_status_checks_policy` is now `true` on the `main` ruleset (DS-115), so merges serialize.** A base move invalidates a PR's results and GitHub does not re-run workflows on base movement, so each PR needs an explicit rebase plus a full 14-check re-run near merge time. Chosen because `check-adapter-sync` already detects stale-base regeneration (PR checkout is the merge ref, `refs/pull/N/merge`) - only re-run freshness was missing, so no new CI gate was needed. Complements the 2026-07-25 required-checks entry.

## Methodology Enforcement

- **2026-07-01: The Elevated-signal table and the "when in doubt, classify Elevated" tie-break are duplicated across more files than a grep suggests** (`02-delegation.md`, `subagent-protocol.md`, `skeptic-protocol.md`, plus restatements in `orchestration-planner.md`/`agentic-status.md`). Match copies by semantics, not by grepping one phrase.

- **2026-07-07: A PreToolUse hook can't see the conductor's own structural decisions (only `tool_input`).** Tier-3 escalation for authoring roles (architect/adr-generator/product-discovery) on Plan+ADR units must be conductor-declared (explicit `model: opus`) - the hook can only backstop a sub-Opus downgrade, never detect the trigger itself.

- **2026-07-25 (supersedes 2026-07-08): `check-vision-alignment` CI is now a required status check on `main`**, per explicit operator decision - no longer advisory-only (14 required checks total). Canonical trigger-path list is still owned by `content/agents/skeptic.md` step 3.6 (grep `keep.*sync` to find the two derived copies).

- **2026-08-01: A Skeptic convergence failure can relocate the same defect rather than repeat it verbatim - a re-review must diff the finding's shape, not its wording.** Two independent tickets (DS-118, DS-120) in one session each showed a "claimed fix" that removed the flagged line while an equivalent defect reappeared one step away (a write became a read of the same field at the same phase; a branch-name check moved into a reserved sub-pattern). See `.agentic/learnings.md` KNW-20260801-001 for both instances and the diagnostic pattern.

## Knowledge Capture

- **2026-06-19: Committed root `MEMORY.md` is public and teammate-facing - keep maintainer-internal content out of it.** Route eval/auto-harness internals and session TODOs to the private memory store instead. Session-scoped files (session-learnings, `decisions.md`, ad-hoc `context.md`) stay local, never opened as a PR except a deliberate curated `docs(memory)` PR when authorized.

## Worktree & Git Hygiene

- **2026-07-26: Never end a session holding uncommitted `MEMORY.md`/`AGENTS.md` edits - the working tree may be the content's only copy.** The conductor is the sanctioned writer of these files, but a worktree-isolated engineer branches from `origin/main` and cannot see them, so a delegated edit is computed against a stale file and can silently drop them. Commit in the session that wrote them; confirm sole-copy status with `git log --all -S "<phrase>"` plus `git stash list` - `--all` does not cover `refs/stash`.

- **2026-06-12: An `isolation:"worktree"` engineer spawn with a named branch can leak into the conductor's own checkout and switch its HEAD** - observed corrupting `main` once. After every worktree-isolated spawn, verify the checkout is still on its expected branch (`git branch --show-current` + `git status`) before committing.

- **2026-07-08: Isolation worktrees always branch from `main` HEAD, never a named feature branch.** A fix meant for an existing feature branch can't be briefed as "branch from `origin/<feature>`" - it silently starts from main. Cherry-pick or push the commit directly onto the branch's remote tip instead.

- **2026-06-29: After an isolation-worktree engineer commits, the main checkout's view of that branch ref can lag behind the worktree's HEAD.** Pushing by branch name can ship the stale commit and `gh pr create` will reject it. Push the explicit commit SHA instead (`git push origin <sha>:refs/heads/<branch>`).

- **2026-07-26:** Isolation worktrees are now cleaned up inline after the branch is pushed to origin, not after PR open or session-start prune. This fixes the branch-rename mapping problem that caused stale worktrees to accumulate, implemented via `scripts/lib/worktree.sh` (`resolve_branch_worktree`) and `bin/agentic-resolve-worktree`.

- **2026-07-26:** `.claude/install.sh` has a zsh variable conflict: a local variable named `status` is read-only in zsh. Avoid `status` as a variable name in zsh-specific code, and run affected blocks in a bash subshell for mixed-shell compatibility.

- **2026-07-09: The same "silent revert" failure mode also occurs from a hand-authored feature commit, not just a regen commit** - a stale local snapshot silently reverted unrelated content in files it legitimately touched and green CI missed it. Diff the PR's base..tip for unrelated hunks before merging or rebasing (PR #390/#432, DS-47).

- **2026-07-08: When `origin/main` advances mid-session, a diff against it can make an unrelated, already-merged PR's files look reverted** - a diff-base artifact, not a real revert; your branch predates the merge. Diagnose against your commit's parent; rebase and re-run any generator the merge may have changed.

- **2026-07-02: Checking for duplicate in-flight work only at spawn time misses collisions that start or merge while a Worker runs.** Check open PRs and `git status` before spawning, and re-check for a superseding merge before opening a PR (dirty `mergeStateStatus` on a fresh PR is the symptom); stand down and cite it.

- **2026-07-31 (supersedes 2026-06-13): Four reusable git lessons, all of which have shipped bugs here.** (1) To flip a gitignored file to tracked, append a negation (`!.agentic/<file>`) rather than removing the ignore rule - additive negation is safe, removal leaks. (2) A negation cannot re-include a file whose parent **directory** is excluded: `.agentic/`, `/.agentic/`, and bare `.agentic` all defeat `!.agentic/qa.md`; only glob forms (`/.agentic/*`, `**/.agentic/**`) work. (3) Matching is **last-match-wins**, so a negation only overrides an umbrella placed **above** it - `bin/agentic-migrate` appended umbrellas at EOF and silently killed every carve-out (fixed #527). (4) **`git diff --quiet <ref> -- <path>` exits 0 for a path that has never been committed to `<ref>`** - "unchanged", not "new" - so an untracked file is invisible to any gate built on it; pair it with `git cat-file -e <ref>:<path>` (this defeated Part G for brand-new files, fixed pre-merge in #534). Green CI per-PR still doesn't guarantee `main`'s end state under concurrent sessions - assert directly with `git ls-files` / `git check-ignore`.

- **2026-07-25 (supersedes 2026-06-16): Merging to `main` needs exactly 1 code-owner approval, not 3** - verified against the live ruleset (`required_approving_review_count: 1`; CODEOWNERS designates `* @tysonhummel` as sole owner). `--admin` is still required for `gh pr merge` when: the PR is authored by @tysonhummel (GitHub disallows self-approval), or no `@tysonhummel` reviewer is present - the normal unattended-agent case. Confirmed merging #483-#486; an approval-required failure on `--admin` means the bypass actor was removed from the ruleset and needs re-adding in GitHub's UI.

- **2026-07-14: The live Claude Code harness auto-locks every `isolation:"worktree"` worktree at creation.** Directory is `.claude/worktrees/agent-<agentId>` (not `worktree-agent-<id>` - that's the branch name); non-force `git worktree remove` refuses it (`remove -f -f` needed). Cleanup detection must match the branch-name pattern, not the dir path.

- **2026-07-26: Work in an isolation worktree can silently absolutize the `.claude/skills/agentic-engineering/{agents,commands,references,rules}` symlinks to that worktree's own path** - `check-adapter-sync` compares regenerated content, and the symlink still resolves fine on the machine that broke it, so an absolutized symlink merged to `main` silently breaks the skill for every other clone. `scripts/check-symlinks-relative.sh` (wired in `adapter-sync.yml` since PR #500) now gates this in CI; before staging, check `git status --short` for those four paths and restore with `git restore --staged --worktree`; audit a landed commit with `git ls-tree -r <sha> .claude/skills/agentic-engineering | awk '$1=="120000"{print $4}'` then `git cat-file -p <sha>:<path>` - a leading `/` means broken. (DS-96, DS-104)

## Adapters & Build

- **2026-07-31 (supersedes 2026-07-09): `scripts/check-resident-budget.sh` and the `resident-budget` CI workflow now exist on `main`.** Baseline is 123,938 B against `THRESHOLD=124938`; lower THRESHOLD in the same PR as any deliberate compression of the resident set. **When a change busts the budget, the fix is progressive disclosure, not raising THRESHOLD** - #534 added ~3.4 KB of sweep procedure to `content/rules/conventions.md` (loaded in *every* session on *every* project, to describe a rarely-firing notice), measured 127,355 B, and landed at 124,440 B by moving the mechanics to `content/references/conventions-detail.md` behind a pointer. Never compress *unrelated* prose to make room: that hides the new cost inside someone else's savings, which is what the ratchet exists to prevent. (ticket: DS-74)

- **2026-07-09: A compression/extraction change that moves inline prose into `content/references/*-detail.md` creates a staleness class that merges silently, no conflict marker** - later commits keep patching the original location while the extracted copy diverges unnoticed. Catching all instances required a file-by-file audit of every post-branch commit (PR #420, DS-68).

- **2026-06-21: Adapter/methodology build discipline.** `content/` is single-sourced into all adapter dirs; any change requires `bash scripts/build-all.sh` (11 dirs) then `git diff --exit-code -- <adapter dirs>`. `content/sections/**` changes also need `scripts/.methodology-baseline.sha256` regenerated. `check-adapter-sync` CI tests the merge result, not your branch - rebase onto current `origin/main` and rebuild before merging.

- **2026-07-24 (supersedes 2026-06-16): Repo checkout convention is `DinoStack`, but `agentic-engineering` stays the stable name for install-targets/identifiers.** Do not rename `~/.claude/skills/agentic-engineering/`, config files, the `opt-in`/`opt-out` marker, or the skill name. All methodology slash commands now use the `/ds-*` prefix (e.g. `/ds-implement-ticket`); `bin/agentic-*` CLI names and their no-slash usage text are unaffected by that rename (DS-26).

- **2026-07-09: Some `content/` source files are hardlinked (not copied) into adapter destinations, inconsistently - don't assume a build script alone keeps things in sync.** E.g. `content/agents/skeptic.md`/`.claude/agents/skeptic.md` share an inode; `.hermes/SKILL.md` is a verbatim embed, not a hardlink. `bash scripts/build-all.sh` is still required regardless. (DS-78)

- **2026-07-15: `.github/workflows/adapter-sync.yml` is the source of truth for the 11-script adapter build set (including `.copilot/build.sh`).** At least two other enumerations had drifted to 10 scripts (missing `.copilot`): `/update-agentic-engineering` Step 3 (fixed) and the installed `.git/hooks/pre-commit` hook (fix in progress). Cross-check future changes against the CI workflow, not against a duplicated list.

- **2026-07-27 (FIXED in #506, `416aa7ad`): `test_hooks_snapshot.sh`'s idempotency assertion had two defects at once - a 12% CI flake AND a 100% vacuous pass on macOS.** It byte-compared every file under the snapshot root including `.snapshot-meta.json`, whose `snapshotted_at` is second-resolution and re-stamped every sync, so a sync pair straddling a second boundary failed legitimately. Separately, its `xargs -I{} sh -c 'echo {}; cat {}' 2>/dev/null` comparator blew BSD's ~255-byte `-I` budget on real paths, returned rc=1, emitted nothing, and compared empty-to-empty - so locally on macOS it asserted **nothing** while CI exercised the real comparison. The durable lesson outlives the fix: a green local loop proves nothing when the comparator may be silently empty, and `2>/dev/null` on a comparison step converts a tooling failure into a false pass. See `.agentic/learnings.md` KNW-20260727-004/006.

## Hooks & Subagent Mechanics

- **2026-07-08: PreToolUse hook mechanics for Agent/Task spawns.** `tool_input` exposes `subagent_type`, `prompt`, `description`, `model` (absent when omitted); precedence is env var > spawn-call `model` > frontmatter `model:` > session default. Deny: print `permissionDecision:"deny"` JSON, exit 0. Warn without blocking: `"allow"` + a `permissionDecisionReason`.

- **2026-06-30: An LLM cannot reliably run a long foreground poll loop (foreground `sleep` is blocked).** Fix: move the poll loop into a small binary invoked as a **background** spawn (`run_in_background: true`) - the conductor stays available and gets a synchronous exit code.

- **2026-06-22: The Graphify PyPI package is genuinely named `graphifyy` (double-y)** - the CLI/skill command stays `graphify`. This looks like a typo and has been "corrected" incorrectly before; it isn't - verified against the upstream README.

- **2026-06-25: AE agents carry an explicit `model:` in frontmatter (opus for `skeptic`/`security-auditor`, sonnet for the rest).** Omit the spawn-call `model` param to accept the role default; pass it only to override a specific spawn. Passing it unconditionally on every spawn silently overrides Opus on review agents.

## Slides (Marp decks, docs/slides/)

- **2026-07-01:** Never include `"mode": "opt-in"` in doc/adapter example JSON unless demonstrating opt-in activation - it silently disables the entire methodology on repos without an `agentic-engineering: opt-in` marker; show only the field being demonstrated (e.g. `{ "profile": "relaxed" }`) or use `"mode": "opt-out"`.

## Bulk Operations & Adapter Sync

- **2026-07-24:** Adapter dirs contain hand-authored sources that `build.sh` does NOT regenerate (.codex/.copilot/.cursor/.gemini/.github hook files, .opencode/plugins/session-context.ts) - a "rebuild adapters, skip them" assumption misses these; check them manually after any adapter source edit or cross-adapter pattern change (ticket: DS-26).

- **2026-07-24:** Bulk file sweeps over evals/ must exclude git worktrees (evals/.worktrees/wt-* are pinned at historical commits) to avoid dirtying checkouts; discovered when a sed sweep modified a pinned worktree's tracked files (ticket: DS-26).
