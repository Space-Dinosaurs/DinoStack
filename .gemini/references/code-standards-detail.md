<!--
Purpose: Full reference for verbose per-language strict-defaults from the Code
         Quality Gates section, and the Browser Verification block. The
         per-language block covers TypeScript/JS, Python, Go, Rust, and Next.js
         strict configurations. Browser Verification covers agent-browser CLI
         usage for post-edit verification.

Public API: Read-only reference document. Cross-referenced from:
            content/rules/code-standards.md (parent rules file; pointer replaces
            these blocks after kernel split);
            content/sections/12-protocol-details.md (Protocol Details entry).

Upstream deps: content/rules/code-standards.md (parent rules file; Code Quality
               Gates intro and other rules remain there for context).

Downstream consumers: engineer agents (per-language defaults for quality gate
                      runs); qa-engineer (browser verification pattern);
                      /init-project (references tooling setup).

Failure modes: Prose + bash blocks; does not auto-execute. Language defaults
               apply to new projects; existing projects may have prior constraints
               that override some settings.

Performance: Standard.
-->

> Parent rules file: content/rules/code-standards.md §Code Quality Gates and §Browser Verification. Read that file first for the full code-quality gate rules and context.

# Code Standards Detail - Full Reference

## Per-language strict defaults

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
