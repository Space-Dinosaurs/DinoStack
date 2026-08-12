#!/usr/bin/env bash
# Purpose: Regression tests for the update-flow shared-constants collapse
#          (scripts/lib/update-shared.json). Seven things are asserted:
#          (1) scripts/update.js and bin/agentic-update both load SKIP_DIRS
#              and REBUILD_TRIGGERS from the shared JSON file rather than a
#              local literal - single-sourcing makes drift structurally
#              impossible for pure DATA, so this is a load-path assertion,
#              not a value-comparison assertion (the JS/Python consumers
#              would trivially "agree" with themselves if they each still
#              hardcoded the same list independently - the failure mode this
#              guards is a REINTRODUCED local literal, not a stale value).
#          (2) install-all.sh's SKIP_DIRS array (loaded via python3 from the
#              same JSON) matches the shared file's skip_dirs exactly.
#          (3) needsRebuild()/_needs_rebuild() - the matching ALGORITHM that
#              genuinely cannot be shared across JS/Python - agree on a
#              cross-language parity vector table.
#          (4) DISPLAY_NAMES matches across scripts/update.js and the prose
#              copy in content/commands/ds-update.md.
#          (5) hooksTouched()/_hooks_touched() cross-language parity vector
#              table.
#          (6) the UPDATE-FLOW fallback fence in content/commands/ds-update.md
#              (used when `agentic-update` is not on PATH) is extracted and
#              RUN with a fake `git`, proving its non-main-branch and
#              dirty-tree guards actually STOP execution before `pull` - a
#              prose-only guard (an echoed error with no `exit`) is invisible
#              to a text-only assertion but not to this one.
#          (7) that same fallback fence's per-adapter install loop is
#              fail-soft (both a failing and a later adapter run, all
#              failures are named with their exit codes, overall exit is
#              non-zero) AND its own in-fence comment's declared fail-soft/
#              fail-fast label matches that measured behavior - so an edit to
#              either the loop body or its label reds the gate independently.
#
# Public API: ./bin/tests/test_update_shared_constants.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, node, python3.
#
# Downstream consumers: developer running locally before commit; wired into
#                       CI via the bin-sh-tests test_*.sh glob discovery.
#
# Failure modes: any test failure prints the failing assertion and exits 1.
#
# Performance: <5 s wall time.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHARED_JSON="$REPO_ROOT/scripts/lib/update-shared.json"
UPDATE_JS="$REPO_ROOT/scripts/update.js"
UPDATER_PY="$REPO_ROOT/bin/agentic-update"
INSTALL_ALL="$REPO_ROOT/install-all.sh"
DS_UPDATE_MD="$REPO_ROOT/content/commands/ds-update.md"

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

if [[ ! -f "$SHARED_JSON" ]]; then
  _fail "shared config file missing at $SHARED_JSON"
  echo; echo "Results: $PASS passed, $FAIL failed."; exit 1
fi

# ---------------------------------------------------------------------------
# Test 1: shared JSON is valid and has the expected shape
# ---------------------------------------------------------------------------
if python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
assert isinstance(data.get('skip_dirs'), list) and len(data['skip_dirs']) > 0
assert isinstance(data.get('rebuild_triggers'), list) and len(data['rebuild_triggers']) > 0
" "$SHARED_JSON" 2>/dev/null; then
  _pass "T1 shared JSON has non-empty skip_dirs and rebuild_triggers arrays"
else
  _fail "T1 shared JSON malformed or missing expected keys"
fi

# ---------------------------------------------------------------------------
# Test 2: scripts/update.js SKIP_DIRS/REBUILD_TRIGGERS match the shared file
# (proves it is actually LOADING from the file, not a reintroduced literal
# that happens to still agree - a stale/mismatched literal fails this).
# ---------------------------------------------------------------------------
JS_OUT="$(node -e "
const u = require('$UPDATE_JS');
const skip = [...u.SKIP_DIRS].sort();
const triggers = [...u.REBUILD_TRIGGERS].sort();
console.log(JSON.stringify({skip_dirs: skip, rebuild_triggers: triggers}));
" 2>&1)"

