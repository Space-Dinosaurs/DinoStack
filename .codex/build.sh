#!/usr/bin/env bash
# Purpose: Deterministically rebuild every tracked Codex adapter artifact.
#
# Public API: bash .codex/build.sh
#
# Upstream deps: content methodology/rules/agents/commands/references, Codex
#                frontmatter and compatibility inventory, the prompt-wrapper
#                generator, and shared hook sources.
#
# Downstream consumers: .codex/install.sh, pre-commit, CI sync checks, and developers.
#
# Failure modes: exits non-zero before mutation when a mirror root is unsafe,
#                or on methodology assembly, mirror replacement, native-skill,
#                prompt-wrapper, or named-agent generation failure.
#
# Side-effects: .codex/AGENTS.md is generated as a minimal always-resident stub
#               (runtime binding preamble, activation-preflight pointer, and a
#               skill-load-on-trigger instruction) - it no longer embeds the
#               full methodology body. The full body is written only into
#               .codex/skills/dinostack/METHODOLOGY.md by the native-skill
#               build step below (scripts/codex-skills.py build), which loads
#               on trigger via the dinostack skill instead of unconditionally
#               on every session (DS-183).
#
# Performance: linear in canonical content and generated Codex artifact size.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
CODEX_DIR="$REPO_DIR/.codex"
REFS_DST="$CODEX_DIR/references"
COMMANDS_DST="$CODEX_DIR/commands"
HOOKS_DST="$CODEX_DIR/hooks"
SKILLS_DST="$CODEX_DIR/skills"

validate_mirror_root() {
  local label="$1"
  local destination_dir="$2"
  local ancestor

  case "$destination_dir" in
    "$CODEX_DIR"/*) ;;
    *)
      echo "ERROR: unsafe Codex mirror root ($label): path escapes $CODEX_DIR: $destination_dir" >&2
      return 1
      ;;
  esac

  if [[ -L "$destination_dir" || ( -e "$destination_dir" && ! -d "$destination_dir" ) ]]; then
    echo "ERROR: unsafe Codex mirror root ($label): expected a real directory: $destination_dir" >&2
    return 1
  fi

  ancestor="$(dirname "$destination_dir")"
  while [[ "$ancestor" != "$REPO_DIR" ]]; do
    if [[ -L "$ancestor" || ! -d "$ancestor" ]]; then
      echo "ERROR: unsafe Codex mirror root ($label): unsafe parent directory: $ancestor" >&2
      return 1
    fi
    ancestor="$(dirname "$ancestor")"
  done
}

# Validate every destination root as one read-only preflight. This must run
# before AGENTS.md or any mirror is changed so one hostile root cannot expose
# an external tree to a later rm, ln, or mkdir.
validate_mirror_root "references" "$REFS_DST"
validate_mirror_root "commands" "$COMMANDS_DST"
validate_mirror_root "hooks" "$HOOKS_DST"

# ---------------------------------------------------------------------------
# Build AGENTS.md
#
# DS-183: AGENTS.md is a minimal always-resident stub, not the full
# methodology body. It carries only the runtime binding preamble (needed to
# locate the repo/config before anything else can run), an
# activation-preflight pointer (not the full preflight text), and an
# instruction to load the `dinostack` skill on trigger - the skill is where
# the full methodology body actually lives (.codex/skills/dinostack/
# METHODOLOGY.md, built independently below by scripts/codex-skills.py
# build(), which calls scripts/build-methodology.sh itself). This mirrors
# DS-143's Claude Code trigger-load design: the resident set stays small and
# the full body loads only when the skill is invoked. The assembled stub
# text is translated through scripts/codex-skills.py runtime-guidance so it
# advertises native dollar skills and dispatcher-backed manual resources,
# same as before.
# ---------------------------------------------------------------------------

AGENTS_DST="$CODEX_DIR/AGENTS.md"
AGENTS_RAW="$(mktemp "$CODEX_DIR/.AGENTS.raw.XXXXXX")"
AGENTS_RENDERED="$(mktemp "$CODEX_DIR/.AGENTS.rendered.XXXXXX")"
cleanup_agents_temps() {
  rm -f "$AGENTS_RAW" "$AGENTS_RENDERED"
}
trap cleanup_agents_temps EXIT

{
  cat <<'HEADER'
# Agentic Engineering Protocol

This file binds the agentic engineering runtime for every Codex session in this repository. The
full methodology (delegation, risk classification, activation preflight, Skeptic loop, quality
gates, agent definitions) loads separately, on trigger, via the `dinostack` skill - see "Load the
methodology on trigger" below.

## Codex runtime binding preamble

Before following any operational instruction below, establish these bindings in order:

1. Preserve the absolute invocation directory, then bind `AE_PROJECT_DIR` to its repository root
   (`git rev-parse --show-toplevel`) when it is inside a Git repository, otherwise to that verified
   absolute invocation directory. Do this before changing directories.
2. Select the active Codex config directory from the first non-empty runtime source in this order:
   `AGENTIC_CONFIG_DIR`, then `CODEX_HOME`, then the standard Codex config directory beneath a
   validated absolute `HOME`. Require the selected path to resolve to a real current-user-owned
   directory that is not group/world writable, then bind `AE_CODEX_CONFIG_DIR` to it. Profile
   identity operations use only the already-validated `$AE_CODEX_CONFIG_DIR` runtime binding;
   the active profile identity file is `$AE_CODEX_CONFIG_DIR/identity.yml`.
3. Inspect `AGENTS.md` beneath that selected config directory without following an unchecked final
   path. Require the installed entry to be a symlink whose physical target is the regular
   `.codex/AGENTS.md` file beneath a repository candidate whose `content/SKILL.md`, `.codex/`
   directory, and executable `bin/ds-codex-dispatch` form the DinoStack repository signature.
   After those checks, bind `AE_REPO_DIR` to that physical repository root. Never infer it from the
   process working directory.
4. When an explicit config source selected the Codex directory, bind `AE_ACTIVATION_CONFIG` to
   `agentic-engineering.json` beneath that directory. On the standard default install, bind
   `AE_ACTIVATION_CONFIG` to `agentic-engineering.json` beneath the standard shared Claude config
   directory under the validated `HOME`. Require the activation file to be a real, current-user-owned
   regular file that is not group/world writable.
5. Then bind `AE_SHARED_CONFIG_DIR` to the validated real parent directory of that activation file.
   It must be current-user-owned and not group/world writable.

If any binding cannot be established exactly, fail closed before executing the methodology. These
rules mirror the native-skill resource-resolution contract and prevent project paths, repository
resources, and shared user configuration from being conflated. After locating the validated
dispatcher, evaluate the same contract with
`$AE_REPO_DIR/bin/ds-codex-dispatch runtime-bindings "<absolute-invocation-directory>"` and
accept its JSON bindings only when they match the paths established above.

**Note:** This file is auto-generated by `.codex/build.sh`. Do not edit it directly - edit the source files in `content/sections/` (methodology) or `content/rules/` (other rules) instead.

For detailed protocol specs (Skeptic loop, subagent protocol, agent team), see the reference docs in `~/.agents/skills/dinostack/references/` (installed globally) or `.codex/references/` (tracked relative symlinks to `../../content/references/*.md`).

---

## Activation preflight (pointer)

Run the activation preflight once at the first skill invocation (and every `/`-command), before any other operational instruction: identity resolution, opt-in/opt-out check, and profile resolution. Its full procedure is Step 1 of the loaded methodology - invoke the `dinostack` skill below and follow it before proceeding. Do not spawn or use LLM reasoning for this step; it is a direct resolver call.

## Identity confirmation (provisional handle)

When the activation preflight resolves a provisional effective identity, surface this notice at the first user-facing turn - non-blocking:

```
IDENTITY: tracking handle '<handle>' auto-derived (provisional) - confirm or correct.
Telemetry is buffered (not lost) until confirmed.
  Confirm: ds-identity confirm --scope <scope>
  Correct: ds-identity init <handle> --force --scope <scope>
```

Profile commands use the active config binding; add `--profile-dir <dir>` only when absent. The notice re-surfaces until confirmation. Full contract: `content/commands/ds-identity.md`.

## Load the methodology on trigger

Before starting any task, check if the `dinostack` skill should be loaded: code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, or project setup. If any signal matches, invoke it (`$dinostack`) before proceeding - it carries the activation preflight, delegation model, risk classification, Skeptic loop, quality gates, agent definitions, and every reference doc. When in doubt, invoke it.

HEADER

  cat <<'FOOTER'


---

## Protocol Reference

For detailed protocol specs, see the reference docs:

- `skeptic-protocol.md` - Skeptic loop orchestration, findings classification, sign-off format
- `subagent-protocol.md` - Parallel spawning rules, worktree isolation, task decomposition
- `agent-team.md` - Named agent roles, composed flows, decision rules
- `design-goals.md` - System design principles and goals

These live in `~/.agents/skills/dinostack/references/` (global install) or `.codex/references/` (tracked relative symlinks to `../../content/references/*.md`).

For command templates (ds-skeptic, ds-implement-ticket, ds-wrap, etc.), see `.codex/commands/`.
FOOTER

} > "$AGENTS_RAW"

python3 "$REPO_DIR/scripts/codex-skills.py" runtime-guidance --repo "$REPO_DIR" \
  < "$AGENTS_RAW" > "$AGENTS_RENDERED"
chmod 0644 "$AGENTS_RENDERED"
mv "$AGENTS_RENDERED" "$AGENTS_DST"
rm "$AGENTS_RAW"
trap - EXIT

echo "Built AGENTS.md"

# ---------------------------------------------------------------------------
# Build the four native skills
#
# scripts/codex-skills.py transforms canonical prose through the reviewed
# compatibility inventory, renders privately, validates resource closure, and
# atomically synchronizes the exact generated allowlist.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Build .codex/hooks/skill-auto-load-check.sh
#
# .codex/config/hooks.json wires a UserPromptSubmit hook whose command
# self-locates at runtime via dirname(dirname(realpath(~/.codex/hooks.json)))
# + "/hooks/<script>" - since ~/.codex/hooks.json symlinks to
# .codex/config/hooks.json (or its hooks-snapshot copy), this resolves to
# .codex/hooks/<script>, NOT the repo-root hooks/ directory. The other two
# Codex hooks (risk-reminder.sh, stop-context-codex.js) are hand-authored
# directly in .codex/hooks/ because they are Codex-specific. skill-auto-load
# behavior is adapter-agnostic and its single source of truth is repo-root
# hooks/skill-auto-load-check.sh. Create a tracked relative symlink at
# .codex/hooks/skill-auto-load-check.sh targeting
# ../../hooks/skill-auto-load-check.sh so the already-wired hooks.json
# command resolves to a real script.
# ---------------------------------------------------------------------------

mkdir -p "$HOOKS_DST"

# ---------------------------------------------------------------------------
# Build tracked relative symlink mirrors
#
# .codex/references and .codex/commands expose canonical sources for browsing
# and manual workflows. Correctness never depends on inode identity.
# ---------------------------------------------------------------------------

sync_link_directory() {
  local source_dir="$1"
  local destination_dir="$2"
  local relative_prefix="$3"
  local src name existing
  mkdir -p "$destination_dir"
  for src in "$source_dir"/*.md; do
    name="$(basename "$src")"
    if [[ -e "$destination_dir/$name" && ! -L "$destination_dir/$name" ]]; then
      rm "$destination_dir/$name"
    fi
    if [[ -L "$destination_dir/$name" && "$(readlink "$destination_dir/$name")" != "$relative_prefix/$name" ]]; then
      rm "$destination_dir/$name"
    fi
    if [[ ! -L "$destination_dir/$name" ]]; then
      ln -s "$relative_prefix/$name" "$destination_dir/$name"
    fi
  done
  for existing in "$destination_dir"/*.md; do
    [[ -e "$existing" || -L "$existing" ]] || continue
    [[ -e "$source_dir/$(basename "$existing")" ]] || rm "$existing"
  done
}

sync_link_directory "$CONTENT/references" "$REFS_DST" "../../content/references"
sync_link_directory "$CONTENT/commands" "$COMMANDS_DST" "../../content/commands"

if [[ -e "$HOOKS_DST/skill-auto-load-check.sh" && ! -L "$HOOKS_DST/skill-auto-load-check.sh" ]]; then
  rm "$HOOKS_DST/skill-auto-load-check.sh"
fi
if [[ -L "$HOOKS_DST/skill-auto-load-check.sh" && \
      "$(readlink "$HOOKS_DST/skill-auto-load-check.sh")" != "../../hooks/skill-auto-load-check.sh" ]]; then
  rm "$HOOKS_DST/skill-auto-load-check.sh"
fi
if [[ ! -L "$HOOKS_DST/skill-auto-load-check.sh" ]]; then
  ln -s "../../hooks/skill-auto-load-check.sh" "$HOOKS_DST/skill-auto-load-check.sh"
fi

echo "Rebuilt command, reference, and shared-hook symlinks"

# The repository-only legacy prompt surface is derived from the completed
# canonical command mirror. It intentionally remains independent of native
# skill generation and owns only .codex/prompts plus its manifest state.
python3 "$CODEX_DIR/lib/prompt-wrappers.py" build --repo "$REPO_DIR"

python3 "$REPO_DIR/scripts/codex-skills.py" build --repo "$REPO_DIR" --output "$SKILLS_DST"

# ---------------------------------------------------------------------------
# Build .codex/agents/ (generated TOML files from content/agents/*.md)
#
# Each content/agents/<name>.md has YAML frontmatter (name, description,
# model, tools) followed by the agent body. The body becomes
# developer_instructions in the TOML file. Only name and description are
# written to the TOML - the model field is intentionally omitted so agents
# inherit the session model. The Claude-specific model and tools: fields
# have no useful Codex TOML equivalent and are silently dropped.
#
# The /dinostack prerequisite blockquote (Claude Code-specific) is
# stripped from the body before writing to developer_instructions. Any line
# matching "> **Prerequisite:**.*dinostack" and any immediately
# following blockquote continuation lines ("> ...") are removed, along with
# one trailing blank line if present.
#
# This keeps content/agents/*.md as the single source of truth - editing
# there regenerates the TOML on the next build.
# ---------------------------------------------------------------------------

AGENTS_TOML_DST="$CODEX_DIR/agents"
mkdir -p "$AGENTS_TOML_DST"

# Track which TOML files we generated so we can remove stale ones below.
declare -a generated_tomls=()

for src in "$CONTENT/agents/"*.md; do
  [ -f "$src" ] || continue

  echo "  building $(basename "$src" .md).toml"

  # --- Parse frontmatter ---
  # Extract the YAML block between the first pair of --- delimiters.
  fm_name=""
  fm_description=""
  in_fm=0
  past_fm=0
  body_lines=()

  while IFS= read -r line; do
    if [[ $in_fm -eq 0 && $past_fm -eq 0 ]]; then
      if [[ "$line" == "---" ]]; then
        in_fm=1
        continue
      fi
    fi
    if [[ $in_fm -eq 1 ]]; then
      if [[ "$line" == "---" ]]; then
        in_fm=0
        past_fm=1
        continue
      fi
      # Parse simple key: value pairs (no nested YAML)
      key="${line%%:*}"
      val="${line#*: }"
      # Strip leading/trailing whitespace from val
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"
      case "$key" in
        name)        fm_name="$val" ;;
      esac
      continue
    fi
    # Past frontmatter: accumulate body lines
    if [[ $past_fm -eq 1 ]]; then
      body_lines+=("$line")
    fi
  done < "$src"

  # Extract 'description' via a real YAML parser rather than the bash
  # key:value line-splitter above - the source value may be a quoted scalar
  # (single-line or folded), so naive line-splitting would capture the
  # literal quote/escape characters instead of the decoded value.
  fm_description="$(python3 - "$src" <<'PYEOF'
import sys, re
import yaml

with open(sys.argv[1], encoding="utf-8") as f:
    text = f.read()
m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
if m:
    fm = yaml.safe_load(m.group(1)) or {}
    desc = fm.get("description") or ""
    print(re.sub(r'\s+', ' ', desc).strip())
PYEOF
)"

  if [[ -z "$fm_name" ]]; then
    echo "WARNING: $src has no 'name' in frontmatter - skipping"
    continue
  fi
  if [[ -z "$fm_description" ]]; then
    echo "WARNING: $src has no 'description' in frontmatter - skipping"
    continue
  fi

  # model is intentionally not written to TOML - agents inherit the session
  # model. Anthropic model IDs (claude-*) are not valid in Codex anyway.

  # Strip /dinostack prerequisite blockquotes from body.
  # Pattern: a line starting with "> " that contains "/dinostack"
  # followed by any immediately-following blockquote continuation lines
  # (lines that start with ">"), followed by one optional blank line.
  # Use a simple state-machine line-skip rather than fragile regex.
  filtered_body_lines=()
  skip_next_blockquotes=0
  skip_one_blank=0
  for bline in "${body_lines[@]}"; do
    if [[ $skip_next_blockquotes -eq 1 ]]; then
      # Still inside the blockquote block - skip continuation lines
      if [[ "$bline" == ">"* ]]; then
        continue
      fi
      skip_next_blockquotes=0
      skip_one_blank=1
    fi
    if [[ $skip_one_blank -eq 1 ]]; then
      skip_one_blank=0
      if [[ -z "$bline" ]]; then
        # Blank line immediately after stripped blockquote - skip it too
        continue
      fi
      # Not blank - keep it and fall through to normal processing
    fi
    # Detect the prerequisite blockquote line
    if [[ "$bline" == ">"* ]] && echo "$bline" | grep -q "/dinostack"; then
      skip_next_blockquotes=1
      continue
    fi
    filtered_body_lines+=("$bline")
  done
  body_lines=("${filtered_body_lines[@]+"${filtered_body_lines[@]}"}")

  # Build the body string: join accumulated lines.
  # We need to escape backslash and double-quote for the TOML triple-quoted
  # string. In TOML """ strings, only backslash requires escaping; double
  # quotes are allowed as long as three consecutive ones are not present.
  # We escape backslash as \\ and replace any run of 3+ double-quotes with
  # escaped variants to be safe.
  if [[ ${#body_lines[@]} -gt 0 ]]; then
    OLD_IFS="$IFS"
    IFS=$'\n'
    body_content="${body_lines[*]}"
    IFS="$OLD_IFS"
  else
    body_content=""
  fi

  # Escape backslashes, then sequences of 3+ double-quotes, for the TOML
  # multi-line basic string. Bash's own `${var//pattern/repl}` parameter
  # substitution is prohibitively slow on large bodies (DS-135 follow-up) -
  # a single backslash-escape pass alone did not complete in 200s on a
  # ~335KB body under bash 3.2.57 (the default macOS /bin/bash). Route both
  # passes through python3 (already a repo dependency) instead. A trailing
  # sentinel byte guards the two escape passes' output against command
  # substitution's trailing-newline stripping, since a body that ends in a
  # blank line would otherwise silently lose that trailing newline.
  body_escaped="$(
    printf '%s' "$body_content" | python3 -c '
import sys
s = sys.stdin.read()
s = s.replace("\\", "\\\\")
s = s.replace("\"\"\"", "\\\"\\\"\\\"")
sys.stdout.write(s)
'
    printf '\x01'
  )"
  body_escaped="${body_escaped%$'\x01'}"

  # Escape description for a TOML basic string (escape backslash then double-quote)
  desc_escaped="${fm_description//\\/\\\\}"
  desc_escaped="${desc_escaped//\"/\\\"}"

  dst="$AGENTS_TOML_DST/${fm_name}.toml"
  generated_tomls+=("${fm_name}.toml")

  {
    echo "# Generated by .codex/build.sh from content/agents/$(basename "$src")"
    echo "# Do not edit directly - edit the source markdown file instead."
    echo ""
    echo "name        = \"${fm_name}\""
    echo "description = \"${desc_escaped}\""
    echo ""
    echo "developer_instructions = \"\"\""
    printf '%s' "$body_escaped"
    echo ""
    echo "\"\"\""
  } > "$dst"

done

# Remove stale TOML files (present in agents/ but not generated this run)
for existing in "$AGENTS_TOML_DST"/*.toml; do
  [ -f "$existing" ] || continue
  bname="$(basename "$existing")"
  found=0
  for gen in "${generated_tomls[@]}"; do
    if [[ "$gen" == "$bname" ]]; then
      found=1
      break
    fi
  done
  if [[ $found -eq 0 ]]; then
    rm "$existing"
    echo "Removed stale agent TOML: $bname"
  fi
done

echo "Built ${#generated_tomls[@]} agent TOML files in .codex/agents/"

echo "Codex adapter build complete."
