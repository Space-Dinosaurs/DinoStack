<!--
Purpose: Detailed conventions reference blocks extracted from
         content/rules/conventions.md. Contains: the full Intent Layer
         section (artifact list, intent debt, Project Overview Layer,
         Project Config toggle prose, and Ubiquitous Language); the
         Session-Start Sweeps detail (knowledge-strand sweep mechanics);
         the full Merge-Time Tracker Writeback rule (its short resident
         rule-statement, with the trigger, the exact invocation and the
         --auto carve-out, lives in content/rules/conventions.md
         § Git Workflow; the operand preconditions, soft-fail behavior,
         TRACKER == none no-op and target-state clause live here - the two
         are one rule split by load tier, not two rules);
         the Context Economy rules; and the External Comment Discipline
         rules.

         Note: The Project Config prose here is the conventions-angle
         description of the same toggles also described in
         content/references/risk-config-and-tiers.md §Config Toggle Catalog
         (behavioral). Both copies must stay in sync with .agentic/config.json.

Public API: Read-only reference document. Cross-referenced from:
            content/rules/conventions.md (inline pointers replacing these
            verbose blocks).

Upstream deps: content/rules/conventions.md (parent rules file; read that
               file first for Writing Style, Project Structure Convention,
               Session Context and Memory, and Git Workflow rules).

Downstream consumers: conductor (Intent Layer for understanding artifact
                      routing; External Comment Discipline for PR bodies,
                      ticket descriptions, commit messages, assembled PR
                      bodies, tracker comments, and review comments; Context
                      Economy for output discipline); content/sections/
                      12-protocol-details.md (conventions reference).

Failure modes: Prose reference; does not auto-execute. The Project Config
               toggle list here is a conventions-angle mirror of the
               section-04 catalog; both must agree with config defaults.
               The glossary.md Ubiquitous Language section is binding on the
               project once introduced - the methodology cannot enforce this
               automatically.

Performance: Standard.
-->

> Parent rules file: `content/rules/conventions.md`. Read that file first for Writing Style, Project Structure Convention, Session Context and Memory, and Git Workflow rules.

## The Intent Layer

A project's intent is encoded across a small set of artifacts. Treat them as a coherent layer, not as unrelated files:

- `docs/overview/vision.md` - product vision and purpose; operator-owned, agents read but never write
- `docs/overview/requirements.md` - scoped functional and non-functional requirements; operator-owned, agents read but never write
- `AGENTS.md` - project-level decisions and conventions (tool-agnostic).
- `MEMORY.md` - stable facts learned about the project, with rationale. Canonical durable-facts store; loaded at session start via the `@MEMORY.md` import in the project root `CLAUDE.md` (added by `/ds-init-project`). Written by `/ds-wrap` (Part B staging-drain promotion, capped 3/run), `learnings-agent` (project-affecting KNW events, 1/event), wrap-ticket, and `/ds-memory-update`. Part E bounds the file's size via compression once it crosses its gate. Root `<cwd>/MEMORY.md` only - NOT `.agentic/memory.md` (that is now deferred-wrap-daemon staging, gitignored, drained into root `MEMORY.md` by the next synchronous `/ds-wrap`). Committed by default for consumer projects scaffolded by `/ds-init-project`. Exception: in the DinoStack repo itself, root `MEMORY.md` is intentionally gitignored (DS-129) - it is the methodology's own self-improvement scratch, not a shippable artifact for consumers to inherit, so writes from `/ds-wrap`, `learnings-agent`, wrap-ticket, and `/ds-memory-update` here are local-only and never reach a PR.
- `.agentic/learnings.md` - structured fix-pattern learnings from resolved Skeptic cycles; committed (not gitignored). Written by `learning-extractor` at `/ds-implement-ticket` Phase 6 clean exit (mechanically wired) and by `learnings-agent` (spawned on the mandatory capture triggers).
- `decisions.md` - the project's decision log, where used.
- `.agentic/findings.md` - curated Skeptic-finding patterns; gitignored/machine-local. Written by `findings-curator` at Phase 6 loop exit.
- `.agentic/qa-regressions.md` - curated QA regression patterns; committed. Written by `qa-regressions-curator` at Phase 6b QA FAIL.
- `qa.md` - QA triggers and project-specific quirks the QA engineer needs to know.
- Module manifests - file-level intent embedded in the source itself (see `module-manifest.md`).
- `glossary.md` - the project's Ubiquitous Language (see below).

