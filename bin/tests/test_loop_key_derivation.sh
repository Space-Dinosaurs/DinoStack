#!/usr/bin/env bash
# Purpose: Pin the per-ticket LOOP_KEY derivation by EXTRACTING the shipped
#          spec's own fenced bash block (marker `# Resume check: loop-key
#          derivation` in content/commands/ds-implement-ticket.md) and
#          EXECUTING it - the same extract-and-execute pattern
#          bin/tests/test_ticket_rework_ledger.sh uses. The functions are never
#          copied here, so this suite fails if the spec's bash drifts from the
#          behaviour the spec's own prose promises. The marker comment is part
#          of the contract: a failed extraction is a loud failure, not a
#          silently-vacuous pass.
#
#          The properties pinned, and the mutation each one catches:
#            - the derived key is NEVER the empty string, and the assembled
#              filename ALWAYS matches ^loop-state-.+\.json$. Moving the
#              emptiness test from the FINAL ASSEMBLED KEY back to the raw
#              inputs makes `###` and `..` produce `.agentic/loop-state-.json`,
#              a file shared by every session on that branch and invisible to
#              the hooks' /^loop-state-.+\.json$/ candidate filter. The weaker
#              "no trailing -/., never escapes .agentic/" form does NOT catch
#              that mutation; this one does.
#            - SESSION_ID is sanitized BEFORE the `session-` prefix is applied.
#              Sanitizing the concatenation instead makes every garbage
#              session id collapse to the single shared key `session`.
#            - the 4-char string "null" is treated as absent, never
#              concatenated. A JSON null read through `jq -r` surfaces as that
#              literal, so the naive form yields `session-null` - one shared
#              key across every session on a harness with no id namespace.
#            - control characters are sanitized. Reverting step 1 from `tr -c`
#              to sed's `s/[^A-Za-z0-9._-]/-/g` lets a newline survive (it is
#              sed's record separator) and defeats the 64-char cap entirely
#              (measured: 129), breaking the filename invariant above.
#            - `/` never survives. Note this is asserted as "no `/`", NOT as
#              "no `..`": `.` IS in the safe set, so `..` legitimately survives
#              (`feature/../../etc/passwd` -> `feature-..-..-etc-passwd`).
#              Asserting `..` is stripped would fail against the spec's own
#              binding sanitizer. Traversal safety never depended on stripping
#              `..` - it rests on the key always being wrapped in the fixed
#              `loop-state-` / `.json` affixes, so a key can never BE a path
#              component, plus the caller's dirname assertion.
#            - the legacy unkeyed path `.agentic/loop-state.json` is never a
#              value this derivation can produce, since every key is non-empty
#              and the affixes are fixed.
#            - sanitize() is NOT injective and `PROJ/123` collides with a
#              literal `PROJ-123`. That is an ACCEPTED, documented risk, kept
#              deliberate by the passing case below rather than overlooked.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_loop_key_derivation.sh
#
# Upstream deps: bash 3.2+, python3 (stdlib, for marker extraction), and
#                content/commands/ds-implement-ticket.md as the SOURCE of the
#                code under test. All state lives in a mktemp dir; the repo is
#                never written to.
#
# Downstream consumers: the `bin-sh-tests` CI job, which glob-discovers
#                       bin/tests/test_*.sh - no CI wiring needed.
#
# Failure modes: `set -uo pipefail` WITHOUT -e (matching sibling suites), so
#                the exit code comes from the FAIL counter. Every verdict goes
#                through _pass/_fail - a bare `[ ... ]` would have its verdict
#                discarded and the suite would report "0 failed" on a real miss.
#
# Performance: < 2 s wall time (pure shell, no network, no subprocess spawns
#              beyond the extraction and /dev/urandom reads).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="$REPO_DIR/content/commands/ds-implement-ticket.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

_eq() { # _eq <label> <actual> <expected>
  if [ "$2" = "$3" ]; then _pass "$1 = '$2'"; else _fail "$1: got '$2' want '$3'"; fi
}

_matches() { # _matches <label> <actual> <ere>
  if printf '%s' "$2" | grep -Eq "$3"; then
    _pass "$1: '$2' matches /$3/"
  else
    _fail "$1: '$2' does NOT match /$3/"
  fi
}

_not_matches() { # _not_matches <label> <actual> <ere>
  if printf '%s' "$2" | grep -Eq "$3"; then
    _fail "$1: '$2' unexpectedly matches /$3/"
  else
    _pass "$1: '$2' does not match /$3/"
  fi
}

if [ ! -f "$SPEC" ]; then
  echo "FAIL: $SPEC not found" >&2
  exit 1
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# --- Extract the derivation block from the shipped spec by its marker -------
DERIVE_MARKER='# Resume check: loop-key derivation'
DERIVE_BLOCK="$TMP_ROOT/derive.sh"

