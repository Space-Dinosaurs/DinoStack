#!/usr/bin/env bash
# Purpose: DS-166 round-2 regression gate. Pins the Phase 5 ownership-claim
#          include lists at BOTH claim sites in content/commands/ds-implement-ticket.md
#          to carry `author_model` AND `ticket_id`, pins the Phase 9 ENGINEER_MODEL jq's
#          ticket scoping and the Model: printf form, and empirically runs the exact jq
#          against a sequential-style claim fixture.
#
#          WHY THIS TEST EXISTS: the DS-166 round-1 defect left the sequential
#          single-engineer claim recording author_model WITHOUT ticket_id, so the
#          ENGINEER_MODEL jq (which scopes `.ticket_id == $t`) never matched on the
#          sequential-multi-unit path - the Model: attribution line stayed inert on
#          sequential-multi-unit PRs while the round-1 comment falsely claimed the site
#          "writes nothing to disk." A prose edit that removes ticket_id from either
#          claim site (re-opening the inert-line bug), drops the jq's ticket scoping, or
#          removes the Model: printf fails here.
#
# Public API: ./bin/tests/test_ds166_model_claim_spec.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, grep, jq. Reads content/commands/ds-implement-ticket.md
#                from the checkout. Honors GATE_REPO to override the root.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml, bin-sh-tests job).
#
# Failure modes: jq missing -> hard _fail (never a silently-skipped assertion,
#                indistinguishable from a passing one); no writes outside a
#                mktemp scratch dir removed by an EXIT trap.
#
# Performance: < 1 s wall time (grep + two jq invocations; no network).

set -uo pipefail

REPO_DIR="${GATE_REPO:-$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)}"
cd "$REPO_DIR" 2>/dev/null || { echo "FATAL: cannot cd to '$REPO_DIR'" >&2; exit 2; }
if ! git rev-parse --show-toplevel >/dev/null 2>&1 \
   || [ ! -f content/commands/ds-implement-ticket.md ]; then
  echo "FATAL: '$REPO_DIR' is not a DinoStack repo root (expected content/commands/ds-implement-ticket.md). Set GATE_REPO." >&2
  exit 2
fi

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

DIT="$REPO_DIR/content/commands/ds-implement-ticket.md"

# --- Prose-pin: both claim sites carry author_model AND ticket_id --------------
# Sequential single-engineer claim (Phase 5 sequential multi-unit path): the
# round-1 defect was this site recording author_model WITHOUT ticket_id.
SEQ_CLAIM="$(grep -F "this append is the ownership claim." "$DIT" || true)"
# Parallel fan-out per-unit claim (Phase 5 parallel path).
FANOUT_CLAIM="$(grep -F "one \`in_progress\` claim record per unit" "$DIT" || true)"

if [ -z "$SEQ_CLAIM" ]; then
  _fail "sequential claim anchor 'this append is the ownership claim.' not found in $DIT"
else
  printf '%s' "$SEQ_CLAIM" | grep -qF 'author_model' \
    && _pass "sequential claim include list carries author_model" \
    || _fail "sequential claim include list lacks author_model"
  printf '%s' "$SEQ_CLAIM" | grep -qF 'ticket_id' \
    && _pass "sequential claim include list carries ticket_id" \
    || _fail "sequential claim include list lacks ticket_id (round-1 inert-line defect)"
fi

if [ -z "$FANOUT_CLAIM" ]; then
  _fail "fan-out claim anchor 'one \`in_progress\` claim record per unit' not found in $DIT"
else
  printf '%s' "$FANOUT_CLAIM" | grep -qF 'author_model' \
    && _pass "fan-out claim include list carries author_model" \
    || _fail "fan-out claim include list lacks author_model"
  printf '%s' "$FANOUT_CLAIM" | grep -qF 'ticket_id' \
    && _pass "fan-out claim include list carries ticket_id" \
    || _fail "fan-out claim include list lacks ticket_id"
fi

# --- Prose-pin: ENGINEER_MODEL jq scopes on ticket_id; Model: printf survives ---
grep -qF '.ticket_id == $t' "$DIT" \
  && _pass "ENGINEER_MODEL jq scopes on .ticket_id == \$t" \
  || _fail "ENGINEER_MODEL jq no longer scopes on .ticket_id == \$t"
grep -qF 'printf "\nModel: %s\n" "$ENGINEER_MODEL"' "$DIT" \
  && _pass "Model: printf form present" \
  || _fail "Model: printf form missing"

# --- Empirical: the exact ENGINEER_MODEL jq returns the model for a
#     ticket_id+author_model sequential-style claim, and EMPTY for the
#     round-1 defect shape (a claim that drops ticket_id) ----------------------
if command -v jq >/dev/null 2>&1; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  cat > "$TMP/tasks-with-ticket.jsonl" <<'EOF'
{"task_id":"TASK-1-seq","session_id":"s1","ticket_id":"TICKET-1","unit_slug":"u1","status":"in_progress","depends_on":[],"created_at":"2026-08-12T00:00:00Z","updated_at":"2026-08-12T00:00:00Z","author_model":"claude-sonnet-4","assigned_agent":"engineer","worktree_path":"/wt","branch_name":"feature/ticket-1"}
{"task_id":"TASK-2-seq","session_id":"s1","ticket_id":"TICKET-1","unit_slug":"u2","status":"done","depends_on":["TASK-1-seq"],"created_at":"2026-08-12T00:00:00Z","updated_at":"2026-08-12T00:00:00Z","author_model":"claude-sonnet-4","assigned_agent":"engineer","worktree_path":"/wt","branch_name":"feature/ticket-1"}
EOF

  cat > "$TMP/tasks-no-ticket.jsonl" <<'EOF'
{"task_id":"TASK-1-seq","session_id":"s1","unit_slug":"u1","status":"in_progress","depends_on":[],"created_at":"2026-08-12T00:00:00Z","updated_at":"2026-08-12T00:00:00Z","author_model":"claude-sonnet-4","assigned_agent":"engineer","worktree_path":"/wt","branch_name":"feature/ticket-1"}
EOF

  ENGINEER_MODEL_JQ='[.[] | select(.ticket_id == $t and .assigned_agent == "engineer" and .author_model != null and (.status == "in_progress" or .status == "done")) | .author_model] | unique | join(", ")'

  RESULT_POS="$(jq -sr --arg t "TICKET-1" "$ENGINEER_MODEL_JQ" "$TMP/tasks-with-ticket.jsonl" 2>/dev/null || true)"
  if [ "$RESULT_POS" = "claude-sonnet-4" ]; then
    _pass "ENGINEER_MODEL jq returns non-empty model for a sequential-style ticket_id+author_model claim"
  else
    _fail "ENGINEER_MODEL jq returned '$RESULT_POS' (expected 'claude-sonnet-4') for a ticket_id+author_model claim - the Model: attribution read would be inert"
  fi

  RESULT_NEG="$(jq -sr --arg t "TICKET-1" "$ENGINEER_MODEL_JQ" "$TMP/tasks-no-ticket.jsonl" 2>/dev/null || true)"
  if [ -z "$RESULT_NEG" ]; then
    _pass "ENGINEER_MODEL jq returns EMPTY for a claim that drops ticket_id (round-1 defect shape)"
  else
    _fail "ENGINEER_MODEL jq returned '$RESULT_NEG' for a claim that drops ticket_id (expected empty) - the round-1 defect shape would now silently attribute a model"
  fi
else
  _fail "jq not found on PATH - ENGINEER_MODEL empirical check cannot run (a silently-skipped regression guard is indistinguishable from a passing one)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
