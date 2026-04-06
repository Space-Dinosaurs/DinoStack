> **Prerequisite:** If the /engineering skill has not been loaded in this session, invoke it first before proceeding.

# /wrap — On-Demand Session Context Enrichment

Use when you want a richer context file than the auto-hook provides — e.g. before handing off complex in-progress work to a future session.

The Stop hook auto-writes `~/.claude/projects/[hash]/context.md` after every turn with raw session data. `/wrap` merges with or rewrites that file with a structured, human-curated version when detail matters. It is also the ongoing counterpart to `/init-project`: where `/init-project` scaffolds the CLAUDE.md hierarchy, `/wrap` populates it — filling in root and subdirectory CLAUDE.md files with decisions, conventions, stack details, and gotchas learned during sessions.

## Your job (main agent)

**Pre-flight check — no active Workers.** Before doing anything else, check whether any background Workers or subagents are currently running. If any are, stop and tell the user: "Cannot run /wrap while background tasks are active. Please wait for them to finish (or stop them) first." Do not proceed until confirmed.

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
- Check for and read: the root `CLAUDE.md` (if it exists), and any `[track]/CLAUDE.md` files in subdirectories that had files touched this session. Record their full current content — this will be passed to the Worker as a dedicated field so it can avoid duplicating what is already captured.
- Note which tracks (subdirectories) had files touched this session — these are candidates for CLAUDE.md updates.
- **Run `git status --porcelain` and `git stash list`** to capture uncommitted changes and stashes. If there are uncommitted tracked files (M, A, D - not ??), list them explicitly. This is critical for preventing work loss across sessions - if the user asked to commit and files were missed, this is the safety net.

This raw data is what the draft Worker will format. The Worker is a fresh agent with no session memory, so if you don't supply the details here, they won't appear in the output.

**Step 1 — Spawn a draft Worker** (background, general-purpose):

---
You are a Worker agent. Format the raw session data below into three outputs. Replace all placeholders with real content from the data provided. If a section genuinely has nothing to say, write the word "None" — never leave brackets or template text.

**Raw session data:**
[paste your Step 0 notes here verbatim — this covers the task, files touched, errors, next steps, tools used, and stable facts. Do NOT embed existing CLAUDE.md file contents here; those go in the dedicated field below.]

**Existing CLAUDE.md file contents:**
[For each CLAUDE.md file read in Step 0, paste its full current content here, clearly labeled with its absolute path, e.g.:

File: /Users/alice/myapp/CLAUDE.md
Content:
<full file content>

File: /Users/alice/myapp/backend/CLAUDE.md
Content:
<full file content>

If no CLAUDE.md files were found, write "None."]

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

**Output 3 — CLAUDE.md updates**

For each CLAUDE.md file whose current content was provided in the "Existing CLAUDE.md file contents" field above, produce proposed additions only - not a full rewrite. Use that existing content as your baseline: do not propose content already present there.

Format each proposed update as:

    File: [full path to CLAUDE.md]
    Section: [section name, e.g. "## Decisions", "## Conventions", "## Stack", "## Key Conventions"]
    Add:
    - [bullet point to add]
    - [another bullet if needed]

If a section doesn't exist in the target file yet but should be added, indicate:

    File: [path]
    New section: [section name]
    Content:
    [section content]

If content in an existing entry should be corrected or superseded, indicate:

    File: [path]
    Section: [section name]
    Update: [existing text] → [replacement text]

Rules:
- Only propose content that was actually established or learned in this session. Do not hallucinate or infer.
- Do not duplicate content already present in the existing CLAUDE.md (check against the "Existing CLAUDE.md file contents" field provided above).
- Do not contradict existing content without flagging it as an Update.
- For root CLAUDE.md: focus on `## Decisions` (resolved architecture decisions as brief bullets) and `## Conventions` (patterns and rules the project follows).
- For subdir CLAUDE.md: focus on `## Stack`, `## Key Conventions`, and any new relevant categories (Commands, Schema, Flows, Gotchas) that emerged this session.
- Quality directive: lean and curated. No verbose rationale paragraphs, no outdated entries, no conflicting information. Brief, actionable bullets only.
- If nothing new for a particular file, write "None" for that file.
- If no CLAUDE.md files were found in the project, write "None."

