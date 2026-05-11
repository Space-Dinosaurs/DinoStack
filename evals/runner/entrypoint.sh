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
#     /workspace/repo   ro   fix-phase output (read-only; agent cannot alter)
#     /scoring/tests    ro   held-out test tree (run by pytest)
#
# Timeout: run_fix_phase / run_score_phase pass EVAL_TIMEOUT_SECONDS via -e.
#          Commands are wrapped with `timeout $EVAL_TIMEOUT_SECONDS` so the
#          in-container process is killed at the real wall-clock limit. The
#          host-side subprocess.run timeout (timeout_seconds + 30) is a safety
#          guard only. This is the authoritative in-container time bound.
#
# Security notes:
#   - No pip install at run time. All dependencies (pytest + plugins) are
#     installed at image build time (Dockerfile.swebench). The agent-controlled
#     /workspace/repo/requirements.txt is NEVER pip-installed during scoring;
#     the agent cannot add dependencies that affect scoring.
#   - Score phase pytest invocation uses --noconftest --rootdir=/scoring/tests
#     --confcutdir=/scoring to prevent conftest.py or pytest.ini planted by the
#     agent in /workspace/repo from executing during scoring.
#   - The `shell` escape hatch is disabled by default; set EVAL_ALLOW_SHELL=1
#     to enable (for local debugging only; never set in production eval runs).
#
# Usage:
#   docker run ... <image-digest> <command> [args...]
#
#   Supported commands:
#     run-tests [pytest-args...]   run pytest against /scoring/tests (score phase)
#     <any other command>          exec directly (e.g. python, cat, ls)
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
    exit 1
fi

COMMAND="$1"
shift

# In-container timeout: EVAL_TIMEOUT_SECONDS is injected by run_fix_phase /
# run_score_phase via -e. If absent, default to 300 s.
TIMEOUT="${EVAL_TIMEOUT_SECONDS:-300}"

case "$COMMAND" in
    run-tests)
        # Score phase: run pytest against the held-out test tree.
        #
        # Security contract:
        #   --noconftest: do NOT load any conftest.py (prevents agent-planted
        #                 conftest.py in /workspace/repo from executing).
        #   --rootdir=/scoring/tests: pytest root is the held-out tree, not
        #                             /workspace/repo or any parent.
        #   --confcutdir=/scoring: conftest discovery stops at /scoring; nothing
        #                          above (including /workspace) is searched.
        #
        # Working directory is /scoring (set by docker run -w /scoring) so
        # pytest does not inherit /workspace/repo as its rootdir.
        #
        # No pip install: all required packages are in the image; the agent
        # cannot add dependencies that take effect during scoring.
        exec timeout "$TIMEOUT" pytest \
            --noconftest \
            --rootdir=/scoring/tests \
            --confcutdir=/scoring \
            /scoring/tests "$@"
        ;;
    shell)
        # Escape hatch for local debugging only.
        # Disabled by default to prevent production eval runs from spawning
        # arbitrary shells. Set EVAL_ALLOW_SHELL=1 to enable.
        if [[ "${EVAL_ALLOW_SHELL:-0}" != "1" ]]; then
            echo "entrypoint.sh: 'shell' command is disabled in production." >&2
            echo "Set EVAL_ALLOW_SHELL=1 to enable for local debugging." >&2
            exit 1
        fi
        if [[ $# -eq 0 ]]; then
            exec /bin/bash
        else
            exec "$@"
        fi
        ;;
    *)
        # Pass through any other command directly (e.g. python, cat, ls).
        exec timeout "$TIMEOUT" "$COMMAND" "$@"
        ;;
esac
