# /init-project

> Run the Activation preflight from `agent-methodology.md` before proceeding. If inactive, no-op and exit.
>
> Additional activation behavior for this command: see Step 0 "Global activation mode" below.

Scaffold a new project with the standard AGENTS.md hierarchy, CLI tool config, and gitignore.

<!-- Risk-tier note: this command performs discovery, confirmation, and scaffolding only. It does not emit or classify risk-tier vocabulary (Trivial, Low, Elevated). No Trivial-tier addition is needed here. -->


## Steps

### 0. Run discovery

**0a. Global activation mode** — read this before any other discovery work.

Read `~/.claude/agentic-engineering.json`. Expected shape: `{ "mode": "opt-out" | "opt-in", "profile": "relaxed" | "default" | "strict", "set_at": "<ISO8601>" }`. If missing or unreadable, assume `mode=opt-out` and `profile=default`.

- **If `mode=opt-in`**: prompt the user before doing any scaffolding:

  > "agentic-engineering is installed in opt-in mode. Activate it for this project? [Y/n]"

  Accept `y` / `yes` / `1` / empty (Enter) as **yes**. Accept `n` / `no` / `2` as **no**.

  - On **yes**: ensure the `AGENTS.md` scaffolded below contains an `agentic-engineering: opt-in` marker. If the template already has an `## Activation` section, use it. Otherwise add one line near the top of `AGENTS.md`:

    ```markdown
    ## Activation
    agentic-engineering: opt-in
    ```

  - After the activation marker, optionally add `agentic-engineering-profile: <relaxed|default|strict>`. Only add this if the user explicitly requests a profile during Step 1 or if a global profile is set in `~/.claude/agentic-engineering.json`. If the user does not mention a profile, do not add the marker (the global default will apply).

  - On **no**: stop `/init-project` here. Print: "Skipped - no scaffolding written. Rerun `/init-project` to activate later, or set `--mode=opt-out` via a reinstall." Exit.

- **If `mode=opt-out`** (default): proceed as today. Do NOT prompt. Mention in the Step 12 summary: "This project will use agentic-engineering by default. Add `agentic-engineering: opt-out` to `AGENTS.md` to disable it in this project."

- **If the config file is missing or malformed**: treat as `mode=opt-out` and proceed without prompting (back-compat with pre-feature installs).

This step runs before Step 0 discovery below because an opt-in decline should short-circuit the entire command.

**0b. Project discovery** — once activation is resolved, silently scan the project to derive as many configuration values as possible.

**Project name** — check in order: `package.json` `.name` (strip leading `@scope/`); `pyproject.toml` `[project] name`; `Cargo.toml` `[package] name`; `go.mod` module path last segment; `build.gradle`/`settings.gradle` `rootProject.name`; git remote origin URL last path segment (strip `.git`); current directory basename. First match wins. Steps 1–5 = high confidence; steps 6–7 = low confidence (annotate as "(inferred)").

**Description** — check in order: `package.json` `.description`; `pyproject.toml` `[project] description`; first non-title, non-badge paragraph of `README.md`. First match wins.

**Tracks** — two passes: (1) check for `apps/`, `packages/`, `services/`, `libs/` at repo root; a subdirectory under these is a track if it contains its own `package.json`, `pyproject.toml`, `go.mod`, or `Cargo.toml`; (2) scan top-level subdirectories (excluding `.git`, `.claude`, `node_modules`, `dist`, `build`, `.next`, `coverage`, `__pycache__`, `.venv`, `venv`) for their own manifest file. Deduplicate. 0 candidates = no signal (omit). 1 candidate = low confidence (annotate). 2+ candidates = high confidence.

**Database CLI** — scan `package.json` deps, `requirements.txt`/`pyproject.toml` deps, `Cargo.toml`, `go.mod`. Match in order: `@prisma/client` or `schema.prisma` → recommend `prisma`; `pg`/`pg-promise`/`psycopg2`/`psycopg`/`asyncpg` → recommend `psql`; `mongoose`/`mongodb`/`pymongo`/`motor` → recommend `mongosh`; `mysql2`/`pymysql`/`aiomysql` → recommend `mysql`; `better-sqlite3`/`sqlite3`/`aiosqlite` → recommend `sqlite3`. No match = no signal (omit). Multiple database matches = list both and ask user to confirm in the confirmation step.

**Web UI** — scan `package.json` deps and scripts. Match in order: `next` dep + `dev` script → Next.js (default port 3000); `@remix-run/react` or `@remix-run/node` → Remix (port 3000); `react-scripts` → CRA (port 3000); `vite` dep + `dev` script (check `vite.config.ts`/`vite.config.js` for `server.port`; default 5173) → Vite; `@vue/cli-service` → Vue CLI (port 8080); `svelte` + `vite` → SvelteKit (port 5173); `astro` → Astro (port 4321). Package manager: prefer `pnpm` if `pnpm-lock.yaml` exists, `yarn` if `yarn.lock`, `bun` if `bun.lock`/`bun.lockb`, else `npm`. No match = no signal (omit). Compose dev command as `[package-manager] run dev` (or `[pm] dev` for bun).

**Tracker** — check in order: (1) if `## Tracker` or `## Linear` already exists in `AGENTS.md` → tracker is already configured, stop tracker detection, annotate as "(already configured)"; (2) check `~/.claude.json` `mcpServers` for keys `linear` or `mcp-atlassian`; (3) scan `git log --oneline -50` for ticket patterns `[A-Z][A-Z0-9]{1,9}-\d+` — if a prefix appears 3+ times, flag as a signal; (4) check for `.linear/` directory. Signals: Linear MCP entry or `.linear/` dir = Linear signal; `mcp-atlassian` entry = Jira signal; commit patterns alone = low confidence. No signals = no prompt (leave tracker unconfigured).

**GitHub CLI** — run `which gh`. If present, treat as a high-confidence signal and include the `gh` line in `## Tools` automatically. If absent, omit.

**Release signals** — scan for any of: `release` or `deploy` scripts in `package.json`; `CHANGELOG.md` at repo root; `vercel.json`; `Dockerfile`; `.github/workflows/` files matching `release*.yml` or `deploy*.yml`; `fly.toml`; `railway.toml`. If any are found, note as a release signal and record the detected type (e.g. "vercel.json", "GitHub Actions release workflow", "Dockerfile"). No match = no signal (omit from Step 1).

**Benchmark signals** — scan for: `bench` or `benchmark` or `profile` scripts in `package.json`; a `benches/` or `benchmarks/` directory at repo root; `k6` config files; `vitest bench` invocations in scripts; `pytest-benchmark` in `requirements.txt`/`pyproject.toml`. If any are found, note as a perf signal and record the detected type (e.g. "vitest bench scripts in package.json", "benchmarks/ directory"). No match = no signal (omit from Step 1).

