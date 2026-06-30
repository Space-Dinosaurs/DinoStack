# Digest-Return Pattern

## Principle

The conductor stays context-lean by spawning context-heavy work in the background and consuming a structured digest on return - not by absorbing the internal loop transcript. Multi-iteration Skeptic/QA loops, long investigations, and parallel fan-out units each run inside a worker's context. Only the digest crosses back.

This is not a new mechanism. The engineer DONE summary and Skeptic sign-off format already produce it. This doc names the discipline so conductors apply it consistently rather than treating each background return as a trigger to re-read or re-derive.

## Digest contract

A loop-running spawn returns a structured digest. Required fields:

- **Terminal status** - one of DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED. No intermediate states.
- **Branch / PR** - the branch name and PR URL (or "no PR" if none was opened).
- **Skeptic sign-off** - verbatim sign-off line including the reviewed scope: a SHA range (base..head) for PR reviews, or the files/components examined for inline reviews. See `content/references/skeptic-protocol.md` for the sign-off format.
- **Falsifiable claims + evidence** - for any claim gated by the conductor's verification rules (Skeptic absence-or-critical findings, investigator external-data claims), include the exact command run and a literal output excerpt. A synthesized summary without raw output is insufficient.
- **Residual risk** - any known open issue, assumption, or concern that did not block the terminal status but could matter downstream.
- **Not-done list** - explicit list of scope items not completed, or "none" if all scope was addressed.

Optional field (default empty; cap 5 entries per return):

- **`learnings_candidate[]`** - worker-internal discoveries the conductor should route through the learnings pipeline. Each entry carries `kind` (`workaround` | `dead-end` | `gotcha` | `decision`), `domain_tag`, `fact` (1-2 sentences on what was discovered), and `why` (why a cold future agent would re-derive it). This is the ONLY channel for worker-internal discovery; the conductor's §Conductor consumption step 3 forbids transcript re-reading, so anything not surfaced here is lost.

The engineer DONE summary and the Skeptic sign-off together supply these fields. `content/agents/engineer.md` specifies the DONE return-summary schema (status, files_modified, quality_gate_results, commit_sha, learnings_candidate, and the rest); `content/sections/02-delegation.md` §Worker preamble specifies the execution contract - the spawn-input fields (outputs, tool_scope, completion_conditions, verification, output_paths, task_id) the conductor fills before spawning; `content/references/skeptic-protocol.md` specifies the sign-off format. This doc does not restate those schemas - it names the discipline of consuming the result as an opaque digest rather than re-reading the internal loop.

## Conductor consumption

When a background loop returns:

1. Read the digest fields above.
2. Spot-check falsifiable claims against live state before acting on them. This is the same obligation described in `content/sections/02-delegation.md` under §Skeptic absence-or-critical findings and §Investigator external-data claims.
3. Act on the terminal outcome. Do not re-read the worker's internal transcript, re-derive findings, or re-run the Skeptic loop. The digest is the output; the transcript is a detail.

This discipline is what keeps the conductor's context flat across many parallel loops. Each parallel unit deposits a digest; the conductor synthesizes digests, not transcripts.

## Why this over a nested-orchestration tier

A nested sub-conductor tier (a "unit-lead" that runs its own Skeptic/QA loop and reports up) would deliver the same context-separation benefit but at real cost: it requires reproducing the conductor's in-session state machinery one level down, rewriting the sole-orchestrator/Skeptic-independence foundation (subagents cannot spawn subagents), and introducing a new trust boundary where digest integrity needs verification. Background-spawn + structured digest return captures most of the benefit without those costs. A formal nested tier remains a future option if conductor context becomes a measured bottleneck on very large parallel fan-out tasks.
