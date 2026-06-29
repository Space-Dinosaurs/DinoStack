<!--
Purpose: Full reference for capability manifest schema and conductor preflight
         flow. Defines the YAML schema agents carry under `capabilities:`,
         the `required_when` predicate grammar, auto_install safety constraints,
         the 7-step preflight procedure, mode resolution, cache semantics, and
         the verbatim output message format.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/06-capability-preflight.md (parent section);
            content/sections/12-protocol-details.md (Protocol Details entry);
            content/agents/qa-engineer.md (populated capabilities block).

Upstream deps: content/sections/05-qa-gate.md (preflight runs before every
               Agent spawn, after QA gate decision, before worker boot);
               .agentic/config.json (capability_preflight_mode key);
               .agentic/.capability-cache.json (runtime hit cache, TTL 30 min).

Downstream consumers: conductor (reads agent spec capabilities: block before
                      every spawn); all agents now have populated manifests
                      as of P2 (qa-engineer at P0, remaining 9 at P2).

Failure modes: Prose; does not execute. advisory mode warns and proceeds on
               missing deps. blocking mode (default as of P2) refuses the
               spawn when required deps fail check after auto_install attempt.

Performance: Standard. Check commands are fast shell one-liners. Cache TTL
             of 30 min prevents re-running checks on every spawn in a session.
-->

> Parent section: METHODOLOGY.md §Capability Preflight. Read that section first for when preflight runs and the advisory-vs-blocking decision.

# Capability Preflight - Full Reference

## YAML schema

Each agent spec under `content/agents/` MAY carry a top-level `capabilities:` block (outside the YAML frontmatter, in the body). The block structure:

```yaml
capabilities:
  required:
    - tool: "<display name or package identifier>"
      check: "<POSIX shell command>"   # exit 0 = present, non-zero = missing
      install: "<install command>"     # used by auto_install and surfaced as hint
      install_hint: "<human-readable install note>"  # optional; overrides `install` in output when present
      auto_install: true | false       # see auto_install safety constraints below
      required_when: "<predicate>"     # optional; absent = unconditionally required
  optional:
    - tool: "<display name>"
      check: "<POSIX shell command>"
      install_hint: "<human-readable install note>"
```

**Field semantics:**

| Field | Required? | Description |
|---|---|---|
| `tool` | Yes | Human-readable name. Surfaced verbatim in preflight output. |
| `check` | Yes | POSIX shell command. Exit 0 = present; non-zero = missing. Stderr suppressed by the preflight runner; agents do not redirect it in the spec. |
| `install` | Conditional | Machine-executable install command. Required when `auto_install: true`. Also surfaced as the install hint when `install_hint` is absent. |
| `install_hint` | Optional | Human-facing install note. Overrides `install` in preflight output when both are set. Use for commands with forbidden side effects (browser binary downloads, global installs) that cannot run under `auto_install`. |
| `auto_install` | Optional | Boolean; default `false`. When `true`, the preflight runner executes `install` automatically when the check fails. Restricted to safe side effects only - see constraints below. |
| `required_when` | Optional | Predicate string. When absent, the entry is unconditionally required. When present, evaluated per-spawn; entries evaluating to `false` are downgraded to optional (warn-on-miss) for that spawn only. |

**Absent `capabilities:` block.** When an agent has no `capabilities:` block at all, preflight is a complete no-op for that agent. This makes adoption incremental: agents that have not yet declared their manifest are never blocked.

**Empty block.** `required: []` and `optional: []` are explicit no-ops (declared but nothing to check). Preferred over absence during the P0/P1 ramp because it signals that the manifest has been considered rather than not yet touched.

---

## `required_when` predicate grammar

The predicate language is a small fixed grammar. No arbitrary code; only the forms listed here are valid.

### Atomic predicates

| Form | Evaluates to |
|---|---|
| `scenario.method == 'X'` | `true` when the spawn's `qa_criteria.scenarios[]` contains at least one entry with `method == X` |
| `scenario.method in ['X', 'Y']` | `true` when at least one scenario's method matches any value in the list |
| `brief.has_field('name')` | `true` when the Brief governing this spawn contains the named field (top-level key or YAML key within `qa_criteria`); `false` when no Brief is present or the field is absent |

### Compound predicates

Atomic predicates joined by `&&` (logical AND) or `||` (logical OR).

**Operator precedence:** `&&` binds tighter than `||`. Parentheses are NOT supported in P0. Evaluate `&&` chains first, then evaluate `||` across the resulting groups.

Example: `scenario.method == 'accessibility' || scenario.method == 'perceptual_diff'` - true when any scenario uses either method.

Example: `scenario.method == 'accessibility' && brief.has_field('wcag_level')` - true only when an accessibility scenario is present AND the Brief declares a `wcag_level` field.

### String quoting

All string literals MUST use single quotes. Double quotes are not supported. Whitespace around `==`, `in`, `&&`, `||` is ignored.

### `brief.has_field()` when Brief is absent