if python3 -c "
import json, sys
shared = json.load(open(sys.argv[1]))
js = json.loads(sys.argv[2])
assert sorted(shared['skip_dirs']) == js['skip_dirs'], (sorted(shared['skip_dirs']), js['skip_dirs'])
assert sorted(shared['rebuild_triggers']) == js['rebuild_triggers'], (sorted(shared['rebuild_triggers']), js['rebuild_triggers'])
" "$SHARED_JSON" "$JS_OUT" 2>/dev/null; then
  _pass "T2 scripts/update.js SKIP_DIRS/REBUILD_TRIGGERS match shared JSON"
else
  _fail "T2 scripts/update.js constants diverged from shared JSON (got: $JS_OUT)"
fi

# ---------------------------------------------------------------------------
# Test 3: bin/agentic-update SKIP_DIRS/REBUILD_TRIGGERS match the shared file
# ---------------------------------------------------------------------------
PY_OUT="$(python3 - "$UPDATER_PY" <<'PYEOF' 2>&1
import importlib.util, importlib.machinery, json, sys

updater_path = sys.argv[1]
loader = importlib.machinery.SourceFileLoader("agentic_update_shared_test", updater_path)
spec = importlib.util.spec_from_file_location("agentic_update_shared_test", updater_path, loader=loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps({
    "skip_dirs": sorted(mod.SKIP_DIRS),
    "rebuild_triggers": sorted(mod.REBUILD_TRIGGERS),
}))
PYEOF
)"

if python3 -c "
import json, sys
shared = json.load(open(sys.argv[1]))
py = json.loads(sys.argv[2])
assert sorted(shared['skip_dirs']) == py['skip_dirs'], (sorted(shared['skip_dirs']), py['skip_dirs'])
assert sorted(shared['rebuild_triggers']) == py['rebuild_triggers'], (sorted(shared['rebuild_triggers']), py['rebuild_triggers'])
" "$SHARED_JSON" "$PY_OUT" 2>/dev/null; then
  _pass "T3 bin/agentic-update SKIP_DIRS/REBUILD_TRIGGERS match shared JSON"
else
  _fail "T3 bin/agentic-update constants diverged from shared JSON (got: $PY_OUT)"
fi

# ---------------------------------------------------------------------------
# Test 4: install-all.sh's SKIP_DIRS array (loaded via python3 at runtime)
# matches the shared file. Exercised by sourcing the array-building prelude
# in a subshell, not by running the whole script (which requires adapters).
# ---------------------------------------------------------------------------
IA_OUT="$(bash -c '
REPO_DIR="'"$REPO_ROOT"'"
SHARED_CONFIG="$REPO_DIR/scripts/lib/update-shared.json"
SKIP_DIRS=()
while IFS= read -r skip_dir; do
  SKIP_DIRS+=("$skip_dir")
