> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# Implement

Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted back to the ticket.

## Invocation

`/implement [TICKET_ID]`

---

## Setup: Read project config

Before any phase, read the project's `CLAUDE.md` and extract the following values:

- `REPO` — absolute path to the repo root
- `GH_REPO` — GitHub repo slug (e.g. `org/repo-name`)
- `BASE_BRANCH` — the branch all work is based from. If not declared in `CLAUDE.md`, resolve in this order: (1) `develop` if it exists locally; (2) `development` if it exists locally; (3) stop and ask the user which branch to use. Do not auto-create a branch. Once resolved, print: `BASE_BRANCH resolved to: [value]`.
- `QUALITY_CMD` — the full quality gate command to run from repo root

**Tracker resolution** — read tracker config using this fallback chain:

1. If a `## Tracker` section exists in `CLAUDE.md` and contains `TRACKER: jira`: set `TRACKER=jira`. Extract `TICKET_PREFIX`, `JIRA_BASE_URL`, `JIRA_QA_ASSIGNEE_ACCOUNT_ID` (optional), `JIRA_QA_TRANSITION` (optional — no default).
2. Else if a `## Tracker` section exists with `TRACKER: linear` (future-proofing): treat as Linear and read Linear fields from `## Tracker` instead of `## Linear`.
3. Else if a `## Linear` section exists: set `TRACKER=linear`. Extract `Team` → `TICKET_PREFIX`, `Workspace` → `LINEAR_WORKSPACE`, `QA assignee ID` → `LINEAR_QA_ASSIGNEE_ID` (optional).
4. Else: set `TRACKER=none`.

**Dual-shape note:** Linear projects canonically store tracker config under `## Linear`; Jira projects use `## Tracker`. This is intentional — it preserves zero-migration compatibility for every existing Linear project that already has a `## Linear` section.

**Legacy `## Linear` shape guard** — if `TRACKER=linear` was resolved from a `## Linear` section AND the section is missing the `Workspace:` field (required for URL generation), stop immediately and print:

```
Your tracker config is missing fields /implement needs. Run /init-project to update it —
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
- `$REPO/CLAUDE.md` for conventions
- `$REPO/.claude/rules/decisions.md` for architectural decisions

Focus on understanding enough to make a solid plan - don't over-read.

---

## Phase 3: Architecture plan

Spawn an `architect` agent. Provide:
- The full ticket title and description
- The relevant code snippets you gathered
- The CLAUDE.md conventions
- Any architectural decisions from decisions.md that bear on this ticket

Ask the architect for:
1. A concrete implementation plan (what changes, in which files, in what order)
2. Which units of work can be done **in parallel** vs must be **sequential**
3. Any risks, gotchas, or ambiguities that need resolution before coding
4. The appropriate adversarial brief type for Skeptic review (security, logic, performance, data integrity, etc.)

Review the output. If anything conflicts with a known decision or feels off, resolve it before moving to implementation.

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
git -C $REPO checkout -b [BRANCH_NAME per CLAUDE.md convention] origin/$BASE_BRANCH
```

**Branch naming:** use the branch naming convention from CLAUDE.md.

Derive the short title from the ticket title: lowercase, hyphens, ~4-5 words max.

---

## Phase 5: Implement

Use the orchestration-planner's output to drive agent spawning decisions if Phase 3b produced a plan. If Phase 3b was skipped, use the architect's plan directly. When both are present, the orchestration-planner's output supersedes the architect's plan for agent spawning and parallelization decisions.

Read the orchestration-planner's output to make the routing determination below if Phase 3b ran; read the architect's output directly if Phase 3b was skipped.

### If work is a single logical unit (or units must be sequential):

Spawn one `engineer` agent per unit in sequence. Each agent prompt should include:
- "You are a Worker agent. Implement this specific task and return your complete output."
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

Spawn one `engineer` agent per worktree in the same message (parallel). Each agent works in its assigned worktree path and commits to its own sub-branch. Each agent's prompt should include the per-unit scope extracted from the plan: if Phase 3b ran, extract from the orchestration-planner's output for that unit; if Phase 3b was skipped, extract from the architect's plan for that unit.

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

---

## Phase 6: Skeptic review

Spawn a `skeptic` agent with:
- The adversarial brief type identified by the architect
- The full diff: `git -C $REPO diff origin/$BASE_BRANCH..HEAD`
- The ticket description as the success criteria
- The QA section from the ticket as acceptance tests

**Findings handling:**
- **Critical:** Route back to a fresh `engineer` agent to fix. Re-run Skeptic after.
- **Major:** Route back to engineer unless there's a strong reason to defer. Re-run Skeptic.
- **Minor:** Address inline or document as known limitation. No re-run needed.

---

## Phase 7: Quality gate

Run the full quality suite:

```bash
export NVM_DIR="$HOME/.nvm" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use 20
cd $REPO && $QUALITY_CMD
```

All checks must pass (typecheck, lint, tests, knip, jscpd). If any fail, spawn a fresh `engineer` agent with the failure output and instruct it to fix - do not suppress or skip checks. Re-run `$QUALITY_CMD` after the fix.

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
