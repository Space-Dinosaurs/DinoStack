---
name: ds-update
description: "Pull the latest agentic-engineering (DinoStack) release and reinstall selected adapters, or perform a fresh clone-and-install if no existing install is detected. Use this when you want to update an ex"
user-invocable: true
---
# /ds-update

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Pull the latest agentic-engineering (DinoStack) release and reinstall selected adapters, or perform a fresh clone-and-install if no existing install is detected. Use this when you want to update an existing install to the current `main`, or when setting up agentic-engineering for the first time inside a Claude Code session.

**Distinct from `/ds-update-agentic-engineering`** (shared prefix, opposite direction): `/ds-update` pulls the methodology *down* from upstream and reinstalls; `/ds-update-agentic-engineering` pushes methodology *edits up* to upstream.

**Distinct from related commands:**
- `/ds-init-project` - scaffolds a project's `AGENTS.md` hierarchy; this command installs or updates the agentic-engineering tool itself.
- `update.sh` (shell TUI) - the non-agent interactive updater; this command provides the same capability through a guided agent flow.

## Step 0 - Detect install state and route

Resolve `AE_REPO_DIR` and decide which flow to run.

```bash
AE_REPO_DIR=""
AE_CONFIG="$HOME/.agentic/agentic-engineering-config.json"
if [[ -f "$AE_CONFIG" ]]; then
  AE_REPO_DIR="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$AE_CONFIG" 2>/dev/null)"
fi
```

**Routing logic (first match wins):**

1. If `AE_REPO_DIR` is non-empty AND `git -C "$AE_REPO_DIR" rev-parse --git-dir >/dev/null 2>&1` succeeds -> **UPDATE-FLOW** against `AE_REPO_DIR`.
2. Else, check the conventional fallback `$HOME/DinoStack`: if `git -C "$HOME/DinoStack" rev-parse --git-dir >/dev/null 2>&1` succeeds, treat it as **UPDATE-FLOW** against `$HOME/DinoStack` (the config entry may be stale or missing).
3. Else -> **FRESH-CLONE-FLOW**.

Report the detected route to the user before proceeding: "Detected existing install at `<path>` - running update flow." or "No existing install found - running fresh install."

## Step 1 - Guided questions (both flows)

Ask only what is needed. Lead with what is already known from config. For each question, show the current saved value and let the user press Enter to accept it.

**Load existing config** from `~/.agentic/agentic-engineering-config.json` to pre-fill defaults:

```python3
import json, os
cfg_path = os.path.expanduser("~/.agentic/agentic-engineering-config.json")
config = {}
if os.path.exists(cfg_path):
    try:
        with open(cfg_path) as f:
            config = json.load(f)
    except Exception:
        config = {}
saved_adapters = config.get("adapters", {})
```

### 1a - Adapters

Discover available adapters by scanning the resolved repo directory (UPDATE-FLOW) or `$HOME/DinoStack` placeholder note for FRESH-CLONE-FLOW (adapters are discovered after clone; proceed with saved adapter config as the default selection and re-confirm after clone lands).

Adapter discovery logic (mirrors `update.js` exactly - use for UPDATE-FLOW; apply same logic post-clone for FRESH-CLONE-FLOW):

- Scan for dot-directories containing `install.sh`, skipping: `.`, `..`, `.git`, `.github`, `.vscode`, `.idea`, `.cache`, `.venv`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`
- `.claude` is always included (locked; cannot be deselected)
- Sort case-insensitively

Display names use the same `DISPLAY_NAMES` map as `update.js`:

```
{ claude: "Claude", codex: "Codex", cursor: "Cursor", gemini: "Gemini",
  openclaw: "OpenClaw", opencode: "OpenCode", kimi: "Kimi", omp: "Pi" }
