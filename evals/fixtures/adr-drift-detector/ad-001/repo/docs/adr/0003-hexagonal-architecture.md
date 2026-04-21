# ADR-0003: Hexagonal architecture (ports and adapters)

Status: Accepted
Date: 2025-12-02

## Decision

We will structure the service as a hexagonal (ports-and-adapters)
architecture. The repository must contain top-level directories named
`domain/`, `ports/`, and `adapters/` under `src/`.

## Consequences

- Business logic lives in `src/domain/` with no framework imports.
- I/O (HTTP, database, queues) is implemented as adapters behind ports.
