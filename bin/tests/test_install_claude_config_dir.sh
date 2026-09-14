#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Regression tests for DS-231 - .claude/install.sh must honor
#          CLAUDE_CONFIG_DIR, the variable Claude Code itself reads. Before
#          DS-231, AE_CONFIG_DIR's chain was flag > AGENTIC_CONFIG_DIR >
#          $HOME/.claude, so an operator with CLAUDE_CONFIG_DIR set got the
#          dinostack output style installed into a directory the harness
#          never reads and /config never listed it.
#
#          Assertions are made against a REAL install invocation (AC2
#          explicitly forbids extracting the code block and hand-binding
#          variables), covering: the unbridged redirect (T1/T2), the pinned
#          activation config (T3), identity scope not flipping (T4), a
#          bridged symlink layout exiting 0 (T5), idempotent overwrite of a
#          stale real copy (T6), refusal of a symlink escaping $HOME (T7),
#          and the unchanged no-env default (T8).
#
# Public API: bash bin/tests/test_install_claude_config_dir.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3, mktemp, tar, shasum/sha256sum.
#
# Failure modes:
#   - Any failing assertion prints "FAIL: ..." and the script exits 1.
#   - CONTAINMENT (the reason this file does not use
#     bin/tests/lib/precommit-hook-guard.sh): faking $HOME is NOT sufficient
#     for an install test. .claude/install.sh calls
#     install_precommit_hook "$REPO_DIR", and scripts/lib/precommit.sh
#     resolves the hooks dir with `rev-parse --git-path hooks` against that
#     repo, which is entirely independent of $HOME - so a $HOME-only sandbox
#     lets the installer write the LIVE checkout's .git/hooks/pre-commit.
#     This file therefore fakes REPO_DIR too: it exports the tracked tree
#     into a sandbox and re-inits a repo there, so hooks-dir resolution
#     cannot name the live checkout. That is a structural argument, and it is
#     ASSERTED rather than assumed - assert_sandbox_hooks_dir() hard-fails
#     (never skips) if the resolved hooks path is not under the sandbox.
#   - The sandbox seeds agentic-engineering.json with skill_auto_load set, and
#     passes --no-identity, to avoid the /dev/tty prompt deadlock documented
#     at bin/tests/test_hooks_snapshot_migration.sh:56-67.
#
# Performance: one tree export (~60 MB of tracked content) plus five install
#   runs; measured well under two minutes.
# ---------------------------------------------------------------------------
set -uo pipefail

LIVE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

sha() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

# Realpath, not the raw mktemp value: on macOS mktemp -d hands back
# /var/folders/... while git reports /private/var/folders/..., and the
# containment assertion below is a prefix test that must not be defeated by
# that alias.
SB="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$SB"' EXIT

# ---------------------------------------------------------------------------
# Sandbox repo: export the tracked tree and re-init it in place, so every
# repo-relative resolution the installer performs (notably the git hooks dir)
# lands inside $SB. See the CONTAINMENT note in the manifest above.
# ---------------------------------------------------------------------------
mkdir -p "$SB/repo" "$SB/home"
# Export the tracked WORKING TREE, not HEAD: this must exercise the installer
# as it currently stands on disk, so a developer running the suite before
# committing tests the change they are about to commit rather than its parent.
( cd "$LIVE_REPO" && git ls-files -z | tar -cf - --null -T - ) | tar -xf - -C "$SB/repo"
git -C "$SB/repo" init -q
git -C "$SB/repo" config user.email "test@example.invalid"
git -C "$SB/repo" config user.name "DS-231 Test"

