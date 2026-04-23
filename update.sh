#!/usr/bin/env bash
set -euo pipefail

# update.sh — interactive updater for the agentic-engineering repo installation.
#
# Presents an arrow-key multi-select menu of adapters (Claude always locked on,
# others togglable), confirms the plan, then performs the update directly in
# bash: a git fast-forward pull followed by each selected adapter's install.sh.
#
# Usage: ./update.sh        (interactive)
#        ./update.sh --help (print usage, exit 0)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# --help flag
# ---------------------------------------------------------------------------

usage() {
  cat <<EOF
Usage: $(basename "$0") [--help]

Interactive updater for the agentic-engineering repo. Opens a multi-select
menu of adapters (Claude locked on, others togglable), confirms the plan,
then runs 'git pull --ff-only origin main' and each chosen install.sh.

Options:
  -h, --help    Print this help and exit.

Requirements:
  - Runs in a TTY (not piped).
  - 'git' must be on PATH.
  - Must be run from an agentic-engineering checkout (contains .claude/install.sh).
  - Must be a git checkout on branch 'main' with a clean working tree (checked before the menu).

Controls:
  up/down   navigate
  space     toggle selected row
  enter     confirm selection and continue to final confirmation
  q         abort (also Ctrl-C)
EOF
}

for arg in "${@:-}"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    "")
      ;;
    *)
      echo "error: unknown argument: $arg" >&2
      echo "" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight guards
# ---------------------------------------------------------------------------

if [[ ! -t 0 || ! -t 1 ]]; then
  echo "error: update.sh requires a terminal (TTY) — run it directly from a shell, not piped." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "error: 'git' not found on PATH." >&2
  exit 1
fi

if [[ ! -f "$REPO_DIR/.claude/install.sh" ]]; then
  echo "error: $REPO_DIR does not look like an agentic-engineering checkout" >&2
  echo "       (expected $REPO_DIR/.claude/install.sh)." >&2
  exit 1
fi

if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: $REPO_DIR is not a git working tree (or git cannot read it)." >&2
  exit 1
fi

CURRENT_BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "error: update.sh must be run from the 'main' branch (currently on '${CURRENT_BRANCH:-unknown}')." >&2
  echo "       switch branches with 'git checkout main' and retry." >&2
  exit 1
fi

if [[ -n "$(git -C "$REPO_DIR" status --porcelain)" ]]; then
  echo "error: local changes block the update — git pull needs a clean working tree." >&2
  echo "" >&2
  STAGED="$(git -C "$REPO_DIR" diff --cached --name-only 2>/dev/null || true)"
  UNSTAGED="$(git -C "$REPO_DIR" diff --name-only 2>/dev/null || true)"
  UNTRACKED="$(git -C "$REPO_DIR" ls-files --others --exclude-standard 2>/dev/null || true)"
  if [[ -n "$STAGED" ]]; then
    echo "  Staged for commit:" >&2
    sed 's/^/    /' <<< "$STAGED" >&2
  fi
  if [[ -n "$UNSTAGED" ]]; then
    echo "  Modified (not staged):" >&2
    sed 's/^/    /' <<< "$UNSTAGED" >&2
  fi
  if [[ -n "$UNTRACKED" ]]; then
    echo "  Untracked:" >&2
    sed 's/^/    /' <<< "$UNTRACKED" >&2
  fi
  if [[ -z "${STAGED}${UNSTAGED}${UNTRACKED}" ]]; then
    echo "  (unexpected state; listing paths:)" >&2
    git -C "$REPO_DIR" status --short >&2
  fi
  echo "" >&2
  echo "  Try again once the working tree is clean." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Dynamic adapter discovery
# ---------------------------------------------------------------------------

shopt -s nullglob
ALL_ADAPTERS=()
for dir in "$REPO_DIR"/.*/; do
  name="$(basename "$dir")"
  case "$name" in
    .|..|.git|.github|.vscode|.idea|.cache|.venv|.mypy_cache|.pytest_cache|.ruff_cache)
      continue
      ;;
  esac
  [[ -f "$dir/install.sh" ]] || continue
  ALL_ADAPTERS+=("$name")
done
shopt -u nullglob

# Split into locked (.claude) and togglable (everything else, sorted).
LOCKED=".claude"
TOGGLABLE=()
for name in "${ALL_ADAPTERS[@]}"; do
  [[ "$name" == "$LOCKED" ]] && continue
  TOGGLABLE+=("$name")
done

