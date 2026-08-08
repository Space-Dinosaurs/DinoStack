#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Tests for .claude/install.sh symlink-convergence, guarded
#          repo_dir write (Changes 1-3 in the converging-symlinks PR), the
#          legacy path-scoped Write() permission-rule migration, and the
#          DS-143 gated import-strip / skill_auto_load migration.
#
# Public API: bash .claude/tests/install-converge.test.sh
#             Exits 0 on all pass, non-zero on any failure.
#
# Upstream deps: bash, python3, git, ln, readlink, mktemp.
#
# Downstream consumers: developer running locally; CI.
#
# Failure modes: failures print the failing test name and exit 1.
#                All side effects use TEMP HOME dirs; the real ~/.claude and
#                ~/.agentic are NEVER touched.
#
# Performance: ~44 s wall time (17 install.sh invocations after the DS-143
#              Skeptic loop 2 fix pass, up from 15; each runs two full adapter
#              builds against the real checkout).
#
# Regression coverage:
#   - Change 1: stale "ours" symlink (target under .../DinoStack/...) is
#     RE-POINTED rather than skipped.
#   - Change 1: broken "ours" symlink is re-pointed.
#   - Change 1: a real file at dst is left untouched (skip).
#   - Change 1: a symlink pointing outside any methodology checkout is skipped.
#   - Change 2: --dry-run makes no filesystem changes.
#   - Change 2 (extended, DS-144): --dry-run leaves an existing CLAUDE.md
#     managed block byte-identical (case (e)), and creates no CLAUDE.md at
#     all when one never existed (case (e2)).
#   - Case (a) positive control (DS-144): a non-dry-run install still writes
#     a complete CLAUDE.md managed block (both markers present), guarding
#     against an over-gating fix that deletes the write entirely instead of
#     wrapping it. Also asserts SKILL_LINK_OK's warning does NOT fire when
#     the skill symlink is freshly established; case (e2) asserts it DOES
#     fire when the skill link was never established under a fresh dry-run.
#   - Change 3: clobber guard - valid DIFFERENT repo_dir is NOT overwritten;
#     absent/invalid repo_dir IS written.
#   - Case (g): legacy path-scoped Write(<cfg>/**) / Write(<cfg>/projects/**)
#     allow rules (ignored by Claude Code's file-permission checks, only
#     Edit(path) rules match) are migrated out of an existing
#     bypassPermissions settings.json when the bare "Write" rule is already
#     present pre-migration; recommended Edit path rules and the bare
#     Write/Edit tool rules are retained; the write fires even when nothing
#     else is missing. Also asserts idempotency: running install a second
#     time against the already-migrated state reports "already configured"
#     and does not attempt to remove legacy rules again. The migration is
#     single-sourced in the install.sh `_migrated_allow()` helper, so this
#     case's assertions cover both the already-bypass branch and the
#     fresh-configure branch (both call the same helper).
#   - Case (h): legacy path-scoped Write(<cfg>/**) allow rule is RETAINED
#     (not stripped) when the bare "Write" rule is ABSENT pre-migration.
#     This does not change effective permissions either way (the scoped
#     rule is inert; bare Write is added by the recommended-merge
#     regardless) - retaining it instead avoids the installer making a
#     surprising-looking edit to a config a user may have deliberately
#     narrowed, at the cost of leaving Claude Code's startup warning about
#     the inert scoped rule in place for that edge case. The install
#     output reports added rules, not a legacy-rule removal.
#   - Case (a) (extended, DS-143): good-link fixture - the emitted CLAUDE.md
#     managed block drops the three @-import lines, the registry-refresh
#     restart notice fires, and the emitted table body is asserted
#     byte-equal to content/templates/claude-managed-content.md (wiring
#     assertion - guards against a lean block that only "looks right"
#     against a hardcoded copy instead of genuinely reading the template).
#   - Case (i): blocked-gate fixture (a real file at the skill symlink
#     destination forces SKILL_LINK_OK=false) - the three @-import lines
#     are RETAINED, the keep-imports warning fires, and the restart notice
#     does NOT fire.
#   - Case (j): migration fixture - a pre-existing old-format block plus
#     skill_auto_load:false plus a good skill link ends, after one run,
#     with the lean block AND skill_auto_load force-set to true.
#   - Case (k): negative migration control - an already-migrated (lean)
#     block plus a user-set skill_auto_load:false stays false (the
#     migration self-disarms once the old @-import marker is gone from
#     disk). Also asserts (MINOR-4, Skeptic loop 2) that the
#     registry-refresh restart notice does NOT fire on this idempotent
#     no-op rewrite, contrasting with case (a)'s fresh create/strip where
#     it must.
#   - Case (l) (Skeptic loop 2, MAJOR-2): the UserPromptSubmit
#     skill-auto-load-check command written into settings.json carries the
#     AE_ADAPTER=claude tag, immunizing it against an ambient AE_ADAPTER env
#     var accidentally routing it into the shared hook script's codex|gemini
#     exit-0 no-op path.
#   - Case (m) (Skeptic loop 2, MINOR-3): a template file missing its
#     manifest comment terminator ("-->") makes install.sh fail loudly and
#     leave CLAUDE.md untouched, instead of silently shipping the whole
#     file (manifest included) into the user's managed block.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"

