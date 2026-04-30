# P2: Tiered Planning Artifacts

**Status:** Proposal (revised)
**Date:** 2026-04-29
**Target file:** `content/rules/agent-methodology.md` (source; the `.claude/skills/...` copy is a hardlink)

## 1. Problem statement

The methodology requires per-task design via the `architect` agent and per-task structural decomposition via the `orchestration-planner`, but it has no upstream "what are we building and why" gate that survives multi-unit fan-out. The architect's output is bounded to the implementation contract for a single feature/change, the orchestration-planner output is purely structural (units, deps, parallelism), and the conductor's "default-and-proceed" protocol assumes the goal itself is unambiguous. Concretely: agent-methodology.md lines 162-164 gate plan-acted-on review at the architect plan, lines 369-377 gate decomposition at orchestration-planner, and lines 36-97 gate clarification at per-question stops - but nowhere does anything force the conductor or the user to commit to a problem statement, success criteria, non-goals, **and a verification plan** before the first engineer spawns. Multi-unit work therefore inherits whatever framing was in the original prompt and accumulates units without any artifact that lets the Skeptic ask "is this the right problem, and how will we know we solved it?" This proposal closes that gap with a tiered planning artifact keyed to the existing risk taxonomy and inserted as a **promotion gate between planning and implementation**.

## 2. Ordering (resolves the chicken-and-egg)

Promotion is downstream of architect+planner, upstream of engineer:

```
Risk classified Elevated
  -> architect (lightweight scoping; existing behavior)
  -> Skeptic on architect plan (existing line 162)
  -> Open Questions resolved (existing line 164)
  -> orchestration-planner (existing line 377)
  -> [PROMOTION GATE] count units, check track span, check session span
       -> 1 unit: no Brief required, proceed to engineer (current behavior)
       -> 2-5 Elevated-or-above units: author Brief, Skeptic the Brief, then engineer
       -> 6+ units OR cross-track OR multi-session OR ADR-class: assemble Plan, Skeptic the Plan, then engineer
  -> engineer(s) spawned with brief_path / plan_path in execution contract
```

Key consequence: the Brief is authored **after** the planner has returned a unit count, so "do we need a Brief?" is a mechanical check, not a guess. The architect plan and planner output are *inputs* the conductor uses to draft the Brief - the Brief is not asking the conductor to predict what will exist; it is asking the conductor to commit to the framing now that the shape is known.

## 3. Brief template

**Canonical path:** `docs/planning/<slug>.md` (slug = kebab-case feature name, prefixed with priority tag if the project uses one, e.g. `p2-foo.md`).

**Template (must fit on one screen; ~20 lines):**

```markdown
# Brief: <feature name>

**Problem:** <1-2 sentences. Behavior gap in user/system terms, not implementation terms.>

**Success criteria:** <Bulleted, observable from outside. Max 4 bullets.>
- <criterion 1>
- <criterion 2>

**Non-goals:** <What this explicitly does NOT do. Max 3 bullets. Write "none plausible" if none.>
- <non-goal 1>

**Constraints:** <Hard constraints only - existing contracts, perf budgets, compat targets, deadlines. Not preferences.>

**Verification:** <Single line. What test(s), gate(s), or browser check(s) prove this is done. Name the qa.md trigger if it will fire. Name the regression test if findings flywheel requires one. "Cannot specify" is a planning gap and must be resolved before sign-off.>

**Risk class:** <Elevated multi-unit / Plan-required - per the trigger table>

**Linked artifacts:** architect-plan: <path>; orchestration: <path or inline JSONL block>
```

**Field guidance (one line each):**
- Problem: behavior gap, not solution. If you wrote "add X", restate as "users cannot Y".
- Success criteria: pass/fail testable from outside. Drives Skeptic completion review.
- Non-goals: written to defeat the most likely scope-creep direction.
- Constraints: list only what would change the architect's design if violated.
- **Verification: non-skippable.** Name the concrete check. If qa.md trigger patterns will match the planned diff, list them. If a regression test is mandated by an existing `.agentic/findings.md` entry, name it. If verification cannot be specified, that is itself a planning gap - the Brief is not Skeptic-eligible until verification is named.
- Risk class: copy from trigger table; binds which downstream artifacts are required.
- Linked artifacts: makes the Brief auditable against its own inputs.

## 4. Plan (assembly + conductor-authored coverage)

**Principle:** the Plan is primarily *assembled* from existing artifacts (architect plan, planner JSONL, Brief), with two short conductor-authored coverage documents and a verification gate. The "assembly" framing prevents the Plan from becoming a long-form design rewrite; the conductor-authored exceptions are explicitly carved out below.

