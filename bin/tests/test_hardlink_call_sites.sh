#!/usr/bin/env bash
# Purpose: enforces AGENTS.md's derived hardlink instruction executably
#          instead of trusting prose. AGENTS.md's hardlink bullet had been
#          wrong three times in a row - each "fix" was a fresh hand-typed
#          count/list of which build scripts hardlink which content/
#          source, and each one went stale or was wrong on arrival (DS-90
#          Unit 5 review). The derived instruction that survived all three
#          rounds is: grep the target build.sh for `hardlink_from_content(`,
#          a bare `ln ` (no `-s`), or `os.link(` - any call against a
#          content/ source genuinely hardlinks it. This test makes that
#          claim self-checking: it derives SET A (which */build.sh scripts
#          call one of those three patterns against a content/ source) via
#          that exact grep, independently derives SET B (which adapter
#          directories actually carry a hardlinked - same-inode - copy of
#          two known content/ artifacts: project-scaffolding.yml and one
#          references/*.md sample file), and asserts the two derived sets
#          agree. A build script that gains or loses a hardlink call (or
#          whose hardlink call stops actually producing a hardlink) reddens
#          this test instead of silently falsifying AGENTS.md.
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

# Known destination path for project-scaffolding.yml, keyed by adapter dir
# (only adapters that handle it at all appear here; this list is read by
# the SAME NAME the derivation loop below computes independently, purely
# as a path-lookup convenience - it is not itself a source of truth for
# "does this adapter hardlink it", which set A and set B both derive
# fresh below).
scaffolding_dst_for() {
  case "$1" in
    .claude)   echo ".claude/skills/agentic-engineering/project-scaffolding.yml" ;;
    .cursor)   echo ".cursor/project-scaffolding.yml" ;;
    .gemini)   echo ".gemini/project-scaffolding.yml" ;;
    .omp)      echo ".omp/skills/agentic-engineering/project-scaffolding.yml" ;;
    .pi)       echo ".pi/skills/agentic-engineering/project-scaffolding.yml" ;;
    .kimi)     echo ".kimi/skills/agentic-engineering/project-scaffolding.yml" ;;
    .openclaw) echo ".openclaw/skills/agentic-engineering/project-scaffolding.yml" ;;
    .opencode) echo ".opencode/skills/agentic-engineering/project-scaffolding.yml" ;;
    *) echo "" ;;
  esac
}

refs_dst_for() {
  case "$1" in
    .cursor)  echo ".cursor/references/$REF_SAMPLE" ;;
    .copilot) echo ".copilot/references/$REF_SAMPLE" ;;
    .gemini)  echo ".gemini/references/$REF_SAMPLE" ;;
    *) echo "" ;;
  esac
}

same_inode() {
  # $1, $2: two paths. True (0) iff both exist and share the same inode
  # (i.e. are hardlinked to the same underlying file).
  [ -f "$1" ] && [ -f "$2" ] || return 1
  local ino1 ino2
  ino1=$(stat -f '%i' "$1" 2>/dev/null || stat -c '%i' "$1" 2>/dev/null)
  ino2=$(stat -f '%i' "$2" 2>/dev/null || stat -c '%i' "$2" 2>/dev/null)
  [ -n "$ino1" ] && [ "$ino1" = "$ino2" ]
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
  calls_hardlink=0
  # hardlink_from_content(...) CALL sites against $CONTENT (excludes the
  # function definition line, which has no opening quote after the name).
  if grep -qE 'hardlink_from_content "\$CONTENT' "$build_script" 2>/dev/null; then
    calls_hardlink=1
  fi
  # bare `ln "..." "..."` (no -s) - after `ln `, the next char is a quote
  # only when no flag is present, so this excludes `ln -s ...` by
  # construction.
  if grep -qE '(^|[[:space:]])ln "\$' "$build_script" 2>/dev/null; then
    calls_hardlink=1
  fi
  if grep -q 'os\.link(' "$build_script" 2>/dev/null; then
    calls_hardlink=1
  fi

  # --- Set B: does this adapter's on-disk output actually carry a
  #     hardlinked (same-inode) copy of a known content/ artifact? ---
  is_hardlinked=0
  scaffolding_dst="$(scaffolding_dst_for "$label")"
  if [ -n "$scaffolding_dst" ] && same_inode "$CONTENT_SCAFFOLDING" "$scaffolding_dst"; then
    is_hardlinked=1
  fi
  refs_dst="$(refs_dst_for "$label")"
  if [ -n "$refs_dst" ] && same_inode "$CONTENT_REF_SAMPLE" "$refs_dst"; then
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
