<!--
Purpose: Operator-facing guide for the role-model routing layer introduced in
         PR #249. Explains what it does, when to use it, how to set it up on
         Pi / oh-my-pi, the configuration shape, common patterns, and the
         concrete failure modes the operator should expect.

Public API: Operator-facing prose. Read first if you are new to role-model
            routing on Pi; deeper schema and resolution algorithm live in
            `content/references/role-models.md` and
            `content/references/model-discovery.md`.

Upstream deps: content/references/role-models.md (schema, resolution);
               content/references/model-discovery.md (selection paths, heuristics);
               bin/agentic-configure, bin/agentic-models (binaries).

Downstream consumers: docs site root index; PR #249 description;
                      doc-sync-obligation.md cross-references.

Failure modes: Stale if PR #249 has not landed or the schema changes.
               When the schema changes, update both this doc and the
               reference under content/references/ in the same change.

Performance: Standard.
-->

# Role-model routing on Pi / oh-my-pi

Per-role and per-reviewer model assignment for Pi and oh-my-pi harnesses.
Lets the operator pin a different model for each agentic-engineering role
and force the adversarial reviewer to run on a model that is NOT the one
that wrote the code under review. Available only when the harness is Pi or
oh-my-pi; Claude / Codex / Cursor / Gemini ignore this layer entirely.

The deeper specification (schema, resolution algorithm, interaction with
Tier) lives in `content/references/role-models.md`. The selection paths
and ranking heuristics behind the setup wizard live in
`content/references/model-discovery.md`. This document is the operator
entry point.

## When to use it

You want this layer when you care about one or more of:

- **Cost asymmetry.** Sonnet-class for the engineer / debugger, Haiku-class
  for the QA pass, Opus only where the design decision actually matters.
- **Antagonist review.** Your engineer runs on Opus; the Skeptic reviews on
  GPT-5 or GLM so the reviewer is not the same model family that produced
  the diff. Catches a class of self-confirming bugs the same-family
  reviewer misses.
- **Provider diversification.** Pin certain roles to Kimi or GLM to spread
  load or hedge against a single provider outage.
- **Tuning per role.** Different `effort` or `reasoning` per role, e.g.
  high-effort architect, low-effort qa-engineer, no-reasoning debugger.

You do NOT need this layer when you run on Claude / Codex / Cursor /
Gemini. The Tier mechanism already does everything you would want on those
harnesses.

## Set up in three steps

1. **Install the agentic-engineering methods.** If you have not already,
   follow `docs/safe-configuration.md` and run
   `bash bootstrap.sh` (or your harness-native install path). This puts
   `bin/agentic-configure` and `bin/agentic-models` on your PATH.