A "Plan" is a directory:

```
docs/planning/<slug>/
  brief.md                  # Brief from Section 3 (assembled)
  architect-plan.md         # architect's existing output, as-is (assembled)
  orchestration.jsonl       # orchestration-planner output, verbatim (assembled)
  risk-register.md          # 5-10 line list, conductor-authored (coverage)
  rollback.md               # 5-10 line list, conductor-authored (coverage)
  verification-gate.md      # see template below, conductor-authored (coverage)
```

**Verification gate template (`verification-gate.md`):**

```markdown
# Verification Gate

**Tests that must pass:**
- Unit: <commands or "n/a">
- Integration: <commands or "n/a">
- E2E: <commands or "n/a">

**qa-engineer triggered?** <yes/no>. If yes, list qa.md trigger patterns that fire and the units they apply to.

**Manual smoke check:** <single paragraph or "none">

**Rollback signal:** <how we will know post-merge that this needs to be reverted - what alarm, what user signal, what metric>

**New regression tests required by findings flywheel?** <yes/no>. If yes, list the `.agentic/findings.md` entry IDs and the test files that will hold the regression.
```

The verification gate is **non-skippable**. If any field is "cannot specify", the Plan is not Skeptic-eligible and the operator must resolve the gap (typically by re-running architect or by tightening the Brief).

**ADR carve-out:** for ADR-required work (cross-track or "Architecture decision constraining future choices"), add `adr-NNN.md` using the project's existing ADR convention. The Plan does not redefine ADR format.

**Coverage exception to "assembly":** risk register, rollback, and verification gate are conductor-authored because they exist nowhere upstream - the architect plan covers implementation, the planner covers structure, neither covers operational risk or verification. These three files are short by design (5-10 lines each plus the verification template); if any one exceeds the budget, the Plan is too large and should be split into multiple Briefs.

## 5. Trigger table

All triggers are mechanical. Operator judgment is not a field. Triggers are evaluated **after** orchestration-planner returns (per the ordering in §2).

| Condition | Artifact required |
|---|---|
| Risk = Trivial or Low | None |
| Risk = Elevated AND orchestration-planner returns 1 unit (or planner skipped per the existing single-unit exception) | None (architect plan only - current behavior) |
| Risk = Elevated AND orchestration-planner returns **2-5 units at Elevated or above** | **Brief** + architect plan |
| Risk = Elevated AND orchestration-planner returns **6+ units at Elevated or above** | **Plan** (Brief + architect + orchestration JSONL + risk register + rollback + verification gate) |
| Any unit's `output_paths` spans 2+ tracks (see "Track" definition below) | **Plan** |
| Work spans 2+ sessions (declared at planning time, OR auto-promoted when `.agentic/loop-state.json` resumes a Brief-tier task into a third session) | **Plan** |
| Cross-track OR triggers an "Architecture decision constraining future choices" risk signal | **Plan + ADR** |

**Unit counting rule.** Only units whose own risk classification is Elevated or above count toward the 2-5 / 6+ thresholds. Trivial units in a mixed-risk plan do not count - they are routed per the standard Trivial conductor rule and contribute zero to promotion.

**"Track" definition (mechanical).** A track is a depth-1 directory under the repo root that contains its own `AGENTS.md` file. Nested `AGENTS.md` files (e.g. `helios/factory/AGENTS.md`) do not create new tracks - they are sub-context within their parent track.

- Worked example A: this repo has `agentic-engineering/AGENTS.md`, `helios/AGENTS.md`, `agentic-factory/AGENTS.md`, `models/AGENTS.md` at depth 1. A unit touching `helios/factory/foo.ts` is in the `helios` track. A unit touching `agentic-engineering/content/rules/x.md` is in the `agentic-engineering` track. A change touching both is cross-track and triggers Plan + ADR.
- Worked example B: a change touching `helios/factory/foo.ts` and `helios/ui/bar.tsx` is single-track (`helios`); the nested `factory/AGENTS.md` does not split the track.

**Other notes:**
- Unit count comes from the orchestration-planner's JSONL output, counted by `unit_slug` entries with risk >= Elevated.
- Track span is computed by mapping each `output_paths` entry to its depth-1 ancestor and checking for `AGENTS.md` at that depth.
- Session span is initially declared, then auto-promoted by the resume hook when the threshold is hit.
- A task can be promoted upward mid-work (e.g., a 3-unit Brief-tier task that the architect re-plans into 8 units gets re-classified as Plan-tier before the next worker spawns). It cannot be demoted.

