#!/usr/bin/env bash
# Purpose: Runnable AUTHORED/DERIVED provenance discriminator for a single
#          repo-relative path (DS-182 Major 3). Exists because DS-183/184/
#          185/186 (budget-gate axis assignment: a hard per-PR delta limit
#          is meaningful only for a hand-authored target, never for a
#          generated one - see scripts/lib/budget-gate.sh's own header
#          comment) each defer to "classify the target as AUTHORED or
#          DERIVED" without re-deriving how, so the classification needs
#          to be a runnable procedure, not a one-off judgment call made
#          fresh in every gate's own review.
#
#          Implements four discriminator rules, checked in this order,
#          first match wins (tie-break: ANY rule finding a generator
#          write to the target means DERIVED, full stop - there is no
#          competing "AUTHORED" rule to out-vote it):
#            D1 - CI regenerate-then-assert-clean pairs: a workflow step
#                 asserting `git diff --exit-code [-- <pathspec>]` after
#                 an earlier generator step in the same job. A pathspec
#                 token that is, or is a directory-prefix of, the target
#                 -> DERIVED. A BARE `git diff --exit-code` (no `--
#                 <pathspec>`, i.e. a whole-tree assertion) cannot alone
#                 prove the target is covered - deferred to D4.
#            D2 - CI-authored commits: a workflow step running `git add
#                 <paths>` in the same file as a later `git commit` step -
#                 any added path that is, or is a directory-prefix of, the
#                 target -> DERIVED.
#            D3 - manifest-declared writes: `git grep -n "writes " --
#                 'scripts/*' 'bin/*' '*/build.sh'` - any matched line
#                 whose text contains the target path verbatim -> DERIVED.
#            D4 - empirical closure: only invoked when D1 found a
#                 whole-tree (no-pathspec) `git diff --exit-code` assertion
#                 and no rule above matched. Extracts the `run:` step
#                 command(s) preceding the diff assertion within the same
#                 job, executes them in a disposable scratch clone (never
#                 the real working tree), and checks whether the target
#                 path actually changed. Changed -> DERIVED. Unchanged (or
#                 the job/generator cannot be resolved) -> falls through
#                 to the AUTHORED default.
#          A path matching no rule is AUTHORED.
#
# Public API: bash scripts/gate-provenance.sh <repo-relative-path>
#             Prints one line: "AUTHORED: <path>" or "DERIVED: <path>
#             (<rule> - <detail>)" to stdout. Exits 0 on either outcome;
#             exits 2 on a usage error (wrong arg count) or when
#             <repo-relative-path> is not given relative to the repo root.
#
# Upstream deps: git (all four rules shell out to it; D4 additionally
#                needs `git clone` and `bash` to execute the extracted
#                generator command(s) in the scratch clone), the
#                .github/workflows/*.yml files (D1/D2), scripts/*, bin/*,
#                and */build.sh module-manifest headers (D3, via `git
#                grep`, so it only sees tracked files).
#
# Downstream consumers: DS-183/184/185/186 (any future budget-gate axis
#                        work should re-run this against its candidate
#                        target before assigning a hard delta limit or an
#                        informational burn line - see
#                        scripts/check-command-file-budget.sh vs
#                        scripts/check-skill-embed-budget.sh for the two
#                        existing AUTHORED/DERIVED assignments this
#                        script's own rule set was built to reproduce).
#
# Failure modes: wrong argument count -> usage to stderr, exit 2. D1/D2/D3
#                are read-only (git log/grep only, no side effects). D4
#                clones the repo into a `mktemp -d` scratch directory,
#                executes the extracted generator command(s) there, and
#                removes the scratch directory on exit via trap - it never
#                writes to the real working tree or pushes anywhere. If
#                D4's job/generator extraction fails to resolve a runnable
#                command, it silently falls through to the AUTHORED
#                default rather than erroring - a heuristic that cannot
#                find a generator is evidence of nothing, not evidence of
#                AUTHORED, but this script biases toward the cheaper
#                default rather than blocking on an inconclusive case. No
#                `-v`/narration flag exists yet - if a D4 fall-through is
#                unexpected, re-run the D1/D2/D3 grep commands from this
#                file's own rule comments by hand against the target to
#                see what almost matched.
#
# Compatible with bash (CI always invokes `bash scripts/gate-provenance.sh
# ...`); a contributor may also run it under zsh, but D4's scratch-clone
# execution shells out via `bash -c` regardless of the invoking shell, so
# behavior does not depend on the invoker either way. Avoid the variable
# names `status` and `path` anywhere in this file - both are special/
# read-only in zsh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKFLOWS_DIR="$REPO_DIR/.github/workflows"

