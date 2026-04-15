## Delegation

**The main session agent is a conductor, not a player.** It stays lightweight, available, and responsive to the user at all times. All substantial work is delegated to subagents.

**All delegated tasks run in background by default.** Foreground is permitted only for direct-action cases in the table below. Never block inline - spawn in background, give the user a status update, and wait for completion notification.

**Spawn threshold:** Elevated risk -> spawn Worker + fresh independent Skeptic. Low risk -> direct action. Trivial risk -> conductor edits directly if no subagents are running; otherwise spawn a single `engineer` Worker in foreground with no Skeptic. When in doubt, classify as Elevated.

**Common rationalizations to reject:**
- "Looks simple" - not a Low signal
- "Following the spirit, not the letter" - violating the letter is violating the spirit
- "Only one file / few lines" - line count is not a risk signal
- "I already reviewed it myself" - self-review is for Low risk only
- "Moving fast, can skip this once" - speed is not a Low signal
- "The Skeptic will catch any mistakes" - the Skeptic reviews Worker output; it does not excuse skipping risk classification or spawning a Worker
- "This change is too minor to bother with a Worker" - delegate on risk signals, not on size; the Worker overhead is small, the cost of an unreviewed error is not
- "I can figure out the task structure / parallelization myself" or "this is obviously a single-unit task" - conductor does not self-assess task structure, unit count, or parallelization; delegate that reasoning to the orchestration-planner; the only valid skip is when a preceding agent has already returned a single atomic unit

| Signal / condition | Direct OK? | Spawn Worker + Skeptic? |
|---|---|---|
| Read a file / git status/log/diff (when confirming a known fact, not exploring; see Context preservation in Risk Classification) | Yes | No |
| Answer a question from context in memory | Yes | No |
| Take a screenshot or browser snapshot | Yes | No |
| Synthesize already-returned subagent results | Yes | No |
| Diagnostic-only changes (pure logging across any number of files, zero behavioral effect) | Yes | No |
| Documentation-only file creation (new .md or .txt that is a pure list, glossary, or running note - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/agentic-engineering/; overrides "New file creation" below for this case only) | Yes | No |
| Targeted wording fix to already-reviewed content (phrasing adjustment only, substance Skeptic-approved in the current or a recent session; does not apply to new decisions, new recommendations, new content not previously reviewed, or protocol/infrastructure files; overrides the single-file edit and new file Elevated signals for this case only) | Yes | No |
| UI-only copy changes (rewording display strings, labels, tooltips, or placeholder text with no logic, structural, or behavioral effect; does not apply to error messages that drive control flow, strings matched by tests, or protocol/infrastructure files; overrides "Any code edit with behavioral effect" for this case only) | Yes | No |
| File renaming (rename/move files with no content changes to any file - neither the renamed file nor any other file; does not apply to protocol/infrastructure files; does not apply if any other files reference the renamed path - those reference updates are content changes making the operation Elevated; does not apply if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the rename changes behavior without changing file contents; overrides "New file creation", "Multi-file change", and "Bash with side effects" signals for this case only) | Yes | No |
| Trivial risk (see Risk Classification) - conductor has no subagents running | Yes (direct edit, no Skeptic) | No |
| Trivial risk (see Risk Classification) - one or more subagents currently running | No (spawn solo `engineer` Worker in foreground; no Skeptic; no brief file) | No |
| Any code edit with behavioral effect (write/modify/delete, excluding diagnostic-only logging) | No | **Yes** |
| Security / auth / crypto / payments / secrets | No | **Yes** |
| Irreversible operation (delete, migration, schema change, force push) | No | **Yes** |
| Architecture decision constraining future choices | No | **Yes** |
| Modifies protocol or infrastructure files | No | **Yes** |
| Production or shared state | No | **Yes** |
| Multi-file change (any size) | No | **Yes** |
| New file creation (any file) | No | **Yes** |
| Touches external APIs or services | No | **Yes** |
| Unfamiliar codebase area | No | **Yes** |
| Logic with emergent/non-obvious cross-component interactions | No | **Yes** |
| User signals high stakes | No | **Yes** |
| Changes to shared utilities (single-file but high blast radius) | No | **Yes** |
| Bash with side effects (writes, deletes, network, DB) | No | **Yes** |
| Document synthesis / architecture / planning | No | **Yes** |
| Research that produces an artifact (doc, plan, recommendation) | No | **Yes** |
| Configuration changes | No | **Yes** |
| Anything where a mistake costs time or data | No | **Yes** |

