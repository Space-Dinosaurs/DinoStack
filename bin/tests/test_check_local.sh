#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Regression guard for scripts/check-local.sh, the single local
#          entry point for CI's gate set.
#
#          The properties worth defending are the ones an operator acts on:
#
#          1. Exit 2 (TOOLCHAIN PREFLIGHT FAILED) must never be conflated
#             with exit 1 (a gate failed). A 2 means nothing was tested and
#             says nothing about the change, and it must run no gate.
#          2. A failing gate must produce exit 1 and name itself, rather than
#             being swallowed by the collect-all-failures harness.
#          3. hooks/tests/test-wrap-acquire-lock.js and
#             test-wrap-release-lock.js must actually be INVOKED. The
#             discovery library deliberately excludes them from
#             list_hooks_js_tests (a separate CI job owns them), and the first
#             version of this runner inherited that exclusion without
#             replacing it - leaving two files behind a required CI check
#             running in no local gate at all, silently. The two scenarios
#             below break each file in turn and require the run to go red.
#          4. The NOT-RUN-LOCALLY block must print on BOTH the pass and the
#             fail path. It is the only thing standing between "the covered
#             set passed" and a reader concluding "CI will be green".
#
#          Scenarios run against a scratch FIXTURE repo - a miniature of this
#          repo's layout with stub gates - so a scenario costs a second
#          instead of the ~40 minutes a real full run costs, and so a gate
#          can be made to fail on purpose without breaking anything real.
#
# Public API: bash bin/tests/test_check_local.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, git (the drift gates diff a real work tree, so
#                the fixture is a real repo - no soft-skip; CI always provides
#                git). python3 with pytest (the fixture runs a real pytest
#                invocation over one trivial test). node (the wrap-lock and
#                hooks-js scenarios execute real .js files, and the preflight
#                probes `require('espree')` against the fixture's own stub).
#                Under CI a missing dependency FAILS rather than skips - a
#                silently-skipped assertion is indistinguishable from a
#                passing one.
#
# Downstream consumers: CI (the bin-sh-tests job auto-discovers
#                       bin/tests/test_*.sh).
#
# Failure modes: each scenario names itself, the exit code it expected, and
#                the exit code plus output it observed.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$REPO_ROOT/scripts/check-local.sh"
LIB="$REPO_ROOT/scripts/lib/ci-test-discovery.sh"

PASS=0
FAIL=0
_pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
_fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

for f in "$GATE" "$LIB"; do
  if [ ! -f "$f" ]; then
    echo "FAIL: required input not found: $f"
    exit 1
  fi
done

_require_tool() {
  # A tool this suite genuinely needs. Hard-fail under CI rather than skip:
  # AGENTS.md records three separate instances of a `command -v` guard turning
  # an unrun assertion into a green job.
  if command -v "$1" >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${CI:-}" ]; then
    _fail "$1 absent on PATH in CI - this suite's assertions cannot be skipped here"
    return 1
  fi
  echo "SKIP: $1 not found on PATH - skipping the scenarios that need it"
  return 1
}

_require_tool git || exit 1
_require_tool python3 || exit 1
_require_tool node || exit 1
if ! python3 -c "import pytest" >/dev/null 2>&1; then
  if [ -n "${CI:-}" ]; then
    _fail "pytest absent in CI - this suite's assertions cannot be skipped here"
    exit 1
  fi
  echo "SKIP: pytest not importable - skipping"
  exit 0
fi

TMPROOT="$(mktemp -d -t check-local-test.XXXXXX)"
cleanup() { rm -rf "$TMPROOT"; }
trap cleanup EXIT

# Resolve a bash >= 5 the same way check-local.sh does, for use as the
# interpreter under a stubbed PATH.
REAL_BASH5=""
for c in "$(command -v bash)" /usr/local/bin/bash /opt/homebrew/bin/bash; do
  [ -n "$c" ] && [ -x "$c" ] || continue
  if [ "$("$c" -c 'echo ${BASH_VERSINFO[0]}' 2>/dev/null)" -ge 5 ] 2>/dev/null; then
    REAL_BASH5="$c"
    break
  fi