Together these form the project's **intent layer**. Drift in any of them is **intent debt** - the system stops reflecting what we meant to build, and downstream agents and humans drift along with the artifacts. Keep them current. A stale entry is worse than a missing one because readers trust it.

### Project Overview Layer

`docs/overview/vision.md` and `docs/overview/requirements.md` are operator-authored documents that capture durable product intent above the task level. When present, Architect, Investigator, and Engineer read them before producing output; the design, investigation, or implementation must not contradict them.

**What each file contains:**
- `vision.md` - why the product exists, who it serves, what outcome it delivers (one screen, narrative form)
- `requirements.md` - scoped functional and non-functional requirements, as bulleted statements

**Rules:**
- Operator-owned: agents read, never write or propose edits to these files
- Optional and graceful: if `docs/overview/` does not exist or these files are absent, nothing breaks
- Not a replacement for per-task Briefs: the Brief's "Problem" and "Constraints" fields should be consistent with these docs when present, but overview docs do not replace task-scoped planning artifacts

### Project Config (`.agentic/config.json`)

`.agentic/config.json` holds project-level methodology toggles the conductor reads to adjust orchestration behavior. It is **committed, not gitignored** in a consumer project - `/ds-init-project` Step 9's default-deny `.agentic/*` umbrella (delegated to `ds-migrate apply` against `content/project-scaffolding.yml`) carries an explicit `!.agentic/config.json` negation, like `qa.md` and `deploy.md`. (DinoStack's own repo is the methodology's source, not a consumer of it, and does not commit its own `.agentic/config.json` - this repo's root `.gitignore` umbrella has no such negation.) It is seeded with defaults by `/ds-init-project`. Twenty-five toggles (one, `qa_default_skip`, is reserved/inert - documented for schema completeness but does not currently alter behavior):

