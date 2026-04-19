# platform-monorepo

agentic-engineering: opt-in

## Decisions
- Monorepo uses pnpm workspaces. Each app under apps/ is independently deployable.

## Conventions
- TypeScript everywhere; no JS files in apps/.
- Each app owns its own AGENTS.md with track-specific conventions.
