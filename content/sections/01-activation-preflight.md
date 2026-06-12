## Activation preflight

Run this check once at the top of the first skill invocation in a session (and at the top of every `/`-command in `content/commands/`). It is fast, silent when active, and governs whether the methodology runs at all in the current project. Keep it to three file reads with no subagent spawn and no LLM reasoning. **Exception:** Step 6 (Scaffolding-sync check) is the single authorized side-effecting exception to this invariant. It calls `bin/agentic-migrate` as a bounded shell-out; the binary is methodology-owned, failure is swallowed, and it never blocks activation.

1. **Read the global mode, profile, and preset.** Load `~/.claude/agentic-engineering.json`. If missing or unreadable, assume `mode=opt-out`, `profile=default`, and `preset=null` (back-compat). Expected shape: `{ "mode": "opt-out" | "opt-in", "profile": "relaxed" | "default" | "strict", "preset": "lean" | "standard" | "strict" | null, "set_at": "<ISO8601>" }`. Any `mode` value other than `opt-in` is treated as `opt-out`. Any `profile` value other than `relaxed` or `strict` is treated as `default`. The `preset` field is optional; when present and non-null, it RESOLVES to a profile via the preset table below and overrides the direct `profile` field. When `preset` is null or missing, the direct `profile` field is used (back-compat).

   Also read the **effective identity** for this session. Check `<cwd>/.agentic/identity.yml` first, then fall back to `~/.agentic/identity.yml`. Use the first file that exists, resolving by the 4-tier confirmation ordering: project-confirmed > global-confirmed > project-provisional > global-provisional > none. In practice this is a two-file read: if the project file exists and is confirmed (no `provisional: true`), use it. If the project file is provisional, also read the global file; if the global is confirmed, prefer the global. Otherwise use the project file. Record `developer_id` and `provisional` from whichever file wins. Absent file or absent `provisional` field = confirmed identity (Python `.get('provisional', False)`; JS `provisional === true`). **This is a read-only field parse - no prompt, no shell-out, no LLM reasoning. The "fast, silent" preflight invariant is preserved.** When `provisional: true` is recorded on the effective identity, the conductor surfaces a non-blocking confirmation notice at its first user-facing turn (see §Session Context and Memory in `content/rules/conventions.md`).

   **Preset table (session-wide risk profile preset):**

   | Preset    | Resolves to profile |
   |-----------|---------------------|
   | lean      | relaxed             |
   | standard  | default             |
   | strict    | strict              |

   Note: this session-wide `preset` field is distinct from the per-spawn `Preset:` declaration introduced in the Tier declaration section below. The session-wide preset is a tone setting; the per-spawn preset is a capability bundle. Both terms use "preset" intentionally - context disambiguates.
2. **Read the project marker.** Look for a root `AGENTS.md` in the current working directory. If the project uses the Claude Code `@AGENTS.md` import pattern, `CLAUDE.md` will point at it - resolve through to the actual `AGENTS.md`. If neither file exists, treat marker as `none`.
3. **Scan for marker lines.** Case-insensitive, whole-line match (allow leading or trailing whitespace, and an optional markdown list prefix `- `):
   - `agentic-engineering: opt-in`
   - `agentic-engineering: opt-out`
   If both appear, the one that appears FIRST wins; print a one-line warning: `agentic-engineering: both opt-in and opt-out markers found in AGENTS.md - using the first one (<value>). Remove the duplicate.`
   Also scan for `agentic-engineering-profile: <value>`. If present, it overrides the global profile. Valid values: `relaxed`, `default`, `strict`. Any other value falls back to the global profile.
   Also scan for `agentic-engineering-preset: <value>`. If present, it overrides the resolved global preset for this project. Valid values: `lean`, `standard`, `strict`. The project preset is resolved through the same preset table (above) to a profile; that resolved profile overrides any direct `agentic-engineering-profile:` line in the same file (preset wins on collision because it is the higher-level knob). Any other value falls back to the global preset/profile resolution.
4. **Activation decision.**
   - `mode=opt-out` AND `marker=opt-out` - skill no-ops silently; fall back to default Claude Code behavior for this session.
   - `mode=opt-in` AND `marker != opt-in` - skill no-ops silently; fall back to default behavior.
   - Any other combination (including `marker=none` with `mode=opt-out`, or `marker=opt-in` with `mode=opt-in`) - proceed with the methodology.
