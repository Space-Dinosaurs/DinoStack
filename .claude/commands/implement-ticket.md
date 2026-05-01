> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# Implement Ticket

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Take a ticket (Linear, Jira, or none) from description to merged PR, with full agent orchestration (Architect → Orchestration Planner (conditional) → Engineer → Skeptic) and the CI Test URL posted back to the ticket.

## Invocation

`/implement-ticket [TICKET_ID]`

---

## Resume check (before setup)

Before reading AGENTS.md or doing any setup, check for `.agentic/loop-state.json`:

**If the file exists and `status == "interrupted"`:**
- Print: "Interrupted loop detected on branch [branch] for ticket [ticket_id]."
- Print: "Last phase: [last_phase] / [last_phase_action], iteration [loop_state.iteration]/[loop_state.max_iterations]."
- Print: "Open findings: [count of findings_log entries with status=open or status=addressed]"
- Ask: "Resume this loop or start fresh? (resume / fresh)"
- If "fresh": delete the file. Proceed normally from Setup below.
- If "resume": apply wait strategy (see below), then jump to the resume entry point determined by `last_phase` / `last_phase_action` per the table below.

**If the file exists and `status == "active"` with `last_updated` more than 10 minutes ago:** treat as implicitly interrupted (the Stop hook may not have fired). Print: "Found an active loop state last written [elapsed] ago — treating as interrupted." Then follow the "interrupted" path above.

**If the file exists and `status == "complete"` or `"stalled"`:**
- Print: "A completed/stalled loop state file exists for ticket [ticket_id]. Clearing it."
- Delete the file. Proceed normally.

**If no file exists:** proceed normally.

**Wait strategy (applied before resuming when `interrupt_reason == "rate_limit"`):**
```
elapsed = now() - interrupted_at
if interrupt_reason == "rate_limit":
  if elapsed < 60 seconds:
    wait_remaining = 60 - elapsed
    print: "Rate limit detected. Waiting [wait_remaining]s before resuming."
    sleep(wait_remaining)
else:
  # session_expiry or unknown: no wait needed
  print: "Loop interrupted. Resuming from last checkpoint."
```

**Resume entry point table:**

| last_phase | last_phase_action | Resume action |
|---|---|---|
| skeptic | spawned | Re-spawn Skeptic with current diff (`git diff origin/$BASE_BRANCH..HEAD`). On iteration 2+, include prior-iteration findings block from `findings_log` (same as normal iteration 2+ behavior). |
| skeptic | returned | Skeptic output was received but Engineer fix pass was not yet spawned. Re-classify findings from `findings_log` (entries with status=open) and spawn the Engineer fix pass. |
| engineer | spawned | Check `git status --porcelain` on the branch. If clean: re-spawn Engineer with same open findings brief. If dirty (uncommitted changes): ask human "The Engineer had uncommitted changes. Discard and re-run, or commit what's there and re-run Skeptic?" |
| engineer | returned | Engineer returned but loop did not advance. Use `last_engineer_summary` from state file. Re-enter Skeptic spawn step. |
| qa | spawned | Re-spawn QA engineer with the prior brief. |
| qa | returned | QA engineer returned but loop did not advance. Re-spawn Engineer fix pass for QA failures. |
| quality_gate | engineer_spawned | Check `git status --porcelain`. If clean: re-spawn Phase 7 engineer with quality gate failure output from `loop_state.last_engineer_summary`. If dirty: ask human (discard and re-run, or commit and re-run `$QUALITY_CMD`). |
| quality_gate | engineer_returned | Phase 7 engineer committed. Re-run `$QUALITY_CMD` only. |
| quality_gate | rerun_pending | Re-run `$QUALITY_CMD` only. |

**After resuming:** always run `git -C $REPO diff origin/$BASE_BRANCH..HEAD` to confirm branch state before re-spawning agents. If the diff is empty and open findings exist, the Engineer's prior work was lost (uncommitted at interruption); flag this to the human before resuming.

**Parse failure:** if `.agentic/loop-state.json` exists but cannot be parsed as JSON, print a warning, offer to delete the file and start fresh. Do not silently ignore it.

