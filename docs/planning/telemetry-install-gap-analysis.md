# Telemetry install gap analysis

**Author:** Tyson Hummel
**Date:** 2026-05-28
**Status:** Proposal — gap analysis + recommended remediation

## Problem statement

The agentic-engineering methodology defines a per-project structured event log (`.agentic/events.jsonl`) and a consumer CLI (`agentic-cost`) that rolls token / wall-time / dollar stats off that log. Both are documented in `METHODOLOGY.md §Events log`, `content/references/events-log.md`, and the `agentic-cost` skill spec.

On a real project that has been running `/implement-ticket` and other Elevated-path flows for weeks (Crocs storefront, 27+ DINO tickets shipped), neither piece is functional:

1. `.agentic/events.jsonl` does not exist. No conductor turn has appended to it. The producer side of the V1 telemetry schema is unwired.
2. `bin/agentic-cost` is not on `PATH` and is not present at any of the obvious install locations (`~/agentic-engineering/bin/`, `~/.claude/skills/agentic-engineering/bin/`). `init-project` does not install it.

The result: a real-world user invoking `/agentic-cost project` to evaluate AE methodology effectiveness gets "command not found" with no data to roll up anyway. The V1 telemetry surface that AE markets is invisible to the user it was built for.

## Evidence (session 2026-05-28)

User attempted to compute AE effectiveness vs DINO peers. Three reports were generated against Jira + GitHub data:

- `crocs-qa-stats-2026-05-28.md`
- `crocs-qa-stats-peer-comparison-2026-05-28.md`
- `ae-effectiveness-analysis-2026-05-28.md`

All three relied on external sources (Jira changelog, GitHub PR metadata) because the local AE telemetry was empty. Invoking `/agentic-cost project` returned:

```
agentic-cost: command not found
```

Inspection of the project tree:

```
$ ls -la .agentic/events.jsonl
ls: .agentic/events.jsonl: No such file or directory
```

Inspection of install scaffold:

```
$ find ~ -maxdepth 4 -name agentic-cost -type f
(no results)
```

`~/.claude/skills/agentic-engineering/` contains `METHODOLOGY.md`, `SKILL.md`, `references/`, `rules/`, `SKILL.frontmatter.yaml` — no `bin/` directory and no executable.

## Gap 1 — events.jsonl emission is documented but unwired

**Spec status:** `METHODOLOGY.md §Events log` defines the per-line schema (`ts`, `phase`, `event`, `agent`, `task_id`, `data`). `content/references/events-log.md` defines the V1 event-type field shapes. Both describe the consumer side cleanly.

**Producer side:** The spec says "Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony." This is the gap. The protocol relies on:

1. Command-spec authors to embed `echo '{...}' >> .agentic/events.jsonl` at every documented boundary in `content/commands/*.md`, OR
2. The conductor (the LLM) to remember to fire the same shell snippets at every spawn / return / phase transition.

Inspection of `content/commands/implement-ticket.md` (~3,000 lines) shows boundary breadcrumbs (`[phase: ...]`) at every transition but no `events.jsonl` append-shell-snippet calls. Same is true across other command specs. The result is that even an obedient conductor following the spec literally does not produce events.

**Why convention-based emission fails in practice:**

- LLM conductors do not reliably remember to fire telemetry shell snippets across long sessions with many phase transitions. Even with strong rule-following, there is no harness-level enforcement, so emission is best-effort and silently fails closed.
- Adding emit snippets to every command spec adds significant prose ceremony, raises maintenance burden, and produces a copy-paste pattern that is easy to drift across spec versions.
- No CI check or pre-commit gate verifies that a spec author who added a new boundary also added the corresponding emit. The producer side rots silently.

**Effect on `/agentic-cost`:** The CLI is designed to read from `events.jsonl`. With no producer, the CLI has nothing to report on. The "V1 instruments engineer/skeptic/qa only" disclosure footer is technically true but masks the deeper problem: V1 instruments nothing if the producer is never wired.

## Gap 2 — `bin/agentic-cost` is not installed by `init-project`

**Spec status:** The `agentic-cost` skill spec at `~/.claude/skills/agentic-engineering/` (or wherever the per-adapter copy lives) references `bin/agentic-cost` as the implementation. The slash-command body documents the CLI surface (`session | task | project`), the optional `pricing.yml` dollar-column behavior, the V1 disclosure footer.

**Install side:** Inspection of `content/commands/init-project.md`:

- Grep for `agentic-cost` → zero hits
- Grep for `bin/` → zero hits in the install scaffold

`init-project` scaffolds `.agentic/` directories, gitignore patterns including `.agentic/events.jsonl`, project-local AGENTS.md, and the standard tool-agnostic config files (`qa.md`, `deploy.md`, `tracking.md`). It does not symlink or copy the `agentic-cost` binary into any per-user PATH location.

`.claude/install.sh` does adapter-level wiring (`~/.claude/CLAUDE.md` managed content, hooks, skill registration) but does not install the `agentic-cost` binary either.