assert_sandbox_hooks_dir() {
  local resolved
  resolved="$(git -C "$SB/repo" rev-parse --path-format=absolute --git-path hooks 2>/dev/null)"
  if [[ -z "$resolved" ]]; then
    echo "  FAIL: could not resolve the sandbox repo's hooks dir - refusing to run" >&2
    exit 1
  fi
  case "$resolved" in
    "$SB"/*) pass "sandbox hooks dir resolves inside the sandbox ($resolved)" ;;
    *)
      echo "  FAIL: sandbox hooks dir resolved OUTSIDE the sandbox: $resolved" >&2
      echo "        Refusing to run - this test would write the live checkout's hook." >&2
      exit 1
      ;;
  esac
}
assert_sandbox_hooks_dir

STYLE_SRC="$SB/repo/.claude/skills/dinostack/output-styles/dinostack.md"
if [[ ! -f "$STYLE_SRC" ]]; then
  echo "  FAIL: built output style missing from the exported tree: $STYLE_SRC" >&2
  exit 1
fi

# Seed the activation config so the skill_auto_load prompt never reaches
# /dev/tty, and run every install with --no-identity for the same reason.
seed_home() {
  local home="$1"
  mkdir -p "$home/.claude"
  printf '%s\n' '{"skill_auto_load": false, "mode": "opt-out", "profile": "default"}' \
    > "$home/.claude/agentic-engineering.json"
}

# run_install <home> <config-dir-or-empty> -> combined output on stdout, the
# installer's exit code in $RC_FILE.
#
# The rc goes through a FILE, not a global. Callers use
# OUT="$(run_install ...)", which runs this function in a command-substitution
# SUBSHELL - a variable assigned here would never reach the parent, and the
# parent would silently read a stale initial value. That made the T5 and T7 rc
# assertions vacuously true in an earlier draft of this file.
RC_FILE="$SB/.last-install-rc"
run_install() {
  local home="$1" cfgdir="${2:-}" rc=0
  if [[ -n "$cfgdir" ]]; then
    env -u AGENTIC_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR \
      HOME="$home" CLAUDE_CONFIG_DIR="$cfgdir" \
      bash "$SB/repo/.claude/install.sh" --no-identity --mode=opt-out --profile=default 2>&1 \
      || rc=$?
  else
    env -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR \
      HOME="$home" \
      bash "$SB/repo/.claude/install.sh" --no-identity --mode=opt-out --profile=default 2>&1 \
      || rc=$?
  fi
  printf '%s' "$rc" > "$RC_FILE"
}
last_rc() { cat "$RC_FILE"; }

# ---------------------------------------------------------------------------
# T1/T2/T3/T4: CLAUDE_CONFIG_DIR set, no bridging symlinks.
# ---------------------------------------------------------------------------
H1="$SB/home/h1"; ALT1="$H1/altcfg"
seed_home "$H1"; mkdir -p "$ALT1"
OUT1="$(run_install "$H1" "$ALT1")"

# T1: the output style follows CLAUDE_CONFIG_DIR, and does NOT land in ~/.claude.
echo "  (T1) alt: $(ls -1 "$ALT1/output-styles" 2>/dev/null | tr '\n' ' ')"
echo "  (T1) home: $(ls -1 "$H1/.claude/output-styles" 2>/dev/null | tr '\n' ' ')"
if [[ -f "$ALT1/output-styles/dinostack.md" ]] \
  && cmp -s "$STYLE_SRC" "$ALT1/output-styles/dinostack.md"; then
  pass "T1 output style installed into CLAUDE_CONFIG_DIR, byte-equal to source"
else
  fail "T1 output style NOT installed into CLAUDE_CONFIG_DIR ($ALT1)"
fi
if [[ -e "$H1/.claude/output-styles/dinostack.md" ]]; then
  fail "T1 output style ALSO landed in \$HOME/.claude (divergent copy)"
else
  pass "T1 no output-style copy left in \$HOME/.claude"
fi

# T2: settings.json follows too.
if [[ -f "$ALT1/settings.json" ]]; then
  pass "T2 settings.json written into CLAUDE_CONFIG_DIR"
else
  fail "T2 settings.json NOT written into CLAUDE_CONFIG_DIR"
fi
if [[ -e "$H1/.claude/settings.json" ]]; then
  fail "T2 settings.json ALSO written into \$HOME/.claude"
else
  pass "T2 no settings.json left in \$HOME/.claude"
fi

# T3: agentic-engineering.json is PINNED to $HOME/.claude - a bare
# CLAUDE_CONFIG_DIR is not an explicit redirect. Four readers hardcode the
# $HOME path (bin/ds-config:86, bin/ds-status:127, bin/ds-disable:50,
# hooks/skill-auto-load-check.sh:56), so moving it would split activation state.
if [[ -f "$H1/.claude/agentic-engineering.json" ]]; then
  pass "T3 agentic-engineering.json stayed in \$HOME/.claude"
else
  fail "T3 agentic-engineering.json missing from \$HOME/.claude"
fi
if [[ -e "$ALT1/agentic-engineering.json" ]]; then
  fail "T3 agentic-engineering.json followed CLAUDE_CONFIG_DIR (activation state split)"
else
  pass "T3 agentic-engineering.json did NOT follow CLAUDE_CONFIG_DIR"
fi

# T4: identity scope must not flip to profile merely because the var is set.
if grep -Fq -- "--scope profile" <<<"$OUT1"; then
  fail "T4 install flipped identity to profile scope on a bare CLAUDE_CONFIG_DIR"
else
  pass "T4 identity scope not flipped by a bare CLAUDE_CONFIG_DIR"
fi

# ---------------------------------------------------------------------------
# T5: bridged layout. settings.json and CLAUDE.md in the alt dir are symlinks
# into the real ~/.claude tree - the measured shape of a multi-profile host.
# A chain-only fix (adding CLAUDE_CONFIG_DIR to :136 and nothing else) makes
# the installer abort here on the islink write refusals, turning a working
# install into a hard failure. This is the load-bearing assertion.
# ---------------------------------------------------------------------------
H2="$SB/home/h2"; ALT2="$H2/altcfg"
seed_home "$H2"; mkdir -p "$ALT2" "$H2/.claude"
printf '%s\n' '{}' > "$H2/.claude/settings.json"
printf '%s\n' '# pre-existing' > "$H2/.claude/CLAUDE.md"
ln -sfn "$H2/.claude/settings.json" "$ALT2/settings.json"
ln -sfn "$H2/.claude/CLAUDE.md" "$ALT2/CLAUDE.md"

OUT2="$(run_install "$H2" "$ALT2")"
RC2="$(last_rc)"
if [[ "$RC2" -eq 0 ]]; then
  pass "T5 bridged install exited 0"
else
  fail "T5 bridged install exited $RC2 (expected 0)"
  echo "$OUT2" | tail -20 >&2
fi
if grep -Fq "refusing to write through symlink" <<<"$OUT2"; then
  fail "T5 bridged install hit a symlink write refusal"
else
  pass "T5 no symlink write refusal on the bridged layout"
fi
# The bridge must be written THROUGH, leaving one real file, not a second copy
# shadowing the symlink.
if [[ -L "$ALT2/settings.json" ]]; then
  pass "T5 bridge symlink preserved (not replaced by a second real file)"
else
  fail "T5 bridge symlink at $ALT2/settings.json was replaced"
fi
STYLE_COUNT=$(find "$H2" -name dinostack.md -path '*output-styles*' | wc -l | tr -d ' ')
if [[ "$STYLE_COUNT" -eq 1 ]]; then
  pass "T5 exactly one dinostack.md on disk"
else
  fail "T5 expected exactly 1 dinostack.md on disk, found $STYLE_COUNT"
  find "$H2" -name dinostack.md -path '*output-styles*' >&2
fi

# ---------------------------------------------------------------------------
# T6: stale real copy at the destination is overwritten, not left divergent.
# ---------------------------------------------------------------------------
H3="$SB/home/h3"; ALT3="$H3/altcfg"
seed_home "$H3"; mkdir -p "$ALT3/output-styles"
printf '%s\n' 'STALE JUNK - must be overwritten' > "$ALT3/output-styles/dinostack.md"
run_install "$H3" "$ALT3" >/dev/null
if cmp -s "$STYLE_SRC" "$ALT3/output-styles/dinostack.md"; then
  pass "T6 stale real copy overwritten with the built source"
else
  fail "T6 stale real copy survived the install"
fi

# ---------------------------------------------------------------------------
# T7: a destination symlinked OUTSIDE $HOME must be refused, victim untouched.
# The resolver's $HOME-containment test is what makes this hold; removing it
# would let the install write through the link.
# ---------------------------------------------------------------------------
H4="$SB/home/h4"; ALT4="$H4/altcfg"
seed_home "$H4"; mkdir -p "$ALT4"
VICTIM="$SB/victim-outside-home.json"
printf '%s\n' '{"victim":"do not touch"}' > "$VICTIM"
VICTIM_SHA_BEFORE="$(sha "$VICTIM")"
ln -sfn "$VICTIM" "$ALT4/settings.json"

OUT4="$(run_install "$H4" "$ALT4")"
RC4="$(last_rc)"
VICTIM_SHA_AFTER="$(sha "$VICTIM")"
if [[ "$VICTIM_SHA_BEFORE" == "$VICTIM_SHA_AFTER" ]]; then
  pass "T7 victim file outside \$HOME unmodified"
else
  fail "T7 victim file outside \$HOME WAS MODIFIED through the symlink"
fi
echo "  (T7) rc=$RC4; refusal lines:"; grep -Fn "refusing" <<<"$OUT4" | sed 's/^/        /'
if [[ "$RC4" -ne 0 ]] || grep -Eq "refusing to write (settings.json )?through symlink" <<<"$OUT4"; then
  pass "T7 install refused the escaping symlink (rc=$RC4)"
else
  fail "T7 install did not refuse the escaping symlink (rc=$RC4)"
fi

# ---------------------------------------------------------------------------
# T8: no config-dir env set at all - unchanged default behavior.
# ---------------------------------------------------------------------------
H5="$SB/home/h5"
seed_home "$H5"
run_install "$H5" "" >/dev/null
if [[ -f "$H5/.claude/settings.json" && -f "$H5/.claude/output-styles/dinostack.md" ]]; then
  pass "T8 default install targets \$HOME/.claude"
else
  fail "T8 default install did NOT target \$HOME/.claude"
fi

# ---------------------------------------------------------------------------
# Containment re-assertion: the live checkout must be untouched.
# ---------------------------------------------------------------------------
assert_sandbox_hooks_dir

echo ""
if [[ "$FAILS" -eq 0 ]]; then
  echo "All DS-231 CLAUDE_CONFIG_DIR install tests passed."
  exit 0
fi
echo "$FAILS assertion(s) failed." >&2
exit 1