- `debugger_on_failure` - boolean, default `false`. When `true`, the Elevated-path quality gate in `/ds-implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass. Opt-in; the default preserves existing behavior. A Trivial-path ticket never invokes the Debugger regardless of this toggle.
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior. **Canonical definition lives in `content/references/planning-artifacts.md` §`qa_default_skip` (canonical definition)** - this entry is a cross-reference only and does not restate the semantics.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. `budget` routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - those require explicit `Tier: 3` regardless of the project `model_profile`. The same exemption covers any Skeptic the Mandatory Tier-3 review escalation rule has elevated for this unit: `budget` must not pass a downgrading `model` param to it. `budget` acts only through the spawn-call param; it never rewrites an agent's frontmatter `model:`.
- `auto_merge_on_ci_green` - boolean, default `false`; governs the "Auto-merge follow-through" rule (see below) - not scoped to `/ds-implement-ticket` alone. Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `capability_preflight_mode` - enum (`advisory` | `blocking`), default `blocking`. Controls what happens when the conductor finds a missing required dependency during capability preflight. `advisory` emits a warning with the install command and proceeds with the spawn. `blocking` refuses the spawn when any required dependency remains missing after auto-install. Default flipped to `blocking` at P2 now that all agent manifests are populated. See `content/references/capability-preflight.md` for the full preflight protocol.
- `perceptual_diff_enabled` - boolean, default `false`. When `true`, qa-engineer runs Playwright `toHaveScreenshot` against committed baselines in `tests/visual-baselines/` and raises auto-Major on drift exceeding per-scenario `tolerance`. Opt-in; baseline maintenance overhead justifies the default of `false`.
- `theme_aware` - boolean, default `false`. Opt-in for the `theme` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer toggles light/dark themes and runs per-(scenario x viewport x theme) tuples. Default toggle covers CSS class (`document.documentElement.classList.toggle('dark')`) and data-attribute (`setAttribute('data-theme', 'dark')`) patterns; other patterns require a `theme` knowledge tag in `qa.md`.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer navigates to the Storybook iframe URL (`/iframe.html?id=<story_id>`) instead of the live app. Requires Storybook 7+; init-project detects the installed version and configures the related `storybook_url` key when SB7+ is present.
- `motion_aware` - boolean, default `false`. Opt-in for the `motion` scenario method auto-Major Skeptic rule. When `true`, qa-engineer runs CDP-emulated reduced-motion checks per scenario. Absent motion scenarios on UI-visible Elevated units with `qa_skip == null` trigger a Skeptic-on-Brief Major finding. Matches `theme_aware` / `perceptual_diff_enabled` opt-in precedent.
- `storybook_version` - enum (`6 | 7`), default `7`. Selects Storybook URL format for `story_id` scenarios. When `6`, qa-engineer converts story IDs to the `?selectedKind=&selectedStory=` URL format. When `7` or absent, uses the current `?id=` format. Set automatically by init-project based on detected framework adapter version.
- `commit_telemetry` - boolean, default `true`. When `true`, `/ds-implement-ticket` Phase 8 commits `.agentic/session-log/<developer_id>.jsonl` as a SEPARATE commit on the PR branch, gated on confirmed (non-provisional) identity. The commit makes per-session telemetry team-visible after squash merge. Set to `false` to opt out. No effect when identity is absent or provisional.
- `knowledge_commit_on_pr` - boolean, default `true`; when `true`, `/ds-implement-ticket` Phase 11e commits changed `MEMORY.md`/`decisions.md`/`.agentic/learnings.md`/`AGENTS.md`/`.agentic/tracking.md` onto the ticket's PR branch. Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `knowledge_commit_exclude` - list of strings, default `[]` (empty, no built-in entries). Each entry must EXACTLY match one of the five knowledge-commit candidate-set strings - `MEMORY.md`, `decisions.md`, `.agentic/learnings.md`, `AGENTS.md`, `.agentic/tracking.md` - to exclude that file from Phase 11e and `/ds-wrap` Part G commits; an entry that does not match any of the five is a silent no-op. Absent/malformed config is treated as an empty list (nothing excluded). Set by editing `.agentic/config.json` directly - not exposed via the settings CLI (same as its sibling `knowledge_commit_on_pr`). DinoStack's own repo sets this locally (gitignored, never committed) to `["AGENTS.md"]` to preserve the 2026-08-11 operator decision that session learnings never write to AGENTS.md here.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in for the daemon-driven deferred-wrap workflow; when `true`, an out-of-session daemon picks up deferred `/ds-wrap` jobs (idle detection, heartbeat, timeout, reclaim, and pending TTL are tuned by the `deferred_wrap_*` related keys below). The default `false` preserves the in-session synchronous `/ds-wrap` behavior.
- `abdication_guard_enabled` - boolean; requires an explicit `true` to run (absent or malformed `.agentic/config.json` = guard does not fire at all; the shipped template and `/ds-init-project` set it). When active, a Stop hook detects three shapes of conductor abdication - a permission-seeking interrogative, a surface-and-proceed default announced and then not acted on, or a prose co-equal ballot in an `## Operator decisions` block - and blocks the stop, injecting a directive. Mechanizes the Proactive autonomy / default-and-proceed rule in `content/sections/02-delegation.md`. All three classifiers are false-negative-biased; the classic interrogative path's suppression surface widened further in that direction in a later fix pass. Two loop-guard layers: `stop_hook_active` flag (primary) and a consecutive-block counter cap (backstop for CC bug #54360), shared across all three classifiers. Set to `false` to opt out once enabled; disable per-session via `AE_ABDICATION_GUARD_DISABLE=1`.
- `skill_candidate_detection` - boolean, default `true`. Master toggle for the skill-candidate detector. When `true`, the Stop hook scans `.agentic/events.jsonl` and `.agentic/learnings.md` for recurring friction patterns (clustered by `domain_tag` / `Domain`) and writes candidates to `.agentic/skill-candidates.md`; the conductor emits a session-start notice when new candidates are found (Layer 1). Layer 3 (`/ds-skill-candidates` command) is also gated on this toggle. When `false`, the detector exits immediately and all layers are dark. Set to `false` to opt out of skill-candidate tracking on this project.
- `skill_candidate_nudge` - boolean, default `false`. Layer-2 opt-in. When `true` AND `skill_candidate_detection` is `true`, a `PostToolUse(Task)` hook emits an in-session nudge the first time a domain crosses the candidate threshold during the current session. `skill_candidate_nudge` alone (with `skill_candidate_detection: false`) has no effect. Default `false` (matches `deferred_wrap_daemon` opt-in precedent).
- `ticket_driven` - enum (`off` | `offer` | `require`). Controls whether the conductor creates a tracker ticket before spawning any subagent (exemptions apply) on net-new work. **Absent-key resolution:** when the key is absent from `.agentic/config.json`, effective value is `offer` when `TRACKER != none` and `off` when `TRACKER == none` - this makes "tracker connected => offer by default" true with zero migration. An explicit value always wins. `offer`: surface-and-proceed - conductor announces ticket creation and proceeds unless the operator replies STOP within one turn. `require`: hard gate - no subagent spawns before a ticket exists (exemptions apply); creation failure surfaces and waits for operator resolution. `off`: gate disabled; no ticket creation attempt. Existing-ticket arrivals (ticket ID resolved in Phase 0, or invocation was `/ds-implement-ticket <ID>`) and `TRACKER=none` projects are always exempt. Cross-ref: `content/commands/ds-implement-ticket.md` §Tracker Create Helper, `content/sections/02-delegation.md` §Ticket-offer gate. Mid-session discovery tickets follow a separate rule: `content/references/delegation-detail.md` §Follow-up Ticket Creation Discipline.
- `rework_detection` - boolean, default `true`; when `false`, disables rework detection end-to-end. Full semantics: `content/references/risk-config-and-tiers.md` §Project config (which points onward to `content/references/ticket-rework.md` §Config toggle).
- `pending_merge_sweep` - boolean, default `true`; set `false` to disable. Controls the session-start pending-merge sweep that pushes the dev-complete transition to the tracker once a ticket's PR merges (the target defaults to the resolved Done value when no dev-complete state is declared). Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `tracker_state_diagnostic` - boolean, default `true`. Controls whether the tracker writeback subagent emits a live diagnostic naming currently-available states when a configured `TRACKER_STATE_*` name cannot be used; set `false` to disable.
- `turn_shape_guard_enabled` - boolean, default `true` (absent key resolves to on); set `false` to opt out, or disable per-session via `AE_TURN_SHAPE_GUARD_DISABLE=1`. Governs the Stop hook (`hooks/enforce-turn-shape.py`) checking the conductor's final turn shape - `_execution_prose_flag` and `_status_only_flag` are both BLOCKING (the latter restored by DS-ANSWERFIRST), `_decision_item_sprawl_flag` is advisory-only. One toggle and one kill switch govern all three; there is no per-check toggle. Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `worktree_read_guard_exemptions` - list of strings, default `[]`; each entry is a path prefix exempted from the worktree-isolated Read guard (`hooks/enforce-worktree-read.py`). Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `worktree_write_guard_exemptions` - list of strings, default `[]`; SEPARATE from `worktree_read_guard_exemptions` - each entry is a path prefix exempted from the worktree-isolated Write/Edit/MultiEdit guard (`hooks/enforce-worktree-write.py`). Full semantics: `content/references/risk-config-and-tiers.md` §Project config.
- `memory_shard_mode` - boolean, default `false` (opt-in). Ships inert as of DS-221 Unit 1: the memory-shard compiler exists but no writer reads this toggle yet. Full semantics: `content/references/memory-shard-convention.md`.