**Concurrent session guard:** if `status == "active"` and `last_updated` was within the last 10 minutes, print a warning ("A session appears to be actively writing this loop state. Are you sure you want to resume here?") and require explicit confirmation before proceeding.

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

## Phase 0b: Brief check

Before any architect spawn, check for an existing Brief.

**Slug derivation:** convert the ticket title to kebab-case and strip any ticket-ID prefix
(e.g. `AE-123 Add user login` becomes `add-user-login`).

**Check (either condition satisfies):**
1. A file exists at `docs/planning/<slug>.md`, OR
2. `.agentic/brief-session.json` exists with `status: complete` AND `brief_path` matching
   the ticket slug.

**If found:**
- Set `brief_path = docs/planning/<slug>.md` in the architect execution contract (Phase 3).
- At the promotion gate in Phase 3b: skip the conductor-authored Brief step - the Brief is
  pre-existing and operator-confirmed.
- Pass `brief_source: operator` to the Skeptic-on-Brief gate; use the operator-confirmed
  Skeptic variant (completeness-only review per `content/commands/brief.md` Section 6).

**If not found:** proceed normally. The promotion gate in Phase 3b determines whether a
Brief is required based on the unit count from the orchestration-planner.

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

**Architect plan Skeptic review (mandatory):** After the Architect returns its plan, spawn a Skeptic with the "Document synthesis, architecture, and planning" adversarial brief. Do not proceed to Phase 3b or Phase 4 until the Skeptic grants sign-off. If the Skeptic-approved plan contains a non-empty "Open questions" section, resolve every open question before proceeding - see `METHODOLOGY.md` for resolution paths. For the full adversarial brief menu, see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

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

### Task-state initialization (multi-unit only)

**Single-unit threshold:** If the orchestration plan identifies only 1 task, skip this step entirely. Task-state initialization is only warranted for plans with 2 or more tasks. For single-unit plans, the conductor operates as today (in-context state only).

After receiving the orchestration-planner's output and before Phase 4, initialize the task-state file:

```bash
mkdir -p .agentic && [ -f .agentic/tasks.jsonl ] || touch .agentic/tasks.jsonl
```

Also add `.agentic/` to the project's `.gitignore` if not already present.

**Generate identifiers (once per conductor session):**
- `session_id`: `<ISO-date>-<4hex>`, e.g. `20260415-a3f2`
- `task_id` per task: `<ticket_id>-<unit_slug>` (e.g. `ENG-42-auth-middleware`), or `<session_id>-<unit_slug>` for null-ticket projects

**Read the orchestration-planner's structured JSONL block** (the `## Task entries (machine-readable)` section at the end of the plan output). For each entry in that block, append a `pending` entry to `.agentic/tasks.jsonl`. Write tasks in dependency order - independent tasks (empty `depends_on`) first, dependent tasks after. Each entry must include the fields from the schema: `task_id`, `session_id`, `ticket_id`, `unit_slug`, `status: pending`, `depends_on`, `created_at`, `updated_at`, and the full `inputs` object (`description`, `acceptance_criteria`, `files_in_scope`, `quality_cmd`, `repo_path`, `base_branch`).

Emit breadcrumb: `[phase: task-state-init | N tasks written]`

**ALL writes to `.agentic/tasks.jsonl` are conductor-only.** Workers do not read or write the task file. Workers return their summaries to the conductor in the normal return path; the conductor extracts results and writes all updates. No lock protocol is needed because the conductor is the sole writer.

**File-absent vs file-present behavior:**

- **File absent:** Fresh start. Create the file and append `pending` entries as described above.
- **File present, same `session_id`:** Continuation within the same session (e.g., a prior worker returned BLOCKED and the human provided direction). Build the in-memory index using the field-level merge algorithm (see Worker behavior in the P1 design), determine which tasks are pending/in-progress/done, and proceed accordingly.
- **File present, different `session_id`, with `in_progress` or `blocked` entries:** Orphaned tasks from a dead session. Log: "Found `.agentic/tasks.jsonl` with N orphaned tasks from a prior session." Surface the task list to the human with their last-known status and `updated_at` timestamp. Ask: "Do you want to resume from this state, or start fresh? (resume/restart)". On **restart**: rename the existing file to `.agentic/tasks.jsonl.YYYYMMDD-HHMMSS.bak`, create a new file, and proceed as fresh start. On **resume**: automatic resume is not yet implemented (P2). Display the last-known state of each task and say: "Automatic resume is not yet implemented. Here is the last-known state of each task: [table]. You can manually direct re-spawns for any in-progress tasks."
- **File present, different `session_id`, all terminal (`done`, `failed`, `abandoned`):** Historical records from a prior implementation. Append new entries for the current session without disturbing existing ones.

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