if [ $# -ne 1 ]; then
  echo "usage: bash scripts/gate-provenance.sh <repo-relative-path>" >&2
  exit 2
fi

TARGET="${1#./}"
TARGET="${TARGET%/}"

# _path_matches <target> <token>
#   True when <target> equals <token>, or <target> lives under <token> as
#   a directory prefix (<token>/<anything>). Strips a trailing slash from
#   <token> first so ".claude" and ".claude/" match identically.
_path_matches() {
  local target="$1" tok="$2"
  tok="${tok%/}"
  [ -z "$tok" ] && return 1
  if [ "$target" = "$tok" ]; then
    return 0
  fi
  case "$target" in
    "$tok"/*) return 0 ;;
  esac
  return 1
}

cd "$REPO_DIR"

# --- D1: CI regenerate-then-assert-clean pairs -----------------------------
d1_result=""
d1_reason=""
d1_wholetree=()  # entries "workflow:lineno" for bare (no-pathspec) hits

if [ -d "$WORKFLOWS_DIR" ]; then
  while IFS= read -r match; do
    [ -z "$match" ] && continue
    wf="${match%%:*}"
    rest="${match#*:}"
    lineno="${rest%%:*}"
    line="${rest#*:}"
    if printf '%s' "$line" | grep -q -- ' -- '; then
      pathspec_raw="$(printf '%s' "$line" | sed -E 's/^.*-- //; s/;.*$//')"
      for tok in $pathspec_raw; do
        if _path_matches "$TARGET" "$tok"; then
          d1_result="DERIVED"
          d1_reason="D1: $wf:$lineno asserts \`git diff --exit-code -- ...\` with a pathspec covering '$tok'"
          break
        fi
      done
      [ -n "$d1_result" ] && break
    else
      d1_wholetree+=("$wf:$lineno")
    fi
  done < <(grep -rn "git diff --exit-code" "$WORKFLOWS_DIR"/*.yml "$WORKFLOWS_DIR"/*.yaml 2>/dev/null || true)
fi

if [ -n "$d1_result" ]; then
  echo "DERIVED: $TARGET ($d1_reason)"
  exit 0
fi

# --- D2: CI-authored commits ------------------------------------------------
d2_result=""
d2_reason=""

if [ -d "$WORKFLOWS_DIR" ]; then
  for wf in "$WORKFLOWS_DIR"/*.yml "$WORKFLOWS_DIR"/*.yaml; do
    [ -f "$wf" ] || continue
    grep -q "git commit" "$wf" || continue
    while IFS= read -r match; do
      [ -z "$match" ] && continue
      lineno="${match%%:*}"
      line="${match#*:}"
      args="$(printf '%s' "$line" | sed -E 's/^.*git add[[:space:]]+//')"
      for tok in $args; do
        tok="${tok%\"}"
        tok="${tok#\"}"
        if _path_matches "$TARGET" "$tok"; then
          d2_result="DERIVED"
          d2_reason="D2: $wf:$lineno runs \`git add\` on '$tok' ahead of a \`git commit\` step in the same workflow"
          break
        fi
      done
      [ -n "$d2_result" ] && break
    done < <(grep -n "git add " "$wf" 2>/dev/null || true)
    [ -n "$d2_result" ] && break
  done
fi

if [ -n "$d2_result" ]; then
  echo "DERIVED: $TARGET ($d2_reason)"
  exit 0
fi

# --- D3: manifest-declared writes -------------------------------------------
d3_result=""
d3_reason=""

while IFS= read -r match; do
  [ -z "$match" ] && continue
  file="${match%%:*}"
  rest="${match#*:}"
  lineno="${rest%%:*}"
  line="${rest#*:}"
  if printf '%s' "$line" | grep -qF "$TARGET"; then
    d3_result="DERIVED"
    d3_reason="D3: $file:$lineno declares a write to '$TARGET'"
    break
  fi
done < <(git grep -n "writes " -- 'scripts/*' 'bin/*' '*/build.sh' 2>/dev/null || true)

if [ -n "$d3_result" ]; then
  echo "DERIVED: $TARGET ($d3_reason)"
  exit 0
fi

# --- D4: empirical closure (only when D1 found a whole-tree assertion) -----
d4_result=""
d4_reason=""

if [ "${#d1_wholetree[@]}" -gt 0 ]; then
  entry="${d1_wholetree[0]}"
  wf="${entry%%:*}"
  diff_lineno="${entry#*:}"

  # Find the nearest enclosing job header (a 2-space-indented "<name>:"
  # line) at or above the diff assertion line, then collect every `run:`
  # step value between that job header and the diff line - this is a
  # heuristic "the generator is whatever this job ran before asserting
  # cleanliness" extraction, not a full YAML/Actions parser.
  job_start_line="$(awk -v stop="$diff_lineno" '
    /^  [A-Za-z0-9_-]+:$/ { last = NR }
    NR == stop { print last; exit }
  ' "$wf")"

  generator_cmds=""
  if [ -n "$job_start_line" ]; then
    generator_cmds="$(awk -v start="$job_start_line" -v stop="$diff_lineno" '
      NR > start && NR < stop && /^\s*run:/ {
        sub(/^\s*run:[[:space:]]*\|?[[:space:]]*/, "");
        if (length($0) > 0) print;
      }
    ' "$wf")"
  fi

  if [ -n "$generator_cmds" ]; then
    SCRATCH_DIR="$(mktemp -d)"
    _d4_cleanup() {
      rm -rf "$SCRATCH_DIR"
    }
    trap _d4_cleanup EXIT

    if git clone --quiet --no-hardlinks "$REPO_DIR" "$SCRATCH_DIR" >/dev/null 2>&1; then
      (cd "$SCRATCH_DIR" && bash -c "$generator_cmds") >/dev/null 2>&1 || true
      if [ -n "$(cd "$SCRATCH_DIR" && git status --porcelain -- "$TARGET" 2>/dev/null)" ]; then
        d4_result="DERIVED"
        d4_reason="D4: running the generator step(s) preceding $wf's whole-tree \`git diff --exit-code\` (line $diff_lineno) in a scratch clone changed '$TARGET'"
      fi
    fi

    _d4_cleanup
    trap - EXIT
  fi
fi

if [ -n "$d4_result" ]; then
  echo "DERIVED: $TARGET ($d4_reason)"
  exit 0
fi

echo "AUTHORED: $TARGET (no D1/D2/D3/D4 rule found a generator write to this path)"
exit 0
