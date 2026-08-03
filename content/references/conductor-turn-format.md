# Conductor Turn Format

## Purpose

The conductor's default output is noise. Every operator turn read is attention spent; a status-only turn spends that attention for no return, and an unstructured turn forces the operator to rebuild context on every check-in - a cost multiplied across many concurrent sessions. This file exists to guard that attention. North Star pillar 1 states the requirement directly (`docs/overview/vision.md:19`):

> "Guard operator attention. Surface decisions and work-stoppages, not status."

Two mechanisms enforce this: a fixed slot order for any turn that IS written (Rule A, §4), and an emission gate that decides whether a turn should be written at all (Rule B, §2). Neither rule replaces judgment - both are the mechanical form of the same North Star sentence.

## The four warrants (Rule B)

A conductor turn is warranted only when at least one of these four conditions holds. Each has a one-line test:

1. **Decision** - a `## Operator decisions` heading is present in the turn.
2. **Stoppage** - a `Waiting:` line is present in the turn (see §7, forced yield).
3. **Completion** - the turn contains `[phase: complete]` or an explicit terminal-completion phrase. A bare `done`, `shipped`, or `merged` deliberately does **not** count - those three words are this repo's canonical vocabulary for a *non-warranted* status ping, exactly the noise this gate exists to suppress.
4. **Answer** - the turn contains a quoted fragment responding to the operator's immediately-preceding message. This is the weakest of the four and best-effort only; it exists so a direct question never goes unanswered, not as a loophole for narration.

Everything else - agent spawned, agent returned, phase advanced, unit merged, CI green - is a silent continue. No turn is written for it.

## Scope filter

A conductor turn reports on **this session's work only**. Do not mention other concurrent sessions, other tickets, or unrelated in-flight work - the operator is tracking those elsewhere and a cross-session mention adds cost without adding a decision. Do not include rationale unless a decision surfaced in the *same* turn depends on it; rationale for past decisions belongs in the PR body, the plan artifact, or a memory file (see §5, bullet 3).

## The fixed slot template (Rule A)

When a turn is warranted, it follows this fixed order:

1. **Identity line first**: `ticket · branch · [phase: x]`. The `[phase: label]` breadcrumb itself is governed by `content/references/subagent-protocol.md` Rule 6 - read it there for firing points and the crash-recovery rationale; it is not restated here to avoid two copies drifting.
2. **Status slots**: `State`, `Running`, `Blocked` - one line each, omitted when empty. Capped at **1-3 status lines per turn**, with the forced-yield shape (§7) as the sole exception to that cap's line *contents* (it uses `Waiting:` lines instead of `State`/`Running`/`Blocked`, still 1-3 lines).
3. **`## Operator decisions`, last.** Placement and internal formatting are governed by `content/sections/02-delegation.md` - read it there rather than here.

**The 1-3 line cap applies to the status slots only.** `## Operator decisions`, when present, is **additional** to that cap, not counted against it. This is a deliberate asymmetry, not an oversight: the kernel paragraph in `content/sections/02-delegation.md` that governs the Operator decisions block mandates a multi-line format per decision item - "the recommended action, one line of why, and the reversal offer" - and explicitly forbids imposing a numeric cap on the number of items, because a cap with no overflow rule would mechanically force the conductor to hide a decision. Reading the 1-3 line cap here as applying to the whole turn, decisions block included, would put this file in direct contradiction with that kernel paragraph. It does not: the cap governs `State`/`Running`/`Blocked` only.

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

One `Waiting:` line per agent, naming the agent and what it is waiting for. Nothing else. No state recap, no phase narration, no next-steps, no "meanwhile" commentary, no restating what was already reported in a prior turn. The operator's own stated requirement, worth quoting directly: *"It should list the agents it's waiting on and why and that's it. Not a whole bunch of extra stuff, only the important and necessary information always."*

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
- **Kill switch.** `AE_TURN_SHAPE_GUARD_DISABLE=1` disables per-session, matching the convention used by the abdication guard and the AskUserQuestion enforcement hook.
- **Classification order.** Warrant classification (§2) runs first and is authoritative. The forced-yield shape check (§4, §7) is strictly subordinate: it fires only when `stoppage` is the sole warrant present on the turn - a turn that also carries a decision, completion, or answer warrant is exempt from the forced-yield shape requirement even if it also contains a `Waiting:` line.
- **Registration is guarded**, unlike its sibling hooks: `test -f <script> && python3 <script> || exit 0`. This is deliberate - a missing script under the unguarded pattern used by other hooks would exit 2 (the blocking code) after a revert or partial checkout, which is exactly the failure this hook must never cause given its advisory-only contract.
- **Fail-open.** A top-level exception guard wraps the hook body; any unexpected error exits 0 rather than surfacing as a block.
- **Enforcement log.** Participates in `hooks/lib/enforcement_log.py` via `log_fire(..., "allow_advisory", ...)`, called only on the finding branch (no log entry on a clean turn).

**Two documented residual false positives** - accepted trade-offs, not defects to fix:

1. A stoppage-only turn that adds a separate explanatory sentence beside the `Waiting:` line is flagged, because the hook expects the `Waiting:` line to be self-contained. Fold the reason into the line itself instead of appending prose: `Waiting: unit 3 still running, blocks merge` rather than a `Waiting:` line followed by a sentence explaining why.
2. A `Waiting:` turn that also answers the operator's preceding question can be misclassified. The `answer` warrant detector (§2, warrant 4) is deliberately weak - best-effort quoted-fragment matching - and can miss a genuine answer folded into a `Waiting:` turn, causing the turn to collapse to the sole-stoppage forced-yield shape and get flagged even though it also carried a real answer.
