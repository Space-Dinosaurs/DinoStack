> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.

# /wrap — On-Demand Session Context Enrichment

> Run the Activation preflight from `agent-methodology.md` before proceeding. If inactive, no-op and exit.

Use when you want a richer context file than the auto-hook provides — e.g. before handing off complex in-progress work to a future session.

The Stop hook auto-writes `<cwd>/.agentic/context.md` after every turn with raw session data. `/wrap` merges with or rewrites that file with a structured, human-curated version when detail matters. It is also the ongoing counterpart to `/init-project`: where `/init-project` scaffolds the AGENTS.md hierarchy, `/wrap` populates it — filling in root and subdirectory AGENTS.md files with decisions, conventions, stack details, and gotchas learned during sessions.

## Your job (main agent)

**Pre-flight scaffold-accuracy check** (runs BEFORE Step 0). `/init-project` is the canonical scaffolding spec; /wrap uses it as the reference for "what this project should look like." Check for drift and auto-migrate the critical items inline:

1. **CLAUDE.md → AGENTS.md migration** (per-file, recursive through tracks). For each `CLAUDE.md` in the project (root + every track directory) where a sibling `AGENTS.md` does not already exist:
   - `cp <dir>/CLAUDE.md <dir>/AGENTS.md` to preserve content.
   - Overwrite `<dir>/CLAUDE.md` with the single line `@AGENTS.md` so Claude Code transparently loads the new file.
   - Skip directories where `AGENTS.md` already exists (leave `CLAUDE.md` untouched).

2. **`.claude/` → `.agentic/` session state migration.** If `<cwd>/.claude/context.md` exists and `<cwd>/.agentic/context.md` does not:
   - `mkdir -p <cwd>/.agentic`
   - `mv <cwd>/.claude/context.md <cwd>/.agentic/context.md`
   - Same for `<cwd>/.claude/memory.md` and `<cwd>/.claude/memory/` (the auto-memory dir).
   - Redo symlinks in `~/.claude/projects/[hash]/` to point at the new `.agentic/` paths.

3. **Legacy config migration (`.claude/<name>.md` → `.agentic/<name>.md`)** — for each of `qa.md`, `deploy.md`, `findings.md`, `tracking.md`:
   - **Both paths exist on disk**: do NOT migrate. Log a drift warning in the wrap run output (e.g. "Drift (both .claude/findings.md and .agentic/findings.md exist - skipping auto-migration; resolve manually via /init-project)"), and add a bullet under the context.md "Watch Out For" section naming the conflicting files. Skip to the next name.
   - **Only legacy `.claude/<name>.md` exists**: first, run `git status --porcelain` to check working-tree cleanliness. If there are staged or unstaged changes, do NOT migrate - log a drift note ("Skipped migration of legacy .claude/<name>.md: working tree dirty. Commit or stash, then re-run /wrap or /init-project.") and add a Watch Out For bullet. If the working tree is clean, migrate: `git mv .claude/<name>.md .agentic/<name>.md`. Log the move to the wrap run output only.
   - **Only `.agentic/<name>.md` exists**: no action.
   - **Neither exists**: no action at this step - the missing-stub creation below handles creation.

4. **Missing-stub creation.** If any of `.agentic/tracking.md`, `.agentic/deploy.md` (only when release signals detected) is missing (checked via resolver: `.agentic/<name>.md` preferred, legacy `.claude/<name>.md` fallback), create a stub at `.agentic/<name>.md` per the template in `/init-project` Steps 6a-6d.

5. **Silent auto-fix for remaining drift.** /wrap is silent and hands-off. For any drift /wrap can fix without user input, fix it inline:
   - Create `docs/overview/`, `docs/technical/`, `docs/planning/`, `docs/research/` (with `.gitkeep`) if missing.
   - Create `.claude/settings.json` (`{}`) if missing.
   - Create `.claude/settings.local.json` with `autoMemoryDirectory` set to `<cwd>/.agentic/memory` if missing or if the key is not yet present (merge rule: never overwrite an existing value).
   - Create `.gitignore` entries for `.claude/settings.local.json` and the `.agentic/` runtime-artifact block (per `/init-project` Step 9) if missing.
   - **Pre-AGENTS.md layout detection (DO NOT auto-split inline).** If root `AGENTS.md` is absent AND root `CLAUDE.md` exists with more than the single-line `@AGENTS.md` pointer, do NOT attempt the Worker+Skeptic three-way split inline — that migration requires user confirmation of the proposed split, and /wrap's silent contract cannot provide one. Instead, add a "Watch Out For" entry in context.md: `Pre-AGENTS.md layout detected (CLAUDE.md has real content, no root AGENTS.md). Run /init-project to run the Worker+Skeptic split and migrate.`

