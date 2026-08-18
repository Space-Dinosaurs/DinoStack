# /ds-prune-harness

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Performs a periodic analysis pass over methodology files to surface deletion candidates - rules whose motivating assumptions have expired as Claude has become more capable.

**When to use:** After each Claude model upgrade, or quarterly. This command is analysis only. It writes a proposal document and stops. No methodology files are changed. Actual deletions go through `/ds-update-agentic-engineering` separately, one candidate at a time.

**Do not use to:** make changes, validate a specific rule's necessity, or replace judgment. The output is a proposal, not a verdict.

## Safety model

The prune analyst Worker is instructed not to write to `content/` and to restrict writes to the single output path in `docs/planning/`. This is enforced by Worker brief compliance, NOT by a harness-level technical barrier. The `tool_scope` field in the execution contract is documentation only - per the Worker preamble section of `METHODOLOGY.md`, it does not physically prevent writes. The analyst is instructed not to write to `content/`, and any violation would surface as a diff the conductor rejects before moving to Step 4. The authoritative gate is the Skeptic review on each subsequent deletion via `/ds-update-agentic-engineering`. Do not describe this mechanism as "physically cannot delete" - it cannot and does not make that guarantee.

## Step 0 - Preflight git sync

Run the Step 0 preflight from `/ds-update-agentic-engineering` verbatim (fetch origin, check clean tree, check divergence, refuse dirty tree). Git state decisions require main-agent judgment; do not delegate this step.

## Step 0.5 - Resolve the ledger path, read carry-over, and check audit-state

The conductor performs this step directly (no Worker) - it is a handful of reads plus one advisory print, not analysis.

**Resolve the ledger and audit-state paths.** Both live at the same resolved path per repo, never hardcoded to `docs/`: prefer a tracked `.agentic/pruning-ledger.md` / `.agentic/pruning-audit-state.json` when the consuming repo tracks `.agentic/`, else `docs/pruning-ledger.md` / `docs/pruning-audit-state.json`. Determine trackability mechanically, never by assuming:

```
git check-ignore -q .agentic/pruning-ledger.md
```

A non-zero exit means `.agentic/` is trackable in this repo - use the `.agentic/` paths. A zero exit (ignored) means use the `docs/` paths. In DinoStack's own repo this resolves to `docs/pruning-ledger.md` and `docs/pruning-audit-state.json` (`.agentic/` is categorically gitignored here) - that is the expected outcome in this repo, not a special case in the resolution logic.

**Read carry-over candidates.** Read the resolved ledger file. Any entry with `Status: RAISED` whose `File(s)` field overlaps this run's scan scope (`content/rules/`, `content/references/`, `content/agents/`, `content/commands/`) is a carried-over candidate: pass its ledger ID, file(s), and rationale to the analyst Worker in the spawn prompt as "already-known - do not re-raise as a new candidate, note as carried-over in the Signal summary instead." Every `RAISED` entry left un-actioned resurfaces this way at the top of every subsequent run - this is the carry-over mechanism, stated explicitly here rather than left implicit: a candidate neither actioned nor rejected does not silently drop off the radar between runs.

**Check audit-state and print the advisory nudge.** Read the resolved audit-state file if present. If `last_run` is non-null and `last_run.model_self_reported` differs from this session's own self-reported model identity, print one advisory line: "Model changed since the last audit (`<old>` -> `<new>`, on `<date>`) - treat prior findings as unverified." This is advisory only - the audit proceeds unconditionally regardless of the comparison, and it is conductor-level prose inside a command's execution flow, not a hook, so it needs no `enforce-*.py` registration. The model-string comparison is supplementary context, not the load-bearing signal - by this repo's own precedent (see `never trust an agent-reported SHA` in `MEMORY.md`), a self-reported model string is not reliable enough to gate anything on.

Pair it with a deterministic, self-report-free secondary nudge in the same step - **this is the load-bearing half**:

```
git log --oneline --since=<last_run.date> -- content/rules content/references content/agents content/commands hooks | wc -l
```

If `last_run` is null (no prior run recorded), skip both nudges - there is nothing to compare against. If the commit count is nonzero, print: "N methodology commits have landed since the last audit (`<date>`)." Label this line as the primary signal in the printed output; label the model-string line as supplementary.

