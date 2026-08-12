#!/usr/bin/env python3
"""
Purpose: Claude Code Stop hook (DS-122; DS-156) that checks the SHAPE of
         the conductor's final assistant message against the turn-shape
         contract in content/references/conductor-turn-format.md §9 (the
         hook contract) / content/sections/02-delegation.md ("Operator
         decisions go last in the turn"). As of DS-156 this hook is NO
         LONGER uniformly advisory: it runs two checks with DIFFERENT
         enforcement postures.

           - `_execution_prose_flag` (execution-turn structural shape,
             REPLACES the deleted `_forced_yield_flag`) is BLOCKING: on a
             finding it exits via {"decision": "block", "reason": ...},
             the same shape its sibling enforce-no-abdication.py uses.
           - `_answer_relevance_flag` (Answer-turn opening-preamble/
             closing-recap phrasing) remains ADVISORY-ONLY - it always
             exits 0 and surfaces via `additionalContext` on the next
             turn, exactly the posture the WHOLE hook carried before
             DS-156. `_status_only_flag` (zero-warrant turns), the
             turn-charge volume check, and the operator-decisions
             per-item sprawl check also remain advisory-only, unchanged
             in posture.

         Why the split, not one posture for both: `_execution_prose_flag`
         is a structural predicate with no phrase matching or inference
         involved - a false positive requires the conductor to have
         actually violated the shape, and advisory enforcement of exactly
         this structural problem shipped three times (DS-122, DS-151,
         DS-155) without the prose ever going away. `_answer_relevance_flag`
         stays advisory because its two mechanized bans are curated phrase
         lists, not semantic detectors, and blocking a genuine answer over
         an opening phrase like "Good question" is a real friction cost.
         See content/references/conductor-turn-format.md's Hook contract
         section for the full rationale and the operator decision that
         overrode the architect's blanket-advisory recommendation.

         DS-155 round 3 history note (identity-line check REMOVED, not
         disabled): this hook previously ran a fifth check flagging a
         missing/malformed "<ticket> · <branch> · [phase: ...]" first
         line. Two successive rounds each replaced the "does this turn owe
         a breadcrumb" predicate with a more careful version, and each was
         falsified in turn: round 1 inferred it from transcript content
         (a prior well-formed identity line anywhere in the session) and
         was both poisonable (a single fabricated identity line
         "established" context forever) and non-bootstrapping (a session
         whose early turns were all malformed never got flagged); round
         2's replacement read REAL state instead (git branch naming
         convention, `.agentic/` ticket-loop state) and was falsified
         empirically against the very session that authored it - a
         Stop-event hook only ever observes the CONDUCTOR's own checkout,
         which structurally never leaves the base branch, so the
         branch-name signal is keyed on a state the consuming session can
         never present. The operator's decision: delete the check rather
         than author a third predicate. The identity/phase breadcrumb
         REMAINS a documented convention
         (content/references/conductor-turn-format.md) - it is simply no
         longer machine-enforced by this hook. DS-155 round 4 update: the
         former identity-line regex is now fully DELETED too, not merely
         unused - round 3 kept it on the theory that the forced-yield
         check depended on it; that theory was wrong (verified by
         execution: _forced_yield_flag reasons positionally via
         _body_after_identity_line, never via a regex match), so the
         regex genuinely had no consumer anywhere in this repo and its
         catastrophic-backtracking guard was protecting nothing. The
         canonical shape stays documented in
         content/references/conductor-turn-format.md alone.

         Four checks, run in this fixed order:

         1. Warrant classification (RUNS FIRST, and is AUTHORITATIVE over
            checks 2a-4 below): classifies which of
            four warrants justify the turn's content -
              - decision:   an "## Operator decisions" heading is present.
                             (DS-156 checked this for the same narrow-
                             literal weakness as completion/answer and
                             found it does NOT share it: 3.4% of the
                             status-only-flagged corpus sample contains
                             decision-adjacent prose ("I recommend...")
                             without the heading, but that prose is
                             exactly the free-form recommendation style the
                             heading requirement exists to discourage, not
                             a false positive of the guard - unlike
                             completion/answer, this warrant gates on a
                             MANDATED STRUCTURAL FORMAT the methodology
                             itself requires authors to use, not on
                             recognising free-form intent, so a hand
                             sample found no case where the guard was
                             wrong to withhold the warrant. Not widened.)
              - stoppage:   at least one "Waiting:" line is present.
                             (DS-156: same check. 7.4% of the same corpus
                             sample contains "waiting on/for" PROSE without
                             a "Waiting:" line, but every hand-checked
                             instance was itself part of a genuinely
                             multi-paragraph, still-in-progress status
                             turn that the guard is correctly nudging
                             toward the terse "Waiting:" format - not a
                             turn the guard wrongly penalised. Not
                             widened.)
              - completion: "[phase: complete]", an unambiguous terminal-
                             completion phrase (anywhere in the domain - see
                             _COMPLETION_RE), OR (DS-156) a LEADING
                             completion declaration - the identity line
                             itself opens with a short terminal claim such
                             as "Done.", "Verification complete.", "Both
                             PRs are done and verified.", or "Merged and
                             fully cleaned up." (see _LEADING_COMPLETION_RE).
                             A bare past-participle "done"/"shipped"/
                             "merged" occurring MID-MESSAGE still does NOT
                             count - this repo's canonical non-warranted
                             status-ping vocabulary ("unit 2 merged", "PR
                             merged, pulling main") must not accidentally
                             launder into a completion warrant. The leading-
                             declaration widening is deliberately scoped to
                             the identity line ONLY (matched via a
                             string-start anchor, not MULTILINE) precisely
                             so it cannot match that
                             same vocabulary buried in ongoing-work prose -
                             see _LEADING_COMPLETION_RE's docstring for the
                             corpus measurement (DS-156) that found the
                             identity-line restriction is what separates a
                             genuine completion report from a completed
                             sub-item inside a still-in-progress turn.
                             (DS-156 round 3) A completion claim - from
                             EITHER _COMPLETION_RE or
                             _LEADING_COMPLETION_RE - is further VETOED
                             outright when a continuing-work signal is
                             present anywhere in the domain
                             (_has_continuing_work_signal: a non-empty
                             Conductor-template "Running:" field, or one of
                             six phrases measured from real false
                             positives - "one to go", "remaining after",
                             "is/are still running", bold-wrapped
                             "**In progress:**" in any position (not only
                             as a sub-heading - see
                             _CONTINUING_WORK_PHRASE_RE's own docstring),
                             "review(s) running", "running on" (see
                             _CONTINUING_WORK_PHRASE_RE's own docstring for
                             the DS-157 round 2 corpus measurement behind
                             the last three and the "still open" phrase
                             that measurement dropped). This closes the
                             remaining false-positive shape the
                             identity-line restriction alone could not: a
                             genuinely short, sentence-complete completion
                             declaration ON the identity line, with the
                             still-in-progress signal appearing separately
                             in the body ("Security audit complete." ...
                             "Skeptic is still running.").
                             (DS-157) A turn whose identity line is NOT
                             itself a leading completion declaration (e.g.
                             "Both units shipped." - "shipped" alone, with
                             no trailing completion-adjacent word, does not
                             match _LEADING_COMPLETION_RE), but whose FIRST
                             body paragraph is ("**DS-156 is done.**
                             ..."), does NOT gain the `completion` WARRANT
                             here - see _has_body_completion_declaration's
                             docstring for the measured reason: granting the
                             warrant would route the turn onto the BLOCKING
                             _execution_prose_flag general branch, which
                             every real multi-paragraph prose completion
                             report in the DS-157 corpus fails (it permits
                             only State:/Running:/Blocked:/Waiting: slot
                             lines, never narrative bullets). Instead this
                             shape is recognized ONE LEVEL DOWN, inside
                             _status_only_flag only (see that function) -
                             it suppresses the ADVISORY status-only nag
                             without ever entering the warrant dict above or
                             the blocking classification path in step 2
                             below.
              - answer:     a quoted fragment of the operator's immediately
                             preceding message, OR (DS-155)
                             _transcript_answer_bonus finding that the
                             operator's most recent GENUINE message (per
                             loop_guard.last_genuine_user_text) looks like a
                             direct question (_looks_like_question: a
                             trailing "?", or a "?" anywhere in a message
                             under _SHORT_QUESTION_TEXT_MAX_CHARS chars)
                             AND that question is still the IMMEDIATELY
                             preceding turn boundary - no genuinely
                             separate, earlier completed assistant turn
                             since it was asked
                             (_has_intervening_assistant_turn: a STALE
                             question, still sitting there after several
                             later background-agent check-in turns, grants
                             nothing; see that function's own docstring
                             for the corpus-measured fix - a pure-text
                             entry immediately followed by a SEPARATE
                             tool_use entry, the real shape, not a mixed
                             same-entry array - and the false negative
                             when the current turn's own entry is not yet
                             on disk). The transcript-derived bonus
                             licenses a plain-prose reply without the narrow
                             quoted-fragment shape below. Best-effort and
                             deliberately the weakest of the four
                             detectors.
            DS-151: the detection domain is restricted to the identity line
            plus UNFENCED body lines only (see _segment/_classify_warrants
            below) - a warrant token that appears only inside a fenced code
            block or pasted diff is an example being discussed, not a live
            warrant, and must not launder pasted content into a false
            decision/stoppage/completion/answer claim. The identity line
            stays in the domain because it carries "[phase: complete]".

         2. DS-156 three-way classification (STRICTLY SUBORDINATE to 1,
            exhaustive and mutually exclusive - see
            content/references/conductor-turn-format.md §9's
            "Classification order" bullet). Answer always wins the shape
            question, regardless of what else co-fires:

            (a) Answer turn (`answer` warrant PRESENT): routes to
                `_answer_relevance_flag` only (ADVISORY - see below).

            (b) Execution turn (`answer` ABSENT, at least one of
                decision/stoppage/completion PRESENT): routes to
                `_execution_prose_flag` (BLOCKING). Its domain depends on
                whether `stoppage` is the SOLE warrant present:
                  - Sole-stoppage branch: every non-blank RAW line after
                    the identity line, fenced or not, must be a
                    "Waiting:" line - predicate-identical to the deleted
                    `_forced_yield_flag` (same gate, same
                    `_body_after_identity_line` domain, same
                    `_WAITING_LINE_RE`, no length test on Waiting:
                    lines).
                  - General branch (decision and/or completion present,
                    with or without stoppage): inspects only the
                    unfenced lines of the fence-aware status region
                    (`_segment`/`_regions`). Only a recognized
                    State:/Running:/Blocked: slot line (bounded by
                    STATUS_LINE_MAX_CHARS) or a Waiting:-shaped line
                    (unbounded length) is permitted; anything else
                    unfenced is a shape violation.
                  On BOTH branches, the identity line at position 1 is
                  additionally checked for LENGTH ONLY (never shape)
                  against STATUS_LINE_MAX_CHARS.

            (c) Zero-warrant turn (neither Answer nor any of
                decision/stoppage/completion present): routes to
                `_status_only_flag` only (ADVISORY, unchanged) - fires
                when the message has MORE than ~1-2 lines of prose
                outside the identity line.

            Known implementation seam (DS-151 amendment A7, still true
            post-DS-156 for the two ADVISORY-only leaves (a) and (c)):
            `_status_only_flag` still operates on the raw, unsegmented
            body-line list (`_body_after_identity_line`), NOT on
            `_segment`'s fence-aware structure that `_execution_prose_flag`
            and checks 3/4 below consume. `_execution_prose_flag` itself
            DOES use `_segment`/`_regions` on its general branch (this is
            new structural coverage DS-156 adds), but keeps the raw-line
            domain on its sole-stoppage branch to stay predicate-identical
            to the deleted `_forced_yield_flag`.

         3. Turn-charge volume check (DS-151): a mechanical backstop for
            the "1-3 status lines per turn" promise in
            content/references/conductor-turn-format.md, which was
            previously enforced by prose only. Rewritten from a
            three-region EXCLUSION model (status / fenced / decisions each
            independently "excluded" from the count, subject to per-warrant
            budgets) to a single whole-message non-negative CHARGE model -
            see "Charge model" below. The single comparison
            `charge(message) > BASE_BODY_BUDGET` replaces the deleted
            per-warrant BODY_BUDGET_* table entirely. Skipped entirely when
            zero warrants are present - that case is already exclusively
            owned by the status-only flag (2a).

         4. Operator-decisions item-sprawl check: flags any single
            "## Operator decisions" item (a numbered or bulleted top-level
            line, with continuation lines - INCLUDING fenced content,
            amendment A2 - folded in) whose line count exceeds
            ITEM_FREE_LINES (aliased MAX_LINES_PER_DECISION_ITEM). Item
            COUNT stays completely unbounded, per
            content/sections/02-delegation.md's ban on a numeric item-count
            cap; this checks per-item SHAPE against the "recommended
            action, one line of why, and the reversal offer" format that
            same rule mandates - a different axis from the banned count
            cap, not a restatement of it.

         Checks 3 and 4 both consume the shared _segment/_regions/
         _decision_items helpers - the single source of truth for fence and
         region structure. This is deliberate: two independent parsers
         drifting apart (the old _count_core_body_lines and the old
         _decision_item_sprawl_flag each re-parsed the text separately) is
         exactly what produced the DS-151 CF-2 convergence failure.

         ---------------------------------------------------------------
         Charge model (DS-151 rewrite; replaces the deleted per-warrant
         exclusion model entirely)
         ---------------------------------------------------------------

         Core decision: replace the three-region exclusion model with a
         single whole-message non-negative CHARGE model. Every non-blank
         body line contributes a charge of 0 or 1, or participates in a
         bounded free pool; nothing is ever subtracted below zero, and no
         line's presence ever reduces another line's charge. Both DS-151
         convergence failures were "a region was subtracted out and the
         subtraction had no aggregate bound" - under a charge model there
         is nothing to subtract, so that defect class has no
         representation. Every free line must be attributable to one of
         exactly three named, individually-capped allowances (fenced
         content, well-formed sole-stoppage Waiting: lines, decision-item
         shape) plus the always-free "## Operator decisions" heading line
         itself - adding a new free region is a visible, reviewable act
         (see hooks/tests/test-turn-charge-model.py invariant I6).

         charge = status_charge + fence_charge + decisions_charge

         status_charge    = count of unfenced, non-blank status-region
                             lines that are NOT a well-formed Waiting: line.
                             well-formed = matches the Waiting: shape AND is
                             <= WAITING_LINE_MAX_CHARS characters. A
                             well-formed Waiting: line charges 0 ONLY when
                             `stoppage` is the SOLE warrant present
                             (amendment A1) - otherwise it charges 1 like
                             any other line. The "unbounded Waiting: line
                             count" promise
                             (content/references/conductor-turn-format.md:64)
                             is scoped to the sole-stoppage forced-yield
                             shape, not to every turn that happens to
                             mention a Waiting: line: an unconditional
                             exclusion here would reopen an unbounded
                             per-instance free pool inside a
                             fully-warranted turn (identity + 40
                             short-but-well-formed Waiting: lines + a
                             decision heading previously charged 0 under an
                             earlier, unamended draft of this model - the
                             same defect class the charge model exists to
                             close).
         fence_charge     = max(0, fenced_nonblank_lines_in_status_region -
                             FENCE_FREE_LINES). The free pool is AGGREGATE
                             across every fence in the status region, not
                             per-fence - this is what makes CF-1 (multiplying
                             free lines by pasting many separate fences)
                             structurally impossible: there is one scalar
                             pool, computed once, not one pool per fence.
                             Splitting one long fence into many short ones
                             therefore gains nothing (verified,
                             hooks/tests/test-turn-charge-model.py
                             invariant I7). Scoped to the STATUS region
                             specifically, not literally "every fence in
                             the message": fenced content INSIDE a decision
                             item is charged through decisions_charge
                             instead (next paragraph). An aggregate pool
                             spanning both regions would double-charge that
                             content and could push `charge` above
                             `nonblank_body_lines`, violating invariant I8.
                             An unmatched trailing fence opener is never
                             validly closed, so its lines are ordinary
                             unfenced prose per _segment - no special case
                             needed; a previously-latched "unclosed fence
                             swallows everything to EOF" bug is
                             structurally impossible here.
         decisions_charge = non_item_line_count (every non-blank line under
                             the heading not folded into a recognized item -
                             fenced or not, full weight, no free pool: non-
                             recognition fails toward charging, not toward
                             free, which is why all three DS-151 CF-2
                             verified escapes close at once)
                             + sum(max(0, item_line_count - ITEM_FREE_LINES)
                             for each item). item_line_count folds in every
                             non-blank line after an item-start marker,
                             INCLUDING fenced lines (amendment A2 - a prior
                             draft of this rewrite silently excluded fenced
                             continuation lines from an item's count, which
                             reopened an unbounded-fenced-content-inside-an-
                             item bypass). A fenced paste inside a decision
                             item is not a way to grow that item for free;
                             it is, however, still charged only once (via
                             decisions_charge, not fence_charge - see above).

         Free pools are named, bounded, and NOT uniformly "aggregate per
         message" (amendment A5, correcting an earlier draft's overly broad
         claim to that effect): the fence pool (FENCE_FREE_LINES) is
         aggregate across the status region; the item allowance
         (ITEM_FREE_LINES) is PER ITEM, with an unbounded item count
         (disclosed below); the well-formed-Waiting: allowance
         (WAITING_LINE_MAX_CHARS) is PER LINE, also with an unbounded line
         count when stoppage is the sole warrant (by design). The
         "## Operator decisions" heading line itself is always free (0
         charge, counted in neither region).

         Warrant-keyed budgets are deleted as unsound, not merely replaced:
         every warrant token is conductor-authored, so a warrant-keyed
         budget was self-serviceable; the deleted `answer` budget was worse
         than self-serviceable, since its only detector
         (_QUOTED_FRAGMENT_RE) fires on any incidental 8+ char quoted
         fragment, so most substantive turns acquired the most generous
         budget by accident. Replacement: a flat BASE_BODY_BUDGET plus
         structurally-verified free pools - the only way to write more
         without charge is to write the shapes the spec mandates. Warrant
         classification survives for _status_only_flag and
         _forced_yield_flag, and (via amendment A1) to gate the
         sole-stoppage Waiting: free pool inside _turn_charge.

         Named accepted limits (must be stated, never claimed closed):
           - Item-shaped status prose is undetectable by any line-counting
             model: a conductor can move status narration below the
             heading, format it as <=ITEM_FREE_LINES-line items, and buy
             unbounded free lines, because item COUNT is unbounded by
             design. content/sections/02-delegation.md forbids this by
             CONTENT ("Nothing follows the heading: no status line, no next
             steps, no caveats") - a semantic rule no mechanical check can
             enforce.
           - A legitimate paste over FENCE_FREE_LINES aggregate lines in
             the status region charges its excess (a 40-line diff pasted
             into the status region charges 20 and fires). Spec-aligned,
             not a defect: content/references/conductor-turn-format.md:282
             routes that content to the PR body, plan artifact, or memory
             file instead.
           - (amendment A10) No character bound exists on ordinary prose
             lines: a verbose turn written as long paragraphs still charges
             1 per non-blank line regardless of that line's length -
             inherited from the underlying line-counting model, not
             introduced by this rewrite. Only Waiting: lines carry a
             character bound (WAITING_LINE_MAX_CHARS), because only
             Waiting: lines can ever be unboundedly free; an ordinary prose
             line is never free regardless of length, so a character cap on
             it would add complexity without closing any bypass.

         This ordering (warrant classification is authoritative; checks
         2a/2b/3/4 are all downstream of it) is the whole design. Two prior
         review rounds rejected an earlier version of this hook that fired
         on correct, fully-warranted turns - a guard that fires on correct
         behavior trains the conductor to ignore its own feedback channel,
         which is worse than no hook at all.

         `background_tasks[]` in the Stop payload is deliberately NOT read
         at all. An earlier design used it and was rejected: harness state
         cannot distinguish "the conductor is yielding" from "the
         conductor is doing something else while agents happen to be
         running in the background" - only the shape of the message text
         itself can.

         A two-layer loop guard bounds how often this hook can re-invoke the
         model - via a BLOCK (`_execution_prose_flag`, DS-156) or an
         ADVISORY (`_answer_relevance_flag`/`_status_only_flag`/volume/
         sprawl) - mirroring the sibling enforce-no-abdication.py. On the
         Claude Code harness, a Stop hook's block (or `additionalContext`
         advisory) re-invokes the model immediately (it does not wait for a
         user turn); when the conductor is blocked on a user decision it has
         nothing substantive to say, so it writes a short status turn, the
         hook flags it, the block/advisory re-invokes the model, and the
         pair loops until the harness's own 9-consecutive-block override
         fires. Layer 1: the `stop_hook_active` payload flag - set by CC
         when this Stop event itself was triggered by a prior Stop-hook
         action - exits silently right after stdin parse. Layer 2: a
         counter-cap backstop for CC bug #54360 (stop_hook_active can fail
         to propagate when a UserPromptSubmit hook interleaves system
         reminders), state at
         <cwd>/.agentic/.turn-shape-guard-fire-count; the counter increments
         and persists BEFORE each block/advisory (a finding whose count
         cannot be persisted is NOT emitted - it would lose its loop bound)
         and resets on a clean turn and on a genuine new user message, so a
         flagged conductor gets at most CONSECUTIVE_BLOCK_CAP block/advisory
         emissions before this hook goes silent. ONE shared counter/cap
         governs BOTH checks (DS-156) - there is no per-check loop bound.
         The counter + user-message-counting machinery lives in the shared
         module hooks/lib/loop_guard.py, loaded lazily via
         _load_loop_guard(); when cwd is absent (synthetic payloads only -
         the CC Stop payload always carries cwd) the counter cannot be
         scoped, so this hook falls through to its legacy advisory-only
         behavior rather than silently swallowing findings.

         Undocumented-until-DS-155 UX cost of the above: the loop guard
         bounds how many TIMES the model is re-invoked, but it does nothing
         about what the operator SEES on each re-invocation. The harness
         does not retract or replace the already-streamed flagged message
         when `additionalContext` re-invokes the model - the operator sees
         BOTH the original flagged turn AND the corrected re-invocation
         turn, back to back, for every single advisory fire. At
         CONSECUTIVE_BLOCK_CAP=2 that is up to two extra visible duplicate
         turns stacked on top of the one substantive turn the operator
         actually wanted, on ONE user-facing exchange. This is a real,
         user-visible cost of the advisory mechanism itself, not a bug in
         the loop-count bound - see also
         content/references/conductor-turn-format.md's Hook contract
         section and residual-false-positive list, which name the same
         cost from the operator-facing side.

Public API: Run as a Claude Code Stop hook (matcher: "*"). Reads JSON from
            stdin. ALWAYS exits 0 (DS-156: the process exit code stays 0
            even on a BLOCKING finding - it is the `"decision": "block"`
            payload, not the process exit code, that stops the turn, the
            same convention enforce-no-abdication.py uses). On a clean
            turn (no findings), emits nothing on stdout. On an
            `_execution_prose_flag` finding, emits exactly one JSON
            object:
              {"decision": "block", "reason": "TURN-SHAPE: <finding>"}
            On any other flagged turn (advisory), emits exactly one JSON
            object:
              {"hookSpecificOutput": {"hookEventName": "Stop",
                                       "additionalContext": "TURN-SHAPE: <finding>"}}
            `additionalContext` (not `systemMessage`) is used deliberately -
            it reaches the model as a system reminder on its next turn,
            giving the conductor a chance to self-correct, whereas
            `systemMessage` is operator-only and invisible to the model.

Upstream deps: Python 3 stdlib only (json, os, re, sys) plus the shared
               hooks/lib/loop_guard.py module (counter + user-message-
               counting machinery for the loop guard), loaded lazily via
               _load_loop_guard(). Lazily imports the shared fire-logging
               helper hooks/lib/enforcement_log.py (log_fire) only on the
               branch that emits a finding - see _load_log_fire().

Downstream consumers: Claude Code hook runner (Stop event, matcher "*").
                      Wired via ~/.claude/settings.json by
                      .claude/install.sh, registered AFTER
                      enforce-no-abdication.py (order: stop-context.js ->
                      enforce-no-abdication.py -> enforce-turn-shape.py).
                      Because a revert of this file would otherwise leave a
                      dangling registration that blocks every stop
                      (`python3 <missing path>` exits 2, the BLOCKING Stop
                      code), install.sh registers this hook via a guarded
                      command string
                      (`test -f ... && python3 ... || exit 0`), not the
                      bare `python3 {path}` form its siblings use.

Failure modes:
    - Malformed/unparseable stdin: fail-open (exit 0, emit nothing).
    - AE_TURN_SHAPE_GUARD_DISABLE=1: short-circuits to exit 0 before any
      other processing, checked FIRST in main() (mirrors
      enforce-no-abdication.py's KILL_SWITCH_ENV idiom).
    - Config toggle is turn_shape_guard_enabled in .agentic/config.json,
      and its polarity is DELIBERATELY INVERTED from the sibling
      abdication_guard_enabled: this hook's guard is `config.get(
      "turn_shape_guard_enabled") is not False` - i.e. default ON when the
      key or the whole config file is absent. This is intentional, not an
      oversight to "fix" into matching the sibling: it governs BOTH checks
      together (there is no separate toggle per check), and the operator
      decision (DS-156) retains this default-on posture even though
      `_execution_prose_flag` can now block, rather than introducing a
      second opt-in gate for the same hook. A missing or unreadable
      config.json is treated as an empty {} (i.e. the guard stays ON), not
      as a disable signal.
    - Empty/unavailable message text (last_assistant_message absent and
      the transcript fallback yields nothing): fail-open (exit 0, emit
      nothing) - there is nothing to classify.
    - Any exception anywhere in main(): fail-open via an outer
      try/except wrapping the entire body (exit 0), matching
      enforce-no-abdication.py's defense-in-depth pattern.
    - stop_hook_active=true: exit 0 silently (Layer 1 primary re-entrancy
      guard) - a re-invocation must never re-flag the same turn.
    - Counter >= CONSECUTIVE_BLOCK_CAP: exit 0 silently, no advisory
      (Layer 2 backstop for CC bug #54360) - the loop is bounded.
    - Counter write fails (unwritable .agentic/, full disk, corrupt tmp,
      etc.): exit 0 silently, no advisory. Rationale: an advisory whose
      count cannot be recorded loses its loop bound; the safe degradation
      is "don't flag" (never an unbounded advisory loop). Only advisories
      after the incremented count has been successfully persisted are
      emitted.
    - hooks/lib/loop_guard.py cannot be loaded, or cwd is absent so the
      counter cannot be scoped: when cwd is absent this hook falls through
      to its legacy advisory-only behavior (synthetic payloads only); when
      cwd is present but the module cannot load, exit 0 silently (same
      rationale as a failed counter write - never emit an advisory without
      a loop bound).
    - DS-156: this hook CAN now return a blocking decision - exactly one
      code path, `_execution_prose_flag`'s finding branch, emits
      {"decision": "block", ...}. Every OTHER path (advisory findings,
      clean turns, every fail-open/fail-closed guard above) still exits 0
      with either no stdout or an advisory `additionalContext` object; the
      process exit CODE is 0 in every case (see "Public API" above).

Performance: < 5 ms per call on typical transcripts - one optional config
             file read and, only when last_assistant_message is absent, a
             single reverse scan of the transcript JSONL to recover the
             most recent assistant message's text.
"""

