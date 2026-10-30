#!/usr/bin/env bash
# Purpose: Pins the route-gated split of content/commands/ds-implement-ticket.md.
#          Each section body moved to content/references/<file> leaves a
#          one-line `**Procedure:**` stub in the command naming
#          `$REPO_DIR/content/references/<file>` and a §heading. This suite
#          asserts every destination file exists, its path literal appears in
#          the command exactly as many times as there are stubs for it (a lost
#          stub strands its procedure; an extra one points at nothing moved),
#          and every stub's §heading is a real heading in its destination.
#
# Public API: ./bin/tests/test_implement_ticket_reference_stubs.sh
#             Exits 0 on all pass, 1 on any failure. Auto-wired into CI by the
#             bin/tests/test_*.sh glob in .github/workflows/bin-tests.yml.
#
# Upstream deps: bash, grep, sed. Reads content/commands/ds-implement-ticket.md
#                and the content/references/ files listed in STUBSPEC.
#
# Downstream consumers: CI (bin-sh-tests); extend STUBSPEC whenever another
#                       section moves out of the command.
#
# Failure modes: none beyond a failing assertion - no writes, no network.
#
# Performance: < 1 s (grep only).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CMD="$REPO_DIR/content/commands/ds-implement-ticket.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

if [[ ! -f "$CMD" ]]; then
  echo "FAIL: $CMD not found" >&2
  exit 1
fi

while IFS=: read -r ref want; do
  [[ -n "$ref" ]] || continue
  dest="$REPO_DIR/content/references/$ref"
  if [[ -f "$dest" ]]; then
    _pass "$ref exists"
  else
    _fail "$ref does not exist"
    continue
  fi
  got="$(grep -cF "\$REPO_DIR/content/references/$ref" "$CMD")"
  if [[ "$got" -eq "$want" ]]; then
    _pass "$ref is named by $want stub line(s) in the command"
  else
    _fail "$ref is named $got time(s) in the command, expected $want"
  fi
  while IFS= read -r heading; do
    if grep -qxE "#{2,4} $(printf '%s' "$heading" | sed 's/[][\.*^$(){}+?|/]/\\&/g')" "$dest"; then
      _pass "$ref carries the stub's heading: $heading"
    else
      _fail "$ref has no heading matching the stub's §$heading"
    fi
  done < <(grep -F "Read \`\$REPO_DIR/content/references/$ref\` §" "$CMD" \
             | sed -e "s/.*references\/$ref\` §//" -e 's/ before any step here;.*//')
done <<'STUBSPEC'
open-goal-loop.md:2
batch-mode.md:3
orchestration-units.md:2
STUBSPEC

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