done
if [ -z "$REAL_BASH5" ]; then
  if [ -n "${CI:-}" ]; then
    _fail "no bash >= 5 available in CI"
    exit 1
  fi
  echo "SKIP: no bash >= 5 on this machine - run 'brew install bash'"
  exit 0
fi

# The 17 pathspec entries adapter-sync.yml's existence step requires. Read out
# of check-local.sh itself so the fixture cannot go stale against the gate.
ADAPTER_PATHS="$(sed -n '/^for p in \.claude \.codex/,/^done/p' "$GATE" \
  | tr ' \\' '\n\n' | sed 's/;$//' | grep -E '^(\.[a-z]|\.github/)' )"
ADAPTER_PATH_COUNT="$(printf '%s\n' "$ADAPTER_PATHS" | grep -c .)"
if [ "$ADAPTER_PATH_COUNT" -eq 17 ]; then
  _pass "extracted all 17 adapter-sync pathspec entries out of check-local.sh"
else
  _fail "expected 17 adapter-sync pathspec entries, extracted $ADAPTER_PATH_COUNT - the fixture would be built against the wrong set:
$ADAPTER_PATHS"
fi

# ---------------------------------------------------------------------------
# Fixture: a miniature of this repo, with stub gates.
# ---------------------------------------------------------------------------
build_fixture() {
  # build_fixture <dir>
  local d="$1"
  mkdir -p "$d/scripts/lib" "$d/scripts/test" "$d/bin/tests" "$d/hooks/tests" \
           "$d/tests" "$d/.claude/tests" "$d/.cursor/tests" "$d/content/commands" \
           "$d/content/agents" "$d/.codex/lib" "$d/.github/workflows"

  cp "$GATE" "$d/scripts/check-local.sh"
  cp "$LIB" "$d/scripts/lib/ci-test-discovery.sh"

  # The preflight probes `require('espree')`, which node resolves by walking
  # up from cwd. The fixture is outside the real repo, so it needs its own
  # trivial copy - self-contained, rather than borrowing the host's install.
  mkdir -p "$d/node_modules/espree"
  printf '{"name":"espree","version":"0.0.0","main":"index.js"}\n' > "$d/node_modules/espree/package.json"
  printf 'module.exports = {};\n' > "$d/node_modules/espree/index.js"

  # Every pathspec entry adapter-sync.yml's existence step checks.
  local p
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    case "$p" in
      *.md) mkdir -p "$d/$(dirname "$p")"; printf 'stub\n' > "$d/$p" ;;
      *)    mkdir -p "$d/$p"; printf 'stub\n' > "$d/$p/.keep" ;;
    esac
  done <<EOF
$ADAPTER_PATHS
EOF

  # Stub gates. Each is trivially green unless a scenario rewrites it.
  local s
  for s in build-all.sh check-symlinks-relative.sh check-methodology-drift.sh \
           check-no-false-umbrella-claims.sh stamp-agent-fragments.sh \
           check-codex-skill-sync.sh; do
    printf '#!/usr/bin/env bash\necho "stub %s ok"\nexit 0\n' "$s" > "$d/scripts/$s"
    chmod +x "$d/scripts/$s"
  done
  for s in check-command-arg-substitution.py check-corpus-coverage.py; do
    printf '#!/usr/bin/env python3\nprint("stub %s ok")\n' "$s" > "$d/scripts/$s"
    chmod +x "$d/scripts/$s"
  done
  printf '#!/usr/bin/env python3\nprint("stub prompt-wrappers ok")\n' > "$d/.codex/lib/prompt-wrappers.py"
  printf 'stub agent\n' > "$d/content/agents/stub.md"

  # One budget gate, discovered the same way check-local.sh discovers them:
  # any scripts/*.sh whose line 1-column-0 sources the shared library.
  printf '# stub budget-gate library\n' > "$d/scripts/lib/budget-gate.sh"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'source "$(dirname "${BASH_SOURCE[0]}")/lib/budget-gate.sh"\n'
    printf 'echo "stub budget gate ok"\nexit 0\n'
  } > "$d/scripts/check-stub-budget.sh"
  chmod +x "$d/scripts/check-stub-budget.sh"

  # A bin-tests.yml carrying one real --collect-only floor step, since
  # check-local.sh derives the floors from the workflow rather than
  # hardcoding them.
  cat > "$d/.github/workflows/bin-tests.yml" <<'WF'
