<!--
Purpose: Trigger-loaded documentation lookup and tool-selection procedures,
         plus Per-Language Strict Defaults, Browser Verification,
         Discovery-Based Check Discipline, and Package Management rules.

Public API: Read-only reference document. Cross-referenced from:
            content/rules/code-standards.md (inline pointers replacing
            these verbose blocks).

Upstream deps: content/rules/code-standards.md (parent engineering contract);
               content/references/worktree-lifecycle.md (§Agent-spawned
               process lifetime ownership, cited by Browser Verification).

Downstream consumers: engineer agents (run per-language quality gates
                      after every implementation; consult Package
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

> Parent engineering contract: `content/rules/code-standards.md`.

## Documentation Lookups

Use current authoritative documentation for the relevant library version. When Context7 is available, resolve the library ID, then query its documentation (`resolve-library-id` -> `query-docs`) to verify API signatures, parameters, return types, configuration defaults, error messages, and version-specific behavior. This applies to investigators, debuggers, architects, and engineers before a consequential conclusion or implementation decision.

## Tool Discipline

Prefer suitable dedicated read, listing, and search tools when the harness exposes them. Otherwise use shell tools: `rg --files` for listing, `rg` (or `grep`) for content search, and an available file reader. Use shell commands for builds, installs, git, network calls, process management, and tasks no dedicated tool covers.

For structural symbol searches, use AST-grep (`sg`) via the shell when available; check with `command -v sg` first.

Choose the output format with the best signal for the agent consuming it. Prefer concise text or tables over verbose dumps when they convey the same information. Use a CLI over an MCP integration when it performs the task with lower token cost and latency; GitHub operations use `gh` per AGENTS.md. Benchmark cost and latency against the alternative before adopting a new tool or integration.

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
agent-browser open <url> --session <name>      # navigate
agent-browser snapshot --session <name>        # get page structure with element refs
agent-browser click @e1 --session <name>       # click by ref
agent-browser fill @e2 "text" --session <name> # fill input by ref
agent-browser close --session <name>           # close each session you opened when done
```

Use one `<name>` unique to this run on every call; without `--session` all agents share one machine-wide default session. Never run `agent-browser close --all`: it closes every concurrent agent's live session, not just yours.

After editing code with a preview server running, always verify with `agent-browser` - open the relevant URL, snapshot to check structure and content, interact with key elements to confirm behavior. `agent-browser` holds a persistent session, so always close each session you opened when verification is done (`agent-browser close --session <name>`) - otherwise the session and its browser process persist after your run ends unless DinoStack's Claude Code reaper backstop closes them. `agent-browser` is headless by default, so no window is left open; what persists is the session's live process, consuming resources and able to collide with a concurrent run (see `content/references/worktree-lifecycle.md` §Agent-spawned process lifetime ownership).

## Discovery-Based Check Discipline

A discovery-based check is one whose pass/fail result depends on a set of items it finds at run time (files matching a glob, lines matching a pattern, entries produced by a scan) rather than a fixed, hand-typed expectation. This class of check passes vacuously - and certifies a gap closed that is still open - the moment its discovery step silently returns zero items: an empty result is trivially "consistent" with almost any assertion built on top of it.

Every discovery-based check MUST hard-fail on zero discovered items, and MUST do so in one of three detectable forms. A check written in a fourth, undetectable idiom is a standards violation to be reported, not a guard silently missed:

- **Form A (shell).** The failure phrase is written to a line using `>&2`, followed by `exit 1` or an equivalent non-zero exit within a few lines.
- **Form B (python).** The failure phrase appears in a `print(..., file=sys.stderr)` call or a `sys.stderr.write(...)` call, followed by `sys.exit(1)` or `raise SystemExit` within a few lines.
- **Form C (pytest-assert).** A single `assert <non-empty-check>, "<message containing the phrase>"` statement, where the assert statement is both the phrase-carrier and the failure mechanism. This is the dominant form in this repository.

A docstring reference to a guard's failure phrase (documenting what the guard does, or citing it as precedent for a sibling check) is the only sanctioned way to mention the phrase outside an actual guard - it is classified DOCUMENTATION, not a violation and not a guard, and does not count toward a check's live-guard total. A phrase mention anywhere else that is not a docstring (a `#` comment, a non-first-statement string, ordinary prose) reports as NON-CONFORMING; this is deliberate, not an oversight, so route future mentions of a guard phrase into a docstring or an actual guard.

Reference implementations that conform: the `hooks-python-tests`, `bin-sh-tests`, `hooks-js-tests`, and `hooks-sh-tests` CI jobs, and `hooks/tests/test-hooks-pep604-guard.py`'s Form-B guards.

## Package Management

- Always install the latest stable version of packages - never pin to an older version unless the project already has an explicit constraint
- When a package is outdated and causing issues, upgrade to the latest stable version first before attempting any patches or workarounds
- Never monkey-patch or work around bugs in an outdated package version; upgrade the package instead
- When adding a new dependency, do not hardcode a version number - use the package manager's default latest resolution (e.g., `npm install pkg`, `pip install pkg`, `go get pkg@latest`)
- If a version constraint already exists in the project, respect it - do not silently downgrade, but flag it to the user if it's causing a problem
