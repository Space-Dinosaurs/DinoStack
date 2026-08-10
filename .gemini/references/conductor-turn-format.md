# Conductor Turn Format

## Purpose

The conductor's default output is noise. Every operator turn read is attention spent; a status-only turn spends that attention for no return, and an unstructured turn forces the operator to rebuild context on every check-in - a cost multiplied across many concurrent sessions. This file exists to guard that attention. North Star pillar 1 states the requirement directly (`docs/overview/vision.md:19`):

> "Guard operator attention. Surface decisions and work-stoppages, not status."

Two mechanisms enforce this: a fixed slot order for any turn that IS written (Rule A, §4), and an emission gate that decides whether a turn should be written at all (Rule B, §2). Neither rule replaces judgment - both are the mechanical form of the same North Star sentence.

## The four warrants (Rule B)

A conductor turn is warranted only when at least one of these four conditions holds. Each has a one-line test:

1. **Decision** - a `## Operator decisions` heading is present in the turn.
2. **Stoppage** - a `Waiting:` line is present in the turn (see §7, forced yield).
3. **Completion** - the turn contains `[phase: complete]` or an explicit terminal-completion phrase. A bare `done`, `shipped`, or `merged` deliberately does **not** count - those words commonly appear in ordinary status prose ("unit 2 merged", "PR merged, pulling main") and are too weak a signal on their own to carry the completion warrant.
4. **Answer** - the turn contains a quoted fragment responding to the operator's immediately-preceding message, OR (DS-155) the operator's most recent genuine message looks like a direct question and the turn is a plain-prose reply. This is the weakest of the four and best-effort only; it exists so a direct question never goes unanswered, not as a loophole for narration.

Everything else - agent spawned, agent returned, phase advanced, unit merged, CI green - is a silent continue. No turn is written for it.

## Scope filter

A conductor turn reports on **this session's work only**. Do not mention other concurrent sessions, other tickets, or unrelated in-flight work - the operator is tracking those elsewhere and a cross-session mention adds cost without adding a decision. Do not include rationale unless a decision surfaced in the *same* turn depends on it; rationale for past decisions belongs in the PR body, the plan artifact, or a memory file (see §5, bullet 3).

## The fixed slot template (Rule A)

When a turn is warranted, it follows this fixed order:

1. **Identity line first**: `ticket · branch · [phase: x]`. The `[phase: label]` breadcrumb itself is governed by `content/references/subagent-protocol.md` Rule 6 - read it there for firing points and the crash-recovery rationale; it is not restated here to avoid two copies drifting.
2. **Status slots**: `State`, `Running`, `Blocked` - one line each, omitted when empty. Capped at **1-3 status lines per turn**, with the forced-yield shape (§7) as the sole exception to the cap itself, not merely to its line contents: a forced-yield turn drops `State`/`Running`/`Blocked` entirely and instead carries one `Waiting:` line per agent, however many that is - the count is unbounded, not re-capped at 1-3.
3. **`## Operator decisions`, last.** Placement and internal formatting are governed by `content/sections/02-delegation.md` - read it there rather than here.

**The 1-3 line cap applies to the status slots only.** `## Operator decisions`, when present, is **additional** to that cap, not counted against it. This is a deliberate asymmetry, not an oversight: the kernel paragraph in `content/sections/02-delegation.md` that governs the Operator decisions block mandates a multi-line format per decision item - "the recommended action, one line of why, and the reversal offer" - and explicitly forbids imposing a numeric cap on the number of items, because a cap with no overflow rule would mechanically force the conductor to hide a decision. Reading the 1-3 line cap here as applying to the whole turn, decisions block included, would put this file in direct contradiction with that kernel paragraph. It does not: the cap governs `State`/`Running`/`Blocked` only.

This prose cap is narrower than what the mechanical hook (§10) actually bounds. `hooks/enforce-turn-shape.py`'s volume check (DS-151) computes a single whole-message CHARGE - every non-blank line, in either the status region or the `## Operator decisions` region, contributes 0 or 1 to the charge unless it participates in one of three named, individually-capped free pools (aggregate fenced content in the status region, well-formed `Waiting:` lines when stoppage is the sole warrant, and up to `ITEM_FREE_LINES` lines per recognized decision item) - and compares that single number against one flat budget, `BASE_BODY_BUDGET = 10`, regardless of which warrant is present. There is no per-warrant table any more, and counting does not stop at the decisions heading: content under the heading is charged too, through its own item-shaped allowance rather than being exempt outright. The two are compatible, not contradictory: this prose rule states the *target* shape for the common case (a status turn should need at most 3 lines), while the hook's volume check is the *mechanical backstop* that catches sprawl generally, sized to leave margin above a realistic warranted turn without punishing one for legitimately using more than 3 lines when its warrant calls for it. See §10 for the charge model and free-pool table.