Return all three outputs clearly labeled. Do not write to disk.

---

**Step 2 — When the draft Worker returns, spawn a fresh Skeptic** (background, general-purpose, never resumed).

Scope constraint: the Skeptic reviews only the accuracy and completeness of the context file and the CLAUDE.md updates. Its findings must only trigger context file or CLAUDE.md rewrites — never code changes, bug fixes, or any development work. If the Skeptic notes that the context file describes pending work that is already complete (or vice versa), the fix is to update the wording to reflect reality accurately.

Provide the draft, the existing CLAUDE.md file contents from Step 0, and this adversarial brief:

> "Is this context file accurate and actionable? Check each section: Does Recent Focus correctly describe what was actually happening — or is it vague, generic, or wrong? Are the Next Steps specific enough to act on without reading the chat history (file paths, commands, branch names)? Are Key File Paths complete — is anything relevant omitted? Does Watch Out For capture real gotchas, or is it empty when it shouldn't be? Is any section still template text rather than real content?"
>
> "Also review the proposed CLAUDE.md updates (Output 3): Is each proposed addition actually derived from this session's work - or is it generic, hallucinated, or already present in the existing file content provided? Is any content going to the wrong file (project-wide content should go to root; track-specific content should go to the track subdir)? Are updates lean - brief bullets only, no verbose rationale? Does any proposed addition contradict or duplicate existing entries in the same file?"

Require this statement before sign-off: "Active search: I have applied the adversarial brief and actively searched for Critical and Major findings."

**Step 3 — Validate sign-off format.**

A valid sign-off requires all four elements: (a) "Reviewed:", (b) "Findings:", (c) "Active search:", (d) "No unresolved Critical or Major findings. Sign-off granted." If any element is missing, spawn a new Skeptic with format instructions (not a new re-route round). Limit: 3 format re-invocations, then escalate to the user.

If Critical or Major findings remain: spawn a new draft Worker with the original draft and findings, get a revised draft, then spawn a fresh Skeptic (Step 2). Repeat until sign-off. If the same finding is contested across 2+ re-routes without resolution, escalate to the user.

**Step 4 — Write to disk** (background Worker, `run_in_background: true`):

---
You are a Worker agent. Write the approved context file, any memory entries, and any CLAUDE.md updates to disk. Do not spawn subagents.

**Project directory:** [absolute cwd]

**Output path (context.md):** Do not attempt to compute the hash manually - Claude Code generates project directory hashes internally and the path cannot be derived from the project path alone. Instead, discover the correct directory by running `ls ~/.claude/projects/` and identify the subdirectory that corresponds to the current project. Once identified, the context.md path is `~/.claude/projects/[matched-hash]/context.md`.

**Memory path (memory.md):** Same directory as context.md identified above, filename `memory.md`.

**Approved context.md content:** [paste the Skeptic-approved context file content here]

