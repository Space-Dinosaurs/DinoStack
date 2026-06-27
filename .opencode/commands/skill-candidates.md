---
description: /skill-candidates
agent: build
---
# /skill-candidates

Read-only view of the skill-candidate backlog. Displays open and dismissed
candidates detected from recurring workflow friction - each with its domain,
count, suggested artifact type, and example note. Points at the `skill-creator`
skill for open items.

No writes, no agent spawns, no network calls. Always exits 0.

## Usage

```
/skill-candidates
```

No subcommands, no flags. Reads `.agentic/skill-candidates.md` from the
current working directory. If the file is absent: "No skill candidates
detected yet."

## Entry format (canonical)

Each entry in `.agentic/skill-candidates.md` has the following structure.
The `## <domain>` heading is the unique key. `Status` is `open` (written by
the detector on first promotion) or `dismissed` (set by a human to suppress).

```markdown
## <domain>
**Count:** <lifetime occurrence count>
**Suggested artifact:** command | named-agent | preset | lint-rule
**First seen:** YYYY-MM-DD
**Last seen:** YYYY-MM-DD
**Status:** open
**Example:** "<data.note from the triggering event>"
```

## What this shows

The backlog is written by the Stop hook's `runSkillCandidateScan` whenever a
domain tag accumulates >= 3 occurrences across sessions (from
`tool_failure_workaround` events and `.agentic/learnings.md` entries). Each
entry carries:

- **Domain** - the `## <domain>` heading (unique key)
- **Count** - lifetime occurrence count across sessions
- **Suggested artifact** - `command`, `named-agent`, `preset`, or `lint-rule`
  (routing taxonomy from the detection signal)
- **Status** - `open` (not yet dismissed) or `dismissed` (operator suppressed)
- **First seen / Last seen** - ISO date range of the friction signal
- **Example** - the `data.note` from the triggering event (illustrative only)

## Grouping by status

The command groups entries by `**Status:**` value:

- **OPEN** - entries with `**Status:** open` whose domain is NOT present in
  `.agentic/.skill-candidates-surfaced`. These are the primary action items.
- **OPEN (already surfaced)** - entries with `**Status:** open` whose domain IS
  in `.agentic/.skill-candidates-surfaced`. Conductor has already nudged once.
- **DISMISSED** - entries with `**Status:** dismissed`.

The command reads `.agentic/.skill-candidates-surfaced` (one domain per line)
to determine which open entries have already been surfaced at session start.
It never writes to this file.

## Output example

```
Skill candidates  (.agentic/skill-candidates.md)

OPEN
  adapter-interface   count: 5   suggested: command
    first seen: 2026-05-01   last seen: 2026-05-12
    example: "adapter build.sh signatures diverged; had to reconcile manually"

  deploy-verification  count: 3   suggested: named-agent
    first seen: 2026-05-10   last seen: 2026-05-12
    example: "ran manual Vercel rollout check; no automated verify step"

OPEN (already surfaced)
  worktree-cleanup    count: 4   suggested: command
    first seen: 2026-05-05   last seen: 2026-05-11
    example: "forgot to remove worktree after merge"

DISMISSED
  (none)

To create a skill for an open item: run /skill-creator <domain>
To dismiss a candidate: edit .agentic/skill-candidates.md and change
  **Status:** open  to  **Status:** dismissed
```

When `.agentic/skill-candidates.md` is absent:

```
No skill candidates detected yet.

The detector runs at session end (Stop hook) and writes candidates here
when a domain tag accumulates >= 3 occurrences. Check back after a few
more sessions, or verify that skill_candidate_detection is true in
.agentic/config.json.
```

## Gating

This command is a no-op (displays the absent-file message) when
`skill_candidate_detection: false` in `.agentic/config.json`. The file is
the single source of truth; the command never calls the detector itself.

## Intent layer note

`.agentic/skill-candidates.md` is **committed** in consumer projects (via a
`!.agentic/skill-candidates.md` carve-out in `project-scaffolding.yml`) so
the backlog travels with the repo and is visible to all team members. It is
NOT committed in the DinoStack methodology source repo itself (the blanket
`.agentic/*` ignore governs there - intended; DinoStack is the source, not
a consumer).
