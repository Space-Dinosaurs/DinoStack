#!/usr/bin/env bash
# Purpose: Regression guard for scripts/skill-embed-sweep-harness.sh and its
#          companion scripts/lib/skill_embed_sweep.py (DS-45). Exercises:
#          exact byte-size construction, base-content preservation, the
#          real-SKILL.md write refusal on `candidate`, pad-line-count/hash
#          integrity on a full candidate, truncation detectability (the
#          tail canary goes missing on a truncated file), bash/zsh output
#          parity, and an install/restore round trip that verifies
#          byte-for-byte fidelity via cmp rather than trusting a rebuild.
#
# Public API: ./bin/tests/test_skill_embed_sweep_harness.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, cmp, mktemp, wc, grep, shasum, cp, ln,
#                chmod, tail, head, sed, awk, tr, cut, mkdir, ls, rm,
#                dirname, cat. zsh is required for the bash/zsh parity
#                assertion when running in CI (the assertion FAILs if zsh
#                is absent under CI=true); locally, without zsh on PATH it
#                is skipped (not failed). This set was derived by grepping
#                the file for every real external-command invocation
#                (excluding comment/string mentions - e.g. "basename" and
#                "test" appear only in prose here, describing scenario
#                names, and are never actually invoked as commands) and
#                diffing it against the declared list (DS-45 round-4 Major
#                3), not by adding a fixed name list from a single
#                finding.
#
#                DS-45 round-9 added a behavioral scenario that executes
#                scripts/check-skill-embed-budget.sh itself as a real
#                subprocess (never a modified copy) - that script's own
#                transitive dependencies are now this file's transitive
#                dependencies too: it reads content/sections/*.md and
#                content/rules/*.md (this scenario supplies its own stub
#                copies of both under the scratch fixture, not the real
#                ones) and invokes `git` via scripts/lib/budget-gate.sh
#                (also copied into the fixture unmodified), which degrades
#                gracefully to its SKIPPED variant against the fixture's
#                deliberately non-git directory rather than requiring a
#                real git repo. `git` is not separately required by this
#                file for that reason - the invoked script's own graceful
#                degradation covers its absence.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: harness script or python helper missing -> immediate FAIL.
#                Any scenario's observed output, exit code, or on-disk
#                state does not match the expected shape -> FAIL naming the
#                scenario and what was observed. DS-45's behavioral fixture
#                scenario additionally FAILs if
#                EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT cannot be read
#                out of the gate script, or if the invoked gate's run
#                against the 160,001 B fixture does not BOTH exit non-zero
#                AND print "ABOVE CEILING" in its output - a non-zero exit
#                alone is not sufficient, since a broken fixture build, a
#                missing scripts/lib/budget-gate.sh copy, or the gate
#                legitimately gaining a new embedded set this fixture does
#                not stub all also exit non-zero without ever having
#                exercised the CEILING comparison; the output-content
#                conjunct is what distinguishes a genuine ceiling
#                rejection from any of those unrelated failures.
#
# Test hygiene: never mutates any tracked file in the working tree,
#               including the real .claude/skills/dinostack/SKILL.md -
#               every fixture repo, "real" SKILL.md stand-in, and backup
#               dir lives under a mktemp -d directory removed on exit via
#               trap. Does not touch network. Runs correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS_SCRIPT="$REPO_DIR/scripts/skill-embed-sweep-harness.sh"
PY_HELPER="$REPO_DIR/scripts/lib/skill_embed_sweep.py"

if [[ ! -f "$HARNESS_SCRIPT" ]]; then
  echo "FAIL: $HARNESS_SCRIPT not found" >&2
  exit 1
fi

if [[ ! -f "$PY_HELPER" ]]; then
  echo "FAIL: $PY_HELPER not found" >&2
  exit 1
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

# --- Build a scratch fixture repo the harness can run against without
#     touching the real working tree: scripts/ (copies of the real harness
#     and python helper), and a fake "real" .claude/skills/dinostack/
#     SKILL.md with a YAML frontmatter block (so head-marker insertion
#     exercises the same frontmatter-aware path the real file uses).
FIXTURE="$TMP_ROOT/fixture"
mkdir -p "$FIXTURE/scripts/lib" "$FIXTURE/.claude/skills/dinostack" "$FIXTURE/.agentic"
cp "$HARNESS_SCRIPT" "$FIXTURE/scripts/skill-embed-sweep-harness.sh"
cp "$PY_HELPER" "$FIXTURE/scripts/lib/skill_embed_sweep.py"
chmod +x "$FIXTURE/scripts/skill-embed-sweep-harness.sh"

REAL_SKILL="$FIXTURE/.claude/skills/dinostack/SKILL.md"
cat > "$REAL_SKILL" <<'EOF'
---
name: "fixture-skill"
description: "stub"
---

# Fixture Skill Body

Some stub methodology content lives here.
EOF
BASE_BYTES="$(wc -c < "$REAL_SKILL" | tr -d '[:space:]')"
# A pristine copy of the real fixture SKILL.md, used by _assert_out_refused
# to reset $REAL_SKILL before every shape probe. Without this, a shape
# whose guard is mutated-broken and successfully bypasses earlier in the
# probe matrix leaves $REAL_SKILL padded, which changes its size and can
# make a LATER (still-correctly-refused) shape's candidate call fail for
# an unrelated reason (base-too-small for --target-bytes) - a false
# "refused" that proves nothing about that shape's own guard. Isolating
# each probe against a known-good starting file makes every shape's
# pass/fail depend only on that shape's own guard behavior.
PRISTINE_REAL_SKILL="$TMP_ROOT/pristine-real-skill.md"
cp "$REAL_SKILL" "$PRISTINE_REAL_SKILL"

_run_harness() {
  # Runs the fixture's own copy of the harness with the fixture as cwd, so
  # REPO_DIR / REAL_SKILL_FILE resolve inside the fixture, not the real repo.
  ( cd "$FIXTURE" && bash scripts/skill-embed-sweep-harness.sh "$@" )
}

_run_harness_zsh() {
  ( cd "$FIXTURE" && zsh scripts/skill-embed-sweep-harness.sh "$@" )
}

# --- Scenario 1: candidate produces exactly the requested byte size ---
# Mutation that would redden this: drop the "- tail_len" term from
# available_for_pad's computation in skill_embed_sweep.py (or any other
# arithmetic error in build_candidate) - the assembled file would then be
# larger or smaller than target_bytes, and the exact-equality check below
# would fail.
target1=$(( BASE_BYTES + 5000 ))
out1="$TMP_ROOT/candidate1.md"
c1_out="$(_run_harness candidate --target-bytes "$target1" --out "$out1" 2>&1)"
c1_rc=$?
if [[ $c1_rc -eq 0 ]]; then
  actual1="$(wc -c < "$out1" | tr -d '[:space:]')"
  if [[ "$actual1" == "$target1" ]]; then
    _pass "candidate produces a file of exactly the requested byte size"
  else
    _fail "candidate size mismatch: requested $target1, got $actual1"
  fi