**Module manifests:** Files modified must carry module manifests per `~/agentic-engineering/.claude/skills/agentic-engineering/rules/module-manifest.md` when non-trivial. Skeptic enforcement is tiered in Phase 6: missing manifests are flagged as Minor (does not block sign-off), stale manifests as Major (blocks sign-off absent a compelling documented reason to defer), and stale manifests whose inaccuracy could mislead a caller on a correctness or security path as Critical. When modifying an existing manifested file, update the manifest in the same change if purpose, public API, upstream dependencies, downstream consumers, or failure/retry semantics shift.

### If work is a single logical unit (or units must be sequential):

Spawn one `engineer` agent per unit in sequence. Each agent prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, filling in fields from the architect's plan / orchestration-planner output for this unit
- The plan for this unit: if Phase 3b ran, use the orchestration-planner's output for this unit; if Phase 3b was skipped, use the architect's plan for this unit
- The branch name to work on
- The repo path: `$REPO`
- Instruction to run `$QUALITY_CMD` from the repo root before finishing and fix any errors

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Task-state reads (multi-unit only, when `.agentic/tasks.jsonl` is in use):**

Before spawning each worker: check the task's `depends_on` field in the file. All dependency `task_id`s must have `status: done` before this task can start. Update the task entry from `pending` -> `in_progress` immediately before spawning. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path if using worktree isolation, null otherwise), and `branch_name` (the branch the worker will operate on).

After each worker returns: read the return summary, extract `worker_summary`, `commit_sha`, `files_modified`, and `quality_gate_passed`. Write an update entry to `.agentic/tasks.jsonl` with these output fields. Status remains `in_progress` until Skeptic sign-off or final determination.

After the Skeptic/QA loop resolves: update the task entry to its terminal status (`done`, `failed`, `blocked`, or `abandoned`) and populate the `loop_state` field from the P0 LOOP_STATE object. Include `outputs.skeptic_status` and `outputs.skeptic_findings_count` from the completed Skeptic review (or `skipped`/null if Skeptic was not required).

### If parallel independent units were identified:

**N=1 degenerate case:** If the orchestration-planner returned exactly 1 unit, do NOT invoke the fan-out primitive. Fall through to the standard single-engineer path above.

Use git worktrees to give each engineer an isolated copy. The orchestration-planner's JSONL block provides `unit_slug`, `merge_order`, and `skeptic_strategy` for each unit - read these fields to drive worktree naming, merge ordering, and Skeptic strategy. Before creating worktrees, prune stale state from any prior fan-out:

```bash
# Prune stale worktree metadata and remove any leftover sub-branches from prior runs:
git -C $REPO worktree prune
# If any ${FEATURE_BRANCH}-${unit_slug} branches exist from a prior run, delete them before proceeding.
```

Create one worktree per unit, each rooted from `BASE_BRANCH` (loop over all N units from the planner's JSONL block in `merge_order` sequence):

```bash
# For each unit (unit_slug from planner JSONL block):
git -C $REPO worktree add ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} \
  -b ${FEATURE_BRANCH}-${unit_slug} origin/$BASE_BRANCH
```

**Task-state reads (when `.agentic/tasks.jsonl` is in use):** Before spawning, verify all `depends_on` task_ids are `done` in the file and update each task entry from `pending` -> `in_progress`. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path of the unit's worktree), and `branch_name` (the unit's sub-branch `${FEATURE_BRANCH}-${unit_slug}`).

Spawn one `engineer` agent per worktree in a single message (parallel, background). Each engineer works in its assigned worktree path and commits to its own sub-branch. Each agent's prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, with fields filled in from the per-unit scope in the planner's JSONL block
- The unit's `task_id`, acceptance criteria, `files_in_scope`, `quality_cmd`, and worktree path
- The per-unit scope: extracted from the orchestration-planner's JSONL block for that unit

