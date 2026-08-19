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
#          DS-182 added a second axis, git-based, on top of the original
#          absolute-size-only measurement: a fixed ceiling on a shared,
#          monotonically growing artifact makes a PR's pass/fail a
#          function of merge order rather than its own diff (two of the
#          three gates measured here sat within one ordinary merge of
#          blocking all work). budget_delta/budget_burn_line/
#          budget_base_resolve give callers a per-PR delta (for an
#          AUTHORED target, where "this PR grew the file by too much" is
#          a meaningful failure) and a purely informational burn line (for
#          a DERIVED/generated target, where a big delta may just be
#          upstream churn, not this PR's doing) without forcing either
#          axis on a caller that doesn't want it.
#
# Public API: source scripts/lib/budget-gate.sh, then call:
#             budget_repo_dir <script_dir>            -> prints repo root
#             budget_file_bytes <path>                -> prints byte count
#             budget_eval <header> <metric_label> <bytes> <threshold> \
#                         <remediation-text> [extra-context-line ...]
#                                                       -> prints an OK or
#                                                          OVER BUDGET
#                                                          report and
#                                                          RETURNS 0 or 1.
#                                                          Never calls
#                                                          `exit` - use this
#                                                          when the caller
#                                                          needs to run more
#                                                          logic (e.g. print
#                                                          a burn line) after
#                                                          the report but
#                                                          before deciding
#                                                          the script's own
#                                                          exit code.
#             budget_report <same args as budget_eval> -> identical output,
#                                                          but calls `exit`
#                                                          0 or 1 itself
#                                                          (thin wrapper:
#                                                          `if budget_eval
#                                                          "$@"; then exit 0;
#                                                          else exit 1; fi`).
#                                                          Use this when the
#                                                          report is the
#                                                          script's last
#                                                          action.
#             budget_base_resolve <repo_dir> [base_branch]
#                                                       -> prints a
#                                                          resolvable git
#                                                          ref for
#                                                          <base_branch>
#                                                          (default "main"),
#                                                          resolved against
#                                                          <repo_dir> (via
#                                                          `git -C
#                                                          <repo_dir>`, never
#                                                          the caller's own
#                                                          cwd - keeps this
#                                                          in sync with
#                                                          budget_delta,
#                                                          which always
#                                                          takes an explicit
#                                                          <repo_dir> too):
#                                                          tries
#                                                          "origin/<b>" then
#                                                          "<b>". Prints
#                                                          nothing and
#                                                          RETURNS 1 when
#                                                          git is absent,
#                                                          <repo_dir> is not
#                                                          a git work tree,
#                                                          or neither ref
#                                                          resolves.
#                                                          Callers MUST
#                                                          treat a 1 return
#                                                          as SKIPPED and
#                                                          continue on the
#                                                          absolute-size
#                                                          axis alone - this
#                                                          function never
#                                                          fails a gate by
#                                                          itself.
#             budget_delta <repo_dir> <path> <base_ref> -> prints the
#                                                          signed byte delta
#                                                          of <path>
#                                                          (relative to
#                                                          <repo_dir> or
#                                                          absolute) between
#                                                          <base_ref> and
#                                                          the working tree.
#                                                          Prints NOTHING
#                                                          and RETURNS 2
#                                                          when <path> does
#                                                          not exist at
#                                                          <base_ref> - a
#                                                          newly-created
#                                                          file is
#                                                          UNMEASURABLE by
#                                                          this function,
#                                                          never a delta
#                                                          equal to its full
#                                                          size (that
#                                                          conflation would
#                                                          fail every
#                                                          file-creating
#                                                          PR).
#             budget_burn_line <repo_dir> <path> <limit> <current_bytes>
#                                                       -> prints exactly
#                                                          one informational
#                                                          line of the form
#                                                          "burn: <B_per_day>
#                                                          B/day over <D> d
#                                                          - <N> d to limit"
#                                                          (the trailing
#                                                          "- <N> d to
#                                                          limit" clause is
#                                                          OMITTED, not
#                                                          zero-filled, when
#                                                          the computed
#                                                          burn rate is <= 0
#                                                          - dividing a
#                                                          non-positive
#                                                          headroom-per-day
#                                                          into a days-to-
#                                                          limit figure is
#                                                          meaningless) and
#                                                          ALWAYS returns 0
#                                                          - no threshold
#                                                          check, no
#                                                          `::warning::`, no
#                                                          effect on caller
#                                                          exit status. <D>
#                                                          is the whole-day
#                                                          span between the
#                                                          resolved base
#                                                          ref's own commit
#                                                          date and now
#                                                          (floored at 1 so
#                                                          a same-day base
#                                                          never divides by
#                                                          zero); <B_per_day>
#                                                          is
#                                                          budget_delta's
#                                                          signed byte delta
#                                                          since that base
#                                                          divided by <D>;
#                                                          <N> is
#                                                          (<limit> -
#                                                          <current_bytes>)
#                                                          divided by
#                                                          <B_per_day>, only
#                                                          when that is
#                                                          positive. Prints
#                                                          a distinct
#                                                          "burn: SKIPPED
#                                                          (...)" line (and
#                                                          still returns 0)
#                                                          when the base is
#                                                          unresolvable, the
#                                                          path is absent at
#                                                          base, or the base
#                                                          ref's commit date
#                                                          cannot be read -
#                                                          this function
#                                                          never prints
#                                                          nothing and never
#                                                          fails.
#
# Upstream deps: bash/zsh builtins, `wc`. budget_base_resolve/
#                budget_delta additionally depend on `git` being present
#                on PATH and, for budget_delta, the caller's `repo_dir`
#                being inside a git work tree - both degrade to SKIPPED
#                (never a hard failure) when either is unavailable; see
#                Failure modes below. budget_burn_line additionally
#                invokes `git log -1 --format=%ct` (for the base ref's
#                commit date) and the `date` builtin/coreutil (for the
#                current epoch) - both degrade to the same SKIPPED
#                treatment as budget_base_resolve/budget_delta rather than
#                a hard failure.
#
# Downstream consumers: scripts/check-resident-budget.sh (unchanged - no
#                        git axis, still calls budget_report exactly as
#                        before DS-182); scripts/check-skill-embed-budget.sh
#                        (hand-rolls its own OK-path report rather than
#                        calling budget_eval/budget_report at all - see
#                        that script's own header comment for why - and
#                        calls budget_burn_line for the informational
#                        burn-rate line printed on every exit path; no
#                        delta axis); scripts/check-command-file-budget.sh
#                        (added a budget_delta-based per-PR delta axis and
#                        calls budget_eval directly, not budget_report, so
#                        a delta breach can still let the THRESHOLD_BYTES
#                        report run before this script decides its own
#                        combined exit code).
#
# Failure modes: budget_file_bytes exits nonzero (via set -e in the
#                sourcing script) if the target path does not exist -
#                callers are expected to guard existence themselves first,
#                since each gate's missing-file message differs.
#                budget_base_resolve and budget_delta never raise a hard
#                error for an ordinary "no git here" or "path new at HEAD"
#                condition - they return a non-zero status a caller is
#                expected to check and treat as SKIPPED, never propagated
#                as a script failure by this library itself.
#                budget_burn_line never returns non-zero at all. This file
#                has no side effects on the repo; it only prints to
#                stdout/stderr and calls `exit` from budget_report (never
#                from budget_eval, budget_base_resolve, budget_delta, or
#                budget_burn_line).
#
# Compatible with both bash and zsh sourcing/invocation of the containing
# script; CI always invokes the sourcing scripts as `bash ...`, but a
# contributor, reviewer, or a regression test may source/run them under
# zsh and behaviour must be identical. Also compatible with bash 3.2 (the
# default /bin/bash on macOS) specifically: budget_eval's extra-context
# array is expanded with an explicit `[ ${#extra_context[@]} -gt 0 ]`
# count guard, not a bare `"${extra_context[@]}"`, because expanding an
# empty array under `set -u` is an "unbound variable" error on bash <4.4
# (3.2 included) even though it is a documented no-op on bash >=4.4 and
# zsh - both guards from the pre-DS-182 budget_report carry over
# unchanged into budget_eval. Avoid the known zsh footguns in this repo:
# never name a variable `status` (read-only in zsh) or `path` (silently
# replaces $PATH). All git invocations inside budget_base_resolve and
# budget_delta redirect stderr to /dev/null, so a missing git, a missing
# ref, or a non-work-tree cwd never leaks noise onto a caller's stderr -
# only this library's own callers decide whether/how to report a SKIPPED
# git axis.

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