6. **Drift that cannot be auto-fixed.** If any drift requires user input (e.g. Linear workspace slug, Jira base URL, confirmation of release commands, selection among multiple detected web UIs), do NOT prompt during /wrap. Instead, record a bullet under "Watch Out For" in the context.md output noting which scaffolding items are still incomplete. The user can address these later by running `/init-project` interactively. Specific drift kinds that always require user input and must be listed here:
   - **CLAUDE.md split** — the pre-AGENTS.md migration requires the user to review and accept the three-way split (AGENTS.md / residual CLAUDE.md / MEMORY.md). /wrap cannot perform this silently; it points at `/init-project`.
   - Linear workspace slug or QA assignee UUID not yet set when `## Linear` is present.
   - Jira `JIRA_BASE_URL`, `TICKET_PREFIX`, or transition name not yet set when `## Tracker` is present.
   - Release command / rollback procedure confirmation when `.agentic/deploy.md` has TODO placeholders.
   - Choice among multiple detected web UIs for `.agentic/qa.md` in a multi-track project.

All steps are silent on success. Log each migration action taken (e.g. "Migrated admin/CLAUDE.md to admin/AGENTS.md + pointer") to the wrap run output only, not as user prompts. After preflight completes, proceed to Step 0.

**Pre-flight check — no active Workers.** Before doing anything else, check whether any background Workers or subagents are currently running. If any are, stop and tell the user: "Cannot run /wrap while background tasks are active. Please wait for them to finish (or stop them) first." Do not proceed until confirmed.

**Pre-flight lock acquisition.** /wrap writes to several shared project-local files (context.md, memory.md, AGENTS.md, compression-state.json, rolling snapshots). Concurrent /wrap runs in the same project would clobber each other. Acquire a project-local lock before proceeding:

1. Ensure `<cwd>/.agentic/` exists (`mkdir -p <cwd>/.agentic`).
2. Attempt atomic acquisition: `mkdir <cwd>/.agentic/wrap.lock` (atomic on POSIX - succeeds only if the directory did not exist).
3. **If `mkdir` succeeds**, immediately write owner metadata: `<cwd>/.agentic/wrap.lock/owner` containing two lines - the current process PID and an ISO8601 UTC timestamp (e.g. `date -u +%Y-%m-%dT%H:%M:%SZ`). Proceed.
4. **If `mkdir` fails** (lock already held), read `<cwd>/.agentic/wrap.lock/owner`. Consider the lock stale if EITHER: (a) the PID is not running (`ps -p <pid>` returns non-zero), OR (b) the timestamp is older than 30 minutes. If stale, remove the lock dir (`rm -rf <cwd>/.agentic/wrap.lock`) and retry step 2 once. If the retry still fails, treat as live.
5. **If the lock is live**, abort immediately. Tell the user: "Another /wrap run is in progress in this project (pid N, started at TIME). Wait for it to finish, then retry." Do not queue or wait. Do not proceed to any subsequent step.

The 30-minute staleness heuristic exists because a crashed or force-killed /wrap may leave the lock dir behind - the PID check catches most cases, but the timestamp backstop covers PID reuse.

**Lock release is mandatory on every exit path.** The lock dir MUST be removed (`rm -rf <cwd>/.agentic/wrap.lock`) before /wrap returns control to the user, on ALL of:
- successful completion at Step 6;
- escalation to the user at Step 3 (format re-invocation limit or contested finding);
- compression failure or escalation at Part E;
- any user-abort path (e.g. drift requiring input, Skeptic scope bail).

If /wrap aborts before this lock step (e.g. at the active-Workers check above), no lock was acquired and no release is needed.

**Pre-flight path check:** Confirm `<cwd>/.agentic/` exists or can be created. The /wrap skill now writes project-local under `<cwd>/.agentic/` instead of the legacy `~/.claude/projects/[hash]/` hashed directories. No disambiguation needed - one canonical location per project.

Tell the user: "Writing enriched session context — I'll let you know when it's done."

**Step 0 — Compile session data** (inline, no subagent needed).

