# The Skeptic Protocol — Adversarial Review Methodology

## 0. Risk Assessment

Before starting any task, the main agent performs a brief risk assessment. The primary outcome is **Low** or **Elevated**. An optional **Elevated + Cleanup** tier extends the Elevated path with a `/simplify` cleanup pass and narrow-scope second review for substantial implementations (see Section 12).

### Risk signals

**Elevated → Full Adversarial Review (Worker + fresh independent Skeptic)**
Any single signal triggers:
- Security / auth / crypto / payments / secrets
- Irreversible operations (deletes, migrations, schema changes, force pushes)
- Architecture decisions that constrain future choices
- Modifies protocol or infrastructure files
- Production or shared state
- Multi-file changes
- New file creation
- Touches external APIs or services
- Unfamiliar codebase area
- Logic with emergent/non-obvious cross-component interactions
- User signals high stakes ("production", "critical", "don't mess this up")
- Configuration changes
- Research that produces a document, recommendation, plan, or anything to be acted on
- Changes to shared utilities, helpers, or abstractions used across many call sites (single-file but high blast radius)
- Anything where a mistake costs time or data

**Low → Light Touch (direct action, brief inline self-check)**
None of the above:
- Single file, well-understood change in familiar code
- Clearly reversible (e.g., file edits that haven't been committed or pushed, reads with no writes)
- Exploration / research / draft work — **only when the output is understanding, not a decision-driving artifact.** If the research will produce a document, recommendation, plan, or anything that drives a subsequent decision or action, it is Elevated, not Low.
- Read operations with minor targeted edits
- **Targeted wording fix to already-reviewed content** - a change that adjusts phrasing only, where the substance was already reviewed and approved (e.g., syncing parallel descriptions, adding a clarifying phrase to an existing enumeration, fixing ambiguous wording). Applies only when the content being adjusted has already passed Skeptic review in the current or a recent session. Overrides the "new file creation" and single-file edit Elevated signals for this case only. Does not override the "modifies protocol or infrastructure files" Elevated signal - wording fixes in protocol or infrastructure files remain Elevated regardless. Does not apply to new decisions, new recommendations, or new content not previously reviewed.
- **File renaming** (renaming or moving files via `git mv` or equivalent, with no content changes to any file - neither the renamed file nor any other file; overrides the "new file creation", "multi-file changes", and "Bash with side effects" Elevated signals for this case only; does not override the "modifies protocol or infrastructure files" Elevated signal - renaming protocol or infrastructure files remains Elevated regardless; if any other files reference the renamed path - imports, cross-references, config entries - the operation is Elevated because those reference updates constitute content changes in other files; if the file's name or path has behavioral significance by convention - framework routing (e.g., Next.js page files), auto-discovery (e.g., Jest test globs, webpack entry points), config naming conventions (e.g., `next.config.js`, `__init__.py`) - the operation is Elevated because the rename changes behavior without changing file contents).

**Uncertainty rule:** When in doubt, classify as Elevated. "Looks simple" is not a Low signal.

**Letter equals spirit rule:** Violating the letter of these rules is violating the spirit of these rules. There is no valid interpretation of a rule that permits bypassing it. "I followed the intent" after skipping a required step is not a defense - the steps exist because intent alone does not catch errors. This principle applies to every rule in both protocols.

**Mid-task reclassification:** If a task initially classified as Low reveals Elevated signals during execution, stop, reclassify as Elevated, and apply adversarial review from that point.

**Low risk self-check:** After completing the change, re-read it in full. Verify: (1) the change does exactly what was intended, (2) no obvious edge cases or errors are introduced, (3) no unintended side effects are present. If any concern arises during self-check, reclassify as Elevated and apply adversarial review.

### Common rationalizations to reject

| Rationalization | Why it fails |
|---|---|
| "This looks simple, I can do it directly." | "Looks simple" is not a Low signal. Simple-looking tasks are where unreviewed errors accumulate most often. |
| "I'm following the spirit of the rule, just not the letter." | Violating the letter is violating the spirit. No exceptions. |
| "It's only one file / a few lines." | Line count is not a risk signal. A one-line change to a shared utility has high blast radius. |
| "I already reviewed it myself." | Self-review is the direct-action self-check for Low risk. It does not substitute for Skeptic review on Elevated tasks. |
| "The Skeptic will catch any mistakes." | The Skeptic reviews Worker output. It does not excuse skipping risk classification or spawning a Worker. |
| "We're moving fast, we can skip review this time." | The protocol exists precisely for times when moving fast creates pressure to skip it. Speed is not a Low signal. |
| "This change is too minor to bother with a Worker." | Delegate on risk signals, not on size. The Worker overhead is small; the cost of an unreviewed error is not. |
| "I ran the tests myself, I don't need a Skeptic" | Valid only when the tight-fix path declaration was made with all 6 checklist items ticked AND the Worker's pre-commit test verification sequence passed. Outside that declared sub-path, tests passing is not a substitute for Skeptic review. The tight-fix path is a narrow declared opt-in, not a general permission to self-verify. |

### Approach by risk level

| Level | Delegation | Review | Declaration |
|---|---|---|---|
| Low | Direct action | Brief inline self-check | Silent |
| Elevated | Worker | Fresh independent Skeptic | Stated before starting |
| Elevated + Cleanup | Worker | Skeptic → `/simplify` → Skeptic (narrow) | Stated before starting |

### Declaration format

When classifying as Elevated, the main agent declares before acting:

```
Risk: Elevated - [specific signal]
Applying adversarial review.
```

---

## 1. Overview

The Skeptic Protocol is an adversarial review loop for multi-agent systems. A Worker implements; the primary agent spawns a fresh Skeptic to critique; if findings remain, the primary agent routes them to a new Worker. The primary agent drives the loop until a clean sign-off is achieved.

The core thesis: **the value of an adversarial reviewer is independence**. A reviewer who has already heard the implementer's justifications is no longer independent — they have been partially anchored to that framing. This is why the Skeptic is always a fresh invocation, never a continuation of a prior round. Workers cannot spawn subagents (platform constraint), so the primary agent is the sole orchestrator: it spawns Workers, spawns Skeptics, and routes findings between them. The Skeptic's independence is guaranteed by its fresh context — it sees only the output and the adversarial brief, never the Worker's reasoning process.

This pattern is applicable to any multi-agent system capable of invoking subagents or secondary model calls. The terminology used here is system-agnostic.

**Document hierarchy:** This is the canonical specification for The Skeptic Protocol. `~/.claude/CLAUDE.md` contains inline risk classification rules and a delegation decision table; procedural details are read from this document via trigger-condition pointers. When documents diverge, this document governs.

---

## 2. The Core Loop

**Architecture note:** Workers cannot spawn subagents — the Task tool is available only to the main (primary) session agent. This means the Skeptic loop is orchestrated by the main agent, not the Worker. Workers implement and return; the main agent handles review.

### Step-by-step

0. **Assess risk.** If Low, act directly with a brief inline self-check. If Elevated, declare the risk signal and proceed with the loop below.

1. **Primary agent spawns Worker** (background, general-purpose) with:
   - The task description and all relevant context
   - The adversarial brief verbatim (see Section 7)

2. **Worker implements** the task fully and returns its output to the primary agent.

   **If the Worker returns NEEDS_CONTEXT or BLOCKED (Step 2 variants):**
   - `NEEDS_CONTEXT`: the Worker could not proceed because specific information is missing. The primary agent determines whether that context can be obtained (from the codebase, prior session context, or the user). If it can: re-spawn the Worker with the missing context provided. If it cannot: escalate to the human with the Worker's stated gap.
   - `BLOCKED`: the Worker hit a hard blocker requiring an architecture decision or human judgment. Escalate immediately to the human with the Worker's blocker description. Do not spawn a Skeptic on incomplete work.
   - `DONE_WITH_CONCERNS`: proceed with Skeptic review as normal. The Worker's stated concerns become additional context for the Skeptic - surface them in the spawn prompt alongside the adversarial brief.

3. **Primary agent spawns a fresh Skeptic** (background, using the `skeptic` agent at `~/.claude/agents/skeptic.md`) with:
   - The adversarial brief verbatim
   - The Worker's complete output (inline or as file paths)
   - The resolved issues preflight list (empty on round 1; see Section 4)

   The agent file owns the classification rules, evaluation process, and sign-off format. The orchestrator's job is to supply the brief, the preflight list, and the artifact to review.

4. **Primary agent reads the Skeptic's findings.**
   - If no Critical or Major findings: sign-off is achieved.
     - If no Minor findings: report back.
     - If Minor findings are present: spawn a general-purpose agent (background) to apply them, passing the list of Minor findings and the relevant file paths. No follow-up Skeptic is required - Minors are by definition low-impact, and the Skeptic's classification already identified the issue. This applies regardless of file type; Minor-fix Workers are an intentional exception to the "modifies protocol or infrastructure files" Elevated signal. For Elevated + Cleanup tasks, run the Minor-fix agent before invoking `/simplify`. Wait for it to complete, then report back.
   - If Critical or Major findings remain: route them to a Worker.

5. **Primary agent spawns a new Worker** with:
   - The original task
   - The Skeptic's findings
   - The prior Worker's output (for context)
   - The session context

6. **Worker addresses findings** — fixes each Critical or Major finding, or documents a specific reason why it is not a real problem — and returns the revised output.

7. **Primary agent updates the resolved issues preflight list** with each addressed finding and its resolution.

8. **Primary agent spawns a NEW fresh Skeptic** — never a continuation of the prior Skeptic — with the revised output, the same adversarial brief, and the updated preflight list.

9. **Repeat steps 4–8** until the Skeptic grants sign-off:
   > "No unresolved Critical or Major findings. Sign-off granted."

10. **QA gate check (conditional).** After sign-off is granted and any minor fixes are applied, the conductor checks the QA gate condition (see agent-methodology.md QA Gate section). If the project has qa.md (resolved via `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback) with trigger patterns matching the diff, spawn `qa-engineer` before reporting back. QA failure routes back to an engineer for fixes, then re-runs QA. If no QA gate applies, proceed directly to step 11.

11. **Primary agent reports back** with:
    - The final implementation
    - The full exchange log (round-by-round: findings, fixes, deferrals with reasoning)
    - The verbatim sign-off statement from the final Skeptic round
    - QA result (pass/fail) if the QA gate was triggered

---

## 3. State Management Rules

| Agent | Continuation rule | Rationale |
|---|---|---|
| Worker | New spawn each round — receives accumulated context via prompt | Cannot maintain context across invocations; the primary agent passes findings and prior output explicitly |
| Skeptic | Always a fresh invocation — never continued from a prior round | Needs adversarial independence; prior-round context anchors the reviewer |

**Violation of the Skeptic freshness rule degrades the protocol.** A Skeptic that has already heard the Worker's justifications will unconsciously apply lower scrutiny in subsequent rounds. Independence requires a clean context.

**Primary agent context accumulation:** The primary agent maintains the exchange log across rounds. When spawning each new Worker, it passes: the original task, the current Skeptic findings, the prior implementation output (or file paths to it), and the accumulated exchange log. Workers must not be expected to maintain state across invocations — the primary agent is the stateful coordinator.

**Worker output management:** For implementations producing large outputs, Workers should write results to files and return file paths rather than inline content. This keeps spawn prompts manageable and prevents context degradation from accumulating full implementation text in the exchange log.

---

## 4. The Resolved Issues Preflight List

Before invoking each new Skeptic (rounds 2+), the primary agent prepends this block to the adversarial brief:

```
The following issues were identified and resolved in prior rounds. Do not
re-raise them unless you believe the resolution is genuinely insufficient:

[C1: <description of finding> → <resolution applied>]
[C2: <description of finding> → <resolution applied>]
[M1: <description of finding> → <resolution applied>]
...
```

The preflight list prevents the Skeptic from re-raising already-addressed findings as new Critical or Major items. It does not prevent the Skeptic from contesting a resolution — if the Skeptic believes a stated resolution is insufficient, it may re-raise the finding with an explicit explanation of why.

**Loop context extension:** When the Skeptic is invoked inside the `/implement-ticket` persistence loop, the conductor passes the findings_log entries (status=open or status=addressed) as the preflight list. The findings_log id field is used as the finding identifier for `[PREV: <id>]` tagging. The preflight list format is identical to the standard Section 4 format; the findings_log schema is the structured backing store.

---

## 5. Escalation Protocol

If the same finding is contested for **2 or more re-routes** without resolution, the primary agent must stop and escalate to a human operator with:

```
Unresolved after N re-routes. Contested finding: [exact finding text].
Worker position: [Worker's documented reasoning for deferral].
Skeptic position: [Skeptic's repeated objection].
Human decision needed.
```

The primary agent tracks contested findings across rounds. After 2 re-routes on the same finding without resolution, it stops routing and escalates. This prevents infinite loops on genuinely ambiguous findings.

**Re-route counter:** The primary agent tracks each finding by its text across all rounds. If the same finding appears in 2 or more Skeptic responses without the Worker resolving it (regardless of whether the rounds are consecutive), the re-route limit is met and the finding must be escalated. Use the finding's text as the identifier.

### Complexity-based round limit

The number of permitted Skeptic rounds scales with task complexity:

- **Simple/targeted changes** (single-file, narrow edit, clearly bounded scope - e.g., a wording fix, a one-sentence addition, a single-function change): Skeptic loop is capped at **1 round**. This overrides the 2-re-route rule above for this category. If the Skeptic raises Critical or Major findings after round 1, escalate directly to the human rather than spawning another Worker. The human decides whether to fix and re-review or accept as-is.
- **Standard Elevated changes**: the 2-re-route rule above applies - if the same finding appears in 2 or more Skeptic responses without resolution, escalate to the human.

**Uncertainty rule for categorization:** When the scope of a change is ambiguous - i.e., it is not obviously a single narrow edit - apply the standard Elevated round limit (the 2-re-route rule). "Looks simple" is not a sufficient basis for the simple/targeted category. This mirrors the Low/Elevated uncertainty rule above.

**Loop contract override:** When operating inside the `/implement-ticket` persistence loop (Phase 6), the loop contract overrides this rule. One re-raise after a claimed fix (convergence failure as defined in the loop contract) is sufficient to trigger escalation. The loop already consumes iteration budget on each fix pass; requiring a second re-raise would waste an additional pass on a finding the Engineer has already failed to address. Outside the loop context (ad-hoc Skeptic re-routes not inside a named loop), the 2-re-route rule applies unchanged.

### Worker decomposition rule

If a Worker discovers mid-task that its work requires decomposition into independent sub-tasks, it should note this and return its partial output with an explicit decomposition request. The primary agent then handles parallel decomposition — spawning multiple Workers and synthesizing results — before routing the assembled output back through Skeptic review.

---

## 6. Findings Classification

**Critical** — Blocks sign-off. Must be resolved before sign-off can be granted. Examples: security vulnerabilities, correctness failures, data loss paths, unauthorized access vectors.

**Major** — Should be fixed. Blocks sign-off unless the Worker provides a compelling documented reason to defer. Examples: missing error handling on critical paths, edge cases that cause silent failures, design issues that will be expensive to fix later. Also Major: the Worker deferred a decision it had sufficient context to make — i.e., punted to the main agent or the Skeptic on a question the spec, requirements, or available information already resolved. Workers must make decisions when they have the context to do so; using adversarial review as a substitute for deciding is a Major deficiency.

**Minor** — Optional. Never blocks sign-off. When Minor findings are present at sign-off, the primary agent spawns a general-purpose agent (background) to apply them - no follow-up Skeptic review is required, regardless of file type. Minor-fix Workers are an intentional exception to the "modifies protocol or infrastructure files" Elevated signal. Examples: style improvements, non-critical logging gaps, minor documentation issues, low-impact optimizations.

The Skeptic must classify every finding. Unclassified findings are treated as Major by default.

**Spec deviation is a finding.** When a Worker implements against an Architect plan, any deviation from the plan's "API / interface design" section is a Skeptic finding. Classify as **Major** by default (the spec was the contract; the Worker did not honor it), or **Critical** if the deviation changes externally observable behavior, breaks a caller, or introduces a security/correctness regression. A documented Worker deviation with explicit rationale may downgrade to Minor, but only if the Skeptic can affirmatively state all three of the following in its sign-off: (1) the Worker's stated rationale for the deviation is technically correct - the Skeptic has verified the claim of infeasibility, conflict, or impracticality, not merely accepted the Worker's assertion; (2) the plan's downstream assumptions still hold under the deviation - no other part of the plan depends on the original spec in a way the deviation breaks; (3) the deviation does not change externally observable behavior, break a caller, or introduce a security/correctness regression - if any of these are present, the finding is Critical, not Minor. If the Skeptic cannot affirmatively state all three, the finding remains at least Major. Silent deviation is never acceptable - the Worker must state the deviation explicitly regardless of rationale. See Section 11 for the mandatory sign-off format when a spec deviation is downgraded.

When reviewing, check spec compliance first - does the implementation do what was asked? Then check code quality. Surface spec compliance issues before stylistic concerns in the findings list. Spec compliance gaps at the Critical or Major level make code quality moot.

### Review depth

Adversarial review applies whenever risk is classified as Elevated. The main agent always uses a fresh independent Skeptic — there is no degraded self-review path for Elevated work. The exchange log is mandatory for all Elevated tasks. The escalation protocol is active for all Elevated tasks.

---

## 7. The Adversarial Brief Requirement

The adversarial brief defines the threat model the Skeptic must adopt. It is written by the primary agent (or human operator) and must be passed to the Worker verbatim.

**The primary agent must use the brief verbatim when invoking each Skeptic. The primary agent must not soften, summarize, or editorialize the brief.** The brief is an instruction to the Skeptic, not a suggestion. Softening it degrades adversarial independence.

The brief should be specific to the domain and threat model of the work being reviewed. Generic briefs produce generic findings.

**Brief extension:** The primary agent may extend a template brief with domain-specific additions: *"In addition to the above, also consider: [domain-specific concerns]."* The primary agent must never remove or soften any language from the selected template. Extension is additive only.

**Active search requirement:** The Skeptic agent enforces this internally - Step 5 of its evaluation process is a brief coverage check, and the required "Active search:" line is part of its sign-off format. The orchestrator does not need to inject this instruction. Providing the adversarial brief is sufficient - the agent applies it actively by design.

---

## 8. Domain-Specific Adversarial Brief Templates

These are starting templates. Adapt them for your specific domain, threat model, and implementation.

**Smart contracts:**
> "A financially motivated attacker has the source code and will look for: reentrancy, access control gaps, signature replay attacks, fee bypass, and any path to transfer an asset without valid authorization. Assume the attacker will read every public function, every state variable, and every event. Assume they will attempt direct contract interaction, bypassing any app-layer controls."

**Authentication and session management:**
> "An attacker controls one compromised account and one compromised device. What can they access, modify, or forge? Look for: session fixation, token replay, insufficient binding between session and device, privilege escalation paths, and any state the server trusts without re-verifying."

**API endpoints:**
> "An attacker can send arbitrary HTTP requests including malformed inputs, missing fields, oversized payloads, replayed tokens, and concurrent requests designed to hit race conditions. Look for: missing input validation, authentication that can be bypassed, rate limiting gaps, and any endpoint that mutates state without idempotency guarantees."

**Cryptographic verification:**
> "An attacker will try to produce a valid-looking signature without the private key. They will also try replay attacks with previously valid signatures. Look for: weak randomness in nonce generation, missing domain separation, algorithm confusion attacks, and any verification path that skips a check under certain conditions."

**DB schema, migrations, and data models:**
> "Is the migration idempotent — what happens if it runs twice? What is the state of the data after partial failure, and can it be recovered without data corruption? Look for: double-run risk (non-idempotent operations), partial failure paths (what if the migration fails halfway?), data loss risk (irreversible column drops, non-nullable additions to tables with existing data), and rollback path (is there a down migration, and is it tested?)."

**Data pipelines and async jobs:**
> "What happens if this job runs twice? What happens if it crashes halfway? What is the state after partial failure, and can it be safely retried without double-processing or data corruption? Look for: non-idempotent operations, missing rollback logic, state that can diverge between systems, and silent failure modes."

**Document synthesis, architecture, and planning:**
> "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?"

**General code review:**
> "Assume this code will be deployed to production and maintained by engineers who did not write it. Find: logic errors, edge cases that cause silent failures, missing error handling, incorrect assumptions about input ranges or ordering, and any assumption that will break under realistic load or adversarial input."

**When reviewing a Worker that implemented against an Architect plan:** In addition to the above, verify that the Worker's output matches the plan's "API / interface design" section exactly. Any deviation is a finding (Major by default, Critical if behavior-changing). A deviation may downgrade to Minor only if the Skeptic can affirmatively state all three criteria in its sign-off: (1) the Worker's rationale is technically verified (not just accepted); (2) no downstream plan assumptions are broken by the deviation; (3) the deviation does not change externally observable behavior, break a caller, or introduce a security/correctness regression. If all three cannot be stated affirmatively, the finding remains at least Major. Silent deviation from the spec is always at least Major.

---

## 9. Primary Agent Orchestration Posture

The primary agent's role is coordination, not implementation. It stays available and responsive at all times. It delegates non-trivial work to Workers and orchestrates Skeptic review of the results.

**The primary agent drives the Skeptic loop.** It spawns Workers, reads their output, spawns fresh Skeptics, reads their findings, and routes findings back to Workers. This is conductor work — the primary agent does not implement, but it does actively manage the review cycle.

**The primary agent never implements directly** unless the task is Low risk: a single-file read, a one-line edit, a factual answer retrievable from memory without any risk of error.

**Multiple Workers can run concurrently** on independent tasks. The primary agent tracks their state and synthesizes results when they return. Concurrency is the primary performance lever — use it whenever tasks are independent.

**The primary agent is a conductor, not an implementer.** Its value is in decomposing work correctly, writing precise adversarial briefs, routing findings accurately, and making good decisions when escalation is required. It should resist the temptation to implement directly even when implementation looks simple - simple-looking tasks are often where unreviewed errors accumulate.

### Review scope: decompose implementation, not review

Workers are decomposed into focused atomic units ("one agent, one task, one prompt"). Skeptic review is scoped differently - for effectiveness, not for symmetry with Workers:

- **Independent elevated units:** one Skeptic per unit. The diff is small, review is fast, findings are high-signal.
- **Interdependent elevated units** (cross-file or cross-component consistency required): one Skeptic reviewing the combined diff from all related Workers. This integration Skeptic replaces per-unit Skeptics for these units. The most dangerous bugs emerge from interactions between components - a per-unit Skeptic cannot see them.
- **Low-risk units:** no Skeptic. Direct action with self-check.

The integration Skeptic receives the same adversarial brief (Section 7) and follows the same sign-off format (Section 11). The only difference is scope: it reviews the combined output of multiple focused Workers rather than a single Worker's output.

---

## 10. When to Use This Protocol

Use The Skeptic Protocol whenever risk is classified as Elevated (see Section 0). Especially:

- **Anything hard to reverse:** deployed smart contracts, database schema migrations, published API contracts, auth system changes.
- **Anything cryptographic:** signature schemes, key derivation, nonce generation, verification logic.
- **Anything with concurrent state:** async jobs, event queues, multi-step transactions, distributed state that can diverge.
- **Anything at a trust boundary:** user input handling, external API integration, permission checks, session management.
- **Any implementation where a silent failure would not be immediately visible:** background jobs, data pipelines, audit log writes.

Do not use it for Low risk work: reading a file, answering a factual question, renaming a variable, renaming or moving a file (unless it is a protocol or infrastructure file, unless other files reference the renamed path, or unless the file's name or path has behavioral significance by convention), or any task where the output is immediately and obviously verifiable by inspection.

---

## 11. Output Format

### Worker output (each round)

Each Worker invocation returns:

**1. Final implementation** — the complete revised output. Not a diff. The full artifact, or file paths to it if the output is large. If the Worker cannot return a complete implementation, it returns a status of `NEEDS_CONTEXT` or `BLOCKED` (as defined in the engineer agent) instead. Section 2 defines the conductor's response path for each of these statuses.

**2. Round summary** — what was changed and why, for the primary agent's exchange log:
```
Changes made:
  C1 (finding title) → fixed by [description of fix]
  M1 (finding title) → fixed by [description of fix]
  M2 (finding title) → deferred: [documented reasoning]
```

### Skeptic output (each round)

The structured sign-off format is required for every Skeptic response, whether findings exist or not:

```
Reviewed: [list of components/aspects examined]
Findings: Critical: N, Major: N, Minor: N — or "No findings."
[List any findings with classification]
[If any Minor finding is a spec-deviation downgrade, include the three-criterion "Spec deviation downgrade justification" block here - see format below]
Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.
No unresolved Critical or Major findings. Sign-off granted.
```

When any Minor finding is a spec-deviation downgrade, the following block must also appear in the sign-off, once per downgraded finding:

```
Spec deviation downgrade justification (if any Minor finding is a spec deviation):
For [finding ID]:
(1) Worker's rationale verified: [specific verification the Skeptic performed]
(2) Downstream plan assumptions preserved: [confirmation no other plan element depends on the original spec in a way the deviation breaks]
(3) No externally observable behavior change, broken caller, or security/correctness regression: [affirmative statement]
```

The "Reviewed" and "Active search" lines are mandatory even when findings are zero — they are evidence that review occurred.

### Primary agent exchange log

The primary agent accumulates the exchange log across all rounds:

```
Round 1:
  Skeptic findings: [C1: ..., M1: ..., Minor: ...]
  Worker actions: [C1 fixed by ..., M1 fixed by ..., Minor: deferred, low priority]

Round 2:
  Skeptic findings: [M2: ...]
  Worker actions: [M2 fixed by ...]

Round 3:
  Skeptic findings: none
  Sign-off granted.
```

### Sign-off validation

The primary agent treats a Skeptic response as a valid sign-off only when it contains all four mandatory elements as distinct lines: (a) a line beginning "Reviewed:", (b) a line beginning "Findings:", (c) an "Active search:" line, and (d) the phrase "No unresolved Critical or Major findings. Sign-off granted." A response containing only the phrase "Sign-off granted" without the other three elements is format-noncompliant and triggers a format re-invocation (spawn a new Skeptic with explicit format instructions). This re-invocation is not counted as a new adversarial round. (e) Conditionally: if any Minor finding in the Findings list is marked as a spec-deviation downgrade, the sign-off must also contain the three-criterion enumeration block specified above for each such finding. A sign-off that omits this block when required is format-noncompliant and triggers the same format re-invocation.

**Format re-invocation limit:** Format re-invocations are limited to 3 attempts. If the Skeptic's response remains format-noncompliant after 3 re-invocations, the primary agent escalates to the human with the last Skeptic response verbatim.

**Irreversible changes:** Workers must not apply irreversible changes before the primary agent has confirmed Skeptic sign-off. The sole exception is the Elevated (tight-fix path) sub-path defined in `agent-methodology.md`: when a tight-fix path declaration is made with all 6 checklist items ticked AND the engineer Worker's pre-commit test verification (BASELINE -> APPLY -> VERIFY) passes, the Worker may commit without prior Skeptic sign-off. Any failure in the verification sequence reverts to the standard rule - the Worker does NOT commit, returns the uncommitted diff, and the conductor spawns a Skeptic on the uncommitted diff. Workers that must stage irreversible changes as part of implementation must write a revert procedure in their return output before applying those changes. If the Skeptic subsequently flags Critical issues, the primary agent instructs the Worker to execute the revert procedure before further changes.

---

## 12. The Cleanup Path (`/simplify` Integration)

The standard Elevated workflow (Worker → Skeptic) is the default for all Elevated tasks. The **Elevated + Cleanup** tier extends this workflow with an automated cleanup pass and a narrow-scope second review. It is reserved for substantial implementations where code hygiene matters.

### Workflow

```
Worker → Skeptic (sign-off) → /simplify → Skeptic (narrow scope)
```

1. The Worker implements the task and returns its output.
2. The primary agent spawns a fresh Skeptic for adversarial review (standard Elevated flow).
3. After Skeptic sign-off is achieved, the primary agent invokes `/simplify` on the implementation. `/simplify` is a bundled Claude Code skill — no installation or setup needed. It spawns three parallel review agents (code reuse, code quality, efficiency), reads recently changed files, aggregates findings, and applies fixes automatically. An optional focus can be provided: `/simplify focus on memory efficiency`.
4. After `/simplify` completes, the primary agent spawns a **second Skeptic** with a narrow scope — it reviews only the `/simplify` diff, not the full implementation.

### Trigger signals

Use Elevated + Cleanup when the implementation is substantial enough that code hygiene becomes a real concern:

- **Multi-file feature implementations** — not just multi-file config changes or renames, but implementations that introduce meaningful new logic across files
- **Significant new code volume** — the Worker created substantial new logic, not just wiring or boilerplate
- **Unfamiliar codebase area** — the Worker may have missed existing patterns, utilities, or abstractions to reuse
- **User explicitly requests polish or quality focus** — e.g., "make sure this is clean", "production quality"

When none of these signals are present, use standard Elevated (Worker → Skeptic). The cleanup path is the extended option, not the default.

### Second Skeptic adversarial brief

The second Skeptic receives a narrow behavioral-preservation brief, not a full architectural audit:

> "Here is the code before and after `/simplify` cleanup. Did the cleanup preserve behavior? Did it introduce any defects? Focus on: behavioral equivalence, accidental deletion of logic or error handling, changed control flow, and any semantic differences between the before and after versions. This is a focused behavioral preservation check — do not re-audit the full implementation."

The second Skeptic uses the same sign-off format (Section 11) and the same findings classification (Section 6). The same escalation rules apply if Critical or Major findings are raised.

### Declaration format

When classifying as Elevated + Cleanup, the main agent declares before acting:

```
Risk: Elevated + Cleanup - [specific signal]
Applying adversarial review with /simplify cleanup pass.
```
