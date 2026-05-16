## QA Gate

**Concurrent QA + Skeptic for UI-visible changes.** When a unit's `qa_criteria` indicates QA fires (Brief/architect plan present, `qa_skip == null`, scenarios non-empty), spawn `qa-engineer` IN PARALLEL with the Skeptic in a single message (both background). Sign-off requires both to pass. This eliminates the sequential Skeptic-then-QA delay for UI-visible changes and aligns with the parallel-by-default philosophy.

For changes whose `qa_criteria` does not match the concurrent path (or where the diff is unknown at planning time), the post-Skeptic QA flow described below remains in effect.

**Pre-spawn trigger check:** Before spawning Workers, the conductor inspects the unit's `qa_criteria` (from the Brief or, if no Brief, from the architect plan). If `qa_criteria` is present AND `qa_skip == null` AND `scenarios[]` is non-empty, mark the unit for concurrent QA at review time. The architect's `qa_criteria` is the authoritative trigger - the qa.md trigger patterns are a SUPPLEMENTAL match-set: when both `qa_criteria` and a qa.md trigger match exist, qa-engineer receives both inputs (the scenarios as the test plan, and any matched qa.md project-knowledge entries as supplemental context). qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`. If `qa_criteria` is absent at planning time and the diff is unknown, defer the check to post-Worker (standard flow).

**When QA is skipped:**
- The change is Trivial risk (direct action; existing carve-out preserved).
- `qa_skip` is one of the 5 valid enum values: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`. The rationale is logged in the Brief / architect plan; QA does not fire.

Note: a project having no qa.md is NOT a reason to skip QA. The default is QA fires for every Elevated unit unless the architect explicitly committed to one of the 5 `qa_skip` enum values. qa.md is supplemental project-knowledge that qa-engineer reads for context (dev server config, project quirks); its absence does not change the QA gate decision. The `qa_default_skip` key in `.agentic/config.json` is a reserved, documented-but-inert schema key (canonical definition in §Planning Artifacts); it does NOT override or weaken this invariant.

**QA gate flow (UI-visible - concurrent):**
1. Worker returns. Conductor confirms `qa_criteria` indicates QA fires for this unit (`qa_skip == null` and scenarios non-empty).
2. If yes: spawn Skeptic AND `qa-engineer` in a single message (parallel, background). Both receive the diff and the unit's `qa_criteria`. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
3. Wait for both to return.
4. If both pass: unit is complete.
5. If Skeptic raises Critical/Major: enter standard Skeptic fix loop. QA re-runs after Skeptic sign-off is achieved.
6. If QA fails (Skeptic already signed off): spawn fix engineer, then re-run QA only.