5. **First-activation notice (one-time, per-project, TTY-only).** Triggered only when Step 4 resolved to active (any proceed branch). Otherwise skip this step entirely.

   **TTY/QUIET gate.** If `os.environ.get("AGENTIC_QUIET") == "1"` OR `not sys.stdout.isatty()`, skip BOTH the notice print AND the sentinel write. Activation proceeds normally without producing the notice or creating the sentinel. This prevents fixture contamination in eval harness runs and unwanted output in CI/headless contexts.

   **Sentinel write contract (race-safe; create-only).** Two parallel subagent activations on the same fresh project must produce exactly one notice and exactly one sentinel; the loser stays silent. The notice prints if and only if the create-only write succeeded.

   1. Compute path: `<project_root>/.agentic/.activated`.
   2. Ensure `.agentic/` exists (`mkdir -p`); failures silently swallowed - do not crash.
   3. Attempt **create-only** write (must fail if the file already exists):
      - Python: `open(path, 'x')` (raises `FileExistsError` if present).
      - Shell: write to `<path>.tmp.<pid>`, then `ln <tmp> <path>` (atomic, fails on EEXIST), unlink tmp.
      - <!-- Race-safe pattern: O_EXCL / link() guarantees that only one of N concurrent racers wins the create; losers see EEXIST and stay silent. Do NOT replace with `if exists: ... else: write` - that pattern has a TOCTOU race. -->
   4. **Print the notice if and only if the create succeeded.** On EEXIST (sentinel already present), skip the print silently. Losers in a race stay silent.
   5. Filesystem errors other than `EEXIST` (read-only filesystem, permission denied, ENOSPC, etc.) are silently swallowed; the notice may re-print on the next session. Methodology must not crash.

   **Sentinel body (exactly three lines, plain text):**
   ```
   # agentic-engineering: first-activation notice has been shown for this project.
   # Deleting this file re-arms the notice only; it does not change activation state.
   # To opt out, use /agentic-disable.
   ```

   **Notice text (verbatim, single line, printed to stdout when create succeeds):**
   ```
   agentic-engineering: active (mode=<mode>, marker=<marker or 'none'>, profile=<profile>, preset=<preset or 'none'>). Run /agentic-status to inspect, /agentic-disable to opt out.
   ```
   Values come from the resolver outputs of Steps 1-3. The literal JSON `null` for `preset` is rendered as the string `none`.

6. **Scaffolding-sync check.** Runs only when Step 4 resolved to active. Silent-fail: any error swallowed; methodology proceeds.

   a. Invoke `agentic-migrate check` (resolved from PATH or adapter install bin/). If binary not found: skip silently.
   b. If status is "ok" (project version >= manifest version): no-op.
   c. If status is "drift": invoke `agentic-migrate apply`. The binary acquires `~/.agentic/.scaffolding-apply.lock` (on EWOULDBLOCK: another session is applying - skip silently). It applies additive gitignore patterns (exact-line match, strip trailing whitespace), writes missing `.agentic/` seed files (never overwrites existing), updates `scaffolding_version` in `.agentic/config.json` when all additive rules satisfied, and appends one-line audit to `.agentic/context.md`. The `markers:` key in the manifest is IGNORED by this path (operator-owned; surface via `/migrate-project --include-destructive` only).
   d. AGENTS.md is never modified by this step. Operator-owned scaffolding requires `/migrate-project --include-destructive`.

7. **When no-opping, print one line and stop:**
   `agentic-engineering: inactive in this project (mode=<mode>, marker=<marker or 'none'>). Add 'agentic-engineering: opt-in' to AGENTS.md to activate.`
   Do not load rules. Do not spawn. Do not print anything else from this skill in this session.

**Graceful defaults:** missing `~/.claude/agentic-engineering.json`, missing `AGENTS.md`/`CLAUDE.md`, malformed JSON, and permission errors all resolve to "mode=opt-out, marker=none, profile=default, preset=null" -> proceed with methodology active. This preserves behavior for users who installed before this feature existed.

**Skill/command references:** Every file in `content/commands/` begins with a one-line reminder to run this preflight and no-op if inactive. The check is performed once per session - subsequent `/`-commands in the same session can trust the earlier result.
