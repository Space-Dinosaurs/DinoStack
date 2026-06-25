<!--
Purpose: Full reference for verbose convention blocks extracted from
         content/rules/conventions.md. Covers: the Project Config toggle
         catalog (conventions view, named distinctly from the behavioral catalog
         in risk-config-and-tiers.md), the Intent Layer (including Project
         Overview Layer and Ubiquitous Language subsections), the Context Economy
         rules, and the External Comment Discipline rules.

Public API: Read-only reference document. Cross-referenced from:
            content/rules/conventions.md (parent rules file; pointers replace
            these blocks after kernel split);
            content/sections/12-protocol-details.md (Protocol Details entry).

Upstream deps: content/rules/conventions.md (parent rules file; Writing Style,
               Project Structure Convention, Session Context and Memory, and
               Git Workflow sections remain there for context).

Downstream consumers: conductor (reads Project Config conventions for toggle
                      semantics and related keys); architect and investigator
                      (read Intent Layer for product-intent file routing);
                      all agents (read External Comment Discipline for PR/tracker
                      comment authoring); all agents (read Context Economy for
                      output discipline).

Failure modes: Prose; does not execute. Project Config block is a conventions
               cross-reference - the behavioral catalog with full toggle semantics
               is in content/references/risk-config-and-tiers.md §Config toggle
               catalog (behavioral).

Performance: Standard.
-->

> Parent rules file: content/rules/conventions.md. Read that file first for Writing Style, Project Structure Convention, Session Context and Memory, and Git Workflow context.

# Conventions Detail - Full Reference

## Project Config conventions

### Project Config (`.agentic/config.json`)

`.agentic/config.json` holds project-level methodology toggles the conductor reads to adjust orchestration behavior. It is **committed, not gitignored** - like `qa.md` and `deploy.md`, it is portable project intent that travels with the repo (the `.agentic/` umbrella ignore must carve it out; see `.gitignore`). It is seeded with defaults by `/init-project`. Thirteen toggles (one, `qa_default_skip`, is reserved/inert - documented for schema completeness but does not currently alter behavior):

