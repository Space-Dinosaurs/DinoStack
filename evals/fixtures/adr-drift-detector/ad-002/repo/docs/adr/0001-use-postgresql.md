# ADR-0001: Use PostgreSQL for all application data

Status: Accepted
Date: 2025-09-15

## Context

We need a durable relational store for orders and users. We previously
used SQLite in prototypes, but production workloads require concurrent
writes and richer indexing.

## Decision

PostgreSQL is our primary datastore in all environments, including
production, staging, and CI. No SQLite, MySQL, or other relational
database is permitted in application code paths. Use `psycopg2` (or
`asyncpg`) as the driver.

## Consequences

- `psycopg2-binary` or `asyncpg` appears in requirements; `sqlite3`
  imports are forbidden in production source paths.
- Connection strings use `postgresql://` schemes.
