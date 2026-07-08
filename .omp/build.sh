#!/usr/bin/env bash
# Purpose: Build the oh-my-pi (omp) adapter outputs from canonical content/.
# Public API: invoked as `bash .omp/build.sh`; idempotent.
# Upstream deps: content/commands/, content/references/, content/rules/, content/agents/,
#               content/sections/, content/SKILL-full.md, scripts/build-methodology.sh.
# Downstream consumers: .omp/skills/agentic-engineering/.
# Failure modes: exits non-zero on missing inputs or assembly failure. Idempotent.
# Performance: standard.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
SKILL_DST="$REPO_DIR/.omp/skills/agentic-engineering"

mkdir -p "$SKILL_DST"

required=(
  "$CONTENT/SKILL-full.md"
  "$REPO_DIR/scripts/build-methodology.sh"
  "$SKILL_DST/SKILL.frontmatter.yaml"
)
for path in "${required[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "build.sh: missing $path" >&2
    exit 1
  fi
done

# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"

# SKILL.md: oh-my-pi implements the Agent Skills standard. Keep adapter
# frontmatter in .omp and derive body from canonical content/SKILL-full.md.
{
  cat "$SKILL_DST/SKILL.frontmatter.yaml"
  echo
  perl -0pe 's/\A<!--.*?-->\n\n?//s; s#rules/agent-methodology\.md#METHODOLOGY.md#g' "$CONTENT/SKILL-full.md"
  cat <<'OMP_NOTES'

## oh-my-pi (omp) usage

oh-my-pi discovers this skill from `.omp/skills/agentic-engineering/` for project-local use and from `~/.omp/agent/skills/agentic-engineering/` after global install.

**Auto-trigger:** The skill loads automatically when you describe software development work. Ask the agent to "use the agentic-engineering skill" for an explicit load.

**IMPORTANT:** oh-my-pi does NOT support custom markdown slash commands like `/init-project`, `/wrap`, `/brief`, or any other command referenced in the "Commands (invoke by name)" section above. That section describes Claude Code slash-command conventions - in oh-my-pi, invoke the same commands via natural language (e.g. "run init-project", "do a wrap") or by reading the corresponding `commands/<name>.md` file directly and following its instructions.

Read `METHODOLOGY.md` at skill load before applying the workflow. Read command details from `commands/<name>.md` when a workflow step asks you to run a command. Read references from `references/` and rules from `rules/` on their documented triggers.

## oh-my-pi subagent mapping

oh-my-pi provides built-in subagent types. Map agentic-engineering roles to them as follows:

- **`task`** (default) - general implementation work (maps to `engineer`, `debugger`, `qa-engineer`, `perf-analyst`). The standard Worker for Elevated-risk tasks.
- **`explore`** - fast read-only codebase exploration (maps to `investigator`, `dependency-auditor`, `adr-drift-detector`).
- **`plan`** - implementation planning and architecture design (maps to `architect`, `orchestration-planner`, `adr-generator`).
- **`designer`** - UI/UX design work (maps to designer roles).
- **`reviewer`** - adversarial code review (maps to `skeptic`, `security-auditor`).
- **`quick_task`** - lightweight, low-risk tasks that don't need full Worker + Skeptic review.

oh-my-pi also provides native commands that map to methodology workflows:
- `/plan` - maps to `orchestration-planner` or `architect` workflows
- `/review` - maps to `skeptic` adversarial review

When spawning a subagent, read the corresponding detailed agent file from `agents/<name>.md` and include its full instructions in the spawn prompt. The agent files contain role-specific constraints, reporting formats, and workflow rules that `references/agent-team.md` does not cover in detail.

| Agentic role | File to read | oh-my-pi subagent type |
|---|---|---|
| `engineer` | `agents/engineer.md` | `task` |
| `debugger` | `agents/debugger.md` | `task` |
| `qa-engineer` | `agents/qa-engineer.md` | `task` |
| `perf-analyst` | `agents/perf-analyst.md` | `task` |
| `investigator` | `agents/investigator.md` | `explore` |
| `dependency-auditor` | `agents/dependency-auditor.md` | `explore` |
| `adr-drift-detector` | `agents/adr-drift-detector.md` | `explore` |
| `architect` | `agents/architect.md` | `plan` |
| `orchestration-planner` | `agents/orchestration-planner.md` | `plan` |
| `adr-generator` | `agents/adr-generator.md` | `plan` |
| `security-auditor` | `agents/security-auditor.md` | `reviewer` or `task` |
| `release-orchestrator` | `agents/release-orchestrator.md` | `task` |

For the **Skeptic** role, spawn a `reviewer` subagent or use oh-my-pi's native `/review` command, prepending the skeptic instructions from `agents/skeptic.md` (or `references/skeptic-protocol.md` for the protocol overview) and restricting its task to read-only review.
OMP_NOTES
} > "$SKILL_DST/SKILL.md"

# ---------------------------------------------------------------------------
# Ensure symlinks in skill directory
# ---------------------------------------------------------------------------

symlink_dir() {
  local target="$1"
  local link="$2"
  if [[ -L "$link" ]]; then
    current="$(readlink "$link")"
    if [[ "$current" == "$target" ]]; then
      echo "  = $(basename "$link") (already linked)"
    else
      rm "$link"
      ln -s "$target" "$link"
      echo "  ~ $(basename "$link") (re-linked)"
    fi
  elif [[ -e "$link" ]]; then
    echo "  ! $(basename "$link") exists and is not a symlink - leaving it"
  else
    ln -s "$target" "$link"
    echo "  + $(basename "$link")"
  fi
}

symlink_dir "../../../content/references" "$SKILL_DST/references"
symlink_dir "../../../content/rules"     "$SKILL_DST/rules"
symlink_dir "../../../content/commands"  "$SKILL_DST/commands"
symlink_dir "../../../content/agents"    "$SKILL_DST/agents"
symlink_dir "../../../content/templates" "$SKILL_DST/templates"

# project-scaffolding.yml: hardlink (single file, not a dir)
SCAFFOLDING_SRC="$REPO_DIR/content/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"
if [[ -L "$SCAFFOLDING_DST" ]]; then
  rm "$SCAFFOLDING_DST"
fi
if [[ ! -e "$SCAFFOLDING_DST" ]]; then
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST" 2>/dev/null || cp "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
  echo "  + project-scaffolding.yml"
fi

# ---------------------------------------------------------------------------
# Make scripts executable
# ---------------------------------------------------------------------------

for script in "$REPO_DIR/.omp"/*.sh; do
  [[ -e "$script" ]] || continue
  chmod +x "$script"
done

echo "Pi (oh-my-pi) adapter build complete."
