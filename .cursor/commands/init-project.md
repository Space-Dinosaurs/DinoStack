# /init-project

Scaffold a new project with the standard CLAUDE.md hierarchy, CLI tool config, and gitignore.

## Steps

### 1. Gather project info

Ask the user (in a single message) for:
- **Project name** - used in headings and filenames. *Required.* If not provided, ask once more. If still not provided, stop the command, tell the user a project name is required, and ask them to re-run `/init-project` with a name ready.
- **One-line description** - what the project does. *Optional.* If skipped or unknown, a TODO placeholder will be used in `CLAUDE.md`.
- **Tracks / components** - list of subdirectories that will each get their own `CLAUDE.md` (e.g. `backend`, `frontend`, `contracts`, `mobile`). *Optional.* If skipped, unknown, or "none/not yet", no track `CLAUDE.md` files will be created - do not default to `backend`/`frontend`. The user can re-run `/init-project` or add them manually later.
- **GitHub CLI** - confirm `gh` is available. *Optional.* If skipped or unconfirmed, omit the `gh` line from `## Tools` entirely (same treatment as the database CLI).
- **Database CLI** - if the project has a database, what CLI will be used? (e.g. `psql`, `mongosh`, `prisma`). *Optional.* If skipped or "none", the database line is omitted from `## Tools` entirely.
- **Web UI** - does this project have a web interface that can be browser-tested? If yes, ask for the dev server start command and port (e.g. `npm run dev`, port `3000`). *Optional.* If skipped or "none/not yet", skip `.claude/qa.md` creation entirely.
- **Linear** - does this project use Linear for issue tracking? If yes, ask for: Linear API key, team key (e.g. `AUT`), default assignee name, and project names (comma-separated). *Optional.* If skipped or "none/not yet", omit the `## Linear` section from `CLAUDE.md` entirely and skip Linear setup in Step 11.

**Partial answers are fine.** If the user gives a partial answer or says "I don't know", proceed with what you have. Never loop or re-ask a question the user has already answered or declined.

Wait for the user's answers before continuing.

### 2. Discovery - scan before creating anything

Before writing any files, check which files already exist. The full set of files this command would create:

- `CLAUDE.md` (root)
- `[track]/CLAUDE.md` for each track the user named (omit if no tracks were named)
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.claude/qa.md` (only if web UI confirmed in Step 1)
- `memory/MEMORY.md` (created at `~/.claude/projects/[hash]/memory/MEMORY.md` by Claude Code - `/init-project` seeds it with a stub)
- `.gitignore`
- `docs/overview/.gitkeep`, `docs/technical/.gitkeep`, `docs/planning/.gitkeep`, `docs/research/.gitkeep`

**Report findings in two groups:**

```
Missing (will be created):
  - CLAUDE.md
  - backend/CLAUDE.md
  - ...

Already exists (will be left untouched or curated in place):
  - .claude/settings.json
  - .gitignore
  - ...
```

**Handle each file as follows - no user prompts, proceed automatically:**

**`.claude/settings.local.json` - always skip silently if it exists.** Do not ask. Do not overwrite. Remind the user: "`.claude/settings.local.json` already exists and was left untouched - it may contain real secrets. Add any new env keys manually."

**`CLAUDE.md` (root) - if it exists, curate in place.** Do not skip. Do not overwrite wholesale. Read it and reorganize it to conform to the target structure (under 40 lines). See Step 3 for the curation process.

**All other existing files - leave untouched.** Note them in the scan output. Do not ask. Do not overwrite.

**`.gitignore` safety check** - regardless of whether `.gitignore` is new or existing: check whether it already contains `.claude/settings.local.json`. If not, append the following two lines:

```
# Claude Code - local settings contain secrets
.claude/settings.local.json
```

This check is unconditional - run it whether `.gitignore` was just created or was already present.

### 3. Curate or create root `CLAUDE.md`

**If `CLAUDE.md` does not exist:** create from scratch using the template below. No curation needed - proceed directly.

**If `CLAUDE.md` exists:** perform intelligent curation with Worker + Skeptic review:

**Main agent pre-work (inline, before spawning Worker):**
Read the existing `CLAUDE.md` and identify two groups of content:

- **Memory candidates** - content that belongs in `MEMORY.md`, not `CLAUDE.md`: detailed rationale paragraphs, implementation details (code snippets, schema explanations), setup command sequences, decision alternatives considered, anything that reads as "what we learned" or "here is how it works" rather than "we decided X".
- **Architecture content to keep** - content that belongs in `CLAUDE.md`: resolved decisions expressed as brief bullets (1 sentence each), cross-cutting conventions, repo structure map, tools and their usage, docs structure.

**Spawn a background Worker** (labeled "CLAUDE.md curation Worker") with:
- The raw existing `CLAUDE.md` content
- The memory candidates identified above
- The Step 1 answers (project name, description, tracks, tools)
- The target `CLAUDE.md` structure below
- Instruction to produce two artifacts: (1) the curated `CLAUDE.md` content conforming to the target structure, (2) `MEMORY.md` entries for each memory candidate using format `- **YYYY-MM-DD:** [what and why, one-two sentences]` with today's date

**Target `CLAUDE.md` structure (under 40 lines):**
- H1: project name
- One-paragraph description
- `## Decisions` - resolved architecture decisions as brief bullets, no rationale paragraphs
- Repo structure map listing each track with a one-line description (omit if no tracks)
- `## Tools`
- `## Linear` (preserve if it exists - do not drop during curation)
- `## Docs`
- `## Conventions`

