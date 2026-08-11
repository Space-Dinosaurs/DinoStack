---
name: fixture-agent
model: sonnet
description: Fixture only - not a real agent. Reproduces the round-2 MINOR
  finding - CAP_RE false-positives against header_text outside the tag
  bracket itself (a field's own title, or a parenthetical pointing
  elsewhere), when neither actually declares a cap inside the
  [MECHANICAL, ...] bracket.
tools: Read, Glob, Grep, Bash
---

## Output format

### Coverage of max 10 items [MECHANICAL]
[The cap-shaped phrase "max 10 items" is part of this field's TITLE, not a
cap declared inside its [MECHANICAL] tag bracket - the tag bracket declares
no cap at all. Must still be flagged.]

### Findings [MECHANICAL] (see cap: 300 chars in Rules)
[The cap-shaped phrase "cap: 300 chars" is a parenthetical pointer to the
Rules section below, not a cap declared inside this field's own
[MECHANICAL] tag bracket. Must still be flagged.]

### Notes [ADVISORY]
[Optional context. Omitted entirely when empty.]

## Rules

- This is a fixture file, not a real agent definition. Findings above are
  capped at 300 chars each - see the field for reference.
