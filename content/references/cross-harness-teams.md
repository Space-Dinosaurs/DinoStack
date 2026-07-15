<!--
Purpose: Documents the cross-harness agent-team layer that lets the conductor
         dispatch leaf workers to entirely different CLIs (codex, gemini,
         cursor-agent, kimi, pi, omp, claude-as-worker) rather than spawning
         them as native subagents within the conductor's own harness.

Public API: Read-only reference. Load when configuring team.yml, deciding
            whether to use cross-harness dispatch vs native delegation,
            authoring or reviewing the self-containment guard, or understanding
            how collected worker output re-enters the Skeptic/QA gates.

Upstream deps: content/sections/02-delegation.md (delegation decision table);
               content/sections/04-risk-classification.md (Tier/role layer);
               bin/agentic-team (discover|dispatch|status|collect);
               bin/_role_spec.py (shared role-spec normalizer).

Downstream consumers: content/sections/02-delegation.md (pointer);
                      content/sections/04-risk-classification.md (pointer);
                      bin/agentic-team (schema section);
                      bin/agentic-configure (team subcommand).

Failure modes: Prose reference; not auto-executed. The most common error path
               is a stale team.yml referencing a harness binary that was
               uninstalled - agentic-team discover catches this and marks the
               harness absent. A PATH guardrail shim that erroneously blocks the
               worker's own binary is caught by the dispatch test suite; workers
               that hang (cursor-agent known bug) are bounded by the per-run
               timeout + kill watchdog.

Performance: Standard. Dispatch is background shell-out per worker; no blocking
             network call on the conductor's critical path. Web enrichment in
             agentic-configure is opt-in and cached.
-->

# Cross-harness agent teams

This layer lets the conductor dispatch leaf workers to entirely different CLI
harnesses -- codex, gemini, cursor-agent, kimi, pi, omp, or claude-as-worker --
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
4. `agentic-team discover` confirms that harness is installed and reachable.

When `team.yml` is absent or `enabled: false`, or when the harness is not
installed, the conductor falls back to native delegation unchanged -- no error,
no prompt, no degraded mode. Cross-harness is additive and fully opt-in.

**The conductor does NOT use cross-harness dispatch for:**

- The `conductor` role itself (conductor re-rooting is not supported in v1;
  the `conductor` entry in `team.yml` is advisory only).
- Orchestration-planner, investigator, or architect roles -- these run in the
  conductor's own context because they produce plans the conductor reasons over
  directly.
- Any spawn that the conductor would classify as direct-action (Low or
  diagnostic-only) -- those stay conductor-direct.
- Spawns where `agentic-team discover` marks the target harness absent.
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
                                # produces a non-zero exit from agentic-team
roles:
  engineer:        { harness: codex,         model: gpt-5.3-codex }
  qa-engineer:     { harness: gemini,        model: gemini-2.5-flash }
  skeptic:         { harness: cursor-agent,  model: cursor-fast }
  security-auditor:{ harness: codex,         model: gpt-5.3-codex }
dispatch:
  timeout_seconds: 1800
  stall_seconds: 120
  retries: 1
  failover: true
  output_format: json