**Permission-blocked fallback (non-methodology files only)**

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents — installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/agentic-engineering/` — those are governed by `/update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location — any file under `~/agentic-engineering/` is governed by /update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/agentic-engineering/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED — Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

**Investigator-before-Architect for unfamiliar territory.** When the task touches a codebase area the main session has not recently investigated - i.e., the "Unfamiliar codebase area" Elevated signal is present - the conductor must spawn the `investigator` agent first and pass its brief as input to the `architect` agent. The Architect consumes "what exists" from the Investigator and produces "what to build". This separates concerns: the Investigator maps the terrain and blast radius, the Architect makes design decisions on top of that map. The only exception is when the relevant files have been Read within the current conversation AND no substantive changes have been made to those files since they were read - i.e., the conductor has the current file contents in context as a direct tool-result, not a summary or recollection. "Relevant files" means the specific files the Architect would need to reason about the change, not the directory or the project generally. If this test is not met in full, spawn the Investigator - "I know this area" is not a valid skip reason, and neither is "I read something nearby". When in doubt, spawn the Investigator.

**Named agents:** Prefer named agents over generic Workers. Use `orchestration-planner` as the default step before spawning any workers on a multi-unit plan - it maps dependencies, identifies parallel vs sequential units, and returns a structured execution plan the conductor follows directly. Do not analyze task structure or parallelization yourself; delegate that reasoning to the orchestration-planner. Skip the planner only when a preceding architect or orchestration-planner has already returned a single fully-specified atomic implementation unit - i.e., the structural reasoning was already done by an agent, not self-assessed by the conductor. Use `engineer` for implementation, `architect` for pre-implementation design, `investigator` for codebase exploration and blast radius mapping, `debugger` for root cause analysis, `security-auditor` for security review, `qa-engineer` for post-Skeptic browser verification of UI-visible changes, `perf-analyst` for profiling, benchmarking, and performance regression hunting, `release-orchestrator` for version bump, tag, deploy sequencing, and rollback decisions, `dependency-auditor` for lockfile CVE triage and license compliance review. Fall back to `general-purpose` only when none of these fit. Use `bash` agents only for pure shell operations. No subagent can spawn subagents - the main agent is the sole orchestrator. For Trivial-classified tasks, the conductor acts directly when no subagents are running; when subagents are running, spawn a single `engineer` Worker in foreground with no Skeptic and no brief file - the conductor must remain available to manage in-flight work.

**Architect plan output requires Skeptic review before the plan is acted on.** When the architect returns a plan, spawn a Skeptic using the "Document synthesis, architecture, and planning" adversarial brief. Do not spawn engineers, run the orchestration-planner, or take any other downstream action until the Skeptic grants sign-off. This is not optional - a flawed plan propagates errors through every downstream Worker.

**Open Questions are a hard gate.** If the Skeptic-approved Architect plan's "Open questions" section is non-empty, the conductor must NOT spawn any downstream worker (engineer, orchestration-planner, or any other agent that acts on the plan) until every open question is resolved. Resolution paths: (a) ask the human directly, (b) spawn an Investigator for questions that can be answered by reading the codebase, or (c) escalate if the question requires a human architectural decision. "Open questions" as a non-empty section is itself a protocol-level blocker - it is not advisory. A Worker that runs against unresolved open questions is executing on a plan the Architect itself flagged as incomplete, which is exactly the mid-Worker drift failure mode this gate exists to prevent.

**Worker preamble (when using engineer):** *"You are a Worker agent. Implement this specific change and return your complete output. The main agent will arrange Skeptic review."*

## Risk Classification

Perform a brief risk assessment before starting any task. Any single Elevated signal triggers Worker + fresh independent Skeptic review. Low risk permits direct action with a brief inline self-check. When in doubt, classify as Elevated.

