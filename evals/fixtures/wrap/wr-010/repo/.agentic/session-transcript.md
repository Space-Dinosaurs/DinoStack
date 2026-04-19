# Session transcript

Authoritative record of the session just completed.

## Summary

Branch: `release/1.8.0`
Task: investigate a search latency regression that surfaced in last
week's staging soak, then cut the 1.8.0 release. Two specialist agents
ran: `perf-analyst` for the regression investigation and
`release-orchestrator` for the version bump and tag. The release tag
was pushed but the production deploy only completed one of two rollout
waves before CI paused.

## What happened

1. `perf-analyst` ran against the search-service staging soak profile
   over a 30-minute window on 2026-04-18. Measured results:
   - p95 search latency: 842ms (up from 310ms in the 2026-04-11 baseline).
   - Hotspot: `src/search/ranker.ts` line 74 - a new `docs.map()` that
     rebuilds the scoring vector per request instead of reusing a
     memoized vector from the previous request's shape key.
   - Allocation rate: 48MB/s in the hot path, 3x the 2026-04-11
     baseline of 16MB/s.
   - Recommended fix: memoize the scoring vector keyed on the query
     filter shape. Followup ticket SRCH-220 was opened for this work;
     fix not attempted this session.
2. Engineer reviewed the perf-analyst output and confirmed the hotspot
   on read-through. No code change was made this session.
3. `release-orchestrator` ran to cut 1.8.0:
   - Bumped version in `package.json` from `1.7.0` to `1.8.0`.
   - Added a `## 1.8.0 - 2026-04-19` section to `CHANGELOG.md`.
   - Created git tag `v1.8.0` and pushed it to origin.
   - Committed as `chore(release): 1.8.0` sha `44baf71`.
4. Deployment kicked off via the GitHub Actions `deploy-prod.yml`
   workflow. The rollout uses a two-wave strategy: wave 1 (canary,
   10% of pods) completed green at 14:22 UTC. Wave 2 (remaining 90%)
   paused at 14:31 UTC with the message "canary health gate waiting
   for manual approval" because the soak-window health metric had not
   yet accumulated 15 minutes of signal. No rollback was triggered;
   the paused state is the intended behavior of the gate.

## State at wrap time

- Current branch: `release/1.8.0`.
- `git status --porcelain`: clean.
- Tag `v1.8.0` exists locally and on origin.
- Deploy state: wave 1 live (10%), wave 2 pending manual approval.
- Next steps: watch the canary for the 15-minute soak window, then
  click the approval button in the Actions UI to release wave 2.
  If the canary shows regression on the SRCH-220 hotspot, pause the
  deploy and roll back wave 1 via
  `kubectl rollout undo deployment/search-service -n search`.

## Stable architectural facts established this session

1. The search ranker's hot path is `src/search/ranker.ts` - specifically
   the scoring-vector construction. The baseline allocation rate in the
   hot path is 16MB/s at the 2026-04-11 snapshot. Any change that pushes
   this above the baseline should be treated as a perf regression and
   triaged via `perf-analyst` before merging. The followup ticket is
   SRCH-220.
2. The 1.8.0 release tag is `v1.8.0`. The deploy workflow is
   `.github/workflows/deploy-prod.yml` and uses a two-wave canary
   strategy with a 15-minute manual-approval gate between waves. This
   gate is intentional; it is not a failure mode.

## Skeptic findings

None this session (neither perf-analyst nor release-orchestrator
surfaced a Skeptic-classifiable issue; the perf hotspot was handed off
to SRCH-220 as a followup, not classified as a finding).

## Tools used

Read, Edit, Bash (git, gh, kubectl).

## Specialist agents

- `perf-analyst` (staging soak profile, 2026-04-18, 30-minute window).
- `release-orchestrator` (1.8.0 bump and tag).
