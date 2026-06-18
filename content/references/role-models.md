<!--
Purpose: Defines the Pi / oh-my-pi role-model routing layer for mapping
         agentic-engineering roles and adversarial reviewers to concrete
         model strings.

Public API: Read-only reference. Load when authoring `role-models.yml` or
            resolving a Pi/omp role spawn, skeptic spawn, or
            security-auditor spawn.

Upstream deps: content/sections/04-risk-classification.md (Tier declaration);
               content/references/role-models-example.yml (example library).

Downstream consumers: content/sections/04-risk-classification.md (inline pointer);
                      content/agents/skeptic.md;
                      content/agents/security-auditor.md;
                      content/commands/init-project.md;
                      bin/agentic-status.

Failure modes: Prose + YAML schema; not auto-executed. Mis-set author-model
               tracking is the common error path: reviewer diversity depends
               on the conductor recording the model used for the author spawn
               and carrying it into the reviewer spawn.

Performance: Standard.
-->

# Role-model routing - Pi / oh-my-pi reference

This layer is consulted ONLY on the Pi (`.pi`) and oh-my-pi (`.omp`) harnesses. On Claude/Codex/Gemini the conductor ignores `role-models.yml` entirely and uses the existing Tier mechanism. The conductor determines the harness from its own runtime identity; if unsure, treat the session as not-Pi and skip this layer.

## File locations + resolution

**Role-model library location:**
- Global: `~/.agentic/role-models.yml`
- Project override: `.agentic/role-models.yml` (wins on key collision; merged shallowly per top-level key)

If neither file exists when a Pi/omp spawn happens, the conductor omits the `model` field and Pi uses its session default. There are NO hardcoded model IDs anywhere in the repo or adapters.

The file is **gitignored** under the `.agentic/` umbrella because it may name user-private model handles. Unlike `.agentic/config.json`, it is NOT carved out. Do NOT add a `!` exception in `.gitignore` for `role-models.yml` by default.

## Schema

```yaml
roles:
  conductor: opus              # advisory; applies only if the harness re-roots the main agent
  investigator: glm-4.6
  architect: opus
  orchestration-planner: opus
  engineer: sonnet
  debugger: sonnet
  qa-engineer: glm-4.6
  skeptic: gpt-5
  security-auditor: gpt-5

reviewers:
  strategy: distinct-from-author   # distinct-from-author | round-robin | by-task
  pool:
    - gpt-5
    - glm-4.6
  by_task:
    security: gpt-5
    architecture: opus
    correctness: glm-4.6
    default: sonnet
  fallback: gpt-5
```

`roles:` maps `<role>: <model-string>`. Supported role keys are exactly: `conductor`, `investigator`, `architect`, `orchestration-planner`, `engineer`, `debugger`, `qa-engineer`, `skeptic`, `security-auditor`. Any role absent from the map means the conductor omits `model` for that spawn and Pi uses its session default. `conductor` is advisory: it applies only if the harness supports re-rooting the main agent; otherwise it is ignored because the main session model is already running.

`reviewers:` controls adversarial-reviewer model diversity for `skeptic` and `security-auditor` spawns.

- `strategy:` enum, exactly one of `distinct-from-author`, `round-robin`, or `by-task`. Default when `reviewers:` exists but `strategy:` is absent: `distinct-from-author`.
- `pool:` ordered list of model strings the reviewer may use. Required when `strategy` is `distinct-from-author` or `round-robin`.
- `by_task:` map of `<task-kind>: <model-string>`, required only when `strategy: by-task`. Task kinds are `security`, `architecture`, `correctness`, and `default`. `default` is the fallback when no specific kind matches.
- `fallback:` single model string used when the strategy cannot pick, such as `distinct-from-author` with the only pool model equal to the author model. Optional; if absent and the strategy cannot pick, the conductor omits `model` and notes the fallback inline.

## Resolution algorithm

1. Conductor reads `.agentic/role-models.yml` if it exists; merges it shallowly over `~/.agentic/role-models.yml`. Project keys win on collision.
2. For a non-reviewer role spawn, resolve `model = roles[<role>]` if present. If absent, omit `model`.
3. For a reviewer spawn (`skeptic` or `security-auditor`), determine the **author model**: the model the conductor used for the engineer or architect spawn that produced the diff or plan under review. The conductor tracks this in-context. If untracked or unknown, treat author model as the session default string and proceed.
4. Apply `reviewers.strategy`:
   - `distinct-from-author`: pick the first `pool` entry that is not equal to the author model. If all pool entries equal the author model, use `fallback` if set, else omit `model`.
   - `round-robin`: pick `pool[i mod len(pool)]` where `i` is the count of reviewer spawns so far this session. The conductor maintains the counter in-context, starting at 0. Round-robin ignores author identity by design; it does not guarantee distinctness from the author. Users who need guaranteed distinctness should use `distinct-from-author`.
   - `by-task`: pick `by_task[<kind>]` where kind is derived from the adversarial brief. `security-auditor` or a security brief maps to `security`; architect-plan review maps to `architecture`; otherwise use `correctness`; final fallback is `default`. If the resolved kind is absent from `by_task`, use `by_task.default`; if `default` is absent, omit `model`.
5. Pass the resolved reviewer model as the `model` field of the reviewer subagent spawn.

## Interaction with Tier and presets

`role-models.yml` resolves the concrete `model` string. The `Tier:` declaration and `Preset:` line remain the conductor's capability-intent signal and still appear in the spawn declaration. On Pi/omp, when both a Tier and a `roles[<role>]` entry exist, the explicit `roles[<role>]` model string wins for the model param because it is the more specific, user-authored intent, and the conductor notes the override inline. The Tier line is still printed for review evidence.

## Worked example

```yaml
roles:
  architect: opus
  engineer: sonnet
  skeptic: gpt-5
  security-auditor: gpt-5

reviewers:
  strategy: distinct-from-author
  pool:
    - gpt-5
    - glm-4.6
  fallback: gpt-5
```

Resolution traces:
- `role=engineer` -> `roles.engineer=sonnet` -> spawn `model=sonnet`.
- `author=opus`, `strategy=distinct-from-author`, `pool=[gpt-5, glm-4.6]` -> reviewer `model=gpt-5`.
- `author=opus`, `strategy=distinct-from-author`, `pool=[opus]`, `fallback=gpt-5` -> reviewer `model=gpt-5`.
- `author=opus`, `strategy=distinct-from-author`, `pool=[opus]`, no `fallback` -> omit `model` and note session-default fallback.
