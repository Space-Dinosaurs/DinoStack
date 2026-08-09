#!/usr/bin/env bash
# Purpose: cross-checks AGENTS.md's derived hardlink instruction against
#          on-disk reality instead of trusting prose alone. AGENTS.md's
#          hardlink bullet had been wrong three times in a row - each "fix"
#          was a fresh hand-typed count/list of which build scripts
#          hardlink which content/ source, and each one went stale or was
#          wrong on arrival (DS-90 Unit 5 review). AGENTS.md's own
#          instruction is: grep the target build.sh for
#          `hardlink_from_content(`, a bare `ln ` (no `-s`), or
#          `os.link(` - any call against a content/ source genuinely
#          hardlinks it. This test does NOT re-run that exact instruction;
#          it derives SET A via a related but not textually identical grep
#          (excluding commented-out lines), and independently derives SET B
#          by searching each adapter directory - not a fixed destination
#          path - for a same-inode (genuinely hardlinked) copy of two known
#          content/ artifacts: project-scaffolding.yml and one
#          references/*.md sample file. It asserts the two derived sets
#          agree. Demonstrated (Unit 5 review): this catches a known
#          sample's hardlink silently degrading to a plain copy on an
#          already-built tree, and a hardcoded destination-path assumption
#          going stale. It does NOT independently verify that AGENTS.md's
#          own grep is the correct enumeration of call sites, and does NOT
#          reliably catch a build script simply gaining or losing a
#          hardlink call within a single CI run - CI always starts from a
#          fresh checkout (git does not preserve hardlinks), so a gained or
#          lost call typically moves both derived sides together and
#          passes. Do not read "reddens CI" broader than this.
#
# Public API: none (standalone script; `bash bin/tests/test_hardlink_call_sites.sh`).
#             Also directly executable under zsh.
#
# Upstream deps: scripts/build-all.sh (rebuilds every adapter so on-disk
#                inode state is real - a fresh git worktree/checkout never
#                preserves hardlinks, since git does not track them, so an
#                unbuilt tree would show nlink=1 everywhere and make this
#                assertion meaningless). Every `*/build.sh` at repo root.
#
# Downstream consumers: bin-sh-tests CI job (bin/tests/test_*.sh discovery).
#
# Failure modes: exits 1 if scripts/build-all.sh fails (cannot verify
#                inode reality on a broken build), or if the grep-derived
#                call-site set (A) disagrees with the inode-derived
#                hardlink set (B) for any adapter directory.
#
# Performance: dominated by scripts/build-all.sh (a handful of seconds);
#              the derivation/assertion itself is sub-second.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

FAIL=0
fail() { echo "FAIL: $1"; FAIL=1; }
pass() { echo "PASS: $1"; }

echo "Rebuilding adapters to establish real on-disk hardlink state..."
BUILD_LOG="$(mktemp)"
if ! bash scripts/build-all.sh >"$BUILD_LOG" 2>&1; then
  fail "scripts/build-all.sh exited non-zero - cannot verify hardlink reality on a broken build"
  cat "$BUILD_LOG"
  rm -f "$BUILD_LOG"
  exit 1
fi
rm -f "$BUILD_LOG"

REF_SAMPLE="regression-test-obligation.md"
CONTENT_SCAFFOLDING="content/project-scaffolding.yml"
CONTENT_REF_SAMPLE="content/references/$REF_SAMPLE"

inode_of() {
  stat -f '%i' "$1" 2>/dev/null || stat -c '%i' "$1" 2>/dev/null
}