import json
import os
import re
import sys

# Kill-switch: set this env var to 1 to disable enforcement entirely.
KILL_SWITCH_ENV = "AE_TURN_SHAPE_GUARD_DISABLE"

# Max consecutive block/advisory emissions since the last new user message
# before this hook goes silent. Keeps the loop guard reachable even when CC
# bug #54360 prevents stop_hook_active from propagating. Shared by BOTH
# _execution_prose_flag (blocking, DS-156) and every advisory check - one
# counter/cap governs how many times either can re-invoke the model.
CONSECUTIVE_BLOCK_CAP = 2

# Counter state file (under .agentic/ which is gitignored). Distinct from the
# abdication hook's .abdication-guard-fire-count so the two guards never
# share state.
COUNTER_FILENAME = ".turn-shape-guard-fire-count"
# State file format: single JSON object {"count": N, "last_user_msg_count": M}

# ---------------------------------------------------------------------------
# Turn-charge model constants (DS-151 rewrite)
# ---------------------------------------------------------------------------
#
# See the module docstring's "Charge model" section for the normative
# charge definition and the amendment (A1-A10) rationale behind each value.
# Grounding for each constant (from the DS-151 architect plan's "Budget
# grounding" table):
#
#   - BASE_BODY_BUDGET=10: round-2 verified realistic 7-line completion and
#     7-line answer turns both fired at 6 under the old model; 10 leaves 3
#     lines margin. The ticket symptom ("15+ line prose turns") fires at 10
#     with 5 lines margin. >= the old largest budget (6), so nothing quiet
#     today becomes noisy.
#   - FENCE_FREE_LINES=20 (aggregate, was 20 PER FENCE under the old model):
#     bounded by two pinned fixtures - a 20-line fence must stay QUIET
#     (F >= 14) and a 30-line fence must stay ADVISORY (F <= 23); 20 sits
#     inside [14, 23] and is the incumbent value, so this is a scope change
#     (per-fence -> aggregate), not a magnitude change.
#   - ITEM_FREE_LINES=3: content/sections/02-delegation.md via
#     content/references/conductor-turn-format.md - "the recommended
#     action, one line of why, and the reversal offer" is three
#     conceptual components, one line each.
#   - WAITING_LINE_MAX_CHARS=120: measured from worked examples (44 and 47
#     chars) and a test fixture (38 chars) in conductor-turn-format.md -
#     ~2.5x the longest honest example.
BASE_BODY_BUDGET = 10  # flat; warrant-independent
FENCE_FREE_LINES = 20  # AGGREGATE across the status region's fences
ITEM_FREE_LINES = 3  # per Operator-decisions item
WAITING_LINE_MAX_CHARS = 120  # a Waiting: line longer than this is prose