**Related config keys (not toggles):** these are tuning params that travel with the same file but are not boolean/enum methodology switches:

- `storybook_url` - optional string, default `http://localhost:6006` when present. Set automatically by init-project Storybook version detection when a SB6 or SB7+ framework adapter is found. Override per-run via the `story-url` knowledge tag in `qa.md`.
- `deferred_wrap_idle_minutes` - integer, default `15`. Minutes of session idle before the deferred-wrap daemon considers a session eligible for an out-of-session wrap. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_heartbeat_seconds` - integer, default `120`. Interval in seconds at which the daemon writes a liveness heartbeat while processing a deferred-wrap job. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_timeout_minutes` - integer, default `10`. Maximum minutes a single deferred-wrap job may run before the daemon aborts it. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_inprogress_reclaim_minutes` - integer, default `30`. Minutes after which an in-progress job whose heartbeat has gone stale is reclaimed and re-queued by the daemon. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_pending_ttl_days` - integer, default `7`. Days a pending deferred-wrap job is retained before the daemon expires it. Only consulted when `deferred_wrap_daemon` is `true`.

The file is operator-tunable but optional and graceful: if absent, every toggle takes its default and nothing breaks.

### Ubiquitous Language (`glossary.md`)

A `glossary.md` at the project root (or referenced from the root `AGENTS.md`) holds the project's domain terms - the **Ubiquitous Language** that humans, code, and LLM agents all use to describe the system. When a glossary is present:

- Agents prefer existing terms over inventing synonyms. If the glossary calls it "shipment", do not introduce "delivery", "consignment", or "package" in code, comments, prompts, or docs without first updating the glossary.
- The Skeptic flags a synonym-of-an-existing-term as a **Minor** finding (style + intent drift).
- The glossary is part of the intent layer above - keep it current as the domain vocabulary evolves.

A glossary is optional; not every project needs one. But once introduced, it is binding on the project.

## Session-Start Sweeps

### Knowledge-strand sweep

Runs at session start, after the pending-merge sweep (see `content/rules/conventions.md` §Session Context and Memory for the sweep order and the summary notice format). **Read-only** - no worktree, no branch, no git write, and no `git fetch`: resolve `BASE_BRANCH` using the same non-interactive steps 1-3 as **Base branch resolution** (declared in `AGENTS.md`, else local `develop`, else local `development`, falling to `main`/`master` per step 5 without the step-4 prompt - this sweep never asks). Because it must not fetch, `origin/<BASE_BRANCH>` here can be a stale local copy of the remote ref; a stale ref can delay a notice by one session (until the next `git fetch` happens elsewhere), which is an acceptable cost for a non-blocking advisory.

Applies Part G's per-file gating (`content/commands/ds-wrap.md` §Part G - Knowledge-file commit) against the conductor's own checkout only, for the same five-file candidate set in the same order (`MEMORY.md`, `decisions.md`, `.agentic/learnings.md`, `AGENTS.md`, `.agentic/tracking.md`): file absent -> skip; file's entry is present in `knowledge_commit_exclude` -> skip; `git check-ignore -q` succeeds -> skip; unchanged versus `origin/<BASE_BRANCH>` -> skip, BUT (same fix as Part G) a path absent from `origin/<BASE_BRANCH>` (`git cat-file -e origin/<BASE_BRANCH>:<path>` fails) is entirely new content and does NOT skip, even though `git diff --quiet` would falsely report it unchanged.

For each file that survives gating, compute a tracker key `<path>:<hash>` where `<hash>` is the first 8 hex characters of the SHA-256 of `git diff origin/<BASE_BRANCH> -- <path>` (the file's own pending diff, not its full contents). If that exact key is not already present in `.agentic/.knowledge-strand-surfaced`, emit at the next user-facing turn boundary:

```
KNOWLEDGE-STRAND: <file1>, <file2> have local changes not yet committed - run /ds-wrap to capture and commit them.
[phase: knowledge-strand]
```

Then append each surfaced file's `<path>:<hash>` key to `.agentic/.knowledge-strand-surfaced` (append-only, one key per line, covered by `/ds-init-project` Step 9's `.agentic/*` umbrella ignore (not individually enumerated - see `content/project-scaffolding.yml`); file-absent = empty set). Keying on the diff hash rather than the bare path means the sweep re-fires for genuinely new stranded content even in a file that already produced a notice, while staying quiet for content it has already surfaced - the same per-event-not-per-path keying discipline the meta-divergence sweep applies via `original_task_id` and the skill-candidate sweep applies via domain. The tracker is still never pruned - once a file is committed (via `/ds-wrap` Part G or otherwise) its diff-against-`origin/<BASE_BRANCH>` changes or disappears, so the old key stops matching and a new key is computed next time content strands again; a stale key left behind is inert, not misleading, and it does not suppress notification of different future content because different content hashes differently. This sweep is cheap (three bounded file checks plus a hash, no network call, no worktree) and therefore carries no separate pagination/throttle mechanism beyond the surfaced-state dedup above - unlike the meta-divergence and skill-candidate sweeps, the tracker here is bounded by strand *events* (one key per distinct stranded-content state, per file) rather than by an ever-growing telemetry stream, and at roughly 70 bytes per entry it stays small enough that adding a cap would cost more to implement and maintain than it would ever save.