Survey the current conversation and note down:
- The main task and its current state (done? blocked? in progress?)
- All files touched or created this session (from tool call history — be specific: full paths)
- Any errors, gotchas, or near-misses that surfaced
- Specific remaining next steps (file paths, branch names, commands, open PRs — concrete enough to act on without re-reading the chat)
- Tools used during the session
- Stable project facts worth preserving: setup commands that don't change, persistent project-wide gotchas or quirks, architectural decisions made, recurring patterns or conventions established. Distinguish these from temporary state (current task, files touched this session) - stable facts will go into memory.md, temporary state into context.md only.
- Identify the project root (absolute cwd).
- Check for and read: the root `AGENTS.md` (if it exists), and any `[track]/AGENTS.md` files in subdirectories that had files touched this session. Record their full current content — this will be passed to the Worker as a dedicated field so it can avoid duplicating what is already captured.
- **Migrate `.claude/compression-state.json` → `.agentic/compression-state.json`** if `.claude/compression-state.json` exists AND `.agentic/compression-state.json` does NOT exist: `mv <cwd>/.claude/compression-state.json <cwd>/.agentic/compression-state.json`. Log the move to the wrap run output only.
- **Read `.agentic/compression-state.json`** if it exists in the project. Record its full current content — this will be passed to Part E later to determine whether compression is needed for each target.
- Note which tracks (subdirectories) had files touched this session — these are candidates for AGENTS.md updates.
- **Check for missing AGENTS.md files:** For each directory that had files touched this session, check whether an AGENTS.md file exists in that directory. Skip generated/artifact directories (`node_modules`, `.next`, `dist`, `out`, `build`, `.expo`, `.turbo`, `coverage`, `.cache`, `__pycache__`, `.git`). For each non-generated directory missing an AGENTS.md, note it as a **new AGENTS.md candidate** and include it explicitly in the raw data passed to the draft Worker. The Worker will propose content for these new files; the conductor will create them automatically without asking the user.
- **Run `git status --porcelain` and `git stash list`** to capture uncommitted changes and stashes. If there are uncommitted tracked files (M, A, D - not ??), list them explicitly. This is critical for preventing work loss across sessions - if the user asked to commit and files were missed, this is the safety net.
- **Note specialist agent outputs** — if `perf-analyst`, `release-orchestrator`, or `dependency-auditor` ran this session, capture their key findings: stable facts (confirmed hotspots with measurements, release version and tag, known CVEs) belong in memory.md entries; session-scoped issues (a partial deploy, a perf regression under investigation, an unresolved dependency conflict) belong in Watch Out For.
- **Note Trivial commits** — if any commits this session were classified Trivial, include them in "files touched" and "next steps" as normal. Trivial commits produce no Skeptic artifact and no adversarial brief - do not flag their absence as a gap. Only note the commit SHA and what changed.
- **Note task-state summary** - if `.agentic/tasks.jsonl` exists and contains entries with the current `session_id`, include in the session wrap summary: final task status counts (N done, N blocked, N failed, N abandoned). Do NOT copy task entries into MEMORY.md - they are already durable in the file.
- **Note loop-state summary** — if `.agentic/loop-state.json` exists: if `status=active`, note in the wrap summary that an incomplete loop was active when `/wrap` ran (the conductor should investigate before ending the session); if `status=interrupted`, note a pending resume is available (the next `/implement-ticket` invocation will offer to resume). The wrap command does NOT delete or modify `loop-state.json` - that is the user's choice (resume vs fresh-start). Do NOT copy loop state details into MEMORY.md or context.md beyond the one-line status note.

This raw data is what the draft Worker will format. The Worker is a fresh agent with no session memory, so if you don't supply the details here, they won't appear in the output.

**Step 0.5 - Route to light, zero-substance, or standard path.**

Inspect what Outputs 2, 3, and 4 would contain based on the raw data already compiled in Step 0. Do not spawn anything yet.

**Zero-substance path** - triggers when ALL of the following hold:
- Output 2 (memory entries) would be "None"
- Output 3 (AGENTS.md updates) would be "None" for every file AND no new AGENTS.md candidates exist
- No specialist agent (`perf-analyst`, `release-orchestrator`, `dependency-auditor`) ran with session-scoped issues to capture
- The session had effectively no file activity worth preserving in context.md: no uncommitted tracked changes, no new stashes, no files touched beyond reads, no meaningful next steps to record. The conductor should judge - if the only meaningful session output is "answered a question", it is zero-substance.

