#!/usr/bin/env python3
"""
Purpose: Stop hook that mechanically reduces conductor abdication - ending a
         turn by asking the user permission to proceed with an obvious
         non-destructive next step, OR by announcing a surface-and-proceed
         default ("Proceeding with X unless you say otherwise") and then
         stopping without actually proceeding. Detects both shapes in the
         final assistant message and blocks the stop, injecting a two-exit
         directive for either shape (proceed with the stated default now, OR
         state explicitly that authorization is required and wait) - because
         this gate cannot itself tell a genuine surface-and-proceed item from
         a hard-stop item wearing the same language; see _ABDICATION_REASON
         and _STALL_REASON. Mechanizes the prose in
         content/sections/02-delegation.md
         (Proactive autonomy / default-and-proceed - which requires the
         conductor to act "in the same turn", not merely announce intent),
         exactly as enforce-background-spawn.py mechanized its rule.

         Also detects a PROSE co-equal ballot: an `## Operator decisions`
         section (content/sections/02-delegation.md) presenting 2+ decision
         items where 2+ carry no derived recommendation marker. This closes
         a gap the tool-path hook (enforce-askuserquestion-default.py) cannot
         see - that hook only inspects AskUserQuestion tool_input, and a
         conductor can write the same forbidden ballot as plain prose instead
         of calling the tool. See content/sections/02-delegation.md
         "AskUserQuestion precondition" and "Operator decisions go last in
         the turn" - both state the ban applies identically to prose, and
         the latter now MANDATES the `(Recommended)`/`Recommendation:`
         marker on every item so a spec-compliant author is never punished
         by this check.

         Ballot item detection is structured-marker-only (markdown bullet,
         plain numbered, bold-numbered) with NO leading-whitespace tolerance
         (an indented sub-bullet is not a new top-level item) and NO
         paragraph-mode fallback (an earlier version had one; it was
         unpinned by any test and over-fired on ordinary multi-paragraph
         prose - see _split_decision_items). Fenced code blocks are masked
         out of the FULL message before the heading is even searched for,
         so a fenced example quoting this rule's own syntax cannot trigger
         it. Known, documented, unfixed evasions: a non-literal heading
         wording, items formatted as a markdown table, a negated
         "No recommendation:" phrase suppressing the marker check, and an
         indented / blockquoted / nested-under-a-parent-bullet item (the
         zero-leading-whitespace anchor that fixes the sub-bullet
         miscount also means a genuine top-level item written in one of
         these three shapes is not detected) - see the KNOWN RESIDUAL
         EVASION comments at each pattern's definition.

         COUPLING WITH _is_abdication: `(recommended)` is one of the Tier 2
         negative-gate tokens (see _NEGATIVE_GATE_PATTERNS group (c) below).
         Because the Operator decisions block is always the last thing in
         the turn (content/sections/02-delegation.md), a spec-compliant
         marker on any item lands inside the TAIL_LENGTH-truncated tail
         _is_abdication inspects, so _is_abdication returns False (negative
         gate suppresses it) for essentially every compliant Operator
         decisions turn regardless of the ballot outcome. This is correct
         by design - a spec-compliant decision block is not a permission-
         seeking interrogative - but it means the two checks are no longer
         incidentally independent on this class of turn: _is_prose_ballot
         is the only classifier actually deciding the outcome once a
         marker is present. Documented here because the spec change
         mandating the marker made this coupling universal rather than
         incidental.

         Scoped to the MAIN session Stop event only (not SubagentStop), so
         it governs the conductor, not Workers.

         Two loop-guard layers are required due to CC bug #54360 (stop_hook_active
         can fail to propagate when a UserPromptSubmit hook interleaves system
         reminders - and this repo has such a hook). Layer 1: check stop_hook_active
         flag (primary). Layer 2: counter-based cap (backstop) that counts
         consecutive blocks since the last new user message and halts at CAP.
         All three classifiers below share this same loop-guard machinery.
         The counter + user-message-counting machinery lives in the shared
         module hooks/lib/loop_guard.py (COUNTER_FILENAME = ".abdication-guard-
         fire-count", CONSECUTIVE_BLOCK_CAP = 2); this hook loads it lazily via
         _load_loop_guard() and exits 0 silently if it cannot be loaded - never
         emitting a block without the loop bound that module provides.

         Detection is precision-biased (false-negative-biased): a missed
         abdication leaves the conductor as-is (status quo); a false positive
         is recoverable, not because any gate suppresses it, but because the
         classic path's injected directive (_ABDICATION_REASON) is now a
         two-exit reroute rather than an unconditional "proceed now" - exit
         (B) lets the model decline and wait for operator authorization on
         the very turn a false positive fires, escapable in the next turn
         rather than forced. Three independent classifiers run per
         invocation, and a block fires if ANY returns true:

         1. _is_abdication(): the classic permission-seeking interrogative
            check (tier1 phrase + same-sentence "?"). Suppressed by
            _HARD_NEGATIVE_GATE_PATTERNS (destructive/irreversible/design-fork
            signals - genuine stop conditions this hook must never override)
            OR by _SURFACE_AND_PROCEED_PATTERNS (unconditionally, matching
            legacy behavior - see rationale below).

         2. _is_stalled_surface_and_proceed(): NEW. A stall-commitment marker
            ("proceeding with", "unless you say otherwise" - NOT a bare
            "(recommended)", which routinely labels an already-derived choice
            with no pending action attached; see below) is only evidence of
            compliant behavior if the conductor actually acted. This
            classifier fires ONLY on POSITIVE proof of a stall: the marker is
            present in the tail, the transcript window was read successfully,
            a genuine prior human-turn boundary was actually located (so the
            scan window is provably scoped to the CURRENT turn), every
            assistant entry inside that window had a recognized content shape
            (a list of blocks, a plain string, or absent/None content -
            anything else cannot be proven to lack a tool_use), and zero
            tool_use blocks were found inside that window. Any failure to
            establish ALL of the above (unreadable/unparseable transcript,
            no boundary found, an unrecognized entry shape, or the marker
            simply absent) means the
            stall is UNPROVEN and this classifier returns False - burden of
            proof is on detecting the stall, not on disproving it.

         3. _is_prose_ballot(): detects a PROSE co-equal ballot in an
            `## Operator decisions` block - see the module-level note above
            and the function's own docstring. Deliberately NOT subject to
            _HARD_NEGATIVE_GATE_PATTERNS - see _is_prose_ballot docstring for
            why (irreversibility vocabulary in the ballot must not silence
            this check, which is exactly the escape it was added to close).

         Classifier (1) keeps the full marker set (including a bare
         "(recommended)") as an UNCONDITIONAL suppressor of its OWN
         interrogative check - this does not change classifier (2)'s or (3)'s
         independent result. For example "Proceeding with X (recommended).
         Want me to start?" makes _is_abdication() return False on its own,
         but classifier (2) evaluates the same tail against the transcript:
         "proceeding with" is a stall-commitment marker, and if the transcript
         shows no tool call this turn, classifier (2) still fires and the
         overall turn BLOCKs - the marker suppresses classifier (1) alone, it
         is not a blanket exemption from the OR'd result across all three
         classifiers. A bare "(recommended)" with no accompanying commitment
         phrase never triggers classifier (2), because labelling a derived
         choice is not itself a promise to act that can go unfulfilled.

Public API: Run as a Claude Code Stop hook (matcher: "*"). Reads JSON from
            stdin, writes {"decision":"block","reason":"<directive>"} to stdout
            when blocking, exits 0 always. Writes nothing when allowing. Emits
            EITHER exactly one valid JSON object OR nothing - never partial or
            garbage stdout (guarded per CC issue #55754 which causes infinite
            loops on invalid Stop hook output).

Upstream deps: Python 3 stdlib only (json, os, re, sys) plus three shared
               hooks/lib/ modules, each loaded lazily and each with a
               DIFFERENT criticality:
                 - loop_guard.py (counter + user-message-counting
                   machinery), via _load_loop_guard(). A HARD dependency:
                   failing to load it means no block is emitted at all.
                 - repo_root.py (resolve_agentic_cwd - anchors the
                   config.json read below to the repo root instead of the
                   raw payload cwd), via _load_repo_root() (mirrors the
                   loop-guard loader). A HARD dependency: failing to load
                   it exits before the config read, so the guard does not
                   run at all.
                 - enforcement_log.py (fire-log telemetry), via
                   _load_log_fire(). A SOFT dependency: failing to load it,
                   or a raising log_fire(), leaves the verdict untouched and
                   only loses the telemetry row.
               No external dependencies.

Observability: every VERDICT path this hook reaches AFTER the
               abdication_guard_enabled gate appends one row to
               .agentic/.enforcement-fires.jsonl via lib/enforcement_log.py
               - "deny" on a block, "allow" on each non-blocking outcome
               (cap_reached, no_message_text, counter_write_failed, and the
               clean-turn classified path), each carrying a `detail` object
               recording the gate/classifier state that produced it. This
               hook is the sole EVERY-VERDICT caller of that module; the
               other thirteen log actions only (see that module's manifest
               for why the postures differ). Deny-only logging would have left
               the central question - does a canonical `## Operator
               decisions` block reach a classifier at all? - unanswerable,
               since "the heading never appears" and "the heading appears
               constantly and every block is compliant" are both silence.

               The paths that deliberately do NOT log are exactly those
               reached BEFORE the enablement gate, and the list carries no
               cardinal on purpose - it moves whenever an early-exit is
               added: the kill switch, a malformed/non-dict payload or
               absent cwd (no usable log target), stop_hook_active
               re-entrancy, the loop-guard load failure, and the
               repo-root-resolver load failure. All share one structural
               reason - each is checked BEFORE the config read, so logging
               there would write into every repo on disk regardless of
               whether that repo ever enabled this guard. Moving any of
               those checks after the config read to make it loggable would
               be a behavior change and is deliberately not done.

               One POST-gate exit is also unlogged, and it is the single
               counterexample to the opening sentence's scope: main()'s
               outermost `except Exception: sys.exit(0)` fail-open. It is
               not a verdict path - it is reached only when a verdict could
               not be computed, from anywhere in the body including inside
               the logging call itself, so there is no verdict state to
               record and a log attempt there could re-raise the very
               failure being absorbed. Consequence for a consumer: rows are
               a complete census of this hook's VERDICTS, not of its
               INVOCATIONS - an unexpected internal error leaves no trace in
               the fire log at all.

               Unlike a PreToolUse hook, this runs once per conductor turn,
               so every-verdict logging is bounded by turn count. It only
               ever writes in a repo that has explicitly set
               abdication_guard_enabled: true.

Downstream consumers: Claude Code hook runner (Stop event, matcher "*"). Wired
                      via ~/.claude/settings.json by .claude/install.sh AFTER
                      stop-context.js so the context writer runs first.

Failure modes:
    - Malformed stdin: fail-open (exit 0, emit nothing). Hook bugs must never
      brick the session - fail-open preserves default CC behavior.
    - Missing or malformed config.json: fail-open (exit 0). The guard requires
      abdication_guard_enabled to be explicitly true in .agentic/config.json - it
      is NOT on by default; an absent config.json, a config.json without the key,
      or any read/parse error all mean the guard does not run at all. The shipped
      template (content/templates/.agentic/config.json) and /ds-init-project set
      the key, so AE-scaffolded projects are covered; a project without that file
      has an inert guard.
    - Missing transcript file, an unreadable/unparseable JSONL window (no
      lines at all, only garbage lines, only valid-JSON-but-unrecognized-
      schema entries, or a window with no genuine human-turn boundary at
      all - e.g. a compacted transcript), or a recognized boundary containing
      an assistant entry whose content shape cannot be classified as
      list-or-string: fail-open (exit 0). This is a burden-of-proof design,
      not an incidental side effect - _is_stalled_surface_and_proceed() only
      fires on POSITIVE stall evidence (parsed window + located boundary +
      recognized structure + zero tool_use found); anything short of that
      full chain is treated as "stall unproven", never as "stall proven".
    - Any exception: fail-open via outer try/except (exit 0).
    - stop_hook_active=true: exit 0 immediately (primary re-entrancy guard).
    - Counter >= CAP: exit 0 without block (backstop for CC bug #54360).
    - Counter write fails (unwritable .agentic/, full disk, corrupt tmp, etc.):
      exit 0 and ALLOW the stop on that invocation. Rationale: a block whose
      count cannot be recorded loses its loop bound; the safe degradation is
      "don't block" (status quo, never an infinite loop). Only blocks after the
      incremented count has been successfully persisted.
    - hooks/lib/loop_guard.py cannot be loaded (missing file, syntax error,
      snapshot copy drift): exit 0 and ALLOW the stop on that invocation -
      same rationale as a failed counter write: a block emitted without the
      loop-guard machinery loses its loop bound. The machinery is a hard
      dependency of every block this hook emits, not optional telemetry.
    - Invalid/garbage stdout: guarded via atomic print-then-exit pattern;
      any exception before the print results in no stdout = allow.

Performance: < 5 ms per call on typical transcripts (one file read for config,
             a small counter file read/write, and up to two full-file scans of
             the transcript JSONL - one forward scan to count genuine human
             turns, and one reverse-from-readlines scan, shared by the
             last-assistant-message fallback and the tool-call-since-last-
             turn check). Both transcript scans are skipped when
             transcript_path is absent; the reverse scan is also skipped
             when last_assistant_message is already populated AND either a
             hard negative-gate token is present (neither classifier can fire
             regardless of transcript evidence) or no stall-commitment marker
             is present in it (classifier 2 cannot fire without one) - see
             main().

Regression corpus: hooks/tests/test-corpus-abdication.py is the permanent
             regression corpus for this hook. FOUR change attempts were each
             measured unsafe and dropped - do not re-attempt any of them
             without first passing that corpus:
               1. Widening _PERMISSION_PHRASES: measured 11/17 then 7/8 false
                  blocks on genuine hard-stop questions.
               2. Narrowing the design-fork negative gate to co-occurrence:
                  composes with (1) to strip hard-stop protection.
               3. A flat whole-block "(recommended)" substring test, no
                  per-item split, routed through _ABDICATION_REASON: rejected
                  on Skeptic findings against the plan proposing it - never
                  built, never reached a measurable shape. Hard-gate/surface-
                  and-proceed suppression and code-fence/blockquote exclusion
                  must be present from first authoring, not bolted on after
                  review. A revival needed to add a compliant ALLOW row
                  and a genuine co-equal-ballot BLOCK row to this corpus,
                  and to route through a dedicated reason constant that
                  does not carry an unconditional "proceed now" directive.
                  A per-item, fence-masking design with a dedicated
                  non-"proceed now" reason (_is_prose_ballot /
                  _BALLOT_REASON) shipped in a950bdd4 (PR #519) - per its
                  PR body, 0 Critical findings across three Skeptic
                  rounds, and it passes this corpus. Groups 3/5/7 remain
                  the floor for the OTHER rejected attempts; Group 8 below
                  now carries the compliant ALLOW row and the genuine
                  co-equal-ballot BLOCK row this revival required, closing
                  that gap. Two limitations remain, both deliberate and
                  known: the negative-gate exemption (self-documented at
                  _is_prose_ballot's own docstring) and the absent
                  ">"-blockquote heading handling.
               4. Widening the destructive gate with
                  drop/alter table|column|index|database|schema: measured
                  13/13 false suppressions.
             Any NEW classifier added here should route its injected
             directive through the two-exit pattern (proceed now OR
             explicitly wait for authorization) shared by _STALL_REASON and,
             as of this commit, _ABDICATION_REASON as well - never an
             unconditional "proceed now" directive. A false positive on an
             unconditional directive forces an irreversible action with no
             escape on that turn; the two-exit pattern is what makes a false
             positive recoverable instead.
"""