**Join condition.** The conductor spawns all N engineers in a single message and waits for all N to return. After all N engineers return, evaluate the join:

- **All-done join:** all N units reach `status: done` (Skeptic signed off per P0 loop where applicable). Proceed to merge phase.
- **Partial success:** one or more units reach `status: failed` or `status: blocked`, and one or more reach `status: done`. Do NOT merge any branch. Apply partial success path (see below).
- **Total failure:** all units failed or blocked. Clean up all worktrees, escalate to human with the orchestration-planner's original plan and all failure outputs. Recommend sequential implementation as fallback.
- **Blocked:** any unit with `status: blocked` is treated as failed for join evaluation. A worker returns `Status: BLOCKED` when it encounters a scope conflict, design ambiguity, or permission issue requiring human input.

**Join timeout.** The join phase has a 30-minute total deadline. If the deadline elapses before all engineers have returned, units with no completion entry are treated as timed out (failed) and handled via the partial success path. Units that completed `status: done` before the deadline are still eligible for merge.

**Fallback: no task-state file.** If `.agentic/tasks.jsonl` is not in use, derive status from each engineer's return value. Each engineer's return must include a structured status line as the first line: `Status: DONE`, `Status: DONE_WITH_CONCERNS`, or `Status: BLOCKED`. The engineer brief must explicitly require this structured first line.

After all engineers return, update task-state output fields for each unit: write `worker_summary`, `commit_sha`, `files_modified`, and `quality_gate_passed` to each task's entry. Status remains `in_progress` until Skeptic sign-off or final determination.

**Partial success path.** When one or more units fail and one or more succeed:
1. Record which units are `done` vs `failed`/`blocked`.
2. If done units are truly independent (no shared interface with failed units): merge done units into `FEATURE_BRANCH` sequentially in `merge_order`. Leave failed units' worktrees in place.
3. Spawn a retry engineer for each failed unit, pointing it at the preserved worktree and the failure detail. The retry brief must include: (a) the original task brief from the task-state `inputs` field, (b) the failure detail from `outputs.worker_summary` and `outputs.quality_gate_passed`, (c) the preserved worktree path, (d) any partial commits in the worktree, and (e) explicit instruction that this is a re-run, not a fresh start.
4. If the retry succeeds, merge and proceed to the Skeptic phase.
5. If the retry fails a second time, escalate to human with the full failure history.
6. Maximum retry depth: 1 automatic retry per unit.

**Per-unit Skeptic spawning (when `SKEPTIC_STRATEGY: per-unit`).** After each unit's engineer returns `done`, spawn a Skeptic for that unit's diff (unit worktree diff against `BASE_BRANCH`). Per-unit Skeptics for independent units can be spawned in parallel (single message - they are reviewing non-overlapping diffs). Each unit's Skeptic integrates with the P0 persistence loop (Engineer -> Skeptic -> fix loop within the unit's worktree). A unit is `status: done` only after its Skeptic signs off, not after the engineer's first commit. After each unit's Skeptic/QA loop resolves, update the task entry to terminal status and populate `loop_state`, `outputs.skeptic_status`, and `outputs.skeptic_findings_count`.

**Integration Skeptic (when `SKEPTIC_STRATEGY: integration`).** Do NOT spawn per-unit Skeptics. After all units' engineers return done, merge all unit branches onto a scratch integration branch (not `FEATURE_BRANCH` - the merge is provisional until the Skeptic signs off). Spawn one integration Skeptic reviewing the combined diff from `BASE_BRANCH` to the scratch integration branch. The integration Skeptic IS the Phase 6 gate for this strategy (see Phase 6 guard below). The orchestration-planner's independence annotation (added when the planner classified units) becomes the adversarial brief hint: pass it to the integration Skeptic so it knows the expected interaction boundaries.

**Merge phase (all-done join).** After all units are done (Skeptics signed off for `per-unit`, or after integration merge for `integration`), merge unit sub-branches into `FEATURE_BRANCH` sequentially in `merge_order`:

```bash
git -C $REPO checkout $FEATURE_BRANCH

# For each unit in merge_order sequence:
git -C $REPO merge --no-ff ${FEATURE_BRANCH}-${unit_slug}

# After each merge, check for conflicts before continuing:
# git -C $REPO diff --name-only --diff-filter=U
# If that command outputs any file names, conflicts are present - apply N>2 conflict recovery below.
```

**N>2 conflict recovery.** On merge conflict at any step:
1. `git -C $REPO merge --abort`
2. Do not attempt remaining merges.
3. Collect conflict files, all units' diffs, and the orchestration-planner output.
4. Spawn a single engineer with a conflict-resolution brief: all units' complete changes, the conflict markers, and explicit instruction to implement all units sequentially in a single worktree targeting `FEATURE_BRANCH`.
5. The sequential re-implementation engineer inherits a single-Skeptic review obligation (one Skeptic over combined diff, since units are now interdependent by fact of their conflict).
6. The conflict re-route counts as iteration 1 of the Phase 6 loop (do not double-count).

**Branch verification before merge.** Before merging each unit's branch, verify the worktree is on the expected branch:

```bash
# Confirm branch matches expected sub-branch before merging:
# git -C ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} rev-parse --abbrev-ref HEAD
# If the branch name does not match ${FEATURE_BRANCH}-${unit_slug}, abort that unit's merge and escalate.
```