**Memory entries to add:** [paste the memory.md entries from the draft Worker's Output 2 here, or "None" if there were none]

**CLAUDE.md updates to apply:** [paste the approved CLAUDE.md updates from Output 3 here, or "None" if there were none]

**Part A — Write context.md**

1. Use the Read tool to attempt to read the file at the output path computed above.

2. **If the file does not exist** (Read returns a file-not-found error): write the new draft content directly to the output path. Return: "Wrote fresh context to [path] (no existing file)."

3. **If the file exists but is empty, or its second line does not begin with `*Written by /wrap`**: the existing file was written by the Stop hook or another source and cannot be meaningfully merged. Write the new draft content directly, overwriting the existing file. Return: "Wrote fresh context to [path] (replaced non-/wrap file)."

4. **If the file exists and its second line begins with `*Written by /wrap`** (i.e. it was produced by a previous `/wrap` run): proceed to the merge step below.

Note: "second line" means the literal second line of the file. A `/wrap`-produced file always starts with `# Session Context` on line 1 and `*Written by /wrap on ...` on line 2.

**Merge step:**

First, check how many session labels are already present in the existing file's Recent Focus section.

- **Three labels present (`[Session A]`, `[Session B]`, `[Session C]`)**: apply a rolling-window merge. Discard the `[Session A]` content from Recent Focus, relabel `[Session B]` as `[Session A]`, relabel `[Session C]` as `[Session B]`, and use the new draft as `[Session C]`. For all other sections (Current Task / Next Steps, Key File Paths, Watch Out For, Tools Used), treat the full existing content as the prior session and apply the standard merge rules below.

- **Two labels present (`[Session A]` and `[Session B]`)**: label the new draft entry `[Session C]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Single unlabeled Recent Focus** (standard case - first merge): label the existing entry `[Session A]` and the new draft entry `[Session B]`, each on its own paragraph.

**Merge rules (existing file = prior session(s), new draft = newest session):**

- **Header line** (`*Written by /wrap...`): replace with a new line using today's date and the note "(merged context)". Keep the `*Project:` line from the new draft.
- **Recent Focus**: apply the labeling logic above.
- **Current Task / Next Steps**: combine all items from both. Remove exact duplicate lines. Keep all non-duplicate items.
- **Key File Paths**: union both lists. Remove exact duplicate lines.
- **Watch Out For**: union both lists. Remove exact duplicate lines. If one had "None" and the other has real entries, use only the real entries.
- **Tools Used**: combine both comma-separated lists, split by comma, trim whitespace, deduplicate, re-join as a single comma-separated list.

Note: this skill does not prevent two sessions from running `/wrap` simultaneously. If that occurs, last-write-wins and one merged result will be silently overwritten.

Write the merged result to disk. Return: "Merged context written to [path] (combined sessions)."

**Part B — Write memory.md**

Skip Part B entirely if the memory entries input above is "None".

1. Use the Read tool to attempt to read the file at the memory.md path.

2. **If the file does not exist**: write all new entries directly as a markdown list. Return: "Wrote fresh memory to [path]."

3. **If the file exists**: read its content. For each new entry, check whether the same fact is already captured - not just as an exact string match, but semantically (same architectural decision, same gotcha, same command). If an existing entry covers the same fact, skip the new entry. If the new entry supersedes an existing one (same topic but updated or corrected), replace the existing entry in place with the new one. Otherwise append the new entry. Write the merged result. Return: "Updated memory at [path] (N entries added, M entries superseded)."

**Part C — Write CLAUDE.md updates**

Skip Part C entirely if the CLAUDE.md updates input above is "None" or all files within it are marked "None".

For each file listed in the updates:

1. Use the Read tool to attempt to read the current file content.

2. **If the file does not exist** (Read returns a file-not-found error): create a minimal stub appropriate for the file type, then continue to steps 3-6 to apply the proposed updates into it.
   - **Subdirectory CLAUDE.md** (any path that is not the project root's CLAUDE.md - i.e. the file is not at `[cwd]/CLAUDE.md`): create a stub with `# [directory name]` as the H1 (derive from the parent directory of the file path), a `## Stack` section header, and a `## Key Conventions` section header.
   - **Root CLAUDE.md** (the file is at `[cwd]/CLAUDE.md`): create a stub with `# [project name]` as the H1 (derive from the cwd directory name), a `## Decisions` section header, and a `## Conventions` section header.
   After creating the stub, proceed with steps 3-6 to apply the proposed updates into the new file. Return: "Created and updated CLAUDE.md at [path] (N additions)."

3. For each `Add:` update: locate the target section. Append the new bullet(s) at the end of that section, before the next `##` heading (or at end of file if it's the last section). Do not duplicate any bullet already present (check semantically, not just string match).

4. For each `New section:` update: insert the new section after the last existing section in the file, maintaining the document's natural flow (decisions and conventions before gotchas; stack and key conventions before less-common categories). Do not blindly append without regard to the existing structure.

5. For each `Update:` update: find the existing text and replace it with the replacement text.

6. Write the updated file to disk.

Return: "Updated CLAUDE.md at [path] (N additions, M updates)" for each file written, or "Skipped [path] (nothing to add)" if all proposed additions were already present.

---

**Step 5 — Worktree cleanup.**

If the project is a git repository with a `/cleanup-worktrees` skill available, run it now. This removes stale isolation worktrees and merged feature branches so the repo is clean for the next session. If the skill is not available, skip this step silently.

**Step 6 — Confirm completion.**

When the write Worker returns, relay its confirmation to the user. Include all paths it reports (context.md, memory.md where written, and any CLAUDE.md files updated or skipped). Also include the cleanup summary if Step 5 ran.
