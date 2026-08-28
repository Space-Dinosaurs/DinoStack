#!/usr/bin/env bash
# Purpose: Regression guard for scripts/gate-provenance.sh (DS-182 Major 3).
#          Runs it against the real repo (not a scratch fixture - D1/D2/D3
#          read real .github/workflows/*.yml and module-manifest headers,
#          so a fixture would only prove the fixture's own shape) for the
#          six paths the DS-182 plan classifies by hand, asserting each
#          resolves to the documented outcome AND cites the rule (D1/D2/D3)
#          expected to fire. Also covers the usage-error path and a D2
#          instance (CHANGELOG.md) distinct from the D1/D3 paths above.
#
# Public API: ./bin/tests/test_gate_provenance.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, scripts/gate-provenance.sh, git (transitively, via
#                the script under test), the real .github/workflows/*.yml
#                and scripts/check-methodology-drift.sh module-manifest
#                header this suite's expectations were derived from - if
#                either drifts (a workflow's pathspec narrows, or the
#                methodology-drift script's manifest wording changes),
#                update this suite's expectations in the same commit.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or output does not match the expected
#                shape -> FAIL naming the scenario and what was observed.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/gate-provenance.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

PASS=0
FAIL=0

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

# _assert_classification <path> <expected-prefix> <expected-rule-substring>
_assert_classification() {
  local target="$1" expected_prefix="$2" expected_rule="$3"
  local out rc
  out="$(cd "$REPO_DIR" && bash scripts/gate-provenance.sh "$target" 2>&1)"
  rc=$?

  if [[ $rc -eq 0 ]]; then
    _pass "gate-provenance.sh exits 0 for '$target'"
  else
    _fail "gate-provenance.sh exited $rc for '$target' (expected 0): $out"
  fi

  if [[ "$out" == "$expected_prefix:"* ]]; then
    _pass "'$target' classifies as $expected_prefix"
  else
    _fail "'$target' classified as [$out], expected to start with '$expected_prefix:'"
  fi

  if [[ -n "$expected_rule" ]]; then
    if echo "$out" | grep -qF "$expected_rule"; then
      _pass "'$target' cites the expected rule ($expected_rule)"
    else
      _fail "'$target' did not cite the expected rule ($expected_rule): $out"
    fi
  fi
}

# --- Direct zsh invocation (DS-182 round-3, discovered mid-round) ---
#
# Every _assert_classification call above/below hardcodes `bash
# scripts/gate-provenance.sh ...` regardless of which shell interprets
# THIS test file - so `zsh bin/tests/test_gate_provenance.sh` had never
# once actually run the gate script itself under zsh, only under a bash
# subshell forked from zsh. Direct `zsh scripts/gate-provenance.sh`
# invocation surfaced three real, pre-existing defects the bash-wrapped
# suite could never have caught: (1) a raw
# "$WORKFLOWS_DIR"/*.yaml glob aborts the whole script when it has zero
# matches (zsh's default NOMATCH behavior, unlike bash's leave-unexpanded
# default) - this repo has no *.yaml workflow files, only *.yml; (2) zsh
# arrays are 1-indexed by default, so a literal `${arr[0]}` read is
# invalid and aborts with "parameter not set"; (3) zsh does not
# word-split an unquoted plain variable expansion by default (unlike
# bash), so `for tok in $pathspec_raw`/`for tok in $args` iterated ONCE
# over the whole multi-token string instead of splitting on whitespace,
# silently breaking D1's pathspec match and D2's `git add` arg match
# under zsh specifically. All three are fixed in this round; this
# section is the regression guard that actually exercises the fix by
# invoking the real script under `zsh`, not a mirror.
_assert_classification_zsh() {
  local target="$1" expected_prefix="$2" expected_rule="$3"
  local out rc
  # An array, not a bare "timeout 20" scalar: this test file may itself
  # be interpreted by zsh (`zsh bin/tests/test_gate_provenance.sh`), and
  # zsh does not word-split an unquoted plain variable expansion by
  # default - the exact same class of bug this test exists to guard
  # against in scripts/gate-provenance.sh itself. "${timeout_cmd[@]}"
  # expands to zero words when the array is empty, in both shells.
  local -a timeout_cmd=()
  if command -v timeout >/dev/null 2>&1; then
    timeout_cmd=(timeout 20)
  elif command -v gtimeout >/dev/null 2>&1; then
    timeout_cmd=(gtimeout 20)
  fi
  # Branches on array length rather than a bare "${timeout_cmd[@]}" or the
  # usual "${arr[@]+"${arr[@]}"}" bash-3.2-empty-array guard: under
  # `set -u`, bash 3.2 (this repo's binding shell target) treats an EMPTY
  # array's "${arr[@]}" as an unbound-variable error (AGENTS.md documents
  # the same class of bug at scripts/check-command-file-budget.sh:83's
  # `command -v` guard) - but the standard bash guard idiom itself
  # misbehaves under zsh (measured: it expands to a single EMPTY-STRING
  # word rather than zero words, so `"" echo hi` then fails with
  # "permission denied" trying to execute an empty command). Neither
  # single form is safe in both shells at once, so this checks
  # "${#timeout_cmd[@]}" first instead.
  if [ "${#timeout_cmd[@]}" -gt 0 ]; then
    out="$(cd "$REPO_DIR" && "${timeout_cmd[@]}" zsh scripts/gate-provenance.sh "$target" 2>&1)"
  else
    out="$(cd "$REPO_DIR" && zsh scripts/gate-provenance.sh "$target" 2>&1)"
  fi
  rc=$?

  if [[ $rc -eq 0 ]]; then
    _pass "zsh direct invocation: gate-provenance.sh exits 0 for '$target'"
  else
    _fail "zsh direct invocation: gate-provenance.sh exited $rc for '$target' (expected 0): $out"
  fi

  if [[ "$out" == "$expected_prefix:"* ]]; then
    _pass "zsh direct invocation: '$target' classifies as $expected_prefix"
  else
    _fail "zsh direct invocation: '$target' classified as [$out], expected to start with '$expected_prefix:'"
  fi

  if [[ -n "$expected_rule" ]]; then
    if echo "$out" | grep -qF "$expected_rule"; then
      _pass "zsh direct invocation: '$target' cites the expected rule ($expected_rule)"
    else
      _fail "zsh direct invocation: '$target' did not cite the expected rule ($expected_rule): $out"
    fi
  fi
}

