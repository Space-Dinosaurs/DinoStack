---
title: "ADR-0002: Logging and trace-id propagation"
status: "Accepted"
date: "2025-12-02"
authors: "platform-team"
tags: ["architecture", "decision"]
supersedes: ""
superseded_by: ""
---

## Status

Accepted

## Context

Stub ADR artifact describing prior state referenced by ag-002.

## Decision

Emit OpenTelemetry spans on every request and propagate `traceparent`
headers through all service hops.

## Consequences

### Positive

- **POS-001**: Unified tracing across services.

### Negative

- **NEG-001**: Small per-request CPU overhead.

## Alternatives Considered

### Bespoke trace headers

- **ALT-001**: **Description**: Internal x-trace-id scheme.
- **ALT-002**: **Rejection Reason**: Does not interop with third-party tools.

## Implementation Notes

- **IMP-001**: Wire the collector into the central ingest pipeline.

## References

- **REF-001**: OpenTelemetry specification.