jobs:
  python-bin-tests:
    steps:
      - name: floor collected test_stub.py count at 1
        run: |
          python3 -m pytest bin/tests/test_stub.py --collect-only -q | grep -c '::test_' | awk '{ if ($1 < 1) { print "expected >= 1"; exit 1 } }'
WF

  # bin/tests: one shell test and one python test (pytest exits 5 on an empty
  # collection, so the fixture must collect at least one).
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/bin/tests/test_stub.sh"
  printf 'def test_stub():\n    assert True\n' > "$d/bin/tests/test_stub.py"

  # The four named orphans bin-tests.yml appends.
  local o
  for o in tests/bootstrap-guard.test.sh scripts/test/repo-dir.test.sh \
           .claude/tests/install-converge.test.sh .cursor/tests/install-converge.test.sh; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$d/$o"
  done

  # hooks/tests: the two wrap-lock files must exist (the discovery library
  # hard-fails on a quarantine arm pointing at nothing, and check-local.sh
  # runs them as their own gate), plus one runnable file per language.
  printf 'process.exit(0);\n' > "$d/hooks/tests/test-stub.js"
  printf 'process.exit(0);\n' > "$d/hooks/tests/test-wrap-acquire-lock.js"
  printf 'process.exit(0);\n' > "$d/hooks/tests/test-wrap-release-lock.js"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/hooks/tests/test-stub.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/hooks/tests/test-version-check-core-repo-dir.sh"
  printf 'raise SystemExit(0)\n' > "$d/hooks/tests/test-stub.py"

  # A real work tree, so the drift gates have something to be clean against.
  ( cd "$d" \
    && git init -q . \
    && git config user.email t@example.com \
    && git config user.name t \
    && git add -A \
    && git commit -qm fixture ) >/dev/null 2>&1
}

run_fixture() {
  # run_fixture <dir> [args...] - prints output, returns the gate's exit code.
  local d="$1"
  shift
  ( cd "$d" && "$REAL_BASH5" scripts/check-local.sh "$@" ) 2>&1
}

# ---------------------------------------------------------------------------
# Scenario group A: gate outcomes (real toolchain, stub gates).
# ---------------------------------------------------------------------------
FX="$TMPROOT/pass"
build_fixture "$FX"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 0 ]; then
  _pass "all-green fixture exits 0"
else
  _fail "all-green fixture expected exit 0, got $rc:
$out"
fi
if printf '%s' "$out" | grep -q "NOT RUN LOCALLY (run in CI):"; then
  _pass "the NOT-RUN-LOCALLY block prints on the passing path"
else
  _fail "no NOT-RUN-LOCALLY block on the passing path:
$out"
fi
for needle in "test_codex_skills.py" "build-slides.sh" "gitleaks git ."; do
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    _pass "the NOT-RUN block names the exact command '$needle'"
  else
    _fail "the NOT-RUN block does not name '$needle':
$out"
  fi
done
if ! printf '%s' "$out" | grep -q "every gate CI runs"; then
  _pass "the runner does not claim to run every gate CI runs"
else
  _fail "the runner still claims to run every gate CI runs:
$out"
fi

FX="$TMPROOT/failgate"
build_fixture "$FX"
printf '#!/usr/bin/env bash\necho "deliberate build-all failure"\nexit 1\n' > "$FX/scripts/build-all.sh"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 1 ]; then
  _pass "a deliberately failing gate exits 1 (not 2)"
else
  _fail "a failing gate expected exit 1, got $rc:
$out"
fi
if printf '%s' "$out" | grep -q "build-all.sh"; then
  _pass "the failure summary names the gate that failed"
else
  _fail "the failure summary did not name build-all.sh:
$out"
fi
if printf '%s' "$out" | grep -q "NOT RUN LOCALLY (run in CI):"; then
  _pass "the NOT-RUN-LOCALLY block prints on the failing path too"
else
  _fail "no NOT-RUN-LOCALLY block on the failing path:
$out"
fi

FX="$TMPROOT/failsubtest"
build_fixture "$FX"
printf '#!/usr/bin/env bash\necho "deliberate sub-test failure"\nexit 3\n' > "$FX/bin/tests/test_stub.sh"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "bin-sh-tests"; then
  _pass "a failing file inside a per-file loop exits 1 and names the loop"
else
  _fail "expected exit 1 naming bin-sh-tests, got $rc:
$out"
fi

# ---------------------------------------------------------------------------
# Scenario group A2: the wrap-lock pair is genuinely invoked.
#
# list_hooks_js_tests excludes both files by design. Breaking each in turn and
# requiring a red run is the only way to prove the runner did not inherit that
# exclusion. Asserting on the printed label alone would pass against a runner
# that prints the label and runs nothing.
# ---------------------------------------------------------------------------
for wl in test-wrap-acquire-lock.js test-wrap-release-lock.js; do
  FX="$TMPROOT/wraplock_${wl%.js}"
  build_fixture "$FX"
  printf 'console.error("deliberate %s failure");\nprocess.exit(1);\n' "$wl" > "$FX/hooks/tests/$wl"
  out="$(run_fixture "$FX")"
  rc=$?
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "wrap-lock-tests"; then
    _pass "hooks/tests/$wl is actually invoked (breaking it turns the run red)"
  else
    _fail "hooks/tests/$wl is not invoked by check-local.sh - expected exit 1 naming wrap-lock-tests, got $rc:
$out"
  fi
done

# Belt and braces: the pair must be excluded from the hooks-js loop (so it is
# not double-counted) while still being named by the runner.
FX="$TMPROOT/wraplock_shape"
build_fixture "$FX"
out="$(run_fixture "$FX")"
if printf '%s' "$out" | grep -q "wrap-lock-tests (2 files)"; then
  _pass "the wrap-lock gate runs exactly the 2 files hooks-tests.yml's job runs"
else
  _fail "expected a 'wrap-lock-tests (2 files)' gate line:
$out"
fi

# A gate script CI runs but that is missing locally is a failure, never a skip.
FX="$TMPROOT/missinggate"
build_fixture "$FX"
rm -f "$FX/scripts/check-corpus-coverage.py"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "check-corpus-coverage.py"; then
  _pass "a missing gate script fails (exit 1) rather than silently skipping"
else
  _fail "expected exit 1 naming the missing gate script, got $rc:
$out"
fi

# A missing adapter-sync pathspec entry must fail: git diff exits 0 on a
# nonexistent pathspec, so without this step the drift check asserts nothing.
FX="$TMPROOT/pathspec"
build_fixture "$FX"
rm -rf "$FX/.hermes"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "pathspec entr"; then
  _pass "a missing adapter-sync pathspec entry fails the run"
else
  _fail "expected exit 1 naming the pathspec check, got $rc:
$out"
fi

# The collected-count floors are derived from bin-tests.yml, so a workflow
# with no such step is broken discovery, not a clean run.
FX="$TMPROOT/nofloors"
build_fixture "$FX"
printf 'jobs: {}\n' > "$FX/.github/workflows/bin-tests.yml"
out="$(run_fixture "$FX")"
rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "discovery is broken, not clean"; then
  _pass "zero collected-count floor steps reads as broken discovery, not a clean run"
else
  _fail "expected exit 1 naming broken floor discovery, got $rc:
$out"
fi

