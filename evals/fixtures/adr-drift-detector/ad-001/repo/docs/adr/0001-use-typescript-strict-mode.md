# ADR-0001: Use TypeScript strict mode

Status: Accepted
Date: 2025-11-04

## Context and Problem Statement

Our frontend codebase has suffered from runtime errors that slipped past
TypeScript's default non-strict checks.

## Decision

We will enable TypeScript `strict` mode across all packages. The `strict`
flag in tsconfig.json must be set to `true`.

## Consequences

- Implicit `any` is forbidden.
- Null checks are enforced.
