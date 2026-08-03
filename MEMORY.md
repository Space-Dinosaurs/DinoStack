# Memory

## How this file is managed

This is the always-loaded tier (imported via `@MEMORY.md`) - keep it under ~120 lines / ~2,000 words. When an entry stops being load-bearing for day-to-day sessions, move it verbatim to `MEMORY-archive.md` rather than deleting it - never delete outright. Before archiving, check `MEMORY-archive.md` for an existing copy first: the archived version is usually longer and should win, so verify any "covered elsewhere" justification against that specific entry, not the batch.

## Project Conventions

- **2026-08-02: Verify a cross-repo handoff doc's premise against this repo before scoping a ticket from it.** DS-120 was written to defend a "check `docs/planning/` for an existing plan" rule that does not exist in DinoStack - it is authentic8-local. Handoffs arrive from sibling repos with their own conventions embedded, so scoping straight from the doc can file a phantom requirement.

- **2026-07-09:** DinoStack's `AGENTS.md` has no `## Tracker` section, so `/implement-ticket` falls through to `TRACKER=none` - infer Jira (solara6.atlassian.net, prefix DS) from `~/.claude/settings.local.json` `ATLASSIAN_*` creds each session. Can't fix via public AGENTS.md (universality); needs a local gitignored mechanism. (DS-74)

- **2026-07-26: DS Jira writebacks to `In Review`/`QA`/`Blocked` don't land because those statuses don't exist in the DS project (workflow is `To Do` / `In Progress` / `Done`) - the forward-only guard is no longer the reason.** Cached in `.agentic/tracker-states.json` (gitignored); cache is a snapshot (`fetched_at: 2026-07-09`), and Phase 2c logs `configured state '...' not found; available: [...]`. What the post-#481 guard does for an absent target is undetermined - no post-#481 DS writeback has been observed. Precondition: this repo resolves `TRACKER=none` (see the DS-74 entry above), so the Helper skips at step 1 unless a session infers Jira manually. Remediation: add the missing statuses to the DS workflow. (ticket: DS-74)

