<!--
Purpose: Operator-facing guide for the capability preflight system.
         Explains the capabilities: YAML block agents declare, required_when
         predicates, auto_install safety, advisory vs blocking mode, and what
         happens when a block is absent.

Public API: Operator-facing prose. Entry point for anyone who wants to add
            capability manifests to custom agents or tune the preflight mode.
            Deeper schema, predicate grammar, 7-step procedure, output format,
            and cache schema live in content/references/capability-preflight.md.

Upstream deps: content/references/capability-preflight.md (full spec);
               content/sections/06-capability-preflight.md (METHODOLOGY.md section);
               .agentic/config.json (capability_preflight_mode key).

Downstream consumers: docs site root index.

Failure modes: Stale if the schema, predicate grammar, mode default, or
               auto_install safety constraints change. Update alongside
               content/references/capability-preflight.md in the same change.

Performance: Standard.
-->

# Capability preflight

Before spawning any agent, the conductor checks whether the tools that agent
needs are actually installed. The check is driven by a `capabilities:` block
each agent optionally declares in its spec file. No block means no check - the
feature is fully incremental.

This document covers what to put in a `capabilities:` block, how the conductor
decides whether a missing tool blocks or just warns, and how to tune the
behavior per project.

The full schema, predicate grammar, 7-step procedure, output format, and cache
schema live in `content/references/capability-preflight.md`. This page is the
operator entry point.

## Why it exists

An agent that silently fails because a CLI tool is missing wastes a Worker turn
and produces confusing output. Capability preflight surfaces the gap before the
spawn, not after - you see "install: npm install --no-save @axe-core/playwright"
instead of a cryptic runtime error three steps into a QA run.

## The capabilities: block

Each agent spec under `content/agents/` may carry a top-level `capabilities:`
block. Two sections: `required` entries that must be present, and `optional`
entries that trigger a warning but never block a spawn.

```yaml
capabilities:
  required:
    - tool: "node"
      check: "command -v node"
    - tool: "@axe-core/playwright"
      check: "node -e \"require('@axe-core/playwright')\" 2>/dev/null"
      install: "npm install --no-save @axe-core/playwright"
      auto_install: true
      required_when: "scenario.method == 'accessibility'"
  optional:
    - tool: "agent-browser"
      check: "command -v agent-browser"
      install_hint: "npm install -g agent-browser"
```

**Field summary:**

| Field | Required? | Description |
|---|---|---|
| `tool` | Yes | Human-readable name, shown verbatim in preflight output. |
| `check` | Yes | POSIX shell command. Exit 0 = present; non-zero = missing. |
| `install` | Conditional | Machine-executable install command. Required when `auto_install: true`. Also used as the install hint when `install_hint` is absent. |
| `install_hint` | No | Human-facing install note. Overrides `install` in output when both are set. Use for commands with side effects (browser binary downloads, global installs) that cannot run automatically. |
| `auto_install` | No | Default `false`. When `true`, the conductor runs `install` automatically on miss, then re-checks before deciding. Restricted to safe side effects - see below. |
| `required_when` | No | Conditional predicate. When absent, the entry is always required. When present, evaluated per-spawn - entries that evaluate to `false` become optional warnings for that spawn. |

**Absent block.** When an agent carries no `capabilities:` block at all,
preflight is a no-op for that agent. Agents without a block are never blocked
by preflight. This keeps adoption incremental - existing agents work unchanged
until a manifest is added.

## required_when predicates

Use `required_when` when a tool is only needed for certain spawn contexts - for
example, an accessibility tool only needed when the QA scenario uses the
`accessibility` method.

The predicate language is a small fixed grammar:

```yaml
# true when any QA scenario uses the 'accessibility' method
required_when: "scenario.method == 'accessibility'"

# true when any scenario uses either method
required_when: "scenario.method == 'accessibility' || scenario.method == 'perceptual_diff'"

# true only when an accessibility scenario AND a wcag_level field are both present
required_when: "scenario.method == 'accessibility' && brief.has_field('wcag_level')"
```

Supported forms:

| Form | Meaning |
|---|---|
| `scenario.method == 'X'` | At least one QA scenario has `method == X`. |
| `scenario.method in ['X', 'Y']` | At least one scenario matches any value in the list. |
| `brief.has_field('name')` | The Brief for this spawn contains the named field. |

Combine atomics with `&&` (AND) and `||` (OR). `&&` binds tighter. Parentheses
are not supported. All string literals use single quotes.

When no Brief is present (single-unit Trivial or ad-hoc spawn),
`brief.has_field('anything')` evaluates to `false`, so entries gated only on
that form are downgraded to optional for briefless spawns.

## auto_install safety

`auto_install: true` is restricted to commands whose only side effect is
mutating `node_modules/` in the project directory or `~/.local/` pip user
site-packages.

**Permitted:**
- `npm install --no-save <pkg>` - project `node_modules/` only; does not touch `package.json` or lock files.
- `pip install --user <pkg>` - user site-packages; no global or system path mutation.

**Forbidden (use `install_hint` instead):**
- Anything that downloads browser binaries (e.g. `playwright install chromium`).
- Global npm installs (`npm install -g <pkg>`).
- Anything requiring `sudo` or elevated privileges.
- Anything that mutates `package.json`, lock files, or any manifest.

If your install command falls in the forbidden category, set `install_hint`
with the human-facing instruction and leave `auto_install` off. The hint is
surfaced as an action item in preflight output but never auto-executed.

## Advisory vs blocking mode

The mode controls what happens when a required tool is missing after any
auto-install attempt.

| Mode | Behavior |
|---|---|
| `advisory` | Emit a warning with the agent name, tool, and install hint. Proceed with the spawn. |
| `blocking` | Emit the same warning. Refuse the spawn until the dependency is resolved. |

Set the mode in `.agentic/config.json`:

```json
{
  "capability_preflight_mode": "advisory"
}
```

Valid values: `advisory` and `blocking`. Any missing or unrecognized value
falls back to `blocking`. The default is `blocking` as of P2, because all
shipped AE agent manifests are now populated. In `blocking` mode the conductor
refuses a spawn when a required declared dependency is still missing after the
auto-install attempt. `advisory` mode (warn and proceed) is opt-in - set
`capability_preflight_mode: advisory` in `.agentic/config.json` if you are
still populating manifests on custom agents and do not want spawns blocked in
the interim.

## What preflight output looks like

When a dependency is missing, the conductor emits a structured notice before
deciding whether to proceed or refuse:

```
qa-engineer preflight: blocking
  required missing: @axe-core/playwright -- install: npm install --no-save @axe-core/playwright
  optional missing: agent-browser -- install: npm install -g agent-browser
```

The exact format is illustrative - runtime output formatting may differ
slightly. When all checks pass, nothing is emitted - a clean preflight produces
no output.

## Cache

Successful checks are cached in `.agentic/.capability-cache.json` (gitignored)
under a key of `<agent>:<tool>`, with a 30-minute TTL. Miss results are never
cached, so installing a dep mid-session is picked up immediately on the next
spawn without any manual cache-bust.

## Related references

- `content/references/capability-preflight.md` - full spec: YAML schema, predicate grammar, 7-step flow, cache schema, POSIX shell precondition.
- `content/sections/06-capability-preflight.md` - the METHODOLOGY.md section that governs when preflight runs relative to the QA gate and Worker boot.
- `.agentic/config.json` - project-level config where `capability_preflight_mode` lives.
