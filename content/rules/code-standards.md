## Documentation Lookups

**When investigating, diagnosing, or reasoning about library, framework, or SDK behavior, look up current documentation using Context7 before forming conclusions.** Training data may be outdated - API signatures, configuration options, default behaviors, and error messages change across versions.

Use Context7 (`resolve-library-id` -> `query-docs`) for:
- Verifying API signatures, method parameters, or return types
- Checking configuration options or default values
- Understanding error messages or behavioral changes across versions
- Any assumption about library behavior that influences a diagnosis or recommendation

Do not rely on training knowledge for library-specific details when Context7 is available. This applies to all agents: investigators, debuggers, architects, and engineers.

## Tool Discipline

**Never use Bash to read files, list directories, or search content.** Use the dedicated tools - they don't trigger permission prompts and give better output:
- Read files: `Read` tool (never `cat`, `head`, `tail`, `sed`)
- List/find files: `Glob` tool (never `ls`, `find`)
- Search content: `Grep` tool (never `grep`, `rg`)

Reserve `Bash` exclusively for: builds, installs, git operations, network calls, process management, and anything no dedicated tool covers.

## Context Window Management

**When `ctx_execute` or `ctx_batch_execute` MCP tools are available, prefer them over raw `Bash` for any operation expected to produce more than ~20 lines of output.** Raw Bash output enters the context window in full; context-mode tools sandbox execution into isolated subprocesses and only let stdout enter context - reducing context consumption by up to 98%.

Key tools and their uses:
- `ctx_execute(language, code)` - run a single script; only stdout enters context
- `ctx_execute_file(path, language, code)` - analyze a file for inspection only; use `Read` instead when you intend to subsequently `Edit` the file

> Never use `ctx_execute` or `ctx_execute_file` to create or modify files - these tools are for analysis, processing, and computation only. Use the native `Write`/`Edit` tools for all file writes.

- `ctx_batch_execute(commands, queries)` - run multiple commands and search results in one call; replaces 10-30 Bash + search steps
- `ctx_index(content, source)` / `ctx_search(queries)` - build and query a knowledge base from arbitrary content
- `ctx_fetch_and_index(url, source)` - fetch a URL, index it, cache for 24 hours

> When ctx tools are available, prefer `ctx_fetch_and_index` over `WebFetch` for URL fetches - `WebFetch` pulls full page content into context.

**Raw Bash remains appropriate per the Tool Discipline rule above** - `git`, builds, installs, process management, and any operation that needs direct filesystem side effects.

**Platform support:** fully supported on Claude Code, Cursor, Codex CLI, OpenCode, Kimi, and oh-my-pi. The tools are available when `ctx_execute` is present as a callable tool in the session. When unavailable, fall back to the `Read`/`Grep`/`Glob` discipline above.

## Module Manifests

**Non-trivial modules must carry a manifest header.** Any source file that exports a public symbol consumed by another module, is over ~50 lines of non-trivial logic, or implements a side-effecting operation (network, disk, database, external service) requires a manifest comment or docstring at the top of the file. See `content/rules/module-manifest.md` for required fields, examples, and exemptions. Skeptic flags missing or stale manifests as a Major finding.

## Code Quality Gates

**After writing or modifying code, run the project's lint, typecheck, and test commands.** All must pass with zero errors before work is complete.

- **Greenfield projects:** zero warnings from the start
- **Existing codebases:** do not introduce new warnings; flag pre-existing issues to the user
- Never suppress or disable rules to pass gates - fix the code. Suppression comments (`@ts-ignore`, `noqa`, etc.) require explicit user approval
- **New projects (via `/init-project`):** set up pre-commit hooks (husky + lint-staged for JS/TS, pre-commit framework for Python)
- **Existing projects without tooling:** run whatever checks are available and recommend setup to the user

**Per-language strict defaults:**
- **TypeScript/JS:** `strict: true` in tsconfig, ESLint `--max-warnings 0`, Vitest/Jest with 80% line coverage
- **Python:** `mypy --strict` or pyright strict mode, `ruff` with recommended + strict rule selection, `pytest --strict-markers -x`
- **Go:** `golangci-lint run --enable-all`
- **Rust:** `deny(warnings, clippy::all, clippy::pedantic)` for applications; libraries use `warn(...)` in source and `-D warnings` in CI
- **Next.js:** disable `devIndicators` in `next.config.ts`; restore `cursor: pointer` on buttons in `globals.css` (`@layer base { button, [role="button"] { cursor: pointer; } }`) - Tailwind preflight removes it

## Package Management

- Always install the latest stable version of packages - never pin to an older version unless the project already has an explicit constraint
- When a package is outdated and causing issues, upgrade to the latest stable version first before attempting any patches or workarounds
- Never monkey-patch or work around bugs in an outdated package version; upgrade the package instead
- When adding a new dependency, do not hardcode a version number - use the package manager's default latest resolution (e.g., `npm install pkg`, `pip install pkg`, `go get pkg@latest`)
- If a version constraint already exists in the project, respect it - do not silently downgrade, but flag it to the user if it's causing a problem

## Browser Verification

`agent-browser` is installed globally. Use it via Bash for all browser verification tasks instead of MCP browser tools.

```bash
agent-browser open <url>      # navigate
agent-browser snapshot        # get page structure with element refs
agent-browser click @e1       # click by ref
agent-browser fill @e2 "text" # fill input by ref
```

After editing code with a preview server running, always verify with `agent-browser` - open the relevant URL, snapshot to check structure and content, interact with key elements to confirm behavior.
