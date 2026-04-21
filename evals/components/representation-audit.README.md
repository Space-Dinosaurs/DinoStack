# representation-audit component eval

Measures whether `content/commands/representation-audit.md` produces a
well-structured proposal artifact under `docs/planning/` when run against
a seeded methodology corpus.

## What this measures

- Does the command produce a proposal file at
  `docs/planning/representation-audit-YYYY-MM-DD.md`?
- Does the proposal carry every required section
  (Signal summary, Rewrite candidates, Files reviewed with no rewrites
  proposed, Recommended action sequence)?
- Does each candidate block contain each required field (File, Current
  form, Proposed form, Signal(s), Meaning preserved, Priority, Priority
  rationale, Risk of meaning shift)?
- Is the total candidate count inside the fixture's declared
  `[min, max]` tier (in-range -> 1.0; off-by-one either side -> 0.5;
  else 0.0)? Fixtures that declare `allow_empty_with_rationale: true`
  allow zero candidates when the proposal states an explicit
  empty-rationale sentence.
- Do Signal labels draw from `R1..R7`, Priority values draw from
  `HIGH/MEDIUM/LOW`, Meaning-preserved values draw from `HIGH/MEDIUM/LOW`?
  Each sub-check is vacuous when no candidate declares the field.
- Does the run avoid any write or edit to `content/**`? The command's
  safety model prohibits it; any content/** mutation is a hard defect.

## What this does NOT measure

- Actual meaning preservation of proposed rewrites. Measurement of
  whether a proposed rewrite preserves the original rule's meaning is
  the meaning-preservation Skeptic's job at
  `/update-agentic-engineering` time - Step 4 of the command - which is
  out of scope here.
- Quality of candidate ranking. The scorer counts candidates and checks
  vocabulary; it does not judge whether the analyst picked the
  highest-impact 3-10 rewrites.
- Proposal prose fluency or readability. The scorer checks structural
  presence; it does not read the Current form / Proposed form pairs for
  stylistic cleanness.
- Step 0 (git-sync preflight). Skipped in the eval - the worktree has
  no origin and no branching state, so preflight would block or no-op
  without measuring anything useful. Maintainer edits to Step 0 will
  not move fixture scores.
- Step 2 (present to user) and Step 4 (action approved candidates via
  `/update-agentic-engineering`). Skipped - the eval has no interactive
  user and writing additional candidates would distort the
  forbidden-content axis.

## Invocation caveat (proxy disclosure)

The eval inlines the verbatim body of
`content/commands/representation-audit.md` into the `-p` prompt. This is
NOT a real `/representation-audit` slash-command dispatch: under a
redirected `$HOME`, the command is not discoverable because the skill /
command install path is absent (same caveat as `/init-project` and
`/wrap`; see `evals/LEARNINGS.md`).

Implication: we measure the COMMAND BODY executed by a top-level Claude
session with Read/Grep/Glob/Task/Write/Edit/Bash tools and
`--permission-mode acceptEdits`. We do not measure the slash-command
plumbing itself. This is a proxy acceptable for scoring the command's
intent plus content, not for validating command installation.

Additional proxy: the eval directs the command to write the proposal
INLINE rather than spawn a Task subagent. Production routes Step 1
through a `general-purpose` Worker spawn. The eval collapses that
subagent hop to measure the proposal-artifact quality without adding
subagent-cost variance. Maintainer edits that only affect the Worker
execution-contract block (budget, tool_scope wording) may not move
fixture scores here.

## Isolation

Tier 2: worktree tmpdir seeded from `fixture/repo/`, plus a fake `$HOME`
tmpdir with a seeded `.claude/agentic-engineering.json` per
`fixture.inputs.home_config`. The subprocess runs with HOME pointed at
the fake dir so it never touches the developer's real `~/.claude/`.

Each fixture's seeded repo contains an opt-in AGENTS.md (the literal
line `agentic-engineering: opt-in`) plus a synthetic `content/rules/`
and `content/references/` snapshot (real text in ra-001 / ra-005;
deliberately sparse or stress-shaped in the others).

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this component:

- Expanding the scorer's signal enum to accept synonyms an analyst
  emitted. Don't - enforce vocabulary in the prompt's Required-outputs
  block instead.
- Loosening the forbidden-content axis to allow edits under
  `content/rules/` for some fixture. Don't - the audit's safety model
  is load-bearing; if a rewrite is worth shipping it goes through
  `/update-agentic-engineering`, not the audit itself.
- Lowering the candidate-count min/max on a fixture to make its tier
  activate. Don't - the range reflects the command's declared 3-10
  window; pick fixtures that either naturally hit in-range or
  deliberately stress the off-by-one tier.

## Known limitations

- The scorer does not verify that the proposal's "Current form" blocks
  quote real file excerpts. A well-formed but fabricated candidate
  would score identically to a grounded one on this scorer.
- The scorer's candidate-parser locates the first `## ` heading
  containing `candidate`. Proposals that split candidates across
  multiple `## ` regions (against the template) will undercount.
