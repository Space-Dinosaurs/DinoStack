# orders-api

agentic-engineering: opt-in

## Stack
- Node.js 20, Express 4.x, PostgreSQL 15
- Jest for tests

## Conventions
- Handlers under src/handlers/; each route gets a dedicated module.
- All inbound JSON bodies validated through the zod schemas in src/schemas/.
- Tickets use the ORD- prefix.
