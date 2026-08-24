#!/usr/bin/env bash
# Purpose: Executable regression spec proving each DS-192 awk field-
#          selector rewrite (bare $N -> harness-substitution-safe `-v idx=N
#          '{print $(idx)}'`/`$NF` idiom) produces output byte-identical to
#          its pre-rewrite form, on representative fixtures, for every
#          rewritten site's field-access shape: the `developer_id:` line
#          ($2 vs $NF), a numstat sum fixture ($2 vs -v idx=2 $(idx) over
#          multiple rows), an ls-tree-shaped fixture ($1/$3 vs -v idx=1/-v
#          idx=3 $(idx)), and the kill-switch printf line (both $2/$3
#          positions vs -v idx2=2 -v idx3=3 $(idx2)/$(idx3)).
#
# Public API: none (standalone script; `bash bin/tests/test_arg_substitution_field_rewrites.sh`).
#
# Upstream deps: none (self-contained fixture strings; awk only).
#
# Downstream consumers: CI (bin-sh-tests); DS-192 QA scenario 4.
#
# Failure modes: exits non-zero if any old-form/new-form pair disagrees on
#                a representative fixture.

set -uo pipefail

FAIL=0
note_fail() {
  echo "FAIL: $1" >&2
  FAIL=1
}

# assert_eq: compares old-form vs new-form output. Fails loudly (rather than
# silently passing) if BOTH sides are empty, unless the caller passes
# "allow-empty" as a 4th argument - a broken fixture (e.g. a renamed key the
# awk pattern no longer matches) produces old=[] new=[] and must not read as
# agreement. Every fixture in this file expects non-empty output (even the
# empty-input numstat case below prints "0" via `END {print s+0}`), so
# allow-empty is not currently used by any call site - it exists so a future
# genuinely-empty-on-both-sides fixture can opt in explicitly rather than
# this guard being loosened for everyone.
assert_eq() {
  local label="$1" old="$2" new="$3" mode="${4:-}"
  echo "$label: old=[$old] new=[$new]"
  if [ "$mode" != "allow-empty" ] && [ -z "$old" ] && [ -z "$new" ]; then
    note_fail "$label: both old-form and new-form output are empty - the fixture likely no longer matches the awk pattern (this assertion would pass vacuously otherwise)"
    return
  fi
  if [ "$old" != "$new" ]; then
    note_fail "$label: old-form and new-form output diverge"
  fi
}

echo "== developer_id: line (\$2 vs \$NF) =="
DEVELOPER_FIXTURE=$'developer_id: tyson-solara6\nsome_other_key: value\n'
old_developer="$(printf '%s' "$DEVELOPER_FIXTURE" | awk '/^developer_id:/{print $2}')"
new_developer="$(printf '%s' "$DEVELOPER_FIXTURE" | awk '/^developer_id:/{print $NF}')"
assert_eq "developer_id (simple two-field value)" "$old_developer" "$new_developer"

echo "== numstat sum fixture (\$2 vs -v idx=2 \$(idx), multiple rows) =="
NUMSTAT_FIXTURE=$'3\t1\tfile_a.md\n5\t2\tfile_b.md\n0\t0\tfile_c.md\n'
old_sum="$(printf '%s' "$NUMSTAT_FIXTURE" | awk '{s += $2} END {print s+0}')"
new_sum="$(printf '%s' "$NUMSTAT_FIXTURE" | awk -v idx=2 '{s += $(idx)} END {print s+0}')"
assert_eq "numstat sum (multi-row)" "$old_sum" "$new_sum"

echo "== numstat sum fixture, empty input (proves zero-emission, not silence) =="
old_sum_empty="$(printf '' | awk '{s += $2} END {print s+0}')"
new_sum_empty="$(printf '' | awk -v idx=2 '{s += $(idx)} END {print s+0}')"
assert_eq "numstat sum (empty input)" "$old_sum_empty" "$new_sum_empty"

echo "== ls-tree-shaped fixture (\$1 mode / \$3 sha, vs -v idx=1/-v idx=3 \$(idx)) =="
LSTREE_ENTRY="100644 blob a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2	content/commands/ds-implement-ticket.md"
old_mode="$(printf '%s' "$LSTREE_ENTRY" | awk '{print $1}')"
new_mode="$(printf '%s' "$LSTREE_ENTRY" | awk -v idx=1 '{print $(idx)}')"
assert_eq "ls-tree mode" "$old_mode" "$new_mode"

old_sha="$(printf '%s' "$LSTREE_ENTRY" | awk '{print $3}')"
new_sha="$(printf '%s' "$LSTREE_ENTRY" | awk -v idx=3 '{print $(idx)}')"
assert_eq "ls-tree sha" "$old_sha" "$new_sha"

echo "== kill-switch printf line (\$2/\$3 positions vs -v idx2=2 -v idx3=3 \$(idx2)/\$(idx3)) =="
KC_NUMSTAT_FIXTURE=$'3\t1\tfile_a.md\n5\t2\tfile_b.md\n0\t0\tfile_c.md\n'
old_printf="$(printf '%s' "$KC_NUMSTAT_FIXTURE" | awk -v kc_branch="feature/test" '$2 > 0 {printf "WARNING: [phase: knowledge-commit] %s has %s deleted line(s) vs origin/%s - this commit may revert content another session already merged. Review the PR diff before merging.\n", $3, $2, kc_branch}')"
new_printf="$(printf '%s' "$KC_NUMSTAT_FIXTURE" | awk -v kc_branch="feature/test" -v idx2=2 -v idx3=3 '$(idx2) > 0 {printf "WARNING: [phase: knowledge-commit] %s has %s deleted line(s) vs origin/%s - this commit may revert content another session already merged. Review the PR diff before merging.\n", $(idx3), $(idx2), kc_branch}')"
assert_eq "kill-switch printf (multi-row, some zero-deletion rows filtered)" "$old_printf" "$new_printf"

echo "== Results =="
if [ "$FAIL" = "0" ]; then
  echo "PASS: every DS-192 awk field-selector rewrite produces output byte-identical to its pre-rewrite bare-\$N form on representative fixtures"
  exit 0
fi

echo "FAIL: one or more old-form/new-form pairs diverged - see FAIL lines above"
exit 1
