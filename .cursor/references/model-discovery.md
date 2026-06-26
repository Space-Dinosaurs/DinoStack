<!--
Purpose: Documents how the Pi / oh-my-pi role-model routing layer selects
         models. Discovery is ask-user (the configure wizard prompts you per
         role) or harness-native (your login/subscription exposes models).
         Model names are pinned by hand in role-models.yml.

Public API: Read-only reference. Load when seeding role-models.yml, when
            adding new roles, or when adding effort / reasoning fields.

Upstream deps: content/references/role-models.md (parent schema);
               content/sections/04-risk-classification.md (Role-model
               routing tier); bin/agentic-models (ranking implementation).

Downstream consumers: bin/agentic-configure (TUI; ranking input);
                      content/commands/init-project.md (Step 6g seed path);
                      content/sections/04-risk-classification.md.

Failure modes: If no role-models.yml exists, the conductor omits model/effort/
               reasoning for every spawn and Pi uses its session default.
               This is not an error - it is the documented no-op path.
               There are NO hardcoded model catalogs in the repo; suggestions
               come from the hint dictionaries applied to names you supply.

Performance: Standard. Ranking is O(M * R) where M is the model count you
             provide and R is the role count, both small.
-->

# Model selection - Pi / oh-my-pi reference

The role-model routing layer in `content/references/role-models.md` lets the user pin a specific model per role. The **selection layer** described here explains how to decide _which model names to use_ so you are not guessing strings from memory.

This is consulted ONLY on the Pi (`.pi`) and oh-my-pi (`.omp`) harnesses. On Claude/Codex/Gemini the user picks models from the harness's built-in catalog; there is nothing to discover here.

## How model selection works

There are three paths - use whichever matches your setup:

**1. Ask-user (the configure wizard).** Run `bin/agentic-configure` interactively. The wizard prompts you role by role and ranks a list you provide against the hint dictionaries. You supply the model names your harness exposes; the wizard scores them and writes a starter `role-models.yml` you can then edit directly.

**2. Harness-native.** Your Pi or oh-my-pi login already grants access to a set of models. Open the harness's own model picker or settings panel, find the models your subscription includes, and copy those names into the wizard prompt or directly into `role-models.yml`. There is no separate network call needed - the harness already knows what you have.

**3. Pin by hand.** Skip the wizard. Open `~/.agentic/role-models.yml` and write model names directly. The format is simple: see the schema in `content/references/role-models.md`. Use the harness's exact model handle (the string you would pass to a spawn call). The conductor forwards it verbatim.

There are NO hardcoded model catalogs in this repo. Suggestions from the wizard come from the hint dictionaries in `bin/agentic-models` applied to the names you supply - not from any built-in list.

## The binary: `bin/agentic-models`

```
agentic-models [--json] [--suggest <role>] [--all-suggestions] \
               [model-name ...] [--models-from FILE]
```

Default mode prints a human-readable summary. `--json` emits the structured payload consumed by the TUI. `--suggest <role>` prints only one role's primary recommendation (used by hooks that want a quick default without parsing JSON).

Model names are supplied as positional arguments, via `--models-from FILE` (one name per line), or piped from stdin. Empty input returns empty suggestions with exit 0.

**Heuristics.** Per role, the binary scores every model you supply with a small hint dictionary. Substring match is case-insensitive; higher score wins. The hint tables are tuned so Opus-class models surface for the architect / security-auditor tier, Sonnet-class for engineer / debugger, Haiku-class for investigator / qa-engineer, and cross-family candidates (Kimi, GLM, GPT-5.x) for the reviewer pool so the antagonist is plausibly as good as the author without being the same model.

**No hardcoded model IDs.** The hint tables in `bin/agentic-models` use family names (`opus`, `sonnet`, `gpt-5`, `kimi-k2.7`, `glm-5.2`) as substring needles, not exact model strings. Adding a new model to the harness does not require any code change; the substring matcher picks it up from whatever list you feed in.

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

The conductor forwards `model`, `effort`, and `reasoning` to the spawn call as separate parameters (or whatever the harness API takes). The setup wizard surfaces only the keys the live harness accepts -- it does not ask for `reasoning` on a model the harness does not support.

**Backward compatibility.** Files written against the scalar-only schema (PR #249) continue to work: every scalar `engineer: sonnet` becomes `{model: sonnet}` at load time. No migration is required.

## Failure modes

- **No model names provided to wizard.** The wizard still runs and writes a `role-models.yml` with scalar defaults drawn from the hint tables' top family names (`opus`, `sonnet`, `haiku`). Edit the file with the exact handles your harness exposes.
- **Model name not recognised by harness.** The conductor forwards whatever string is in `role-models.yml` verbatim. If the harness rejects it, the spawn fails with the harness's own error. Fix the string in `role-models.yml` and retry.
- **Harness does not support `effort` or `reasoning`.** The conductor forwards only the keys the user's spawn target supports. There is no error; the harness silently ignores unknown parameters.
- **No role-models.yml present.** The conductor omits `model`/`effort`/`reasoning` for every spawn and Pi uses its session defaults. This is the documented no-op path, not an error.
