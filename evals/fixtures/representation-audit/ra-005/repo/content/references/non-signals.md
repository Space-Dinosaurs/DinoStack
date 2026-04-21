# non-signals

Patterns below are explicit Non-Signals per `/representation-audit`. The analyst must NOT flag these as candidates.

## Table of agent roles (NOT an R-signal candidate)

| Agent     | Role                              |
|-----------|-----------------------------------|
| Engineer  | Implements scoped tasks           |
| Skeptic   | Adversarial review                |
| Conductor | Session orchestration             |
| Architect | Pre-implementation design         |
| Debugger  | Root-cause diagnosis              |

## Short rule (brevity is correct - NOT a candidate)

Fail fast on dirty trees.

## Proper agent names in normative rules (NOT R4 candidates)

The engineer runs the quality gates. The skeptic reviews the diff. The orchestration-planner emits the routing decision. These are the protocol's proper nouns; rewriting them to role descriptions in normative rules would degrade precision.

## Fenced code block (NOT an R3 candidate)

```
git fetch origin
git status
git diff --stat origin/main...HEAD
```

Exact-syntax CLI examples inside code fences are appropriate as-is.
