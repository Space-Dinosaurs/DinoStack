---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Reproduces silent-pass vector (a)
  from the round-2 Major finding: SECTION_START_RE.search is not fence-aware,
  so a fenced illustrative example containing "## Output format" earlier in
  the file wins the match and the real section is never inspected.
tools: Read, Glob, Grep, Bash
---

Example (illustrative only, shown inside a fence - not the agent's own
return-contract section):

```
## Output format

### Answer [MECHANICAL, cap: 100 chars]
[Tagged example inside the fence - deliberately compliant so a non-fence-aware
start scan that matches THIS heading first would wrongly report the file as
contract-compliant.]
```

## Output format

### Answer
[This is the REAL return-contract section's only field, deliberately left
untagged. A fence-aware start scan must skip the fenced example above and
land here, flagging this field as a violation.]

## Rules

- This is a fixture file, not a real agent definition.
