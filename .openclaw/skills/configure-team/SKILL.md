---
name: configure-team
description: "Set up and verify a cross-harness agent team so any conductor (Claude, Codex, Gemini, Kimi, or other) can dispatch work across multiple AI harnesses with explicit role assignments."
user-invocable: true
---
# /configure-team - Cross-Harness Team Setup

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Set up and verify a cross-harness agent team so any conductor (Claude, Codex, Gemini, Kimi, or other) can dispatch work across multiple AI harnesses with explicit role assignments.

## Step 1 - Configure the team

Run `bin/agentic-team configure` to launch an interactive wizard that walks through role-to-harness assignments and writes `.agentic/team.yml` (or `~/.agentic/team.yml` for a user-global config):

```bash
bin/agentic-team configure
```

For non-interactive use - useful in scripts or automated onboarding - pass assignments directly:

```bash
bin/agentic-team configure \
  --non-interactive \
  --assign architect=claude:claude-opus-4-5 \
  --assign engineer=codex:gpt-5 \
  --assign skeptic=gemini:gemini-2.5-pro \
  [--default-harness claude] \
  [--path .agentic/team.yml]
```

`--assign` accepts `role=harness:model`. Repeat for each role. `--default-harness` sets the fallback harness for any unassigned role. `--path` overrides the output location (default `.agentic/team.yml`).

Add `--web` to allow the wizard to make a live network call for model-capability enrichment when ranking assignments. Offline by default.

Exit codes: `0` success or no-op; `2` bad `--assign` value, unknown `--default-harness`, or `--non-interactive` used without `--assign`.

## Step 2 - Verify discovery

Confirm which harnesses are installed and which models they can reach:

```bash
bin/agentic-team discover
```

For machine-readable output:

```bash
bin/agentic-team discover --json
```

Each discovered harness reports its binary path, reachable models, and any auth errors. A harness listed as `--assign` target but absent from discovery output means it is not installed or not authenticated - resolve that before dispatching.

## Step 3 - Dispatch a team

See `content/references/cross-harness-teams.md` for the full dispatch, status-check, and collect flow.

**Suppression contract (binding on all harnesses).** While a team run is active - indicated by `.agentic/team-active` existing in the project root - the conductor MUST NOT spawn its own native subagents. The cross-harness team is the active delegation surface; spawning native agents alongside it creates duplicate work and uncoordinated state. On Claude Code this contract is enforced by a hook; on Codex, Gemini, Kimi, and other harnesses it is a prose contract that the conductor must honor. Treat the presence of `.agentic/team-active` as a hard suppression signal regardless of harness.
