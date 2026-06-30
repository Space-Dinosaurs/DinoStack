---
description: "Interactive planning dialogue. Produces a Brief at `docs/planning/<slug>.md` via a"
---
# /brief

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

<!--
Purpose: Interactive planning dialogue that produces a Brief artifact before architect and engineer
         are spawned. Translates operator planning-intent into a committed, Skeptic-eligible Brief
         at docs/planning/<slug>.md via a structured multi-turn conversation. Synthesizes the
         outcome rubric (from product-discovery staged draft or inline elicitation) into the
         Brief's Outcome rubric field.

Public API: /brief [topic] | /brief --from <path>
            Invoked explicitly by the operator or auto-triggered by the conductor on
            planning-intent signals per Section 1.

Upstream deps: content/sections/03-planning-artifacts.md (Brief template and field guidance,
               including Outcome rubric field schema);
               content/sections/02-delegation.md (surface-and-proceed protocol);
               content/rules/conventions.md (git worktree conventions, base-branch resolution);
               .agentic/brief-session.json (resume state, includes rubric array);
               MEMORY.md (prior-decisions scan, auto-injected at session start);
               docs/overview/_proposed/outcome-rubric.md (when product-discovery was run first).

Downstream consumers: content/commands/implement-ticket.md Phase 0b (brief_path check);
                      content/sections/03-planning-artifacts.md (Skeptic variant selection);
                      architect agent (receives brief_path in execution contract);
                      Skeptic (receives operator-confirmed variant from Section 6; evaluates
                      Outcome rubric field per step 3.5 in skeptic.md).

Failure modes: Brief with empty Verification field is NOT Skeptic-eligible - conductor must
               collect a real value before writing to disk. Parse failure on brief-session.json
               triggers the corruption branch in Section 2 (no silent ignore). Scope-creep
               or whole-pivot detection surfaces as a guardrail (Section 4), not an error.

Performance: Standard. Prior-decisions scan is capped (Section 7). No subagent spawns during
             the dialogue phase itself.
-->

Interactive planning dialogue. Produces a Brief at `docs/planning/<slug>.md` via a
structured multi-turn conversation, then hands off to the architect and engineer with
`brief_path` pre-populated in the execution contract.

**Session budget note:** Brief sessions are structured multi-turn conversations that track state in `brief-session.json`. Each gray-area resolution consumes conductor turns. Complex Briefs with many gray areas can drive long sessions that accumulate stale state. The conductor SHOULD recommend `/wrap` after resolving 10+ gray areas in a single session, or when the total conductor turn count approaches the soft limit defined in `content/references/subagent-protocol.md` Section 13.

---

## Section 1 - Trigger model

### Auto-invocation on planning-intent signals

The conductor monitors operator messages for planning-intent signals. When detected, it
auto-invokes `/brief` using the surface-and-proceed pattern.

**Surface-and-proceed announcement (auto-trigger only):**

> "Starting /brief for [topic] - reply STOP to abort or skip the dialogue."

**"One turn" definition:** one operator message and the conductor's immediate response.
STOP must appear in the very next operator message after the conductor's announcement;
otherwise the conductor proceeds.

**Explicit invocation** `/brief [topic]` works identically but skips the announcement.

### Planning-intent signals (fire on any of)

- Exploratory framing: "I want to build...", "We should add...", "Let's create...",
  "thinking about...", "considering..."
- Multi-step feature descriptions with no specific ticket reference
- Requests for design or plan: "can you plan...", "let's design..."
- Feature names or descriptions spanning more than one sentence with vague outcome language

### Negative-signal suppression list (do NOT fire on any of)

- Single-file questions ("how do I X in this file")
- Debugging questions ("why is this failing")
- Code-review questions ("look at this PR")
- Bug reports ("Y is broken")
- Explicit ticket references ("work on TICKET-123")
- Direct implementation requests with specific scope

Signal must be exploratory framing, not execution. When ambiguous, prefer NOT firing.

### Discovery before brief

When the problem, users, or scope are still fuzzy - or the project has no `docs/overview/vision.md` / `docs/overview/requirements.md` yet - spawn the `product-discovery` agent first. Discovery decides WHAT to build and WHY (the problem, the personas including the counterparty, the market context, the staged vision and requirements); `/brief` and the architect decide HOW. Run discovery, let the operator ratify and promote the staged intent layer, then return to `/brief` to frame the execution. Skip discovery and go straight to `/brief` only when the problem and scope are already clear.

### PRD handoff express path

