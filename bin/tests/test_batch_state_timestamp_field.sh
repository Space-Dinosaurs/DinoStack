#!/usr/bin/env bash
# Purpose: Prose-invariant regression guard for DS-96 (batch-state.json's
#          staleness gates keyed on a field nothing writes, and failed OPEN)
#          AND its Tier-3-Skeptic-flagged follow-on Critical: turning on
#          Contract A step 2's abort gate for batch-state.json (by fixing the
#          field name) had a first-order consequence nobody traced forward -
#          it also aborted the FIRST write of every approved resume of an
#          interrupted or paused batch, because batch-state's
#          touchTimestampOnTerminal:true (hooks/lib/state-mark.js) refreshes
#          `updated_at` on the terminal mark while leaving the dead session's
#          `session_id` on disk, and step 2 had no `status` precondition. The
#          canonical timestamp field for `.agentic/batch-state.json` is
#          `updated_at` (matching the schema block and the merged writer
#          `hooks/lib/state-mark.js`'s `tsField: 'updated_at'`); the
#          `.agentic/loop-state.json` file's equivalent field is `last_updated`
#          and must NOT be touched. This suite pins that every batch-state
#          staleness reader in content/commands/ds-implement-ticket.md keys on
#          `updated_at`, that dual-file sentences (Contract A step 2) state
#          the per-file mapping explicitly rather than naming one field for
#          both files, that Contract A step 2's `status=active` precondition
#          (which fixes the resume-abort Critical) is scoped to
#          `batch-state.json` ONLY - loop-state.json's unconditional abort
#          stays intact because its Phase 7 stall path can leave a live
#          session holding a non-active file - that Contract
#          C's refusal message offers a file-removal remedy, that the
#          updated_at refresh-cadence claim is qualified to the Claude Code
#          Stop hook, that batch-state's updated_at is documented as
#          canonical (not a fallback) on the loop-state side, that the schema
#          still declares `updated_at`, that absent-timestamp tolerance is
#          documented, and that the stale "out of scope here" placeholder
#          note is gone. Pure text assertions - there is no executable block
#          to extract here (the gates are prose contracts the conductor
#          applies, not code), the same rationale as
#          test_ticket_rework_triage_badge.sh's sibling spec.
#
# Public API: ./bin/tests/test_batch_state_timestamp_field.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, grep, awk. Reads content/commands/ds-implement-ticket.md
#                and content/references/cross-session-loop-resume.md from the
#                checkout. No jq, no python3, no network - pure text
#                assertions.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: none beyond a failing assertion - this test makes no writes
#                and no network calls.
#
# Performance: < 1 s wall time (pure grep, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="$REPO_DIR/content/commands/ds-implement-ticket.md"
SPEC2="$REPO_DIR/content/references/cross-session-loop-resume.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

if [[ ! -f "$SPEC" ]]; then
  echo "FAIL: $SPEC not found" >&2
  exit 1
fi
if [[ ! -f "$SPEC2" ]]; then
  echo "FAIL: $SPEC2 not found" >&2
  exit 1
fi

_present() { # _present <file> <label> <pattern>
  if grep -qiE "$3" "$1"; then
    _pass "$2"
  else
    _fail "$2 - spec no longer contains: /$3/"
  fi
}
_absent() { # _absent <file> <label> <pattern>
  if grep -qiE "$3" "$1"; then
    _fail "$2 - spec still contains: /$3/"
  else
    _pass "$2"
  fi
}

echo ""
echo "--- Contract C refusal text keys on updated_at, not last_updated ---"
_present "$SPEC" "Contract C refusal message keys on updated_at" \
         'Another batch session is active for this project root \(session_id=<X>, updated_at=<Y>\)'
_absent "$SPEC" "Contract C refusal message no longer keys on last_updated" \
         'Another batch session is active for this project root \(session_id=<X>, last_updated=<Y>\)'
_present "$SPEC" "Contract C condition text checks updated_at within 10 minutes" \
         'different .session_id., and .updated_at. within the last 10 minutes: REFUSE'

echo ""
echo "--- Contract A step 2 states the per-file mapping (dual-file sentence) ---"
_present "$SPEC" "Contract A step 2 names both field names in the same clause" \
         'liveness-timestamp field \(.last_updated. for .loop-state\.json., .updated_at. for .batch-state\.json.'
_absent "$SPEC" "Contract A step 2 no longer keys the shared abort condition on last_updated alone" \
         'does not match the current session, AND its .last_updated. is within the last 10 minutes'

echo ""
echo "--- Contract A step 2's status=active precondition is scoped to batch-state.json ONLY ---"
# Without this precondition, the first Contract A write of an approved resume of an
# interrupted or paused batch aborts against the dead session's own (terminal-mark
# refreshed) timestamp - there is no live session left to kill. See the batch-state
# module's touchTimestampOnTerminal:true in hooks/lib/state-mark.js. Scoped to
# batch-state.json ONLY: loop-state.json's stall path (Phase 7 -> mark-blocked-and-
# continue) can leave a live session holding a non-active loop-state.json, so adding
# the precondition there would let a foreign session clobber a live file.
_present "$SPEC" "Contract A step 2 scopes the precondition to batch-state.json only" \
         'EXCEPT that on .batch-state\.json. ONLY, this condition additionally requires .status. to be .active.'
