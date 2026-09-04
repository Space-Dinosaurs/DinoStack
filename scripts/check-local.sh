#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: THE single local entry point for the locally-runnable part of CI's
#          gate set, in CI's order. Before this existed there was no such
#          command: contributors ran an ad-hoc subset, and the gaps were
#          re-diagnosed from scratch by every engineer who hit them.
#
#          COVERAGE IS DELIBERATELY PARTIAL AND SAYS SO. Three CI gates are
#          too slow or too toolchain-heavy to belong in a pre-commit loop
#          (the full Codex skill suite, the slides build plus its overflow
#          checks, and the gitleaks full-history scan). They are NOT run
#          here, and this script prints them, with their exact commands,
#          under a "NOT RUN LOCALLY (run in CI)" block at the end of EVERY
#          run - pass or fail. A green run means "the covered set passed",
#          never "CI will be green", and the block is what keeps that
#          distinction in front of the reader instead of buried here.
#
# Pillar 8 record (docs/overview/vision.md):
#   Catch - in ONE session, three engineers independently re-diagnosed
#           hooks/tests/test-stdin-guard.js failing on `require('espree')`
#           (a transitive eslint dep; CI runs `npm ci`, CONTRIBUTING.md
#           documented only `pip install pyyaml`), and every engineer and
#           Skeptic re-verified the folklore of "4 pre-existing bin/tests
#           failures" - which is false. `pytest bin/tests/` is green. The two
#           real local failures are bash-3.2-only and are toolchain failures,
#           which the preflight below now prevents outright.
#   Retirement - the PREFLIGHT retires when a devcontainer or `mise` file pins
#           the toolchain for CI and local alike, making the check redundant.
#           The ENTRY POINT does not retire: it is an ergonomics surface, not
#           a gate, and adds no enforcement to retire.
#
# Public API:
#   bash scripts/check-local.sh
#     exit 0 - every COVERED gate passed (see the NOT-RUN block it prints).
#     exit 1 - a gate failed.
#     exit 2 - TOOLCHAIN PREFLIGHT FAILED. Distinct from 1 and never conflated
#              with it: nothing was tested, so a 2 is never evidence about the
#              code. No gate runs on this path. A usage error is also a 2,
#              for the same reason.
#
#   Every gate runs even after an earlier one fails; failures are collected
#   and reported together at the end. One local round, not one per finding.
#
# Environment:
#   DS_CHECK_LOCAL_BASH5_CANDIDATES - colon-separated extra paths to search
#            for a bash >= 5 when the `bash` on PATH is older (macOS ships
#            3.2). Defaults to /usr/local/bin/bash:/opt/homebrew/bin/bash.
#
# Upstream dependencies: bash >= 5, node + npm ci, python3 + pytest +
#            pytest-timeout + pyyaml, zsh, gitleaks, gh >= 2.52, git. The
#            preflight verifies each and prints the exact install command for
#            whatever is missing. NOTHING here downgrades a missing tool to a
#            skip: a silently-skipped assertion is indistinguishable from a
#            pass (see AGENTS.md, three separate recorded instances of that
#            failure family).
#
# Downstream consumers: contributors; CONTRIBUTING.md "Local toolchain";
#            bin/tests/test_check_local.sh.
#
# Failure modes: preflight miss -> exit 2 naming every missing tool at once.
#            Any gate nonzero -> exit 1 with that gate's captured output
#            replayed and a summary listing every failed gate.
# ---------------------------------------------------------------------------
set -uo pipefail

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      echo "usage: bash scripts/check-local.sh"
      echo "  runs the locally-runnable part of CI's gate set, in CI's order."
      echo "  every run ends with a 'NOT RUN LOCALLY (run in CI)' block naming"
      echo "  the gates it does not cover and their exact commands."
      echo "  exit 0 = every covered gate passed, 1 = a gate failed,"
      echo "  2 = toolchain preflight failed (nothing was tested)."
      exit 0
      ;;
    *)
      echo "check-local: unknown argument '$arg' (this script takes no options)" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

