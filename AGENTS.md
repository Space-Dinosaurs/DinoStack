# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

## Decisions
- Internal eval harness lives at `evals/` (Python 3.11, stdlib + pyyaml, git worktrees, shell-out to Codex CLI). Component-first approach per `docs/planning/p2-self-improving-harness.md`. See `evals/LEARNINGS.md` before starting work on any new component eval, and `evals/OVERFITTING-RULE.md` before shipping content/ edits motivated by eval scores.
- Methodology source-of-truth lives in `content/sections/01-*.md` through `10-*.md`. The legacy `content/rules/agent-methodology.md` path no longer exists - edit `content/sections/` for any methodology change.
- `scripts/build-methodology.sh` is the canonical methodology assembly script. Adapter builds (`.claude/build.sh`, `.codex/build.sh`, `.gemini/build.sh`, `.kimi/build.sh`) invoke it via `bash "$REPO_DIR/scripts/build-methodology.sh"`. `.cursor/build.sh` has a different output structure and does not use it.
- `.claude/install.sh` manages `~/.claude/CLAUDE.md` via a `managed_content` Python string (lines ~364-380). Four @-import lines (METHODOLOGY.md plus 3 rules files under `rules/`) must appear in that string or rules will not auto-inject in Claude Code sessions. Re-run install.sh after any changes to that string.
- Auto-harness keep-metric is mean-of-medians (`evals/auto/runner_shim.py:147`, PR #41). Median was blind to single-fixture wins when ≥half fixtures sat at ceiling 1.0.
- Auto-harness dimension signal (`evals/auto/loop.py:_build_dimension_signal`, PR #49) requires scorers to emit `{dim: {score: float}}`. Components using semantically-rich nested dicts (`tp_recall.matched[*].credit`, `signal_discipline` tiers, etc.) are dim-signal-blind until per-component extractors are added.

## Tools
- GitHub operations: use `gh` CLI - do not use GitHub MCP
- `gh pr create` for this repo requires an explicit token: `GITHUB_TOKEN=$(gh auth token --user tyson-solara6 2>/dev/null) gh pr create --repo Solara6/agentic-engineering` (SSH-alias remote not recognized by default gh auth)
- `rm -rf` is blocked by Claude Code permissions in this repo; remove files individually: `rm <file>` then `rmdir <dir>`

## Deploy
- Docs site: see `docs/technical/deploy.md`. Always verify the linked project ID before running `vercel --prod`.

## Docs
- `docs/planning/` - pre-implementation design artifacts
- `docs/research/` - research notes and reference material
- `docs/technical/` - implementation specs and architecture
- `docs/overview/` - high-level summaries and onboarding docs

## Conventions
- Conductor never creates worktrees for itself - it edits directly on its current branch. Worktrees are exclusively for subagents, created at `.agentic/worktrees/<branch-name>` and branching from the conductor's current branch. Subagent branches merge back to the conductor's branch; the conductor's branch then PRs to `main`.
- When isolation:worktree Workers are used across multiple sequential spawns in the same task, the worktree is cleaned up between them and subsequent Workers fall back to the main tree. Tell follow-up Workers this explicitly.
- When you struggle with a repeatable task (starting dev servers, deploying, running migrations, connecting to databases, etc.) and find the solution, proactively save the working steps to MEMORY.md so future sessions don't repeat the struggle.
- The pre-commit hook does not currently auto-stage `.claude/skills/agentic-engineering/METHODOLOGY.md` or `.codex/agents/*.toml`. After any `content/` edit, either stage these regenerated artifacts manually or extend the `git add` list in `hooks/pre-commit`.
- Any change to `content/rules/`, `content/references/`, `content/agents/`, `content/commands/`, or `content/sections/` MUST also update `docs/agentic-engineering.html` and any affected `docs/slides/*.md` (and rebuild the matching `.html`) in the same PR. Public-facing intent debt is the worst kind. Skeptic flags missing docs sync as a Major finding.
