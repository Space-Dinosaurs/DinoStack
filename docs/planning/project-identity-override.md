# Brief: Project-level identity override

Status: approved-design, implementation in progress
Promotion tier: Brief (3 Elevated units)
Source artifacts: architect plan (2 Skeptic rounds, 3 Majors resolved), orchestration-planner unit block (below)

## Problem

The developer identity that attributes telemetry is global-only today (`~/.agentic/identity.yml`). A developer who uses one handle for most projects but a different handle for a few specific repos cannot express that - there is no per-project override. We add a project-local `<repo>/.agentic/identity.yml` that takes precedence over the global file for sessions run in that repo.

## Success criteria

1. `agentic-identity init <handle> --scope project` writes `<cwd>/.agentic/identity.yml` (gitignored); `--scope` defaults to `global`, preserving all existing behavior byte-for-byte.
2. Effective-identity resolution follows a confirmation-tier-first total ordering: **project-confirmed > global-confirmed > project-provisional > global-provisional > none**. A provisional project file never suppresses a working confirmed-global identity.
3. The same 4-tier resolution is implemented in both the Python CLI (`_resolve_effective_identity`) and the JS Stop hook (`getIdentity(cwd)`), and the two implementations agree for every populated-state combination.
4. `flushPendingBuffer` gains `repo_root_filter=None`: default preserves current behavior; when set (project-scope `init`/`confirm`), only pending records whose `repo_root` matches the current repo are attributed to the project handle - other repos' buffered sessions are left in the buffer (no cross-repo mis-attribution).
5. The Stop hook resolves identity project-first at both call sites; a confirmed project identity writes session logs directly (bypassing the pending buffer) exactly as a confirmed global identity does.
6. Regression tests prove: (A) project-scope flush leaves other-repo records untouched; (B) confirmed-global is not suppressed by provisional-project; plus positive cases (C project-confirmed beats global-confirmed, D no-`repo_root` record skipped by filter, E global flush unaffected).
7. Methodology prose (preflight, conventions, command docs) reflects the new resolution; all 8 adapters and `scripts/.methodology-baseline.sha256` are regenerated so `check-adapter-sync` and `check-drift` pass.
8. README gains an "Identity and Telemetry" section documenting global vs project registration, the precedence, the gitignored/per-developer semantics, and the `agentic-cost` attribution link - matching shipped behavior.

## Non-goals

- **Telemetry durability / sharing** (committing telemetry on PR create/update) - that is a separate plan (Track A / its own ticket), implemented in a future session. This Brief is attribution-handle resolution only.
- **Committed shared-team handle** as the default - the default is per-developer/gitignored; teams may force-add the file as a documented secondary use, but no first-class "shared handle" workflow is built here.
- **Renaming the `agentic-engineering` product / skill / config files** - out of scope.
- No new runtime dependencies; no schema change to the identity file format.

## Constraints

- 100% back-compat: absent project file + no `--scope` = current behavior, verified by tests and the `--scope global` default.
- `<repo>/.agentic/identity.yml` is covered by the existing `.agentic/*` gitignore umbrella (no carve-out added) so a developer's handle never lands in the repo by default.
- Content/`sections` edits require regenerating the methodology baseline; any `content/**` edit requires rebuilding all 8 adapters in the same change (CI gates: `check-adapter-sync`, `check-drift`). The rebuild commit must touch ONLY generated paths (adapter-rebuild revert hazard).
- Stop hook stays Node-built-ins-only (no subprocess to the CLI); the 4-tier read is two `existsSync`+`readFileSync` calls (~1ms, within budget).
- `--scope effective` is wired to the `show` subparser ONLY (structural rejection for init/confirm/auto) - Skeptic Minor from plan review.

## Verification

- Python: `bin/tests/test_agentic_identity.py` - 5 new tests (A-E above) green, plus the existing suite.
- CI gates on the content unit: `check-adapter-sync`, `check-drift`, DCO all green.
- Manual smoke (from the architect plan): init --scope project -> show --scope effective shows `scope: project`; provisional-project + confirmed-global resolves to global; two-repo pending records flush in isolation under project scope.

## QA criteria

```yaml
qa_skip: pure-backend-library
qa_skip_rationale: CLI binary + Node stop-hook + methodology prose; no browser-visible UI surface. Verified via the Python test suite, CLI invocation, and CI gates.
scenarios: []
```

## Cross-artifact alignment

Every success criterion above maps to at least one unit's `acceptance_criteria` (planner block below): SC1/SC2/SC3/SC4/SC5/SC6 -> `code-impl`; SC7 -> `content-rebuild`; SC8 -> `readme-docs`. No uncovered criterion.

## Units (orchestration-planner output)

- `code-impl` (Elevated, merge_order 1, per-unit skeptic, depends_on none): `bin/agentic-identity` + `hooks/stop-context.js` + `bin/tests/test_agentic_identity.py`.
- `content-rebuild` (Elevated, merge_order 2, per-unit skeptic, depends_on none): 6 content files + all 8 adapters + baseline regen. Prose and rebuild MUST land in one PR (adapter-sync gate).
- `readme-docs` (Elevated, merge_order 3, per-unit skeptic, depends_on code-impl): README "Identity and Telemetry" section, after code-impl merges so it documents shipped behavior.

code-impl and content-rebuild are fully independent (disjoint files, no shared interface) - Phase 1 runs them in parallel.

## Open questions

None.