**Where the binary actually lives:** Inspection of `/Users/tyson.hummel/Documents/tools/agentic-engineering/` (this repo) shows that `bin/agentic-cost` was searched for above; if it exists in the source repo, no install path copies it to a user-accessible location.

**Effect:** Even if `events.jsonl` were populated, the consumer is unreachable. The skill spec describes a CLI that the user cannot invoke.

## Why this matters

The V1 telemetry surface is the only first-party way for a user to evaluate AE methodology effectiveness using AE's own instruments. Without it, users fall back to external proxies (Jira changelog mining, GitHub PR metrics, time-tracking heuristics) — all of which require multi-step research and produce results loaded with confounders (ticket-mix differences, status-flip-discipline variation, reviewer rigor variation).

The user in the evidence session above ran three external-data reports across ~9 hours of session time to produce a defensible AE-effectiveness analysis. A working `/agentic-cost project` against a populated `events.jsonl` would have produced the same data at session-end with one command.

If AE is going to be evaluated by users (and it should be), the V1 surface needs to actually surface.

## Proposed remediation

Two fixes, ordered by leverage:

### Fix A — auto-emit events from a harness hook (Claude Code first)

Replace the convention-based "spec authors embed shell snippets" pattern with a hook-based auto-emit. Specifically:

1. Add a `PostToolUse` hook entry for the `Task` tool (subagent spawn) that appends `spawn_start` events to `.agentic/events.jsonl` on the tool call and `spawn_complete` events on the tool return.
2. Add a `Stop` hook entry that appends the V1 `session_total` event already documented in `events-log.md`.
3. Keep the documented per-spec `[phase: ...]` breadcrumbs — those are for human-readable transcripts, not telemetry. But remove the assumption that conductor-driven shell snippets will produce telemetry.

Adapter coverage:

- Claude Code: hook entries in `.claude/install.sh` (managed content) wire `PostToolUse(Task)` and `Stop` to a small bash script. The script does the JSONL append with `flock`-style locking — or accepts EEXIST on append since JSONL is append-only.
- Codex / Gemini: per-adapter equivalent hooks. V1 spec says these adapters produce no token data; they can still emit `spawn_start`/`spawn_complete` skeletons with token fields nulled.

This converts telemetry from "convention adhered to by an LLM" to "side effect of running the harness." It cannot silently fail closed.

### Fix B — install `bin/agentic-cost` from `init-project` (and adapter installs)

Add an explicit step to `init-project` (or to the per-adapter install.sh) that places the `agentic-cost` binary on the user's PATH. Two viable mechanisms:

1. **Symlink from the source repo.** `bootstrap.sh` (per AGENTS.md, the public `curl | bash` installer) writes `repo_dir` to `~/.agentic/agentic-engineering-config.json`. The install scripts can read `repo_dir` and `ln -s "${repo_dir}/bin/agentic-cost" /usr/local/bin/agentic-cost` (or `~/.local/bin/agentic-cost`). Symlink keeps the binary in sync with whatever version the repo is at.
2. **Vendor into the adapter install.** Each adapter's `install.sh` copies the binary into the adapter's bin directory and adds that directory to PATH. Simpler isolation but creates drift between adapters.

Mechanism 1 is preferred because the V1 binary is Python stdlib (per the skill spec) and one source-of-truth is more maintainable.

`init-project` should verify after install that `agentic-cost --version` (or `agentic-cost session --help`) is callable, and emit a clear failure with the PATH gap diagnosed if not.

### Fix C (downstream of A) — surface the empty-log case clearly

Once Fix A lands, projects that turn on agentic-engineering AFTER existing work will have empty or partial `events.jsonl` for historical tickets. The CLI should explicitly say so when invoked against a near-empty log, e.g.:

```
events.jsonl contains 0 events (telemetry was not active before <YYYY-MM-DD>).
No rollup possible. Run /implement-ticket or other instrumented flows to begin populating.
```

rather than the current behavior of "command not found" or (post-Fix-A-only) silently rendering a 0-row table.

## Recommendation

Land Fix A first. It is the load-bearing change — Fix B is useless without it. Fix A is also small (one hook entry per adapter, one bash emit script in the repo, no spec rewrites required) and immediately unblocks every project that has the methodology installed.

Fix B can land in the same release or shortly after. It is install-only and adapter-local — no user-facing protocol change.

Fix C is one-line UX polish.

## Open questions

- Does `bin/agentic-cost` exist in the source repo as a working Python script? This doc assumes yes per the skill spec; if no, the binary itself is the first deliverable, not the install path.
- Are there other V1 consumers besides `/agentic-cost` that depend on `events.jsonl` and are equally unreachable today (e.g. the meta-divergence sweep documented in `content/rules/conventions.md`)? Worth scanning.
- Should the harness-level emit hook live in the agentic-engineering repo and be installed per-adapter, or should each adapter's install.sh ship its own emit script with a shared schema? Centralized script is easier to maintain; per-adapter scripts handle differences in hook payload shape.