# ---------------------------------------------------------------------------
# Preflight. Exit 2. Runs no gate.
# ---------------------------------------------------------------------------
PREFLIGHT_MISSES=""

_miss() {
  # _miss <what> <install command>
  PREFLIGHT_MISSES="${PREFLIGHT_MISSES}  - $1
      fix: $2
"
}

_version_ge() {
  # _version_ge <have> <want> - dotted numeric compare, true when have >= want.
  [ "$(printf '%s\n%s\n' "$2" "$1" | LC_ALL=C sort -t. -k1,1n -k2,2n -k3,3n | head -1)" = "$2" ]
}

# bash >= 5. macOS ships 3.2, under which the GATE SCRIPT
# scripts/check-methodology-drift.sh and the test suite
# bin/tests/test_update_shared_constants.sh both fail for reasons that have
# nothing to do with the change under test. Every shell gate below runs under
# BASH5, not /bin/bash, so CI's shell is what gets exercised.
BASH5=""
_bash_major() { "$1" -c 'echo ${BASH_VERSINFO[0]}' 2>/dev/null; }
_cands="bash:${DS_CHECK_LOCAL_BASH5_CANDIDATES:-/usr/local/bin/bash:/opt/homebrew/bin/bash}"
_old_ifs="$IFS"
IFS=:
for _cand in $_cands; do
  IFS="$_old_ifs"
  _resolved="$(command -v "$_cand" 2>/dev/null)" || _resolved=""
  if [ -n "$_resolved" ] && [ "$(_bash_major "$_resolved")" -ge 5 ] 2>/dev/null; then
    BASH5="$_resolved"
    break
  fi
  IFS=:
done
IFS="$_old_ifs"
if [ -z "$BASH5" ]; then
  _miss "bash >= 5 (searched: ${_cands//:/, })" "brew install bash"
fi

# node + the transitive espree parser the JS hook tests load. CI runs `npm ci`;
# this is the exact dependency three separate engineers re-diagnosed by hand.
if ! command -v node >/dev/null 2>&1; then
  _miss "node (not on PATH)" "brew install node"
elif ! node -e "require('espree')" >/dev/null 2>&1; then
  _miss "the espree parser required by hooks/tests/test-stdin-guard.js (a transitive eslint dep)" \
        "npm ci"
fi

# python3 + the three modules bin-tests.yml installs.
if ! command -v python3 >/dev/null 2>&1; then
  _miss "python3 (not on PATH)" "brew install python"
elif ! python3 -c "import pytest, pytest_timeout, yaml" >/dev/null 2>&1; then
  _miss "python modules pytest / pytest-timeout / pyyaml" \
        "pip install pytest pytest-timeout pyyaml"
fi

# gh >= 2.52.
if ! command -v gh >/dev/null 2>&1; then
  _miss "gh (not on PATH)" "brew install gh"
else
  _gh_ver="$(gh --version 2>/dev/null | head -1 | sed -E 's/[^0-9]*([0-9]+(\.[0-9]+)*).*/\1/')"
  if [ -z "$_gh_ver" ] || ! _version_ge "$_gh_ver" "2.52"; then
    _miss "gh >= 2.52 (found '${_gh_ver:-none}')" "brew upgrade gh"
  fi
fi

# zsh - the bash/zsh parity matrix in test_check_resident_budget.sh and
# test_phase8_telemetry_shell.py asserts against it.
if ! command -v zsh >/dev/null 2>&1; then
  _miss "zsh (not on PATH)" "brew install zsh"
fi

# gitleaks - test_gitleaks_allowlist_scope.sh hard-fails under CI without it.
if ! command -v gitleaks >/dev/null 2>&1; then
  _miss "gitleaks (not on PATH)" "brew install gitleaks"
fi

if [ -n "$PREFLIGHT_MISSES" ]; then
  {
    echo "TOOLCHAIN PREFLIGHT FAILED - no gate was run, so this says nothing about your change."
    echo
    printf '%s' "$PREFLIGHT_MISSES"
    echo "Install the above, then re-run: bash scripts/check-local.sh"
  } >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Gate harness.
