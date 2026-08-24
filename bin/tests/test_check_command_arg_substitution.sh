#!/usr/bin/env bash
# Purpose: Executable regression spec for scripts/check-command-arg-
#          substitution.py (DS-192) - the fence-state-machine gate that
#          fails CI when a bare $0-$9/$ARGUMENTS token reappears inside an
#          executable (bare/```bash/```sh) fence under content/commands.
#          Exercises the 6 named reddening mutations from the DS-192 plan
#          plus a clean-tree pass assertion, operating only on scratch-
#          directory copies of the real command files, never mutating
#          content/commands directly (hardlink hazard: content/commands/
#          ds-implement-ticket.md and .cursor/commands/ds-implement-
#          ticket.md share an inode on this machine).
#
# Public API: none (standalone script; `bash bin/tests/test_check_command_arg_substitution.sh`).
#
# Upstream deps: scripts/check-command-arg-substitution.py; a fresh copy
#                of content/commands, made under a mktemp scratch dir.
#
# Downstream consumers: CI (bin-sh-tests); .github/workflows/command-arg-
#                        substitution.yml (documents the gate this test
#                        pins, but does not itself invoke this file).
#
# Failure modes: exits non-zero if any mutation's expected exit code or
#                stdout/stderr shape does not hold. Cleans up its scratch
#                dir on exit via a trap regardless of outcome.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHECK_SCRIPT="$REPO_ROOT/scripts/check-command-arg-substitution.py"
SCRATCH="$(mktemp -d)"
CLEAN_DIR="$SCRATCH/clean"
WORK_DIR="$SCRATCH/work"

cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null || true
}
trap cleanup EXIT

FAIL=0
note_fail() {
  echo "FAIL: $1" >&2
  FAIL=1
}

if [ ! -f "$CHECK_SCRIPT" ]; then
  note_fail "$CHECK_SCRIPT not found"
  echo "FAIL: cannot proceed without the check script" >&2
  exit 1
fi

mkdir -p "$CLEAN_DIR"
cp -R "$REPO_ROOT/content/commands/." "$CLEAN_DIR/"

fresh_work() {
  rm -rf "$WORK_DIR" 2>/dev/null || true
  cp -R "$CLEAN_DIR" "$WORK_DIR"
}

run_check() {
  local target="$1"
  python3 "$CHECK_SCRIPT" "$target"
}

echo "== Clean-tree pass: the real content/commands tree scans with zero violations =="
out="$(run_check "$CLEAN_DIR" 2>&1)"
rc=$?
echo "clean-tree exit=$rc output=[$out]"
if [ "$rc" != "0" ]; then
  note_fail "clean-tree pass: expected exit 0, got $rc"
fi
case "$out" in
  "OK: "*"file(s) scanned, zero violations") ;;
  *) note_fail "clean-tree pass: expected an 'OK: ... zero violations' line, got: $out" ;;
esac

echo "== Mutation 1: revert a fixed site (developer_id NF) to bare \$2 =="
fresh_work
doc="$WORK_DIR/ds-implement-ticket.md"
python3 - "$doc" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
old = "awk '/^developer_id:/{print $NF}'"
new = "awk '/^developer_id:/{print $2}'"
assert content.count(old) >= 1, "fixture no longer contains the DS-192 NF form - update this mutation"
content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
PYEOF
fixture_rc=$?
if [ "$fixture_rc" != "0" ]; then
  note_fail "mutation 1: fixture-apply heredoc exited $fixture_rc - mutation did not land"
fi
if ! grep -qF "awk '/^developer_id:/{print \$2}'" "$doc"; then
  note_fail "mutation 1: reverted bare-\$2 form is not present in the fixture after applying the mutation"
fi
out="$(run_check "$WORK_DIR" 2>&1)"
rc=$?
echo "mutation1 exit=$rc output=[$out]"
if [ "$rc" != "1" ]; then
  note_fail "mutation 1: expected exit 1 (bare-token violation), got $rc"
fi
if ! printf '%s' "$out" | grep -q 'developer_id'; then
  note_fail "mutation 1: output does not cite the reverted developer_id violation line"
fi

echo "== Mutation 2: insert a brand-new bare token inside an existing bash fence =="
fresh_work
doc="$WORK_DIR/ds-implement-ticket.md"
python3 - "$doc" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()
inserted = False
for i, line in enumerate(lines):
    if line.rstrip("\n") == "```bash":
        lines.insert(i + 1, "echo injected $1\n")
        inserted = True
        break
assert inserted, "no ```bash fence found to inject into"
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
fixture_rc=$?
if [ "$fixture_rc" != "0" ]; then
  note_fail "mutation 2: fixture-apply heredoc exited $fixture_rc - mutation did not land"
fi
if ! grep -qF 'echo injected $1' "$doc"; then
  note_fail "mutation 2: injected bare-token line is not present in the fixture after applying the mutation"
fi
out="$(run_check "$WORK_DIR" 2>&1)"
rc=$?
echo "mutation2 exit=$rc output=[$out]"
if [ "$rc" != "1" ]; then
  note_fail "mutation 2: expected exit 1 (new bare-token violation), got $rc"