if ! python3 - "$SPEC" "$DERIVE_MARKER" "$DERIVE_BLOCK" <<'PY'
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
then
  _fail "could not extract the loop-key derivation block from the shipped spec"
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi
_pass "extracted the loop-key derivation block from the shipped spec"

if bash -n "$DERIVE_BLOCK" 2>/dev/null; then
  _pass "extracted block is valid bash"
else
  _fail "extracted block is not valid bash"
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# shellcheck source=/dev/null
. "$DERIVE_BLOCK"

echo "--- ae_derive_loop_key: every reachable branch ---"

UUID="0f3c1d2e-5a6b-4c7d-8e9f-0a1b2c3d4e5f"

# B1 - the common case.
_eq "B1 common ticket id" "$(ae_derive_loop_key 'DS-90' "$UUID")" "DS-90"

# B1 - traversal-shaped id. `/` must NOT survive. `..` legitimately DOES.
TRAV="$(ae_derive_loop_key 'feature/../../etc/passwd' "$UUID")"
_not_matches "traversal id: no '/' survives sanitization" "$TRAV" '/'
_eq "traversal id sanitizes to the spec's executed output" "$TRAV" "feature-..-..-etc-passwd"

# B1 fails -> B2. `###` and `..` both sanitize to empty.
_eq "'###' ticket id falls through to the session branch" \
  "$(ae_derive_loop_key '###' "$UUID")" "session-$UUID"
_eq "'..' ticket id falls through to the session branch" \
  "$(ae_derive_loop_key '..' "$UUID")" "session-$UUID"

# B2 - empty TICKET_ID, real session id.
_eq "empty ticket id + uuid keys on the session" \
  "$(ae_derive_loop_key '' "$UUID")" "session-$UUID"

# B2 refused -> B3. The 4-char string "null" must be treated as ABSENT.
NULLSID="$(ae_derive_loop_key '' 'null')"
_matches "SESSION_ID of the literal string 'null' hits the nosid floor" \
  "$NULLSID" '^session-nosid-[0-9a-f]{8}$'
_not_matches "SESSION_ID 'null' NEVER produces the shared key 'session-null'" \
  "$NULLSID" '^session-null$'

# B2 fails -> B3: empty SESSION_ID.
_matches "empty ticket id + empty session id hits the nosid floor" \
  "$(ae_derive_loop_key '' '')" '^session-nosid-[0-9a-f]{8}$'

# B1 and B2 both fail -> B3.
_matches "'###' ticket + '###' session hits the nosid floor" \
  "$(ae_derive_loop_key '###' '###')" '^session-nosid-[0-9a-f]{8}$'

# The nosid floor must be per-invocation random, not a constant.
N1="$(ae_derive_loop_key '' '')"
N2="$(ae_derive_loop_key '' '')"
if [ "$N1" != "$N2" ]; then
  _pass "the nosid floor is random per invocation ('$N1' != '$N2')"
else
  _fail "the nosid floor produced the same key twice ('$N1') - sessions would collide"
fi

# sanitize(SESSION_ID) is applied BEFORE the prefix, never after. Sanitizing
# the concatenation would yield the shared key 'session' for every garbage id.
SANITIZED_SID="$(ae_derive_loop_key '' '###')"
_not_matches "sanitize is applied to SESSION_ID BEFORE prefixing, so garbage never yields the shared key 'session'" \
  "$SANITIZED_SID" '^session$'
_matches "garbage SESSION_ID falls through to the nosid floor instead" \
  "$SANITIZED_SID" '^session-nosid-[0-9a-f]{8}$'

echo "--- length cap and trailing-character discipline ---"

LONG_ID="$(printf 'A%.0s' $(seq 1 200))"
LONG_KEY="$(ae_derive_loop_key "$LONG_ID" "$UUID")"
_eq "a 200-char safe ticket id is capped at 64 chars" "${#LONG_KEY}" "64"
_not_matches "the capped key has no trailing '-' or '.'" "$LONG_KEY" '[-.]$'

# The truncation must not expose a trailing separator. 63 safe chars then a
# run that sanitizes to '-' puts a '-' exactly at position 64.
EDGE_ID="$(printf 'A%.0s' $(seq 1 63))///////"
EDGE_KEY="$(ae_derive_loop_key "$EDGE_ID" "$UUID")"
_not_matches "truncation never leaves a trailing '-' or '.' exposed" "$EDGE_KEY" '[-.]$'

echo "--- control characters (the sed-vs-tr distinction) ---"

