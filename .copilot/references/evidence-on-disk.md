<!--
Purpose: Defines the evidence-on-disk spill/sketch/rehydrate protocol for
         write-capable worker subagents (engineer, release-orchestrator,
         general-purpose). Workers compress large tool outputs into compact
         in-context sketch lines with node IDs and rehydrate raw text on
         demand.

Public API: Referenced by content/agents/engineer.md (## Implementation process,
            "Context economy: evidence-on-disk" step) and by
            content/references/delegation-detail.md (§Worker Preamble and
            Execution Contract Template). The sketch line format is a shared
            binding contract with bin/agentic-evidence - the worked example
            below must match the CLI's emitted sketch lines byte-for-byte.

Upstream deps: bin/agentic-evidence (spill/sketch/get/prune CLI). Correctness
               of the CLI is gated by bin/tests/test_agentic_evidence.py
               (required bin-tests CI check).

Downstream consumers: content/agents/engineer.md (Context economy step),
                      content/references/delegation-detail.md (advisory pointer),
                      content/SKILL.md (Reference Docs list).

Failure modes: If the sketch line format in the worked example drifts from the
               CLI's emitted format, node-ID citations stop matching raw nodes.
               The worked example's sketch lines are the binding contract -
               rename fields or change separators only in lock-step with the CLI.

Performance: N/A - methodology document consumed by LLMs at spawn time.
-->
# Evidence-On-Disk Reference

The evidence-on-disk protocol is a repo-shipped, universality-safe,
dependency-free primitive for write-capable worker subagents. It compresses
large tool output - search results, stack traces, file dumps, test logs - into
a compact in-context sketch with node IDs, rehydrating raw text on demand.

---

## Purpose

A worker's context window is a scarce resource, and raw tool output is its
biggest consumer. A single `grep -rn` over a large tree or a full test log can
return tens of thousands of characters that the worker needs exactly once, then
never again. Pasting the full output into context burns the window; discarding
it loses the evidence.

Evidence-on-disk borrows the TencentDB-Agent-Memory operational pattern:
"compress, but never lose the road back to the evidence." The worker spills the
raw output to the live worktree's `.agentic/evidence/` store, keeps a one-line
sketch (node ID plus metadata) in context, and rehydrates the raw text on demand
with a single `get <node-id>` call. The in-context cost drops from the full
output to one line per node; the evidence is never lost until teardown.

The protocol does NOT rely on the operator-local context-mode `ctx_*` MCP
plugin (`ctx_execute`, `ctx_batch_execute`, `ctx_search`). That plugin is an
operator-local convenience, not a universality-safe primitive - a consumer
project on another harness, or a worktree without the plugin configured, does
not have it. Evidence-on-disk ships in the repo and works everywhere git does.
The universality pillar requires shared behavior that resolves per-operator at
runtime; a dependency on an operator-local plugin violates that pillar.

## When to Spill (Trigger Thresholds)

Spill any tool output that exceeds ~20 lines OR ~8k chars AND that the worker
expects to need again. Both thresholds are advisory guides, not hard limits.

Pressure is graduated by run phase:

- **Early in a run (mild):** spill only outputs larger than ~8k chars. Fresh
  context is cheap; the worker can afford to keep moderate outputs inline.
- **Late in a heavy run (aggressive):** spill anything larger than ~1-2k chars
  the worker might need, and re-paste a fresh sketch so the in-context map stays
  accurate as nodes accumulate.

**Sketch cap.** Keep the pasted sketch under ~40 lines (one line per node). The
CLI warns on stderr past 40 nodes - at that point the worker should prune stale
nodes (`prune --older-than HOURS`) and re-paste a trimmed sketch rather than let
the map itself become a context burden.

## The Three-Step Loop

1. **Spill** the output to the evidence store: `agentic-evidence spill`.
2. **Keep the printed sketch line in your context.** Each spill prints one line
   of the form `- n<seq> | label: <label> | tool: <tool> | chars: <N> | ts: <ts> | status: <status>`.
   That line is the permanent in-context pointer to the node.
3. **`get <node-id>` on demand** when the raw text is needed again. The raw text
   is rehydrated into the tool result exactly as spilled.

