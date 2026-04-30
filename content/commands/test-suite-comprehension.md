# /test-suite-comprehension

> Run the Activation preflight from `agent-methodology.md` before proceeding. If inactive, no-op and exit.

Map a project's test suite against its source files and surface where verification gaps live. Returns a coverage summary, a gap report ranked by risk, and the specific test files that are highest-leverage places to add coverage.

This command is analysis only. It does not modify tests, source files, or CI. It returns a structured report the user can act on.

## When to use

- "Find coverage gaps in this codebase."
- "What's untested here?"
- "Where should I add tests next?"
- "Review the test suite for verification gaps."
- Before opening a PR that adds substantial new logic, to confirm the verification surface caught up with the implementation surface.
- Pairs with the QA gate (post-Skeptic UI verification) and `qa-engineer`. This command targets the unit / integration test layer; QA gate targets browser-level behavior.

## Motivation

As code generation becomes cheap, the bottleneck shifts to verification. Large test suites become hard to comprehend - tests accumulate, organization drifts, and gaps form silently. This command is a comprehension tool: it tells you what the suite actually covers and where the holes are, so you can decide where to invest test effort rather than guessing.

## What it does

Produces a single Markdown report containing:

1. **Coverage summary** - language and test framework detected, total source files, total test files, line/branch coverage if a coverage tool is available.
2. **Gap report** - ranked list of source modules with weak or absent coverage, each entry annotated with:
   - The module's purpose (pulled from its module manifest if present).
   - Why the gap matters (blast radius, side effects, intent-layer signals).
   - The risk classification (High / Medium / Low) of leaving it uncovered.
3. **Recommended additions** - 3 to 10 specific test files where adding cases would close the highest-leverage gaps, with one-sentence rationale per recommendation.
4. **Suite hygiene observations** - any structural issues worth knowing: dead tests, duplicate coverage, tests that exercise nothing meaningful, fixture sprawl, slow-test outliers.

The report is written to `docs/planning/test-suite-comprehension-YYYY-MM-DD.md`. Nothing else is changed.

## Instructions

### Step 0 - Activation preflight

Run the Activation preflight from `agent-methodology.md`. If inactive, no-op and exit.

### Step 1 - Detect language and test framework

Inspect the project root and the most representative track (or all tracks for a monorepo). Identify:

- Primary language(s) - infer from `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, etc.
- Test framework - Vitest, Jest, Mocha, pytest, unittest, Go's `testing`, Rust's `cargo test`, etc.
- Test discovery pattern - file globs, naming conventions, directory layout.
- Coverage tool, if configured - `c8`, `vitest --coverage`, `coverage.py`, `go test -cover`, `tarpaulin`, etc.

Skip detection for harnesses already documented in `AGENTS.md` or `qa.md`.

### Step 2 - Run coverage if available

If a coverage tool is configured and runnable in the project's normal way, run it and capture the report. Do NOT modify CI config or install new tools - if coverage is not configured, note that in the report and proceed without it (the gap analysis still works using static cross-referencing).

### Step 3 - Build the source / test cross-reference

For each non-trivial source module (per the criteria in `module-manifest.md`):

- Find any test files that import or reference the module by name.
- Pull the module's manifest header if present - `Purpose`, `Public API`, `Failure modes`, and `Downstream consumers` are the inputs that drive risk ranking.
- Note any side-effecting operations declared in the manifest (network, disk, DB, external service) - these elevate the risk of leaving the module uncovered.

For each test file:

- Identify the module(s) it primarily exercises.
- Note tests that exercise nothing concrete (smoke tests with no assertions, snapshot-only tests on stable output, tests that mock the entire module under test).

### Step 4 - Rank gaps by risk

Score each uncovered or weakly-covered module against:

- **Blast radius** - downstream consumers count from manifest; modules with many consumers rank higher.
- **Side effects** - manifest-declared I/O, mutation, or external calls rank higher than pure functions.
- **Public surface** - exported symbols rank higher than internal helpers.
- **Recent change activity** - modules modified in the last 30 days that gained no test changes rank higher.
- **Failure mode severity** - manifest-declared failure modes that mention data loss, security, or silent corruption rank highest.

Classify as High / Medium / Low risk for leaving uncovered.

### Step 5 - Write the report

Write to `docs/planning/test-suite-comprehension-YYYY-MM-DD.md` with the structure declared above. Sort the gap report by risk descending. The Recommended additions section must be specific - name file paths and the kind of case to add ("add a malformed-input case to `src/parsers/webhook.test.ts` exercising the missing oversized-payload branch"), not generic advice ("add more tests").

### Step 6 - Print a one-paragraph debrief

After writing the report, print 3-5 sentences naming the report path, the count of High-risk gaps, and the single highest-leverage recommendation. Do not rehash the report.

## Examples

**Trigger phrases that should invoke this command:**

- "Find coverage gaps in the backend track."
- "What parts of the migration code are untested?"
- "Review the test suite before I open the PR."
- "Where would adding 3 tests give us the most safety?"

**Out of scope:**

- Writing the actual test cases - that is a separate Engineer task once the report identifies the targets.
- Modifying CI configuration to add coverage tooling - propose it in the report; the user decides.
- Browser-level QA verification - that is `qa-engineer` and the QA gate.
