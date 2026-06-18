#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Builds the OpenClaw adapter skill tree deterministically from
#          content/ sources. Generates the entry skill (agentic-engineering),
#          one skill dir per command, and one skill dir per agent (prefixed
#          agent-<name> on both dir and frontmatter name to avoid identity
#          collisions). Produces byte-identical output across runs.
#
# Public API: Run directly: bash .openclaw/build.sh
#             Called by install.sh and the adapter-sync CI workflow.
#
# Upstream deps: content/commands/*.md, content/agents/*.md,
#                content/SKILL.md, content/project-scaffolding.yml,
#                scripts/build-methodology.sh. Python 3 on PATH.
#
# Downstream consumers: .openclaw/skills/ (installed via install.sh to
#                       ~/.openclaw/skills/ as per-skill-dir symlinks).
#
# Failure modes: Exits non-zero on any error (set -euo pipefail). Safe to
#                re-run; ln -sfn and conditional hardlink are idempotent.
#
# Performance: Standard. Regenerates all SKILL.md files on each run.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
SKILLS_DIR="$REPO_DIR/.openclaw/skills"
SKILL_DST="$SKILLS_DIR/agentic-engineering"

mkdir -p "$SKILL_DST"

# ---------------------------------------------------------------------------
# Entry skill: agentic-engineering
# ---------------------------------------------------------------------------

cat > "$SKILL_DST/SKILL.md" <<'SKILLEOF'
---
name: agentic-engineering
description: >
  Apply when the user mentions any software development work: implementing features, fixing bugs,
  reviewing or refactoring code, debugging, testing, deploying, working with agents or subagents,
  making architecture decisions, setting up projects, managing dependencies, writing scripts, or
  any task that involves reading, writing, or reasoning about code and systems.
user-invocable: true
---

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**BEFORE ANY ACTION: classify risk first.** Elevated = spawn Worker + Skeptic in background. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging. When in doubt, classify Elevated.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (Read/Glob/Grep
  over Bash for reads), code quality gates, package management conventions, and browser verification
  with agent-browser.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Reference Docs (read on trigger - see Protocol Details in agent-methodology.md)

- **references/skeptic-protocol.md** - Skeptic loop orchestration, findings classification
  (Critical/Major/Minor), sign-off format, adversarial briefs, and the Elevated + Cleanup path.

- **references/subagent-protocol.md** - parallel spawning rules, worktree isolation, check-in
  behavior, phase breadcrumbs, and task decomposition rules for multi-Worker plans.

- **references/agent-team.md** - named agent roles (engineer, architect, investigator, debugger,
  security-auditor, orchestration-planner), composed flows, decision rules, and spawn requirements.

- **references/design-goals.md** - design principles and goals of the Agentic Engineering system;
  read when evaluating whether a proposed change aligns with the system's intent.

- **references/regression-test-obligation.md** - per-finding regression-test obligation: every
  Skeptic finding fixed during a task must come with a regression test that would have caught it;
  read when fixing a Skeptic finding to confirm what counts as a valid regression test.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.
SKILLEOF

echo "  + agentic-engineering/SKILL.md"

# ---------------------------------------------------------------------------
# Methodology: assemble content/sections/*.md into METHODOLOGY.md
# ---------------------------------------------------------------------------

bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"
echo "  + agentic-engineering/METHODOLOGY.md"

# ---------------------------------------------------------------------------
# Symlinks: references, rules, templates (relative, idempotent)
# ---------------------------------------------------------------------------

for target in references rules templates; do
  link="$SKILL_DST/$target"
  expected="../../../content/$target"
  if [[ -L "$link" ]]; then
    current="$(readlink "$link")"
    if [[ "$current" == "$expected" ]]; then
      echo "  = agentic-engineering/$target (already linked)"
    else
      ln -sfn "$expected" "$link"
      echo "  ~ agentic-engineering/$target (re-linked)"
    fi
  elif [[ -e "$link" ]]; then
    echo "  ! agentic-engineering/$target (real file exists - skipping)"
  else
    ln -sfn "$expected" "$link"
    echo "  + agentic-engineering/$target"
  fi
done

# ---------------------------------------------------------------------------
# project-scaffolding.yml: hardlink (or copy on filesystems that forbid it)
# ---------------------------------------------------------------------------

SCAFFOLDING_SRC="$REPO_DIR/content/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"

need_copy=true
if [[ -e "$SCAFFOLDING_DST" ]]; then
  src_ino="$(python3 -c "import os; print(os.stat('$SCAFFOLDING_SRC').st_ino)" 2>/dev/null || echo "")"
  dst_ino="$(python3 -c "import os; print(os.stat('$SCAFFOLDING_DST').st_ino)" 2>/dev/null || echo "")"
  if [[ -n "$src_ino" && "$src_ino" == "$dst_ino" ]]; then
    need_copy=false
    echo "  = agentic-engineering/project-scaffolding.yml (already linked)"
  fi
fi

if [[ "$need_copy" == "true" ]]; then
  rm -f "$SCAFFOLDING_DST"
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST" 2>/dev/null || cp "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
  echo "  + agentic-engineering/project-scaffolding.yml"
fi

# ---------------------------------------------------------------------------
# Command skills (19): one skill dir per command file
# ---------------------------------------------------------------------------