# A newline is sed's RECORD SEPARATOR: `sed -e 's/[^A-Za-z0-9._-]/-/g'` does
# NOT replace it, and `cut -c1-64` truncates PER LINE. `tr -c` is byte-oriented
# and closes both. Reverting step 1 to sed fails all three assertions here.
NL_KEY="$(ae_derive_loop_key "$(printf 'x\ny')" "$UUID")"
_eq "a newline-bearing ticket id sanitizes to a single-line key" "$NL_KEY" "x-y"
if [ "$(printf '%s' "$NL_KEY" | wc -l | tr -d ' ')" = "0" ]; then
  _pass "the derived key contains no raw newline"
else
  _fail "the derived key contains a raw newline - the filename invariant is broken"
fi

# A MULTI-LINE 200-char id: under sed the cap yielded 129 chars, not 64.
ML_ID="$(printf 'A%.0s' $(seq 1 100))$(printf '\n')$(printf 'B%.0s' $(seq 1 100))"
ML_KEY="$(ae_derive_loop_key "$ML_ID" "$UUID")"
_eq "a MULTI-LINE 200-char ticket id is still capped at exactly 64" "${#ML_KEY}" "64"

# A tab and a NUL-adjacent control char must map like any other unsafe byte.
_eq "a tab-bearing ticket id sanitizes" "$(ae_derive_loop_key "$(printf 'a\tb')" "$UUID")" "a-b"

# Multibyte input: each byte maps to '-', runs collapse, trailing strip.
_eq "a multibyte ticket id strips to its safe prefix" \
  "$(ae_derive_loop_key 'DS-90é' "$UUID")" "DS-90"

echo "--- the invariants the hooks and the caller depend on ---"

# THE KEY IS NEVER EMPTY, AND THE FILENAME ALWAYS MATCHES THE CANDIDATE REGEX.
# This is the assertion that catches moving the emptiness test off the final
# assembled key. Exercised across every input shape that could plausibly empty.
for pair in \
  'DS-90|'"$UUID" \
  '###|'"$UUID" \
  '..|'"$UUID" \
  '|'"$UUID" \
  '|null' \
  '|' \
  '###|###' \
  '...|...' \
  '-|-' \
  '/|/' \
  'feature/../../etc/passwd|'"$UUID"
do
  t="${pair%%|*}"
  s="${pair#*|}"
  k="$(ae_derive_loop_key "$t" "$s")"
  if [ -z "$k" ]; then
    _fail "LOOP_KEY is the EMPTY STRING for ticket='$t' session='$s' - .agentic/loop-state-.json would be shared by every session"
    continue
  fi
  fname="loop-state-$k.json"
  if printf '%s' "$fname" | grep -Eq '^loop-state-.+\.json$'; then
    _pass "ticket='$t' session='$s' -> '$fname' matches ^loop-state-.+\\.json\$"
  else
    _fail "ticket='$t' session='$s' -> '$fname' does NOT match ^loop-state-.+\\.json\$"
  fi
  # The assembled path's dirname must resolve to .agentic/ - guard (c).
  assembled=".agentic/$fname"
  if [ "$(dirname "$assembled")" = ".agentic" ]; then
    _pass "ticket='$t' session='$s' -> assembled dirname resolves to .agentic/"
  else
    _fail "ticket='$t' session='$s' -> assembled dirname is '$(dirname "$assembled")', NOT .agentic/"
  fi
  # The derivation can never produce the LEGACY unkeyed path.
  if [ "$assembled" = ".agentic/loop-state.json" ]; then
    _fail "ticket='$t' session='$s' produced the LEGACY unkeyed path .agentic/loop-state.json"
  fi
done

echo "--- accepted, documented collision (sanitize is not injective) ---"

# KNOWN AND ACCEPTED, not a defect: sanitize() is not injective, so a freeform
# id shaped like `PROJ/123` maps onto the same key as a literal ticket key
# `PROJ-123` and the two loops would share one file - reintroducing, for that
# pair only, the contention this unit removes. Not mitigated because real Jira
# (^[A-Z][A-Z0-9]+-\d+$) and Linear (^[A-Z]+-\d+$) keys are already entirely in
# the safe set, so a collision needs an operator-supplied freeform id
# deliberately shaped to collide. The pre-specified mitigation is to append
# `-<6hex sha256(raw)>` only when sanitized != raw; it is a one-line change if
# ever observed, and is not applied now because it makes every non-ASCII-ticket
# filename unreadable for a failure nobody has hit. This case exists so the
# risk stays DELIBERATE rather than overlooked.
_eq "documented collision: 'PROJ/123' and 'PROJ-123' map to the same key" \
  "$(ae_derive_loop_key 'PROJ/123' "$UUID")" \
  "$(ae_derive_loop_key 'PROJ-123' "$UUID")"

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
