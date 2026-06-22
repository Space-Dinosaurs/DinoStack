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
               content/sections/04-risk-classification.md (Tier/role-models layer);
               content/references/role-models.md (Pi/omp role-model schema);
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
- Spawns where `agentic-team discover` marks the target harness absent or
  unauthenticated.

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
  output_format: json
```

**Field notes:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `enabled` | bool | yes | Set `false` to disable cross-harness dispatch without removing the file. |
| `default_harness` | string | no | Fallback harness for roles not listed under `roles:`. Validated against the known-harness table; unknown value -> non-zero exit. |
| `roles` | map | no | Keys are role names (same set as `role-models.yml`). Values are a scalar harness name or `{harness, model}` mapping. |
| `roles[*].harness` | string | yes (if mapping) | Must be one of the 7 known harness labels. Unknown value -> non-zero exit. |
| `roles[*].model` | string | no | Passed to the harness's `--model` flag. Omit to let the harness use its session default (no hardcoded IDs). |
| `dispatch.timeout_seconds` | int | no | Per-worker wall-clock timeout. Default 1800 (30 min). Watchdog kills the process on expiry. |
| `dispatch.output_format` | string | no | `json` (default) or `text`. Governs the `collect` demux path. |

The scalar-or-mapping normalize logic for role-spec entries is shared with
`bin/agentic-configure` via `bin/_role_spec.py`. Both tools import the same
normalizer; there is no inline copy.

Role names are the same set as `role-models.yml`: `conductor`, `investigator`,
`architect`, `orchestration-planner`, `engineer`, `debugger`, `qa-engineer`,
`skeptic`, `security-auditor`. Unrecognized role keys are passed through and
the dispatch tool validates the harness field regardless.

## Per-harness dispatch table

`bin/agentic-team dispatch` builds the worker invocation from this table. Exact
flags for kimi, pi, and omp are **probed at discovery time** (`agentic-team
discover`), not hardcoded -- consistent with the "no hardcoded model IDs" stance
from `content/references/role-models.md`.

| Harness | Non-interactive incantation | Output flag | Notes / gotchas |
|---|---|---|---|
| **codex** | `codex exec "<brief>"` or `codex exec -` (stdin) | `--json` (JSONL events) | `--sandbox read-only` applied by default; `--skip-git-repo-check` added when workdir is not a git repo; reads saved auth or `CODEX_API_KEY`; final message extracted from the last JSONL event. |
| **gemini** | `gemini -p "<brief>"` | `--output-format json` | Headless on non-TTY or `-p`; slash/custom commands are broken headless -- pass the full brief inline; `head -c 50000` guard applied to large stdin. Response text extracted via `jq '.response'`. |
| **cursor-agent** | `cursor-agent -p --force "<brief>" < /dev/null` | `--output-format json` | `--force` required for file writes; **known hang bug** -- stdin is always redirected from `/dev/null` AND a timeout + kill watchdog is applied; marked `experimental` in discovery output until upstream fixes the hang. |
| **kimi** | `kimi-cli` headless run (exact flag confirmed by `discover`) | per kimi-cli | Binary name is `kimi-cli` (not `kimi`); exact non-interactive flag probed at discovery. No custom slash commands; methodology loaded via inline skill content in the brief. |
| **pi** | `pi` run with prompt (pi-coding-agent; `.pi/` project resources) | per pi | Built-in subagent types exist but MUST be suppressed via the leaf-worker clause. Exact headless flag probed at discovery. |
| **omp** | oh-my-pi headless run | per omp | Same leaf-worker suppression; omp built-in subagents not used as nested spawns. Exact flag probed at discovery. |
| **claude (worker)** | `claude -p "<brief>"` | `--output-format json` | Only as a *dispatched leaf worker*, never re-entering OMC. Harness label is `claude`; binary is `claude`. |

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

> "You are a leaf worker: no sub-agents, no git, no oh-my-claudecode. Write
> your output to the workdir and exit. Do not spawn any additional processes
> beyond your own execution."

This relies on worker cooperation. It is defense-in-depth, not a hard fence.

### 5. Conductor-side suppression

While the sentinel file `<workdir>/.agentic/teamrun/.active` exists, the
conductor suppresses native `Task` spawns and OMC skill calls.

**On Claude Code:** hook-enforced. The existing
`hooks/enforce-background-spawn.py` hook (wired by `.claude/install.sh`, already
intercepting `Task`) is extended with a branch: when `.active` exists and is
live (conductor PID present + not dead, mtime < 2 h), the hook denies any
`Task` call outright (not just non-background) and denies any Skill call whose
`skill` argument starts with `oh-my-claudecode:`. The denial message instructs
the conductor to dispatch via `agentic-team` instead.

Stale-sentinel guard: the hook treats `.active` as expired when its recorded
PID is dead OR its mtime is more than 2 hours old, so a crashed conductor does
not permanently suppress native Task. `agentic-team status --reap` clears
expired sentinels explicitly.

Sentinel lifecycle: created by `agentic-team dispatch` on first run (carries
conductor PID); removed by `agentic-team collect` when the last run in the
batch completes.

**On all other harnesses:** prose rule only. There is no hook infrastructure
equivalent to `enforce-background-spawn.py` on codex, gemini, kimi, cursor,
pi, or omp. The suppression on those harnesses is stated here as a convention
the conductor follows, **not as a mechanically enforced constraint.** Agents
running on those harnesses must apply the suppression as a discipline, not rely
on it as a guarantee.

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
| kimi | per kimi-cli (probed) | shape confirmed at AC2 discovery |
| pi / omp | per harness (probed) | shape confirmed at AC2 discovery |
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
