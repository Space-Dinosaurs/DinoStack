# ADR-0002: Use React for the UI layer

Status: Accepted
Date: 2025-11-10

## Decision

We will adopt React as our single UI framework. New UI code goes through
React components; no new Vue, Angular, or Svelte code will be introduced.

## Consequences

- `react` and `react-dom` appear in package.json dependencies.
- JSX/TSX is the canonical component format.