Re-run `agentic-evidence sketch` to refresh the map as nodes accumulate. The
sketch command lists every live node; replacing the in-context sketch with a
fresh one keeps the node-ID map accurate.

## Teardown

Run `agentic-evidence prune --all` at worker end. This mirrors the
temp-file-ownership rule in `content/rules/conventions.md` - agents that write
temp files are responsible for deleting them in teardown, and
`.agentic/evidence/` is a temp store in exactly that sense.

Use `agentic-evidence prune --older-than HOURS` for mid-run housekeeping - for
example, pruning nodes older than the current phase before re-pasting a fresh
sketch under the ~40-line cap.

## Lifecycle and Ephemerality (Critical)

**Evidence lives ONLY in the live worktree and DIES at cleanup.** The evidence
store is written to the worktree's `.agentic/evidence/` directory, which is
untracked scratch. When the worktree is removed at push or merge, the evidence
is gone with it.

Consequences:

- **Node-ID citations in a worker return are useful during the run itself** -
  the conductor or a follow-up worker in the same worktree can `get` the raw
  text while the store still exists.
- **They are also useful for PRE-cleanup conductor access** via
  `bin/agentic-resolve-worktree`, which locates the live worktree so the
  conductor can read evidence before it is torn down.
- **There is NO post-merge evidence retrieval.** Once the branch is pushed or
  merged and the worktree is removed, node IDs point at nothing. Do not cite
  node IDs in a return expecting the conductor to retrieve evidence after
  cleanup.
- **Raw tool output may contain absolute paths or secrets.** Evidence is NEVER
  committed. The `.agentic/` directory is gitignored by the shared scaffold
  (`content/commands/ds-init-project.md`), and `.agentic/evidence/` is added to
  that denylist as runtime scratch. A worker must never stage or commit evidence
  content.

## Enforcement Posture

Advisory, not a hard gate. Spill judgment is context-dependent - what counts as
"egregious" varies by run, tool, and how much context remains. There is no
mechanical enforcement and no new required execution-contract field.

- The CLI's correctness is gated by `bin/tests/test_agentic_evidence.py`, part
  of the required `bin-tests` CI check. The protocol's machinery is tested; the
  worker's judgment in applying it is not.
- A Skeptic may raise a Minor advisory finding for egregious verbatim tool dumps
  that clearly should have been spilled - for example, a multi-thousand-char
  raw output pasted wholesale into a return or into the in-context record when
  the worker plainly expected to use it again. This is advisory because the
  line is a judgment call, not a hard violation.

## Reader Restriction

Read-only agents - architect, investigator, skeptic, qa-engineer,
orchestration-planner - cannot write evidence. Their tool grants omit Edit and
Write, so they have no mechanism to spill. This pattern targets write-capable
workers only: engineer, release-orchestrator, and general-purpose. A read-only
agent that encounters a large output should rely on its own judgment
(summarize, cite paths, or return a pointer) rather than the evidence store.

## Worked Example

A worker runs a route search across the codebase, collects a failing test's
stack trace, and dumps a source file. All three outputs are large and the worker
will need them again while patching. It spills each to the evidence store, keeps
the printed sketch in context, and rehydrates the stack trace on demand.

```
$ agentic-evidence spill < /tmp/route-search.txt
$ agentic-evidence spill < /tmp/stack-trace.txt
$ agentic-evidence spill < /tmp/file-dump.txt

$ agentic-evidence sketch
- n1 | label: route-search | tool: Bash | chars: 45230 | ts: 2026-08-05T09:14:02Z | status: ok
- n2 | label: stack-trace | tool: Bash | chars: 8341 | ts: 2026-08-05T09:15:47Z | status: ok
- n3 | label: file-dump | tool: Bash | chars: 2110 | ts: 2026-08-05T09:16:11Z | status: ok

$ agentic-evidence get n2
<the raw stack-trace text rehydrated verbatim, 8,341 chars>
```

The three sketch lines are the shared binding contract - byte-identical to the
CLI's emitted sketch format. The worker keeps exactly these lines in context
(not the raw outputs) and calls `get n2` when the stack trace is needed.
