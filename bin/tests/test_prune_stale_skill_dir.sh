#!/usr/bin/env bash
# Purpose: Regression coverage for the skill-rename self-heal mechanism
#          (agentic-engineering -> dinostack). Covers two things: (1) the
#          shared real-directory ownership predicate in
#          scripts/lib/prune-stale-skill-dir.sh, exercised directly against
#          fixtures (positive: all-symlinks removed; negative: one
#          unrecognized entry refuses deletion), and (2) a wiring assertion
#          per adapter per mechanism proving the prune call sites actually
#          exist in each install.sh - a mechanism that ships uncalled and
#          passes review is the default failure in this repo, not the
#          exception (pattern: check_prose_wiring() in
#          test_worktree_lifecycle_spec.sh).
# Public API: bash bin/tests/test_prune_stale_skill_dir.sh (or under zsh).
#             No args. Exits 1 on any failure.
# Upstream deps: scripts/lib/prune-stale-skill-dir.sh, the 7 skill-dir
#                install.sh scripts.
# Downstream consumers: bin/tests/ CI harness (test_*.sh glob).
# Failure modes: prints "FAIL: <reason>" per failing assertion; exits 1 if
#                FAIL count > 0.
# Side-effects: creates/removes a scratch directory under mktemp; does not
#               touch the real checkout or any real skill install location.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/prune-stale-skill-dir.sh"

FAIL=0
fail() {
  echo "FAIL: $1"
  FAIL=$((FAIL + 1))
}
pass() {
  echo "PASS: $1"
}

# ---------------------------------------------------------------------------
# Fixture setup
# ---------------------------------------------------------------------------

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

# A stand-in "methodology checkout" that deliberately does NOT contain
# "DinoStack" (or "agentic-engineering") anywhere in its path - the ownership
# predicate must key on $repo_dir, never on a name substring, or a checkout
# cloned under any other directory name (bootstrap.sh's AE_DEST_DIR supports
# arbitrary names; the pre-DinoStack convention was literally
# "agentic-engineering") would never be recognized as owned.
OWNED_REPO="$SCRATCH/checkout-owned-by-this-test"
mkdir -p "$OWNED_REPO/content/agents" "$OWNED_REPO/content/commands"

# An UNRELATED clone that DOES happen to contain a DinoStack-like name
# component - the name-based predicate this replaces would have wrongly
# treated this as owned; the $repo_dir-keyed predicate must not.
UNRELATED_REPO="$SCRATCH/my-DinoStack-unrelated-clone"
mkdir -p "$UNRELATED_REPO/content/agents"

[[ -f "$LIB" ]] || {
  fail "scripts/lib/prune-stale-skill-dir.sh not found at $LIB"
  echo "$FAIL failed"
  exit 1
}
# shellcheck source=/dev/null
. "$LIB"

# ---------------------------------------------------------------------------
# RED-then-GREEN: positive case - all-symlink real directory is removed
# when every symlink resolves inside $OWNED_REPO (the passed repo_dir),
# despite $OWNED_REPO's path containing no "DinoStack" substring at all.
# ---------------------------------------------------------------------------

POS_DIR="$SCRATCH/skills/agentic-engineering"
mkdir -p "$POS_DIR"
ln -s "$OWNED_REPO/content/agents" "$POS_DIR/agents"
ln -s "$OWNED_REPO/content/commands" "$POS_DIR/commands"

if ae_prune_stale_skill_dir "$POS_DIR" "$OWNED_REPO"; then
  if [[ -d "$POS_DIR" ]]; then
    fail "positive case: directory still exists after a claimed successful prune"
  else
    pass "positive case: all-symlink stale directory removed (owned by \$repo_dir, name has no DinoStack substring)"
  fi
else
  fail "positive case: ae_prune_stale_skill_dir returned non-zero on an all-owned directory"
fi

# ---------------------------------------------------------------------------
# Negative regression test: one unrecognized entry must refuse deletion
# ---------------------------------------------------------------------------

NEG_DIR="$SCRATCH/skills2/agentic-engineering"
mkdir -p "$NEG_DIR"
ln -s "$OWNED_REPO/content/agents" "$NEG_DIR/agents"
echo "operator content - not ours" > "$NEG_DIR/notes.txt"

if ae_prune_stale_skill_dir "$NEG_DIR" "$OWNED_REPO" SKILL.md METHODOLOGY.md; then
  fail "negative case: prune reported success despite an unrecognized entry"
else
  if [[ -d "$NEG_DIR" && -f "$NEG_DIR/notes.txt" ]]; then
    pass "negative case: unrecognized entry refused deletion, directory and file survive"
  else
    fail "negative case: directory or unrecognized file was removed despite refusal contract"
  fi