## Length discipline

This section supersedes and absorbs `.agentic/memory/keep-conductor-updates-short.md` into the always-loaded reference tier. It carries forward all six "How to apply" bullets from that memory entry, each with an explicit disposition note against this file's rules.

- *"Default to 1-3 lines per turn. Result first. No preamble, no recap of what I just did."* - the line-count half of this bullet is **relocated** to Rule A above (§4) and now applies specifically to the status slots. The "Result first. No preamble, no recap" half is reproduced here verbatim and stands independently of the cap: lead with the outcome, never with a restatement of the work already visible in the transcript.
- *"Progress pings while agents run: one line, or say nothing."* - verbatim; unchanged.
- *"Do NOT explain reasoning, trade-offs, or rejected alternatives unless asked - those belong in the PR body, the plan artifact, or a memory file, not the chat turn."* - reproduced in full, including the routing-destination clause. That clause matters: it is the part that says where the excluded content goes, not just that it is excluded.
- *"Surface a finding only when it changes what the operator would do. 'Worth knowing about' is usually not."* - verbatim; unchanged.
- *"`## Operator decisions`: the recommended action and one line of why. Nothing else."* - **not restated here.** `content/sections/02-delegation.md` and `content/references/delegation-detail.md` §Operator Decisions Block Rationale both already cover this in fuller form (the recommendation-plus-confirmation shape, the "(Recommended)" label convention, the ban on co-equal ballots). A third copy here would be a third place to drift.
- *"Final completion: what shipped, where it landed, what is left. Not how it was built."* - verbatim; unchanged.

Closing line, verbatim: *"Length is the default failure mode here, not brevity. When unsure, cut."*

## Worked example - a normal turn

```
DS-123 · fix/foo · [phase: skeptic-review]
State: 2 of 3 units merged, unit 3 in review
Running: skeptic on unit 3 (~4 min)
Blocked: nothing

## Operator decisions
1. <action> - <one line why>. Reply STOP to skip.
```

## Worked example - forced yield

When all work is with background agents and the conductor must end its turn - no decision, no completion, no answer pending, only a stoppage on background work - the turn collapses to a `Waiting:` list:

```
DS-123 · fix/foo · [phase: skeptic-review]
Waiting: skeptic - unit 3 correctness review
Waiting: qa-engineer - unit 3 browser scenarios
```

One `Waiting:` line per agent, naming the agent and what it is waiting for. Nothing else. No state recap, no phase narration, no next-steps, no "meanwhile" commentary, no restating what was already reported in a prior turn. The operator's requirement, as recorded in ticket DS-122: *"It should list the agents it's waiting on and why and that's it. Not a whole bunch of extra stuff, only the important and necessary information always."*

Each `Waiting:` line must be <=120 characters (`WAITING_LINE_MAX_CHARS`) to count as well-formed and free under the volume check (§10). Free-of-charge status is scoped further than that character bound alone: a well-formed `Waiting:` line is free ONLY when `stoppage` is the SOLE warrant present on the turn (DS-151 amendment A1) - the moment any other warrant (decision, completion, answer) co-occurs on the same turn, `Waiting:` lines revert to charging like ordinary lines instead of staying free.

## Worked non-example - the silent continue

**REJECTED (INVALID - no warrant):**

```
DS-123 · fix/foo · [phase: engineer-spawned]
State: engineer returned unit 2, spawning skeptic now
```

This carries no decision, no `Waiting:` line, no completion phrase, and answers no operator question. It is a status ping, and per Rule B it should not have been written at all.

**CORRECT behavior for the same moment:** say nothing. Spawn the skeptic and keep working. The next turn written is whichever of the four warrants fires next - most likely the skeptic's findings surfacing a decision, or a forced-yield `Waiting:` turn if the conductor's own work is now exhausted and only background agents remain.

## Edge case: interaction with the abdication guard

This section documents an **interaction**, not a "no conflict" - the honest claim is that the two hooks never contradict, not that they are unrelated. `hooks/enforce-no-abdication.py` runs three classifiers OR-gated together: `_is_abdication` (the classic permission-seeking interrogative), `_is_stalled_surface_and_proceed` (an announced-then-unexecuted default), and `_is_prose_ballot` (a co-equal ballot lacking a `(Recommended)`/`Recommendation:` marker). The turn-shape hook described in §10 below is a separate mechanism. Three points establish how they relate:

1. **Severity is asymmetric by design.** The turn-shape hook is advisory-only: it always exits 0 and never blocks the current stop; its finding surfaces as additional context on the *next* turn. The abdication guard can exit 2 and block the current stop outright. Only one of the two mechanisms can ever actually block a turn.
2. **The axes are disjoint.** The turn-shape hook inspects structural shape and *warrant presence* - whether a `## Operator decisions` heading exists at all, a boolean. It never inspects whether individual decision items carry a `(Recommended)`/`Recommendation:` marker; that inspection belongs exclusively to `_is_prose_ballot`. Because the two hooks check different properties of the text, they cannot contradict each other - at most both fire additively on the same turn ("fix your identity line" from one, "fix your ballot markers" from the other), and those two findings are never mutually exclusive.
3. **Convergent steady state.** A spec-compliant turn - correct fixed-slot shape, and any `## Operator decisions` items carrying a `(Recommended)` marker - suppresses `_is_abdication` (a documented negative-gate coupling: the marker is one of the tokens `_is_abdication` inspects) and suppresses `_is_prose_ballot` (no unmarked items to flag). The turn-shape hook's own forced-yield shape check is separately gated off in this case because the `decision` warrant is present. All three mechanisms independently agree there is nothing to flag on a correctly-shaped turn - arrived at by two unrelated code paths, not by one hook deferring to the other.

State plainly: **a silent continue is the opposite of abdication.** The abdication guard fires on permission-seeking language and on an announced-then-unexecuted default. It never fires on silently continuing work with no turn written at all - that is exactly the behavior Rule B (§2) mandates for the non-warranted case, and the two mechanisms agree on it.

## Hook contract

`hooks/enforce-turn-shape.py` implements the checks in §2 and §4 mechanically.

- **Output.** Non-blocking. On a finding, emits `{"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "TURN-SHAPE: <finding>"}}` and exits 0. Exit is 0 unconditionally - this hook can never block a stop.
- **Config toggle.** `turn_shape_guard_enabled` in `.agentic/config.json`, **default ON when the key is absent.** This is deliberately inverted from `abdication_guard_enabled` (which defaults OFF when absent and requires explicit opt-in): because this hook never blocks, there is no downside symmetric to the abdication guard's block-by-default risk, so the safer default here is to run.
- **Kill switch.** `AE_TURN_SHAPE_GUARD_DISABLE=1` disables per-session, matching the convention used by the abdication guard's own kill switch (`hooks/enforce-no-abdication.py`).
- **Loop guard.** Like its blocking sibling, this hook bounds how often its advisory can re-invoke the model (a Stop hook's `additionalContext` re-invokes the model immediately, without waiting for a user turn - so a blocked conductor that keeps writing the same non-conforming turn could otherwise loop until the harness's own 9-consecutive-block override). Two layers, sharing the same machinery as `enforce-no-abdication.py` via `hooks/lib/loop_guard.py`: Layer 1 is the `stop_hook_active` payload flag, checked right after stdin parse, exiting silently - a re-invocation never re-flags the same turn. Layer 2 is a per-`cwd` counter (`.agentic/.turn-shape-guard-fire-count`, cap 2) as a backstop for CC bug #54360, where `stop_hook_active` can fail to propagate when a UserPromptSubmit hook interleaves system reminders; the counter increments and persists BEFORE each advisory (an advisory whose count cannot be persisted is not emitted - it would lose its loop bound) and resets on a clean turn and on a genuine new user message (counting excludes tool_result and harness-injected lines), so a blocked conductor emitting a non-conforming turn gets at most CAP advisories before the hook goes silent. The guard only suppresses advisories - it never changes the never-block invariant, and every exit stays 0.
  - **Bounding re-invocation count does not bound visible duplicate output (DS-155).** The Claude Code harness does not retract or replace the already-streamed flagged turn when `additionalContext` re-invokes the model - the operator sees BOTH the original flagged message AND the corrected re-invocation, back to back, for every single advisory fire. At `CONSECUTIVE_BLOCK_CAP = 2` that is up to two extra visible duplicate turns stacked on the one substantive turn the operator actually wanted, on a single exchange. This is a real user-facing UX cost of the advisory mechanism itself, distinct from (and not fixed by) the loop-count bound above - see residual false positive 4 below.
