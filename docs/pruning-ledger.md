# Pruning Ledger

## Scope

This ledger is fed by exactly two commands: **`/ds-prune-harness`** and **`/ds-representation-audit`**. Both write candidate proposals to `docs/planning/` (gitignored, ephemeral) and, once the user approves or rejects a candidate, record a standing entry here.

`/ds-evaluate` and `/ds-failure-audit` are deliberately **not** in scope. They produce whole-report scorecards, not standing per-item candidates, and their `docs/planning/` output stays ephemeral - a later reader must not assume either of those commands feeds this ledger.

## Path resolution

This file's path is resolved per-repo, not hardcoded: prefer a tracked `.agentic/pruning-ledger.md` when the consuming repo tracks `.agentic/`, else `docs/pruning-ledger.md`. Determined mechanically via `git check-ignore -q <path>` (exit 1 means tracked-capable, exit 0 means ignored, exit 128 is a git failure and neither - see `/ds-prune-harness` Step 0.5 for the full three-way handling), never assumed. In this repo, `.agentic/` is categorically gitignored (see `AGENTS.md`'s "DinoStack does not commit its own `.agentic/` runtime files" decision block - DinoStack is the methodology's source, not a consumer of it, so its own `.agentic/` scratch stays untracked - and the `.agentic/*` umbrella in `.gitignore`), so the resolver lands on `docs/pruning-ledger.md` - this file is the expected outcome here, not a special case.

## Lifecycle

- **RAISED** - a candidate the user approved for action, or explicitly deferred (not rejected), pending a deletion/rewrite PR via `/ds-update-agentic-engineering`.
- **ACTIONED** - the candidate's deletion/rewrite PR merged. `Disposition` carries the PR URL. This transition happens **in the same PR diff as the deletion/rewrite itself** - the Skeptic reviewing that deletion necessarily reviews the ledger update, so a `RAISED` entry can only reach `ACTIONED` via a PR a Skeptic already gated. This is what closes the write-only-graveyard risk: nothing here can be marked done without independent review of the same change.
- **REJECTED** - the user declined the candidate at proposal-review time. `Disposition` carries the user's stated reason and the date.

**Carry-over:** every `RAISED` entry left un-actioned resurfaces at the top of the next `/ds-prune-harness` (or `/ds-representation-audit`) run's proposal, rather than sitting silently. A candidate neither approved-and-actioned nor explicitly rejected stays `RAISED` indefinitely if the audit command is never run again - this is a real residual gap inherent to "the process only runs when invoked," not one this ledger's mechanics can force closed on their own.

## Entry schema

```
## PL-YYYYMMDD-N
- Status: RAISED | ACTIONED | REJECTED
- Source: ds-prune-harness run YYYY-MM-DD (docs/planning/harness-pruning-YYYY-MM-DD.md)
- File(s): content/path/to/file.md (lines N-M)
- Signal(s): [...]
- Confidence: HIGH | MEDIUM | LOW
- Rationale: [one paragraph]
- Disposition: [filled on ACTIONED/REJECTED - PR link or rejection reason + date]
```

`Source` names either `ds-prune-harness` or `ds-representation-audit` and the date of the run that produced the candidate, plus the proposal file's path under `docs/planning/` at the time it was written (that file is gitignored and will not exist by the time a later reader opens this ledger - the path is provenance, not a live link).

---

## PL-20260825-1
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/design-goals.md (title line; Goal 2; Goal 3; Non-Goals section)
- Signal(s): Signal 5 (orphaned legacy text) + internal contradiction with the live corpus
- Confidence: HIGH
- Rationale: Title still reads "claude-protocols" (pre-rename); Goal 3 cites two nonexistent paths (.claude/rules/decisions.md, claude-hooks/stop-context.js) and a false "/ds-memory-update is the only write path to decisions.md" claim; Goal 2 enumerates two risk levels omitting Trivial; Non-Goals ("does not commit, push, merge") contradict the shipped /ds-implement-ticket Phases 8-12 auto-merge workflow. Approved for rewrite, not deletion; Goal 4 (three-question partition test) is canonical per AGENTS.md and must be preserved verbatim.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/824

