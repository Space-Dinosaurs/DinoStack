# Agent Team Playbook

## The team

| Agent | Role | Writes files? |
|---|---|---|
| `investigator` | Codebase investigation. Traces data flow, maps blast radius, explores unfamiliar areas before design or implementation. | No |
| `debugger` | Root cause analysis. Given a failure, diagnoses what's wrong and produces a fix brief. | No |
| `security-auditor` | OWASP-structured security review. Covers injection, auth, secrets, privilege escalation. | No |
| `architect` | Pre-implementation design. Reads the codebase, produces a structured technical plan. | No |
| `orchestration-planner` | Team composition and sequencing. Given a goal, produces a structured execution plan: which agents to spawn, in what order, with what handoffs, and where Skeptic review is needed. | No |
| `engineer` | Implements the change. Reads conventions, writes code, runs quality gates, reports clearly. | Yes |
| `qa-engineer` | Post-Skeptic browser verification. Spawns after Skeptic sign-off when the diff matches QA trigger patterns in `.claude/qa.md`. Verifies changes in a real browser, returns structured pass/fail report. Appends learned quirks to `.claude/qa.md` Knowledge section. | No (appends to qa.md only) |
| `skeptic` | Adversarial reviewer. Reviews Worker output for Critical/Major/Minor findings. | No |

The `skeptic` is the review layer - it is not a specialist. The `qa-engineer` is a conditional gate that fires only when UI-visible changes are detected. All others are specialists that produce output feeding into the main flow.

---

## Composed flows

### Standard feature

```
architect (plan)
    ↓
skeptic (plan review)  ←── required before proceeding
    ↓ sign-off
engineer (implement)  ←── re-routes findings
    ↓
skeptic (review)
    ↓ sign-off
qa-engineer (verify)  ←── conditional: only if .claude/qa.md trigger patterns match the diff
    ↓ pass
done
```

### Security-sensitive feature (auth, payments, secrets, user data)

```
architect (plan)
    ↓
skeptic (plan review)  ←── required before proceeding
    ↓ sign-off
engineer (implement)  ←── re-routes findings
    ↓
skeptic (review)
    ↓ sign-off
security-auditor (audit)
    ↓
qa-engineer (verify)  ←── conditional: only if .claude/qa.md trigger patterns match the diff
    ↓ pass
done (or route findings back to engineer if Critical/High)
```

### Bug or broken test

```
debugger (diagnose)
    ↓ Confidence: High/Medium
engineer (implement fix)
    ↓
skeptic (review)
    ↓ sign-off
done

    ↓ Confidence: Low
escalate to human (describe what information is needed to close the diagnosis)
```

When the debugger returns `Confidence: Low`, do not proceed to engineer. The debugger's output will describe what specific information (logs, env values, reproduction steps, access to a running system) would close the diagnosis. Surface this to the user and wait for direction before re-spawning the debugger or proceeding to fix.

### Quick change (Low risk, 1-2 lines, no Elevated signals)

```
direct action (no agents needed)
    ↓
self-check
```

---

## Complex or ambiguous goals

### Complex or ambiguous goal (use orchestration-planner first)

```
orchestration-planner (produces execution plan)
    ↓
[execute the plan - agent sequence varies by task]
```

Use `orchestration-planner` when the right agent combination is not obvious, when multiple phases are likely, or when a high-level requirement needs decomposing before execution. It returns a structured plan the conductor follows directly.

---

## Decision rules

**Use `orchestration-planner` when:**
- The task is complex and the right agents / sequencing are not immediately obvious
- Multiple phases are involved and you want to reason about them up front
- You want to avoid costly mid-task reclassification

**Use `architect` when:**
- The task involves meaningful design decisions (data model, API shape, integration points)
- The codebase is unfamiliar and exploration is needed before touching code
- The feature touches multiple subsystems and sequencing matters
- Skip it for well-understood, self-contained changes - go straight to `engineer`

**Use `security-auditor` when:**
- The change touches auth, sessions, tokens, passwords, or permissions
- New API endpoints are exposed to untrusted input
- Secrets handling or encryption is involved
- Any privilege boundary is crossed

**Use `debugger` when:**
- A test is failing and the root cause is not obvious
- A stack trace or production error needs diagnosis before a fix is attempted
- Skip it when the bug is already understood - go straight to `engineer`

**Use `qa-engineer` when:**
- Skeptic has signed off AND the project has `.claude/qa.md` with trigger patterns matching the diff
- User explicitly asks to verify, test, or QA a change ("run QA", "check the feature works", "verify in the browser", "does it work")
- Do NOT use when: no `.claude/qa.md` exists, the change is backend-only (no matching patterns), or the change is Low risk

**When the architect returns a plan, spawn a Skeptic to review it before proceeding.** This is mandatory - do not spawn engineers, run the orchestration-planner, or take any action on the plan until the Skeptic grants sign-off. Use the "Document synthesis, architecture, and planning" adversarial brief. A flawed plan propagates errors through every downstream Worker; the plan review Skeptic is the gate that prevents this.

**Skeptic is always spawned for Elevated risk.** It reviews whatever the engineer produced. The security-auditor is an additional pass, not a replacement for the Skeptic.

---

## Spawning

Spawn all agents in background. The main session agent is the sole orchestrator - no agent spawns other agents.

When spawning `engineer`, include:
- The Architect's plan (if one was produced)
- Relevant file paths or codebase root
- Acceptance criteria
- Session context (`~/.claude/projects/[hash]/context.md`)

When spawning `skeptic` for architect plan review, include:
- The adversarial brief verbatim: "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?"
- The architect's complete plan output
- Any established architectural constraints or prior decisions the Skeptic should check against

When spawning `skeptic` for engineer output review, include:
- The adversarial brief (run `/skeptic` for templates)
- The engineer's output (file paths or inline)
- Resolved issues preflight from prior rounds

When spawning `security-auditor`, include:
- The files changed or the scope of the feature
- The domain (e.g., "authentication flow", "payment processing")

When spawning `qa-engineer`, include:
- The unit's acceptance criteria as the test plan
- The `.claude/qa.md` config (dev server command, port, URLs)
- Which pages/features to verify based on the files changed
- The qa-engineer uses `agent-browser` for all browser interaction
- QA returns a structured pass/fail report with bugs and evidence
- On failure, the conductor spawns fix engineers, then re-runs QA