### Sibling-PR auto-merge sweep

Runs at session start, after the knowledge-strand sweep. Skip entirely - zero `gh` calls - unless `auto_merge_on_ci_green` is `true` in `.agentic/config.json` (same toggle Phase 10's timeout handling and Phase 12's conditional auto-merge already gate on; see `content/commands/ds-implement-ticket.md` Phase 10 "Phase 10 timeout handling" and Phase 12 "Conditional auto-merge"). When the toggle is `false` (default), this sweep fires no behavior and states no merge intention.

When enabled, list every other open PR the agent owns (`gh pr list --author "@me"`) against `$BASE_BRANCH` whose `mergeStateStatus` is `BEHIND` - never a PR authored by someone else - and for each non-draft match (ascending PR-number order, FIFO), rebase it onto the current base then queue GitHub's own auto-merge:

```bash
# @harness:sibling-pr-sweep
if [ "$AUTO_MERGE_ON_CI_GREEN" = "true" ]; then
  SIBLING_PRS=$(gh pr list --repo "$GH_REPO" --base "$BASE_BRANCH" --author "@me" --json number,mergeStateStatus,isDraft 2>/dev/null)
  if [ -n "$SIBLING_PRS" ]; then
    BEHIND_NUMBERS=$(echo "$SIBLING_PRS" | jq -r '[.[] | select(.mergeStateStatus == "BEHIND" and .isDraft == false) | .number] | sort | .[]')
    for N in $BEHIND_NUMBERS; do
      if gh pr update-branch "$N" --repo "$GH_REPO" --rebase 2>/dev/null; then
        if gh pr merge "$N" --repo "$GH_REPO" --squash --delete-branch --auto 2>/dev/null; then
          echo "[phase: sibling-pr-sweep | pr=$N | result: rebased-and-queued]"
        else
          echo "[phase: sibling-pr-sweep | pr=$N | result: queue-failed]"
        fi
      else
        echo "[phase: sibling-pr-sweep | pr=$N | result: rebase-failed]"
      fi
    done
  fi
fi
```

Soft-fail per PR - a single PR's rebase or queue failure is reported and the sweep continues to the next PR; a single PR's failure never blocks the sweep or the rest of the session-start sequence. As with every other `--auto` call in this methodology, exit 0 means QUEUED, not MERGED - no tracker writeback fires from this sweep; the session-start pending-merge sweep remains the sole mechanism that pushes the dev-complete transition once a queued merge actually lands.

## Auto-merge follow-through

Parent rule: `content/rules/conventions.md` §Git Workflow ("Auto-merge follow-through") carries the trigger and the honest-report obligation in resident form. This section is the full mechanism; the two are one rule split by load tier, never two rules.

**The trigger is the event, not a command.** Whenever an agent has opened a PR it owns against `$BASE_BRANCH` and `auto_merge_on_ci_green` is `true`, it queues `gh pr merge <N> --repo <repo> --squash --delete-branch --auto` before ending the turn - this applies identically to ad-hoc conductor-orchestrated work, a bare `gh pr create`, multi-unit fan-out, and a command-driven run; none of them is a precondition for the rule to fire, and none of them is required for it to be inert when the toggle is `false`. `/ds-implement-ticket` Phase 10's timeout handling (see `content/commands/ds-implement-ticket.md` "Phase 10 timeout handling") is one CALL SITE of this rule, not its definition - it applies the same `--auto` queue at the specific moment the CI poll loop times out, so a PR that goes green after the poll gives up does not require a resumed session to merge. The "Sibling-PR auto-merge sweep" above is a second call site, extending the same rule to PRs the agent may have opened in an earlier session or unit.

**Honest-report obligation.** When `auto_merge_on_ci_green` is `false` (default), nothing queues, and a turn must state the PR's real state - never a future merge intention it has no mechanism to carry out. "Next I merge those two once CI is green" describes an event nothing in the session will actually perform once the turn ends. When a queue was placed, `--auto` exiting 0 means QUEUED, not MERGED, and the report must say so, not claim the merge happened.

