> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /init-project

Scaffold a new project with the standard AGENTS.md hierarchy, CLI tool config, and gitignore.

<!-- Risk-tier note: this command performs discovery, confirmation, and scaffolding only. It does not emit or classify risk-tier vocabulary (Trivial, Low, Elevated). No Trivial-tier addition is needed here. -->


## Steps

### 0. Run discovery

Before prompting for anything, silently scan the project to derive as many configuration values as possible.

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
- "no release" / "skip release" → clear release signal (suppresses `.claude/release.md` creation)
- "no benchmarks" / "skip benchmarks" → clear benchmark signal
- "no dep audit" / "skip dep audit" → clear dep-audit derivation

Corrections patch in-memory state; they do not re-run discovery. After corrections, echo only the changed lines: "Updated: [field] → [value]. Anything else, or press Enter to continue."

**Exit conditions:** empty input (Enter), "done", or "accept" → proceed with current state.

**If tracker signals were found** but tracker is not already configured, prompt before the confirmation block ends:

- Linear only → "Set up Linear tracker? [y/N]"
- Jira only → "Set up Jira tracker? [y/N]"
- Both → "I detected signals for both Linear and Jira. Which tracker does this project use? [linear/jira/neither]"

Wait for tracker confirmation before proceeding.

**Required fields** — project name is required. If it was not discovered and the user does not provide it in the override step, ask once more: "A project name is required. What should I call this project?" If still not provided, stop and ask the user to re-run `/init-project` with a name ready.

### 2. File scan and mode detection

**Idempotent mode trigger** — if `AGENTS.md` already exists and contains any of the standard sections (`## Tools`, `## Docs`, `## Conventions`, `## Linear`, or `## Tracker`), this is an **update run**, not a greenfield run. Switch to the update mode algorithm (Step 2a) instead of the normal create flow.

**Greenfield mode** — if `AGENTS.md` does not exist, or exists but contains none of the standard sections, proceed with the normal create flow (Steps 3 onward).

Before writing any files, check which files already exist. The full set of files this command would create:

- `AGENTS.md` (root) - the canonical project-instructions file, read by Claude Code, Codex, Cursor, and other tools. Claude Code reads it via a one-line `CLAUDE.md` containing `@AGENTS.md`.
- `[track]/AGENTS.md` for each track the user named (omit if no tracks were named)
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.claude/qa.md` (only if web UI confirmed in Step 1)
- `.claude/release.md` (only if release signals detected in Step 0)
- `.claude/findings.md` - the findings flywheel's project-local anti-pattern log - always created empty, populated by `/implement-ticket` Phase 6c, `/wrap` Part D, and any ad-hoc Worker+Skeptic cycle over time
- `memory/MEMORY.md` (created at `~/.claude/projects/[hash]/memory/MEMORY.md` by Claude Code - `/init-project` seeds it with a stub)
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

**`.claude/settings.local.json` - always skip silently if it exists.** Do not ask. Do not overwrite. Remind the user: "`.claude/settings.local.json` already exists and was left untouched - it may contain real secrets. Add any new env keys manually."

**`AGENTS.md` (root) - if it exists, curate in place.** Do not skip. Do not overwrite wholesale. Read it and reorganize it to conform to the target structure (under 40 lines). See Step 3 for the curation process.

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

1. **Legacy `## Linear` migration** — if `## Linear` exists but is missing `Workspace:` or `QA assignee ID:` fields:
   - Attempt to derive `Workspace`: scan git remote origin URL and last 50 commit messages for `linear.app/<slug>/` URL patterns. Use the slug if found.
   - Attempt to derive `QA assignee ID`: check for any UUID-shaped value already in the section.
   - Prompt only for values that could not be derived: "What is your Linear workspace slug?" and/or "What is the Linear QA assignee UUID? (optional — press Enter to skip)".
   - Rewrite `## Linear` in place using the new canonical shape (see Step 11a for shape). Preserve `Projects:` if present. Preserve the old `Default assignee:` name as a comment line if it existed and differs from any new UUID.

