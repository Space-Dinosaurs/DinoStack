# /update-protocol

Governs all edits to methodology documents and protocol files within the `~/agentic-engineering/` repository. Use this command whenever a rule, convention, agent definition, or command file under `~/agentic-engineering/` needs to change.

Scope: all files physically located under `~/agentic-engineering/`. This includes `content/rules/`, `content/commands/`, `content/references/`, `content/agents/`, and `.claude/commands/` within the repo. Files that live outside the repo (e.g., agent definitions in `~/.claude/agents/` that are not symlinks into this repo) are out of scope.

## Step 1 — Spawn a Worker

Spawn a Worker subagent with instructions:
1. Read the current file(s) to be changed.
2. Apply the edit using the Edit tool.
3. If editing `content/rules/`, `content/references/`, or `content/agents/`: edit only the `content/` path. The corresponding `.claude/skills/agentic-engineering/` and `.claude/agents/` paths are symlinks pointing into `content/`, so the edit is immediately live. No build step is required.
4. If editing `content/commands/`: edit only the `content/commands/` path. The `.claude/commands/*.md` copies are build artifacts - `build.sh` prepends the `/agentic-engineering` prerequisite blockquote and writes the result to `.claude/commands/`. The build must be run after approval for the change to take effect.
5. Return the full diff.
6. If the Edit cannot be applied for any reason other than a Claude Code permission denial (file not found, ambiguous anchor, etc.), return a clear error description instead of a diff - do not attempt workarounds.

## Permission-blocked path

If the Worker in Step 1 returns a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED — Edit permission was denied by the permission system"), the main session may apply the edit directly, then present the diff to the user in Step 2 as normal. The user approval gate in Step 2 is preserved without exception — the main session never applies an edit and proceeds without human review. Step 3 proceeds only after approval.

## Step 2 — Present to the user

Show the diff, state what the change does. If the diff includes `content/commands/` changes, remind the user that `.claude/commands/` is a build artifact and `build.sh` must be run after approval. For rules, references, and agent edits, note that those changes are already live via symlinks - no build step is needed. Wait for explicit approval.

## Step 3 — Run the build

After approval: if the diff includes any `content/commands/` changes, run `bash ~/agentic-engineering/.claude/build.sh` and confirm success. If the diff only touches `content/rules/`, `content/references/`, or `content/agents/`, skip the build - those changes are already live.

Note: This command governs edits to its own source file — the recursion is intentional.
