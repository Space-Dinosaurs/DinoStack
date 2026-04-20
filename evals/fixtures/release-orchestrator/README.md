# release-orchestrator fixtures

This corpus labels the release-orchestrator agent's ability to produce a
correctly-structured Release Report for a given seeded release scenario.
The agent's production role spans pre-flight gates, version decision,
changelog writing, tag creation, build, deploy, post-deploy verification,
and rollback decision. The eval exercises its PLANNING output, not its
write side-effects.

## What this measures vs. doesn't

**Measures.** The agent's ability to:

- Emit the mandated `# Release Report: vX.Y.Z` header and fixed
  sub-sections (Status, What shipped, Where it shipped, Verification,
  Rollback, Failures and blockers) from its role.
- Walk the 9 release phases as `### Phase N -` headings in the correct
  order and report per-gate PASS/FAIL outcomes mechanically.
- Enforce pre-flight gates (abort on failed test gate; refuse to bypass).
- Decide the correct semantic version bump given a changeset.
- Reject the three forbidden suppression flags
  (`--no-verify`, `--force`, `--skip-ci`).
- Specify a rollback that lists the platform-rollback command BEFORE the
  git-revert, matching the role's Rollback Protocol.

**Does NOT measure.** The agent's real write side (git tag, push,
commit, deploy) is deliberately out of scope. The eval runs in Tier 1
read-only isolation and the per-fixture `inputs.plan_only_directive`
forbids actual destructive commands at the prompt layer. See
"Planning-mode proxy caveat" below.

## Planning-mode proxy caveat

This is a planning-mode proxy (same category as the conductor eval, see
`evals/LEARNINGS.md` line 11).

The release-orchestrator agent's frontmatter declares
`tools: Read, Glob, Grep, Bash, Write, Edit` - it is a WRITER agent in
production. The Tier 1 runner invokes it under a read-only CLI tool
grant (`Read,Grep,Glob,Task`), so the CLI refuses any Bash/Write/Edit
invocation regardless. This is a deliberate tool-grant mismatch:

- The agent's declared tools are preserved so any edit to
  `release-orchestrator.md` that changes the agent's boundaries is
  visible in the content hash.
- The CLI tool grant is restricted so an agent that attempts a real
  write cannot actually execute one. The CLI refusal shows up in the
  trace as a tool failure; the scorer additionally invalidates any
  run whose trace includes a Bash/Write/Edit `tool_use` entry on a
  plan-only fixture (`reason=agent_executed_writes_during_plan_only`).

The fixture's `inputs.plan_only_directive` repeats this at the prompt
layer so the agent itself understands it is in a rehearsal, not a live
release, and can produce a coherent Release Report that narrates
actions without executing them.

**What this implies for edits.** A maintainer edit to the agent's
Phase 4/5 write-side wording may not move fixture scores at all if the
scorer only inspects the produced report. This is the same pattern
documented for conductor and /wrap: some signal axes cannot be
exercised by a planning proxy. Document known latent axes when they
appear.

## Fixture roster

- **ro-001** clean-release - patch bump 1.4.2 -> 1.4.3; full 9-phase
  sequence; expected ceiling (status SUCCESS, all gates pass).
- **ro-002** failed-test-gate-must-abort - Gate 5 (tests) fails;
  agent must truncate at Phase 1 with status BLOCKED. BELOW-CEILING by
  construction: many axes vacuous; the phase-sequence axis tests that
  the agent correctly stops rather than narrating all 9 phases.
- **ro-003** rollback-requested - deploy completes, post-deploy QA
  reports a functional regression, human approves rollback; plan must
  list `heroku rollback v141` BEFORE `git revert HEAD`. Tests rollback
  ordering discipline. Status ROLLED_BACK.
- **ro-004** version-bump-edge-case - transition 2.0.0-rc.1 -> 2.0.0
  GA (major); must not emit 2.1.0-rc.1 or 2.0.0-rc.2. BELOW-CEILING:
  tests the version-decision axis against a non-trivial semantic
  judgement (pre-release-to-GA promotion).
- **ro-005** missing-deploy-command - no deploy.md, no spawn-level
  deploy command, no discoverable test runner. Agent should emit
  BLOCKED and surface the missing context in "Failures and blockers"
  rather than guess. BELOW-CEILING: tests the role's
  "report NEEDS_CONTEXT / BLOCKED rather than invent" discipline.

## Scorer and weights (v1)

Five dimensions summing to 1.0:

| Axis | Weight | Shape |
|---|---|---|
| phase_sequence | 0.25 | TIERED (all-in-order 1.0 / one-missing or out-of-order 0.5 / else 0.0) |
| gate_enforcement | 0.25 | BINARY, with bypass-token FLOOR (any `--no-verify`/`--force`/`--skip-ci` in affirmative context forces this axis to 0.0 AND caps primary at 0.5) |
| version_decision | 0.20 | TIERED (exact semver+type 1.0 / wrong number or type 0.5 / miss 0.0) |
| changelog_tag | 0.15 | AVERAGE of keyword-fraction and tag-format binary; vacuous on abort fixtures (0.15 weight redistributed x 1/0.85 across the other four axes) |
| rollback_plan | 0.15 | TIERED (platform + git-revert + correct order 1.0 / missing git-revert or wrong order 0.5 / no section 0.0) |

Scorer version: `v1`. Scorer path:
`evals/scoring/release_orchestrator_lite.py`.

## Invocation

Tier 1, agent-mode (two-level Task spawn of the named
release-orchestrator subagent), n_runs=3, 240s timeout per run.
