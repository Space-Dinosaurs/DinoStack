#!/usr/bin/env bash
# Purpose: Regression guard for the ticket-rework alert's THREE executable
#          blocks in content/commands/ds-implement-ticket.md:
#            1. the Phase 1 per-ticket variable reset  (RESET_MARKER)
#            2. the Phase 1 detection read             (READ_MARKER)
#            3. the Phase 9 ledger write               (WRITE_MARKER)
#          All three are EXTRACTED FROM THE SHIPPED SPEC by their marker
#          comment and executed, not copied here, so this test fails if the
#          spec's bash drifts from the behaviour the spec's own prose
#          promises. Each marker is part of the contract - see Failure modes.
#
#          Each fixture below pins a defect found in Skeptic review of the
#          originating PR, so a future edit that reintroduces one fails here.
#          Review round 1:
#            - qa_status must carry the skip rationale on BOTH non-QA paths
#              (Trivial, and Elevated with qa_skip), never a bare null. A
#              null renders "n/a" in the operator notice, which says QA was
#              unavailable when the truth is it was deliberately skipped.
#            - skeptic_rounds must be the SKEPTIC round count, not the QA
#              loop's. Phase 6b overwrites the keyed loop-state file with
#              phase:qa, iteration:1 before Phase 9 runs. Per-ticket keying
#              does NOT fix this: same ticket, same key, same file.
#            - skeptic_rounds must not be inherited from another ticket. This
#              is now enforced by TWO independent mechanisms, and the three
#              cases below cover both: the file is KEYED PER TICKET, so a
#              foreign ticket's state is not at this path at all and the
#              `[ -f ]` test short-circuits; and the surviving ticket_id jq
#              guard still rejects a foreign record if $LOOP_KEY is
#              mis-derived. Before keying there was one shared
#              .agentic/loop-state.json that persisted across a batch, and an
#              unscoped read gave Trivial ticket 2 Elevated ticket 1's count.
#            - detection must skip ONE malformed line, not abort the whole
#              parse. The ledger is appended locklessly; a torn line is an
#              expected input, and slurp would disable detection for every
#              ticket in the file permanently.
#            - duplicate pr_number must resolve latest-wins (replay carries
#              the resolved qa_status and higher skeptic_rounds).
#          Review round 2:
#            - the Trivial rationale needs a definition site a Trivial ticket
#              can actually REACH. Phase 6b's skip branch carries the same
#              string but is unreachable on the Trivial path, so a
#              Phase-6b-only definition satisfies the prose and still writes
#              null. It must be set at the Phase 2 declaration. Pinned by
#              prose invariants, because a runtime fixture that injects
#              QA_STATUS asserts pass-through, not derivation - which is
#              precisely how this defect survived a green suite once.
#            - the three in-context variables that feed the record
#              (RISK_CLASS, SKEPTIC_ROUNDS, QA_STATUS) must be reset per
#              ticket. The conductor carries ONE scope across a batch, so
#              without the reset a Trivial ticket inherits the previous
#              Elevated ticket's values - and a stale SKEPTIC_ROUNDS also
#              short-circuits the [ -z "$TRL_ROUNDS" ] gate, disabling the
#              ticket_id/phase guards in the exact case they exist for.
#
# Public API: ./bin/tests/test_ticket_rework_ledger.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, jq, python3, mktemp. Reads
#                content/commands/ds-implement-ticket.md from the checkout.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: a missing or renamed extraction marker fails loudly rather
#                than silently testing nothing - the marker comments are part
#                of the contract. `gh` is stubbed on PATH, so no network call
#                is ever made and the real gh is never invoked. All state is
#                written under a mktemp dir; the repo is never touched.
#
# Performance: < 2 s wall time (pure shell + jq, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="$REPO_DIR/content/commands/ds-implement-ticket.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

_eq() { # _eq <label> <actual> <expected>
  if [[ "$2" == "$3" ]]; then _pass "$1 = $2"; else _fail "$1: got '$2' want '$3'"; fi
}

if [[ ! -f "$SPEC" ]]; then
  echo "FAIL: $SPEC not found" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# --- Extract the two fenced bash blocks from the shipped spec by marker ----
# The marker comments are the first line of each block in the spec. If either
# is renamed the extraction fails loudly rather than testing a stale copy.
WRITE_MARKER='# Phase 9: ticket-rework ledger write'
READ_MARKER='# Phase 1: ticket-rework detection'
RESET_MARKER='# Phase 1: per-ticket variable reset'

