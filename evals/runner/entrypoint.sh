#!/bin/bash
# entrypoint.sh
#
# Purpose: Container entrypoint for the Tier 3 swebench eval sandbox.
#
# Mount layout enforced by the caller (evals/runner/isolator.py Tier3Docker):
#
#   Fix phase:
#     /workspace/repo   rw   seeded fix-phase repo; agent writes here
#     /scoring/tests         NOT mounted - held-out tests are unreachable
#
#   Score phase (separate docker run invocation):
#     /workspace/repo   ro   fix-phase output (read by pytest)
#     /scoring/tests    ro   held-out test tree (run by pytest)
#
# Usage:
#   docker run ... ae-eval-swebench:latest <command> [args...]
#
#   If no command is provided, prints usage and exits 1.
#   Supported commands:
#     run-tests [pytest-args...]   run pytest against /scoring/tests
#     shell [cmd...]               run an arbitrary command (for debugging only)
#     <any other command>          exec directly
#
# Network: container is started with --network none; any network attempt
#          will fail with ENETUNREACH or ECONNREFUSED. This entrypoint does
#          not attempt network operations.
#
# Non-root: runs as evaluser (uid 1001) set in the Dockerfile.

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "entrypoint.sh: no command supplied" >&2
    echo "Usage: entrypoint.sh <command> [args...]" >&2
    echo "       entrypoint.sh run-tests [pytest-args...]" >&2
    echo "       entrypoint.sh shell [cmd...]" >&2
    exit 1
fi

COMMAND="$1"
shift

case "$COMMAND" in
    run-tests)
        # Install per-task requirements if present (fix-phase or scoring phase).
        if [[ -f /workspace/repo/requirements.txt ]]; then
            pip install --no-cache-dir --quiet -r /workspace/repo/requirements.txt
        fi
        # Run pytest against the held-out test tree.
        # /scoring/tests is only mounted during the score phase; during the fix
        # phase this path does not exist and pytest would exit with no-tests-found.
        exec pytest /scoring/tests "$@"
        ;;
    shell)
        # Escape hatch for debugging; not used in production eval runs.
        if [[ $# -eq 0 ]]; then
            exec /bin/bash
        else
            exec "$@"
        fi
        ;;
    *)
        # Pass through any other command directly (e.g. python, cat, ls).
        exec "$COMMAND" "$@"
        ;;
esac