## Merge-Time Tracker Writeback

Parent rule: `content/rules/conventions.md` §Git Workflow ("Merge-time tracker writeback") carries the trigger, the exact invocation, and the `--auto` carve-out in resident form. This section is the full rule; the two are one rule split by load tier, never two rules.

When an agent merges a PR **outside** `/ds-implement-ticket` Phase 12's auto-merge block (that block owns its own writeback decision at site W7 and MUST NOT also fire this rule), and `gh pr merge` exits 0, and the agent knows **both** the ticket ID and the merged PR number, immediately run `/ds-ticket-status-sync <TICKET_ID> --pr <PR_NUMBER> --no-confirm`. A `gh pr merge --auto` call exiting 0 means QUEUED, not merged, and does NOT trigger this rule. If either the ticket ID or the PR number is unknown, do nothing here - the automatic backstop is the session-start `--pending-merge` sweep, and `/ds-ticket-status-sync --all` remains available on operator invocation. Soft-fail: a failure logs one line and never blocks the merge or any following step. `TRACKER == none` is a silent no-op. This does not change what state is written - the transition target is still `$TRACKER_STATE_DEV_COMPLETE`; AE still never writes the terminal `TRACKER_STATE_DONE` at any site.

## Context Economy

Agents must be mindful of context-window consumption. Large outputs increase latency, burn tokens, and can push the session toward truncation. Follow these rules:

- **Do not duplicate file contents in prose.** Reference files by path. The reader can use ReadFile if they need the full text.
- **Keep diffs minimal.** Use standard unified diff format with 3 lines of context per hunk. Do not paste entire files when only a few lines changed.
- **Do not paste tool output verbatim** unless specifically asked or unless the output is short (<20 lines). Summarize command results: "`pytest` passes (42 tests, 0 failures)" rather than dumping the full test log.
- **Structured blocks over prose.** Prefer the JSON structured block for machine-readable data (file lists, gate results) and keep prose for human-readable narrative only.

Multi-developer coordination guidance lives in `content/references/multi-developer-coordination.md`.

## External Comment Discipline

Agents author artifacts that humans read outside the session - PR titles and bodies, PR review comments, Linear comments, Jira comments, commit messages that summarise work, deploy and release notes. These surfaces have a different cost profile from in-session output: humans read them under time pressure, often on a phone, often days after the work landed. Verbosity is not free here - it is a tax on every future reader.

Apply these rules to every external-facing comment:

- **Lead with the result and the link.** The first line should answer "what changed and where do I look?" - not restate the ticket, not narrate the journey.
- **Bullets over prose.** Each bullet earns its place by adding something the diff, screenshot, or linked artifact does not already show. If a bullet just describes what the diff shows, delete it.
- **Cut what the reader can see for themselves.** Do not restate the ticket. Do not narrate the agent's own process ("I reviewed", "we investigated", "after analysis"). Do not summarise a diff that is one click away.
- **Evidence beats description.** A screenshot, a test URL, a log excerpt, or a link to the failing line is worth more than a paragraph of explanation. Link, do not transcribe.
- **No marketing voice, no emojis, no agent attribution footers.** The writing-style rules elsewhere in this methodology (plain verbs, no rule-of-three triads, no AI vocabulary, no em dashes) apply with extra force on external surfaces because humans read them quickly and judgmentally.
- **Length is not the metric; signal-per-line is.** A long comment is fine when every line is load-bearing. A three-line comment that restates the ticket is too long.
- **Skeptic findings posted as PR review comments** are one finding per comment in the form `[Severity] path:line - issue. Fix: <one-line action>.` No preamble, no sign-off banner, no "Active search" line on per-finding comments - that line belongs to the conductor-internal sign-off, not the PR surface.
- **Self-check before posting.** Re-read this section. For each sentence ask: is this load-bearing for a human deciding "do I need to act on this?" If not, delete it.

### Ticket descriptions