else
  _fail "candidate exited $c1_rc unexpectedly: $c1_out"
fi

# --- Scenario 2: candidate preserves the base content verbatim ---
# Mutation that would redden this: corrupt _insert_head_marker's split/join
# insertion logic (e.g. off-by-one on insert_at) so a byte of the base
# content is dropped or duplicated - the known base marker string below
# would then either vanish or move relative to the frontmatter close, and
# a straight substring-count check catches either.
if grep -qF "Some stub methodology content lives here." "$out1"; then
  _pass "candidate preserves a known base-content string verbatim"
else
  _fail "candidate lost the known base-content string entirely"
fi
frontmatter_close_line="$(grep -n '^---$' "$out1" | sed -n '2p' | cut -d: -f1)"
head_marker_line="$(grep -n 'DS-45-SWEEP-HEAD' "$out1" | head -1 | cut -d: -f1)"
if [[ -n "$frontmatter_close_line" && -n "$head_marker_line" && \
      "$head_marker_line" -eq $(( frontmatter_close_line + 1 )) ]]; then
  _pass "head canary lands immediately after the frontmatter close, not before it"
else
  _fail "head canary is not positioned right after frontmatter close (frontmatter_close=$frontmatter_close_line head_marker=$head_marker_line)"
fi

# --- Scenario 3: candidate refuses to write to the real, tracked SKILL.md,
#     under every path shape a caller could supply, not just the one
#     literal absolute path (DS-45 round-2 Critical) ---
# Mutation that would redden ALL of these: delete the check-out-refusal
# call in cmd_candidate() - the fixture's "real" SKILL.md would then be
# silently overwritten with padded content and the exit code would be 0
# instead of 1, for every shape below. Mutation that reddens 3i (hardlink)
# specifically while leaving 3a-3h green: revert paths_refer_to_same_file()
# to plain os.path.realpath string equality (drop the os.stat/st_ino
# branch entirely, keep only a bare `return real_a == real_b`) - a
# hardlink has its own unrelated path string, so only inode comparison
# can catch it; verified by execution. Mutation that reddens 3g/3h
# (case-differing basename/directory) specifically: this needed BOTH the
# os.stat/st_ino branch removed from paths_refer_to_same_file() AND
# .casefold() removed from _tail_matches_skill_artifact_shape() at once -
# verified by execution that dropping only one of the two leaves 3g/3h
# green, because on this machine's case-insensitive-but-preserving
# filesystem (macOS/APFS) os.path.exists() and os.stat() themselves
# resolve a case-differing path to the SAME inode as the real file, so
# the stat branch alone (with no casefold logic at all) already catches
# the case-differing shapes here - the casefold fallback in
# paths_refer_to_same_file() is the defense specifically for a
# genuinely case-sensitive filesystem, or a target that does not yet
# exist under any case-folded resolution, neither of which this
# platform's default test run exercises for 3g/3h. Do not assume a
# claimed single-change mutation reddens a given shape without running
# it - a stat-level defense here backstops a string-level one silently.
_assert_out_refused() {
  local label="$1" out_path="$2"
  local before after out_txt rc
  # Reset $REAL_SKILL to a known-good state before every probe (see the
  # PRISTINE_REAL_SKILL comment above) - otherwise a bypass by an earlier
  # (deliberately mutated, in a mutation test) shape can leave a later
  # shape's own candidate call failing for an unrelated reason.
  cp "$PRISTINE_REAL_SKILL" "$REAL_SKILL"
  before="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
  out_txt="$(_run_harness candidate --target-bytes "$target1" --out "$out_path" 2>&1)"
  rc=$?
  after="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
  if [[ $rc -ne 0 && "$before" == "$after" ]]; then
    _pass "candidate refuses --out shape [$label] and leaves the real SKILL.md untouched"
  else
    _fail "candidate did NOT refuse --out shape [$label] (rc=$rc, hash changed: $([ "$before" != "$after" ] && echo yes || echo no)): $out_txt"
  fi
}

# Fixture artifacts for the symlink/hardlink shapes, kept under $TMP_ROOT
# so the top-level trap cleans them up.
mkdir -p "$TMP_ROOT/shape-fixtures"
SYMLINK_TO_REAL="$TMP_ROOT/shape-fixtures/alias-skill.md"
ln -s "$REAL_SKILL" "$SYMLINK_TO_REAL"
DIR_SYMLINK="$TMP_ROOT/shape-fixtures/claude-alias"
ln -s "$FIXTURE/.claude" "$DIR_SYMLINK"
HARDLINK_TO_REAL="$TMP_ROOT/shape-fixtures/hardlink-skill.md"
ln "$REAL_SKILL" "$HARDLINK_TO_REAL"

# 3a: relative path (resolved from the harness's own cwd, $FIXTURE)
_assert_out_refused "relative path" "./.claude/skills/dinostack/SKILL.md"
# 3b: relative path with '..' segments
_assert_out_refused "'..' segments" ".claude/skills/dinostack/../dinostack/SKILL.md"
# 3c: absolute path (the exact shape the original test covered)
_assert_out_refused "absolute path" "$REAL_SKILL"
# 3d: symlink whose target is the real file
_assert_out_refused "symlink to the real file" "$SYMLINK_TO_REAL"
# 3e: a directory-symlink component earlier in the path
_assert_out_refused "directory-symlink path component" "$DIR_SYMLINK/skills/dinostack/SKILL.md"
# 3f: trailing slash on the target
_assert_out_refused "trailing slash" "${REAL_SKILL}/"
# 3g: case-differing basename (the exact bypass the reviewer found)
_assert_out_refused "case-differing basename (skill.MD)" "$FIXTURE/.claude/skills/dinostack/skill.MD"
# 3h: case-differing directory component
_assert_out_refused "case-differing directory component (Skills/)" "$FIXTURE/.claude/Skills/dinostack/SKILL.md"
# 3i: a hardlink to the real file, reached via an unrelated path string -
# only an inode/stat comparison (not any path-string comparison, however
# case-folded) can detect this one.
_assert_out_refused "hardlink to the real file" "$HARDLINK_TO_REAL"

