<!--
Purpose: Detailed code-standards reference blocks extracted from
         content/rules/code-standards.md. Contains: the verbose Per-language
         strict defaults block (TypeScript/JS, Python, Go, Rust, Next.js
         strict settings), the Browser Verification block (agent-browser
         CLI usage for all browser verification tasks), the
         Discovery-Based Check Discipline block (mandated hard-fail forms
         for any check whose result depends on a discovered set of items),
         the Context Window Management block (ctx_* MCP tool usage detail),
         and the Package Management block (dependency-versioning rules).

Public API: Read-only reference document. Cross-referenced from:
            content/rules/code-standards.md (inline pointers replacing
            these verbose blocks).

Upstream deps: content/rules/code-standards.md (parent rules file; read
               that file first for Documentation Lookups, Tool Discipline,
               Module Manifests, DRY, and Code Quality Gates preamble
               rules).

Downstream consumers: engineer agents (run per-language quality gates
                      after every implementation; consult Context Window
                      Management when ctx_* tools are present, and Package
                      Management when adding/upgrading a dependency);
                      content/sections/12-protocol-details.md (code
                      standards reference).

Failure modes: Prose + code blocks; does not auto-execute. Per-language
               defaults are pinned to the tool versions current at time
               of authoring - check tooling docs for version-specific
               changes (e.g. ESLint flat-config migration, ruff rule
               selection changes).

Performance: Standard.
-->

> Parent rules file: `content/rules/code-standards.md`. Read that file first for Documentation Lookups, Tool Discipline, Module Manifests, DRY, and Code Quality Gates rules.

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

## Context Window Management

**See `content/rules/code-standards.md` §Context Window Management for the inline output-size threshold that triggers preferring `ctx_execute`/`ctx_batch_execute` over raw `Bash`.** Raw Bash output enters the context window in full; context-mode tools sandbox execution into isolated subprocesses and only let stdout enter context - reducing context consumption by up to 98%.

Key tools and their uses:
- `ctx_execute(language, code)` - run a single script; only stdout enters context
- `ctx_execute_file(path, language, code)` - analyze a file for inspection only; use `Read` instead when you intend to subsequently `Edit` the file

> Never use `ctx_execute` or `ctx_execute_file` to create or modify files - these tools are for analysis, processing, and computation only. Use the native `Write`/`Edit` tools for all file writes.

- `ctx_batch_execute(commands, queries)` - run multiple commands and search results in one call; replaces 10-30 Bash + search steps
- `ctx_index(content, source)` / `ctx_search(queries)` - build and query a knowledge base from arbitrary content
- `ctx_fetch_and_index(url, source)` - fetch a URL, index it, cache for 24 hours

> When ctx tools are available, prefer `ctx_fetch_and_index` over `WebFetch` for URL fetches - `WebFetch` pulls full page content into context.

**Raw Bash remains appropriate per the Tool Discipline rule in `content/rules/code-standards.md`** - `git`, builds, installs, process management, and any operation that needs direct filesystem side effects.

**Platform support:** fully supported on Claude Code, Cursor, Codex CLI, OpenCode, Kimi, and oh-my-pi. The tools are available when `ctx_execute` is present as a callable tool in the session. When unavailable, fall back to the `Read`/`Glob`/`Grep` tool-discipline in `content/rules/code-standards.md`.

## Package Management

- Always install the latest stable version of packages - never pin to an older version unless the project already has an explicit constraint
- When a package is outdated and causing issues, upgrade to the latest stable version first before attempting any patches or workarounds
- Never monkey-patch or work around bugs in an outdated package version; upgrade the package instead
- When adding a new dependency, do not hardcode a version number - use the package manager's default latest resolution (e.g., `npm install pkg`, `pip install pkg`, `go get pkg@latest`)
- If a version constraint already exists in the project, respect it - do not silently downgrade, but flag it to the user if it's causing a problem