**Dep-audit command** — derived from the package manager already detected in the Web UI pass. Map: `pnpm-lock.yaml` → `pnpm audit`; `yarn.lock` → `yarn audit`; `package-lock.json` or npm detected → `npm audit`; `requirements.txt`/`pyproject.toml` (poetry or pip) → `pip-audit`; `Cargo.lock` → `cargo audit`; `go.sum` → `govulncheck`. No lockfile detected = no signal (omit). This is a pure derivation from existing package manager detection — no extra scan needed.

**Auto-memory directory** - memory lives at `<cwd>/.agentic/memory/`. This is project-local (not under the sensitive `.claude/` path) and not platform-hashed. `/init-project` writes this path as `autoMemoryDirectory` in Step 7. Note: `autoMemoryDirectory` is **ignored** if set in the checked-in `.claude/settings.json` for security - it must be written to `.claude/settings.local.json` (the gitignored user-local file). Only Claude Code honors this setting; Codex/Cursor/Gemini adapters do not consume it.

### 1. Present discovery results

Present the results of Step 0 in a single message:

```
Discovery complete. Here's what I found:

  Project name:  [value]         ([source, e.g. "from package.json"])
  Description:   [value]         ([source])
  Tracks:        [list]          ([e.g. "detected as monorepo — apps/"])
  Database CLI:  [value]         ([e.g. "detected @prisma/client"])
  Web UI:        [command, port] ([e.g. "detected Next.js"])
  GitHub CLI:    gh               (detected on PATH)
  Tracker:       [value]         ([e.g. "from AGENTS.md ## Linear" or "detected in ~/.claude.json"])
  Release:       [detected type]  ([e.g. "vercel.json", "GitHub Actions release workflow"])
  Benchmarks:    [detected type]  ([e.g. "vitest bench scripts in package.json"])
  Dep audit:     [command]        ([e.g. "npm audit", derived from package manager])
  Auto-memory:   [selected path]  ([e.g. "selected from 3 existing dirs - most recent" or "greenfield - new dir will be created"])

Fields not shown were not detected and are optional — you can add them now or later.

Press Enter to accept all, or tell me what to change (e.g. "project name is widgetco", "no web UI", "no gh", "use Jira").
```

Show only fields where a value was found. Omit fields with no detection. Annotate low-confidence values with "(inferred — verify)".

**Override grammar** — the user may correct any field in free-form. Recognized patterns:
- "project name is X" → override project name
- "description is X" → override description
- "tracks are X, Y" / "add track Z" / "remove track Z" → update track list
- "database is X" / "use X for database" → override database CLI
- "no web UI" / "skip web UI" → clear web UI
- "no gh" / "skip gh" → remove gh from Tools
- "use Linear" / "set up Linear" / "use Jira" / "set up Jira" / "no tracker" → set tracker
- "port is N" → override detected port
- "no release" / "skip release" → clear release signal (suppresses `.agentic/deploy.md` creation)
- "no benchmarks" / "skip benchmarks" → clear benchmark signal
- "no dep audit" / "skip dep audit" → clear dep-audit derivation
- "no auto-memory" / "skip auto-memory pin" → clear autoMemoryDirectory signal (suppresses the Step 7 write and the Step 2a idempotent update)

### Principle: Negative answers are sticky

**Negative answers are sticky.** Whenever the user declines a feature in Step 1 - any "no X" / "skip X" override above, or any `n` / `no` / `neither` / `none` / `skip` answer (or empty Enter) to a y/N prompt below - record this as an explicit decline for that feature in the in-memory state. A declined feature must suppress ALL downstream prompts and actions about that feature in Steps 2a, 6, 6a, 7, 10, 11, and the final summary reminders in Step 12. Never re-prompt for something the user already declined. The only permissible follow-up after a decline is a single contradiction-resolution prompt when existing on-disk state conflicts with the decline (see Step 2a, Legacy `## Linear` migration).

