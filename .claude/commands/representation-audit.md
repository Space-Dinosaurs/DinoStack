> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /representation-audit

> Run the Activation preflight from `agent-methodology.md` before proceeding. If inactive, no-op and exit.

Performs a periodic prose quality pass over methodology files to surface Python-shaped writing and propose cleaner natural-language rewrites.

**When to use:** After any substantial methodology addition, or quarterly. This command is analysis only. It writes a rewrite proposal document and stops. No methodology files are changed. Actual rewrites go through `/update-agentic-engineering` separately, one candidate at a time.

**Do not use to:** make changes, validate a specific rule's wording, or replace editorial judgment. The output is a proposal, not a verdict.

**Motivation:** NLH's 2024 result showed that rewriting harness logic into structured natural language lifted OSWatch performance from 30.4% to 47.2%. Representation is a performance lever. Dense exception chains, nested conditional prose, and imperative pseudocode increase the probability that a model parses the structure correctly but applies the wrong meaning. This command applies representation improvement as a maintenance pass.

## Safety model

The audit analyst Worker is instructed not to write to `content/` and to restrict writes to the single output path in `docs/planning/`. This is enforced by Worker brief compliance, NOT by a harness-level technical barrier. The `tool_scope` field in the execution contract is documentation only - per the Worker preamble section of `agent-methodology.md`, it does not physically prevent writes. The analyst is instructed not to write to `content/`, and any violation would surface as a diff the conductor rejects before moving to Step 4. The authoritative gate is the meaning-preservation Skeptic review on each subsequent rewrite via `/update-agentic-engineering`. Do not describe this mechanism as "physically cannot edit" - it cannot and does not make that guarantee.

## Step 0 - Preflight git sync

Run the Step 0 preflight from `/update-agentic-engineering` verbatim (fetch origin, check clean tree, check divergence, refuse dirty tree). Git state decisions require main-agent judgment; do not delegate this step.

## Step 1 - Spawn the audit analyst

Spawn a single `general-purpose` Worker in background with the following execution contract (NLH format per `agent-methodology.md`):

*"You are a Worker agent. Produce a representation audit proposal for the agentic-engineering methodology corpus and return your complete output. The main agent will present the proposal to the user for approval."*

