#!/usr/bin/env bash
# Purpose: Wrapper for scripts/check-slide-overflow.js - handles the npm
#          install staleness gate and conditionally rebuilds docs/slides
#          before measuring, then delegates to the Node measurement/compare
#          script.
#
# Public API: bash scripts/check-slide-overflow.sh [--deck <html path>]...
#               [--baseline <path>] [--repeat N]
#             All flags are forwarded verbatim to check-slide-overflow.js.
#             Exit code is exactly the underlying node script's exit code
#             (0 clean, 1 overflow/stale-baseline, 2 font load error,
#             3 measurement unstable).
#
# Upstream deps: scripts/package.json + scripts/package-lock.json (puppeteer-
#                core, @puppeteer/browsers); scripts/build-slides.sh (only
#                invoked when no --deck flag is present); scripts/check-
#                slide-overflow.js.
#
# Downstream consumers: .github/workflows/slides-sync.yml check-slide-
#                        overflow job; scripts/check-slide-overflow-live-
#                        selftest.sh (uses --deck mode, so this script never
#                        rebuilds docs/slides for fixture runs); contributors
#                        running the gate locally.
#
# Failure modes: propagates check-slide-overflow.js's exit code unchanged.
#                A missing/stale npm install is repaired automatically
#                (network required on a cold cache). When --deck is passed,
#                build-slides.sh is deliberately SKIPPED - fixture/single-
#                deck runs must never rebuild docs/slides. `npm ci` DELETES
#                node_modules before reinstalling, which would also delete
#                the Chrome-for-Testing cache living under node_modules/
#                .chrome-for-testing-cache - so the staleness check below
#                compares the installed vs. committed lockfiles' `packages`
#                maps (via node, ignoring the root "" entry that node_modules
#                /.package-lock.json always omits by design) rather than a
#                byte-for-byte `cmp`, which would ALWAYS report stale (that
#                root-entry omission is unconditional npm behavior) and
#                force a Chrome re-download on every single invocation.
#
# Performance: cold run needs network for `npm ci` and, on first live
#              measurement, a Chrome-for-Testing download. A "warm" run is
#              offline for the Chrome download ONLY on a machine that
#              persists node_modules/.chrome-for-testing-cache across runs -
#              in CI, with no actions/cache step configured for that
#              directory, every job run downloads Chrome fresh; locally, an
#              intervening `npm ci` (including this script's own staleness
#              gate, when build-slides.sh's separate gate fires) deletes it
#              too, since npm ci always wipes node_modules first. The
#              Google Fonts the decks @import are fetched on every run
#              regardless.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_DIR/scripts"

# Staleness-gated install. See Failure modes above for why this compares
# normalized `packages` maps instead of a byte-for-byte `cmp` of the two
# lockfiles.
lockfile_in_sync() {
  node -e '
    const fs = require("fs");
    function norm(p) {
      const data = JSON.parse(fs.readFileSync(p, "utf8"));
      const packages = { ...(data.packages || {}) };
      delete packages[""];
      return JSON.stringify(packages);
    }
    process.exit(norm(process.argv[1]) === norm(process.argv[2]) ? 0 : 1);
  ' "$1" "$2"
}

if [ ! -d "$SCRIPTS_DIR/node_modules/puppeteer-core" ] \
  || [ ! -f "$SCRIPTS_DIR/node_modules/.package-lock.json" ] \
  || ! lockfile_in_sync "$SCRIPTS_DIR/node_modules/.package-lock.json" "$SCRIPTS_DIR/package-lock.json"; then
  npm ci --prefix "$SCRIPTS_DIR" --no-audit --no-fund
fi

has_deck_flag=0
for arg in "$@"; do
  if [ "$arg" = "--deck" ]; then
    has_deck_flag=1
    break
  fi
done

if [ "$has_deck_flag" -eq 0 ]; then
  bash "$SCRIPTS_DIR/build-slides.sh"
fi

exec node "$SCRIPTS_DIR/check-slide-overflow.js" "$@"