import json
import os
import re
import sys

# Kill-switch: set this env var to 1 to disable enforcement entirely.
KILL_SWITCH_ENV = "AE_ABDICATION_GUARD_DISABLE"

# Max consecutive blocks since the last new user message before we stop blocking.
# Keeps the loop guard reachable even when CC bug #54360 prevents
# stop_hook_active from propagating.
CONSECUTIVE_BLOCK_CAP = 2

# Tail length (characters) of the assistant message to examine. Only the tail
# matters for permission-seeking interrogatives - they appear at the end.
TAIL_LENGTH = 600

# Counter state file (under .agentic/ which is gitignored).
COUNTER_FILENAME = ".abdication-guard-fire-count"
# State file format: single JSON object {"count": N, "last_user_msg_count": M}

# ---------------------------------------------------------------------------
# Classifier patterns
# ---------------------------------------------------------------------------

# Tier 1 (positive): permission-seeking phrases. Word-boundary anchored to
# avoid partial matches. Case-insensitive.
_PERMISSION_PHRASES = re.compile(
    r"\b(?:"
    r"want me to"
    r"|should i"
    r"|shall i"
    r"|would you like me to"
    r"|do you want me to"
    r"|let me know if you(?:'d| (?:like|want))"
    r"|ready (?:for me )?to proceed"
    r"|should i go ahead"
    r"|want me to go ahead"
    r")\b",
    re.IGNORECASE,
)