done < <(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for d in data[\"skip_dirs\"]:
    print(d)
" "$SHARED_CONFIG")
printf "%s\n" "${SKIP_DIRS[@]}" | sort
' 2>&1)"

EXPECTED_OUT="$(python3 -c "
import json
data = json.load(open('$SHARED_JSON'))
print('\n'.join(sorted(data['skip_dirs'])))
")"

if [[ "$IA_OUT" == "$EXPECTED_OUT" ]]; then
  _pass "T4 install-all.sh SKIP_DIRS (loaded from shared JSON) matches expected"
else
  _fail "T4 install-all.sh SKIP_DIRS mismatch. Got:
$IA_OUT
Expected:
$EXPECTED_OUT"
fi

# ---------------------------------------------------------------------------
# Test 5 (non-vacuity, RED/GREEN for T2/T3): a deliberately mutated shared
# JSON (extra bogus skip dir NOT in the loaded module output) must FAIL the
# comparison logic used above - proves T2/T3 are not vacuously true.
# ---------------------------------------------------------------------------
BOGUS_JSON="$(mktemp)"
python3 -c "
import json
data = json.load(open('$SHARED_JSON'))
data['skip_dirs'] = data['skip_dirs'] + ['.this_should_not_be_here']
json.dump(data, open('$BOGUS_JSON', 'w'))
"
if python3 -c "
import json, sys
shared = json.load(open(sys.argv[1]))
js = json.loads(sys.argv[2])
assert sorted(shared['skip_dirs']) == js['skip_dirs']
" "$BOGUS_JSON" "$JS_OUT" 2>/dev/null; then
  _fail "T5 non-vacuity check: bogus JSON incorrectly matched real module output (comparison is vacuous)"
else
  _pass "T5 non-vacuity check: bogus JSON correctly fails the comparison (T2/T3 are falsifiable)"
fi
rm -f "$BOGUS_JSON"

# ---------------------------------------------------------------------------
# Test 6: cross-language parity vectors for needsRebuild()/_needs_rebuild().
# The matching ALGORITHM (not just the trigger-list data) is duplicated
# across JS and Python since it can't practically be shared across
# languages. This vector table is the enforcing test the brief calls for.
# ---------------------------------------------------------------------------
declare -a VECTORS=(
  # old_head|new_head|changed_paths(comma-sep)|expected(0/1)
  "|def456|content/x.md|1"                       # empty old_head -> always rebuild
  "abc123|abc123|content/x.md|0"                  # same heads -> never rebuild
  "abc123|def456|content/x.md|1"                  # content/ prefix
  "abc123|def456|docs/x.md|0"                     # not a trigger
  "abc123|def456|.cursor/build.sh|1"               # */build.sh catch-all
  "abc123|def456|build.sh|1"                       # bare build.sh
  "abc123|def456|.claude/install.sh|1"             # exact-path trigger
  "abc123|def456|bin/agentic-update|1"             # bin/ prefix
  "abc123|def456|scripts/build-all.sh|1"           # exact-path trigger
  "abc123|def456|hooks/foo.py|1"                   # hooks/ prefix
  "abc123|def456|docs/x.md,content/y.md|1"         # mixed: one trigger present
  "abc123|def456|/content/x.md|1"                  # leading-slash normalisation
  "abc123|def456|content\\\\x.md|1"                # backslash normalisation
)

for vector in "${VECTORS[@]}"; do
  IFS='|' read -r old new paths expected <<< "$vector"
  # Build a JSON array of changed paths from the comma-separated field.
  paths_json="$(python3 -c "
import json, sys
p = sys.argv[1]
print(json.dumps(p.split(',') if p else []))
" "$paths")"

  js_result="$(node -e "
const u = require('$UPDATE_JS');
const paths = $paths_json;
console.log(u.needsRebuild('$old', '$new', paths) ? '1' : '0');
" 2>&1)"

  py_result="$(python3 - "$UPDATER_PY" "$old" "$new" "$paths_json" <<'PYEOF' 2>&1
import importlib.util, importlib.machinery, json, sys

updater_path, old, new, paths_json = sys.argv[1:5]
loader = importlib.machinery.SourceFileLoader("agentic_update_vec_test", updater_path)
spec = importlib.util.spec_from_file_location("agentic_update_vec_test", updater_path, loader=loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
paths = json.loads(paths_json)
print("1" if mod._needs_rebuild(old, new, paths) else "0")
PYEOF
)"

  if [[ "$js_result" == "$expected" && "$py_result" == "$expected" ]]; then
    _pass "T6 vector '$paths' (old=$old new=$new): JS=$js_result PY=$py_result expected=$expected"
  else
    _fail "T6 vector '$paths' (old=$old new=$new): JS=$js_result PY=$py_result expected=$expected"
  fi
done

# ---------------------------------------------------------------------------
# Test 7 (non-vacuity for T6): confirm the vector table can actually catch a
# broken implementation, by simulating a deliberately-wrong "always false"
# predicate (stub_result is always "0", never queries the real modules) and
# checking it DISAGREES with the table's own expected value for at least one
# vector - i.e. the T6 comparison `[[ "$js_result" == "$expected" ]]` would
# genuinely fail against this stub, proving T6 is falsifiable and not merely
# a property of the table's shape.
# ---------------------------------------------------------------------------
MISMATCH_FOUND=0
for vector in "${VECTORS[@]}"; do
  IFS='|' read -r old new paths expected <<< "$vector"
  stub_result="0"  # simulates an always-false needsRebuild/_needs_rebuild
  if [[ "$stub_result" != "$expected" ]]; then
    MISMATCH_FOUND=1
    break
  fi
done
if [[ "$MISMATCH_FOUND" == "1" ]]; then
  _pass "T7 non-vacuity check: an always-false stub disagrees with the vector table (T6 is falsifiable)"
else
  _fail "T7 non-vacuity check: vector table cannot distinguish an always-false stub from a correct implementation"
fi

# ---------------------------------------------------------------------------
# Test 7b (MINOR fix): scripts/update.js DISPLAY_NAMES matches the shared
# JSON (single-sourced - see the loadSharedConfig()/DISPLAY_NAMES comment
# in scripts/update.js).
# ---------------------------------------------------------------------------
DN_JS_OUT="$(node -e "
const u = require('$UPDATE_JS');
console.log(JSON.stringify(u.DISPLAY_NAMES));
" 2>&1)"

if python3 -c "
import json, sys
shared = json.load(open(sys.argv[1]))
js = json.loads(sys.argv[2])
assert shared['display_names'] == js, (shared['display_names'], js)
" "$SHARED_JSON" "$DN_JS_OUT" 2>/dev/null; then
  _pass "T7b scripts/update.js DISPLAY_NAMES matches shared JSON"
else
  _fail "T7b scripts/update.js DISPLAY_NAMES diverged from shared JSON (got: $DN_JS_OUT)"
fi

# ---------------------------------------------------------------------------
# Test 7c (MINOR fix): content/commands/ds-update.md's prose DISPLAY_NAMES
# copy is parity-gated against the shared JSON. Markdown cannot load JSON at
# doc-render time, so this prose copy cannot be single-sourced the way the
# JS copy above was - this gate is the alternative the brief calls for: a
# real CI failure on drift, not a "keep in sync manually" comment.
#
# Extracts the `{ claude: "Claude", codex: "Codex", ... }` block from the
# doc (the one immediately following the "Display names use the same
# `DISPLAY_NAMES` map" sentence) and parses it as a permissive key:value
# list, tolerant of the doc's unquoted-key JS-object-literal style.
# ---------------------------------------------------------------------------
if [[ -f "$DS_UPDATE_MD" ]]; then
  DOC_PARITY_RESULT="$(python3 -c "
import json, re, sys

doc_path = sys.argv[1]
shared_path = sys.argv[2]

text = open(doc_path, encoding='utf-8').read()
m = re.search(r'DISPLAY_NAMES.*?\n\n\`\`\`\n(\{.*?\})\n\`\`\`', text, re.DOTALL)
if not m:
    print('EXTRACT_FAILED')
    sys.exit(0)

body = m.group(1)
# Pull out bare-key: \"Value\" pairs - tolerant of the doc's unquoted-key
# JS-object-literal style (not valid JSON as-is).
pairs = re.findall(r'(\w+):\s*\"([^\"]+)\"', body)
doc_map = dict(pairs)

shared = json.load(open(shared_path))
if doc_map == shared['display_names']:
    print('MATCH')
else:
    print('MISMATCH: doc=' + json.dumps(doc_map) + ' shared=' + json.dumps(shared['display_names']))
" "$DS_UPDATE_MD" "$SHARED_JSON" 2>&1)"

  if [[ "$DOC_PARITY_RESULT" == "MATCH" ]]; then
    _pass "T7c content/commands/ds-update.md DISPLAY_NAMES prose copy matches shared JSON"
  elif [[ "$DOC_PARITY_RESULT" == "EXTRACT_FAILED" ]]; then
    _fail "T7c could not extract the DISPLAY_NAMES block from $DS_UPDATE_MD - doc structure changed; update the extraction regex"
  else
    _fail "T7c content/commands/ds-update.md DISPLAY_NAMES prose copy diverged from shared JSON ($DOC_PARITY_RESULT)"
  fi
else
  _fail "T7c $DS_UPDATE_MD not found"
fi

# ---------------------------------------------------------------------------
# Test 8: cross-language parity vectors for hooksTouched()/_hooks_touched().
# Mirrors the same case table as scripts/test/update-hookstouched.test.js
# (which is not wired to any CI workflow - grep confirms no .github/workflows
# reference), so this is the only CI-enforced parity coverage for the
# predicate. Same non-vacuity pattern as T6/T7 below.
# ---------------------------------------------------------------------------
declare -a HOOKS_VECTORS=(
  # changed_paths(comma-sep)|expected(0/1)
  "hooks/enforce-background-spawn.py|1"      # hooks/-prefixed -> touched
  "hooks/stop-context.js|1"                  # hooks/-prefixed -> touched
  "README.md|0"                              # non-hooks -> not touched
  "content/agents/engineer.md|0"             # non-hooks -> not touched
  "README.md,hooks/x.sh|1"                   # mixed: one hooks/ present -> touched
  "|0"                                       # empty changed_paths -> not touched
  "hooks\\\\foo.py|1"                        # backslash-normalized -> touched
  "/hooks/foo.py|1"                          # leading-slash -> touched
)

for vector in "${HOOKS_VECTORS[@]}"; do
  IFS='|' read -r paths expected <<< "$vector"
  paths_json="$(python3 -c "
import json, sys
p = sys.argv[1]
print(json.dumps(p.split(',') if p else []))
" "$paths")"

  js_result="$(node -e "
const u = require('$UPDATE_JS');
const paths = $paths_json;
console.log(u.hooksTouched(paths) ? '1' : '0');
" 2>&1)"

  py_result="$(python3 - "$UPDATER_PY" "$paths_json" <<'PYEOF' 2>&1
import importlib.util, importlib.machinery, json, sys

updater_path, paths_json = sys.argv[1:3]
loader = importlib.machinery.SourceFileLoader("agentic_update_hooks_test", updater_path)
spec = importlib.util.spec_from_file_location("agentic_update_hooks_test", updater_path, loader=loader)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
paths = json.loads(paths_json)
print("1" if mod._hooks_touched(paths) else "0")
PYEOF
)"

  if [[ "$js_result" == "$expected" && "$py_result" == "$expected" ]]; then
    _pass "T8 hooksTouched vector '$paths': JS=$js_result PY=$py_result expected=$expected"
  else
    _fail "T8 hooksTouched vector '$paths': JS=$js_result PY=$py_result expected=$expected"
  fi
done

# ---------------------------------------------------------------------------
# Test 9 (non-vacuity for T8): an always-false stub must disagree with the
# HOOKS_VECTORS table for at least one vector.
# ---------------------------------------------------------------------------
HOOKS_MISMATCH_FOUND=0
for vector in "${HOOKS_VECTORS[@]}"; do
  IFS='|' read -r paths expected <<< "$vector"
  stub_result="0"  # simulates an always-false hooksTouched/_hooks_touched
  if [[ "$stub_result" != "$expected" ]]; then
    HOOKS_MISMATCH_FOUND=1
    break
  fi
done
if [[ "$HOOKS_MISMATCH_FOUND" == "1" ]]; then
  _pass "T9 non-vacuity check: an always-false stub disagrees with the hooksTouched vector table (T8 is falsifiable)"
else
  _fail "T9 non-vacuity check: hooksTouched vector table cannot distinguish an always-false stub from a correct implementation"
fi

# ---------------------------------------------------------------------------
# Test 10: the UPDATE-FLOW fallback fence's non-main-branch and dirty-tree
# guards must actually STOP execution before reaching `git ... pull`, not
# merely print an error and fall through to it. A prose-only guard (an
# executed comment like `# STOP - do not proceed` with no `exit`) is
# invisible to a text assertion that just checks the error message exists -
# this test extracts the literal fenced block from content/commands/ds-update.md
# and RUNS it, verifying via a fake `git` on PATH that `pull` is never
# invoked when either guard should have fired.
# ---------------------------------------------------------------------------
if [[ -f "$DS_UPDATE_MD" ]]; then
  FALLBACK_SCRIPT="$(python3 -c "
import re, sys

text = open(sys.argv[1], encoding='utf-8').read()
# Anchor on the sentence immediately preceding the fallback fence (there are
# two 'CURRENT_BRANCH=' fences in this doc - Step 2b's non-blocking preview,
# and this one - so a bare 'first \`\`\`bash after CURRENT_BRANCH=' match would
# silently grab the wrong, non-authoritative block).
anchor = 'not optional preview info as in Step 2b:'
anchor_idx = text.find(anchor)
if anchor_idx == -1:
    print('EXTRACT_FAILED')
    sys.exit(0)
m = re.search(r'\`\`\`bash\nCURRENT_BRANCH=.*?\n\`\`\`', text[anchor_idx:], re.DOTALL)
if not m:
    print('EXTRACT_FAILED')
    sys.exit(0)
# Strip the \`\`\`bash / \`\`\` fence markers, keep the body verbatim.
body = m.group(0)
body = body[len('\`\`\`bash\n'):-len('\`\`\`')]
print(body)
" "$DS_UPDATE_MD")"

  if [[ "$FALLBACK_SCRIPT" == "EXTRACT_FAILED" || -z "$FALLBACK_SCRIPT" ]]; then
    _fail "T10 could not extract the UPDATE-FLOW fallback fence from $DS_UPDATE_MD - doc structure changed; update the extraction regex"
  else
    FALLBACK_TMPDIR="$(mktemp -d)"
    FAKE_GIT_LOG="$FALLBACK_TMPDIR/git-calls.log"
    FAKE_BIN_DIR="$FALLBACK_TMPDIR/bin"
    mkdir -p "$FAKE_BIN_DIR"

    # Fake `git` on PATH: logs every invoked subcommand (rev-parse/status/pull)
    # and returns branch/dirty-state controlled by env vars, so the extracted
    # fence's body runs completely unmodified - only its `git` calls are
    # intercepted, which is what lets this test catch a reintroduced
    # comment-only guard without also masking a real behavioral change.
    cat > "$FAKE_BIN_DIR/git" <<'FAKEGIT'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_GIT_LOG"
# Expected invocation shapes from the extracted fence:
#   git -C <dir> rev-parse --abbrev-ref HEAD
#   git -C <dir> status --porcelain
#   git -C <dir> pull --ff-only origin main
if [[ "$*" == *"rev-parse --abbrev-ref HEAD"* ]]; then
  echo "${FAKE_BRANCH:-main}"
  exit 0
elif [[ "$*" == *"status --porcelain"* ]]; then
  printf '%s' "${FAKE_DIRTY:-}"
  exit 0
elif [[ "$*" == *"pull --ff-only"* ]]; then
  echo "pull invoked" >> "$FAKE_GIT_LOG.pull-reached"
  exit 0
fi
exit 0
FAKEGIT
    chmod +x "$FAKE_BIN_DIR/git"

    run_fallback_fence() {
      # Args: $1 = FAKE_BRANCH, $2 = FAKE_DIRTY
      : > "$FAKE_GIT_LOG"
      rm -f "$FAKE_GIT_LOG.pull-reached"
      (
        PATH="$FAKE_BIN_DIR:$PATH"
        export PATH
        FAKE_GIT_LOG="$FAKE_GIT_LOG"
        export FAKE_GIT_LOG
        FAKE_BRANCH="$1"
        export FAKE_BRANCH
        FAKE_DIRTY="$2"
        export FAKE_DIRTY
        AE_REPO_DIR="$FALLBACK_TMPDIR/fake-repo"
        export AE_REPO_DIR
        SELECTED_ADAPTERS=()
        bash -c "$FALLBACK_SCRIPT"
      )
    }

    # --- Guard A: non-main branch, clean tree -> must STOP before pull ---
    run_fallback_fence "feature/some-branch" ""
    FENCE_RC=$?
    if [[ "$FENCE_RC" -ne 0 ]]; then
      _pass "T10a non-main-branch guard: fence exits non-zero"
    else
      _fail "T10a non-main-branch guard: fence exited 0 - the guard did not stop execution"
    fi
    if [[ ! -f "$FAKE_GIT_LOG.pull-reached" ]]; then
      _pass "T10a non-main-branch guard: pull was never invoked"
    else
      _fail "T10a non-main-branch guard: pull WAS invoked despite non-main branch - the STOP is prose-only"
    fi

    # --- Guard B: main branch, dirty tree -> must STOP before pull ---
    run_fallback_fence "main" "M some/dirty/file.txt"
    FENCE_RC=$?
    if [[ "$FENCE_RC" -ne 0 ]]; then
      _pass "T10b dirty-tree guard: fence exits non-zero"
    else
      _fail "T10b dirty-tree guard: fence exited 0 - the guard did not stop execution"
    fi
    if [[ ! -f "$FAKE_GIT_LOG.pull-reached" ]]; then
      _pass "T10b dirty-tree guard: pull was never invoked"
    else
      _fail "T10b dirty-tree guard: pull WAS invoked despite a dirty tree - the STOP is prose-only"
    fi

    # --- Non-vacuity: main branch, clean tree -> both guards pass through,
    # pull IS reached (proves the harness can observe a reached pull at all,
    # so T10a/T10b's "pull never invoked" checks are falsifiable). ---
    run_fallback_fence "main" ""
    if [[ -f "$FAKE_GIT_LOG.pull-reached" ]]; then
      _pass "T10c non-vacuity: clean main branch reaches pull (harness can detect a reached pull)"
    else
      _fail "T10c non-vacuity: clean main branch never reached pull - the fake git harness itself is broken, T10a/T10b prove nothing"
    fi

    # -------------------------------------------------------------------
    # Test 11: the fallback fence's per-adapter install loop must be
    # fail-soft - a failing adapter must not stop the loop, every failing
    # adapter must be named with its exit code, and the overall exit must
    # be non-zero. Two fake adapters, both failing with distinct exit
    # codes; each writes a marker file on invocation so "did the loop
    # continue past the first failure" is directly observable, not
    # inferred from output text alone.
    # -------------------------------------------------------------------
    AGG_TMPDIR="$FALLBACK_TMPDIR/agg-repo"
    mkdir -p "$AGG_TMPDIR/adapterA" "$AGG_TMPDIR/adapterB"
    cat > "$AGG_TMPDIR/adapterA/install.sh" <<EOF
#!/usr/bin/env bash
touch "$FALLBACK_TMPDIR/adapterA-ran"
exit 3
EOF
    chmod +x "$AGG_TMPDIR/adapterA/install.sh"
    cat > "$AGG_TMPDIR/adapterB/install.sh" <<EOF
#!/usr/bin/env bash
touch "$FALLBACK_TMPDIR/adapterB-ran"
exit 5
EOF
    chmod +x "$AGG_TMPDIR/adapterB/install.sh"

    # The doc's fence uses illustrative angle-bracket placeholders
    # (--mode=<mode>, --profile=<profile>, [--identity=<handle>|--no-identity])
    # that are not meant to be executed literally - `<mode>` etc. parse as
    # shell redirections, not text, and would break every adapter
    # invocation before this test could observe fail-soft behavior at all.
    # Substitute them with harmless literal values for this execution only;
    # T10's guard tests never reach this line so they are unaffected, and
    # T12's label extraction reads FALLBACK_SCRIPT's comment text, not this
    # substituted copy.
    AGG_SCRIPT="$(printf '%s\n' "$FALLBACK_SCRIPT" | sed -E \
      -e 's/--mode=<mode>/--mode=test-mode/g' \
      -e 's/--profile=<profile>/--profile=test-profile/g' \
      -e 's/\[--identity=<handle>\|--no-identity\]//g')"

    rm -f "$FALLBACK_TMPDIR/adapterA-ran" "$FALLBACK_TMPDIR/adapterB-ran"
    AGG_OUTPUT="$(
      (
        PATH="$FAKE_BIN_DIR:$PATH"
        export PATH
        FAKE_GIT_LOG="$FAKE_GIT_LOG"
        export FAKE_GIT_LOG
        FAKE_BRANCH="main"
        export FAKE_BRANCH
        FAKE_DIRTY=""
        export FAKE_DIRTY
        AE_REPO_DIR="$AGG_TMPDIR"
        export AE_REPO_DIR
        # SELECTED_ADAPTERS is a bash array and arrays cannot be exported to
        # a child process, so the assignment is prepended to the script text
        # passed to `bash -c` rather than set in this subshell's own
        # environment (which the child bash -c process would not inherit).
        bash -c 'SELECTED_ADAPTERS=(adapterA adapterB)
'"$AGG_SCRIPT"
      ) 2>&1
    )"
    AGG_RC=$?

    if [[ "$AGG_RC" -ne 0 ]]; then
      _pass "T11a aggregation: overall exit is non-zero when adapters fail"
    else
      _fail "T11a aggregation: overall exit was 0 despite two adapter failures"
    fi

    if [[ -f "$FALLBACK_TMPDIR/adapterA-ran" && -f "$FALLBACK_TMPDIR/adapterB-ran" ]]; then
      _pass "T11b aggregation: loop continues past the first failure (both adapters ran)"
      AGG_BOTH_RAN=1
    else
      _fail "T11b aggregation: loop stopped after the first failure - not fail-soft"
      AGG_BOTH_RAN=0
    fi

    if [[ "$AGG_OUTPUT" == *"adapterA/install.sh (exit 3)"* && "$AGG_OUTPUT" == *"adapterB/install.sh (exit 5)"* ]]; then
      _pass "T11c aggregation: both failing adapters are named with their exit codes"
    else
      _fail "T11c aggregation: output does not name both failures with exit codes. Got:
$AGG_OUTPUT"
    fi

    # -------------------------------------------------------------------
    # Test 12: doc-vs-code parity for the fallback loop's fail-soft/
    # fail-fast label. The in-fence comment immediately preceding the loop
    # (extracted as part of FALLBACK_SCRIPT, same text T10 already ran)
    # declares which behavior the loop has; T11 just measured which
    # behavior it ACTUALLY has. This assertion ties the two together so
    # either side drifting independently reds the gate - a code edit that
    # makes the loop stop on first failure fails T11b already, and a prose
    # edit that relabels the comment without touching the loop body fails
    # only here.
    # -------------------------------------------------------------------
    FENCE_LABEL="$(printf '%s\n' "$FALLBACK_SCRIPT" | grep -A5 "Run each selected adapter" | grep -oE 'fail-(soft|fast)' | head -1)"
    if [[ "$AGG_BOTH_RAN" -eq 1 ]]; then
      ACTUAL_BEHAVIOR="fail-soft"
    else
      ACTUAL_BEHAVIOR="fail-fast"
    fi

    if [[ -n "$FENCE_LABEL" && "$FENCE_LABEL" == "$ACTUAL_BEHAVIOR" ]]; then
      _pass "T12 doc-vs-code parity: fallback loop's declared behavior ($FENCE_LABEL) matches its measured behavior ($ACTUAL_BEHAVIOR)"
    else
      _fail "T12 doc-vs-code parity: fallback loop declares '${FENCE_LABEL:-<none found>}' but measured behavior is '$ACTUAL_BEHAVIOR' - content/commands/ds-update.md's fallback-loop comment has diverged from the loop's actual behavior"
    fi

    rm -rf "$FALLBACK_TMPDIR"
  fi
else
  _fail "T10 $DS_UPDATE_MD not found"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
