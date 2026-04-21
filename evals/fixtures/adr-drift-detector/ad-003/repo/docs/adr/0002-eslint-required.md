# ADR-0002: ESLint required in all packages

Status: Accepted
Date: 2025-09-10

## Decision

Every package must have an ESLint configuration file and `eslint`
in devDependencies. Lint must run in CI.

## Consequences

- `eslint` appears in each package's devDependencies.
- `.eslintrc.json` or equivalent is present.