If the operator passes a PRD document, the conductor skips intent-capture and jumps to
PRD extraction (Section 5). Replace the standard announcement with:

> "Found PRD - extracting Brief fields."

---

## Section 2 - Resume check

On invocation, if `.agentic/brief-session.json` exists:

**If `status: interrupted`** (or `dialogue_active` with `updated_at` more than 10 min ago):

> "Interrupted /brief session detected for '<slug>'. Last phase: [status], [N] gray areas answered. Resume this session or start fresh? (resume / fresh)"

- On "resume": restore state from file and re-enter dialogue at the last recorded phase.
- On "fresh": delete the file and start from Turn 1.

**Parse-failure branch:** if file is unparseable:

> "Brief session state file is corrupted. Start fresh? (yes/no - if no, please move/delete the file manually and retry)."

- On yes: delete file and start fresh.
- On no: halt.

---

## Section 3 - Dialogue protocol

### Turn 1 - Intent capture

If `/brief` received no topic argument, conductor asks:

> "What are you trying to build or solve? One or two sentences is enough to start."

Operator replies. Write `brief-session.json` with `status: intent_captured`.

Run the prior-decisions scan (Section 7) after intent is captured but before presenting
the gray-area menu.

### Slug derivation

**Slug derivation.** Convert the operator's intent statement to a slug:
1. Take the first 6-8 significant words (skip articles: a, an, the; skip pronouns: I, we, you)
2. Lowercase and join with hyphens
3. Strip non-alphanumeric characters (keep only [a-z0-9-])
4. Cap at 60 characters total (truncate at last full word)

Example: intent "I want to build an interactive planning command" -> slug `build-interactive-planning-command`.

The same slug derivation algorithm applies in `implement-ticket.md` Phase 0b (when deriving slug from ticket title, the ticket-ID prefix is also stripped). For `/brief`, no ticket prefix exists - derive directly from intent.

### Turn 2 - Gray area menu

Conductor reads the intent and generates 4-8 SCOPE-SPECIFIC gray areas inline (no
subagent spawn). These must be concrete decisions, not generic checklists.

Examples for "user authentication": session handling, error responses, multi-device
policy, recovery flow.
Examples for "CLI for db backups": output format, flag design, progress reporting,
error recovery.

Present as a numbered menu:

> "Here are the areas where scope is still open. Pick the ones you want to talk through
> (e.g. '1, 3, 5'), or 'all' to cover everything, or 'none' to skip to the Brief draft:
> 1. [gray area]
> 2. [gray area]
> ..."

Write `brief-session.json` with `status: menu_presented` and the `gray_areas` array.

### Turn 3...N - Per-area dialogue

One exchange per selected gray area (`selected: true` in the state file):

- Conductor asks one focused question.
- Operator answers.
- Conductor may ask one follow-up if the answer is ambiguous, then moves to the next area.
- Scope-creep guardrail fires if an answer introduces a new major scope element (Section 4).
- Append each answer to `dialogue_log` in the state file.
- Update `gray_areas[i].answered: true` after each exchange.
- Write `status: dialogue_active` throughout.

### Turn N+1 - Brief draft

Conductor synthesizes the Brief from intent + dialogue, formats per the Brief template
in `content/sections/03-planning-artifacts.md`, and includes the **Outcome rubric** field:

- **If `docs/overview/_proposed/outcome-rubric.md` exists** (product-discovery ran before /brief): copy its lines verbatim into the rubric field and note "copied from discovery draft - confirm or adjust."
- **Otherwise**: prompt the operator inline: "List the 3-6 things that would make this 'done' - one per line, most critical first." For each criterion the operator provides, assign a `verification_type`: `deterministic` if a gate is nameable, `judgment` otherwise. Present the assigned types for confirmation before writing.

The outcome rubric is part of the Brief draft and subject to the same iteration rounds (max 3 adjustments). Store the confirmed rubric in `brief-session.json` under the `rubric` array (see Section 8).

Conductor presents the full Brief to the operator:

> "Here's the Brief draft. Review it and say 'looks good' to write it, or tell me what
> to adjust:
>
> # Brief: <feature name>
> ..."

Write `status: draft_presented`.

### Turn N+2 to N+k - Iteration

Operator may request changes. Conductor adjusts. Max 3 adjustment rounds; on the 4th:

> "We've revised several times - do you want to keep discussing or finalize what we have?"

Write `status: iterating` during revision rounds.

### Turn N+k - Write and hand-off

