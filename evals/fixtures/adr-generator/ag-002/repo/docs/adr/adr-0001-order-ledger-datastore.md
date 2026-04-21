---
title: "ADR-0001: Order-ledger datastore selection"
status: "Accepted"
date: "2025-11-01"
authors: "platform-team"
tags: ["architecture", "decision"]
supersedes: ""
superseded_by: ""
---

## Status

Accepted

## Context

Stub ADR included as a fixture artifact to illustrate the seeded prior
state that the adr-generator would read if it had filesystem access at
eval time. Under Tier 1 isolation the agent receives this information
via the prompt's `existing_adrs` block, not by reading this file.

## Decision

Adopt PostgreSQL on RDS.

## Consequences

### Positive

- **POS-001**: Strong transactional guarantees.

### Negative

- **NEG-001**: Vertical scaling ceiling on the writer.

## Alternatives Considered

### DynamoDB

- **ALT-001**: **Description**: Managed NoSQL.
- **ALT-002**: **Rejection Reason**: Weaker cross-item transactions.

## Implementation Notes

- **IMP-001**: Provision primary + two read replicas.

## References

- **REF-001**: RDS documentation.
