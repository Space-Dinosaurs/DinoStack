# ADR-0002: Use structured logging with correlation IDs

Status: Accepted
Date: 2025-10-01

## Decision

All log lines must be emitted in JSON format via the `structlog` library.
Each log line must carry a `correlation_id` field.

## Consequences

- `structlog` appears in dependencies.
- A middleware attaches `correlation_id` to the context at request start.