2. **Tracker mutual exclusion** — Linear and Jira are mutually exclusive:
   - If user confirmed Jira during Step 1 and `## Linear` exists: plan to remove `## Linear` and write `## Tracker` (Jira shape).
   - If user confirmed Linear and `## Tracker` (Jira) exists: plan to remove `## Tracker` and write `## Linear` (Linear shape).
   - If no tracker change: leave existing section untouched.

3. **`## Tools` backfill** — for each new CLI tool discovered in Step 0 that is not already present in `## Tools`: plan to append it. Never touch existing entries. Match on CLI name (e.g. `psql`, `mongosh`, `gh`). If a dep-audit command was derived in Step 0 and no dep-audit entry exists in `## Tools`: plan to append it (e.g. `- Dependency audit: use \`npm audit --json\` for vulnerability scans`).

4. **Missing sections** — if `## Docs` or `## Conventions` is absent: plan to add them (same content as greenfield template).

5. **`docs/` directories** — plan to create any missing subdirectories.

6. **`.claude/qa.md`** — if web UI was confirmed and file does not exist: plan to create it.

7. **`.claude/release.md`** — if release signals were detected and file does not exist: plan to create it using the same template as Step 6a.

8. **`.claude/findings.md`** — if the file does not exist: plan to create it using the same stub template as Step 6b.

**Present the diff:**

```
Here's what I'd update:

  AGENTS.md:
    - Migrate ## Linear to new shape (Workspace: [value], QA assignee ID: [value or "not set"])
    - Append to ## Tools: [new entry]

  .claude/qa.md:
    - Create (not found, web UI detected as [framework] on port [N])

  .claude/release.md:
    - Create (not found, release signal detected: [type])

  .claude/findings.md:
    - Create (not found)

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

**Target `AGENTS.md` structure (under 40 lines):**
- H1: project name
- One-paragraph description
- `## Decisions` - resolved architecture decisions as brief bullets, no rationale paragraphs
- Repo structure map listing each track with a one-line description (omit if no tracks)
- `## Tools`
- `## Linear` OR `## Tracker` (preserve whichever is present — do not drop during curation)
- `## Docs`
- `## Conventions`

**Spawn a fresh Skeptic** after the Worker returns with this adversarial brief:
> "Is the curated AGENTS.md under 40 lines? Does it have all required sections (H1, overview paragraph, Decisions, Tools, Docs, Conventions)? Did any implementation detail or rationale paragraph remain that belongs in memory.md instead? Are the memory entries stable facts (not temporary task state)? Does the curated AGENTS.md preserve all architecture decisions from the original, just compressed to brief bullets?"

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
  Include the `gh` line only if `gh` was detected or confirmed; include the database line only if a DB CLI was specified; include the dep-audit line only if a dep-audit command was derived in Step 0, and use the exact command derived there.
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

Keep it under 40 lines.

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

### 6. Create `.claude/qa.md`

Only create if the user confirmed a web UI in Step 1. Only create if the file does not already exist.

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

### 6a. Create `.claude/release.md`

Only create if release signals were detected in Step 0 AND the user has not suppressed the signal ("no release") AND the file does not already exist.

Fill in the `command` from the detected release type where possible. Use `TODO` for values that were not detected or confirmed.

Content template:

```markdown
# Release Config

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

### 6b. Create `.claude/findings.md`

Always create. No signal required - the findings flywheel applies to every project regardless of stack or release setup. Only create if the file does not already exist.

Content template:

```markdown
# Findings

