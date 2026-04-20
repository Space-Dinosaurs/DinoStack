# it-003-server

agentic-engineering: opt-in

## Stack
- Node.js 20, TypeScript 5.4, Express 4
- Vitest

## Conventions
- Branch naming: feat/<slug>, fix/<slug>
- Keep diffs small; out-of-scope refactors are a separate ticket
- Conventional-commit prefixes

## Project config
- BASE_BRANCH: main
- QUALITY_CMD: pnpm run lint && pnpm run typecheck && pnpm test
