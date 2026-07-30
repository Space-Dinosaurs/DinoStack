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
               Quality Gates preamble, and Package Management rules);
               agent-browser.json (project-root config file consumed via
               --config by the Browser Verification section below - seeded
               by /ds-init-project Step 6h, supplies the
               --disable-blink-features=AutomationControlled stealth flag).

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

Every invocation carries two things, resolved once per run and reused for every call: a project-config flag that turns on bot-evasion (`$CONFIG_FLAG`), and a `--session` name that isolates this run's browser state from any concurrent run (`$SESSION`).

```bash
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
CONFIG_FLAG=()
[ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/agent-browser.json" ] && CONFIG_FLAG=(--config "$REPO_ROOT/agent-browser.json")
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" <subcommand> [args...]
```

`$CONFIG_FLAG` **must** be a bash array, never a quoted string - a quoted-string form breaks on repo paths containing a space, and naive re-quoting breaks the unseeded-project case instead. The existence guard (`[ -f "$REPO_ROOT/agent-browser.json" ]`) is required: passing `--config` unconditionally on a project with no seeded `agent-browser.json` hard-fails every call.

**Resolve `$SESSION` once per run:**
1. `$REPO_ROOT` non-empty -> `verify-<sanitize(basename "$REPO_ROOT")>`
2. `$REPO_ROOT` empty -> `verify-<epoch-seconds>-<pid>`

`sanitize(x)`: lowercase; replace characters outside `[a-z0-9-]` with `-`; collapse repeats; strip leading/trailing `-`; cap ~40 chars.

```bash
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" open <url>                # navigate
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" snapshot                  # get page structure with element refs
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" click @e1                 # click by ref
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" fill @e2 "text"           # fill input by ref
agent-browser "${CONFIG_FLAG[@]}" --session "$SESSION" close 2>/dev/null || true # scoped close - never `close --all` in automatic teardown
```

After editing code with a preview server running, always verify with `agent-browser` - open the relevant URL, snapshot to check structure and content, interact with key elements to confirm behavior. `agent-browser` holds a persistent session, so always scoped-close it when verification is done - otherwise the browser lingers open after the task. `agent-browser close --all` closes every session on the machine, including a concurrently-running sibling's - reserve it for manual, deliberate operator cleanup, never an automatic teardown path.

**Escape hatch** (to observe the raw, non-stealth fingerprint): open a fresh, never-used `--session <name>` with the config flag omitted from that session's first `open` onward, or explicitly `close` an existing session and reopen the same name without the flag. Never edit the committed `agent-browser.json` in place to toggle this - args are resolved per-session at (re)launch, so editing the file while any session (this run's or a concurrent sibling's) may be live risks a silent, destructive relaunch that destroys that session's cookies, auth state, and navigation position with no error surfaced.