# Case-insensitive alphabetical sort of togglable adapters.
if (( ${#TOGGLABLE[@]} > 0 )); then
  IFS=$'\n' TOGGLABLE=($(printf '%s\n' "${TOGGLABLE[@]}" | LC_ALL=C sort -f))
  unset IFS
fi

# ---------------------------------------------------------------------------
# Display-name derivation
# ---------------------------------------------------------------------------

display_name() {
  local raw="$1"
  local stripped="${raw#.}"
  case "$stripped" in
    claude)   echo "Claude" ;;
    codex)    echo "Codex" ;;
    cursor)   echo "Cursor" ;;
    gemini)   echo "Gemini" ;;
    opencode) echo "OpenCode" ;;
    *)
      # Title-case fallback: uppercase first letter, lowercase rest.
      local first="${stripped:0:1}"
      local rest="${stripped:1}"
      printf '%s%s\n' "$(printf '%s' "$first" | tr '[:lower:]' '[:upper:]')" "$(printf '%s' "$rest" | tr '[:upper:]' '[:lower:]')"
      ;;
  esac
}

# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

# Selection state: parallel array to TOGGLABLE — "1" = on, "0" = off. Default off.
SELECTED=()
if (( ${#TOGGLABLE[@]} > 0 )); then
  for _ in "${TOGGLABLE[@]}"; do
    SELECTED+=("0")
  done
fi

CURSOR=0  # index into TOGGLABLE (0-based)

# Tracks whether we entered the terminfo alternate-screen buffer so the
# trap can reliably leave it on any exit path.
ALT_SCREEN_ACTIVE=0

_restore_term() {
  tput cnorm 2>/dev/null || true
  stty echo 2>/dev/null || true
  if (( ALT_SCREEN_ACTIVE == 1 )); then
    tput rmcup 2>/dev/null || true
    ALT_SCREEN_ACTIVE=0
  fi
}

trap '_restore_term' EXIT HUP TERM QUIT
trap '_restore_term; exit 130' INT

draw_menu() {
  # Header + blank + locked + togglable + blank + help line.
  # We print the whole block, then on subsequent redraws move the cursor up
  # by the number of printed lines and overwrite.
  local locked_label
  locked_label="$(display_name "$LOCKED")"

  printf '  Update agentic-engineering\n'
  printf '\n'
  printf '  [\xe2\x97\x8f] %-16s (always updated)\n' "$locked_label"

  if (( ${#TOGGLABLE[@]} > 0 )); then
    local i=0
    for name in "${TOGGLABLE[@]}"; do
      local mark=" "
      [[ "${SELECTED[$i]:-0}" == "1" ]] && mark="x"
      local pointer="  "
      [[ $i -eq $CURSOR ]] && pointer="> "
      printf '%s[%s] %s\n' "$pointer" "$mark" "$(display_name "$name")"
      i=$((i + 1))
    done
  fi

  printf '\n'
  printf '  \xe2\x86\x91/\xe2\x86\x93 navigate \xc2\xb7 space toggle \xc2\xb7 enter confirm \xc2\xb7 q abort\n'
}

run_menu() {
  if (( ${#TOGGLABLE[@]} == 0 )); then
    # No extras to toggle. Still show the Claude row + help, let user confirm.
    draw_menu
    return 0
  fi

  # Enter the terminfo alternate-screen buffer so the menu has a private
  # canvas. This avoids redraw bugs on narrow terminals where logical lines
  # wrap: a full clear-and-repaint on each keystroke stays correct at any
  # width. The buffer is dismissed on exit (via _restore_term), so the menu
  # doesn't clutter scrollback — the "Will run:" confirmation below still
  # shows the user's selection in the normal terminal.
  if tput smcup 2>/dev/null; then
    ALT_SCREEN_ACTIVE=1
  fi

  tput civis 2>/dev/null || true
  stty -echo

  tput clear 2>/dev/null || printf '\033[H\033[2J'
  draw_menu

  local key rest
  while true; do
    IFS= read -rsn1 key || { return 1; }
    case "$key" in
      $'\x1b')
        # Read the rest of the escape sequence (2 more bytes for arrow keys).
        # No timeout: arrow keys arrive atomically as ESC [ A/B, so the 2-byte
        # read returns immediately. A bare ESC press will block until the next
        # 2 keys arrive — acceptable since ESC has no meaning in this menu.
        # (We intentionally avoid `read -t 0.01`: fractional timeouts are not
        # supported on bash 3.2, the default on macOS.)
        IFS= read -rsn2 rest || rest=""
        case "$rest" in
          '[A') # up
            if (( CURSOR > 0 )); then
              CURSOR=$((CURSOR - 1))
            fi
            ;;
          '[B') # down
            if (( CURSOR < ${#TOGGLABLE[@]} - 1 )); then
              CURSOR=$((CURSOR + 1))
            fi
            ;;
        esac
        ;;
      ' ')
        if [[ "${SELECTED[$CURSOR]}" == "1" ]]; then
          SELECTED[$CURSOR]="0"
        else
          SELECTED[$CURSOR]="1"
        fi
        ;;
      '') # Enter
        break
        ;;
      q|Q)
        # _restore_term (EXIT trap) will dismiss alt-screen and restore
        # terminal state; the caller will print "aborted." in normal mode.
        return 1
        ;;
    esac

    # Full clear-and-repaint. In the alt-screen buffer this is cheap and
    # completely avoids any visual-vs-logical line-count accounting.
    tput clear 2>/dev/null || printf '\033[H\033[2J'
    draw_menu
  done

  return 0
}

# ---------------------------------------------------------------------------
# Run menu
# ---------------------------------------------------------------------------

if ! run_menu; then
  _restore_term
  echo "aborted."
  exit 130
fi

_restore_term

# ---------------------------------------------------------------------------
# Build the list of install-script commands
# ---------------------------------------------------------------------------

# Always include .claude first.
INSTALL_CMDS=("bash .claude/install.sh")
SELECTED_NAMES=("$(display_name "$LOCKED")")

for i in "${!TOGGLABLE[@]}"; do
  if [[ "${SELECTED[$i]}" == "1" ]]; then
    adapter="${TOGGLABLE[$i]}"
    INSTALL_CMDS+=("bash $adapter/install.sh")
    SELECTED_NAMES+=("$(display_name "$adapter")")
  fi
done

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

echo "Will run:"
echo "  git fetch origin"
echo "  git pull --ff-only origin main"
for cmd in "${INSTALL_CMDS[@]}"; do
  echo "  $cmd"
done
echo ""
echo "Adapters to refresh: ${SELECTED_NAMES[*]}"
echo ""

read -r -p "Proceed? [Y/n] " REPLY
case "${REPLY:-}" in
  n|N|no|NO)
    echo "aborted."
    exit 0
    ;;
  *)
    ;;
esac

# ---------------------------------------------------------------------------
# Perform the update
# ---------------------------------------------------------------------------

cd "$REPO_DIR"

echo ""
echo ">>> git fetch origin"
rc=0; git fetch origin || rc=$?
if (( rc != 0 )); then
  echo "error: 'git fetch origin' failed (exit $rc)." >&2
  exit "$rc"
fi

OLD_HEAD="$(git rev-parse HEAD)"

echo ""
echo ">>> git pull --ff-only origin main"
rc=0; git pull --ff-only origin main || rc=$?
if (( rc != 0 )); then
  echo "error: 'git pull --ff-only origin main' failed (exit $rc)." >&2
  echo "       resolve the non-fast-forward (or other) condition and retry." >&2
  exit "$rc"
fi

NEW_HEAD="$(git rev-parse HEAD)"

if [[ "$OLD_HEAD" == "$NEW_HEAD" ]]; then
  COMMITS_PULLED=0
else
  COMMITS_PULLED="$(git rev-list "$OLD_HEAD..$NEW_HEAD" --count)"
fi

# Run each selected install script. Use absolute paths; each script
# self-locates via BASH_SOURCE so cwd doesn't matter.
REFRESHED=()
for i in "${!INSTALL_CMDS[@]}"; do
  # INSTALL_CMDS entries look like "bash <adapter>/install.sh"; extract the
  # adapter dir to build an absolute path.
  entry="${INSTALL_CMDS[$i]}"
  # Strip leading "bash " and trailing "/install.sh" to recover the adapter name.
  rel="${entry#bash }"
  adapter_dir="${rel%/install.sh}"
  script_abs="$REPO_DIR/$adapter_dir/install.sh"
  display="${SELECTED_NAMES[$i]}"

  echo ""
  echo ">>> bash $script_abs"
  rc=0; bash "$script_abs" || rc=$?
  if (( rc != 0 )); then
    echo "" >&2
    echo "error: install script failed: $script_abs (exit $rc)." >&2
    if (( ${#REFRESHED[@]} > 0 )); then
      echo "       partial progress: pulled ${COMMITS_PULLED} commit(s); refreshed ${REFRESHED[*]} before failure on ${display}." >&2
    else
      echo "       partial progress: pulled ${COMMITS_PULLED} commit(s); failed on the first adapter (${display})." >&2
    fi
    echo "       re-run ./update.sh after resolving the failure." >&2
    exit "$rc"
  fi
  REFRESHED+=("$display")
done

echo ""
if (( COMMITS_PULLED == 0 )); then
  echo "Already up to date. Refreshed ${#REFRESHED[@]} adapter(s): ${REFRESHED[*]}."
else
  echo "Updated: pulled ${COMMITS_PULLED} commit(s); refreshed ${#REFRESHED[@]} adapter(s): ${REFRESHED[*]}."
fi
