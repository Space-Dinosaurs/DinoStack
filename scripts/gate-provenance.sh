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
# Failure modes: wrong argument count -> usage to stderr, exit 2. An
#                argument that is empty, absolute (leading `/`), or
#                contains a `..` path-traversal segment also exits 2 -
#                this script's whole purpose is telling other tickets how
#                to classify a path, and a confident AUTHORED/DERIVED
#                answer on malformed input is worse than a refusal (DS-182
#                round-3 Major 3). D1/D2/D3 are read-only (git log/grep
#                only, no side effects). D4 clones the repo into a
#                `mktemp -d` scratch directory, executes the extracted
#                generator command(s) there, and removes the scratch
#                directory on exit via trap - it never writes to the real
#                working tree or pushes anywhere. If D4's job/generator
#                extraction fails to resolve a runnable command, it
#                silently falls through to the AUTHORED default rather
#                than erroring - a heuristic that cannot find a generator
#                is evidence of nothing, not evidence of AUTHORED, but this
#                script biases toward the cheaper default rather than
#                blocking on an inconclusive case. No `-v`/narration flag
#                exists yet - if a D4 fall-through is unexpected, re-run
#                the D1/D2/D3 grep commands from this file's own rule
#                comments by hand against the target to see what almost
#                matched.
#
# D4 verification (DS-182 round-3 Major 2): the `run:` step extraction
# awk originally used `\s`, a GNU-awk extension that is a silent no-op
# under BSD awk (the one-true-awk macOS contributors run - this is where
# the round-3 Major 2 bug was found), so D4's clone-and-execute block was
# reachable but never actually entered - `generator_cmds` was always
# empty. `\s` is NOT portable to assume broken everywhere, though: gawk
# (what this repo's Ubuntu CI runner installs) supports `\s` as its own
# GNU extension and matches under it, so a mutation check asserting `\s`
# yields empty output fails on CI even though the fix (`[[:space:]]`,
# POSIX-portable across both) is correct - do not reintroduce that
# mutation check; see bin/tests/test_gate_provenance.sh's D4 extraction
# test for the removed instance and why. Fixed to `[[:space:]]` and
# confirmed against the real, live
# .github/workflows/codex-skill-sync.yml (the only bare, no-pathspec
# `git diff --exit-code` in this repo, i.e. the only real trigger for D4 -
# its line number moves as the workflow is edited, so it is looked up at
# check time rather than hard-pinned)
# in bin/tests/test_gate_provenance.sh, which extracts and pins the exact
# 5 real generator commands. Every path D1/D2/D3 do not resolve now
# genuinely reaches D4's scratch-clone-and-execute step (measured: 6m42s
# wall-clock for one such run) - in the current repo this always falls
# through to AUTHORED regardless, because every real target D4's
# generator commands touch lives under `.codex/`, which D1's earlier
# adapter-sync.yml pathspec already classifies as DERIVED before D4 is
# ever reached; a genuine D4-only DERIVED verdict has not been observed
# and cannot be produced against this repo's current workflow layout. Full
# live execution of D4 (the clone-and-build itself, not just the
# extraction) is opt-in in the test suite (`RUN_SLOW_D4_TEST=1`) rather
# than run by default, given that measured cost.
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

if [ -z "$1" ]; then
  echo "error: <repo-relative-path> must not be empty" >&2
  exit 2
fi

case "$1" in
  /*)
    echo "error: <repo-relative-path> must be repo-relative, not absolute: $1" >&2
    exit 2
    ;;
  ..|../*|*/../*|*/..)
    echo "error: <repo-relative-path> must not contain a '..' escape: $1" >&2
    exit 2
    ;;
esac

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

# WORKFLOW_FILES is built via `find`, never a raw "$WORKFLOWS_DIR"/*.yaml
# glob - zsh (unlike bash) aborts on a glob with zero matches ("no matches
# found") instead of leaving the pattern unexpanded, and this repo has no
# .github/workflows/*.yaml files today, only *.yml, so a direct glob here
# crashes `zsh scripts/gate-provenance.sh <target>` outright even though
# this script's own compatibility note above promises identical behavior
# under both shells.
WORKFLOW_FILES=()
if [ -d "$WORKFLOWS_DIR" ]; then
  while IFS= read -r wf; do
    WORKFLOW_FILES+=("$wf")
  done < <(find "$WORKFLOWS_DIR" -maxdepth 1 \( -name '*.yml' -o -name '*.yaml' \) 2>/dev/null | sort)
fi

# --- D1: CI regenerate-then-assert-clean pairs -----------------------------
d1_result=""
d1_reason=""
# First bare (no-pathspec) "workflow:lineno" hit, D4's only input. A
# scalar, not an array: zsh arrays are 1-indexed by default (bash's are
# 0-indexed), so a literal `${arr[0]}` read - needed by D4 below - is
# invalid under zsh and aborts with "parameter not set". Only the first
# hit is ever consumed, so tracking it in a scalar sidesteps the
# indexing-base mismatch entirely rather than requiring KSH_ARRAYS or a
# portable-extraction workaround.
d1_first_wholetree=""

