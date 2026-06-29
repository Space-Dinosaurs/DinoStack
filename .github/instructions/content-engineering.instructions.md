---
applyTo: "content/**"
---

# Content Engineering Rules

These rules apply when authoring or modifying files under `content/`.

## Module Manifests

Non-trivial modules should carry a manifest header. Any source file that exports a
public symbol consumed by another module, is over ~50 lines of non-trivial logic, or
implements a side-effecting operation (network, disk, database, external service) should
include a manifest comment at the top of the file. Required fields: Module/Purpose,
Role, Inputs, Outputs, Side-effects, Consumers, Failure modes.

## DRY and Abstraction

Do not Repeat Yourself. Before writing new content:
- Grep the existing files for material that already covers the sub-topic.
- Prefer adding a cross-reference to an existing reference doc over duplicating it.
- Extract repeated rule patterns into a shared reference file and link to it.

If duplication is genuinely appropriate (two paths are about to diverge), state the
reason explicitly in a comment at the top of the section.

## Writing Style

- No em dashes (--). Use regular hyphens (-) instead.
- Concise and direct. Avoid marketing voice.
- Lead with the rule, follow with the rationale.
- Use second-person ("you", "the conductor") not passive voice.

## Cross-Reference Discipline

When a rule in `content/rules/` references detail in `content/references/`, use the
"read on trigger" pattern: state the trigger condition inline, then name the reference
file. Do not inline the full reference body into the rules file.
