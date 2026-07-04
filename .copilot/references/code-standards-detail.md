<!--
Purpose: Detailed code-standards reference blocks extracted from
         content/rules/code-standards.md. Contains: the Tool Selection
         elaboration (ripgrep raw-speed tip, agent-ergonomic tool-selection
         rationale and benchmark numbers), the Context Window Management
         (ctx_* tools) full tool list and platform-support detail, the
         verbose Per-language strict defaults block (TypeScript/JS, Python,
         Go, Rust, Next.js strict settings), and the Browser Verification
         block (agent-browser CLI usage for all browser verification
         tasks).

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

## Tool Selection

**Optional raw-speed tip:** the `Grep` tool already uses Claude Code's bundled ripgrep (`@vscode/ripgrep`, present since v1.0.84) - no install needed for correctness. For faster raw `rg` in Bash on large trees, install system ripgrep (`brew install ripgrep`) and set `USE_BUILTIN_RIPGREP=0` to swap the bundled binary for the system one. This is a performance-only setup choice; the methodology does not require it.

**Agent-ergonomic tool selection**

When choosing between tool options for the same job, prefer the option that minimizes token cost and latency for agent consumers:

- **Prefer token-efficient output.** Text and tabular tool output is cheaper for models to consume than JSON dumps with identical semantic content. When a tool offers multiple output formats, pick the one that gives the model the signal it needs with the least surrounding structure.
- **Prefer CLI over MCP server when the CLI is cheaper.** An MCP server adds a protocol layer that inflates token cost and latency with no functional gain when a CLI covers the same job. Concrete reference: the GitHub MCP server costs approximately 3x the tokens and 2x the latency of the `gh` CLI for the same GitHub operations. AE uses `gh` for all GitHub operations (see AGENTS.md) - this is the principle in action.
- **Measure before adopting.** Do not assume a new tool or MCP server is cost-neutral. Before integrating either, benchmark its token/latency profile against the alternative. The `ctx_*` context-mode tools earn their place because their token reduction is measured (~98% context savings versus raw Bash output) - not assumed.

These rules complement the existing tool hierarchy above (Read/Glob/Grep over Bash) and the Context Window Management rules below (`ctx_*` over raw Bash for large output). Together they form AE's tool-selection standard: reach for the tool whose output-to-signal ratio is best for the model reading it.

## Context Window Management (ctx_* tools)

Key tools and their uses:
- `ctx_execute(language, code)` - run a single script; only stdout enters context
- `ctx_execute_file(path, language, code)` - analyze a file for inspection only; use `Read` instead when you intend to subsequently `Edit` the file
- `ctx_batch_execute(commands, queries)` - run multiple commands and search results in one call; replaces 10-30 Bash + search steps
- `ctx_index(content, source)` / `ctx_search(queries)` - build and query a knowledge base from arbitrary content
- `ctx_fetch_and_index(url, source)` - fetch a URL, index it, cache for 24 hours

> When ctx tools are available, prefer `ctx_fetch_and_index` over `WebFetch` for URL fetches - `WebFetch` pulls full page content into context.

**Raw Bash remains appropriate per the Tool Discipline rule in the parent file** - `git`, builds, installs, process management, and any operation that needs direct filesystem side effects.

**Platform support:** fully supported on Claude Code, Cursor, Codex CLI, OpenCode, Kimi, and oh-my-pi. The tools are available when `ctx_execute` is present as a callable tool in the session. When unavailable, fall back to the `Read`/`Glob`/`Grep` tool-discipline in the parent file.

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
