# Implement Ticket

Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted back to the ticket.

## Invocation

`/implement-ticket [TICKET_ID]`

---

## Setup: Read project config

Before any phase, read the project's `AGENTS.md` and extract the following values:

- `REPO` — absolute path to the repo root
- `GH_REPO` — GitHub repo slug (e.g. `org/repo-name`)
- `BASE_BRANCH` — the branch all work is based from. If not declared in `AGENTS.md`, resolve in this order: (1) `develop` if it exists locally; (2) `development` if it exists locally; (3) stop and ask the user which branch to use. Do not auto-create a branch. Once resolved, print: `BASE_BRANCH resolved to: [value]`.
- `QUALITY_CMD` — the full quality gate command to run from repo root

**Tracker resolution** — read tracker config using this fallback chain:

1. If a `## Tracker` section exists in `AGENTS.md` and contains `TRACKER: jira`: set `TRACKER=jira`. Extract `TICKET_PREFIX`, `JIRA_BASE_URL`, `JIRA_QA_ASSIGNEE_ACCOUNT_ID` (optional), `JIRA_QA_TRANSITION` (optional — no default).
2. Else if a `## Tracker` section exists with `TRACKER: linear` (future-proofing): treat as Linear and read Linear fields from `## Tracker` instead of `## Linear`.
3. Else if a `## Linear` section exists: set `TRACKER=linear`. Extract `Team` → `TICKET_PREFIX`, `Workspace` → `LINEAR_WORKSPACE`, `QA assignee ID` → `LINEAR_QA_ASSIGNEE_ID` (optional).
4. Else: set `TRACKER=none`.

**Dual-shape note:** Linear projects canonically store tracker config under `## Linear`; Jira projects use `## Tracker`. This is intentional — it preserves zero-migration compatibility for every existing Linear project that already has a `## Linear` section.

**Legacy `## Linear` shape guard** — if `TRACKER=linear` was resolved from a `## Linear` section AND the section is missing the `Workspace:` field (required for URL generation), stop immediately and print:

```
Your tracker config is missing fields /implement-ticket needs. Run /init-project to update it —
discovery will fill in most fields automatically.
```

Do not continue. Do not attempt to write the migration. All config-mutation logic lives in `/init-project`.

Print a summary of resolved values before Phase 1:

```
Tracker:       [linear | jira | none]
TICKET_PREFIX: [value or "n/a"]
BASE_BRANCH:   [value]
```

All work lives in `$REPO`.

---

## Phase 1: Understand the ticket

(Setup has already resolved TRACKER. Execute exactly one of the sub-sections below.)

#### If TRACKER is `linear`

1. Call `mcp__linear__get_issue` with the ticket ID and `includeRelations: true`.
2. Read the full description — specifically the **Implementation**, **Files**, and **QA** sections.
3. Note any blocking tickets (`blockedBy`) — confirm they are done before proceeding.
4. Note the ticket type (feature vs bug) — this drives branch naming.

#### If TRACKER is `jira`

1. Call `mcp__mcp-atlassian__jira_get_issue` with `issue_key: "[TICKET_PREFIX]-NNN"` and `fields: "*all"` to get the full issue including description and current status.
2. Read the full description — note any **Acceptance Criteria**, **Implementation Notes**, and **QA** content in the description or sub-tasks.
3. Note any blocking issues — confirm they are resolved before proceeding.
4. Note the issue type (Story, Bug, Task) — this drives branch naming.

#### If TRACKER is `none`

No ticket to fetch. Ask the user: "No tracker configured. Please describe what you want to implement." Use the user's description as the ticket content for all downstream phases. Set ticket type to "feature" unless the user indicates otherwise.

---

Proceed to Phase 2 regardless of which sub-section executed.

---

## Phase 2: Read the codebase

