> **Prerequisite:** If the /engineering skill has not been loaded in this session, invoke it first before proceeding.

# /memory-update — Memory Protocol: Capture a Decision

When a project-affecting decision has been confirmed in conversation, the main agent invokes this skill with the decision context passed as `$ARGUMENTS`.

## Your job (main agent)

**Immediately** spawn a background `general-purpose` Worker (`run_in_background: true`). Return to the conversation instantly. Do not report completion to the user unless there is an escalation.

**Before spawning:** Locate the MEMORY.md path from your auto-injected context. Claude Code injects a block at startup that says: "You have a persistent auto memory directory at `~/.claude/projects/[hash]/memory/`." Use that path to construct the full MEMORY.md path: `[memory_dir]/MEMORY.md`. Pass this path to the Worker as `$MEMORY_PATH`.

**What to pass as context:** A concise summary of the decision — 1-3 sentences covering what was decided, why, and any key tradeoffs.

When spawning the Worker, substitute `$ARGUMENTS` with the actual decision context and `$MEMORY_PATH` with the resolved path before passing the prompt. Do not pass literal placeholder text.

---

## Step 1 — Spawn a single Worker that verifies and writes

Spawn a **background general-purpose Task** with this prompt (substitute `$ARGUMENTS` and `$MEMORY_PATH` with actual values):

---
You are a Memory Worker. Your job is to write an accurate, verified entry to MEMORY.md. You will draft, verify, and write in one pass. Do not return a draft for review — write directly to disk.

**The decision context:** $ARGUMENTS

**MEMORY.md path:** $MEMORY_PATH

### Part 1 — Relevance filter

Only proceed if the decision would matter to a new engineer joining the project tomorrow — architectural choices, technology decisions, scope resolutions, deliberate tradeoffs, deferred decisions. Do NOT update MEMORY.md for conversational agreements, personal preferences, or anything that doesn't affect how the project is built or understood. If the decision does not pass this filter, return: "No-op: decision does not qualify for MEMORY.md."

### Part 2 — Verify your claims

Before drafting, verify any factual claims the entry will make:
- If the entry names specific files, read them to confirm they exist and behave as described.
- If the entry describes a code pattern, read the relevant code to confirm it is accurate.
- If the entry refers to configuration values, check the actual config files.
- Do not assert something as fact without verifying it. If you cannot verify a claim, omit it or soften it to "intended to" / "expected to".

### Part 3 — Draft the entry

1. Read the current MEMORY.md (create it with just `# Memory\n\n` if it does not exist).
2. Assess against what is already there:
   - **Update existing**: decision clarifies or supersedes a prior entry → update that entry in place, adjusting the date
   - **New entry**: decision is not yet captured → draft a new date-stamped bullet
   - **No-op**: decision is already accurately captured → return: "No-op: decision already captured."
3. Entry format — one date-stamped bullet per decision:
   ```
   - **YYYY-MM-DD:** [what was decided and why, in one sentence with rationale]
   ```
4. Do not add section headers beyond the `# Memory` file header.

### Part 4 — Write to disk

Apply the change directly to the file at $MEMORY_PATH:
- New entry: append the bullet
- Update existing: replace the prior bullet in place
- If MEMORY.md does not exist: create it with the header `# Memory\n\n` then write the bullet

Do not commit — committing is the user's responsibility. Return confirmation when done.
---

## Step 2 — When the Worker returns

If the Worker returned "No-op" or "Abort": complete silently. No further action.

Otherwise: complete silently — do NOT report back to the user.
