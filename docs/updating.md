# Updating

## Quick update (recommended)

Run `agentic-update` from any directory, no arguments.

What it does: pulls the latest `main`, rebuilds adapters only if something changed under `content/`, `hooks/`, `bin/`, or the build scripts, resets the version-check cache, and runs `agentic-doctor --fix` to repair drifted symlinks or hooks. No TTY required.

Flags:

- `--check` - report how many commits behind you are without pulling
- `--no-doctor` - skip the `agentic-doctor --fix` repair step
- `--adapters=cursor,codex` - rebuild only the specified adapters

First time? `agentic-update` installs itself to `~/.local/bin/` on your next `./update.sh` or `/pull-and-install` run; after that it works from anywhere.

## TUI updater (`./update.sh`)

Run `./update.sh` for an interactive update. It pulls the latest `main` branch and refreshes selected adapters. Uses a native Node.js TUI - arrow keys to navigate, space to toggle adapters, enter to confirm. The `.claude` adapter is always-on (locked, non-toggleable); the TUI is for selecting ADDITIONAL adapters to refresh. Your selections are saved to `~/.agentic/agentic-engineering-config.json` for future runs. Warnings are shown (but non-blocking) if you're not on `main` or have a dirty working tree. Failed adapter installs are reported at the end without aborting the others.

## Non-interactive / CI (`./install-all.sh`)

`./install-all.sh` is the non-interactive counterpart to the `./update.sh` TUI. It discovers every adapter (`.claude` first) and runs each adapter's `install.sh` in one shot - no terminal/TTY required, so it works in scripts and CI. It does not pull from git; run `git pull` first if you want the latest `main`. Activation flags are forwarded verbatim to each adapter, and installs continue on error: any failures are listed in a final summary and the script exits non-zero if at least one adapter failed.

```
./install-all.sh --mode=opt-out --profile=default --identity=<handle>
```

## Manual update

```bash
cd ~/DinoStack
git pull
bash .claude/install.sh    # and/or .cursor/install.sh, .opencode/install.sh
```

## Clean manual refresh (prunes stale symlinks)

```bash
bash .claude/uninstall.sh
git pull
bash .claude/install.sh
```

## Health check and repair (`agentic-doctor`)

`agentic-doctor` is a read-only health inspector that verifies your install is wired correctly. Run it any time symlinks feel broken, hooks aren't firing, or you've moved the repo to a new path.

```bash
agentic-doctor          # read-only scan; exit 0 = healthy, 1 = findings
agentic-doctor --fix    # re-point drifted symlinks and repair hook paths; exit 0 = all fixed, 2 = some unfixable
agentic-doctor --dry-run  # same as the default scan - enumerate findings without changing anything
```

What it checks:

- `repo_dir` in `~/.agentic/agentic-engineering-config.json` points to a valid git repo
- Every managed symlink under `~/.claude/agents/`, `~/.claude/commands/`, and `~/.claude/skills/agentic-engineering/` resolves into `repo_dir`
- Every hook command path in `~/.claude/settings.json` points into `repo_dir`
- `~/.local/bin/agentic-*` wrappers exist and point into `repo_dir/bin/`
- The git pre-commit hook at `<repo_dir>/.git/hooks/pre-commit` is linked to the managed hook

Real files (not symlinks) and symlinks pointing outside any DinoStack repo are skipped rather than flagged.

`--fix` repairs only links and paths that belong to DinoStack. It never runs `install.sh` or rebuilds adapters. Reach for it after moving the repo or if a partial install left something dangling.

## Safeguards

**Split-brain guard:** bootstrap detects an existing valid install before cloning. If `~/.agentic/agentic-engineering-config.json` already records a live DinoStack git repo at a different path, bootstrap aborts without cloning and prints an update-in-place message like:

```
To update in place: AE_DEST_DIR=<existing> <bootstrap.sh>, or run <existing>/update.sh.
```

The exact message echoes how you invoked bootstrap (the `<bootstrap.sh>` token is whatever you actually ran).

This prevents two clones from diverging while adapters and config point at the wrong one.

**Self-heal on reinstall:** re-running an adapter installer (e.g. `bash .claude/install.sh`) repairs drifted symlinks and stale hook paths instead of clobbering your config. `repo_dir` is updated when stale and never clobbered when it already points at another valid clone, so moving the repo and reinstalling is safe.

**Fast-path on `update.sh`:** `./update.sh` skips the adapter rebuild step when no adapter source has changed since the last pull, so routine updates complete faster.

## Agent-driven update

Ask your coding agent:

```
Pull the latest changes to DinoStack and re-run the installer
```

The agent handles the git pull and runs the installer. It's idempotent - existing symlinks and settings are preserved, new ones are added, and build artifacts are regenerated.

For a clean refresh that also prunes stale symlinks for files removed upstream, ask:

```
Do a clean refresh of DinoStack - uninstall, pull, then reinstall
```
