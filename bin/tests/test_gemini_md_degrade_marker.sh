#!/usr/bin/env bash
# Purpose: Regression suite for the GEMINI_MD_DEGRADE_MARKER mechanism in
#          .gemini/install.sh and .gemini/uninstall.sh (DS-184 round 3,
#          M1-M4). Round 2 shipped the marker (distinguishing our own
#          degrade-path-generated ~/.gemini/GEMINI.md from genuine user
#          data) but left two live bugs undetected by any test: the
#          degrade branch unconditionally `rm`s a symlink at the
#          destination even when it points at something the user owns
#          (M1), and the healthy branch never consulted the marker at all,
#          so replacing our own prior degrade artifact printed a false
#          "already exists ... NOT a symlink" warning and took an
#          unnecessary backup (M2). Both were only found by running the
#          REAL installer against a real, unfaked $HOME - an earlier
#          extracted-block harness missed them entirely. Every scenario
#          below therefore runs the real .gemini/install.sh /
#          .gemini/uninstall.sh via `HOME=<scratch> bash ...`, never an
#          extracted snippet.
#
#          Scenarios (M4's explicit minimum list):
#            1. A foreign symlink at the GEMINI.md destination is preserved
#               on BOTH the degrade branch (M1) and the healthy branch.
#            2. A foreign regular file (no marker) is preserved+backed up
#               with an accurate warning, on both branches.
#            3. Our own marked degrade artifact is replaced with neither a
#               backup nor a warning, on both branches (M2), and does not
#               accumulate backups across repeated degrade installs.
#            4. Uninstall removes our own marked artifact and leaves a
#               foreign file/symlink alone.
#            5. The marker match is first-line-EQUALS, not
#               first-line-CONTAINS (m5) - a line that merely contains the
#               marker string is treated as foreign, on both install.sh
#               and uninstall.sh.
#
#          Each scenario prints, at the end, the exact mutation that would
#          redden it (per the DS-184 review's mutation-per-branch
#          requirement) - see the comments beside each assertion group.
#
# Public API: ./bin/tests/test_gemini_md_degrade_marker.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp, python3 (transitively, via install.sh's
#                own JSON config writes).
#
# Downstream consumers: developer running locally before commit; CI
#   (bin-sh-tests auto-discovers bin/tests/test_*.sh).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. A temporary fake HOME is used per scenario; the
#                real ~/.gemini is never touched. install.sh/uninstall.sh
#                run against the REAL checkout (REPO_DIR unfaked) - only
#                $HOME is sandboxed, so the pre-commit hook guard is used
#                the same way test_gemini_skill_auto_load_hook.sh uses it.
#
# Performance: ~30-60s wall time (multiple real install.sh/uninstall.sh
#              invocations, each running .gemini/build.sh).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

PASS=0
FAIL=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }

TMP_ROOT="$(mktemp -d)"
cleanup() {
  precommit_hook_guard_restore
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

precommit_hook_guard_save "$REPO_DIR"

install_real() {
  # $1 = HOME dir; stdout/stderr captured by caller
  HOME="$1" bash "$REPO_DIR/.gemini/install.sh" --mode=opt-out --profile=default < /dev/null
}

uninstall_real() {
  # $1 = HOME dir
  HOME="$1" bash "$REPO_DIR/.gemini/uninstall.sh" < /dev/null
}

MARKER='<!-- dinostack:gemini-degrade-generated -->'

# ---------------------------------------------------------------------------
# Scenario 1a: degrade-path install, foreign symlink at destination (M1)
# Mutation that reddens this: reverting install.sh's degrade branch to
# `if [[ -L "$GEMINI_MD_DST" ]]; then rm "$GEMINI_MD_DST"; ...`
# ---------------------------------------------------------------------------
H1="$TMP_ROOT/h1-degrade-foreign-symlink"
mkdir -p "$H1/.gemini/skills/dinostack"   # real dir blocks the skill link -> forces degrade
echo "mine" > "$H1/mine.md"
ln -s "$H1/mine.md" "$H1/.gemini/GEMINI.md"

out1="$(install_real "$H1" 2>&1)"
rc1=$?

if [[ $rc1 -ne 0 ]]; then
  fail "scenario1a: install.sh exited $rc1 (output below)"
  echo "$out1" >&2
elif [[ ! -L "$H1/.gemini/GEMINI.md" ]]; then
  fail "scenario1a: foreign symlink at GEMINI.md was replaced with a real file (M1 regressed)"
elif [[ "$(readlink "$H1/.gemini/GEMINI.md")" != "$H1/mine.md" ]]; then
  fail "scenario1a: foreign symlink target changed unexpectedly: $(readlink "$H1/.gemini/GEMINI.md")"
else
  pass "scenario1a: degrade-path install preserves a foreign symlink at ~/.gemini/GEMINI.md (M1)"
fi

if [[ "$out1" == *"symlink points elsewhere"*"skipping degrade-path write"* ]]; then
  pass "scenario1a: degrade-path install prints a skip message naming the foreign target"
else
  fail "scenario1a: expected a 'symlink points elsewhere ... skipping degrade-path write' message, got:"$'\n'"$out1"
fi

# ---------------------------------------------------------------------------
# Scenario 1b: healthy-path install, foreign symlink at destination
# (pre-existing behaviour, asserted here for parity with 1a)
# ---------------------------------------------------------------------------
H1B="$TMP_ROOT/h1b-healthy-foreign-symlink"
mkdir -p "$H1B/.gemini"
echo "mine" > "$H1B/mine.md"
ln -s "$H1B/mine.md" "$H1B/.gemini/GEMINI.md"

out1b="$(install_real "$H1B" 2>&1)"
if [[ -L "$H1B/.gemini/GEMINI.md" ]] && [[ "$(readlink "$H1B/.gemini/GEMINI.md")" == "$H1B/mine.md" ]]; then
  pass "scenario1b: healthy-path install preserves a foreign symlink at ~/.gemini/GEMINI.md"
else
  fail "scenario1b: healthy-path install did not preserve the foreign symlink"
fi

# ---------------------------------------------------------------------------
# Scenario 2: foreign regular file (no marker) is backed up with an
# accurate warning, on the healthy branch.
# Mutation that reddens this: deleting the backup/warning block entirely,
# or making it fire on OUR OWN marked artifact too (which scenario 3 below
# separately catches).
# ---------------------------------------------------------------------------
H2="$TMP_ROOT/h2-foreign-regular-file"
mkdir -p "$H2/.gemini"
printf 'my own personal gemini notes\nnot generated by dinostack\n' > "$H2/.gemini/GEMINI.md"

out2="$(install_real "$H2" 2>&1)"
backup2="$(ls -t "$H2/.gemini/GEMINI.md.backup-"* 2>/dev/null | head -1 || true)"

if [[ -n "$backup2" ]] && grep -qF "not generated by dinostack" "$backup2"; then
  pass "scenario2: foreign regular GEMINI.md is backed up with its original content intact"
else
  fail "scenario2: expected a backup file containing the foreign content; found: '$backup2'"
fi

if [[ "$out2" == *"WARNING: ~/.gemini/GEMINI.md already exists and is NOT a symlink"* ]]; then
  pass "scenario2: foreign regular GEMINI.md triggers the loud backup warning"
else
  fail "scenario2: expected the loud backup warning, got:"$'\n'"$out2"
fi

if [[ -L "$H2/.gemini/GEMINI.md" ]]; then
  pass "scenario2: GEMINI.md destination is now our symlink after backing up the foreign file"
else
  fail "scenario2: GEMINI.md destination is not a symlink after install"
fi

# ---------------------------------------------------------------------------
# Scenario 3: our own marked degrade artifact is replaced with no backup
# and no warning, on BOTH branches (M2), and does not accumulate backups
# across repeated degrade installs.
# Mutation that reddens this: removing the marker check from either branch
# (reverting to the pre-fix "always warn+backup on any real file" shape).
# ---------------------------------------------------------------------------
H3="$TMP_ROOT/h3-own-marked-artifact"
mkdir -p "$H3/.gemini/skills/dinostack"   # forces degrade for the first install

install_real "$H3" > /dev/null 2>&1
first_line3="$(head -1 "$H3/.gemini/GEMINI.md" 2>/dev/null || true)"
if [[ "$first_line3" == "$MARKER" ]]; then
  pass "scenario3: first degrade install writes the marker as the literal first line"
else
  fail "scenario3: expected first line to equal the marker exactly, got: '$first_line3'"
fi

# Second degrade install (still blocked skill link) - marker recognized,
# overwritten in place, no backup accumulation.
out3b="$(install_real "$H3" 2>&1)"
backups3="$(ls "$H3/.gemini/GEMINI.md.backup-"* 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$backups3" == "0" ]]; then
  pass "scenario3: repeated degrade installs onto our own marked artifact produce zero backups"
else
  fail "scenario3: expected zero backups after a second degrade install, found $backups3"
fi
if [[ "$out3b" == *"Overwriting prior dinostack degrade-path GEMINI.md (no backup"* ]]; then
  pass "scenario3: second degrade install prints the no-backup overwrite message"
else
  fail "scenario3: expected the no-backup overwrite message on the second degrade install, got:"$'\n'"$out3b"
fi

