# Contributing

## Getting started

1. Fork and clone the repo to `~/agentic-engineering/`:
   ```bash
   git clone git@github.com:Space-Dinosaurs/DinoStack.git ~/agentic-engineering
   ```
2. Install the adapter for your tool:
   - Claude Code: `.claude/install.sh` (runs the initial build and wires up the pre-commit hook)
   - Cursor: `.cursor/install.sh` (runs the initial build for the Cursor adapter)
3. Test changes locally by re-running the relevant `install.sh` and verifying behavior in a session

## What to contribute

- Bug fixes in rules, references, or adapter scripts
- New agents or commands
- Rule improvements (make them clearer or more precise)
- New adapters for other tools (see [ADAPTERS.md](ADAPTERS.md))
- Documentation improvements

### What's not welcome

- Customer-specific or branded workflows
- Private credentials, internal paths, or client names
- Bypasses of the project's safety conventions presented as features
- Automation that weakens the deny-list
- Wholesale rewrites of methodology rules without a protocol-change issue first

## Protocol-change process

Changes to the methodology itself - conductor rules, the Skeptic protocol, risk classification, memory persistence, worktree lifecycle, slash commands, or agent definitions - go through the protocol-change RFC flow before a PR is opened. Open an issue using the [Protocol change template](.github/ISSUE_TEMPLATE/protocol_change.yml) describing the motivation, the proposed change, backward-compatibility impact, and affected adapters. The lead maintainer approves the direction, requests revisions, or declines. Once approved, open a PR referencing the issue. See [GOVERNANCE.md](GOVERNANCE.md) for the full flow.

## PR guidelines

- One concern per PR — don't bundle unrelated changes
- Describe the *why* in the PR body, not just the *what*
- Test locally before opening: re-run `install.sh`, open a Claude Code session, verify the change works as expected

### Adapter compatibility declaration

Every PR must declare which adapters it affects. The PR template includes a checklist - tick all that apply (Claude Code, Cursor, Codex CLI, Gemini CLI, Kimi Code, OpenCode, Pi coding agent, Pi oh-my-pi, Hermes, or "None" for methodology / docs-only changes). For changes that touch `content/` (the single source of truth), assume all adapters are affected unless the change is scoped to adapter-specific files. For agent-behavior changes, include a short before/after transcript in the PR body so reviewers can see the effect without re-running the scenario locally.

## Before editing

**Pull before you change anything.** Run `git fetch origin && git pull --rebase origin main` at the start of every editing session — especially one that will spawn agents or touch multiple files. This repo is actively maintained. A refactor landing remotely while you work (file renames, symlink restructures, directory reshapes) turns clean edits into hand-merges. Cheap to prevent, expensive to untangle.

## Editing content

**Edit in `content/`, never in adapter files directly.** The `content/` directory is the single source of truth:
- `content/rules/` - the 3 rule files (agent-methodology, code-standards, conventions)
- `content/references/` - the 7 reference docs (agent-team, design-goals, doc-sync-obligation, multi-developer-coordination, regression-test-obligation, skeptic-protocol, subagent-protocol)
- `content/commands/` - the 14 command files (agentic-cost, agentic-disable, agentic-status, brief, cleanup-worktrees, implement-ticket, init-project, memory-update, prune-harness, representation-audit, skeptic, test-suite-comprehension, update-agentic-engineering, wrap)
- `content/agents/` - the 16 agent definitions (adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket)

Build scripts regenerate adapter files from `content/`:
- `.claude/build.sh` - rebuilds `.claude/commands/*.md` by prepending the `/agentic-engineering` prerequisite blockquote to each `content/commands/*.md` source. Rules, references, and agents need no copy step - `.claude/skills/agentic-engineering/rules`, `.claude/skills/agentic-engineering/references`, and `.claude/agents/` are all symlinks pointing directly into `content/`.
- `.cursor/build.sh` - combines frontmatter sidecars with rules to produce .mdc files, copies references and commands

The pre-commit hook runs both build scripts automatically when `content/` files are staged. If you bypass the hook, run the build scripts manually before committing.

A third build script, `scripts/build-slides.sh`, regenerates `docs/slides/*.html` from `docs/slides/*-slides.md` using a pinned Marp toolchain (`scripts/package.json` + `scripts/package-lock.json`). It is a separate mechanism from the two adapter builds above: it is NOT run by the `content/` pre-commit hook. Instead it is enforced by the `slides-sync` CI gate, which rebuilds the decks and fails the build on any drift - analogous to how `adapter-sync` and `methodology-drift` enforce the adapter and methodology builds. After changing any slide `.md`, run `bash scripts/build-slides.sh` and commit the regenerated `.html`; never hand-edit the `.html`. Upgrading marp is an intentional same-PR action: bump `scripts/package.json`, regenerate `scripts/package-lock.json`, and rebuild all decks.

**Frontmatter sidecars.** Cursor rules require YAML frontmatter. This metadata lives in `.cursor/rules/frontmatter/*.yaml` (one file per rule). The cursor build script combines the sidecar with the rule content to produce the `.mdc` file. Edit the sidecar to change frontmatter; edit `content/rules/` to change rule content.

## Architecture guardrails

**Methodology vs. adapters.** Rules and references live in `content/rules/` and `content/references/`. Adapters (`.claude/`, `.cursor/`) translate those into tool-specific formats. Content changes go in `content/` - never edit generated adapter files directly.

## Developer Certificate of Origin (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org) as a lightweight alternative to a CLA. By adding a `Signed-off-by` line to your commits, you certify that you wrote the contribution or otherwise have the right to submit it under the project's license.

### How to sign a commit

```bash
git commit -s -m "your message"
```

The `-s` flag appends a line like `Signed-off-by: Your Name <you@example.com>` using the name and email from your local git config.

### Fixing missing sign-offs

- Last commit only: `git commit --amend --signoff` then `git push --force-with-lease`
- Multiple commits in a PR: `git rebase --signoff <base-branch>` then force-push

### AI-assisted contributions

If you used AI assistance to author your contribution, certify in the PR description that you reviewed the AI-generated content and have the right to submit it under the project license. The DCO sign-off applies regardless of how the contribution was authored.

PRs without a signed-off commit on every commit will be blocked by the DCO check (configured by `.github/workflows/dco.yml`).

## Style

Match existing patterns before adding new ones. Rules are terse by design. Look at existing rule files before writing new content — if it reads longer than the files around it, trim it.

