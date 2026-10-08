@AGENTS.md
<!-- dinostack:memory-main-only -->
MEMORY.md (durable facts, operator rulings) is not auto-loaded. Main session: a DinoStack SessionStart hook delivers it; if it is absent or truncated, Read all of it before any other tool call, whatever the task. Subagents: grep on demand (`grep -n -i '<topic>' MEMORY.md`); if your worktree lacks it, grep the primary checkout's copy, never Read it (Read is denied there).
