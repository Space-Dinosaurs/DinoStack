#!/usr/bin/env bash
# Purpose: Assert that hooks/session-end-reap-browsers.py (DS-254) is wired
#          into the SESSIONEND hooks array that the REAL .claude/install.sh
#          writes, with the GUARDED command form and a 5s timeout, in the
#          SAME matcher-"*" block as session-end-wrap.js (never a second
#          SessionEnd registration); that its basename is in bin/ds-doctor's
#          MANAGED_HOOK_BASENAMES; and that bin/ds-doctor's
#          check_hook_scripts_exist() actually covers it, both warnings and
#          non-warnings alike.
#
#          Plan gate V5. The registration half is asserted against the
#          GENERATED $FAKE_HOME/.claude/settings.json, never against
#          .claude/install.sh's own source text - same discipline as
#          test_install_worktree_isolation_spawn_guard.sh,
#          test_install_worktree_read_guard.sh and
#          test_install_worktree_write_guard.sh, whose fixture setup this
#          file copies verbatim (the four prompt-suppression seeds plus the
#          git-hooks-dir sandbox), because a faked $HOME lacking `git
#          --git-path hooks` resolution can escape its sandbox and mutate
#          the LIVE primary checkout's pre-commit hook symlink.
#
#          Why the guarded form is load-bearing: `python3 <missing path>`
#          exits 2, and exit 2 on SessionEnd is the BLOCKING code. An
#          unguarded registration that outlives its script (a branch
#          switch, a moved checkout, a reverted PR) would turn every
#          session end into a failure.
#
#          Why the doctor membership is load-bearing: check_hook_scripts_exist()
#          walks the settings.command strings and SKIPS any basename not in
#          MANAGED_HOOK_BASENAMES, so dropping the entry does not make the
#          doctor complain - it makes it silently certify a broken
#          registration as healthy. Both directions are asserted below (a
#          managed-but-missing script FAILS; an unmanaged-and-missing
#          script is ignored).
#
# Public API: ./bin/tests/test_install_session_end_reap_browsers.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
#
# Downstream consumers: developer running locally before commit; CI (the
#                       `bin-sh-tests` job's bin/tests/test_*.sh glob).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. A temporary fake HOME is used; the real ~/.claude
#                is never touched, and the git shim keeps the real
#                pre-commit hook out of reach.
#
# Performance: ~10-20 s wall time (one .claude/install.sh run, which builds
#              the Claude and Cursor adapters).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
REAPER_BASENAME="session-end-reap-browsers.py"

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

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.claude"

# ---------------------------------------------------------------------------
# Seed 1: skill_auto_load key present -> suppresses the ae_write_config
# /dev/tty prompt (gated `if "skill_auto_load" not in config:`).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude/agentic-engineering.json" <<'EOF'
{"skill_auto_load": false}
EOF

# ---------------------------------------------------------------------------
# Seed 2: ~/.claude.json with both MCP servers pre-configured -> suppresses
# both MCP ae_confirm gates (they check $HOME/.claude.json).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude.json" <<'EOF'
{"mcpServers":{"chrome-devtools":{},"mcp-atlassian":{}}}
EOF

# ---------------------------------------------------------------------------
# Seed 3: no-op executables for the five CLI_TOOLS on PATH -> suppresses the
# five ae_confirm "Install <tool>?" prompts (command -v succeeds for all 5).
# ---------------------------------------------------------------------------
FAKE_BIN="$TMP_ROOT/fakebin"
mkdir -p "$FAKE_BIN"
for tool in gh agent-browser lc jira rclone; do
  cat > "$FAKE_BIN/$tool" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$FAKE_BIN/$tool"
done

# ---------------------------------------------------------------------------
# Seed 5 (git-level sandbox): running the REAL .claude/install.sh from an
# isolation worktree calls scripts/lib/precommit.sh's
# resolve_git_hooks_dir(), which shells out to
# `git -C "$REPO_DIR" rev-parse --git-path hooks`. From inside a worktree
# that resolves to the PRIMARY checkout's common `.git/hooks` dir, so an
# unsandboxed run here would re-point the live primary checkout's
# `.git/hooks/pre-commit` symlink at this disposable worktree. A `git` shim
# is placed ahead of the real git on PATH; it recognises ONLY the exact
# `rev-parse --git-path hooks` query and answers with a scratch directory
# inside $TMP_ROOT, passing every other git invocation through untouched.
# ---------------------------------------------------------------------------
REAL_GIT="$(command -v git)"
SCRATCH_HOOKS_DIR="$TMP_ROOT/scratch-git-hooks"
mkdir -p "$SCRATCH_HOOKS_DIR"
cat > "$FAKE_BIN/git" <<EOF
#!/usr/bin/env bash
joined=" \$* "
if [[ "\$joined" == *" rev-parse "* && "\$joined" == *" --git-path "* && "\$joined" == *" hooks"* ]]; then
  echo "$SCRATCH_HOOKS_DIR"
  exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$FAKE_BIN/git"

