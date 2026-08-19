#!/usr/bin/env bash
# Purpose: Single source for the "iterate content/rules/*.md excluding
#          module-manifest.md" list shared by .kimi/build.sh (SKILL.md
#          embed) and .kimi/install.sh (AGENTS.md degrade-path fallback
#          embed) - previously duplicated verbatim in both scripts (m6,
#          DS-185 round 2). Both sites format the same underlying file
#          list differently (build.sh emits a "### rules/<name>" heading
#          per file for the skill body; install.sh emits a plain "---"
#          separator for the degrade-path fallback), so this file exposes
#          only the file-listing step, not the formatting.
#
# Public API: source this file, then call `kimi_rules_files "$CONTENT_DIR"`
#             - prints one absolute path per line, sorted, excluding
#             module-manifest.md. Exits with no output (not an error) when
#             content/rules/ contains only module-manifest.md or is empty.
#
# Upstream deps: content/rules/*.md, bash 3.2+ (no bash 4+ constructs).
#
# Downstream consumers: .kimi/build.sh (SKILL.md embed loop),
#                        .kimi/install.sh (AGENTS.md fallback embed loop).
#
# Failure modes: none - a glob that matches nothing (missing content/rules/
#                directory under a broken REPO_DIR) prints nothing, same as
#                the two loops it replaces did. (m4, DS-185 round 3) This
#                file sets `set -euo pipefail` at file scope, which mutates
#                the sourcing caller's own shell options as a side effect -
#                harmless for both current callers (.kimi/build.sh and
#                .kimi/install.sh already set the same options before
#                sourcing this file), but disclosed here since it is a real
#                side effect a future caller without those options set
#                would inherit unexpectedly.
set -euo pipefail

kimi_rules_files() {
  local content_dir="$1"
  local f name
  for f in "$content_dir/rules/"*.md; do
    [[ -f "$f" ]] || continue
    name="$(basename "$f")"
    [[ "$name" == "module-manifest.md" ]] && continue
    echo "$f"
  done
}