```

**Field notes:**

| Field | Type | Required | Default (absent key) | Notes |
|---|---|---|---|---|
| `enabled` | bool | yes | `false` (absent file = feature off) | Set `false` to disable cross-harness dispatch without removing the file. Absent file is equivalent to `enabled: false`. |
| `default_harness` | string | no | none (unrouted roles fall through to native spawn) | Fallback harness for roles not listed under `roles:`. Validated against the known-harness table; unknown value -> non-zero exit. |
| `roles` | map | no | none (empty - all roles use native spawn unless `default_harness` is set) | Keys are role names (the 9 known roles in `bin/_role_spec.py:KNOWN_ROLES`). Values are a scalar harness name or `{harness, model}` mapping. |
| `roles[*].harness` | string | yes (if mapping) | n/a | Must be one of the 7 known harness labels. Unknown value -> non-zero exit. |
| `roles[*].model` | string | no | none (harness uses its own session default) | Forwarded to the harness's own `--model`/`-m` flag at dispatch (all 7 harnesses accept a model flag; codex/gemini use `-m`, all others use `--model`). Omit to let the harness use its session default (no hardcoded IDs). |
| `roles[*].models` | list | no | none (mutually exclusive with `model`; when both present `models` wins) | Round-robin author pool: a list of model handles the role rotates through, one per successive dispatch. The rotation cursor is persisted durably at `~/.agentic/rotation/<role>` (NOT the throwaway per-dispatch workdir) under an flock, so rotation advances across genuinely separate dispatches and concurrent dispatches of the same role do not race. Mutually exclusive with `model`; when both are present `models` wins. Use for co-author roles, e.g. `engineer: { harness: omp, models: [kimi/kimi-k2.7, glm/glm-5.2] }`. Each entry must be a non-empty string or dispatch config validation fails. |
| `dispatch.timeout_seconds` | int | no | `1800` (30 min) | Per-worker wall-clock hard cap. Watchdog (`_supervise.py`) kills the process group with `EXIT_TIMEOUT`/124 on expiry. Absent key resolves to `bin/agentic-team:_DEFAULT_DISPATCH_SETTINGS` (`1800`) — deliberately NOT `_supervise.py:DEFAULT_TIMEOUT_SECONDS` (`600`, that constant is `_supervise.py`'s internal fallback for callers that omit the parameter, which `agentic-team` never does). The tool-generated scaffold writes the same `timeout_seconds: 1800` explicitly. |
| `dispatch.stall_seconds` | int | no | per-harness (`120` baseline; `300` for `claude`/`gemini`/`cursor-agent`) | Max inactivity (no stdout/stderr write) before the worker is killed with `EXIT_STALL`/125. Absent key resolves per-harness via `_supervise.py:_STALL_DEFAULTS`; an explicit value overrides uniformly for all harnesses. |
| `dispatch.retries` | int | no | `1` | Same-harness re-spawn attempts after a nonzero/stall/timeout exit, before failover. Chain begins with `1 + retries` literal repeats of the requested `(harness, model)`. |
| `dispatch.failover` | bool | no | `true` | After same-harness retries exhaust, try other models declared for the role in `team.yml`, then a terminal `claude` fallback. Set `false` to stop the chain after retries. |
| `dispatch.output_format` | string | no | `"json"` | `json` or `text`. Governs the `collect` demux path. |

The scalar-or-mapping normalize logic for role-spec entries is shared with
`bin/agentic-configure` via `bin/_role_spec.py`. Both tools import the same
normalizer; there is no inline copy.

Role names are the 9 known roles in `bin/_role_spec.py:KNOWN_ROLES`:
`conductor`, `investigator`, `architect`, `orchestration-planner`, `engineer`,
`debugger`, `qa-engineer`, `skeptic`, `security-auditor`. Unrecognized role
keys are passed through and the dispatch tool validates the harness field
regardless.

## Per-harness dispatch table

`bin/agentic-team dispatch` builds the worker invocation from this table. All 7
harnesses now have **confirmed** (not probed) non-interactive flags, verified
live against each CLI -- not hardcoded model IDs, just binary names and flag
spellings, consistent with the "no hardcoded model IDs" stance anchored in
`bin/_role_spec.py` (single source of harness/role labels) and the binary-name
map in `bin/agentic-team` (the one allowed per-harness hardcoded fact).

| Harness | Non-interactive incantation | Model flag | Output flag | Notes / gotchas |
|---|---|---|---|---|
| **codex** | `codex exec "<brief>"` or `codex exec -` (stdin) | `-m <model>` | `--json` (JSONL events) | `--sandbox read-only` applied by default; `--skip-git-repo-check` added when workdir is not a git repo; reads saved auth or `CODEX_API_KEY`; final message extracted from the last JSONL event. |
| **gemini** | `gemini -p "<brief>"` | `-m <model>` | `--output-format json` | Headless on non-TTY or `-p`; slash/custom commands are broken headless -- pass the full brief inline; `head -c 50000` guard applied to large stdin. Response text extracted via `jq '.response'`. |
| **cursor-agent** | `cursor-agent -p --force "<brief>" < /dev/null` | `--model <model>` | `--output-format json` | `--force` required for file writes; **known hang bug** -- stdin is always redirected from `/dev/null` AND a timeout + kill watchdog is applied; marked `experimental` in discovery output until upstream fixes the hang. `--list-models` also confirmed (used by discovery model probe). |
| **kimi** | `kimi-cli --print --yolo --final-message-only -p "<brief>"` | `--model <model>` | text (final-message-only) | Binary name is `kimi-cli` (not `kimi`); `--print` is mandatory for non-interactive/auto-dismiss-AskUserQuestion behavior -- bare `-p` alone is interactive-with-prompt. No custom slash commands; methodology loaded via inline skill content in the brief. |
| **pi** | `pi -p "<brief>"` | `--model <model>` | text (default mode) | Built-in subagent types exist but MUST be suppressed via the leaf-worker clause. Also supports `--mode text\|json\|rpc`; default text mode is used so `collect()`'s raw-stdout path works. |
| **omp** | `omp -p "<brief>"` | `--model <model>` | text (default mode) | Same leaf-worker suppression; omp built-in subagents not used as nested spawns. `--mode json` emits streaming JSONL `message_update` events (not a single JSON object), not worth parsing in v1, so default text mode is kept. `omp models ls --json` confirmed (used by discovery model probe). |
| **claude (worker)** | `claude -p "<brief>"` | `--model <model>` | `--output-format json` | Only as a *dispatched leaf worker*, never re-entering OMC. Harness label is `claude`; binary is `claude`. |

Discovery (`agentic-team discover`) best-effort populates a `models: [...]`
list per harness: omp via `omp models ls --json` (stdout parsed, stderr
extension-load warnings tolerated) and cursor-agent via `cursor-agent
--list-models` (line-per-model text). claude/codex/gemini/kimi/pi have no
reliable list command confirmed and always report `models: []`. Every probe
has a 10s timeout and fails silently to `[]` on any exception -- a broken
probe never breaks `discover` as a whole.

**Binary-name map (discovery uses this, not the harness label):**

| Harness label | Binary name |
|---|---|
| codex | `codex` |
| gemini | `gemini` |
| cursor-agent | `cursor-agent` |
| kimi | `kimi-cli` |
| pi | `pi` |
| omp | `omp` |
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
codex this is `--sandbox read-only`. The `agentic-team discover` output records
`native_subagent_disable_flag` per harness; dispatch sets it when non-null.
This is stronger than the PATH guardrail because it is enforced by the harness
process itself, not by a wrapper script.

### 2a. Cross-harness escalation (RISK-ACCEPTED note)

Some harnesses have no read-only sandbox flag and must run with permissions
relaxed to work non-interactively. These are the accepted-risk dispatch paths:

- **opencode** runs with `--dangerously-skip-permissions` (and, where
  applicable, `--allow-all-tools` / `--allow-all-paths`). This is required for
  non-interactive dispatch; the workdir fence (§1) and the leaf-worker clause
  (§4) are the containment for it, not a native sandbox.
- **copilot** is gated behind an explicit opt-in: a copilot dispatch is
  refused unless `AGENTIC_TEAM_ALLOW_COPILOT=1` is set, because its
  non-interactive mode also relaxes permissions.

Two dispatch defaults keep cross-harness escalation from happening silently:

- **`dispatch.failover` defaults to `false`.** Failover re-runs the same brief
  on a *different* harness (a different sandboxing posture and a different
  provider's credentials), so it is opt-in per team via `dispatch.failover:
  true` in `team.yml`. Same-harness retries (`dispatch.retries`) stay on the
  original harness/model and are unaffected.
- **The worker environment is an allowlist, not the conductor's full
  `os.environ`.** A dispatched worker receives shell/locale/runtime basics,
  recognized provider-auth variables, and the harness/provider prefixes this
  tool dispatches to - not every unrelated credential in the parent
  environment. Set `AGENTIC_TEAM_ENV_PASSTHROUGH=<comma-separated names>` to
  force-forward extra variables for a non-standard setup.

### 3. PATH guardrail (accidental re-entry -- NOT a security sandbox)

Each worker launch prepends a wrapper directory to `PATH`. Shims in that
directory for `git`, `omc`, and all sibling CLI names (`codex`, `gemini`,
`cursor-agent`, `kimi-cli`, `pi`, `omp`, `claude`) exit 1 and append a line to
`<workdir>/.agentic/teamrun/<run-id>/violations.log`. The worker's own binary
is exempt (a codex worker can still run `codex`; its shim is not placed).

**This guardrail catches accidental bare-name re-entry by a cooperative worker.
It does NOT stop an absolute-path call (`/usr/bin/git`, a pre-resolved path, or
a worker that deliberately bypasses `PATH`).** It is a guardrail, not a
guarantee. Do not claim it provides enforcement beyond its design surface.

### 4. Leaf-worker clause (defense-in-depth)

Every worker brief includes the clause:

> "You are a leaf worker: do not spawn sub-agents, do not run git, do not
> invoke oh-my-claudecode."

This relies on worker cooperation. It is defense-in-depth, not a hard fence.

### 5. Conductor-side suppression

Two independent layers keep the conductor from spawning native subagents when
a role should be cross-harness dispatched instead: a **proactive routing
check** (runs before any dispatch has ever happened) and the sentinel
suppression described below (active only after a run is in flight).

**Proactive team-routing enforcement (fixes the chicken-and-egg bug):** the
sentinel-only suppression below has a gap - the sentinel is created by the
*first* `agentic-team dispatch`, so if the conductor never dispatches (e.g. it
keeps using native `Task`/`Agent` because nothing is stopping it), a `team.yml`
with `enabled: true` was previously silently ignored. `hooks/enforce-background-
spawn.py` closes this gap with a branch that runs BEFORE the sentinel check: it
loads the effective `team.yml` (global + project, project wins, same merge
semantics as `bin/agentic-team`; PyYAML imported opportunistically, fails open
if unavailable) and, when `enabled: true` and the spawned `subagent_type` is one
of the five dispatchable roles (`engineer`, `debugger`, `qa-engineer`,
`skeptic`, `security-auditor`) whose resolved harness (role entry, else
`default_harness`) is anything other than `claude`, denies the native spawn
with an actionable instruction, e.g.:

> `cross-harness team active: role 'engineer' is assigned to harness 'omp'
> (model kimi/kimi-k2.7). Dispatch with: bin/agentic-team dispatch --harness
> omp --role engineer --brief <file> --workdir <dir> --model kimi/kimi-k2.7 -
> then poll status/collect.`

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
via `agentic-team` instead.

Stale-sentinel guard: the hook treats `.active` as expired when its recorded
PID is dead OR its mtime is more than 2 hours old, so a crashed conductor does
not permanently suppress native Task. The sentinel self-expires when its conductor PID is dead or its mtime exceeds 2 h; there is no manual clear command.

Sentinel lifecycle: created by `agentic-team dispatch` on first run (carries
conductor PID); removed by `agentic-team collect` when the last run in the
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
| **Hermes** | Prose-contract only - no hook infrastructure | Would live in a Hermes hook slot if the runtime adds them |

The leaf-worker clause (layer 4) and workdir fence (layer 1) provide
defense-in-depth for harnesses without hook enforcement. Agents on prose-only
harnesses must apply the suppression as a discipline; callers cannot rely on
mechanical enforcement as a guarantee.

## How collected worker output re-enters the Skeptic/QA gates

Cross-harness workers are leaf processes. They write their output to
`<workdir>/.agentic/teamrun/<run-id>/stdout` (and `stderr`, `exit`).
`agentic-team collect <run-id>` demuxes the per-harness output shape and
returns the final message text:

| Harness | Output shape | collect extraction |
|---|---|---|
| codex | JSONL events | last event matching `type: message` |
| gemini | JSON `{response: ...}` | `jq '.response'` |
| cursor-agent | JSON | `jq '.result'` |
| kimi | raw text (`--final-message-only`) | raw stdout |
| pi / omp | raw text (default text mode) | raw stdout |
| claude (worker) | JSON `{result: ...}` | `jq '.result'` |

Once `collect` returns the final message, **that text is treated identically to
a Worker return summary from a native subagent.** The conductor passes it to the
standard Skeptic and QA gates unchanged:

- The Skeptic receives the collected output as the diff/plan under review; the
  adversarial brief and findings classification are unchanged.
- The QA gate fires on the same `qa_criteria` trigger logic as any other Worker
  unit (see `content/sections/05-qa-gate.md`).
- Re-route limits (max 3 fix passes), convergence-failure escalation, and
  per-ticket QA flow are all applied identically.

No new gate, no bypass, no special case for cross-harness origin. The harness
boundary is transparent to the Skeptic/QA layer.

## Supervision, stall/timeout detection, and failover

Every dispatched worker (all 9 harnesses, not just `cursor-agent`) runs under
`bin/_supervise.py`'s `supervise()`: a background poll loop that watches
stdout/stderr mtimes for a heartbeat, kills the whole process group
(`os.killpg`) on stall (`EXIT_STALL`/125) or hard timeout (`EXIT_TIMEOUT`/124),
and records every state transition to `<run-dir>/status.json`. `team.yml`'s
optional `dispatch:` block (`timeout_seconds`, `stall_seconds`, `retries`,
`failover`) tunes this per-project; unset keys fall back to
`_supervise.py`'s per-harness stall defaults.

On a nonzero exit (including a stall/timeout sentinel), dispatch advances a
failover chain: same-harness retries first, then other models declared for
the role in `team.yml`, then a terminal `claude` fallback -- writing
`retrying` or `failed_over` to `status.json` at each step. The conductor
should poll `agentic-team status --json` (no run-id) rather than raw file
reads to narrate state transitions to the operator, since it reflects the
current attempt/harness/model after any failover, not just the original
dispatch parameters.
