# Implement Ticket

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Take a ticket (Linear, Jira, or none) from description to merged PR, with agent orchestration matched to the active tier (minimal: engineer + Skeptic; medium: + conditional architect + inline 5-line Brief; full: + Brief/Plan artifacts + QA gate + wrap-ticket) and the CI Test URL posted back to the ticket.

## Invocation

`/implement-ticket <input> [--tier=minimal|medium|full]`

`<input>` accepts: a single ticket ID (`DINO-639`), a comma/space-separated list, a tracker issue URL (Jira `/browse/...`, Linear `/issue/...`), a tracker search/filter URL, a pasted screenshot, a freeform description, any mixture, or a project-local classifier in `.agentic/phase0-classifiers.yml`.

Phase 0 input normalization runs inside the body file, not here. Bare-ID, single-issue-URL, and operator-enumerated list invocations bypass the confirmation prompt — backward compatible with the prior single-argument contract.

---

## Tier resolution (router-owned)

Resolve the active tier BEFORE any other logic. Resolution order (first wins):

1. CLI flag: `--tier=minimal|medium|full`.
2. Project config: `agentic_tier` in `.agentic/config.json`.
3. Global config: `tier` field in `~/.claude/agentic-engineering.json` (or harness-equivalent shared config — `~/.codex/config.toml`, `~/.gemini/settings.json`, etc.).
4. Legacy `profile` field in either config: `relaxed` → `minimal`, `default` → `medium`, `strict` → `full`.
5. Default: `minimal`.

Dispatch to the body file matching the active tier:

- `tier=minimal` → `implement-ticket-minimal.md`
- `tier=medium` → `implement-ticket-medium.md`
- `tier=full` → `implement-ticket-full.md`

The body file lives in the same directory as this router. In source installations that is `content/commands/`; each adapter copies the router + all three body files into the harness's commands dir (`.claude/commands/`, `.codex/commands/`, `.gemini/commands/`, `.github/prompts/`), so the body is always co-located.

Read `implement-ticket-<tier>.md` next to this router and execute it as if it were this command's body. Do not summarize; follow it verbatim. The `$ARGUMENTS` / `<input>` value is propagated as-is — input normalization is the body file's responsibility, not the router's.
