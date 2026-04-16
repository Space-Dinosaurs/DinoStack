# Agent Team Playbook

## The team

| Agent | Role | Writes files? |
|---|---|---|
| `investigator` | Codebase investigation. Traces data flow, maps blast radius, explores unfamiliar areas before design or implementation. | No |
| `debugger` | Root cause analysis. Given a failure, diagnoses what's wrong and produces a fix brief. | No |
| `security-auditor` | OWASP-structured security review. Covers injection, auth, secrets, privilege escalation. | No |
| `perf-analyst` | Performance profiling. Measures latency, memory, and throughput; identifies hotspots with evidence; produces a fix brief for the engineer. Does not implement fixes. | No |
| `dependency-auditor` | Supply-chain review. Runs vulnerability scanners across all detected ecosystems, audits lockfiles, flags license risks and maintenance signals. Produces a findings report for the engineer to execute. | No |
| `release-orchestrator` | End-to-end release sequencing. Owns pre-flight gates, version bump, changelog, tag, deploy, and post-deploy verification. Writes version bumps and changelog entries; does not write feature code. | Yes |
| `architect` | Pre-implementation design. Reads the codebase, produces a structured technical plan. | No |
| `orchestration-planner` | Team composition and sequencing. Given a goal, produces a structured execution plan: which agents to spawn, in what order, with what handoffs, and where Skeptic review is needed. | No |
| `engineer` | Implements the change. Reads conventions, writes code, runs quality gates, reports clearly. | Yes |
| `qa-engineer` | Post-Skeptic browser verification. Spawns after Skeptic sign-off when the diff matches QA trigger patterns in `.claude/qa.md`. Verifies changes in a real browser, returns structured pass/fail report. Appends learned quirks to `.claude/qa.md` Knowledge section. | No (appends to qa.md only) |
| `skeptic` | Adversarial reviewer. Reviews Worker output for Critical/Major/Minor findings. | No |

The `skeptic` is the cross-cutting review layer - its specialty is adversarial review itself, applied across every flow rather than producing a forward artifact. The `qa-engineer` is a conditional gate that fires only when UI-visible changes are detected. All others are specialists that produce output feeding into the main flow.

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

### Trivial change (single-file cosmetic or copy change, no logic impact)

```
[no subagents running] conductor edits directly
    ↓
done (commit still required)

[subagents running] solo engineer Worker in foreground
    ↓
done (no Skeptic, no brief file, commit still required)
```

Trivial bypasses the Skeptic entirely. The conductor MUST NOT spawn a Skeptic for a Trivial task. The conductor availability rule drives the Worker/direct split: a conductor managing in-flight subagents must not block itself with direct implementation work - spawn the engineer Worker instead and remain available. If the Worker discovers mid-task that the change is not actually Trivial (e.g., the target file turns out to be a shared token file), it must stop and report; the conductor re-classifies as Elevated.

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

**Use `perf-analyst` when:**
- A feature is slow, a regression has been reported, or you need before/after benchmarking around a change
- Profiling CPU hotspots, memory leaks, or throughput limits
- A perf budget exists and must be measured against
- Skip when the bottleneck is already understood - go straight to `engineer`

**Use `release-orchestrator` when:**
- Cutting a release, shipping to production, bumping a version and tagging, or rolling back the last release
- You need the full release sequence: pre-flight checks, changelog, tag, deploy, post-deploy verification
- Do NOT use for feature implementation or bug fixing - this agent sequences a release, it does not write product code

**Use `dependency-auditor` when:**
- Running a supply-chain review or CVE scan of the project's lockfiles
- Evaluating whether a new or upgraded dependency is safe to add
- Checking license compliance across the dependency graph
- Skip when a shallow CVE check as part of a security audit is sufficient - the `security-auditor` covers that path

