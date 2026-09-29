#!/usr/bin/env bash
# Purpose: Wiring guard for content/references/runbook-conductor.md. Asserts
#          the reference exists, that its two entry pointers name it
#          (/ds-ticket-triage Output item 8 and the conductor-turn-format.md
#          scope-filter exception), and that the triage artifact's Kickoff
#          skeleton carries no /rename line (the rename belongs only to the
#          post-"conduct" chat output, so runs without cross-session tools
#          keep today's artifact).
#
# Public API: ./bin/tests/test_runbook_conductor_wiring.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml.
#
# Upstream deps: bash, grep, awk. Reads the three files above from the checkout.
#
# Downstream consumers: developer running locally; CI (bin-tests.yml).
#                       Retires with the reference: delete this file in the
#                       same change that removes runbook-conductor.md.
#
# Failure modes: none beyond a failing assertion - no writes, no network.
#
# Performance: < 1 s.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
REF_PATH="content/references/runbook-conductor.md"
REF="$REPO_DIR/$REF_PATH"
TRIAGE="$REPO_DIR/content/commands/ds-ticket-triage.md"
TURN="$REPO_DIR/content/references/conductor-turn-format.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

for f in "$TRIAGE" "$TURN"; do
  if [[ ! -f "$f" ]]; then
    echo "FAIL: $f not found" >&2
    exit 1
  fi
done

if [[ -f "$REF" ]]; then
  _pass "reference exists: $REF_PATH"
else
  _fail "reference missing: $REF_PATH"
fi

item8="$(awk '/^## Output$/{in_out=1; next} in_out && /^## /{in_out=0} in_out && /^8\. /{print}' "$TRIAGE")"
if [[ -z "$item8" ]]; then
  _fail "ds-ticket-triage.md ## Output has no item 8"
elif grep -qF "$REF_PATH" <<<"$item8"; then
  _pass "triage Output item 8 names $REF_PATH"
else
  _fail "triage Output item 8 does not name $REF_PATH"
fi

exception="$(grep -F 'Exception: in a runbook-conductor session' "$TURN")"
if [[ -z "$exception" ]]; then
  _fail "conductor-turn-format.md has no runbook-conductor scope-filter exception"
elif grep -qF "$REF_PATH" <<<"$exception"; then
  _pass "conductor-turn-format.md exception names $REF_PATH"
else
  _fail "conductor-turn-format.md exception does not name $REF_PATH"
fi

kickoff="$(awk '/^## Kickoff prompts$/{in_k=1; next} in_k && /phase=draft/{in_k=0} in_k{print}' "$TRIAGE")"
if [[ -z "$kickoff" ]]; then
  _fail "ds-ticket-triage.md Kickoff prompts skeleton not found"
elif grep -qF '/rename' <<<"$kickoff"; then
  _fail "Kickoff prompts skeleton contains /rename (it belongs only in the post-conduct chat output)"
else
  _pass "Kickoff prompts skeleton contains no /rename"
fi

echo "---"
echo "$PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