**Rejected alternative (do not build):** a SessionStart/Stop `enforce-*.py` hook firing this nudge automatically every session. Rejected because (a) it cannot know the current model version any more reliably than the conductor's self-report, so it buys no rigor; (b) to be useful it would gate on inferred session capability, which `hooks/AGENTS.md` flatly prohibits; (c) it adds a hook plus a `MANAGED_HOOK_BASENAMES` entry and multiple subcount-site updates for a nudge that fires at most quarterly.

## Step 1 - Spawn the prune analyst

Before spawning, the **conductor** (not the Worker) runs `bin/ds-hook-fire-report --json` and captures the output. This feeds Signal 8 below. The analyst Worker's `tool_scope` has no Bash - this ticket does not widen it - so the conductor runs the command and passes the JSON verbatim into the spawn prompt; the analyst never shells out to it itself. Also pass any carried-over candidates read from the ledger at Step 0.5, per that step's instruction.

Spawn a single `general-purpose` Worker in background with the following execution contract (NLH format per `METHODOLOGY.md`):

*"You are a Worker agent. Produce a pruning proposal for the dinostack methodology corpus and return your complete output. The main agent will present the proposal to the user for approval."*

- outputs: a pruning proposal document written to `docs/planning/harness-pruning-YYYY-MM-DD.md` (substitute today's date)
- budget: ~40 tool calls
- tool_scope: Read, Glob, Grep, Write (Write restricted to the single output path - documentation only, Worker brief compliance)
- completion_conditions: every file under `content/rules/`, `content/references/`, `content/agents/`, `content/commands/` read; signal checklist applied section-by-section; proposal document written using the template below; no `content/` file modified; if no candidates are found after applying all signals, the proposal still writes and states this explicitly with rationale (an empty proposal is a valid output)
- output_paths: `docs/planning/harness-pruning-YYYY-MM-DD.md`

Pass the `bin/ds-hook-fire-report --json` output captured above into the spawn prompt alongside the signal checklist, so the analyst can apply Signal 8 to it directly.

Pass the signal checklist verbatim in the spawn prompt (see Signal Checklist below). The analyst applies the checklist section-by-section and writes candidates incrementally to its output document rather than holding all findings in memory.

## Mandatory pre-filter - floor vs. dial

Before including any candidate, apply the floor-vs-dial test from `content/references/obsolescence-signal.md`. A rule/hook that enforces a floor is never a candidate regardless of which signals fired; only harness-driven vestiges are retirement candidates. This pre-filter runs before the signal checklist below - a candidate that fails it is excluded before Signal 1 is even applied, not flagged and then discarded.

## Signal checklist (verbatim - this is the binding contract)

The analyst applies each signal to every file in scope and flags candidates as they are found. No signal is skipped except Signal 4 when findings.md is absent at both resolver paths (see Signal 4).

**Signal 1 - explicit model-version reference.** Candidate if the named version is older than the current deployed model. NOTE: on the current corpus, no model-version references exist in rules/references/agents - this signal is primarily a forward-looking guard. If it fires, flag with HIGH confidence.

**Signal 2 - "because the model forgets" framing.** Candidate if that failure class has not appeared in findings.md (resolved via `.agentic/findings.md` preferred, legacy `.claude/findings.md` fallback) in the last 6 months, or the rule has no known firing instance. MEDIUM confidence.

**Signal 3 - verbatim duplication across files.** Flag the duplicate, not the canonical (usually the longer or more detailed version). EXCEPTION: cross-reference duplication is NOT a candidate. Intentional repetition - a preamble appearing in both a rule file AND the command that instructs agents to follow the rule, the execution contract appearing in both `METHODOLOGY.md` AND `implement-ticket.md`, the Skeptic sign-off format appearing in both `skeptic-protocol.md` AND `METHODOLOGY.md` - is load-bearing structural redundancy, not accidental bloat. The analyst must explicitly test: "would deleting this copy break a cross-reference another doc depends on?" If yes, not a candidate. MEDIUM confidence when the duplication is genuinely accidental.

**Signal 4 - contradiction with findings.md entries.** Resolve findings.md via `.agentic/findings.md` preferred, legacy `.claude/findings.md` fallback. If neither path exists (as is currently the case for this repo), SKIP this signal entirely and note "Signal 4 skipped: findings.md does not exist at either resolver path in this repo" in the proposal's signal summary. Do not produce false candidates.

**Signal 5 - orphaned fallback text.** Sections labeled "fallback", "legacy", or "if the agent cannot" where the older behavior no longer occurs. MEDIUM confidence.

**Signal 6 - rule complexity exceeding the behavior it constrains.** LOW confidence - the analyst flags these with an explicit "low-confidence" marker and explicitly defers to human judgment. Not a standalone deletion candidate - only a "consider simplifying" suggestion. The analyst must NOT propose outright deletion on Signal 6 alone.

**Signal 7 - reference doc that is a strict subset of another.** MEDIUM confidence. Flag for consolidation, not outright deletion, unless the subset is empty (no unique content).

**Signal 8 - zero enforcement action in the fire log.** Candidate if `bin/ds-hook-fire-report --json` (run by the conductor before Step 1 and passed into this spawn prompt - see Step 1) reports a hook with status `ZERO_INVOCATIONS` or `ZERO_ACTION_IN_WINDOW`. Confidence depends on window coverage: MEDIUM at `window_days >= 30`, LOW (informational only, never a standalone deletion candidate) below 30 days of log coverage. Before treating any `ZERO_*` status as candidate evidence, the write-up must note whether the hook is even registered - cross-reference `bin/ds-doctor`'s hook-liveness check (`MANAGED_HOOK_BASENAMES`). A silently unregistered hook also shows zero fires, and that is a different, more urgent finding ("the enforcement was already dead," not "the rule expired") - flag it separately, not as a Signal 8 pruning candidate. `UNMEASURED` status (fires log absent entirely) is never itself a signal - it means no data exists, not that the hook is unused. **Every Signal 8 candidate is subject to the mandatory pre-filter above before it is proposed**: a zero-fire enforcement hook is very often a model-driven floor being cheap to satisfy (see the worked example in `content/references/obsolescence-signal.md`), not evidence the rule is unnecessary - do not let a MEDIUM/LOW confidence tier substitute for applying the floor-vs-dial test.

**Explicit non-signals:**
- Short rules - length is not a deletion signal
- "This could be inferred" - theoretical deducibility is not a signal; affirmative evidence of expiration is required
- Intentional cross-reference duplication (see Signal 3 exception)

## Confidence tiers

Every candidate in the proposal carries a confidence tier:

- **HIGH** - Signal 1 (named model version is stale). Also used when multiple MEDIUM signals fire on the same candidate.
- **MEDIUM** - Signals 2, 3, 5, 7 when the evidence is unambiguous; Signal 8 at `window_days >= 30`.
- **LOW** - Signal 6 (complexity) only, always with a "consider simplifying" suggestion rather than a deletion proposal; Signal 8 below 30 days of log coverage (informational only, never a standalone candidate).

Mixed-signal candidates take the highest confidence among the triggering signals.

## Proposal document template

The analyst writes the proposal using this exact structure:

```
# Harness Pruning Proposal - YYYY-MM-DD

## Signal summary
- Total candidates: N (H high / M medium / L low confidence)
- Floor-vs-dial test applied to: [count] candidates; [count] excluded as floors
- Signals that fired: [list]
- Signals skipped: [list, with reason - e.g., "Signal 4: findings.md absent at both resolver paths"]
- Signals that produced no candidates: [list]

## Deletion candidates

### [Candidate title]
- Confidence: HIGH | MEDIUM | LOW
- File: content/path/to/file.md (lines N-M)
- Signal(s): [which signals fired]
- Rationale: [why this is a candidate, specific evidence]
- Risk if wrong: [what breaks if this is deleted incorrectly]
- Suggested action: [delete / consolidate into X / simplify]

(repeat per candidate)

## Notable checks that passed
[Optional: rules reviewed and explicitly kept, with brief rationale - only if especially relevant]

## Recommended action sequence
[Ordered list of candidates to action, one per /ds-update-agentic-engineering invocation - see Step 4]
```

## Step 2 - Present to user and collect decisions

After the analyst returns, the conductor:

1. Reads the proposal file.
2. Presents inline: candidate count by confidence tier, top 3 candidates with one-line description each, and the full proposal file path.
3. Waits for explicit user approval of SPECIFIC candidates before moving to Step 4. The user may approve a subset, defer others, or reject all.

Do not proceed to Step 4 without a clear "approve candidate X" (or equivalent) from the user.

## Step 2.5 - Record ledger entries

For every candidate the user decided on in Step 2 (approved-pending-action, explicitly deferred, or rejected - not candidates the user left unaddressed), record a ledger entry. This is a shippable tracked-file write (the ledger is a tracked file per Step 0.5's resolution), so it must be delegated, not conductor-written directly:

Spawn a worktree-isolated `engineer` (Trivial risk - markdown append plus a JSON field update, no logic) on a branch named `chore/pruning-ledger-YYYY-MM-DD` (substitute today's date), branched from `origin/main`, briefed to:

1. Append one `## PL-YYYYMMDD-N` entry per decided candidate to the resolved ledger file, using the schema documented in that file's own header - `Status: RAISED` for approved-pending-action or explicitly-deferred candidates, `Status: REJECTED` (with `Disposition:` carrying the user's stated reason and today's date) for rejected candidates.
2. Update the resolved audit-state file's `last_run` field: `{"command": "ds-prune-harness", "date": "YYYY-MM-DD", "model_self_reported": "<this session's self-reported model string>", "note": "self-reported by the conductor session that ran the audit; not independently verified"}`.
3. Commit both changes together with DCO sign-off, push, open a PR.

Standard 1 code-owner approval on this PR - no Skeptic loop at this tier (Trivial).

**Carry-over, stated explicitly:** any candidate left `RAISED` after this step (approved-pending-action or deferred, not yet `ACTIONED`) resurfaces at the top of the next `/ds-prune-harness` run's proposal per Step 0.5's carry-over read - it does not sit silently until someone remembers to re-run the audit.

## Step 3 - (deliberately not automated)

There is no Step 3 that runs automatically. The proposal is a human-reviewed artifact. Each approved candidate moves to Step 4 individually.

## Step 4 - Action approved candidates

**One `/ds-update-agentic-engineering` invocation per approved candidate.** Each deletion gets its own Worker + Skeptic cycle.

If the user approves N candidates, the conductor runs `/ds-update-agentic-engineering` exactly N times, one per candidate, sequentially. Each call gets its own Worker spawn for the specific deletion, its own Skeptic review on the single-file diff, and its own commit. Batching deletions into a single Worker scope collapses the per-deletion review gate and is prohibited.

**Why this matters:** each deletion is an independent content decision. A Skeptic reviewing a single-file, single-deletion diff can check that nothing else references the deleted rule. A Skeptic reviewing 5 deletions at once has scope bleed and may miss cross-references.

**Close the ledger entry in the same PR diff as the deletion.** Each `/ds-update-agentic-engineering` spawn brief for a candidate that has a ledger entry (Step 2.5 will have recorded one as `RAISED` for every approved candidate) must include that candidate's ledger ID and instruct the engineer to flip the entry to `Status: ACTIONED` with `Disposition: <this PR's URL>` **in the same PR diff as the deletion itself** - not a separate follow-up commit. This is what closes the write-only-graveyard risk: the Skeptic reviewing the deletion diff necessarily reviews the ledger update in the same review pass, so a `RAISED` entry can only reach `ACTIONED` via a PR a Skeptic already gated.

## docs/planning/ - Vercel note

`docs/planning/` is inside the Vercel static deploy tree. Proposal files written there will be published to the deployed site. This is intentional - the pruning audit trail is a design artifact. If the deployed site's nav does not link `docs/planning/`, the files are accessible only by direct URL. Do not treat proposal files as sensitive.

If you want to avoid publishing a given proposal, move or delete the file from `docs/planning/` before deploying - but this is optional and not required by default.

## Risks and failure modes

- **Over-pruning (analyst flags an active, necessary rule):** mitigated by per-candidate user approval and a fresh independent Skeptic on each `/ds-update-agentic-engineering` deletion. The Skeptic's cross-reference check is the last line of defense.
- **Under-pruning (0 candidates):** a valid output. The proposal must state that all signals were applied and explain which signals were checked. Silently returning an empty proposal without rationale is not acceptable.
- **False-positive on Signal 3 (intentional duplication flagged):** the signal explicitly lists the cross-reference exception. If the analyst flags a known intentional duplicate, it is a proposal error - reject the candidate in Step 2.
- **Signal 6 subjectivity:** clamped to "consider simplifying" suggestions only, never outright deletion proposals. Human judgment is required; the analyst is not authorized to propose deletion on Signal 6 alone.
