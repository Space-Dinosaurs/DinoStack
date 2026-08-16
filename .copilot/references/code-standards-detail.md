<!--
Purpose: Detailed code-standards reference blocks extracted from
         content/rules/code-standards.md. Contains: the verbose Per-language
         strict defaults block (TypeScript/JS, Python, Go, Rust, Next.js
         strict settings), the Browser Verification block (agent-browser
         CLI usage for all browser verification tasks), and the
         Discovery-Based Check Discipline block (mandated hard-fail forms
         for any check whose result depends on a discovered set of items).

Public API: Read-only reference document. Cross-referenced from:
            content/rules/code-standards.md (inline pointers replacing
            these verbose blocks).

Upstream deps: content/rules/code-standards.md (parent rules file; read
               that file first for Documentation Lookups, Tool Discipline,
               Context Window Management, Module Manifests, DRY, Code
               Quality Gates preamble, and Package Management rules).

Downstream consumers: engineer agents (run per-language quality gates
                      after every implementation); content/sections/
                      12-protocol-details.md (code standards reference).

Failure modes: Prose + code blocks; does not auto-execute. Per-language
               defaults are pinned to the tool versions current at time
               of authoring - check tooling docs for version-specific
               changes (e.g. ESLint flat-config migration, ruff rule
               selection changes).

Performance: Standard.
-->

> Parent rules file: `content/rules/code-standards.md`. Read that file first for Documentation Lookups, Tool Discipline, Context Window Management, Module Manifests, DRY, and Package Management rules.

## Per-Language Strict Defaults

**Per-language strict defaults:**
- **TypeScript/JS:** `strict: true` in tsconfig, ESLint `--max-warnings 0`, Vitest/Jest with 80% line coverage
- **Python:** `mypy --strict` or pyright strict mode, `ruff` with recommended + strict rule selection, `pytest --strict-markers -x`
- **Go:** `golangci-lint run --enable-all`
- **Rust:** `deny(warnings, clippy::all, clippy::pedantic)` for applications; libraries use `warn(...)` in source and `-D warnings` in CI
- **Next.js:** disable `devIndicators` in `next.config.ts`; restore `cursor: pointer` on buttons in `globals.css` (`@layer base { button, [role="button"] { cursor: pointer; } }`) - Tailwind preflight removes it

## Browser Verification

`agent-browser` is installed globally. Use it via Bash for all browser verification tasks instead of MCP browser tools.

```bash
agent-browser open <url>      # navigate
agent-browser snapshot        # get page structure with element refs
agent-browser click @e1       # click by ref
agent-browser fill @e2 "text" # fill input by ref
agent-browser close           # close the session when done (close --all closes every session)
```

After editing code with a preview server running, always verify with `agent-browser` - open the relevant URL, snapshot to check structure and content, interact with key elements to confirm behavior. `agent-browser` holds a persistent session, so always close it when verification is done (`agent-browser close`, or `close --all` to close every session) - otherwise the browser lingers open after the task.

## Discovery-Based Check Discipline

A discovery-based check is one whose pass/fail result depends on a set of items it finds at run time (files matching a glob, lines matching a pattern, entries produced by a scan) rather than a fixed, hand-typed expectation. This class of check passes vacuously - and certifies a gap closed that is still open - the moment its discovery step silently returns zero items: an empty result is trivially "consistent" with almost any assertion built on top of it.

Every discovery-based check MUST hard-fail on zero discovered items, and MUST do so in one of three detectable forms. A check written in a fourth, undetectable idiom is a standards violation to be reported, not a guard silently missed:

- **Form A (shell).** The failure phrase is written to a line using `>&2`, followed by `exit 1` or an equivalent non-zero exit within a few lines.
- **Form B (python).** The failure phrase appears in a `print(..., file=sys.stderr)` call or a `sys.stderr.write(...)` call, followed by `sys.exit(1)` or `raise SystemExit` within a few lines.
- **Form C (pytest-assert).** A single `assert <non-empty-check>, "<message containing the phrase>"` statement, where the assert statement is both the phrase-carrier and the failure mechanism. This is the dominant form in this repository.

A docstring reference to a guard's failure phrase (documenting what the guard does, or citing it as precedent for a sibling check) is the only sanctioned way to mention the phrase outside an actual guard - it is classified DOCUMENTATION, not a violation and not a guard, and does not count toward a check's live-guard total. A phrase mention anywhere else that is not a docstring (a `#` comment, a non-first-statement string, ordinary prose) reports as NON-CONFORMING; this is deliberate, not an oversight, so route future mentions of a guard phrase into a docstring or an actual guard.

Reference implementations that conform: the `hooks-python-tests`, `bin-sh-tests`, `hooks-js-tests`, and `hooks-sh-tests` CI jobs, and `hooks/tests/test-hooks-pep604-guard.py`'s Form-B guards.