## 6. Gate semantics

**Promotion gate position (per §2):** Brief and Plan sit between orchestration-planner output and the first engineer spawn. They do **not** sit upstream of architect.

**Authoring sequence (Brief tier):**
1. Architect runs (existing behavior, with existing investigator-before-architect rules).
2. Skeptic on architect plan (existing line 162).
3. Open Questions on architect plan resolved (existing line 164).
4. Orchestration-planner runs (existing line 377).
5. **Promotion check** against the trigger table.
6. If 2-5 Elevated-or-above units: conductor authors Brief at `docs/planning/<slug>.md` using architect output, planner output, and the original ticket as inputs.
7. Spawn Skeptic on the Brief using the existing "Document synthesis, architecture, and planning" adversarial brief. Verification field is part of the Skeptic's review surface.
8. On Brief sign-off (and after any Open Questions in the Brief are resolved), engineer(s) spawn with `brief_path` populated in their execution contract (see §7).

**Authoring sequence (Plan tier):** identical to Brief tier through step 6, plus:
- Conductor authors `risk-register.md`, `rollback.md`, and `verification-gate.md`, and assembles the Plan directory.
- A second Skeptic pass reviews the assembled Plan as a whole (not the components individually - they were already reviewed). Scope: integration coherence, missing rollback for any high-blast-radius unit, risk register completeness, **verification gate completeness (no "cannot specify" entries)**.
- Workers spawn only after assembled-Plan sign-off, with both `brief_path` and `plan_path` in their execution contract.

**ADR tier:** ADR is authored alongside the Brief (not after), because the architectural decision shapes the Brief's constraints. ADR review follows the project's existing ADR process; if none exists, the ADR goes through the same "Document synthesis, architecture, and planning" Skeptic review as the Brief.

**What blocks:**
- Missing required artifact at any tier blocks engineer spawn.
- Brief or Plan Skeptic finds Critical or Major findings: same loop semantics as architect-plan Skeptic (re-route limits apply, max 3 fix passes).
- Brief or Plan Open Questions section non-empty: same hard gate as architect Open Questions (line 164). The new section explicitly extends the existing rule rather than restating it.
- Verification gate field set to "cannot specify": blocks Skeptic sign-off until resolved.
- Trigger-table promotion mid-work: conductor stops, authors the missing artifacts, runs the appropriate Skeptic, then resumes.

**What does not block:**
- Risk class = Elevated single-unit: no Brief required. The architect plan is the artifact. This preserves current behavior for the dominant Elevated case (single-file behavioral edits, single new file, single-config changes - the bulk of Elevated work in observed sessions; precise share is not yet measured, see §11).

## 7. Engineer contract extension (closes the planning-theater gap)

Without this section, the Brief would be a gate-only document that never reaches the engineer - the exact failure mode this proposal exists to prevent. The engineer execution contract template (agent-methodology.md lines 171-179) gains two fields:

```
- brief_path: [path to Brief, or "n/a" if architect plan is the sole artifact]
- plan_path:  [path to Plan directory, or "n/a" if Brief-tier or below]
```

Engineer reads the Brief (and Plan, if present) before starting. Success criteria, non-goals, and verification gate are the criteria the engineer is measured against - they supersede any informal interpretation of the ticket. If the engineer discovers a conflict between the Brief and the architect plan, it returns BLOCKED (this is a hard blocker per the Worker autonomy contract, not a design-taste call).

## 8. Resume protocol interaction

`.agentic/loop-state.json` gains three fields when a Brief or Plan is in play:

```json
{
  "brief_path": "docs/planning/<slug>.md",       // null when none
  "plan_path":  "docs/planning/<slug>/",          // null when none
  "promotion_tier": "elevated-single | brief | plan | plan-adr"
}
```

**Transitions:**
- **At Brief authoring:** conductor writes `brief_path` and sets `promotion_tier` to `brief`.
- **At Plan assembly:** conductor writes `plan_path` and updates `promotion_tier` accordingly.
- **On resume:** the conductor re-reads the Brief (and Plan, if present) before spawning the next worker. The Brief/Plan is the source of truth for success criteria; the conductor does not rely on in-context recall of those fields across resume.
- **On mid-flight promotion:** if a task initially classified as Elevated-single (no Brief) discovers via planner re-decomposition or scope expansion that it is now Brief-tier or Plan-tier, the conductor authors the **retroactive Brief** before the next engineer spawn, runs Brief-Skeptic, and updates loop-state. Already-completed units are not retroactively re-reviewed; the Brief governs all subsequent units.
- **Session-span auto-promotion:** when resume count for a Brief-tier task hits 3, the conductor authors the missing Plan-tier artifacts before the next worker spawn (per §5 trigger row).

