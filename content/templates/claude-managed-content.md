<!--
Purpose: Single source of truth for the "Skill Loading" table that .claude/install.sh
         writes into ~/.claude/CLAUDE.md's managed-by-agentic-engineering block. Extracted
         so a resident-budget CI check and the installer can both read one canonical copy
         instead of drifting independently.

Public API: intended to be consumed verbatim (as markdown prose) by .claude/install.sh when
            it assembles the managed_content Python string, and by any CI budget check that
            needs to account for this content without duplicating it inline. Not yet wired -
            .claude/install.sh still carries this table inline; a later unit of DS-143 points
            the installer at this file.

Upstream deps: none (leaf content file; no imports or code dependencies).

Downstream consumers: none yet (.claude/install.sh does not read this file as of this unit -
                      see Public API). Deliberately omits the three @-import lines
                      (METHODOLOGY.md, rules/code-standards.md, rules/conventions.md): the
                      trigger-loaded design removes those lines from the managed block
                      entirely rather than moving them here.

Failure modes: none (static content file; no execution).

Performance: standard.
-->

## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.
