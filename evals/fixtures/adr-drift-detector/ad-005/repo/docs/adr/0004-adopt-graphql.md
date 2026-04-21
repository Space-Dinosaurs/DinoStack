# ADR-0004: Adopt GraphQL for the public API

Status: Proposed
Date: 2026-03-12

## Context

The REST API has accumulated client-specific endpoints. A single
GraphQL surface may reduce round trips and client coupling.

## Decision (proposed)

Adopt GraphQL as the primary public API. Retain REST for legacy
integrations during a 12-month deprecation window.

## Open questions

- Cost of rewriting the mobile client.
- Auth/authorization story for field-level permissions.
