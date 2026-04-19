# checkout-monorepo

agentic-engineering: opt-in

## Decisions
- Monorepo split into apps/web (Next.js) and apps/api (Fastify).
- Shared types live in packages/shared-types; both apps import from there.

## Conventions
- One AGENTS.md per app with track-specific conventions.
- Tickets use the CHK- prefix.