Before planning, gather context:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO fetch origin $BASE_BRANCH --quiet
```

Read:
- Files mentioned in the ticket description
- Sibling files to understand existing patterns
- `$REPO/AGENTS.md` for conventions
- The project's `MEMORY.md` (auto-injected at session start) for architectural decisions and rationale; if the project maintains a custom decision log, read that too
- Any `[track]/AGENTS.md` files for tracks touched by this ticket - track-specific conventions, stack, and gotchas

Focus on understanding enough to make a solid plan - don't over-read.

**Investigator conditional:** If the code area touched by this ticket is unfamiliar to the current session (files not yet read, subsystems not yet traced), spawn an `investigator` agent first. Pass its brief to the Architect in Phase 3. Skip this step if Phase 2 reads already covered the relevant area.

---

## Phase 3: Architecture plan

Spawn an `architect` agent. Provide:
- The full ticket title and description
- The relevant code snippets you gathered
- The AGENTS.md conventions
- Any architectural decisions and rationale from MEMORY.md (or the project's custom decision log) that bear on this ticket

Ask the architect for:
1. A concrete implementation plan (what changes, in which files, in what order)
2. Which units of work can be done **in parallel** vs must be **sequential**
3. Any risks, gotchas, or ambiguities that need resolution before coding
4. The appropriate adversarial brief type for Skeptic review (security, logic, performance, data integrity, etc.)

**Architect plan Skeptic review (mandatory):** After the Architect returns its plan, spawn a Skeptic with the "Document synthesis, architecture, and planning" adversarial brief. Do not proceed to Phase 3b or Phase 4 until the Skeptic grants sign-off. If the Skeptic-approved plan contains a non-empty "Open questions" section, resolve every open question before proceeding - see `agent-methodology.md` for resolution paths. For the full adversarial brief menu, see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

---

## Phase 3b: Orchestration plan (conditional)

**Trigger** - spawn `orchestration-planner` if any of the following are true:
- The architect identified parallel units
- The ticket mentions changes across 3 or more distinct directories or top-level modules
- The architect's plan contains 3 or more distinct implementation units, or explicitly flags sequencing uncertainty or agent selection ambiguity

**Skip** - proceed directly to Phase 4 if none of the trigger conditions above are true.

**When spawning `orchestration-planner`, provide:**
- The full ticket title and description
- The architect's complete output
- Instruction to produce: agent roster, execution phases (each with Give it / Returns / Proceed when fields), Skeptic checkpoints, and parallelization opportunities

The orchestration-planner's output drives Phase 5 agent spawning. If Phase 3b was skipped, Phase 5 falls back to the architect's plan directly.

---

## Phase 4: Create the branch

Create the branch locally from `$BASE_BRANCH` - do not push yet (push happens after the first commit):

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO checkout -b [BRANCH_NAME per AGENTS.md convention] origin/$BASE_BRANCH
```

**Branch naming:** use the branch naming convention from AGENTS.md.

Derive the short title from the ticket title: lowercase, hyphens, ~4-5 words max.

---

## Phase 5: Implement

Use the orchestration-planner's output to drive agent spawning decisions if Phase 3b produced a plan. If Phase 3b was skipped, use the architect's plan directly. When both are present, the orchestration-planner's output supersedes the architect's plan for agent spawning and parallelization decisions.

Read the orchestration-planner's output to make the routing determination below if Phase 3b ran; read the architect's output directly if Phase 3b was skipped.

**Module manifests:** Files modified must carry module manifests per `~/agentic-engineering/.claude/skills/agentic-engineering/rules/module-manifest.md` when non-trivial. Skeptic will flag missing or stale manifests as Major findings in Phase 6.

### If work is a single logical unit (or units must be sequential):

Spawn one `engineer` agent per unit in sequence. Each agent prompt should include:
- The execution contract block from `agent-methodology.md` (Worker preamble section), filling in fields from the architect's plan / orchestration-planner output for this unit
- The plan for this unit: if Phase 3b ran, use the orchestration-planner's output for this unit; if Phase 3b was skipped, use the architect's plan for this unit
- The branch name to work on
- The repo path: `$REPO`
- Instruction to run `$QUALITY_CMD` from the repo root before finishing and fix any errors

### If parallel independent units were identified:

Use git worktrees to give each engineer an isolated copy. Each worktree gets its own branch (a sub-branch of the feature branch):

```bash
# Create one worktree per parallel unit, each on its own sub-branch
git -C $REPO worktree add ${REPO}/.worktrees/[BRANCH_NAME]-unit1 -b [BRANCH_NAME]-unit1 origin/$BASE_BRANCH
git -C $REPO worktree add ${REPO}/.worktrees/[BRANCH_NAME]-unit2 -b [BRANCH_NAME]-unit2 origin/$BASE_BRANCH
```

