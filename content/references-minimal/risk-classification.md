# Risk Classification Quick Reference (minimal)

## Trivial

ALL hold:
- 1 file (or +colocated test/snapshot)
- no behavior/control-flow/API surface change
- no shared design tokens, theme, config, env, CI
- no downstream consumer imports the change
- reversible one-line revert
- no security/auth/permissions/billing/PII surface

Examples: typo fix, hardcoded color/padding/font in one component, user-visible copy change, renaming within a single template.

NOT trivial even if it feels small: edits to `tailwind.config.*`, theme files, CSS variables, shared tokens; 2+ file edits; auth/payments paths; renames with import-update side effects.

## Low

Single-file local behavioral edit. Examples: bug fix in one function, local handler update, single-component refactor without touching exports.

## Elevated

Anything else. Default. Worker + Skeptic required.

## Profile field (legacy)

`profile: relaxed` demotes single-file local behavioral edit to Low. `profile: default` = current behavior (Low is single-file no-behavior, Elevated otherwise). `profile: strict` = Elevated by default, no overrides.

`profile` is deprecated in favor of `tier` (`minimal|medium|full`). When both set, `tier` wins.