Zero-substance procedure:
- Do NOT write context.md (the Stop hook already writes a raw context file after every turn - running /wrap on a zero-substance session duplicates that work with a hand-curated version of nothing)
- Skip Steps 1-3 entirely (no Worker, no Skeptic)
- Skip Step 4 Parts A, B, C entirely
- Skip Part E (nothing changed, nothing to compress)
- Still run Step 5 (worktree cleanup) - that is always useful
- Step 6 confirmation must say: "zero-substance path - nothing new to capture this session; ran worktree cleanup only"

**Light path** - triggers when the zero-substance conditions do NOT all hold BUT ALL of the following hold:
- Output 2 (memory entries) would be "None" - STRICT: even a single memory entry routes to standard path
- Output 3 (AGENTS.md updates) would be "None" for every file AND no new AGENTS.md candidates exist
- No specialist agent ran with session-scoped issues to capture

Light path procedure (replaces Steps 1-3; preserves parts of Step 4):
1. Main agent drafts context.md inline from the Step 0 raw data, following the Output 1 structure exactly. No Worker, no Skeptic.
2. Skip Step 1 (draft Worker) and Steps 2-3 (Skeptic + sign-off validation).
3. Proceed to Step 4 Part A with the inline draft.
4. Skip Part B (memory.md - input is None), Part C (AGENTS.md - input is None).
5. Skip Part E entirely (nothing changed, nothing to compress).
6. Run Step 5 (worktree cleanup) as normal.
7. Step 6 confirmation must say: "light path (no stable facts or AGENTS.md updates to review this session)".

**Escape hatch for light path:** If, while drafting context.md inline, the main agent notices something it wants the Skeptic to review - ambiguous next-step wording, uncertainty about whether a fact is stable or temporary, unfamiliar territory in the raw data - it must abandon the light path and fall back to the standard path. The light path is for cases where there is genuinely nothing worth an adversarial pass.

**Escape hatch for zero-substance path:** If the conductor has ANY uncertainty about whether the session is truly zero-substance - for example, the user asked a question whose answer feels architecturally significant, or an implicit decision was made without writing anything down - it must abandon the zero-substance path and use the light or standard path instead. When in doubt, do not use the zero-substance path.

**Standard path** - triggers when neither of the above applies (i.e. at least one of Outputs 2/3/4 has real content, OR a specialist agent ran with session-scoped issues). Proceed to Step 1 unchanged.

**Step 1 — Spawn a draft Worker** (background, general-purpose):

---
You are a Worker agent. Format the raw session data below into three outputs. Replace all placeholders with real content from the data provided. If a section genuinely has nothing to say, write the word "None" — never leave brackets or template text.

**Raw session data:**
[paste your Step 0 notes here verbatim — this covers the task, files touched, errors, next steps, tools used, and stable facts. Do NOT embed existing AGENTS.md file contents here; those go in the dedicated field below.]

**Existing AGENTS.md file contents:**
[For each AGENTS.md file read in Step 0, paste its full current content here, clearly labeled with its absolute path, e.g.:

File: /Users/alice/myapp/AGENTS.md
Content:
<full file content>

File: /Users/alice/myapp/backend/AGENTS.md
Content:
<full file content>

If no AGENTS.md files were found, write "None."]

**Output 1 — context.md draft**

Produce this exact structure. Include only temporary session state here (current task, files touched, recent errors, next steps). Do not include stable project facts in this file - those belong in Output 2.

    # Session Context
    *Written by /wrap on YYYY-MM-DD. Preserved by Stop hook. Not committed to git.*
    *Project: [absolute cwd]*

    ## Recent Focus
    [1–3 sentences: what was being worked on when /wrap was invoked]

    ## Current Task / Next Steps
    [Specific next steps: file paths, branch names, open PRs, exact commands. Concrete enough to act on without reading the chat history.]

    ## Key File Paths
    [Files touched or created this session that the next session will care about]

    ## Uncommitted Changes
    [Output of `git status --porcelain` for tracked files only (M/A/D/R, not ??). If working tree is clean, write "(working tree clean)". If there are uncommitted files, list each with its status prefix. This section is a safety net - if the user asked to commit all changes and files appear here, they were missed.]

    ## Stashes
    [Output of `git stash list`, or "(no stashes)" if empty. Stashes may contain work from previous sessions that was never committed.]

    ## Watch Out For
    [Session-specific issues, errors, or near-misses from this session only. Stable/recurring project quirks do not belong here - those go in memory.md. Or: None.]

    ## Tools Used
    [Comma-separated list of unique tools used this session]

**Output 2 — memory.md entries**

Review the raw session data for stable project facts: setup commands that don't change, persistent project-wide gotchas or quirks, architectural decisions, recurring patterns, project conventions. For each stable fact, produce one entry in this format:

`- **YYYY-MM-DD:** [what was decided and why this approach was chosen - alternatives considered may be noted as supporting context, in one to two sentences]`

Use today's date for all entries. If there are no stable facts to record, write "None."

Stable = true every session, not just this one. Temporary = only relevant right now (current task, files touched this session).

For architectural and technology decisions especially: the entry must clearly state why the chosen approach was selected on its own merits. Alternatives considered and their rejection reasons are useful supporting context but are secondary - the positive reasoning for the choice is the primary requirement. A future session asking "should we reconsider X?" should find the answer in the entry without re-researching it.

**Output 3 — AGENTS.md updates**

For each AGENTS.md file whose current content was provided in the "Existing AGENTS.md file contents" field above, produce proposed additions only - not a full rewrite. Use that existing content as your baseline: do not propose content already present there.

Format each proposed update as:

    File: [full path to AGENTS.md]
    Section: [section name, e.g. "## Decisions", "## Conventions", "## Stack", "## Key Conventions"]
    Add:
    - [bullet point to add]
    - [another bullet if needed]

If a section doesn't exist in the target file yet but should be added, indicate:

    File: [full path to AGENTS.md]
    New section: [section name]
    Content:
    [section content]

If content in an existing entry should be corrected or superseded, indicate:

    File: [full path to AGENTS.md]
    Section: [section name]
    Update: [existing text] → [replacement text]

Rules:
- Only propose content that was actually established or learned in this session. Do not hallucinate or infer.
- Do not duplicate content already present in the existing AGENTS.md (check against the "Existing AGENTS.md file contents" field provided above).
- Do not contradict existing content without flagging it as an Update.
- For root AGENTS.md: focus on `## Decisions` (resolved architecture decisions as brief bullets) and `## Conventions` (patterns and rules the project follows).
- For subdir AGENTS.md: focus on `## Stack`, `## Key Conventions`, and any new relevant categories (Commands, Schema, Flows, Gotchas) that emerged this session.
- Quality directive: lean and curated. No verbose rationale paragraphs, no outdated entries, no conflicting information. Brief, actionable bullets only.
- If nothing new for a particular file, write "None" for that file.
- If no AGENTS.md files were found in the project, write "None."

**New AGENTS.md files:** For any touched directory explicitly noted as a "new AGENTS.md candidate" in the raw session data (i.e. the directory had files touched but has no existing AGENTS.md), propose creating a new file. Use this format:

    File: [full path to new AGENTS.md]
    New file: true
    Content:
    # [Directory name]

    [One sentence description of what this directory contains, based on the session data.]

    ## Stack
    [Key technologies from package.json or inferred from file types touched - bullet list]

    ## Key Conventions
    [Conventions observed from the session - bullet list. If none observed, omit this section.]

    ## Gotchas
    [Any gotchas or sharp edges encountered - bullet list. If none, omit this section.]

This is automatic - do not ask the user. Populate sections from session context and any package.json content included in the session data.

Return all three outputs clearly labeled. Do not write to disk.

---

**Step 2 — When the draft Worker returns, spawn a fresh Skeptic** (background, general-purpose, never resumed).

Scope constraint: the Skeptic reviews only the accuracy and completeness of the context file and the AGENTS.md updates. Its findings must only trigger context file or AGENTS.md rewrites - never code changes, bug fixes, or any development work. If the Skeptic notes that the context file describes pending work that is already complete (or vice versa), the fix is to update the wording to reflect reality accurately.

Provide the draft, the existing AGENTS.md file contents from Step 0, and this adversarial brief. **Omit any section below whose corresponding Output is "None"** - always keep the Output 1 (context.md accuracy) review as the baseline pass; drop the memory-review language if Output 2 is "None"; drop the AGENTS.md-review paragraph if Output 3 is "None". The full brief below is the "all outputs present" case:

> "Is this context file accurate and actionable? Check each section: Does Recent Focus correctly describe what was actually happening — or is it vague, generic, or wrong? Are the Next Steps specific enough to act on without reading the chat history (file paths, commands, branch names)? Are Key File Paths complete — is anything relevant omitted? Does Watch Out For capture real gotchas, or is it empty when it shouldn't be? Is any section still template text rather than real content?"
>
> "Also review the proposed AGENTS.md updates (Output 3): Is each proposed addition actually derived from this session's work - or is it generic, hallucinated, or already present in the existing file content provided? Is any content going to the wrong file (project-wide content should go to root; track-specific content should go to the track subdir)? Are updates lean - brief bullets only, no verbose rationale? Does any proposed addition contradict or duplicate existing entries in the same file?"

