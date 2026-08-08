<!--
Purpose: Single source of truth for the "Skill Loading" table that .claude/install.sh
         writes into ~/.claude/CLAUDE.md's managed-by-agentic-engineering block. Extracted
         so a resident-budget CI check and the installer can both read one canonical copy
         instead of drifting independently.

Public API: consumed verbatim (as markdown prose, manifest header stripped) by
            .claude/install.sh when it assembles the managed_content Python string, and by
            scripts/check-resident-budget.sh, which measures the post-manifest body of this
            file as the sole methodology content resident in every Claude Code session.

Upstream deps: none (leaf content file; no imports or code dependencies).

Downstream consumers: .claude/install.sh (reads this file at template_path and strips the
                      manifest header before writing the managed block to ~/.claude/CLAUDE.md);
                      scripts/check-resident-budget.sh (measures the post-manifest body).
                      Deliberately omits the three @-import lines
                      (METHODOLOGY.md, rules/code-standards.md, rules/conventions.md): the
                      trigger-loaded design removes those lines from the managed block
                      entirely rather than moving them here. install.sh still appends them
                      as a fallback when the skill symlink does not resolve (SKILL_LINK_OK
                      != true).

Failure modes: none (static content file; no execution).

Performance: standard.
-->

## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.