_assert_classification_zsh ".codex/skill-compatibility.yml" "DERIVED" "D1:"
_assert_classification_zsh "CHANGELOG.md" "DERIVED" "D2:"
_assert_classification_zsh "scripts/.methodology-baseline.sha256" "DERIVED" "D3:"

# --- DERIVED via D1 (adapter-sync.yml's .claude/.codex pathspec) ---
_assert_classification ".codex/skill-compatibility.yml" "DERIVED" "D1:"
_assert_classification ".claude/skills/dinostack/SKILL.md" "DERIVED" "D1:"

# --- DERIVED via D1 (slides-sync.yml's docs/slides pathspec) ---
_assert_classification "docs/slides/foo.html" "DERIVED" "D1:"

# --- DERIVED via D3 (check-methodology-drift.sh's manifest "writes" line) ---
_assert_classification "scripts/.methodology-baseline.sha256" "DERIVED" "D3:"

# --- DERIVED via D2 (changelog-publish.yml's git add + git commit pair) ---
_assert_classification "CHANGELOG.md" "DERIVED" "D2:"

# --- AUTHORED (no rule fires) ---
#
# DS-182 round-3 Major 2 fixed D4's [[:space:]] regex (previously \s, a
# GNU-awk-only extension that always yielded empty output under this repo's
# actual awk, so D4's clone-and-execute block was silently skipped every
# time). That fix has a real cost here: ANY path reaching D4 - which every
# AUTHORED verdict does, since AUTHORED means no D1/D2/D3 rule matched - now
# genuinely clones the repo and runs codex-skill-sync.yml's 5 real generator
# commands (measured 6m42s for one such run this round). Gating these two
# behind the same RUN_SLOW_D4_TEST flag as the dedicated D4 execution test
# below, rather than letting every default `bin/tests` run pay ~7 minutes
# twice, is the direct, unavoidable consequence of the correctness fix, not
# a scope expansion - D4's own runtime cost is inherent to its design (it
# must run whatever CI ran before the diff assertion it audits) and is not
# redesigned here.
if [[ "${RUN_SLOW_D4_TEST:-}" == "1" ]]; then
  _assert_classification "content/commands/ds-implement-ticket.md" "AUTHORED" ""
  _assert_classification "content/templates/claude-managed-content.md" "AUTHORED" ""
else
  echo "SKIP: 2 AUTHORED assertions that now reach D4's real clone-and-execute path (set RUN_SLOW_D4_TEST=1 to run; ~7 minutes each)"
fi