# Tier 2 (negative gate): hard-stop or legitimate-question signals.
# Presence of any of these tokens suppresses the classic _is_abdication()
# check even if a permission phrase is present. Two groups, split into two
# separate patterns because they are treated differently by the NEW stall
# classifier (_is_stalled_surface_and_proceed) below:
#   (a)+(b) HARD gate - destructive/irreversible signals and product-judgment
#       / design-fork signals. Blocking here would force the conductor to
#       execute an action it correctly and legitimately paused on. This gate
#       suppresses BOTH classifiers unconditionally - it must never be
#       overridden by tool-call evidence.
#   (c) surface-and-proceed markers ("(recommended)", "proceeding with",
#       "unless you say otherwise"). These suppress the classic
#       _is_abdication() interrogative check unconditionally (legacy
#       behavior preserved - see module docstring), but do NOT by themselves
#       prove the conductor acted: _is_stalled_surface_and_proceed() treats
#       their presence as a POSITIVE stall signal when the transcript shows
#       no tool call since the last human turn.
#
# Fix pass 2 (utility-over-inclusion finding): the (a-cont.) spend-money and
# send-external-message tokens below were originally bare words ("spend",
# "cost", "send", "post", "notify", ...). A hard-gate hit SUPPRESSES the
# stall classifier entirely - so an over-broad gate does not merely produce
# a benign false-negative, it silences the guard on a genuine stall (e.g.
# "Sending the brief to the engineer now. Proceeding with unit 3 unless you
# say otherwise." and "This will cost a few minutes. Proceeding with the
# rebase unless you say otherwise." both hit the bare-word gate and went
# unguarded). These two categories are therefore evaluated by
# _hard_negative_gate_hit() below as a CO-OCCURRENCE requirement (action verb
# AND a monetary/authorization or external-target signal in the same tail),
# not by _HARD_NEGATIVE_GATE_PATTERNS alone. The remaining categories
# (destructive, irreversible, force push, delete, schema migration,
# production deploy, etc.) keep their original bare-word breadth - deliberate
# over-inclusion remains an acceptable tradeoff there because those tokens
# are already fairly action-specific in ordinary conductor vocabulary; see
# the fix-pass return notes for a documented breadth caveat on "permanently".
_HARD_NEGATIVE_GATE_PATTERNS = re.compile(
    r"(?:"
    # --- (a) destructive / irreversible ---
    r"\bdestructive\b"
    r"|\birreversible\b"
    r"|\bforce push\b"
    r"|\bforce-push\b"
    r"|\bdelet(?:e|es|ed|ing)\b"
    r"|\bdrop table\b"
    r"|\bschema migration\b"
    r"|\bproduction deploy\b"
    r"|\bpermanently (?:remove|delete)\b"
    r"|\bpermanently\b"
    r"|\bcan(?:not|\'t|not) be undone\b"
    r"|\bno undo\b"
    r"|\bunrecoverable\b"
    r"|\bdata loss\b"
    r"|\bwipe\b"
    r"|\boverwrite\b"
    # --- (b) cannot-derive / credential / target-selection ---
    r"|\bcannot derive\b"
    r"|\bmissing credential\b"
    r"|\bapi key\b"
    r"|\bwhich environment\b"
    r"|\bwhich workspace\b"
    r"|\bmerge to main\b"
    # --- (b cont.) product-judgment / design-fork signals ---
    r"|\bwhich direction\b"
    r"|\bwhich approach\b"
    r"|\bwhich option\b"
    r"|\bwhich of these\b"
    r"|\bchanges the (?:data model|schema|api|contract)\b"
    r"|\bload-bearing\b"
    r"|\bdesign (?:decision|fork|choice)\b"
    r")",
    re.IGNORECASE,
)

# --- (a cont.) spend-money hard-stop: co-occurrence, not a bare word ---
# A spend/cost ACTION token alone ("cost a few minutes") is ordinary
# conductor vocabulary, not a hard-stop signal - it must co-occur with a
# monetary amount, a credit/budget/invoice/billing token, or explicit
# authorization language before it suppresses the stall classifier.
_SPEND_ACTION_PATTERN = re.compile(
    r"\bspend(?:ing)?\b|\bspent\b|\bcost(?:s)?\b",
    re.IGNORECASE,
)
_SPEND_SIGNAL_PATTERN = re.compile(
    r"\$\s?\d"
    r"|\b\d+(?:\.\d+)?\s*(?:dollars|usd)\b"
    r"|\bcredits?\b"
    r"|\bbudget\b"
    r"|\binvoice\b"
    r"|\bbilling\b"
    r"|\bapprove(?:d|s)?\b"
    r"|\bauthoriz(?:e|ed|es|ation)\b"
    r"|\byour ok\b"
    r"|\bsign[- ]?off\b",
    re.IGNORECASE,
)

# --- (a cont.) external-message hard-stop: co-occurrence, not a bare word ---
# A send/post/email/publish/notify ACTION token alone ("Sending the brief to
# the engineer") is an ordinary internal-spawn narration, not a hard-stop
# signal - it must co-occur with an external-facing target before it
# suppresses the stall classifier.
_EXTERNAL_MSG_ACTION_PATTERN = re.compile(
    r"\bsend(?:ing)?\b|\bpost(?:ing)?\b|\bemail(?:ing)?\b|\bpublish(?:ing)?\b|\bnotify(?:ing)?\b",
    re.IGNORECASE,
)
_EXTERNAL_MSG_TARGET_PATTERN = re.compile(
    r"\bemail\b"
    r"|\bslack\b"
    r"|\bcustomer\b"
    r"|\buser-facing\b"
    r"|\btracker\b"
    r"|\bcomment\b"
    r"|\bwebhook\b"
    r"|\bproduction\b"
    r"|[\w.+-]+@[\w-]+\.[\w.-]+",
    re.IGNORECASE,
)


