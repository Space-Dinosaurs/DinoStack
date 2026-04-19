# api

## Stack
- Fastify 4, Node.js 20, TypeScript 5.4
- Postgres via pg; jest for tests

## Key Conventions
- Routes under src/routes/; each file mounts a single plugin.
- DB queries go through src/db.ts; no inline SQL in route handlers.