# DS-156. Bounds two distinct things, on every execution-turn branch of
# _execution_prose_flag: the identity line at position 1 (both branches),
# and a State:/Running:/Blocked: slot line (general branch only - the
# sole-stoppage branch permits no slot lines at all). See
# content/references/conductor-turn-format.md's "STATUS_LINE_MAX_CHARS ...
# is defined exactly once, here" paragraph for the full normative
# definition and rationale. Deliberately does NOT bound Waiting: lines in
# the shape check (see WAITING_LINE_MAX_CHARS above, which governs the
# advisory volume check only) - importing this bound onto Waiting: lines
# would convert the hook's only forced-yield path from a silent pass into
# a block, a behavior change nobody has authorized.
STATUS_LINE_MAX_CHARS = 200

# DS-156. The Answer-turn volume ceiling: a runaway-generation backstop,
# never a shaping constraint (content/references/conductor-turn-format.md
# section 4/9 explicitly uncaps Answer-turn length). 5x BASE_BODY_BUDGET,
# a deliberately loose multiple chosen to sit well above a realistic
# detailed answer while still catching sustained runaway output.
ANSWER_BODY_BUDGET = 50

# Kept as its own name (rather than inlining ITEM_FREE_LINES everywhere) so
# external references to the per-item cap keep a stable, descriptive name.
MAX_LINES_PER_DECISION_ITEM = ITEM_FREE_LINES

# ---------------------------------------------------------------------------
# Classifier patterns
# ---------------------------------------------------------------------------

