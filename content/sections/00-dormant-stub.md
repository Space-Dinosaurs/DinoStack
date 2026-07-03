<!-- tiers: none -->
<!--
  Single source for the per-adapter DORMANT stub.

  This file is NOT part of the assembled methodology. The leading
  `<!-- tiers: none -->` marker plus the `00-` prefix exclusion in
  scripts/build-methodology.sh keep it out of METHODOLOGY.md. It exists
  only so each adapter's install.sh (via scripts/lib/stub.sh `ae_stub_body`)
  can render one identical stub body into that adapter's dormant artifact.

  Token `{{TIER_FILE}}` is replaced at build/install time with the
  absolute path to the resolved-tier methodology file. When no path is
  known (adapter build with no install context) it renders as the literal
  relative pointer below so the stub still reads sensibly.

  Budget: the rendered body (this file minus this comment header) must
  stay <= 2048 bytes. scripts/check-stub-budget.sh enforces it in CI.
-->
## agentic-engineering (dormant)

The agentic-engineering methodology is installed on this machine but is **dormant** in this project. No delegation model, risk gates, or review loops apply here until it is activated. This stub costs nothing at rest.

**Activate in this project** (any one of these, first hit wins):

1. Run `/ds activate` (writes `.agentic/active`; `--session` for this session only, `--tier=minimal|medium|full` to pick depth).
2. Create a `.agentic/` directory in the project root — auto-detected as active on the next turn.
3. Add this project to the allowlist: `agentic-ds activate` from the project root records it in `~/.agentic/activation.json`.

A `.agentic/dormant` tombstone file overrides auto-detection — remove it (or run `/ds activate`) to re-enable a previously deactivated project.

**When active**, load the full methodology from `{{TIER_FILE}}` and follow it. When dormant, ignore it entirely.

Run `/ds status` to see the current activation state, tier, and resident footprint.
