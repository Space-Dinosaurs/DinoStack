#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Compensating control for dependency advisories. This repo shipped a
#          high-severity js-yaml CVE in two manifests, and two high-severity
#          brace-expansion alerts were auto-dismissed on 2026-08-03 and left
#          unfixed for five weeks. Nothing measured it: before this script,
#          `grep -rln 'npm audit' .github/workflows/ scripts/*.sh` returned
#          nothing. This closes that hole for both npm manifests in the repo -
#          package-lock.json at the root and scripts/package-lock.json.
#
#          THE FAILURE PREDICATE IS ACTIONABILITY, NOT SEVERITY. A gate that
#          fails on `npm audit`'s exit code, or on --audit-level=high, would
#          red-line main permanently today: scripts/ carries 4 high-severity
#          advisories rooted in extract-zip, whose newest published version is
#          2.0.1 and whose advisories cover `*` (verified against the registry
#          - there is no patched extract-zip at any version). A permanently
#          red gate is a gate that gets ignored or ripped out, so it would be
#          a compensating control in name only.
#
#          npm nonetheless reports fixAvailable as a TRUTHY OBJECT for all
#          four of those, because it can propose a top-level remediation:
#          downgrading @marp-team/marp-cli from >=2.5.0 to 2.4.0, flagged
#          isSemVerMajor: true. So "fixAvailable is truthy" is NOT the
#          actionability test either - it also red-lines main today. The test
#          that actually separates the two populations is whether the fix is
#          NON-BREAKING:
#
#            fixAvailable === false/absent  -> unfixable. Standing condition.
#            fixAvailable === true          -> ACTIONABLE. Plain `npm audit fix`.
#            {..., isSemVerMajor: true}     -> breaking-only. Standing condition.
#            {..., isSemVerMajor: false}    -> ACTIONABLE. Plain `npm audit fix`.
#            any other shape                -> ACTIONABLE (fail toward noticing).
#
#          A non-breaking fix is unambiguously something somebody can act on
#          today. A breaking-only fix is a judgement call with a product cost
#          (here: losing marp-cli features), which is an operator disposition,
#          not a CI red. KNOWN AND DELIBERATE LIMIT: an advisory whose only
#          remedy is a semver-major bump is REPORTED but does not fail. That
#          is the price of the gate staying green on a tree with a genuinely
#          unpatchable transitive dep; the breaking-only block is printed on
#          every run, pass or fail, so it stays in front of a reader instead
#          of being silently swallowed.
#
# Pillar 8 record (docs/overview/vision.md):
#   Catch - a high-severity js-yaml CVE sat in BOTH manifests, and two
#           high-severity brace-expansion alerts were auto-dismissed by a
#           Dependabot triage preset on 2026-08-03 and left unfixed for five
#           weeks. Nothing in the repo would have reported any of them: there
#           was no `npm audit` call in any workflow or script. This gate fails
#           on exactly that population - an advisory with a non-breaking fix
#           available - so all three would have been a red job the same day.
#   Retirement - this gate retires when Dependabot (or an equivalent) is
#           configured to open update PRs for BOTH manifests with no
#           auto-dismiss preset in front of it. At that point an actionable
#           advisory arrives as a reviewable PR on its own, and a second
#           mechanism asserting the same thing is duplicated machinery. It is
#           a compensating control for a disabled automation, NOT a permanent
#           enforcement floor, and should not be treated as one.
#   Cost against Pillars 1/5/6 - one advisory CI job, ~0.5 s per manifest,
#           no install step, no matrix. It is deliberately NOT a required
#           check: a red here is information for the operator, not a merge
#           block, which is what keeps its claim on operator attention
#           proportionate to it being a compensating control.
#
# Public API:
#   bash scripts/check-npm-audit.sh
#     Audits every manifest in MANIFEST_DIRS live against the registry.
#   bash scripts/check-npm-audit.sh --classify <file>
#     Classifies one pre-captured `npm audit --json` report. No network, no
#     npm. This is the deterministic entry point bin/tests/test_check_npm_
#     audit.sh drives with fixtures; live mode cannot be asserted on, since
#     its verdict changes whenever the advisory database does.
#
#   exit 0 - no actionable advisory (unfixable/breaking-only may be present,
#            and are listed).
#   exit 1 - at least one actionable advisory. The failing report names each.
#   exit 2 - THE AUDIT DID NOT RUN (npm missing, registry unreachable, or a
#            payload that is not an audit report). Never conflated with 0:
#            a no-op read must not be reported as "zero vulnerabilities".
#
# Network / CI asymmetry: live mode needs the registry. When it is
#            unreachable (or npm is absent), the behaviour SPLITS on ${CI},
#            following bin/tests/test_check_resident_budget.sh's established
#            pattern: under CI this is exit 2, a hard red - a job that goes
#            green having asserted nothing is the failure mode AGENTS.md
#            records three separate instances of. Off CI it prints a loud
#            SKIPPED block and exits 0, so an offline contributor running
#            scripts/check-local.sh on an unrelated change is not blocked by
#            a gate that structurally cannot run. --classify mode never
#            skips: no network is involved, so a bad payload is always a 2.
#
# Upstream deps: npm (live mode only; `npm audit` reads the lockfile and
#            needs NO node_modules present - verified on a tree with neither
#            node_modules/ nor scripts/node_modules/, so this gate needs no
#            install step and costs ~0.5 s per manifest). node, for parsing.
#            package-lock.json and scripts/package-lock.json.
#
# Downstream consumers: .github/workflows/codeql.yml npm-audit job;
#            scripts/check-local.sh; bin/tests/test_check_npm_audit.sh.
#
# Failure modes: a MISSING lockfile is exit 2, never a skip - a renamed or
#            deleted manifest must not silently shrink this gate's coverage
#            to nothing. A report lacking auditReportVersion or a
#            vulnerabilities object is treated as "did not run" (exit 2)
#            rather than as an empty result, because npm emits a bare
#            {message, error} object on registry failure and that object
#            would otherwise parse as zero vulnerabilities.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Every directory holding an npm manifest this repo is responsible for.
# Paths are relative to REPO_ROOT; "." is the root manifest.
MANIFEST_DIRS=("." "scripts")