if [ "${#WORKFLOW_FILES[@]}" -gt 0 ]; then
  while IFS= read -r match; do
    [ -z "$match" ] && continue
    wf="${match%%:*}"
    rest="${match#*:}"
    lineno="${rest%%:*}"
    line="${rest#*:}"
    if printf '%s' "$line" | grep -q -- ' -- '; then
      pathspec_raw="$(printf '%s' "$line" | sed -E 's/^.*-- //; s/;.*$//')"
      # Splitting via `for tok in $(printf ...)` rather than a bare
      # `for tok in $pathspec_raw` is load-bearing, not style: zsh does
      # NOT word-split an unquoted plain variable expansion by default
      # (unlike bash), so a bare `$pathspec_raw` here iterates ONCE over
      # the whole multi-token string under zsh - it DOES word-split
      # unquoted command-substitution output, which is what this form
      # relies on to behave identically in both shells.
      for tok in $(printf '%s' "$pathspec_raw"); do
        if _path_matches "$TARGET" "$tok"; then
          d1_result="DERIVED"
          d1_reason="D1: $wf:$lineno asserts \`git diff --exit-code -- ...\` with a pathspec covering '$tok'"
          break
        fi
      done
      [ -n "$d1_result" ] && break
    else
      [ -z "$d1_first_wholetree" ] && d1_first_wholetree="$wf:$lineno"
    fi
  done < <(grep -rn "git diff --exit-code" "${WORKFLOW_FILES[@]}" 2>/dev/null || true)
fi

if [ -n "$d1_result" ]; then
  echo "DERIVED: $TARGET ($d1_reason)"
  exit 0
fi

# --- D2: CI-authored commits ------------------------------------------------
d2_result=""
d2_reason=""

if [ "${#WORKFLOW_FILES[@]}" -gt 0 ]; then
  for wf in "${WORKFLOW_FILES[@]}"; do
    [ -f "$wf" ] || continue
    grep -q "git commit" "$wf" || continue
    while IFS= read -r match; do
      [ -z "$match" ] && continue
      lineno="${match%%:*}"
      line="${match#*:}"
      args="$(printf '%s' "$line" | sed -E 's/^.*git add[[:space:]]+//')"
      # See the D1 pathspec loop above for why this must be a
      # command-substitution split, not a bare `$args`.
      for tok in $(printf '%s' "$args"); do
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
#
# Extracts path-shaped tokens ([A-Za-z0-9._/-]+, trailing sentence
# punctuation stripped) from each matched "writes " line and runs each
# through the same _path_matches used by D1/D2, rather than an unanchored
# substring search. An unanchored `grep -qF "$TARGET"` false-positived on
# TARGET="AGENTS.md" against bin/ds-disable's "writes opt-out marker to
# <cwd>/AGENTS.md" - that sentence is about a CONSUMER project's AGENTS.md,
# not this repo's, but "AGENTS.md" is a substring of "<cwd>/AGENTS.md" so
# the old check matched it anyway.
#
# Two further narrowings, both measured false positives from the tokenized
# approach alone: (1) a candidate token is discarded unless it contains a
# '/' or a '.' - a bare alnum word like "content" or "bin" is at least as
# likely to be ordinary English prose (git_fixture.py's "...file with
# unchanged content..." docstring matched TARGET="content" this way) as a
# path, and neither D1 nor D2's own token sources (pathspecs, `git add`
# arguments) ever emit a bare extension-less, slash-less word for a
# multi-segment target like this. (2) any matched line whose own text
# contains the D3 search invocation itself (`git grep -n "writes "`) is
# skipped, wherever it appears - not just in this script's own source, but
# in ANY file that quotes or mirrors this exact D3 implementation (e.g. a
# regression test copying it verbatim for verification). Filtering by
# self-file-path alone is insufficient: this line's own literal text -
# "writes " next to 'scripts/*'/'bin/*' - self-classifies "bin"/"scripts"
# as DERIVED off a pathspec argument in EVERY file that contains it, not
# just this one, so the exclusion has to be on the line's content, not a
# hardcoded path.
#
# Known residual gap: a bare, unqualified filename mentioned in CLI
# help/docstring prose as the write target (e.g. bin/ds-help's "writes an
# opt-out marker to AGENTS.md", describing a write to the CALLING
# project's own AGENTS.md at runtime, not a path inside this repo) still
# satisfies both narrowings above - it has a '.' and is a real path-aware
# token match - and D3 has no way to distinguish that from a genuine
# in-repo manifest declaration using text pattern matching alone. TARGET=
# "AGENTS.md" specifically still classifies DERIVED via bin/ds-help for
# this reason; treat any D3 hit against a bare top-level filename as
# needing a by-hand read of the cited line before trusting it.
d3_result=""
d3_reason=""

while IFS= read -r match; do
  [ -z "$match" ] && continue
  file="${match%%:*}"
  rest="${match#*:}"
  lineno="${rest%%:*}"
  line="${rest#*:}"
  case "$line" in
    *'git grep -n "writes "'*) continue ;;
  esac
  for raw_tok in $(printf '%s' "$line" | grep -oE '[A-Za-z0-9._/-]+'); do
    tok="${raw_tok%.}"
    [ -z "$tok" ] && continue
    case "$tok" in
      */*|*.*) ;;
      *) continue ;;
    esac
    if _path_matches "$TARGET" "$tok"; then
      d3_result="DERIVED"
      d3_reason="D3: $file:$lineno declares a write to '$tok'"
      break
    fi
  done
  [ -n "$d3_result" ] && break
done < <(git grep -n "writes " -- 'scripts/*' 'bin/*' '*/build.sh' 2>/dev/null || true)

if [ -n "$d3_result" ]; then
  echo "DERIVED: $TARGET ($d3_reason)"
  exit 0
fi

# --- D4: empirical closure (only when D1 found a whole-tree assertion) -----
d4_result=""
d4_reason=""

if [ -n "$d1_first_wholetree" ]; then
  entry="$d1_first_wholetree"
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
      NR > start && NR < stop && /^[[:space:]]*run:/ {
        sub(/^[[:space:]]*run:[[:space:]]*\|?[[:space:]]*/, "");
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
