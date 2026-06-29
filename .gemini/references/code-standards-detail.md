<!--
Purpose: Detailed code-standards reference blocks extracted from
         content/rules/code-standards.md. Contains: the verbose Per-language
         strict defaults block (TypeScript/JS, Python, Go, Rust, Next.js
         strict settings) and the Browser Verification block (agent-browser
         CLI usage for all browser verification tasks).

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
```

After editing code with a preview server running, always verify with `agent-browser` - open the relevant URL, snapshot to check structure and content, interact with key elements to confirm behavior.