_extract() { # _extract <marker> <outfile>
  python3 - "$SPEC" "$1" "$2" <<'PY'
import sys
spec, marker, out = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(spec).read()
i = text.find(marker)
if i < 0:
    sys.exit("marker not found: " + marker)
j = text.find("\n```", i)
if j < 0:
    sys.exit("unterminated fenced block for marker: " + marker)
open(out, "w").write(text[i:j] + "\n")
PY
}

WRITE_BLOCK="$TMP_ROOT/write.sh"
READ_BLOCK="$TMP_ROOT/read.sh"

if ! _extract "$WRITE_MARKER" "$WRITE_BLOCK"; then
  _fail "could not extract the Phase 9 write block from the spec"
  echo "Results: $PASS passed, $FAIL failed"; exit 1
fi
_pass "extracted Phase 9 write block from the shipped spec"

if ! _extract "$READ_MARKER" "$READ_BLOCK"; then
  _fail "could not extract the Phase 1 detection block from the spec"
  echo "Results: $PASS passed, $FAIL failed"; exit 1
fi
_pass "extracted Phase 1 detection block from the shipped spec"

RESET_BLOCK="$TMP_ROOT/reset.sh"
if ! _extract "$RESET_MARKER" "$RESET_BLOCK"; then
  _fail "could not extract the Phase 1 per-ticket reset block from the spec"
  echo "Results: $PASS passed, $FAIL failed"; exit 1
fi
_pass "extracted Phase 1 per-ticket reset block from the shipped spec"

# Self-check: this file's own manifest must name every marker it extracts.
# The manifest tells a maintainer which comments are load-bearing; a manifest
# that undercounts them invites removing one that is. (This exact staleness
# was a Major finding in review round 3, when a third marker was added and
# the header still said "two executable blocks".)
MARKER_COUNT=3
if [[ "$(grep -cE '^[A-Z]+_MARKER=' "$0")" -eq "$MARKER_COUNT" ]]; then
  _pass "marker count matches the manifest's stated $MARKER_COUNT blocks"
else
  _fail "this file defines $(grep -cE '^[A-Z]+_MARKER=' "$0") markers but its manifest documents $MARKER_COUNT - update the Purpose field"
fi

for b in "$WRITE_BLOCK" "$READ_BLOCK" "$RESET_BLOCK"; do
  if bash -n "$b" 2>/dev/null; then
    _pass "extracted block parses: $(basename "$b")"
  else
    _fail "extracted block is not valid bash: $(basename "$b")"
  fi
done

# --- Sandbox: fake gh on PATH, throwaway repo root -------------------------
WORK="$TMP_ROOT/work"
mkdir -p "$WORK/.agentic" "$TMP_ROOT/bin"
cat > "$TMP_ROOT/bin/gh" <<'GH'
#!/usr/bin/env bash
# Stub: emits $FAKE_GH_PR, or fails like `gh pr view` on an unknown branch.
[ -n "${FAKE_GH_PR:-}" ] || exit 1
echo "$FAKE_GH_PR"
GH
chmod +x "$TMP_ROOT/bin/gh"
export PATH="$TMP_ROOT/bin:$PATH"
cd "$WORK" || exit 1

_write() { # _write - run the Phase 9 block with the caller's env
  env "$@" bash -c "source '$WRITE_BLOCK'"
}
_last() { tail -1 .agentic/ticket-ledger.jsonl; }
_field() { _last | jq -r "$1"; }

# ===========================================================================
echo ""
echo "--- Elevated happy path: full record ---"
: > .agentic/ticket-ledger.jsonl
printf '{"ticket_id":"DS-87","loop_state":{"phase":"skeptic","iteration":3}}' > .agentic/loop-state-DS-87.json
printf '%s\n' \
  '{"task_id":"DS-87-a","ticket_id":"DS-87"}' \
  '{"task_id":"DS-87-b","ticket_id":"DS-87"}' \
  '{"task_id":"DS-99-a","ticket_id":"DS-99"}' > .agentic/tasks.jsonl
