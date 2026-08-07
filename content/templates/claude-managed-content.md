<!--
Purpose: Single source of truth for the "Skill Loading" table that .claude/install.sh
         writes into ~/.claude/CLAUDE.md's managed-by-agentic-engineering block. Extracted
         so a resident-budget CI check and the installer can both read one canonical copy
         instead of drifting independently.

Public API: consumed verbatim (as markdown prose) by .claude/install.sh when it assembles
            the managed_content Python string, and by any CI budget check that needs to
            account for this content without duplicating it inline.

Upstream deps: none (leaf content file; no imports or code dependencies).

Downstream consumers: .claude/install.sh (managed_content block writer). Does NOT include
                      the three @-import lines (METHODOLOGY.md, rules/code-standards.md,
                      rules/conventions.md) - those are appended separately by the installer
                      because their presence depends on the Claude-build embed decision
                      (see .claude/build.sh's "Embedded Resident Content" step).

Failure modes: none (static content file; no execution).

Performance: standard.
-->

## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.