# budget_eval <header> <metric_label> <bytes> <threshold> \
#              <remediation-text> [extra-context-line ...]
#   Prints the shared "<header>: OK" / "<header>: OVER BUDGET" report
#   shape and RETURNS 0 (OK) or 1 (OVER BUDGET) - never calls `exit`.
#   <metric_label> becomes the primary "  <metric_label>: <bytes> B"
#   line. Any further positional arguments are printed verbatim as
#   additional "  <line>" context lines between the metric line and the
#   threshold/headroom lines (callers pre-render these themselves, since
#   their internal padding varies per gate) - e.g. resident's "file total
#   (incl. manifest): N B" line, or command-file-budget.sh's per-PR delta
#   line. <remediation-text> is a full multi-line string printed only on
#   overage, after a blank line.
budget_eval() {
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
    if [ "${#extra_context[@]}" -gt 0 ]; then
      for context_line in "${extra_context[@]}"; do
        echo "  $context_line"
      done
    fi
    echo "  threshold: $threshold B"
    echo "  headroom:  $headroom B"
    return 0
  fi

  local overage=$(( bytes - threshold ))
  echo "$header: OVER BUDGET" >&2
  echo "  $metric_label: $bytes B" >&2
  if [ "${#extra_context[@]}" -gt 0 ]; then
    for context_line in "${extra_context[@]}"; do
      echo "  $context_line" >&2
    done
  fi
  echo "  threshold: $threshold B" >&2
  echo "  overage:   $overage B" >&2
  echo "" >&2
  echo "$remediation" >&2
  return 1
}

