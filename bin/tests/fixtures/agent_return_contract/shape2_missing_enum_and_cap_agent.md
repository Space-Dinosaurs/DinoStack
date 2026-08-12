---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 2 negative fixture - a
  classification field with no closed enum, and a block-scalar field with no
  declared cap.
tools: Read, Glob, Grep, Bash
---

## Output format

```yaml
status: null
skipped_reason: null
notes: |
  <open-ended free text field, unbounded and unmarked>
```

## Rules

- This is a fixture file, not a real agent definition.
