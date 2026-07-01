<!--
Purpose: Defines the Skeptic Protocol - the adversarial review loop that governs
         all Elevated-risk changes. Sections are referenced directly by conductors
         and spawn briefs; section numbers are stable identifiers.

Public API: Referenced by section number across the methodology. Key sections:
  Section 2 - Skeptic loop orchestration (conductor entry point)
  Section 4.5 - Global-context input set (required in every spawn brief)
  Section 5 - Re-route limits and convergence failure
  Section 6 - Findings classification (Critical/Major/Minor definitions)
  Section 8 - Adversarial brief templates (domain-specific)
  Section 9 - Review scope guidance for decomposed tasks
  Section 11 - Sign-off format and validation rules
  Section 12 - Elevated + Cleanup path (/simplify integration)
  Section 14 - Skeptic calibration and meta-review telemetry

Upstream deps: content/agents/skeptic.md (Skeptic agent identity),
               content/rules/module-manifest.md (manifest policy enforced by Skeptic),
               content/agents/engineer.md (Worker the Skeptic reviews),
               METHODOLOGY.md (risk classification, re-route limits, QA gate)

Downstream consumers: content/agents/skeptic.md (spawned with Section 4.5 block),
                      content/commands/implement-ticket.md (Phase 6 Skeptic loop),
                      METHODOLOGY.md (imports loop semantics and re-route limits),
                      content/agents/architect.md (plan Skeptic references Section 8)

Failure modes: If this document goes stale, conductors construct incorrect spawn
               briefs (missing Global-context block), Skeptics apply wrong findings
               thresholds, and sign-off format validation fails. Section numbers
               are cross-referenced by string match - renumbering any section
               without a grep-and-replace sweep breaks all in-flight briefs.

Performance: N/A - methodology document consumed by LLMs at spawn time.
-->
# The Skeptic Protocol — Adversarial Review Methodology

## 0. Risk Assessment

Before starting any task, the main agent performs a brief risk assessment. The primary outcome is **Low** or **Elevated**. An optional **Elevated + Cleanup** tier extends the Elevated path with a `/simplify` cleanup pass and narrow-scope second review for substantial implementations (see Section 12).

### Risk signals

**Elevated → Full Adversarial Review (Worker + fresh independent Skeptic)**
Any single signal triggers:
- Security / auth / crypto / payments / secrets
- Irreversible operations (deletes, migrations, schema changes, force pushes)
- Architecture decisions that constrain future choices
- Modifies protocol or infrastructure files
- Production or shared state
- Multi-file changes
- New file creation
- Touches external APIs or services
- Unfamiliar codebase area
- Logic with emergent/non-obvious cross-component interactions
- User signals high stakes ("production", "critical", "don't mess this up")
- Configuration changes
- Research that produces a document, recommendation, plan, or anything to be acted on
- Changes to shared utilities, helpers, or abstractions used across many call sites (single-file but high blast radius)
- Anything where a mistake costs time or data

