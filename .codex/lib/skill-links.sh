#!/usr/bin/env bash
# Purpose: Match and retire this checkout's native-skill symlinks across namespace upgrades.
# Public API: codex_skill_link_owned <destination> <skill>; codex_remove_skill_link <destination> <skill>.
# Upstream deps: bash, python3; REPO_DIR supplied by the installer/uninstaller.
# Downstream consumers: .codex/install.sh, .codex/uninstall.sh.
# Failure modes: foreign links and real entries are preserved; normalization errors fail closed.
# Performance: one local Python process per inspected symlink.

SKILL_NAMES=(dinostack-codex dinostack-codex-brief dinostack-codex-wrap dinostack-codex-implement-ticket)
LEGACY_SKILL_NAMES=(dinostack brief wrap implement-ticket agentic-engineering)

codex_skill_link_owned() {
  python3 - "$REPO_DIR" "$1" "$2" <<'PY'
import os
import sys
from pathlib import Path

repo, link, name = map(Path, sys.argv[1:])
if not link.is_symlink():
    sys.exit(1)
name = str(name)
legacy = name.removeprefix("dinostack-codex-")
if name in {"dinostack-codex", "dinostack", "agentic-engineering"}:
    names = ("dinostack-codex", "dinostack", "agentic-engineering")
    sources = [repo / ".codex/skill"]
else:
    names = (legacy, "dinostack-codex-" + legacy)
    sources = []
sources.extend(repo / ".codex/skills" / item for item in names)
# realpath also normalizes relative and dangling targets, without requiring existence.
target = os.path.realpath(link.parent / os.readlink(link))
sys.exit(0 if target in {os.path.realpath(source) for source in sources} else 1)
PY
}

codex_remove_skill_link() {
  local destination="$1" skill="$2"
  if [[ -L "$destination" ]]; then
    if codex_skill_link_owned "$destination" "$skill"; then
      rm "$destination"
      echo "  - Removed owned skill symlink at $destination"
    else
      echo "  ! $destination (foreign symlink - leaving it)"
    fi
  elif [[ -e "$destination" ]]; then
    echo "  ! $destination (real file/directory - leaving it)"
  fi
}
