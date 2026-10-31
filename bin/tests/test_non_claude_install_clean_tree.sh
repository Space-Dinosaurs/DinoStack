#!/usr/bin/env bash
# Purpose: Regression test for "Claude Code first": outside DS_ALL_HARNESSES=1 a
#          non-Claude installer must not rewrite tracked files in the
#          checkout (a rebuild from a content/ that its committed files lag
#          dirtied the tree, and the next bin/ds-update refused to run). Runs
#          the real .gemini/install.sh and .kimi/install.sh with a fake HOME,
#          after seeding pre-existing dirt in each adapter dir (an edit to a
#          tracked generated file and a new untracked file), and asserts that
#          `git status --porcelain` and the seeded content are unchanged. A
#          second case puts content/ ahead of the committed Kimi files (a
#          renamed section heading) and asserts two Kimi installs leave the
#          tree and .kimi/AGENTS.md unchanged.
#
# Public API: bash bin/tests/test_non_claude_install_clean_tree.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3. Only $HOME is sandboxed; the seeded
#                paths in the live checkout are restored on exit.
#
# Failure modes: a seeded path already dirty before the run fails under CI and
#                skips locally (the restore would discard someone's edit).
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0
FAIL=0
_pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
_fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

MARKER="<!-- test_non_claude_install_clean_tree seeded edit -->"
# adapter|tracked generated file its build rewrites|seeded untracked file
CASES=".gemini|.gemini/skills/dinostack/SKILL.md|.gemini/zz-test-untracked.txt
.kimi|.kimi/AGENTS.md|.kimi/zz-test-untracked.txt"

SEEDED_TRACKED=()
SEEDED_UNTRACKED=()
FAKE_HOME="$(mktemp -d)"
restore_seeded() {
  local p
  for p in ${SEEDED_TRACKED[@]+"${SEEDED_TRACKED[@]}"}; do
    git -C "$REPO_DIR" checkout -q -- "$p"
  done
  for p in ${SEEDED_UNTRACKED[@]+"${SEEDED_UNTRACKED[@]}"}; do
    rm -f "$REPO_DIR/$p"
  done
  SEEDED_TRACKED=()
  SEEDED_UNTRACKED=()
}
cleanup() {
  restore_seeded
  find "${FAKE_HOME:?}" -depth -delete 2>/dev/null
}
trap cleanup EXIT

while IFS='|' read -r adapter tracked untracked; do
  if [ -n "$(git -C "$REPO_DIR" status --porcelain -- "$tracked" "$untracked")" ]; then
    if [ -n "${CI:-}" ]; then
      _fail "$adapter: $tracked or $untracked is already dirty; cannot seed it"
      continue
    fi
    echo "SKIP: $adapter: $tracked or $untracked is already dirty locally"
    continue
  fi
  # Replace the file rather than appending in place, so a hardlink into
  # content/ is never written through.
  python3 - "$REPO_DIR/$tracked" "$MARKER" <<'PYEOF'
import os, sys
path, marker = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
tmp = path + ".seed-tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(text + "\n" + marker + "\n")
os.replace(tmp, path)
PYEOF
  SEEDED_TRACKED+=("$tracked")
  printf 'pre-existing untracked file\n' > "$REPO_DIR/$untracked"
  SEEDED_UNTRACKED+=("$untracked")

  before="$(git -C "$REPO_DIR" status --porcelain)"
  mkdir -p "$FAKE_HOME/.claude"
  printf '{"skill_auto_load": false}\n' > "$FAKE_HOME/.claude/agentic-engineering.json"
  env -u DS_ALL_HARNESSES -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME \
    HOME="$FAKE_HOME" bash "$REPO_DIR/$adapter/install.sh" \
    --no-identity --mode=opt-out --profile=default </dev/null >"$FAKE_HOME/install.out" 2>&1
  rc=$?
  after="$(git -C "$REPO_DIR" status --porcelain)"

  if [ "$rc" -eq 0 ]; then
    _pass "$adapter: install.sh exits 0"
  else
    _fail "$adapter: install.sh exited $rc:
$(tail -20 "$FAKE_HOME/install.out")"
  fi
  if [ "$before" = "$after" ]; then
    _pass "$adapter: git status --porcelain unchanged by the install"
  else
    _fail "$adapter: the install changed git status:
--- before
$before
--- after
$after"
  fi
  if grep -qF -- "$MARKER" "$REPO_DIR/$tracked"; then
    _pass "$adapter: the pre-existing edit to $tracked survived"
  else
    _fail "$adapter: the install rewrote $tracked, dropping the pre-existing edit"
  fi
  if [ -f "$REPO_DIR/$untracked" ]; then
    _pass "$adapter: the pre-existing untracked $untracked survived"
  else
    _fail "$adapter: the install deleted the pre-existing untracked $untracked"
  fi
done <<EOF
$CASES
EOF
restore_seeded

# Content ahead of the committed Kimi files: .kimi/install.sh reads content/
# at install time, so a renamed section heading must not make it rewrite or
# grow the tracked .kimi/AGENTS.md, on the first install or on a repeat.
AHEAD=content/sections/03-planning-artifacts.md
if [ -n "$(git -C "$REPO_DIR" status --porcelain -- "$AHEAD" .kimi/AGENTS.md)" ]; then
  if [ -n "${CI:-}" ]; then
    _fail "content-ahead: $AHEAD or .kimi/AGENTS.md is already dirty; cannot seed it"
  else
    echo "SKIP: content-ahead: $AHEAD or .kimi/AGENTS.md is already dirty locally"
  fi
else
  python3 - "$REPO_DIR/$AHEAD" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
new, n = re.subn(r"^## (.+)$", r"## \1 (renamed by test)", text, count=1, flags=re.M)
assert n == 1, "no '## ' heading to rename"
tmp = path + ".seed-tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(new)
os.replace(tmp, path)
PYEOF
  # .kimi/AGENTS.md is restored on exit too, in case an install grew it.
  SEEDED_TRACKED+=("$AHEAD" ".kimi/AGENTS.md")
  agents_bytes_before="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
  before="$(git -C "$REPO_DIR" status --porcelain)"
  for run in 1 2; do
    env -u DS_ALL_HARNESSES -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME \
      HOME="$FAKE_HOME" bash "$REPO_DIR/.kimi/install.sh" \
      --no-identity --mode=opt-out --profile=default </dev/null >"$FAKE_HOME/install.out" 2>&1
    rc=$?
    after="$(git -C "$REPO_DIR" status --porcelain)"
    agents_bytes_after="$(wc -c < "$REPO_DIR/.kimi/AGENTS.md" | tr -d '[:space:]')"
    if [ "$rc" -eq 0 ] && [ "$before" = "$after" ] && [ "$agents_bytes_before" = "$agents_bytes_after" ]; then
      _pass "content-ahead: Kimi install $run leaves git status and .kimi/AGENTS.md ($agents_bytes_after B) unchanged"
    else
      _fail "content-ahead: Kimi install $run (exit $rc) changed the tree or .kimi/AGENTS.md ($agents_bytes_before B -> $agents_bytes_after B):
--- before
$before
--- after
$after"
    fi
  done
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
[ "$FAIL" -eq 0 ] || exit 1
exit 0
