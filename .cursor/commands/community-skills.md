# /community-skills - Browse and manage community skills

Use this command to list, install, or uninstall community skills from the agentic-engineering repo without re-running the installer.

Community skills live in `$REPO_DIR/community-skills/` (where `$REPO_DIR` is the location of the cloned agentic-engineering repository, typically `~/agentic-engineering`). Each is a self-contained skill directory with its own `SKILL.md` and `README.md`. Installing a community skill means creating a symlink at `~/.claude/skills/<name>` pointing to the skill directory.

**Note:** Community skills are a Claude Code feature. If you are using a different tool adapter (e.g. Cursor), this command does not apply.

## Subcommands

### `/community-skills list`

List all community skills available in the repo, with their description and install status (installed / not installed).

Steps:
1. Locate the agentic-engineering repo. Check `~/agentic-engineering` first; if the user's checkout is elsewhere, they should provide the path.
2. For each immediate subdirectory in `community-skills/` (excluding `_template` and anything without a `SKILL.md`):
   - Parse the `description` field from SKILL.md YAML frontmatter (fallback: first non-heading non-blank line).
   - Check whether `~/.claude/skills/<name>` exists as a symlink pointing at `community-skills/<name>`.
3. Print a table: name, description (truncated to ~80 chars), status.

### `/community-skills install <name>`

Install a named community skill by symlinking it into `~/.claude/skills/`.

Steps:
1. Verify `$REPO_DIR/community-skills/<name>/SKILL.md` exists. If not, report "skill not found" and stop.
2. Check the destination `~/.claude/skills/<name>`:
   - If it is a symlink pointing at the expected source: report "already installed", stop.
   - If it is a symlink pointing elsewhere: report "points to <other> - refusing to overwrite", stop.
   - If it is a real file or directory: report "real file/directory exists at destination - refusing to overwrite", stop.
3. Otherwise, create the symlink: `ln -s $REPO_DIR/community-skills/<name> ~/.claude/skills/<name>`.
4. Report success: "installed <name> -> <target>".

### `/community-skills uninstall <name>`

Remove a community skill symlink. Only removes if the destination is a symlink pointing at a community skill within the agentic-engineering repo.

Steps:
1. Check `~/.claude/skills/<name>`:
   - If it does not exist: report "not installed", stop.
   - If it is a real file or directory (not a symlink): report "real file/directory at destination - refusing to remove", stop.
   - If it is a symlink whose target is not under `$REPO_DIR/community-skills/`: report "symlink points elsewhere - refusing to remove", stop.
2. Otherwise, remove the symlink.
3. Report success: "uninstalled <name>".

### `/community-skills installed`

List only the community skills currently installed (symlinks in `~/.claude/skills/` whose targets are under `$REPO_DIR/community-skills/`).

## Notes for the agent

- The agent should inspect the repo and filesystem directly using Bash/Read tools rather than asking the user for paths that can be discovered.
- When listing, use a simple aligned text table. Do not use fancy formatting.
- This is a Low-risk command (reading filesystem, creating symlinks) - does not require Worker/Skeptic spawning.