Declinable features enumerated (each must be honored in every downstream step): project name (not declinable — required), description, tracks, database CLI, web UI, `gh`, tracker (Linear / Jira / neither), release, benchmarks, dep audit, **auto-memory pin** (new — declined via "no auto-memory" / "skip auto-memory pin"; suppresses Step 2a item 9, Step 7's `autoMemoryDirectory` write, and Step 12 reminder 12).

When adding a new declinable feature to Step 1, extend the override grammar above AND wire the decline signal through every downstream step that prompts about or acts on that feature.

Corrections patch in-memory state; they do not re-run discovery. After corrections, echo only the changed lines: "Updated: [field] → [value]. Anything else, or press Enter to continue."

**Exit conditions:** empty input (Enter), "done", or "accept" → proceed with current state.

**If tracker signals were found** but tracker is not already configured, prompt before the confirmation block ends. Accept numeric shortcuts in addition to named answers so the user can answer any tracker prompt with a digit.

- **Linear only** → "Set up Linear tracker? [y/N]"
  - Accept as **yes**: `y`, `yes`, `1`
  - Accept as **no**: `n`, `no`, `2`, empty (Enter)
- **Jira only** → "Set up Jira tracker? [y/N]"
  - Accept as **yes**: `y`, `yes`, `1`
  - Accept as **no**: `n`, `no`, `2`, empty (Enter)
- **Both detected** → present a numbered list:

  ```
  I detected signals for both Linear and Jira. Which tracker does this project use?
    1. Linear
    2. Jira
    3. Neither (skip tracker setup)

  Answer with a number, name, or "neither" / "none" / "skip".
  ```

  Accept:
  - **Linear**: `1`, `linear`
  - **Jira**: `2`, `jira`
  - **Neither / skip**: `3`, `neither`, `none`, `skip`, `n`, `no`, empty (Enter)

Wait for tracker confirmation before proceeding. A "no" / "neither" / "skip" / empty answer to any of the above prompts records tracker = **declined** in the in-memory state (per the "Negative answers are sticky" principle). Declined tracker suppresses Step 2a Linear migration prompts, Step 11 tracker setup, and the Step 12 Linear QA assignee reminder.

**Required fields** — project name is required. If it was not discovered and the user does not provide it in the override step, ask once more: "A project name is required. What should I call this project?" If still not provided, stop and ask the user to re-run `/init-project` with a name ready.

### 2. File scan and mode detection

**Idempotent mode trigger** — if `AGENTS.md` already exists and contains any of the standard sections (`## Tools`, `## Docs`, `## Conventions`, `## Linear`, or `## Tracker`), this is an **update run**, not a greenfield run. Switch to the update mode algorithm (Step 2a) instead of the normal create flow.

**Greenfield mode** — if `AGENTS.md` does not exist, or exists but contains none of the standard sections, proceed with the normal create flow (Steps 3 onward).

Before writing any files, check which files already exist. The full set of files this command would create:

- `AGENTS.md` (root) - the canonical project-instructions file, read by Claude Code, Codex, Cursor, and other tools. Claude Code reads it via a one-line `CLAUDE.md` containing `@AGENTS.md`.
- `[track]/AGENTS.md` for each track the user named (omit if no tracks were named)
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.agentic/qa.md` (only if web UI confirmed in Step 1)
- `.agentic/deploy.md` (only if release signals detected in Step 0)
- `.agentic/tracking.md` (only if a tracker was confirmed in Step 1)
- `.agentic/preferences.json` - tool-agnostic, gitignored session-agent preferences file; always created empty (`{}`) so the session-start scaffolding check has a place to persist "never prompt again"
- `memory/MEMORY.md` (created at `<cwd>/.agentic/memory/MEMORY.md` by Claude Code - `/init-project` seeds it with a stub)
- `.gitignore`
- `docs/overview/.gitkeep`, `docs/technical/.gitkeep`, `docs/planning/.gitkeep`, `docs/research/.gitkeep`

**Report findings in two groups:**

```
Missing (will be created):
  - AGENTS.md
  - backend/AGENTS.md
  - ...

Already exists (will be left untouched or curated in place):
  - .claude/settings.json
  - .gitignore
  - ...
```

**Handle each file as follows - no user prompts, proceed automatically:**

**`.claude/settings.local.json` - always skip silently if it exists.** Do not ask. Do not overwrite. **Exception:** if the file exists but lacks the `autoMemoryDirectory` key, Step 2a item 9 will perform a narrow idempotent merge to add that single field without touching any other keys. See Step 2a item 9. Remind the user: "`.claude/settings.local.json` already exists and was left untouched - it may contain real secrets. Add any new env keys manually."

**`AGENTS.md` (root) - if it exists, curate in place.** Do not skip. Do not overwrite wholesale. Read it and reorganize it to conform to the target structure (under 45 lines). See Step 3 for the curation process.

**All other existing files - leave untouched.** Note them in the scan output. Do not ask. Do not overwrite.

**`.gitignore` safety check** - regardless of whether `.gitignore` is new or existing: check whether it already contains `.claude/settings.local.json`. If not, append the following two lines:

```
# Claude Code - local settings contain secrets
.claude/settings.local.json
```

This check is unconditional - run it whether `.gitignore` was just created or was already present.

### 2a. Update mode algorithm

This step runs only when Step 2 detects an existing configured `AGENTS.md` (update run).

**Compute the diff** — compare current `AGENTS.md` and adjacent files against what Step 1 discovery + confirmation implies:

0. **Pre-AGENTS.md migration (CLAUDE.md only)** — runs BEFORE item 1 below. Detect pre-AGENTS.md layout via both:
   - Root `AGENTS.md` is absent, AND
   - Root `CLAUDE.md` exists and contains more than the single-line pointer `@AGENTS.md` (i.e. has real content — prose, sections, or instructions beyond the pointer).

   If detected, run a Worker+Skeptic split before Step 2a's other items. If NOT detected (both `AGENTS.md` and a non-pointer `CLAUDE.md` exist, or `CLAUDE.md` is already just `@AGENTS.md`, or neither exists), skip item 0 entirely and proceed to item 1.

   **Main agent pre-work (inline, before spawning Worker):** read the existing root `CLAUDE.md` and classify its content into three buckets:
   - **agentic** — content that belongs in the scaffolded `AGENTS.md`: project description, `## Decisions`, repo structure map, `## Tools`, `## Docs`, `## Conventions`, `## Session start`, tracker metadata. This is agentic-engineering's canonical project-instructions surface.
   - **project-specific-keep** — content the user may want to keep in a Claude-Code-specific file: user-authored prose addressed specifically to Claude Code ("Claude, when you see X, do Y"), Claude Code MCP conventions, or any explicit Claude-only guidance. Residual `CLAUDE.md` content after the split.
   - **stable-facts** — content that reads as "what we learned" or "here is how it works" (detailed rationale paragraphs, implementation details, setup command sequences, decision alternatives considered, dated observations). Destined for `MEMORY.md` per the `- **YYYY-MM-DD:** [what and why]` format described in Step 3.

   **Spawn Worker** (labeled "CLAUDE.md split Worker") with:
   - The raw existing root `CLAUDE.md` content.
   - The three-bucket classification above, with the main agent's pre-classification notes.
   - The target `AGENTS.md` structure (from Step 3 template).
   - Instruction to produce three artifacts:
     1. **Proposed `AGENTS.md`** — the agentic-engineering canonical file, conforming to the Step 3 structure, populated from the agentic bucket.
     2. **Residual `CLAUDE.md`** — contains only the project-specific-keep bucket. If this bucket is empty after the split, the Worker must return `CLAUDE.md: empty` so the conductor can replace the file with the single-line `@AGENTS.md` pointer.
     3. **`MEMORY.md` additions** — stable-facts bucket formatted as `- **YYYY-MM-DD:** [what and why, one-two sentences]` entries using today's date.

   **Spawn Skeptic** (fresh, background) with the Worker's three artifacts and this adversarial brief verbatim:

   > "Does the split preserve every fact and instruction from the original CLAUDE.md? For each bucket: is any agentic content still sitting in the residual CLAUDE.md that should have moved to AGENTS.md? Is any project-specific Claude-only instruction incorrectly promoted to the tool-agnostic AGENTS.md where Codex/Cursor/Gemini will also read it? Are the MEMORY.md additions stable facts (rationale, dated observations) rather than temporary task state? Is the proposed AGENTS.md under 45 lines and does it have all required sections (H1, overview paragraph, Decisions, Tools, Docs, Conventions, Session start)? Did any implementation detail or rationale paragraph remain in AGENTS.md that belongs in MEMORY.md instead? Is the residual CLAUDE.md genuinely Claude-Code-specific, or is it agentic content that was dropped into the wrong bucket?"

   Require the standard sign-off format: `Reviewed: ... Findings: ... Active search: ... No unresolved Critical or Major findings. Sign-off granted.`

   **PRESENT the three-way split to the user BEFORE applying** (diff-style preview):

   ```
   Pre-AGENTS.md migration detected. Proposed split of root CLAUDE.md:

   ─── Proposed AGENTS.md (NEW) ───────────────────────────────
   [Worker's proposed AGENTS.md content]

   ─── Residual CLAUDE.md (AFTER) ─────────────────────────────
   [Worker's residual CLAUDE.md content, OR "(empty — will be replaced with single-line `@AGENTS.md` pointer)"]

   ─── MEMORY.md additions (APPEND) ───────────────────────────
   [Worker's MEMORY.md entries]

   Accept this split? [y/N/edit]
   ```

   Accept:
   - `y` / `yes` / `1`: apply the split. Write the proposed `AGENTS.md`. Write the residual `CLAUDE.md`; if the residual is empty, replace `CLAUDE.md` with the single-line pointer `@AGENTS.md` instead. Append the MEMORY.md entries per Step 3's semantic-dedup merge rule. **Enter alone does NOT apply** - this is a destructive three-way write; require an explicit `y`.
   - `n` / `no` / `2` / empty (Enter): abort the pre-AGENTS.md migration for this run. Do NOT proceed to items 1+ of Step 2a (which assume AGENTS.md exists) — instead, print: "Pre-AGENTS.md migration declined. Existing CLAUDE.md left untouched. /init-project cannot continue in update mode without a canonical AGENTS.md. Re-run /init-project later, or run the greenfield creation flow manually." and exit the command.
   - `edit` / `e`: prompt for a free-form correction nudge ("What should change? One or two sentences."), then re-spawn the Worker with the original CLAUDE.md plus the user's nudge, re-spawn a fresh Skeptic, and present the revised three-way split. **Iteration cap: 3.** After 3 `edit` iterations, fall back to: "Three edit iterations reached. The split still needs manual review. Aborting /init-project; edit CLAUDE.md and AGENTS.md manually, then re-run /init-project." and exit.

   After a `y`-accepted split completes, proceed to item 1 below. The downstream items now operate against the newly-written `AGENTS.md`.

1. **Legacy `## Linear` migration** — if `## Linear` exists but is missing `Workspace:` or `QA assignee ID:` fields:
   - **First, check Step 1 tracker state.** If the user declined tracker in Step 1 (`no tracker` / "neither" / "skip" / Enter on the tracker prompt), do NOT prompt for Linear workspace slug, QA assignee UUID, or any other Linear field. Instead, ask ONCE - framed as contradiction resolution, not as a follow-up about whether to set up Linear:

     > "I see a `## Linear` section in AGENTS.md but you declined tracker setup in Step 1. Remove the `## Linear` section? [y/N]"

     Accept `y` / `yes` / `1` as yes (plan removal of `## Linear`). Accept `n` / `no` / `2` / empty as no (leave `## Linear` as-is; do not migrate, do not prompt for any field). Either way, do not ask anything else about Linear in this run.
   - **Otherwise** (user accepted or confirmed Linear, or tracker is unspecified and there was no Step 1 decline):
     - Attempt to derive `Workspace`: scan git remote origin URL and last 50 commit messages for `linear.app/<slug>/` URL patterns. Use the slug if found.
     - Attempt to derive `QA assignee ID`: check for any UUID-shaped value already in the section.
     - Prompt only for values that could not be derived: "What is your Linear workspace slug?" and/or "What is the Linear QA assignee UUID? (optional — press Enter to skip)".
     - Rewrite `## Linear` in place using the new canonical shape (see Step 11a for shape). Preserve `Projects:` if present. Preserve the old `Default assignee:` name as a comment line if it existed and differs from any new UUID.

2. **Tracker mutual exclusion** — Linear and Jira are mutually exclusive:
   - If user confirmed Jira during Step 1 and `## Linear` exists: plan to remove `## Linear` and write `## Tracker` (Jira shape).
   - If user confirmed Linear and `## Tracker` (Jira) exists: plan to remove `## Tracker` and write `## Linear` (Linear shape).
   - If the user **declined** tracker in Step 1 and either `## Linear` or `## Tracker` exists: handle the same way as the legacy migration in case 1 above — ask ONCE as a contradiction-resolution prompt ("I see `## [Linear|Tracker]` in AGENTS.md but you declined tracker setup in Step 1. Remove the section? [y/N]"). If yes, plan removal. If no, leave the section untouched. Do not prompt for any tracker field.
   - If no tracker change: leave existing section untouched.

3. **`## Tools` backfill** — for each new CLI tool discovered in Step 0 that is not already present in `## Tools`: plan to append it. Never touch existing entries. Match on CLI name (e.g. `psql`, `mongosh`, `gh`). If a dep-audit command was derived in Step 0 and no dep-audit entry exists in `## Tools`: plan to append it (e.g. `- Dependency audit: use \`npm audit --json\` for vulnerability scans`). **Honor Step 1 declines in backfill:** if the user declined `gh` (`no gh` / `skip gh`), do not append a `gh` entry even if `gh` was detected on PATH. If the user declined dep audit (`no dep audit` / `skip dep audit`), do not append a dep-audit entry even if a command was derived.

4. **Missing sections** — if `## Docs` or `## Conventions` is absent: plan to add them (same content as greenfield template).

5. **`docs/` directories** — plan to create any missing subdirectories.

6. **`.agentic/qa.md`** — if web UI was confirmed **and the user did not decline web UI in Step 1** (`no web UI` / `skip web UI`) and file does not exist (checked via resolver: `.agentic/qa.md` OR legacy `.claude/qa.md`): plan to create it at `.agentic/qa.md`. If the user declined web UI, do not create the file and do not prompt for port or command.

7. **`.agentic/deploy.md`** — if release signals were detected **and the user did not decline release in Step 1** (`no release` / `skip release`) and file does not exist (checked via resolver: `.agentic/deploy.md` OR legacy `.claude/deploy.md`): plan to create it at `.agentic/deploy.md` using the same template as Step 6a. If the user declined release, do not create the file and do not prompt for deploy command or rollback procedure.

9. **Auto-memory directory** — if the user declined auto-memory in Step 1 (`no auto-memory` / `skip auto-memory pin`): skip entirely. If `.claude/settings.local.json` already has `autoMemoryDirectory` set (to any value): leave it alone (idempotent — user's existing preference wins, even if it differs from the Step 0 selection). If the file exists but lacks the `autoMemoryDirectory` key: plan to merge it in using the selected path from Step 0 (do not overwrite other keys in the file). If the file does not exist: Step 7 handles creation with the key present. If auto-memory was declined but the key is already set on disk: leave it (do not remove — user's existing preference wins).

10. **`.agentic/preferences.json`** — if the file does not exist: plan to create it with `{}` as content.

11. **Legacy path migration (`.claude/<name>.md` → `.agentic/<name>.md`)** — for each of `qa.md`, `deploy.md`, `findings.md`, `tracking.md`:
    - **Both paths exist** (e.g. `.claude/findings.md` AND `.agentic/findings.md` both on disk): refuse to migrate. Emit a **Major warning** in the diff preview block listing each conflicting pair: `WARNING (Major): both .claude/<name>.md and .agentic/<name>.md exist for <name>. Cannot decide which is canonical. Resolve manually (remove or merge one) before re-running /init-project.` Do NOT proceed to apply any changes — block the "Proceed? [y/N]" confirmation until the conflict is resolved.
    - **Only legacy `.claude/<name>.md` exists**: plan to migrate via `git mv .claude/<name>.md .agentic/<name>.md`. Before planning the `git mv`, run `git status --porcelain` to verify the working tree is clean of staged or unstaged changes. If dirty, block with: `Cannot migrate legacy .claude/ config while the working tree is dirty. Commit or stash first, then re-run /init-project.` Do NOT stash or commit on behalf of the user.
    - **Only `.agentic/<name>.md` exists** (the normal post-migration state): no action needed.
    - **Neither exists**: no action for this step (creation of the file, if applicable, is handled by items 6-8 above).
    **Per-track coverage:** apply the same four rules to every per-track path (`<track>/.claude/qa.md` and `<track>/.claude/deploy.md`) for every track detected in Step 0. A project may have a mix of migrated and legacy per-track paths; each is evaluated independently.
    List each planned `git mv` in the diff preview under a `Legacy migration:` heading so the user sees the moves before confirming.

**Present the diff:**

```
Here's what I'd update:

  AGENTS.md:
    - Migrate ## Linear to new shape (Workspace: [value], QA assignee ID: [value or "not set"])
    - Append to ## Tools: [new entry]

  .agentic/qa.md:
    - Create (not found, web UI detected as [framework] on port [N])

  .agentic/deploy.md:
    - Create (not found, release signal detected: [type])

  docs/research/:
    - Create .gitkeep (directory missing)

No changes needed for: .gitignore, .claude/settings.json, [track] AGENTS.md files.

Proceed? [y/N]
```

On "y": apply all planned changes. On "n" or Enter: abort with "Update cancelled. No files were modified."

**Never destroy existing content.** All changes are additive or migrate-in-place. The `## Decisions` and `## Conventions` content in `AGENTS.md` is never overwritten — sections are only added if absent.

After applying changes, skip to Step 12 (Summary) — do not re-run Steps 3 through 11.

### 3. Curate or create root `AGENTS.md`

**If `AGENTS.md` does not exist:** create from scratch using the template below. No curation needed - proceed directly. Also create a one-line `CLAUDE.md` at the project root containing `@AGENTS.md` so Claude Code automatically loads the project instructions.

**If `AGENTS.md` exists:** perform intelligent curation with Worker + Skeptic review:

**Main agent pre-work (inline, before spawning Worker):**
Read the existing `AGENTS.md` and identify two groups of content:

- **Memory candidates** - content that belongs in `MEMORY.md`, not `AGENTS.md`: detailed rationale paragraphs, implementation details (code snippets, schema explanations), setup command sequences, decision alternatives considered, anything that reads as "what we learned" or "here is how it works" rather than "we decided X".
- **Architecture content to keep** - content that belongs in `AGENTS.md`: resolved decisions expressed as brief bullets (1 sentence each), cross-cutting conventions, repo structure map, tools and their usage, docs structure.

**Spawn a background Worker** (labeled "AGENTS.md curation Worker") with:
- The raw existing `AGENTS.md` content
- The memory candidates identified above
- The Step 1 answers (project name, description, tracks, tools)
- The target `AGENTS.md` structure below
- Instruction to produce two artifacts: (1) the curated `AGENTS.md` content conforming to the target structure, (2) `MEMORY.md` entries for each memory candidate using format `- **YYYY-MM-DD:** [what and why, one-two sentences]` with today's date

**Target `AGENTS.md` structure (under 45 lines):**
- H1: project name
- One-paragraph description
- `## Decisions` - resolved architecture decisions as brief bullets, no rationale paragraphs
- Repo structure map listing each track with a one-line description (omit if no tracks)
- `## Tools`
- `## Linear` OR `## Tracker` (preserve whichever is present — do not drop during curation)
- `## Docs`
- `## Conventions`
- `## Session start` (tool-agnostic session-agent scaffolding check; see template block below)

**Spawn a fresh Skeptic** after the Worker returns with this adversarial brief:
> "Is the curated AGENTS.md under 45 lines? Does it have all required sections (H1, overview paragraph, Decisions, Tools, Docs, Conventions, Session start)? Did any implementation detail or rationale paragraph remain that belongs in memory.md instead? Are the memory entries stable facts (not temporary task state)? Does the curated AGENTS.md preserve all architecture decisions from the original, just compressed to brief bullets?"

Require sign-off format:
```
Reviewed: [file]
Findings: Critical: N, Major: N, Minor: N - [brief descriptions, or "None"]
Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.
No unresolved Critical or Major findings. Sign-off granted.
```

After sign-off: write the curated `AGENTS.md`, then merge the Worker's memory entries into `MEMORY.md` using semantic dedup - skip any entry already captured, supersede if updated, append if new. Before merging, check whether `MEMORY.md` exists. If it does not exist, create it with the stub header first (same content as Step 7), then merge. This ensures Step 8's guard ("if the file already exists, leave the stub header step") remains correct.

**`AGENTS.md` template (use for new files, and as the structural target for curation):**
- H1: project name
- One-paragraph description. If no description was provided, use `<!-- TODO: Add one-paragraph description -->` as the placeholder.
- `## Decisions` - resolved architecture decisions as brief bullets - fill in as the project takes shape. Use a single TODO bullet placeholder if no decisions are known yet. Label it clearly: "Resolved architecture decisions as brief bullets - fill in as the project takes shape."
- Repo structure map listing each track directory with a one-line description (omit if no tracks were named)
- Note: "Each track directory has its own `AGENTS.md` with deeper context." (omit if no tracks were named)
- `## Tools` section - document the CLI tools confirmed in Step 1:
  ```markdown
  ## Tools
  - GitHub operations: use `gh` CLI - do not use GitHub MCP
  - [Database CLI if applicable, e.g.: Database operations: use `psql` with `$DB_URL`]
  - [Dep audit if applicable - use the command derived in Step 0 from the detected package manager: `npm audit --json` for npm, `pnpm audit --json` for pnpm, `yarn audit --json` for yarn, `pip-audit` for pip/poetry, `cargo audit` for cargo, `govulncheck ./...` for go. Do NOT hardcode `npm audit` for non-npm projects.]
  ```
  Include the `gh` line only if `gh` was detected or confirmed **and not declined** in Step 1 (`no gh` / `skip gh`); include the database line only if a DB CLI was specified; include the dep-audit line only if a dep-audit command was derived in Step 0 **and not declined** in Step 1 (`no dep audit` / `skip dep audit`), and use the exact command derived there.
- `## Docs` section:
  ```markdown
  ## Docs
  - `docs/planning/` - pre-implementation design artifacts
  - `docs/research/` - research notes and reference material
  - `docs/technical/` - implementation specs and architecture
  - `docs/overview/` - high-level summaries and onboarding docs
  ```
  Always include this section.
- `## Conventions` - a single TODO bullet placeholder; filled in as the project evolves.
- `## Session start` section - tool-agnostic instruction for the session agent to verify scaffolding on the first interaction of each new session:
  ```markdown
  ## Session start
  - On the first interaction of a new session, silently check that `/init-project` scaffolding exists. Check each item only if its precondition holds:
    - Root `AGENTS.md` has required sections (`## Tools`, `## Docs`, `## Conventions`, `## Session start`) - always check.
    - `.claude/settings.json` - always check.
    - `docs/{planning,research,technical,overview}/` - always check.
    - Seeded `MEMORY.md` at `<cwd>/.agentic/memory/MEMORY.md` - always check.
    - `.agentic/qa.md` (or legacy `.claude/qa.md`) - only if this project has a web UI.
    - `.agentic/deploy.md` (or legacy `.claude/deploy.md`) - only if release signals apply to this project.
    - `.agentic/tracking.md` (or legacy `.claude/tracking.md`) - only if a tracker was confirmed during `/init-project`.
  - Filesystem existence only - no LLM reasoning pass. Per-track scaffolds (`[track]/AGENTS.md`, `[track]/.agentic/qa.md`, `[track]/.agentic/deploy.md`) are out of scope for this session-start check - do not flag them.
  - Do NOT include `.agentic/preferences.json` or `.claude/settings.local.json` in the "missing" list. Both are gitignored per-developer files; their absence on a fresh checkout is expected and handled elsewhere (Step 6c creates `.agentic/preferences.json`; Step 7 creates `.claude/settings.local.json`).
  - If `.agentic/preferences.json` exists and contains `"skipScaffoldingCheck": true`, skip the check entirely.
  - If anything is missing, prompt the user ONCE per session on one line: `Scaffolding check: missing [list]. Re-run the init-project scaffolding command (/init-project in Claude Code, equivalent command in your tool) to fix? [y/N/never]`. `y` runs it; `N` or Enter defers to the next session; `never` performs a read-modify-write on `.agentic/preferences.json`: read the existing JSON (or `{}` if absent), set `skipScaffoldingCheck: true`, write the merged object back. Do not overwrite other keys.
  ```

Keep it under 45 lines.

If the project shows parallel fan-out signals (3 or more distinct modules or tracks, complex orchestration history in git log, or prior multi-unit plans visible in docs/planning/), add a note in the scaffolded root AGENTS.md under `## Conventions`: "`.agentic/tasks.jsonl` is the task coordination surface for multi-unit orchestration plans."

### 4. Create subdirectory `AGENTS.md` files

If the user provided no tracks (skipped, said "none", or "not yet"), skip this step entirely.

For each track the user named, **only create `[track]/AGENTS.md` if it does not already exist** - never overwrite an existing track `AGENTS.md`. For missing ones, create with:
- H1: `[Project Name] - [Track Name]`
- `## Stack` section with a TODO bullet
- `## Key Conventions` section with a TODO bullet
- A brief note: "Fill this in as the track is built out."

These are intentionally sparse stubs - they grow with the code.

### 5. Create `.claude/settings.json`

Only create if it does not already exist. Content:

```json
{}
```

MCP servers are not added by default - prefer CLI tools (`gh`, `psql`, etc.). Only add MCP blocks if there is a specific reason.

### 6. Create `.agentic/qa.md`

Only create if the user confirmed a web UI in Step 1 AND the user did not decline web UI in Step 1 (`no web UI` / `skip web UI`). Only create if the file does not already exist at either `.agentic/qa.md` (preferred) or the legacy `.claude/qa.md` (back-compat). Writers always write to `.agentic/qa.md`. If web UI was declined, skip this step entirely — do not prompt for port, command, or staging URL.

Fill in `command` and `port` from the Step 1 confirmation results. If discovery populated these values and the user confirmed them, use those values directly. Use `TODO` placeholders only for values that were neither discovered nor provided.

Content template:

```markdown
# QA Config

## Dev server
command: [command from Step 1, or TODO]
port: [port from Step 1, or TODO]

## URLs
local: http://localhost:[port from Step 1, or TODO]
staging: <!-- optional: add staging/preview URL here -->

## Preferences
prefer: local
```

The `qa-engineer` agent reads this file to know how to start the dev server and which URL to test against. Fill in `staging` if the project has a staging environment. Change `prefer` to `staging` to make qa-engineer default to the staging URL when both are available. The agent also appends a `## Knowledge` section over time as it discovers project-specific quirks - do not remove it.

**Multi-track projects.** If two or more tracks have detected web UIs (distinct ports / dev scripts), create a per-track qa.md at `<track>/.agentic/qa.md` for EACH track with its own command/port/URL, AND create a root `.agentic/qa.md` that is an index listing the tracks with pointers. Example root:

```markdown
# QA Config (Multi-track Index)

This project has multiple web UIs. Per-track qa.md files:
- admin/.agentic/qa.md - admin panel (port 4322)
- dashboard/.agentic/qa.md - ops dashboard (port 4321)
- verify/.agentic/qa.md - public verify page (port 4324)

qa-engineer: pick the track based on which one the diff touches.
```

When `qa-engineer` runs, it reads the root first (resolver: `.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). If the root is an index, it picks the track matching the diff's file paths and reads that track's qa.md for command/port/URLs. **Per-track resolver also applies during the back-compat window**: `<track>/.agentic/qa.md` preferred, `<track>/.claude/qa.md` fallback. Step 2a item 11 plans `git mv` for per-track legacy paths on each update run.

### 6a. Create `.agentic/deploy.md`

Only create if release signals were detected in Step 0 AND the user has not suppressed the signal ("no release") AND the file does not already exist at either `.agentic/deploy.md` (preferred) or the legacy `.claude/deploy.md` (back-compat). Writers always write to `.agentic/deploy.md`.

Fill in the `command` from the detected release type where possible. Use `TODO` for values that were not detected or confirmed.

Content template:

```markdown
# Deploy Config

## Environments
production: [detected deploy command, e.g. "vercel --prod --yes", or TODO]
staging: <!-- optional: add staging deploy command -->

## Version scheme
[semver | calver | date-based | TODO]

## Changelog
path: CHANGELOG.md  <!-- or detected path -->

## Rollback
command: [TODO - fill in once known]
notes: <!-- e.g. "Vercel: redeploy previous deployment from dashboard" -->

## Preferences
prefer: production
```

The `release-orchestrator` agent reads this file the same way `qa-engineer` reads `qa.md` — it uses these values as defaults for target environment, deploy command, and rollback procedure. Fill in `staging` if the project has a staging environment. Update `command` once the exact deploy command is confirmed.

**Multi-track projects.** If two or more tracks have distinct deploy targets (e.g. Vercel for one, Railway for another, EAS for mobile), create a per-track deploy.md at `<track>/.agentic/deploy.md` for EACH track that deploys, AND create a root `.agentic/deploy.md` that is an index listing the tracks with pointers. Same index/pointer pattern as qa.md above. `release-orchestrator` follows the same resolution: root first via resolver (`.agentic/` preferred, `.claude/` fallback); if index, pick the track matching the diff. **Per-track resolver also applies during the back-compat window**: `<track>/.agentic/deploy.md` preferred, `<track>/.claude/deploy.md` fallback. Step 2a item 11 plans `git mv` for per-track legacy paths on each update run.

### 6b. Create `.agentic/tracking.md`

Always create when a tracker was confirmed in Step 1 (Linear or Jira). Only create if the file does not already exist at either `.agentic/tracking.md` (preferred) or the legacy `.claude/tracking.md` (back-compat). Writers always write to `.agentic/tracking.md`.

This is the operational ticket-tracking surface used by the `orchestration-planner` agent and any command that routes work against tickets. It is separate from the tracker metadata in `AGENTS.md` (which declares team/workspace/project). `tracking.md` is where active work, sprint notes, ticket-status conventions, and any project-specific ticket-flow instructions live.

Content template (Linear):

```markdown
# Tracking

<!-- Read by orchestration-planner and any command that coordinates work against tickets. -->
<!-- Declared team/workspace/project lives in AGENTS.md ## Linear; this file is for active work flow. -->

## Conventions
- Branch prefix: `[TEAM]-<id>-<description>` (e.g. `FRM-12-fix-login`)
- Ticket lifecycle: Backlog -> Ready -> In Progress -> In Review -> QA -> Done
- QA assignee: see `AGENTS.md ## Linear QA assignee ID`

## Active work
<!-- Rolling list of in-flight tickets (optional). Keep short; sprint-scoped. -->

## Commands
<!-- Project-specific lc (linearctl) invocations or policy overrides. -->
```

Content template (Jira):

```markdown
# Tracking

<!-- Read by orchestration-planner and any command that coordinates work against tickets. -->
<!-- Declared project key / base URL lives in AGENTS.md ## Tracker; this file is for active work flow. -->

## Conventions
- Branch prefix: `[PROJECT]-<id>-<description>` (e.g. `PROJ-42-add-auth`)
- Ticket lifecycle: <state names from your Jira workflow>
- QA transition: see `AGENTS.md ## Tracker JIRA_QA_TRANSITION`

## Active work
<!-- Rolling list of in-flight tickets (optional). -->

## Commands
<!-- Project-specific atlassian-mcp calls or policy overrides. -->
```

Read by the `orchestration-planner` agent at plan time (step 7 of its brief). A missing `tracking.md` is non-fatal - the planner falls back to AGENTS.md's tracker section for basic metadata.

**Track-level tracking.md is rare** - only create if the project genuinely has teams split across tracks with different Linear teams or Jira projects per track. Default is root-only.

### 6c. Create `.agentic/preferences.json`

Always create. No signal required - the session-start scaffolding check declared in the root `AGENTS.md` template needs a tool-agnostic place to persist its "never prompt again" preference. Only create if the file does not already exist.

Seed with an empty object:

```json
{}
```

This is a tool-agnostic, gitignored preferences file read by session agents (the `.agentic/` directory is already gitignored by the block appended in Step 9, so no separate gitignore entry is needed). Currently it holds `skipScaffoldingCheck` (set to `true` when the user answers `never` to the session-start scaffolding prompt). Future session-level preferences may be added to this file.

Because `.agentic/` is gitignored, `.agentic/preferences.json` is per-developer - each developer's "never prompt again" preference is local to their checkout and does not leak to collaborators.

**Write semantics for the `never` answer.** When the session agent writes `skipScaffoldingCheck`, it must read-modify-write: read the existing JSON (or `{}` if absent), set `skipScaffoldingCheck: true`, and write the merged object back. Do not clobber other keys.

### 7. Create `.claude/settings.local.json`

Only create this file if it does not already exist (enforced in Step 2 - skip if it exists).

```json
{
  "autoMemoryDirectory": "<cwd>/.agentic/memory",
  "env": {}
}
```

The path is the project-local `.agentic/memory/` directory (absolute path preferred for portability). Claude Code honors this setting to pin the session's auto-memory directory to a known path regardless of which subdirectory you launch from. **Schema caveat:** `autoMemoryDirectory` is ignored if set in the checked-in `.claude/settings.json` for security - it MUST live in `.claude/settings.local.json` (user-local, gitignored). Only Claude Code consumes this field; Codex/Cursor/Gemini adapters ignore it.

**If the user declined auto-memory in Step 1** (`no auto-memory` / `skip auto-memory pin`): omit the `autoMemoryDirectory` field entirely — write just `{"env": {}}`.

**Merge rule for update mode** (Step 2a): if `.claude/settings.local.json` already exists, merge `autoMemoryDirectory` into it only if the key is not already set. Never overwrite an existing `autoMemoryDirectory` value — the user's existing preference wins. Preserve all other keys in the file (`env`, `LINEAR_API_KEY`, etc.).

Add any project-specific env vars here (e.g. database connection strings, API keys).

### 8. Seed `MEMORY.md`

The project MEMORY.md lives at `<cwd>/.agentic/memory/MEMORY.md` and is auto-injected by Claude Code at startup.

If the file does not already exist, create the memory directory and seed the file:
- Resolve the memory directory path from the Claude Code auto-injected context (look for "You have a persistent auto memory directory at `<cwd>/.agentic/memory/`")
- Create the file at `[memory_dir]/MEMORY.md` with:

```
# Memory

<!-- Stable facts about this project: architecture, key paths, decisions and their rationale. -->
<!-- Use /memory-update to add entries. Update in place - do not accumulate stale entries. -->
<!-- Entry format: - **YYYY-MM-DD:** [what and why, one sentence] -->
```

If the file already exists (e.g. because AGENTS.md curation in Step 3 merged entries into it), leave the stub header step and proceed to Step 9.

### 9. Create `.gitignore`

If `.gitignore` does not exist, create it. Include at minimum:
```
# Claude Code - local settings contain secrets
.claude/settings.local.json

# Dependencies
node_modules/

# Environment files
.env
.env.local
.env*.local

# OS
.DS_Store
```

Add any framework-specific entries if the stack is already known (e.g. `.next/` for Next.js, `dist/` for Vite, `out/` for general builds).

If `.gitignore` already exists, apply the safety check from Step 2 (append `.claude/settings.local.json` if missing) and leave the rest untouched.

Regardless of whether `.gitignore` is new or existing: check whether the targeted `.agentic/` runtime-artifact block below is present. If not, append it. If `.gitignore` does not exist, the entry above creates it - ensure this block is included in the new file's contents.

```
# Agentic engineering runtime artifacts (must not be committed).
# The .agentic/ directory holds BOTH runtime artifacts (runtime-only, gitignored)
# AND tool-agnostic config files (qa.md, deploy.md, tracking.md)
# that ARE checked in. The entries below ignore only the runtime artifacts.
.agentic/loop-state.json
.agentic/hud/
.agentic/tasks.jsonl
.agentic/context.md
.agentic/memory/
.agentic/memory.md
.agentic/wrap.lock/
.agentic/preferences.json
.agentic/compression-state.json
# Tracked (explicitly NOT ignored): .agentic/qa.md, .agentic/deploy.md,
# .agentic/tracking.md - these are tool-agnostic agent config and belong in
# source control.
```

The targeted list covers runtime artifacts only: `loop-state.json` (loop resume state written by `/implement-ticket` Phase 6 and the Stop hook), `hud/` (per-worker HUD files for P1 fan-out observability), `tasks.jsonl` (multi-unit task coordination), `context.md` (session context written by /wrap and the Stop hook), `memory/` and `memory.md` (auto-memory directory and file), `wrap.lock/` (/wrap concurrency lock dir), `preferences.json` (per-developer session preferences), and `compression-state.json` (compression bookkeeping). The tool-agnostic config files (`qa.md`, `deploy.md`, `tracking.md`) are NOT ignored - they are checked in so every tool (Claude Code, Codex, Cursor, Gemini) reads the same project config.

### 10. Create `docs/` structure

Create the following empty directories with a `.gitkeep` (only for directories that do not already exist):
```
docs/
  overview/
  technical/
  planning/
  research/
```

### 11. Set up tracker

Only run if the user confirmed a specific tracker (Linear or Jira) in Step 1. If tracker was "none", "neither", declined (`no tracker` / empty-Enter or `n`/`no`/`2`/`3` on any tracker prompt), or not confirmed, skip this step entirely — do not prompt for API keys, workspace slug, team key, project key, base URL, or any other tracker field.

**11a. Linear setup** (run if tracker = Linear)

Check if `linearctl` is installed: `which lc`. If not installed:

```bash
npm install -g linearctl
```

If the user provided a Linear API key in Step 1, authenticate:

```bash
lc init --api-key [LINEAR_API_KEY]
```

Store the key in `.claude/settings.local.json` under `"env"`:

```json
{
  "env": {
    "LINEAR_API_KEY": "[key from Step 1]"
  }
}
```

If `.claude/settings.local.json` already exists, merge `LINEAR_API_KEY` into the existing `"env"` object — do not overwrite other keys.

If `lc` was already installed, run `lc doctor` to verify the connection. If it fails and the user provided a key, re-init with `lc init --api-key`.

**Add `## Linear` section to `AGENTS.md`** (canonical shape):

```markdown
## Linear
- Team: [team key, e.g. FRM]
- Workspace: [workspace slug, e.g. acme]
- QA assignee ID: [Linear user UUID — optional, omit line if not provided]
- Branch prefix: Include issue ID (e.g., `feature/[TEAM]-12-description`)
- Projects: [comma-separated project names, or omit this line if none provided]
```

Place after `## Tools`. Prompt for: team key (required), workspace slug (required), QA assignee UUID (optional — "press Enter to skip"). If the user did not provide project names, omit the `Projects:` line.

Run `lc doctor` to confirm the connection. If it fails, add a reminder to the summary with the manual steps.

**11b. Jira setup** (run if tracker = Jira)

Jira credentials go in `~/.claude.json` under `mcpServers.mcp-atlassian.env` — NOT in `.claude/settings.local.json`. Print the following instructions for the user to complete manually:

```
Jira credentials must be added to ~/.claude.json manually.

Find or create the mcp-atlassian entry under mcpServers and add to its env block:

  For Jira Cloud:
    "JIRA_URL": "https://yourcompany.atlassian.net"
    "JIRA_USERNAME": "your@email.com"
    "JIRA_API_TOKEN": "your-api-token"

  For Jira Server/Data Center:
    "JIRA_URL": "https://jira.yourcompany.com"
    "JIRA_PERSONAL_TOKEN": "your-personal-access-token"

Get a Cloud API token at: https://id.atlassian.com/manage-profile/security/api-tokens
Find your Atlassian account ID at: https://[your-instance].atlassian.net/rest/api/3/myself
```

**Add `## Tracker` section to `AGENTS.md`** (canonical shape):

```markdown
## Tracker
TRACKER: jira
TICKET_PREFIX: [project key, e.g. PROJ]
JIRA_BASE_URL: [e.g. https://acme.atlassian.net]
JIRA_QA_ASSIGNEE_ACCOUNT_ID: [Atlassian account ID — optional, omit line if not provided]
JIRA_QA_TRANSITION: [transition name — optional, omit line if not provided]
```

Place after `## Tools`. Prompt for: TICKET_PREFIX (required), JIRA_BASE_URL (required), JIRA_QA_ASSIGNEE_ACCOUNT_ID (optional), JIRA_QA_TRANSITION (optional). **Do not use a default value for `JIRA_QA_TRANSITION`** — if the user does not provide one, omit the line entirely. `/implement-ticket` Phase 11 will skip the transition step when absent rather than guessing a transition name.

**11c. None**

No tracker setup needed. Skip this step.

### 12. Summary

After all files are processed, print a short summary with three sections:

**Created:** list every file that was newly written.
**Curated:** list `AGENTS.md` if it was reorganized in place (with a note: "reorganized to target structure; extracted facts moved to MEMORY.md").
**Skipped (already existed):** list every file that was left untouched and why (auto-skipped `.claude/settings.local.json`, or existing track `AGENTS.md`, or other existing files left untouched).

Then remind the user to (**omit any reminder for a feature the user declined in Step 1**, per "Negative answers are sticky"):
1. Update the `## Tools` section in root `AGENTS.md` as new CLI tools are added to the project over time
2. Fill in the `## Conventions` section in root `AGENTS.md` as the project takes shape
3. Grow each `[track]/AGENTS.md` alongside the code - add commands, schema, flows, and gotchas as they emerge (omit this reminder if no tracks were created)
4. Stable project facts (architecture decisions, key paths, rationale) go in `MEMORY.md` via `/memory-update` — not in `AGENTS.md`. On re-run, `/init-project` will auto-detect new tools, migrate legacy `## Linear` sections, and backfill missing config without destroying existing content.
5. Add any project-specific env vars to `.claude/settings.local.json` under `"env"` (e.g. database connection strings, API keys) - omit this reminder if `.claude/settings.local.json` was skipped
6. Confirm `gh` is installed and update the `## Tools` section in root `AGENTS.md` to add `- GitHub operations: use \`gh\` CLI - do not use GitHub MCP` - show only if `gh` was not detected and not confirmed in Step 1 AND `gh` was not declined in Step 1 (`no gh` / `skip gh`)
7. Update `.agentic/qa.md` with your staging URL once a staging environment is available - show only if `.agentic/qa.md` was created (and therefore web UI was not declined)
8. *(If `.agentic/deploy.md` was created — i.e. release signals detected and release was not declined)* Fill in the deploy command and rollback procedure in `.agentic/deploy.md`. The `release-orchestrator` agent uses this file the way `qa-engineer` uses `qa.md`. Update the `command` field once the exact deploy command is confirmed.
9. `/init-project` no longer auto-creates `.agentic/findings.md`. Pattern-promotion logic was removed; only the regression-test obligation for fixed Skeptic findings remains, and that is enforced inline by the Worker and Skeptic - no project-local file is needed. Existing `findings.md` files (legacy or migrated) are left untouched; they remain in source control if checked in, but no agent reads or writes them anymore.
10. *(If Jira was configured — i.e. user confirmed Jira in Step 1, not declined)* Add your Jira credentials to `~/.claude.json` under `mcpServers.mcp-atlassian.env` — see the instructions printed in Step 11b.
11. *(If Linear was configured without a QA assignee UUID — i.e. user confirmed Linear in Step 1, not declined)* You skipped the QA assignee UUID — `/implement-ticket` will skip the QA assignee update and only transition state + post comment. Add it later by re-running `/init-project`.
12. *(If auto-memory was not declined in Step 1)* Auto-memory is now pinned to `[selected-path]` via `.claude/settings.local.json`. All future Claude Code sessions in this project — regardless of which subdirectory you launch from — will write context and memory to that single directory. No action needed; just aware.
13. *(If global mode from Step 0a was `opt-out`)* This project will use agentic-engineering by default. To disable the methodology here without affecting other projects, add `agentic-engineering: opt-out` to `AGENTS.md` (under `## Activation` or as a bare line near the top). *(If global mode was `opt-in` and the user activated)* This project has `agentic-engineering: opt-in` in `AGENTS.md`; remove that line to deactivate here later. To change the risk profile for this project, add `agentic-engineering-profile: relaxed` (or `default` or `strict`) to `AGENTS.md`.