usage() {
  echo "usage: bash scripts/check-npm-audit.sh [--classify <npm-audit-json-file>]"
  echo "  no args    - audit every manifest live against the registry"
  echo "  --classify - classify one pre-captured report; no network, no npm"
  echo "  exit 0 = no actionable advisory, 1 = actionable advisory found,"
  echo "  2 = the audit did not run (never conflated with 0)"
}

CLASSIFY_FILE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --classify)
      if [ "$#" -lt 2 ]; then
        echo "check-npm-audit: --classify needs a file argument" >&2
        exit 2
      fi
      CLASSIFY_FILE="$2"
      shift 2
      ;;
    *)
      echo "check-npm-audit: unknown argument '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# The classifier. Reads one npm audit --json report on stdin, prints a
# per-advisory breakdown, and exits 0 (no actionable), 1 (actionable), or
# 3 (payload is not an audit report). Kept in one place so live mode and
# --classify mode cannot drift apart.
# ---------------------------------------------------------------------------
classify_report() {
  local label="$1"
  node -e '
const label = process.argv[1];
let raw = "";
process.stdin.on("data", d => (raw += d));
process.stdin.on("end", () => {
  let report;
  try {
    report = JSON.parse(raw);
  } catch (e) {
    console.log(`  ERROR: ${label}: output is not JSON (${e.message})`);
    process.exit(3);
  }
  // npm emits a bare {message, error} object when the advisory endpoint is
  // unreachable. That parses fine and has no vulnerabilities key, so without
  // this guard a network failure would read as "0 vulnerabilities".
  if (
    report === null ||
    typeof report !== "object" ||
    report.auditReportVersion === undefined ||
    typeof report.vulnerabilities !== "object" ||
    report.vulnerabilities === null
  ) {
    const why = report && report.message ? report.message : "no auditReportVersion/vulnerabilities in payload";
    console.log(`  ERROR: ${label}: the audit did not run - ${why}`);
    process.exit(3);
  }

  const actionable = [];
  const breaking = [];
  const unfixable = [];

  for (const [name, v] of Object.entries(report.vulnerabilities)) {
    const fa = v.fixAvailable;
    const sev = v.severity || "unknown";
    let bucket;
    let note;
    if (fa === false || fa === undefined || fa === null) {
      bucket = unfixable;
      note = "no fix published";
    } else if (fa === true) {
      bucket = actionable;
      note = "non-breaking fix via `npm audit fix`";
    } else if (typeof fa === "object") {
      if (fa.isSemVerMajor === true) {
        bucket = breaking;
        note = `breaking-only fix: ${fa.name}@${fa.version}`;
      } else {
        bucket = actionable;
        note = `non-breaking fix: ${fa.name}@${fa.version}`;
      }
    } else {
      // Unrecognised shape. Fail toward noticing rather than toward green.
      bucket = actionable;
      note = `unrecognised fixAvailable shape (${JSON.stringify(fa)})`;
    }
    bucket.push(`    - ${name} (${sev}): ${note}`);
  }

  const show = (title, arr) => {
    if (arr.length === 0) return;
    console.log(`  ${title} (${arr.length}):`);
    arr.sort().forEach(l => console.log(l));
  };

  // Printed on every run, pass or fail: these are the standing conditions
  // this gate deliberately does not fail on, and burying them would make the
  // predicate invisible to whoever reads a green log.
  show("unfixable - no published fix, standing condition", unfixable);
  show("breaking-only - fix requires a semver-major change, operator call", breaking);
  show("ACTIONABLE - non-breaking fix available", actionable);

  if (actionable.length === 0) {
    console.log(`  OK: ${label}: no actionable advisory (${unfixable.length} unfixable, ${breaking.length} breaking-only).`);
    process.exit(0);
  }
  console.log(`  FAIL: ${label}: ${actionable.length} actionable advisory/advisories with a non-breaking fix available.`);
  process.exit(1);
});
' "$label"
}