cmd_count=0
while IFS= read -r src; do
  [[ -e "$src" ]] || continue
  name="$(basename "$src" .md)"
  dir="$SKILLS_DIR/$name"
  mkdir -p "$dir"

  python3 - "$src" "$dir/SKILL.md" "$name" <<'PYEOF'
import sys, re

src_path, dst_path, cmd_name = sys.argv[1], sys.argv[2], sys.argv[3]

with open(src_path) as f:
    raw = f.read()

# Strip the prerequisite blockquote
content = re.sub(r'\n*>\s*\*\*Prerequisite:\*\*[^\n]*\n*', '\n', raw, count=1)

# Extract description - priority order:
# 1. Purpose: field from a LEADING HTML comment block (within first 2000 chars)
# 2. First real prose line (not heading, not blockquote, not comment fence)
# 3. Heading text fallback

desc = ""

# Priority 1: Purpose field from a leading HTML comment (<!-- ... -->) in the first 2000 chars.
# Only matches comments that open before the main body to avoid inline comments deeper in the file.
leading_text = raw[:2000]
comment_match = re.search(r'<!--(.*?)-->', leading_text, re.DOTALL)
if comment_match:
    comment_body = comment_match.group(1)
    # Stop at any "FieldName:" label on its own line (allowing spaces in the field name)
    purpose_match = re.search(r'Purpose:\s*(.*?)(?=\n\s*[\w][\w\s]*:\s|\Z)', comment_body, re.DOTALL)
    if purpose_match:
        purpose_text = purpose_match.group(1)
        # Collapse whitespace and newlines to a single space
        purpose_text = re.sub(r'\s+', ' ', purpose_text).strip()
        # Trim to ~200 chars at a word boundary
        if len(purpose_text) > 200:
            trimmed = purpose_text[:200]
            last_space = trimmed.rfind(' ')
            purpose_text = trimmed[:last_space] if last_space > 0 else trimmed
        if purpose_text:
            desc = purpose_text

# Priority 2: First real prose line
if not desc:
    lines = content.strip().split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('# '):
            continue
        if stripped.startswith('>'):
            continue
        if stripped.startswith('<!--') or stripped.startswith('-->'):
            continue
        desc = stripped[:200]
        break

# Priority 3: Heading text fallback
if not desc:
    for line in content.strip().split('\n'):
        stripped = line.strip()
        if stripped.startswith('# '):
            desc = stripped.lstrip('# ').strip()
            break

if not desc:
    desc = f"Run the {cmd_name} command"

# Always quote the description value for YAML safety
desc_escaped = desc.replace('"', '\\"')

skill_content = f"""---
name: {cmd_name}
description: "{desc_escaped}"
user-invocable: true
---
{content.strip()}
"""

with open(dst_path, 'w') as f:
    f.write(skill_content)

print("  + " + cmd_name + "/SKILL.md")
PYEOF

  cmd_count=$((cmd_count + 1))
done < <(LC_ALL=C find "$CONTENT/commands" -maxdepth 1 -name '*.md' | LC_ALL=C sort)

# ---------------------------------------------------------------------------
# Agent skills (16): one skill dir per agent, prefixed agent-<name>
# ---------------------------------------------------------------------------

agent_count=0
while IFS= read -r src; do
  [[ -e "$src" ]] || continue
  base="$(basename "$src" .md)"
  skill_name="agent-$base"
  dir="$SKILLS_DIR/$skill_name"
  mkdir -p "$dir"

  python3 - "$src" "$dir/SKILL.md" "$skill_name" <<'PYEOF'
import sys, re

src_path, dst_path, skill_name = sys.argv[1], sys.argv[2], sys.argv[3]

with open(src_path) as f:
    content = f.read()

# Extract existing frontmatter
fm_match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
if not fm_match:
    sys.exit("No frontmatter found in " + src_path)

fm_text = fm_match.group(1)
body = fm_match.group(2)

# Parse description from frontmatter (handles multiline > style)
desc_match = re.search(r'description:\s*>([\s\S]*?)(?=\n\w|\n---|\Z)', fm_text)
if not desc_match:
    desc_match = re.search(r'description:\s*(.*)', fm_text)
desc = desc_match.group(1).strip().replace('\n', ' ') if desc_match else f"Agent: {skill_name}"
# Collapse multiple spaces from multiline join
desc = re.sub(r'\s+', ' ', desc).strip()

# Always quote the description value for YAML safety (mirrors command path)
desc_escaped = desc.replace('"', '\\"')

# Strip the prerequisite blockquote from body
body = re.sub(r'\n*>\s*\*\*Prerequisite:\*\*[^\n]*\n*', '\n', body, count=1)
body = body.lstrip('\n')

new_skill = f"""---
name: {skill_name}
description: "{desc_escaped}"
user-invocable: false
disable-model-invocation: true
---
{body}"""

with open(dst_path, 'w') as f:
    f.write(new_skill)

print("  + " + skill_name + "/SKILL.md")
PYEOF

  agent_count=$((agent_count + 1))
done < <(LC_ALL=C find "$CONTENT/agents" -maxdepth 1 -name '*.md' | LC_ALL=C sort)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total=$((1 + cmd_count + agent_count))
echo ""
echo "OpenClaw adapter build complete."
echo "  Skills generated: $total (1 entry + $cmd_count commands + $agent_count agents)"
