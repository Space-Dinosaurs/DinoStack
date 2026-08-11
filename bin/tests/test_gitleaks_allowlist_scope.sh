#!/usr/bin/env bash
# Purpose: Regression guard for .gitleaks.toml's allowlist scope. .gitleaks.toml
#          configures the `scan` CI job (a required status check on `main`) and
#          carries two [[allowlists]] blocks: one exempting eval fixture
#          corpora (evals/fixtures/** and evals/skill-comparison/tasks/**),
#          and one narrowly exempting .codex/skill-compatibility.yml's
#          source_token/generated_token fields from the generic-api-key rule
#          only. Nothing previously pinned this file - a future edit could
#          silently broaden the allowlist (e.g. to a whole-file path
#          exemption, or dropping targetRules so it exempts every rule) and
#          no gate would notice, leaving a permanent hole in a required
#          security check.
#
#          This guard runs the real gitleaks binary (never parses the TOML)
#          against small scratch git repos, each seeded with the REAL,
#          unmodified .gitleaks.toml from this repo plus one planted probe
#          secret, and asserts the probe is caught or suppressed as
#          expected. Mirrors the CI job's scan mode (`gitleaks git .`,
#          history scan of committed blobs - see .github/workflows/
#          gitleaks.yml) rather than a worktree/no-git scan, since a
#          worktree-mode probe would not exercise the same code path the
#          required check actually runs.
#
# Public API: ./bin/tests/test_gitleaks_allowlist_scope.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp, python3 (fixture file authoring), and the
#                `gitleaks` CLI on PATH. If gitleaks is missing: hard FAIL
#                under CI=true (this is a security regression guard - a
#                silently skipped assertion here is indistinguishable from a
#                passing one, and the whole point is not to have that hole
#                again); locally, SKIP with a message so contributors
#                without gitleaks installed can still run the rest of the
#                suite.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh). bin-tests.yml
#                        carries a matching "install gitleaks CLI" step so
#                        this guard is never the reason CI lacks the binary.
#
# Failure modes: .gitleaks.toml missing -> immediate FAIL. gitleaks missing
#                under CI -> immediate FAIL. Any scenario's observed
#                caught/suppressed outcome does not match expected -> FAIL
#                naming the scenario, the planted secret's path, and the
#                gitleaks exit code / report content observed.
#
# Test hygiene: never mutates .gitleaks.toml or any tracked file. Every
#               probe lives in its own throwaway `git init` scratch repo
#               under a mktemp -d directory, removed on exit via trap. Does
#               not touch network (beyond whatever the pre-installed
#               gitleaks binary itself needs, which is none for `git .`
#               scans of a local repo). Runs correctly from any cwd.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
REAL_TOML="$REPO_DIR/.gitleaks.toml"

if [[ ! -f "$REAL_TOML" ]]; then
  echo "FAIL: $REAL_TOML not found" >&2
  exit 1
fi

if ! command -v gitleaks >/dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then
    echo "FAIL: gitleaks CLI not found on PATH in CI - this guard cannot be skipped here (see .github/workflows/bin-tests.yml's install step)" >&2
    exit 1
  else
    echo "SKIP: gitleaks CLI not found on PATH - skipping .gitleaks.toml allowlist-scope guard (install gitleaks to run this locally)"
    exit 0
  fi
fi

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

# Build a one-commit scratch git repo at $1 seeded with the real
# .gitleaks.toml (copied verbatim, never mutated). Caller populates files
# under $1 before calling this, or passes a populate callback name in $2.
_init_scratch_repo() {
  local dir="$1"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" config user.email "probe@example.invalid"
  git -C "$dir" config user.name "gitleaks-probe"
  cp "$REAL_TOML" "$dir/.gitleaks.toml"
}

_commit_scratch_repo() {
  local dir="$1"
  git -C "$dir" add -A
  git -C "$dir" commit -q -m "probe" >/dev/null
}

# Runs `gitleaks git .` (matching the CI job's scan mode) inside $1.
# Writes the JSON report to $1/leaks.json and returns gitleaks' exit code
# via the global GITLEAKS_RC. Never redirects stderr to /dev/null - a
# tooling failure here must surface, not silently read as "no leaks".
_run_scan() {
  local dir="$1"
  local out
  out="$(cd "$dir" && gitleaks git . --report-format json --report-path leaks.json 2>&1)"
  GITLEAKS_RC=$?
  GITLEAKS_OUTPUT="$out"
}