**Use `qa-engineer` when:**
- Skeptic has signed off AND the project has `.claude/qa.md` with trigger patterns matching the diff
- User explicitly asks to verify, test, or QA a change ("run QA", "check the feature works", "verify in the browser", "does it work")
- Do NOT use when: no `.claude/qa.md` exists, the change is backend-only (no matching patterns), or the change is Low risk

**When the architect returns a plan, spawn a Skeptic to review it before proceeding.** This is mandatory - do not spawn engineers, run the orchestration-planner, or take any action on the plan until the Skeptic grants sign-off. Use the "Document synthesis, architecture, and planning" adversarial brief. A flawed plan propagates errors through every downstream Worker; the plan review Skeptic is the gate that prevents this.

**Skeptic is always spawned for Elevated risk.** It reviews whatever the engineer produced. The security-auditor is an additional pass, not a replacement for the Skeptic.

**Trivial risk skips Skeptic entirely.** Trivial tasks - single-file cosmetic or copy changes with no logic impact, where all qualifying signals hold - do not go through the Skeptic loop. The conductor edits directly when no subagents are running; otherwise a single `engineer` Worker handles it in foreground with no Skeptic and no brief file. When in doubt between Trivial and Elevated, choose Elevated.

---

## Spawning

Spawn all agents in background. The main session agent is the sole orchestrator - no agent spawns other agents.

When spawning `engineer`, include:
- The Architect's plan (if one was produced)
- Relevant file paths or codebase root
- Acceptance criteria
- Session context (`~/.claude/projects/[hash]/context.md`)
- For Elevated-path spawns: the execution contract block from `agent-methodology.md` (Worker preamble section), with all required fields filled in from the architect's plan or orchestration-planner output

When spawned via `/implement-ticket` Phase 5 with a `task_id` in the execution contract, the engineer includes `task_id` in its return summary for conductor correlation. The conductor handles all `.agentic/tasks.jsonl` writes.

**Fan-out spawning.** When fan-out is active (N >= 2 parallel units), the conductor reads `unit_slug`, `merge_order`, and `skeptic_strategy` from the orchestration-planner's JSONL block at Phase 5 to determine worktree naming (`${FEATURE_BRANCH}-${unit_slug}`), merge ordering (sequential by `merge_order` value), and Skeptic review strategy (`per-unit` spawns one Skeptic per unit in parallel; `integration` defers to a single Skeptic after all units merge onto a scratch integration branch). All N engineers are spawned in a single message (parallel, background). The `task_id` field in each engineer's execution contract uses the format `<ticket_id>-<unit_slug>` for multi-unit correlation.

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

When spawning `perf-analyst`, include:
- The target: what to profile (function, endpoint, query, service, or workflow)
- The repro command: how to run the code so it can be measured
- The baseline (optional): prior measurement, commit SHA, or branch name to compare against
- The perf budget (optional): a target such as "under 100ms p99" or "< 50 MB peak memory"
- The hypothesis (optional): a suspicion about the bottleneck - treated as unconfirmed until measured

When spawning `release-orchestrator`, include:
- The target environment: where this release is going (staging, production, a named remote)
- The release type hint: patch / minor / major, or a description of the changeset
- The changeset boundary: "since last tag", "since commit abc123", or a specific range
- The deploy command or runbook reference: the exact command or a path to a runbook
- The `.claude/release.md` config (if it exists) for environment, version scheme, and rollback info

When spawning `dependency-auditor`, include:
- The scope: "full audit", a specific package name and version, or a before/after lockfile diff
- The project root directory to scan
- Known constraints (optional): license policy (e.g., "GPL is not allowed"), min-version floors, or specific CVE IDs to verify

When spawning `qa-engineer`, include:
- The unit's acceptance criteria as the test plan
- The `.claude/qa.md` config (dev server command, port, URLs)
- Which pages/features to verify based on the files changed
- The qa-engineer uses `agent-browser` for all browser interaction
- QA returns a structured pass/fail report with bugs and evidence
- On failure, the conductor spawns fix engineers, then re-runs QA
