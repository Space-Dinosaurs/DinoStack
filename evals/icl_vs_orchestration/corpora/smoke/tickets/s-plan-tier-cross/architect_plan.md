## Architect Plan

Migrate Redis session store to Postgres sessions table.

## Rationale
Redis adds operational complexity (separate cluster, TTL management, eviction
policy). Postgres sessions table simplifies the stack: one fewer service,
transactional consistency with user records, native expiry via scheduled job.

## Changes
1. migrations/0042_session_store.sql: CREATE TABLE sessions (id, user_id,
   data jsonb, expires_at timestamptz). Add index on user_id.
2. src/session/adapter.ts: replace RedisSessionAdapter with PgSessionAdapter
   using the existing db client from src/db.ts.
3. tests/session.integration.test.ts: update tests to use PgSessionAdapter
   and the test database fixture.

## qa_criteria
qa_skip: null
scenarios:
  - id: 1
    description: Session create/read/delete roundtrip via Postgres adapter
    method: runtime-required
    evidence: integration tests pass against test DB
  - id: 2
    description: Expired sessions are not returned
    method: api
    evidence: unit test with mocked time passes