# --- D3 false-positive regression (DS-182 round-3 Minor) ---
#
# D3's TARGET reaching AUTHORED (no D1/D2/D3 rule matched) also now falls
# through to D4's expensive clone-and-execute path, so these three targets
# can't be checked via the full script without paying that cost too (see
# above). Mirrors scripts/gate-provenance.sh's D3 block verbatim, run
# against the real repo, to prove the boundary-anchoring and self-exclusion
# fixes hold without invoking D4.
_test_d3_no_false_positive() {
  local target="$1" label="$2"
  local d3_result="" file rest lineno line raw_tok tok match

  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    file="${match%%:*}"
    rest="${match#*:}"
    lineno="${rest%%:*}"
    line="${rest#*:}"
    # Line-content skip, not a hardcoded self-file-path skip: the D3
    # search invocation's own literal text - "writes " next to
    # 'scripts/*'/'bin/*' - self-matches in ANY file that quotes or
    # mirrors it verbatim, including this test function itself (its own
    # git grep call two lines below). Must match
    # scripts/gate-provenance.sh's D3 block exactly.
    case "$line" in
      *'git grep -n "writes "'*) continue ;;
    esac
    for raw_tok in $(printf '%s' "$line" | grep -oE '[A-Za-z0-9._/-]+'); do
      tok="${raw_tok%.}"
      [[ -z "$tok" ]] && continue
      case "$tok" in
        */*|*.*) ;;
        *) continue ;;
      esac
      if [[ "$target" == "$tok" || "$target" == "$tok"/* ]]; then
        d3_result="$file:$lineno declares a write to '$tok'"
        break
      fi
    done
    [[ -n "$d3_result" ]] && break
  done < <(cd "$REPO_DIR" && git grep -n "writes " -- 'scripts/*' 'bin/*' '*/build.sh' 2>/dev/null || true)

  if [[ -z "$d3_result" ]]; then
    _pass "$label: D3 no longer false-positives on TARGET='$target'"
  else
    _fail "$label: D3 still false-positives on TARGET='$target' ($d3_result)"
  fi
}

_test_d3_no_false_positive "content" "bare-word false positive (was: git_fixture.py's 'unchanged content' prose)"
_test_d3_no_false_positive "bin" "self-referential false positive (was: this script's own git-grep pathspec argument)"
_test_d3_no_false_positive "scripts" "self-referential false positive (was: this script's own git-grep pathspec argument)"

# --- D4 extraction regression (DS-182 round-3 Major 2) ---
#
# D4 is only actually ENTERED (its scratch-clone-and-execute step reached)
# when D1 finds a whole-tree (no-pathspec) `git diff --exit-code` assertion
# and no D1/D2/D3 rule matched the target first. The only such assertion in
# this repo today is in .github/workflows/codex-skill-sync.yml (its line
# number is looked up at check time below, not hard-pinned - the workflow
# gets edited often enough that a literal line number goes stale), and
# every real target its preceding generator commands touch (all under .codex/) is
# already caught by D1's earlier adapter-sync.yml pathspec, so D4 can never
# be observed producing a real DERIVED verdict in this repo as it stands -
# see scripts/gate-provenance.sh's own D4 comment block for why. What CAN
# and MUST be regression-tested without a multi-minute scratch clone is the
# extraction step itself: the awk logic that locates the job's `run:` steps
# between the job header and the diff-assertion line. This mirrors
# scripts/gate-provenance.sh's own extraction verbatim (job_start_line then
# generator_cmds) against the REAL live codex-skill-sync.yml, not a
# fixture - a fixture would only prove the fixture's own shape.
_test_d4_extraction() {
  local wf="$REPO_DIR/.github/workflows/codex-skill-sync.yml"
  local diff_lineno job_start_line generator_cmds expected

  diff_lineno="$(grep -n "git diff --exit-code" "$wf" | head -1 | cut -d: -f1)"
  if [[ -z "$diff_lineno" ]]; then
    _fail "codex-skill-sync.yml no longer contains a bare 'git diff --exit-code' assertion - re-verify D4's only real-repo entry point before trusting this test"
    return
  fi

  job_start_line="$(awk -v stop="$diff_lineno" '
    /^  [A-Za-z0-9_-]+:$/ { last = NR }
    NR == stop { print last; exit }
  ' "$wf")"

  # Fixed extraction (must match scripts/gate-provenance.sh's D4 block).
  generator_cmds="$(awk -v start="$job_start_line" -v stop="$diff_lineno" '
    NR > start && NR < stop && /^[[:space:]]*run:/ {
      sub(/^[[:space:]]*run:[[:space:]]*\|?[[:space:]]*/, "");
      if (length($0) > 0) print;
    }
  ' "$wf")"

  expected="$(printf '%s\n' \
    'python3 .codex/lib/prompt-wrappers.py build --repo .' \
    'bash scripts/check-codex-skill-sync.sh' \
    'python3 scripts/test/test_codex_skills.py' \
    'python3 scripts/test/test_codex_skills.py --clean-clone' \
    'bash .codex/build.sh')"

  if [[ "$generator_cmds" == "$expected" ]]; then
    _pass "D4 extraction (fixed [[:space:]] regex) finds all 5 real generator commands preceding codex-skill-sync.yml:${diff_lineno}'s whole-tree diff assertion"
  else
    _fail "D4 extraction did not match the 5 expected commands. Got:
$generator_cmds
Expected:
$expected"
  fi

  # No mutation check here: an earlier version of this test asserted that
  # the ORIGINAL \s regex (pre-fix) yields empty output under "this awk" -
  # but \s is a GNU-awk extension. It IS empty under BSD awk (what macOS
  # contributors run, and where the round-3 Major 2 bug was discovered),
  # but non-empty under gawk (what the Ubuntu CI runner installs), so the
  # assertion was actually pinning "which awk is on PATH", not "is the fix
  # load-bearing" - it failed on CI the moment it ran there. The positive
  # assertion above already covers load-bearingness: it fails if the
  # current [[:space:]] regex regresses on either awk, which is the
  # property that matters. Do not re-add a mutation check against deleted
  # code without first confirming the assertion holds under both BSD awk
  # and gawk.
}
_test_d4_extraction