# --- Scenario 4: declared pad-line count and pad_block_sha256 are correct
#     on a full (untruncated) candidate ---
# Mutation that would redden this: change build_candidate() to hash the
# wrong byte range (e.g. hash the head+pad block instead of the pad block
# alone) - the recomputed hash below would then never match the declared
# one, on every run, since the fixture always finds a mismatch
# deterministically once the hashed range is wrong.
declared_count_raw="$(grep -oE 'declared_total_pad_lines=[0-9]+' "$out1" | cut -d= -f2)"
# Force base-10 interpretation via bash's 10#<n> arithmetic-expansion
# prefix rather than sed 's/^0*//': the sed form strips a zero-count
# field ("00000000") down to an empty string, producing a spurious
# mismatch against actual_count's "0" at near-minimum --target-bytes
# values (DS-45 round-2 Minor 4). 10#$declared_count_raw is correct for
# every declared value, including all-zero and non-zero-with-leading-
# zeros, without bash misreading a leading-zero literal as octal.
declared_count=$((10#${declared_count_raw}))
actual_count="$(grep -c 'DS-45-SWEEP-PAD' "$out1")"
declared_hash="$(grep -oE 'pad_block_sha256=[0-9a-f]+' "$out1" | cut -d= -f2)"
recomputed_hash="$(grep 'DS-45-SWEEP-PAD' "$out1" | shasum -a 256 | cut -d' ' -f1)"
# grep adds a trailing newline per matched line, matching how the pad block
# bytes were assembled (each _pad_line ends with \n), so this recomputation
# is byte-comparable to the hash the harness declared.
if [[ "$declared_count" == "$actual_count" ]]; then
  _pass "declared_total_pad_lines matches the actual PAD line count"
else
  _fail "pad line count mismatch: declared=$declared_count actual=$actual_count"
fi
if [[ "$declared_hash" == "$recomputed_hash" ]]; then
  _pass "pad_block_sha256 matches an independent recomputation of the pad block"
else
  _fail "pad_block_sha256 mismatch: declared=$declared_hash recomputed=$recomputed_hash"
fi

# --- Scenario 4b: declared_total_pad_lines parses correctly at the
#     minimum viable target size, where the true count is zero
#     (DS-45 round-2 Minor 4) ---
# Mutation that would redden this: revert declared_count's parse back to
# `sed 's/^0*//'` - a zero count is stored as "00000000" in the tail
# block, and stripping ALL leading zeros collapses that to an empty
# string, so `[[ "" == "0" ]]` is false even though both sides genuinely
# mean zero.
# The reported minimum is itself a function of --target-bytes (its digit
# count is embedded literally in the head marker line, e.g. "target_bytes=1"
# vs "target_bytes=389" differ in length), so find the fixed point
# iteratively: probe with the last reported minimum until a probe
# actually succeeds.
min_probe=1
out_minimal="$TMP_ROOT/candidate-minimal.md"
minimal_out=""
minimal_rc=1
min_viable=""
for _attempt in 1 2 3 4 5 6; do
  minimal_out="$(_run_harness candidate --target-bytes "$min_probe" --out "$out_minimal" 2>&1)"
  minimal_rc=$?
  if [[ $minimal_rc -eq 0 ]]; then
    min_viable="$min_probe"
    break
  fi
  reported_min="$(echo "$minimal_out" | grep -oE '[0-9]+ B = base\+head' | grep -oE '^[0-9]+')"
  if [[ -z "$reported_min" || "$reported_min" == "$min_probe" ]]; then
    break
  fi
  min_probe="$reported_min"
done
if [[ -n "$min_viable" ]]; then
  declared_count_minimal_raw="$(grep -oE 'declared_total_pad_lines=[0-9]+' "$out_minimal" | cut -d= -f2)"
  declared_count_minimal=$((10#${declared_count_minimal_raw}))
  actual_count_minimal="$(grep -c 'DS-45-SWEEP-PAD' "$out_minimal")"
  if [[ "$declared_count_minimal" == "0" && "$declared_count_minimal" == "$actual_count_minimal" ]]; then
    _pass "declared_total_pad_lines parses correctly as 0 at the minimum viable target size"
  else
    _fail "pad line count mismatch at minimum viable size: declared=$declared_count_minimal actual=$actual_count_minimal"
  fi
else
  _fail "could not converge on the minimum viable candidate size (last attempt: $minimal_out)"
fi

# --- Scenario 5a: the end-of-file marker is genuinely the FINAL line of an
#     untruncated candidate, not just present somewhere in it ---
# Mutation that would redden this: reorder build_candidate() so the tail
# block is assembled before the remainder filler (candidate = with_head +
# pad_block + tail_block + filler instead of ... + filler + tail_block) -
# the filler (inert 'x' bytes) would then become the file's actual last
# line instead of the marker, and this exact-last-line check catches that
# deterministically regardless of how large the filler happens to be
# (unlike a fixed-byte-count truncation test, whose sensitivity to this
# specific mutation depends on filler size at a given target size).
last_line="$(tail -1 "$out1")"
if [[ "$last_line" == "DS-45-SWEEP-END-OF-FILE -->" ]]; then
  _pass "the end-of-file marker is the literal final line of an untruncated candidate"
else
  _fail "final line is not the end-of-file marker: got [$last_line]"
fi

# --- Scenario 5b: a truncated candidate loses its end-of-file marker ---
# Demonstrates the detection property the tail canary exists for: cutting
# the last 200 B off a real candidate (at this fixture's target size, well
# past the filler and into the tail block) removes the marker. This is a
# behavioral demonstration built on 5a's structural guarantee above, not an
# independent mutation-provable unit by itself at every possible target
# size/filler-length combination - 5a is what pins the ordering invariant
# this scenario depends on.
truncated="$TMP_ROOT/truncated.md"
full_size="$(wc -c < "$out1" | tr -d '[:space:]')"
truncate_to=$(( full_size - 200 ))
head -c "$truncate_to" "$out1" > "$truncated"
if grep -q "DS-45-SWEEP-END-OF-FILE" "$truncated"; then
  _fail "truncated candidate still shows the end-of-file marker - truncation would go undetected"
else
  _pass "truncating the last 200 B removes the end-of-file marker (truncation is detectable)"
fi

# --- Scenario 6: bash/zsh output parity ---
if command -v zsh >/dev/null 2>&1; then
  out_bash="$TMP_ROOT/parity-bash.md"
  out_zsh="$TMP_ROOT/parity-zsh.md"
  bash_out="$(_run_harness candidate --target-bytes "$target1" --out "$out_bash" --sweep-id deadbeefcafe 2>&1)"
  bash_rc=$?
  zsh_out="$(_run_harness_zsh candidate --target-bytes "$target1" --out "$out_zsh" --sweep-id deadbeefcafe 2>&1)"
  zsh_rc=$?
  if [[ $bash_rc -eq 0 && $zsh_rc -eq 0 ]]; then
    _pass "candidate exits 0 under both bash and zsh"
  else
    _fail "candidate exit code differs across shells (bash=$bash_rc zsh=$zsh_rc)"
  fi
  if cmp -s "$out_bash" "$out_zsh"; then
    _pass "bash and zsh produce byte-identical candidates given a pinned --sweep-id"
  else
    _fail "bash and zsh candidates diverged with the same --sweep-id"
  fi
elif [[ -n "${CI:-}" ]]; then
  _fail "zsh absent on PATH in CI - parity assertion cannot be skipped here"
else
  echo "SKIP: zsh not found on PATH - skipping zsh parity assertion (bash-only coverage above still applies)"
fi

# --- Scenario 7: install/restore round trip preserves byte-for-byte
#     fidelity, verified via cmp rather than a rebuild ---
# Mutation that would redden this: have cmd_restore() cp from anywhere
# other than the exact --backup path (e.g. a stale variable), or drop the
# cmp verification inside cmd_restore() - the round-trip hash comparison
# below would then diverge from the pre-install original on a corrupted
# restore, and pass the mutant would slip a wrong file through today.
original_hash="$(cd "$FIXTURE" && shasum -a 256 .claude/skills/dinostack/SKILL.md | cut -d' ' -f1)"
backup_dir="$TMP_ROOT/backups"
install_out="$(_run_harness install --candidate "$out1" --backup-dir "$backup_dir" 2>&1)"
install_rc=$?
backup_path="$(echo "$install_out" | grep -E '^backup:' | awk '{print $2}')"
installed_hash="$(cd "$FIXTURE" && shasum -a 256 .claude/skills/dinostack/SKILL.md | cut -d' ' -f1)"
candidate_hash="$(shasum -a 256 "$out1" | cut -d' ' -f1)"
if [[ $install_rc -eq 0 && -n "$backup_path" && -f "$backup_path" && \
      "$installed_hash" == "$candidate_hash" ]]; then
  _pass "install copies the candidate over the real path and writes a readable backup"
else
  _fail "install did not behave as expected (rc=$install_rc backup_path=$backup_path): $install_out"
fi
restore_out="$(_run_harness restore --backup "$backup_path" 2>&1)"
restore_rc=$?
restored_hash="$(cd "$FIXTURE" && shasum -a 256 .claude/skills/dinostack/SKILL.md | cut -d' ' -f1)"
if [[ $restore_rc -eq 0 && "$restored_hash" == "$original_hash" ]]; then
  _pass "restore returns the real file to its exact pre-install byte content"
else
  _fail "restore did not reproduce the original file (rc=$restore_rc restored=$restored_hash original=$original_hash): $restore_out"
fi

# --- Scenario 8: candidate refuses --out matching the SKILL.md artifact
#     shape under a DIFFERENT checkout, not just this checkout's own real
#     file (DS-45 round-2 Minor 1) ---
# Mutation that would redden this: delete the
# _tail_matches_skill_artifact_shape() check (or its call site) from
# cmd_candidate()'s guard, leaving only the paths_refer_to_same_file()
# comparison against THIS checkout's REAL_SKILL_FILE - the other
# checkout's real SKILL.md is a different on-disk file entirely (not a
# symlink/hardlink/case-variant of this one), so only the shape check
# can refuse it.
OTHER_CHECKOUT="$TMP_ROOT/other-checkout"
mkdir -p "$OTHER_CHECKOUT/.claude/skills/dinostack"
OTHER_REAL_SKILL="$OTHER_CHECKOUT/.claude/skills/dinostack/SKILL.md"
printf '%s\n' "genuine content from a different checkout" > "$OTHER_REAL_SKILL"
other_before="$(shasum -a 256 "$OTHER_REAL_SKILL" | cut -d' ' -f1)"
other_out="$(_run_harness candidate --target-bytes "$target1" --out "$OTHER_REAL_SKILL" 2>&1)"
other_rc=$?
other_after="$(shasum -a 256 "$OTHER_REAL_SKILL" | cut -d' ' -f1)"
if [[ $other_rc -ne 0 && "$other_before" == "$other_after" ]]; then
  _pass "candidate refuses --out matching the SKILL.md shape under a different checkout"
else
  _fail "candidate did NOT refuse a different checkout's SKILL.md (rc=$other_rc, hash changed: $([ "$other_before" != "$other_after" ] && echo yes || echo no)): $other_out"
fi

# --- Scenario 9: a refused candidate invocation creates no directories
#     (DS-45 round-2 Minor 3) ---
# Mutation that would redden this: move `mkdir -p "$(dirname "${out}")"`
# back above the refusal check in cmd_candidate() - a refused invocation
# would then still create the (otherwise never-created) parent directory
# as a side effect.
NEVER_CREATED_DIR="$TMP_ROOT/never-created-by-a-refused-call"
refused_dir_out="$(_run_harness candidate --target-bytes "$target1" \
  --out "$NEVER_CREATED_DIR/.claude/skills/dinostack/SKILL.md" 2>&1)"
refused_dir_rc=$?
if [[ $refused_dir_rc -ne 0 && ! -d "$NEVER_CREATED_DIR" ]]; then
  _pass "a refused candidate invocation creates no directories"
else
  _fail "a refused candidate invocation still created a directory (rc=$refused_dir_rc, dir exists: $([ -d "$NEVER_CREATED_DIR" ] && echo yes || echo no)): $refused_dir_out"
fi

# --- Scenario 10: a trailing flag with no following value prints usage
#     instead of dying on an unbound variable (DS-45 round-2 Minor 5) ---
# Mutation that would redden this: revert any of the three `case` arms'
# `_require_flag_value` guards back to a bare `var="$2"; shift 2` - `$2`
# is then read under `set -u` with nothing left in "$@", and bash exits
# with "unbound variable" instead of the usage message.
trailing_candidate_out="$(_run_harness candidate --target-bytes "$target1" --out 2>&1)"
trailing_candidate_rc=$?
if [[ $trailing_candidate_rc -ne 0 && "$trailing_candidate_out" == *"requires a value"* \
      && "$trailing_candidate_out" != *"unbound variable"* ]]; then
  _pass "candidate: a trailing --out with no value prints usage, not an unbound-variable crash"
else
  _fail "candidate: trailing --out did not print the expected usage message (rc=$trailing_candidate_rc): $trailing_candidate_out"
fi
trailing_install_out="$(_run_harness install --candidate 2>&1)"
trailing_install_rc=$?
if [[ $trailing_install_rc -ne 0 && "$trailing_install_out" == *"requires a value"* \
      && "$trailing_install_out" != *"unbound variable"* ]]; then
  _pass "install: a trailing --candidate with no value prints usage, not an unbound-variable crash"
else
  _fail "install: trailing --candidate did not print the expected usage message (rc=$trailing_install_rc): $trailing_install_out"
fi
trailing_restore_out="$(_run_harness restore --backup 2>&1)"
trailing_restore_rc=$?
if [[ $trailing_restore_rc -ne 0 && "$trailing_restore_out" == *"requires a value"* \
      && "$trailing_restore_out" != *"unbound variable"* ]]; then
  _pass "restore: a trailing --backup with no value prints usage, not an unbound-variable crash"
else
  _fail "restore: trailing --backup did not print the expected usage message (rc=$trailing_restore_rc): $trailing_restore_out"
fi

# --- Scenario 11: install refuses to back up an already-padded real file
#     (DS-45 round-2 Major 2, install side) ---
# Mutation that would redden this: delete the CANARY_MARKER grep guard in
# cmd_install() - a padded real file would then be silently backed up
# (capturing padding as the "restore point") and overwritten again with a
# second candidate's content.
cp "$out1" "$REAL_SKILL"
padded_before="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
padded_backup_dir="$TMP_ROOT/backups-padded-install-refusal"
install_over_padded_out="$(_run_harness install --candidate "$out1" --backup-dir "$padded_backup_dir" 2>&1)"
install_over_padded_rc=$?
padded_after="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
backup_dir_empty=1
if [[ -d "$padded_backup_dir" ]] && [[ -n "$(ls -A "$padded_backup_dir" 2>/dev/null)" ]]; then
  backup_dir_empty=0
fi
if [[ $install_over_padded_rc -ne 0 && "$padded_before" == "$padded_after" && $backup_dir_empty -eq 1 ]]; then
  _pass "install refuses to back up an already-padded real file (no backup written, real file untouched)"
else
  _fail "install did NOT refuse an already-padded real file (rc=$install_over_padded_rc, hash changed: $([ "$padded_before" != "$padded_after" ] && echo yes || echo no), backup written: $([ $backup_dir_empty -eq 0 ] && echo yes || echo no)): $install_over_padded_out"
fi
# Restore the pristine fixture for subsequent scenarios.
cp "$PRISTINE_REAL_SKILL" "$REAL_SKILL"

# --- Scenario 12: restore refuses BEFORE touching the real file when the
#     backup it is given still carries a sweep canary (DS-45 round-2
#     Major 2, restore side; ordering fixed round-3 Major 1) ---
# Mutation that would redden this: delete the CANARY_MARKER grep guard
# that now runs on `${backup}` BEFORE the `cp` in cmd_restore() (or revert
# it to its round-2 position, checking `${REAL_SKILL_FILE}` AFTER the
# `cp`) - restoring from a backup that was itself padded content would
# then overwrite the real file with padding, either leaving that overwrite
# in place while reporting success (if the guard is deleted entirely) or
# reporting failure only after the real file was already destroyed (if
# the guard is merely reordered back to post-cp).
# Attempt to restore FROM a padded "backup" (out1 itself carries the
# canary, playing the role of a backup that was padded to begin with -
# exactly what Major 2 says a pre-fix `install` could have produced).
# $REAL_SKILL is the pristine fixture going in (restored after scenario
# 11 above) - capture its hash before the call so the assertion can prove
# the real file was never touched, not merely that rc was nonzero.
pristine_before_hash="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
padded_restore_out="$(_run_harness restore --backup "$out1" 2>&1)"
padded_restore_rc=$?
padded_restore_hash="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
out1_hash="$(shasum -a 256 "$out1" | cut -d' ' -f1)"
if [[ $padded_restore_rc -ne 0 && "$padded_restore_out" == *"DS-45 sweep canary"* \
      && "$padded_restore_hash" == "$pristine_before_hash" \
      && "$padded_restore_hash" != "$out1_hash" ]]; then
  _pass "restore refuses a padded backup before touching the real file (real file untouched)"
else
  _fail "restore did NOT refuse a padded backup harmlessly (rc=$padded_restore_rc, real file untouched: $([ "$padded_restore_hash" == "$pristine_before_hash" ] && echo yes || echo no), real file became the padded backup: $([ "$padded_restore_hash" == "$out1_hash" ] && echo yes || echo no)): $padded_restore_out"
fi
# Restore the pristine fixture for subsequent scenarios.
cp "$PRISTINE_REAL_SKILL" "$REAL_SKILL"

# --- Scenario 13: install aborts without overwriting when the backup
#     write fails to verify (a read-only backup directory forces the
#     failure the reviewer used to confirm this property) ---
# Mutation that would redden this: reorder cmd_install() to `cp` the
# candidate over the real file BEFORE writing/verifying the backup - the
# real file would then be overwritten even though the backup never
# succeeded.
readonly_backup_dir="$TMP_ROOT/readonly-backup-dir"
mkdir -p "$readonly_backup_dir"
chmod 555 "$readonly_backup_dir"
readonly_before="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
readonly_install_out="$(_run_harness install --candidate "$out1" --backup-dir "$readonly_backup_dir" 2>&1)"
readonly_install_rc=$?
readonly_after="$(shasum -a 256 "$REAL_SKILL" | cut -d' ' -f1)"
chmod 755 "$readonly_backup_dir"
if [[ $readonly_install_rc -ne 0 && "$readonly_before" == "$readonly_after" ]]; then
  _pass "install aborts without overwriting when the backup directory is not writable"
else
  _fail "install did NOT abort on an unwritable backup dir (rc=$readonly_install_rc, real file changed: $([ "$readonly_before" != "$readonly_after" ] && echo yes || echo no)): $readonly_install_out"
fi

# --- Scenario 13b: candidate refuses a padded resolved --base with a
#     message naming the padded base as the cause, instead of surfacing a
#     misleading minimum-viable-size error one step later (DS-45
#     round-3 Minor 4) ---
# Mutation that would redden this: delete the CANARY_MARKER grep guard on
# `${base}` in cmd_candidate() - building a candidate on top of a padded
# base would then either silently double-pad, or (at an equal
# --target-bytes to the padded base's own size) fail with "target_bytes
# is smaller than the minimum viable candidate size", pointing at the
# wrong cause.
padded_base="$TMP_ROOT/padded-base-fixture.md"
cp "$out1" "$padded_base"
padded_base_size="$(wc -c < "$padded_base" | tr -d ' ')"
padded_base_candidate_out="$(_run_harness candidate --target-bytes "$padded_base_size" \
  --out "$TMP_ROOT/never-written-from-padded-base.md" --base "$padded_base" 2>&1)"
padded_base_candidate_rc=$?
padded_base_out_exists=0
[[ -f "$TMP_ROOT/never-written-from-padded-base.md" ]] && padded_base_out_exists=1
if [[ $padded_base_candidate_rc -ne 0 && "$padded_base_candidate_out" == *"DS-45 sweep canary"* \
      && "$padded_base_candidate_out" != *"minimum viable candidate size"* \
      && $padded_base_out_exists -eq 0 ]]; then
  _pass "candidate refuses a padded --base, naming the padded base as the cause"
else
  _fail "candidate did NOT refuse a padded --base correctly (rc=$padded_base_candidate_rc, out written: $([ $padded_base_out_exists -eq 1 ] && echo yes || echo no)): $padded_base_candidate_out"
fi

# --- Scenario 14: install verifies its own write, not just the backup
#     (DS-45 round-4 Minor 4) ---
# Mutation that would redden this: delete the cmp-after-install-cp check
# added to cmd_install() - a partial/corrupted `cp` of the candidate onto
# the real file would then be reported as a success unconditionally, the
# same gap cmd_restore() already closed for its own write.
# A fake `cp` on PATH performs the real copy for every call EXCEPT the
# install write (candidate -> real file), which it deliberately corrupts
# by truncating the destination by one byte after copying - simulating a
# partial write without needing to fake disk-full or process-interruption
# conditions.
FAKE_CP_DIR="$TMP_ROOT/fake-cp-bin"
mkdir -p "$FAKE_CP_DIR"
REAL_CP_BIN="$(command -v cp)"
corrupt_candidate_src="$out1"
corrupt_install_backup_dir="$TMP_ROOT/backups-corrupt-install"
# Match on the SOURCE argument only ($1): the harness passes the literal
# --candidate value unresolved for the install write ("$1" == out1's exact
# string, set at test-script scope with no symlink resolution involved),
# whereas the destination argument the harness passes is computed via a
# cd+pwd inside the harness itself and could differ in string form from
# this test's own $REAL_SKILL on a symlinked tmpdir (e.g. macOS
# /var -> /private/var) - matching on the destination would be fragile.
cat > "$FAKE_CP_DIR/cp" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$1" == "$corrupt_candidate_src" ]]; then
  "$REAL_CP_BIN" "\$@"
  # Truncate the destination by one byte to simulate a partial write.
  filesize="\$(wc -c < "\$2")"
  head -c "\$((filesize - 1))" "\$2" > "\$2.tmp" && mv "\$2.tmp" "\$2"
else
  "$REAL_CP_BIN" "\$@"
fi
EOF
chmod +x "$FAKE_CP_DIR/cp"
corrupt_install_out="$(cd "$FIXTURE" && PATH="$FAKE_CP_DIR:$PATH" bash scripts/skill-embed-sweep-harness.sh install --candidate "$out1" --backup-dir "$corrupt_install_backup_dir" 2>&1)"
corrupt_install_rc=$?
if [[ $corrupt_install_rc -ne 0 && "$corrupt_install_out" == *"does NOT"*"verify byte-identical"* ]]; then
  _pass "install detects and reports a partial/corrupted write instead of reporting success"
else
  _fail "install did NOT detect a corrupted write (rc=$corrupt_install_rc): $corrupt_install_out"
fi
# Restore the pristine fixture for subsequent scenarios (a corrupted real
# file, or a backup left over from this scenario, must not leak forward).
cp "$PRISTINE_REAL_SKILL" "$REAL_SKILL"

# --- Scenario 15: runbook doc-content pins (DS-45 round-2 Major 1,
#     Major 3, Minor 2) - a plain prose file has no executable behavior to
#     mutation-test, so these pin the corrected wording against a silent
#     revert to the earlier, defective phrasing ---
RUNBOOK="$REPO_DIR/docs/skill-embed-injection-sweep.md"
CEILING_SCRIPT="$REPO_DIR/scripts/check-skill-embed-budget.sh"
if [[ ! -f "$RUNBOOK" ]]; then
  _fail "runbook not found: $RUNBOOK"
elif [[ ! -f "$CEILING_SCRIPT" ]]; then
  _fail "CEILING script not found: $CEILING_SCRIPT"
else
  # Major 1: Step 4's confirmation must observe the restored file BEFORE
  # anything regenerates it - the old ordering ran build-all.sh first,
  # which made the following git-status check vacuous. Pin: the git
  # status check line must appear, and it must not be preceded by a
  # 'build-all.sh &&' on the same line. Mutation that would redden this:
  # remove the git status line, or reintroduce 'build-all.sh && git
  # status --short' on one line ahead of it.
  if grep -q 'git status --short -- .claude/skills/dinostack/SKILL.md' "$RUNBOOK" \
     && ! grep -q 'build-all.sh && git status --short' "$RUNBOOK"; then
    _pass "runbook Step 4 no longer chains build-all.sh before the restore confirmation"
  else
    _fail "runbook Step 4's restore confirmation is missing, or still chains build-all.sh before it (the vacuous-check ordering)"
  fi

  # Major 3: the CEILING comment must no longer claim the build-size
  # snapshot is "unrelated" to the injection-confirmed figure. Round-5
  # Minor 1: this used to also require the exact phrase 'CEILING
  # (139,160 B) ends up' to be present - a Skeptic reworded it to
  # 'CEILING (139,160 B) therefore sits' without changing its meaning and
  # reddened the pin. A pin should fire when the false 'unrelated' framing
  # RETURNS, not when a correct sentence is reworded, so this is now
  # negative-only. Mutation that would redden this: reintroduce the
  # literal string '1.1x an unrelated build-size snapshot' anywhere in
  # the CEILING comment.
  if ! grep -q '1.1x an unrelated build-size snapshot' "$CEILING_SCRIPT"; then
    _pass "CEILING comment drops the false 'unrelated' framing"
  else
    _fail "CEILING comment still asserts the build-size snapshot is 'unrelated' to the injection-confirmed figure"
  fi
  # Mutation that would redden this: reintroduce the identical false
  # claim into AGENTS.md's copy of the CEILING provenance summary.
  if grep -qF '1.1x an unrelated 2026-08-07 build-size snapshot' "$REPO_DIR/AGENTS.md"; then
    _fail "AGENTS.md:24 still carries the false 'unrelated build-size snapshot' claim"
  else
    _pass "AGENTS.md no longer carries the false 'unrelated build-size snapshot' claim"
  fi

  # Minor 2: the canary scheme's disclosure must keep stating that this
  # scheme does not independently verify base-content completeness (a
  # mid-file elision of base content is undetectable by it) - checked as
  # two independent anchors rather than one exact phrase, so a legitimate
  # rewording of the connecting words between them does not redden this
  # (round-5 Minor 1: the earlier single-phrase form was exactly the
  # rewording-fragile shape a Skeptic demonstrated breaking elsewhere in
  # this scenario). Mutation that would redden this: delete the
  # disclosure sentence (or replace "does not independently verify" with
  # an unqualified completeness claim) from the runbook's canary-scheme
  # section.
  if grep -q 'does not' "$RUNBOOK" && grep -q 'independently verify' "$RUNBOOK"; then
    _pass "runbook's canary-scheme claim still discloses the mid-file-elision gap"
  else
    _fail "runbook's canary-scheme claim no longer discloses the mid-file-elision gap"
  fi

  # Round-4 Major 1: the runbook must not claim the 127,107 B figure's
  # provenance "was never recorded" - a gitignored planning doc records
  # it, so the correct framing is "not traceable through git history",
  # already stated by the CEILING comment this runbook points at.
  # Mutation that would redden this: reintroduce "was never recorded"
  # anywhere in the runbook.
  if grep -q "was never recorded" "$RUNBOOK"; then
    _fail "runbook still claims the 127,107 B figure's provenance 'was never recorded'"
  else
    _pass "runbook no longer claims the 127,107 B figure's provenance 'was never recorded'"
  fi

  # Round-4 Major 2: the runbook must not claim DS-146's 130,015 B figure
  # is "the only" prior injection observation on record - the 127,107 B
  # figure five lines above is also called an "empirically-confirmed
  # verbatim-injection point", so "the only" contradicts the runbook's
  # own text. Round-5 Major 2: the identical set-completeness claim
  # ("the only prior injection observation") also existed one file over,
  # in the harness script's own header, unguarded by any pin here - it
  # was fixed there in the same round this comment was extended. Both
  # files are now checked so this class cannot resurface unpinned in
  # either. Mutation that would redden this: reintroduce either phrase
  # into its respective file.
  if grep -q "The only prior injection observation on record" "$RUNBOOK"; then
    _fail "runbook still claims DS-146 is 'the only' prior injection observation on record"
  else
    _pass "runbook no longer claims DS-146 is 'the only' prior injection observation on record"
  fi
  if grep -q "the only prior injection observation" "$HARNESS_SCRIPT"; then
    _fail "harness script header still claims DS-146 is 'the only' prior injection observation on record"
  else
    _pass "harness script header no longer claims DS-146 is 'the only' prior injection observation on record"
  fi

  # Round-4 Minor 1 pin retired (round 5): it guarded the literal phrase
  # "own header and failure", which never appeared anywhere in either
  # script on this branch - the phrase this pin was meant to catch a
  # revert of was "this file's own failure message cites" (no "header"),
  # so the pin was dead weight that could never redden regardless of what
  # the CEILING comment said. Fixed in the same round by deleting the
  # false self-reference itself (round-5 Major 1) rather than restoring
  # a pin that never covered it. See the Major 1 fix in
  # scripts/check-skill-embed-budget.sh's CEILING comment.

  # DS-45: the ABOVE-CEILING message must cite the 2026-09-03 swept
  # result, and a real fixture one byte past the swept upper bound
  # (160,000 B) must be genuinely rejected by the live gate. See
  # docs/skill-embed-injection-sweep.md and AGENTS.md for the sweep
  # itself; the two checks below assert message content and gate
  # behavior separately, since they are different properties.
  above_ceiling_block="$(awk '/^  echo "check-skill-embed-budget\.sh: ABOVE CEILING\./{p=1} p{print; if (/^  exit 1$/) exit}' "$CEILING_SCRIPT")"
  # Message-content check: a single distinctive phrase spanning the
  # attribution (date, ticket, "swept") - "DS-45" and "swept" alone each
  # recur later in the same block in unrelated sentences ("the full
  # DS-45 provenance", "a new swept confirmation"), so pinning them
  # separately cannot discriminate a mutated attribution sentence.
  # Mutations that would redden this: (a) delete or reword the
  # attribution phrase even with the figure line left intact;
  # (b) change either pinned historical figure (145,000 B or 160,000 B).
  if [[ "$above_ceiling_block" == *"A 2026-09-03 swept measurement (DS-45) confirmed"* ]] \
     && [[ "$above_ceiling_block" == *"(145,000 B) as an intact injection point"* ]] \
     && [[ "$above_ceiling_block" == *"160,000 B"* ]]; then
    _pass "CEILING script's ABOVE-CEILING framing cites the swept figures and attribution as one distinctive phrase"
  else
    _fail "CEILING script's ABOVE-CEILING framing is missing the swept figures or the single-phrase attribution"
  fi

  # Behavioral check: build a scratch REPO_DIR under TMP_ROOT carrying the
  # REAL, unmodified check-skill-embed-budget.sh and budget-gate.sh (never
  # a copy edited for the test), plus the minimum content/sections and
  # content/rules stub files the gate's own embed-completeness check
  # requires (EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT, each with a
  # matching top-level heading embedded in the fixture SKILL.md) so the
  # run reaches the FLOOR/CEILING logic instead of failing earlier on an
  # unrelated check. The fixture SKILL.md is built at EXACTLY 160,001 B
  # (the gate's own `wc -c`, not a length estimate) and the gate is
  # invoked for real against it - never against the tracked, real
  # .claude/skills/dinostack/SKILL.md. Asserting on exit status alone was
  # found vacuous against three unrelated failure routes that also exit
  # non-zero (a broken fixture builder before SKILL.md is written; a
  # missing budget-gate.sh dependency; the gate legitimately gaining a
  # third embedded set this fixture does not stub) - each would report
  # PASS despite never having exercised the CEILING comparison at all.
  # Fixed the same way the corrupt-install scenario elsewhere in this
  # file already conjoins rc with output content: require BOTH non-zero
  # exit AND the "ABOVE CEILING" string in the gate's own output, so a
  # failure for any OTHER reason correctly reddens this check instead of
  # passing it. Mutation that would redden this: raise CEILING (in ANY
  # assignment shape - source-text spelling is irrelevant, since nothing
  # here reads the source) above 160,000, so a genuinely 160,001 B
  # artifact is accepted instead of rejected.
  CEILING_FIXTURE="$TMP_ROOT/ceiling-behavior"
  mkdir -p "$CEILING_FIXTURE/scripts/lib" "$CEILING_FIXTURE/.claude/skills/dinostack" \
    "$CEILING_FIXTURE/content/sections" "$CEILING_FIXTURE/content/rules"
  cp "$CEILING_SCRIPT" "$CEILING_FIXTURE/scripts/check-skill-embed-budget.sh"
  cp "$REPO_DIR/scripts/lib/budget-gate.sh" "$CEILING_FIXTURE/scripts/lib/budget-gate.sh"
  ceiling_fixture_section_count="$(grep -E '^EXPECTED_SECTION_COUNT=' "$CEILING_SCRIPT" | head -1 | cut -d= -f2)"
  ceiling_fixture_rules_count="$(grep -E '^EXPECTED_RULES_COUNT=' "$CEILING_SCRIPT" | head -1 | cut -d= -f2)"
  if [[ -z "$ceiling_fixture_section_count" || -z "$ceiling_fixture_rules_count" ]]; then
    _fail "could not read EXPECTED_SECTION_COUNT/EXPECTED_RULES_COUNT out of $CEILING_SCRIPT to build the behavioral fixture"
  else
    python3 -c "
import sys, os

fixture_dir = sys.argv[1]
skill_bytes = int(sys.argv[2])
section_count = int(sys.argv[3])
rules_count = int(sys.argv[4])

headings = []
for i in range(1, section_count + 1):
    heading = '## Section %d' % i
    headings.append(heading)
    path = os.path.join(fixture_dir, 'content', 'sections', '%02d-stub.md' % i)
    with open(path, 'w') as f:
        f.write(heading + '\n\nstub body.\n')
for i in range(1, rules_count + 1):
    heading = '## Rule %d' % i
    headings.append(heading)
    path = os.path.join(fixture_dir, 'content', 'rules', 'rule%d.md' % i)
    with open(path, 'w') as f:
        f.write(heading + '\n\nstub body.\n')

header_block = '\n'.join(headings) + '\n'
header_bytes = len(header_block.encode())
pad_len = skill_bytes - header_bytes
if pad_len < 0:
    sys.stderr.write('build fixture: skill_bytes too small for headings\n')
    sys.exit(1)

skill_path = os.path.join(fixture_dir, '.claude', 'skills', 'dinostack', 'SKILL.md')
with open(skill_path, 'w') as f:
    f.write(header_block)
    f.write('x' * pad_len)
" "$CEILING_FIXTURE" 160001 "$ceiling_fixture_section_count" "$ceiling_fixture_rules_count"
    ceiling_behavior_out="$(cd "$CEILING_FIXTURE" && bash scripts/check-skill-embed-budget.sh 2>&1)"
    ceiling_behavior_rc=$?
    if [[ $ceiling_behavior_rc -ne 0 ]] && [[ "$ceiling_behavior_out" == *"ABOVE CEILING"* ]]; then
      _pass "CEILING script rejects a real 160,001 B fixture (one byte past the swept upper bound) specifically for exceeding CEILING"
    else
      _fail "CEILING script did not reject a real 160,001 B fixture with an ABOVE CEILING failure (rc=$ceiling_behavior_rc): $ceiling_behavior_out"
    fi
  fi
  # Single distinctive phrase, not two separable bare-token greps (a
  # co-occurrence of '2026-09-03' and '160,000' from unrelated sentences
  # could otherwise satisfy this).
  if grep -qF '140,000 / 145,000 / 150,000 / 160,000 B' "$REPO_DIR/AGENTS.md"; then
    _pass "AGENTS.md cites the 2026-09-03 sweep result up to 160,000 B"
  else
    _fail "AGENTS.md is missing the 2026-09-03 sweep result"
  fi

  # Round-4 Minor 3: the CEILING comment must attribute the 126,509 B
  # baf0b011 measurement to the pre-rename agentic-engineering skill
  # directory, not dinostack, and must not claim the two `git log -S`
  # queries "return only" the introducing commit (both queries actually
  # return multiple/different commits - see the comment's own rewritten
  # text). Mutation that would redden this: replace
  # 'agentic-engineering/SKILL.md' with 'dinostack/SKILL.md', or
  # reintroduce 'return only the commits'.
  if grep -q 'agentic-engineering/SKILL.md' "$CEILING_SCRIPT"; then
    _pass "CEILING comment attributes the baf0b011 measurement to the pre-rename skill directory"
  else
    _fail "CEILING comment is missing the pre-rename agentic-engineering/SKILL.md attribution"
  fi
  if grep -q 'return only the commits' "$CEILING_SCRIPT"; then
    _fail "CEILING comment still claims the git log -S queries 'return only' the introducing commit"
  else
    _pass "CEILING comment no longer overclaims what the git log -S queries return"
  fi

  # Round-4 Major 3: the harness's and this test's own Upstream deps
  # manifests must list cp, dirname, and cat - all three are genuinely
  # invoked (cp is the write primitive at three call sites; dirname
  # resolves --out's and the backup dir's parent; cat backs the heredoc
  # usage message) and were missing from both manifests going into this
  # round. Mutation that would redden this: drop either tool entry from
  # the harness script's Upstream deps comment block.
  if grep -q 'dirname (resolving --out' "$HARNESS_SCRIPT" && grep -q 'cat (the heredoc' "$HARNESS_SCRIPT"; then
    _pass "harness script's Upstream deps manifest lists cp, dirname, and cat"
  else
    _fail "harness script's Upstream deps manifest is missing cp, dirname, or cat"
  fi
  # Scoped to the "# Upstream deps:" comment block only (from that header
  # line to the next blank comment line) - a whole-file grep here would be
  # vacuously self-satisfying, since this very assertion's own source line
  # contains the literal strings "cut, mkdir, ls, rm," and "dirname, cat"
  # as its grep patterns, and would match itself regardless of what the
  # manifest actually says.
  SELF_SCRIPT="$REPO_DIR/bin/tests/test_skill_embed_sweep_harness.sh"
  self_manifest_block="$(awk '/^# Upstream deps:/{p=1} p{print; if (/^#[[:space:]]*$/) exit}' "$SELF_SCRIPT")"
  # Mutation that would redden this: drop 'dirname' or 'cat' from this
  # file's own Upstream deps comment block.
  if [[ "$self_manifest_block" == *"cut, mkdir, ls, rm,"* && "$self_manifest_block" == *"dirname, cat."* ]]; then
    _pass "this test file's own Upstream deps manifest lists cut, mkdir, ls, rm, dirname, and cat"
  else
    _fail "this test file's own Upstream deps manifest is missing cut, mkdir, ls, rm, dirname, or cat"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
