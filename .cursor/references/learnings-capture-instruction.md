<!--
Purpose: The single standing "watch for learnings" instruction every agent role
         points at, plus the canonical definition of the `learnings_candidate[]`
         digest field. Written once so ~20 agent files carry a pointer instead of
         a copy: duplicated normative prose in this repo has drifted before and
         cost multiple review rounds to reconcile.

Public API: Read-only reference. Two consumable parts: the capture procedure
            (split by whether the shard CLI is the reading agent's capture path,
            and otherwise by whether its return contract defines
            `learnings_candidate[]`) and the `learnings_candidate[]` entry shape.

Upstream deps: bin/ds-learning-shard (owns the --event-type enum, the flag
               names, and the per-session cap this document describes);
               content/references/capture-classification.md (the conductor-side
               gate that classifies what this document collects).

Downstream consumers: every agent in content/agents/ (via a pointer);
                      content/agents/engineer.md,
                      content/agents/investigator.md,
                      content/agents/debugger.md and
                      content/references/digest-return-pattern.md, all four of which
                      defer the `learnings_candidate[]` shape to this file;
                      content/references/conductor-operating-rules.md, whose
                      `kind`-to-`event_type` map consumes the enum declared here and
                      must change in lockstep with it (see "One co-dependent site"
                      below).

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

## If the shard CLI is your capture path

**This branch has a fixed membership list, not a capability test.** Exactly four roles
capture through `ds-learning-shard`: `engineer`, `adr-generator`, `product-discovery`
and `release-orchestrator`. Every other agent in `content/agents/` belongs to the next
section. Do not infer your branch from your `tools:` grant - most read-only roles do
hold `Bash` and are still not in this branch, because the split is by role, not by
capability. If your own role file does not give you a positive "the CLI is yours"
instruction, you are in the next section.

Holding `Bash` is a precondition of this branch, never the rule that assigns it:
`learning-extractor`, `learnings-agent` and `wrap-ticket` hold `Edit`/`Write` but no
`Bash`, so they could not run the CLI in any case - and all three are the capture
pipeline's own writers besides.

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

If your own return contract also defines `learnings_candidate[]`, populate it too.
`engineer` is the only role in this branch that does; `adr-generator`,
`product-discovery` and `release-orchestrator` return formats declare no such field,
so for those three the shard is the whole capture path. Where both apply the paths are
complementary: the shard survives your context, the digest reaches the conductor this
turn.

## If the shard CLI is not your capture path

Every role other than the four named above is here, whether or not it holds `Bash`.
What you can capture depends on whether your own return contract defines the
`learnings_candidate[]` field:

- **Contract defines `learnings_candidate[]`** (`investigator`, `debugger`): populate
  it. That is your entire capture path, and the conductor is forbidden from
  re-reading your transcript, so anything not in that field is lost.
- **Contract does not define it** (every other role in this branch): you have no capture
  channel, and you must not invent one. The conductor's routing hop in
  `content/references/conductor-operating-rules.md` consumes `learnings_candidate[]`
  only from `engineer`, `investigator` and `debugger` returns, so a block emitted by
  any other role is unread output appended to a return format the conductor parses.
  Surface an incidental discovery in whatever narrative section your output format
  already provides, or not at all. `skeptic` is the sharp case: its sign-off is
  checked for a fixed set of required elements, so an appended block is unparsed
  text sitting inside a validated format - never add one.

Adding the field to another read-only role is a two-sided change - the role's return
contract and the routing hop - never a pointer on its own.

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

This is the canonical definition of the field and the only place it is declared.
`content/agents/engineer.md`, `content/agents/investigator.md`,
`content/agents/debugger.md` and `content/references/digest-return-pattern.md` all
point here rather than restate it.

**One co-dependent site.** `content/references/conductor-operating-rules.md`
§"Routing hop for `learnings_candidate[]`" maps each `kind` onto a
`learnings-agent` `event_type`. It consumes the enum rather than declaring it, so it
is not a second definition - but adding, removing or renaming a `kind` value here
without updating that map leaves the conductor with no `event_type` for the new
value. Change the two together, and change `bin/ds-learning-shard`'s
`--event-type` enum in the same pass: this table and that CLI flag are the same
four values by construction.

## Session identity

`SESSION_KEY` arrives **in your spawn brief**. It is the only source.

- **If your brief has no `SESSION_KEY`, skip shard capture silently.** Do not invent
  a key, do not ask for one, do not block. `learnings_candidate[]` still applies and
  needs no session key.
- **Never read a session id from the environment.** `CLAUDE_CODE_SESSION_ID` is
  Claude-only and this instruction must hold on every harness; `AGENTIC_SESSION_ID`
  and `CLAUDE_SESSION_UUID` are dead, verified empty in a live session, and
  `bin/ds-migrate` is silently degraded today precisely because it reads them.
