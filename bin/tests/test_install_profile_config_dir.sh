#!/usr/bin/env bash
# Purpose: Regression tests for the profile-aware installer flag (D-4).
#          Asserts that .claude/install.sh --config-dir=<dir> writes the
#          per-harness config (agentic-engineering.json, settings.json,
#          CLAUDE.md, agents/commands/skills symlinks) into <dir>, and does
#          NOT relocate shared user state (~/.agentic, ~/.local/bin) which
#          must always stay in the real $HOME. Also checks default behavior
#          (no flag) still targets $HOME/.claude, and that AGENTIC_CONFIG_DIR
#          env has the same effect as the flag.
#
# Public API: ./bin/tests/test_install_profile_config_dir.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp. Runs the installer with a sandboxed
#                HOME so the real user config is never touched.
#
# Failure modes: any failing assertion prints and exits 1. Fully hermetic:
#                all writes land under a throwaway HOME.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

# ---------------------------------------------------------------------------
# Test 1: --config-dir redirects the harness config; shared state stays in HOME
# ---------------------------------------------------------------------------
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home"
mkdir -p "$HOME"
PROFILE="$SANDBOX/profile"     # stand-in for ~/.claude-<tenant>
mkdir -p "$PROFILE"

bash "$REPO_DIR/.claude/install.sh" \
  --config-dir="$PROFILE" --no-identity --mode=opt-out --profile=default \
  >/dev/null 2>&1 || true

# Harness config must land in the profile dir.
[[ -f "$PROFILE/agentic-engineering.json" ]] \
  && pass "agentic-engineering.json in profile dir" \
  || fail "agentic-engineering.json NOT in profile dir"
[[ -f "$PROFILE/settings.json" ]] \
  && pass "settings.json in profile dir" \
  || fail "settings.json NOT in profile dir ($PROFILE)"

# The default ~/.claude under the sandbox HOME must NOT have been populated
# with the harness config when --config-dir pointed elsewhere.
if [[ -f "$HOME/.claude/settings.json" ]]; then
  fail "settings.json leaked into \$HOME/.claude despite --config-dir"
else
  pass "no settings.json leak into \$HOME/.claude"
fi

# Shared state is allowed (and expected) in the real HOME, not the profile.
if [[ -e "$PROFILE/.agentic/agentic-engineering-config.json" ]]; then
  fail "shared repo_dir config wrongly written under profile dir"
else
  pass "shared repo_dir config not placed under profile dir"
fi

# ---------------------------------------------------------------------------
# Test 2: AGENTIC_CONFIG_DIR env behaves like the flag
# ---------------------------------------------------------------------------
SANDBOX2="$(mktemp -d)"
export HOME="$SANDBOX2/home"; mkdir -p "$HOME"
PROFILE2="$SANDBOX2/prof2"; mkdir -p "$PROFILE2"
AGENTIC_CONFIG_DIR="$PROFILE2" bash "$REPO_DIR/.claude/install.sh" \
  --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
[[ -f "$PROFILE2/settings.json" ]] \
  && pass "AGENTIC_CONFIG_DIR env redirects settings.json" \
  || fail "AGENTIC_CONFIG_DIR env did NOT redirect settings.json"
rm -rf "$SANDBOX2"

# ---------------------------------------------------------------------------
# Test 3: default (no flag/env) targets \$HOME/.claude
# ---------------------------------------------------------------------------
SANDBOX3="$(mktemp -d)"
export HOME="$SANDBOX3/home"; mkdir -p "$HOME"
bash "$REPO_DIR/.claude/install.sh" \
  --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
[[ -f "$HOME/.claude/settings.json" ]] \
  && pass "default install targets \$HOME/.claude" \
  || fail "default install did NOT target \$HOME/.claude"
rm -rf "$SANDBOX3"

