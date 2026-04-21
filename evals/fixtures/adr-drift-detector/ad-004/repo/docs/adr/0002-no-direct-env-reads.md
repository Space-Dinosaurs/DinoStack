# ADR-0002: No direct environment variable reads outside config module

Status: Accepted
Date: 2025-11-05

## Decision

All environment variable access must go through `src/config/env.py`.
Application modules may not call `os.environ` or `os.getenv` directly.

## Consequences

- A single config module is the auditable surface for env coupling.
- Tests may mock `src/config/env.py` rather than patching `os.environ`
  module-by-module.