- **Classification order.** Warrant classification (§2) runs first and is authoritative. The forced-yield shape check (§4, §7) is strictly subordinate: it fires only when `stoppage` is the sole warrant present on the turn - a turn that also carries a decision, completion, or answer warrant is exempt from the forced-yield shape requirement even if it also contains a `Waiting:` line.
- **Volume check (DS-151).** A mechanical backstop for the length-discipline promise above: it computes a single whole-message CHARGE and compares it against one flat budget, `BASE_BODY_BUDGET = 10` - there is no per-warrant table any more. Every non-blank line in the status region charges 1 unless it is a well-formed `Waiting:` line **and** `stoppage` is the SOLE warrant present, in which case it charges 0; fenced content in the status region is scored as a single aggregate pool (the first `FENCE_FREE_LINES` fenced lines are free, everything past that charges full weight, regardless of how many separate fences it is split across). Every non-blank line under the `## Operator decisions` heading charges 1 unless it falls inside a recognized item's first `ITEM_FREE_LINES` lines - fenced content inside an item counts toward that item's own line total, it does not escape into the status-region fence pool, so it is charged exactly once. The check is skipped entirely when zero warrants are present (that case belongs exclusively to `_status_only_flag` above). See the table immediately below for the full free-pool definitions.

  | Free pool | Cap | Scope |
  |---|---|---|
  | `FENCE_FREE_LINES` | 20 lines | Aggregate across every fence in the status region (not per fence) |
  | Well-formed `Waiting:` lines | unbounded line count, each <=`WAITING_LINE_MAX_CHARS` (120) chars | Per line, ONLY when `stoppage` is the sole warrant present on the turn |
  | `ITEM_FREE_LINES` | 3 lines | Per recognized `## Operator decisions` item (fenced or not), unbounded item count |
  | The `## Operator decisions` heading line itself | always free | n/a - counted in neither region |

  Two things worth stating explicitly about how these pools behave, since neither is obvious from the table alone:
  - **Sole-stoppage forced-yield turns are not skipped outright any more; they charge 0 by construction.** The deleted exclusion model exempted a sole-stoppage turn from measurement entirely. Under the charge model there is nothing to exempt: every well-formed `Waiting:` line charges 0 while `stoppage` is the SOLE warrant present (amendment A1), so a clean forced-yield turn's charge is 0 regardless of how many `Waiting:` lines it carries - the same "unbounded per-instance" property as before, just enforced structurally rather than by a skip branch. The moment ANY other warrant (decision, completion, answer) co-occurs, every `Waiting:` line reverts to charging 1 like ordinary prose - a well-formed-but-non-sole-warrant `Waiting:` line is no longer free.
  - **The free pools are NOT uniformly "aggregate per message"** (amendment A5): the fence pool is aggregate across the status region; the `ITEM_FREE_LINES` allowance is per item, with an unbounded item count; the well-formed-`Waiting:` allowance is per line, also with an unbounded line count when stoppage is the sole warrant. Only the fence pool pools multiple instances into one scalar - the other two stay individually capped per instance while allowing unbounded instance count.

  What counts toward the charge: fenced content in the STATUS region participates in the single aggregate pool above - the first `FENCE_FREE_LINES` fenced lines across every fence in the status region are free, and every fenced line past that charges full weight, so splitting one long fence into many short ones gains nothing (the pool is aggregate, not per fence). An UNCLOSED fence (the message ends mid-fence, or any other odd count of `` ``` `` delimiters) gets NO exclusion at all - `_segment` fails closed and treats an unmatched trailing opener as never validly fenced, so every line collected since it charges full weight as ordinary prose. Fenced content INSIDE a recognized `## Operator decisions` item folds into that item's own `ITEM_FREE_LINES` allowance instead of the status-region fence pool - it is charged once, through the item, never twice (double-charging it in both pools would risk pushing the charge above the message's own non-blank line count). The `## Operator decisions` block's total line count IS now part of the whole-message charge, unlike the deleted exclusion model where it was never bounded by this check at all: every line under the heading that does not fall inside a recognized item's first `ITEM_FREE_LINES` lines charges 1, so an unrecognized or sprawling decisions region can push the message over budget on its own (see the next bullet for the separate PER-ITEM shape bound, which is additional to this whole-message charge, not a substitute for it).
- **Named accepted limits (DS-151, amendments A5/A10).** Three limits are accepted by design, never claimed closed:
  1. Item-shaped status prose is undetectable by any line-counting model: a conductor can move status narration below the `## Operator decisions` heading, format it as <=`ITEM_FREE_LINES`-line items, and buy unbounded free lines, because item COUNT is unbounded by design (`content/sections/02-delegation.md`'s ban on a numeric item cap). Only content, never shape, forbids this - the item-sprawl check below cannot enforce a semantic rule.
  2. A legitimate paste over `FENCE_FREE_LINES` aggregate lines in the status region charges its excess (residual false positive #3 below) - spec-aligned, not a defect.
  3. No character bound exists on ordinary prose lines: a verbose turn written as long paragraphs still charges 1 per non-blank line regardless of that line's length. Only well-formed `Waiting:` lines carry a character bound (`WAITING_LINE_MAX_CHARS`), because only `Waiting:` lines can ever be unboundedly free; an ordinary prose line is never free regardless of length, so a character cap on it would add complexity without closing any bypass.
- **Operator-decisions item-sprawl check (DS-151).** A second, independent mechanical check: item COUNT under `## Operator decisions` stays completely unbounded, per `content/sections/02-delegation.md`'s ban on a numeric item cap - but each individual item's LINE COUNT is bounded at `ITEM_FREE_LINES` (3) lines (aliased `MAX_LINES_PER_DECISION_ITEM`), matching the mandated "recommended action, one line of why, and the reversal offer" shape quoted above. An item (a numbered or bulleted top-level line, with any continuation lines - fenced or not - folded into it) that sprawls past 3 lines is flagged by name. This is a different axis than the banned item-count cap - ten one-line items pass; one forty-line item does not.
- **Registration is guarded**, unlike its sibling hooks: `test -f <script> && python3 <script> || exit 0`. This is deliberate - a missing script under the unguarded pattern used by other hooks would exit 2 (the blocking code) after a revert or partial checkout, which is exactly the failure this hook must never cause given its advisory-only contract.
- **Fail-open.** A top-level exception guard wraps the hook body; any unexpected error exits 0 rather than surfacing as a block.
- **Enforcement log.** Participates in `hooks/lib/enforcement_log.py` via `log_fire(..., "allow_advisory", ...)`, called only on the finding branch (no log entry on a clean turn).

**Four documented residual false positives / costs** - accepted trade-offs, not defects to fix:

1. A stoppage-only turn that adds a separate explanatory sentence beside the `Waiting:` line is flagged, because the hook expects the `Waiting:` line to be self-contained. Fold the reason into the line itself instead of appending prose: `Waiting: engineer - unit 3, blocks merge` rather than a `Waiting:` line followed by a sentence explaining why.
2. A `Waiting:` turn that also answers the operator's preceding question can be misclassified. The `answer` warrant detector (§2, warrant 4) is deliberately weak - best-effort quoted-fragment matching, plus a transcript-derived question bonus added in DS-155 (see below) - and can still miss a genuine answer folded into a `Waiting:` turn, causing the turn to collapse to the sole-stoppage forced-yield shape and get flagged even though it also carried a real answer.
3. (DS-151) A legitimate paste over `FENCE_FREE_LINES` (20) aggregate lines in the status region charges its excess even when it is a single honest fence, not sprawling prose - a 40-line diff pasted into the status region charges 20 and fires. The pool is aggregate across the whole status region, not per fence, so splitting the paste into several shorter fences gains nothing; there is no mechanical way to distinguish a legitimately long paste from an abusive one without the pool losing its purpose. Spec-aligned, not a defect: this content belongs in the PR body, the plan artifact, or a memory file instead (§5, "routes... not the chat turn").
4. (DS-155) **Every advisory fire, by design, produces visible duplicate operator-facing output** - not a false positive in the classification sense, but a UX cost inherent to the `additionalContext` re-invocation mechanism (see the Loop guard bullet above). The harness streams both the original flagged turn and the corrected re-invocation to the operator; the loop guard bounds how many TIMES this can happen (`CONSECUTIVE_BLOCK_CAP = 2`), not whether the operator sees the duplication when it does happen. Accepted because the alternative - suppressing the original streamed turn - is not something a Stop hook can do on this harness; named here so a future design does not assume the loop-count bound also solved the duplicate-output problem, which it does not.

DS-155 also narrowed two of the false-positive classes this hook was originally built to describe (not fully closed - each keeps a named residual gap, stated at its own definition site): a genuine plain-prose answer to a direct operator question no longer requires the narrow quoted-fragment `answer` shape (`_transcript_answer_bonus`, gated on the most recent GENUINE transcript message looking like a question), and the identity-line check (§2) is exempted for a session that has never carried an established identity line at all (`_session_has_established_identity`) rather than demanding one unconditionally - both are best-effort, soft-fail signals derived from the transcript, not claims of full closure.
