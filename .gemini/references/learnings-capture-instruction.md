<!--
Purpose: The single standing "watch for learnings" instruction every agent role
         points at, plus the canonical definition of the `learnings_candidate[]`
         digest field. Written once so ~20 agent files carry a pointer instead of
         a copy: duplicated normative prose in this repo has drifted before and
         cost multiple review rounds to reconcile.

Public API: Read-only reference. Two consumable parts: the capture procedure
            (split by whether the reading agent can write) and the
            `learnings_candidate[]` entry shape.

Upstream deps: bin/ds-learning-shard (owns the --event-type enum, the flag
               names, and the per-session cap this document describes);
               content/references/capture-classification.md (the conductor-side
               gate that classifies what this document collects).

Downstream consumers: every agent in content/agents/ (via a pointer);
                      content/agents/engineer.md and
                      content/references/digest-return-pattern.md, both of which
                      defer the `learnings_candidate[]` shape to this file.

Failure modes: Prose; does not execute. If the flag names or the --event-type
               enum here drift from bin/ds-learning-shard, agents emit invalid
               invocations - argparse exits 2 on a bad flag, which is the one
               non-soft-fail path in that CLI.

Performance: Standard.
-->

> Parent: METHODOLOGY.md §Events log. Read `content/references/capture-classification.md`
> for the conductor-side gate that decides what actually gets written.

# Learnings Capture Instruction

Capture happens **in flight**, at the moment the learning occurs. Not batched to the
end of the task, where it is reconstructed from memory or lost outright.

## What counts as a learning

Four kinds, which are exactly the `--event-type` enum of `bin/ds-learning-shard`
and exactly the `kind` enum of `learnings_candidate[]`:

| Kind | Fires when |
|---|---|
| `workaround` | You worked around a tool or command failure. |
| `dead-end` | You tried an approach that cost non-trivial effort and did not work. |
| `gotcha` | You hit a cross-component gotcha: behaviour in one place that only makes sense given something elsewhere. |
| `decision` | You made a local design decision the task spec did not give you. |

**Do not pre-filter for importance.** Classification is conductor-side, through the
guardrail-first gate in `content/references/capture-classification.md`. If you judge
importance yourself you will drop exactly the entries that look small in the moment
and are expensive to re-derive cold. Record it and move on.

## If you can write (Edit/Write available)

Call the CLI the moment the learning occurs:

```bash
ds-learning-shard append \
  --repo "$PWD" \
  --session-key "<SESSION_KEY from your spawn brief>" \
  --agent-id "<your agent id>" \
  --role "<your role, e.g. engineer>" \
  --event-type workaround \
  --domain-tag "<short slug>" \
  --description "<what happened>" \
  --resolution "<how it was resolved, optional>"
```

- `--repo` accepts **any** path inside the repo, including an isolation worktree.
  You do not need to resolve the primary checkout; the CLI does.
- The store lives under `~/.agentic/learnings-shards/`, outside the repo on purpose:
  an isolation worktree's `.agentic/` is deleted before the PR opens.
- **The cap is CLI-enforced.** Never count your own entries and never decide you have
  had enough. An over-cap append is a no-op that exits 0.
- Every runtime condition is a soft-fail: the CLI exits 0 and prints one line to
  stderr. **Never block your task on it, never retry it, never report it as a
  failure.** The one exception is a malformed invocation (argparse exit 2), which
  means you typed a flag wrong; fix the flag.

Also populate `learnings_candidate[]` in your return digest as usual. The two paths
are complementary: the shard survives your context, the digest reaches the conductor
this turn.

## If you cannot write (read-only agent)

Agents declaring `disallowedTools: [Edit, Write, Agent]` cannot run the CLI and
cannot delegate to something that can. Populate `learnings_candidate[]` in your
return digest instead. That is your entire capture path, and the conductor is
forbidden from re-reading your transcript, so anything not in that field is lost.

## `learnings_candidate[]` (canonical definition)

Optional digest field. Default `[]`; omit when empty. Cap 5 entries per return.

```yaml
learnings_candidate:
  - kind: workaround | dead-end | gotcha | decision
    domain_tag: <slug>
    fact: <1-2 sentences: what was discovered>
    why: <why a cold future agent would re-derive this>
```

```json
{
  "type": "array",
  "maxItems": 5,
  "default": [],
  "items": {
    "type": "object",
    "required": ["kind", "domain_tag", "fact", "why"],
    "properties": {
      "kind":       { "enum": ["workaround", "dead-end", "gotcha", "decision"] },
      "domain_tag": { "type": "string" },
      "fact":       { "type": "string" },
      "why":        { "type": "string" }
    }
  }
}
```

This is the only definition of the field. `content/agents/engineer.md` and
`content/references/digest-return-pattern.md` both point here rather than restate it.

## Session identity

`SESSION_KEY` arrives **in your spawn brief**. It is the only source.

- **If your brief has no `SESSION_KEY`, skip shard capture silently.** Do not invent
  a key, do not ask for one, do not block. `learnings_candidate[]` still applies and
  needs no session key.
- **Never read a session id from the environment.** `CLAUDE_CODE_SESSION_ID` is
  Claude-only and this instruction must hold on every harness; `AGENTIC_SESSION_ID`
  and `CLAUDE_SESSION_UUID` are dead, verified empty in a live session, and
  `bin/ds-migrate` is silently degraded today precisely because it reads them.
