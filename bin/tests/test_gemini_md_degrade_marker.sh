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
#          Round 4 additionally fixes: the degrade branch treated ANY
#          symlink at the destination as foreign, including our own (from a
#          prior healthy install, or dangling after a repo move), refusing
#          to deliver the methodology body at all in either case - now it
#          replaces a symlink pointing at our own stub, or a dangling one,
#          with the degrade-path body, and only a symlink resolving
#          elsewhere is treated as foreign (scenarios 1c/1d below). Round 4
#          also closes a coverage gap in scenario 5's own header, which
#          claimed install.sh's first-line-EQUALS behaviour was covered
#          "implicitly via scenario 3's exact marker" - scenario 3 only
#          ever writes an exact marker, so it cannot distinguish EQUALS
#          from CONTAINS; scenarios 5b/5c below exercise install.sh
#          directly with a substring-marker file.
#
#          Scenarios (M4's explicit minimum list):
#            1. A foreign symlink at the GEMINI.md destination is preserved
#               on BOTH the degrade branch (M1) and the healthy branch.
#            1c/1d (round 4). A symlink at the destination that is OURS
#               (points at our stub, or is dangling) is replaced with the
#               degrade-path body rather than skipped, on the degrade
#               branch (M1 round-4 fix).
#            2. A foreign regular file (no marker) is preserved+backed up
#               with an accurate warning, on both branches.
#            3. Our own marked degrade artifact is replaced with neither a
#               backup nor a warning, on both branches (M2), and does not
#               accumulate backups across repeated degrade installs.
#            4. Uninstall removes our own marked artifact and leaves a
#               foreign file/symlink alone.
#            5. The marker match is first-line-EQUALS, not
#               first-line-CONTAINS (m5) - a line that merely contains the
#               marker string is treated as foreign, on uninstall.sh (5)
#               and on install.sh's degrade and healthy branches (5b/5c,
#               round 4 - the pre-round-4 header's claim that scenario 3
#               covered this "implicitly" was false, since scenario 3 never
#               writes a substring-only marker).
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
# Scenario 1c (round 4, M1 regression fix): a symlink at the destination
# pointing at OUR OWN stub (left over from a prior healthy install, now
# unusable because a later run forced degrade) is replaced with the
# degrade-path body, not skipped as foreign.
# Mutation that reddens this: reverting the degrade branch to treat every
# `-L "$GEMINI_MD_DST"` as foreign (round-3 shape).
# ---------------------------------------------------------------------------
H1C="$TMP_ROOT/h1c-degrade-own-symlink"
mkdir -p "$H1C/.gemini"
install_real "$H1C" > /dev/null 2>&1   # healthy install first: creates our own symlink
if [[ ! -L "$H1C/.gemini/GEMINI.md" ]]; then
  fail "scenario1c: setup failed - first install did not create the expected symlink"
else
  rm "$H1C/.gemini/skills/dinostack"   # remove our own skill symlink first...
  mkdir -p "$H1C/.gemini/skills/dinostack"   # ...then occupy the destination with a real dir -> forces degrade
  out1c="$(install_real "$H1C" 2>&1)"
  if [[ -L "$H1C/.gemini/GEMINI.md" ]]; then
    fail "scenario1c: degrade install left our own stale symlink in place instead of delivering the body (M1 round-4 regressed)"
  elif [[ ! -f "$H1C/.gemini/GEMINI.md" ]]; then
    fail "scenario1c: degrade install left no GEMINI.md at all"
  elif [[ "$(head -1 "$H1C/.gemini/GEMINI.md")" != "$MARKER" ]]; then
    fail "scenario1c: degrade install wrote GEMINI.md but not with our marker as first line"
  else
    pass "scenario1c: degrade install replaces our own stale symlink with the degrade-path body (M1 round-4)"
  fi
  if [[ "$out1c" == *"Replacing dinostack symlink at ~/.gemini/GEMINI.md with the degrade-path body"* ]]; then
    pass "scenario1c: degrade install prints an accurate replacing-our-own-symlink message"
  else
    fail "scenario1c: expected a 'Replacing dinostack symlink ... degrade-path body' message, got:"$'\n'"$out1c"
  fi
fi

# ---------------------------------------------------------------------------
# Scenario 1d (round 4, M1 regression fix): a DANGLING symlink at the
# destination (simulating a repo move - the target no longer exists) is
# replaced with the degrade-path body, not skipped as foreign.
# Mutation that reddens this: reverting the degrade branch's dangling-check
# (`[[ ! -e "$GEMINI_MD_DST" ]]`) to only the equals-our-stub check.
# ---------------------------------------------------------------------------
H1D="$TMP_ROOT/h1d-degrade-dangling-symlink"
mkdir -p "$H1D/.gemini/skills/dinostack"   # forces degrade
ln -s "$H1D/nonexistent-target.md" "$H1D/.gemini/GEMINI.md"

out1d="$(install_real "$H1D" 2>&1)"
if [[ -L "$H1D/.gemini/GEMINI.md" ]]; then
  fail "scenario1d: degrade install left a dangling symlink in place instead of delivering the body (M1 round-4 regressed)"
