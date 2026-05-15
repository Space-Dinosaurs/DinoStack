# Brief: Skill Auto-Trigger Enforcement

**Problem:** Adapters without first-class hook mechanisms (Kimi, Pi, OMP, OpenCode) do not automatically engage the `agentic-engineering` skill before the agent starts implementing, bypassing adversarial review, worktree isolation, and risk classification.

**Success criteria:**
- `skill_auto_load: true` in `~/.claude/agentic-engineering.json` causes all hook-capable adapters (Claude, Codex, Gemini, Kimi) to emit a skill-load instruction at session/turn start
- All 8 `install.sh` scripts write `skill_auto_load` to config with read-modify-write (no key destruction on re-run)
- OpenCode emits skill-load instruction on `session.created` (or first `session.idle`) when flag is true
- Pi adapter's SKILL.md begins with the auto-load preamble; Claude's SKILL.md reflects the same via rebuild

**Non-goals:**
- Tool-level blocking gate (Option C from planning doc) - repo doesn't own CLI internals
- Domain classifier / keyword-based pre-action check (Option A) - probabilistic, adds friction
- Fixing Cursor's hooks.json copy-vs-symlink update delivery problem

**Constraints:**
- `content/SKILL.md` preamble propagates only to Pi and Claude (only adapters consuming it via build); other adapters are out of scope for SKILL.md enforcement
- Unit 11 (content/SKILL.md + rebuild) must run last - `.claude/build.sh` rebuilds commands, METHODOLOGY.md, references, and SKILL.md
- `skill_auto_load` defaults to `false` (opt-in); adoption requires user re-run of install.sh

**Verification:**
- Run each `install.sh` with `--dry-run` equivalent and inspect config file for `skill_auto_load` key presence and read-modify-write idempotency
- Confirm `hooks/skill-auto-load-check.sh` emits instruction when flag=true and is silent when false
- Confirm `.kimi/hooks/session-start.sh` emits to stdout when flag=true
- Confirm `.opencode/plugins/session-context.ts` handles `session.created` (or `session.idle` guard)
- Confirm `content/SKILL.md` preamble present; `.pi/build.sh` and `.claude/build.sh` succeed; generated SKILL.md files reflect preamble

**QA criteria:**
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: >
    Shell scripts, TypeScript plugin handler, markdown content only.
    No UI surface. Observable behavior is hook stdout injection and config file writes,
    verifiable by running install scripts and inspecting file contents - no browser or
    running service required.
```

**Linked artifacts:** architect-plan: inline (3-round Skeptic review, no saved file); orchestration: orchestration.jsonl
