#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Compensating control for dependency advisories. Nothing in this repo
#          measured them: before this script, no workflow and no script called
#          `npm audit` at all - `git grep -l 'npm audit' <any pre-gate commit>
#          -- .github/workflows/ scripts/` returns nothing - while a
#          high-severity advisory with a non-breaking fix sat unfixed in BOTH
#          manifests. This closes that hole for both npm manifests in the repo
#          - package-lock.json at the root and scripts/package-lock.json.
#
#          Configuring Dependabot version updates does not close it. Security
#          alerts are governed independently of version-update scope, and a
#          dev-scope alert can be auto-triaged away without anyone acting on
#          it, so a manifest can be fully covered by .github/dependabot.yml
#          and still carry an unaddressed actionable advisory.
#
#          DELIBERATELY NOT NAMED HERE: the specific alert-history incident
#          that prompted this gate. Alert state is mutable - an alert that is
#          later fixed stops reporting the history it had when someone read
#          it - so a rationale resting on one is unverifiable by whoever
#          reads it next, however accurately it was measured when written.
#          A claim that cannot be sourced is deleted rather than softened.
#          The reasons above are checkable today and are sufficient alone.
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
#   Catch - a high-severity advisory with a non-breaking fix available sat
#           unfixed in BOTH manifests, and nothing in the repo would have
#           reported it: there was no `npm audit` call in any workflow or
#           script (verifiable against any pre-gate commit). This gate fails on
#           exactly that population - an advisory with a non-breaking fix
#           available - so it would have been a red job the same day.
#   Retirement - keyed to an OBSERVABLE, not to a config file. "Dependabot is
#           configured for both manifests" is NOT the condition and never was:
#           .github/dependabot.yml already configures npm updates for both
#           directories, and security alerts are governed separately from
#           version-update scope, so that file says nothing about whether an
#           advisory gets acted on. The testable condition: the next time this
#           gate goes red, check whether an update PR proposing that same fix
#           was already open BEFORE the gate fired. If it was, the automation
#           is reaching these advisories on its own, this gate is duplicated
#           machinery, and it should be deleted. If it was not, the mechanism
#           this compensates for is still not working. It is a compensating
#           control, NOT a permanent enforcement floor, and should not be
#           treated as one.
#
#           SCOPE LIMIT ON THAT TEST, and it is not a small one: Dependabot
#           `ignore` rules suppress security updates as well as version
#           updates, so an advisory whose remediating package is ignored can
#           never produce the update PR the test looks for. .github/
#           dependabot.yml ignores @marp-team/* on /scripts, and every
#           advisory scripts/ carries today remediates through
#           @marp-team/marp-cli. For that population the test is guaranteed
#           to answer "no update PR was open" - because of a deliberate
#           config choice, NOT because the automation failed to reach the
#           advisory. Answering the retirement question on that evidence
#           would keep this gate alive on a result that was never capable of
#           coming out any other way. So: run the test only on an advisory
#           whose remediating package is NOT covered by an `ignore` rule. If
#           the gate has only ever gone red on ignored packages, the test has
#           not been run yet and the retirement question stays open.
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
#   PRECEDENCE when manifests disagree: an actionable advisory DETECTED in any
#            manifest outranks another manifest's inability to run, so such a
#            run is exit 1 (on CI and off it), never a skip. A real finding is
#            never discarded in favour of "this gate asserted nothing". The
#            unaudited manifest is named in the same output, so the incomplete
#            coverage stays visible rather than being traded away.
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
# Failure modes: every way this gate can end up auditing nothing is exit 2,
#            never a skip and never a clean pass. There are four, and they
#            are separate checks because each is reached differently:
#              - a MISSING lockfile (a renamed or deleted manifest).
#              - an EMPTY MANIFEST_DIRS (the list itself edited to nothing).
#              - a PRESENT but DEGENERATE lockfile, which is the one that
#                looks clean: a package-lock.json containing `{}` returns a
#                well-formed report with auditReportVersion 2, an empty
#                vulnerabilities map and metadata.dependencies.total 0
#                (measured on npm 11.19.0). Zero resolved dependencies is a
#                did-not-run; only a report showing the manifest resolved at
#                least one dependency can claim a clean tree.
#              - a report lacking auditReportVersion or a vulnerabilities
#                object, because npm emits a bare {message, error} object on
#                registry failure and that object would otherwise parse as
#                zero vulnerabilities.
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
# Mode is tracked separately from the filename. Deriving "are we classifying?"
# from `[ -n "$CLASSIFY_FILE" ]` alone made `--classify ""` fall through to a
# LIVE NETWORK AUDIT: the caller asked for a deterministic offline
# classification and silently got the opposite of what it asked for.
CLASSIFY_MODE=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --classify)
      if [ "$#" -lt 2 ]; then
        echo "check-npm-audit: --classify needs a file argument" >&2
        exit 2
      fi
      CLASSIFY_FILE="$2"
      CLASSIFY_MODE=1
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
# per-advisory breakdown, and exits 0 (no actionable), 4 (actionable), or
# 3 (payload is not an audit report). Kept in one place so live mode and
# --classify mode cannot drift apart.
#
# ACTIONABLE IS 4, NOT 1, AND THAT IS LOAD-BEARING. node exits 1 on an
# uncaught exception, so while actionable was 1 a classifier CRASH was
# indistinguishable from a real finding: callers reported it as "actionable
# advisories found", failing loud with the wrong diagnosis and sending the
# reader to hunt an advisory that does not exist. With 4 reserved for the
# verdict, every unexpected code - 1 included - falls through to the
# did-not-run path, which is what a crash actually is. Callers map these onto
# the script's public 0/1/2 contract; 4 never escapes this file.
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

  // A PRESENT but degenerate lockfile audits as a flawless clean report. A
  // package-lock.json containing `{}` yields auditReportVersion 2, an empty
  // vulnerabilities map, and metadata.dependencies.total 0 (measured on npm
  // 11.19.0), which every guard above accepts and which then prints "OK: no
  // actionable advisory". That shrinks the coverage of this gate to nothing
  // - the identical failure the missing-lockfile check exists to prevent,
  // reached by a file that exists rather than one that does not. Zero
  // resolved dependencies is therefore a did-not-run, never a clean tree.
  // For reference, the two manifests in this repo resolve 99 and 170.
  //
  // NO APOSTROPHES ANYWHERE IN THIS node -e BODY: it is a single-quoted
  // shell string, so one apostrophe terminates it and the rest of the
  // classifier is parsed by bash as filenames.
  const deps = report.metadata && report.metadata.dependencies;
  const depTotal = deps && typeof deps.total === "number" ? deps.total : null;
  if (depTotal === null) {
    console.log(`  ERROR: ${label}: the audit did not run - no metadata.dependencies.total in payload, so the report cannot show that the manifest resolved anything.`);
    process.exit(3);
  }
  if (depTotal < 1) {
    console.log(`  ERROR: ${label}: the audit did not run - the manifest resolved 0 dependencies (an empty or degenerate lockfile), so a clean result asserts nothing.`);
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
  process.exit(4);
});
' "$label"
}

