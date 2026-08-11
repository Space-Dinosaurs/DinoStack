---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Used by test_agent_return_contract_spec.py.
tools: Read, Glob, Grep, Bash
---

## Output format

This field's header declares no cap. Its body happens to contain an
unrelated cap-shaped phrase ("at max 3 items of supporting evidence") that
is NOT a cap declaration for this field - it is describing something else
entirely. A body-wide CAP_RE search would wrongly treat that phrase as
satisfying this field's cap requirement; the gate must anchor the cap
requirement to the field's own header text only.

### Root cause [MECHANICAL]
[Specific explanation. Cite at max 3 items of supporting evidence for the
root cause - this phrase is NOT this field's cap declaration, it is
describing evidence-citation style, and must not satisfy CAP_RE.]

### Confidence [MECHANICAL, enum]
[High / Medium / Low]

### Notes [ADVISORY]
[Optional context. Omitted entirely when empty.]

## Rules

- This is a fixture file, not a real agent definition.
