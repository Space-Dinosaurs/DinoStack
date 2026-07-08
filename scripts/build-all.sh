#!/usr/bin/env bash
# Purpose: Rebuild all 11 adapters locally in the same order used by CI
#          (adapter-sync.yml). Provides a single local entrypoint so
#          engineers don't have to invoke ten build.sh scripts by hand.
#
# Public API: bash scripts/build-all.sh
#             Exits 0 when all adapters build successfully.
#             Exits non-zero (first failure) when any adapter build fails.
#
# Upstream deps: scripts/build-commands.sh (regenerates implement-ticket-{full,medium}.md
#                from implement-ticket-body.md before adapter copies); .claude/build.sh,
#                .cursor/build.sh, .codex/build.sh, .gemini/build.sh, .kimi/build.sh,
#                .opencode/build.sh, .omp/build.sh, .pi/build.sh, .hermes/build.sh,
#                .openclaw/build.sh, .copilot/build.sh; bash; coreutils.
#
# Downstream consumers: local developer workflows; mirrors .github/workflows/adapter-sync.yml.
#
# Failure modes: exits 1 on the first adapter whose build.sh returns non-zero;
#                the failed adapter name is printed to stderr. Idempotent when
#                run on a clean tree (git diff --exit-code stays zero).
#
# Performance: sequential; total time ~equals the sum of per-adapter build times
#              (typically a few seconds each on a warm tree).

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Regenerate the implement-ticket-full.md and implement-ticket-medium.md command
# bodies from the annotated single-source implement-ticket-body.md before any
# adapter build runs. Every adapter's build.sh copies content/commands/*.md
# into the adapter's harness dir; this step ensures those copies are derived
# from the canonical source rather than from stale committed copies.
bash "$REPO_DIR/scripts/build-commands.sh"

ADAPTERS=(
  .claude
  .cursor
  .codex
  .gemini
  .kimi
  .opencode
  .omp
  .pi
  .hermes
  .openclaw
  .copilot
)

for adapter in "${ADAPTERS[@]}"; do
  build_script="$REPO_DIR/$adapter/build.sh"
  if [ ! -f "$build_script" ]; then
    echo "build-all.sh: missing build script: $build_script" >&2
    exit 1
  fi
  echo "--- building $adapter ---"
  if bash "$build_script"; then
    echo "--- $adapter: OK ---"
  else
    echo "build-all.sh: $adapter build failed" >&2
    exit 1
  fi
done

echo ""
echo "build-all.sh: all ${#ADAPTERS[@]} adapters built successfully."

# Dormant-stub budget gate (Unit 11): the rendered stub must stay <= 2KB.
if [ -x "$REPO_DIR/scripts/check-stub-budget.sh" ] || [ -f "$REPO_DIR/scripts/check-stub-budget.sh" ]; then
  bash "$REPO_DIR/scripts/check-stub-budget.sh"
fi