<!-- Recurring Skeptic anti-patterns promoted after sign-off by /implement-ticket, /wrap, or any Worker+Skeptic cycle. -->
<!-- Target under 15 entries; consolidate or retire stale entries when adding. -->
<!-- Read by Architect at plan time and Skeptic at review time. -->
```

Architect reads this file at plan time to surface prior lessons and cites applicable entries in the plan's "Trade-offs and constraints" section. Skeptic reads it at review time and raises a Major finding if the diff repeats a documented anti-pattern. Promotion happens in `/implement-ticket` Phase 6c, `/wrap` Part D, and any ad-hoc Worker+Skeptic cycle - after the QA gate passes.

Full spec: `~/agentic-engineering/.claude/skills/agentic-engineering/references/findings-flywheel.md`

### 7. Create `.claude/settings.local.json`

Only create this file if it does not already exist (enforced in Step 2 - skip if it exists).

```json
{
  "env": {}
}
```

Add any project-specific env vars here (e.g. database connection strings, API keys).

### 8. Seed `MEMORY.md`

The project MEMORY.md lives outside the project directory at `~/.claude/projects/[hash]/memory/MEMORY.md` and is auto-injected by Claude Code at startup.

If the file does not already exist, create the memory directory and seed the file:
- Resolve the memory directory path from the Claude Code auto-injected context (look for "You have a persistent auto memory directory at `~/.claude/projects/[hash]/memory/`")
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

Regardless of whether `.gitignore` is new or existing: check whether it already contains `.agentic/`. If not, append the following block to it. If `.gitignore` does not exist, the entry above creates it - ensure this block is included in the new file's contents.

```
# Agentic engineering runtime artifacts (must not be committed)
# .agentic/ covers: loop-state.json (cross-session resume state), hud/ (per-worker HUD files),
# and tasks.jsonl (multi-unit task coordination). All are runtime data, not source.
.agentic/
```

The `.agentic/` directory-level entry covers all runtime artifacts: `loop-state.json` (loop resume state written by `/implement-ticket` Phase 6 and the Stop hook), `hud/` (per-worker HUD files for P1 fan-out observability), and `tasks.jsonl` (multi-unit task coordination). None of these should be committed.

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

Only run if the user confirmed a tracker in Step 1. If tracker was "none" or not confirmed, skip this step entirely.

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

Then remind the user to:
1. Update the `## Tools` section in root `AGENTS.md` as new CLI tools are added to the project over time
2. Fill in the `## Conventions` section in root `AGENTS.md` as the project takes shape
3. Grow each `[track]/AGENTS.md` alongside the code - add commands, schema, flows, and gotchas as they emerge (omit this reminder if no tracks were created)
4. Stable project facts (architecture decisions, key paths, rationale) go in `MEMORY.md` via `/memory-update` — not in `AGENTS.md`. On re-run, `/init-project` will auto-detect new tools, migrate legacy `## Linear` sections, and backfill missing config without destroying existing content.
5. Add any project-specific env vars to `.claude/settings.local.json` under `"env"` (e.g. database connection strings, API keys) - omit this reminder if `.claude/settings.local.json` was skipped
6. Confirm `gh` is installed and update the `## Tools` section in root `AGENTS.md` to add `- GitHub operations: use \`gh\` CLI - do not use GitHub MCP` - show only if `gh` was not detected and not confirmed in Step 1
7. Update `.claude/qa.md` with your staging URL once a staging environment is available - show only if `.claude/qa.md` was created
8a. *(If `.claude/release.md` was created)* Fill in the deploy command and rollback procedure in `.claude/release.md`. The `release-orchestrator` agent uses this file the way `qa-engineer` uses `qa.md`. Update the `command` field once the exact deploy command is confirmed.
8b. `.claude/findings.md` is created empty and populated by `/implement-ticket`, `/wrap`, and ad-hoc Worker+Skeptic cycles as recurring review patterns emerge. No action needed at init time.
8. *(If Jira was configured)* Add your Jira credentials to `~/.claude.json` under `mcpServers.mcp-atlassian.env` — see the instructions printed in Step 11b.
9. *(If Linear was configured without a QA assignee UUID)* You skipped the QA assignee UUID — `/implement-ticket` will skip the QA assignee update and only transition state + post comment. Add it later by re-running `/init-project`.
