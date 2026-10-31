#!/usr/bin/env bash
# Purpose: Run a non-Claude adapter's build from its install.sh without
#          leaving the checkout dirty. Claude Code is the primary harness
#          (root AGENTS.md, "Claude Code first"): `main` carries non-Claude
#          artifacts that lag `content/` until the on-demand catch-up chore,
#          so a build from `main` rewrites tracked files, and the next
#          bin/ds-update refuses the dirty tree. Outside DS_ALL_HARNESSES=1,
#          every tracked non-Claude path the build modified or deleted is
#          restored, and every new untracked, non-ignored file it created
#          there is removed. Paths already dirty before the build are left
#          alone, so an operator's own edits survive. Gitignored build
#          outputs are kept.
#
# Public API: ae_harness_build <repo_dir> <build_script> [args...]
#             Returns the build script's exit status.
#
# Upstream deps: bash 3.2+, git, grep.
#
# Downstream consumers: the non-Claude adapter install.sh scripts.
#
# Failure modes: a repo_dir that is not a git work tree, or
#                DS_ALL_HARNESSES=1, runs the build with no restore.

# The non-Claude half of adapter-sync.yml's drift pathspec.
AE_NON_CLAUDE_PATHSPEC=(.codex .cursor .gemini .kimi .opencode .omp .pi .hermes .openclaw .copilot
  .github/copilot-instructions.md .github/agents .github/prompts .github/instructions .github/hooks .github/skills)

_ae_harness_tree_state() {
  # Modified/deleted tracked paths, then new untracked non-ignored paths.
  git -C "$1" diff --name-only -- "${AE_NON_CLAUDE_PATHSPEC[@]}" 2>/dev/null | sed 's/^/M /'
  git -C "$1" ls-files --others --exclude-standard -- "${AE_NON_CLAUDE_PATHSPEC[@]}" 2>/dev/null | sed 's/^/U /'
}

ae_harness_build() {
  local repo="$1" script="$2"
  shift 2
  if [[ "${DS_ALL_HARNESSES:-}" == "1" ]] \
    || ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    bash "$script" "$@"
    return
  fi
  local before after rc line kind path
  before="$(_ae_harness_tree_state "$repo")"
  rc=0
  bash "$script" "$@" || rc=$?
  after="$(_ae_harness_tree_state "$repo")"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if printf '%s\n' "$before" | grep -Fxq -- "$line"; then
      continue
    fi
    kind="${line%% *}"
    path="${line#* }"
    if [[ "$kind" == "M" ]]; then
      git -C "$repo" checkout -q -- "$path"
    else
      rm -f -- "$repo/$path"
    fi
  done <<EOF
$after
EOF
  return "$rc"
}