# ---------------------------------------------------------------------------
# Seed 4: ~/.claude/settings.json with permissions.defaultMode already set to
# bypassPermissions -> suppresses the tty_input permissions-configuration
# prompt (its gate reads perms.get("defaultMode")).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude/settings.json" <<'EOF'
{"permissions":{"defaultMode":"bypassPermissions"}}
EOF

# ---------------------------------------------------------------------------
# Snapshot the AMBIENT git hooks dir before running install.sh, so we can
# assert afterward that this test's git shim actually prevented any
# mutation of it.
# ---------------------------------------------------------------------------
AMBIENT_HOOKS_DIR="$("$REAL_GIT" -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)"
case "$AMBIENT_HOOKS_DIR" in
  /*) : ;;
  *) AMBIENT_HOOKS_DIR="$REPO_DIR/$AMBIENT_HOOKS_DIR" ;;
esac
AMBIENT_PRECOMMIT="$AMBIENT_HOOKS_DIR/pre-commit"
AMBIENT_PRECOMMIT_BEFORE=""
if [[ -L "$AMBIENT_PRECOMMIT" ]]; then
  AMBIENT_PRECOMMIT_BEFORE="$(readlink "$AMBIENT_PRECOMMIT")"
fi

echo ""
echo "=== Running .claude/install.sh against a fully-seeded fake HOME ==="

# DS-231: unset all four harness config-dir vars. Faking $HOME alone is not
# sufficient - .claude/install.sh resolves AE_CONFIG_DIR through
# AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > $HOME/.claude, so a developer
# session with CLAUDE_CONFIG_DIR set would aim the install at that REAL
# directory instead of the fake HOME.
#
# The identity prompt is suppressed with the `--no-identity` FLAG, not the
# AE_NO_IDENTITY env var: install.sh:111 initialises that variable to false
# before argument parsing, so an env-var spelling is clobbered. `< /dev/null`
# alone is also not enough, since the identity lib reads /dev/tty.
env -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR \
  PATH="$FAKE_BIN:$PATH" HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/install.sh" \
  --mode=opt-out --profile=default --no-identity \
  < /dev/null > "$FAKE_HOME/.install_out" 2>&1
INSTALL_RC=$?

# Tolerated failure signature (copied from
# bin/tests/test_hooks_snapshot_no_live_rewire.sh): from a git worktree,
# install.sh's UNRELATED "Installing pre-commit hook" step fails after the
# settings.json wiring this test asserts on has already completed.
if [[ $INSTALL_RC -ne 0 ]]; then
  if grep -q "Installing pre-commit hook" "$FAKE_HOME/.install_out" 2>/dev/null && \
     tail -n 5 "$FAKE_HOME/.install_out" | grep -q "\.git/hooks/pre-commit: Not a directory"; then
    echo "  [warn] install.sh exited $INSTALL_RC at the known worktree-only pre-commit-hook step (unrelated, pre-existing) - tolerated" >&2
  else
    echo "  [install.sh output]:" >&2
    cat "$FAKE_HOME/.install_out" >&2
    _fail "install.sh exited $INSTALL_RC for an unexpected reason"
  fi
fi

SETTINGS="$FAKE_HOME/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  _pass "install.sh wrote ~/.claude/settings.json"
else
  echo "  [install.sh output]:" >&2
  cat "$FAKE_HOME/.install_out" >&2
  _fail "install.sh did not write ~/.claude/settings.json"
  echo ""
  echo "Results: $PASS passed, $FAIL failed."
  exit 1
fi

# ---------------------------------------------------------------------------
# THE core assertion - read the GENERATED settings.json, never install.sh's
# own source.
# ---------------------------------------------------------------------------
echo ""
python3 - "$SETTINGS" "$REAPER_BASENAME" <<'PY'
import json
import sys

settings_path, basename = sys.argv[1], sys.argv[2]
with open(settings_path) as handle:
    data = json.load(handle)

failures = []


def check(ok, message):
    print(("PASS: " if ok else "FAIL: ") + message)
    if not ok:
        failures.append(message)


session_end = data.get("hooks", {}).get("SessionEnd", [])
star_blocks = [b for b in session_end if b.get("matcher") == "*"]
check(len(star_blocks) == 1,
      "exactly one SessionEnd matcher-* block (got %d)" % len(star_blocks))

block = star_blocks[0] if star_blocks else {"hooks": []}
commands = [h.get("command", "") for h in block.get("hooks", [])]
reaper = [c for c in commands if basename in c]
check(len(reaper) == 1,
      "exactly one SessionEnd entry references %s (got %d)"
      % (basename, len(reaper)))
check(any("session-end-wrap.js" in c for c in commands),
      "the pre-existing session-end-wrap.js entry is still in the SAME block")

if reaper:
    command = reaper[0]
    check(command.startswith("test -f ") and " && " in command
          and command.rstrip().endswith("|| exit 0"),
          "the registration uses the guarded `test -f ... && ... || exit 0` "
          "form, not a bare interpreter invocation: %r" % command)
    entries = [h for h in block.get("hooks", [])
               if basename in h.get("command", "")]
    check(entries and entries[0].get("timeout") == 5,
          "the registration carries \"timeout\": 5 (got %r)"
          % (entries[0].get("timeout") if entries else None))
    # The guarded form must name the script it guards, twice.
    check(command.count(basename) == 2,
          "the guarded command names the script exactly twice "
          "(test -f <path> && python3 <path>): %r" % command)

print("")
sys.exit(1 if failures else 0)
PY
if [[ $? -eq 0 ]]; then
  _pass "generated SessionEnd registration assertions"
else
  _fail "generated SessionEnd registration assertions"
fi

# ---------------------------------------------------------------------------
# bin/ds-doctor: the basename must be in MANAGED_HOOK_BASENAMES, and the
# check that consumes that list must actually cover the hook.
# ---------------------------------------------------------------------------
echo ""
python3 - "$REPO_DIR" "$REAPER_BASENAME" "$TMP_ROOT" <<'PY'
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile

repo_dir, basename, tmp_root = sys.argv[1], sys.argv[2], sys.argv[3]

loader = importlib.machinery.SourceFileLoader(
    "ds_doctor_under_test", os.path.join(repo_dir, "bin", "ds-doctor"))
spec = importlib.util.spec_from_loader(loader.name, loader)
doctor_module = importlib.util.module_from_spec(spec)
loader.exec_module(doctor_module)

failures = []


def check(ok, message):
    print(("PASS: " if ok else "FAIL: ") + message)
    if not ok:
        failures.append(message)


check(basename in doctor_module.MANAGED_HOOK_BASENAMES,
      "bin/ds-doctor MANAGED_HOOK_BASENAMES contains %s" % basename)

# Functional pin, both directions. check_hook_scripts_exist() skips any
# basename absent from the list, so membership is only load-bearing if a
# managed-but-missing script is reported and an unmanaged one is not. The
# paths are scratch paths that deliberately do not exist; the check only
# tests os.path.exists() on the token it parses out of the command string,
# and it only considers tokens containing the literal "/hooks/" - hence the
# `scratch/hooks/` component.
scratch_hooks = os.path.join(tmp_root, "scratch", "hooks")
missing_managed = os.path.join(scratch_hooks, basename)
missing_unmanaged = os.path.join(scratch_hooks, "not-a-managed-hook.py")
assert not os.path.exists(missing_managed), missing_managed
assert not os.path.exists(missing_unmanaged), missing_unmanaged

fixture = os.path.join(tmp_root, "doctor-fixture-settings.json")
with open(fixture, "w") as handle:
    json.dump({"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "test -f %s && python3 %s || exit 0"
         % (missing_managed, missing_managed), "timeout": 5},
        {"type": "command", "command": "test -f %s && python3 %s || exit 0"
         % (missing_unmanaged, missing_unmanaged), "timeout": 5},
    ]}]}}, handle)

doctor_module._settings_path = lambda: doctor_module.Path(fixture)
doc = doctor_module.Doctor(doctor_module.Path(repo_dir), fix=False)
doctor_module.check_hook_scripts_exist(doc)
findings = "\n".join("%s %s" % pair for pair in doc.findings)
check(any(status == "FAIL" and missing_managed in message
          for status, message in doc.findings),
      "check_hook_scripts_exist() FAILs on the missing managed script "
      "(%s)" % basename)
check(not any(missing_unmanaged in message for _, message in doc.findings),
      "check_hook_scripts_exist() ignores an unmanaged basename "
      "(so membership in the list is what makes the check cover the hook)")
if failures:
    print("--- doctor findings ---")
    print(findings)

print("")
sys.exit(1 if failures else 0)
PY
if [[ $? -eq 0 ]]; then
  _pass "bin/ds-doctor membership and functional coverage"
else
  _fail "bin/ds-doctor membership and functional coverage"
fi

# ---------------------------------------------------------------------------
# Sandbox effectiveness: the git shim must have kept the live primary
# checkout's pre-commit hook untouched.
# ---------------------------------------------------------------------------
echo ""
AMBIENT_PRECOMMIT_AFTER=""
if [[ -L "$AMBIENT_PRECOMMIT" ]]; then
  AMBIENT_PRECOMMIT_AFTER="$(readlink "$AMBIENT_PRECOMMIT")"
fi
if [[ "$AMBIENT_PRECOMMIT_BEFORE" == "$AMBIENT_PRECOMMIT_AFTER" ]]; then
  _pass "the ambient git hooks dir was not mutated by this run"
else
  _fail "the ambient pre-commit hook changed: before='$AMBIENT_PRECOMMIT_BEFORE' after='$AMBIENT_PRECOMMIT_AFTER'"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