# --- D4 full execution (opt-in, ~7 minutes measured) ---
#
# Exercises D4's real scratch-clone-and-execute path end to end: git clone
# --no-hardlinks of this repo, running codex-skill-sync.yml's 5 generator
# commands (including a --clean-clone Codex-skills test pass) inside it,
# then checking whether README.md changed. Measured wall-clock: 6m42s on
# this machine. That cost is inherent to D4's own design (it must actually
# run whatever CI ran before the diff assertion it's auditing) and is not
# something this ticket redesigns - see scripts/gate-provenance.sh's D4
# comment block. Excluded from the default (fast) run so bin-sh-tests does
# not pay ~7 minutes on every PR; set RUN_SLOW_D4_TEST=1 to also run it
# locally or in a dedicated slow-suite CI job.
if [[ "${RUN_SLOW_D4_TEST:-}" == "1" ]]; then
  _assert_classification "README.md" "AUTHORED" "no D1/D2/D3/D4 rule found a generator write to this path"

  # Also under direct zsh invocation - this is the ONLY assertion in this
  # suite that reaches D4's `${d1_first_wholetree}` scalar read (the fix
  # for zsh's 1-indexed-by-default arrays; a literal `${arr[0]}` read
  # aborts with "parameter not set" under zsh). Every fast D1/D2/D3 zsh
  # target above resolves before D4, so only a real AUTHORED verdict
  # actually exercises this line - hence gating it behind the same
  # RUN_SLOW_D4_TEST flag rather than a cheaper mirror.
  _assert_classification_zsh "README.md" "AUTHORED" "no D1/D2/D3/D4 rule found a generator write to this path"
else
  echo "SKIP: D4 full-execution test (set RUN_SLOW_D4_TEST=1 to run; ~7 minutes)"
fi

# --- Usage error: wrong argument count exits 2 ---
usage_out="$(cd "$REPO_DIR" && bash scripts/gate-provenance.sh 2>&1)"
usage_rc=$?
if [[ $usage_rc -eq 2 ]]; then
  _pass "gate-provenance.sh with no args exits 2"
else
  _fail "gate-provenance.sh with no args exited $usage_rc (expected 2): $usage_out"
fi

# --- Malformed input exits 2, never a confident wrong answer (DS-182 round-3 Major 3) ---
# _assert_exit2 <path> <label>
_assert_exit2() {
  local target="$1" label="$2" out rc
  out="$(cd "$REPO_DIR" && bash scripts/gate-provenance.sh "$target" 2>&1)"
  rc=$?
  if [[ $rc -eq 2 ]]; then
    _pass "$label ('$target') exits 2"
  else
    _fail "$label ('$target') exited $rc (expected 2), printed AUTHORED/DERIVED instead of refusing: $out"
  fi
}

_assert_exit2 "/etc/passwd" "absolute path"
_assert_exit2 "../outside.md" "leading .. escape"
_assert_exit2 "foo/../bar" "embedded .. escape"
_assert_exit2 "foo/.." "trailing .. escape"
_assert_exit2 ".." "bare .."
_assert_exit2 "" "empty argument"

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
