---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 3 (fixed literal-line
  template) positive fixture - every line's value is a closed enum, a bare
  count, or explicitly bounded to one line by its own placeholder text.
tools: Read, Glob, Grep, Bash
---

## Output format

Return exactly this structure and nothing else:

```
GOAL_MET: true|false
Evidence: <one-line quote, count, or file:line citation>
```

## Rules

- This is a fixture file, not a real agent definition.