Spawn one `engineer` agent per worktree in the same message (parallel). Each agent works in its assigned worktree path and commits to its own sub-branch. Each agent's prompt should include:
- The execution contract block from `agent-methodology.md` (Worker preamble section), with fields filled in from the per-unit scope in the plan
- The per-unit scope extracted from the plan: if Phase 3b ran, extract from the orchestration-planner's output for that unit; if Phase 3b was skipped, extract from the architect's plan for that unit

After all engineers complete, verify each engineer committed successfully, then merge their sub-branches into the main feature branch:

```bash
# Verify each engineer committed successfully before merging.
# Run the following for each worktree and abort if output is non-empty (uncommitted changes present):
# git -C ${REPO}/.worktrees/[BRANCH_NAME]-unit1 status --porcelain
# git -C ${REPO}/.worktrees/[BRANCH_NAME]-unit2 status --porcelain

git -C $REPO checkout [BRANCH_NAME]
git -C $REPO merge --no-ff [BRANCH_NAME]-unit1

# After each merge, check for conflicts before continuing:
# git -C $REPO diff --name-only --diff-filter=U
# If that command outputs any file names, conflicts are present. Run:
#   git -C $REPO merge --abort
# Then route back to a fresh engineer with: the original ticket title and description;
# the plan for both units (from orchestration-planner output if Phase 3b ran, from architect
# if skipped); both units' full changes (diffs or file contents from their worktrees);
# the target branch ([BRANCH_NAME] on the main repo, not a worktree); and explicit
# instruction to implement the two units sequentially (not in parallel) to resolve the conflict.
# Do not continue to the next merge or clean up worktrees until the conflict-free merge succeeds.

git -C $REPO merge --no-ff [BRANCH_NAME]-unit2

# Repeat the same conflict check after this merge before proceeding.

# Clean up worktrees and sub-branches
git -C $REPO worktree remove ${REPO}/.worktrees/[BRANCH_NAME]-unit1 --force
git -C $REPO worktree remove ${REPO}/.worktrees/[BRANCH_NAME]-unit2 --force
git -C $REPO branch -d [BRANCH_NAME]-unit1 [BRANCH_NAME]-unit2
```

For full worktree cleanup rules (isolation worktrees, feature worktrees, stale branch pruning), see `agent-methodology.md §Worktree Lifecycle`.

**Merge-conflict re-route and loop iteration:** If a merge conflict re-route occurred above and the re-routed Engineer's output then goes through Skeptic review in Phase 6, the conflict re-route counts as iteration 1 of the Phase 6 loop. Do not double-count: the conflict-resolution Engineer pass is the first fix pass; Phase 6 initializes its `iteration` counter at 1 to reflect this.

---

## Phase 6: Skeptic review

**Phase 6 guard (tight-fix path).** If Phase 5 spawned the engineer under the Elevated (tight-fix path) sub-path (see `agent-methodology.md`) AND the Worker returned Status: DONE with the verbatim pre-commit test output in its summary, skip the rest of Phase 6. The tight-fix path's pre-commit test verification replaces the post-impl Skeptic for this case. If the Worker returned Status: BLOCKED or DONE_WITH_CONCERNS, fall through to the standard Phase 6 Skeptic spawn on the uncommitted diff (see `skeptic-protocol.md` line 376 for the amended "no irreversible changes" rule that permits this sub-path).

Spawn a `skeptic` agent with:
- The adversarial brief type identified by the architect
- The full diff: `git -C $REPO diff origin/$BASE_BRANCH..HEAD`
- The ticket description as the success criteria
- The QA section from the ticket as acceptance tests

For the full adversarial brief menu (security, logic, performance, data integrity, etc.), see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Findings handling - loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (create `.agentic/` directory if absent):

```
LOOP_STATE initialized:
  phase: skeptic
  iteration: 1
  max_iterations: 3
  findings_log: []
  last_engineer_summary: null
  termination_reason: null
```

Write this as JSON to `.agentic/loop-state.json`:

```json
{
  "phase": "skeptic",
  "iteration": 1,
  "max_iterations": 3,
  "findings_log": [],
  "last_engineer_summary": null,
  "termination_reason": null
}
```

**Stability contract:** `.agentic/loop-state.json` is a stable contract from P0 onward. The P2 rate-limit resumer will READ this file for resume keying; any schema change post-P0 must consider P2 readers.

The file is overwritten (not appended) on each iteration state update and at loop exit with `termination_reason` set. It is not deleted on clean termination - the final state is the post-mortem record until the next loop invocation overwrites it. Whether `.agentic/` is gitignored is deferred to project convention.

Emit the inline breadcrumb:

```
[loop: skeptic | iteration 1/3 | open findings: -]
```

**Loop entry (repeat until termination):**

**Step 1.** Spawn `skeptic` with adversarial brief. On iteration 2+, prepend the "Prior iteration findings" block to the brief (see `skeptic-protocol.md` Section 4 - findings_log entries map directly to the preflight list format). Format re-invocations (up to 3 per `skeptic-protocol.md` Section 11) do NOT increment `iteration`.

```
## Prior iteration findings

The following findings were raised in earlier iterations. For each:
- If the current diff shows the finding was addressed: mark it CLOSED with a one-line confirmation.
- If the current diff does NOT show the finding was addressed: re-raise it using [PREV: <id>] prefix in the finding title.
- Do not re-raise findings that were resolved - do not invent new instances of a previously-closed finding without new evidence.

[paste findings_log entries with status=open or status=addressed]
```

**Step 2.** Receive Skeptic output. Classify findings. Update `findings_log`:
- Each finding gets a short slug `id` (e.g. `"null-deref-user-service"`), `severity`, `first_raised: <iteration>`, `status: open`.
- If a finding carries `[PREV: <id>]`, set `re_raised: true` on the matching `findings_log` entry.
- Minor findings: the conductor may mark them `deferred` if the finding scope exceeds the ticket. Deferred Minors do not re-enter the loop and are documented in the PR description. Major findings may NOT be deferred without explicit human approval - escalate rather than accepting a self-declared deferral. **Loop-context override:** the base `skeptic-protocol.md` permits deferral of Majors with "a compelling documented reason"; inside the loop, this is tightened to require explicit human approval. The conductor escalates rather than accepting an Engineer's self-declared deferral.
- Overwrite `.agentic/loop-state.json` with the updated LOOP_STATE.

**Step 3. Termination check:**
- If no Critical or Major findings: auto-close all `findings_log` entries with `status: open` or `status: addressed` (set to `closed`). Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. Exit loop cleanly. Proceed to Phase 6b.
- If `iteration == max_iterations` AND Critical or Major findings remain: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human (see Escalation section below). Phase 6b does NOT run.
- If any Critical finding carries `re_raised: true` (same finding re-raised after a claimed fix): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human. (This overrides the 2-re-route rule in `skeptic-protocol.md` Section 5 - see that section for the override note. One re-raise after a claimed fix is sufficient within the loop.)

**Step 4. Engineer fix pass.** Spawn a fresh `engineer` agent with:
- The open Critical and Major findings from `findings_log` (status=open)
- The `last_engineer_summary` from the prior iteration
- Instruction: "Address only the findings listed below. Do not expand scope. Do not refactor, rename, or clean up code outside the finding scope. For each finding, confirm in your summary what you changed and why it addresses the finding."
- The branch name and repo path
- Instruction to run `$QUALITY_CMD` before finishing

**Step 5.** Receive Engineer output.
- If `Status: BLOCKED`: set `termination_reason: blocked`. Overwrite `.agentic/loop-state.json`. Emit escalation format. Stop. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply the missing context (from codebase, session context, or by asking the human) and re-spawn the Engineer with the same findings brief and the added context. Do NOT increment `iteration`. If the conductor cannot supply the context, escalate to the human with the Engineer's stated gap.
- If `Status: DONE_WITH_CONCERNS`: proceed normally. The Engineer's stated concerns become additional context for the next Skeptic spawn (include them alongside the adversarial brief). Update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.
- Otherwise (`Status: DONE`): update `last_engineer_summary`. Update `findings_log` entries the Engineer claims to have fixed to `status: addressed`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.

**Escalation format (cap_reached, convergence_failure, or blocked):**

```
LOOP STALLED - [reason: cap_reached | convergence_failure | blocked]
Iteration: [N] of 3

Open findings that could not be resolved:
[list findings_log entries with status=open]

[If convergence_failure]: The following finding was re-raised after a claimed fix:
[finding id, original raise, claimed fix, Skeptic's re-raise note]

[If blocked]: Engineer returned BLOCKED with the following description:
[Engineer's blocker description verbatim]

Recommended action: review the open findings above and either:
(a) Provide clarifying direction to the Engineer on how to address [finding id], or
(b) Accept the finding as a known limitation and confirm deferral, or
(c) Scope the fix as a follow-on ticket.
```

Note: the escalation format surfaces findings and history only. The conductor does not synthesize fix suggestions - that would undermine the convergence failure signal.

---

## Phase 6b: QA Gate (conditional)

**Phase 6b only runs if Phase 6 exits cleanly (Skeptic sign-off granted, `termination_reason: clean`).** If Phase 6 exits via `cap_reached`, `convergence_failure`, or `blocked` escalation, Phase 6b is skipped entirely. Running QA on a Skeptic-rejected implementation is wasteful - the Phase 6 escalation subsumes Phase 6b for that session.

**Cap independence:** Phase 6 and Phase 6b caps are independent - exhausting the Phase 6 Skeptic cap (3 fix passes) does not consume Phase 6b QA cap budget, and vice versa. Each phase gets its own 3-fix-pass budget evaluated separately.

**Trigger:** `.claude/qa.md` exists AND has a `## QA triggers` section AND the diff matches at least one trigger pattern.

- **If not triggered:** skip directly to Phase 6c.
- **If triggered:** proceed with the QA loop contract below.

For full QA gate rules, see `agent-methodology.md §QA Gate`.

**QA loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (overwriting the Phase 6 state):

```
LOOP_STATE initialized:
  phase: qa
  iteration: 1
  max_iterations: 3
  qa_failures_log: []
  last_engineer_summary: null
  termination_reason: null
```

Write as JSON to `.agentic/loop-state.json` (same stability contract as Phase 6 - see above).

Emit the inline breadcrumb:

```
[loop: qa | iteration 1/3 | open failures: -]
```

**Loop entry (repeat until termination):**

**Step 1.** Spawn `qa-engineer` with ticket context, diff, and `.claude/qa.md` config. On iteration 2+, prepend the "Prior QA failures" section to the brief:

```
## Prior QA failures

The following failures were identified and fix attempts were made in earlier iterations. For each:
- If the acceptance criterion now passes: mark it CLOSED with a one-line confirmation.
- If the criterion still fails: re-raise it using [PREV: <id>] prefix in the failure description.
- Do not re-raise failures that are confirmed fixed.

[paste qa_failures_log entries with status=open or status=addressed]
```

**Step 2.** Receive QA output. Update `qa_failures_log`:
- Each failure gets a short slug `id`, `description`, `first_raised: <iteration>`, `status: open`.
- If a failure carries `[PREV: <id>]`, set `re_raised: true` on the matching `qa_failures_log` entry.
- Overwrite `.agentic/loop-state.json` with the updated LOOP_STATE.

**Step 3. Termination check:**
- If PASS (all acceptance criteria met): auto-close all `qa_failures_log` entries. Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. Exit loop cleanly. Proceed to Phase 6c.
- If `iteration == max_iterations` AND still failing: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human with the `qa_failures_log`. Phase 6c does NOT run.
- If same failure recurs unchanged after a claimed fix (`re_raised: true`): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human with convergence note.

**Step 4. Engineer fix pass.** Spawn `engineer` with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6:
- If `Status: BLOCKED`: set `termination_reason: blocked`. Escalate immediately. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply context and re-spawn without incrementing `iteration`. If context cannot be supplied, escalate to human.

**Step 5.** Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT (whether `Status: DONE` or `Status: DONE_WITH_CONCERNS`): update `qa_failures_log` entries the Engineer claims to have fixed to `status: addressed`. Update `last_engineer_summary`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.

---

## Phase 6c: Promote findings