# No hardcoded per-adapter destination table (Unit 5 review MINOR 1: a prior
# version hand-typed "skills/agentic-engineering/..." destination paths,
# which Unit 6 of this same rename program breaks by renaming that
# directory). Instead, search each adapter directory for ANY file sharing
# both the sample artifact's basename and its content/ source inode - this
# derives "is this adapter's copy of the sample hardlinked" from on-disk
# reality without assuming or encoding a destination path convention.
adapter_has_hardlinked_copy() {
  # $1: adapter dir (e.g. ".omp"). $2: content/ source path for the sample.
  local adapter_dir="$1" content_src="$2"
  local fname src_inode candidate cand_inode
  fname="$(basename "$content_src")"
  src_inode="$(inode_of "$content_src")"
  [ -n "$src_inode" ] || return 1
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    cand_inode="$(inode_of "$candidate")"
    if [ -n "$cand_inode" ] && [ "$cand_inode" = "$src_inode" ]; then
      return 0
    fi
  done < <(find "$adapter_dir" -type f -name "$fname" 2>/dev/null)
  return 1
}

MISMATCHES=""
ADAPTER_COUNT=0

# NOTE: adapter directories are all dotfiles (.claude, .cursor, ...), and a
# bare `*/build.sh` glob does NOT match dot-directories in bash (nor zsh) by
# default - an earlier revision of this loop used `./*/build.sh` and silently
# matched zero files, making the whole test vacuous (it always printed PASS
# because the loop body, including the mismatch check, never ran). `find` is
# used here specifically to avoid that trap.
while IFS= read -r build_script; do
  [ -f "$build_script" ] || continue
  adapter_dir="$(dirname "$build_script")"
  label="${adapter_dir#./}"

  # --- Set A: does this script call one of the three hardlink patterns
  #     against a content/ source? ---
  # Strip full-line comments first (MINOR: a commented-out `ln "$..."` or
  # similar was matching by literal text alone, with no distinction between
  # a comment and a real call site).
  code_only="$(grep -v '^[[:space:]]*#' "$build_script" 2>/dev/null)"
  calls_hardlink=0
  # hardlink_from_content(...) CALL sites against $CONTENT (excludes the
  # function definition line, which has no opening quote after the name).
  if echo "$code_only" | grep -qE 'hardlink_from_content "\$CONTENT' 2>/dev/null; then
    calls_hardlink=1
  fi
  # bare `ln "..." "..."` (no -s) - after `ln `, the next char is a quote
  # only when no flag is present, so this excludes `ln -s ...` by
  # construction.
  if echo "$code_only" | grep -qE '(^|[[:space:]])ln "\$' 2>/dev/null; then
    calls_hardlink=1
  fi
  if echo "$code_only" | grep -q 'os\.link(' 2>/dev/null; then
    calls_hardlink=1
  fi

  # --- Set B: does this adapter's on-disk output actually carry a
  #     hardlinked (same-inode) copy of a known content/ artifact,
  #     ANYWHERE under the adapter directory? Derived by filename+inode
  #     search rather than a hardcoded destination table (MINOR: a prior
  #     hand-typed table encoded "skills/agentic-engineering/..." paths
  #     that a later directory rename would silently break). ---
  is_hardlinked=0
  if adapter_has_hardlinked_copy "$adapter_dir" "$CONTENT_SCAFFOLDING"; then
    is_hardlinked=1
  fi
  if adapter_has_hardlinked_copy "$adapter_dir" "$CONTENT_REF_SAMPLE"; then
    is_hardlinked=1
  fi

  ADAPTER_COUNT=$((ADAPTER_COUNT + 1))
  if [ "$calls_hardlink" != "$is_hardlinked" ]; then
    MISMATCHES="${MISMATCHES}${label}: grep-derived-calls-hardlink=$calls_hardlink inode-derived-is-hardlinked=$is_hardlinked
"
  fi
done < <(find . -mindepth 2 -maxdepth 2 -name build.sh | sort)

if [ "$ADAPTER_COUNT" -eq 0 ]; then
  fail "find matched zero */build.sh files - discovery is broken, not clean"
fi

if [ -n "$MISMATCHES" ]; then
  fail "grep-derived hardlink call-site set disagrees with on-disk inode reality:
$MISMATCHES"
else
  pass "grep-derived hardlink call-site set matches on-disk inode reality for every */build.sh"
fi

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
echo "All tests passed."