**Spawn a fresh Skeptic** after the Worker returns with this adversarial brief:
> "Is the curated CLAUDE.md under 40 lines? Does it have all required sections (H1, overview paragraph, Decisions, Tools, Docs, Conventions)? Did any implementation detail or rationale paragraph remain that belongs in memory.md instead? Are the memory entries stable facts (not temporary task state)? Does the curated CLAUDE.md preserve all architecture decisions from the original, just compressed to brief bullets?"

Require sign-off format:
```
Reviewed: [file]
Findings: Critical: N, Major: N, Minor: N - [brief descriptions, or "None"]
Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.
No unresolved Critical or Major findings. Sign-off granted.
```

After sign-off: write the curated `CLAUDE.md`, then merge the Worker's memory entries into `MEMORY.md` using semantic dedup - skip any entry already captured, supersede if updated, append if new. Before merging, check whether `MEMORY.md` exists. If it does not exist, create it with the stub header first (same content as Step 7), then merge. This ensures Step 8's guard ("if the file already exists, leave the stub header step") remains correct.

**`CLAUDE.md` template (use for new files, and as the structural target for curation):**
- H1: project name
- One-paragraph description. If no description was provided, use `<!-- TODO: Add one-paragraph description -->` as the placeholder.
- `## Decisions` - resolved architecture decisions as brief bullets - fill in as the project takes shape. Use a single TODO bullet placeholder if no decisions are known yet. Label it clearly: "Resolved architecture decisions as brief bullets - fill in as the project takes shape."
- Repo structure map listing each track directory with a one-line description (omit if no tracks were named)
- Note: "Each track directory has its own `CLAUDE.md` with deeper context." (omit if no tracks were named)
- `## Tools` section - document the CLI tools confirmed in Step 1:
  ```markdown
  ## Tools
  - GitHub operations: use `gh` CLI - do not use GitHub MCP
  - [Database CLI if applicable, e.g.: Database operations: use `psql` with `$DB_URL`]
  ```
  Include the `gh` line only if `gh` was confirmed; include the database line only if a DB CLI was specified.
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

### 4. Create subdirectory `CLAUDE.md` files

If the user provided no tracks (skipped, said "none", or "not yet"), skip this step entirely.

For each track the user named, **only create `[track]/CLAUDE.md` if it does not already exist** - never overwrite an existing track `CLAUDE.md`. For missing ones, create with:
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

Fill in `command` and `port` from the Step 1 answers. Use `TODO` placeholders for any unknowns.

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

If the file already exists (e.g. because CLAUDE.md curation in Step 3 merged entries into it), leave the stub header step and proceed to Step 9.

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

### 10. Create `docs/` structure

Create the following empty directories with a `.gitkeep` (only for directories that do not already exist):
```
docs/
  overview/
  technical/
  planning/
  research/
```

### 11. Set up Linear

Only if the user confirmed Linear in Step 1. This step has three parts:

**11a. Install and authenticate the CLI**

Check if `linearctl` is installed: `which lc`. If not installed:

```bash
npm install -g linearctl
```

If the user provided an API key in Step 1, authenticate:

```bash
lc init --api-key <LINEAR_API_KEY>
```

Then store the key in `.claude/settings.local.json` under `"env"`:

```json
{
  "env": {
    "LINEAR_API_KEY": "<key from Step 1>"
  }
}
```

If `.claude/settings.local.json` already exists, add the `LINEAR_API_KEY` entry to the existing `"env"` object - do not overwrite other keys.

If `lc` was already installed, run `lc doctor` to verify the connection. If it fails and the user provided a key, re-init with `lc init --api-key`.

**11b. Add `## Linear` section to `CLAUDE.md`**

Add a `## Linear` section to root `CLAUDE.md` after the `## Tools` section:

```markdown
## Linear
- Team: [team key from Step 1]
- Default assignee: [assignee from Step 1]
- Branch prefix: Include issue ID (e.g., `feature/[TEAM]-12-description`)
- Projects: [comma-separated project names from Step 1, or omit this line if none provided]
```

If the user did not provide project names, omit the "Projects" line. The global `/linear` command reads this section for defaults.

**11c. Verify**

Run `lc doctor` to confirm the connection is working. If it fails, add a reminder to the summary with the manual steps.

### 12. Summary

After all files are processed, print a short summary with three sections:

**Created:** list every file that was newly written.
**Curated:** list `CLAUDE.md` if it was reorganized in place (with a note: "reorganized to target structure; extracted facts moved to MEMORY.md").
**Skipped (already existed):** list every file that was left untouched and why (auto-skipped `.claude/settings.local.json`, or existing track `CLAUDE.md`, or other existing files left untouched).

Then remind the user to:
1. Update the `## Tools` section in root `CLAUDE.md` as new CLI tools are added to the project over time
2. Fill in the `## Conventions` section in root `CLAUDE.md` as the project takes shape
3. Grow each `[track]/CLAUDE.md` alongside the code - add commands, schema, flows, and gotchas as they emerge (omit this reminder if no tracks were created)
4. Stable project facts (architecture decisions, key paths, rationale) go in `MEMORY.md` via `/memory-update` - not in `CLAUDE.md`. On re-run, `/init-project` will automatically curate `CLAUDE.md` and extract any facts that have crept in.
5. Add any project-specific env vars to `.claude/settings.local.json` under `"env"` (e.g. database connection strings, API keys) - omit this reminder if `.claude/settings.local.json` was skipped
6. Confirm `gh` is installed and update the `## Tools` section in root `CLAUDE.md` to add `- GitHub operations: use \`gh\` CLI - do not use GitHub MCP` - show only if `gh` was skipped in Step 1
7. Update `.claude/qa.md` with your staging URL once a staging environment is available - show only if `.claude/qa.md` was created
8. Install the Linear CLI (`npm install -g linearctl && lc init`) and use `/linear` for issue management - show only if Linear was confirmed in Step 1 and `lc` was not found
