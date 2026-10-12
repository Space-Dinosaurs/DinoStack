@AGENTS.md
<!-- dinostack:memory-main-only -->
MEMORY.md (durable facts, operator rulings) is not auto-loaded. Main session: a DinoStack SessionStart hook delivers it whole, or its head plus a directive for the rest - follow that directive; if neither is in context, grep on demand and Read only bounded windows around hits, never the whole file at once. Subagents: grep on demand (`grep -n -i '<topic>' MEMORY.md`); if your worktree lacks it, grep the primary checkout's copy, never Read it (Read is denied there).
