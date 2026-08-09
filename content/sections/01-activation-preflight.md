## Activation preflight

Run this check once at the first skill invocation (and every `/`-command). Read activation config and the project marker directly; resolve identity exactly once with `ds-identity resolve-hook --cwd <cwd>` (3-second timeout, 64 KiB output cap). Do not spawn or use LLM reasoning. Resolver failure means identity `none` and never blocks activation. **Exception:** Step 6 may run the bounded, fail-open `bin/ds-migrate` scaffolding sync.

1. **Read the global mode and profile.** Load `~/.claude/agentic-engineering.json`. If missing or unreadable, assume `mode=opt-out` and `profile=default` (back-compat). Expected shape: `{ "mode": "opt-out" | "opt-in", "profile": "relaxed" | "default" | "strict", "set_at": "<ISO8601>" }`. Any `mode` value other than `opt-in` is treated as `opt-out`. Any `profile` value other than `relaxed` or `strict` is treated as `default` (see the deprecated legacy preset subsection below for the fallback path when `profile` is genuinely absent rather than merely invalid).

   Also invoke that resolver and record only validated JSON `null` or `{developer_id, provisional, identity_scope, config_dir?}`. It safely discovers project/profile/global candidates and applies confirmation-first ordering: project > profile > global, then provisional project > profile > global. Do not re-read identity files. A provisional winner triggers the scoped first-turn notice. Full resolver and routing contract: `content/commands/ds-identity.md`.

   **Deprecated legacy preset (read-only compat).** Older configs may still carry a session-wide `preset` field (`lean` | `standard` | `strict`) at either scope. It is a read-only fallback used ONLY when `profile` is genuinely ABSENT at that scope - check key presence, not truthiness. An invalid `profile` value is treated identically to absent for this purpose (a valid legacy `preset` may then apply); if nothing validates anywhere, terminate at `default`.

   Legacy preset table:

   | Preset    | Resolves to profile |
   |-----------|---------------------|
   | lean      | relaxed             |
   | standard  | default             |
   | strict    | strict              |

   Precedence chain (replaces the old "preset wins on collision" rule): project `profile` > project `preset` (legacy, only if project profile absent) > global `profile` > global `preset` (legacy, only if global profile absent) > hardcoded `"default"`.

   Presence of a legacy `preset` key at either scope fires a deprecation notice regardless of whether it wins resolution (see §Session Context and Memory in `content/rules/conventions.md` for the two notice templates).

   Note: this deprecated session-wide `preset` field is distinct from the per-spawn `Preset:` declaration introduced in the Tier declaration section below - that mechanism is unaffected by this deprecation. The session-wide preset was a legacy tone-setting alias; the per-spawn preset is a capability bundle. Both terms use "preset" intentionally - context disambiguates.
2. **Read the project marker.** Look for a root `AGENTS.md` in the current working directory. If the project uses the Claude Code `@AGENTS.md` import pattern, `CLAUDE.md` will point at it - resolve through to the actual `AGENTS.md`. If neither file exists, treat marker as `none`.
3. **Scan for marker lines.** Case-insensitive, whole-line match (allow leading or trailing whitespace, and an optional markdown list prefix `- `):
   - `agentic-engineering: opt-in`
   - `agentic-engineering: opt-out`
   If both appear, the one that appears FIRST wins; print a one-line warning: `dinostack: both opt-in and opt-out markers found in AGENTS.md - using the first one (<value>). Remove the duplicate.`
   Also scan for `agentic-engineering-profile: <value>`. If present, it overrides the global profile. Valid values: `relaxed`, `default`, `strict`. Any other value falls back to the precedence chain in the deprecated legacy preset subsection above (project preset, then global profile, then global preset, then default).
   Also scan for `agentic-engineering-preset: <value>` (deprecated legacy alias). If present, it resolves through the legacy preset table above ONLY when no valid `agentic-engineering-profile:` line is present in the same file - it is a fallback below the project profile, not an override that wins on collision. Any other value falls back to the next step in the precedence chain (global profile, then global preset, then default). Presence of this marker fires a deprecation notice regardless of whether it wins.
4. **Activation decision.**
   - `mode=opt-out` AND `marker=opt-out` - skill no-ops silently; fall back to default Claude Code behavior for this session.
   - `mode=opt-in` AND `marker != opt-in` - skill no-ops silently; fall back to default behavior.
   - Any other combination (including `marker=none` with `mode=opt-out`, or `marker=opt-in` with `mode=opt-in`) - proceed with the methodology.

   On any proceed branch: immediately run Step 5 (first-activation notice) and Step 6 (scaffolding-sync); read `content/references/activation-detail.md` §Step 5: First-Activation Notice and §Step 6: Scaffolding-Sync Check for the full implementation.

   *(Steps 5-6 are deferred to `content/references/activation-detail.md` as a deliberate forcing-read exception - the breadcrumb above ensures every active session reads them.)*

7. **When no-opping, print one line and stop:** *(Steps 5-6 deferred above)*

**Skill/command references:** Every file in `content/commands/` begins with a one-line reminder to run this preflight and no-op if inactive. The check is performed once per session - subsequent `/`-commands in the same session can trust the earlier result.