if [[ ! -f "$INSTALL_SH" ]]; then
  echo "FAIL: $INSTALL_SH not found" >&2
  exit 1
fi

PASS=0
FAIL=0
FAKE_HOME=""

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

_cleanup() {
  if [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]]; then
    rm -rf "$FAKE_HOME"
  fi
}
trap _cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: run install.sh with a temp HOME, capturing output.
# Passes --mode=opt-out --profile=default to suppress interactive prompts.
# Extra args are passed through.
# ---------------------------------------------------------------------------
_run_install() {
  local fake_home="$1"
  shift
  # Ensure the fake HOME has the minimal ~/.agentic dir so repo-dir.sh works.
  mkdir -p "$fake_home/.agentic"
  # Run install.sh with fake HOME; stdin is /dev/null to skip TTY prompts.
  HOME="$fake_home" bash "$INSTALL_SH" --mode=opt-out --profile=default "$@" \
    < /dev/null > "$fake_home/.install_out" 2>&1
  return $?
}

# Source dir that install.sh will symlink FROM (agents dir used as a concrete target).
AGENTS_SRC="$REPO_DIR/.claude/agents"

# Pick one .md file from agents/ to use as a concrete fixture target.
_pick_fixture_file() {
  local f
  for f in "$AGENTS_SRC"/*.md; do
    [[ -e "$f" ]] && { echo "$f"; return 0; }
  done
  echo ""
}

FIXTURE_SRC="$(_pick_fixture_file)"
if [[ -z "$FIXTURE_SRC" ]]; then
  echo "FAIL: no .md fixture file found in $AGENTS_SRC" >&2
  exit 1
fi
FIXTURE_NAME="$(basename "$FIXTURE_SRC")"

# ===========================================================================
# Test cases
# ===========================================================================

# ---------------------------------------------------------------------------
# Case (a): stale "ours" symlink (target under fake .../DinoStack/...) gets
#           RE-POINTED to the correct src.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Create a fake "other DinoStack checkout" path (doesn't need to exist for
# the ownership predicate - just needs to match */DinoStack/*).
FAKE_OTHER="/tmp/other-DinoStack/path/to/$FIXTURE_NAME"
ln -s "$FAKE_OTHER" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# After install, the symlink should now point to the real src.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$FIXTURE_SRC" ]]; then
    _pass "case (a): stale 'ours' symlink re-pointed"
  else
    _fail "case (a): expected target '$FIXTURE_SRC', got '$actual_target'"
  fi
else
  _fail "case (a): $FIXTURE_NAME is not a symlink after install"
fi

# Also verify that the install output mentioned re-pointing (~ line).
if grep -q "~ $FIXTURE_NAME" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (a): install output includes re-point indicator"
else
  _fail "case (a): install output did not include '~ $FIXTURE_NAME' indicator"
fi

# Positive control (DS-144): a non-dry-run install still writes a complete
# CLAUDE.md managed block, guarding against an over-gating fix that deletes
# the write entirely instead of wrapping it. Also asserts SKILL_LINK_OK's
# warning does NOT fire when the skill symlink freshly links (this fixture's
# only pre-populated dir is .claude/agents, so $SKILLS_DST is absent and the
# real `ln -s` runs).
if [[ -f "$FAKE_HOME/.claude/CLAUDE.md" ]] \
   && grep -Fq "BEGIN managed-by-agentic-engineering" "$FAKE_HOME/.claude/CLAUDE.md" \
   && grep -Fq "END managed-by-agentic-engineering" "$FAKE_HOME/.claude/CLAUDE.md"; then
  _pass "case (a): non-dry-run install still writes CLAUDE.md with both markers"
else
  _fail "case (a): non-dry-run install did not write a complete managed CLAUDE.md block"
fi
if grep -Fq "WARNING: the agentic-engineering skill is not linked to this checkout" "$FAKE_HOME/.install_out"; then
  _fail "case (a): SKILL_LINK_OK warning fired even though the skill was freshly linked"
else
  _pass "case (a): no SKILL_LINK_OK warning when the skill links successfully"
fi

# DS-143: good-link fixture - the @-import lines must be gone (the table is
# written from the template instead), and the registry-refresh restart
# notice must fire because this run actually stripped the imports.
_case_a_import_count="$(grep -c "@skills/agentic-engineering" "$FAKE_HOME/.claude/CLAUDE.md" 2>/dev/null)"
if [[ "$_case_a_import_count" -eq 0 ]]; then
  _pass "case (a): DS-143 good-link CLAUDE.md contains no @skills/agentic-engineering import lines"
else
  _fail "case (a): DS-143 good-link CLAUDE.md still contains @skills/agentic-engineering import lines (count=$_case_a_import_count)"
fi

if grep -Fq "IMPORTANT: skill definitions changed" "$FAKE_HOME/.install_out"; then
  _pass "case (a): DS-143 good-link install output includes the registry-refresh restart notice"
else
  _fail "case (a): DS-143 good-link install output missing the registry-refresh restart notice"
fi

# DS-143 wiring assertion (mandatory): the emitted table body must be
# byte-equal to content/templates/claude-managed-content.md's post-manifest
# body - a lean block that merely "looks right" against a hardcoded copy is
# not acceptable coverage for single-sourcing.
_case_a_table="$(python3 -c "
import re, sys
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(
    r'<!-- BEGIN managed-by-agentic-engineering -->\n(.*)\n<!-- END managed-by-agentic-engineering -->',
    content, re.DOTALL
)
sys.stdout.write(m.group(1) if m else '')
" "$FAKE_HOME/.claude/CLAUDE.md" 2>/dev/null)"
_template_body="$(python3 -c "
import sys
with open(sys.argv[1]) as f:
    data = f.read()
idx = data.find('-->')
body = data[idx + 3:].strip(chr(10))
sys.stdout.write(body)
" "$REPO_DIR/content/templates/claude-managed-content.md" 2>/dev/null)"
if [[ -n "$_template_body" ]] && [[ "$_case_a_table" == "$_template_body" ]]; then
  _pass "case (a): DS-143 wiring - emitted table body is byte-equal to content/templates/claude-managed-content.md"
else
  _fail "case (a): DS-143 wiring - emitted table body diverges from the template"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (b): broken "ours" symlink (target under DinoStack, but file is gone)
#           gets RE-POINTED.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# A symlink under a methodology path that does not actually exist.
ln -s "/nonexistent/DinoStack/path/$FIXTURE_NAME" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$FIXTURE_SRC" ]]; then
    _pass "case (b): broken 'ours' symlink re-pointed"
  else
    _fail "case (b): expected target '$FIXTURE_SRC', got '$actual_target'"
  fi
else
  _fail "case (b): $FIXTURE_NAME is not a symlink after install"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (c): a REAL file at dst is left untouched (skip).
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
REAL_FILE_CONTENT="# real user file - must not be clobbered"
printf '%s\n' "$REAL_FILE_CONTENT" > "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# Must still be a regular file, not a symlink.
if [[ -f "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]] && [[ ! -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_content="$(cat "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_content" == "$REAL_FILE_CONTENT" ]]; then
    _pass "case (c): real file at dst untouched"
  else
    _fail "case (c): real file content was altered"
  fi
else
  _fail "case (c): real file was replaced by a symlink"
fi

# Also check the install output says "skipping" for this file.
if grep -q "! $FIXTURE_NAME" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (c): install output indicates skip for real file"
else
  _fail "case (c): install output did not mention skip for '$FIXTURE_NAME'"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (d): symlink pointing OUTSIDE any methodology checkout is left untouched.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Target is outside any DinoStack path (no DinoStack component).
OUTSIDE_TARGET="/tmp/user/totally-unrelated/$FIXTURE_NAME"
ln -s "$OUTSIDE_TARGET" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# Symlink should still point to the original outside target.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$OUTSIDE_TARGET" ]]; then
    _pass "case (d): out-of-checkout symlink untouched"
  else
    _fail "case (d): out-of-checkout symlink was changed to '$actual_target'"
  fi
else
  _fail "case (d): $FIXTURE_NAME is no longer a symlink (was clobbered)"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (e): --dry-run changes nothing.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Set up a stale "ours" symlink that would normally be re-pointed.
ln -s "/nonexistent/DinoStack/old/$FIXTURE_NAME" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"
OLD_TARGET="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"

# Also exercises DS-144: --dry-run must leave an existing CLAUDE.md managed
# block byte-identical, and must print the CLAUDE.md dry-run intent line.
mkdir -p "$FAKE_HOME/.claude"
cat > "$FAKE_HOME/.claude/CLAUDE.md" <<'EOF'
<!-- BEGIN managed-by-agentic-engineering -->
placeholder managed content
<!-- END managed-by-agentic-engineering -->
EOF
before_sha="$(shasum -a 256 "$FAKE_HOME/.claude/CLAUDE.md" | awk '{print $1}')"
if [[ -z "$before_sha" ]]; then
  _fail "case (e): could not compute before_sha (fixture write failed?)"
fi

_run_install "$FAKE_HOME" --dry-run || true
# NOTE (DS-144, A2): a scrubbed-PATH empirical pre-check
# (`env PATH=/usr/bin:/bin bash .claude/install.sh --mode=opt-out
# --profile=default --dry-run < /dev/null; echo "rc=$?"`) returned rc=1
# (ModuleNotFoundError: yaml, reached via the initial adapter build phase
# which still runs under --dry-run). Per the plan's A2 addendum, any doubt
# means dropping the rc assertion from BOTH case (e) and case (e2) - the
# grep assertions below already satisfy the anti-vacuous-green requirement
# on their own.

# Symlink must NOT have been changed.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$OLD_TARGET" ]]; then
    _pass "case (e): --dry-run left symlink unchanged"
  else
    _fail "case (e): --dry-run changed symlink to '$actual_target' (expected '$OLD_TARGET')"
  fi
else
  _fail "case (e): $FIXTURE_NAME is no longer a symlink after --dry-run"
fi

# Dry-run output should mention "would re-point".
if grep -q "would re-point" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (e): --dry-run output includes 'would re-point'"
else
  _fail "case (e): --dry-run output did not include 'would re-point'"
fi

# The repo_dir config file must NOT be created or modified under --dry-run.
if [[ ! -f "$FAKE_HOME/.agentic/agentic-engineering-config.json" ]]; then
  _pass "case (e): --dry-run did not create the repo_dir config file"
else
  _fail "case (e): --dry-run created ~/.agentic/agentic-engineering-config.json (must not mutate config)"
fi

# DS-144: --dry-run must leave the existing CLAUDE.md managed block
# byte-identical. Skip the comparison entirely when before_sha is empty
# (A6) - otherwise an empty-to-empty match would emit a spurious PASS for
# a fixture-write failure the earlier _fail already flagged.
if [[ -n "$before_sha" ]]; then
  after_sha="$(shasum -a 256 "$FAKE_HOME/.claude/CLAUDE.md" | awk '{print $1}')"
  if [[ "$before_sha" == "$after_sha" ]]; then
    _pass "case (e): --dry-run leaves CLAUDE.md byte-identical"
  else
    _fail "case (e): --dry-run modified CLAUDE.md"
  fi
fi
if grep -Fq "[dry-run] would update managed-by-agentic-engineering" "$FAKE_HOME/.install_out"; then
  _pass "case (e): dry-run output names the CLAUDE.md intent"
else
  _fail "case (e): dry-run output missing CLAUDE.md intent line"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (e2): --dry-run on a machine that has never had ~/.claude/CLAUDE.md
#            creates none. This is the literal "fresh machine" scenario
#            DS-144's ticket describes.
# ---------------------------------------------------------------------------
FAKE_HOME="$(mktemp -d)"
_run_install "$FAKE_HOME" --dry-run || true
# See case (e)'s note re: the rc assertion - DROPPED here per the same
# empirically-determined A2 decision (scrubbed-PATH pre-check returned
# rc=1; any doubt means drop from both cases together).
if grep -Fq "[dry-run] would update managed-by-agentic-engineering" "$FAKE_HOME/.install_out"; then
  _pass "case (e2): dry-run output names the CLAUDE.md intent (proves the run reached the CLAUDE.md phase)"
else
  _fail "case (e2): dry-run output missing CLAUDE.md intent line (absence assertion below is unanchored)"
fi
if [[ ! -f "$FAKE_HOME/.claude/CLAUDE.md" ]]; then
  _pass "case (e2): --dry-run creates no CLAUDE.md when absent"
else
  _fail "case (e2): --dry-run created CLAUDE.md on a fresh machine"
fi
if grep -Fq "WARNING: the agentic-engineering skill is not linked to this checkout" "$FAKE_HOME/.install_out"; then
  _pass "case (e2): SKILL_LINK_OK warning fires when the skill link was never established under dry-run"
else
  _fail "case (e2): SKILL_LINK_OK warning did not fire on fresh dry-run"
fi
# The warning is emitted at two call sites (the skill-symlink block and the
# Summary block, per addendum A5) - a plain at-least-once grep above matches
# the first occurrence and would stay green even if the second (Summary)
# emission drifted or was deleted outright. Pin the count explicitly.
_e2_warning_count="$(grep -Fc "WARNING: the agentic-engineering skill is not linked to this checkout" "$FAKE_HOME/.install_out")"
if [[ "$_e2_warning_count" -eq 2 ]]; then
  _pass "case (e2): SKILL_LINK_OK warning fires exactly twice (skill-symlink block + Summary block)"
else
  _fail "case (e2): SKILL_LINK_OK warning fired $_e2_warning_count time(s), expected exactly 2"
fi
rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f1): clobber guard - config with a valid DIFFERENT repo_dir is NOT
#            overwritten; a warning is printed.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"

# Create a fake "other valid repo" that passes validate_repo_dir (a git repo).
FAKE_OTHER_REPO="$(mktemp -d)"
git -C "$FAKE_OTHER_REPO" init -q
git -C "$FAKE_OTHER_REPO" commit --allow-empty -q -m "init" 2>/dev/null || true

# Write it as the existing repo_dir in the config.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" "$FAKE_OTHER_REPO" <<'PYEOF'
import json, sys, os
cfg, repo_dir = sys.argv[1], sys.argv[2]
with open(cfg, "w") as f:
    json.dump({"repo_dir": repo_dir}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

# Config must still contain the original other repo_dir.
actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ "$actual_repo_dir" == "$FAKE_OTHER_REPO" ]]; then
  _pass "case (f1): valid different repo_dir not overwritten"
else
  _fail "case (f1): repo_dir was changed to '$actual_repo_dir' (expected '$FAKE_OTHER_REPO')"
fi

# Install output (stderr merged into stdout via 2>&1 in _run_install) should
# contain the warning.
if grep -q "warning:" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (f1): warning printed for different valid repo_dir"
else
  _fail "case (f1): no warning printed for different valid repo_dir"
fi

rm -rf "$FAKE_OTHER_REPO" "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f2): absent repo_dir in config IS written.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"
# Write config with no repo_dir key.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"mode": "opt-out"}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ -n "$actual_repo_dir" ]]; then
  _pass "case (f2): absent repo_dir was written (value: $actual_repo_dir)"
else
  _fail "case (f2): repo_dir was not written when config had no repo_dir key"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f3): invalid repo_dir in config IS overwritten.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"
# Write config with a repo_dir that is not a git repo.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"repo_dir": "/nonexistent/path/that/is/not/a/git/repo"}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ -n "$actual_repo_dir" ]] && [[ "$actual_repo_dir" != "/nonexistent/path/that/is/not/a/git/repo" ]]; then
  _pass "case (f3): invalid repo_dir overwritten (new value: $actual_repo_dir)"
else
  _fail "case (f3): invalid repo_dir was not overwritten (got '$actual_repo_dir')"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (g): permissions migration - legacy path-scoped Write() allow rules
#           are removed from an existing bypassPermissions settings.json
#           when the bare "Write" rule is already present pre-migration;
#           recommended Edit path rules and bare Write/Edit are retained;
#           the write fires even when nothing else is missing. Exercises
#           install.sh's single-sourced `_migrated_allow()` helper, which
#           the fresh-configure (interactive) branch also calls - that
#           branch reads /dev/tty and cannot be exercised directly in CI,
#           so this case is the sole coverage for both branches' migration.
#           Also verifies idempotency: a second install run against the
#           now-migrated state reports "already configured" and does not
#           attempt to remove legacy rules a second time.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude"
python3 - "$FAKE_HOME/.claude/settings.json" <<'PYEOF'
import json, sys

settings = {
    "permissions": {
        "defaultMode": "bypassPermissions",
        "allow": [
            "Bash(*)",
            "Write",
            "Write(~/.claude/**)",
            "Edit",
            "Edit(~/.claude/**)",
            "Write(~/.claude/projects/**)",
            "Edit(~/.claude/projects/**)"
        ],
        "deny": [
            "Bash(git push --force*)",
            "Bash(rm -rf*)",
            "Bash(git reset --hard*)",
            "Bash(git clean -f*)",
            "Bash(sudo rm*)",
            "Bash(dd if=*)",
            "Bash(shutdown*)",
            "Bash(reboot*)"
        ],
        "additionalDirectories": ["~/.claude/projects"]
    }
}
with open(sys.argv[1], "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

result_allow="$(python3 -c "
import json
with open('$FAKE_HOME/.claude/settings.json') as f:
    print(json.dumps(json.load(f)['permissions']['allow']))
")"

if [[ "$result_allow" != *"Write(~/.claude/**)"* ]] && [[ "$result_allow" != *"Write(~/.claude/projects/**)"* ]]; then
  _pass "case (g): legacy path-scoped Write() rules removed"
else
  _fail "case (g): legacy path-scoped Write() rules still present: $result_allow"
fi

if [[ "$result_allow" == *'"Edit(~/.claude/**)"'* ]] \
   && [[ "$result_allow" == *'"Edit(~/.claude/projects/**)"'* ]] \
   && [[ "$result_allow" == *'"Write"'* ]] \
   && [[ "$result_allow" == *'"Edit"'* ]]; then
  _pass "case (g): recommended Edit path rules and bare Write/Edit retained"
else
  _fail "case (g): expected recommended allow rules missing: $result_allow"
fi

if grep -q "removed 2 legacy Write rules" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (g): install output reports legacy-rule removal"
else
  _fail "case (g): install output did not report legacy-rule removal"
fi

# Idempotency: running install a second time against the now-migrated state
# must NOT report removing legacy rules again (there are none left to
# remove) and must report the already-configured no-op path.
_run_install "$FAKE_HOME" || true

result_allow_second="$(python3 -c "
import json
with open('$FAKE_HOME/.claude/settings.json') as f:
    print(json.dumps(json.load(f)['permissions']['allow']))
")"

if [[ "$result_allow_second" != *"Write(~/.claude/**)"* ]] && [[ "$result_allow_second" != *"Write(~/.claude/projects/**)"* ]]; then
  _pass "case (g): idempotent second run keeps legacy rules absent"
else
  _fail "case (g): idempotent second run reintroduced legacy rules: $result_allow_second"
fi

if grep -q "already configured" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (g): idempotent second run reports already configured"
else
  _fail "case (g): idempotent second run did not report already configured"
fi

if grep -q "legacy Write rules" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _fail "case (g): idempotent second run should not mention legacy Write rules again"
else
  _pass "case (g): idempotent second run does not re-report legacy-rule removal"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (h): permissions migration - legacy path-scoped Write() allow rule is
#           RETAINED when the bare "Write" rule is ABSENT pre-migration.
#           This does not change effective permissions either way (the
#           scoped rule is inert; the bare "Write" rule IS added by the
#           recommended-merge regardless) - retaining it instead avoids the
#           installer making a surprising-looking edit to a config a user
#           may have deliberately narrowed. The install output reports
#           added rules, not a legacy-rule removal.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude"
python3 - "$FAKE_HOME/.claude/settings.json" <<'PYEOF'
import json, sys

settings = {
    "permissions": {
        "defaultMode": "bypassPermissions",
        "allow": [
            "Bash(*)",
            "Write(~/.claude/**)",
            "Edit",
            "Edit(~/.claude/**)",
            "Edit(~/.claude/projects/**)"
        ],
        "deny": [
            "Bash(git push --force*)",
            "Bash(rm -rf*)",
            "Bash(git reset --hard*)",
            "Bash(git clean -f*)",
            "Bash(sudo rm*)",
            "Bash(dd if=*)",
            "Bash(shutdown*)",
            "Bash(reboot*)"
        ],
        "additionalDirectories": ["~/.claude/projects"]
    }
}
with open(sys.argv[1], "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

result_allow_h="$(python3 -c "
import json
with open('$FAKE_HOME/.claude/settings.json') as f:
    print(json.dumps(json.load(f)['permissions']['allow']))
")"

if [[ "$result_allow_h" == *'"Write(~/.claude/**)"'* ]]; then
  _pass "case (h): legacy scoped Write() rule retained when bare Write was absent pre-migration"
else
  _fail "case (h): legacy scoped Write() rule was stripped despite bare Write being absent pre-migration: $result_allow_h"
fi

if [[ "$result_allow_h" == *'"Write"'* ]]; then
  _pass "case (h): bare Write rule added by recommended-merge"
else
  _fail "case (h): bare Write rule was not added: $result_allow_h"
fi

if grep -q "legacy Write rules" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _fail "case (h): install output should not report removing legacy Write rules"
else
  _pass "case (h): install output does not report legacy-rule removal"
fi

if grep -q "added" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (h): install output reports added rules"
else
  _fail "case (h): install output did not report added rules"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (i): DS-143 blocked-gate - a real file/dir at the skill symlink
#           destination forces SKILL_LINK_OK=false. The three @-import
#           lines must be RETAINED (never stripped without a working skill
#           link to fall back on), the skill-link keep-imports warning must
#           fire, and the registry-refresh restart notice must NOT fire
#           (the gate blocked the strip, so there is nothing to restart
#           into - the SKILL_LINK_OK warning covers that case instead).
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/skills/agentic-engineering"
touch "$FAKE_HOME/.claude/skills/agentic-engineering/placeholder.md"

_run_install "$FAKE_HOME" || true

if [[ -f "$FAKE_HOME/.claude/CLAUDE.md" ]] \
   && grep -Fq "@skills/agentic-engineering/METHODOLOGY.md" "$FAKE_HOME/.claude/CLAUDE.md" \
   && grep -Fq "@skills/agentic-engineering/rules/code-standards.md" "$FAKE_HOME/.claude/CLAUDE.md" \
   && grep -Fq "@skills/agentic-engineering/rules/conventions.md" "$FAKE_HOME/.claude/CLAUDE.md"; then
  _pass "case (i): blocked-gate CLAUDE.md retains all three @-import lines"
else
  _fail "case (i): blocked-gate CLAUDE.md is missing one or more @-import lines"
fi

if grep -Fq "WARNING: keeping the @-import lines in CLAUDE.md's managed block" "$FAKE_HOME/.install_out"; then
  _pass "case (i): blocked-gate install output warns that the @-imports were kept"
else
  _fail "case (i): blocked-gate install output missing the keep-imports warning"
fi

if grep -Fq "IMPORTANT: skill definitions changed" "$FAKE_HOME/.install_out"; then
  _fail "case (i): blocked-gate install output should NOT print the registry-refresh restart notice"
else
  _pass "case (i): blocked-gate install output correctly suppresses the restart notice"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (j): DS-143 migration - a pre-existing OLD-format managed block
#           (imports present) plus skill_auto_load:false plus a good skill
#           link. One run must end with the lean block AND
#           skill_auto_load:true (one-time forced migration, since imports
#           are being removed and the flag would otherwise leave the user
#           with neither always-on methodology nor a reliable trigger).
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude" "$FAKE_HOME/.agentic"
cat > "$FAKE_HOME/.claude/CLAUDE.md" <<'EOF'
<!-- BEGIN managed-by-agentic-engineering -->
## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.

@skills/agentic-engineering/METHODOLOGY.md
@skills/agentic-engineering/rules/code-standards.md
@skills/agentic-engineering/rules/conventions.md
<!-- END managed-by-agentic-engineering -->
EOF
python3 - "$FAKE_HOME/.claude/agentic-engineering.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"mode": "opt-out", "profile": "default", "skill_auto_load": False}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

_case_j_import_count="$(grep -c "@skills/agentic-engineering" "$FAKE_HOME/.claude/CLAUDE.md" 2>/dev/null)"
if [[ "$_case_j_import_count" -eq 0 ]]; then
  _pass "case (j): migration run leaves the lean block (no @-import lines)"
else
  _fail "case (j): migration run did not strip the @-import lines (count=$_case_j_import_count)"
fi

_j_auto_load="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    print(json.load(f).get('skill_auto_load'))
" "$FAKE_HOME/.claude/agentic-engineering.json" 2>/dev/null)"
if [[ "$_j_auto_load" == "True" ]]; then
  _pass "case (j): migration run force-sets skill_auto_load=true"
else
  _fail "case (j): expected skill_auto_load=True after migration, got '$_j_auto_load'"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (k): DS-143 negative migration control - an already-migrated block
#           (lean, no import string) plus a user-set skill_auto_load:false
#           must stay false. Proves the migration self-disarms once the old
#           marker is gone from disk.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude" "$FAKE_HOME/.agentic"
cat > "$FAKE_HOME/.claude/CLAUDE.md" <<'EOF'
<!-- BEGIN managed-by-agentic-engineering -->
## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.
<!-- END managed-by-agentic-engineering -->
EOF
python3 - "$FAKE_HOME/.claude/agentic-engineering.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"mode": "opt-out", "profile": "default", "skill_auto_load": False}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

_k_auto_load="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    print(json.load(f).get('skill_auto_load'))
" "$FAKE_HOME/.claude/agentic-engineering.json" 2>/dev/null)"
if [[ "$_k_auto_load" == "False" ]]; then
  _pass "case (k): already-migrated block with user-set skill_auto_load=false stays false (self-disarmed)"
else
  _fail "case (k): expected skill_auto_load to stay False, got '$_k_auto_load'"
fi

# MINOR-4 (DS-143 Skeptic loop 2): re-writing an already-lean block with
# identical content is a no-op rewrite (updated == existing) - the
# registry-refresh restart notice must NOT fire, unlike case (a)'s fresh
# create/strip where it must.
if grep -Fq "IMPORTANT: skill definitions changed" "$FAKE_HOME/.install_out"; then
  _fail "case (k): registry-refresh restart notice fired on an idempotent no-op rewrite"
else
  _pass "case (k): registry-refresh restart notice does NOT fire on an idempotent no-op rewrite"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (l): Skeptic loop 2 fix (MAJOR-2, DS-143) - the UserPromptSubmit
#           skill-auto-load-check command install.sh writes into
#           settings.json must carry the AE_ADAPTER=claude tag. Without it,
#           an ambient AE_ADAPTER env var (e.g. left over from a Gemini/Codex
#           run in the same shell) would silently turn Claude's skill-load
#           nudge into a no-op via the shared hook script's codex|gemini
#           exit-0 case. Mirrors the shape of the AE_ADAPTER=gemini assertion
#           in bin/tests/test_gemini_skill_auto_load_hook.sh.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude" "$FAKE_HOME/.agentic"

_run_install "$FAKE_HOME" || true

_l_skill_cmd="$(python3 -c "
import json
with open('$FAKE_HOME/.claude/settings.json') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        command = h.get('command', '')
        if 'skill-auto-load-check.sh' in command:
            print(command)
            raise SystemExit(0)
raise SystemExit('skill-auto-load-check command not found')
" 2>/dev/null)"

if [[ "$_l_skill_cmd" == *"AE_ADAPTER=claude"* ]]; then
  _pass "case (l): claude UserPromptSubmit skill-auto-load-check command carries the AE_ADAPTER=claude tag"
else
  _fail "case (l): claude UserPromptSubmit skill-auto-load-check command missing AE_ADAPTER=claude tag: $_l_skill_cmd"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (m): Skeptic loop 2 fix (MINOR-3, DS-143) - if
#           content/templates/claude-managed-content.md loses its manifest
#           comment terminator ("-->"), install.sh must fail loudly (not
#           silently ship the whole file, manifest comment included, into
#           the user's CLAUDE.md) AND must not touch CLAUDE.md at all.
#           Mutates the REAL template file in this checkout for the
#           duration of the case only; always restored via trap-adjacent
#           cleanup below, mirroring the canary-mutation pattern used
#           elsewhere in this repo for gate verification.
# ---------------------------------------------------------------------------

TEMPLATE_PATH="$REPO_DIR/content/templates/claude-managed-content.md"
TEMPLATE_BACKUP="$(mktemp)"
cp "$TEMPLATE_PATH" "$TEMPLATE_BACKUP"
printf 'no manifest comment here, no terminator either\n' > "$TEMPLATE_PATH"

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude" "$FAKE_HOME/.agentic"

_run_install "$FAKE_HOME" || true

cp "$TEMPLATE_BACKUP" "$TEMPLATE_PATH"
rm -f "$TEMPLATE_BACKUP"

if grep -Fq "could not find manifest comment terminator" "$FAKE_HOME/.install_out"; then
  _pass "case (m): install.sh fails loudly when the template's manifest terminator is missing"
else
  _fail "case (m): install.sh did not report the missing manifest terminator"
fi

if [[ ! -f "$FAKE_HOME/.claude/CLAUDE.md" ]]; then
  _pass "case (m): CLAUDE.md was NOT created when the template's manifest terminator is missing"
else
  _fail "case (m): CLAUDE.md was created despite the template's manifest terminator being missing"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
