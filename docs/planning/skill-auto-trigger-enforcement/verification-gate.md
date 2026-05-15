# Verification Gate

**Tests that must pass:**
- Unit: n/a (shell scripts; no unit test framework)
- Integration: manually run each install.sh, inspect config for `skill_auto_load` key; run `skill-auto-load-check.sh` with flag true/false and confirm stdout behavior
- E2E: n/a (no running service)

**qa-engineer triggered?** No. `qa_skip: pure-backend-library` - all changes are shell scripts, TypeScript plugin, and markdown. No UI to verify in a browser.

**Manual smoke check:**
1. Set `skill_auto_load: true` in `~/.claude/agentic-engineering.json`
2. Run `bash hooks/skill-auto-load-check.sh` - confirm skill-load instruction appears on stdout
3. Re-run any install.sh - confirm `skill_auto_load` key is preserved (not reset to false)
4. Start a Kimi session with the flag set - confirm skill-load instruction appears before first response
5. Confirm `content/SKILL.md` begins with auto-load preamble; confirm `.pi/build.sh` and `.claude/build.sh` complete without error
6. Inspect `.opencode/plugins/session-context.ts` for `session.created` (or `session.idle` guard) handler branch
7. Inspect `.codex/config/hooks.json` for second `UserPromptSubmit` entry calling `skill-auto-load-check.sh`

**Rollback signal:** Any of: (a) install.sh destroys existing config keys on re-run; (b) Kimi hook emits to wrong channel causing session errors; (c) `.claude/build.sh` in Unit 11 clobbers commands or METHODOLOGY.md with stale content; (d) OpenCode plugin crashes on unrecognized event type.

**New regression tests required by findings flywheel?** No - no `.agentic/findings.md` entries exist for this task.
