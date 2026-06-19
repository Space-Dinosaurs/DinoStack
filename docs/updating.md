# Updating

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