# Now unblock the skill link and install again: healthy branch must
# recognize the marker, replace with the symlink, no backup, no warning.
rmdir "$H3/.gemini/skills/dinostack"
out3c="$(install_real "$H3" 2>&1)"
backups3c="$(ls "$H3/.gemini/GEMINI.md.backup-"* 2>/dev/null | wc -l | tr -d ' ')"

if [[ "$out3c" == *"WARNING: ~/.gemini/GEMINI.md already exists and is NOT a symlink"* ]]; then
  fail "scenario3: healthy install falsely warned about our own marked artifact (M2 regressed)"
else
  pass "scenario3: healthy install replacing our own marked artifact prints no false warning (M2)"
fi

if [[ "$backups3c" == "0" ]]; then
  pass "scenario3: healthy install replacing our own marked artifact takes no backup"
else
  fail "scenario3: expected zero backups when healthy-replacing our own marked artifact, found $backups3c"
fi

if [[ -L "$H3/.gemini/GEMINI.md" ]]; then
  pass "scenario3: GEMINI.md destination is a symlink after the healthy install replaces our artifact"
else
  fail "scenario3: GEMINI.md destination is not a symlink after the healthy install"
fi

# ---------------------------------------------------------------------------
# Scenario 4: uninstall removes our own marked artifact and leaves a
# foreign file/symlink alone.
# Mutation that reddens this: reverting uninstall.sh's marker check to
# "always leave any real file alone" (pre-M2/M3 shape), or to
# "always delete any real file" (an over-correction).
# ---------------------------------------------------------------------------
H4A="$TMP_ROOT/h4a-uninstall-removes-ours"
mkdir -p "$H4A/.gemini/skills/dinostack"
install_real "$H4A" > /dev/null 2>&1
out4a="$(uninstall_real "$H4A" 2>&1)"
if [[ ! -e "$H4A/.gemini/GEMINI.md" ]] && [[ "$out4a" == *"dinostack degrade-path artifact) removed"* ]]; then
  pass "scenario4a: uninstall removes our own marked degrade-path artifact"
else
  fail "scenario4a: expected our marked artifact removed with an accurate message, got:"$'\n'"$out4a"
fi

H4B="$TMP_ROOT/h4b-uninstall-preserves-foreign"
mkdir -p "$H4B/.gemini"
printf 'a genuinely user-authored file, no marker here\n' > "$H4B/.gemini/GEMINI.md"
out4b="$(uninstall_real "$H4B" 2>&1)"
if [[ -e "$H4B/.gemini/GEMINI.md" ]] && grep -qF "a genuinely user-authored file" "$H4B/.gemini/GEMINI.md"; then
  pass "scenario4b: uninstall leaves a genuinely user-authored GEMINI.md untouched"
else
  fail "scenario4b: uninstall modified or removed a genuinely user-authored GEMINI.md"
fi

# ---------------------------------------------------------------------------
# Scenario 5: marker match is first-line-EQUALS, not first-line-CONTAINS
# (m5), on both install.sh (implicit via scenario 3's exact marker) and
# uninstall.sh (explicit here).
# Mutation that reddens this: reverting either script's comparison from
# `[[ "$first_line" == "$MARKER" ]]` back to
# `head -1 ... | grep -qF "$MARKER"`.
# ---------------------------------------------------------------------------
H5="$TMP_ROOT/h5-marker-substring-not-equal"
mkdir -p "$H5/.gemini"
printf 'this line merely contains %s in the middle, not exactly\nother content\n' "$MARKER" > "$H5/.gemini/GEMINI.md"

out5="$(uninstall_real "$H5" 2>&1)"
if [[ -e "$H5/.gemini/GEMINI.md" ]] && [[ "$out5" == *"~/.gemini/GEMINI.md (real file - not removing)"* ]]; then
  pass "scenario5: a first line merely CONTAINING the marker is treated as foreign, not deleted (m5)"
else
  fail "scenario5: expected the substring-marker file preserved and reported as a real file, got:"$'\n'"$out5"
fi

# ---------------------------------------------------------------------------
# Static check (m1 regression): the pre-commit hook's git add invocation
# stages all four .gemini/ generated artifact paths. Mutation that reddens
# this: dropping any one of the four paths from hooks/pre-commit's git add
# block.
# ---------------------------------------------------------------------------
PRECOMMIT="$REPO_DIR/hooks/pre-commit"
for p in \
  '.gemini/GEMINI.md' \
  '.gemini/skills/dinostack/SKILL.md' \
  '.gemini/references/' \
  '.gemini/commands/' \
  '.gemini/agents/'
do
  if grep -qF "$p" "$PRECOMMIT"; then
    pass "static: hooks/pre-commit stages $p"
  else
    fail "static: hooks/pre-commit does not reference $p in its git add block"
  fi
done

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