- `debugger_on_failure` - boolean, default `false`. When `true`, the Elevated-path quality gate in `/implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass. Opt-in; the default preserves existing behavior. A Trivial-path ticket never invokes the Debugger regardless of this toggle.
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior. **Canonical definition lives in `content/references/planning-artifacts.md` §`qa_default_skip` (canonical definition)** - this entry is a cross-reference only and does not restate the semantics.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. `budget` routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - those require explicit `Tier: 3` regardless of the project `model_profile`. The same exemption covers any Skeptic the Mandatory Tier-3 review escalation rule has elevated for this unit: `budget` must not pass a downgrading `model` param to it. `budget` acts only through the spawn-call param; it never rewrites an agent's frontmatter `model:`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory` | `blocking`), default `blocking`. Controls what happens when the conductor finds a missing required dependency during capability preflight. `advisory` emits a warning with the install command and proceeds with the spawn. `blocking` refuses the spawn when any required dependency remains missing after auto-install. Default flipped to `blocking` at P2 now that all agent manifests are populated. See `content/references/capability-preflight.md` for the full preflight protocol.
- `perceptual_diff_enabled` - boolean, default `false`. When `true`, qa-engineer runs Playwright `toHaveScreenshot` against committed baselines in `tests/visual-baselines/` and raises auto-Major on drift exceeding per-scenario `tolerance`. Opt-in; baseline maintenance overhead justifies the default of `false`.
- `theme_aware` - boolean, default `false`. Opt-in for the `theme` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer toggles light/dark themes and runs per-(scenario x viewport x theme) tuples. Default toggle covers CSS class (`document.documentElement.classList.toggle('dark')`) and data-attribute (`setAttribute('data-theme', 'dark')`) patterns; other patterns require a `theme` knowledge tag in `qa.md`.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer navigates to the Storybook iframe URL (`/iframe.html?id=<story_id>`) instead of the live app. Requires Storybook 7+; init-project detects the installed version and configures the related `storybook_url` key when SB7+ is present.
- `motion_aware` - boolean, default `false`. Opt-in for the `motion` scenario method auto-Major Skeptic rule. When `true`, qa-engineer runs CDP-emulated reduced-motion checks per scenario. Absent motion scenarios on UI-visible Elevated units with `qa_skip == null` trigger a Skeptic-on-Brief Major finding. Matches `theme_aware` / `perceptual_diff_enabled` opt-in precedent.
- `storybook_version` - enum (`6 | 7`), default `7`. Selects Storybook URL format for `story_id` scenarios. When `6`, qa-engineer converts story IDs to the `?selectedKind=&selectedStory=` URL format. When `7` or absent, uses the current `?id=` format. Set automatically by init-project based on detected framework adapter version.
- `commit_telemetry` - boolean, default `true`. When `true`, `/implement-ticket` Phase 8 commits `.agentic/session-log/<developer_id>.jsonl` as a SEPARATE commit on the PR branch, gated on confirmed (non-provisional) identity. The commit makes per-session telemetry team-visible after squash merge. Set to `false` to opt out. No effect when identity is absent or provisional.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in for the daemon-driven deferred-wrap workflow; when `true`, an out-of-session daemon picks up deferred `/wrap` jobs (idle detection, heartbeat, timeout, reclaim, and pending TTL are tuned by the `deferred_wrap_*` related keys below). The default `false` preserves the in-session synchronous `/wrap` behavior.
- `abdication_guard_enabled` - boolean, default `false`. When `true`, a Stop hook detects conductor abdication - ending a turn by asking the user permission to proceed with an obvious non-destructive next step - and blocks the stop, injecting a "proceed" directive. Mechanizes the Proactive autonomy / default-and-proceed rule in `content/sections/02-delegation.md`. Precision-biased classifier (false-negative over false-positive). Two loop-guard layers: `stop_hook_active` flag (primary) and a consecutive-block counter cap (backstop for CC bug #54360). Disable per-session via `AE_ABDICATION_GUARD_DISABLE=1`. Default `false` because this ships in the open-source methodology; individual projects opt in.

**Related config keys (not toggles):** these are tuning params that travel with the same file but are not boolean/enum methodology switches:

- `storybook_url` - optional string, default `http://localhost:6006` when present. Set automatically by init-project Storybook version detection when a SB6 or SB7+ framework adapter is found. Override per-run via the `story-url` knowledge tag in `qa.md`.
- `deferred_wrap_idle_minutes` - integer, default `15`. Minutes of session idle before the deferred-wrap daemon considers a session eligible for an out-of-session wrap. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_heartbeat_seconds` - integer, default `120`. Interval in seconds at which the daemon writes a liveness heartbeat while processing a deferred-wrap job. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_timeout_minutes` - integer, default `10`. Maximum minutes a single deferred-wrap job may run before the daemon aborts it. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_inprogress_reclaim_minutes` - integer, default `30`. Minutes after which an in-progress job whose heartbeat has gone stale is reclaimed and re-queued by the daemon. Only consulted when `deferred_wrap_daemon` is `true`.
- `deferred_wrap_pending_ttl_days` - integer, default `7`. Days a pending deferred-wrap job is retained before the daemon expires it. Only consulted when `deferred_wrap_daemon` is `true`.

The file is operator-tunable but optional and graceful: if absent, every toggle takes its default and nothing breaks.

## The Intent Layer

A project's intent is encoded across a small set of artifacts. Treat them as a coherent layer, not as unrelated files:

- `docs/overview/vision.md` - product vision and purpose; operator-owned, agents read but never write
- `docs/overview/requirements.md` - scoped functional and non-functional requirements; operator-owned, agents read but never write
- `AGENTS.md` - project-level decisions and conventions (tool-agnostic).
- `MEMORY.md` - stable facts learned about the project, with rationale. Canonical durable-facts store; auto-injected by Claude Code at startup. Written by `/wrap`, wrap-ticket, and `/memory-update`. Root `<cwd>/MEMORY.md` only - NOT `.agentic/memory.md` (that is `/wrap`-internal rolling scratch, gitignored).
- `.agentic/learnings.md` - structured fix-pattern learnings from resolved Skeptic cycles; committed (not gitignored). Written by `learning-extractor` at `/implement-ticket` Phase 6 clean exit (mechanically wired) and by `learnings-agent` (conductor-discretionary).
- `decisions.md` - the project's decision log, where used.
- `.agentic/findings.md` - curated Skeptic-finding patterns; gitignored/machine-local. Written by `findings-curator` at Phase 6 loop exit.
- `.agentic/qa-regressions.md` - curated QA regression patterns; committed. Written by `qa-regressions-curator` at Phase 6b QA FAIL.
- `qa.md` - QA triggers and project-specific quirks the QA engineer needs to know.
- Module manifests - file-level intent embedded in the source itself (see `module-manifest.md`).
- `glossary.md` - the project's Ubiquitous Language (see below).

Together these form the project's **intent layer**. Drift in any of them is **intent debt** - the system stops reflecting what we meant to build, and downstream agents and humans drift along with the artifacts. Keep them current. A stale entry is worse than a missing one because readers trust it.

### Project Overview Layer

`docs/overview/vision.md` and `docs/overview/requirements.md` are operator-authored documents that capture durable product intent above the task level. When present, Architect and Investigator read them before producing output; the design or investigation must not contradict them.

**What each file contains:**
- `vision.md` - why the product exists, who it serves, what outcome it delivers (one screen, narrative form)
- `requirements.md` - scoped functional and non-functional requirements, as bulleted statements

**Rules:**
- Operator-owned: agents read, never write or propose edits to these files
- Optional and graceful: if `docs/overview/` does not exist or these files are absent, nothing breaks
- Not a replacement for per-task Briefs: the Brief's "Problem" and "Constraints" fields should be consistent with these docs when present, but overview docs do not replace task-scoped planning artifacts

### Project Config (`.agentic/config.json`)

`.agentic/config.json` holds project-level methodology toggles the conductor reads to adjust orchestration behavior. It is **committed, not gitignored** - like `qa.md` and `deploy.md`, it is portable project intent that travels with the repo (the `.agentic/` umbrella ignore must carve it out; see `.gitignore`). It is seeded with defaults by `/init-project`. Thirteen toggles (one, `qa_default_skip`, is reserved/inert - documented for schema completeness but does not currently alter behavior):

- `debugger_on_failure` - boolean, default `false`. When `true`, the Elevated-path quality gate in `/implement-ticket` Phase 7 interposes a Debugger diagnosis step before each engineer fix pass. Opt-in; the default preserves existing behavior. A Trivial-path ticket never invokes the Debugger regardless of this toggle.
- `qa_default_skip` - reserved; documented for schema completeness; does not currently alter QA-gate behavior. **Canonical definition lives in `content/references/planning-artifacts.md` §`qa_default_skip` (canonical definition)** - this entry is a cross-reference only and does not restate the semantics.
- `model_profile` - enum (`default` | `budget`); unrecognized values fall back to `default`. `budget` routes eligible spawns to Tier 1 to reduce cost. **Carve-out:** `budget` NEVER applies to `security-auditor` or any agent whose spec mandates Tier 3 - those require explicit `Tier: 3` regardless of the project `model_profile`. The same exemption covers any Skeptic the Mandatory Tier-3 review escalation rule has elevated for this unit: `budget` must not pass a downgrading `model` param to it. `budget` acts only through the spawn-call param; it never rewrites an agent's frontmatter `model:`.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, `/implement-ticket` Phase 12 squash-merges the PR after all CI checks pass, the PR is marked ready, and no reviewer has requested changes. The default `false` preserves typical team git workflow (draft -> CI -> ready -> reviewers -> human merges).
- `capability_preflight_mode` - enum (`advisory` | `blocking`), default `blocking`. Controls what happens when the conductor finds a missing required dependency during capability preflight. `advisory` emits a warning with the install command and proceeds with the spawn. `blocking` refuses the spawn when any required dependency remains missing after auto-install. Default flipped to `blocking` at P2 now that all agent manifests are populated. See `content/references/capability-preflight.md` for the full preflight protocol.
- `perceptual_diff_enabled` - boolean, default `false`. When `true`, qa-engineer runs Playwright `toHaveScreenshot` against committed baselines in `tests/visual-baselines/` and raises auto-Major on drift exceeding per-scenario `tolerance`. Opt-in; baseline maintenance overhead justifies the default of `false`.
- `theme_aware` - boolean, default `false`. Opt-in for the `theme` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer toggles light/dark themes and runs per-(scenario x viewport x theme) tuples. Default toggle covers CSS class (`document.documentElement.classList.toggle('dark')`) and data-attribute (`setAttribute('data-theme', 'dark')`) patterns; other patterns require a `theme` knowledge tag in `qa.md`.
- `storybook_enabled` - boolean, default `false`. Opt-in for `story_id` field on `visual_conformance` and `accessibility` scenarios; when `true`, qa-engineer navigates to the Storybook iframe URL (`/iframe.html?id=<story_id>`) instead of the live app. Requires Storybook 7+; init-project detects the installed version and configures the related `storybook_url` key when SB7+ is present.
- `motion_aware` - boolean, default `false`. Opt-in for the `motion` scenario method auto-Major Skeptic rule. When `true`, qa-engineer runs CDP-emulated reduced-motion checks per scenario. Absent motion scenarios on UI-visible Elevated units with `qa_skip == null` trigger a Skeptic-on-Brief Major finding. Matches `theme_aware` / `perceptual_diff_enabled` opt-in precedent.
- `storybook_version` - enum (`6 | 7`), default `7`. Selects Storybook URL format for `story_id` scenarios. When `6`, qa-engineer converts story IDs to the `?selectedKind=&selectedStory=` URL format. When `7` or absent, uses the current `?id=` format. Set automatically by init-project based on detected framework adapter version.
- `commit_telemetry` - boolean, default `true`. When `true`, `/implement-ticket` Phase 8 commits `.agentic/session-log/<developer_id>.jsonl` as a SEPARATE commit on the PR branch, gated on confirmed (non-provisional) identity. The commit makes per-session telemetry team-visible after squash merge. Set to `false` to opt out. No effect when identity is absent or provisional.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in for the daemon-driven deferred-wrap workflow; when `true`, an out-of-session daemon picks up deferred `/wrap` jobs (idle detection, heartbeat, timeout, reclaim, and pending TTL are tuned by the `deferred_wrap_*` related keys below). The default `false` preserves the in-session synchronous `/wrap` behavior.
- `abdication_guard_enabled` - boolean, default `false`. When `true`, a Stop hook detects conductor abdication - ending a turn by asking the user permission to proceed with an obvious non-destructive next step - and blocks the stop, injecting a "proceed" directive. Mechanizes the Proactive autonomy / default-and-proceed rule in `content/sections/02-delegation.md`. Precision-biased classifier (false-negative over false-positive). Two loop-guard layers: `stop_hook_active` flag (primary) and a consecutive-block counter cap (backstop for CC bug #54360). Disable per-session via `AE_ABDICATION_GUARD_DISABLE=1`. Default `false` because this ships in the open-source methodology; individual projects opt in.

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

This rule layers conciseness expectations on top of the structural templates in `content/commands/implement-ticket.md` (PR body, tracker comment). The templates still apply; this rule governs the substance that fills them.
