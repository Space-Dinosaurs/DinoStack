# Activation (minimal)

Read once at session start. Silent on default.

1. Read `~/.claude/agentic-engineering.json`. If absent or `mode=opt-out`, no-op.
2. If `mode=opt-in`, check for `agentic-engineering: opt-in` line in root `AGENTS.md`. Absent -> no-op.
3. Read `tier` field; default `minimal`. Read `profile` for back-compat: `relaxed` -> `minimal`, `default` -> `medium`, `strict` -> `full`.
4. Project override: read `.agentic/config.json` and use `agentic_tier` if present (`minimal`, `medium`, or `full`). This overrides the global tier.
5. Proceed silently on proceed branches.

No scaffolding-sync, no identity file, no deprecation notices, no meta-divergence sweep, no skill-candidate sweep, no activation notice. Keep activation cost under 100 tokens.

Tier default: `minimal`.

# Delegation (minimal)

Three named agents: `engineer`, `skeptic`, `investigator`. All spawn in worktree isolation.

## Engineer

Owns shippable code. One task, one prompt. Reads file path + symbol, gets diff + commit + PR URL back.

- `isolation: worktree` mandatory. Branch from `origin/main`.
- Single round by default; Skeptic may bounce back for fixes.
- Returns: `diff_summary`, `commit_sha`, `pr_url`, `quality_gate_results`.

## Skeptic

Adversarial review. Reads diff in full. Findings: Critical/Major/Minor.

- Critical blocks merge. Major blocks merge unless justified. Minor documented, not blocking.
- Cap at 3 fix passes. Convergence failure (same finding re-raised) escalates immediately.
- Reads `git diff origin/$BASE_BRANCH..HEAD` in full before sign-off.
- Returns: `sign_off: granted | blocked`, `findings[]`.

## Investigator

Read-only code locator. Returns file:line table for "where is X", "what calls Y". Skips fixes.

## Worktree isolation

Every shippable-edit spawn sets `isolation: worktree`. Main checkout reserved for conductor-only artifacts (`.agentic/`, `docs/planning/`). Trivial-tier changes also worktree-isolated.

After Worker returns and PR opens, conductor removes the isolation worktree.

## No QA gate, no wrap-ticket, no architect, no planner

If a task needs them, escalate to `--tier=medium` (architect + planner + inline Brief + Skeptic + loop-state) or `--tier=full` (full Brief/Plan + QA + wrap-ticket + learning-extractor).

# Risk Classification (minimal)

Classify before every spawn. Defaults: when in doubt, Elevated.

| Class | When | Action |
|---|---|---|
| Trivial | 1 file (or +colocated test), no behavior/control-flow/API surface change, no shared tokens/config/CI/auth, reversible one-liner | Direct edit (still delegated to worktree-isolated engineer) |
| Low | 1 file local behavioral edit, no cross-component data flow, no security surface, no shared utility, no exported types | Direct edit + inline self-check |
| Elevated | Anything else: multi-file, security/auth/crypto/payments, architecture decision, new file exporting public symbol, shared utility, config/CI/env | Worker + Skeptic |

Profile field `profile=relaxed` makes the single-file behavioral edit Low instead of Elevated. Default tier = minimal does not apply this demotion (stays default).

Risk class determines:
- Trivial -> engineer with no Skeptic, no brief, no worktree brief file.
- Low -> engineer direct, conductor self-checks diff after return.
- Elevated -> engineer + Skeptic + worktree isolation. Skeptic reads diff in full.

No promotion-gate (Brief/Plan artifacts) in minimal. If Brief/Plan needed, escalate to `--tier=medium`.