1. Conductor writes Brief to `docs/planning/<slug>.md` per the template.
2. Sets `brief-session.json` `status: complete`, `brief_path`, `brief_source: operator`.
3. Commit:
   ```bash
   git add docs/planning/<slug>.md
   git commit -m "docs(brief): add <slug> brief"
   ```
4. If `TRACKER != none` AND `ticket_driven` active (per resolution rule in `content/sections/02-delegation.md` §Ticket-offer gate): derive TICKET_TITLE from the Brief's Feature Name, TICKET_BODY from Problem + Success criteria, TICKET_TYPE from the Brief type (default `feature`); then:
   - **`offer` mode:** emit `Creating ticket for this work - reply STOP to skip and proceed ad-hoc.` Wait one turn. If no STOP: invoke the Tracker Create Helper (cross-ref `content/commands/implement-ticket.md` §Tracker Create Helper). If STOP: skip creation, proceed ad-hoc (architect spawn, step 6).
   - **`require` mode:** invoke the Tracker Create Helper immediately (no skip path).
   - On CREATE_STATUS=created: hand off to `/implement-ticket <CREATED_TICKET_ID>` with `brief_path` in the execution contract INSTEAD of spawning the architect directly (skip steps 5-6).
   - On CREATE_STATUS=failed: emit the failure line; in `offer` mode proceed ad-hoc (architect spawn, step 6); in `require` mode STOP and wait for operator resolution.
   - On CREATE_STATUS=skipped (`offer` mode): emit the skip line and proceed ad-hoc (architect spawn, step 6).
   - On CREATE_STATUS=skipped (`require` mode): surface the conflict (`ticket_driven=require but tracker '<type>' has no create integration - proceed ad-hoc this once, or stop?`) and WAIT for operator.
5. When no ticket was created (ad-hoc path only): surface-and-proceed:
   > "Brief written to docs/planning/<slug>.md and committed. Spawning architect with
   > brief_path - reply STOP to halt or refine the Brief first."
6. If no STOP in one turn: spawn architect with `brief_path` in execution contract.
7. After architect returns: spawn Skeptic using the operator-confirmed variant (Section 6).
8. PR opens at the end of the full engineer flow (after Skeptic sign-off on engineer
   output), NOT after Brief commit.

---

## Section 4 - Scope-creep guardrail and operator pushback

### Standard scope-creep handling

When the conductor identifies a dimension exceeding stated intent, surface it as a
gray area rather than adding it silently:

> "This sounds like it might go beyond [original intent]. I'll add '[new dimension]'
> to the deferred list for now - flag it if it belongs in scope."

Add the item to the `deferred` array with `reason: scope-creep-candidate`.

### Operator pushback ("no, this IS in scope")

> Conductor: "Got it - I'll fold this in."

1. Remove item from `deferred` (set entry `status: withdrawn`).
2. Update gray-area menu: append the new dimension as a fresh entry with `answered: false`.
3. Re-prompt: "New gray area: [new dimension]. Want to address this now or revisit later?"

### Whole-pivot detection

When a new dimension materially changes the original intent:

> "This sounds like a pivot - want to restart the Brief with the new framing?
> (restart / continue with both)"

- On restart: clear `brief-session.json`, re-announce, begin from Turn 1.
- On "continue with both": add both framings to the Problem field and continue the
  dialogue.

---

## Section 5 - PRD express-path

**Invocation:** `/brief --from <path>` where path is relative or absolute.

### Standard extraction

Scan for headings or labels matching: Problem / Goals / Non-goals / Constraints /
Verification (or equivalents: Objective, Acceptance Criteria, Out of Scope, Success
Metrics, Definition of Done). Map matching content to Brief fields.

Also scan for headings matching: Definition of Done / Acceptance Criteria / Success Metrics / Pass-Fail / Rubric. Extract matching items as outcome rubric candidates - assign `verification_type: deterministic` when the item names a measurable gate, `verification_type: judgment` otherwise. Cap at 6 lines. If none of these headings exist, pre-fill the Outcome rubric field with `[extracted from PRD - review required]` and prompt: "I could not find explicit acceptance criteria in this PRD. List the 3-6 things that would make this 'done', one per line."

### Fallback when no structural signals detected

1. Treat the entire PRD as the Problem field (truncate to 500 words; note remainder as
   "see full PRD").
2. Pre-fill Success criteria, Non-goals, and Constraints with
   `[extracted from PRD - review required]`.
3. Pre-fill Verification with
   `[REQUIRES OPERATOR INPUT - cannot proceed without verification gate]`.