# ---------------------------------------------------------------------------
# --classify mode. Deterministic, offline, and never skips.
# ---------------------------------------------------------------------------
if [ "$CLASSIFY_MODE" -eq 1 ]; then
  # An empty path is a usage error, never a silent fall-through to live mode.
  if [ -z "$CLASSIFY_FILE" ]; then
    echo "check-npm-audit: --classify needs a non-empty file argument" >&2
    exit 2
  fi
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
    4) exit 1 ;;
    # 3 is the classifier's did-not-run verdict. Any OTHER code is a
    # classifier crash (node exits 1 on an uncaught exception), which is also
    # a did-not-run, not a finding.
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

# An EMPTY MANIFEST_DIRS is a hard exit 2 and never a skip, for the same
# reason a missing lockfile is: both loops below would no-op, overall would
# stay 0, and the gate would exit 0 under CI having audited nothing - the one
# shape this gate exists to prevent. Not left to the grep pin in
# bin/tests/test_check_npm_audit.sh: a pin asserts the list's CONTENT is
# unchanged, not that the gate refuses to run on an empty one. Checked before
# node/npm so the diagnosis is the real defect rather than a missing tool, and
# written as a count (safe on an empty array under bash 3.2, unlike the
# "${MANIFEST_DIRS[@]}" expansions below, which are an unbound-variable error
# there - measured on 3.2.57).
if [ "${#MANIFEST_DIRS[@]}" -eq 0 ]; then
  echo "check-npm-audit: MANIFEST_DIRS is empty - this gate would audit nothing." >&2
  echo "  A gate that goes green having asserted nothing is worse than a red one." >&2
  exit 2
fi

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
# Set (not exited on) when a manifest could not be audited, so the loop can
# finish and the two outcomes can be weighed together after it. See the
# precedence block below.
could_not_run=""
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
    4) overall=1 ;;
    # 3 is the classifier's did-not-run verdict; any other code is a
    # classifier crash, which is also a did-not-run rather than a finding.
    # Neither exits here. Exiting mid-loop DISCARDED an actionable advisory
    # an earlier manifest had already found - off CI that printed a FAIL line
    # naming the advisory and then exited 0 SKIPPED.
    # APPENDED, not assigned: when BOTH manifests fail, an assignment left the
    # one-line summary below naming only the last one, silently understating
    # how much coverage was lost. The per-manifest ERROR lines above always
    # print either way, so nothing was unlogged - but the summary is what a
    # reader acts on, and it is consumed twice below.
    *)
      if [ -n "$could_not_run" ]; then
        could_not_run="$could_not_run; npm audit produced no usable report for $label"
      else
        could_not_run="npm audit produced no usable report for $label"
      fi
      ;;
  esac
done

echo
# PRECEDENCE, decided deliberately: a DETECTED actionable advisory outranks a
# later manifest's inability to run. Exit 1 is a true, specific statement
# about this tree - a named advisory with a named non-breaking fix, already
# printed above. The did-not-run path says only "this gate asserted nothing",
# which carries strictly less information and, off CI, is a skip. Letting the
# skip win discards a real finding and prints SKIPPED directly beneath a FAIL
# line naming the advisory, which is the worst available outcome. The reverse
# costs nothing: the unaudited manifest is still named below, so incomplete
# coverage stays visible, and under CI both paths are red regardless.
if [ "$overall" -ne 0 ]; then
  echo "::error::check-npm-audit: actionable dependency advisories found (a non-breaking fix is available)"
  echo "check-npm-audit: FAILED - at least one advisory has a non-breaking fix available."
  if [ -n "$could_not_run" ]; then
    echo "  AND COVERAGE WAS INCOMPLETE: $could_not_run"
    echo "  Fixing what is listed above does not fully clear this run - a manifest was never audited."
  fi
  echo "  Fix with: npm audit fix --prefix <manifest dir>   (then commit the lockfile)"
  exit 1
fi
# No actionable advisory was found, but a manifest never ran, so this gate
# cannot claim a clean tree: hard red under CI, loud skip off it.
if [ -n "$could_not_run" ]; then
  cannot_run "$could_not_run"
fi
echo "check-npm-audit: OK - no advisory with a non-breaking fix available."
exit 0