_absent "$SPEC" "Contract A step 2 no longer claims the precondition applies to BOTH files" \
        'precondition applies to BOTH files'
_present "$SPEC" "Contract A step 2 states batch-state's rationale (touchTimestampOnTerminal true)" \
         'touchTimestampOnTerminal: true.*hooks/lib/state-mark\.js'
_present "$SPEC" "Contract A step 2 cites the pause path's clean exit" \
         'Exit cleanly\. Do NOT advance to the next ticket'
_present "$SPEC" "Contract A step 2 states loop-state does NOT carry the precondition" \
         'loop-state\.json. does NOT carry the precondition'
_present "$SPEC" "Contract A step 2 cites loop-state's touchTimestampOnTerminal:false shield" \
         'touchTimestampOnTerminal: false'
_present "$SPEC" "Contract A step 2 cites the stall path leaving a live session holding a non-active loop-state" \
         'mark-blocked-and-continue'

echo ""
echo "--- Contract C's REFUSE message offers a file-removal remedy (Minor 1) ---"
_present "$SPEC" "Contract C message offers removing batch-state.json as a remedy" \
         'kill it and re-invoke, or remove \.agentic/batch-state\.json and re-invoke'
_absent "$SPEC" "Contract C message no longer lacks a file-removal remedy" \
        'Wait for it to finish, or kill it and re-invoke\.'

echo ""
echo "--- updated_at refresh cadence is qualified to the Claude Code Stop hook (Minor 2) ---"
_present "$SPEC" "batch-state updated_at bullet names the Claude Code Stop hook, not a bare per-turn claim" \
         'refreshed per-turn by the Claude Code Stop hook'
_present "$SPEC" "batch-state updated_at bullet documents the off-Claude-Code coarser-cadence, fail-open direction" \
         'fail-open'

echo ""
echo "--- loop-state Field notes call batch-state's updated_at canonical, not a fallback (Minor 3) ---"
_present "$SPEC" "loop-state Field notes call updated_at canonical on batch-state.json" \
         '.updated_at. is the CANONICAL field on .batch-state\.json.'
_absent "$SPEC" "loop-state Field notes no longer call updated_at an accepted reader fallback" \
        'accepted reader fallback'

echo ""
echo "--- N=1 foreign-batch warning keys on updated_at ---"
_present "$SPEC" "N=1 foreign-batch warning condition checks updated_at" \
         'different .session_id. \+ .updated_at. within the last 10 minutes'
_present "$SPEC" "N=1 foreign-batch NOTE message keys on updated_at" \
         'a batch session is active for this project root \(session_id=<X>, updated_at=<Y>\)'

echo ""
echo "--- Phase 0a-pre decision table keys on updated_at for batch-state rows ---"
_present "$SPEC" "decision table active-row keys on updated_at (>10 min)" \
         'status=active. AND .updated_at > 10 min. ago'
_present "$SPEC" "decision table active-row keys on updated_at (<=10 min, same session)" \
         'status=active. AND .updated_at ≤ 10 min. AND .session_id. matches current'
_absent "$SPEC" "decision table no longer has a bare last_updated row for batch-state" \
        'status=active. AND .last_updated'

echo ""
echo "--- Phase 0a-open-goal resume classification keys on updated_at ---"
_present "$SPEC" "open-goal resume classification checks updated_at older than 10 min" \
         'differs, AND .updated_at. older than 10 min'
_present "$SPEC" "open-goal resume classification checks updated_at within 10 min" \
         'differs, AND .updated_at. within last 10 min'

echo ""
echo "--- Phase 0a init Contract C application keys on updated_at ---"
_present "$SPEC" "Phase 0a init's Contract C check reads updated_at" \
         'different .session_id., and .updated_at. within the last 10 minutes, REFUSE'

echo ""
echo "--- The batch-state.json schema block still declares updated_at ---"
_present "$SPEC" 'schema JSON block declares "updated_at": "<ISO8601>"' \
         '"updated_at": "<ISO8601>"'

echo ""
echo "--- Absent-timestamp-is-stale tolerance is documented ---"
_present "$SPEC" "batch-state Field semantics documents absent updated_at as stale" \
         'ABSENT .updated_at. as \*\*stale\*\*'
_present "$SPEC2" "cross-session-loop-resume.md documents absent liveness timestamp as stale" \
         'absent liveness-timestamp field is treated as stale'

echo ""
echo "--- The DS-96 'out of scope here' placeholder is gone ---"
_absent "$SPEC" "DS-96 out-of-scope placeholder note is removed" \
        'DS-96, out of scope here'
_absent "$SPEC" "'Known separate defect' heading tied to DS-96 is removed" \
        'Known separate defect \(DS-96'

echo ""
echo "--- loop-state.json's own last_updated field is untouched (not renamed) ---"
_present "$SPEC" "loop-state.json schema JSON block still declares last_updated" \
         '"last_updated": "<ISO8601>"'
_present "$SPEC" "loop-state.json Field notes still name last_updated as its own field" \
         '.last_updated. is the per-turn liveness timestamp'

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
