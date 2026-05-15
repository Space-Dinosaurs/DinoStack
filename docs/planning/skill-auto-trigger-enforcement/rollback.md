# Rollback

**Trigger:** See verification-gate.md for signals that indicate rollback is needed.

**Procedure:**

1. Revert the PR: `gh pr close <number>` or `git revert` the merge commit on main.
2. For config files already written to user machines by re-run of install.sh: manually remove `skill_auto_load` key from `~/.claude/agentic-engineering.json` (and `~/.config/opencode/agentic-engineering.json` for OpenCode users).
3. For `.codex/config/hooks.json` (symlinked): reverting the repo file immediately removes the hook for all installed users.
4. For `.claude/settings.json` (written by install.sh): re-run install.sh from the reverted commit to restore the prior hook configuration.
5. For `content/SKILL.md` preamble: revert removes it from repo; re-run `.pi/build.sh` and `.claude/build.sh` to regenerate derived SKILL.md files.

**Partial rollback:** If only Unit 11 needs rollback (preamble causes issues), revert `content/SKILL.md` and rebuild. Units 1-8 are independent and can remain.
