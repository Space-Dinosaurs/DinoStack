## Capability Preflight

Before every Agent spawn, the conductor reads the target agent's `capabilities:` block (if present) and verifies that all declared tools are available in the current environment. Absent block = no-op for that agent.

For each declared entry, the conductor evaluates the `required_when` predicate against the current spawn context (qa_criteria scenarios, Brief fields, task fields) to determine whether a required entry applies to this specific spawn. Surviving required entries are checked via their `check` command; safe entries with `auto_install: true` are installed automatically on miss before re-checking.

**Advisory vs blocking mode** is controlled by `.agentic/config.json` `capability_preflight_mode` (default `blocking`). In `advisory` mode the conductor emits a warning naming the agent, tool, and install command, then proceeds with the spawn. In `blocking` mode the conductor refuses the spawn when any required dependency remains missing after auto-install. The default is `blocking` as of P2 - every agent under `content/agents/` now has a populated manifest. Setting `advisory` switches to warn-and-proceed.

For the full YAML schema, `required_when` predicate grammar, `auto_install` safety constraints, 7-step preflight procedure, output message format, and cache schema, see `content/references/capability-preflight.md`.
