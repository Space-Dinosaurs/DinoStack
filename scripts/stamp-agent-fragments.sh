#!/usr/bin/env bash
# Purpose: Stamp shared wording fragments from content/fragments/
#          pre-submit-check-kernels.md into every `<!-- shared:<id> -->
#          ...<!-- /shared -->` span in content/agents/*.md, so a rule
#          stated in both engineer.md and skeptic.md has exactly one
#          hand-edited source of truth.
#
# Public API: bash scripts/stamp-agent-fragments.sh
#             No arguments. Writes to content/agents/*.md in place; prints
#             one line per file changed, or a "no changes" line when the
#             tree is already stamped. Idempotent - re-running on a stamped
#             tree is a no-op (byte-identical output, exit 0).
#
# Upstream deps: content/fragments/pre-submit-check-kernels.md (the canonical
#                `<!-- FRAGMENT:<id> -->...<!-- /FRAGMENT -->` source blocks);
#                content/agents/*.md (files scanned for `<!-- shared:<id> -->`
#                spans); scripts/lib/stamp_agent_fragments.py (the Python
#                implementation - see its own header for parsing detail);
#                python3, bash.
#
# Downstream consumers: scripts/build-all.sh (runs this FIRST, before the
#                        ADAPTERS loop, so every adapter build sees the
#                        stamped content); .github/workflows/
#                        agent-fragment-sync.yml (runs this then diffs
#                        content/agents/engineer.md and content/agents/
#                        skeptic.md against the working tree to catch a
#                        hand-edit that skipped the stamp).
#
# Failure modes: exits non-zero if a `<!-- shared:<id> -->` span in any
#                content/agents/*.md file references a fragment id with no
#                matching `<!-- FRAGMENT:<id> -->` definition in the kernels
#                file - fails loud rather than silently leaving the span
#                unstamped. Exits non-zero if the kernels file is missing.
#                Read-only against the kernels file; writes only the
#                content/agents/*.md files whose spans actually changed.
#
# Performance: O(total size of content/agents/*.md); single regex pass per file.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "$REPO_DIR/scripts/lib/stamp_agent_fragments.py"