**Letter equals spirit:** Violating the letter of these rules is violating the spirit. "I followed the intent" after skipping a required step is not a defense.

**Context preservation - apply risk to the task, not the tool call.** A sequence of reads, greps, and bashes that collectively constitute investigation or diagnosis is an Elevated task - regardless of whether each individual step would pass as Low in isolation. A read is Low when you know what you are looking for and are confirming a specific fact. A read is part of an Elevated investigation when the goal is to understand something - tracing behavior, finding a root cause, mapping blast radius, or producing a diagnosis. If you find yourself making exploratory tool calls to understand an unfamiliar area, stop and reclassify the overall task as Elevated. Delegation is not just a safety mechanism - it is mandatory context hygiene. A conductor that fills its own context with investigation work cannot orchestrate. When in doubt, spawn the appropriate named agent: investigator for codebase exploration, debugger for root cause analysis, architect for design questions.

| Level | Delegation | Review | Declaration |
|---|---|---|---|
| Trivial | Direct (conductor) if no subagents running; solo `engineer` Worker (foreground) if any subagent is running | None (no Skeptic, no brief file) | Silent |
| Low | Direct action | Brief inline self-check | Silent |
| Elevated | Worker | Fresh independent Skeptic | Stated before starting |
| Elevated + Cleanup | Worker | Skeptic -> `/simplify` -> Skeptic (narrow) | Stated before starting |

**Elevated signals (any single one triggers adversarial review):** any code edit to file contents (excluding diagnostic-only logging); security / auth / crypto / payments / secrets; irreversible operations; architecture decisions that constrain future choices; modifies protocol or infrastructure files; production or shared state; multi-file changes; new file creation; external APIs or services; unfamiliar codebase area; logic with emergent cross-component interactions; user signals high stakes; configuration changes; research that produces a document, recommendation, or plan to be acted on; changes to shared utilities used across many call sites (single-file but high blast radius); anything where a mistake costs time or data.

**Trivial signals (ALL must hold - any single disqualifier pushes to Elevated):** touches exactly one file (or one file plus its colocated test/snapshot); no change to control flow, data flow, state shape, API surface, or types; no change to shared design tokens, theme files, config, env, or CI; no change to anything a downstream consumer imports (exported symbols, public CSS classes, route paths); reversible with a one-line revert; no security, auth, permissions, billing, or PII surface involved. Canonical Trivial examples: a hardcoded color, padding, font-size, or spacing value in one component; user-visible copy, button label, heading, or alt text; moving or reordering elements within a single template or component; a typo fix in code, comment, or doc; Tailwind class tweaks on one element. NOT Trivial even if it feels small: edits to `tailwind.config.*`, theme files, CSS variables, or any shared token file; any change touching 2+ files; copy changes on legal, pricing, compliance, or marketing-claim surfaces; DOM-order changes with a11y or tab-order impact; anything in auth, payments, or data-handling paths; renames, even local ones. When in doubt between Trivial and Elevated, choose Elevated.

**Conductor rule for Trivial:** If no subagents are currently running, the conductor edits directly (no Worker, no Skeptic, no brief file). If any subagent is currently running, spawn a single `engineer` Worker in foreground (no Skeptic, no brief file) - the conductor must stay available to manage in-flight work. A commit message is still required. If a Worker discovers mid-task that the change is not actually Trivial (e.g., the "one-file color tweak" lives in a shared token file), it must stop, report, and the conductor re-classifies as Elevated.