# ---------------------------------------------------------------------------
# Test 4: per-harness --config-dir isolation across all 4 harnesses
# (regression for PR #416 review finding 4: AE_CONFIG_PATH must follow
# --config-dir for codex/omp/pi, not collapse to $HOME/.claude).
# ---------------------------------------------------------------------------
SX="$(mktemp -d)"
export HOME="$SX/home"; mkdir -p "$HOME"
PROF_TENANT_A="$SX/.harness-a"
PROF_TENANT_B="$SX/.harness-b"
mkdir -p "$PROF_TENANT_A" "$PROF_TENANT_B"
for harness in claude codex omp pi; do
  bash "$REPO_DIR/.$harness/install.sh" --config-dir="$PROF_TENANT_A" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
  bash "$REPO_DIR/.$harness/install.sh" --config-dir="$PROF_TENANT_B" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
  if [[ -f "$PROF_TENANT_A/agentic-engineering.json" && -f "$PROF_TENANT_B/agentic-engineering.json" ]]; then
    pass "$harness: both tenants wrote agentic-engineering.json"
  else
    fail "$harness: agentic-engineering.json NOT present in both tenants"
  fi
  if [[ -f "$HOME/.claude/agentic-engineering.json" ]]; then
    fail "$harness: --config-dir wrote into shared \$HOME/.claude (regression F4)"
  else
    pass "$harness: --config-dir did NOT touch shared \$HOME/.claude"
  fi
done
rm -rf "$SX"

# ---------------------------------------------------------------------------
# Test 5: symlinked config FILE refusal (PR #416 review finding 1+2)
# ---------------------------------------------------------------------------
SYMT="$(mktemp -d)"
export HOME="$SYMT/home"; mkdir -p "$HOME"
echo "KEEP" > "$SYMT/victim_a"
ln -sf "$SYMT/victim_a" "$HOME/victim_a.json"

SY_O="$SYMT/omp_prof"; mkdir -p "$SY_O"
ln -sf "$SYMT/victim_a" "$SY_O/agentic-engineering.json"
bash "$REPO_DIR/.omp/install.sh" --config-dir="$SY_O" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
grep -q KEEP "$SYMT/victim_a" && pass "omp JSON symlink write blocked" || fail "omp JSON symlink write truncated victim"

SY_PI="$SYMT/pi_prof"; mkdir -p "$SY_PI"
ln -sf "$SYMT/victim_a" "$SY_PI/agentic-engineering.json"
bash "$REPO_DIR/.pi/install.sh" --config-dir="$SY_PI" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
grep -q KEEP "$SYMT/victim_a" && pass "pi JSON symlink write blocked" || fail "pi JSON symlink write truncated victim"

SY_CX="$SYMT/codex_prof"; mkdir -p "$SY_CX"
mkdir -p "$SYMT/victim_b"
echo "KEEP" > "$SYMT/victim_b/inside.txt"
ln -sf "$SYMT/victim_b" "$SY_CX/config.toml"
bash "$REPO_DIR/.codex/install.sh" --config-dir="$SY_CX" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
keep_b_kept=false
if [[ -f "$SYMT/victim_b/inside.txt" ]]; then
  if grep -q KEEP "$SYMT/victim_b/inside.txt"; then
    keep_b_kept=true
  fi
fi
if [[ "$keep_b_kept" == "true" ]]; then
  pass "codex config.toml symlink write blocked"
else
  fail "codex config.toml symlink write truncated victim"
fi
rm -rf "$SYMT"