## PL-20260825-2
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/skeptic-protocol.md (Section 0 "Risk Assessment"; "Document hierarchy" passage; ~/.claude/agents/skeptic.md citation)
- Signal(s): Signal 3 (verbatim duplication) + Signal 5 (orphaned legacy text)
- Confidence: HIGH
- Rationale: Section 0 duplicates the Elevated-signal and common-rationalizations tables canonical in content/sections/02-delegation.md, 04-risk-classification.md, and delegation-detail.md (a known DS-48 multi-copy drift hazard); states risk is "Low or Elevated" only, missing Trivial; the "~/.claude/CLAUDE.md contains inline risk classification rules" hierarchy claim is stale post-DS-143. Approved for pointer-izing after confirming the skeptic agent's read chain resolves the canonical table.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/826

## PL-20260825-3
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/subagent-protocol.md (Section 12 sync targets; Section 11 path citation; Rule 4 / Section 4 agent-type tables; TaskOutput references; line ~212 Section 0 citation)
- Signal(s): Signal 5 (orphaned legacy text) + Signal 3 (contradiction with the named-agent roster)
- Confidence: HIGH
- Rationale: Section 12 instructs updating ~/.claude/CLAUDE.md risk tables that no longer exist post-DS-143; Section 11 cites nonexistent .claude/rules/decisions.md; TaskOutput references describe a replaced harness tool shape; Rule 4 and Section 4 tables recommend general-purpose Workers broadly, contradicting the named DinoStack agent roster. Approved for rewrite; the general-purpose guidance is to be scoped to harnesses lacking named agents (portability pillar), not deleted.
- Disposition: Rewritten in https://github.com/Space-Dinosaurs/DinoStack/pull/827 - all five defects fixed (including a fifth, sibling-reported staleness at line ~212's Skeptic Protocol Section 0 citation). The general-purpose guidance was scoped, not deleted: verification found every spawn-capable adapter ships the full named-agent roster and Cursor has no spawning at all, so no live portability role exists today, but `general-purpose` remains an explicit fallback row for a harness that might need it in future. Note on axis substitution: the Rationale above calls for scoping this guidance "to harnesses lacking named agents" (a portability axis), but the implementation scoped it on task-fit instead ("use a named agent unless none of the named agents fit the task"). The harness-lineup check found every spawn-capable adapter ships the named roster, so the portability axis had no live referent to scope against; the kernel's own task-fit fallback wording was used instead.

## PL-20260825-4
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/tier-map-example.yml (model id entries)
- Signal(s): Signal 1 (explicit model-version reference)
- Confidence: HIGH
- Rationale: Example tier map names gpt-4o-mini, gpt-4o, o3, gemini-2.0-* era models, stale relative to current provider lineups. The file self-disclaims ("examples only, not kept current"), so this is a refresh, not a behavioral premise on a dead model. Operator decision 2026-08-25: explicitly deferred - the disclaimer is accepted as sufficient for now; refresh in a later pass. Operator decision 2026-08-26: approved under the don't-pin-models directive.
- Disposition: Neutralized to placeholders rather than refreshed to a new set of concrete ids, so the file cannot go stale again. PR: https://github.com/Space-Dinosaurs/DinoStack/pull/841

## PL-20260825-5
- Status: RAISED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/conductor-turn-format.md (retired-mechanism passages: _status_only_flag, _answer_relevance_flag, volume check, WAITING_LINE_MAX_CHARS, residuals kept "for the git-blame trail", historical Known-uncovered-shapes rows)
- Signal(s): Signal 5 (orphaned legacy text) + Signal 6 (complexity)
- Confidence: MEDIUM
- Rationale: DS-171 deleted these checks from hooks/enforce-turn-shape.py; the reference doc retains history-of-deleted-code prose that git history already archives. Operator decision 2026-08-25: deferred (not in the approved first wave); carries over to the next run.
- Disposition:

## PL-20260825-6
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/events-log.md (the deprecated conductor_direct event documentation block)
- Signal(s): Signal 5 (orphaned legacy text)
- Confidence: MEDIUM
- Rationale: Block is self-labeled deprecated and historical-only; nothing emits or consumes the event (2026-06-27 decision: a deterministic hook cannot detect an LLM-semantic event). Approved for deletion, optionally leaving a one-line legacy-name note for log parsers reading old events.jsonl files.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/829