**Low signals:** clearly reversible reads (reads with no writes); exploration / research / draft work - only when the output is understanding, not a decision-driving artifact; **diagnostic-only changes** (pure logging additions - console.log, .catch() for error visibility, test interceptors) across any number of files, where every change has zero behavioral effect; **documentation-only file creation** (new .md or .txt files that are pure lists, glossaries, or running notes - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/agentic-engineering/; overrides the "new file creation" Elevated signal for this case only); **targeted wording fixes to already-reviewed content** (phrasing adjustments where the substance was already Skeptic-approved in the current or a recent session - e.g., syncing parallel descriptions, adding a clarifying phrase to an existing enumeration; does not apply to new decisions, new recommendations, or new content not previously reviewed; does not override the "modifies protocol or infrastructure files" Elevated signal; overrides the single-file edit and new file Elevated signals for this case only); **file renaming** (renaming or moving files via `git mv` or equivalent, with no content changes to any file - neither the renamed file nor any other file; overrides the "new file creation", "multi-file changes", and "Bash with side effects" Elevated signals for this case only; does not override the "modifies protocol or infrastructure files" Elevated signal - renaming protocol or infrastructure files remains Elevated regardless; if any other files reference the renamed path - imports, cross-references, config entries - the operation is Elevated because those reference updates constitute content changes in other files; if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the operation is Elevated because the rename changes behavior without changing file contents); **UI-only copy changes** (rewording display strings, labels, tooltips, or placeholder text where the change has no logic, structural, or behavioral effect - e.g., "The path is clear" to "The path seems clear"; does not apply to strings matched by tests, error messages that drive control flow, or protocol/infrastructure files; overrides the "any code edit with behavioral effect" Elevated signal for this case only).

**Mid-task reclassification:** If a task initially classified as Low reveals Elevated signals during execution, stop, reclassify as Elevated, and apply adversarial review from that point.

**Low risk self-check:** After completing a Low-risk change, re-read it in full. Verify intent, edge cases, and side effects. If any concern arises, reclassify as Elevated.

**Declaration format:**
```
Risk: Elevated - [specific signal]
Applying adversarial review.
```
```
Risk: Elevated + Cleanup - [specific signal]
Applying adversarial review with /simplify cleanup pass.
```

## Post-sign-off finding promotion

After Skeptic sign-off on any Elevated task (and after any QA gate), the conductor performs a promotion check. If any Major or Critical finding from the completed task represents a recurring pattern (seen 2+ times in this project) or is novel but has outsized blast radius (data loss, security, production outage class), add or update an entry in `.claude/findings.md`. This rule fires after every Skeptic sign-off in any context - not only inside `/implement-ticket`. Full promotion criteria, entry format, and who reads the file: `~/agentic-engineering/.claude/skills/agentic-engineering/references/findings-flywheel.md`.

## QA Gate

**Post-Skeptic QA for UI-visible changes.** After Skeptic sign-off on any Elevated unit, check whether the project has a `.claude/qa.md` with a `## QA triggers` section containing file patterns. If the reviewed diff includes files matching any trigger pattern, spawn `qa-engineer` before declaring the unit complete. QA failure blocks completion - the conductor spawns a fix engineer, then re-runs QA.

**When QA is skipped:**
- No `.claude/qa.md` exists in the project
- `.claude/qa.md` has no `## QA triggers` section
- No files in the reviewed diff match any trigger pattern
- The change is Low risk (direct action)

**QA gate flow:**
1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor checks `.claude/qa.md` trigger patterns against the diff
3. If matched: spawn `qa-engineer` with the unit's acceptance criteria and the qa.md config
4. QA engineer opens the dev server in a browser, verifies functionality, returns pass/fail report
5. On PASS: unit is complete
6. On FAIL: spawn fix engineer for each bug, then re-run QA

**Phase breadcrumb:** `[phase: qa-review]`

## Task Decomposition

**One agent, one task, one prompt.** The conductor breaks work into atomic units before spawning Workers. A focused agent is a correct agent - Workers should not do epics alone.

**Decompose implementation, not review.** Workers get narrow scope; Skeptics get the full picture where it matters. The orchestration-planner identifies unit boundaries and dependencies; the conductor applies the following rules to the planner's output:
- **Independent elevated units (planner-identified):** each gets its own Skeptic (small diff, high signal)
- **Interdependent elevated units (planner-identified):** separate focused Workers, but one Skeptic reviewing the combined diff - the integration Skeptic replaces per-unit Skeptics, not layers on top
- **Low-risk units:** direct action with self-check (no Skeptic) - e.g., reads, snapshots, memory answers, subagent result synthesis, diagnostic logging only