Apply the post-sign-off finding promotion rule from `agent-methodology.md` §Post-sign-off finding promotion. The rule is not `/implement-ticket`-specific - it fires after every Skeptic sign-off in any context. Full promotion criteria, entry format, and size-cap rules: `~/agentic-engineering/.claude/skills/agentic-engineering/references/findings-flywheel.md`.

---

## Phase 7: Quality gate

Run the full quality suite:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
cd $REPO && $QUALITY_CMD
```

All checks must pass (typecheck, lint, tests, knip, jscpd). Do not suppress or skip checks.

**If `$QUALITY_CMD` fails:**

This phase runs after Phase 6 and 6b loops have already exited cleanly. A quality gate failure here does NOT continue or re-enter the Phase 6 iteration counter. Instead:

1. Spawn one `engineer` fix pass scoped to the quality gate failure output. The Skeptic has already signed off on the implementation - this is a targeted quality gate fix, not a Skeptic-loop re-entry.
2. Re-run `$QUALITY_CMD`.
3. If it passes: proceed to Phase 6c (finding promotion) then Phase 8.
4. If it still fails: escalate to the human. Include the quality gate output from both the first run and the post-fix re-run. Do not spawn another Engineer pass.

**No unbounded loop:** Phase 7 failure only ever triggers one Engineer fix pass followed by one re-run. There is no retry loop at this phase.

**Tight-fix path interaction:** If the tight-fix path fired (Phase 6 guard bypassed the Skeptic entirely) and the Worker committed successfully, then Phase 7 fails - this triggers the one-Engineer-pass rule above. It does NOT re-enter the Phase 6 Skeptic loop. The Skeptic already signed off on the implementation via the tight-fix path's pre-commit verification. The Phase 7 fix pass is scoped to quality gate failures only.

---

## Phase 8: Commit and push

**Sequential path:** Stage specific files and commit as described below.

**Parallel path:** All commits were already made to sub-branches and merged in Phase 5. Phase 8 should only handle any post-merge fixup files that were not captured in the sub-branch commits. Run `git -C $REPO status --short` after the merge to check for any unstaged post-merge fixup files. If output is non-empty, stage and commit those files. If output is empty, skip the stage-and-commit step and proceed directly to push.

**Only run the following commit block if `status --short` was non-empty (parallel path) or on the sequential path:**

Stage specific files - never `git add -A` or `git add .`:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
git -C $REPO add [specific files]
git -C $REPO commit -m "$(cat <<'EOF'
type(scope): short imperative description

More detail on what changed and why if needed.
Closes [TICKET_PREFIX]-NNN

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
git -C $REPO push -u origin [BRANCH_NAME]
```

Commit message types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.

---

## Phase 9: Open the PR

Compose the `[TRACKER_REFERENCE_BLOCK]` based on the resolved `TRACKER`, then run the `gh pr create` command with that block included in the body.

#### If TRACKER is `linear`

```
## Linear
Closes [[TICKET_PREFIX]-NNN](https://linear.app/[LINEAR_WORKSPACE]/issue/[TICKET_PREFIX]-NNN)
```

#### If TRACKER is `jira`

```
## Jira
Closes [[TICKET_PREFIX]-NNN]([JIRA_BASE_URL]/browse/[TICKET_PREFIX]-NNN)
```

#### If TRACKER is `none`

Omit the tracker reference block entirely. The PR body will have only Summary and Test plan, and the PR title should omit the `[TICKET_PREFIX]-NNN:` prefix.

---

Run:

```bash
gh pr create \
  --repo [GH_REPO] \
  --base [BASE_BRANCH] \
  --head [BRANCH_NAME] \
  --title "[TICKET_PREFIX]-NNN: [ticket title]" \
  --body "$(cat <<'EOF'
## Summary
- [bullet 1]
- [bullet 2]

[TRACKER_REFERENCE_BLOCK]

## Test plan
- [ ] [step 1]
- [ ] [step 2]
EOF
)"
```

For `TRACKER=none`, omit the tracker reference block line and drop the `[TICKET_PREFIX]-NNN:` prefix from `--title`.

Capture the PR number from the URL printed by `gh pr create`.

---

## Phase 10: Wait for CI Test URL

The CI workflow deploys the branch to Cloudflare and posts a comment on the PR from `github-actions[bot]` containing a markdown "Test URL" link.