# budget_report <same args as budget_eval>
#   Thin exit-calling wrapper around budget_eval, for callers whose report
#   is the script's last action.
budget_report() {
  if budget_eval "$@"; then
    exit 0
  else
    exit 1
  fi
}

# budget_base_resolve <repo_dir> [base_branch]
#   Prints a resolvable base ref for <base_branch> (default "main"),
#   resolved against <repo_dir> via `git -C <repo_dir>` - never the
#   caller's own cwd, so this stays in sync with budget_delta, which
#   always takes an explicit <repo_dir> too: tries "origin/<base_branch>"
#   first, then bare "<base_branch>". Prints nothing and returns 1 when
#   git is absent from PATH, <repo_dir> is not inside a git work tree, or
#   neither ref resolves (e.g. a non-git scratch fixture, or a shallow
#   clone missing the remote-tracking ref). Every git invocation here
#   redirects stderr to /dev/null so a missing ref never leaks noise.
#   Callers MUST treat a 1 return as SKIPPED and continue on the
#   absolute-size axis alone - this function never fails a gate by
#   itself, it only reports whether a git-based axis is even possible
#   right now.
budget_base_resolve() {
  local repo_dir="$1"
  local base_branch="${2:-main}"
  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi
  if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  if git -C "$repo_dir" rev-parse --verify "origin/$base_branch" >/dev/null 2>&1; then
    echo "origin/$base_branch"
    return 0
  fi
  if git -C "$repo_dir" rev-parse --verify "$base_branch" >/dev/null 2>&1; then
    echo "$base_branch"
    return 0
  fi
  return 1
}