# ---------------------------------------------------------------------------
# Scenario group B: preflight misses. Each must exit 2, not 1, and run no gate.
#
# PATH is replaced wholesale with a stub dir holding thin wrappers for exactly
# the tools the runner uses, so "missing" means genuinely absent rather than
# present-but-broken.
# ---------------------------------------------------------------------------
# Wrappers for exactly the tools check-local.sh and its stub gates use: the
# six the preflight itself probes, plus the coreutils the gate harness needs
# once preflight passes.
STUB_TOOLS="sed head sort dirname basename node python3 gh zsh gitleaks \
mktemp cat date grep tr wc git rm mkdir chmod touch env uname awk cut expr diff"

make_stub_path() {
  # make_stub_path <dir> <tool-to-omit-or-empty>
  local d="$1" omit="${2:-}"
  local t real
  mkdir -p "$d"
  for t in $STUB_TOOLS; do
    [ "$t" = "$omit" ] && continue
    real="$(command -v "$t" 2>/dev/null)" || real=""
    [ -n "$real" ] || continue
    printf '#!/bin/sh\nexec %s "$@"\n' "$real" > "$d/$t"
    chmod +x "$d/$t"
  done
}

# Overridable by the one scenario that needs the bash >= 5 lookup to find
# nothing at all.
BASH5_CANDS="$REAL_BASH5"

run_preflight() {
  # run_preflight <fixture> <stubpath>
  local fx="$1" sp="$2"
  ( cd "$fx" && env -i HOME="$HOME" PATH="$sp" \
      DS_CHECK_LOCAL_BASH5_CANDIDATES="$BASH5_CANDS" \
      "$REAL_BASH5" scripts/check-local.sh ) 2>&1
}

assert_preflight_miss() {
  # assert_preflight_miss <label> <stubdir-omit> <needle>
  local label="$1" omit="$2" needle="$3"
  local fx="$TMPROOT/pf_${label// /_}"
  build_fixture "$fx"
  # The stub build-all.sh leaves a marker; a preflight failure must run no gate.
  printf '#!/usr/bin/env bash\ntouch "$(dirname "$0")/../GATE_RAN"\nexit 0\n' > "$fx/scripts/build-all.sh"
  local sp="$TMPROOT/stubpath_${label// /_}"
  make_stub_path "$sp" "$omit"
  local out rc
  out="$(run_preflight "$fx" "$sp")"
  rc=$?
  if [ "$rc" -eq 2 ]; then
    _pass "preflight miss [$label] exits 2, not 1"
  else
    _fail "preflight miss [$label] expected exit 2, got $rc:
$out"
  fi
  if printf '%s' "$out" | grep -q -- "$needle"; then
    _pass "preflight miss [$label] prints the install command '$needle'"
  else
    _fail "preflight miss [$label] did not print '$needle':
$out"
  fi
  if [ ! -e "$fx/GATE_RAN" ]; then
    _pass "preflight miss [$label] ran no gate"
  else
    _fail "preflight miss [$label] ran a gate despite failing preflight"
  fi
}

assert_preflight_miss "zsh missing"      zsh      "brew install zsh"
assert_preflight_miss "gitleaks missing" gitleaks "brew install gitleaks"
assert_preflight_miss "node missing"     node     "brew install node"

# node present but espree unresolvable - the exact dependency three engineers
# re-diagnosed independently in one session.
FX="$TMPROOT/pf_espree"
build_fixture "$FX"
printf '#!/usr/bin/env bash\ntouch "$(dirname "$0")/../GATE_RAN"\nexit 0\n' > "$FX/scripts/build-all.sh"
SP="$TMPROOT/stubpath_espree"
make_stub_path "$SP" node
printf '#!/bin/sh\nexit 1\n' > "$SP/node"
chmod +x "$SP/node"
out="$(run_preflight "$FX" "$SP")"
rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q "npm ci" && [ ! -e "$FX/GATE_RAN" ]; then
  _pass "preflight miss [espree unresolvable] exits 2, says 'npm ci', and runs no gate"
else
  _fail "expected exit 2 naming 'npm ci', got $rc:
$out"
fi