**Post-merge integration quality check.** After all N merges complete cleanly on `FEATURE_BRANCH`, run `$QUALITY_CMD` from `FEATURE_BRANCH` root. If the integration check fails, spawn one engineer on `FEATURE_BRANCH` with the integration failure output. This engineer has full context (all units' work is on the branch). The resulting fix goes through a single Skeptic on the incremental diff before Phase 5 is declared complete. The integration fix Skeptic does NOT replace Phase 6.

**Worktree cleanup.** After all merges succeed (or after escalation, to prevent stale worktree accumulation):

```bash
# For each unit:
git -C $REPO worktree remove ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} --force
git -C $REPO branch -d ${FEATURE_BRANCH}-${unit_slug}
git -C $REPO worktree prune
```

For full worktree cleanup rules (isolation worktrees, feature worktrees, stale branch pruning), see `METHODOLOGY.md §Worktree Lifecycle`.

**Merge-conflict re-route and loop iteration:** If a merge conflict re-route occurred above and the re-routed Engineer's output then goes through Skeptic review in Phase 6, the conflict re-route counts as iteration 1 of the Phase 6 loop. Do not double-count: the conflict-resolution Engineer pass is the first fix pass; Phase 6 initializes its `iteration` counter at 1 to reflect this.

---

## Phase 6: Skeptic review

**Phase 6 guard (fan-out integration Skeptic).** When fan-out was active in Phase 5 and `SKEPTIC_STRATEGY: integration`, the integration Skeptic that reviewed the combined diff in Phase 5 IS the Phase 6 gate. Do not spawn a second Skeptic - Phase 6 is complete when the integration Skeptic signs off. When `SKEPTIC_STRATEGY: per-unit`, Phase 6 fires as normal - a Skeptic reviews the combined diff from `BASE_BRANCH` after all merges (`git -C $REPO diff origin/$BASE_BRANCH..HEAD`). This is a full-picture review that catches cross-unit interactions the per-unit Skeptics could not see (emergent behaviors, combined diff scope). Phase 6 is NOT skipped for the `per-unit` strategy.

Spawn a `skeptic` agent with:
- The adversarial brief type identified by the architect
- The full diff: `git -C $REPO diff origin/$BASE_BRANCH..HEAD`
- The ticket description as the success criteria
- The QA section from the ticket as acceptance tests

For the full adversarial brief menu (security, logic, performance, data integrity, etc.), see `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

**Tier:** Declare a tier if this spawn warrants non-default model selection (see Tier declaration in METHODOLOGY.md). Default is Tier 2 (omit the model param).

**Findings handling - loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (create `.agentic/` directory if absent). **Use atomic write: write to `.agentic/loop-state.json.tmp` first, then rename to `.agentic/loop-state.json`.**

**Full P2 schema (extends the P0 in-context schema with cross-session resume fields):**

```json
{
  "schema_version": 1,
  "ticket_id": "<string | null>",
  "branch": "<string>",
  "repo": "<string>",
  "base_branch": "<string>",
  "status": "active",
  "interrupted_at": null,
  "interrupt_reason": null,
  "last_phase": "skeptic",
  "last_phase_action": "spawned",
  "loop_state": {
    "phase": "skeptic",
    "iteration": 1,
    "max_iterations": 3,
    "findings_log": [],
    "qa_failures_log": [],
    "last_engineer_summary": null,
    "termination_reason": null
  }
}
```

**Field notes:**
- `last_phase` is the **authoritative resume key** - used exclusively for resume entry selection. Do NOT use `loop_state.phase` for this.
- `loop_state.phase` reflects which loop is active (skeptic or qa) and is used only to reconstruct in-context LOOP_STATE on resume.
- `last_engineer_summary` must be written verbatim to disk when an Engineer returns, capped at 2000 characters if longer. This allows resume to reconstruct the brief for the next Skeptic spawn.
- `status` values: `"active"` (loop running), `"interrupted"` (Stop hook or crash), `"complete"` (loop exited cleanly), `"stalled"` (cap_reached/convergence_failure/blocked escalation).

**Write triggers for Phase 6 Skeptic loop (overwrite using atomic write at each transition):**
- At loop initialization (before first Skeptic spawn): `last_phase=skeptic`, `last_phase_action=spawned`
- After Skeptic returns, before Engineer spawn: `last_phase=skeptic`, `last_phase_action=returned`
- After Engineer spawned (fix pass): `last_phase=engineer`, `last_phase_action=spawned`
- After Engineer returns: `last_phase=engineer`, `last_phase_action=returned`; update `loop_state.last_engineer_summary` (verbatim, capped 2000 chars)
- After each `findings_log` update (Steps 2, 3, 5): overwrite with updated `loop_state`
- On clean termination: set `status=complete`, `loop_state.termination_reason=clean`
- On stalled termination (cap_reached, convergence_failure, blocked): set `status=stalled`

**Stability contract:** `.agentic/loop-state.json` is a stable contract from P0 onward. Any schema change must consider resume readers.

The file is overwritten (not appended) on each iteration state update and at loop exit with `termination_reason` set. It is not deleted on clean termination - the final state is the post-mortem record until the next loop invocation overwrites it. Whether `.agentic/` is gitignored is deferred to project convention.

Emit the inline breadcrumb:

```
[loop: skeptic | iteration 1/3 | open findings: -]
```

**Loop entry (repeat until termination):**

**Step 1.** Spawn `skeptic` with adversarial brief. On iteration 2+, prepend the "Prior iteration findings" block to the brief (see `skeptic-protocol.md` Section 4 - findings_log entries map directly to the preflight list format). Format re-invocations (up to 3 per `skeptic-protocol.md` Section 11) do NOT increment `iteration`.

**Telemetry emit (V1):** Bracket the Skeptic Task tool call with:
```
agentic-emit spawn_start skeptic - '{"tier":<tier>,"tool_use_id":"<toolu_id_if_known_else_null>"}'
# ... Task tool call ...
# After return, parse subagent transcript for tokens/wall_seconds:
USAGE="$(agentic-parse-subagent-usage <session_uuid> <agent_id>)"
agentic-emit spawn_complete skeptic - "$(printf '{"tier":<tier>,"agent_id":"<agent_id>","status":"ok",%s}' "${USAGE#\{}")"
```
See `METHODOLOGY.md §Events log` for the full event schema.

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

**Meta-divergence surfacing (in-session scan).** Before each turn boundary entering Phase 6 (loop initialization) and after returning from a Worker (after Step 5), the conductor scans `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For any event with non-empty `data.divergence.critical_missed` or `data.divergence.major_missed`, emit a META-DIVERGENCE line at the next user-facing turn boundary and append `original_task_id` to the tracker file:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Tracker append is a single line per `original_task_id`; the file is created if absent (`.agentic/.meta-divergence-surfaced`, gitignored under the `.agentic/` umbrella). Minor-only divergences are NOT surfaced inline. See `content/references/skeptic-protocol.md` Section 14 for the full specification.

**Step 3. Termination check:**
- If no Critical or Major findings: auto-close all `findings_log` entries with `status: open` or `status: addressed` (set to `closed`). Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. **Then run "Calibration emit + meta-Skeptic sampling" below before exiting the loop.** Exit loop cleanly. Proceed to Phase 6b.
- If `iteration == max_iterations` AND Critical or Major findings remain: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human (see Escalation section below). Phase 6b does NOT run.
- If any Critical finding carries `re_raised: true` (same finding re-raised after a claimed fix): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human. (This overrides the 2-re-route rule in `skeptic-protocol.md` Section 5 - see that section for the override note. One re-raise after a claimed fix is sufficient within the loop.)

**Calibration emit + meta-Skeptic sampling (clean exit only).** When Step 3 takes the clean-exit branch (sign-off granted), the conductor performs the following before declaring the unit complete:

1. **Build the calibration data block.** Compute `diff_lines` from the reviewed diff (`git -C $REPO diff origin/$BASE_BRANCH..HEAD | wc -l`, or the unit-scoped equivalent for fan-out). Tally `findings_count` from the final Skeptic round's findings list (Critical / Major / Minor counts). Read `iteration` from the loop state.

2. **Emit the extended `spawn_complete` event.** Construct the merged JSON inline (no `bin/agentic-emit` flag changes) and call:

   ```bash
   USAGE_AND_CALIBRATION='{"tier":<tier>,"agent_id":"<agent_id>","status":"ok","wall_seconds":<n>,"tokens":{...},"findings_count":{"critical":<c>,"major":<m>,"minor":<n>},"diff_lines":<d>,"signed_off":true,"iteration":<i>,"meta_review":null}'
   agentic-emit spawn_complete skeptic <task_id> "$USAGE_AND_CALIBRATION"
   ```

   The conductor builds the JSON by merging the existing usage fields (from `agentic-parse-subagent-usage`) with the calibration fields. `bin/agentic-emit` is unchanged.

3. **Compute the deterministic sampling bucket.** Hash `<task_id><iteration>` into a uniform 0-99 bucket (`python3 -c 'import hashlib,sys; print(int(hashlib.sha256(sys.argv[1].encode()).hexdigest(),16) % 100)' "<task_id><iteration>"`). If `bucket < 5`, the spawn is sampled.

4. **If sampled, spawn meta-Skeptic in background (fire-and-forget).** Do NOT wait for return. The conductor declares the unit complete and proceeds to Phase 6b without blocking. Meta-Skeptic spawn brief includes:
   - The original diff
   - The original Skeptic's findings list verbatim
   - The original Skeptic's sign-off statement verbatim
   - The original adversarial brief
   - Instruction to produce a divergence report as TEXT in the return summary (Critical missed / Major missed / Minor missed / Agreement). Meta-Skeptic does NOT write to `.agentic/`.

5. **On meta-Skeptic return (asynchronous).** When meta-Skeptic eventually returns its textual divergence report, the conductor parses the report, constructs the `meta_review_complete` payload, and emits:

   ```bash
   META_DATA='{"original_task_id":"<id>","divergence":{"critical_missed":[...],"major_missed":[...],"minor_missed":[...]},"agreement":<bool>}'
   agentic-emit meta_review_complete skeptic-meta <original_task_id> "$META_DATA"
   ```

   The next in-session scan or session-start sweep will surface any Critical/Major divergence per the Meta-divergence surfacing block above.

See `content/references/skeptic-protocol.md` Section 14 for the full calibration specification.

**Step 4. Engineer fix pass.** Spawn a fresh `engineer` agent with:
- The open Critical and Major findings from `findings_log` (status=open)
- The `last_engineer_summary` from the prior iteration
- Instruction: "Address only the findings listed below. Do not expand scope. Do not refactor, rename, or clean up code outside the finding scope. For each finding, confirm in your summary what you changed and why it addresses the finding."
- The branch name and repo path
- Instruction to run `$QUALITY_CMD` before finishing

**Telemetry emit (V1):** Bracket the Engineer Task tool call with `agentic-emit spawn_start engineer <task_id> ...` before, and `agentic-emit spawn_complete engineer <task_id> ...` after - using `agentic-parse-subagent-usage` to populate tokens/model/wall_seconds. Same pattern as the Skeptic emit in Step 1.

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

**Trigger:** qa.md exists at either resolver path (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback) AND has a `## QA triggers` section AND the diff matches at least one trigger pattern.

- **If not triggered:** skip directly to Phase 7.
- **If triggered - UI-visible changes (concurrent path):** when trigger patterns match a UI-visible diff, `qa-engineer` was already spawned IN PARALLEL with the Skeptic during Phase 6 (single message, both background). If QA passed concurrently, Phase 6b is already satisfied - skip to Phase 7. If QA failed concurrently or was deferred, proceed with the QA loop contract below. See `content/sections/05-qa-gate.md` for the full concurrent QA spec.
- **If triggered - non-UI changes (sequential path):** proceed with the QA loop contract below.

For full QA gate rules, see `METHODOLOGY.md §QA Gate`.

**QA loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state.json` (overwriting the Phase 6 state). **Use atomic write (tmp+rename).** Reset `last_phase=qa`, `last_phase_action=spawned`. Same write-trigger pattern as Phase 6 applies here: write at every phase transition (QA spawn, QA return, Engineer spawn, Engineer return). On clean exit set `status=complete`; on stalled exit set `status=stalled`.

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

**Step 1.** Spawn `qa-engineer` with ticket context, diff, and the resolved qa.md config (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). On iteration 2+, prepend the "Prior QA failures" section to the brief:

**Telemetry emit (V1):** Bracket the QA Task tool call with `agentic-emit spawn_start qa-engineer <task_id> ...` before and `agentic-emit spawn_complete qa-engineer <task_id> ...` after. Same pattern as Phase 6 emits.

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
- If PASS (all acceptance criteria met): auto-close all `qa_failures_log` entries. Set `termination_reason: clean`. Overwrite `.agentic/loop-state.json`. Exit loop cleanly. Proceed to Phase 7.
- If `iteration == max_iterations` AND still failing: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state.json`. Escalate to human with the `qa_failures_log`. Phase 7 does NOT run.
- If same failure recurs unchanged after a claimed fix (`re_raised: true`): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state.json`. Escalate to human with convergence note.

**Step 4. Engineer fix pass.** Spawn `engineer` with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. Bracket the Task call with `agentic-emit spawn_start engineer <task_id> ...` and `agentic-emit spawn_complete engineer <task_id> ...` per the Phase 6 emit pattern. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6:
- If `Status: BLOCKED`: set `termination_reason: blocked`. Escalate immediately. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply context and re-spawn without incrementing `iteration`. If context cannot be supplied, escalate to human.

**Step 5.** Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT (whether `Status: DONE` or `Status: DONE_WITH_CONCERNS`): update `qa_failures_log` entries the Engineer claims to have fixed to `status: addressed`. Update `last_engineer_summary`. Increment `iteration`. Overwrite `.agentic/loop-state.json`. Update inline breadcrumb. Go to Step 1.

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

1. Before spawning the Phase 7 engineer: write `.agentic/loop-state.json` with `last_phase=quality_gate`, `last_phase_action=engineer_spawned` (atomic write).
2. Spawn one `engineer` fix pass scoped to the quality gate failure output. The Skeptic has already signed off on the implementation - this is a targeted quality gate fix, not a Skeptic-loop re-entry.
3. After the engineer returns and commits: write `last_phase=quality_gate`, `last_phase_action=engineer_returned` (atomic write).
4. Before re-running `$QUALITY_CMD`: write `last_phase=quality_gate`, `last_phase_action=rerun_pending` (atomic write).
5. Re-run `$QUALITY_CMD`.
6. If it passes: set `status=complete` in loop-state.json. Proceed to Phase 8.
7. If it still fails: set `status=stalled`. Escalate to the human. Include the quality gate output from both the first run and the post-fix re-run. Do not spawn another Engineer pass.

**No unbounded loop:** Phase 7 failure only ever triggers one Engineer fix pass followed by one re-run. There is no retry loop at this phase.

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

---

## Phase 12: Loop state cleanup

After the PR is open (Phase 9 complete), set `.agentic/loop-state.json` to `status: "complete"` using atomic write (tmp+rename), or delete the file. This prevents the next `/implement-ticket` invocation on this project from presenting a stale completed loop as a resume candidate.

If the file does not exist (it was never written, e.g. loop never started), skip silently.