Require this statement before sign-off: "Active search: I have applied the adversarial brief and actively searched for Critical and Major findings."

**Step 3 — Validate sign-off format.**

A valid sign-off requires all four elements: (a) "Reviewed:", (b) "Findings:", (c) "Active search:", (d) "No unresolved Critical or Major findings. Sign-off granted." If any element is missing, spawn a new Skeptic with format instructions (not a new re-route round). Limit: 3 format re-invocations, then escalate to the user.

If Critical or Major findings remain: spawn a new draft Worker with the original draft and findings, get a revised draft, then spawn a fresh Skeptic (Step 2). Repeat until sign-off. If the same finding is contested across 2+ re-routes without resolution, escalate to the user.

**Step 4 — Write to disk** (main agent, inline — do NOT delegate to a subagent).

Background subagents cannot reliably get Write/Edit permissions. The main agent must perform all writes directly. Invoking /wrap implies permission to write these files.

**Project directory:** [absolute cwd]

**Output path (context.md):** `<cwd>/.agentic/context.md`. Project-local. The file lives next to the code it describes and is gate-free (no sensitive-file check). The Stop hook writes to the same path. Create the `<cwd>/.agentic/` directory if it does not exist.

**Memory path (memory.md):** `<cwd>/.agentic/memory.md`. Same directory as context.md.

**Migration note:** Earlier versions of this skill wrote to `~/.claude/projects/[hash]/{context,memory}.md`. If those files exist for the current project but the project-local files do not, copy them once into `<cwd>/.agentic/` before merging. Symlinks at the old hashed location pointing at the new project paths are acceptable - they preserve any platform mechanism that auto-loads from the legacy path while keeping writes gate-free.

**Part A — Write context.md**

1. Use the Read tool to attempt to read the file at the output path computed above.

2. **If the file does not exist** (Read returns a file-not-found error): write the new draft content directly to the output path. Return: "Wrote fresh context to [path] (no existing file)."

3. **If the file exists but is empty, or its second line does not begin with `*Written by /wrap`**: the existing file was written by the Stop hook or another source and cannot be meaningfully merged. Write the new draft content directly, overwriting the existing file. Return: "Wrote fresh context to [path] (replaced non-/wrap file)."

4. **If the file exists and its second line begins with `*Written by /wrap`** (i.e. it was produced by a previous `/wrap` run): proceed to the merge step below.

Note: "second line" means the literal second line of the file. A `/wrap`-produced file always starts with `# Session Context` on line 1 and `*Written by /wrap on ...` on line 2.

**Merge step:**

First, check how many session labels are already present in the existing file's Recent Focus section.

- **Five labels present (`[Session A]` through `[Session E]`)**: apply a rolling-window merge. Discard the `[Session A]` content from Recent Focus, relabel `[Session B]` as `[Session A]`, `[Session C]` as `[Session B]`, `[Session D]` as `[Session C]`, `[Session E]` as `[Session D]`, and use the new draft as `[Session E]`. For all other sections (Current Task / Next Steps, Key File Paths, Watch Out For, Tools Used), treat the full existing content as the prior session and apply the standard merge rules below.

- **Four labels present (`[Session A]` through `[Session D]`)**: label the new draft entry `[Session E]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Three labels present (`[Session A]`, `[Session B]`, `[Session C]`)**: label the new draft entry `[Session D]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Two labels present (`[Session A]` and `[Session B]`)**: label the new draft entry `[Session C]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Single unlabeled Recent Focus** (standard case - first merge): label the existing entry `[Session A]` and the new draft entry `[Session B]`, each on its own paragraph.

**Merge rules (existing file = prior session(s), new draft = newest session):**

- **Header line** (`*Written by /wrap...`): replace with a new line using today's date and the note "(merged context)". Keep the `*Project:` line from the new draft.
- **Recent Focus**: apply the labeling logic above.
- **Current Task / Next Steps**: combine all items from both. Remove exact duplicate lines. Keep all non-duplicate items.
- **Key File Paths**: union both lists. Remove exact duplicate lines.
- **Watch Out For**: union both lists. Remove exact duplicate lines. If one had "None" and the other has real entries, use only the real entries.
- **Tools Used**: combine both comma-separated lists, split by comma, trim whitespace, deduplicate, re-join as a single comma-separated list.

Write the merged result to disk. Return: "Merged context written to [path] (combined sessions)."

**Part B — Write memory.md**

Skip Part B entirely if the memory entries input above is "None".

1. Use the Read tool to attempt to read the file at the memory.md path.

2. **If the file does not exist**: write all new entries directly as a markdown list. Return: "Wrote fresh memory to [path]."

3. **If the file exists**: read its content. For each new entry, check whether the same fact is already captured - not just as an exact string match, but semantically (same architectural decision, same gotcha, same command). If an existing entry covers the same fact, skip the new entry. If the new entry supersedes an existing one (same topic but updated or corrected), replace the existing entry in place with the new one. Otherwise append the new entry. Write the merged result. Return: "Updated memory at [path] (N entries added, M entries superseded)."

**Part C — Write AGENTS.md updates**

Skip Part C entirely if the AGENTS.md updates input above is "None" or all files within it are marked "None".

For each file listed in the updates:

1. Use the Read tool to attempt to read the current file content.

2. **If the file does not exist** (Read returns a file-not-found error): create a minimal stub appropriate for the file type, then continue to steps 3-6 to apply the proposed updates into it.
   - **Subdirectory AGENTS.md** (any path that is not the project root's AGENTS.md - i.e. the file is not at `[cwd]/AGENTS.md`): create a stub with `# [directory name]` as the H1 (derive from the parent directory of the file path), a `## Stack` section header, and a `## Key Conventions` section header.
   - **Root AGENTS.md** (the file is at `[cwd]/AGENTS.md`): create a stub with `# [project name]` as the H1 (derive from the cwd directory name), a `## Decisions` section header, and a `## Conventions` section header.
   If the draft Worker proposed a complete `New file: true` block with content, use that content as the starting file instead of the minimal stub.
   After creating the stub or new file, proceed with steps 3-6 to apply the proposed updates into it. Return: "Created and updated AGENTS.md at [path] (N additions)."

