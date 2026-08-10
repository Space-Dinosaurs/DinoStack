#!/usr/bin/env python3
"""
Purpose: ADVISORY Claude Code Stop hook (DS-122) that checks the SHAPE of
         the conductor's final assistant message against the turn-shape
         contract in content/sections/02-delegation.md /
         content/rules/conventions.md ("Operator decisions go last in the
         turn" and "Waiting:" forced-yield shape). It NEVER blocks - this
         is the single most important property of this hook, unlike its
         sibling enforce-no-abdication.py, which does block. A finding
         here is surfaced purely as feedback text so the conductor can
         self-correct on its next turn.

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

         2a. Status-only flag: fires when the message has MORE than ~1-2
             lines of prose outside the identity line AND has NONE of the
             four warrants above.

         2b. Forced-yield shape check - STRICTLY SUBORDINATE to (1). Runs
             ONLY when `stoppage` is the SOLE warrant present (a "Waiting:"
             line exists and none of decision/completion/answer is
             present). When that gate passes, the message must be exactly
             the identity line plus one or more "Waiting:" lines and
             nothing else; any extra content flags "forced-yield: extra
             content". When a "Waiting:" line co-occurs with ANY other
             warrant, this check is skipped entirely - no flag, regardless
             of how much other prose accompanies it.

            Known implementation seam (DS-151 amendment A7): 2a and 2b
            still operate on the raw, unsegmented body-line list
            (_body_after_identity_line), NOT on _segment's fence-aware
            structure that checks 3 and 4 below consume. This is a
            deliberate scope boundary, not an oversight: neither check's
            correctness depends on fence-awareness (a fenced "Waiting:"
            line inside a code block is already extremely unlikely prose,
            and status-only's blunt >2-line threshold has no reported
            fence-sensitive failure mode), and bringing them onto _segment
            was out of scope for the DS-151 charge-model rewrite. If a
            fence-related false positive/negative is ever reported against
            either check, migrate it onto _segment then.

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
                             (content/references/conductor-turn-format.md:31)
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
             not a defect: content/references/conductor-turn-format.md:44
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

         A two-layer loop guard bounds how often an advisory can re-invoke
         the model, mirroring the sibling enforce-no-abdication.py. On the
         Claude Code harness, a Stop hook's `additionalContext` re-invokes
         the model immediately (it does not wait for a user turn); when the
         conductor is blocked on a user decision it has nothing substantive
         to say, so it writes a short status turn, the hook flags it, the
         advisory re-invokes the model, and the pair loops until the
         harness's own 9-consecutive-block override fires. Layer 1: the
         `stop_hook_active` payload flag - set by CC when this Stop event
         itself was triggered by a prior Stop-hook action - exits silently
         right after stdin parse. Layer 2: a counter-cap backstop for CC bug
         #54360 (stop_hook_active can fail to propagate when a
         UserPromptSubmit hook interleaves system reminders), state at
         <cwd>/.agentic/.turn-shape-guard-fire-count; the counter increments
         and persists BEFORE each advisory (an advisory whose count cannot
         be persisted is NOT emitted - it would lose its loop bound) and
         resets on a clean turn and on a genuine new user message, so a
         blocked conductor gets at most CONSECUTIVE_BLOCK_CAP advisories
         before this hook goes silent. The counter + user-message-counting
         machinery lives in the shared module hooks/lib/loop_guard.py,
         loaded lazily via _load_loop_guard(); when cwd is absent (synthetic
         payloads only - the CC Stop payload always carries cwd) the counter
         cannot be scoped, so this hook falls through to its legacy
         advisory-only behavior rather than silently swallowing findings.
         This hook NEVER blocks - the guard only suppresses advisories; every
         exit stays 0.

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
            stdin. ALWAYS exits 0. On a clean turn (no findings), emits
            nothing on stdout. On a flagged turn, emits exactly one JSON
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
      oversight to "fix" into matching the sibling: unlike
      enforce-no-abdication.py, this hook NEVER blocks, so there is no
      opt-in-only safety rationale for defaulting it off. A missing or
      unreadable config.json is treated as an empty {} (i.e. the guard
      stays ON), not as a disable signal.
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
    - This hook can NEVER return a blocking decision - there is no code
      path that emits {"decision": "block", ...}. Every exit is exit 0
      with either no stdout or an advisory `additionalContext` object.

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

# Max consecutive advisories since the last new user message before this hook
# goes silent. Keeps the loop guard reachable even when CC bug #54360
# prevents stop_hook_active from propagating. This hook NEVER blocks - the
# cap only bounds how many times the advisory can re-invoke the model.
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

# Terminal-completion signal, ANYWHERE in the domain (identity line + body).
# "[phase: complete]" or an unambiguous terminal-completion phrase.
# Deliberately does NOT match a bare past participle ("done", "shipped",
# "merged") - those are this repo's canonical non-warranted status-ping
# vocabulary ("unit 2 merged", "PR merged, pulling main") and must never be
# laundered into a completion warrant.
#
# DS-156 additions (structured-field sentinels, safe anywhere in the domain
# because the label itself is what makes them unambiguous, not their
# position): `status: DONE` / `status: DONE_WITH_CONCERNS` - this repo's own
# engineer-role return contract's terminal enum values (see
# content/references/conductor-turn-format.md and the Engineer role's
# `quality_gate_results` block); `state: complete` / `state: work complete`
# - the Conductor template's own "State:" field (content/references/
# conductor-turn-format.md's "Conductor\nState: ...\nRunning: ...\nBlocked:
# ..." shape); `run complete` / `review complete` - this repo's fixed
# PR-review-run closing phrase. Corpus-measured (DS-156, see
# _LEADING_COMPLETION_RE's docstring for the full method): 0 false positives
# found across an 80-item hand-labelled sample of newly-recognised
# completions that included these four additions.
_COMPLETION_RE = re.compile(
    r"\[phase:\s*complete\]"
    r"|\ball\s+(?:done|complete)\b"
    r"|\bfully\s+complete\b"
    r"|\btask(?:s)?\s+(?:is|are)\s+complete\b"
    r"|\bwork\s+is\s+complete\b"
    r"|\bnothing\s+(?:left|more)\s+to\s+do\b"
    r"|\bstatus\s*:\s*done(?:_with_concerns)?\b"
    r"|\bstate\s*:\s*(?:work\s+)?complete\b"
    r"|\brun\s+(?:is\s+)?complete\b"
    r"|\breview\s+(?:is\s+)?complete\b"
    r"|\ball\s+state\s+files\s+are\s+(?:written|updated|current)\b",
    re.IGNORECASE,
)

# DS-156: a LEADING completion declaration - the identity line (the very
# start of the domain, matched via \A / .match() so MULTILINE is never
# enabled and no line other than the first can match) opens with a short
# terminal claim. Two shapes:
#   1. Up to 3 leading words, then "is"/"are", then "done"/"complete"/
#      "completed", then up to 2 short trailing modifiers ("and verified",
#      ", deployed") before terminal punctuation. Covers "Done.",
#      "Verification complete.", "Both PRs are done and verified.",
#      "Amend done, all clean.".
#   2. A leading past-participle completion verb (merged/shipped/deployed/
#      pushed/landed) followed within 40 chars by a completion-adjacent
#      word (live/deployed/merged/complete/done/cleaned up). Covers "Merged
#      and fully cleaned up.".
#
# Corpus method (DS-156, ticket: repo-local ad-hoc, not a numbered ticket
# in this session): extracted every FINAL assistant-turn text (grouped by
# transcript `message.id`, excluding any group that itself contains a
# tool_use block, i.e. the same "completed turn" scope the Stop hook acts
# on) from ~/.claude/projects - 3,336 files, 165,442 assistant entries,
# 6,744 candidate final-turn texts. Applied the PRE-FIX
# _classify_warrants/_status_only_flag to find turns already flagged
# status-only: 1,231 of 6,744 (18.3%). Hand-labelled samples (not the full
# 1,231 - see below) as genuine-completion vs genuine-status-only.
#
# Round 1 (7 candidate anywhere-scoped phrases, incl. a "merged and
# (live|deployed)" phrase): 220-item random preview plus a targeted
# 50-item hand-verified sample of newly-matched turns found 3 false
# positives (idx 17, 24, 36 of that sample), ALL traced to the
# "merged/shipped and (live|deployed)" phrase matching a COMPLETED
# SUB-ITEM's description inside a turn whose OVERALL state was still
# in-progress (CI running, another unit still building, a future-tense
# "I'll report when it's merged and live"). All 3 shared one property:
# the matching text was NOT the identity line (line 1) of the turn - it
# was buried in the body, several lines after an identity line that
# itself carried the real (in-progress) state.
#
# Round 2 (this version): moved the past-participle phrase, plus a new
# generalised "done/complete" leading-sentence pattern, to an
# IDENTITY-LINE-ONLY match (`\A`, not `re.MULTILINE`). Re-verified: an
# 80-item hand-labelled sample of turns newly recognised as completion
# under the final regex found 0 false positives (see git history / PR
# description for the sample). A parallel 80-item sample of turns still
# flagged status-only after the fix found the residual gap is real but
# small - confirmed misses include a completion buried under a "## Done"
# sub-heading (not the identity line) and "Status: DONE_WITH_CONCERNS"
# variants not yet covered by that exact spelling at the time of
# sampling. Net effect on the full 1,231-turn flagged set: 198 turns
# (16.1%) newly recognised as completion; 1,033 (83.9%) remain correctly
# flagged status-only. NOT rounded to zero - the residual gap (turns whose
# completion declaration sits below the identity line, or uses wording
# outside the patterns above) is real and disclosed, not chased further
# here per the same "measured, not assumed" discipline that motivated this
# fix in the first place.
_LEADING_COMPLETION_RE = re.compile(
    r"\A\s*\*{0,2}"
    r"(?:"
    r"(?:[A-Za-z][\w'/-]*\s+){0,3}(?:is\s+|are\s+)?(?:done|complete|completed)"
    r"(?:\s*,?\s*(?:and\s+)?[a-z]+){0,2}"
    r"|(?:merged|shipped|deployed|pushed|landed)\b.{0,40}?"
    r"\b(?:live|deployed|merged|complete|completed|done|cleaned up)\b"
    r")\*{0,2}[.!,:]",
    re.IGNORECASE,
)

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
    return {
        "decision": bool(_OPERATOR_DECISIONS_HEADING_RE.search(domain_text)),
        "stoppage": any(_WAITING_LINE_RE.match(ln) for ln in unfenced_lines),
        "completion": bool(_COMPLETION_RE.search(domain_text))
        or bool(_LEADING_COMPLETION_RE.match(domain_text)),
        "answer": bool(_QUOTED_FRAGMENT_RE.search(domain_text)) or answer_bonus,
    }


def _status_only_flag(text: str, warrants: dict) -> bool:
    """Fires when the message exceeds ~1-2 lines of prose outside the
    identity line AND carries none of the four warrants. Raw-line path -
    see the module docstring's "Known implementation seam" note."""
    if any(warrants.values()):
        return False
    body_lines = [ln for ln in _body_after_identity_line(text) if ln.strip()]
    return len(body_lines) > 2


def _forced_yield_flag(text: str, warrants: dict):
    """Return a finding string, or None. Raw-line path - see the module
    docstring's "Known implementation seam" note.

    Runs ONLY when `stoppage` is the SOLE warrant present. When that gate
    passes, every non-blank line after the identity line must itself be a
    "Waiting:" line - any other content flags "forced-yield: extra
    content". When "Waiting:" co-occurs with ANY other warrant, this check
    is skipped entirely (returns None unconditionally).
    """
    if not warrants["stoppage"]:
        return None
    if warrants["decision"] or warrants["completion"] or warrants["answer"]:
        return None

    body_lines = [ln for ln in _body_after_identity_line(text) if ln.strip()]
    for line in body_lines:
        if not _WAITING_LINE_RE.match(line):
            return "forced-yield: extra content beyond identity + Waiting: lines"
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
    same defect would just be noise. Otherwise flags iff
    _turn_charge(text)[0] > BASE_BODY_BUDGET - see the module docstring's
    "Charge model" section for the definition.
    """
    if not any(warrants.get(name) for name in ("decision", "stoppage", "completion", "answer")):
        return None

    charge, breakdown = _turn_charge(text, warrants)
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


def _decision_item_sprawl_flag(text: str):
    """Return a finding string, or None.

    Consumes the shared _segment/_regions/_decision_items helpers instead
    of re-slicing text[m.end():]. Item COUNT under "## Operator decisions"
    stays completely unbounded - content/sections/02-delegation.md forbids
    a numeric cap there. This checks per-ITEM SHAPE instead (folding in
    fenced content per amendment A2): each item must fit within
    ITEM_FREE_LINES (aliased MAX_LINES_PER_DECISION_ITEM) lines, matching
    the mandated "recommended action, one line of why, and the reversal
    offer" shape (content/references/conductor-turn-format.md:34). Stays
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
        # the safe failure direction (this hook never blocks), but the
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
        # never blocks, so it defaults ON - only an explicit `false` disables
        # it. Absent/unreadable/malformed config.json is treated as {} (i.e.
        # stays ON), not as a disable signal.
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

        findings = []

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

        # 2a. Status-only flag.
        if _status_only_flag(msg_text, warrants):
            findings.append(
                "status-only turn - no decision/stoppage/completion/answer warrant present"
            )

        # 2b. Forced-yield shape check (strictly subordinate to 1).
        forced_yield_finding = _forced_yield_flag(msg_text, warrants)
        if forced_yield_finding:
            findings.append(forced_yield_finding)

        # 3. Turn-charge volume check (DS-151). Skipped when no warrant is
        # present - that case is already exclusively owned by the
        # status-only flag. Unlike the deleted exclusion model, a
        # sole-stoppage forced-yield turn is NOT unconditionally skipped
        # here any more: constraint 1 (the Waiting: line count is
        # unbounded) is now satisfied structurally inside _turn_charge
        # itself (well-formed Waiting: lines charge 0 when stoppage is the
        # sole warrant), so a clean forced-yield turn charges 0 regardless
        # of how many Waiting: lines it has, and a dirty one is already
        # caught by _forced_yield_flag above.
        volume_finding = _volume_flag(msg_text, warrants)
        if volume_finding:
            findings.append(volume_finding)

        # 4. Operator-decisions per-item sprawl check (DS-151). Independent
        # of the volume check above - item COUNT stays unbounded, only
        # per-item line count is checked, and a single sprawling item can
        # be under the whole-message charge budget while still violating
        # per-item shape.
        decision_sprawl_finding = _decision_item_sprawl_flag(msg_text)
        if decision_sprawl_finding:
            findings.append(decision_sprawl_finding)

        if not findings:
            # Clean turn - reset the advisory counter (when engaged) and
            # silent allow, no telemetry.
            if loop_guard_engaged:
                lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
            sys.exit(0)

        reason = "; ".join(findings)
        # Only emit the advisory if the loop bound can be persisted. When the
        # counter is engaged, persist count+1 BEFORE emitting; if persistence
        # fails (unwritable .agentic/, full disk, etc.), exit 0 silently - an
        # advisory whose count cannot be recorded loses its loop bound and
        # can cause an unbounded advisory loop when stop_hook_active also
        # fails (CC bug #54360).
        if loop_guard_engaged:
            new_count = state["count"] + 1
            if not lg.write_counter(cwd, COUNTER_FILENAME, new_count, current_user_msg_count):
                sys.exit(0)
        # Decision print comes FIRST, unconditionally. Telemetry is loaded
        # and called only after the decision has reached stdout, wrapped in
        # its own try/except so a raising log_fire can never suppress or
        # follow this advisory - matches the enforce-*.py convention (see
        # hooks/lib/enforcement_log.py manifest "Failure modes").
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
        # Defense-in-depth: any unexpected error exits 0 (fail-open). This
        # hook must NEVER block the stop.
        sys.exit(0)


if __name__ == "__main__":
    main()