## PL-20260825-7
- Status: RAISED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/regression-test-obligation.md + content/references/qa-regression-obligation.md + content/agents/skeptic.md Step 9 (triplicated pre-fix-failure verification procedure)
- Signal(s): Signal 3 (verbatim duplication)
- Confidence: MEDIUM
- Rationale: The same scratch-worktree pre-fix-failure verification procedure is maintained near-verbatim in three places, a silent-drift hazard. Operator decision 2026-08-25: explicitly deferred - consolidation has higher mechanical cost (every citing spawn-brief template must still resolve one Read away) and is not in the approved first wave.
- Disposition:

## PL-20260825-8
- Status: RAISED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/conventions-detail.md (Project Config catalog) + content/references/risk-config-and-tiers.md (Config Toggle Catalog)
- Signal(s): Signal 3 (verbatim duplication)
- Confidence: MEDIUM
- Rationale: The full 24-toggle catalog is maintained twice; both manifests admit the sync burden, and the count appears in four surface forms across 8 CI-pinned prose sites. Operator decision 2026-08-25: explicitly deferred - consolidating moves the pinned sites and must update bin/tests/test_tracker_writeback_ranking_spec.py in the same PR; not in the approved first wave.
- Disposition:

## PL-20260825-9
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/agents/adr-drift-detector.md (4 copies) + content/agents/adr-generator.md (5 copies, one inside the fenced ADR template)
- Signal(s): Signal 3 (verbatim duplication within single files)
- Confidence: MEDIUM
- Rationale: The /dinostack prerequisite blockquote is repeated 4-5 times within single agent files; one top-of-file copy is the intentional pattern. The copy inside adr-generator.md's fenced ADR template is an outright defect - every generated ADR ships a skill-load instruction in its front matter. Approved: dedupe to one copy per file and remove the in-fence copy as a bug fix.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/823

## PL-20260825-10
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/agents/release-orchestrator.md (Phases 6-8 self-spawn instructions)
- Signal(s): Signal 5 (legacy text) + contradiction with live enforcement
- Confidence: MEDIUM
- Rationale: release-orchestrator is itself a subagent and subagents cannot spawn subagents (hooks/enforce-orchestrator-singularity.py denies exactly this), yet Phases 6-8 instruct it to spawn the debugger and qa-engineer. Approved: rewrite to hand failures and QA needs back to the conductor via structured returns. The singularity hook itself is a floor and is not a candidate.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/825

## PL-20260825-11
- Status: REJECTED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/references/wrap-context-format.md (10-branch merge ladder)
- Signal(s): Signal 6 (complexity, consider-simplifying only)
- Confidence: LOW
- Rationale: The merge ladder is intricate but byte-pinned from its NORMATIVE marker to EOF by hooks/tests/test-wrap-context-format-golden.js; simplification is a deliberate gate-updating change with high cost against uncertain benefit.
- Disposition: Rejected 2026-08-25 - leave as is unless a concrete wrap defect ever traces to ladder complexity; recorded so future runs do not re-litigate from scratch.

## PL-20260825-12
- Status: RAISED
- Source: ds-prune-harness run 2026-08-25 (docs/planning/harness-pruning-2026-08-25.md)
- File(s): content/commands/ds-cost.md (V1 "instruments engineer/skeptic/qa only" scope footer)
- Signal(s): Signal 5 (possible staleness)
- Confidence: LOW
- Rationale: events-log.md documents hook-emitted spawn_start telemetry for every subagent spawn (DS-160), but whether the footer describes the emit sites or ds-cost's aggregation logic was not determinable from prose alone. Operator decision 2026-08-25: deferred pending verification against bin/'s cost aggregation; no standalone ticket warranted.
- Disposition:

## PL-20260826-1
- Status: RAISED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/commands/ds-implement-ticket.md (line ~2353, Phase 8 COMMIT_MSG template)
- Signal(s): Signal 1 (explicit model-version reference)
- Confidence: HIGH
- Rationale: The Phase 8 commit template hardcodes the trailer "Co-Authored-By: Claude Sonnet 4.6" - a live template, not an example, so every current-model session misattributes its commits. Operator decision 2026-08-26: approved; per the operator's standing directive there is to be NO Claude attribution in PRs or commits, so the trailer is deleted outright rather than parameterized.
- Disposition:

## PL-20260826-2
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/commands/ds-cost.md (lines ~64-77, pricing.yml example)
- Signal(s): Signal 1
- Confidence: HIGH
- Rationale: Example pricing config pins claude-sonnet-4-6 and claude-opus-4-7 with concrete per-token rates and no disclaimer. Operator decision 2026-08-26: approved; per the "don't pin models" directive, neutralize ids to placeholders.
- Disposition: Replaced pinned model ids with `<model-id-1>`/`<model-id-2>` placeholders and added the tier-map-example.yml-style illustrative-example disclaimer. PR: https://github.com/Space-Dinosaurs/DinoStack/pull/840

## PL-20260826-3
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/commands/ds-configure-team.md (line ~47)
- Signal(s): Signal 1
- Confidence: HIGH
- Rationale: Non-interactive wizard example pins claude-opus-4-5 with no disclaimer. Approved; neutralize to a placeholder per the "don't pin models" directive.
- Disposition: Neutralized all three pinned model ids in the non-interactive `--assign` example block (`architect=claude`, `debugger=kimi`, `engineer=omp:REPLACE_WITH_MODEL_ID`) per the "don't pin models" directive. The disclaimed interactive-wizard transcript ids ("shown for reference only") were deliberately retained. PR: https://github.com/Space-Dinosaurs/DinoStack/pull/837

## PL-20260826-4
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/commands/ds-prune-harness.md (lines ~71 and ~77)
- Signal(s): Signal 4 (contradiction with live state) + falsified Signal-1 NOTE
- Confidence: MEDIUM
- Rationale: Two parenthetical self-claims are now false: "no model-version references exist in rules/references/agents" (falsified by tier-map-example.yml among others) and "findings.md does not exist at either resolver path" (.agentic/findings.md exists, 7 entries). The 2026-08-25 run had to override its own contract because of the second. Approved: delete both stale asides per the prefer-deletion rule.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/839

## PL-20260826-5
- Status: ACTIONED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/commands/ds-wrap.md (lines ~127-135, Deferred-enrichment data model section)
- Signal(s): Signal 3 (verbatim duplication)
- Confidence: MEDIUM
- Rationale: ds-wrap.md carries verbatim copies of the pinned header prefix block and the spillover record schema whose declared single normative home is content/references/wrap-context-format.md ("Edit the algorithm here, not in either consumer"). Nothing depends on ds-wrap.md's copies. Approved: consolidate to pointers, keeping the pending-<session_id>.json marker schema that ds-wrap.md genuinely owns.
- Disposition: https://github.com/Space-Dinosaurs/DinoStack/pull/842

## PL-20260826-6
- Status: RAISED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/references/wrap-context-format.md (lines ~93-113, ten-bullet rolling-label enumeration)
- Signal(s): Signal 6 (complexity, consider-simplifying only)
- Confidence: LOW
- Rationale: Nine of ten bullets are one parametric sentence instantiated for N=2..9; a parametric rule plus two special cases would express the same algorithm in ~4 bullets. The file is sha256-pinned by test-wrap-context-format-golden.js and the enumeration may be deliberate few-shot scaffolding. Operator decision 2026-08-26: deferred - not actioned without an explicit judgment that the enumeration is not load-bearing.
- Disposition:

## PL-20260826-7
- Status: RAISED
- Source: ds-prune-harness run 2026-08-26 (docs/planning/harness-pruning-2026-08-26.md)
- File(s): content/references/events-log.md (lines ~83-90, hook-emitted-variant schema bullets)
- Signal(s): Signal 6 (complexity, consider-simplifying only)
- Confidence: LOW
- Rationale: Schema bullets carry round-by-round development narratives ("round-2 fix...", "round-5 correction...") that are git-blame material, though some double as do-not-regress warnings and schema drift here silently miscounts ds-cost output. Operator decision 2026-08-26: deferred - simplification requires preserving the normative warnings; not actioned this run.
- Disposition:
