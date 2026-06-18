<!--
Purpose: Documents the harness model discovery protocol used by the
         Pi/oh-my-pi role-model routing layer. The discovery binary
         (`bin/agentic-models`) and the setup wizard (`bin/agentic-configure`)
         read this spec to populate `role-models.yml` against models the user
         actually has on the harness (e.g. 9router).

Public API: Read-only reference. Load when probing the harness for available
            models, when seeding role-models.yml, or when adding new roles /
            effort / reasoning fields.

Upstream deps: content/references/role-models.md (parent schema);
               content/sections/04-risk-classification.md (Role-model
               routing tier); bin/agentic-models (the implementation).

Downstream consumers: bin/agentic-configure (TUI; uses --json);
                      content/commands/init-project.md (Step 6g seed path);
                      content/sections/04-risk-classification.md.

Failure modes: Probe failure is non-fatal: the binary exits 2 and emits a
               single error line. The setup wizard catches that and falls
               back to the scalar-only form of role-models.yml with the
               user typing model names by hand. There are NO hardcoded model
               catalogs anywhere in the repo; suggestions are derived from
               live probe data plus the hint dictionaries in the binary.

Performance: Standard. Probe is one HTTP GET; suggestion rank is O(M * R)
              where M is model count and R is role count, both small.
-->

# Model discovery - Pi / oh-my-pi reference

The role-model routing layer in `content/references/role-models.md` lets the user pin a specific model per role. The **discovery layer** described here figures out _which models are actually available on the user's harness_ so the user is not asked to type strings from memory.

This is consulted ONLY on the Pi (`.pi`) and oh-my-pi (`.omp`) harnesses. On Claude/Codex/Gemini the user picks models from the harness's built-in catalog; there is nothing to discover.

## Why a separate discovery step

Role-model routing accepts any string the harness recognises, but the strings vary per harness and per provider. On 9router the user has 60+ models; on a fresh Pi session the user has 4. Hardcoding a model catalog in the repo contradicts the "no hardcoded model IDs" stance and drifts the moment a provider releases a new model. Discovery is the boring solution: ask the harness what it has, rank against the role heuristics, surface the best fit per role, let the user override.

## The binary: `bin/agentic-models`

```
agentic-models [--json] [--probe-url URL] [--probe-key KEY] \
               [--suggest <role>] [--all-suggestions] [--timeout 10]
```

Default mode prints a human-readable summary. `--json` emits the structured payload consumed by the TUI. `--suggest <role>` prints only one role's primary recommendation (used by hooks that want a quick default without parsing JSON).

**Probe protocol.** The binary issues one `GET {NINEROUTER_URL}/models` (or `--probe-url` override) with optional `Authorization: Bearer {NINEROUTER_KEY}`. It expects an OpenAI-compatible `/v1/models` response with a `data: [{id, ...}]` shape. The probe is the only network call. There is no fallback to a hardcoded catalog.

**Exit codes.** 0 on success, 2 on probe failure, 3 on invalid arguments. The setup wizard treats 2 as "user must type models by hand" and offers to retry with a different `--probe-url`.

**Heuristics.** Per role, the binary scores every model with a small hint dictionary. Substring match is case-insensitive; higher score wins. The hint tables are tuned so Opus-class models surface for the architect / security-auditor tier, Sonnet-class for engineer / debugger, Haiku-class for investigator / qa-engineer, and cross-family candidates (Kimi, GLM, GPT-5.x) for the reviewer pool so the antagonist is plausibly as good as the author without being the same model.

**No hardcoded model IDs.** The hint tables in `bin/agentic-models` use family names (`opus`, `sonnet`, `gpt-5`, `kimi-k2.7`, `glm-5.2`) as substring needles, not exact model strings. Adding a new model to the harness does not require any code change; the substring matcher picks it up.

## Schema extension: effort and reasoning

`role-models.yml` accepts a per-role mapping in addition to the scalar form. The mapping carries three keys:

| Key         | Type   | Default | Notes                                                                                                             |
| ----------- | ------ | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `model`     | string | unset   | The model id the harness recognises. Required for the spawn to have any effect.                                   |
| `effort`    | string | unset   | Pass-through; the harness interprets (e.g. `low` / `medium` / `high` / `xhigh`). Conductor does not validate.     |
| `reasoning` | string | unset   | Pass-through; the harness interprets (e.g. `enabled` or a token budget like `8192`). Conductor does not validate. |

**Resolution rules** (full algorithm in `role-models.md`):

1. If the role value is a string, treat it as `{model: <string>}` and `effort`/`reasoning` stay unset.
2. If the role value is a mapping, copy present keys. Absent keys are not passed on the spawn call; the harness uses its own default.
3. Unknown keys in the mapping are passed through unchanged.

The conductor forwards `model`, `effort`, and `reasoning` to the spawn call as separate parameters (or whatever the harness API takes). The setup wizard surfaces only the keys the live harness accepts -- it does not ask for `reasoning` on a model the harness lists without reasoning support.

**Backward compatibility.** Files written against the scalar-only schema (PR #249) continue to work: every scalar `engineer: sonnet` becomes `{model: sonnet}` at load time. No migration is required.

## Worked probe

Running `bin/agentic-models --probe-url $NINEROUTER_URL` against a typical 9router setup:

```
Probe URL: https://9router.example/v1
Models discovered: 61

Per-role primary recommendation:
    conductor              -> cc/claude-opus-4-5
    architect              -> cc/claude-opus-4-5
    engineer               -> cc/claude-sonnet-4-5
    debugger               -> cc/claude-sonnet-4-5
    qa-engineer            -> cc/claude-haiku-4-5
    skeptic                -> cc/claude-opus-4-5
    security-auditor       -> cc/claude-opus-4-5

Reviewer pool (distinct-from-author / round-robin candidates):
  - cx/gpt-5.5
  - cx/gpt-5.4
  - kimi/kimi-k2.5-thinking
  - kimi/kimi-k2.7
  - glm/glm-5.2
```

The reviewer pool deliberately pulls cross-family candidates so the `distinct-from-author` strategy always has a non-Claude option when the author is Claude.

## Failure modes

- **Probe unreachable.** The binary exits 2 with `error: probe failed: <reason>` on stderr. The setup wizard offers the user three options: (a) retry with a different `--probe-url`; (b) skip discovery and type model names by hand; (c) abort setup and run the binary manually.
- **Probe succeeds, no models match hints.** Every role's `primary` is `(no match)`. The setup wizard shows the raw model list and lets the user pick; it does not invent defaults.
- **Harness does not support `effort` or `reasoning`.** The conductor forwards only the keys the user's spawn target supports. There is no error; the harness silently ignores unknown parameters.
- **Probe returns a non-OpenAI shape.** The binary fails with `error: probe failed: Expecting value` or similar JSON decode error. The user is told to check the `--probe-url` and that the harness implements the OpenAI `/v1/models` endpoint.
