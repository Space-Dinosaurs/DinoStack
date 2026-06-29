#!/usr/bin/env bash
# Purpose: Rebuild all 11 adapters locally in the same order used by CI
#          (adapter-sync.yml). Provides a single local entrypoint so
#          engineers don't have to invoke ten build.sh scripts by hand.
#
# Public API: bash scripts/build-all.sh
#             Exits 0 when all adapters build successfully.
#             Exits non-zero (first failure) when any adapter build fails.
#
# Upstream deps: .claude/build.sh, .cursor/build.sh, .codex/build.sh,
#                .gemini/build.sh, .kimi/build.sh, .opencode/build.sh,
#                .omp/build.sh, .pi/build.sh, .hermes/build.sh,
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
