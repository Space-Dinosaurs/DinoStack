# Purpose: Shared infra for the three size-ratchet gates under scripts/
#          (check-resident-budget.sh, check-skill-embed-budget.sh,
#          check-command-file-budget.sh). Extracts the byte-for-byte
#          identical pieces that had accumulated across all three
#          (repo-dir resolution, plain byte measurement, and the common
#          "OK / OVER BUDGET" report shape) so a third near-copy of the
#          skeleton is no longer the norm. Each gate's genuinely distinct
#          MEASUREMENT logic (resident's manifest-offset split, skill-
#          embed's two-sided floor/ceiling, this file's raw `wc -c`)
#          stays in its own script - only the plumbing around that
#          measurement lives here.
#
# Public API: source scripts/lib/budget-gate.sh, then call:
#             budget_repo_dir <script_dir>            -> prints repo root
#             budget_file_bytes <path>                -> prints byte count
#             budget_report <header> <metric_label> <bytes> <threshold> \
#                            <remediation-text> [extra-context-line ...]
#                                                       -> prints an OK or
#                                                          OVER BUDGET
#                                                          report and
#                                                          `exit`s 0 or 1
#
# Upstream deps: none beyond bash/zsh builtins and `wc`.
#
# Downstream consumers: scripts/check-resident-budget.sh,
#                        scripts/check-skill-embed-budget.sh,
#                        scripts/check-command-file-budget.sh.
#
# Failure modes: budget_file_bytes exits nonzero (via set -e in the
#                sourcing script) if the target path does not exist -
#                callers are expected to guard existence themselves first,
#                since each gate's missing-file message differs. This file
#                has no side effects on the repo; it only prints to
#                stdout/stderr and calls `exit` from budget_report.
#
# Compatible with both bash and zsh sourcing/invocation of the containing
# script; CI always invokes the sourcing scripts as `bash ...`, but a
# contributor, reviewer, or a regression test may source/run them under
# zsh and behaviour must be identical. Avoid the known zsh footguns in
# this repo: never name a variable `status` (read-only in zsh) or `path`
# (silently replaces $PATH).

# budget_repo_dir <script_dir>
#   <script_dir> is the caller's own directory, already resolved by the
#   caller (via `cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd`) BEFORE
#   sourcing this file - that resolution has to happen pre-source, since
#   it is how the caller finds this file in the first place, so it is not
#   duplication this library can remove. What this function removes is
#   the "/.." repo-root step and re-`cd`/`pwd` that followed it in all
#   three gates. Every gate lives directly under scripts/, one level
#   below the repo root, so the repo root is simply the parent directory.
budget_repo_dir() {
  local script_dir="$1"
  dirname "$script_dir"
}

# budget_file_bytes <path>
#   Prints the byte size of <path> with whitespace stripped. Does not
#   check existence - callers guard that themselves with their own
#   (differently worded) missing-file message before calling this.
budget_file_bytes() {
  local target_path="$1"
  wc -c < "$target_path" | tr -d '[:space:]'
}

# budget_report <header> <metric_label> <bytes> <threshold> \
#                <remediation-text> [extra-context-line ...]
#   Prints the shared "<header>: OK" / "<header>: OVER BUDGET" report
#   shape and exits 0 (OK) or 1 (OVER BUDGET). <metric_label> becomes the
#   primary "  <metric_label>: <bytes> B" line. Any further positional
#   arguments are printed verbatim as additional "  <line>" context lines
#   between the metric line and the threshold/headroom lines (callers
#   pre-render these themselves, since their internal padding varies per
#   gate) - e.g. resident's "file total (incl. manifest): N B" line.
#   <remediation-text> is a full multi-line string printed only on
#   overage, after a blank line.
budget_report() {
  local header="$1"
  local metric_label="$2"
  local bytes="$3"
  local threshold="$4"
  local remediation="$5"
  shift 5
  local extra_context=("$@")

  if [ "$bytes" -le "$threshold" ]; then
    local headroom=$(( threshold - bytes ))
    echo "$header: OK"
    echo "  $metric_label: $bytes B"
    for context_line in "${extra_context[@]}"; do
      echo "  $context_line"
    done
    echo "  threshold: $threshold B"
    echo "  headroom:  $headroom B"
    exit 0
  fi

  local overage=$(( bytes - threshold ))
  echo "$header: OVER BUDGET" >&2
  echo "  $metric_label: $bytes B" >&2
  for context_line in "${extra_context[@]}"; do
    echo "  $context_line" >&2
  done
  echo "  threshold: $threshold B" >&2
  echo "  overage:   $overage B" >&2
  echo "" >&2
  echo "$remediation" >&2
  exit 1
}