## 9. Exact edit locations in agent-methodology.md

Per-edit summary only. No final prose.

| Location | Change | Approx lines added |
|---|---|---|
| **New section "## Planning Artifacts"** inserted between "## Delegation" and "## Risk Classification" (delegation ends at line ~180; risk classification begins at line 181) | Full new section: ordering diagram, trigger table, Brief template, Plan assembly + verification-gate description, gate semantics, mid-flight promotion. | ~80-100 |
| "## Delegation" -> "Architect plan output requires Skeptic review" paragraph (lines 162-163) | No structural change. Add a trailing sentence: "When orchestration-planner output triggers Brief or Plan promotion (see Planning Artifacts), an additional Skeptic pass reviews the Brief or Plan before any engineer spawns." | ~1 |
| "## Delegation" -> "Open Questions are a hard gate" paragraph (line 164) | Add one sentence extending the gate to Brief and Plan Open Questions with identical semantics. | ~1 |
| "## Delegation" -> "Worker preamble (when using engineer)" execution contract template (lines 171-179) | Add two contract fields: `brief_path` and `plan_path`. Add one sentence after the template: "When `brief_path` or `plan_path` is populated, the engineer reads it before starting; success criteria and the verification gate supersede any informal interpretation of the ticket." | ~4 |
| "## Task Decomposition" -> "Before spawning workers: run the orchestration-planner" paragraph (line 377 area) | Add one sentence: "When orchestration-planner output triggers Plan-tier promotion (see Planning Artifacts), the conductor authors risk register, rollback, and verification gate before spawning workers." | ~1 |
| "## Risk Classification" Declaration format block (lines 273-281) | Extend the format to optionally include `Brief: <path>` or `Plan: <path>` line when an artifact is required. | ~3 |
| "## Cross-session loop resume" bullet list (lines 346-353) | Add one bullet: "**Brief/Plan paths recorded.** When a Brief or Plan governs the task, `brief_path`, `plan_path`, and `promotion_tier` are written to `.agentic/loop-state.json` at authoring time. On resume, the conductor re-reads the Brief/Plan before spawning the next worker. Mid-flight promotion (Elevated-single -> Brief or Plan tier) authors a retroactive Brief before the next engineer spawn." | ~3 |
| Cross-reference at top of "## Protocol Details (read on trigger)" (line 420 area) | Add one bullet pointing to the new Planning Artifacts section. | ~2 |

**Net additions:** ~95-115 lines, almost all concentrated in the new section. Existing prose is touched in 6 surgical spots, none requiring restructuring.

**Out of scope for this edit:**
- `/implement-ticket` command file: a follow-up edit will wire Brief authoring into the post-planner phase and Plan assembly into the appropriate gate. Not part of agent-methodology.md changes.
- `architect` agent spec: no change required - the architect runs upstream of the Brief in the new ordering and does not consume it.
- `engineer` agent spec: no spec change. The contract field is the only mechanism, consistent with how `task_id` was added.
- `findings.md` flywheel: unchanged.

## 10. Open questions

**None.** Prior open questions resolved as follows:

1. **Brief authoring agent vs conductor-authored.** Resolved: **conductor-authored**, with the Skeptic pass catching framing failures. Rationale: the Brief is short, the conductor already has architect+planner output in context at the promotion gate, and adding a `planner` agent before the Skeptic introduces a second review surface for marginal gain. If observation shows conductor-authored Briefs systematically fail Skeptic review, revisit in a follow-on proposal. Non-blocking.
2. **Session-span trigger detection.** Resolved: **declared up-front by the conductor when planner returns >=6 units regardless of trigger, AND auto-promoted by `.agentic/loop-state.json` on the third resume of any Brief-tier task** (see §8). The two-mechanism approach gives both proactive and reactive coverage. No better mechanical proxy is available without instrumenting estimated effort, which is out of scope.
3. **Plan-tier without orchestration-planner.** Resolved: **track span and ADR-class triggers fire regardless of unit count and regardless of whether the planner ran**. If a single-unit task is cross-track or ADR-class, the conductor authors the Plan even though the planner was skipped (the orchestration JSONL field in the Plan directory becomes a single-line stub noting "single unit, planner skipped per single-unit exception"). This eliminates the contradiction.