Poll every 60 seconds for up to 5 minutes (5 checks):

```bash
PR_NUMBER=[PR_NUMBER]
TEST_URL=""

for i in 1 2 3 4 5; do
  BODY=$(gh pr view $PR_NUMBER \
    --repo $GH_REPO \
    --json comments \
    --jq '.comments[] | select(.author.login == "github-actions[bot]") | select(.body | contains("Test URL")) | .body' \
    2>/dev/null | head -1)

  if [ -n "$BODY" ]; then
    echo "CI comment found:"
    echo "$BODY"
    # Extract URL from markdown link: [Test URL](https://...)
    TEST_URL=$(echo "$BODY" | grep -oP '\[Test URL\]\(\K[^)]+')
    echo "Test URL: $TEST_URL"
    break
  fi

  echo "Waiting for CI... ($i/5)"
  sleep 60
done

echo "Final Test URL: ${TEST_URL:-not found}"
```

If CI hasn't posted after 5 minutes, proceed with what you have - post the PR link to the ticket and note that the Test URL is pending.

---

## Phase 11: Post to tracker

Once you have the Test URL (or the PR link as fallback):

(Execute exactly one of the sub-sections below based on the resolved `TRACKER`.)

#### If TRACKER is `linear`

1. **Update the issue** — call `mcp__linear__save_issue` with:
   - `state: "Testing"` (or the equivalent state transition for your team)
   - `assigneeId: "[LINEAR_QA_ASSIGNEE_ID]"` — **only include this field if `LINEAR_QA_ASSIGNEE_ID` was present in `## Linear`**. If absent, skip the assignee change entirely and log: "QA assignee ID not configured — skipping assignee update. Add it to ## Linear to enable this."

2. **Post the comment** — call `mcp__linear__save_comment` with body:

```
Implementation complete. Ready for QA.

**Test URL:** [EXTRACTED_TEST_URL or "pending — see PR"]
**PR:** https://github.com/[GH_REPO]/pull/[PR_NUMBER]

[1-2 sentences on what specifically to test and any known limitations from the Skeptic review]
```

#### If TRACKER is `jira`

1. **Transition the issue** — **only if `JIRA_QA_TRANSITION` was present in `## Tracker`**. If absent, skip this step entirely and log: "JIRA_QA_TRANSITION not configured — skipping transition. Add it to ## Tracker to enable this."
   
   If present: call `mcp__mcp-atlassian__jira_get_transitions` with the ticket ID to list available transitions, then call `mcp__mcp-atlassian__jira_transition_issue` with:
   - `issue_key: "[TICKET_PREFIX]-NNN"`
   - the transition ID matching `[JIRA_QA_TRANSITION]` (by name)
   
   If the transition name is not found in the returned list, log the failure ("JIRA_QA_TRANSITION value '[value]' did not match any available transition — skipping") and proceed to step 2. Do not abort Phase 11 — the comment is higher value than the status change.

2. **Update the assignee** — **only if `JIRA_QA_ASSIGNEE_ACCOUNT_ID` was present in `## Tracker`**. If absent, skip and log: "Jira QA assignee not configured — skipping assignee update." 
   
   If present: call `mcp__mcp-atlassian__jira_update_issue` with:
   - `issue_key: "[TICKET_PREFIX]-NNN"`
   - `fields: '{"assignee": {"accountId": "[JIRA_QA_ASSIGNEE_ACCOUNT_ID]"}}'`
   
   If the call fails (invalid account ID, permission error), log and proceed to step 3.

3. **Post the comment** — call `mcp__mcp-atlassian__jira_add_comment` with:
   - `issue_key: "[TICKET_PREFIX]-NNN"`
   - `body`:

```
Implementation complete. Ready for QA.

Test URL: [EXTRACTED_TEST_URL or "pending — see PR"]
PR: https://github.com/[GH_REPO]/pull/[PR_NUMBER]

[1-2 sentences on what specifically to test and any known limitations from the Skeptic review]
```

#### If TRACKER is `none`

Skip Phase 11 entirely. Print: "No tracker configured — skipping ticket update. PR is open at: https://github.com/[GH_REPO]/pull/[PR_NUMBER]"
