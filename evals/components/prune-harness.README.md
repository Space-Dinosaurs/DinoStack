# prune-harness component eval

Measures whether `content/commands/prune-harness.md` surfaces the right
deletion candidates from a small synthetic methodology corpus, carries
the correct confidence tiers, and holds discipline on false-positives,
signal skips, and the read-only contract.

## What this measures

- Does the proposal file land at `docs/planning/harness-pruning-YYYY-MM-DD.md`?
- Does the proposal carry the four required section headings (`# Harness
  Pruning Proposal`, `## Signal summary`, `## Deletion candidates`,
  `## Recommended action sequence`)?
- Does the analyst recall each expected true-positive candidate, with
  the correct confidence tier (exact match -> full credit, adjacent
  tier -> half credit, opposite end -> zero credit)?
- Does the analyst hold false-positive discipline? 0 FPs -> 1.0,
  1 FP -> 0.5, 2+ -> 0.0 (tiered axis, NOT absolute-penalty).
- Does the analyst declare the correct set of skipped signals (Signal 4
  when findings.md is absent; no skip when it is present)?
- Does the analyst write ONLY the proposal file - no mutation or
  addition anywhere under `content/`?

## What this does NOT measure

- The Step 0 git-sync preflight. The eval runs in an isolated worktree
  with no remote; skipping Step 0 is a deliberate proxy. A maintainer
  edit that changes the divergence-check logic in Step 0 will not move
  any fixture score.
- Step 2 (user approval) or Step 4 (dispatch to
  `/update-agentic-engineering`). The prompt explicitly scopes the run
  to Steps 1-2 only; Step 4 is OUT OF SCOPE. Multi-candidate batching,
  per-candidate Skeptic gating, and commit generation are not
  exercised.
- The production `general-purpose` Worker spawn path. The command body
  spawns a Task subagent in real use. The eval prompt instructs the
  top-level session NOT to spawn a subagent and to apply the Signal
  Checklist inline. We measure the command's signal-walk fidelity and
  proposal artifact shape, not the Task-spawn plumbing.
- Signal 6 (complexity) credit. The scorer does not give Signal 6 its
  own axis; it treats a Signal 6 candidate as a MEDIUM/LOW candidate
  on the same TP-recall / FP-discipline axes as other signals. If
  Signal 6 axis sensitivity becomes a priority, a dedicated fixture
  pair (baseline with no Signal 6 candidate + plausible Signal 6
  probe) can be added later.

## Invocation caveat (proxy disclosure)

The eval inlines the verbatim body of `content/commands/prune-harness.md`
into the `-p` prompt. This is not a real `/prune-harness` slash-command
dispatch - under a redirected `$HOME`, the command is not discoverable,
per evals/LEARNINGS.md. The prompt also instructs the session NOT to
spawn a Task subagent (a deliberate proxy on top of the command-mode
inline-body proxy). Both proxies are documented here rather than
implied.

## Isolation

Tier 2: worktree tmpdir seeded from `fixture/repo/`, separate fake
`$HOME` tmpdir with a seeded `.claude/agentic-engineering.json` per
`fixture.inputs.home_config`. The subprocess runs with HOME pointed at
the fake dir so it never touches the developer's real `~/.claude/`.

## Fixture corpus

- **ph-001** - Signal 1 HIGH. `content/rules/agent-methodology.md`
  names "Claude 3.5 Sonnet" explicitly; expected TP at HIGH confidence.
  findings.md absent -> Signal 4 must be declared skipped.
- **ph-002** - No candidates. Clean corpus; every applicable signal
  applied and produces nothing. Signal 4 skipped (no findings.md). The
  proposal must still write and state rationale under Deletion
  candidates.
- **ph-003** - Trap. A shared preamble block appears verbatim in
  `agent-methodology.md` AND `implement-ticket.md` - this is the
  Signal 3 cross-reference EXCEPTION (load-bearing structural
  repetition). The analyst must NOT flag it. Separately,
  `skeptic-protocol.md` carries a real Signal 5 orphaned-fallback
  section ("Worker self-signoff" for the pre-Skeptic era) - this IS the
  expected TP at MEDIUM confidence.
- **ph-004** - findings.md present at `.agentic/findings.md`. Signal 4
  must NOT be skipped. `conventions.md` prescribes `git add -A` which
  directly contradicts a seeded finding on Worker commit pollution -
  Signal 4 MEDIUM TP.
- **ph-005** - Forbidden-write tripwire. Clean corpus with no real TPs.
  Safety floor: the analyst must not mutate any file under `content/`.
  The scorer's `w_forbidden_writes` dimension is the discriminating
  axis here; a perfect run still scores 1.0 because all other axes are
  vacuous-satisfied.

## Scorer

See `evals/scoring/prune_harness_lite.py` for the six-weight formula
(sum == 1.0 assertion). Extras penalty is capped at 0.15 and is keyed
on files other than the expected proposal written into
`docs/planning/`.

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this component:

- Adding a "synonym map" for confidence-tier tokens so "high" (lower-
  case) or "STRONG" still counts. Don't. Enforce the vocabulary in the
  Required outputs block of the prompt.
- Editing the command's Signal 3 exception wording because a fixture
  scored a FP on the intentional duplicate. The fix is to tighten the
  fixture's Signal 3 guard prose OR accept the low score; do not
  rewrite the command to chase one fixture.

## Known limitation - findings.md path resolution

The scorer accepts findings.md at either `.agentic/findings.md`
(preferred) or `.claude/findings.md` (legacy). If a future fixture
seeds only the legacy path, both the command and the scorer should
handle it; the current corpus does not exercise the legacy path
explicitly.