```

For adapter names not in the map, apply the generic capitalizer: strip the leading `.`, then capitalize the first character and lowercase the rest (e.g. `.hermes` -> `Hermes`, `.pi` -> `Pi`).

If two adapters resolve to the same display name (e.g. both `.omp` and `.pi` would show as `Pi`), disambiguate by appending the raw directory name in parentheses: `Pi (.omp)` / `Pi (.pi)`.

Default each adapter to its saved state in `config.adapters[<adapter>]` (true/false). If no saved state, default to unselected (except `.claude` which is always selected).

Show the adapter list with checkboxes and current defaults. Let the user confirm or change the selection.

### 1b - Activation mode and risk profile

Ask for activation mode (`opt-in` / `opt-out`, default from saved config or `opt-out`) and risk profile (`relaxed` / `default` / `strict`, default from saved config or `default`). Show the current values if known.

### 1c - Developer identity

Run `agentic-identity show --scope effective` to check the current identity state:

- **Confirmed identity found:** "Identity: `<handle>` (confirmed). Keep or change? [Enter = keep]"
- **Provisional identity found:** "Identity: `<handle>` (provisional - not yet confirmed). Options: (c)onfirm as-is, (e)dit handle, (s)kip. [c]"
- **No identity found:** "No developer identity set. Options: (a)uto-detect from GitHub, (m)anual entry, (s)kip."
  - Auto-detect: run `gh api user --jq .login` (suppress if `gh` is not on PATH); show the detected handle and confirm.
  - Manual: prompt for handle string.
  - Skip: proceed without identity.

Resolve to either a handle (pass `--identity=<handle>` to install.sh in Step 4) or skip (pass `--no-identity`).

## Step 2 - Git preview (UPDATE-FLOW only, informational)

Skip this step for FRESH-CLONE-FLOW.

This step is read-only: it only gathers what Step 3's confirmation display needs to show. **Enforcement of the branch/dirty-tree/divergence safety checks happens inside `agentic-update` at Step 4**, not here - `agentic-update` already implements the branch check, the dirty-tree check, and fails closed on a non-fast-forward (diverged) pull. Reimplementing that enforcement in prose here would be exactly the drift this command collapsed (see PR history: four independent copies of "get the latest methodology" had already diverged before this section was rewritten to delegate).

**2a - Fetch:**
```bash
git -C "$AE_REPO_DIR" fetch origin
```
If fetch fails, stop and report the error. Network issues are surfaced verbatim.

**2b - Preview info (for the Step 3 display only):**
```bash
CURRENT_BRANCH="$(git -C "$AE_REPO_DIR" rev-parse --abbrev-ref HEAD)"
COUNTS="$(git -C "$AE_REPO_DIR" rev-list --left-right --count HEAD...origin/main)"
LOCAL_AHEAD="$(echo "$COUNTS" | awk '{print $1}')"
REMOTE_AHEAD="$(echo "$COUNTS" | awk '{print $2}')"
DIRTY="$(git -C "$AE_REPO_DIR" status --porcelain)"
```
Use these only to populate the Step 3 "Plan:" display (branch name, "clean"/"has local changes", "origin/main is N commit(s) ahead", and a note when both are ahead - "local and origin have diverged; the update will fail at Step 4 until resolved"). None of these conditions block Step 3 from being shown; `agentic-update` is the actual gate.

## Step 3 - Confirm plan

Before executing any side effects, show the user exactly what will run. Example:

```
Plan:
  Flow: UPDATE (repo: /Users/you/agentic-engineering)
  Branch: main (clean, origin/main is N commit(s) ahead)

  Commands to run:
    git -C /Users/you/DinoStack pull --ff-only origin main
    bash /Users/you/DinoStack/.claude/install.sh --mode=opt-out --profile=default --identity=yourhandle
    bash /Users/you/DinoStack/.codex/install.sh --mode=opt-out --profile=default --identity=yourhandle

  Adapters: Claude (locked), Codex
  Mode: opt-out | Profile: default | Identity: yourhandle

Proceed? [Y/n]
```

If the user enters `n` or `no`, cancel with no changes made. Any other input (including Enter) confirms and proceeds.

This explicit confirmation is what authorizes the side-effecting Step 4 as a conductor-direct action.

## Step 4 - Execute

### UPDATE-FLOW

Delegate the mechanical steps - branch/dirty-tree/divergence enforcement, the pull, the hooks-change note, and the adapter loop - to `agentic-update` in a single call rather than reimplementing them here. This is what actually collapses the drift: before this rewrite, this section duplicated `bin/agentic-update`'s branch check, dirty-tree check, pull, and per-adapter install loop line-for-line in prose, and the two copies had already started to diverge.

**4a - Detect `--identity` flag support** (before delegating, so the flag is only passed when the pulled install.sh - as of the START of this step - is known to support it; `agentic-update` re-checks this per-adapter internally as it runs each install.sh after its own pull):
```bash
INSTALL_SH="$AE_REPO_DIR/.claude/install.sh"
if grep -q -- '--identity' "$INSTALL_SH" 2>/dev/null; then
  IDENTITY_SUPPORTED=1
else
  IDENTITY_SUPPORTED=0
