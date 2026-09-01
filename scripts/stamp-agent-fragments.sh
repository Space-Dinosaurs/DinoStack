#!/usr/bin/env bash
# Purpose: Stamp shared wording fragments from content/fragments/
#          pre-submit-check-kernels.md into every `<!-- shared:<id> -->
#          ...<!-- /shared -->` span in content/agents/*.md, so wording that
#          must read identically in two or more agent definitions has
#          exactly one hand-edited source of truth. The mechanism is
#          file-set agnostic: it stamps whichever agent files carry a span,
#          so adding a consumer needs no change here - but it does need TWO
#          pins in bin/tests/test_stamp_agent_fragments.py, not one: a key
#          in EXPECTED_SPAN_IDS, and (for a fragment whose consumer set is
#          itself asserted, as learnings-retrieval's is) the matching entry
#          in LEARNINGS_RETRIEVAL_FILES, which is checked bidirectionally
#          and so fails on an unlisted addition as well as a removal.
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
#                        stamped content); hooks/pre-commit (runs this before
#                        the adapter-build loop when content/ is staged, so a
#                        local commit stamps before adapters build from it);
#                        .github/workflows/agent-fragment-sync.yml (runs
#                        this then diffs content/agents/*.md against the
#                        working tree to catch a hand-edit that skipped the
#                        stamp); bin/ds-learnings-retrieval-rate, which is a
#                        consumer of the `<!-- shared:<id> -->` MARKER
#                        SYNTAX rather than of this script - it derives its
#                        `wiring` column by looking for that literal opener
#                        in content/agents/*.md, so a change to the marker
#                        spelling silently degrades every role in that tool
#                        to `unwired-control`. Its SPAN_MARKER is pinned
#                        against SHARED_RE by
#                        bin/tests/test_ds_learnings_retrieval_rate.py::
#                        test_span_marker_matches_the_stamper; change the
#                        syntax and that test reddens.
#
# Failure modes: exits non-zero if a `<!-- shared:<id> -->` span in any
#                content/agents/*.md file references a fragment id with no
#                matching `<!-- FRAGMENT:<id> -->` definition in the kernels
#                file. Exits non-zero if a file's `<!-- shared: -->` opener
#                and `<!-- /shared -->` closer counts don't match, or if a
#                span's body contains a nested `<!-- shared: -->` opener -
#                both cases fail loud (per-file opener/closer counts printed
#                to stderr) rather than silently corrupting or skipping a
#                span, which is what the non-greedy span regex would
#                otherwise do on a missing closer. Exits non-zero if a
#                `<!-- FRAGMENT: -->` body in the kernels file itself
#                contains a marker-like string, which would otherwise make
#                stamping non-convergent (the target file grows a little on
#                every re-run, each exiting 0). Exits non-zero if the
#                kernels file is missing. Read-only against the kernels
#                file; writes only the content/agents/*.md files whose
#                spans actually changed.
#
# Performance: O(total size of content/agents/*.md); single regex pass per file.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "$REPO_DIR/scripts/lib/stamp_agent_fragments.py"