**The recoverability test governs content, not just length.** At creation time, capture what cannot be recovered later - the operator's intent: the Problem, why it matters, and what done looks like (Acceptance Criteria). Everything else - a proposed approach, a root cause, a file list, an implementation sequence, a blast-radius map - is recoverable at any later time by re-deriving it fresh against the tree as it exists at pickup, and is strictly better derived then: the picking-up session's own Investigator and Architect produce it independently, verified against current state rather than graded against a possibly-stale guess. Exclude it regardless of whether it is already free in context - a design costs nothing to write down and still anchors the implementing session, still goes stale before pickup, and still lets a Skeptic mistake two descendants of the same guess for independent corroboration.

**Problem and Acceptance Criteria are mandatory, not optional.** They are the irrecoverable half - once the operator's moment of intent passes, a later session can only guess or re-interrupt the operator. When Acceptance Criteria are genuinely undecided at creation time, write that down explicitly (`Acceptance Criteria: not yet defined - <what is blocking a decision>`) rather than omitting the section - an honest "unknown" preserves the fact that nobody has answered it yet; silent omission is indistinguishable from nobody having asked.

**Evidence is intent-bearing; a proposed fix is not.** A failing command, a log line, a stack trace, the file:line where a defect was observed, the commit that introduced it, or what was already tried and did not work - these anchor the Problem and belong in the ticket, however much space they take. A proposed approach, a diagnosis presented as established fact, or an implementation sequence anchors a design instead, and does not belong regardless of length or cost.

Lead with the Problem. These are soft targets, not hard caps, and they bound derived-content risk, not the intent content above - the signal-per-line test (`content/references/conventions-detail.md` §External Comment Discipline) and DS-156's relevance-over-length rule (`content/references/conductor-turn-format.md` §Length discipline) override any arithmetic: a 7-line Problem that is all load-bearing operator intent passes, evidence that legitimately runs long passes, and a 3-line Problem that restates the ticket fails.

- **Problem:** soft target ≤ 5 lines.
- **Acceptance Criteria:** soft target ≤ 8 bullets.
- **Total:** soft target ≈ 15 lines.

The fixed-form `## Scope boundary` append (written by the Create Helper collision pre-check - see `content/commands/ds-implement-ticket.md` §Tracker Create Helper) is excluded from the budget.

Per-line self-check: would a future reader need this line to know what to build, or when it is done? If not, delete it. A line that describes HOW rather than WHAT or WHY fails this check even when short.

**Cross-reference.** The direct-tool and follow-up ticket-creation path is governed by `content/references/delegation-detail.md` §Follow-up Ticket Creation Discipline - its carve-out, promotion bar, and batching rules decide whether a discovery becomes a ticket at all, independently of content. These soft length bounds apply to tickets authored through the Tracker Create Helper (see `content/commands/ds-implement-ticket.md` §Tracker Create Helper); the recoverability test applies to all three authoring paths (Tracker Create Helper direct, `/ds-brief`, `/ds-feedback-triage`) - nothing exempts hand-authored ticket bodies from the intent-vs-derived boundary, even though the length guidance does not reach the direct-tool path.

### Commit messages

Subject line: `type(scope): <imperative description>`, written in the imperative mood. The cap is on the whole subject INCLUDING the `type(scope):` prefix - ≤ 50 characters total, leaving roughly 25-35 characters for the description on typical scopes. A description that cannot fit pushes the detail into the body. Conventional git subject-line guidance: git truncates long subjects in tooling output, and 50 is the traditional subject cap. This is guidance, not a repo-precedent claim - subjects in this repo routinely run 60-120+ characters.

The body below the blank line is uncapped; put detail there. Trailer lines (Closes, Co-Authored-By, Developer, Signed-off-by) are excluded from the subject cap and pass through unchanged.

### Assembled PR bodies

The conductor assembles the final PR body. The **Summary** section is ≤ 5 single-line bullets. QA Evidence, the North Star alignment section, the tracker reference block, and the Test plan checkboxes are separate fixed-form sections, excluded from the Summary budget. The whole body is uncapped - the answer-relevance rule applies over any line arithmetic. The conductor seeds the Summary from the engineer's `pr_description_body` (2000-character cap at `content/agents/engineer.md:169`, unchanged). The general principle these per-surface rules instantiate is `content/rules/conventions.md` §Writing Style (length discipline).

This rule layers conciseness expectations on top of the structural templates in `content/commands/ds-implement-ticket.md` (PR body, tracker comment, ticket description). The templates still apply; this rule governs the substance that fills them.
