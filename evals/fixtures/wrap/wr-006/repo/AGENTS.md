# payments-core

agentic-engineering: opt-in

## Stack
- Node.js 20, TypeScript 5.4
- Jest for tests; pg for Postgres

## Conventions
- Handlers live under src/handlers/.
- Database migrations live under db/migrations/ and run forward-only in prod.
- All money amounts use integer minor-units; never floats.