# budget_delta <repo_dir> <path> <base_ref>
#   Prints the signed byte delta of <path> (current working-tree bytes
#   minus its byte size at <base_ref>). <path> may be given absolute
#   (e.g. "$REPO_DIR/content/foo.md") or already relative to <repo_dir> -
#   either way it is normalized to a path relative to <repo_dir> before
#   being looked up in git, since that is what a `<ref>:<path>` git
#   object spec requires. Prints NOTHING and returns 2 when <path> does
#   not exist at <base_ref> - a path absent at base is UNMEASURABLE, not
#   a delta equal to its own full size; conflating the two would fail
#   every PR that creates a new file under budget-gate coverage. All git
#   invocations redirect stderr to /dev/null.
budget_delta() {
  local repo_dir="$1"
  local target_path="$2"
  local base_ref="$3"
  local rel_path="$target_path"
  case "$target_path" in
    "$repo_dir"/*)
      rel_path="${target_path#"$repo_dir"/}"
      ;;
  esac

  if ! git -C "$repo_dir" cat-file -e "$base_ref:$rel_path" >/dev/null 2>&1; then
    return 2
  fi

  local base_bytes
  base_bytes="$(git -C "$repo_dir" cat-file -s "$base_ref:$rel_path" 2>/dev/null)" || return 2
  local current_bytes
  current_bytes="$(budget_file_bytes "$target_path")"
  echo $(( current_bytes - base_bytes ))
  return 0
}

# budget_burn_line <repo_dir> <path> <limit> <current_bytes>
#   Prints exactly one informational "burn: <B_per_day> B/day over <D> d -
#   <N> d to limit" line and ALWAYS returns 0 - no threshold check, no
#   `::warning::`, no effect on caller exit status. Never prints nothing:
#   every unavailable-input case (git absent, <repo_dir> not a work tree,
#   no base ref resolves, <path> absent at the resolved base ref, or the
#   base ref's own commit date cannot be read) renders a distinct "burn:
#   SKIPPED (...)" line instead, so a caller can unconditionally echo its
#   output without a separate presence check.
#
#   <D> is the whole-day span between the resolved base ref's own commit
#   date (`git log -1 --format=%ct`) and now, floored at 1 so a same-day
#   base never divides by zero. Because every current caller resolves its
#   base against `origin/main`/`main` (a fast-moving branch, not a fixed
#   release window), <D> is nearly always exactly 1 in ordinary same-day
#   CI use - <B_per_day> then reduces to this branch's own raw delta, not
#   a rate measured over a meaningful window. Treat "B/day" as a relabeled
#   delta unless <D> is actually greater than 1 (e.g. a local run against
#   a base several days stale). <B_per_day> is budget_delta's signed byte
#   delta of <path> since that base, divided by <D> (integer division,
#   truncated toward zero). The trailing "- <N> d to limit" clause -
#   <N> = (<limit> - <current_bytes>) / <B_per_day> - is OMITTED (not
#   zero-filled) whenever <B_per_day> is <= 0 (no meaningful "days to
#   limit" for a non-positive burn rate) OR <current_bytes> is already at
#   or over <limit> (headroom <= 0): bash's truncate-toward-zero integer
#   division would otherwise render a small negative headroom as "0 d to
#   limit", which reads as "at the limit right now" rather than "already
#   past it".
#
#   Deliberately takes no <base_ref> argument - it resolves its own base
#   via budget_base_resolve, since every current caller wants the default
#   "main" resolution and a caller needing a non-default base branch can
#   call budget_base_resolve and budget_delta directly instead of going
#   through this wrapper.
budget_burn_line() {
  local repo_dir="$1"
  local target_path="$2"
  local limit="$3"
  local current_bytes="$4"
  local base_ref
  if ! base_ref="$(budget_base_resolve "$repo_dir")"; then
    echo "burn: SKIPPED (base unresolvable)"
    return 0
  fi

  local delta_bytes
  if ! delta_bytes="$(budget_delta "$repo_dir" "$target_path" "$base_ref")"; then
    echo "burn: SKIPPED (absent at base $base_ref)"
    return 0
  fi

  local base_epoch
  if ! base_epoch="$(git -C "$repo_dir" log -1 --format=%ct "$base_ref" 2>/dev/null)" || [ -z "$base_epoch" ]; then
    echo "burn: SKIPPED (commit date unavailable for $base_ref)"
    return 0
  fi

  local now_epoch days_span
  now_epoch="$(date +%s)"
  days_span=$(( (now_epoch - base_epoch) / 86400 ))
  if [ "$days_span" -lt 1 ]; then
    days_span=1
  fi

  local burn_per_day headroom
  burn_per_day=$(( delta_bytes / days_span ))
  headroom=$(( limit - current_bytes ))

  if [ "$burn_per_day" -gt 0 ] && [ "$headroom" -gt 0 ]; then
    local days_to_limit=$(( headroom / burn_per_day ))
    echo "burn: ${burn_per_day} B/day over ${days_span} d - ${days_to_limit} d to limit"
  else
    echo "burn: ${burn_per_day} B/day over ${days_span} d"
  fi
  return 0
}
