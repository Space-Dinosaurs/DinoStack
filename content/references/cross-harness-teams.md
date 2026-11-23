<!--
Purpose: Documents the cross-harness agent-team layer that lets the conductor
         dispatch leaf workers to entirely different CLIs (codex, gemini,
         cursor-agent, kimi, pi, omp, opencode, copilot, claude-as-worker)
         rather than spawning them as native subagents within the conductor's
         own harness.

Public API: Read-only reference. Load when configuring team.yml, deciding
            whether to use cross-harness dispatch vs native delegation,
            authoring or reviewing the self-containment guard, or understanding
            how collected worker output re-enters the Skeptic/QA gates.

Upstream deps: content/sections/02-delegation.md (delegation decision table);
               content/sections/04-risk-classification.md (Tier/role layer);
               bin/ds-team (discover|dispatch|status|collect);
               bin/_role_spec.py (shared role-spec normalizer).

Downstream consumers: content/sections/02-delegation.md (pointer);
                      content/sections/04-risk-classification.md (pointer);
                      bin/ds-team (schema section);
                      bin/ds-configure (team subcommand).

Failure modes: Prose reference; not auto-executed. The most common error path
               is a stale team.yml referencing a harness binary that was
               uninstalled - ds-team discover catches this and marks the
               harness absent. A PATH guardrail shim that erroneously blocks the
               worker's own binary is caught by the dispatch test suite; workers
               that hang (cursor-agent known bug) are bounded by the per-run
               timeout + kill watchdog.

Performance: Standard. Dispatch is background shell-out per worker; no blocking
             network call on the conductor's critical path. Web enrichment in
             ds-configure is opt-in and cached.
-->

# Cross-harness agent teams

This layer lets the conductor dispatch leaf workers to entirely different CLI
harnesses -- codex, gemini, cursor-agent, kimi, pi, omp, opencode, copilot, or
claude-as-worker --
rather than spawning native subagents within its own harness. It is **OMC-
independent**: it does not trigger oh-my-claudecode, nor does it use the
conductor harness's own built-in subagent mechanism.

## When to use cross-harness dispatch vs native delegation

**Use the standard delegation table first** (see `content/sections/02-
delegation.md`). Cross-harness dispatch is a *specialization* of the Worker
spawn path, not a replacement for it. Apply it when all of the following hold:

1. The task warrants a Worker spawn by the standard risk table (Elevated or
   Trivial-delegate).
2. `team.yml` is present and `enabled: true` for this project or globally.
3. The role being dispatched has a `roles[<role>]` entry in `team.yml` with a
   `harness` value other than the conductor's own harness.
4. `ds-team discover` confirms that harness is installed and reachable.

When `team.yml` is absent or `enabled: false`, or when the harness is not
installed, the conductor falls back to native delegation unchanged -- no error,
no prompt, no degraded mode. Cross-harness is additive and fully opt-in.

**The conductor does NOT use cross-harness dispatch for:**

- The `conductor` role itself (conductor re-rooting is not supported in v1;
  the `conductor` entry in `team.yml` is advisory only).
- Orchestration-planner, investigator, or architect roles -- these run in the
  conductor's own context because they produce plans the conductor reasons over
  directly.