fi
if ! printf '%s' "$out" | grep -q "injected \$1"; then
  note_fail "mutation 2: output does not cite the injected violation line"
fi

echo "== Mutation 3: insert a bare token inside a yaml-tagged fence (decoy - must NOT trip the gate) =="
fresh_work
doc="$WORK_DIR/ds-implement-ticket.md"
python3 - "$doc" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()
inserted = False
for i, line in enumerate(lines):
    if line.rstrip("\n") == "```yaml":
        lines.insert(i + 1, "decoy: $1\n")
        inserted = True
        break
assert inserted, "no ```yaml fence found to inject into"
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
fixture_rc=$?
# G3 (DS-192 round 3): mutation 3's assertion below is NEGATIVE (rc must be
# 0), so an unchecked, silently-failed fixture heredoc would leave $doc
# unmutated and this assertion would pass vacuously - testing nothing. Both
# checks below must run BEFORE run_check so a fixture failure is caught on
# its own terms, independent of whatever run_check happens to report.
if [ "$fixture_rc" != "0" ]; then
  note_fail "mutation 3: fixture-apply heredoc exited $fixture_rc - mutation did not land"
fi
if ! grep -qF 'decoy: $1' "$doc"; then
  note_fail "mutation 3: injected yaml-fence decoy line is not present in the fixture after applying the mutation"
fi
out="$(run_check "$WORK_DIR" 2>&1)"
rc=$?
echo "mutation3 exit=$rc output=[$out]"
if [ "$rc" != "0" ]; then
  note_fail "mutation 3: a bare token inside a yaml fence must NOT trip the gate, got exit $rc"
fi

echo "== Mutation 4: point the target dir at a nonexistent path =="
out="$(python3 "$CHECK_SCRIPT" "/nonexistent/dir-that-does-not-exist" 2>&1)"
rc=$?
echo "mutation4 exit=$rc output=[$out]"
if [ "$rc" != "1" ]; then
  note_fail "mutation 4: expected exit 1 (empty discovery set), got $rc"
fi
if ! printf '%s' "$out" | grep -qi "discovery set is empty"; then
  note_fail "mutation 4: expected an 'ERROR: discovery set is empty' message, got: $out"
fi

echo "== Mutation 5: insert a 4-backtick fence line (unclassifiable) =="
fresh_work
doc="$WORK_DIR/ds-implement-ticket.md"
python3 - "$doc" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()
lines.insert(5, "````\n")
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
fixture_rc=$?
if [ "$fixture_rc" != "0" ]; then
  note_fail "mutation 5: fixture-apply heredoc exited $fixture_rc - mutation did not land"
fi
if ! grep -qF '````' "$doc"; then
  note_fail "mutation 5: injected 4-backtick fence line is not present in the fixture after applying the mutation"
fi
out="$(run_check "$WORK_DIR" 2>&1)"
rc=$?
echo "mutation5 exit=$rc output=[$out]"
if [ "$rc" != "2" ]; then
  note_fail "mutation 5: expected exit 2 (unrecognized fence line), got $rc"
fi
if ! printf '%s' "$out" | grep -qi "unrecognized fence line"; then
  note_fail "mutation 5: expected an 'unrecognized fence line' message, got: $out"
fi

echo "== Mutation 6: delete a closing fence (unterminated fence block) =="
fresh_work
doc="$WORK_DIR/ds-implement-ticket.md"
python3 - "$doc" <<'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()
open_idx = None
for i, line in enumerate(lines):
    if line.rstrip("\n") == "```bash":
        open_idx = i
        break
assert open_idx is not None, "no ```bash fence found"
close_idx = None
for i in range(open_idx + 1, len(lines)):
    if lines[i].rstrip("\n") == "```":
        close_idx = i
        break
assert close_idx is not None, "no closing fence found for the first ```bash block"
del lines[close_idx]
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
fixture_rc=$?
if [ "$fixture_rc" != "0" ]; then
  note_fail "mutation 6: fixture-apply heredoc exited $fixture_rc - mutation did not land"
fi
clean_fence_count="$(grep -cF '```' "$CLEAN_DIR/ds-implement-ticket.md")"
mutated_fence_count="$(grep -cF '```' "$doc")"
if [ "$mutated_fence_count" != "$((clean_fence_count - 1))" ]; then
  note_fail "mutation 6: expected exactly one fence line removed from the fixture (clean=$clean_fence_count, mutated=$mutated_fence_count) - mutation did not land as expected"
fi
out="$(run_check "$WORK_DIR" 2>&1)"
rc=$?
echo "mutation6 exit=$rc output=[$out]"
if [ "$rc" != "2" ]; then
  note_fail "mutation 6: expected exit 2 (unterminated fence block), got $rc"
fi
if ! printf '%s' "$out" | grep -qi "unterminated fence block"; then
  note_fail "mutation 6: expected an 'unterminated fence block' message, got: $out"
fi

echo "== Results =="
if [ "$FAIL" = "0" ]; then
  echo "PASS: clean-tree pass holds; all 6 named DS-192 mutations produce their expected exit code and message"
  exit 0
fi

echo "FAIL: one or more mutations did not hold - see FAIL lines above"
exit 1