When the spawn has no Brief (single-unit Trivial or ad-hoc spawn), `brief.has_field('anything')` evaluates to `false`. Entries gated only on `brief.has_field()` are downgraded to optional for briefless spawns.

---

## `auto_install: true` safety constraints

`auto_install: true` is restricted to commands whose ONLY side effect is mutating `node_modules/` in the project directory or `~/.local/` / pip `--user` site-packages. The preflight runner MUST enforce these constraints before executing any auto_install command.

**Specifically permitted:**
- `npm install --no-save <pkg>` (mutates project `node_modules/` only; does not update `package.json` or `package-lock.json`)
- `pip install --user <pkg>` (mutates user site-packages; no global or system path mutation)

**Specifically forbidden in `auto_install: true` entries:**
- Anything that downloads browser binaries to system or user caches (e.g., `playwright install chromium` - downloads ~150MB to `~/.cache/ms-playwright`)
- Global npm installs (`npm install -g <pkg>`)
- Anything requiring `sudo` or elevated privileges
- Anything that mutates `package.json`, `package-lock.json`, `yarn.lock`, `requirements.txt`, `pyproject.toml`, or any manifest/lock file

Commands in the forbidden set MUST use `install_hint` instead of `install + auto_install: true`. The install hint is surfaced as an operator action item in the preflight output, not auto-executed.

---

## Conductor preflight flow

Run before every Agent spawn when the target agent's spec contains a `capabilities:` block.

1. **Read `capabilities:` block.** If absent, skip preflight entirely for this spawn (no-op).

2. **Resolve `required_when` per spawn.** For each entry under `required:`, evaluate its `required_when` predicate (if present) against the current spawn context: the spawn's `qa_criteria` block (when spawning qa-engineer), the Brief's success criteria and fields, and the unit's task fields. Entries whose `required_when` evaluates to `false` are downgraded to optional (warn-on-miss) for this spawn. Entries with no `required_when` are unconditionally required.

3. **Check each entry.** For every required entry surviving step 2, and for every optional entry, run the `check` command. Check commands MUST be POSIX-shell compatible (the methodology already assumes POSIX shell; Windows operators run via WSL or Git Bash - native PowerShell is not supported). Cache each HIT result under `.agentic/.capability-cache.json` keyed by `(agent, tool)` with a 30-minute TTL.

4. **Cache miss policy: cache hits only.** Miss results are NEVER cached. An operator who installs a dep mid-session sees it picked up on the next spawn without any manual cache-bust operation.

5. **Auto-install.** For each `required` entry that failed its check where `auto_install: true`: execute the `install` command, then re-run the `check`. If the re-check still fails, treat the entry as a regular miss (continue to step 6). If the re-check passes, cache the hit and proceed.

6. **Emit preflight output.** Collect all remaining required misses and optional misses. Emit the verbatim message template (see Output format below). In `advisory` mode: emit and proceed with the spawn. In `blocking` mode: emit and refuse the spawn when any required miss remains after step 5.

7. **Mode resolution.** Read `capability_preflight_mode` from `.agentic/config.json`. Valid values: `advisory` and `blocking`. Any missing or unrecognized value falls back to `blocking` (default as of P2 - all agent manifests are now populated). Projects seeded before P2 that have `advisory` in their config retain their existing value.

---

## Output format

When preflight finds any missing dependency, emit the following verbatim block (adapt `<agent>`, `<mode>`, and the line items to match the specific agent and findings):

```
<agent> preflight: <mode>
  required missing: <tool> — install: <install_hint or install>
  optional missing: <tool> — install: <install_hint>
```

- Omit the `required missing:` section when there are no required misses.
- Omit the `optional missing:` section when there are no optional misses.
- When both sections are empty, emit nothing (no preflight output for a clean check).
- `<mode>` is either `advisory` or `blocking` (the resolved mode from config).

Example (blocking mode, one required miss, one optional miss):

```
qa-engineer preflight: blocking
  required missing: @axe-core/playwright — install: npm install --no-save @axe-core/playwright
  optional missing: agent-browser — install: npm install -g agent-browser
```

---

## Cache schema

File: `.agentic/.capability-cache.json` (gitignored under the `.agentic/` umbrella).

```json
{
  "<agent>:<tool>": {
    "result": "present",
    "checked_at": "<ISO8601 UTC timestamp>"
  }
}
```

- Only `"present"` (hit) entries are written. Miss results are not stored.
- TTL is 30 minutes from `checked_at`. Expired entries are re-checked on next spawn.
- The file is created on first hit; absence is equivalent to an empty cache.
- The conductor is the sole writer. Subagents do not write this file.

---

## POSIX shell precondition

All `check` commands in capability manifests MUST be valid POSIX `/bin/sh` commands. The preflight runner executes them with `sh -c '<check>'` and reads the exit code (0 = present, non-zero = missing). Stderr is discarded by the runner; `check` commands do not need to redirect it themselves.

The methodology already assumes POSIX shell as the ambient environment. Windows operators run via WSL or Git Bash; native PowerShell syntax in `check` commands will fail silently and be treated as a miss.
