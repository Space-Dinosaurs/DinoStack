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
# Upstream deps: bash, python3, cmp, mktemp, wc, grep. zsh is required for
#                the bash/zsh parity assertion when running in CI (the
#                assertion FAILs if zsh is absent under CI=true); locally,
#                without zsh on PATH it is skipped (not failed).
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: harness script or python helper missing -> immediate FAIL.
#                Any scenario's observed output, exit code, or on-disk
#                state does not match the expected shape -> FAIL naming the
#                scenario and what was observed.
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

# --- Scenario 3: candidate refuses to write to the real, tracked SKILL.md ---
# Mutation that would redden this: delete the out_real/real_skill_real
# equality guard in cmd_candidate() - the fixture's "real" SKILL.md would
# then be silently overwritten with padded content and the exit code would
# be 0 instead of 1.
before_hash="$(cd "$FIXTURE" && shasum -a 256 .claude/skills/dinostack/SKILL.md | cut -d' ' -f1)"
refuse_out="$(_run_harness candidate --target-bytes "$target1" --out "$REAL_SKILL" 2>&1)"
refuse_rc=$?
after_hash="$(cd "$FIXTURE" && shasum -a 256 .claude/skills/dinostack/SKILL.md | cut -d' ' -f1)"
if [[ $refuse_rc -ne 0 && "$before_hash" == "$after_hash" ]]; then
  _pass "candidate refuses --out pointed at the real SKILL.md and leaves it untouched"
else
  _fail "candidate did not refuse the real SKILL.md path (rc=$refuse_rc, hash changed: $([ "$before_hash" != "$after_hash" ] && echo yes || echo no)): $refuse_out"
fi

# --- Scenario 4: declared pad-line count and pad_block_sha256 are correct
#     on a full (untruncated) candidate ---
# Mutation that would redden this: change build_candidate() to hash the
# wrong byte range (e.g. hash the head+pad block instead of the pad block
# alone) - the recomputed hash below would then never match the declared
# one, on every run, since the fixture always finds a mismatch
# deterministically once the hashed range is wrong.
declared_count="$(grep -oE 'declared_total_pad_lines=[0-9]+' "$out1" | cut -d= -f2 | sed 's/^0*//')"
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

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
