---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Round-2 regression fixture - a
  file whose return-contract section uses a heading not in HEADING_SYNONYMS
  and is not present in any shape-assignment or exemption allowlist. Must
  fail loudly (a non-empty violation), never silently skip.
tools: Read, Glob, Grep, Bash
---

## Bespoke response shape

### Answer
[This section uses a heading with no recognized synonym - the extractor
must not silently treat this file as having "no section" and skip it
without a loud violation.]

## Rules

- This is a fixture file, not a real agent definition.