# ---------------------------------------------------------------------------
FAILED=""
GATE_LOG="$(mktemp -t check-local.XXXXXX)"
trap 'rm -f "$GATE_LOG"' EXIT

# _split_lines <newline-separated-list>
# Splits on newlines only (never on spaces or tabs) with globbing disabled,
# leaving the result in the array _SPLIT. Sole home of that idiom.
_SPLIT=()
_split_lines() {
  local saved_ifs="$IFS"
  IFS='
'
  set -f
  # shellcheck disable=SC2206
  _SPLIT=($1)
  set +f
  IFS="$saved_ifs"
}

_run_gate() {
  # _run_gate <label> <command...>
  local label="$1"
  shift
  local start end rc
  start=$(date +%s)
  printf '==> %s\n' "$label"
  "$@" >"$GATE_LOG" 2>&1
  rc=$?
  end=$(date +%s)
  if [ "$rc" -ne 0 ]; then
    FAILED="${FAILED}${label}
"
    echo "--- FAILED (exit $rc, $((end - start))s): $label"
    cat "$GATE_LOG"
    echo "--- end $label"
  else
    echo "    ok ($((end - start))s)"
  fi
  return 0
}

# _run_snippet <label> <shell-snippet>
# For the CI steps whose body is a shell snippet rather than a command, run
# under the resolved bash 5 exactly as the runner would.
_run_snippet() {
  _run_gate "$1" "$BASH5" -c "$2"
}

# _run_file_loop <label> <runner> <path>...
# Runs one file per iteration under <runner>, replaying output only for the
# files that fail. Mirrors CI's per-file loop, including its one-file-one-
# verdict granularity.
_run_file_loop() {
  local label="$1" runner="$2"
  shift 2
  local f rc start end failures=0 count=0
  start=$(date +%s)
  printf '==> %s (%s files)\n' "$label" "$#"
  for f in "$@"; do
    "$runner" "$f" >"$GATE_LOG" 2>&1
    rc=$?
    count=$((count + 1))
    if [ "$rc" -ne 0 ]; then
      failures=$((failures + 1))
      echo "--- FAILED (exit $rc): $f"
      cat "$GATE_LOG"
      echo "--- end $f"
    fi
  done
  end=$(date +%s)
  if [ "$failures" -ne 0 ]; then
    FAILED="${FAILED}${label} (${failures}/${count} files)
"
  else
    echo "    ok ($count files, $((end - start))s)"
  fi
  return 0
}

# shellcheck source=scripts/lib/ci-test-discovery.sh
. "$REPO_ROOT/scripts/lib/ci-test-discovery.sh"

_loop_from_discovery() {
  # _loop_from_discovery <label> <runner> <discovery-fn>
  local label="$1" runner="$2" fn="$3"
  local listing
  if ! listing="$("$fn" "$REPO_ROOT")"; then
    FAILED="${FAILED}${label}: test discovery failed
"
    return 0
  fi
  _split_lines "$listing"
  _run_file_loop "$label" "$runner" "${_SPLIT[@]}"
}

_require_file() {
  if [ ! -f "$REPO_ROOT/$1" ]; then
    echo "check-local: expected gate script '$1' not found - CI runs it, so its absence here is a hard error, not a skip" >&2
    FAILED="${FAILED}missing gate script: $1
"
    return 1
  fi
  return 0
}

RUN_START=$(date +%s)

# --- build + drift ---------------------------------------------------------
#
# CI runs these as independent jobs on independent fresh checkouts, so their
# relative order there is undefined. Locally they share ONE tree, so the two
# generators (agent-fragment stamping and the adapter build) must both run
# BEFORE either drift diff - otherwise a stamped content/agents/ change would
# be reported as adapter drift that a rebuild would have absorbed.
if _require_file scripts/stamp-agent-fragments.sh; then
  _run_gate "stamp-agent-fragments.sh" "$BASH5" scripts/stamp-agent-fragments.sh
