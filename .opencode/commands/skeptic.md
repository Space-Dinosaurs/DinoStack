---
description: /skeptic - The Skeptic Protocol Invocation
agent: build
---
# /skeptic - The Skeptic Protocol Invocation

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Orchestrate adversarial review for `$ARGUMENTS`. The main agent drives the loop: spawn Worker, spawn Skeptic, route findings, repeat until sign-off.

## Your job (main agent)

Tell the user: "Running Skeptic Protocol for: $ARGUMENTS. I'll report back when sign-off is achieved."

You drive the loop. Do not implement the task yourself.

---

## Step 1 - Spawn the Worker

Spawn a **background general-purpose subagent via the `Agent` tool** with this prompt (fill in bracketed sections):

---
You are a Worker agent. Implement the task fully and return your complete output. The main agent will arrange Skeptic review.

**Task:** $ARGUMENTS

**Context (REQUIRED - do not leave blank):** [Paste the relevant AGENTS.md sections, specs, schema, or file paths the Worker needs. Include the project AGENTS.md at minimum.]

**Session context:** [Paste the content of `<cwd>/.agentic/context.md`]

The adversarial brief below will be used by the Skeptic reviewing your output. Write your implementation knowing you will be evaluated against it.

**Adversarial brief:** [Select and paste verbatim from the brief selection table below.]

Implement the task fully. Return your complete output. If your output is large, write it to files and return the file paths.
---

## Step 2 - Spawn the Skeptic

When the Worker returns, spawn a **background general-purpose subagent via the `Agent` tool** using the `skeptic` agent with this prompt (fill in bracketed sections):

---
You are a Skeptic agent. Read your evaluation framework from `~/.claude/agents/skeptic.md` first - it contains your classification rules, evaluation process, and required sign-off format.

**What to review:** [Worker's complete output - paste inline or give file paths]

**Adversarial brief:** [Paste verbatim from the selection table]

**Resolved issues preflight:**
- Round 1: "No prior rounds. This is round 1."
- Rounds 2+: "The following issues were identified and resolved in prior rounds. Do not re-raise them unless the resolution is genuinely insufficient: [list each: C1/M1/etc: description - resolution applied]"

Evaluate and return your findings using the sign-off format from your agent definition.
---

The Skeptic is always a fresh spawn - never resumed, never continued from a prior round.

## Step 3 - Read findings

A valid sign-off contains all four mandatory elements as distinct lines:
- (a) a line beginning "Reviewed:"
- (b) a line beginning "Findings:"
- (c) an "Active search:" line
- (d) the exact phrase "No unresolved Critical or Major findings. Sign-off granted."

If any element is missing: spawn a new Skeptic with explicit format instructions ("Your previous response did not conform to the required sign-off format. Please restate your findings and sign-off using the required format."). This format re-invocation is not counted as a new adversarial round. Limit: 3 format re-invocations. If still noncompliant after 3, escalate to the human.

If sign-off is achieved: report back to the user with the final output and the sign-off statement.

If Critical or Major findings remain: proceed to Step 4.

## Step 4 - Route findings to a Worker

Spawn a **background general-purpose subagent via the `Agent` tool** with:

- The original task
- The Skeptic's findings (verbatim)
- The prior Worker's output (or file paths to it)
- The accumulated exchange log
- The session context

Worker prompt:

---
You are a Worker agent. Address the Skeptic findings below and return your revised output.

**Original task:** $ARGUMENTS

**Skeptic findings:**
[Paste findings verbatim]

**Prior output:**
[Paste prior output or file paths]

**Exchange log so far:**
[Paste accumulated log]

For each Critical or Major finding: fix it, or document a specific reason why it is not a real problem. Return your revised complete output.
---

Update the resolved issues preflight list with each addressed finding and its resolution.

Return to Step 2 with the revised output.

## Step 5 - Escalation

After the same finding is contested for 2 or more re-routes without resolution: stop. Escalate to the human with:
- The full exchange log
- The contested findings
- Worker positions and Skeptic positions on each unresolved finding

Do not attempt further re-routes without human direction.

---

## Adversarial brief selection

Pick the single best match. If multiple apply, use the first match in this list.

| Task type | Use this brief |
|---|---|
| Smart contracts, on-chain logic | "A financially motivated attacker has the source code and will look for: reentrancy, access control gaps, signature replay attacks, fee bypass, and any path to transfer an asset without valid authorization. Assume the attacker will read every public function, every state variable, and every event. Assume they will attempt direct contract interaction, bypassing any app-layer controls." |
| Auth, sessions, tokens, middleware | "An attacker controls one compromised account and one compromised device. What can they access, modify, or forge? Look for: session fixation, token replay, insufficient binding between session and device, privilege escalation paths, and any state the server trusts without re-verifying." |
| API endpoints, HTTP handlers | "An attacker can send arbitrary HTTP requests including malformed inputs, missing fields, oversized payloads, replayed tokens, and concurrent requests designed to hit race conditions. Look for: missing input validation, authentication that can be bypassed, rate limiting gaps, and any endpoint that mutates state without idempotency guarantees." |
| Cryptographic ops, signature verification | "An attacker will try to produce a valid-looking signature without the private key. They will also try replay attacks with previously valid signatures. Look for: weak randomness in nonce generation, missing domain separation, algorithm confusion attacks, and any verification path that skips a check under certain conditions." |
| DB schema, migrations, data models | "Is the migration idempotent - what happens if it runs twice? What is the state of the data after partial failure, and can it be recovered without data corruption? Look for: double-run risk (non-idempotent operations), partial failure paths (what if the migration fails halfway?), data loss risk (irreversible column drops, non-nullable additions to tables with existing data), and rollback path (is there a down migration, and is it tested?)." |
| Async jobs, data pipelines, queues | "What happens if this job runs twice? What happens if it crashes halfway? What is the state after partial failure, and can it be safely retried without double-processing or data corruption? Look for: non-idempotent operations, missing rollback logic, state that can diverge between systems, and silent failure modes." |
| Document synthesis, architecture, planning | "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?" |
| All other tasks | "Assume this code will be deployed to production and maintained by engineers who did not write it. Find: logic errors, edge cases that cause silent failures, missing error handling, incorrect assumptions about input ranges or ordering, and any assumption that will break under realistic load or adversarial input." |

## Notes

- The Skeptic is always a fresh spawn - never a continuation of a prior round.
- The main agent never touches the Worker's implementation. Review only the returned result.
- Keep the preflight list honest: only mark issues as resolved when they genuinely are.
- Pass the adversarial brief to the Skeptic verbatim - never soften or summarize it.