fi
```
If `IDENTITY_SUPPORTED=0`, skip identity flags and note: "This install.sh version does not support `--identity`. Re-run after a future update to configure identity."

**4b - Delegate to `agentic-update`:**

```bash
# ADAPTERS_CSV: comma-joined SELECTED_ADAPTERS from Step 1a.
# Only pass --identity/--no-identity when IDENTITY_SUPPORTED=1 (from 4a).
agentic-update --mode=<mode> --profile=<profile> [--identity=<handle>|--no-identity] --adapters=<ADAPTERS_CSV> --no-doctor
UPDATE_STATUS=$?
```

`--no-doctor` is passed deliberately: this command's own Step 5 runs a diagnostic-only `agentic-doctor` (no `--fix`) so findings are reported, not silently auto-applied - `agentic-update`'s built-in doctor step defaults to `--fix`, which would change that contract if left enabled here.

On non-zero `UPDATE_STATUS`: stop and show `agentic-update`'s stdout/stderr verbatim. `agentic-update` already produces actionable messages for every case this section used to check by hand: non-main branch, dirty tree (lists the dirty files), a failed or diverged (non-fast-forward) pull, and a failed adapter install (names which adapter and its exit code, fail-fast - remaining adapters do not run). It also prints the hooks-change note to stderr internally when the pull touched `hooks/`, using the same wording this section used to duplicate - that note surfaces automatically as part of the verbatim output, nothing further to do here.

If `agentic-update` is not found on PATH (e.g. this is the very first `/ds-update` run in a fresh shell before `~/.local/bin` was picked up), fall back to running the branch/dirty-tree checks, the pull, and the per-adapter install loop directly. This fallback has no other gate - `agentic-update`'s own branch and dirty-tree checks are unreachable when it isn't found - so both hard blocks below are mandatory here, not optional preview info as in Step 2b:

```bash
CURRENT_BRANCH="$(git -C "$AE_REPO_DIR" rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "error: must be on 'main' to update (currently on '$CURRENT_BRANCH'). Run: git -C $AE_REPO_DIR checkout main"
  # STOP - do not proceed
fi

DIRTY="$(git -C "$AE_REPO_DIR" status --porcelain)"
if [[ -n "$DIRTY" ]]; then
  echo "error: working tree has uncommitted changes; commit or stash first:"
  echo "$DIRTY"
  # STOP - do not proceed
fi

git -C "$AE_REPO_DIR" pull --ff-only origin main
for adapter in "${SELECTED_ADAPTERS[@]}"; do
  bash "$AE_REPO_DIR/${adapter}/install.sh" --mode=<mode> --profile=<profile> [--identity=<handle>|--no-identity]
  # On non-zero exit: stop immediately, report which adapter failed and its exit code.
done
```
A non-main branch or a dirty tree can silently fast-forward the branch into a broken state (the same reason `agentic-update` enforces both internally) - never skip these two checks on the fallback path.

Note "agentic-update not found on PATH; ran the fallback sequence directly. Open a new shell so `agentic-update` is available next time."

### FRESH-CLONE-FLOW

**4a - Determine destination:**
```bash
DEST="${AE_DEST_DIR:-$HOME/DinoStack}"
```
If `AE_DEST_DIR` is set in the environment, use it. Otherwise default to `$HOME/DinoStack`.

**4b - Clone (HTTPS with SSH fallback, same as bootstrap.sh):**

Do NOT use anonymous `curl | bash` of bootstrap.sh (fails for private repos) and do NOT use a bare `git clone` without an existing-dir check.

1. If `$DEST` already exists and is not a git repo: stop with "Directory `<DEST>` exists but is not a git repository. Move or remove it, or set `AE_DEST_DIR` to a different path."
2. If `$DEST` already exists and is a valid git repo: treat as UPDATE-FLOW against that path instead (re-route; inform the user).
3. Otherwise clone:
   ```bash
   HTTPS_URL="https://github.com/Space-Dinosaurs/DinoStack.git"
   SSH_URL="git@github.com:Space-Dinosaurs/DinoStack.git"
   if ! git clone "$HTTPS_URL" "$DEST"; then
     echo "HTTPS clone failed (repo may be private); trying SSH..."
     if ! git clone "$SSH_URL" "$DEST"; then
       echo "Both HTTPS and SSH clone failed. If the repo is private, ensure SSH access is configured."
       # STOP - report failure
     fi
   fi
   ```
   If the user provided a custom URL before this step, substitute it for `HTTPS_URL` (no SSH fallback for custom URLs unless user specifies one).

**4c - Run adapters (same loop as UPDATE-FLOW):**

After the clone lands, run the same per-adapter install loop used by UPDATE-FLOW's `agentic-update`-not-found fallback (Step 4). Do NOT use bootstrap.sh as the sole adapter installer - bootstrap.sh only wires `.claude`, so users who selected Codex/Cursor/etc. in Step 1a would never have those adapters installed. Do NOT delegate this loop to `agentic-update` either: it errors out when `repo_dir` does not yet exist rather than cloning, and even after the clone lands it would misfire - `agentic-update`'s rebuild-skip logic treats `old_head == new_head` (true immediately after a fresh clone, before any pull) as "nothing changed, skip the adapter loop", which would silently skip every adapter on a brand-new install.

bootstrap.sh may be invoked for global PATH wiring / config-dir setup if needed, but adapter installation must use the loop below:

```bash
# Detect --identity flag support from the freshly cloned install.sh
INSTALL_SH="$DEST/.claude/install.sh"
if grep -q -- '--identity' "$INSTALL_SH" 2>/dev/null; then
  IDENTITY_SUPPORTED=1
