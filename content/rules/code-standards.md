## Documentation Lookups

**When investigating, diagnosing, or reasoning about library, framework, or SDK behavior, look up current documentation using Context7 before forming conclusions.** Training data may be outdated - API signatures, configuration options, default behaviors, and error messages change across versions.

Use Context7 (`resolve-library-id` -> `query-docs`) for:
- Verifying API signatures, method parameters, or return types
- Checking configuration options or default values
- Understanding error messages or behavioral changes across versions
- Any assumption about library behavior that influences a diagnosis or recommendation

Do not rely on training knowledge for library-specific details when Context7 is available. This applies to all agents: investigators, debuggers, architects, and engineers.

## Tool Discipline

**Prefer the dedicated tools for reads, listing, and search when they are available; use Bash as the sanctioned fallback when they are not.** `Read` is always present and is the primary tool for reading file contents - always prefer it over `cat`/`head`/`tail`/`sed`. For listing and searching, prefer `Glob` and `Grep` when the harness exposes them - they avoid permission prompts and give cleaner output:
- Read files: `Read` tool (always available; never `cat`, `head`, `tail`, `sed`).
- List/find files: `Glob` tool when available; otherwise Bash `find` (or `rg --files`).
- Search content: `Grep` tool when available; otherwise Bash `rg` (preferred) or `grep`.

Reserve `Bash` for: builds, installs, git operations, network calls, process management, listing/searching when `Glob`/`Grep` are unavailable, and anything no dedicated tool covers.

`sg` (AST-grep) for structural symbol-level searches is always run via Bash - no dedicated harness tool wraps it. This is independent of the `Glob`/`Grep` availability question above: Bash-based search is sanctioned generally (via `rg`/`grep`/`find`), and `sg` is the specific tool for structural AST queries. Check availability with `which sg 2>/dev/null` before use.

**Optional raw-speed tip:** the `Grep` tool already uses Claude Code's bundled ripgrep (`@vscode/ripgrep`, present since v1.0.84) - no install needed for correctness. For faster raw `rg` in Bash on large trees, install system ripgrep (`brew install ripgrep`) and set `USE_BUILTIN_RIPGREP=0` to swap the bundled binary for the system one. This is a performance-only setup choice; the methodology does not require it.

**Agent-ergonomic tool selection**

When choosing between tool options for the same job, prefer the option that minimizes token cost and latency for agent consumers:

- **Prefer token-efficient output.** Text and tabular tool output is cheaper for models to consume than JSON dumps with identical semantic content. When a tool offers multiple output formats, pick the one that gives the model the signal it needs with the least surrounding structure.
- **Prefer CLI over MCP server when the CLI is cheaper.** An MCP server adds a protocol layer that inflates token cost and latency with no functional gain when a CLI covers the same job. Concrete reference: the GitHub MCP server costs approximately 3x the tokens and 2x the latency of the `gh` CLI for the same GitHub operations. AE uses `gh` for all GitHub operations (see AGENTS.md) - this is the principle in action.
- **Measure before adopting.** Do not assume a new tool or MCP server is cost-neutral. Before integrating either, benchmark its token/latency profile against the alternative. The `ctx_*` context-mode tools earn their place because their token reduction is measured (~98% context savings versus raw Bash output) - not assumed.

These rules complement the existing tool hierarchy above (Read/Glob/Grep over Bash) and the Context Window Management rules below (`ctx_*` over raw Bash for large output). Together they form AE's tool-selection standard: reach for the tool whose output-to-signal ratio is best for the model reading it.

## Context Window Management

**When `ctx_execute` or `ctx_batch_execute` MCP tools are available, prefer them over raw `Bash` for any operation expected to produce more than ~20 lines of output.** For tool usage detail, the create/modify-files prohibition, the `ctx_fetch_and_index`-over-`WebFetch` preference, and platform support: read `content/references/code-standards-detail.md` §Context Window Management.

## Module Manifests

**Non-trivial modules should carry a manifest header.** Any source file that exports a public symbol consumed by another module, is over ~50 lines of non-trivial logic, or implements a side-effecting operation (network, disk, database, external service) is encouraged to include a manifest comment or docstring at the top of the file. See `content/rules/module-manifest.md` for required fields, examples, and exemptions. Skeptic applies tiered enforcement: missing manifests are **Minor** (does not block sign-off), stale manifests are **Major** (blocks sign-off absent a compelling documented reason to defer), and stale manifests whose inaccuracy could mislead a caller on a correctness or security path are **Critical**. See `content/rules/module-manifest.md` for the full policy.

## DRY and Abstraction

**Do not Repeat Yourself. Engineers must actively scan their own output for duplication before declaring work complete.**

- **Repeated logic** — any block that appears more than once with identical or near-identical structure must be extracted into a helper, utility, or shared component.
- **Copy-paste with tweaks** — copying code and changing only names or constants is a strong signal for abstraction, not a valid implementation strategy.
- **Existing utilities first** — before writing new code, grep the codebase for functions that already solve the sub-problem. Prefer calling an existing utility over reimplementing it.
- **Follow established patterns** — if the codebase has a convention for this class of problem (validation schemas, error wrappers, React hooks, data transformers), use it.
- **Intentional exceptions** — if duplication is genuinely appropriate (the two paths are about to diverge significantly, or extraction would obscure meaning), state the reason explicitly in the output.

The Skeptic review layer enforces this: duplication and missed abstractions are **Major** findings that block sign-off unless justified.

## Code Quality Gates

**After writing or modifying code, run the project's lint, typecheck, and test commands.** All must pass with zero errors before work is complete.

- **Greenfield projects:** zero warnings from the start
- **Existing codebases:** do not introduce new warnings; flag pre-existing issues to the user
- Never suppress or disable rules to pass gates - fix the code. Suppression comments (`@ts-ignore`, `noqa`, etc.) require explicit user approval
- **New projects (via `/ds-init-project`):** set up pre-commit hooks (husky + lint-staged for JS/TS, pre-commit framework for Python)
- **Existing projects without tooling:** run whatever checks are available and recommend setup to the user

Read `content/references/code-standards-detail.md` §Per-Language Strict Defaults, §Browser Verification, and §Discovery-Based Check Discipline when implementing or modifying code.

## Package Management

**Dependency versioning rules** - when adding a new dependency, upgrading an existing one, or encountering a bug in an already-installed outdated dependency: read `content/references/code-standards-detail.md` §Package Management for the latest-stable-version default, the no-hardcoded-version rule, the no-monkey-patch rule, and the existing-constraint exception.
