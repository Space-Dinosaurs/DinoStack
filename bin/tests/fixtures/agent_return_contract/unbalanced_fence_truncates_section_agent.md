---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Reproduces silent-pass vector (b)
  from the round-2 Major finding: _fenced_spans pairs fence markers
  positionally under an unverified "fences are balanced" assumption. An odd
  (unbalanced) fence-marker count inside the section mis-pairs everything
  after it, so an in-fence "##"-level example line is wrongly treated as
  NOT fenced and truncates the section before the real untagged field.
tools: Read, Glob, Grep, Bash
---

## Output format

Here is a stray fence marker used inline in prose, not meant as a real code block:
```
end of stray block, unrelated content

The real template:
```

### Root cause [MECHANICAL, cap: 500 chars]
[content]

## Diagnosis: [example, illustrative only, appears mid-fence in the real corpus pattern]

### Evidence
[This field should be flagged untagged, but an extractor that assumes
balanced fences truncates the section at the in-fence "## Diagnosis:" line
above and never reaches this field.]
```

## Rules

- This is a fixture file, not a real agent definition.
