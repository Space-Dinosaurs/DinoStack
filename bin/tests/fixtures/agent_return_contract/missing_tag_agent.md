---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Used by test_agent_return_contract_spec.py.
tools: Read, Glob, Grep, Bash
---

## Output format

Every field below should be tagged per `content/references/subagent-return-contract.md`,
but this fixture deliberately omits the tag on one field to test the gate.

### Root cause
[Specific explanation, capped at 500 chars - but missing its [MECHANICAL] tag.]

### Confidence [MECHANICAL, enum]
[High / Medium / Low]

### Notes [ADVISORY]
[Optional context. Omitted entirely when empty - present here only as a fixture example.]

## Rules

- This is a fixture file, not a real agent definition.