def _hard_negative_gate_hit(tail: str) -> bool:
    """Return True iff `tail` contains a genuine hard-stop signal.

    Most categories (destructive/irreversible/force-push/delete/schema
    migration/production deploy/cannot-derive/design-fork/etc.) are bare-word
    matches via _HARD_NEGATIVE_GATE_PATTERNS - deliberately broad, see the
    comment above that pattern.

    The spend-money and external-message categories are NARROWER: they
    require an action token (spend/cost, or send/post/email/publish/notify)
    to CO-OCCUR with a monetary/authorization signal or an external-facing
    target, respectively, in the same tail. A bare action word alone
    ("cost a few minutes", "sending the brief to the engineer") does not
    qualify - see _SPEND_ACTION_PATTERN / _EXTERNAL_MSG_ACTION_PATTERN.
    """
    if _HARD_NEGATIVE_GATE_PATTERNS.search(tail):
        return True
    if _SPEND_ACTION_PATTERN.search(tail) and _SPEND_SIGNAL_PATTERN.search(tail):
        return True
    if _EXTERNAL_MSG_ACTION_PATTERN.search(tail) and _EXTERNAL_MSG_TARGET_PATTERN.search(tail):
        return True
    return False


# --- (c) surface-and-proceed markers (see comment block above) ---
_SURFACE_AND_PROCEED_PATTERNS = re.compile(
    r"(?:\(recommended\)|proceeding with|unless you say otherwise)",
    re.IGNORECASE,
)

# Narrower subset of (c) used ONLY by _is_stalled_surface_and_proceed()
# (classifier 2) and by main()'s decision to scan the transcript at all.
# A bare "(recommended)" labels an already-derived choice and appears
# routinely with no pending action attached (e.g. "Option B (recommended)
# because it matches src/foo.ts.") - it is not a commitment to a specific
# next action, so it must not by itself prove a stall. "proceeding with" and
# "unless you say otherwise" ARE commitments to a stated default: their
# presence with zero tool-use evidence this turn is the actual stall shape
# this classifier exists to catch. Classifier (1)'s suppression gate above
# deliberately keeps the broader _SURFACE_AND_PROCEED_PATTERNS (including the
# bare "(recommended)") - that is a different, unrelated use of the phrase.
_STALL_TRIGGER_PATTERNS = re.compile(
    r"(?:proceeding with|unless you say otherwise)",
    re.IGNORECASE,
)

# Combined gate, kept as a FUNCTION (not a pure regex - the spend/
# external-message categories are co-occurrence checks, not single-pattern
# matches - see _hard_negative_gate_hit): hard gate OR surface-and-proceed
# marker either one suppresses the classic _is_abdication() interrogative
# check. This is NOT "unchanged" from main - the classic path's suppression
# surface is WIDER here. A corpus diff of 95 classic-abdication strings
# (old function vs new) found 35 divergences, all old=BLOCK -> new=ALLOW,
# across three added/broadened mechanisms: the `delete` ->
# `delet(?:e|es|ed|ing)` inflection widening in _HARD_NEGATIVE_GATE_PATTERNS
# (e.g. "I deleted the temp files.", "Deleting the stale worktree now. Want
# me to run the tests?"), the new spend co-occurrence gate
# (_SPEND_ACTION_PATTERN + _SPEND_SIGNAL_PATTERN, e.g. "The run will cost
# about $200."), and the new external-message co-occurrence gate
# (_EXTERNAL_MSG_ACTION_PATTERN + _EXTERNAL_MSG_TARGET_PATTERN, e.g.
# "Sending the summary to the tracker."). The direction is deliberate: this
# module is false-negative-biased throughout (a missed abdication is status
# quo; a false positive forces an unwanted continuation - see the module
# docstring), so trading classic-path coverage for fewer false positives on
# genuine hard-stop language is consistent with that bias. Classifier (2)
# still independently evaluates the same tail, so the net two-classifier
# guard is not weakened by this classic-path widening.
def _negative_gate_hit(tail: str) -> bool:
    return _hard_negative_gate_hit(tail) or bool(_SURFACE_AND_PROCEED_PATTERNS.search(tail))


# Sentence boundary: split right after a terminator (./?/!) that is followed
# by whitespace. Deliberately naive (does not special-case abbreviations or
# numbered-list markers like "1.") - false splits only produce extra sentence
# chunks, they never merge a question with unrelated text, so they cannot
# cause a false negative or false positive here.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")

# The harness-injected-marker tuple and _is_harness_injected_text() now live in
# hooks/lib/loop_guard.py (see is_harness_injected_text) - shared with
# enforce-turn-shape.py. The markers are load-bearing for the #54360 backstop;
# do not prune them from loop_guard.py without re-verifying against a fresh
# transcript sample first (see the block comment there).


def _is_abdication(text: str) -> bool:
    """Return True if the tail of text looks like a permission-seeking abdication.

    Precision-biased (false-negative-biased): only fire when BOTH conditions hold
    and NO negative-gate token is present. See the module docstring for the
    false-positive-cost analysis (why a false positive here is recoverable) -
    do not restate that justification here; it drifts independently if repeated.
    """
    tail = text[-TAIL_LENGTH:]

    # Negative gate first (cheaper than full regex scan).
    if _negative_gate_hit(tail):
        return False

    # Require a permission phrase somewhere in the tail (cheap pre-filter
    # before the more expensive sentence segmentation below).
    if not _PERMISSION_PHRASES.search(tail):
        return False

    # Sentence-granularity check: the SAME sentence must both end with "?"
    # AND contain a permission phrase. A permission-seeking question followed
    # by trailing declarative sentences ("Want me to file this? Learnings
    # captured.") must still fire - checking only the final line missed this
    # because trailing text pushed the question mark off the last line.
    # Conversely, a permission phrase appearing in one (non-question)
    # sentence while an unrelated "?" appears in a later sentence must NOT
    # fire.
    for sentence in _SENTENCE_SPLIT_RE.split(tail):
        stripped = sentence.strip()
        if not stripped:
            continue
        if stripped.endswith("?") and _PERMISSION_PHRASES.search(stripped):
            return True

    return False


def _is_stalled_surface_and_proceed(text: str, stall_provable: bool, had_tool_call: bool) -> bool:
    """Return True if the tail announces a surface-and-proceed default AND
    the transcript furnishes POSITIVE proof the conductor took no action on
    it this turn.

    This is the fix for the reported stall bug: a surface-and-proceed marker
    used to be treated as proof of already-compliant behavior regardless of
    whether any action followed it. That is only true when the conductor's
    turn actually made a tool call (spawned an agent, ran a command, edited a
    file) after announcing the default - not merely because the phrase is
    present.

    Burden of proof is inverted from a naive implementation (Finding 2): this
    only fires on POSITIVE stall evidence, never on absence of evidence.
    `stall_provable` (computed by main() from _scan_transcript_tail's result)
    must already encode "the window was read successfully, a genuine human-
    turn boundary was located, and every assistant entry in that window had a
    recognized content shape" - i.e. `had_tool_call` is only meaningful
    (decisive) when `stall_provable` is True. An unreadable/unparseable
    transcript, a window with no located human-turn boundary (e.g. a
    compacted transcript with no user turn at all), or an unrecognized
    assistant content shape all leave `stall_provable` False, and this
    classifier returns False in every one of those cases - an unprovable
    claim must never block.

    Fail-open by construction:
      - A hard negative-gate token (destructive/irreversible/design-fork/
        spend-money/external-message) always suppresses this check - never
        force a stop the conductor correctly paused on for a genuine reason.
      - No stall-commitment marker in the tail (_STALL_TRIGGER_PATTERNS:
        "proceeding with" / "unless you say otherwise" - deliberately NOT a
        bare "(recommended)", see _STALL_TRIGGER_PATTERNS) -> False (nothing
        to evaluate).
      - stall_provable is False -> False. Without a fully-proven scan this
        classifier cannot establish a stall occurred.
      - had_tool_call is True -> False (compliant: the conductor followed
        through in this turn).
    """
    tail = text[-TAIL_LENGTH:]

    if _hard_negative_gate_hit(tail):
        return False

    if not _STALL_TRIGGER_PATTERNS.search(tail):
        return False

    if not stall_provable:
        return False

    return not had_tool_call