# "## Operator decisions" heading (see content/sections/02-delegation.md
# "Operator decisions go last in the turn"). Case-insensitive, tolerant of
# 2+ leading hashes and an optional trailing colon - mirrors
# enforce-no-abdication.py's _OPERATOR_DECISIONS_HEADING_RE.
_OPERATOR_DECISIONS_HEADING_RE = re.compile(
    r"^[ \t]*#{2,}\s*operator decisions\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# A "Waiting:" line - the forced-yield / hard-stop marker.
_WAITING_LINE_RE = re.compile(r"^\s*waiting\s*:\s*\S", re.IGNORECASE)

# DS-156. A recognized State:/Running:/Blocked: status slot line - the
# fixed-set label whitelist _execution_prose_flag's general branch
# permits (content/references/conductor-turn-format.md §4 step 2). A
# label the whitelist was not taught (e.g. "Note:") fails CLOSED (is
# flagged), matching the Known-uncovered-shapes table's explicit "an
# INVENTED label ... FAILS CLOSED" disclosure - this is a fixed-set shape
# test, never a content-legitimacy test.
_STATUS_SLOT_LINE_RE = re.compile(r"^\s*(?:state|running|blocked)\s*:\s*\S", re.IGNORECASE)

# DS-156. Answer-turn relevance ban 2 (opening preamble) - a curated
# phrase list, not a semantic detector (content/references/
# conductor-turn-format.md §5/§9). Anchored to the very start of the
# (stripped) message via \A so mid-answer lexical overlap with these
# phrases is never mistaken for an opening preamble. Tolerates a leading
# markdown bold/italic wrapper ("**Good question.**").
_OPENING_FILLER_RE = re.compile(
    r"\A\s*\*{0,2}(?:"
    r"good\s+question|great\s+question|"
    r"let\s+me\s+(?:look\s+into|check|take\s+a\s+look\s+at|dig\s+into)\s+(?:that|this)|"
    r"here'?s\s+what\s+i\s+found|"
    r"happy\s+to\s+(?:help|answer)(?:\s+with\s+that)?|"
    r"sure(?:,|!|\.)|of\s+course(?:,|!|\.)"
    r")\b",
    re.IGNORECASE,
)

# DS-156. Answer-turn relevance ban 5 (closing recap) - a curated phrase
# list, checked ONLY against the final non-blank line/paragraph of the
# message (a "closing" recap by definition sits at the end, not
# incidentally reusing one of these phrases mid-answer).
_CLOSING_RECAP_RE = re.compile(
    r"\b(?:to\s+(?:summarize|recap|sum\s+up)|in\s+summary|in\s+short|"
    r"that'?s\s+(?:the|my|a)\s+(?:summary|recap))\b",
    re.IGNORECASE,
)

# Terminal-completion signal, ANYWHERE in the domain (identity line + body).
# "[phase: complete]" or an unambiguous terminal-completion phrase.
# Deliberately does NOT match a bare past participle ("done", "shipped",
# "merged") - those are this repo's canonical non-warranted status-ping
# vocabulary ("unit 2 merged", "PR merged, pulling main") and must never be
# laundered into a completion warrant.
#
# DS-156 additions (structured-field sentinels, safe anywhere in the domain
# because the label itself is what makes them unambiguous, not their
# position): `state: complete` / `state: work complete` - the Conductor
# template's own "State:" field (content/references/conductor-turn-format.md's
# "Conductor\nState: ...\nRunning: ...\nBlocked: ..." shape); `run complete`
# / this repo's fixed PR-review-run closing phrase; `all state files are
# written` - the same PR-review-run's other closing phrase.
#
# DS-156 round 3 (Skeptic-caught sampling-frame error - see
# _LEADING_COMPLETION_RE's docstring): `status: DONE` / `status:
# DONE_WITH_CONCERNS` and `review complete` are DELETED, not narrowed. Both
# were justified by an unfiltered corpus that was ~48% subagent (sidechain)
# transcript turns - a population `enforce-turn-shape.py` never evaluates,
# since it is registered on the `Stop` event only (`.claude/install.sh`),
# which fires for the main agent; subagent turns fire `SubagentStop`
# instead, a different, unregistered event. Re-measured on main-agent-only
# turns (isSidechain absent/false): `status: DONE` / `DONE_WITH_CONCERNS`
# contributed 0 of 103 newly-recognised main-agent completions (all 72 of
# its overall-corpus hits were sidechain engineer-role returns); `review
# complete` likewise contributed 0. Worse than merely useless: a conductor
# never emits `Status: DONE` itself - its only appearance in a real
# conductor turn is a RELAY of a subagent's return text (`"The engineer
# returned Status: DONE, spawning the Skeptic now."`), which is exactly a
# still-in-progress turn the guard must still flag. Per AGENTS.md's "prefer
# deletion once nothing is load-bearing" rule, both are removed rather than
# re-scoped. `state: complete` (14), `run complete` (29), and `all state
# files are written` (25) DO have nonzero main-agent contribution and are
# kept, gated by `_has_continuing_work_signal` below.
_COMPLETION_RE = re.compile(
    r"\[phase:\s*complete\]"
    r"|\ball\s+(?:done|complete)\b"
    r"|\bfully\s+complete\b"
    r"|\btask(?:s)?\s+(?:is|are)\s+complete\b"
    r"|\bwork\s+is\s+complete\b"
    r"|\bnothing\s+(?:left|more)\s+to\s+do\b"
    r"|\bstate\s*:\s*(?:work\s+)?complete\b"
    r"|\brun\s+(?:is\s+)?complete\b"
    r"|\ball\s+state\s+files\s+are\s+(?:written|updated|current)\b",
    re.IGNORECASE,
)

# DS-156: a continuing-work signal - when present ANYWHERE in the domain, it
# vetoes the completion warrant regardless of which pattern above or below
# would otherwise have granted it (see _classify_warrants). Two components:
#
#   1. `_RUNNING_FIELD_ACTIVE_RE` - the Conductor template's own "Running:"
#      field carrying a non-empty, non-"nothing"/non-"none" value. Round 3
#      finding: `state: complete` (and the leading-declaration pattern
#      below) both matched turns like "State: work complete and live.\n
#      Running: knowledge PR #1027 auto-merge watcher.\nBlocked: none." -
#      the SAME template's sibling field says work is still running, which
#      the pre-round-3 regex ignored entirely. 7 of the 103 newly-recognised
#      main-agent turns in the round-2 measurement were this exact shape.
#   2. `_CONTINUING_WORK_PHRASE_RE` - derived from 4 REAL main-agent turns
#      the round-3 Skeptic review hand-labelled as false positives (not a
#      hand-written phrase list assumed to generalise - each phrase below
#      is traceable to one of these 4):
#        - "Self-hosting is done. Two Phase 5 deliverables down, one to
#          go." -> `\bone\s+(?:more\s+)?to\s+go\b`
#        - "Done and moving." / body: "Unit C running ... Remaining after
#          C: unit F's re-review, then tests, CI wiring, doc sync." ->
#          `\bremaining\s+after\b`
#        - "Security audit complete." / body: "I will wait for the
#          integration Skeptic to finish ... Skeptic is still running." ->
#          `\b(?:is|are)\s+still\s+running\b`
#        - "Done." / body: "the two background agents ... are still
#          running; I'll fold their results in when they land." -> the
#          same `(?:is|are)\s+still\s+running` phrase.
#      A broader first attempt (also matching bare "waiting on/for" and
#      "still <adjective>" generally) was measured and REJECTED: it
#      additionally caught 6 genuinely-complete main-agent turns where the
#      phrase described something OTHER than this turn's own work ("AUT-405
#      is waiting on [these images]", "three things waiting on you:",
#      "Other Claude Code sessions are still running the pre-refresh hooks"
#      - an unrelated session, not this turn's own dependency). Narrowing to
#      the 3 phrases actually present in the 4 confirmed real false
#      positives, plus the Running: field check, catches all 4 confirmed
#      false positives and all 7 Running:-field cases while introducing
#      exactly 1 new over-suppression in the same measurement pass (a
#      genuine completion mentioning "Other ... sessions are still
#      running" as an unrelated aside) - disclosed as a residual trade-off
#      below, not chased further, matching the discipline already applied
#      to the sub-heading gap. CONVERSE DISCLOSURE (Skeptic Major, round
#      3 sign-off): this veto is deliberately NON-GENERALIZING - it catches
#      only the phrasings measured in the corpus, not "continuing work" as
#      a concept. A leading "Done." paired with any OTHER realistic
#      in-progress phrasing not in the 3-phrase list ("next up", "in
#      flight", "underway", "pending the review", "I'll pick this up
#      when...", "round 2 is running now", etc.) is granted the warrant
#      and goes quiet. This is a deliberate precision-over-recall choice,
#      not an oversight: the measured incidence of these other phrasings
#      in the real corpus is 0 of 90 newly-recognised main-agent turns,
#      and the broader alternative's measured cost (6 wrongly-suppressed
#      genuine completions, see above) is worse than this gap's cost. Not
#      widened without a fresh corpus measurement justifying it.
# DS-157 round 1 added four phrases here; DS-157 round 2 (this version,
# Skeptic Major 1) narrowed/dropped two of them after a fresh full-corpus
# both-directions measurement showed the round-1 set broke as much as it
# fixed on THIS regex specifically (it is shared between
# `_has_body_completion_declaration`'s advisory-suppression use below and
# `_classify_warrants`'s `completion` WARRANT-granting use at
# `_classify_warrants:1113` - round 1's safety analysis reasoned only about
# the former and never noticed the latter). Full-population corpus method
# (same ~/.claude/projects extraction as `_LEADING_COMPLETION_RE`'s
# docstring, main-agent-only, isSidechain absent/false; 3,937 final turns,
# 324 matching any of the four round-1 candidate phrases): each phrase was
# measured in isolation against a BASE (pre-DS-157, 3-phrase) regex, on
# both the `completion` warrant delta and the `_status_only_flag` advisory
# delta.
#   - "review(s) running" / "running on" (KEPT, unchanged from round 1) -
#     "Review running on #639", "Two reviews still running" (the
#     bare-noun-subject form the existing `is|are still running` phrase
#     above does not match, since there is no is/are). Measured: 0
#     completion-warrant false-positive losses, 1 legitimate loss ("A
#     cleanup pass is running on three Minors" - genuinely this turn's own
#     unfinished work), 2 correctly-still-advisory newly-firing cases, both
#     inspected and both genuine (the same "Review running on #639" turn
#     that motivated the phrase, plus the round-1 "in progress" sub-item
#     trap below).
#   - "in progress" (NARROWED, round 2): round 1's bare `\bin\s+progress\b`
#     was measured causing 7 full-population completion-warrant losses, ALL
#     traced to a tracker STATUS VALUE describing an OTHER ticket ("AUT-577
#     still In Progress in another session", "set to In Progress", table
#     cells, backtick-quoted status values) - not this turn's own remaining
#     work. Its one genuine motivating case ("**Done and independently
#     verified:** ... **In progress:** the two remaining Majors...") is
#     bold-wrapped "in progress" - narrowing to that exact shape
#     (`\*\*in\s+progress:?\*\*`) measured 0 of the 7 false positives (none
#     of them are bold-wrapped as exactly "in progress") while still
#     catching the motivating case. NOTE: the narrowed regex has no
#     positional constraint - it matches bold-wrapped `**In progress**` in
#     ANY position (line start, mid-sentence, sub-item), not only when used
#     as a markdown sub-heading. Do not describe this shape as a
#     "sub-heading" elsewhere; that overstates what the regex actually
#     matches (Skeptic finding, DS-157 round 3, Minor 1).
#   - "still open" (DROPPED, round 2) - measured causing 10 full-population
#     completion-warrant losses, 100% false positives on inspection: every
#     instance described a backlog/PR/ticket list ("Still open, in priority
#     order: **THU-85**...", "#414/#422, still open separately", "Still
#     open from earlier, if you want any of it:") - the same
#     other-work-not-this-turn's-own-work shape `_CONTINUING_WORK_PHRASE_RE`'s
#     own docstring above already documents and rejects for the broader
#     phrase set this regex superseded. Its one real motivating instance
#     ("Split done. ... Review running on #639 ... Two loose ends still
#     open.") is already caught by the kept "running on" phrase in the same
#     message - "still open" was redundant there, not load-bearing. No
#     narrower form was substituted: unlike "in progress", no single
#     recurring SHAPE (bold-wrapped, tracker-value, etc.) separates its true
#     from false uses in this corpus; the generic "open" is backlog/PR/
#     issue vocabulary too common to narrow safely without a larger sample.
_RUNNING_FIELD_ACTIVE_RE = re.compile(
    r"^\s*running\s*:\s*(?!nothing\b)(?!none\b)\S", re.IGNORECASE | re.MULTILINE
)
_CONTINUING_WORK_PHRASE_RE = re.compile(
    r"\b(?:is|are)\s+still\s+running\b"
    r"|\bone\s+(?:more\s+)?to\s+go\b"
    r"|\bremaining\s+after\b"
    r"|\*\*in\s+progress:?\*\*"
    r"|\breview(?:s)?\s+running\b"
    r"|\brunning\s+on\b",
    re.IGNORECASE,
)


def _has_continuing_work_signal(text: str) -> bool:
    return bool(_RUNNING_FIELD_ACTIVE_RE.search(text)) or bool(
        _CONTINUING_WORK_PHRASE_RE.search(text)
    )


# DS-156: a LEADING completion declaration - the identity line (the very
# start of the domain, matched via \A / .match() so MULTILINE is never
# enabled and no line other than the first can match) opens with a short
# terminal claim. Two shapes:
#   1. Up to 3 leading words, then "is"/"are", then "done"/"complete"/
#      "completed", then up to 2 short trailing modifiers ("and verified",
#      " deployed") before terminal punctuation. Covers "Done.",
#      "Verification complete.", "Both PRs are done and verified.".
#      Terminal punctuation is `[.!:]` ONLY (round 3: comma removed - see
#      docstring below, Skeptic Major 3) - a trailing comma marks a clause
#      boundary, not a sentence boundary, and matching through it let the
#      pattern grant the warrant on a leading CLAUSE while ignoring
#      whatever continuation followed the comma.
#   2. A leading past-participle completion verb (merged/shipped/deployed/
#      pushed/landed) followed within 40 chars by a completion-adjacent
#      word (live/deployed/merged/complete/done/cleaned up). Covers "Merged
#      and fully cleaned up.".
#
# Corpus method (DS-156, ticket: repo-local ad-hoc, not a numbered ticket
# in this session): extracted every FINAL assistant-turn text (grouped by
# transcript `message.id`, excluding any group that itself contains a
# tool_use block, i.e. the same "completed turn" scope the Stop hook acts
# on) from ~/.claude/projects - 3,341 files, 165,965 assistant entries.
#
# Round 1 measured on the UNFILTERED corpus (6,744 candidate final turns,
# 1,231 already flagged status-only): 7 candidate anywhere-scoped phrases,
# incl. a "merged and (live|deployed)" phrase. A 50-item hand-verified
# sample of newly-matched turns found 3 false positives, ALL traced to the
# "merged/shipped and (live|deployed)" phrase matching a COMPLETED
# SUB-ITEM's description inside a turn whose OVERALL state was still
# in-progress, and all 3 NOT on the identity line.
#
# Round 2 (shipped as commit cf6bc9d5) fixed round 1's defect by moving
# that phrase, plus a new "done/complete" leading-sentence pattern, to an
# IDENTITY-LINE-ONLY match. Its own 80-item precision/recall samples found
# 0 false positives and were reported as the closing measurement - but
# both samples were STILL drawn from the round-1 UNFILTERED corpus.
#
# Round 3 (this version - Skeptic Major 1/2/3 on commit cf6bc9d5): that
# unfiltered corpus is ~48% turns this hook never evaluates -
# `enforce-turn-shape.py` is registered on `Stop` only, which fires for
# the main agent; subagent turns fire the unregistered `SubagentStop`
# event instead. Splitting the corpus by `isSidechain` (3,535 main-agent /
# 3,225 sidechain candidate final turns) and re-deriving every figure on
# the main-agent population alone: pre-fix (origin/main) flagged
# status-only 981 of 3,535 (not 1,231 of 6,744); round 2's fix (commit
# cf6bc9d5) recognised 103 of those 981 as completions (not 198/16.1%) -
# 103/981 = 10.5%.
#
# Independently hand-labelling all 103 (not a random sub-sample - the full
# newly-recognised main-agent set) found 4 genuine false positives (3.9%)
# and 7 borderline (the Running:-field shape above), none caught by round
# 2's identity-line restriction because the false-positive shape here is
# different: round 1's traps put the risky phrase in the BODY; these put a
# genuinely short, sentence-complete completion declaration ON the
# identity line, with the continuing-work signal appearing SEPARATELY,
# later in the body ("Security audit complete." ... "Skeptic is still
# running."). Position alone cannot distinguish this shape - hence
# `_has_continuing_work_signal` above.
#
# After applying all round-3 fixes (delete `status: DONE`/`DONE_WITH_
# CONCERNS`/`review complete` outright - 0 main-agent contribution each;
# drop the comma from `_LEADING_COMPLETION_RE`'s terminator class; gate
# every remaining pattern on `_has_continuing_work_signal`), re-running the
# full pipeline on the same 981-turn population: 90 are newly recognised as
# completions (9.2%), 891 remain correctly flagged status-only (90.8%). 13
# of round 2's 103 are correctly reverted back to flagged - the 4 confirmed
# false positives, the 7 Running:-field cases, and 2 further instances of
# the same `(?:is|are)\s+still\s+running` phrase caught along the way.
#
# Independently re-labelled this round-3 set of 90 (not sampled - all 90,
# same full-population discipline as round 2): 0 confirmed false
# positives. One residual is disclosed rather than chased: of the 13
# turns reverted to flagged, 1 was itself a genuine completion ("Other
# Claude Code sessions are still running the pre-refresh hooks in memory"
# - an aside about an UNRELATED session, not this turn's own dependency)
# over-suppressed by the same `(?:is|are)\s+still\s+running` phrase that
# correctly catches the 3 real false positives using that exact shape.
# Distinguishing "my own dependent work is still running" from "an
# unrelated process is running" requires semantic understanding this
# lexical guard does not have - not attempted here, matching the
# discipline already applied to the sub-heading gap below.
#
# Also re-checked (Skeptic Major 3): Confirmed by execution that a leading
# declaration followed by a body continuing-work signal, OR a relayed
# `Status: DONE` substring inside ongoing prose ("The engineer returned
# Status: DONE, spawning the Skeptic now."), no longer grants the warrant
# under this version - the former via `_has_continuing_work_signal`, the
# latter because the `status: DONE` sentinel is deleted outright.
#
# Known residual gap, PARTIALLY closed by DS-157 and DS-159 (see
# _has_body_completion_declaration below - those fixes suppress the
# ADVISORY status-only nag for a completion declared in the body's first
# paragraph (DS-157) or as the identity line's own trailing sentence
# (DS-159), but deliberately do NOT extend this WARRANT-granting regex's
# own domain past the identity line's first sentence; see that function's
# docstring for why): a completion declared under a markdown sub-heading
# (e.g. "## Done") several lines into the body, rather than in the first
# body paragraph or on the identity line, is still not recognised as a
# `completion` WARRANT - see
# `hooks/tests/fixtures/turn-shape-completion-corpus.json` case A9.
_LEADING_COMPLETION_RE = re.compile(
    r"\A\s*\*{0,2}"
    r"(?:"
    r"(?:[A-Za-z][\w'/-]*\s+){0,3}(?:is\s+|are\s+)?(?:done|complete|completed)"
    r"(?:\s*,?\s*(?:and\s+)?[a-z]+){0,2}"
    r"|(?:merged|shipped|deployed|pushed|landed)\b.{0,40}?"
    r"\b(?:live|deployed|merged|complete|completed|done|cleaned up)\b"
    r")\*{0,2}[.!:]",
    re.IGNORECASE,
)

# DS-157. A TALLY/partial-progress header ("Three done, two building:",
# "Four of seven done:") - structurally identical to a genuine leading
# completion declaration (a short leading-words group, then "done", then
# comma-joined trailing modifiers, then a terminal `:`), but it introduces a
# MIXED breakdown of an overall still-in-progress turn, not a claim that
# THIS turn's work is complete. Measured directly from the DS-157 corpus
# (see _has_body_completion_declaration): "Three done, two building:" and
# "Four of seven done:" both matched the leading-completion shape and were
# both false positives, in both cases immediately followed by a table
# showing some rows still building/queued. Scoped to a leading
# number-word/digit specifically (not e.g. "Both units shipped." - two is a
# pronoun there, not a tally count) so it does not reopen the identity-line
# `_LEADING_COMPLETION_RE` path, which this constant is never used against.
_TALLY_HEADER_RE = re.compile(
    r"^\*{0,2}(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:of\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
    r"(?:is\s+|are\s+)?(?:done|complete|completed)\b",
    re.IGNORECASE,
)

# DS-159. A BARE trailing completion word as the identity line's OWN final
# sentence - e.g. "All three shipped. Done." - deliberately narrow:
# `_LEADING_COMPLETION_RE`'s `\A` anchor never scans past the identity
# line's first sentence (see `_has_body_completion_declaration`'s
# docstring for the DS-157 sibling gap this closes for the BODY case), so
# a genuine completion declared as a SECOND sentence on the identity line
# itself - rather than in the body's first paragraph - was equally
# invisible. Consumed only by `_identity_line_trailing_completion` below,
# itself only an ADVISORY-suppression input to
# `_has_body_completion_declaration` - see that function's docstring for
# why this never widens the BLOCKING `completion` WARRANT.
#
# Scoped to a single bare word (+ optional bold markers) precisely
# because a general "match _LEADING_COMPLETION_RE against every later
# sentence" was measured unsafe: against a ~12.8k-turn corpus
# (`~/.claude/projects`, main-agent-only, isSidechain absent/false) it
# produced 30 newly-granted matches, at least 2 confirmed false positives
# ("Status while it completes:" - `_LEADING_COMPLETION_RE`'s optional
# trailing-word group silently absorbed the "s" in "completes" via its
# missing `\b`; "Both mechanical fixes are done. Now finalizing state
# files..." - a genuine DS-156-round-1-class sub-item match on a MIDDLE
# sentence of a still-in-progress turn). Restricting to only the FINAL
# sentence removed the middle-sentence class but not "Will report when
# done." (a future-tense promise, not a completion) or "Writing the file
# complete." (extra words before "complete" reopening the same
# `_LEADING_COMPLETION_RE` looseness). This closed-vocabulary bare-word
# regex was re-measured against the same corpus at 3 newly-granted
# matches, all 3 confirmed genuine ("Fix confirmed against live traffic.
# Done.", "All three shipped. Done.", "All three PRs merged and verified
# on `main`. Done."), 0 false positives, 0 losses.
_BARE_TRAILING_COMPLETION_RE = re.compile(
    r"\A\*{0,2}(?:done|complete|completed|finished)\*{0,2}[.!]\Z",
    re.IGNORECASE,
)

# Splits a line into sentences on a terminal `.`/`!`/`:` followed by
# whitespace - used only to isolate the identity line's OWN final
# sentence for `_identity_line_trailing_completion` below. Deliberately
# not fence-aware or otherwise general-purpose: the identity line is
# always a single raw line by `_segment`'s construction.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!:])\s+")


def _identity_line_trailing_completion(identity_line: str) -> bool:
    """True iff the identity line has more than one sentence AND its FINAL
    sentence is a bare completion word (see `_BARE_TRAILING_COMPLETION_RE`).
    See that constant's docstring for the corpus measurement behind the
    narrow bare-word shape."""
    sentences = _SENTENCE_BOUNDARY_RE.split(identity_line)
    if len(sentences) < 2:
        return False
    return bool(_BARE_TRAILING_COMPLETION_RE.match(sentences[-1].strip()))

# Best-effort "answer" warrant: a quoted fragment (>=8 chars inside the
# quote marks) anywhere in the message. Deliberately loose - this is the
# weakest of the four detectors by design (see module docstring). It
# cannot verify the quote actually echoes the operator's preceding
# message; it only recognizes the SHAPE of "I am answering by quoting
# something".
#
# The single-quote alternative is DELIBERATELY OMITTED (Skeptic Major 1):
# `'[^'\n]{8,}'` matches the text between any two apostrophes in ordinary
# English prose - "they're green, that's all", "I don't think we can't
# merge yet" both false-positive as a quoted "answer". A straight-quote
# pair heuristic is not a reliable single-quote detector on prose that
# routinely contains contractions and possessives, and this detector is
# explicitly licensed to be loose only in the "cannot verify an echo"
# sense - not in the sense of matching non-quote punctuation. Double
# quotes and a leading blockquote marker (">") remain, since neither is
# routinely produced by ordinary prose.
_QUOTED_FRAGMENT_RE = re.compile(r'"[^"\n]{8,}"|^>\s*\S.{6,}', re.MULTILINE)

# Start of a "## Operator decisions" item: a numbered ("1.", "2)") or
# bulleted ("-", "*", "+") line, allowing up to 3 leading spaces (DS-151:
# was column-0 anchored, which let an indented item escape recognition -
# CF-2's indented-item bypass) followed by whitespace then non-whitespace.
# Used by _decision_items (consumed by both _turn_charge and
# _decision_item_sprawl_flag).
_DECISION_ITEM_START_RE = re.compile(r"^ {0,3}(?:\d+[.)]|[-*+])\s+\S")


def _body_after_identity_line(text: str) -> list:
    """Return all lines AFTER the first non-blank (identity) line.

    Raw-line path, deliberately NOT fence-aware - used only by
    _status_only_flag and _forced_yield_flag. See the module docstring's
    "Known implementation seam" note (DS-151 amendment A7) for why those
    two checks stay on this path rather than _segment's fence-aware
    structure.
    """
    lines = text.splitlines()
    seen_identity = False
    body = []
    for line in lines:
        if not seen_identity:
            if line.strip():
                seen_identity = True
            continue
        body.append(line)
    return body


# ---------------------------------------------------------------------------
# Shared structural helpers (DS-151): single source of truth for fence and
# region structure, consumed by _classify_warrants, _turn_charge, and
# _decision_item_sprawl_flag.
# ---------------------------------------------------------------------------


def _segment(text: str) -> tuple:
    """(identity_line, [(line, is_fenced), ...]) for lines AFTER the
    identity line. Fenced = inside a MATCHED ``` pair, inclusive of both
    delimiters. An unmatched trailing opener is NOT fenced (fail closed).
    Single source of truth for fence structure - _regions, _decision_items,
    _classify_warrants, and _turn_charge all consume this; none re-parses
    fence structure independently."""
    lines = text.splitlines()
    idx = len(lines)
    identity_line = ""
    for i, line in enumerate(lines):
        if line.strip():
            identity_line = line
            idx = i + 1
            break
    body_lines = lines[idx:]

    fence_positions = [i for i, ln in enumerate(body_lines) if ln.strip().startswith("```")]
    matched = set()
    i = 0
    while i + 1 < len(fence_positions):
        open_i, close_i = fence_positions[i], fence_positions[i + 1]
        for k in range(open_i, close_i + 1):
            matched.add(k)
        i += 2

    return identity_line, [(ln, idx2 in matched) for idx2, ln in enumerate(body_lines)]


def _regions(body: list) -> tuple:
    """Split body at the first UNFENCED '## Operator decisions' heading.
    (status_lines, decisions_lines, heading_present). The heading line
    belongs to neither region."""
    for i, (line, is_fenced) in enumerate(body):
        if not is_fenced and _OPERATOR_DECISIONS_HEADING_RE.match(line):
            return body[:i], body[i + 1:], True
    return body, [], False


def _decision_items(decisions: list) -> tuple:
    """([(label, line_count), ...], non_item_line_count).

    An item starts at an unfenced non-blank line matching
    _DECISION_ITEM_START_RE; every subsequent non-blank line - fenced OR
    unfenced (DS-151 amendment A2: fenced content inside an item folds
    into that item's line count, it does not escape for free) - folds into
    it until the next unfenced item-start line. Non-blank lines BEFORE the
    first item start, and any when no item exists at all, are counted in
    non_item_line_count - never silently ignored (this is exactly the gap
    that produced the DS-151 CF-2 convergence failure).
    """
    items = []
    label = None
    count = 0
    non_item = 0
    for line, is_fenced in decisions:
        if not line.strip():
            continue
        if not is_fenced and _DECISION_ITEM_START_RE.match(line):
            if label is not None:
                items.append((label, count))
            label = line.strip()
            count = 1
        elif label is not None:
            count += 1
        else:
            non_item += 1
    if label is not None:
        items.append((label, count))
    return items, non_item


def _classify_warrants(text: str, answer_bonus: bool = False) -> dict:
    """Detection domain is the identity line plus UNFENCED body lines only
    (DS-151) - a warrant token inside a fence is an example being
    discussed, not a warrant. The identity line carries "[phase:
    complete]", so it MUST remain in the domain.

    answer_bonus (DS-155): OR'd into the `answer` warrant alongside
    _QUOTED_FRAGMENT_RE. Callers pass the result of
    _transcript_answer_bonus (True when the operator's most recent genuine
    message looks like a direct question) so a plain-prose reply to a
    direct question satisfies the warrant without needing a quoted
    fragment. Defaults to False so every existing single-argument call
    site (including hooks/tests/test-turn-charge-model.py's direct
    _turn_charge(text) calls) is unaffected."""
    identity_line, body = _segment(text)
    unfenced_lines = [ln for ln, is_fenced in body if not is_fenced]
    domain_text = identity_line + "\n" + "\n".join(unfenced_lines)
    completion_claimed = bool(_COMPLETION_RE.search(domain_text)) or bool(
        _LEADING_COMPLETION_RE.match(domain_text)
    )
    return {
        "decision": bool(_OPERATOR_DECISIONS_HEADING_RE.search(domain_text)),
        "stoppage": any(_WAITING_LINE_RE.match(ln) for ln in unfenced_lines),
        # DS-156 round 3: a completion claim is vetoed outright when a
        # continuing-work signal is present anywhere in the same domain -
        # see _has_continuing_work_signal's docstring.
        "completion": completion_claimed and not _has_continuing_work_signal(domain_text),
        "answer": bool(_QUOTED_FRAGMENT_RE.search(domain_text)) or answer_bonus,
    }


def _has_body_completion_declaration(text: str) -> bool:
    """DS-157. True iff the FIRST unfenced paragraph immediately following
    the identity line opens with a leading completion declaration (the same
    shape `_LEADING_COMPLETION_RE` recognizes on the identity line itself),
    the domain carries no continuing-work signal, and that paragraph is not
    a tally/partial-progress header.

    ADVISORY-ONLY consumer, deliberately: this feeds `_status_only_flag`
    ONLY (suppresses the nag on a genuine completion report whose identity
    line does not itself carry a recognizable leading declaration - see the
    reported symptom below). It is NEVER folded into `_classify_warrants`'s
    `completion` key, and therefore never grants the `completion` WARRANT
    or routes a turn onto the BLOCKING `_execution_prose_flag` path. This is
    a deliberate, measured design choice, not an oversight - see "Why not
    widen the warrant" below.

    Reported symptom (DS-157, ticket: repo-local ad-hoc): "Both units
    shipped.\\n\\n**DS-156 is done.** ..." was flagged status-only. The
    identity line "Both units shipped." does not match
    `_LEADING_COMPLETION_RE` - "shipped" is a recognized leading
    past-participle, but the pattern requires a completion-adjacent word
    (live/deployed/merged/complete/done/cleaned up) within 40 characters
    after it, and none follows before the sentence ends. The genuine
    completion declaration, "**DS-156 is done.**", is in the body's first
    paragraph, not the identity line - `_LEADING_COMPLETION_RE`'s `\\A`
    anchor deliberately never scans past position 1 (DS-156 round 1 found
    an anywhere-scoped version of this pattern false-positives on completed
    SUB-ITEMS inside still-in-progress turns).

    Corpus method: same population as `_LEADING_COMPLETION_RE`'s DS-156
    corpus history (`~/.claude/projects`, main-agent-only final turns,
    isSidechain absent/false; re-run for DS-157 at 3,564 files / 3,901
    main-agent candidate final turns, 970 currently flagged status-only -
    the corpus is a live, growing directory, so these are point-in-time
    figures, not a reproducible constant).

    Round 1 (REJECTED): matched the leading-completion shape against the
    first line of ANY unfenced paragraph anywhere in the body, gated only
    by the existing `_has_continuing_work_signal`. 15 of 970 status-only
    turns newly matched; independently hand-labelling all 15 found 4 false
    positives (26.7%) - all four reproducing DS-156 round 1's exact defect
    class one position over: a genuinely short, sentence-complete
    completion-shaped header ("Three done, two building:", "Four of seven
    done:", "**Done and approved:**") describing progress on only PART of a
    still-in-progress turn, or a full turn whose OVERALL state was still
    in-progress two paragraphs later ("Fix round running. ... **Done and
    independently verified:** the feature works. ... **In progress:** the
    two Majors ..."). None of the 4 were on the identity line, matching the
    "anywhere-scoped body match reopens the sub-item trap" pattern the
    identity-line anchor was originally built to close.

    Round 2: restricted the domain to the FIRST unfenced paragraph
    immediately after the identity line only (not "any paragraph"), and
    added a `_TALLY_HEADER_RE` exclusion for a leading number-word/digit
    tally shape. This alone eliminated 2 of the 4 round-1 false positives
    (the ones whose match was NOT the first paragraph) but left 2 survivors
    whose match WAS the first paragraph: the tally-header case ("Three
    done, two building:") and the sub-item case ("**Done and independently
    verified:**" as literally paragraph 1, with "**In progress:**" as
    paragraph 2 of the SAME still-in-progress turn).

    Round 3: the tally survivor is closed by `_TALLY_HEADER_RE` (added in
    this round). The sub-item survivor, plus a THIRD false positive found
    while re-measuring round 2's fix on the full 970-turn population
    ("Split done. ... Review running on #639 ... Two loose ends still
    open."), are closed by extending `_CONTINUING_WORK_PHRASE_RE` with four
    phrases measured directly from these real false positives: "in
    progress", "review(s) running", "running on", "still open". This round's
    OWN measurement was one-directional (see below) and missed a defect in
    its own fix.

    Round 4 / DS-157 round 2 (current, Skeptic Major 1/Minor 1): round 3's
    measurement above tracked only `_status_only_flag` newly going quiet -
    it never measured turns that newly START firing, nor (the actual bug)
    that `_CONTINUING_WORK_PHRASE_RE` is ALSO consumed by
    `_classify_warrants` (`_classify_warrants:1113`) to veto the
    `completion` WARRANT itself, a path round 3's safety analysis never
    mentioned. Re-measured all three directions on the full main-agent
    population (3,937 final turns, 324 matching any of round 3's four
    phrases) with each phrase isolated against a pre-DS-157 3-phrase
    baseline:
      - "review(s) running" / "running on": 0 status-only newly-quiet, 2
        newly-firing (both inspected, both genuine ongoing work); 0
        completion-warrant gains, 1 loss (inspected, genuine - "a cleanup
        pass is running on three Minors"). KEPT unchanged.
      - "in progress": 0 status-only newly-quiet, 2 newly-firing; 0
        completion-warrant gains, 7 losses - ALL 7 inspected and ALL 7
        false positives (a tracker STATUS VALUE for an OTHER ticket, e.g.
        "AUT-577 still In Progress in another session", never this turn's
        own work). NARROWED to the exact bold-wrapped shape the one
        genuine motivating case actually has (`\\*\\*in\\s+progress:?\\*\\*`) -
        re-measured at 0 of the 7 false positives while still catching the
        motivating case. The regex itself has no positional constraint (it
        matches bold-wrapped `**In progress**` anywhere, not only as a
        markdown sub-heading) - see this file's `_CONTINUING_WORK_PHRASE_RE`
        docstring for the full caveat.
      - "still open": 0 status-only newly-quiet, 2 newly-firing; 0
        completion-warrant gains, 10 losses - ALL 10 inspected and ALL 10
        false positives (backlog/PR/ticket-list vocabulary describing OTHER
        work, e.g. "Still open, in priority order: **THU-85** ..."). Its
        one real motivating instance is already caught by the co-occurring
        "running on" phrase in the same message, so nothing was lost by
        dropping it. DROPPED outright, per this file's stated discipline of
        deletion over a narrowed rewrite when nothing is load-bearing on
        the claim (no single recurring shape separates "still open" true
        positives from false positives in this corpus, unlike "in
        progress"'s bold-wrapped shape).
    Net status-only-advisory effect of this round's fix, all four phrases
    combined vs the round-3 shipped set: 0 change in newly-quiet (dropping
    "still open"/narrowing "in progress" removes no legitimate suppression,
    since neither ever independently produced one in this population), 2
    fewer newly-firing false vetoes eliminated (the "in progress"/"still
    open" instances that had been vetoing genuine completions on unrelated
    grounds). Net completion-warrant effect: 17 of 18 measured full-
    population warrant losses eliminated (7 "in progress" + 10 "still
    open"), 1 genuine loss ("running on") retained correctly.
    `_execution_prose_flag` block/pass delta across this same population:
    0 in both directions (no measured turn's execution-path outcome
    changed). See `_CONTINUING_WORK_PHRASE_RE`'s own docstring for the
    phrase-to-instance mapping. A completion declared later than the first
    body paragraph remains a disclosed, unrecognised residual (see
    `_LEADING_COMPLETION_RE`'s "Known residual gap" comment and case A9 in
    `hooks/tests/fixtures/turn-shape-completion-corpus.json`).

    Why not widen the `completion` WARRANT instead (the blocking-path
    safety analysis this ticket required): every one of the 6 confirmed
    true positives is a multi-paragraph prose report with bulleted detail
    ("- Killed any dev servers...", "- Removed both agent worktrees..."),
    not a terse `State:`/`Running:`/`Blocked:`/`Waiting:` slot-line turn.
    Granting the `completion` warrant would route each of them onto
    `_execution_prose_flag`'s GENERAL branch (§4/§9,
    content/references/conductor-turn-format.md), which permits ONLY
    recognized slot lines or `Waiting:` lines in the unfenced status
    region - every one of those bullet lines is "unrecognized" under that
    whitelist and would BLOCK. Verified by execution against the reported
    example with the warrant granted synthetically: `_execution_prose_flag`
    returns a blocking finding ("unrecognized line in the status region").
    Widening the warrant would therefore convert today's advisory nag into
    a hard BLOCK on the exact turns it is meant to help - objectively worse
    than the status quo. Suppressing only `_status_only_flag`'s advisory
    output, without granting the warrant, is the safe fix: it silences the
    nag on a genuine completion report without moving that report onto a
    structural shape check it was never written to satisfy.

    DS-159 addendum: this function ALSO now returns True when the
    completion declaration is the identity line's OWN final sentence
    (`_identity_line_trailing_completion`) rather than the body's first
    paragraph - see the reported symptom "All three shipped. Done.\\n\\n|
    ticket | what landed |\\n..." (a markdown table, not prose, as the
    first body paragraph). Same "why not widen the warrant" analysis
    applies and was re-verified: synthetically granting `completion` for
    this exact example still returns `_execution_prose_flag`'s blocking
    finding (the table row is an unrecognized status-region line), so this
    stays an advisory-only addition, same as the rest of this function.
    """
    identity_line, body = _segment(text)
    unfenced_lines = [ln for ln, is_fenced in body if not is_fenced]
    domain_text = identity_line + "\n" + "\n".join(unfenced_lines)
    if _has_continuing_work_signal(domain_text):
        return False

    if _identity_line_trailing_completion(identity_line):
        return True

    paragraphs = []
    current = []
    for line in unfenced_lines:
        if not line.strip():
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    if not paragraphs:
        return False

    first_line = paragraphs[0][0].strip()
    if _TALLY_HEADER_RE.match(first_line):
        return False
    return bool(_LEADING_COMPLETION_RE.match(first_line))


def _status_only_flag(text: str, warrants: dict) -> bool:
    """Fires when the message exceeds ~1-2 lines of prose outside the
    identity line AND carries none of the four warrants, AND (DS-157) the
    body's first paragraph is not itself a recognized completion
    declaration - see `_has_body_completion_declaration`'s docstring for
    why that check suppresses only this advisory, never the `completion`
    WARRANT itself. Raw-line path for the line-count test - see the module
    docstring's "Known implementation seam" note."""
    if any(warrants.values()):
        return False
    if _has_body_completion_declaration(text):
        return False
    body_lines = [ln for ln in _body_after_identity_line(text) if ln.strip()]
    return len(body_lines) > 2


def _execution_prose_flag(text: str, warrants: dict):
    """Return a finding string, or None. BLOCKING (DS-156) - implements
    content/references/conductor-turn-format.md §4's execution-turn
    structural rule. REPLACES _forced_yield_flag; it does not run
    alongside it - the sole-stoppage branch below is predicate-identical
    to the deleted _forced_yield_flag (same gate, same
    _body_after_identity_line domain, same _WAITING_LINE_RE, no length
    test on Waiting: lines), so nothing that used to pass now fails on
    that branch alone.

    Called ONLY for execution turns (answer warrant ABSENT, at least one
    of decision/stoppage/completion PRESENT) - see main()'s three-way
    classification gate; a zero-warrant turn routes to _status_only_flag
    instead, and an Answer turn routes to _answer_relevance_flag instead.

    On BOTH branches below, the identity line at position 1 is checked
    for LENGTH ONLY, never shape, against STATUS_LINE_MAX_CHARS - the
    bound is a property of position 1 itself, not of which branch is
    running (a sole-stoppage turn cannot use its wider raw-line domain to
    smuggle an over-length line into position 1).
    """
    identity_line, body = _segment(text)
    if len(identity_line) > STATUS_LINE_MAX_CHARS:
        return (
            "execution turn: identity line is {} characters, over the "
            "{}-character limit"
        ).format(len(identity_line), STATUS_LINE_MAX_CHARS)

    stoppage_sole = warrants["stoppage"] and not (
        warrants["decision"] or warrants["completion"]
    )

    if stoppage_sole:
        # Sole-stoppage branch: every non-blank RAW line after the
        # identity line, fenced or not, must be a Waiting: line. Same
        # domain _forced_yield_flag inspected today via
        # _body_after_identity_line.
        for line in _body_after_identity_line(text):
            if not line.strip():
                continue
            if not _WAITING_LINE_RE.match(line):
                return (
                    "execution turn (sole-stoppage): line other than a "
                    "Waiting: line present after the identity line"
                )
        return None

    # General branch: decision and/or completion present, with or without
    # stoppage. Inspects only the unfenced lines of the fence-aware status
    # region. Waiting: lines are exempt from the length bound by design.
    status_lines, _decisions_lines, _heading_present = _regions(body)
    for line, is_fenced in status_lines:
        if is_fenced or not line.strip():
            continue
        if _WAITING_LINE_RE.match(line):
            continue
        stripped = line.strip()
        if _STATUS_SLOT_LINE_RE.match(line):
            if len(stripped) > STATUS_LINE_MAX_CHARS:
                return (
                    "execution turn: status slot line is {} characters, "
                    "over the {}-character limit"
                ).format(len(stripped), STATUS_LINE_MAX_CHARS)
            continue
        return (
            "execution turn: unrecognized line in the status region "
            "(expected only State:/Running:/Blocked: slot lines or "
            "Waiting: lines)"
        )
    return None


def _turn_charge(text: str, warrants: dict = None) -> tuple:
    """(charge, breakdown). breakdown keys: status, fence, decisions,
    fence_lines, items, waiting_ok, nonblank.

    See the module docstring's "Charge model" section for the normative
    charge definition, including why fence_charge is scoped to the status
    region rather than literally "every fence in the message" (required to
    satisfy invariant I8 in hooks/tests/test-turn-charge-model.py - an
    aggregate pool spanning both regions would double-charge fenced content
    inside a decision item, since that content is already charged via
    decisions_charge).

    warrants (DS-155): optional already-computed warrant dict. When
    omitted (every existing test-turn-charge-model.py call site passes
    only `text`), recomputed internally via _classify_warrants(text) -
    identical to pre-DS-155 behavior. main()/_volume_flag pass their own
    already-computed dict so the transcript-derived answer_bonus (see
    _classify_warrants) is applied exactly once and consistently, rather
    than recomputed here without it.
    """
    identity_line, body = _segment(text)
    status_lines, decisions_lines, heading_present = _regions(body)
    if warrants is None:
        warrants = _classify_warrants(text)
    stoppage_sole = warrants["stoppage"] and not (
        warrants["decision"] or warrants["completion"] or warrants["answer"]
    )

    status_charge = 0
    waiting_ok = 0
    fenced_nonblank_status = 0
    for line, is_fenced in status_lines:
        if not line.strip():
            continue
        if is_fenced:
            fenced_nonblank_status += 1
            continue
        stripped = line.strip()
        well_formed_waiting = (
            bool(_WAITING_LINE_RE.match(line)) and len(stripped) <= WAITING_LINE_MAX_CHARS
        )
        if well_formed_waiting and stoppage_sole:
            waiting_ok += 1
            continue
        status_charge += 1

    fence_charge = max(0, fenced_nonblank_status - FENCE_FREE_LINES)

    items, non_item_count = _decision_items(decisions_lines)
    decisions_charge = non_item_count + sum(max(0, count - ITEM_FREE_LINES) for _, count in items)

    nonblank = sum(1 for line, _ in body if line.strip())

    charge = status_charge + fence_charge + decisions_charge
    breakdown = {
        "status": status_charge,
        "fence": fence_charge,
        "decisions": decisions_charge,
        "fence_lines": fenced_nonblank_status,
        "items": len(items),
        "waiting_ok": waiting_ok,
        "nonblank": nonblank,
    }
    return charge, breakdown


def _volume_flag(text: str, warrants: dict):
    """Return a finding string, or None.

    Returns None when zero warrants are present - that case is already
    exclusively owned by _status_only_flag, and a second finding for the
    same defect would just be noise.

    DS-156: on an Answer turn (warrants["answer"] True - §4's "Answer
    always wins the shape question" rule applies here too, regardless of
    which other warrant(s) co-fire), this does NOT short-circuit to
    no-charge. It compares a flat non-blank-line count (none of the
    execution-turn free-pool machinery - status slots, Waiting: lines,
    decision items - constrains Answer-turn shape) against the separate,
    deliberately high ANSWER_BODY_BUDGET ceiling. On an execution turn,
    unchanged from DS-151: flags iff _turn_charge(text)[0] >
    BASE_BODY_BUDGET - see the module docstring's "Charge model" section.
    """
    if not any(warrants.get(name) for name in ("decision", "stoppage", "completion", "answer")):
        return None

    charge, breakdown = _turn_charge(text, warrants)

    if warrants.get("answer"):
        answer_charge = breakdown["nonblank"]
        if answer_charge <= ANSWER_BODY_BUDGET:
            return None
        return (
            "turn volume exceeded: answer turn charge is {charge} non-blank "
            "lines, advisory budget is {budget} (runaway-generation "
            "backstop, not a shaping constraint)"
        ).format(charge=answer_charge, budget=ANSWER_BODY_BUDGET)

    if charge <= BASE_BODY_BUDGET:
        return None

    return (
        "turn volume exceeded: charge is {charge}, budget is {budget} "
        "(status {status}, fenced overflow {fence} of {fence_lines} fenced "
        "lines, decisions {decisions}; {waiting_ok} well-formed Waiting: "
        "lines and the first {free_fence} fenced lines are free)"
    ).format(
        charge=charge,
        budget=BASE_BODY_BUDGET,
        status=breakdown["status"],
        fence=breakdown["fence"],
        fence_lines=breakdown["fence_lines"],
        decisions=breakdown["decisions"],
        waiting_ok=breakdown["waiting_ok"],
        free_fence=FENCE_FREE_LINES,
    )


def _answer_relevance_flag(text: str):
    """Return a finding string, or None. ADVISORY (DS-156) - implements
    content/references/conductor-turn-format.md §5's relevance bans 2
    (opening preamble) and 5 (closing recap) against Answer-turn prose,
    via curated phrase-list regexes. Bans 1, 3, 4, 6 are deliberately NOT
    mechanized - see the module docstring / §9's non-mechanization
    rationale. Called ONLY when the Answer warrant is present (an
    execution turn has no prose region for these bans to inspect)."""
    stripped = text.strip()
    if not stripped:
        return None
    opening = _OPENING_FILLER_RE.match(stripped)
    if opening:
        return (
            "answer turn: opens with a preamble phrase (relevance ban 2) - "
            '"{}"'
        ).format(opening.group(0).strip())
    # Ban 5 is scoped to the CLOSING of the answer, not incidental
    # mid-answer reuse of one of these phrases - checked against the
    # final non-blank paragraph only.
    paragraphs = [p for p in stripped.split("\n\n") if p.strip()]
    tail = paragraphs[-1] if paragraphs else stripped
    recap = _CLOSING_RECAP_RE.search(tail)
    if recap:
        return (
            "answer turn: closes with a recap of what was just said "
            '(relevance ban 5) - "{}"'
        ).format(recap.group(0))
    return None


def _decision_item_sprawl_flag(text: str):
    """Return a finding string, or None.

    Consumes the shared _segment/_regions/_decision_items helpers instead
    of re-slicing text[m.end():]. Item COUNT under "## Operator decisions"
    stays completely unbounded - content/sections/02-delegation.md forbids
    a numeric cap there. This checks per-ITEM SHAPE instead (folding in
    fenced content per amendment A2): each item must fit within
    ITEM_FREE_LINES (aliased MAX_LINES_PER_DECISION_ITEM) lines, matching
    the mandated "recommended action, one line of why, and the reversal
    offer" shape (content/references/conductor-turn-format.md:83). Stays
    ADDITIONAL to the volume check: a lone over-long item can be under the
    whole-message BASE_BODY_BUDGET while still violating per-item shape.
    """
    _, body = _segment(text)
    _, decisions_lines, heading_present = _regions(body)
    if not heading_present:
        return None

    items, _ = _decision_items(decisions_lines)
    for label, count in items:
        if count > MAX_LINES_PER_DECISION_ITEM:
            short_label = label if len(label) <= 60 else label[:57] + "..."
            return (
                "operator-decisions item sprawl: item '{label}' is {count} "
                "lines, budget is {budget} lines per item (recommended "
                "action, one line of why, and the reversal offer - item "
                "COUNT stays unbounded, only per-item shape is bounded)"
            ).format(label=short_label, count=count, budget=MAX_LINES_PER_DECISION_ITEM)
    return None


# ---------------------------------------------------------------------------
# Transcript fallback
# ---------------------------------------------------------------------------


def _resolve_assistant_content(obj: dict):
    """Return the raw `content` value for an assistant-role transcript
    line, or None if `obj` is not an assistant entry. Shared resolution
    step for _extract_assistant_text and _assistant_entry_has_tool_use
    (DS-155 round 3) - both need the SAME raw content value, just
    interpreted differently (concatenated text vs. presence of a
    tool_use block), so this is the single source of truth for "what is
    this entry's content" - mirrors the same discipline already applied
    to _segment/_regions/_decision_items."""
    if not isinstance(obj, dict):
        return None
    role = obj.get("role") or obj.get("type", "")
    if role != "assistant":
        return None
    content = obj.get("content")
    if content is None:
        msg = obj.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content")
    return content


def _extract_assistant_text(obj: dict) -> str:
    """Return the text of `obj` if it is an assistant transcript line, else
    "". Factored out of _last_assistant_text_from_transcript (DS-155) so
    other assistant-text scans do not re-implement the same shape parsing
    independently."""
    content = _resolve_assistant_content(obj)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        # Joined with "\n", not " " (Skeptic Minor): a space-join collapses
        # a multi-block message onto a single line, so
        # _body_after_identity_line() sees an empty body and both the
        # status-only and forced-yield checks go silently inert on this
        # fallback path even though they fire correctly on the primary
        # last_assistant_message path for the same text. Under-flagging is
        # the safe failure direction (a missed finding here means no
        # advisory context or, on the sole-stoppage branch, no BLOCKING
        # decision either - see DS-156's two-posture split), but the
        # fallback should still mirror the primary path's line structure.
        return "\n".join(parts)
    return ""


def _assistant_entry_has_tool_use(obj: dict) -> bool:
    """True iff `obj` is an assistant transcript line whose content
    includes a tool_use block - i.e. this entry is inherently MID-TURN
    scaffolding: the assistant asked to call a tool, so THIS entry can
    never be the FINAL message of a completed Stop-triggered turn (Claude
    Code's Stop event cannot fire mid-tool-call).

    DS-155 round 4 corpus note: real Claude Code transcripts essentially
    NEVER put `text` and `tool_use` in the SAME entry's content array - a
    corpus measurement across 3,429 local transcript files / 169,745
    assistant entries found exactly 4 mixed `('text','tool_use', ...)`
    entries (0.002%) against 83,085 pure `('tool_use',)` entries and
    42,195 pure `('text',)` entries. The real "the model spoke, then
    called a tool" shape is a PURE-TEXT entry followed by a SEPARATE
    pure-`tool_use` entry (measured 30,027 times in the same corpus) -
    this function alone cannot detect that shape, since it only inspects
    ONE entry's own content. See _has_intervening_assistant_turn for how
    the two are combined: this function still catches the rare same-entry
    mixed case, and the caller separately tracks tool_use ACROSS entries
    to catch the common split-entry case.
    """
    content = _resolve_assistant_content(obj)
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
    return False


def _assistant_message_id(obj: dict) -> str:
    """Return `obj["message"]["id"]` if present and non-empty, else None
    (DS-155 round 5).

    Every real Claude Code transcript entry carries this field, and
    entries that are physically split across multiple JSONL lines but
    belong to ONE logical assistant message share the SAME id - this is
    the actual delimiter for "these entries are the same message", not
    proximity in the transcript. Corpus-verified: of 5,480 real adjacent
    (pure-text entry, tool_use entry) pairs sampled, 5,479 (99.98%) share
    one message.id; the remaining 1 pair belongs to two DIFFERENT
    messages that merely happen to be adjacent - exactly the shape that
    defeated the round-4 purely-positional rule (a genuinely separate,
    already-completed turn immediately followed by a new turn that opens
    with a tool call was silently excused). Returns None (not an error) -
    the caller degrades to a positional fallback - when the field is
    absent, not a string, or empty; `obj` not being an assistant entry
    also returns None (obj.get("message") is then typically absent or
    lacks "id").
    """
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message")
    if isinstance(msg, dict):
        mid = msg.get("id")
        if isinstance(mid, str) and mid:
            return mid
    return None


def _last_assistant_text_from_transcript(transcript_path: str) -> str:
    """Best-effort reverse scan for the most recent assistant message text.

    Fallback only - used when last_assistant_message is absent/empty from
    the Stop payload. Mirrors the two transcript shapes handled by
    enforce-no-abdication.py's _scan_transcript_tail, but this hook only
    needs the text (no tool-call tracking), so the scan is simpler: stop
    at the first assistant entry found while scanning in reverse.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return ""

    try:
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            text = _extract_assistant_text(obj)
            if text:
                return text
        return ""
    except Exception:
        return ""


# Cheap, best-effort "this looks like a direct question" signal used by
# _transcript_answer_bonus. A trailing '?' (allowing trailing whitespace/
# quote/paren punctuation) is the strongest reliable signal; a '?' anywhere
# in a SHORT message also counts (covers "quick question: what's the plan
# for X? thanks" where the '?' isn't the literal last character). Length-
# gated deliberately: an incidental '?' buried inside a long paste or diff
# is not evidence the whole message is a question, so it is NOT credited -
# under-crediting here just falls back to today's narrower behavior (no
# crash, no false grant), which is the required soft-fail direction.
_TRAILING_QUESTION_RE = re.compile(r"\?[\s'\")\]]*$")
_SHORT_QUESTION_TEXT_MAX_CHARS = 300


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _TRAILING_QUESTION_RE.search(stripped):
        return True
    return "?" in stripped and len(stripped) <= _SHORT_QUESTION_TEXT_MAX_CHARS


def _has_intervening_assistant_turn(transcript_path: str, current_text: str) -> bool:
    """True iff a genuinely SEPARATE, EARLIER completed assistant turn
    exists between the most recent genuine user message and now - i.e. the
    operator's question is STALE and must not grant the answer bonus.
    Closes the demonstrated repro: operator asks a question, then several
    later background-agent check-in turns pass (each its own COMPLETED
    assistant turn, none of them a reply to the question), and a later
    unrelated status-only or malformed-forced-yield turn was incorrectly
    going QUIET under the ORIGINAL question purely because it was still
    the most recent genuine user line in the transcript.

    History (each round measured against a local Claude Code transcript
    corpus - 900 files / ~1,623 completed-turn evaluation points, unless
    noted otherwise - not assumed from a hand-built fixture):
      - Round 2: introduced this check. Positionally "skip the first
        non-blank text entry, whatever it is" - two bugs, a false positive
        (ANY non-blank text entry counted as a boundary candidate, no
        exemption) and a false negative (the "first one" assumption breaks
        when the current turn's own entry is not yet on disk).
      - Round 3: fixed both round-2 bugs. The false-positive fix exempted
        an entry whose content mixes `text` AND `tool_use` in the SAME
        array, reasoning that shape is the common "narrate, then call a
        tool" pattern. MEASURED WRONG round 4: that same-entry shape
        occurs 4 times in 169,745 real assistant entries (0.002%) - dead
        code, protecting against a shape that essentially never happens.
        Round-3 correctness: 1,025 / 1,623 (63.2%).
      - Round 4: replaced the same-entry check with cross-entry positional
        tracking - a pure-text entry is transparent scaffolding when a
        tool_use entry was seen immediately before it (in time) during the
        reverse scan, consumed by AT MOST one preceding text entry. This
        matched the REAL shape (a pure-text entry followed by a SEPARATE
        tool_use entry, measured 30,027 times) and raised correctness to
        1,580 / 1,623 (97.4%). Still wrong on the remaining 43: pure
        POSITION cannot distinguish "this text precedes ITS OWN later tool
        call" from "this text is a genuinely separate, already-completed
        turn that HAPPENS to be followed by an unrelated turn's tool call"
        - both look identical by position alone. Demonstrated live: a
        completed turn immediately followed by new work opening with a
        tool call was silently excused as if it belonged to that new work.
      - Round 5 (current): every real transcript entry carries
        `message.id` (see _assistant_message_id), and entries that
        genuinely belong to the SAME logical assistant message share one.
        That is the real delimiter "position" was only ever a proxy for.
        Scope the tool_use exemption to a SHARED message.id instead of
        position. Corpus-verified: of 5,480 real adjacent (pure-text,
        tool_use) entry pairs, 5,479 (99.98%) share one message.id: the
        id-scoped rule keeps round 4's fix for the common case exact,
        while separately and correctly rejecting the 1-in-5,480 case where
        they do not. Correctness: 1,620 / 1,623 (99.8%).

    NAMED RESIDUAL (round 5, not rounded to zero): 3 of 1,623 evaluation
    points remain wrong, all in the same direction (expected stale=True,
    got False). All 3 share one shape: a pure-text entry and its own later
    tool_use entry share message.id, but a harness-injected/system
    bookkeeping line (a system-role entry, or a non-genuine `user`
    system-reminder) is interleaved BETWEEN them in the transcript. This
    id-set match does not require the two entries to be CONTIGUOUS, so it
    still (correctly, in the sense that they genuinely are one API
    response) treats them as one message and exempts the text entry. A
    stricter contiguity-tracking refinement is a POSSIBLE further fix
    (reset id-pending tracking on any interruption by a non-assistant,
    non-tool_result line) but is NOT implemented here - it was not the
    validated fix for this round, and the gap is disclosed rather than
    hidden.

    Reverse-scans the transcript. For each line, in order:
      1. A genuine user turn (loop_guard.is_genuine_user_turn) is the
         boundary - stop, no intervening turn found (False).
      2. Any assistant entry whose content includes a tool_use block is
         transparent (it can never be a completed turn's final message -
         Stop cannot fire mid-tool-call). If it carries a message.id, add
         that id to a PENDING set (ids are globally unique, so this set
         never needs an entry removed - a later same-id text entry is
         unambiguously the same message, not a positional coincidence).
         If it has NO message.id, set a positional fallback flag instead.
      3. An assistant entry with pure text and no tool_use of its own:
         - If its message.id is in the pending set: transparent mid-turn
           scaffolding (the SAME logical message narrated, then called a
           tool). The id stays in the set (safe - ids are unique).
         - Else, if it has NO message.id and the positional fallback flag
           is set: transparent (FALLBACK for transcripts that never carry
           message.id - reproduces round 4's own rule exactly for that
           class of input). Clear the flag (consumed once).
         - Else, if its text matches `current_text` AND the current-turn
           slot has not been consumed yet: treat it as THIS turn's own
           entry and skip it (consume the slot, once).
         - Otherwise: a genuinely different, earlier completed turn -
           stale (True).

    Fails CLOSED toward True (i.e. "stale, do not grant" - the narrower,
    safer direction) on any read/parse error, when loop_guard is
    unavailable, on an empty transcript_path, or when no genuine user
    boundary is found at all (the scan cannot positively confirm
    recency).
    """
    lg = _LOOP_GUARD
    if lg is None or not transcript_path:
        return True
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return True

    current_stripped = current_text.strip()

    try:
        consumed_current_turn_slot = False
        pending_message_ids = set()
        positional_pending = False
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if lg.is_genuine_user_turn(obj):
                return False  # reached the boundary - no intervening turn
            if _assistant_entry_has_tool_use(obj):
                entry_id = _assistant_message_id(obj)
                if entry_id is not None:
                    # PRIMARY mechanism: track the tool_use's message.id.
                    # IDs are globally unique per assistant message, so
                    # adding to a set never needs to be "consumed" or reset
                    # - a later (older, in reverse scan) text entry sharing
                    # this exact id is unambiguously part of the SAME
                    # logical message, never a coincidence of position.
                    pending_message_ids.add(entry_id)
                else:
                    # FALLBACK: no message.id on this tool_use entry (a
                    # transcript shape that predates the id field, or a
                    # synthetic/hand-built payload). Degrade to the
                    # positional rule alone.
                    positional_pending = True
                continue  # tool_use entry - always mid-turn, never a boundary marker
            assistant_text = _extract_assistant_text(obj)
            if not assistant_text.strip():
                continue  # empty text, no tool_use - never a boundary marker
            # Pure text, no tool_use of its own.
            entry_id = _assistant_message_id(obj)
            if entry_id is not None and entry_id in pending_message_ids:
                # This text entry shares a message.id with a tool_use entry
                # already seen in this reverse scan - the SAME logical
                # assistant message narrated, then called a tool. Mid-turn
                # scaffolding, never a boundary marker.
                continue
            if entry_id is None and positional_pending:
                # FALLBACK: this text entry has no message.id, so identity
                # cannot be verified - fall back to the positional rule
                # (the most recently seen unconsumed tool_use, regardless
                # of id, explains AT MOST one preceding text entry). This
                # reproduces the prior (pre-message.id) behavior exactly
                # for any transcript shape that never carries message.id.
                positional_pending = False
                continue
            if not consumed_current_turn_slot and assistant_text.strip() == current_stripped:
                consumed_current_turn_slot = True
                continue
            return True  # a genuinely different, earlier completed turn
        return True  # no genuine user boundary found - cannot confirm recency
    except Exception:
        return True


def _transcript_answer_bonus(transcript_path: str, current_text: str) -> bool:
    """True iff the operator's most recent GENUINE message (per
    loop_guard.last_genuine_user_text - filters tool_result/meta/harness-
    injected lines) looks like a direct question, per _looks_like_question,
    AND that question is still the IMMEDIATELY preceding turn boundary
    with no intervening completed assistant turn since it was asked (per
    _has_intervening_assistant_turn, compared against `current_text` - the
    turn under evaluation) - a stale question grants nothing.

    Licenses a plain-prose reply to satisfy the `answer` warrant without
    needing _QUOTED_FRAGMENT_RE's narrow quoted-fragment/blockquote shape -
    the module docstring already calls that detector "the weakest of the
    four" and the ticket symptom (a substantive plain-prose answer flagged
    status-only) traces directly to it.

    Soft-fail, matching every other transcript-derived signal in this
    hook: any error (missing/unreadable transcript, no genuine turn found,
    loop_guard unavailable, stale question) returns False - i.e. today's
    narrower behavior. Never raises, never widens the warrant on an
    unconfirmed or stale signal.

    Known residual gap: loop_guard's harness-injected-text filter treats
    ANY text block containing a marker like "<system-reminder>" as
    non-genuine in its entirety (see loop_guard._extract_genuine_user_text)
    - if a live harness ever concatenates the operator's own typed
    question and an injected system-reminder into ONE text block (rather
    than as separate content blocks, which is the observed live shape),
    that whole turn would be invisible to this scan and the bonus would
    fall through to False on an actual question. That failure direction is
    safe (under-grant, never a fabricated grant) but is a real,
    unverified-against-every-harness-version gap, not a closed case.
    """
    if not transcript_path:
        return False
    lg = _LOOP_GUARD
    if lg is None:
        return False
    try:
        text = lg.last_genuine_user_text(transcript_path)
    except Exception:
        return False
    if not _looks_like_question(text):
        return False
    if _has_intervening_assistant_turn(transcript_path, current_text):
        return False
    return True


# ---------------------------------------------------------------------------
# Loop-guard loader (counter + user-message counting live in loop_guard.py)
# ---------------------------------------------------------------------------


def _load_loop_guard():
    """Best-effort dynamic import of the shared loop-guard module.

    Returns None when the module cannot be loaded (missing file, syntax
    error, snapshot copy drift). main() treats a None load as "exit 0
    silently when a cwd is present" (never emit an advisory without a loop
    bound) and as "fall through to legacy advisory behavior when no cwd is
    present" (synthetic payloads only). Loaded once at module scope; every
    invocation reuses the loaded module.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "loop_guard.py")
        spec = _ilu.spec_from_file_location("loop_guard", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_LOOP_GUARD = _load_loop_guard()


# ---------------------------------------------------------------------------
# Fire-log integration
# ---------------------------------------------------------------------------


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of this hook's advisory output.

    Called lazily from inside the finding-emission branch (never at module
    scope), mirroring enforce-tier.py's own _load_log_fire() - the
    overwhelming majority of invocations (every silent allow, and every
    kill-switched invocation) never read, compile, or exec this file at
    all.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "enforcement_log.py")
        spec = _ilu.spec_from_file_location("enforcement_log", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        # Kill-switch: operator escape hatch, checked first.
        if os.environ.get(KILL_SWITCH_ENV) == "1":
            sys.exit(0)

        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        # Layer 1 (primary re-entrancy guard): stop_hook_active is set by CC
        # when this Stop event itself was triggered by a prior Stop-hook
        # action. A re-invocation must never re-flag the same turn.
        if data.get("stop_hook_active") is True:
            sys.exit(0)

        cwd = data.get("cwd", "")
        if not isinstance(cwd, str):
            cwd = ""

        # Resolve transcript_path once, up front (DS-155), so every
        # transcript-derived signal below (loop-guard counting, the
        # last-assistant-message fallback, the answer-warrant bonus) reads
        # the same normalized value instead of each re-deriving it locally
        # with its own type guard.
        transcript_path = data.get("transcript_path", "")
        if not isinstance(transcript_path, str):
            # A non-string value (e.g. a number) would reach open() in
            # loop_guard.count_user_messages, which Python treats as a raw
            # file descriptor - guard it here, mirroring the sibling hook.
            transcript_path = ""

        # Config toggle: DELIBERATELY INVERTED from enforce-no-abdication.py's
        # abdication_guard_enabled (which requires explicit True). This hook
        # defaults ON regardless of its now-BLOCKING _execution_prose_flag
        # posture (DS-156, §9) - only an explicit `false` disables it, a
        # deliberate operator decision, not a legacy carryover from an
        # advisory-only era. Absent/unreadable/malformed config.json is
        # treated as {} (i.e. stays ON), not as a disable signal.
        config = {}
        if cwd:
            config_path = os.path.join(cwd, ".agentic", "config.json")
            try:
                with open(config_path, "r") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                config = {}
        if config.get("turn_shape_guard_enabled") is False:
            sys.exit(0)

        # Layer 2 (counter cap backstop for CC bug #54360): read the current
        # advisory count and the user-message count at the last advisory. If
        # a new genuine user message has arrived since, reset the counter
        # (genuine new turn). When count >= CONSECUTIVE_BLOCK_CAP, exit 0
        # silently - a blocked conductor gets at most CAP advisories before
        # this hook goes silent. The counter is only engaged when a cwd is
        # available to scope it; the CC Stop payload always carries cwd, so
        # the absent-cwd case is synthetic payloads only, where this hook
        # falls through to its legacy advisory-only behavior rather than
        # silently swallowing findings.
        lg = _LOOP_GUARD
        loop_guard_engaged = False
        current_user_msg_count = 0
        state = {"count": 0, "last_user_msg_count": 0}
        if cwd:
            if lg is None:
                # Loop-guard machinery unavailable - cannot bound an advisory.
                # Fail open (never emit an advisory without a loop bound).
                sys.exit(0)
            loop_guard_engaged = True
            if transcript_path:
                current_user_msg_count = lg.count_user_messages(transcript_path)

            state = lg.read_counter(cwd, COUNTER_FILENAME)
            # If the user has sent a new message since the last advisory,
            # reset.
            if current_user_msg_count > state["last_user_msg_count"]:
                lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
                state = {"count": 0, "last_user_msg_count": current_user_msg_count}

            if state["count"] >= CONSECUTIVE_BLOCK_CAP:
                # CAP reached - no more advisories this turn. Prevents the
                # re-invocation loop when stop_hook_active fails to propagate.
                sys.exit(0)

        # Resolve message text: prefer the pre-extracted field, fall back to
        # a transcript scan.
        msg_text = data.get("last_assistant_message", "")
        if not isinstance(msg_text, str):
            msg_text = ""

        if not msg_text.strip():
            if transcript_path:
                msg_text = _last_assistant_text_from_transcript(transcript_path)

        if not msg_text.strip():
            # No message text available - nothing to classify.
            sys.exit(0)

        # 1. Warrant classification (authoritative). answer_bonus is
        # computed from the transcript once, gated on recency
        # (_has_intervening_assistant_turn - a stale question grants
        # nothing, DS-155), and OR'd into the `answer` warrant so a
        # plain-prose reply to a direct operator question no longer needs
        # a quoted fragment - see _transcript_answer_bonus. (DS-155 round
        # 3: this hook no longer runs an identity-line check at all - see
        # the module docstring's "DS-155 round 3 history note".)
        answer_bonus = _transcript_answer_bonus(transcript_path, msg_text)
        warrants = _classify_warrants(msg_text, answer_bonus=answer_bonus)

        # DS-156 three-way, exhaustive, mutually-exclusive classification
        # (content/references/conductor-turn-format.md §9's "Classification
        # order" bullet). Answer always wins the shape question, regardless
        # of what else co-fires.
        is_answer_turn = warrants["answer"]
        is_execution_turn = not is_answer_turn and (
            warrants["decision"] or warrants["stoppage"] or warrants["completion"]
        )
        # is_zero_warrant_turn = not is_answer_turn and not is_execution_turn

        block_finding = None
        advisory_findings = []

        if is_answer_turn:
            # 2. Answer-turn relevance check (ADVISORY).
            relevance_finding = _answer_relevance_flag(msg_text)
            if relevance_finding:
                advisory_findings.append(relevance_finding)
        elif is_execution_turn:
            # 2. Execution-turn structural shape check (BLOCKING). This
            # REPLACES the deleted _forced_yield_flag.
            block_finding = _execution_prose_flag(msg_text, warrants)
        else:
            # 2. Zero-warrant turn: status-only flag (ADVISORY, unchanged).
            if _status_only_flag(msg_text, warrants):
                advisory_findings.append(
                    "status-only turn - no decision/stoppage/completion/answer warrant present"
                )

        # 3/4. Turn-charge volume check and operator-decisions per-item
        # sprawl check (both DS-151, both ADVISORY, both unaffected by
        # DS-156 other than _volume_flag's Answer-turn re-budget). Skipped
        # when the execution-turn shape check already blocked - a blocked
        # turn gets one directive to reshape, not an additional advisory
        # pile-on. _volume_flag already returns None on a zero-warrant
        # turn; _decision_item_sprawl_flag already returns None when no
        # '## Operator decisions' heading is present.
        if block_finding is None:
            volume_finding = _volume_flag(msg_text, warrants)
            if volume_finding:
                advisory_findings.append(volume_finding)

            decision_sprawl_finding = _decision_item_sprawl_flag(msg_text)
            if decision_sprawl_finding:
                advisory_findings.append(decision_sprawl_finding)

        if block_finding is None and not advisory_findings:
            # Clean turn - reset the shared counter (when engaged) and
            # silent allow, no telemetry.
            if loop_guard_engaged:
                lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
            sys.exit(0)

        # Only emit (block OR advisory) if the loop bound can be persisted.
        # When the counter is engaged, persist count+1 BEFORE emitting; if
        # persistence fails (unwritable .agentic/, full disk, etc.), exit 0
        # silently - a finding whose count cannot be recorded loses its
        # loop bound and can cause an unbounded re-invocation loop when
        # stop_hook_active also fails (CC bug #54360). Both checks share
        # ONE counter/cap (DS-156) - a block and an advisory are both "this
        # hook re-invoked the model" events from the loop guard's
        # perspective.
        if loop_guard_engaged:
            new_count = state["count"] + 1
            if not lg.write_counter(cwd, COUNTER_FILENAME, new_count, current_user_msg_count):
                sys.exit(0)

        if block_finding is not None:
            # BLOCKING (DS-156): the same {"decision": "block", "reason":
            # ...} shape hooks/enforce-no-abdication.py uses. Decision
            # print comes FIRST, unconditionally; telemetry is loaded and
            # called only after the decision has reached stdout, wrapped
            # in its own try/except so a raising log_fire can never
            # suppress or follow this decision.
            reason = "TURN-SHAPE: " + block_finding
            print(json.dumps({"decision": "block", "reason": reason}))
            try:
                _load_log_fire()(data, "enforce-turn-shape", "deny", block_finding)
            except Exception:
                pass
            sys.exit(0)

        reason = "; ".join(advisory_findings)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "Stop",
                        "additionalContext": "TURN-SHAPE: " + reason,
                    }
                }
            )
        )
        try:
            _load_log_fire()(data, "enforce-turn-shape", "allow_advisory", reason)
        except Exception:
            pass
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 and emits nothing
        # (fail-open). An unexpected exception must NEVER manufacture a
        # spurious {"decision": "block", ...} payload from
        # _execution_prose_flag - the process exit code was already 0 on
        # every other path (DS-156, §9), so this is unchanged from before;
        # what "fail-open" protects here is the BLOCKING payload, not the
        # exit code.
        sys.exit(0)


if __name__ == "__main__":
    main()
