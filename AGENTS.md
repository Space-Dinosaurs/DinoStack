# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

## Decisions
- Internal eval harness lives at `evals/` (Python 3.11, stdlib + pyyaml, git worktrees, shell-out to Codex CLI). Component-first approach per `docs/planning/p2-self-improving-harness.md`. See `evals/LEARNINGS.md` before starting work on any new component eval, and `evals/OVERFITTING-RULE.md` before shipping content/ edits motivated by eval scores.
- Methodology source-of-truth lives in `content/sections/01-*.md` through `10-*.md`. The legacy `content/rules/agent-methodology.md` path no longer exists - edit `content/sections/` for any methodology change.
- `scripts/build-methodology.sh` is the canonical methodology assembly script. Adapter builds (`.claude/build.sh`, `.codex/build.sh`, `.gemini/build.sh`, `.kimi/build.sh`) invoke it via `bash "$REPO_DIR/scripts/build-methodology.sh"`. `.cursor/build.sh` has a different output structure and does not use it.

## Tools
- GitHub operations: use `gh` CLI - do not use GitHub MCP

## Deploy
- Docs site: see `docs/technical/deploy.md`. Always verify the linked project ID before running `vercel --prod`.

## Docs
- `docs/planning/` - pre-implementation design artifacts
- `docs/research/` - research notes and reference material
- `docs/technical/` - implementation specs and architecture
- `docs/overview/` - high-level summaries and onboarding docs

## Conventions
- All repo changes must be done in a git worktree branched from `main`. Do not do feature work in the primary checkout, and do not branch new work from another feature branch unless the user explicitly asks for stacked work.
- When you struggle with a repeatable task (starting dev servers, deploying, running migrations, connecting to databases, etc.) and find the solution, proactively save the working steps to MEMORY.md so future sessions don't repeat the struggle.
- The pre-commit hook does not currently auto-stage `.claude/skills/agentic-engineering/METHODOLOGY.md` or `.codex/agents/*.toml`. After any `content/` edit, either stage these regenerated artifacts manually or extend the `git add` list in `hooks/pre-commit`.