# ---------------------------------------------------------------------------
# Prose-ballot detection
# ---------------------------------------------------------------------------

# The literal heading from content/sections/02-delegation.md ("Operator
# decisions go last in the turn"). Case-insensitive, tolerant of surrounding
# whitespace on the heading line and an optional trailing colon, anchored to
# a line start so it cannot match mid-sentence prose that happens to contain
# the words. `#{2,}` (2 OR MORE hashes) rather than a fixed `#{2}` so a
# `### Operator decisions` (3-hash) heading still matches - `#{2}` consumes
# exactly two hashes and leaves the third unmatched against the following
# `\s*`, silently failing to find the heading at all.
#
# KNOWN RESIDUAL EVASION (documented, not fixed - see Skeptic review):
# a heading with different WORDING ("## Decisions for you", "## Open
# items") or items formatted as a markdown table are NOT caught by this
# regex/tokenizer pair. Both would require either free-text heading-intent
# classification or a table parser, neither of which is safe to add as a
# regex without materially raising the false-positive rate on legitimate
# turns. This is a known gap, not an oversight.
#
# The zero-leading-whitespace item-start anchor (below, _ITEM_START_RE)
# also misses three shapes, for the same "known gap, not an oversight"
# reason: an INDENTED top-level bullet (real conductor output never
# indents a genuine top-level item, so this miss is judged acceptable), a
# BLOCKQUOTED bullet ("> - Option A?" - same judgment, real output does
# not quote its own decisions), and a bullet NESTED UNDER A PARENT BULLET
# (a decision item written as a sub-item of some other bullet rather than
# at the block's own top level) - this last one is judged the most
# plausible of the three to occur in real output and is the one most
# worth a human reviewer's attention if this detector is ever revisited.
_OPERATOR_DECISIONS_HEADING_RE = re.compile(
    r"^[ \t]*#{2,}\s*operator decisions\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# A top-level list item start, anchored to the ABSOLUTE start of the line
# (no leading whitespace permitted before the marker). Three accepted
# shapes, matched by real conductor output rather than an idealized single
# format:
#   - markdown bullet: "- ", "* ", "+ "
#   - plain numbered:  "1. " / "1) "
#   - bold-numbered:   "**1." / "**1)" (no space required after "**" or
#     before the digit - this is the shape conductors actually emit, e.g.
#     "**1. Run one command to unblock PR #516.**")
# The no-leading-whitespace anchor is deliberate: an INDENTED bullet/number
# ("   - the DCO check passed") is a sub-bullet of the enclosing item, not a
# new top-level decision, and must not be counted as one. A genuinely
# top-level markdown list in an Operator decisions block is never indented -
# it starts at column 0 immediately under the heading.
_ITEM_START_RE = re.compile(
    r"^(?:"
    r"[-*+]\s+"
    r"|\d+[.)]\s+"
    r"|\*\*\s*\d+[.)]"
    r")",
    re.MULTILINE,
)

# Fenced code blocks (```...```). Masked out BEFORE the heading search even
# runs (see _mask_fenced_code_blocks / its call site in _is_prose_ballot) so
# that (a) a fenced example that happens to quote the literal heading text
# (a PR body, a /ds-wrap note, a Skeptic digest explaining this very rule)
# is never mistaken for a real Operator decisions block, and (b) diff-style
# '+'/'-' prefixed lines inside a fence are never mistaken for markdown
# bullet item starts. Non-greedy + DOTALL so multiple fences in one message
# are each matched individually rather than spanning from the first opening
# fence to the last closing one.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Marks that an item already carries a derived recommendation, per the
# methodology's own convention: the literal "(Recommended)" suffix used on
# the tool path, or a "Recommendation:" lead-in for the prose path.
#
# KNOWN RESIDUAL EVASION (documented, not fixed - see Skeptic review): this
# matches the word "recommendation" followed by a colon regardless of
# negation, so "No recommendation: you decide." is read as carrying a
# marker. A conductor need only write the word to suppress the check. Low
# severity (requires deliberately gaming the guard's own wording, not an
# accidental miss) and left as a documented gap rather than a regex fix
# that would need negation-scope parsing to do properly.
_RECOMMENDATION_RE = re.compile(r"\(recommended\)|recommendation\s*:", re.IGNORECASE)


def _mask_fenced_code_blocks(text: str) -> str:
    """Replace each fenced code block with a single-line placeholder.

    See _FENCE_RE for why: prevents a fenced example that quotes this rule's
    own heading/list syntax from being misread as a real Operator decisions
    block, and prevents diff/list-like syntax inside a fence from being
    misread as a new item marker.
    """
    return _FENCE_RE.sub("<code-block>", text)


def _extract_operator_decisions_block(masked_text: str) -> str:
    """Return the text following the '## Operator decisions' heading.

    Returns '' if the heading is absent. Per content/sections/02-delegation.md
    the block is always the last thing in the turn (nothing follows the
    heading), so everything after the heading match is the block content -
    there is no closing marker to look for.

    CALLER CONTRACT: masked_text must already have fenced code blocks masked
    out (see _mask_fenced_code_blocks). Extracting from unmasked text lets a
    fenced example that quotes the literal heading text falsely match, and
    the resulting "block" would swallow real content past the fence's
    closing backticks (the block is assumed to run to end-of-message).
    """
    match = _OPERATOR_DECISIONS_HEADING_RE.search(masked_text)
    if not match:
        return ""
    return masked_text[match.end():]


def _split_decision_items(masked_block: str) -> list:
    """Split an already-fence-masked Operator decisions block into items.

    Scans for _ITEM_START_RE markers (bullet, numbered, or bold-numbered).
    Each item runs from its marker to the character before the next marker
    (or end of block), so continuation lines belonging to the same item
    (including a "Recommendation:" line that isn't on the marker's own
    line) stay part of that item's text.

    Returns [] when no structured marker is found anywhere in the block.
    There is deliberately NO paragraph-mode fallback: an earlier version
    tried to also split on blank lines when no marker was present, to catch
    arbitrarily-formatted items, but it was unpinned by any test that
    verified it actually caught the format it was meant for, and it
    over-fired on ordinary non-ballot prose (e.g. two blank-line-separated
    paragraphs of "nothing to decide" narrative). Structured markers only -
    an author who writes a real ballot without any list/number syntax is a
    genuine, currently-uncovered gap (see the heading docstring's KNOWN
    RESIDUAL EVASION note), not a case worth risking false positives on
    every ordinary multi-paragraph turn to catch.

    CALLER CONTRACT: masked_block must already have fenced code blocks
    masked out (see _mask_fenced_code_blocks) - this function does not
    mask internally, so a caller passing unmasked text risks diff-style
    '+'/'-' lines inside a fence being misread as item markers.
    """
    starts = [m.start() for m in _ITEM_START_RE.finditer(masked_block)]
    if not starts:
        return []
    items = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(masked_block)
        items.append(masked_block[start:end])
    return items


def _is_prose_ballot(text: str) -> bool:
    """Return True if text contains a co-equal ballot in an Operator
    decisions block.

    Fires only when: (1) the '## Operator decisions' heading is present,
    (2) the block contains 2 or more list items, AND (3) 2 or more of those
    items carry no derived-recommendation marker. A single item never fires
    (the rule bans co-equal *ballots*, not surfacing one genuine decision -
    content/sections/02-delegation.md "Proactive autonomy" anti-pattern
    list). An item that DOES carry a recommendation does not count toward
    the violation, so a block with one flagged decision plus other already-
    recommended items does not fire - this mirrors the tool-path hook
    (enforce-askuserquestion-default.py), which only denies a 2+-option
    AskUserQuestion call when NO option carries the "(Recommended)" label.
    content/sections/02-delegation.md "Operator decisions go last in the
    turn" now mandates the same marker on the prose path, so a compliant
    author is never punished by this check - only an author who omits the
    marker the spec itself requires is.

    Fenced code blocks are masked FIRST, before the heading search runs -
    see _extract_operator_decisions_block's CALLER CONTRACT for why order
    matters here.

    Deliberately scans the FULL message text, not the TAIL_LENGTH-truncated
    tail _is_abdication uses: the Operator decisions block is, by the same
    section's own convention, the last thing in the turn, and real items
    with one-line reasoning routinely exceed the 600-char tail window.

    Deliberately independent of _NEGATIVE_GATE_PATTERNS. That gate exists to
    let a genuine SINGLE irreversible-action confirmation pass the
    permission-phrase classifier without being mistaken for abdication. A
    multi-item ballot saturated with irreversibility vocabulary
    ("destructive", "cannot be undone", "design decision") is exactly the
    failure mode that motivated this check - the incident this hook was
    added to catch used that exact vocabulary to make the negative gate
    silence the permission-phrase check. Routing this check through the same
    gate would repeat the escape it exists to close.
    """
    masked = _mask_fenced_code_blocks(text)
    block = _extract_operator_decisions_block(masked)
    if not block:
        return False
    items = _split_decision_items(block)
    if len(items) < 2:
        return False
    unrecommended = sum(1 for item in items if not _RECOMMENDATION_RE.search(item))
    return unrecommended >= 2


# ---------------------------------------------------------------------------
# Loop-guard loader (counter + user-message counting live in loop_guard.py)
# ---------------------------------------------------------------------------


def _load_loop_guard():
    """Best-effort dynamic import of the shared loop-guard module.

    Returns None when the module cannot be loaded (missing file, syntax
    error, snapshot copy drift) - main() treats None as "do not block": a
    block emitted without the loop-guard machinery loses its loop bound
    (same rationale as a failed counter write). Loaded once at module scope;
    every invocation that reaches the loop-guard section reuses the loaded
    module.
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


def _load_repo_root():
    """Best-effort dynamic import of hooks/lib/repo_root.py (mirrors
    _load_loop_guard above). Returns None on any load failure - callers
    must skip the .agentic/ read/write rather than fall back to a raw cwd.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "repo_root.py")
        spec = _ilu.spec_from_file_location("repo_root", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_REPO_ROOT = _load_repo_root()


# ---------------------------------------------------------------------------
# Fire-log integration (observability only - never affects a verdict)
# ---------------------------------------------------------------------------

HOOK_NAME = "enforce-no-abdication"


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of this hook's verdict. Contrast
    _load_loop_guard() above, which IS a hard dependency: a block emitted
    without the loop-guard machinery loses its loop bound, whereas a fire
    that goes unlogged merely goes unmeasured.

    Called lazily from inside _fire_log() (never at module scope), mirroring
    enforce-turn-shape.py's own _load_log_fire() - every invocation that
    exits before a verdict is reached (kill switch, malformed stdin,
    stop_hook_active, guard-not-enabled) never reads, compiles, or execs
    this file at all.
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


def _fire_log(data, decision, reason, detail=None):
    """Append one fire-log row. Swallows EVERYTHING - never raises, never
    prints, never influences the caller's verdict.

    Two layers of suppression, deliberately redundant: log_fire() is itself
    fail-open by contract, and this wrapper re-catches anyway. The second
    layer is what covers a HALF-APPLIED hooks snapshot (DS-54), where an
    older 4-parameter lib/enforcement_log.py meets this newer caller passing
    `detail=` and raises TypeError before any of log_fire()'s own internal
    try/except is entered. See hooks/tests/_fire_log_test_helper.py, which
    exercises exactly that shape with an unconditionally-raising stub.

    Every call site must place this AFTER the verdict has been printed (on
    the block path) and immediately BEFORE sys.exit(0), so no ordering
    change can let telemetry precede or suppress a decision.
    """
    try:
        _load_log_fire()(data, HOOK_NAME, decision, reason, detail=detail)
    except Exception:
        pass


def _gate_token(tail):
    """Return a short, fixed-vocabulary label for the negative-gate token
    that suppressed the classic interrogative check, or None if none did.

    Evaluation order mirrors _negative_gate_hit()/_hard_negative_gate_hit()
    exactly, so the reported token is the one that ACTUALLY suppressed,
    not merely one that was also present.

    PII BOUNDARY - the reason this returns a category label rather than the
    matched text for two of the four branches. _HARD_NEGATIVE_GATE_PATTERNS
    and _SURFACE_AND_PROCEED_PATTERNS are closed vocabularies of literal
    words and phrases, so echoing their match is safe. The two co-occurrence
    gates are NOT: _SPEND_SIGNAL_PATTERN matches `\\$\\s?\\d` (a real dollar
    amount) and _EXTERNAL_MSG_TARGET_PATTERN matches a bare email-address
    regex, so echoing either match would write operator/customer PII into a
    telemetry file that has no redaction layer. Those two report a fixed
    category name and never the matched text. Do not "improve" this by
    reporting the match uniformly.

    Read-only and pure: this function is called only from inside the
    logging path and can never change a verdict.
    """
    m = _HARD_NEGATIVE_GATE_PATTERNS.search(tail)
    if m:
        return m.group(0).strip().lower()
    if _SPEND_ACTION_PATTERN.search(tail) and _SPEND_SIGNAL_PATTERN.search(tail):
        return "<spend co-occurrence>"
    if _EXTERNAL_MSG_ACTION_PATTERN.search(tail) and _EXTERNAL_MSG_TARGET_PATTERN.search(tail):
        return "<external-message co-occurrence>"
    m = _SURFACE_AND_PROCEED_PATTERNS.search(tail)
    if m:
        return m.group(0).strip().lower()
    return None


def _ballot_shape(text):
    """Return (heading_present, item_count, unrecommended_count) for the
    Operator decisions block, recomputed purely for telemetry.

    This is the datum that makes the central question answerable at all:
    "does the canonical decisions-block shape ever reach classifier 3?" A
    deny-only log cannot distinguish 'the heading never appears' from 'the
    heading appears constantly and every block is compliant' - both look
    like silence. Recording heading/item/unrecommended counts on ALLOW rows
    separates them.

    Mirrors _is_prose_ballot()'s own sequence (mask fences, extract block,
    split items, count unmarked) rather than refactoring that function, so
    the classifier's decision path is untouched by this change. The
    duplication is deliberate and is the price of the zero-behavior-change
    constraint; if _is_prose_ballot's sequence changes, change this too.
    """
    masked = _mask_fenced_code_blocks(text)
    block = _extract_operator_decisions_block(masked)
    if not block:
        return False, 0, 0
    items = _split_decision_items(block)
    unrecommended = sum(1 for item in items if not _RECOMMENDATION_RE.search(item))
    return True, len(items), unrecommended


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def _scan_transcript_tail(transcript_path: str) -> dict:
    """Single reverse (tail-first) scan of the transcript JSONL, shared by
    both the last-assistant-message fallback and the tool-call-since-last-
    turn check (avoids two separate reverse-scan implementations - see
    module docstring point 2).

    Reads lines in reverse from the end of the file back to (and including)
    the most recent GENUINE human turn line, then stops - everything at or
    before that boundary is a prior turn and irrelevant to either check.

    Returns:
        {"last_assistant_text": str, "had_tool_call": bool,
         "boundary_found": bool, "shape_unrecognized": bool}

    - last_assistant_text: the most recent assistant message's concatenated
      text content (matches the old _last_assistant_text_from_transcript
      behavior exactly - same two transcript shapes, same join semantics).
    - had_tool_call: True iff any assistant message within the scanned
      window (i.e. since the last genuine human turn) contains a
      type=="tool_use" content block in a RECOGNIZED shape - evidence the
      conductor actually acted this turn, not merely announced intent.
    - boundary_found: True iff the reverse scan actually located a genuine
      human-turn line and stopped there (see loop_guard.is_genuine_user_turn).
      False means the window is NOT provably scoped to "since the current
      human turn" - e.g. the file has no human turn at all (a compacted
      window), is empty, or every line failed to parse.
    - shape_unrecognized: True iff at least one assistant entry INSIDE the
      scanned window had a content shape that is neither a list of blocks, a
      plain string, nor absent/None (e.g. a bare dict) - such a shape cannot
      be proven to lack a tool_use block, so had_tool_call's absence-of-
      evidence must not be read as evidence-of-absence. Absent content
      (content is None) IS a recognized shape - an entry with no content at
      all has nothing to hide a tool_use in, so it does not trigger
      shape_unrecognized (see the `elif content is None` branch below).

    Burden-of-proof inversion (Finding 2): had_tool_call, boundary_found, and
    the negation of shape_unrecognized ALL default to their "unproven" value
    (False, False, False respectively is the *safe* starting state before any
    positive evidence is found) and only flip to the "proven" direction on
    positive evidence encountered during a successful scan. Callers combine
    these into a single `stall_provable` flag (see main()) that requires
    boundary_found AND NOT shape_unrecognized before treating had_tool_call
    as decisive - a stall is asserted only on complete positive proof, never
    inferred from an unparseable or partially-recognized window.

    Fail-open: on any read error (open() failure, or an exception mid-scan),
    returns had_tool_call=False, boundary_found=False, shape_unrecognized=True
    and last_assistant_text="" - i.e. maximally "unproven", so the classifier
    that consumes this result can never treat a read failure as proof of a
    stall.
    """
    result = {
        "last_assistant_text": "",
        "had_tool_call": False,
        "boundary_found": False,
        "shape_unrecognized": False,
    }
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        result["shape_unrecognized"] = True
        return result

    had_tool_call = False
    boundary_found = False
    shape_unrecognized = False
    text_captured = False

    try:
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            # Handle two common transcript shapes:
            # Shape 1: {"role": "assistant"/"user", "content": [...]}
            # Shape 2: {"type": "assistant"/"user", "message": {"content": [...]}}
            role = obj.get("role") or obj.get("type", "")

            if role == "user" and _LOOP_GUARD.is_genuine_user_turn(obj):
                # Reached the boundary of the current turn - stop scanning.
                boundary_found = True
                break

            if role != "assistant":
                continue

            content = obj.get("content")
            if content is None:
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content")

            if isinstance(content, str):
                if not text_captured:
                    result["last_assistant_text"] = content
                    text_captured = True
            elif isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                    had_tool_call = True
                if not text_captured:
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    result["last_assistant_text"] = " ".join(parts)
                    text_captured = True
            elif content is None:
                # No content at all - a recognized (empty) shape; nothing to
                # prove or disprove from this entry.
                pass
            else:
                # Unrecognized content shape (e.g. a bare dict, not a list of
                # blocks) - cannot be proven to lack a tool_use, so the
                # absence of a detected tool_use here is not decisive.
                shape_unrecognized = True
    except Exception:
        # Partial-scan failure: the state captured so far is unreliable -
        # treat as fully unproven (fail-open).
        return {
            "last_assistant_text": "",
            "had_tool_call": False,
            "boundary_found": False,
            "shape_unrecognized": True,
        }

    result["had_tool_call"] = had_tool_call
    result["boundary_found"] = boundary_found
    result["shape_unrecognized"] = shape_unrecognized
    return result


# ---------------------------------------------------------------------------
# Block reasons
# ---------------------------------------------------------------------------

_ABDICATION_REASON = (
    "ABDICATION GUARD: You ended your turn by asking the user permission "
    "to proceed with a next step. This block cannot itself tell whether "
    "that was a genuinely derivable default wearing permission-seeking "
    "language, or a genuine hard-stop - you must classify it honestly. Two "
    "compliant exits: (A) If this is non-destructive and a default is "
    "derivable (METHODOLOGY §Delegation, Proactive autonomy - consult the "
    "six default sources: codebase patterns, MEMORY.md, architect plan, "
    "AGENTS.md, the product-intent layer when docs/overview/vision.md or "
    "requirements.md exist, conservative ticket interpretation), proceed "
    "with the next "
    "logical step NOW, in this same turn - do not ask 'want me to', "
    "'should I', 'shall I', or similar permission-seeking phrases. (B) If "
    "this genuinely requires authorization you do not have - (1) a "
    "genuinely irreversible/destructive action not pre-authorized, (2) "
    "information you cannot derive (credentials, product judgments), or "
    "(3) ambiguous acceptance criteria with no inferable default - do NOT "
    "proceed. Say so explicitly, state that you are waiting for operator "
    "authorization, and end the turn; that is an equally compliant "
    "response to this block, not a loophole. Choosing exit (B) for an item "
    "that is genuinely exit (A) is itself the abdication this guard "
    "exists to catch."
)

_STALL_REASON = (
    "ABDICATION GUARD: You announced a surface-and-proceed default "
    "(\"proceeding with\" / \"unless you say otherwise\") "
    "and then stopped without taking any action this turn. This block cannot "
    "tell whether that was a genuine surface-and-proceed item or a hard-stop "
    "item wearing surface-and-proceed language - you must classify it "
    "honestly. Two compliant exits: (A) If this is genuinely non-destructive "
    "and a default was derivable (METHODOLOGY §Delegation, surface-and-proceed "
    "branch), proceed with the stated default NOW, in this same turn - spawn "
    "the agent, run the command, or make the edit you said you would. (B) If "
    "this actually requires authorization you do not have - it is "
    "irreversible, spends real money, or sends an external message - do NOT "
    "proceed. Say so explicitly, state that you are waiting for operator "
    "authorization, and end the turn; that is an equally compliant response "
    "to this block, not a loophole. Choosing exit (B) for an item that is "
    "genuinely exit (A) is itself the abdication this guard exists to catch."
)

_BALLOT_REASON = (
    "ABDICATION GUARD: Your 'Operator decisions' block presents a "
    "co-equal ballot - 2 or more decision items with no derived "
    "recommendation. The METHODOLOGY §Delegation AskUserQuestion "
    "precondition bans co-equal ballots identically whether presented "
    "via the tool or as prose (content/sections/02-delegation.md, "
    "'Operator decisions go last in the turn'). Consult the six "
    "default sources (codebase patterns, MEMORY.md, architect plan, "
    "AGENTS.md, the product-intent layer when docs/overview/vision.md or "
    "requirements.md exist, conservative ticket interpretation) for each "
    "item: "
    "either pick the best option and proceed, noting the choice, or "
    "surface exactly ONE recommended action per item, marked with a "
    "'Recommendation:' lead-in or a '(Recommended)' suffix. Revise the "
    "Operator decisions block now."
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        # Kill-switch: operator escape hatch.
        if os.environ.get(KILL_SWITCH_ENV) == "1":
            sys.exit(0)

        # Parse stdin JSON payload. Fail-open on any parse error.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        # Primary re-entrancy guard: stop_hook_active is set by CC when this
        # Stop event itself was triggered by a prior Stop-hook block.
        if data.get("stop_hook_active") is True:
            sys.exit(0)

        cwd = data.get("cwd", "")
        if not cwd:
            sys.exit(0)

        lg = _LOOP_GUARD
        if lg is None:
            # Loop-guard machinery unavailable (missing/corrupt
            # hooks/lib/loop_guard.py) - cannot bound a block. Fail open
            # toward allow-stop (never emit a block without a loop bound).
            sys.exit(0)

        if _REPO_ROOT is None:
            # Repo-root resolver unavailable (missing/corrupt
            # hooks/lib/repo_root.py) - never read config.json from an
            # unanchored (possibly drifted) cwd.
            sys.exit(0)

        # Runs only when abdication_guard_enabled is exactly `true`. Absent
        # config, a missing key, or any parse error means it does not run.
        config_path = os.path.join(_REPO_ROOT.resolve_agentic_cwd(cwd), ".agentic", "config.json")
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            if config.get("abdication_guard_enabled") is not True:
                sys.exit(0)
        except Exception:
            sys.exit(0)

        # Counter backstop (CC bug #54360 defence): read the current count and
        # the user-message count at the last block. If a new user message has
        # arrived since the last block, reset the counter (genuine new turn).
        transcript_path = data.get("transcript_path", "")
        if not isinstance(transcript_path, str):
            # A non-string value (e.g. a number) would reach open() below,
            # which Python treats as a raw file descriptor - guard it here,
            # mirroring the existing last_assistant_message type check.
            transcript_path = ""
        current_user_msg_count = 0
        if transcript_path:
            current_user_msg_count = lg.count_user_messages(transcript_path)

        state = lg.read_counter(cwd, COUNTER_FILENAME)
        # If the user has sent a new message since the last block, reset.
        if current_user_msg_count > state["last_user_msg_count"]:
            lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
            state = {"count": 0, "last_user_msg_count": current_user_msg_count}

        if state["count"] >= CONSECUTIVE_BLOCK_CAP:
            # CAP reached - do not block further. Prevents infinite loop when
            # stop_hook_active fails to propagate (CC bug #54360).
            _fire_log(
                data,
                "allow",
                "consecutive-block cap reached; not blocking this turn",
                {"path": "cap_reached", "count": state["count"], "cap": CONSECUTIVE_BLOCK_CAP},
            )
            sys.exit(0)

        # Resolve the last assistant message text. Prefer pre-extracted field;
        # fall back to transcript scan. A transcript scan is also needed
        # (even when last_assistant_message is already populated) whenever
        # the message contains a stall-commitment marker AND no hard
        # negative-gate token is present, to determine whether a tool call
        # followed it this turn - see _is_stalled_surface_and_proceed(). When
        # msg_text is empty we cannot evaluate the hard gate yet, so the scan
        # runs unconditionally to recover text (Finding 7: this is the only
        # case where we scan without already knowing a marker/gate verdict).
        msg_text = data.get("last_assistant_message", "")
        if not isinstance(msg_text, str):
            msg_text = ""

        if not msg_text.strip():
            needs_transcript_scan = True
        else:
            tail_for_gate = msg_text[-TAIL_LENGTH:]
            if _hard_negative_gate_hit(tail_for_gate):
                # This scan exists only to feed classifier (2)
                # (_is_stalled_surface_and_proceed), which cannot fire once a
                # hard gate token is present - skip it. Classifier (3)
                # (_is_prose_ballot) is deliberately exempt from the hard
                # gate and CAN still fire here, but it operates purely on
                # msg_text and never consults this scan's output, so
                # skipping it does not affect classifier (3)'s result.
                needs_transcript_scan = False
            else:
                needs_transcript_scan = bool(_STALL_TRIGGER_PATTERNS.search(tail_for_gate))

        scan = None
        if transcript_path and needs_transcript_scan:
            scan = _scan_transcript_tail(transcript_path)

        if not msg_text.strip() and scan is not None:
            msg_text = scan["last_assistant_text"]

        if not msg_text.strip():
            # No message text available - cannot classify.
            _fire_log(
                data,
                "allow",
                "no assistant message text available; cannot classify",
                {"path": "no_message_text", "scanned": scan is not None},
            )
            sys.exit(0)

        # stall_provable requires ALL of: a scan was run, the file was read
        # successfully, a genuine human-turn boundary was actually located
        # (so the window is provably scoped to the current turn), and no
        # assistant entry in that window had an unrecognized content shape.
        # Absent any of these, had_tool_call cannot be treated as decisive -
        # see _scan_transcript_tail's docstring (Finding 2: burden of proof
        # is on proving the stall, not on disproving it).
        if scan is not None:
            had_tool_call = scan["had_tool_call"]
            stall_provable = scan["boundary_found"] and not scan["shape_unrecognized"]
        else:
            had_tool_call = False
            stall_provable = False

        # Run all three classifiers; a block fires if ANY returns True.
        # Prose-ballot scans the full message; abdication and the stall check
        # scan only the tail (see _is_abdication / _is_stalled_surface_and_proceed
        # / _is_prose_ballot).
        is_stall = _is_stalled_surface_and_proceed(msg_text, stall_provable, had_tool_call)
        is_classic_abdication = _is_abdication(msg_text)
        is_ballot = _is_prose_ballot(msg_text)

        # Telemetry only. Computed from msg_text and the already-completed
        # scan result via pure, read-only helpers, AFTER all three
        # classifiers have already returned - nothing below can reach back
        # and alter a verdict. Wrapped so that a defect in the telemetry
        # computation itself degrades to "no detail" rather than to a
        # changed decision (the outer try/except would otherwise convert
        # such a defect into a silent allow).
        try:
            _tail = msg_text[-TAIL_LENGTH:]
            _heading, _items, _unrecommended = _ballot_shape(msg_text)
            verdict_detail = {
                "path": "classified",
                "hard_gate": _hard_negative_gate_hit(_tail),
                "soft_gate": bool(_SURFACE_AND_PROCEED_PATTERNS.search(_tail)),
                "gate_token": _gate_token(_tail),
                "permission_phrase": bool(_PERMISSION_PHRASES.search(_tail)),
                "stall_marker": bool(_STALL_TRIGGER_PATTERNS.search(_tail)),
                "scanned": scan is not None,
                "stall_provable": stall_provable,
                "had_tool_call": had_tool_call,
                "decisions_heading": _heading,
                "decision_items": _items,
                "unrecommended_items": _unrecommended,
                "c1_abdication": is_classic_abdication,
                "c2_stall": is_stall,
                "c3_ballot": is_ballot,
            }
        except Exception:
            verdict_detail = {"path": "classified", "detail_error": True}

        if not is_stall and not is_classic_abdication and not is_ballot:
            # No classifier fired - reset counter (clean turn) and allow.
            lg.reset_counter(cwd, COUNTER_FILENAME, current_user_msg_count)
            _fire_log(data, "allow", "no classifier fired; clean turn", verdict_detail)
            sys.exit(0)

        # Abdication, stall, or ballot detected. Only block if we can persist
        # the incremented count. If persistence fails (unwritable .agentic/,
        # full disk, etc.) the loop bound is lost; the safe degradation is
        # allow-stop to avoid an infinite block loop when stop_hook_active
        # also fails (CC bug #54360). All three classifiers share this same
        # counter/cap.
        new_count = state["count"] + 1
        if not lg.write_counter(cwd, COUNTER_FILENAME, new_count, current_user_msg_count):
            _fire_log(
                data,
                "allow",
                "classifier fired but the loop-guard counter write failed; allowing the stop",
                dict(verdict_detail, path="counter_write_failed"),
            )
            sys.exit(0)

        if is_ballot:
            reason = _BALLOT_REASON
            fired = "ballot"
        elif is_stall:
            reason = _STALL_REASON
            fired = "stall"
        else:
            reason = _ABDICATION_REASON
            fired = "abdication"
        # Decision print comes FIRST, unconditionally, matching the deny-path
        # convention in every other enforce-*.py hook carrying this same
        # note (see
        # hooks/lib/enforcement_log.py manifest "Failure modes"). Telemetry
        # is loaded and called only after the decision has reached stdout,
        # wrapped in its own try/except so a raising log_fire can never
        # suppress or follow the block.
        print(json.dumps({"decision": "block", "reason": reason}))
        _fire_log(
            data,
            "deny",
            "blocked the stop: " + fired + " classifier fired",
            dict(verdict_detail, fired=fired),
        )
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