_write REWORK_DETECTION=true TICKET_ID=DS-87 LOOP_KEY=DS-87 BRANCH_NAME=feature/ds-87 GH_REPO=o/r \
       RISK_CLASS=Elevated SKEPTIC_ROUNDS=3 QA_STATUS=PASS FAKE_GH_PR=458
_eq "elevated pr_number"      "$(_field .pr_number)"      "458"
_eq "elevated skeptic_rounds" "$(_field .skeptic_rounds)" "3"
_eq "elevated qa_status"      "$(_field .qa_status)"      "PASS"
_eq "elevated unit_count"     "$(_field .unit_count)"     "2"
_eq "elevated branch"         "$(_field .branch)"         "feature/ds-87"
_eq "opened_ts is ISO8601 Z"  "$(_field .opened_ts | grep -cE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')" "1"

# ===========================================================================
echo ""
echo "--- Major 1: qa_status carries the rationale on BOTH non-QA paths ---"
: > .agentic/ticket-ledger.jsonl
rm -f .agentic/loop-state-*.json .agentic/tasks.jsonl
# Trivial: no Skeptic loop, no QA. Rationale, not null.
_write REWORK_DETECTION=true TICKET_ID=DS-91 LOOP_KEY=DS-91 BRANCH_NAME=fix/ds-91 GH_REPO=o/r \
       RISK_CLASS=Trivial QA_STATUS="skipped:Trivial path" FAKE_GH_PR=462
_eq "trivial risk_class"     "$(_field .risk_class)"          "Trivial"
_eq "trivial qa_status"      "$(_field .qa_status)"           "skipped:Trivial path"
_eq "trivial qa NOT null"    "$(_field '.qa_status|type')"    "string"
_eq "trivial skeptic null"   "$(_field '.skeptic_rounds|type')" "null"
_eq "trivial unit_count"     "$(_field .unit_count)"          "1"

# Elevated with qa_skip: Skeptic ran, QA did not. Rationale, not null.
printf '{"ticket_id":"DS-92","loop_state":{"phase":"skeptic","iteration":2}}' > .agentic/loop-state-DS-92.json
_write REWORK_DETECTION=true TICKET_ID=DS-92 LOOP_KEY=DS-92 BRANCH_NAME=feature/ds-92 GH_REPO=o/r \
       RISK_CLASS=Elevated SKEPTIC_ROUNDS=2 QA_STATUS="skipped:docs-only" FAKE_GH_PR=463
_eq "qa_skip qa_status"      "$(_field .qa_status)"           "skipped:docs-only"
_eq "qa_skip qa NOT null"    "$(_field '.qa_status|type')"    "string"
_eq "qa_skip rounds kept"    "$(_field .skeptic_rounds)"      "2"

# ===========================================================================
echo ""
echo "--- Major 2: skeptic_rounds is the Skeptic count, not the QA count ---"
# CASE 2 of the three keying cases - THE PHASE GUARD.
# Phase 6b has overwritten THIS ticket's own keyed file with phase:qa,
# iteration:1 by Phase 9. Keying does not help here (same ticket, same key,
# same file), so the phase guard is the only thing standing between the
# operator and "1 Skeptic round" on a ticket that took three.
# The in-context SKEPTIC_ROUNDS captured at Phase 6 clean exit must win.
: > .agentic/ticket-ledger.jsonl
rm -f .agentic/loop-state-*.json
printf '{"ticket_id":"DS-93","loop_state":{"phase":"qa","iteration":1}}' > .agentic/loop-state-DS-93.json
_write REWORK_DETECTION=true TICKET_ID=DS-93 LOOP_KEY=DS-93 BRANCH_NAME=feature/ds-93 GH_REPO=o/r \
       RISK_CLASS=Elevated SKEPTIC_ROUNDS=3 QA_STATUS=PASS FAKE_GH_PR=464
_eq "3 skeptic rounds not 1 QA iteration" "$(_field .skeptic_rounds)" "3"

# Resume fallback: in-context value lost, THIS ticket's own keyed file is found
# and its phase is qa -> the phase clause rejects it. PINS THE PHASE GUARD:
# the file exists at the invoked key, so [ -f ] does NOT short-circuit and jq
# genuinely runs. Deleting the phase clause makes this assertion return 1.
: > .agentic/ticket-ledger.jsonl
_write REWORK_DETECTION=true TICKET_ID=DS-93 LOOP_KEY=DS-93 BRANCH_NAME=feature/ds-93 GH_REPO=o/r \
       RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=464
