# ADR-0001: Use PostgreSQL in production code paths

Status: Accepted
Date: 2025-10-20

## Context

Production data must be durable across multi-writer workloads.

## Decision

Production application code must use PostgreSQL as its datastore.
SQLite remains acceptable ONLY for:

- Test fixtures (under `tests/` or `spec/` directories)
- Local CLI tooling that is not part of the deployed service

Do not introduce `import sqlite3` or similar imports under
`src/`, `app/`, or `lib/`.

## Consequences

- `psycopg2-binary` is the canonical driver.
- Connection strings in production use `postgresql://`.