3. For each `Add:` update: locate the target section. Append the new bullet(s) at the end of that section, before the next `##` heading (or at end of file if it's the last section). Do not duplicate any bullet already present (check semantically, not just string match).

4. For each `New section:` update: insert the new section after the last existing section in the file, maintaining the document's natural flow (decisions and conventions before gotchas; stack and key conventions before less-common categories). Do not blindly append without regard to the existing structure.

5. For each `Update:` update: find the existing text and replace it with the replacement text.

6. Write the updated file to disk.

Return: "Updated AGENTS.md at [path] (N additions, M updates)" for each file written, or "Skipped [path] (nothing to add)" if all proposed additions were already present.

**Part E — Compress always-loaded memory files**

Skip Part E entirely if Parts B and C both reported no changes (no new memory entries, no AGENTS.md updates). Nothing changed this session - no need to recompress. Part A always writes context.md and is not a signal of session-meaningful change.

**Targets:**
- The `memory.md` file written by Part B (same absolute path computed in Step 4).
- `[cwd]/CLAUDE.md` if it exists at the project root.

Skip any target that does not exist.

**State file:** `[cwd]/.agentic/compression-state.json`. Schema:

    {
      "targets": {
        "<absolute path>": {
          "last_compressed_size_bytes": <int>,
          "last_compressed_at": "<YYYY-MM-DD>",
          "original_backup_path": "<absolute path to FILE.original.md>",
          "rolling_snapshots": ["<absolute path to FILE.pre-YYYY-MM-DD-HHMMSS.md>", ...]
        }
      }
    }

If the file does not exist, treat all targets as never-compressed.

**Gate:** For each target, compute current file size in bytes. Compress only if:
- (a) No prior entry exists for this target AND current size > 2000 bytes, or
- (b) A prior entry exists AND current size >= 1.5 * `last_compressed_size_bytes`.

Otherwise skip that target silently.

**For each target that passes the gate:**

1. Spawn a dedicated background Worker (general-purpose) with this brief verbatim:

   > You are a compression Worker. Rewrite the file content below into a token-dense form suitable for an LLM to read on every session start. Hard constraints, no exceptions:
   > - Preserve every technical fact, decision, gotcha, and rationale. If you are not certain a phrase is filler, keep it.
   > - Never alter: file paths, absolute or relative; shell commands; environment variable names; version numbers; dates; URLs; project names; person names; flag names; function/identifier names; quoted strings; code blocks; markdown links.
   > - Never merge or collapse two bullet entries that have distinct dates, distinct timestamps, or distinct dated headings - even if their text appears similar. Each dated entry is a separate fact and must remain its own bullet.
   > - You may: drop articles (a/an/the), drop hedging (just/really/basically), collapse multi-sentence prose into fragments, replace verbose connectors with punctuation, merge bullet sub-points when the meaning is identical AND neither bullet carries a date or timestamp.
   > - You must: keep the markdown structure intact (headings, list nesting, code fences). Keep section headings byte-identical so future readers can locate facts.
   > - Output the rewritten file content only. No commentary.
   >
   > File content:
   > [paste full file content]

2. When the compression Worker returns, spawn a fresh Skeptic (background, general-purpose, never resumed) with the original file content, the compressed draft, and this adversarial brief verbatim:

   > You are reviewing a memory-file compression for fact loss. The original file is the source of truth. The compressed file must preserve every technical fact, decision, path, command, date, version, URL, and rationale from the original. Stylistic compression of prose is allowed; semantic loss is not.
   >
   > Walk the original file section by section. For each fact, locate it in the compressed file. Classify any discrepancy:
   > - Critical: a path/command/date/version/URL/identifier was altered, dropped, or invented.
   > - Critical: a decision, gotcha, or rationale was dropped or its meaning changed.
   > - Major: structural - a heading was renamed or a section was merged in a way that obscures lookup.
   > - Minor: stylistic regressions only.
   >
   > Require this statement before sign-off: "Active search: I walked the original section by section and verified every fact appears in the compressed output."
   >
   > Sign-off format: "Reviewed: ... Findings: ... Active search: ... No unresolved Critical or Major findings. Sign-off granted."

3. Validate sign-off format the same way Step 3 does (all four elements: "Reviewed:", "Findings:", "Active search:", "No unresolved Critical or Major findings. Sign-off granted."). If any element is missing, spawn a new Skeptic with format instructions (not a re-route round). Limit: 3 format re-invocations, then escalate to the user.

   If Critical or Major findings remain: spawn a new compression Worker with the original file content, the prior draft, and the findings; get a revised draft; spawn a fresh Skeptic. Repeat until sign-off. Limit: 3 re-routes, then skip compression for that target this session and log the failure in Step 6.

4. On sign-off, the main agent (not a subagent - same rationale as the rest of Step 4) writes in this order:
   - (a) If `FILE.original.md` does not already exist, create it from the current (pre-compression) file content. Never overwrite an existing `.original.md` - it is the canonical first-ever backup.
   - (b) Write a rolling snapshot `FILE.pre-YYYY-MM-DD-HHMMSS.md` (using the current UTC timestamp at write time) from the current (pre-compression) file content. Always write; never skip.
   - (c) Prune rolling snapshots: keep only the 3 most recent `FILE.pre-*.md` snapshots for this target (by timestamp in filename). Delete older ones.
   - (d) Overwrite `FILE.md` with the compressed content.
   - (e) Update `[cwd]/.agentic/compression-state.json` with `last_compressed_size_bytes` set to the byte count of the compressed output, `last_compressed_at` set to today's date, `original_backup_path` set to the absolute path of the `.original.md` file, and `rolling_snapshots` set to the sorted list of absolute paths of the retained rolling snapshots for this target. Create the file if it does not exist (the `.agentic/` directory is already created by the lock acquisition step).

**Step 5 — Worktree cleanup.**

If the project is a git repository with a `/cleanup-worktrees` skill available, run it now. This removes stale isolation worktrees and merged feature branches so the repo is clean for the next session. If the skill is not available, skip this step silently.

**Step 6 — Confirm completion.**

Release the pre-flight lock: `rm -rf <cwd>/.agentic/wrap.lock`. This must run before returning to the user, regardless of whether any prior step reported "skipped" or "nothing to do".

Relay confirmation to the user. Include all paths written (context.md, memory.md, any AGENTS.md files updated or skipped). Also include the cleanup summary if Step 5 ran.

Include compression results from Part E: for each file compressed, list the file path with before and after byte counts (e.g. "memory.md compressed: 4821 -> 2103 bytes"). If Part E was skipped (no changes this session) write "No compression needed (no session changes)." If no targets crossed the gate write "No compression needed (targets below threshold)." If a target failed after 3 re-routes, write "Compression failed for [path] after 3 re-routes - skipped this session."

**Final reminder:** After `/wrap` completes, close the session cleanly so the Stop hook can finish writing `context.md`. In the terminal CLI, use `/exit` rather than ctrl+c - ctrl+c can interrupt the hook and lose session state. In the Claude desktop or web app, `/exit` is not available; just close the window or tab normally rather than force-quitting.