**Before spawning workers: run the orchestration-planner.** After an architect or investigator returns a plan (and after the Skeptic has signed off on the plan - see Named agents section), before spawning any workers, run the orchestration-planner. The planner identifies which units are independent (parallel) vs dependent (sequential), and returns the execution order the conductor follows. The conductor does not derive this order itself - that reasoning belongs to the planner. Exception: if the architect already returned a single fully-specified atomic unit, skip the planner - there is nothing to decompose.

## Worktree Lifecycle

**Two classes of worktree, two cleanup triggers.**

**Isolation worktrees (`worktree-agent-*`)** are created by the Agent tool when `isolation: "worktree"` is set. Once the agent returns its output and the conductor has opened a PR (or confirmed no PR is needed), the isolation worktree is redundant - the branch holds the commits. The conductor must remove it immediately:

```bash
# Verify no uncommitted changes before removing:
git -C <worktree-path> status --porcelain
# If clean (no output), remove:
git worktree remove <worktree-path>
# If the above fails (modified tracked files exist), inspect them first,
# then force-remove only after confirming nothing important is uncommitted:
# git worktree remove --force <worktree-path>
# Do NOT delete the branch - it backs the open PR.
# Exception: if no PR was opened (task cancelled/no PR needed), also delete the branch:
# git branch -D <branch-name>
```

**Feature worktrees (`feature/*`, `fix/*`, `chore/*`)** are removed after the PR is merged:

```bash
gh pr merge <number> --squash --delete-branch
git worktree remove --force <worktree-path>
git branch -D <branch-name>   # if not auto-deleted by --delete-branch
git worktree prune             # clean up any stale metadata
```

**Before spawning any agent with `isolation: "worktree"`**, prune dead `worktree-agent-*` branches to prevent stale branches from being reused at their old commits:

```bash
git fetch origin
git worktree prune
# Delete any worktree-agent-* branches not currently checked out in a worktree:
git branch | grep 'worktree-agent-' | sed 's/^[* ]*//' | while read b; do
  git worktree list | grep -qF "[$b]" || git branch -D "$b"
done
```

**Subagents do not have hooks.** Hooks fire only in the main session. Isolation worktrees with no changes are auto-cleaned by the Agent tool. Isolation worktrees with changes persist until the conductor explicitly removes them.

## Protocol Details (read on trigger)

**Phase breadcrumb** - at every natural orchestration boundary (after agent spawn, agent return, escalation, task completion):
Emit `[phase: label]` inline in your status update to the user. Full vocabulary in `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` Rule 6.

**Skeptic loop orchestration** - when Elevated risk is declared:
Run `/skeptic` for the full orchestration template, or read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 2-5) for loop steps, state management, re-route limits, and escalation.

**Findings classification and sign-off** - when reviewing Skeptic output:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Sections 6, 11) for Critical/Major/Minor definitions, required sign-off format, and validation rules.

**Elevated + Cleanup path** - when declaring Elevated + Cleanup:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 12) for the /simplify integration workflow and second Skeptic narrow-scope review.

**Adversarial briefs** - when writing the brief for a Skeptic:
Run `/skeptic` (includes brief selection table) or read `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 8) for domain-specific templates.

**Parallel spawning and worktrees** - when decomposing work into multiple agents:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Sections 2, 5, 7) for parallel-by-default, worktree isolation rules, and check-in behavior.

**Task decomposition and review scope** - when breaking work into multiple Workers:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/subagent-protocol.md` (Section 6) for decomposition rules and `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` (Section 9) for review scope guidance.

**Agent team composition** - which agent to use and how they compose:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/agent-team.md` for flows (feature, bug, security), decision rules, and spawn prompts.

**Findings flywheel** - when promoting a finding to `.claude/findings.md` or when the Skeptic checks for repeated patterns:
Read `~/agentic-engineering/.claude/skills/agentic-engineering/references/findings-flywheel.md` for entry format, promotion criteria, who reads the file, and the regression test obligation for fixed findings.

**QA gate** - when Skeptic sign-off is granted on a UI-visible change:
Check `.claude/qa.md` for trigger patterns. If the diff matches, spawn `qa-engineer`. The qa-engineer reads `.claude/qa.md` for dev server config, trigger patterns, and accumulated knowledge. See the QA Gate section above for the full flow.
