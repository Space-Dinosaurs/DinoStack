# Governance

## Current model

agentic-engineering is led by a single lead maintainer (the project creator) with informal community input. This model is expected to evolve toward a small maintainer group as the contributor base grows.

- **Lead maintainer:** `<lead maintainer handle TBD>`
- **Decision authority:** the lead maintainer has final say on protocol direction, releases, and contributor access. Day-to-day PR review may be delegated as the contributor base grows.

## How decisions are made

Most changes go through the standard PR flow described in [CONTRIBUTING.md](CONTRIBUTING.md). The lead maintainer reviews and merges.

For larger or load-bearing changes - the protocol itself, risk classification, the Skeptic loop, conductor rules, worktree lifecycle, slash commands, agent definitions, memory persistence - use the **protocol-change RFC flow**:

1. Open an issue using the **Protocol change** template ([.github/ISSUE_TEMPLATE/protocol_change.yml](.github/ISSUE_TEMPLATE/protocol_change.yml)).
2. Describe the motivation, the proposed change, backward-compatibility impact, and affected adapters.
3. Discussion happens on the issue. The lead maintainer either approves the direction (allowing a PR to follow), requests revisions, or declines with a reason.
4. If approved, open a PR referencing the protocol-change issue. The PR is reviewed against the agreed-upon design.

Protocol changes that bypass this flow may be closed with a request to open an RFC issue first.

## Maintainer responsibilities

- Review PRs in a reasonable timeframe
- Keep the methodology coherent across adapters
- Tag and document releases in [CHANGELOG.md](CHANGELOG.md)
- Maintain the issue and PR backlog

## Becoming a maintainer

The project will add maintainers as the contributor base grows. There is no formal application process yet. Sustained, high-quality contributions and engagement in reviews are the path.

## Changing this document

Governance changes follow the same protocol-change RFC flow described above.