else
  IDENTITY_SUPPORTED=0
fi

# Run each selected adapter's install.sh (fail-fast)
for adapter in "${SELECTED_ADAPTERS[@]}"; do
  bash "$DEST/${adapter}/install.sh" --mode=<mode> --profile=<profile> [--identity=<handle>|--no-identity]
  # On non-zero exit: stop immediately, report which adapter failed and its exit code.
done
```

On non-zero exit from any adapter: stop immediately, report which adapter failed and its exit code. Do not run remaining adapters. Surface error messages verbatim.

## Step 5 - Install health check

After adapters are installed, run a read-only health check to surface any configuration or wiring issues:

```bash
agentic-doctor
```

`agentic-doctor` is invoked without `--fix` here - this is a diagnostic-only pass; it makes no changes. If the command is not on PATH (e.g. a fresh install before PATH is reloaded), skip this step silently and note "Health check skipped - `agentic-doctor` not found on PATH; open a new shell and run `agentic-doctor` manually."

Parse the exit code and output:

- **Exit 0 (no findings):** print `Health: OK`
- **Non-zero exit or any finding lines in output:** print `Health: N issue(s) - run agentic-doctor --fix to converge` (where N is the count of finding lines, or "1+" if the count cannot be parsed).

Print the full `agentic-doctor` output below the summary line so the user can see what was found.

## Step 6 - Persist config and report

**6a - Merged config write:**

Read the existing config, update only the keys this command owns (`repo_dir` for fresh install, `adapters`, `updatedAt`), and write back atomically (tmp + rename). Preserve ALL other keys including any the user or other tools may have written.

```python3
import json, os, sys, datetime, tempfile

# Context vars resolved during Step 4 routing (conductor-set pseudocode, not runtime literals):
#   fresh_install: bool  - True when FRESH-CLONE-FLOW was taken; False for UPDATE-FLOW
#   dest: str            - DEST from FRESH-CLONE-FLOW (AE_REPO_DIR for UPDATE-FLOW)
#   selected_adapters: list[str] - adapter directory names selected in Step 1a

cfg_path = os.path.expanduser("~/.agentic/agentic-engineering-config.json")
os.makedirs(os.path.dirname(cfg_path), exist_ok=True)

# Read existing config (preserves unknown keys)
data = {}
if os.path.exists(cfg_path):
    try:
        with open(cfg_path) as f:
            data = json.load(f)
    except Exception:
        data = {}

# Update only the keys this command owns
if fresh_install:
    data["repo_dir"] = dest  # DEST from FRESH-CLONE-FLOW
# Always update adapters and timestamp
data["adapters"] = {adapter: True for adapter in selected_adapters}
data["updatedAt"] = datetime.datetime.utcnow().isoformat() + "Z"

# Atomic write (tmp + rename)
dir_ = os.path.dirname(cfg_path)
with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tf:
    json.dump(data, tf, indent=2)
    tf.write("\n")
    tmp_path = tf.name
os.replace(tmp_path, cfg_path)
```

If the config write fails, warn the user (non-fatal) and continue.

**6b - Summary report:**

```
Done.

  Flow: UPDATE | FRESH INSTALL
  Repo: /path/to/DinoStack
  Commits pulled: N  (or "already up to date" / "fresh install")
  Adapters installed: Claude, Codex
  Mode: opt-out | Profile: default | Identity: yourhandle (confirmed)
  Health: OK  (or "N issue(s) - run agentic-doctor --fix to converge")

Next steps:
  - Run /ds-status to verify the install is active in this project.
  - Run agentic-identity show to confirm your developer identity.
  - Open a new shell if adapters added shell integrations.
```
