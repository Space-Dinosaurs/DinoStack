<!--
Purpose: Single source of truth for the "Skill Loading" table that .claude/install.sh
         writes into ~/.claude/CLAUDE.md's managed-by-agentic-engineering block. Extracted
         so a resident-budget CI check and the installer can both read one canonical copy
         instead of drifting independently.

Public API: consumed verbatim (as markdown prose) by .claude/install.sh when it assembles the
            managed_content string for ~/.claude/CLAUDE.md's managed-by-agentic-engineering
            block, and by any CI budget check that needs to account for this content without
            duplicating it inline. This manifest comment header is repo metadata: install.sh
            strips everything up to and including the comment's closing delimiter before
            emitting the body, so none of this text reaches the user's CLAUDE.md.

Upstream deps: none (leaf content file; no imports or code dependencies).

Downstream consumers: .claude/install.sh (reads this file at run time when writing the
                      managed-by-agentic-engineering block; gated on AE_DRY_RUN and
                      SKILL_LINK_OK - DS-143). Deliberately omits the three @-import lines
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