- outputs: a rewrite proposal document written to `docs/planning/representation-audit-YYYY-MM-DD.md` (substitute today's date)
- budget: ~50 tool calls
- tool_scope: Read, Glob, Grep, Write (Write restricted to the single output path - documentation only, Worker brief compliance)
- completion_conditions: all files under `content/rules/` and `content/references/` read in full; 7-signal checklist applied to each file; 3-10 highest-impact rewrite candidates identified and ranked by read-frequency and signal-intensity; proposal written using the template below; no `content/` file modified; if fewer than 3 candidates pass HIGH or MEDIUM priority after applying all signals, the proposal still writes and states this explicitly with rationale - silently returning an empty proposal without rationale is not acceptable
- output_paths: `docs/planning/representation-audit-YYYY-MM-DD.md`

Pass the signal checklist verbatim in the spawn prompt (see Signal Checklist below). The analyst applies the checklist file-by-file and writes candidates to the output document rather than holding all findings in memory.

## Signal checklist (verbatim - this is the binding contract)

The analyst applies each signal to every file in scope and flags candidates as they are found. Candidates are ranked by read-frequency (files loaded on every task rank higher) and signal-intensity (how many signals fire in the same block and how densely). No signal is skipped.

**Signal R1 - long exception chains.**

Candidate if a rule is stated with 4+ qualifier clauses chained in a single sentence or paragraph ("unless A, unless B, unless C, does not apply when D..."). The structure signals a Python-shaped approach: rules are expressed by adding exception branches rather than by restating the positive principle more precisely.

Real instance to calibrate against: `agent-methodology.md` line 106, the Low signals block - the "documentation-only file creation" bullet chains six qualifiers in a single parenthetical: "new .md or .txt files that are pure lists, glossaries, or running notes - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/agentic-engineering/; overrides the 'new file creation' Elevated signal for this case only." That sentence is the calibration specimen for R1 intensity. Flag at or above that density. Confidence: MEDIUM-HIGH depending on intensity.

**Signal R2 - nested conditional prose.**

Candidate if more than two conditional branches are expressed in a single prose block without a structural separator (table, sub-heading, or bullet). The reader must hold all branches in working memory to understand any single path.

Real instance to calibrate against: `agent-methodology.md` line 106, same Low signals block - it packs four distinct direct-action overrides (documentation creation, wording fixes, file renaming, UI copy changes) into a single paragraph, each with their own conditions and carve-outs. That is the calibration specimen for R2 density. The clean spawn-threshold enumeration in the table at lines 19-49 is NOT an R2 candidate - it uses structural separation (table) correctly. Confidence: MEDIUM.

**Signal R3 - imperative pseudocode in prose.**

Candidate if prose reads like a switch statement or procedural step sequence where a structural description of the outcome would communicate the same intent more directly.

Real instance to calibrate against: `skeptic-protocol.md` Section 2 Step-by-step (lines ~93-140) - the numbered 1-through-11 loop reads procedurally, but because execution order genuinely matters here, the format is appropriate and the section is borderline. Use it to calibrate the signal's upper boundary. Flag blocks where the imperative structure obscures rather than clarifies. Confidence: MEDIUM.

**IMPORTANT non-signal - see Non-Signals section below.** The Execution Contract template in `agent-methodology.md` (the 5-field outputs/budget/tool_scope/completion_conditions/output_paths block, lines ~79-83) is a Markdown bullet list that could superficially match R3. It must NOT be flagged. Template blocks are load-bearing structured formats, not prose.

**Signal R4 - reference by code-name rather than meaning.**

Candidate if an explanatory prose sentence uses a code-name or file path where the role description or plain-language label would communicate faster to a reader who does not know the repo.

Real instance to calibrate against: `design-goals.md` line 22 - "The Subagent Protocol (`agent-methodology/subagent-protocol.md`) operationalizes this goal" - the parenthetical path reference is functional, but in a pure explanatory sentence, "the orchestration rules file" or the section heading would land faster for a first-time reader. Use this as a low-end calibration (LOW confidence). Note: proper agent names (`engineer`, `skeptic`, `orchestration-planner`) used as proper nouns in normative rules are NOT R4 candidates - see Non-Signals below. Confidence: LOW-MEDIUM.

**Signal R5 - definition by exclusion.**

Candidate if a concept is defined entirely as "when not X and not Y and not Z" without a positive anchor that states what the concept IS.

Real instance to calibrate against: `skeptic-protocol.md` lines 27-35, the Low risk definition - it opens with "None of the above:" and lists examples, but the positive definition ("direct action with a brief inline self-check") appears as a secondary label rather than the lead. Compare to the Elevated definition above it, which leads with the positive mechanism ("Full Adversarial Review: Worker + fresh independent Skeptic"). The contrast makes the R5 pattern visible. Confidence: MEDIUM.

**Signal R6 - duplicated conditional clauses.**

Candidate if the same qualifier phrase appears 2+ times in the same document where a single anchored reference would suffice. Repetition that serves a genuine cross-reference purpose is excluded (see Non-Signals).

Real instance to calibrate against: `agent-methodology.md` lines 27-29 and 106 - the phrase "does not override the 'modifies protocol or infrastructure files' Elevated signal" appears in the Documentation-only creation bullet, the targeted wording fix bullet, the file renaming bullet, and again in the Low signals paragraph. Four occurrences of the same qualifier in the same document. This is the calibration specimen for R6. Confidence: MEDIUM.

**Signal R7 - rationale buried after mechanism.**

Candidate if a rule states the imperative first and the rationale last, and the rationale is non-obvious enough that a reader encountering the rule cold would reasonably ask "why?" before complying.

Real instance to calibrate against: `agent-methodology.md` line 29, the file renaming direct-action row note: "does not apply if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the rename changes behavior without changing file contents." The mechanism (exclusion condition) comes first; the explanatory principle ("the rename changes behavior without changing file contents") comes last. For a reader unfamiliar with the pattern, leading with the principle would reduce parsing friction. Confidence: LOW-MEDIUM.

## Non-signals (explicit carve-outs)

The analyst must NOT flag the following as rewrite candidates under any signal:

**Short rules.** A rule being brief is not a signal. Brevity is correct. Do not propose expanding short rules.

**Tables.** Table format is already a clean structural representation. Converting a well-formed table to prose would be a representation regression, not an improvement.

**Fenced code blocks.** Exact-syntax examples, CLI commands, and format templates inside code fences are appropriate as-is.

**Markdown bullet lists that function as templates.** This is the key exclusion. The Execution Contract template in `agent-methodology.md` (the 5-field outputs/budget/tool_scope/completion_conditions/output_paths block around lines 79-83) and any other template block whose bullet structure is copied verbatim into agent spawn prompts or proposal documents is load-bearing structured format, NOT prose. Do not propose rewriting templates into flowing prose. The signal is "this reads like Python"; templates are not prose and cannot read like Python. This exclusion applies to any block that functions as a fill-in-the-blank form.

**Intentional cross-reference duplication.** Per the `/prune-harness` Signal 3 exception - a rule appearing verbatim in both a rule file and a command that instructs agents to follow it is load-bearing structural redundancy. The same qualifier appearing in two different rules within one document because each rule needs to be independently self-contained is also not R6 if removing the repetition would make either rule ambiguous when read in isolation.

**Proper agent names in normative rules.** `engineer`, `skeptic`, `orchestration-planner`, and other named agents used as proper nouns in normative rules are not R4 candidates. These names are the vocabulary of the protocol - rewriting them to role descriptions in normative statements would degrade precision, not improve it.

## Clean natural-language counter-examples

The analyst uses these as the positive target for proposed rewrites:

- Active voice with a concrete subject: "The conductor spawns a Skeptic after each Worker return" is cleaner than "A Skeptic is spawned by the conductor when a Worker has returned."
- Short declarative sentences with qualifiers as separate statements rather than chained parentheticals.
- Rationale before mechanism when the rationale is non-obvious: state the principle, then the rule that operationalizes it.
- Positive definitions that state what a concept IS before listing what it is not.
- Structural descriptions of outcomes rather than step-by-step procedures when execution order does not matter.

## Audit scope

**Files in scope:** all files under `content/rules/` and `content/references/`.

**Candidate count:** 3-10 total. Ranking by:

(a) **Signal intensity** - how many signals fire in the same block and how densely. A block that fires R1 + R2 + R6 simultaneously ranks above a block that fires one signal mildly.

(b) **Read frequency** - files loaded on every task rank higher than on-trigger files. Within a file, sections read on every task rank higher than sections read only when a specific protocol is triggered.

**Priority tiers:**

- **HIGH:** every-task file with 2+ signals firing in the same block
- **MEDIUM:** on-trigger file with a clear unambiguous signal, or every-task file with a mild single signal
- **LOW:** rarely-read file OR ambiguous signal where meaning-shift risk is non-trivial

Every candidate carries a priority tier and explicit rationale.

## Proposal document template

The analyst writes the proposal using this exact structure:

```
# Representation Audit Proposal - YYYY-MM-DD

## Signal summary
- Total candidates: N (H high / M medium / L low priority)
- Files read: [list]
- Signals that fired per file: [summary]
- Signals skipped or no candidates: [list with reason]

## Rewrite candidates (ranked HIGH to LOW priority)

### [Candidate title]
- File: content/path/to/file.md (lines N-M)
- Current form: [quoted verbatim]
- Proposed form: [quoted full rewrite]
- Signal(s): [which R1-R7 fired]
- Meaning preserved: HIGH | MEDIUM | LOW
- Risk of meaning shift: [concrete statement of what could change]
- Priority: HIGH | MEDIUM | LOW
- Priority rationale: [one sentence]

(repeat per candidate)

## Files reviewed with no rewrites proposed
[list with brief rationale per file]

## Recommended action sequence
[Ordered list, one per /update-agentic-engineering invocation]
```

## Step 2 - Present to user

After the analyst returns, the conductor:

1. Reads the proposal file.
2. Presents inline: candidate count by priority tier, top 3 HIGH-priority candidates with a one-line description each, and the full proposal file path.
3. Waits for explicit user approval of specific candidates before moving to Step 4. The user may approve a subset, defer others, or reject all.

Do not proceed to Step 4 without a clear "approve candidate X" (or equivalent) from the user.

## Step 3 - (deliberately not automated)

There is no Step 3 that runs automatically. The proposal is a human-reviewed artifact. Each approved candidate moves to Step 4 individually.

## Step 4 - Action approved candidates

**One `/update-agentic-engineering` invocation per approved candidate.** Each rewrite gets its own Worker + Skeptic cycle.

If the user approves N candidates, the conductor runs `/update-agentic-engineering` exactly N times, one per candidate, sequentially. Each call gets its own Worker spawn for the specific rewrite, its own meaning-preservation Skeptic review on the single-file diff, and its own commit. Batching rewrites into a single Worker scope is prohibited - rationale: cross-reference scope-bleed, and each rewrite needs its own independent meaning-preservation review. A Skeptic reviewing five rewrites at once cannot give each the focused attention that a single-candidate diff enables.

**Meaning-preservation Skeptic brief (pass this verbatim in each `/update-agentic-engineering` call):**

"This is a prose rewrite of a methodology rule. Your one question: does the proposed form preserve the original rule's meaning exactly, including all boundary conditions, exceptions, and scope qualifiers? Read the current form and the proposed form side-by-side and re-derive the logical conditions from both. Verify they are equivalent. Flag any qualifier, exception, or nuance present in the original that is absent or weakened in the proposed form - even if the proposed prose sounds cleaner. A rewrite that shortens a rule by removing an important exception is a Critical finding. A rewrite that merely sounds less clean is not a finding. The goal is representation improvement, not substance change."

## docs/planning/ - Vercel note

`docs/planning/` is inside the Vercel static deploy tree (per project MEMORY.md). Proposal files written there will be published to the deployed site. This is intentional - the representation audit trail is a design artifact. If the deployed site's nav does not link `docs/planning/`, the files are accessible only by direct URL. Do not treat proposal files as sensitive.

If you want to avoid publishing a given proposal, move or delete the file from `docs/planning/` before deploying - but this is optional and not required by default.

## Relationship to /prune-harness

`/prune-harness` subtracts expired rules. `/representation-audit` rewrites dense prose into cleaner natural language. Both write to `docs/planning/`. Both route actual changes through `/update-agentic-engineering` one candidate at a time.

A rule that qualifies for both pruning and representation rewriting is first a deletion candidate - run `/prune-harness` first, since there is no point rewriting a rule you are about to delete. The representation audit simply will not include rules that have already been deleted.

## Risks and failure modes

- **Meaning shift on rewrite (primary):** the primary risk. Mitigated by the meaning-preservation Skeptic brief, per-candidate user approval, and MEDIUM/LOW confidence flags on ambiguous candidates.
- **Over-rewriting (secondary):** the analyst flags more than 10 candidates or proposes rewrites that are stylistically cleaner but not actually clearer to a model. Mitigated by the 3-10 candidate cap and the "Files reviewed with no rewrites proposed" accountability section.
- **Stylistic-cleanness trap (secondary):** rewrites that are prettier to humans but harder for LLMs to parse because they compress information or introduce ambiguity. Mitigated by the clean-NL counter-examples section emphasizing structural clarity over compression, and by the meaning-preservation Skeptic's re-derivation check.
- **Template corruption:** a rewrite proposal that converts a load-bearing template block into flowing prose. Mitigated by the explicit Execution Contract non-signal exclusion above.