# Asserts a specific path appears as a finding's "File" field in
# $1/leaks.json. Reads the JSON with python3 rather than grep, since the
# report is a real JSON array and grep on it is fragile.
_leaks_contain_path() {
  local dir="$1" target_path="$2"
  python3 - "$dir/leaks.json" "$target_path" <<'PYEOF'
import json
import sys

report_path, target = sys.argv[1], sys.argv[2]
try:
    with open(report_path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = []
sys.exit(0 if any(entry.get("File") == target for entry in data) else 1)
PYEOF
}

# NOTE on fixture shape: the real .codex/skill-compatibility.yml is JSON
# despite its .yml extension (it is machine-generated by
# scripts/codex-skills.py as a JSON document) - keys are double-quoted,
# e.g. "source_token": "value". The allowlist's own regex
# ('''(?:source|generated)_token":\s*"[^"]*"''') is anchored on that exact
# quoted-key shape (it matches the literal text `_token":` - a closing
# quote immediately before the colon). Every fixture below uses that same
# quoted-key JSON shape, not bare YAML `key: "value"`, so these probes
# exercise the allowlist's actual matching behavior rather than a shape it
# was never written to match.

# ---------------------------------------------------------------------------
# Assertion 0 (baseline, not in the task's required 4 but necessary for the
# other assertions to be meaningful): a source_token/generated_token pair in
# the allowlisted file, in the real quoted-key shape, IS suppressed. Without
# this passing first, "still caught" assertions below would prove nothing -
# they'd pass even if the allowlist never matched anything at all.
# ---------------------------------------------------------------------------
A0_DIR="$TMP_ROOT/a0-baseline-suppressed"
_init_scratch_repo "$A0_DIR"
mkdir -p "$A0_DIR/.codex"
cat > "$A0_DIR/.codex/skill-compatibility.yml" <<'EOF'
{
  "source_token": "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd",
  "generated_token": "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abce"
}
EOF
_commit_scratch_repo "$A0_DIR"
_run_scan "$A0_DIR"

if ! _leaks_contain_path "$A0_DIR" ".codex/skill-compatibility.yml"; then
  _pass "assertion 0 (baseline): source_token/generated_token in the allowlisted file, quoted-key shape, is suppressed"
else
  _fail "assertion 0 (baseline): source_token/generated_token in the allowlisted file was caught (expected suppressed - allowlist may not be matching at all): $GITLEAKS_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Assertion 1: a secret under a key that is NOT source_token/generated_token
# in the allowlisted file (.codex/skill-compatibility.yml) is still CAUGHT.
# Pins the targetRules/regexTarget/regexes leg - a broadened allowlist that
# dropped the exact key-name regex (or widened it to match any key) would
# let this probe through.
# ---------------------------------------------------------------------------
A1_DIR="$TMP_ROOT/a1-non-exempt-key"
_init_scratch_repo "$A1_DIR"
mkdir -p "$A1_DIR/.codex"
cat > "$A1_DIR/.codex/skill-compatibility.yml" <<'EOF'
{
  "other_token": "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
}
EOF
_commit_scratch_repo "$A1_DIR"
_run_scan "$A1_DIR"

if [[ $GITLEAKS_RC -eq 1 ]] && _leaks_contain_path "$A1_DIR" ".codex/skill-compatibility.yml"; then
  _pass "assertion 1: non-exempt key (other_token) in the allowlisted file is caught"
else
  _fail "assertion 1: non-exempt key (other_token) in the allowlisted file was NOT caught (rc=$GITLEAKS_RC): $GITLEAKS_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Assertion 2: a source_token-keyed secret in a DIFFERENT .codex/ file is
# still CAUGHT. Pins the path leg - a broadened allowlist path glob (e.g.
# '.codex/.*' instead of the exact filename anchor) would let this through.
# ---------------------------------------------------------------------------
A2_DIR="$TMP_ROOT/a2-wrong-file"
_init_scratch_repo "$A2_DIR"
mkdir -p "$A2_DIR/.codex"
cat > "$A2_DIR/.codex/other-inventory.yml" <<'EOF'
{
  "source_token": "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"
}
EOF
_commit_scratch_repo "$A2_DIR"
_run_scan "$A2_DIR"

if [[ $GITLEAKS_RC -eq 1 ]] && _leaks_contain_path "$A2_DIR" ".codex/other-inventory.yml"; then
  _pass "assertion 2: source_token-keyed secret in a different .codex/ file is caught"
else
  _fail "assertion 2: source_token-keyed secret in a different .codex/ file was NOT caught (rc=$GITLEAKS_RC): $GITLEAKS_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Assertion 3: a provider-specific secret (a github-pat-shaped ghp_ token)
# planted as the VALUE of source_token in the allowlisted file is still
# CAUGHT. Measured mechanism (mutation-verified, see the engineer's return
# summary): github-pat's own "match" text is just the bare token
# (e.g. "ghp_..."), never the "source_token": prefix, so the allowlist's
# regexes leg (anchored on that key-name text) structurally never matches a
# github-pat finding regardless of targetRules alone - dropping targetRules
# by itself does NOT let this probe through. What DOES let it through is
# widening regexes to match unconditionally (e.g. '''.*''') together with
# dropping targetRules - i.e. this assertion pins the narrow-regex leg,
# with targetRules as defense in depth rather than the sole guard.
# ---------------------------------------------------------------------------
A3_DIR="$TMP_ROOT/a3-wrong-rule"
_init_scratch_repo "$A3_DIR"
mkdir -p "$A3_DIR/.codex"
cat > "$A3_DIR/.codex/skill-compatibility.yml" <<'EOF'
{
  "source_token": "ghp_QaPP1MvT5sh146bScdlQyJWQ2XjSx0kfqala"
}
EOF
_commit_scratch_repo "$A3_DIR"
_run_scan "$A3_DIR"

if [[ $GITLEAKS_RC -eq 1 ]] && _leaks_contain_path "$A3_DIR" ".codex/skill-compatibility.yml"; then
  _pass "assertion 3: github-pat-shaped secret as source_token's value in the allowlisted file is caught"
else
  _fail "assertion 3: github-pat-shaped secret as source_token's value in the allowlisted file was NOT caught (rc=$GITLEAKS_RC): $GITLEAKS_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Assertion 4: the eval-fixture boundary is intact. evals/ is git-untracked
# in the real repo (decision #203) and therefore invisible inside an
# isolation worktree, so this probe never touches the real evals/ directory
# on disk - it constructs the paths itself inside the scratch repo.
# ---------------------------------------------------------------------------
A4_DIR="$TMP_ROOT/a4-eval-boundary"
_init_scratch_repo "$A4_DIR"
mkdir -p "$A4_DIR/evals/fixtures" "$A4_DIR/evals/skill-comparison/tasks" "$A4_DIR/evals/skill-comparison/harness"
SECRET_LINE='other_token: "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890abcd"'
echo "$SECRET_LINE" > "$A4_DIR/evals/fixtures/probe.yml"
echo "$SECRET_LINE" > "$A4_DIR/evals/skill-comparison/tasks/probe.yml"
echo "$SECRET_LINE" > "$A4_DIR/evals/skill-comparison/harness/probe.yml"
_commit_scratch_repo "$A4_DIR"
_run_scan "$A4_DIR"

if ! _leaks_contain_path "$A4_DIR" "evals/fixtures/probe.yml"; then
  _pass "assertion 4a: secret under evals/fixtures/ is suppressed"
else
  _fail "assertion 4a: secret under evals/fixtures/ was caught (expected suppressed): $GITLEAKS_OUTPUT"
fi

if ! _leaks_contain_path "$A4_DIR" "evals/skill-comparison/tasks/probe.yml"; then
  _pass "assertion 4b: secret under evals/skill-comparison/tasks/ is suppressed"
else
  _fail "assertion 4b: secret under evals/skill-comparison/tasks/ was caught (expected suppressed): $GITLEAKS_OUTPUT"
fi

if _leaks_contain_path "$A4_DIR" "evals/skill-comparison/harness/probe.yml"; then
  _pass "assertion 4c: secret under evals/skill-comparison/ outside tasks/ is caught"
else
  _fail "assertion 4c: secret under evals/skill-comparison/ outside tasks/ was NOT caught (expected caught, rc=$GITLEAKS_RC): $GITLEAKS_OUTPUT"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