fi
if _require_file scripts/build-all.sh; then
  _run_gate "build-all.sh" "$BASH5" scripts/build-all.sh
fi

# adapter-sync.yml :: "Verify adapter-sync pathspec entries exist". git diff
# silently exits 0 on a nonexistent pathspec, so this step is what stops the
# drift check below from asserting nothing.
_run_snippet "adapter-sync pathspec entries exist" '
for p in .claude .codex .cursor .gemini .kimi .opencode .omp .pi .hermes .openclaw .copilot \
         .github/copilot-instructions.md .github/agents .github/prompts .github/instructions .github/hooks .github/skills; do
  if [[ ! -e "$p" ]]; then
    echo "adapter-sync pathspec entry missing: $p (drift check would silently pass on this)" >&2
    exit 1
  fi
done'

# agent-fragment-sync.yml :: "Fail on agent-check fragment drift".
_run_gate "agent-fragment drift (git diff --exit-code -- content/agents/)" \
  git diff --exit-code -- content/agents/

# Pathspec copied VERBATIM from the `Fail on adapter drift` step in
# .github/workflows/adapter-sync.yml. Keep the two byte-identical.
_run_gate "adapter drift (git diff --exit-code)" \
  git diff --exit-code -- .claude .codex .cursor .gemini .kimi .opencode .omp .pi .hermes .openclaw .copilot .github/copilot-instructions.md .github/agents .github/prompts .github/instructions .github/hooks .github/skills

# --- symlink + methodology drift ------------------------------------------
if _require_file scripts/check-symlinks-relative.sh; then
  _run_gate "check-symlinks-relative.sh" "$BASH5" scripts/check-symlinks-relative.sh
fi
if _require_file scripts/check-methodology-drift.sh; then
  _run_gate "check-methodology-drift.sh" "$BASH5" scripts/check-methodology-drift.sh
fi

# --- codex skill sync (the cheap half only) --------------------------------
# codex-skill-sync.yml's own bootstrap step comes first; the full
# scripts/test/test_codex_skills.py suite is NOT run here - see the NOT-RUN
# block at the end.
if _require_file .codex/lib/prompt-wrappers.py; then
  _run_gate "codex prompt-wrapper bootstrap" \
    python3 .codex/lib/prompt-wrappers.py build --repo .
fi
if _require_file scripts/check-codex-skill-sync.sh; then
  _run_gate "check-codex-skill-sync.sh" "$BASH5" scripts/check-codex-skill-sync.sh
fi

# --- no-planning-docs.yml --------------------------------------------------
_run_snippet "docs/planning must not be tracked" '
tracked=$(git ls-files docs/planning/)
if [ -n "$tracked" ]; then
  echo "docs/planning/ files are tracked in git. Remove with: git rm --cached docs/planning/<file>" >&2
  echo "$tracked" >&2
  exit 1
fi
echo "OK: no docs/planning/ files are tracked."'

# --- python bin tests ------------------------------------------------------
_run_gate "pytest bin/tests/" \
  python3 -m pytest bin/tests/ -q --timeout=60 --timeout-method=thread

# --- bin-tests.yml collected-count floors ----------------------------------
# Derived from the workflow, never hand-copied: each floor lives in exactly
# one place (the workflow step), so a bumped pin cannot drift from a stale
# duplicate here.
_FLOOR_LINES="$(grep -F -- '--collect-only -q' "$REPO_ROOT/.github/workflows/bin-tests.yml" 2>/dev/null \
  | sed 's/^[[:space:]]*//')"
if [ -z "$_FLOOR_LINES" ]; then
  echo "check-local: found zero --collect-only floor steps in bin-tests.yml - discovery is broken, not clean" >&2
  FAILED="${FAILED}collected-count floor discovery matched zero steps
"
else
  _split_lines "$_FLOOR_LINES"
  _floor_n=0
  for _floor in "${_SPLIT[@]}"; do
    _floor_n=$((_floor_n + 1))
    _run_snippet "collected-count floor #${_floor_n}" "$_floor"
  done