fi

# A directory with a real file NOT in the allowed list is also refused,
# even when every other entry is legitimate.
NEG_DIR2="$SCRATCH/skills3/agentic-engineering"
mkdir -p "$NEG_DIR2"
ln -s "$OWNED_REPO/content/agents" "$NEG_DIR2/agents"
echo "real" > "$NEG_DIR2/SKILL.md"
echo "unexpected" > "$NEG_DIR2/EXTRA.md"

if ae_prune_stale_skill_dir "$NEG_DIR2" "$OWNED_REPO" SKILL.md METHODOLOGY.md; then
  fail "negative case 2: prune reported success despite an unallowed real file"
else
  if [[ -f "$NEG_DIR2/EXTRA.md" ]]; then
    pass "negative case 2: unallowed real file refused deletion"
  else
    fail "negative case 2: unallowed real file was removed despite refusal contract"
  fi
fi

# ---------------------------------------------------------------------------
# MAJOR-2 regression: an unrelated clone whose path happens to contain a
# DinoStack-like name component must NOT be treated as owned just because
# the string matched - only realpath-inside-$repo_dir counts. Passing
# $OWNED_REPO as repo_dir while every symlink actually resolves inside
# $UNRELATED_REPO must refuse the prune.
# ---------------------------------------------------------------------------

NEG_DIR3="$SCRATCH/skills4/agentic-engineering"
mkdir -p "$NEG_DIR3"
ln -s "$UNRELATED_REPO/content/agents" "$NEG_DIR3/agents"

if ae_prune_stale_skill_dir "$NEG_DIR3" "$OWNED_REPO"; then
  fail "negative case 3: prune reported success on a symlink resolving into an unrelated -DinoStack-named clone"
else
  if [[ -d "$NEG_DIR3" ]]; then
    pass "negative case 3: symlink resolving outside \$repo_dir refused deletion despite a DinoStack-like name substring"
  else
    fail "negative case 3: directory was removed despite resolving outside \$repo_dir"
  fi
fi

# ---------------------------------------------------------------------------
# Wiring assertions: prove the prune call sites are actually invoked, not
# merely defined. Pattern mirrors check_prose_wiring() in
# test_worktree_lifecycle_spec.sh.
# ---------------------------------------------------------------------------

check_wiring() {
  local file="$1"
  local pattern="$2"
  local label="$3"
  if [[ ! -f "$REPO_DIR/$file" ]]; then
    fail "wiring: $file does not exist"
    return
  fi
  if grep -q "$pattern" "$REPO_DIR/$file"; then
    pass "wiring: $label invoked in $file"
  else
    fail "wiring: $label NOT invoked in $file (pattern: $pattern)"
  fi
}

# Real-directory adapters: shared-lib function CALL site (not merely its
# `command -v ae_prune_stale_skill_dir` existence guard, which stays present
# even when the invocation line beneath it is deleted). The pattern below
# only matches the actual call (with its dirname-derived path argument), so
# removing just the invocation - leaving the guard and surrounding block
# intact - reddens this assertion. Verified per-adapter: deleting only the
# invocation line is RED; restoring it is GREEN (see task notes).
check_wiring ".kimi/install.sh" 'ae_prune_stale_skill_dir "\$(dirname' "ae_prune_stale_skill_dir invocation"
check_wiring ".omp/install.sh"  'ae_prune_stale_skill_dir "\$(dirname' "ae_prune_stale_skill_dir invocation"
check_wiring ".pi/install.sh"   'ae_prune_stale_skill_dir "\$(dirname' "ae_prune_stale_skill_dir invocation"

# Symlink-destination adapters: the actual `rm` deletion line, not just the
# variable assignment or the surrounding `if` guard (both of which survive a
# mutation that deletes only the deletion action).
check_wiring ".claude/install.sh"   'rm -f "\$_ae_stale_skill_dst"' "stale core-skill symlink deletion"
check_wiring ".opencode/install.sh" 'rm -f "\$_ae_stale_skill_dst"' "stale core-skill symlink deletion"
check_wiring ".openclaw/install.sh" 'rm "\$_ae_stale_core_skill_dst"' "stale core-skill symlink deletion"
check_wiring ".codex/install.sh"    'rm "\$_ae_stale_skill_dst"' "stale core-skill symlink deletion"

echo ""
if [[ "$FAIL" -gt 0 ]]; then
  echo "$FAIL assertion(s) failed"
  exit 1
fi
echo "ALL PASS"
exit 0