**QA gate flow (non-UI - post-sign-off):**
1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor inspects the unit's `qa_criteria` (from Brief or architect plan).
3. If `qa_criteria` is present AND `qa_skip == null` AND scenarios non-empty: spawn `qa-engineer` with the unit's `qa_criteria` and ticket context. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
4. QA engineer opens the dev server in a browser (or invokes API/runtime checks per the scenarios' `method`), verifies functionality, returns pass/fail report.
5. On PASS: unit is complete.
6. On FAIL: spawn fix engineer for each bug, then re-run QA.

**Phase breadcrumb:** `[phase: qa-review]`

### Per-ticket, in-flow (anti-pattern: end-of-batch QA sweep)

**Phase 6b is a per-ticket, in-flow gate. Conductor MUST NOT aggregate Phase 6b across multiple tickets to run as a final batch step.** Each ticket's QA fires inside that ticket's own loop, before Phase 7. If runtime QA cannot run for ticket N at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for ticket N specifically, not deferred work to triage at batch end.

When QA cannot run for ticket N, set the unit's QA result to `qa_blocked` and surface the blocker to the operator with the specific cause and the three options:

- **Provide the missing input** (env file, credentials, working preview URL) and re-run Phase 6b.
- **Accept INCONCLUSIVE** with `qa_unverified=true` recorded on the unit (see classification rules below). The PR can still merge, but the ticket carries a known unverified-runtime flag.
- **Abandon the ticket** - close the PR or revert.

Per-ticket QA scales via parallel-by-worktree (see below) - that is the mechanism for "many tickets in flight without a serial QA queue", not batching.

### Conductor preflight before any qa-engineer spawn

Before spawning `qa-engineer` for any unit, the conductor verifies the project env file exists at the path that the dev server will load. The exact path and pull command come from the resolved qa.md (`env_file:` and `env_pull_command:` fields if present) or from project config (e.g. an `env:pull:<app>` script in `package.json`). If the env file is missing, do NOT spawn qa-engineer. Instead surface the verbatim message to the operator:

```
QA env preflight FAILED: <env_file> is missing.
Pull it with: <env_pull_command>
Then re-run Phase 6b for this ticket.
```

Wait for the operator to provide the env file (or accept INCONCLUSIVE per the classification rules below) before proceeding. Spawning qa-engineer just to discover the env is missing wastes a worker turn - the dev server will fail to boot and the qa-engineer will return BLOCKED with no useful signal.

### INCONCLUSIVE classification (no static-only auto-pass)

Static-only QA on an Elevated UI-visible change is approximately zero signal. State hooks, prop-sync bugs, missing render branches, and conditional rendering bugs are invisible to source review. Source verification of an Elevated UI-visible criterion is NOT progress on that criterion.

When the qa-engineer cannot reach a runtime path - preview deploy is blocked AND local-env runtime is unavailable - the unit's QA result is **INCONCLUSIVE** with `qa_unverified=true`, NOT a pass. The conductor surfaces this state to the operator with the same three options as `qa_blocked` above (provide env / accept the unverified state / abandon). The conductor MUST NOT auto-promote INCONCLUSIVE to PASS, and MUST NOT silently proceed to Phase 7 with `qa_unverified=true` set; the operator must explicitly accept that state before merge.

### Multi-PR / multi-ticket parallel-by-worktree

When more than one PR (or unit) is awaiting QA, the conductor defaults to parallel verification - one qa-engineer per PR, each in its own worktree, each on a unique port. Single-message fan-out:

```bash
# For each PR awaiting QA at index N (0-based):
git worktree add .agentic/worktrees/qa-<branch> <branch>
# Spawn qa-engineer with isolation: "worktree" and PORT=$((3000 + N)) injected into the brief.
```

All qa-engineers run concurrently (background, single message). After each returns, remove its worktree:

```bash
git worktree remove .agentic/worktrees/qa-<branch>
```

Serial multi-PR QA is reserved for cases where the parallel path is structurally blocked (e.g. only one preview environment available). Default is parallel.

### Architect-plan-driven scenarios (no hand-authored briefs)

Phase 6b reads `qa_criteria.scenarios[]` directly from the architect plan or Brief - that block is the authoritative test plan. The architect plan template MUST include the `qa_criteria` YAML block on every Elevated unit (Critical Skeptic finding if absent; see `content/agents/architect.md`). The qa-engineer brief is a thin wrapper supplying the URL, the dev-server boot recipe, the diff, and the `ticket_id`; it does NOT re-author scenarios. Conductor MUST NOT hand-author scenarios at spawn time - that recreates the failure mode where verification drifts from what the architect committed to.

### qa-engineer dev-server boot pattern

When the qa-engineer needs to start a local dev server, it resolves the boot command in this order:

1. Per-track qa.md `command:` field (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback; for multi-track repos, the track-scoped qa.md takes priority over the root index per `content/agents/qa-engineer.md`).
2. Fallback to the project's package.json `dev` script (`npm run dev`, `pnpm dev`, etc.) if no qa.md `command:` is set.

After starting the server, the qa-engineer polls for readiness with a curl-until loop bounded by a 90-second timeout - never a fixed `sleep`:

```bash
PORT=<port>
TIMEOUT=90
ELAPSED=0
until curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT}/" | grep -qE '^(200|3..)$'; do
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "Dev server failed to respond on port ${PORT} within ${TIMEOUT}s"
    exit 1
  fi
done
```

Boot detection by fixed `sleep` is unreliable across machines and network conditions; the curl-until loop is the canonical pattern.

### Re-route limits

**Re-route limits.** Within any loop (Skeptic re-route or QA re-route), the conductor applies a max of 3 fix passes before escalating to the human. This applies to loops inside `/implement-ticket` Phase 6 and 6b, and to any ad-hoc Skeptic loop the conductor runs outside that command. The conductor tracks re-route count in-context. When the cap is reached with open findings, the conductor does not spawn another Engineer - it surfaces the stall with the open findings list and waits for human direction.

**Convergence failure.** A convergence failure occurs when a Skeptic raises the same finding unchanged after the Engineer claimed to have addressed it. Convergence failures bypass the remaining iteration budget and escalate immediately. They indicate either a misunderstanding between the Engineer and the finding, or a design-level conflict that requires human arbitration. Within the persistence loop, one re-raise after a claimed fix is sufficient (overrides the 2-re-route rule in skeptic-protocol.md Section 5 - see that section for the override note).