_eq "phase:qa disk read rejected" "$(_field '.skeptic_rounds|type')" "null"

# Resume fallback: this ticket's own keyed file says phase:skeptic -> accepted.
# Positive control: without it, "returns null" would be satisfied by a read
# that never happened.
: > .agentic/ticket-ledger.jsonl
printf '{"ticket_id":"DS-93","loop_state":{"phase":"skeptic","iteration":4}}' > .agentic/loop-state-DS-93.json
_write REWORK_DETECTION=true TICKET_ID=DS-93 LOOP_KEY=DS-93 BRANCH_NAME=feature/ds-93 GH_REPO=o/r \
       RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=464
_eq "phase:skeptic disk read accepted" "$(_field .skeptic_rounds)" "4"

# ===========================================================================
echo ""
echo "--- Major 3 / CASE 1: batch - ticket 2 must not inherit ticket 1's rounds ---"
# CASE 1 of the three keying cases - THE ABSENT-FILE CASE. PINS THE KEYING
# MECHANISM ITSELF. Elevated ticket DS-87 finished and left its own keyed file
# behind at iteration 3. Ticket DS-88 now opens its PR under LOOP_KEY=DS-88.
# .agentic/loop-state-DS-88.json does not exist, so the [ -f ] test
# short-circuits, jq NEVER RUNS, and skeptic_rounds is null. Reverting the
# Phase 9 read to the shared unkeyed path makes this find DS-87's file and
# report 3 rounds for a Trivial ticket that ran no Skeptic loop.
: > .agentic/ticket-ledger.jsonl
rm -f .agentic/loop-state-*.json
printf '{"ticket_id":"DS-87","loop_state":{"phase":"skeptic","iteration":3}}' > .agentic/loop-state-DS-87.json
_write REWORK_DETECTION=true TICKET_ID=DS-88 LOOP_KEY=DS-88 BRANCH_NAME=fix/ds-88 GH_REPO=o/r \
       RISK_CLASS=Trivial QA_STATUS="skipped:Trivial path" FAKE_GH_PR=465
_eq "CASE 1 absent-file: foreign ticket rounds not inherited" "$(_field '.skeptic_rounds|type')" "null"

# ===========================================================================
echo ""
echo "--- CASE 3: mis-derived LOOP_KEY - the ONLY case that exercises the ticket_id guard ---"
# The keep-both-guards ruling needs a test, or it is supported by nothing.
# Here TICKET_ID=DS-88 but LOOP_KEY=DS-87 - a MIS-DERIVED key, the failure mode
# the ticket_id guard is retained as defence-in-depth against. The file IS
# found (so [ -f ] does not short-circuit) and its phase IS "skeptic" (so the
# phase clause passes), which means the ticket_id clause is the ONLY thing
# producing null. Delete that clause and this assertion returns 3.
: > .agentic/ticket-ledger.jsonl
rm -f .agentic/loop-state-*.json
printf '{"ticket_id":"DS-87","loop_state":{"phase":"skeptic","iteration":3}}' > .agentic/loop-state-DS-87.json
_write REWORK_DETECTION=true TICKET_ID=DS-88 LOOP_KEY=DS-87 BRANCH_NAME=fix/ds-88 GH_REPO=o/r \
       RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=466
_eq "CASE 3 mis-derived key: the ticket_id guard rejects the foreign record" \
    "$(_field '.skeptic_rounds|type')" "null"

# ===========================================================================
echo ""
echo "--- Major B: batch carry-over in ONE shell scope (the real conductor shape) ---"
# Every fixture above builds a fresh env per invocation, which CANNOT model the
# actual failure: the conductor carries ONE variable scope across a whole batch.
# This block runs two tickets in a single `bash -c` with no env reset between
# them, exactly as the conductor does, and applies the spec's own reset block at
# the top of ticket 2 - the mechanism under test.
: > .agentic/ticket-ledger.jsonl
rm -f .agentic/loop-state-*.json
printf '{"ticket_id":"DS-87","loop_state":{"phase":"skeptic","iteration":3}}' > .agentic/loop-state-DS-87.json