fi

# --- shell/js/python test loops, exactly CI's sets --------------------------
_loop_from_discovery "bin-sh-tests"       "$BASH5" list_bin_sh_tests
_loop_from_discovery "hooks-js-tests"     node     list_hooks_js_tests
_loop_from_discovery "hooks-sh-tests"     "$BASH5" list_hooks_sh_tests
_loop_from_discovery "hooks-python-tests" python3  list_hooks_py_tests

# hooks-tests.yml :: wrap-lock-tests. list_hooks_js_tests EXCLUDES these two
# because a separate CI job owns them; excluding them here as well would mean
# two files behind a required check never run locally at all. Kept literal and
# adjacent to the exclusion for exactly that reason.
_run_file_loop "wrap-lock-tests" node \
  hooks/tests/test-wrap-acquire-lock.js \
  hooks/tests/test-wrap-release-lock.js

# --- budget gates ----------------------------------------------------------
# Derived, never hand-listed: every scripts/*.sh that sources the shared
# budget-gate library is a budget gate, so a newly added one is picked up
# without editing this file. Includes the 4 adapter skill-embed budgets.
BUDGET_GATES="$(grep -rln '^source .*lib/budget-gate.sh' scripts/*.sh 2>/dev/null | LC_ALL=C sort)"
if [ -z "$BUDGET_GATES" ]; then
  echo "check-local: budget-gate discovery matched zero scripts - discovery is broken, not clean" >&2
  FAILED="${FAILED}budget-gate discovery matched zero scripts
"
else
  _split_lines "$BUDGET_GATES"
  _run_file_loop "budget gates" "$BASH5" "${_SPLIT[@]}"
fi

# --- remaining standalone gates -------------------------------------------
if _require_file scripts/check-command-arg-substitution.py; then
  _run_gate "check-command-arg-substitution.py" \
    python3 scripts/check-command-arg-substitution.py content/commands
fi
if _require_file scripts/check-no-false-umbrella-claims.sh; then
  _run_gate "check-no-false-umbrella-claims.sh" "$BASH5" scripts/check-no-false-umbrella-claims.sh
fi
if _require_file scripts/check-corpus-coverage.py; then
  _run_gate "check-corpus-coverage.py" python3 scripts/check-corpus-coverage.py
fi

# ---------------------------------------------------------------------------
# Coverage gap, printed on EVERY run. A green run above means "the covered set
# passed", not "CI will be green"; these three are the difference. Each is
# excluded on cost, not on judgement that it does not matter.
# ---------------------------------------------------------------------------
print_not_run_block() {
  cat <<'NOTRUN'

NOT RUN LOCALLY (run in CI):
  These gates are excluded on cost, not because they are optional. A green run
  above does NOT mean CI will be green. Run any of them by hand when your
  change touches what it covers.

  codex-skill-sync.yml - the full Codex skill suite (~8-20 min in CI):
      python3 scripts/test/test_codex_skills.py
      python3 scripts/test/test_codex_skills.py --clean-clone
      bash .codex/build.sh && git diff --exit-code
  slides-sync.yml - slide build and overflow checks (needs the slides toolchain):
      npm ci --prefix scripts --no-audit --no-fund
      bash scripts/build-slides.sh && git diff --exit-code -- docs/slides
      bash scripts/check-slide-overflow.sh
      bash scripts/check-slide-overflow-live-selftest.sh
  gitleaks.yml - full-history secret scan (whole-repo history, slow):
      gitleaks git . --redact=100 --verbose --exit-code 1
NOTRUN
}

RUN_END=$(date +%s)
echo
echo "total: $((RUN_END - RUN_START))s"
if [ -n "$FAILED" ]; then
  echo
  echo "FAILED gates:"
  printf '%s' "$FAILED" | sed 's/^/  - /'
  print_not_run_block
  exit 1
fi
echo "all covered gates passed."
print_not_run_block
exit 0