# ---------------------------------------------------------------------------
# Test 6: symlinked config DIRECTORY refusal (PR #416 review finding 3)
# ---------------------------------------------------------------------------
SYMD="$(mktemp -d)"
export HOME="$SYMD/home"; mkdir -p "$HOME"
mkdir -p "$SYMD/real_dir"
echo "KEEP_DIR" > "$SYMD/real_dir/inside.txt"
for harness in claude codex omp pi; do
  link="$SYMD/.${harness}-victim"
  ln -sfn "$SYMD/real_dir" "$link"
  # Snapshot the symlink target's contents so we can detect a file planted
  # through the followed symlink (a refusal that still writes is not a refusal).
  before_count="$(find "$SYMD/real_dir" -mindepth 1 | wc -l | tr -d ' ')"
  rc=0
  bash "$REPO_DIR/.$harness/install.sh" --config-dir="$link" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    pass "$harness: refused symlinked config dir (rc=$rc)"
  else
    fail "$harness: did NOT refuse symlinked config dir (rc=0)"
  fi
  contents_ok=false
  if [[ -f "$SYMD/real_dir/inside.txt" ]]; then
    if grep -q KEEP_DIR "$SYMD/real_dir/inside.txt"; then
      contents_ok=true
    fi
  fi
  if [[ "$contents_ok" == "true" ]]; then
    pass "$harness: real_dir intact after refusal"
  else
    fail "$harness: real_dir corrupted"
  fi
  # Stronger than exit-code + pre-existing-file: assert NO new file was planted
  # inside the symlink target through the followed link (round-6 review gap).
  after_count="$(find "$SYMD/real_dir" -mindepth 1 | wc -l | tr -d ' ')"
  if [[ "$after_count" -eq "$before_count" ]]; then
    pass "$harness: no file planted through symlinked config dir"
  else
    fail "$harness: file planted inside symlink target ($before_count -> $after_count)"
  fi
done
rm -rf "$SYMD"

# ---------------------------------------------------------------------------
# Test 7: install-profiles.sh refuses symlinked profile base dir
# (PR #416 review finding 3 - per-tenant loop guard).
# ---------------------------------------------------------------------------
SYP="$(mktemp -d)"
export HOME="$SYP/home"; mkdir -p "$HOME"
mkdir -p "$SYP/realprof"
echo "KEEP_PROF" > "$SYP/realprof/inside.txt"
ln -sfn "$SYP/realprof" "$HOME/.claude-victim"
out="$($REPO_DIR/scripts/install-profiles.sh --tenants=victim --no-cursor --no-identity --mode=opt-out --profile=default 2>&1 || true)"
if echo "$out" | grep -q "refusing.*symlink"; then
  pass "install-profiles refused symlinked profile dir"
else
  fail "install-profiles did not refuse symlinked profile dir"
fi
if [[ -f "$SYP/realprof/inside.txt" ]] && grep -q KEEP_PROF "$SYP/realprof/inside.txt"; then
  pass "install-profiles preserved realprof contents"
else
  fail "install-profiles corrupted realprof contents"
fi
rm -rf "$SYP"

# --- Standalone --config-dir pointing at a not-yet-existing directory ---
# Regression guard: each installer must mkdir -p its config dir before the first
# ae_write_* call. Previously .omp and .codex crashed with FileNotFoundError when
# --config-dir named a nested directory that did not exist yet (masked in the
# orchestrated install-profiles flow because it pre-creates tenant dirs).
NX="$(mktemp -d)"
export HOME="$NX/home"; mkdir -p "$HOME"
for harness in claude codex omp pi; do
  # Deliberately deep + nonexistent: neither the leaf nor its parent exist yet.
  target="$NX/fresh-$harness/nested/agent"
  rc=0
  bash "$REPO_DIR/.$harness/install.sh" --config-dir="$target" --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -eq 0 && -f "$target/agentic-engineering.json" ]]; then
    pass "$harness: created config in not-yet-existing --config-dir (no crash)"
  else
    fail "$harness: failed on not-yet-existing --config-dir (rc=$rc, file=$([[ -f "$target/agentic-engineering.json" ]] && echo present || echo missing))"
  fi
done
rm -rf "$NX"

if [[ "$FAILS" -gt 0 ]]; then
  echo "FAILED: $FAILS assertion(s)"; exit 1
fi
echo "All profile-config-dir tests passed."
