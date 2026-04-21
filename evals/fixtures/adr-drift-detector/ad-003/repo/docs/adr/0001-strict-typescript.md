# ADR-0001: Strict TypeScript compiler settings

Status: Accepted
Date: 2025-08-20

## Decision

The tsconfig.json for every package must set:

- `"strict": true`
- `"noImplicitAny": true`
- `"strictNullChecks": true`

No package-level override is permitted to weaken these settings.

## Consequences

- CI fails if any tsconfig.json narrows these fields.