- **2026-08-02: The local gitignored tracker overlay now exists (`bin/agentic-tracker`, PR #537) but is NOT initialized here** - `grep "Tracker" AGENTS.md` is still empty and this repo still resolves `TRACKER=none`, so the manual `ATLASSIAN_*` inference above remains the live workaround until `agentic-tracker init` is run. The overlay is applied after the four-step `AGENTS.md` chain: when `AGENTS.md` declares no tracker (this repo's case) or a different one, the overlay is **sole source and fully replaces** the base (`_source: "overlay"`); field-by-field merge (`_source: "merged"`) happens only when both declare the same tracker.

- **2026-08-02: `bin/agentic-base-sync` is the only mechanism that moves a local branch ref outside an explicit checkout+pull** - `/ds-implement-ticket` Phase 12 calls it unconditionally after merge. It deliberately has no blanket dirty-guard; do not re-add one (`content/references/base-branch-sync.md`, `KNW-20260801-006`).

## Decisions

- **2026-07-25 (supersedes 2026-05-18): Adapter-drift CI gate (`check-adapter-sync`) is now a required status check on `main` and hard-blocks merge on drift.** Verified against the live branch-protection ruleset (15 required checks total, `check-adapter-sync` among them). No longer advisory-only.

- **2026-07-01: "Works for everyone" (universality) is a North Star pillar.** Shared DinoStack behavior must never bake in one operator's identity, workspace, tracker, or local setup - resolve per-operator context at runtime and degrade gracefully when unconfigured. Test: would this work for a teammate with different credentials/tracker/harness?

- **2026-07-29: `strict_required_status_checks_policy` is now `true` on the `main` ruleset (DS-115), so merges serialize.** A base move invalidates a PR's results and GitHub does not re-run workflows on base movement, so each PR needs an explicit rebase plus a full 15-check re-run near merge time. Chosen because `check-adapter-sync` already detects stale-base regeneration (PR checkout is the merge ref, `refs/pull/N/merge`) - only re-run freshness was missing, so no new CI gate was needed. Complements the 2026-07-25 required-checks entry.

## Methodology Enforcement

- **2026-07-01: The Elevated-signal table and the "when in doubt, classify Elevated" tie-break are duplicated across more files than a grep suggests** (`02-delegation.md`, `subagent-protocol.md`, `skeptic-protocol.md`, plus restatements in `orchestration-planner.md`/`agentic-status.md`). Match copies by semantics, not by grepping one phrase.

- **2026-07-25 (supersedes 2026-07-08): `check-vision-alignment` CI is now a required status check on `main`**, per explicit operator decision - no longer advisory-only (15 required checks total, verified against ruleset `14778332` on 2026-08-02; `strict_required_status_checks_policy: true`). Canonical trigger-path list is still owned by `content/agents/skeptic.md` step 3.6 (grep `keep.*sync` to find the two derived copies).

- **2026-08-01: A Skeptic convergence failure can relocate the same defect rather than repeat it verbatim - a re-review must diff the finding's shape, not its wording.** Two independent tickets (DS-118, DS-120) in one session each showed a "claimed fix" that removed the flagged line while an equivalent defect reappeared one step away (a write became a read of the same field at the same phase; a branch-name check moved into a reserved sub-pattern). See `.agentic/learnings.md` KNW-20260801-001 for both instances and the diagnostic pattern.

## Knowledge Capture

- **2026-06-19: Committed root `MEMORY.md` is public and teammate-facing - keep maintainer-internal content out of it.** Route eval/auto-harness internals and session TODOs to the private memory store instead. Session-scoped files (session-learnings, `decisions.md`, ad-hoc `context.md`) stay local, never opened as a PR except a deliberate curated `docs(memory)` PR when authorized.

## Worktree & Git Hygiene

- **2026-07-26: Never end a session holding uncommitted `MEMORY.md`/`AGENTS.md` edits - the working tree may be the content's only copy.** The conductor is the sanctioned writer of these files, but a worktree-isolated engineer branches from `origin/main` and cannot see them, so a delegated edit is computed against a stale file and can silently drop them. Commit in the session that wrote them; confirm sole-copy status with `git log --all -S "<phrase>"` plus `git stash list` - `--all` does not cover `refs/stash`.

- **2026-06-12: An `isolation:"worktree"` engineer spawn with a named branch can leak into the conductor's own checkout and switch its HEAD** - observed corrupting `main` once. After every worktree-isolated spawn, verify the checkout is still on its expected branch (`git branch --show-current` + `git status`) before committing.

- **2026-07-08: Isolation worktrees always branch from `main` HEAD, never a named feature branch.** A fix meant for an existing feature branch can't be briefed as "branch from `origin/<feature>`" - it silently starts from main. Cherry-pick or push the commit directly onto the branch's remote tip instead.

- **2026-07-02: Checking for duplicate in-flight work only at spawn time misses collisions that start or merge while a Worker runs.** Check open PRs and `git status` before spawning, and re-check for a superseding merge before opening a PR (dirty `mergeStateStatus` on a fresh PR is the symptom); stand down and cite it.

- **2026-07-31 (supersedes 2026-06-13): Four reusable git lessons, all of which have shipped bugs here.** (1) To flip a gitignored file to tracked, append a negation (`!.agentic/<file>`) rather than removing the ignore rule - additive negation is safe, removal leaks. (2) A negation cannot re-include a file whose parent **directory** is excluded: `.agentic/`, `/.agentic/`, and bare `.agentic` all defeat `!.agentic/qa.md`; only glob forms (`/.agentic/*`, `**/.agentic/**`) work. (3) Matching is **last-match-wins**, so a negation only overrides an umbrella placed **above** it - `bin/agentic-migrate` appended umbrellas at EOF and silently killed every carve-out (fixed #527). (4) **`git diff --quiet <ref> -- <path>` exits 0 for a path that has never been committed to `<ref>`** - "unchanged", not "new" - so an untracked file is invisible to any gate built on it; pair it with `git cat-file -e <ref>:<path>` (this defeated Part G for brand-new files, fixed pre-merge in #534). Green CI per-PR still doesn't guarantee `main`'s end state under concurrent sessions - assert directly with `git ls-files` / `git check-ignore`.

- **2026-07-25 (supersedes 2026-06-16): Merging to `main` needs exactly 1 code-owner approval, not 3** - verified against the live ruleset (`required_approving_review_count: 1`; CODEOWNERS designates `* @tysonhummel` as sole owner). `--admin` is still required for `gh pr merge` when: the PR is authored by @tysonhummel (GitHub disallows self-approval), or no `@tysonhummel` reviewer is present - the normal unattended-agent case. Confirmed merging #483-#486; an approval-required failure on `--admin` means the bypass actor was removed from the ruleset and needs re-adding in GitHub's UI.

## Adapters & Build

- **2026-08-02 (supersedes 2026-07-31/2026-07-09): `scripts/check-resident-budget.sh` and the `resident-budget` CI workflow exist on `main`, but do not trust a cited baseline/THRESHOLD pair - run the script for the live figure.** THRESHOLD ratchets downward over time and every baseline/THRESHOLD pair this entry has ever cited went stale within days, which is why no current pair is reproduced here - the script's own output is the only live source. (The byte figures below are a fixed historical anecdote, not a baseline.) Run `bash scripts/build-methodology.sh` first - the script measures the freshly rebuilt `METHODOLOGY.md`, not the file on disk. Lower THRESHOLD in the same PR as any deliberate compression of the resident set. **When a change busts the budget, the fix is progressive disclosure, not raising THRESHOLD** - #534 added ~3.4 KB of sweep procedure to `content/rules/conventions.md` (loaded in *every* session on *every* project, to describe a rarely-firing notice), measured 127,355 B, and landed at 124,440 B by moving the mechanics to `content/references/conventions-detail.md` behind a pointer. Never compress *unrelated* prose to make room: that hides the new cost inside someone else's savings, which is what the ratchet exists to prevent. (ticket: DS-74, DS-122)

- **2026-07-09: A compression/extraction change that moves inline prose into `content/references/*-detail.md` creates a staleness class that merges silently, no conflict marker** - later commits keep patching the original location while the extracted copy diverges unnoticed. Catching all instances required a file-by-file audit of every post-branch commit (PR #420, DS-68).

- **2026-08-02: The same relocation also carries stale claims across intact - the sibling of the entry above.** Where that one is about the original site drifting after extraction, this is about the extracted block arriving already wrong: a verbatim move preserves whatever the block asserted, and reviewers read the move as a no-op and never re-check its content. DS-68's relocated prose carried a byte figure that was stale before the move. When moving a block into `content/references/`, re-verify every count, path, and figure inside it against live state in the same PR - "verbatim" is a diff property, not a correctness property.

- **2026-06-21: Adapter/methodology build discipline.** `content/` is single-sourced into all adapter dirs; any change requires `bash scripts/build-all.sh` (11 dirs) then `git diff --exit-code -- <adapter dirs>`. `content/sections/**` changes also need `scripts/.methodology-baseline.sha256` regenerated. `check-adapter-sync` CI tests the merge result, not your branch - rebase onto current `origin/main` and rebuild before merging.

- **2026-07-24 (supersedes 2026-06-16): Repo checkout convention is `DinoStack`, but `agentic-engineering` stays the stable name for install-targets/identifiers.** Do not rename `~/.claude/skills/agentic-engineering/`, config files, the `opt-in`/`opt-out` marker, or the skill name. All methodology slash commands now use the `/ds-*` prefix (e.g. `/ds-implement-ticket`); `bin/agentic-*` CLI names and their no-slash usage text are unaffected by that rename (DS-26).

## Hooks & Subagent Mechanics

- **2026-08-02: Worktree isolation is enforced only on Bash git operations aimed at the shared checkout - not on reads.** A plain `Read` of an absolute path into the conductor's checkout succeeds from inside an isolation worktree, including for files absent from that worktree (`.agentic/`, `docs/planning/`, `evals/`). Verified empirically. Isolation constrains where an agent can write and run git, not what it can see - so "the worktree cannot see it" is false for `Read` and true for `git`.

- **2026-06-25: AE agents carry an explicit `model:` in frontmatter (opus for `skeptic`/`security-auditor`, sonnet for the rest).** Omit the spawn-call `model` param to accept the role default; pass it only to override a specific spawn. Passing it unconditionally on every spawn silently overrides Opus on review agents.

## Slides (Marp decks, docs/slides/)

- **2026-07-01:** Never include `"mode": "opt-in"` in doc/adapter example JSON unless demonstrating opt-in activation - it silently disables the entire methodology on repos without an `agentic-engineering: opt-in` marker; show only the field being demonstrated (e.g. `{ "profile": "relaxed" }`) or use `"mode": "opt-out"`.

## Bulk Operations & Adapter Sync

- **2026-07-24:** Adapter dirs contain hand-authored sources that `build.sh` does NOT regenerate (.codex/.copilot/.cursor/.gemini/.github hook files, .opencode/plugins/session-context.ts) - a "rebuild adapters, skip them" assumption misses these; check them manually after any adapter source edit or cross-adapter pattern change (ticket: DS-26).