2. **Gather your model names.** Open your Pi or oh-my-pi model picker (or
   the harness's settings panel) and note the model handles your
   subscription includes -- for example `cc/claude-opus-4-5` or
   `gpt-5`. You will supply these to the wizard in the next step. If
   you only know family names (`opus`, `sonnet`, `haiku`), those work
   too; the wizard accepts any substring the harness recognises.
3. **Seed `~/.agentic/role-models.yml`.** Run `bin/agentic-configure`. The
   wizard asks you per role, ranks the names you provide using the hint
   dictionaries in `bin/agentic-models`, and writes a starter file. You
   then edit it to taste. The file path is `~/.agentic/role-models.yml`
   (NOT `.agentic/config.json`; that is a different committed file).

The file is gitignored under the `.agentic/` umbrella because it may name
private model handles. If you want a project-local override, write
`.agentic/role-models.yml` in the project root; project keys win on
collision with the global file.

## Configuration shape

The minimum useful file:

```yaml
roles:
  architect: opus
  engineer: sonnet
  qa-engineer: haiku
```

Adding the antagonist-reviewer pool:

```yaml
roles:
  architect: opus
  engineer: sonnet
  qa-engineer: haiku

reviewers:
  strategy: distinct-from-author
  pool:
    - gpt-5
    - glm-4.6
    - kimi-k2.7
  fallback: gpt-5
```

With this, an engineer that runs on Opus produces a diff that gets reviewed
by GPT-5 first; if GPT-5 is unavailable, the strategy falls back to the
next pool entry whose model differs from Opus. Reviewers NEVER run on the
same model as the author.

For tuning per role, use the mapping form:

```yaml
roles:
  architect:
    model: opus
    effort: high
    reasoning: 8192
  engineer:
    model: sonnet
    effort: medium
  qa-engineer:
    model: haiku
    effort: low
```

The conductor forwards only the keys that are set. `effort` and `reasoning`
are pass-through; the harness interprets them. A harness that does not
support `reasoning` silently drops it.

The full role list and resolution rules live in
`content/references/role-models.md`.

## Verify it works

After writing `~/.agentic/role-models.yml`, run:

```bash
bin/agentic-status
```

The status command prints the resolved model for each role based on the
current file. If a role shows `(session default)` rather than a model, the
conductor will omit the model field for that spawn and Pi uses its own
default. Use this to spot typos or missing keys before you start a real
session.

You can also preview rankings for a list of model names:

```bash
bin/agentic-models opus sonnet haiku gpt-5 glm-4.6 --suggest engineer
bin/agentic-models opus sonnet haiku gpt-5 glm-4.6 --all-suggestions
```

Pass the model names your harness exposes as positional arguments.
The binary ranks them per role using the hint dictionaries. Useful
when you are deciding which model to pin a role to.

## Common patterns

**Cost-optimised default.** Opus only for architect and security-auditor;
Sonnet for engineer / debugger; Haiku for qa-engineer and investigator;
cross-family reviewer pool. See
`content/references/role-models-example.yml` for a copy-pasteable starting
point.

**Antagonist-only.** Skip the per-role pins and only set `reviewers:`.
The conductor leaves forward-role spawns at the harness default, but
forces reviewer spawns to a cross-family pool with `distinct-from-author`.
This is the cheapest way to get the diversity win without committing to a
full pin matrix.

**Per-task reviewer split.** Use `strategy: by-task` with `by_task:` to
pick a different reviewer model per adversarial brief kind. Security
briefs land on GPT-5; architect-plan review lands on Opus; everything else
on GLM. Useful when different review kinds have known-good model fits.

**Effort-only pinning.** Pin `effort: high` on architect and
`effort: low` on qa-engineer while leaving model unset. Pi uses its
session default model but varies effort per role. Cheap way to tune
latency-vs-depth without owning model names.

## Failure modes

- **Model name not recognised by harness.** The conductor forwards the
  string from `role-models.yml` verbatim. If the harness rejects it,
  the spawn fails with the harness's own error. Fix the string in
  `role-models.yml` and retry. Use `bin/agentic-status` to preview
  what the conductor will send before starting a real session.
- **No role-models.yml present.** The conductor omits the `model` field
  on every Pi/omp spawn. Pi uses its session default for everything.
  This is not an error; it is the documented no-op path.
- **Pool exhausted.** If `strategy: distinct-from-author` runs out of pool
  entries whose model differs from the author and no `fallback:` is set,
  the conductor omits `model` for that reviewer spawn and notes the
  session-default fallback inline. Reviewer diversity is best-effort, not
  guaranteed.
- **Harness does not support a field.** `effort` and `reasoning` are
  silently dropped on harnesses that do not implement them. No error.

## When things go wrong

1. Run `bin/agentic-status` to see what the conductor resolves for each
   role right now.
2. Run `bin/agentic-models <your-model-names> --all-suggestions` to
   confirm the ranking heuristics score your model list as expected.
   Supply the exact model handles your harness exposes.
3. If the file looks right and the status prints the right models but
   spawns still use the wrong model, check that Pi's session default is
   not silently overriding. Pi treats `--model` as advisory in some
   paths; the conductor logs the resolution, and you can compare against
   the spawn output.

## Related references

- `content/references/role-models.md` - schema, resolution algorithm,
  interaction with Tier and presets
- `content/references/model-discovery.md` - model selection paths, heuristics,
  effort/reasoning field semantics
- `content/references/role-models-example.yml` - copy-paste starter
- `content/commands/init-project.md` - Step 6g seeds the global file on
  fresh projects
- `bin/agentic-configure` - interactive setup wizard
- `bin/agentic-models` - probe + per-role suggest
- `bin/agentic-status` - shows the resolved model for each role