# Brief: Commit per-developer telemetry on PR create/update (DS-15)

Status: approved-design, implementation in progress
Promotion tier: Brief (2 Elevated units)
Source artifacts: design `docs/planning/pr-telemetry-commit.md` (2 Skeptic rounds, 1 Major + 2 Minors resolved); orchestration-planner unit block (below).

## Problem

Per-developer telemetry (`.agentic/session-log/<dev>.jsonl`) is local-only and gitignored, so `agentic-cost team` only ever sees the current machine's sessions. Bake into the methodology: when a confirmed identity exists and telemetry is captured, commit the session-log as a separate commit at `/implement-ticket` Phase 8 (PR create/update), so the data travels with the repo and becomes team-usable.

## Success criteria

1. `.agentic/session-log/<dev>.jsonl` is git-trackable via a single `!.agentic/session-log/` carve-out under the `.agentic/*` umbrella; no other `.agentic/` runtime file is un-ignored.
2. `.agentic/config.json` gains `"commit_telemetry": true`; the toggle is documented in `content/rules/conventions.md` §Project Config, in `content/commands/init-project.md` Step 6f (seed block + toggle docs + `/agentic-status` print).
3. `/implement-ticket` Phase 8 commits `.agentic/session-log/<dev>.jsonl` as a SEPARATE commit on the PR branch, gated on confirmed identity AND `commit_telemetry != false`, using the design's path-aware `$PR_CHECKOUT` resolution + `rev-parse --abbrev-ref HEAD == $BRANCH_NAME` guard. The block is soft-fail throughout and NEVER commits to a branch other than the PR branch.
4. All "NOT committed to git" / "local-only" session-log framing in methodology prose is updated to the committed-via-carve-out reality: `content/rules/conventions.md` §Session Context, `content/references/events-log.md` (incl. the TEAM-dimension note), `content/sections/09-events-log.md` (the METHODOLOGY source line).
5. All 8 adapters rebuilt + `scripts/.methodology-baseline.sha256` regenerated (content/sections touched); `check-adapter-sync` and `check-drift` pass.
6. Telemetry commit is skipped (soft-fail, one-line warning, feature commit unaffected) when identity is absent or provisional, or `commit_telemetry: false`.

## Non-goals

- **Global / individual kill-switch** (`~/.agentic/` opt-out) - DESCOPED for MVP; per-project `.agentic/config.json` toggle only. Possible follow-up.
- **Per-PR rollup record** - commit the existing per-developer session-log JSONL as-is (append-only, conflict-free); no new schema or aggregation artifact.
- **PRs not created via `/implement-ticket`** - not covered (documented limitation).
- **No Stop-hook / session-log schema change**, no new code, no new dependency. The committed artifact is exactly what `hooks/stop-context.js` writeSessionLog (lines 430-446) already produces.
- **Eventual consistency is accepted:** the Phase 8 commit carries prior sessions only; the current session's line lands in the next ticket's Phase 8 commit. Known property, not a bug.

## Constraints

- The gitignore carve-out (Unit 1) must be on `main` before the Phase 8 block (Unit 2) is exercised - enforced by merge order (Unit 1 first). The two are disjoint files and built in parallel.
- All `content/**` edits land WITH the adapter rebuild + baseline in one PR (adapter-sync + drift gates). The rebuild commit must touch ONLY generated paths (adapter-rebuild revert hazard - verify `git status`).
- Default `commit_telemetry: true` is the operator's explicit directive ("bake it in"); the confirmed-identity gate is the safety against accidental commits; the toggle is the opt-out.
- Soft-fail discipline: a telemetry-commit failure or branch mismatch never blocks the feature commit, the push, or PR open.

## Verification

- No automated test surface exists (the change is shell embedded in a markdown command spec + config + prose). The gate is: (a) per-unit Skeptic review - Unit 2's Skeptic checks the Phase 8 block matches the design spec verbatim and no "NOT committed" language survives; (b) the design's manual smoke tests (run `/implement-ticket` after merge: confirm a separate `chore(telemetry):` commit appears on the PR branch under a confirmed identity, is absent under provisional/no-identity, and is absent with `commit_telemetry: false`; confirm `.gitignore` un-ignores `session-log/` but still ignores `events.jsonl`).

## QA criteria

```yaml
qa_skip: pure-backend-library
qa_skip_rationale: Shell command-spec embedded in markdown + config JSON + methodology prose + generated adapters. No browser-visible UI; no runtime code path testable in this repo. Verified via Skeptic review + the design's manual smoke tests run against /implement-ticket.
scenarios: []
```

## Cross-artifact alignment

SC1, SC2(config key) -> `gitignore-config` unit. SC2(docs), SC3, SC4, SC5 -> `content-rebuild` unit. SC6 is delivered by the Phase 8 block (SC3) and the gate logic. No uncovered success criterion.

## Units (orchestration-planner output)

- `gitignore-config` (Elevated, merge_order 1, per-unit skeptic, depends_on none): `.gitignore` carve-out + `.agentic/config.json` toggle. Non-content, no adapter rebuild.
- `content-rebuild` (Elevated, merge_order 2, per-unit skeptic, depends_on gitignore-config for MERGE order only): Phase 8 block in `implement-ticket.md` + prose (conventions, events-log, sections/09, init-project) + all 8 adapters + baseline. Built in parallel with Unit 1; merged second.

## Open questions

None (design OQs resolved 2026-06-12).