elif [[ ! -f "$H1D/.gemini/GEMINI.md" ]]; then
  fail "scenario1d: degrade install left no GEMINI.md at all"
elif [[ "$(head -1 "$H1D/.gemini/GEMINI.md")" != "$MARKER" ]]; then
  fail "scenario1d: degrade install wrote GEMINI.md but not with our marker as first line"
else
  pass "scenario1d: degrade install replaces a dangling symlink with the degrade-path body (M1 round-4)"
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
# (m5), on uninstall.sh. install.sh's own EQUALS behaviour is exercised
# separately by scenarios 5b/5c below (round 4) - scenario 3 alone cannot
# cover it, since it only ever writes an exact marker.
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
# Scenario 5b (round 4): install.sh's DEGRADE branch treats a first line
# merely CONTAINING the marker as foreign - backed up with a warning, not
# silently overwritten as if it were our own artifact.
# Mutation that reddens this: reverting install.sh's degrade-branch marker
# comparison from `[[ "$first_line" == "$GEMINI_MD_DEGRADE_MARKER" ]]` back
# to `head -1 ... | grep -qF "$GEMINI_MD_DEGRADE_MARKER"`.
# ---------------------------------------------------------------------------
H5B="$TMP_ROOT/h5b-install-degrade-substring-marker"
mkdir -p "$H5B/.gemini/skills/dinostack"   # forces degrade
printf 'this line merely contains %s in the middle, not exactly\nmy own content\n' "$MARKER" > "$H5B/.gemini/GEMINI.md"

out5b="$(install_real "$H5B" 2>&1)"
backup5b="$(ls -t "$H5B/.gemini/GEMINI.md.backup-"* 2>/dev/null | head -1 || true)"
if [[ -n "$backup5b" ]] && grep -qF "my own content" "$backup5b"; then
  pass "scenario5b: degrade install backs up a substring-marker file rather than silently overwriting it (m5, round 4)"
else
  fail "scenario5b: expected a backup file preserving the substring-marker file's content; found: '$backup5b'"
fi
if [[ "$(head -1 "$H5B/.gemini/GEMINI.md")" == "$MARKER" ]]; then
  pass "scenario5b: degrade install writes the exact marker as the new first line after backing up"
else
  fail "scenario5b: expected the exact marker as the new first line, got: '$(head -1 "$H5B/.gemini/GEMINI.md")'"
fi

# ---------------------------------------------------------------------------
# Scenario 5c (round 4): install.sh's HEALTHY branch treats a first line
# merely CONTAINING the marker as foreign - backed up with a warning, not
# silently replaced as if it were our own artifact.
# Mutation that reddens this: reverting install.sh's healthy-branch marker
# comparison from `[[ "$first_line" == "$GEMINI_MD_DEGRADE_MARKER" ]]` back
# to `head -1 ... | grep -qF "$GEMINI_MD_DEGRADE_MARKER"`.
# ---------------------------------------------------------------------------
H5C="$TMP_ROOT/h5c-install-healthy-substring-marker"
mkdir -p "$H5C/.gemini"
printf 'this line merely contains %s in the middle, not exactly\nmy own content\n' "$MARKER" > "$H5C/.gemini/GEMINI.md"

out5c="$(install_real "$H5C" 2>&1)"
backup5c="$(ls -t "$H5C/.gemini/GEMINI.md.backup-"* 2>/dev/null | head -1 || true)"
if [[ -n "$backup5c" ]] && grep -qF "my own content" "$backup5c"; then
  pass "scenario5c: healthy install backs up a substring-marker file rather than silently replacing it (m5, round 4)"
else
  fail "scenario5c: expected a backup file preserving the substring-marker file's content; found: '$backup5c'"
fi
if [[ -L "$H5C/.gemini/GEMINI.md" ]]; then
  pass "scenario5c: healthy install replaces the substring-marker file with our symlink after backing it up"
else
  fail "scenario5c: GEMINI.md destination is not a symlink after the healthy install"
fi

# ---------------------------------------------------------------------------
# Static check (m1 regression): the pre-commit hook's `git add` invocation
# stages every .gemini/ generated artifact path listed below. Scoped to the
# git-add block itself (not the whole file), so a path mentioned elsewhere
# in hooks/pre-commit (e.g. in a comment) cannot pass this check by
# accident. Mutation that reddens this: dropping any one of the listed
# paths from hooks/pre-commit's git add block.
# ---------------------------------------------------------------------------
PRECOMMIT="$REPO_DIR/hooks/pre-commit"
GIT_ADD_BLOCK="$(awk '/^  git add \\$/{f=1; print; next} f{print; if ($0 !~ /\\$/) exit}' "$PRECOMMIT")"
for p in \
  '.gemini/GEMINI.md' \
  '.gemini/skills/dinostack/SKILL.md' \
  '.gemini/references/' \
  '.gemini/commands/' \
  '.gemini/agents/'
do
  if grep -qF "$p" <<<"$GIT_ADD_BLOCK"; then
    pass "static: hooks/pre-commit's git add block stages $p"
  else
    fail "static: hooks/pre-commit's git add block does not reference $p"
  fi
done

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
