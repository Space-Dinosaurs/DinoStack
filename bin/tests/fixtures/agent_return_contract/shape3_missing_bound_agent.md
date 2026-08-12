---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 3 negative fixture - a
  line whose value is neither a closed enum, a bare count, nor bounded to one
  line by its own placeholder text.
tools: Read, Glob, Grep, Bash
---

## Output format

Return exactly this structure and nothing else:

```
GOAL_MET: true|false
Evidence: <supporting detail>
```

## Rules

- This is a fixture file, not a real agent definition.
