---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Shape 4 (fixed markdown-sectioned
  flat report) positive fixture - the status line declares a closed enum, and
  every other section's open-ended placeholder declares an explicit cap.
tools: Read, Glob, Grep, Bash
---

## Report structure

```
# Release Report: vX.Y.Z

## Status: SUCCESS | FAILED | ROLLED_BACK | BLOCKED

## What shipped
- Version: vX.Y.Z

## Failures and blockers
<If status is not SUCCESS: which gate failed, what the error was, what was
done - max 500 chars>
```

## Rules

- This is a fixture file, not a real agent definition.
