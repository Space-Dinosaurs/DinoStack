# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Module manifest
# Purpose: Append one `step_outcome` event (bin/ds-emit) to the PRIMARY
#          checkout's .agentic/events.jsonl, so a helper run from a linked
#          worktree is still counted where /ds-evaluate reads. Step ids and
#          how they are counted: bin/_steps.py.
#
# Public API:
#   ds_step_outcome EMIT BASE HELPER STEP OUTCOME TASK [PR]
#     EMIT     path of bin/ds-emit; a missing file makes this a no-op.
#     BASE     directory the primary checkout is resolved from
#              (`git rev-parse --git-common-dir`); when that is not a git
#              work tree with a `.git` common dir, ds-emit's own default
#              (.agentic under the current directory) is used.
#     HELPER   the calling script's name, recorded as data.helper.
#     STEP     step id; OUTCOME one value of the helper's header enum.
#     TASK     ticket id or `-` (null).
#     PR       recorded as data.pr only when it is all digits.
#
# Upstream deps: git, bin/ds-emit.
#
# Downstream consumers: bin/ds-ticket-ci, bin/ds-ticket-commit,
#                       bin/ds-ticket-finish.
#
# Failure modes: never fails the caller; ds-emit is best-effort and its
#                output is discarded.
#
# Performance: one git rev-parse plus one ds-emit call.
# ---------------------------------------------------------------------------

ds_step_outcome() {
  local so_emit="$1" so_base="$2" so_helper="$3" so_step="$4" so_outcome="$5" so_task="$6" so_pr="${7:-}"
  local so_gcd so_common so_json
  [ -f "$so_emit" ] || return 0
  so_json="{\"step\":\"$so_step\",\"outcome\":\"$so_outcome\",\"helper\":\"$so_helper\""
  case "$so_pr" in ''|*[!0-9]*) ;; *) so_json="$so_json,\"pr\":$so_pr" ;; esac
  so_json="$so_json}"
  so_common=""
  if so_gcd=$(git -C "$so_base" rev-parse --git-common-dir 2>/dev/null) && [ -n "$so_gcd" ]; then
    so_common=$(cd "$so_base" 2>/dev/null && cd "$so_gcd" 2>/dev/null && pwd -P) || so_common=""
  fi
  case "$so_common" in
    */.git) AGENTIC_DIR="${so_common%/.git}/.agentic" bash "$so_emit" step_outcome - "$so_task" "$so_json" >/dev/null 2>&1 ;;
    *) bash "$so_emit" step_outcome - "$so_task" "$so_json" >/dev/null 2>&1 ;;
  esac
  return 0
}