BATCH_OUT=$(env GH_REPO=o/r REWORK_DETECTION=true bash -c '
  # ---- ticket 1: Elevated. Sets all three variables on its own path. ----
  RISK_CLASS="Elevated"; SKEPTIC_ROUNDS=3; QA_STATUS="PASS"
  TICKET_ID="DS-87"; LOOP_KEY="DS-87"; BRANCH_NAME="feature/ds-87"; FAKE_GH_PR=458
  export FAKE_GH_PR
  source "'"$WRITE_BLOCK"'"

  # ---- ticket 2: Trivial. Reaches neither Phase 6 nor Phase 6b. ----
  # The spec reset runs first, then only what a Trivial ticket actually sets.
  # LOOP_KEY is re-derived per ticket at the Resume check, so ticket 2 carries
  # its OWN key - which is exactly why its keyed file is absent below.
  source "'"$RESET_BLOCK"'"
  RISK_CLASS="Trivial"; QA_STATUS="skipped:Trivial path"   # Phase 2 declaration
  TICKET_ID="DS-91"; LOOP_KEY="DS-91"; BRANCH_NAME="fix/ds-91"; FAKE_GH_PR=462
  export FAKE_GH_PR
  source "'"$WRITE_BLOCK"'"
')

t1=$(head -1 .agentic/ticket-ledger.jsonl)
t2=$(tail -1 .agentic/ticket-ledger.jsonl)
_eq "batch t1 records its own rounds"       "$(echo "$t1" | jq -r .skeptic_rounds)"      "3"
_eq "batch t1 records its own qa_status"    "$(echo "$t1" | jq -r .qa_status)"           "PASS"
_eq "batch t2 does NOT inherit rounds"      "$(echo "$t2" | jq -r '.skeptic_rounds|type')" "null"
_eq "batch t2 does NOT inherit PASS"        "$(echo "$t2" | jq -r .qa_status)"           "skipped:Trivial path"
_eq "batch t2 does NOT inherit risk_class"  "$(echo "$t2" | jq -r .risk_class)"          "Trivial"
_eq "batch t2 is its own ticket"            "$(echo "$t2" | jq -r .ticket_id)"           "DS-91"

# The reset is what makes the Phase 9 disk fallback REACHABLE. Without it,
# SKEPTIC_ROUNDS is still 3 from ticket 1, the `[ -z "$TRL_ROUNDS" ]` gate is
# false, and the fallback never executes at all. Prove the fallback runs and
# still yields null: .agentic/loop-state-DS-87.json still says DS-87/skeptic/3,
# and ticket 2 (LOOP_KEY=DS-91) must still get null.
#
# LABEL CORRECTED for per-ticket keying. This scenario now returns null via the
# `[ -f ]` KEYING SHORT-CIRCUIT - ticket 2's own keyed file does not exist, so
# jq never runs and the ticket_id guard is never reached. The old label claimed
# "its ticket_id guard rejected the foreign record", which became FALSE here
# while the suite stayed green - exactly the defect class this suite guards
# against. The ticket_id-guard claim now lives on CASE 3 above, where the file
# IS found and the guard genuinely is the only thing producing null.
_eq "disk fallback returned null for the foreign record (via keying short-circuit)" \
    "$(echo "$t2" | jq -r '.skeptic_rounds|type')" "null"

# Isolate the RESET itself. Above, ticket 2 sets QA_STATUS explicitly (modelling
# the Phase 2 declaration), so that assertion would hold even with no reset at
# all. Here ticket 2 sets NOTHING beyond its identity: any non-empty field can
# only have come from ticket 1. This is the assertion that fails without the
# reset block, independent of whether any later definition site fires.
: > .agentic/ticket-ledger.jsonl
env GH_REPO=o/r REWORK_DETECTION=true bash -c '
  RISK_CLASS="Elevated"; SKEPTIC_ROUNDS=3; QA_STATUS="PASS"
  TICKET_ID="DS-87"; BRANCH_NAME="feature/ds-87"; FAKE_GH_PR=458
  export FAKE_GH_PR
  source "'"$WRITE_BLOCK"'"

  source "'"$RESET_BLOCK"'"      # <- the mechanism under test, and nothing else
  TICKET_ID="DS-91"; BRANCH_NAME="fix/ds-91"; FAKE_GH_PR=462
  export FAKE_GH_PR
  source "'"$WRITE_BLOCK"'"
' >/dev/null 2>&1
bare=$(tail -1 .agentic/ticket-ledger.jsonl)
_eq "reset alone neutralises qa_status carry-over"  "$(echo "$bare" | jq -r '.qa_status|type')"      "null"
_eq "reset alone neutralises rounds carry-over"     "$(echo "$bare" | jq -r '.skeptic_rounds|type')" "null"
# risk_class normalizes ""->null like its two siblings, so a cleared value
# stores an explicit null (which the null-render rule renders "n/a") rather
# than an empty string, which that rule has nothing sensible to render.
_eq "reset alone neutralises risk_class carry-over" "$(echo "$bare" | jq -r '.risk_class|type')"    "null"

# ===========================================================================
echo ""
echo "--- Phase 9 skip conditions: no record written ---"
: > .agentic/ticket-ledger.jsonl
_write REWORK_DETECTION=false TICKET_ID=DS-94 BRANCH_NAME=b GH_REPO=o/r RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=999
_eq "toggle off writes nothing"   "$(wc -l < .agentic/ticket-ledger.jsonl | tr -d ' ')" "0"
_write REWORK_DETECTION=true TICKET_ID= BRANCH_NAME=b GH_REPO=o/r RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=999
_eq "empty ticket writes nothing" "$(wc -l < .agentic/ticket-ledger.jsonl | tr -d ' ')" "0"
_write REWORK_DETECTION=true TICKET_ID=DS-94 BRANCH_NAME=b GH_REPO=o/r RISK_CLASS=Elevated QA_STATUS=PASS FAKE_GH_PR=
_eq "no PR number writes nothing" "$(wc -l < .agentic/ticket-ledger.jsonl | tr -d ' ')" "0"

# ===========================================================================
echo ""
echo "--- Phase 1 detection ---"
_read() { # _read <ticket> <toggle> -> "<attempts>|<is_rework>|<latest_pr>"
  env REWORK_DETECTION="$2" TICKET_ID="$1" bash -c \
    "source '$READ_BLOCK'
     printf '%s|%s|%s' \"\$PRIOR_ATTEMPTS\" \"\$IS_REWORK\" \
       \"\$(printf '%s' \"\$PRIOR_COMPLETED_JSON\" | jq -r '.[-1].pr_number // \"-\"')\""
}

: > .agentic/ticket-ledger.jsonl
printf '%s\n' \
  '{"ticket_id":"DS-87","pr_number":458,"opened_ts":"2026-07-17T11:54:58Z"}' \
  '{"ticket_id":"DS-99","pr_number":401,"opened_ts":"2026-07-01T00:00:00Z"}' \
  '{"ticket_id":"DS-87","pr_number":470,"opened_ts":"2026-07-20T09:00:00Z"}' \
  >> .agentic/ticket-ledger.jsonl
_eq "two attempts, latest last" "$(_read DS-87 true)" "2|true|470"
_eq "other ticket unaffected"   "$(_read DS-99 true)" "1|true|401"
_eq "unknown ticket is inert"   "$(_read DS-404 true)" "0|false|-"
_eq "toggle off is inert"       "$(_read DS-87 false)" "0|false|-"

echo ""
echo "--- Major 4: ONE malformed line must not disable the whole ledger ---"
cp .agentic/ticket-ledger.jsonl "$TMP_ROOT/ledger.good"
printf '%s\n' '{"ticket_id":"DS-87","pr_num' >> .agentic/ticket-ledger.jsonl   # torn append
printf '%s\n' '{"ticket_id":"DS-87","pr_number":480,"opened_ts":"2026-07-22T00:00:00Z"}' \
  >> .agentic/ticket-ledger.jsonl
_eq "good lines survive a torn line" "$(_read DS-87 true)" "3|true|480"
cp "$TMP_ROOT/ledger.good" .agentic/ticket-ledger.jsonl

echo ""
echo "--- Minor 2: duplicate pr_number resolves latest-wins ---"
: > .agentic/ticket-ledger.jsonl
printf '%s\n' \
  '{"ticket_id":"DS-87","pr_number":458,"opened_ts":"2026-07-17T00:00:00Z","skeptic_rounds":1,"qa_status":null}' \
  '{"ticket_id":"DS-87","pr_number":458,"opened_ts":"2026-07-18T00:00:00Z","skeptic_rounds":3,"qa_status":"PASS"}' \
  >> .agentic/ticket-ledger.jsonl
dup=$(env REWORK_DETECTION=true TICKET_ID=DS-87 bash -c \
  "source '$READ_BLOCK'
   printf '%s|%s' \"\$PRIOR_ATTEMPTS\" \
     \"\$(printf '%s' \"\$PRIOR_COMPLETED_JSON\" | jq -r '.[-1].skeptic_rounds')\"")
_eq "duplicate collapses, later record wins" "$dup" "1|3"

echo ""
echo "--- absent ledger ---"
rm -f .agentic/ticket-ledger.jsonl
_eq "absent ledger is inert" "$(_read DS-87 true)" "0|false|-"

# ===========================================================================
# Prose invariants. Some defects in this feature live in the spec's PROSE, not
# its bash - the conductor is the interpreter, so an instruction that tells it
# to set a variable to the wrong value is a real defect that no runtime
# fixture can catch. (Precedent: bin/tests/test_tracker_writeback_ranking_spec.py
# pins prose invariants for another block in this same file.)
echo ""
echo "--- Major 1 (prose): qa_status contract must not contradict itself ---"

_absent() { # _absent <label> <pattern>
  if grep -qiE "$2" "$SPEC"; then
    _fail "$1 - spec still contains: /$2/"
  else
    _pass "$1"
  fi
}
_present() { # _present <label> <pattern>
  if grep -qiE "$2" "$SPEC"; then
    _pass "$1"
  else
    _fail "$1 - spec no longer contains: /$2/"
  fi
}

# The retracted clause: it named Trivial and qa_skip as null-writing paths,
# directly contradicting the sentence before it and the merged reference doc
# (content/references/ticket-rework.md nullability table + Trivial example).
_absent "no 'empty when legitimately null (Trivial, or Elevated with qa_skip)' clause" \
        'empty when it is legitimately null'
_absent "no 'Null on two paths' claim for qa_status" \
        '\*\*Null on two paths\*\*'

# The contract that replaced it must still be stated.
_present "both non-QA paths documented as writing the rationale" \
         'Both non-QA paths .* write the rationale, not null'
_present "Phase 6b skip branch sets QA_STATUS" \
         'QA_STATUS="skipped:<rationale>"'
_present "Phase 6b PASS exit sets QA_STATUS" \
         'QA_STATUS="PASS"'
_present "every other terminal QA verdict sets QA_STATUS (incl. INCONCLUSIVE)" \
         'QA_STATUS="INCONCLUSIVE"'

# Major A: the contract above is only real if a Trivial ticket can REACH a
# definition site. Phase 6b is unreachable on the Trivial path, so a
# Phase-6b-only definition satisfies the prose and still writes null. Pin the
# mechanism, not just the promise: the Trivial rationale must be set at the
# Phase 2 declaration, which is on the Trivial path.
_present "a Trivial-REACHABLE QA_STATUS definition site exists (Phase 2 declaration)" \
         'QA_STATUS="skipped:Trivial path"'
_present "the Phase 2 declaration subsection is unconditional" \
         '### Risk classification declaration \(unconditional'
_present "spec states why Phase 6b alone is insufficient for Trivial" \
         'only point in the command a Trivial ticket can record that rationale'

echo ""
echo "--- Major B (prose): per-ticket reset must exist and cover all three ---"
_present "per-ticket reset section exists" \
         '### Per-ticket variable reset'
_present "reset clears RISK_CLASS"    'RISK_CLASS=""'
_present "reset clears SKEPTIC_ROUNDS" 'SKEPTIC_ROUNDS=""'
_present "reset clears QA_STATUS"      'QA_STATUS=""'
_present "reset explains it makes the disk fallback reachable" \
         'makes the Phase 9 disk fallback .*reachable'

echo ""
echo "--- Major 2 (prose): SKEPTIC_ROUNDS captured before Phase 6b overwrites ---"
_present "Phase 6 Step 3 clean exit sets SKEPTIC_ROUNDS" \
         'Set .SKEPTIC_ROUNDS. to this loop.s final'
_present "the overwrite hazard is stated at the capture site" \
         'overwriting the Phase 6 state'

echo ""
echo "--- Major 4 (prose): the anti-slurp rule must survive edits ---"
_present "spec warns against -s (slurp) for the detection read" \
         'Do NOT use .-s. \(slurp\)'
_absent  "detection block no longer uses jq -cs" \
         'jq -cs --arg t'

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