**Low → Light Touch (direct action, brief inline self-check)**
None of the above:
- Single file, well-understood change in familiar code
- Clearly reversible (e.g., file edits that haven't been committed or pushed, reads with no writes)
- Exploration / research / draft work — **only when the output is understanding, not a decision-driving artifact.** If the research will produce a document, recommendation, plan, or anything that drives a subsequent decision or action, it is Elevated, not Low.
- Read operations with minor targeted edits
- **Targeted wording fix to already-reviewed content** - a change that adjusts phrasing only, where the substance was already reviewed and approved (e.g., syncing parallel descriptions, adding a clarifying phrase to an existing enumeration, fixing ambiguous wording). Applies only when the content being adjusted has already passed Skeptic review in the current or a recent session. Overrides the "new file creation" and single-file edit Elevated signals for this case only. Does not override the "modifies protocol or infrastructure files" Elevated signal - wording fixes in protocol or infrastructure files remain Elevated regardless. Does not apply to new decisions, new recommendations, or new content not previously reviewed.
- **File renaming** (renaming or moving files via `git mv` or equivalent, with no content changes to any file - neither the renamed file nor any other file; overrides the "new file creation", "multi-file changes", and "Bash with side effects" Elevated signals for this case only; does not override the "modifies protocol or infrastructure files" Elevated signal - renaming protocol or infrastructure files remains Elevated regardless; if any other files reference the renamed path - imports, cross-references, config entries - the operation is Elevated because those reference updates constitute content changes in other files; if the file's name or path has behavioral significance by convention - framework routing (e.g., Next.js page files), auto-discovery (e.g., Jest test globs, webpack entry points), config naming conventions (e.g., `next.config.js`, `__init__.py`) - the operation is Elevated because the rename changes behavior without changing file contents).

**Uncertainty rule:** When in doubt, classify as Elevated. "Looks simple" is not a Low signal.

**Letter equals spirit rule:** Violating the letter of these rules is violating the spirit of these rules. There is no valid interpretation of a rule that permits bypassing it. "I followed the intent" after skipping a required step is not a defense - the steps exist because intent alone does not catch errors. This principle applies to every rule in both protocols.

**Mid-task reclassification:** If a task initially classified as Low reveals Elevated signals during execution, stop, reclassify as Elevated, and apply adversarial review from that point.

**Low risk self-check:** After completing the change, re-read it in full. Verify: (1) the change does exactly what was intended, (2) no obvious edge cases or errors are introduced, (3) no unintended side effects are present. If any concern arises during self-check, reclassify as Elevated and apply adversarial review.

### Common rationalizations to reject

| Rationalization | Why it fails |
|---|---|
| "This looks simple, I can do it directly." | "Looks simple" is not a Low signal. Simple-looking tasks are where unreviewed errors accumulate most often. |
| "I'm following the spirit of the rule, just not the letter." | Violating the letter is violating the spirit. No exceptions. |
| "It's only one file / a few lines." | Line count is not a risk signal. A one-line change to a shared utility has high blast radius. |
| "I already reviewed it myself." | Self-review is the direct-action self-check for Low risk. It does not substitute for Skeptic review on Elevated tasks. |
| "The Skeptic will catch any mistakes." | The Skeptic reviews Worker output. It does not excuse skipping risk classification or spawning a Worker. |
| "We're moving fast, we can skip review this time." | The protocol exists precisely for times when moving fast creates pressure to skip it. Speed is not a Low signal. |
| "This change is too minor to bother with a Worker." | Delegate on risk signals, not on size. The Worker overhead is small; the cost of an unreviewed error is not. |

### Approach by risk level

| Level | Delegation | Review | Declaration |
|---|---|---|---|
| Low | Direct action | Brief inline self-check | Silent |
| Elevated | Worker | Fresh independent Skeptic | Stated before starting |
| Elevated + Cleanup | Worker | Skeptic → `/simplify` → Skeptic (narrow) | Stated before starting |

### Declaration format

When classifying as Elevated, the main agent declares before acting:

```
Risk: Elevated - [specific signal]
Tier: 2 (role default)
Applying adversarial review.
```

---

## 1. Overview

The Skeptic Protocol is an adversarial review loop for multi-agent systems. A Worker implements; the primary agent spawns a fresh Skeptic to critique; if findings remain, the primary agent routes them to a new Worker. The primary agent drives the loop until a clean sign-off is achieved.

The core thesis: **the value of an adversarial reviewer is independence**. A reviewer who has already heard the implementer's justifications is no longer independent — they have been partially anchored to that framing. This is why the Skeptic is always a fresh invocation, never a continuation of a prior round. Workers cannot spawn subagents (platform constraint), so the primary agent is the sole orchestrator: it spawns Workers, spawns Skeptics, and routes findings between them. The Skeptic's independence is guaranteed by its fresh context — it sees only the output and the adversarial brief, never the Worker's reasoning process.

This pattern is applicable to any multi-agent system capable of invoking subagents or secondary model calls. The terminology used here is system-agnostic.

**Document hierarchy:** This is the canonical specification for The Skeptic Protocol. `~/.claude/CLAUDE.md` contains inline risk classification rules and a delegation decision table; procedural details are read from this document via trigger-condition pointers. When documents diverge, this document governs.

---

## 2. The Core Loop

**Architecture note:** Workers cannot spawn subagents - the spawn (`Agent`) tool is available only to the main (primary) session agent. This means the Skeptic loop is orchestrated by the main agent, not the Worker. Workers implement and return; the main agent handles review.

### Step-by-step

0. **Assess risk.** If Low, act directly with a brief inline self-check. If Elevated, declare the risk signal and proceed with the loop below.

1. **Primary agent spawns Worker** (background, general-purpose) with:
   - The task description and all relevant context
   - The adversarial brief verbatim (see Section 7)

2. **Worker implements** the task fully and returns its output to the primary agent.

   **If the Worker returns NEEDS_CONTEXT or BLOCKED (Step 2 variants):**
   - `NEEDS_CONTEXT`: the Worker could not proceed because specific information is missing. The primary agent determines whether that context can be obtained (from the codebase, prior session context, or the user). If it can: re-spawn the Worker with the missing context provided. If it cannot: escalate to the human with the Worker's stated gap.
   - `BLOCKED`: the Worker hit a hard blocker requiring an architecture decision or human judgment. Escalate immediately to the human with the Worker's blocker description. Do not spawn a Skeptic on incomplete work.
   - `DONE_WITH_CONCERNS`: proceed with Skeptic review as normal. The Worker's stated concerns become additional context for the Skeptic - surface them in the spawn prompt alongside the adversarial brief.

3. **Primary agent spawns a fresh Skeptic** (background, using the `skeptic` agent at `~/.claude/agents/skeptic.md`) with:
   - The adversarial brief verbatim
   - The Worker's complete output (inline or as file paths)
   - The resolved issues preflight list (empty on round 1; see Section 4)

   The agent file owns the classification rules, evaluation process, and sign-off format. The orchestrator's job is to supply the brief, the preflight list, and the artifact to review.

4. **Primary agent reads the Skeptic's findings.**
   - If no Critical or Major findings: sign-off is achieved.
     - If no Minor findings: report back.
     - If Minor findings are present: spawn a general-purpose agent (background) to apply them, passing the list of Minor findings and the relevant file paths. No follow-up Skeptic is required - Minors are by definition low-impact, and the Skeptic's classification already identified the issue. This applies regardless of file type; Minor-fix Workers are an intentional exception to the "modifies protocol or infrastructure files" Elevated signal. For Elevated + Cleanup tasks, run the Minor-fix agent before invoking `/simplify`. Wait for it to complete, then report back.
   - If Critical or Major findings remain: route them to a Worker.

5. **Primary agent spawns a new Worker** with:
   - The original task
   - The Skeptic's findings
   - The prior Worker's output (for context)
   - The session context

6. **Worker addresses findings** — fixes each Critical or Major finding, or documents a specific reason why it is not a real problem — and returns the revised output.

7. **Primary agent updates the resolved issues preflight list** with each addressed finding and its resolution.

8. **Primary agent spawns a NEW fresh Skeptic** — never a continuation of the prior Skeptic — with the revised output, the same adversarial brief, and the updated preflight list.

9. **Repeat steps 4–8** until the Skeptic grants sign-off:
   > "No unresolved Critical or Major findings. Sign-off granted."

10. **QA gate check (conditional).** Two paths, depending on whether the diff matches UI-visible trigger patterns:

    - **UI-visible changes (concurrent path):** When QA trigger patterns match a UI-visible diff, spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. If the Skeptic raises Critical/Major findings, enter the standard fix loop; QA re-runs after Skeptic sign-off is achieved. If QA fails after Skeptic sign-off, spawn a fix engineer and re-run QA only. See `content/sections/05-qa-gate.md` for the full concurrent QA spec.

    - **Non-UI changes (sequential path):** After sign-off is granted and any minor fixes are applied, check the QA gate condition (see METHODOLOGY.md §QA Gate). If the project has qa.md (resolved via `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback) with trigger patterns matching the diff, spawn `qa-engineer` before reporting back. QA failure routes back to an engineer for fixes, then re-runs QA.

    If no QA gate applies on either path, proceed directly to step 11.

11. **Primary agent reports back** with:
    - The final implementation
    - The full exchange log (round-by-round: findings, fixes, deferrals with reasoning)
    - The verbatim sign-off statement from the final Skeptic round
    - QA result (pass/fail) if the QA gate was triggered

---

## 3. State Management Rules

| Agent | Continuation rule | Rationale |
|---|---|---|
| Worker | New spawn each round — receives accumulated context via prompt | Cannot maintain context across invocations; the primary agent passes findings and prior output explicitly |
| Skeptic | Always a fresh invocation — never continued from a prior round | Needs adversarial independence; prior-round context anchors the reviewer |

**Violation of the Skeptic freshness rule degrades the protocol.** A Skeptic that has already heard the Worker's justifications will unconsciously apply lower scrutiny in subsequent rounds. Independence requires a clean context.

**Primary agent context accumulation:** The primary agent maintains the exchange log across rounds. When spawning each new Worker, it passes: the original task, the current Skeptic findings, the prior implementation output (or file paths to it), and the accumulated exchange log. Workers must not be expected to maintain state across invocations — the primary agent is the stateful coordinator.

**Worker output management:** For implementations producing large outputs, Workers should write results to files and return file paths rather than inline content. This keeps spawn prompts readable and auditable - a brief that embeds full implementation text is harder to review, increases copy-paste error risk when portions are excerpted for the Skeptic, and grows the exchange log past a useful size.

### Exchange log compression

The conductor maintains an exchange log across Skeptic rounds to enforce the 2-re-route escalation limit. In long-running sessions, this log can grow large. The conductor MAY compress the exchange log to preserve context space, provided the compressed format retains all metadata required for escalation correctness.

**Compression rules:**

1. **Always preserve in full:**
   - Round 1 (original plan + first Skeptic findings)
   - The most recent round
   - Any round containing a Critical finding that remains open

2. **Compress middle rounds** (rounds 2 through N-1, where N is the most recent round) into a single summary block:
   ```
   Rounds 2–{N-1} (compressed):
   - Rounds skipped: {count}
   - Findings raised and resolved: [{finding_id}, {finding_id}, ...]
   - Findings deferred: [{finding_id}: {rationale}, ...]
   - Round outcomes: [Round 2: sign-off, Round 3: findings remained, ...]
   ```

3. **Escalation metadata retention:** The compressed log MUST retain:
   - Every finding ID ever raised, its classification (Critical/Major/Minor), and its final resolution status
   - For each finding that was escalated or re-routed, the round number(s) in which it appeared
   - The total re-route count for each finding

4. **When to compress:** The conductor SHOULD apply compression after Round 3 sign-off, or earlier if the compressed log would exceed a single screenful or the preflight list can no longer fit in a single spawn prompt.

5. **Fresh Skeptic invariant:** Compression affects ONLY the conductor's internal exchange log. The Skeptic remains a fresh invocation for every round. The Skeptic never sees the compressed log — it receives only the current round's adversarial brief, preflight list, and artifact.

---

## 4. The Resolved Issues Preflight List

Before invoking each new Skeptic (rounds 2+), the primary agent prepends this block to the adversarial brief:

```
The following issues were identified and resolved in prior rounds. Do not
re-raise them unless you believe the resolution is genuinely insufficient:

[C1: <description of finding> → <resolution applied>]
[C2: <description of finding> → <resolution applied>]
[M1: <description of finding> → <resolution applied>]
...
```

The preflight list prevents the Skeptic from re-raising already-addressed findings as new Critical or Major items. It does not prevent the Skeptic from contesting a resolution — if the Skeptic believes a stated resolution is insufficient, it may re-raise the finding with an explicit explanation of why.

**Loop context extension:** When the Skeptic is invoked inside the `/implement-ticket` persistence loop, the conductor passes the findings_log entries (status=open or status=addressed) as the preflight list. The findings_log id field is used as the finding identifier for `[PREV: <id>]` tagging. The preflight list format is identical to the standard Section 4 format; the findings_log schema is the structured backing store.

---

## 4.5. Global-Context Input Set

Every Skeptic spawn prompt MUST include the following block in this order, after the adversarial brief and before the artifact under review:

```
## Global-context inputs

1. Architect plan: <absolute path to plan.md, OR "n/a - <enumerated reason>">
2. Brief / Plan tier artifact: <absolute path, OR "n/a - <enumerated reason>">
3. qa_criteria block (verbatim YAML, OR "n/a - <enumerated reason>")
4. Per-consumer impact table (verbatim, OR "n/a - <enumerated reason>")
5. Related files (list of absolute paths the diff touches OR is logically coupled to)
6. Diff under review: <git diff command OR file paths>
```

### Enumerated `n/a` rationale set

A bare `n/a` is invalid. Only the following strings are valid `n/a` values. Any other string triggers Skeptic Step 0 BLOCKED.

- `n/a - Trivial direct edit`
- `n/a - permission-blocked carve-out`
- `n/a - Brief tier (per-consumer lives in architect plan path above)` (per-consumer table only, on Skeptic-on-Brief)
- `n/a - non-shared-utility surface (importer count below 5 threshold)` (per-consumer table only)
- `n/a - architect plan deferred to Plan-tier second pass` (Brief field only)
- `n/a - Skeptic-on-Brief (Brief is the artifact under review)` (Brief field only)
- `n/a - assembled Plan review (per-unit plans listed inline)` (architect plan field only, on Plan-tier second-pass)

### Review-environment freshness precondition

A Skeptic comparing a PR against a base branch MUST work from a live, synchronized git state - never a stale local checkout whose `main` may lag the remote or reflect files from unrelated branches. Two failure modes to prevent: (1) a reviewer that sees fewer files than the live PR (stale local tree) raises "X is missing" when X was added in a commit the reviewer cannot see; (2) a reviewer that diffs against `FETCH_HEAD` or a stale symbolic ref picks up files from other in-flight PRs, producing spurious "was reverted" or "renamed back" findings.

**Required approach:** Use `gh pr diff <n>` or `gh pr view <n> --json files,headRefName,baseRefName` to obtain the canonical PR diff. If using local git, run `git fetch origin <base> <head>` first and diff fully-qualified remote refs (`origin/<base>..origin/<head>`) - never `main..HEAD` or `FETCH_HEAD` unless you have just fetched and confirmed the ref resolves to the expected commit.

**Commit-SHA attestation (when reviewing a PR against a base branch):** When the Skeptic is reviewing a PR diff - not an inline/non-PR worktree diff - it MUST state the head commit SHA and base commit SHA it reviewed. Unified format: `Reviewed: <base-sha>..<head-sha> - [files/components examined]`. The conductor confirms these match the live PR before acting on the findings. A Skeptic output that omits the SHA range on a PR review is treated as unverified and the conductor re-spawns with explicit instructions to include it. For inline/non-PR reviews (the common `/implement-ticket` worktree case), the standard `Reviewed: [files/components examined]` form is used; the Skeptic MAY optionally include the commit SHA(s) under review.

### Skeptic Step 0 - Input validation (BLOCKED on incomplete inputs)

Before reading any artifact or producing any findings, the Skeptic verifies the Global-context input set is complete and well-formed:

1. All 6 fields are present.
2. Any `n/a` value is one of the enumerated strings above.

If either check fails, the Skeptic returns immediately with:

```
BLOCKED - Global-context input set incomplete: <missing or invalid fields listed>
```

No review content follows the BLOCKED line. The Skeptic does NOT produce findings, a "Reviewed:" line, or a sign-off.

**BLOCKED return semantics for the conductor:**

- `loop-state.json` `last_phase_action` is set to `skeptic_blocked_input`.
- Resume re-spawns the Skeptic with corrected inputs; iteration counter does NOT advance.
- Step-0 BLOCKED is conductor-fault, not engineer-fault. Does NOT count toward the 3-fix-pass re-route cap (Section 5). Consumes a separate counter capped at 3, tracked in a per-unit-slug counter file.
- The CONDUCTOR fixes the spawn brief, NOT the Engineer.

**Per-unit-slug counter files (Q-C=C1):**

The conductor tracks Step-0 BLOCKED returns per spawn target using counter files at `.agentic/.spawn-block-counter-<unit_slug>`. For single-unit spawns, `unit_slug` is `single`. Each BLOCKED return increments the counter. After 3 BLOCKED returns on the same target, the conductor escalates to the human operator and does NOT retry.

Cleanup: after Phase 6 loop terminates with sign-off, run `rm -f .agentic/.spawn-block-counter-*` to clear all counter files for the session.

### Plan-tier second-pass overflow fallback

When the combined Global-context input set for a Plan-tier second-pass Skeptic exceeds 60K input tokens, the conductor switches to per-unit second-pass mode: one Skeptic per unit (each with that unit's Global-context subset) plus one lightweight integration Skeptic receiving the combined findings list only (not the full Global-context). Documented in `content/sections/03-planning-artifacts.md`. The 60K limit is a prompt-assembly threshold for review focus, not a model context constraint; it applies regardless of the underlying model's window size, because adversarial review signal degrades as the assembled prompt grows.

### Supplemental-context block for multi-dimensional supplemental reviewers

`security-auditor` and `perf-analyst` in the multi-dimensional fan-out (`multi-dimensional` skeptic_strategy, see Section 13) receive a **Supplemental-context** block instead of the Global-context input set. This block uses a different heading (`## Supplemental context`) and is informational only - Step 0 BLOCKED enforcement does NOT apply.

```
## Supplemental context (informational, NOT Step-0 enforced)

- Architect plan: <absolute path>
- Brief / Plan tier artifact: <absolute path or omitted>
- qa_criteria block: <verbatim YAML or omitted>
- Per-consumer impact table: <verbatim or omitted>
- Related files: <list>
- Diff under review: <as today>
```

Fields may be omitted without triggering any block. The `n/a` enum does not apply. See `content/agents/security-auditor.md` and `content/agents/perf-analyst.md` for the Reading-your-spawn-prompt item enumerating this block.

**Heading distinction:** `## Global-context inputs` is the correctness-Skeptic heading (Step-0 enforced). `## Supplemental context` is the supplemental-reviewer heading (no enforcement). These headings are lexically distinct by design; a future reviewer class that requires a third contract receives its own heading rather than reusing either existing one.

### `visual_conformance` enforcement (auto-Critical rule)

When reviewing a Brief or architect plan whose unit is UI-visible AND the ticket text contains an "Expected Result" block, a "Visual spec" block, or an equivalent enumeration of visible properties (colors, positions, copy, typography, element presence), the Skeptic raises a **Critical** finding if `qa_criteria.scenarios[]` does not contain at least one scenario with `method: visual_conformance`, a verbatim `source_quote`, and at least one `expected_visual_claims[]` entry. Individual claims marked `advisory: true` are opted out of auto-fail and auto-Critical enforcement but remain auditable in the review surface. This rule does NOT fire when `qa_skip` is set to one of the 5 valid enum values. The canonical statement of the schema, field rules, and trigger predicate lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### `accessibility` enforcement (auto-Critical rule)

When reviewing a Brief or architect plan whose unit is UI-visible AND the unit is Elevated AND `qa_skip == null`, the Skeptic raises a **Critical** finding if `qa_criteria.scenarios[]` does not contain at least one scenario with `method: accessibility`. `wcag_level` defaults to `AA` - no additional field is required when targeting AA. This rule does NOT fire when `qa_skip` is set to one of the 5 valid enum values. When both `wcag_level` and `axe_tags` are explicitly set on the same scenario, the Skeptic raises a **Minor** finding (redundant declaration - explicit `axe_tags` wins at runtime; remove `wcag_level` or `axe_tags` to eliminate the redundancy). The canonical statement of the schema, field rules, and trigger predicate lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### `perceptual_diff` enforcement (auto-Major rule)

When reviewing a Brief or architect plan where `.agentic/config.json` has `perceptual_diff_enabled: true` AND the unit is UI-visible AND the ticket text contains a visual spec (Expected Result block, design mockup reference, explicit "matches design" criterion), the Skeptic raises a **Major** finding if `qa_criteria.scenarios[]` does not contain at least one scenario with `method: perceptual_diff`. This rule is opt-in: when `perceptual_diff_enabled` is absent or `false`, this rule does NOT fire. The canonical statement of the schema, field rules, and trigger predicate lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### `viewport` enforcement (auto-Major rule, Skeptic judgment)

When reviewing a Brief or architect plan whose unit is clearly responsive - mobile breakpoint changes, new Tailwind responsive prefixes touching layout, explicit "works on mobile" or "responsive" success criterion - the Skeptic raises a **Major** finding if `qa_criteria.viewport` is absent, null, or `[desktop]`-only. This is a **Skeptic judgment call, not a regex**: the Skeptic reads the ticket text and architect plan holistically and raises the finding only when the work is clearly responsive. Trying to mechanize this with keyword matching produces false positives (prose words like "automobile" or "Markdown" containing responsive-prefix patterns) and misses synonyms ("phone layout", "small screens", "narrow viewport"). The canonical statement of the schema and viewport canonical sizes lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### `theme` enforcement (auto-Major rule)

When reviewing a Brief or architect plan where `.agentic/config.json` has `theme_aware: true` AND a scenario's method is `visual_conformance`, `accessibility`, or `motion` AND the `theme` field is absent on that scenario, the Skeptic raises a **Major** finding. This rule is opt-in: when `theme_aware` is absent or `false`, this rule does NOT fire. When `theme` is present on any scenario whose method is NOT in `{visual_conformance, accessibility, motion}` (i.e., `perceptual_diff`, `browser`, `api`, or `runtime-required`), the Skeptic raises a **Critical** finding - `theme` is restricted to these three methods only. Valid `theme` values are `light`, `dark`, and `both`; any other value is a Major finding. The canonical statement of the schema, field rules, and trigger predicate lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### `story_id` enforcement (auto-Critical for compatibility)

When reviewing a Brief or architect plan where any scenario has `story_id` set AND that scenario's method is NOT `visual_conformance` or `accessibility` (i.e., the method is `perceptual_diff`, `browser`, `api`, or `runtime-required`), the Skeptic raises a **Critical** finding regardless of config state. Rationale: `perceptual_diff` would have ambiguous baseline-path semantics when the story render and live-app render differ; `api` and `runtime-required` have no browser surface; `browser` interaction flows do not compose with Storybook's isolated component render. `story_id` on a config-disabled project (`storybook_enabled: false` or absent) while using a compatible method (`visual_conformance` or `accessibility`) is NOT a plan-time finding - the runtime gate (INCONCLUSIVE with operator message) handles that case. The canonical statement of the schema, field rules, and trigger predicate lives in `content/references/planning-artifacts.md` (Field guidance, QA criteria entry) - this section mirrors only enough to ensure a Skeptic reviewer cannot miss the rule.

### FE-discipline findings (auto-apply on FE diffs)

**Trigger:** the diff touches one or more files matching
`**/*.{tsx,jsx,vue,svelte,astro,css,scss,html,mdx}` AND the file is NOT in the
exclusion set: `content/**`, `docs/**/*.{mdx,html}`,
`**/docs/**/*.{mdx,html}`, `**/*.stories.{tsx,jsx,ts,js}`,
`**/*.test.{tsx,jsx,ts,js}`, `**/*.spec.{tsx,jsx,ts,js}`.

When the trigger fires, the Skeptic applies the findings table below. Every
finding MUST cite (a) the file:line and (b) the matching section in
`content/references/frontend-discipline.md`. Findings missing either citation
are invalid.

| Finding ID | Severity | Trigger condition |
|---|---|---|
| `semantic-html-misuse` | Major | non-semantic element used where a native semantic element exists (e.g., `div onClick` instead of `button`) |
| `aria-needs-no-aria` | Major | ARIA attribute added to an element that already has native semantics (e.g., `<button role="button">`) |
| `missing-focus-management` | Major | modal/drawer/popover-style component lacks focus trap or focus restore to trigger |
| `hardcoded-token-instead-of-design-token` | Major | hardcoded color/spacing/font value in a codebase where a token system is detected (heuristics in `content/references/frontend-discipline.md` §6); the finding MUST cite which heuristic triggered detection |
| `missing-keyboard-support` | Major | element with `onClick` handler is not a native interactive element and lacks both `onKeyDown` handler and `tabIndex` |
| `motion-not-reduced-motion-aware` | Major | CSS animation or transition present without a `prefers-reduced-motion: reduce` media query guard |
| `outline-none-without-replacement` | Major | `outline: none` or `outline: 0` applied without a `:focus-visible` replacement focus indicator |
| `missing-responsive-class` | Minor | fixed-width or single-breakpoint sizing on a surface that is otherwise responsive (often intentional on desktop-only surfaces; Skeptic judgment required) |

### motion enforcement (auto-Major)

**Trigger:** `.agentic/config.json` has `motion_aware: true` AND the unit is UI-visible AND risk is Elevated AND `qa_skip == null` AND no scenario with `method: motion` is present in `qa_criteria.scenarios`.

When all trigger conditions hold, the Skeptic raises a **Major** finding. Rationale: a motion-aware project has declared that reduced-motion behavior is a testable concern; omitting a `motion` scenario from an Elevated UI-visible change leaves the `prefers-reduced-motion: reduce` path unverified. The finding must cite `content/references/frontend-discipline.md` §5 (Reduced motion).

This rule is opt-in: when `motion_aware` is absent or `false`, this rule does NOT fire. When the unit is not UI-visible (e.g., `qa_skip: pure-backend-library`), this rule does NOT fire.

Note: P2 motion scenarios do not support `story_id`; see `content/references/planning-artifacts.md` per-method table.

---

## 5. Escalation Protocol

If the same finding is contested for **2 or more re-routes** without resolution, the primary agent must stop and escalate to a human operator with:

```
Unresolved after N re-routes. Contested finding: [exact finding text].
Worker position: [Worker's documented reasoning for deferral].
Skeptic position: [Skeptic's repeated objection].
Human decision needed.
```

The primary agent tracks contested findings across rounds. After 2 re-routes on the same finding without resolution, it stops routing and escalates. This prevents infinite loops on genuinely ambiguous findings.

**Re-route counter:** The primary agent tracks each finding by its text across all rounds. If the same finding appears in 2 or more Skeptic responses without the Worker resolving it (regardless of whether the rounds are consecutive), the re-route limit is met and the finding must be escalated. Use the finding's text as the identifier.

### Complexity-based round limit

The number of permitted Skeptic rounds scales with task complexity:

- **Simple/targeted changes** - a unit that meets the simple/targeted-unit mechanical metric (`content/sections/04-risk-classification.md` §Simple/targeted unit (mechanical metric)): Skeptic loop is capped at **1 round**. This overrides the 2-re-route rule above for this category. The Skeptic still runs at least once - this lever caps loop depth, it does not skip review. If the Skeptic raises Critical or Major findings after round 1, escalate directly to the human rather than spawning another Worker. The human decides whether to fix and re-review or accept as-is.
- **Standard Elevated changes**: the 2-re-route rule above applies - if the same finding appears in 2 or more Skeptic responses without resolution, escalate to the human.

**Uncertainty rule for categorization:** The simple/targeted-unit metric is computed mechanically from the actual diff, not estimated. If the unit fails any clause of the metric - touches more than 1 file (or more than 1 file plus its colocated test/snapshot), exceeds 40 changed lines, or matches any of the 5 Mandatory Tier-3 escalation signal categories - apply the standard Elevated round limit (the 2-re-route rule). "Looks simple" is not a sufficient basis for the simple/targeted category; the metric's clauses are the only basis.

**Loop contract override:** When operating inside the `/implement-ticket` persistence loop (Phase 6), the loop contract overrides this rule. One re-raise after a claimed fix (convergence failure as defined in the loop contract) is sufficient to trigger escalation. The loop already consumes iteration budget on each fix pass; requiring a second re-raise would waste an additional pass on a finding the Engineer has already failed to address. Outside the loop context (ad-hoc Skeptic re-routes not inside a named loop), the 2-re-route rule applies unchanged.

### Worker decomposition rule

If a Worker discovers mid-task that its work requires decomposition into independent sub-tasks, it should note this and return its partial output with an explicit decomposition request. The primary agent then handles parallel decomposition — spawning multiple Workers and synthesizing results — before routing the assembled output back through Skeptic review.

### Cognitive surrender check (rubber-stamp guard)

A Skeptic that signs off on the same diff across two or more iterations with **zero findings at any classification** (no Critical, no Major, no Minor) is a possible **rubber-stamp** signal. The reviewer may have surrendered cognition - skimming the artifact, anchoring on the Worker's output, and granting sign-off without independently re-reading the diff. This is the Shaw / Nave "cognitive surrender" failure mode: uncritical reliance on AI-generated output, bypassing the deliberation step the protocol depends on.

To guard against this, when a clean two-iteration agreement occurs, the Skeptic must include an explicit **audit note** as a Minor finding in its sign-off. The audit note is a one-line attestation that the diff was independently re-read end-to-end with the named heuristics applied. Example:

```
Minor: Audit note - re-read all 3 files end-to-end; checked for
        spec drift, missing error paths, and intent-layer drift; no
        findings.
```

Without that audit note, the conductor treats clean two-iteration agreement as suspect and requests another pass with a fresh Skeptic. This is distinct from cognitive offloading (strategic delegation during deliberation, which is the protocol's intended mode) - the audit note is the evidence that deliberation actually occurred.

Audit-note Minors are bookkeeping rather than diff-level findings; they are exempt from re-raise and convergence-failure detection in `/implement-ticket` Phase 6.

The audit-note mechanism is the **primary** defense against the rubber-stamp / cognitive-surrender failure mode. The calibration sampling described in Section 14 is a **secondary** backstop that detects drift in aggregate over time. The two mechanisms compose: per-spawn discipline lives in the audit note; long-horizon drift detection lives in the meta-Skeptic sampling pass and the `agentic-calibrate` queryable surface.

---

## 6. Findings Classification

**Critical** — Blocks sign-off. Must be resolved before sign-off can be granted. Examples: security vulnerabilities, correctness failures, data loss paths, unauthorized access vectors.

**Major** — Should be fixed. Blocks sign-off unless the Worker provides a compelling documented reason to defer. Examples: missing error handling on critical paths, edge cases that cause silent failures, design issues that will be expensive to fix later. Also Major: the Worker deferred a decision it had sufficient context to make — i.e., punted to the main agent or the Skeptic on a question the spec, requirements, or available information already resolved. Workers must make decisions when they have the context to do so; using adversarial review as a substitute for deciding is a Major deficiency.

**Minor** — Optional. Never blocks sign-off. When Minor findings are present at sign-off, the primary agent spawns a general-purpose agent (background) to apply them - no follow-up Skeptic review is required, regardless of file type. Minor-fix Workers are an intentional exception to the "modifies protocol or infrastructure files" Elevated signal. Examples: style improvements, non-critical logging gaps, minor documentation issues, low-impact optimizations.

- **Missing telemetry emit at an instrumented boundary.** When a conductor spawns engineer/skeptic/qa and `.agentic/events.jsonl` does not contain the corresponding `spawn_start`/`spawn_complete` events (or, for ad-hoc sessions, the hook-emitted `spawn_start` with `data.source:"hook"`) for that boundary, flag as **Minor**. Does not block sign-off; surfaced for awareness so cost dashboards stay accurate. (`conductor_direct` is deprecated and no longer emitted; its absence is not a finding.)

The Skeptic must classify every finding. Unclassified findings are treated as Major by default.

**Spec deviation is a finding.** When a Worker implements against an Architect plan, any deviation from the plan's "API / interface design" section is a Skeptic finding. Classify as **Major** by default (the spec was the contract; the Worker did not honor it), or **Critical** if the deviation changes externally observable behavior, breaks a caller, or introduces a security/correctness regression. A documented Worker deviation with explicit rationale may downgrade to Minor, but only if the Skeptic can affirmatively state all three of the following in its sign-off: (1) the Worker's stated rationale for the deviation is technically correct - the Skeptic has verified the claim of infeasibility, conflict, or impracticality, not merely accepted the Worker's assertion; (2) the plan's downstream assumptions still hold under the deviation - no other part of the plan depends on the original spec in a way the deviation breaks; (3) the deviation does not change externally observable behavior, break a caller, or introduce a security/correctness regression - if any of these are present, the finding is Critical, not Minor. If the Skeptic cannot affirmatively state all three, the finding remains at least Major. Silent deviation is never acceptable - the Worker must state the deviation explicitly regardless of rationale. See Section 11 for the mandatory sign-off format when a spec deviation is downgraded.

When reviewing, check spec compliance first - does the implementation do what was asked? Then check code quality. Surface spec compliance issues before stylistic concerns in the findings list. Spec compliance gaps at the Critical or Major level make code quality moot.

**QA-fix iteration regression verification.** When the Skeptic runs in parallel with a re-spawned qa-engineer (QA-fix iteration in the concurrent QA flow, or Phase 6b sequential QA fix engineer), the verification additionally checks the `qa-regression-obligation.md` contract: the engineer added a unit/integration/e2e test for the failing scenario (id, description), OR documented an exception in `.agentic/qa-regressions.md` with a reason. This is symmetric to the Skeptic-finding regression rule in `content/references/regression-test-obligation.md`. Missing test without explanation and without a curated-index entry is a Major finding. Canonical statement in `content/references/qa-regression-obligation.md`.

**Existential-negative findings require evidence.** An existential-negative finding is any finding that asserts absence, non-completion, reversion, or relocation - "X is missing", "Y was not done", "Z was reverted", "the file was moved back", "the guard does not exist". These findings are not self-verifying: they depend entirely on the reviewer's git state being synchronized and correct. A Skeptic MUST NOT classify an existential-negative claim as Critical or Major unless it cites the exact command, ref, and literal output that substantiates it (e.g., `git ls-files origin/main..origin/<head> | grep <path>` showing the file absent, or `gh pr diff <n>` excerpt showing the deletion). Without raw evidence, the claim is a hypothesis. Hypotheses MUST be downgraded to Minor (flagged for conductor verification) with the note "unverified - requires conductor spot-check against live PR state before acting." The failure mode this prevents: a Skeptic working from a stale or contaminated tree raises a blocking Critical on work that is present and correct in the live PR, causing the conductor to revert or re-implement code that never needed changing. "The file wasn't in my diff" is not evidence of absence - it is evidence that the reviewer's diff may be incomplete.

### Review depth

Adversarial review applies whenever risk is classified as Elevated. The main agent always uses a fresh independent Skeptic — there is no degraded self-review path for Elevated work. The exchange log is mandatory for all Elevated tasks. The escalation protocol is active for all Elevated tasks.

---

## 7. The Adversarial Brief Requirement

The adversarial brief defines the threat model the Skeptic must adopt. It is written by the primary agent (or human operator) and must be passed to the Worker verbatim.

**The primary agent must use the brief verbatim when invoking each Skeptic. The primary agent must not soften, summarize, or editorialize the brief.** The brief is an instruction to the Skeptic, not a suggestion. Softening it degrades adversarial independence.

**Global-context input set (Section 4.5):** Every Skeptic spawn prompt must also include the Global-context input set (architect plan, Brief/Plan artifact, qa_criteria block, per-consumer impact table, related files, diff under review) in addition to the adversarial brief. See Section 4.5 for the canonical block format, the enumerated `n/a` rationale set, and Step-0 BLOCKED return semantics.

The brief should be specific to the domain and threat model of the work being reviewed. Generic briefs produce generic findings.

**Brief extension:** The primary agent may extend a template brief with domain-specific additions: *"In addition to the above, also consider: [domain-specific concerns]."* The primary agent must never remove or soften any language from the selected template. Extension is additive only.

**Active search requirement:** The Skeptic agent enforces this internally - Step 5 of its evaluation process is a brief coverage check, and the required "Active search:" line is part of its sign-off format. The orchestrator does not need to inject this instruction. Providing the adversarial brief is sufficient - the agent applies it actively by design.

---

## 8. Domain-Specific Adversarial Brief Templates

These are starting templates. Adapt them for your specific domain, threat model, and implementation.

**Smart contracts:**
> "A financially motivated attacker has the source code and will look for: reentrancy, access control gaps, signature replay attacks, fee bypass, and any path to transfer an asset without valid authorization. Assume the attacker will read every public function, every state variable, and every event. Assume they will attempt direct contract interaction, bypassing any app-layer controls."

**Authentication and session management:**
> "An attacker controls one compromised account and one compromised device. What can they access, modify, or forge? Look for: session fixation, token replay, insufficient binding between session and device, privilege escalation paths, and any state the server trusts without re-verifying."

**API endpoints:**
> "An attacker can send arbitrary HTTP requests including malformed inputs, missing fields, oversized payloads, replayed tokens, and concurrent requests designed to hit race conditions. Look for: missing input validation, authentication that can be bypassed, rate limiting gaps, and any endpoint that mutates state without idempotency guarantees."

**Cryptographic verification:**
> "An attacker will try to produce a valid-looking signature without the private key. They will also try replay attacks with previously valid signatures. Look for: weak randomness in nonce generation, missing domain separation, algorithm confusion attacks, and any verification path that skips a check under certain conditions."

**DB schema, migrations, and data models:**
> "Is the migration idempotent — what happens if it runs twice? What is the state of the data after partial failure, and can it be recovered without data corruption? Look for: double-run risk (non-idempotent operations), partial failure paths (what if the migration fails halfway?), data loss risk (irreversible column drops, non-nullable additions to tables with existing data), and rollback path (is there a down migration, and is it tested?)."

**Data pipelines and async jobs:**
> "What happens if this job runs twice? What happens if it crashes halfway? What is the state after partial failure, and can it be safely retried without double-processing or data corruption? Look for: non-idempotent operations, missing rollback logic, state that can diverge between systems, and silent failure modes."

**Document synthesis, architecture, and planning:**
> "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?
>
> For architect plans and orchestration-planner output, additionally verify the Open Questions / Deferred defaults split: (a) every item under 'Open Questions' must meet at least one condition - no derivable default, OR irreversible, OR load-bearing fork; (b) every item under 'Deferred defaults' must meet all three conditions - reversible, default derivable, not a load-bearing fork. A reversible+defaultable item hiding in 'Open Questions' (manufactures a false gate) is a Major finding. An irreversible or load-bearing item hiding in 'Deferred defaults' (silently bypasses the gate it requires) is a Major finding. When neither section is present on an artifact that has parked choices, flag absence of the expected structure as a Minor finding."

**General code review:**
> "Assume this code will be deployed to production and maintained by engineers who did not write it. Find: logic errors, edge cases that cause silent failures, missing error handling, incorrect assumptions about input ranges or ordering, and any assumption that will break under realistic load or adversarial input."

**When reviewing a Worker that implemented against an Architect plan:** In addition to the above, verify that the Worker's output matches the plan's "API / interface design" section exactly. Any deviation is a finding (Major by default, Critical if behavior-changing). A deviation may downgrade to Minor only if the Skeptic can affirmatively state all three criteria in its sign-off: (1) the Worker's rationale is technically verified (not just accepted); (2) no downstream plan assumptions are broken by the deviation; (3) the deviation does not change externally observable behavior, break a caller, or introduce a security/correctness regression. If all three cannot be stated affirmatively, the finding remains at least Major. Silent deviation from the spec is always at least Major.

---

## 9. Primary Agent Orchestration Posture

The primary agent's role is coordination, not implementation. It stays available and responsive at all times. It delegates non-trivial work to Workers and orchestrates Skeptic review of the results.

**The primary agent drives the Skeptic loop.** It spawns Workers, reads their output, spawns fresh Skeptics, reads their findings, and routes findings back to Workers. This is conductor work — the primary agent does not implement, but it does actively manage the review cycle.

**The primary agent never implements directly** unless the task is Low risk: a single-file read, a one-line edit, a factual answer retrievable from memory without any risk of error.

**Multiple Workers can run concurrently** on independent tasks. The primary agent tracks their state and synthesizes results when they return. Concurrency is the primary performance lever — use it whenever tasks are independent.

**The primary agent is a conductor, not an implementer.** Its value is in decomposing work correctly, writing precise adversarial briefs, routing findings accurately, and making good decisions when escalation is required. It should resist the temptation to implement directly even when implementation looks simple - simple-looking tasks are often where unreviewed errors accumulate.

### Review scope: decompose implementation, not review

Workers are decomposed into focused atomic units ("one agent, one task, one prompt"). Skeptic review is scoped differently - for effectiveness, not for symmetry with Workers:

- **Independent elevated units:** one Skeptic per unit. The diff is small, review is fast, findings are high-signal.
- **Interdependent elevated units** (cross-file or cross-component consistency required): one Skeptic reviewing the combined diff from all related Workers. This integration Skeptic replaces per-unit Skeptics for these units. The most dangerous bugs emerge from interactions between components - a per-unit Skeptic cannot see them.
- **Low-risk units:** no Skeptic. Direct action with self-check.

The integration Skeptic receives the same adversarial brief (Section 7) and follows the same sign-off format (Section 11). The only difference is scope: it reviews the combined output of multiple focused Workers rather than a single Worker's output.

---

## 10. When to Use This Protocol

Use The Skeptic Protocol whenever risk is classified as Elevated (see Section 0). Especially:

- **Anything hard to reverse:** deployed smart contracts, database schema migrations, published API contracts, auth system changes.
- **Anything cryptographic:** signature schemes, key derivation, nonce generation, verification logic.
- **Anything with concurrent state:** async jobs, event queues, multi-step transactions, distributed state that can diverge.
- **Anything at a trust boundary:** user input handling, external API integration, permission checks, session management.
- **Any implementation where a silent failure would not be immediately visible:** background jobs, data pipelines, audit log writes.

Do not use it for Low risk work: reading a file, answering a factual question, renaming a variable, renaming or moving a file (unless it is a protocol or infrastructure file, unless other files reference the renamed path, or unless the file's name or path has behavioral significance by convention), or any task where the output is immediately and obviously verifiable by inspection.

---

## 11. Output Format

### Worker output (each round)

Each Worker invocation returns:

**1. Final implementation** — the complete revised output. Not a diff. The full artifact, or file paths to it if the output is large. If the Worker cannot return a complete implementation, it returns a status of `NEEDS_CONTEXT` or `BLOCKED` (as defined in the engineer agent) instead. Section 2 defines the conductor's response path for each of these statuses.

**2. Round summary** — what was changed and why, for the primary agent's exchange log:
```
Changes made:
  C1 (finding title) → fixed by [description of fix]
  M1 (finding title) → fixed by [description of fix]
  M2 (finding title) → deferred: [documented reasoning]
```

### Skeptic output (each round)

The structured sign-off format is required for every Skeptic response, whether findings exist or not:

```
Reviewed: [files/components examined]
  (For PR reviews: Reviewed: <base-sha>..<head-sha> - [files/components examined])
Findings: Critical: N, Major: N, Minor: N
[Each finding on its own line: Critical - description (file:line or region)]
If all counts are zero, write instead: Findings: No findings.
[If any Minor finding is a spec-deviation downgrade, include the three-criterion "Spec deviation downgrade justification" block here - see format below]
Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.
No unresolved Critical or Major findings. Sign-off granted.
```

When any Minor finding is a spec-deviation downgrade, the following block must also appear in the sign-off, once per downgraded finding:

```
Spec deviation downgrade justification (if any Minor finding is a spec deviation):
For [finding ID]:
(1) Worker's rationale verified: [specific verification the Skeptic performed]
(2) Downstream plan assumptions preserved: [confirmation no other plan element depends on the original spec in a way the deviation breaks]
(3) No externally observable behavior change, broken caller, or security/correctness regression: [affirmative statement]
```

The "Reviewed" and "Active search" lines are mandatory even when findings are zero — they are evidence that review occurred.

### Primary agent exchange log

The primary agent accumulates the exchange log across all rounds:

```
Round 1:
  Skeptic findings: [C1: ..., M1: ..., Minor: ...]
  Worker actions: [C1 fixed by ..., M1 fixed by ..., Minor: deferred, low priority]

Round 2:
  Skeptic findings: [M2: ...]
  Worker actions: [M2 fixed by ...]

Round 3:
  Skeptic findings: none
  Sign-off granted.
```

#### Example: compressed 4-round exchange log

```
Round 1:
  Skeptic findings: [C1: missing input validation, M1: inconsistent error handling, Minor: typo in comment]
  Worker actions: [C1 fixed by adding validate_input(), M1 fixed by unifying error format, Minor: deferred]

Rounds 2–3 (compressed):
  - Rounds skipped: 2
  - Findings raised and resolved: [M2: missing docstring on validate_input]
  - Findings deferred: []
  - Round outcomes: [Round 2: findings remained, Round 3: sign-off]

Round 4 (most recent):
  Skeptic findings: [M3: test coverage gap in edge case]
  Worker actions: [M3 fixed by adding test_validate_input_empty_string]
```

### Sign-off validation

The primary agent treats a Skeptic response as a valid sign-off only when it contains all four mandatory elements as distinct lines: (a) a line beginning "Reviewed:", (b) a line beginning "Findings:", (c) an "Active search:" line, and (d) the phrase "No unresolved Critical or Major findings. Sign-off granted." A response containing only the phrase "Sign-off granted" without the other three elements is format-noncompliant and triggers a format re-invocation (spawn a new Skeptic with explicit format instructions). This re-invocation is not counted as a new adversarial round. (e) Conditionally: if any Minor finding in the Findings list is marked as a spec-deviation downgrade, the sign-off must also contain the three-criterion enumeration block specified above for each such finding. A sign-off that omits this block when required is format-noncompliant and triggers the same format re-invocation. (f) For PR reviews specifically: the "Reviewed:" line must include the `<base-sha>..<head-sha>` range (see §Review-environment freshness precondition). A PR-review sign-off that uses `Reviewed: [files only]` without the SHA range is format-noncompliant.

**Format re-invocation limit:** Format re-invocations are limited to 3 attempts. If the Skeptic's response remains format-noncompliant after 3 re-invocations, the primary agent escalates to the human with the last Skeptic response verbatim.

**Irreversible changes:** Workers must not apply irreversible changes before Skeptic sign-off. Workers that must stage irreversible changes as part of implementation must write a revert procedure in their return output before applying those changes. If the Skeptic subsequently flags Critical issues, the primary agent instructs the Worker to execute the revert procedure before further changes.

---

## 12. The Cleanup Path (`/simplify` Integration)

The standard Elevated workflow (Worker → Skeptic) is the default for all Elevated tasks. The **Elevated + Cleanup** tier extends this workflow with an automated cleanup pass and a narrow-scope second review. It is reserved for substantial implementations where code hygiene matters.

### Workflow

```
Worker → Skeptic (sign-off) → /simplify → Skeptic (narrow scope)
```

1. The Worker implements the task and returns its output.
2. The primary agent spawns a fresh Skeptic for adversarial review (standard Elevated flow).
3. After Skeptic sign-off is achieved, the primary agent invokes `/simplify` on the implementation. `/simplify` is a bundled Claude Code skill — no installation or setup needed. It spawns three parallel review agents (code reuse, code quality, efficiency), reads recently changed files, aggregates findings, and applies fixes automatically. An optional focus can be provided: `/simplify focus on memory efficiency`.
4. After `/simplify` completes, the primary agent spawns a **second Skeptic** with a narrow scope — it reviews only the `/simplify` diff, not the full implementation.

### Trigger signals

Use Elevated + Cleanup when the implementation is substantial enough that code hygiene becomes a real concern:

- **Multi-file feature implementations** — not just multi-file config changes or renames, but implementations that introduce meaningful new logic across files
- **Significant new code volume** — the Worker created substantial new logic, not just wiring or boilerplate
- **Unfamiliar codebase area** — the Worker may have missed existing patterns, utilities, or abstractions to reuse
- **User explicitly requests polish or quality focus** — e.g., "make sure this is clean", "production quality"

When none of these signals are present, use standard Elevated (Worker → Skeptic). The cleanup path is the extended option, not the default.

### Second Skeptic adversarial brief

The second Skeptic receives a narrow behavioral-preservation brief, not a full architectural audit:

> "Here is the code before and after `/simplify` cleanup. Did the cleanup preserve behavior? Did it introduce any defects? Focus on: behavioral equivalence, accidental deletion of logic or error handling, changed control flow, and any semantic differences between the before and after versions. This is a focused behavioral preservation check — do not re-audit the full implementation."

The second Skeptic uses the same sign-off format (Section 11) and the same findings classification (Section 6). The same escalation rules apply if Critical or Major findings are raised.

### Declaration format

When classifying as Elevated + Cleanup, the main agent declares before acting:

```
Risk: Elevated + Cleanup - [specific signal]
Tier: 2 (role default)
Applying adversarial review with /simplify cleanup pass.
```

---

## 13. Multi-Dimensional Review (`multi-dimensional` strategy)

For high-stakes Elevated units - specifically those in security-sensitive domains (auth, payments, data migrations, crypto, secrets management) - the conductor MAY use the `multi-dimensional` skeptic_strategy instead of the standard single-Skeptic flow. This strategy is the review analog of the `/simplify` fan-out pattern: rather than serializing correctness, security, and performance review, all three happen in parallel on the same diff.

### When to use

Use `multi-dimensional` when two conditions hold:
1. The unit is Elevated risk with a security-sensitive domain signal (auth, payments, crypto, data migrations, secrets).
2. There is meaningful non-trivial logic - i.e., a correctness bug and a security flaw could plausibly coexist undetected without separate specialist review.

Standard single-Skeptic review remains the default. `multi-dimensional` is the high-stakes extension, not a replacement for routine Elevated units.

### Workflow

```
Worker -> [correctness-Skeptic + security-auditor + perf-analyst] (parallel) -> synthesize -> fix loop if needed
```

1. Worker implements and returns output.
2. Conductor spawns three reviewers in a **single message** (parallel, background):
   - A correctness-Skeptic using the standard adversarial brief for the domain.
   - A `security-auditor` with the changed files and domain context.
   - A `perf-analyst` with the target, repro command, and any known perf budget.
3. All three return independently. Conductor synthesizes findings into a unified list before opening any fix loop.
4. Sign-off requires all three to clear - a single open Critical or Major finding from any reviewer blocks completion.
5. Fix loops follow the standard re-route rules (Section 5). Each fix re-runs only the reviewers that raised findings, unless the fix touches the other reviewers' scope.

### Declaration format

When using this strategy, the conductor declares before spawning:

```
Risk: Elevated (multi-dimensional review) - [specific signal]
Tier: 3 (Opus)
Fanning out correctness-Skeptic + security-auditor + perf-analyst in parallel.
```

---

## 14. Calibration mechanisms

The Skeptic loop's review depth degrades silently if it degrades at all. A Skeptic that drifts into rubber-stamp behavior produces clean sign-offs identical in surface form to genuine ones. Section 5's audit-note mechanism is the primary per-spawn defense; this section adds the secondary backstop: aggregate drift detection via structured findings counters, sampled meta-review, and an inspection CLI.

This is a calibration layer, not a gating layer. Original Skeptic sign-off remains binding for merge decisions. Meta-divergence on Critical or Major findings is surfaced inline to the user as advisory; Minor divergences appear only in the `agentic-calibrate divergence` output.

### Findings counters in the events log

Every `spawn_complete` event for `agent == "skeptic"` carries the following fields inside `data` (the conductor constructs the JSON inline before calling `bin/agentic-emit`; meta-Skeptic and the original Skeptic do not write to `.agentic/`):

```json
{
  "findings_count": {"critical": 0, "major": 1, "minor": 3},
  "diff_lines": 142,
  "signed_off": true,
  "iteration": 2,
  "meta_review": null
}
```

`meta_review` is `null` when the unit was not sampled. When sampled and completed, a separate `meta_review_complete` event (agent: `skeptic-meta`) is appended later by the conductor; see "Meta-Skeptic spawn brief" below.

Existing `spawn_complete` fields (`tier`, `tool_use_id`, `agent_id`, `model`, `wall_seconds`, `tokens`, `status`) coexist with the calibration fields inside the same `data` object. The events log schema does not gain a new event type for the per-spawn counters.

### Sampling protocol

A 5% sample of Skeptic sign-offs triggers a meta-review. Selection is deterministic: hash `task_id` concatenated with `iteration` into a uniform 0-99 bucket; trigger if `bucket < 5`. The deterministic hash means a sampling decision is reproducible from the events log without needing to record an RNG seed.

Meta-Skeptic spawns are **background fire-and-forget**. The conductor declares the unit complete without waiting for meta-Skeptic return. When meta-Skeptic returns its textual divergence report asynchronously, the conductor parses the report, constructs the `meta_review_complete` event, and emits via `bin/agentic-emit`.

### Meta-Skeptic spawn brief

The meta-Skeptic receives:
- The original diff (`git diff origin/$BASE_BRANCH..HEAD` or unit equivalent)
- The original Skeptic's findings list verbatim
- The original Skeptic's sign-off statement verbatim
- The original adversarial brief

The meta-Skeptic produces a divergence report as **TEXT** in its return summary. The expected shape is:

```
Critical missed: [list of finding titles, or "none"]
Major missed: [list of finding titles, or "none"]
Minor missed: [list of finding titles, or "none"]
Agreement: [yes | no]
```

**Meta-Skeptic does NOT write to `.agentic/`.** Its sole output is the return text. The conductor parses the return text and emits the structured `meta_review_complete` event itself, preserving the single-writer convention for `.agentic/events.jsonl`.

### Meta-divergence surfacing

When meta-Skeptic identifies a Critical or Major finding the original Skeptic missed, the conductor surfaces this at the next user-facing turn boundary as a single inline line:

```
META-DIVERGENCE: meta-Skeptic identified [Critical|Major] '<finding-title>' that original Skeptic missed on <task_id>. Original sign-off stands; review recommended before merging.
[phase: meta-divergence-critical]
```

Original sign-off remains binding. Minor-only divergences are NOT surfaced inline; they appear only in `agentic-calibrate divergence` output.

**Surfacing has two binding triggers:**

1. **In-session scan.** At each turn boundary entering `/implement-ticket` Phase 6 or returning from a Worker, the conductor scans `.agentic/events.jsonl` for `meta_review_complete` events whose `original_task_id` is not present in `.agentic/.meta-divergence-surfaced`. For any with non-empty `critical_missed` or `major_missed`, emit the META-DIVERGENCE line and append `original_task_id` to the surfaced-tracker file.

2. **Session-start sweep.** On every session boot (first turn of session, after reading `.agentic/context.md`), the conductor sweeps `.agentic/events.jsonl` for ALL `meta_review_complete` events whose `original_task_id` is not in `.agentic/.meta-divergence-surfaced`. Emits the META-DIVERGENCE line for each Critical/Major divergence and appends to the tracker. This catches divergences whose meta-Skeptic completed asynchronously after the originating session ended.

**Tracker file (`.agentic/.meta-divergence-surfaced`)** is one `original_task_id` per line, append-only, written by the conductor only. File-absent is equivalent to empty set. Project-local; gitignored under the `.agentic/` umbrella.

### Session-start sweep pagination

The session-start sweep described above scans `.agentic/events.jsonl` for `meta_review_complete` events. Without pagination, this scan reads the entire file on every boot -- a vicious loop as the file grows unbounded.

**Pagination tracker file:** `.agentic/.meta-divergence-last-sweep`

Format: single line, ISO8601 UTC timestamp (e.g. `2026-05-13T16:30:00Z`). File-absent equals "no prior sweep".

**Sweep procedure:**

1. Read `.agentic/.meta-divergence-last-sweep`. If the file does not exist, set `since_ts` to `null` (first run).
2. Read `.agentic/events.jsonl` line by line:
   - If `since_ts` is not `null`: skip any event whose `ts` field is less than or equal to `since_ts`. Only process events where `ts > since_ts`.
   - If `since_ts` is `null` (first run on a legacy file): read only the **last 100 lines** of the file. This caps cold-start cost on projects with large pre-existing event logs.
3. Process the filtered events as described in the "Meta-divergence surfacing" subsection above.
4. After the sweep completes (whether or not any divergences were found), write the current ISO8601 UTC timestamp to `.agentic/.meta-divergence-last-sweep` (atomic: write to tmp, then `mv`). This timestamp becomes the `since_ts` for the next sweep.

**In-session scan pagination:** The in-session scan (at Phase 6 boundaries) uses the same pagination tracker. It reads only events with `ts > since_ts` and updates the tracker after completion. Both sweep points share the same `.agentic/.meta-divergence-last-sweep` file; the last write wins, which is correct because sweeps are serialized per session.

**No events missed:** Because `meta_review_complete` events are appended to the JSONL file with monotonically increasing `ts` fields, scanning `ts > since_ts` is exhaustive for new events. Events with `ts == since_ts` were already processed in the prior sweep and their `original_task_id` values are already in `.agentic/.meta-divergence-surfaced`.

**Legacy file handling:** The 100-line cap on first run means a single cold-start sweep is bounded. After that first sweep writes the tracker, all subsequent sweeps are incremental. If the file has fewer than 100 lines total, the first sweep processes all of them -- no events are skipped.

### Inspection CLI

`bin/agentic-calibrate` is the queryable surface for calibration data:

```
agentic-calibrate density   [--since <ISO8601>] [--task <task_id>]
agentic-calibrate divergence [--since <ISO8601>]
agentic-calibrate help
```

`density` reads `.agentic/events.jsonl`, filters Skeptic `spawn_complete` events, and prints findings-per-100-diff-lines aggregates plus a per-iteration breakdown. Spawns where `diff_lines == 0` are excluded from the aggregate denominator; per-row output prints `N/A` in the density column for those rows. When fewer than 10 spawns have been observed (after zero-diff exclusion), the command prints `warming up: N/10 spawns observed; baseline not yet established.` to indicate that drift signals are not yet meaningful.

`divergence` reads `meta_review_complete` events and prints the divergence rate (Critical/Major/Minor missed counts and percentage of sampled spawns).

### Threat model

The deterministic counters and findings-density metrics are designed for **drift detection in a non-adversarial conductor relationship**. They are not cheating-prevention mechanisms. A conductor that wishes to mis-emit findings counts can do so; the threat model is operator self-deception over time, not adversarial spoofing. If the conductor itself is compromised, calibration data from that conductor is unreliable by construction - this is an explicit accepted limitation.

Cross-references: Section 5 (audit-note as primary rubber-stamp defense; calibration sampling as secondary backstop), Section 6 (findings classification feeding the counters), Section 11 (sign-off format that must be present for an event to be recorded with `signed_off: true`).
