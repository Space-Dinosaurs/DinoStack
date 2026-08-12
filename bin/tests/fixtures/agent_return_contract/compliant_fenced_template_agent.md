---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Used by test_agent_return_contract_spec.py.
tools: Read, Glob, Grep, Bash
---

## Output format

Use this exact structure - reproduces the real content/agents/*.md corpus
shape (e.g. debugger.md), where the field template lives inside a fenced
code block that itself contains a '##'-level example line. A section-end
scan that is not fence-aware truncates the section at that in-fence line,
long before it reaches the real end-of-section heading ('## Rules' below).

```
## Diagnosis: [one-line description of the bug]

### Root cause [MECHANICAL, cap: 500 chars]
[Specific explanation.]

### Confidence [MECHANICAL, enum]
[High / Medium / Low]

### Notes [ADVISORY]
[Optional context. Omitted entirely when empty.]
```

## Rules

- This is a fixture file, not a real agent definition.
- At max 3 items of supporting evidence may be cited elsewhere in this file - this sentence exists only to prove CAP_RE does not scan outside the field's own header text; it must never satisfy any field's cap requirement.