- Low-risk work (diagnostic-only included) -- it uses native delegation.
- Spawns where `ds-team discover` marks the target harness absent.
  (Authentication errors are not a discover state -- they surface at dispatch
  time from the harness's own stderr/exit code.)

## Config: `team.yml`

Cross-harness team topology is stored in a **dedicated committed file** -- NOT
a block inside `role-models.yml`. `role-models.yml` is Pi/omp-only and
gitignored (it may name user-private model handles); team topology is shareable
project intent and belongs in version control.

**File locations (project wins on key collision, merged shallowly per top-level
key):**

- Global: `~/.agentic/team.yml`
- Project: `.agentic/team.yml` (committed; `.gitignore` carries `!.agentic/team.yml`)

### Schema

```yaml
# ~/.agentic/team.yml  or  .agentic/team.yml
enabled: true
default_harness: codex          # where a role goes if no per-role harness is set;
                                # validated same as roles[*].harness -- unknown value
                                # produces a non-zero exit from ds-team
roles:
  engineer:        { harness: codex,         model: gpt-5.3-codex }
  qa-engineer:     { harness: gemini,        model: gemini-2.5-flash }
  skeptic:         { harness: cursor-agent,  model: cursor-fast }
  security-auditor:{ harness: codex,         model: gpt-5.3-codex }
dispatch:
  timeout_seconds: 1800
  output_format: json
```

**Field notes:**

| Field | Type | Required | Default (absent key) | Notes |
|---|---|---|---|---|
| `enabled` | bool | yes | `false` (absent file = feature off) | Set `false` to disable cross-harness dispatch without removing the file. Absent file is equivalent to `enabled: false`. |
| `default_harness` | string | no | none (unrouted roles fall through to native spawn) | Fallback harness for roles not listed under `roles:`. Validated against the known-harness table; unknown value -> non-zero exit. |
| `roles` | map | no | none (empty - all roles use native spawn unless `default_harness` is set) | Keys are role names (the 9 known roles in `bin/_role_spec.py:KNOWN_ROLES`). Values are a scalar harness name or `{harness, model}` mapping. |
| `roles[*].harness` | string | yes (if mapping) | n/a | Must be one of the 9 known harness labels. Unknown value -> non-zero exit. |
| `roles[*].model` | string | no | none (harness uses its own session default) | Forwarded to the harness's own `--model`/`-m` flag at dispatch (all 9 harnesses accept a model flag; codex/gemini/kimi use `-m`, all others use `--model`). Omit to let the harness use its session default (no hardcoded IDs). For kimi, an empty model means Kimi Code's `default_model` in its own `config.toml`: that one line is the place to bump when Kimi ships a new flagship. There is no automatic latest-model lookup, because Kimi silently falls back to an older model on a mistyped id. |
| `roles[*].backend` | string | no | none (worker inherits the parent environment only) | Name of a preset under `backends:`. Applies only when the role's harness (else `default_harness`) matches the dispatch harness, and only to the five dispatchable roles. See "Backend presets" below. |
| `backends` | map | no | none (no presets) | `<name>: {env: {<VAR>: "<string>"}}`. Read from the global `~/.agentic/team.yml` only; a `backends:` key in a project `team.yml` is an error (exit 2). |
| `dispatch.timeout_seconds` | int | no | `1800` (30 min) | Not read by `ds-team dispatch` today. The only watchdog is cursor-agent's fixed 300 s timeout; every other worker runs until it exits. |
| `dispatch.output_format` | string | no | `"json"` | `json` or `text`. Governs the `collect` demux path. |

The scalar-or-mapping normalize logic for role-spec entries is shared with
`bin/ds-configure` via `bin/_role_spec.py`. Both tools import the same
normalizer; there is no inline copy.

### Backend presets

A backend preset routes one role's worker through a different model backend
without touching the operator's shell or keys. Its `env` map is merged into
that worker's copy of the environment only; the parent environment and every
other dispatch are unchanged. A preset worker does not inherit
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN`
unless the preset sets that variable itself, so real credentials never go to
the preset's base URL.

```yaml
# ~/.agentic/team.yml (global only)
enabled: true
backends:
  gateway:
    env:
      ANTHROPIC_BASE_URL: http://localhost:4000
      ANTHROPIC_AUTH_TOKEN: dinostack-placeholder   # non-secret placeholder
      CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY: "true"
roles:
  skeptic: { harness: claude, backend: gateway, model: "claude-deepseek-pro[1m]" }
```

A preset holds only non-secret values: a base URL, a placeholder token,
flags. Real keys stay in the gateway's own environment. `ds-team` and
`ds-doctor --cross-harness` reject a preset value that looks like a key and
never echo it. The check is a floor, not a scanner: it fails closed on any run
of 32 or more letters and digits containing both (a hex digest, for
example), so such values do not belong in a preset, and a short key without
a known prefix passes. URL userinfo with a password and UUID-shaped values
are rejected too. A preset may only set keys starting with `ANTHROPIC_`,
`CLAUDE_CODE_`, `OPENAI_` or `KIMI_` (so not `PATH`, `HOME`, `NODE_OPTIONS`
or `CLAUDE_CONFIG_DIR`), any `*_BASE_URL` value must be `https://` or
`http://` on `localhost`, `127.0.0.1` or `::1`, every value must be a quoted
string, and `backend` is accepted only on `engineer`, `debugger`,
`qa-engineer`, `skeptic`, and `security-auditor`.

**DeepSeek has no harness of its own.** Route it as `harness: claude` plus a
gateway preset and a `claude-deepseek-*` model id; `claude-kimi-*` ids reach
Kimi the same way. DeepSeek has no prompt caching, and `deepseek-v4-pro` is
text-only.

**Read-only roles through a preset.** When a `claude` worker for `skeptic`
or `security-auditor` (the read-only roles that accept `backend`) runs
through a preset, dispatch adds `--tools Read,Grep,Glob --strict-mcp-config
--setting-sources user`, so the model can call only those three tools and no
MCP server, and the workdir's project settings are not loaded. A `claude`
dispatch without a preset keeps its existing argv and its full tool set.
Read-only limits the model's tool set; it is not a sandbox. Hooks and other
settings the worker still loads (the operator's user settings for `claude`;
Kimi Code may run project hooks) still execute.

Role names are the 9 known roles in `bin/_role_spec.py:KNOWN_ROLES`:
`conductor`, `investigator`, `architect`, `orchestration-planner`, `engineer`,
`debugger`, `qa-engineer`, `skeptic`, `security-auditor`. Unrecognized role
keys are passed through and the dispatch tool validates the harness field
regardless.

## Per-harness dispatch table

`bin/ds-team dispatch` builds the worker invocation from this table. All 9
harnesses now have **confirmed** (not probed) non-interactive flags, verified
live against each CLI -- not hardcoded model IDs, just binary names and flag
spellings, consistent with the "no hardcoded model IDs" stance anchored in
`bin/_role_spec.py` (single source of harness/role labels) and the binary-name
map in `bin/ds-team` (the one allowed per-harness hardcoded fact).

| Harness | Non-interactive incantation | Model flag | Output flag | Notes / gotchas |
|---|---|---|---|---|
| **codex** | `codex exec "<brief>"` or `codex exec -` (stdin) | `-m <model>` | `--json` (JSONL events) | `--sandbox read-only` applied by default; `--skip-git-repo-check` added when workdir is not a git repo; reads saved auth or `CODEX_API_KEY`; final message extracted from the last JSONL event. |
| **gemini** | `gemini -p "<brief>"` | `-m <model>` | `--output-format json` | Headless on non-TTY or `-p`; slash/custom commands are broken headless -- pass the full brief inline; `head -c 50000` guard applied to large stdin; methodology is delivered as a file in the run directory at dispatch time (`.gemini/skills/dinostack/SKILL.full.md`, full corpus) because Gemini CLI denies `activate_skill` non-interactively (`write.toml`, priority 10, `interactive = false` in the installed policy bundle) - dispatch refuses (exit 2) if unresolvable, unreadable, or empty, or set `AGENTIC_TEAM_ALLOW_NO_METHODOLOGY=1` to override. Response text extracted via `jq '.response'`. |
| **cursor-agent** | `cursor-agent -p --force "<brief>" < /dev/null` | `--model <model>` | `--output-format json` | `--force` required for file writes; **known hang bug** -- stdin is always redirected from `/dev/null` AND a timeout + kill watchdog is applied; marked `experimental` in discovery output until upstream fixes the hang. `--list-models` also confirmed (used by discovery model probe). |
| **kimi** | `kimi -p "<brief>" --output-format stream-json [--agent-file <private-tmp-dir>/kimi-readonly-agent.md]` | `-m <alias>` | `--output-format stream-json` (JSON Lines) | Kimi Code 2.x; dispatch refuses (exit 2) when `kimi --version` is below 2 or absent, and never falls back to the legacy `kimi-cli`. `-p` cannot be combined with `--yolo`/`--auto`/`--plan`, and print mode approves every tool call, so read-only roles (`skeptic`, `investigator`, `security-auditor`, `architect`) get a generated agent file allowing only `Read`, `Grep`, and `Glob` with `subagents: []`; write-capable roles get no agent file. No custom slash commands; methodology is delivered as a file in the run directory at dispatch time (`.kimi/skills/dinostack/SKILL.md`, already full corpus) for the same reason as Gemini - dispatch refuses (exit 2) if unresolvable, unreadable, or empty, same override. |
| **pi** | `pi -p "<brief>"` | `--model <model>` | text (default mode) | Built-in subagent types exist but MUST be suppressed via the leaf-worker clause. Also supports `--mode text\|json\|rpc`; default text mode is used so `collect()`'s raw-stdout path works. |
| **omp** | `omp -p "<brief>"` | `--model <model>` | text (default mode) | Same leaf-worker suppression; omp built-in subagents not used as nested spawns. `--mode json` emits streaming JSONL `message_update` events (not a single JSON object), not worth parsing in v1, so default text mode is kept. `omp models ls --json` confirmed (used by discovery model probe). |
| **opencode** | `opencode run "<brief>" --dangerously-skip-permissions` | `--model <model>` | raw stdout | `--dangerously-skip-permissions` required for non-interactive dispatch (detached worker has no TTY for permission prompts); `--model` forwarded only when a model is configured; final message is raw stdout (no demux). |
| **copilot** | `copilot -p "<brief>" --allow-all-tools --allow-all-paths` | `--model <model>` | raw stdout | `--allow-all-tools --allow-all-paths` required for non-interactive file writes (see RISK-ACCEPTED note below); `--model` forwarded only when configured; final message is raw stdout (no demux). |
| **claude (worker)** | `claude -p "<brief>"` | `--model <model>` | `--output-format json` | Only as a *dispatched leaf worker*, never re-entering OMC. Harness label is `claude`; binary is `claude`. |

Discovery (`ds-team discover`) best-effort populates a `models: [...]`
list per harness: omp via `omp models ls --json` (stdout parsed, stderr
extension-load warnings tolerated) and cursor-agent via `cursor-agent
--list-models` (line-per-model text). claude/codex/gemini/kimi/pi/opencode/copilot
have no reliable list command confirmed and always report `models: []`. Every probe
has a 10s timeout and fails silently to `[]` on any exception -- a broken
probe never breaks `discover` as a whole.

**Methodology-delivery scope, alternatives rejected, and known limitations.**
File-in-run-dir delivery is used for gemini and kimi only, because both were
live-confirmed to have no headless skill-trigger route (see the table Notes
above). pi and omp ship stub `SKILL.md` files and their headless skill-loading
is unaudited; codex, cursor-agent, opencode, copilot, and claude-as-worker use
other mechanisms and were not investigated as part of this fix. Two
alternatives were rejected: `tools.allowed: ["activate_skill"]` restores the
tool to Gemini's headless schema live, but call-time reliability was
unconfirmed across two attempts (one quota-contaminated), so it is named here
for a future investigator rather than adopted; argv-inlining the skill content
was rejected outright because it overflows Linux's `MAX_ARG_STRLEN`
(131,072 B) on `ubuntu-latest` CI runners. Known limitation:
`.gemini/skills/dinostack/` has no `references/`/`agents/` siblings, unlike
`.kimi/skills/dinostack/` -- `SKILL.full.md`'s internal pointers to
`content/references/*.md` resolve only when `worker_cwd` happens to be a
DinoStack checkout itself; in a genuine consumer-repo throwaway workdir those
pointers dangle. Separately, the `head -c 50000` guard on large stdin named
in the gemini table row above has no implementation anywhere in this
codebase (grep-confirmed) -- pre-existing, out of scope here, left untouched.

**Kimi Code 2.x only.** The kimi harness drives Kimi Code 2.x (`kimi`). When
`kimi --version` reports a major version below 2, or no `kimi` is installed,
dispatch refuses with exit 2 before creating a run directory, names a
detected legacy `kimi-cli` in the message, and asks for Kimi Code 2.x. There
is no fallback to the legacy CLI's argv. The read-only agent file is written
to a private `0700` temporary directory outside the workdir, so a concurrent
worker in the same workdir cannot rewrite it, and is removed when the worker
exits. It closes subagent delegation with `subagents: []` (an absent key
would inherit the default profile's delegation targets).
Whether its body replaces Kimi's own system prompt is unverified.

**RISK-ACCEPTED: copilot's `--allow-all-paths` grant.** Unlike every other
harness above, copilot is dispatched with `--allow-all-paths` in addition to
`--allow-all-tools`. Per `copilot --help`, both flags are required to get
non-interactive operation at all -- copilot exposes no path-scoped equivalent
(no `--sandbox` flag, no directory allowlist) -- so this is a deliberate
trade-off of autonomy over sandboxed path-scoping, not an oversight. The
PATH guardrail (section 3 below) does **not** mitigate this: it only
intercepts bare-name re-entry to sibling CLIs, it is not a filesystem
sandbox. `_cmd_dispatch` sets the copilot subprocess's `cwd` to the
caller-supplied `--workdir` (a throwaway worktree/copy), but setting `cwd`
only changes how *relative* paths resolve -- it does **not** block
absolute-path reads or writes (`~/.ssh/id_rsa`, `/etc/...`, any path the
brief spells out in full), and the subprocess still inherits the full parent
environment, so ambient credentials in env vars remain reachable. Given the
threat model is a prompt-influenced `brief_text`, `--allow-all-paths` is a
genuine, deliberately-accepted risk whenever the brief is not fully trusted
-- it is **not a sandbox**. The disposable workdir limits the *relative*-path
blast radius and keeps repo mutations isolated to a throwaway tree; it is
not a filesystem confinement boundary. Operators must still pass a
genuinely disposable `--workdir` for copilot dispatches and treat the brief
as untrusted input, since the flag itself enforces nothing.

**Operator opt-in gate.** Because this is the only harness that trades away
worktree isolation, `_cmd_dispatch` refuses to launch a copilot worker unless
the operator sets `AGENTIC_TEAM_ALLOW_COPILOT=1`. Merely listing `copilot` in
`team.yml` is not enough -- dispatch fails fast (exit 2, before any run
directory is created) with a message naming the env var. This makes the
`--allow-all-paths` trade-off an explicit, auditable consent rather than an
implicit side effect of configuration.

**Binary-name map (discovery uses this, not the harness label):**

| Harness label | Binary name |
|---|---|
| codex | `codex` |
| gemini | `gemini` |
| cursor-agent | `cursor-agent` |
| kimi | `kimi` (Kimi Code 2.x) |
| pi | `pi` |
| omp | `omp` |
| opencode | `opencode` |
| copilot | `copilot` |
| claude | `claude` |

The binary-name map is the only per-harness hardcoded fact in the repo. It maps
*names*, not model IDs or flag strings.

## Self-containment guard

When a DinoStack team is triggered, the worker must NOT trigger external
orchestration (oh-my-claudecode) NOR the conductor harness's own native
subagents. The guard is layered; the layers are listed from strongest to
weakest:

### 1. Workdir fence (PRIMARY containment)

Each worker runs in its own **throwaway `--workdir`** -- either a git worktree
or a directory copy of the relevant files. The worker has no access to the real
repository tree regardless of what it runs. The conductor is the sole git
owner; workers never run git on the live repo. This is the real containment
boundary.

### 2. Harness-native sandbox (strongest per-worker fence, where available)

Where the harness exposes a sandbox flag, it is applied at dispatch time. For
codex this is `--sandbox read-only`. The `ds-team discover` output records
`native_subagent_disable_flag` per harness; dispatch sets it when non-null.
This is stronger than the PATH guardrail because it is enforced by the harness
process itself, not by a wrapper script.

### 3. PATH guardrail (accidental re-entry -- NOT a security sandbox)

Each worker launch prepends a wrapper directory to `PATH`. Shims in that
directory for `git`, `omc`, and all sibling CLI names (`codex`, `gemini`,
`cursor-agent`, `kimi`, `kimi-cli`, `pi`, `omp`, `opencode`, `copilot`, `claude`) exit 1 and append a line to
`<workdir>/.agentic/teamrun/<run-id>/violations.log`. The worker's own binary
is exempt (a codex worker can still run `codex`; its shim is not placed).

**This guardrail catches accidental bare-name re-entry by a cooperative worker.
It does NOT stop an absolute-path call (`/usr/bin/git`, a pre-resolved path, or
a worker that deliberately bypasses `PATH`).** It is a guardrail, not a
guarantee. Do not claim it provides enforcement beyond its design surface.

### 4. Leaf-worker clause (defense-in-depth)

Every worker brief includes the clause:

> "You are a leaf worker: no sub-agents, no git, no oh-my-claudecode. Write
> your output to the workdir and exit. Do not spawn any additional processes
> beyond your own execution."

This relies on worker cooperation. It is defense-in-depth, not a hard fence.

### 5. Conductor-side suppression

Two independent layers keep the conductor from spawning native subagents when
a role should be cross-harness dispatched instead: a **proactive routing
check** (runs before any dispatch has ever happened) and the sentinel
suppression described below (active only after a run is in flight).

**Proactive team-routing enforcement (fixes the chicken-and-egg bug):** the
sentinel-only suppression below has a gap - the sentinel is created by the
*first* `ds-team dispatch`, so if the conductor never dispatches (e.g. it
keeps using native `Task`/`Agent` because nothing is stopping it), a `team.yml`
with `enabled: true` was previously silently ignored. `hooks/enforce-background-
spawn.py` closes this gap with a branch that runs BEFORE the sentinel check: it
loads the effective `team.yml` (global + project, project wins, same merge
semantics as `bin/ds-team`; PyYAML imported opportunistically, fails open
if unavailable) and, when `enabled: true` and the spawned `subagent_type` is one
of the five dispatchable roles (`engineer`, `debugger`, `qa-engineer`,
`skeptic`, `security-auditor`) whose resolved harness (role entry, else
`default_harness`) is anything other than `claude`, denies the native spawn
with an actionable instruction, e.g.:

> `cross-harness team active: role 'engineer' is assigned to harness 'omp'.
> Dispatch with: bin/ds-team dispatch --harness omp --role engineer
> --brief <file> --workdir <dir> --model <model-from-team.yml> - then poll
> status/collect.`

The model value is deliberately never interpolated into this message - it is
untrusted, project-controlled text from `team.yml`, so the hook substitutes
the literal placeholder `<model-from-team.yml>` instead.

A dispatchable role whose resolved harness is `claude` but whose role entry
carries a `backend:` preset is denied too, because a native spawn would skip
the preset's environment. The message names `bin/ds-team dispatch --harness
claude --role <role>` and never echoes the backend name or the model.

`conductor`, `investigator`, `architect`, and `orchestration-planner` are never
denied by this branch even if `team.yml` maps them elsewhere (their entries are
advisory only, per the "does NOT use cross-harness dispatch for" list above).
Fail-open on every error path (missing file, unreadable, malformed YAML, import
failure) - a broken or absent `team.yml` never blocks native spawning. Escape
hatch: `AE_TEAM_ROUTING_DISABLE=1` skips this branch entirely, before any file
I/O.

**Sentinel suppression:** while the sentinel file
`<workdir>/.agentic/teamrun/.active` exists, the conductor suppresses native
`Task` spawns and OMC skill calls.

**On Claude Code:** hook-enforced. The `hooks/enforce-background-spawn.py` hook
(wired by `.claude/install.sh`, PreToolUse matcher for both `Task` and `Agent`)
contains a sentinel-suppression branch: when `.active` exists and is live
(conductor PID present + not dead, mtime < 2 h), the hook denies any `Task` or
`Agent` call outright and denies any Skill call whose `skill` argument starts
with `oh-my-claudecode:`. The denial message instructs the conductor to dispatch
via `ds-team` instead.

Stale-sentinel guard: the hook treats `.active` as expired when its recorded
PID is dead OR its mtime is more than 2 hours old, so a crashed conductor does
not permanently suppress native Task. The sentinel self-expires when its conductor PID is dead or its mtime exceeds 2 h; there is no manual clear command.

Sentinel lifecycle: created by `ds-team dispatch` on first run (carries
conductor PID); removed by `ds-team collect` when the last run in the
batch completes.

**On all other harnesses:** Agents running on non-Claude harnesses MUST treat
`<workdir>/.agentic/teamrun/.active` as a hard suppression signal and MUST NOT
spawn the conductor harness's native subagents while it is live. This is a
binding prose contract, not a mechanically enforced hook. Per-harness status:

| Harness | Enforcement status | Hook location (if it existed) |
|---|---|---|
| **Claude Code** | Hook-enforced (`hooks/enforce-background-spawn.py`, wired by `.claude/install.sh`; PreToolUse deny on `Task` and `Agent` + OMC skill calls while `.active` is live) | Already deployed |
| **Codex** | Prose-contract only - no `PreToolUse`-deny hook infrastructure available | Would live in `.codex/hooks/` or a `CODEX_HOOK_PATH` entry |
| **Gemini** | Prose-contract only - no hook interception layer available | Would require a Gemini hook shim if the CLI gains hook support |
| **Kimi** | Prose-contract only - no hook infrastructure | Would live alongside `.kimi/` config |
| **Cursor** | Prose-contract only - Cursor extension hooks exist but do not cover CLI headless mode | Would require a cursor-agent wrapper or sidecar |
| **OpenCode** | Prose-contract only - no hook infrastructure | Would live in `.opencode/` hooks if the runtime adds them |
| **OpenClaw** | Prose-contract only - no hook infrastructure | Would live in `.openclaw/` hooks if the runtime adds them |
| **Pi** | Prose-contract only - no hook infrastructure | Would live in `.pi/` config hooks if the runtime adds them |
| **omp** | Prose-contract only - no hook infrastructure | Would live in `.omp/` config hooks if the runtime adds them |
| **Copilot** | Prose-contract only - no hook infrastructure | Would live in `.copilot/` config hooks if the runtime adds them |
| **Hermes** | Prose-contract only - no hook infrastructure | Would live in a Hermes hook slot if the runtime adds them |

The leaf-worker clause (layer 4) and workdir fence (layer 1) provide
defense-in-depth for harnesses without hook enforcement. Agents on prose-only
harnesses must apply the suppression as a discipline; callers cannot rely on
mechanical enforcement as a guarantee.

## How collected worker output re-enters the Skeptic/QA gates

Cross-harness workers are leaf processes. They write their output to
`<workdir>/.agentic/teamrun/<run-id>/stdout` (and `stderr`, `exit`).
`ds-team collect <run-id>` demuxes the per-harness output shape and
returns the final message text:

| Harness | Output shape | collect extraction |
|---|---|---|
| codex | JSONL events | last event matching `type: message` |
| gemini | JSON `{response: ...}` | `jq '.response'` |
| cursor-agent | JSON | `jq '.result'` |
| kimi | JSON Lines (`--output-format stream-json`) | last `role: assistant` line with non-blank text content; raw stdout when none parses |
| pi / omp | raw text (default text mode) | raw stdout |
| opencode | raw stdout | raw stdout, no demux |
| copilot | raw stdout | raw stdout, no demux |
| claude (worker) | JSON `{result: ...}` | `jq '.result'` |

Once `collect` returns the final message, **that text is treated identically to
a Worker return summary from a native subagent.** The conductor passes it to the
standard Skeptic and QA gates unchanged:

- The Skeptic receives the collected output as the diff/plan under review; the
  adversarial brief and findings classification are unchanged.
- The QA gate fires on the same `qa_criteria` trigger logic as any other Worker
  unit (see `content/sections/05-qa-gate.md`).
- Re-route limits (max 3 fix passes in a Skeptic loop, 3 in a QA loop),
  convergence-failure escalation, and per-ticket QA flow all apply identically.

No new gate, no bypass, no special case for cross-harness origin. The harness
boundary is transparent to the Skeptic/QA layer.

## Conductor Dispatch Contract

**Cross-harness teams (opt-in) - harness-neutral conductor contract.** When `team.yml` is present and `enabled: true`, the conductor - regardless of which CLI harness it is running on (Claude Code, Codex, Gemini, Cursor, Kimi, Pi, omp, OpenClaw, OpenCode, Copilot, Hermes) - follows the same four-step dispatch contract for any dispatchable role (`engineer`, `debugger`, `qa-engineer`, `skeptic`, `security-auditor`) whose `team.yml` entry resolves to a harness other than its own, or carries a `backend:` preset:

1. **Discover** - run `bin/ds-team discover` to confirm the target harness binary is installed and its native sandbox flag (if any). Missing binary -> fall back to native delegation unchanged, no error, no prompt.
2. **Dispatch** - run `bin/ds-team dispatch --role <role> --brief <path>` to spawn the worker in its own throwaway workdir (worktree or directory copy). The conductor never runs git inside the worker's workdir; the conductor remains sole git owner of the live repo.
3. **Status poll** - run `bin/ds-team status <run-id>` until the run reaches a terminal state (`done`/`failed`/`timeout`). Poll with your own bound; `dispatch.timeout_seconds` is not enforced by dispatch (only cursor-agent has a watchdog).
4. **Collect** - run `bin/ds-team collect <run-id>` to demux the harness-specific output shape and extract the final message text.

Once `collect` returns, its output re-enters the Skeptic/QA gates exactly as described above under "How collected worker output re-enters the Skeptic/QA gates" - same adversarial review, same `qa_criteria` triggers, same re-route limits, no new gate or bypass for cross-harness origin.

**Routing enforcement differs by harness.** Only Claude Code has a mechanical `PreToolUse` deny hook (`hooks/enforce-background-spawn.py`, wired by `.claude/install.sh`) that enforces background-by-default on legacy `Task` spawns and suppresses native `Task`/`Agent` spawns and `oh-my-claudecode:*` Skill calls while a cross-harness run's sentinel (`.agentic/teamrun/.active`) is live. That same hook also proactively blocks a native spawn for a dispatchable role whose resolved `team.yml` harness is not `claude`, or is `claude` with a `backend:` preset - the "Proactive team-routing enforcement" branch described above, which runs before any dispatch has ever happened and closes the chicken-and-egg gap in the sentinel-only check (escape hatch: `AE_TEAM_ROUTING_DISABLE=1`). On every other harness (Codex, Gemini, Cursor, Kimi, Pi, omp, OpenClaw, OpenCode, Copilot, Hermes) this is a **binding prose contract, not a mechanically enforced hook** - the conductor on those harnesses must self-apply the discover -> dispatch -> status -> collect sequence and must not silently fall back to a native spawn just because no hook stops it.
