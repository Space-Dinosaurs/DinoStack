---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 4 negative fixture - the
  "Failures and blockers" section's open-ended placeholder declares no cap.
tools: Read, Glob, Grep, Bash
---

## Report structure

```
# Release Report: vX.Y.Z

## Status: SUCCESS | FAILED | ROLLED_BACK | BLOCKED

## What shipped
- Version: vX.Y.Z

## Failures and blockers
<If status is not SUCCESS: which gate failed, what the error was, what was done>
```

## Rules

- This is a fixture file, not a real agent definition.