## 11. Rejected alternatives

**(a) Separate planning-risk taxonomy.** Define Tier-A / Tier-B / Tier-C planning levels independent of the existing Trivial/Low/Elevated risk axis. Rejected: introduces a second vocabulary the conductor must reason about at every spawn, and the two axes correlate so strongly (Elevated multi-unit ~= needs planning) that the second axis is mostly redundant. Reusing the risk taxonomy plus mechanical post-conditions (unit count, track span) yields the same routing without the cognitive tax.

**(b) Brief required for all Elevated work.** Make the Brief mandatory for every Elevated task, including single-unit. Rejected: the dominant Elevated case in observed sessions is single-unit (single-file behavioral edit, single-config change, single new file) where the architect plan already serves as the framing artifact. Adding a Brief upstream of every such task is the planning-theater failure mode this proposal exists to prevent. The Brief earns its keep when there are 2+ units sharing a goal; below that threshold the architect plan is sufficient. *Note: the precise share of Elevated work that is single-unit is not yet measured by the eval harness; the claim "dominant" is based on session observation, not a numeric baseline. A measurement is filed as a follow-on for the eval harness but is not a precondition for this proposal.*

**(c) Plan-first always with Brief as a section.** Always produce a Plan directory; the Brief is just the first file inside it. Rejected: the cost of authoring (and Skeptic-reviewing) a risk register, rollback, and verification gate for a 3-unit task is disproportionate to the blast radius. Tiering exists precisely so that small multi-unit work pays only for what it needs. Plan is reserved for 6+ units, cross-track, or multi-session, where the assembled artifacts genuinely add value.

**(d) Brief upstream of architect.** Author the Brief before architect runs. Rejected (this was the original draft of this proposal): introduces a chicken-and-egg problem - the Brief's "risk class" field cannot be filled until orchestration-planner has counted units, but the planner runs after the architect. Inverting the order (architect first, planner second, Brief at the promotion gate) makes every trigger evaluable from existing artifacts.

## 12. Follow-on docs unit

**Scope (separate Elevated unit, runs AFTER `/update-agentic-engineering` lands the methodology edit):**

The methodology rule edit is in scope for `/update-agentic-engineering`; documentation under `docs/**` is explicitly out of scope for that command (per its own Scope section). A separate Elevated unit handles docs:

**Files in scope for the docs unit:**

1. **`docs/agentic-engineering.html`** - the public docs site. Updates required:
   - Add a "Planning Artifacts" section (or subsection under an existing planning/orchestration heading) covering the three tiers (Elevated-single, Brief, Plan), the trigger table, the ordering, and the verification-gate requirement.
   - Update any "how a task flows" diagram to show the promotion gate between planner and engineer.
   - Cross-link from the existing risk classification and orchestration-planner sections.

2. **`docs/slides/orchestration-planner-slides.html`** + companion `.md` - the planner is the gate that feeds promotion; add a slide showing what happens after planner returns (the promotion check) and link forward to the new Planning Artifacts deck.

3. **`docs/slides/how-it-works-slides.html`** + companion `.md` - update the end-to-end flow slide to include the Brief/Plan gate.

4. **`docs/slides/work-tracking-slides.html`** + companion `.md` - update the loop-state.json field list to include `brief_path`, `plan_path`, `promotion_tier`.

5. **New deck `docs/slides/planning-artifacts-slides.md` (+ generated `.html`)** - dedicated slide deck mirroring the structure of the existing slide decks (skeptic-protocol, parallel-fanout, profiles). Sections: problem, ordering, trigger table, Brief template, Plan assembly, verification gate, engineer contract extension, resume interaction.

**Verified in scope check:** the slide files listed above all exist in `docs/slides/` per directory listing. No `decisions-log` or other path is referenced - only files that exist.

**Ordering and dependencies:**
- Methodology edit (via `/update-agentic-engineering`) lands first. The docs unit reads the merged source as authoritative input.
- Docs unit is its own Elevated unit with its own Brief if it expands beyond 5 file edits (the current scope is 5 file edits + 1 new file = 6 files; this puts the docs unit on the Brief tier per §5).
- Docs unit must not begin before the methodology PR is merged - drift between the rule source and the docs is an active failure mode.

**Out of scope for the docs unit:**
- README.md updates (no current Planning Artifacts mention to drift from; can be picked up opportunistically).
- Any change to `content/commands/` or `.codex/skill/` - those are methodology-source territory and would require routing through `/update-agentic-engineering`.

