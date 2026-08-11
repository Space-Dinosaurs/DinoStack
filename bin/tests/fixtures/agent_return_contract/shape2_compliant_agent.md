---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 2 (structured schema-object
  return) positive fixture - every classification field declares a closed
  enum, and every open-ended/repeated field declares an explicit bound.
tools: Read, Glob, Grep, Bash
---

## Output format

```yaml
status: DONE | FAILED | BLOCKED
skipped_reason: null   # enum: null | "zero-substance" | "no-consumer"
task_id: <string or null>
notes: |
  <one-line summary>
items_written: []  # capped at 20 entries; each item <one-line description>
```

## Rules

- This is a fixture file, not a real agent definition.
