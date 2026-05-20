<!--
Purpose: Full reference for QA gate operational details extracted from
         METHODOLOGY.md §QA Gate. Contains parallel-by-worktree fan-out
         commands, architect-plan-driven scenarios deep prose, and the
         dev-server boot pattern with curl-until loop.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/05-qa-gate.md (pointer before Re-route limits),
            content/sections/11-protocol-details.md (QA gate Protocol Details entry).

Upstream deps: content/sections/05-qa-gate.md (parent section; read that
               section first for the concurrent-vs-sequential flow, skip enums,
               conductor preflight, and INCONCLUSIVE classification);
               content/agents/qa-engineer.md (track-scoped qa.md resolution).

Downstream consumers: qa-engineer spawns (boot pattern, fan-out commands);
                      conductor orchestration (parallel-by-worktree setup);
                      /implement-ticket Phase 6b (architect-plan-driven scenarios).

Failure modes: Prose; does not execute. The curl-until loop is the canonical
               boot-detection pattern - drift from this reference causes
               qa-engineers to use unreliable fixed-sleep alternatives.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §QA Gate. Read that section first for the concurrent-vs-sequential flow, skip enums, conductor preflight, and INCONCLUSIVE classification.

# QA Gate - Full Reference

## Multi-PR / multi-ticket parallel-by-worktree

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

## Architect-plan-driven scenarios

Phase 6b reads `qa_criteria.scenarios[]` directly from the architect plan or Brief - that block is the authoritative test plan. The architect plan template MUST include the `qa_criteria` YAML block on every Elevated unit (Critical Skeptic finding if absent; see `content/agents/architect.md`). The qa-engineer brief is a thin wrapper supplying the URL, the dev-server boot recipe, the diff, and the `ticket_id`; it does NOT re-author scenarios. Conductor MUST NOT hand-author scenarios at spawn time - that recreates the failure mode where verification drifts from what the architect committed to.

## qa-engineer dev-server boot pattern

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