# ---------------------------------------------------------------------------
# --classify mode. Deterministic, offline, and never skips.
# ---------------------------------------------------------------------------
if [ -n "$CLASSIFY_FILE" ]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "check-npm-audit: node is not on PATH - cannot classify" >&2
    exit 2
  fi
  if [ ! -f "$CLASSIFY_FILE" ]; then
    echo "check-npm-audit: --classify file not found: $CLASSIFY_FILE" >&2
    exit 2
  fi
  echo "==> classify: $CLASSIFY_FILE"
  classify_report "$CLASSIFY_FILE" < "$CLASSIFY_FILE"
  rc=$?
  case "$rc" in
    0) exit 0 ;;
    1) exit 1 ;;
    *) exit 2 ;;
  esac
fi

# ---------------------------------------------------------------------------
# Live mode.
# ---------------------------------------------------------------------------

# ${CI} splits the could-not-run path between a hard red and a loud skip.
# See "Network / CI asymmetry" in the header.
on_ci() { [ -n "${CI:-}" ]; }

cannot_run() {
  # cannot_run <reason>
  if on_ci; then
    echo "::error::check-npm-audit: the audit did not run under CI - $1" >&2
    echo "check-npm-audit: FAILED (the audit did not run): $1" >&2
    echo "A gate that goes green having asserted nothing is worse than a red one." >&2
    exit 2
  fi
  echo
  echo "check-npm-audit: SKIPPED - $1"
  echo "  This is a skip ONLY because CI is unset. The same condition is a hard"
  echo "  failure under CI, so the gate cannot go green in CI without auditing."
  exit 0
}

if ! command -v node >/dev/null 2>&1; then
  cannot_run "node is not on PATH"
fi
if ! command -v npm >/dev/null 2>&1; then
  cannot_run "npm is not on PATH"
fi

# A missing lockfile is never a skip: a renamed manifest must not silently
# reduce this gate's coverage to nothing.
for d in "${MANIFEST_DIRS[@]}"; do
  if [ ! -f "$REPO_ROOT/$d/package-lock.json" ]; then
    echo "check-npm-audit: expected lockfile not found: $d/package-lock.json" >&2
    echo "  MANIFEST_DIRS in this script is stale, or a manifest was removed." >&2
    exit 2
  fi
done

AUDIT_OUT="$(mktemp -t check-npm-audit.XXXXXX)"
trap 'rm -f "$AUDIT_OUT"' EXIT

overall=0
echo "check-npm-audit: auditing ${#MANIFEST_DIRS[@]} manifest(s) from lockfiles (no node_modules required)"

for d in "${MANIFEST_DIRS[@]}"; do
  label="$d/package-lock.json"
  echo
  echo "==> $label"
  # stderr is discarded deliberately: npm interleaves `npm warn`/`npm error`
  # lines with the JSON document, and stdout alone is pure JSON on both the
  # success and the endpoint-failure paths (verified on npm 11.4.2). The
  # failure REASON survives regardless - npm puts it in the JSON `message`
  # field, which the classifier prints.
  npm audit --json --prefix "$REPO_ROOT/$d" >"$AUDIT_OUT" 2>/dev/null
  # npm audit's own exit code is deliberately ignored: it is 1 whenever any
  # advisory exists at all, which is precisely the severity-shaped predicate
  # this gate exists to replace. The verdict comes from the classifier.
  classify_report "$label" <"$AUDIT_OUT"
  rc=$?
  case "$rc" in
    0) ;;
    1) overall=1 ;;
    *) cannot_run "npm audit produced no usable report for $label" ;;
  esac
done

echo
if [ "$overall" -ne 0 ]; then
  echo "::error::check-npm-audit: actionable dependency advisories found (a non-breaking fix is available)"
  echo "check-npm-audit: FAILED - at least one advisory has a non-breaking fix available."
  echo "  Fix with: npm audit fix --prefix <manifest dir>   (then commit the lockfile)"
  exit 1
fi
echo "check-npm-audit: OK - no advisory with a non-breaking fix available."
exit 0