4. Surface to operator:
   > "Auto-extraction was minimal - this PRD doesn't have structural headings I can map
   > to Brief fields. I've put the full content in Problem; you need to fill in
   > Verification before we can proceed (Brief cannot ship without it). Want to discuss
   > the gray areas now or just edit the draft?"

**Verification field is always required.** A Brief with `[REQUIRES OPERATOR INPUT]` in
Verification is NOT Skeptic-eligible. The conductor must collect a real Verification
value before writing the Brief to disk.

---

## Section 6 - Skeptic variant selection

Conductor reads `brief-session.json` `brief_source` field.

### When `brief_source: operator` (Brief from /brief dialogue)

> "Verify completeness only: all 6 fields present, Verification field is non-empty and
> not 'cannot specify', no Open Questions remaining (a non-empty "Deferred defaults" section
> does not count as unresolved Open Questions - those do not block). The problem framing and success
> criteria have already been operator-confirmed in the /brief session - DO NOT relitigate
> framing decisions. Major findings are limited to: missing field, empty Verification,
> unresolved Open Questions, or contradictions between Brief fields. Out of scope:
> framing critique, alternative solutions, scope arguments."

### When `brief_source: conductor` (auto-authored at gate, no /brief session)

Use the standard "Document synthesis, architecture, and planning" adversarial brief.
Full framing review is in scope.

---

## Section 7 - Prior-decisions scan (capped)

Runs after intent capture, before the gray-area menu.

**MEMORY.md:** already in context (auto-injected at session start). NO file read.
Scan in-context content for keyword overlap with intent (substring match on
space-separated keywords from the intent statement).

**`docs/planning/`:** Glob `*.md` at top level only (or Bash `find docs/planning -maxdepth 1 -name '*.md'` when Glob is unavailable), NOT subdirectories. Use filenames
only (directory listing). Match by slug-name keyword similarity (substring match).
Read AT MOST the first 20 lines of the top 3 closest-matching files.
If no matches, skip reads entirely.

**Volume cap:** if `docs/planning/` has more than 50 `.md` entries at top level, restrict
to the 10 most recently modified by mtime before keyword matching.

Silent on no match.

---

## Section 8 - State file: `.agentic/brief-session.json`

Gitignored under the existing `.agentic/` rule. No `.gitignore` change needed.

### Schema

```json
{
  "schema_version": 1,
  "status": "<see enum>",
  "topic": "<intent statement>",
  "slug": "<kebab-case-feature-name>",
  "worktree_path": null,
  "brief_path": "<docs/planning/<slug>.md or null>",
  "brief_source": "<operator | conductor>",
  "created_at": "<ISO8601>",
  "updated_at": "<ISO8601>",
  "gray_areas": [
    {"id": 1, "text": "<text>", "selected": true, "answered": false}
  ],
  "dialogue_log": [
    {
      "gray_area_id": 1,
      "question": "<question text>",
      "answer": "<operator answer>",
      "followup_question": "<string or null>",
      "followup_answer": "<string or null>",
      "timestamp": "<ISO8601>"
    }
  ],
  "deferred": [
    {
      "text": "<item>",
      "reason": "<scope-creep-candidate | operator-choice>",
      "status": "<active | withdrawn>"
    }
  ],
  "draft": {
    "problem": "<string or null>",
    "success_criteria": ["<string>"],
    "non_goals": ["<string>"],
    "constraints": "<string or null>",
    "verification": "<string or null>"
  },
  "rubric": [
    {
      "id": 1,
      "line": "<one-line observable acceptance criterion>",
      "verification_type": "<deterministic | judgment>",
      "confirmed": false
    }
  ]
}
```

### Status enum (exhaustive)

`intent_captured | menu_presented | dialogue_active | draft_presented | iterating | complete | interrupted`

### Field notes

- `slug`: kebab-case slug derived from the operator's intent statement per the slug-derivation
  algorithm in Section 3 - Slug derivation. Must match the slug used by `implement-ticket.md`
  Phase 0b for the same intent.
- `worktree_path`: reserved for future use; currently null. The conductor works directly on its current branch - no worktree is created by /brief.
- `gray_areas[].selected: bool` - true if operator chose this area in the menu-selection
  step; false if deferred or skipped. Conductor only walks through areas where
  `selected: true`.
- `brief_source` drives Skeptic variant selection per Section 6.
- `deferred[].status: withdrawn` marks items the operator pushed back and folded in scope.
