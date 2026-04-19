# Findings

## Deploy step missing package sync (2026-03-22)

**Context:** release pipeline for `apps/web` shipped a build without running `pnpm install --frozen-lockfile` after a lockfile bump. Missing transitive dependency surfaced at runtime in prod.

**Pattern:** any deploy workflow that skips the lockfile-install gate risks shipping a stale `node_modules` snapshot.

**Instances observed:** 1 (this session).

## Migration rollback not tested before merge (2026-04-02)

**Context:** migration `0047_add_order_status.sql` was merged after forward-apply tested, but the `down.sql` path errored on a foreign-key constraint. Caught in staging, not prod.

**Pattern:** migrations without round-trip (up + down) tests pass local checks but break rollback paths.

**Instances observed:** 1 (this session).
