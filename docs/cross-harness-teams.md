<!--
Purpose: Operator-facing guide for the cross-harness agent-teams feature
         introduced with bin/agentic-team. Explains what it does, when to use
         it, how to set it up, the four subcommands, the self-containment
         guard, and the concrete failure modes the operator should expect.
         Works on any conductor harness (Claude, Codex, Gemini, Kimi, etc.);
         not specific to Pi or oh-my-pi.

Public API: Operator-facing prose. Read first if you are new to cross-harness
            teams; deeper schema, dispatch table, and self-containment design
            live in `content/references/cross-harness-teams.md`.

Upstream deps: content/references/cross-harness-teams.md (full spec);
               bin/agentic-team (discover|dispatch|status|collect|configure).

See also: content/references/role-models.md (Pi/omp role-model routing schema,
          Layer 1 - separate from this layer).

Downstream consumers: docs site root index; doc-sync-obligation.md
                      cross-references.

Failure modes: Stale if bin/agentic-team or content/references/cross-harness-teams.md
               changes. When the schema changes, update both this doc and the
               reference in content/references/ in the same change.

Performance: Standard.
-->

# Cross-harness agent teams

Dispatch leaf workers to entirely different CLI harnesses -- codex, gemini,
cursor-agent, kimi, pi, omp, or claude-as-worker -- from **any** conductor
harness (Claude Code, Codex, Gemini, Kimi, Pi, omp, or any other). The
conductor retains full orchestration (Skeptic gates, QA gates, risk
classification), while each worker role runs on the CLI best suited to it.
This feature is **self-contained and OMC-independent**: it does not trigger
oh-my-claudecode, and it does not use the conductor harness's own native
subagent mechanism.

This is a **standalone any-harness layer** -- it is not an extension of
role-model routing and it is not specific to Pi or oh-my-pi. Any conductor
harness can use it.

The deeper specification (schema, dispatch table, self-containment design,
and collected-output re-entry into Skeptic/QA gates) lives in
`content/references/cross-harness-teams.md`. This document is the operator
entry point.

## When to use it

You want cross-harness teams when you care about one or more of:

- **Multi-harness shop.** You have codex, gemini, and cursor-agent installed
  and want each role dispatched to the CLI it runs best on, without manual
  context-switching.
- **Harness-level antagonist review.** Your engineer runs on one harness
  (e.g. codex) and your Skeptic reviews the diff on a completely different
  harness (e.g. gemini). This is a harness-boundary diversity win independent
  of any model-level routing.
- **Cost or quota isolation.** Pin quota-heavy roles to cheaper CLIs without
  changing the conductor's own session.
- **Provider experimentation.** Route a single role to a new CLI to evaluate
  it in production without affecting other roles.

You do **NOT** need this layer when:

- You run on a single harness. The Tier declaration mechanism already gives
  you per-role model diversity within one harness.
- `team.yml` is absent or `enabled: false`. Cross-harness dispatch is fully
  opt-in; the conductor falls back to native delegation silently.
- The role is `conductor`, `orchestration-planner`, `investigator`, or
  `architect`. Those always run in the conductor's own context because they
  produce plans the conductor reasons over directly.

## How it relates to role-model routing

These are two distinct, complementary layers -- neither requires the other:

| Layer | File | What it controls | Who it affects |
|---|---|---|---|
| Role-model routing (Layer 1) | `~/.agentic/role-models.yml` (gitignored) | which model to use within ONE harness | Pi / oh-my-pi only |
| Cross-harness teams (Layer 2) | `.agentic/team.yml` (committed) | which harness (and optionally model) per role | any conductor harness |

Role-model routing maps `role -> model` inside a single harness (Pi/omp
only). Cross-harness teams map `role -> (harness, model)` and run that
harness's own non-interactive mode as a separate process. `team.yml` is a
**separate committed file** from the gitignored `role-models.yml` -- team
topology is shareable project intent and belongs in version control.

When both files are present, they compose: `team.yml` selects the harness
and optional model handle; if the target harness is Pi or omp,
`role-models.yml` further refines the model selection on that harness.

## Set up

### 1. Write team.yml

The file can live globally (`~/.agentic/team.yml`) or per-project
(`.agentic/team.yml`, committed). Project keys win on collision; the merge
is shallow per top-level key.

The `.gitignore` umbrella excludes `.agentic/*` by default; the project file
requires an explicit carve-out line `!.agentic/team.yml` so it commits.

Minimum useful file:

```yaml
enabled: true
roles:
  engineer:    { harness: codex,   model: gpt-5.3-codex }
  qa-engineer: { harness: gemini,  model: gemini-2.5-flash }
  skeptic:     { harness: cursor-agent }
```

Full schema:

```yaml
# ~/.agentic/team.yml  or  .agentic/team.yml
enabled: true
default_harness: codex          # where a role goes when not listed under roles:
                                # validated against the 7 known harness labels;
                                # unknown value -> non-zero exit from agentic-team
roles:
  engineer:         { harness: codex,         model: gpt-5.3-codex }
  qa-engineer:      { harness: gemini,        model: gemini-2.5-flash }
  skeptic:          { harness: cursor-agent,  model: cursor-fast }
  security-auditor: { harness: codex,         model: gpt-5.3-codex }
dispatch:
  timeout_seconds: 1800   # per-worker wall-clock limit; default 1800 (30 min)
  output_format: json     # json (default) or text
```

**Field notes:**

| Field | Required | Notes |
|---|---|---|
| `enabled` | yes | `false` disables cross-harness dispatch without removing the file |
| `default_harness` | no | Fallback for roles not listed under `roles:` |
| `roles[*].harness` | yes (mapping form) | One of 7 known labels: codex, gemini, cursor-agent, kimi, pi, omp, claude |
| `roles[*].model` | no | Passed to the harness `--model` flag; omit to use harness session default |
| `roles[*].effort` | no | Forwarded to the harness; silently dropped if unsupported |
| `roles[*].reasoning` | no | Forwarded to the harness; silently dropped if unsupported |
| `dispatch.timeout_seconds` | no | Watchdog kills the worker on expiry; default 1800 |
| `dispatch.output_format` | no | Governs the `collect` demux path |

### 2. Use the setup wizard (optional)

The recommended entry point is the slash command (available in all harnesses):

```
/configure-team
```

Or run the binary directly:

```bash
bin/agentic-team configure
```

The wizard discovers installed harnesses, ranks roles to the best available
(harness, model) pair, and writes a starter file. Use `--assign role=harness:model`
for non-interactive assignment of a single role.

### 3. Verify

```bash
agentic-team discover
```

This probes each known harness and reports `installed` or `absent` per
harness, along with `version`, `models`, `invocation_family`, and
`native_subagent_disable_flag`. Run this after writing `team.yml` to confirm
the harnesses you assigned are present before starting a real session.

Authentication errors are not a discover state. If a harness is installed but
its credentials are invalid or expired, that surfaces at dispatch time from
the harness's own stderr/exit code -- not as a named discover status.

## The four subcommands

- `agentic-team discover` - probe all 7 known harnesses; reports installed
  status, version, reachable models, and invocation family. Use `--json` for
  machine-readable output.
- `agentic-team dispatch --harness <h> --role <r> --brief <file> --workdir <dir>` -
  spawn a worker in the background; prints a run-id to stdout immediately.
  The conductor uses the run-id to check status and collect output later.
- `agentic-team status <run-id>` - prints `running`, `done`, or `failed`.
  Poll this after dispatch to know when the worker has finished.
- `agentic-team collect <run-id>` - demux the per-harness output shape and
  print the final message text. The conductor passes this text to the standard
  Skeptic and QA gates unchanged.

## Per-harness dispatch table

How `agentic-team dispatch` invokes each harness non-interactively:

| Harness | Non-interactive invocation | Notes |
|---|---|---|
| **codex** | `codex exec "<brief>" --json --sandbox read-only --skip-git-repo-check` | `--sandbox read-only` applied by default; JSONL event stream |
| **gemini** | `gemini -p "<brief>" --output-format json` | Headless on `-p`; slash commands broken headless - full brief inline |
| **cursor-agent** | `cursor-agent -p --force "<brief>" --output-format json < /dev/null` | `--force` required for file writes; known hang bug - stdin always `/dev/null` + timeout watchdog; marked `experimental` in discover output. Note: `< /dev/null` is presentation shorthand -- the dispatcher sets `stdin=subprocess.DEVNULL` at the `Popen` call; it is not a literal argv element. |
| **kimi** | `kimi-cli --print --yolo --final-message-only -p "<brief>"` | Binary name is `kimi-cli` (not `kimi`); `--print` required for non-interactive/auto-dismiss behavior |
| **pi** | `pi -p "<brief>"` | Built-in subagent types exist but suppressed via leaf-worker clause |
| **omp** | `omp -p "<brief>"` | Same leaf-worker suppression; omp built-in subagents not used as nested spawns |
| **claude (worker)** | `claude -p "<brief>" --output-format json` | Dispatched as a leaf worker only; does NOT re-enter OMC |

**Binary-name map** (the only hardcoded per-harness fact in the repo):

| Harness label | Binary name |
|---|---|
| kimi | `kimi-cli` (the only label/binary mismatch) |
| all others | same as harness label |

Non-interactive flags for all 7 harnesses (including kimi, pi, and omp) are
**confirmed and fixed**, verified live against each CLI -- not probed at
discovery time. Discovery only probes for available *models* (see the
per-harness dispatch table note above), never the invocation flags
themselves; this is consistent with the "no hardcoded model IDs" stance
(binary names and flag spellings are the one allowed per-harness hardcoded
fact).

## Self-containment - what is actually enforced

The guard is layered. Layers are listed strongest to weakest:

1. **Workdir fence (PRIMARY).** Each worker runs in its own throwaway
   `--workdir` (a git worktree or directory copy). The worker has no access
   to the live repository tree. The conductor is the sole git owner; workers
   never run git on the live repo. This is the real containment boundary.

2. **Harness-native sandbox (strongest per-worker fence, where available).**
   Where the harness exposes a sandbox flag it is applied at dispatch time.
   For codex this is `--sandbox read-only`. Enforced by the harness process
   itself, not by a wrapper script.

3. **PATH guardrail (accidental re-entry -- NOT a security sandbox).** Each
   worker launch prepends a shim directory to `PATH`. Shims for `git`, `omc`,
   and all sibling CLI names (`codex`, `gemini`, `cursor-agent`, `kimi`,
   `kimi-cli`, `pi`, `omp`, `claude`) exit 1 and log to `violations.log`. The worker's
   own binary is exempt. **This guardrail catches accidental bare-name
   re-entry by a cooperative worker. It does NOT stop an absolute-path call
   (`/usr/bin/git` or any pre-resolved path). Do not claim it provides
   enforcement beyond its design surface.**

4. **Leaf-worker clause (defense-in-depth).** Every brief is prepended with:
   "You are a leaf worker: no sub-agents, no git, no oh-my-claudecode."
   This relies on worker cooperation; it is not a hard fence.

5. **Proactive team-routing enforcement (fixes the chicken-and-egg bug).**
   The sentinel below only kicks in once a dispatch has already happened --
   if the conductor never dispatches (nothing was stopping it from using
   native `Task`/`Agent`), a `team.yml` with `enabled: true` was previously
   silently ignored forever. `hooks/enforce-background-spawn.py` closes this
   gap with a branch that runs BEFORE the sentinel check: it loads the
   effective `team.yml` (global + project, project wins; PyYAML imported
   opportunistically, fails open if unavailable) and, when `enabled: true`
   and the spawned `subagent_type` is one of the five dispatchable roles
   (`engineer`, `debugger`, `qa-engineer`, `skeptic`, `security-auditor`)
   whose resolved harness (role entry, else `default_harness`) is anything
   other than `claude`, denies the native spawn with an actionable
   `bin/agentic-team dispatch ...` instruction. `conductor`, `investigator`,
   `architect`, and `orchestration-planner` are never denied by this branch.
   Fails open on every error path (missing file, unreadable, malformed YAML,
   import failure) -- a broken or absent `team.yml` never blocks native
   spawning. Escape hatch: `AE_TEAM_ROUTING_DISABLE=1` skips this branch
   entirely, before any file I/O.

6. **Conductor-side `.active` sentinel.** While
   `<workdir>/.agentic/teamrun/.active` exists (with a live conductor PID,
   mtime < 2 h), the conductor suppresses native `Task` spawns and OMC skill
   calls. On Claude Code this is hook-enforced
   (`hooks/enforce-background-spawn.py`). On all other harnesses it is a prose
   convention, not a mechanically enforced constraint. The sentinel is created
   by `dispatch` on first run and removed by `collect` when the last run
   completes. The sentinel self-expires when its conductor PID is dead or its mtime exceeds 2 h; there is no manual clear command.

## Failure modes

- **cursor-agent headless hang.** Known upstream bug. The dispatcher always
  redirects stdin from `/dev/null` and starts a timeout kill watchdog (default
  300 s for cursor-agent, 1800 s otherwise). The harness is marked
  `experimental` in `discover` output until upstream fixes the hang.
- **Harness not installed.** `discover` reports `installed: false`. `dispatch`
  returns non-zero immediately with a named error -- no silent hang.
- **Harness not authenticated.** `dispatch` surfaces a clear error from the
  harness's own output; it does not hang waiting for credentials. Check the
  harness's own auth flow (`codex login`, `gemini auth`, etc.) then retry.
- **Worker exit captured by reaper.** A background reaper thread writes the
  exit code to `<run-dir>/exit`. If the process crashes without writing an
  exit file, the reaper detects the dead PID and writes `exit=1`; `status`
  then reports `failed` correctly rather than hanging.
- **No team.yml or `enabled: false`.** Feature is inactive. The conductor
  falls back to native delegation unchanged -- no error, no degraded mode.
- **Malformed team.yml.** `agentic-team` exits non-zero with a YAML parse
  error on stderr before any dispatch occurs.
- **Unknown harness or role in team.yml.** Non-zero exit with a named error
  line listing the known values.

## Related references

- `content/references/cross-harness-teams.md` - full spec: schema, dispatch
  table, self-containment design, output collection, Skeptic/QA re-entry
- `bin/agentic-team` - discover, dispatch, status, collect, configure implementation
- `docs/role-model-routing.md` - operator guide for role-model routing (Layer 1, Pi/omp only)
- `content/references/role-models.md` - Pi/omp per-role model routing schema (Layer 1)