# python3 present but a module missing.
FX="$TMPROOT/pf_pymod"
build_fixture "$FX"
printf '#!/usr/bin/env bash\ntouch "$(dirname "$0")/../GATE_RAN"\nexit 0\n' > "$FX/scripts/build-all.sh"
SP="$TMPROOT/stubpath_pymod"
make_stub_path "$SP" python3
printf '#!/bin/sh\nexit 1\n' > "$SP/python3"
chmod +x "$SP/python3"
out="$(run_preflight "$FX" "$SP")"
rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q "pip install pytest pytest-timeout pyyaml" && [ ! -e "$FX/GATE_RAN" ]; then
  _pass "preflight miss [python modules] exits 2, says the pip command, and runs no gate"
else
  _fail "expected exit 2 naming the pip install command, got $rc:
$out"
fi

# gh present but below the 2.52 floor.
FX="$TMPROOT/pf_gh"
build_fixture "$FX"
printf '#!/usr/bin/env bash\ntouch "$(dirname "$0")/../GATE_RAN"\nexit 0\n' > "$FX/scripts/build-all.sh"
SP="$TMPROOT/stubpath_gh"
make_stub_path "$SP" gh
printf '#!/bin/sh\necho "gh version 2.40.1 (2024-01-01)"\n' > "$SP/gh"
chmod +x "$SP/gh"
out="$(run_preflight "$FX" "$SP")"
rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q "brew upgrade gh" && [ ! -e "$FX/GATE_RAN" ]; then
  _pass "preflight miss [gh below 2.52] exits 2, says 'brew upgrade gh', and runs no gate"
else
  _fail "expected exit 2 naming 'brew upgrade gh', got $rc:
$out"
fi

# A gh at or above the floor is accepted (the comparison is numeric, not
# lexicographic - 2.100 must not read as older than 2.52).
FX="$TMPROOT/pf_gh_ok"
build_fixture "$FX"
SP="$TMPROOT/stubpath_gh_ok"
make_stub_path "$SP" gh
printf '#!/bin/sh\necho "gh version 2.100.0 (2026-09-03)"\n' > "$SP/gh"
chmod +x "$SP/gh"
out="$(run_preflight "$FX" "$SP")"
rc=$?
if [ "$rc" -ne 2 ]; then
  _pass "gh 2.100.0 passes the >= 2.52 floor (numeric compare, not lexicographic)"
else
  _fail "gh 2.100.0 was rejected by the >= 2.52 floor:
$out"
fi

# No bash >= 5 anywhere: not on PATH, and the candidate list points at nothing.
FX="$TMPROOT/pf_bash"
build_fixture "$FX"
printf '#!/usr/bin/env bash\ntouch "$(dirname "$0")/../GATE_RAN"\nexit 0\n' > "$FX/scripts/build-all.sh"
SP="$TMPROOT/stubpath_bash"
make_stub_path "$SP" ""
BASH5_CANDS="$TMPROOT/no-such-bash"
out="$(run_preflight "$FX" "$SP")"
rc=$?
BASH5_CANDS="$REAL_BASH5"
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q "brew install bash" && [ ! -e "$FX/GATE_RAN" ]; then
  _pass "preflight miss [no bash >= 5] exits 2, says 'brew install bash', and runs no gate"
else
  _fail "expected exit 2 naming 'brew install bash', got $rc:
$out"
fi

# An unknown argument is a usage error, which is also exit 2 (nothing tested).
# --fast used to be accepted here and was removed: it skipped the adapter-drift
# detection while measurably saving nothing, so it must now be rejected like
# any other unknown option rather than silently ignored.
FX="$TMPROOT/badarg"
build_fixture "$FX"
for bad in --nope --fast; do
  out="$(run_fixture "$FX" "$bad")"
  rc=$?
  if [ "$rc" -eq 2 ]; then
    _pass "'$bad' exits 2 (nothing was tested), not 1"
  else
    _fail "'$bad' expected exit 2, got $rc:
$out"
  fi
done

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
