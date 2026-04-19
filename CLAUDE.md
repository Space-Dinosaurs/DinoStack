# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

## Decisions
- Internal eval harness lives at `evals/` (Python 3.11, stdlib + pyyaml, git worktrees, shell-out to Claude CLI). Component-first approach per `docs/planning/p2-self-improving-harness.md`. See `evals/LEARNINGS.md` before starting work on any new component eval, and `evals/OVERFITTING-RULE.md` before shipping content/ edits motivated by eval scores.

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
- When you struggle with a repeatable task (starting dev servers, deploying, running migrations, connecting to databases, etc.) and find the solution, proactively save the working steps to MEMORY.md so future sessions don't repeat the struggle.
