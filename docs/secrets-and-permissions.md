# Secrets and permissions

Where secrets belong, what the framework writes to disk, how a secret can still
leak even when stored correctly, and how to scope permissions so a mistake costs
less. Companion to [SAFETY.md](../SAFETY.md),
[safe-configuration.md](safe-configuration.md), and
[threat-model.md](threat-model.md). Report flaws via
[SECURITY.md](../SECURITY.md).

## Where secrets belong

- **`.claude/settings.local.json`** - the home for secrets and local env values.
  It is **always gitignored** ([content/rules/conventions.md](../content/rules/conventions.md)),
  so it never lands in a commit.
- **`.env`, `.env.local`, `.env*.local`** - gitignored environment files, fine
  for local credentials.

Put nothing secret in a tracked, committed file.

## Committed vs gitignored: the `.agentic/` carve-out map

The `.agentic/` directory is broadly gitignored, but several files are
deliberately **committed** because they carry portable project intent. This
matters for secrets: a committed file ends up in history and on every clone, so
never write a credential into one.

| Path | State | Why |
|---|---|---|
| `.claude/settings.local.json` | **gitignored** | Secrets and local env. |
| `.env`, `.env*.local` | **gitignored** | Local credentials. |
| `.agentic/config.json` | **committed** | Project methodology toggles - portable intent ([content/rules/conventions.md](../content/rules/conventions.md)). |
| `.agentic/qa.md`, `.agentic/deploy.md` | **committed** | QA triggers and deploy knowledge - travel with the repo. |
| `.agentic/session-log/<id>.jsonl` | **committed** (when `commit_telemetry: true` and identity confirmed) | Per-developer session telemetry, made team-visible after merge. |
| `.agentic/events.jsonl` | **gitignored** | Local structured event log. |
| `.agentic/learnings.md`, `.agentic/findings.md`, `.agentic/qa-regressions.md` | **committed** | Curated patterns - part of the intent layer. |
| `.agentic/loop-state.json`, `.agentic/tasks.jsonl`, `.agentic/worktrees/` | **gitignored** | Ephemeral runtime state. |

The committed files - `config.json`, `qa.md`, `deploy.md` - are the easy place
to accidentally paste a secret (a database URL, an API endpoint with an embedded
token). Do not. Reference secrets by name and keep the value in
`.claude/settings.local.json`.

Note: this repo (DinoStack itself) gitignores its **own** entire `/.agentic/`
because it is the methodology, not a consumer of it. The carve-out map above
describes how **consumer projects** track this state. See the comments in this
repo's [`.gitignore`](../.gitignore).

## What the framework writes

The framework writes telemetry as agents run:

- **`.agentic/events.jsonl`** - a per-project structured event log
  (spawns, returns, findings, QA results). Gitignored.
- **`.agentic/session-log/<developer_id>.jsonl`** - a per-developer session
  rollup written by the Stop hook. Committed when `commit_telemetry: true`
  (the default) and identity is confirmed, then made team-visible after merge
  ([content/rules/conventions.md](../content/rules/conventions.md)).

**The no-secrets boundary is a design intent, not an enforced guarantee.** The
telemetry schema enumerates a fixed set of fields and explicitly excludes prompt
content, file paths, tool I/O, user messages, finding text, commit messages, and
environment variable values
([content/sections/09-events-log.md](../content/sections/09-events-log.md)).
That is the **intended** boundary. It is not runtime-enforced redaction:
nothing scans these writes and strips a secret that slipped into a free-text
field such as a `note`. Treat the boundary as a design contract that a bug could
violate, and review what gets committed - especially the session-log commit.

## How secrets can still leak

Storing a secret correctly is necessary, not sufficient. The framework does not
sandbox the agent, so:

- An agent that **legitimately reads** a secret (to call an API or run a test)
  can then send it over the network or write it somewhere unintended. This is
  the secret-exfiltration scenario in [threat-model.md](threat-model.md).
- A secret pasted into a **committed** `.agentic/` file (see the map above)
  enters git history.
- A secret that lands in a free-text telemetry field is not stripped by the
  no-secrets boundary, because that boundary is intent, not enforcement.

There is no layer that prevents a secret the agent holds from leaving the
machine. The mitigation is to limit what the secret can do.

## Scoping permissions to reduce blast radius

- **Least privilege.** Give credentials the narrowest scope that works - a
  token that can read one repo, not your whole account.
- **Short-lived.** Prefer expiring tokens over long-lived keys, so an exposed
  secret has a short useful life.
- **Match the risk profile to the context.** Use `strict` on shared or
  sensitive repos so more changes get independent review before they land
  ([safe-configuration.md](safe-configuration.md#risk-profiles)).
- **Keep the deny-list configured.** It rails off the destructive command forms
  most likely to do collateral damage
  ([safe-configuration.md](safe-configuration.md#deny-list)).
- **Constrain the environment** for untrusted work - a throwaway checkout or a
  machine without production credentials limits what a misused secret reaches.

## If a secret was ever committed

Treat it as compromised. **Rotate it immediately** - revoke the exposed
credential and issue a new one - and assume the old value is public, because git
history and any public mirror (this repo's `docs/` is served publicly) may
retain it. Then report the exposure per [SECURITY.md](../SECURITY.md) if it
points to a framework-level flaw (for example, the framework wrote the secret
somewhere it should not have). General contribution guidance is in
[CONTRIBUTING.md](../CONTRIBUTING.md).
