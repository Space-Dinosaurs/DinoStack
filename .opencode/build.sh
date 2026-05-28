#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
AGENTS_DST="$REPO_DIR/.opencode/agents"
COMMANDS_DST="$REPO_DIR/.opencode/commands"
SKILL_DST="$REPO_DIR/.opencode/skills/agentic-engineering"

mkdir -p "$AGENTS_DST" "$COMMANDS_DST"

# ---------------------------------------------------------------------------
# Agents: convert Claude Code frontmatter to OpenCode format
#
# Claude Code uses: name, description, tools (comma-separated list)
# OpenCode uses: description, mode, permission (dict)
#
# Map: tools: Read,Glob,Grep,Bash -> read-only subagent
#      tools: Read,Glob,Grep,Bash,Write,Edit -> full-access subagent
# ---------------------------------------------------------------------------

for src in "$CONTENT/agents/"*.md; do
  [[ -e "$src" ]] || continue
  agent_name="$(basename "$src" .md)"
  dst="$AGENTS_DST/$agent_name.md"

  python3 - "$src" "$dst" "$agent_name" <<'PYEOF'
import sys, re

src_path, dst_path, agent_name = sys.argv[1], sys.argv[2], sys.argv[3]

with open(src_path) as f:
    content = f.read()

# Extract existing frontmatter
fm_match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
if not fm_match:
    sys.exit("No frontmatter found in " + src_path)

fm_text = fm_match.group(1)
body = fm_match.group(2)

# Parse frontmatter fields
desc_match = re.search(r'description:\s*>([\s\S]*?)(?=\n\w|\n---|\Z)', fm_text)
if not desc_match:
    desc_match = re.search(r'description:\s*(.*)', fm_text)
desc = desc_match.group(1).strip().replace('\n', ' ') if desc_match else ""

tools_match = re.search(r'tools:\s*(.*)', fm_text)
tools_str = tools_match.group(1).strip() if tools_match else ""

has_write = bool(re.search(r'\bWrite\b', tools_str))
has_edit = bool(re.search(r'\bEdit\b', tools_str))

if has_write or has_edit:
    perm_block = """permission:
  edit: allow
  bash: allow"""
else:
    perm_block = """permission:
  edit: deny
  bash:
    "*": ask
    "git *": allow
    "grep *": allow
    "rg *": allow"""

# Remove the prerequisite blockquote from body (opencode doesn't use it)
body = re.sub(r'\n*>\s*\*\*Prerequisite:\*\*[^\n]*\n*', '\n', body, count=1)
body = body.lstrip('\n')

new_fm = f"""---
description: {desc}
mode: subagent
{perm_block}
---"""

with open(dst_path, 'w') as f:
    f.write(new_fm + '\n' + body)

print("  + " + agent_name)
PYEOF
done

# ---------------------------------------------------------------------------
# Commands: strip the prerequisite line and convert
#
# Claude Code commands are plain markdown. OpenCode commands use frontmatter
# with description, agent, model, template.
# ---------------------------------------------------------------------------

for src in "$CONTENT/commands/"*.md; do
  [[ -e "$src" ]] || continue
  name="$(basename "$src" .md)"
  dst="$COMMANDS_DST/$name.md"

  python3 - "$src" "$dst" "$name" <<'PYEOF'
import sys, re

src_path, dst_path, cmd_name = sys.argv[1], sys.argv[2], sys.argv[3]

with open(src_path) as f:
    content = f.read()

# Strip the prerequisite blockquote
content = re.sub(r'\n*>\s*\*\*Prerequisite:\*\*[^\n]*\n*', '\n', content, count=1)

# Extract the first line as description (typically a heading or summary)
lines = content.strip().split('\n')
desc = ""
for line in lines:
    stripped = line.strip()
    if stripped.startswith('# '):
        desc = stripped.lstrip('# ').strip()
        break
    elif stripped and not stripped.startswith('>'):
        desc = stripped[:120]
        break

if not desc:
    desc = f"Run the {cmd_name} command"

# Build OpenCode command format
new_content = f"""---
description: {desc}
agent: build
---
{content.strip()}"""

with open(dst_path, 'w') as f:
    f.write(new_content + '\n')

print("  + " + cmd_name)
PYEOF
done

# ---------------------------------------------------------------------------
# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
# ---------------------------------------------------------------------------

mkdir -p "$SKILL_DST"
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"
echo "  + METHODOLOGY.md"

# ---------------------------------------------------------------------------
# References: ensure symlinks in skill dir
# ---------------------------------------------------------------------------

for target in references rules templates; do
  link="$SKILL_DST/$target"
  expected="../../../content/$target"
  if [[ -L "$link" ]]; then
    current="$(readlink "$link")"
    if [[ "$current" == "$expected" ]]; then
      echo "  = $target (already linked)"
    else
      ln -sf "$expected" "$link"
      echo "  ~ $target (re-linked)"
    fi
  else
    ln -sf "$expected" "$link"
    echo "  + $target"
  fi
done

# project-scaffolding.yml: hardlink into skill dir
SCAFFOLDING_SRC="$REPO_DIR/content/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"
if [[ ! -e "$SCAFFOLDING_DST" ]] || [[ "$(python3 -c "import os; print(os.stat('$SCAFFOLDING_SRC').st_ino)" 2>/dev/null)" != "$(python3 -c "import os; print(os.stat('$SCAFFOLDING_DST').st_ino)" 2>/dev/null)" ]]; then
  rm -f "$SCAFFOLDING_DST"
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST" 2>/dev/null || cp "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
  echo "  + project-scaffolding.yml"
else
  echo "  = project-scaffolding.yml (already linked)"
fi

echo "OpenCode adapter build complete."